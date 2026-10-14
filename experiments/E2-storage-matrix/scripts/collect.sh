#!/usr/bin/env bash
# E2 collection: deploy, run both arms, extract results, tear down. Once per
# replication, and each replication is an INDEPENDENT deployment - per the
# benchmark protocol, re-running a task inside one deployment is repetition, not
# replication, and only replication crosses the placement/hardware boundary that
# actually varies between runs.
#
# The stack is destroyed at the end of every replication, including on failure,
# because the standing cost is an instance plus ten interface endpoints and the
# trap CLAUDE.md names is forgetting, not spending.
#
# Usage:  ./collect.sh [replications]     (default 3, per the protocol)
set -euo pipefail

REPS="${1:-3}"
STACK="E2-StorageMatrix-dev"
REGION="${AWS_DEFAULT_REGION:-ap-southeast-1}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$REPO" rev-parse --short HEAD)"
OUT_ROOT="$REPO/results/E2/$RUN_ID"

if [ -e "$OUT_ROOT" ]; then
    echo "run $RUN_ID already exists - results are immutable, refusing" >&2
    exit 1
fi

# The first `aws` on PATH is not necessarily a working v2. On the study's own
# machine it was an x86 CLI v1 script that died with "Bad CPU type", so every call
# below - including the teardown check - would have failed. Pick the first v2 on
# PATH, explicitly, or refuse to start: a teardown that cannot run is the one
# failure this script cannot be allowed to discover halfway through.
AWS_BIN=""
for candidate in $(type -ap aws); do
    if "$candidate" --version 2>&1 | grep -q '^aws-cli/2'; then AWS_BIN="$candidate"; break; fi
done
if [ -z "$AWS_BIN" ]; then
    echo "FATAL: no working AWS CLI v2 on PATH (found: $(type -ap aws | tr '\n' ' '))" >&2
    exit 1
fi
aws() { "$AWS_BIN" "$@"; }

# A dirty tree means meta.json's git_sha does not describe what ran. The protocol
# requires the run be reconstructible from a commit, so this refuses rather than
# recording git_dirty:true and hoping someone reads it.
if [ -z "${ALLOW_DIRTY:-}" ] && ! git -C "$REPO" diff --quiet HEAD --; then
    echo "FATAL: working tree is dirty - commit first (ALLOW_DIRTY=1 to override for a non-result run)" >&2
    exit 1
fi

# A stack that already exists was left by something this run does not know about.
# Deploying over it would measure an unknown state and destroy someone's evidence.
if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
    echo "FATAL: $STACK already exists - inspect and destroy it by hand before a run" >&2
    exit 1
fi

# stderr, not stdout: run_task returns its task id on stdout, and a progress line
# landing there gets captured into the caller's variable instead of being read.
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }

# FSx takes a FINAL BACKUP when a file system or volume is deleted, and that backup
# is NOT a CloudFormation resource: `cdk destroy` reports success and leaves it
# billing indefinitely. Seven of them accumulated across four failed deploy cycles
# before anyone looked, and every teardown check up to that point had reported the
# account clean because none of them queried describe-backups.
#
# Both OpenZFS file systems and ONTAP volumes do this. There is no SkipFinalBackup
# equivalent exposed through CloudFormation for AWS::FSx::Volume, so it cannot be
# turned off in the stack - it has to be swept afterwards.
#
# The sweep is SCOPED. This account is shared with unrelated projects, and the first
# version of this function deleted every FSx backup in the region. A backup is ours
# only if its source file system or volume came from this stack (IDs captured
# before destroy, from both the resource list and the event history, so a stack that
# rolled back still yields them), or if it carries this study's tags (the stack sets
# CopyTagsToBackups).
FSX_SOURCE_IDS=""

capture_fsx_ids() {
    local ids
    ids=$( {
        aws cloudformation list-stack-resources --region "$REGION" --stack-name "$STACK" \
            --query "StackResourceSummaries[?ResourceType=='AWS::FSx::FileSystem' || ResourceType=='AWS::FSx::Volume'].PhysicalResourceId" \
            --output text 2>/dev/null || true
        aws cloudformation describe-stack-events --region "$REGION" --stack-name "$STACK" \
            --query "StackEvents[?ResourceType=='AWS::FSx::FileSystem' || ResourceType=='AWS::FSx::Volume'].PhysicalResourceId" \
            --output text 2>/dev/null || true
    } | tr '\t' '\n' | grep -E '^(fs|fsvol)-[0-9a-f]+$' || true)
    FSX_SOURCE_IDS=$(printf '%s\n' $FSX_SOURCE_IDS $ids | sort -u | tr '\n' ' ')
}

# Backups that are ours, by source ID or by tag, in any lifecycle except DELETED.
# Prints "id lifecycle" per line.
our_backups() {
    aws fsx describe-backups --region "$REGION" --output json \
      | python3 -c '
import json, sys
ids = set(sys.argv[1].split())
for b in json.load(sys.stdin)["Backups"]:
    if b["Lifecycle"] == "DELETED":
        continue
    src = {b.get("FileSystem", {}).get("FileSystemId"), b.get("Volume", {}).get("VolumeId")}
    tags = {t["Key"]: t["Value"] for t in b.get("Tags", [])}
    tagged = tags.get("Study") == "aws-wordpress" and tags.get("Experiment") == "E2"
    if (src & ids) or tagged:
        print(b["BackupId"], b["Lifecycle"])
' "$FSX_SOURCE_IDS"
}

# Delete our backups and keep looking until none remain. "None remain" must be seen
# twice, a minute apart, because a final backup is created during deletion and an
# empty answer taken too early is the false "clean" this function exists to prevent.
# Exits 3, naming every backup left, if it cannot get there - never returns quietly.
sweep_fsx_backups() {
    local deadline=$(( $(date +%s) + 2400 )) empty_seen=0 listing
    log "  sweeping FSx backups from: ${FSX_SOURCE_IDS:-<no source ids>} (and tag Experiment=E2)"
    while :; do
        listing=$(our_backups) || { echo "SWEEP ERROR: describe-backups failed" >&2; exit 3; }
        if [ -z "$listing" ]; then
            empty_seen=$((empty_seen + 1))
            [ "$empty_seen" -ge 2 ] && { log "  no FSx backups from this stack remain"; return 0; }
        else
            empty_seen=0
            while read -r id lifecycle; do
                if [ "$lifecycle" = "AVAILABLE" ] || [ "$lifecycle" = "FAILED" ]; then
                    log "  deleting FSx backup $id ($lifecycle)"
                    aws fsx delete-backup --region "$REGION" --backup-id "$id" >/dev/null \
                        || log "  delete of $id refused, will retry"
                else
                    log "  FSx backup $id is $lifecycle, waiting"
                fi
            done <<< "$listing"
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo "SWEEP FAILED - these FSx backups are still billing:" >&2
            echo "$listing" >&2
            exit 3
        fi
        sleep 60
    done
}

destroy() {
    # Installed as the EXIT trap BEFORE deploy, so a failed or rolled-back deploy is
    # torn down and swept too. That was the path the seven leaked backups took: the
    # deploy failed, the trap had not been set yet, and nothing swept.
    trap - EXIT
    log "destroying $STACK"
    capture_fsx_ids
    # cdk's exit code is logged, not trusted: the verdict is whether the stack still
    # exists afterwards. A deploy that died before the stack was created leaves
    # nothing to destroy, and that is a clean teardown, not a failed one.
    (cd "$REPO/infra" && ./node_modules/.bin/cdk destroy "$STACK" --force) \
        || log "  cdk destroy exited non-zero; checking what is actually left"
    log "sweeping FSx final backups (not CloudFormation resources)"
    sweep_fsx_backups
    if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
        echo "TEARDOWN FAILED - $STACK still exists, check the console, this is billing now" >&2
        exit 2
    fi
    log "teardown verified: stack gone, no FSx backups from it remain"
}

# An ECS task id is 32 hex characters. Anything else means the capture picked up
# something that was not the id, and the resulting log-stream lookup would fail with
# a regex complaint that says nothing about the real cause.
require_task_id() {
    if ! [[ "$1" =~ ^[0-9a-f]{32}$ ]]; then
        echo "FATAL: $2 task id is malformed: ${1@Q}" >&2
        echo "       Expected 32 hex chars. Something wrote to run_task's stdout." >&2
        exit 1
    fi
}

stack_output() {
    aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

# Run one task to completion and print its log stream name.
run_task() {
    local arm="$1" task_def="$2" launch_spec="$3" prefix="$4"
    local task_arn
    # shellcheck disable=SC2086
    task_arn=$(aws ecs run-task --region "$REGION" \
        --cluster "$CLUSTER" --task-definition "$task_def" $launch_spec \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=DISABLED}" \
        --query 'tasks[0].taskArn' --output text)
    if [ -z "$task_arn" ] || [ "$task_arn" = "None" ]; then
        echo "failed to start $arm task" >&2; return 1
    fi
    log "  $arm task started, waiting"
    aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn"

    local exit_code reason
    exit_code=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
        --query 'tasks[0].containers[0].exitCode' --output text)
    reason=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
        --query 'tasks[0].stoppedReason' --output text)
    log "  $arm exit=$exit_code ($reason)"
    if [ "$exit_code" != "0" ]; then
        # The entrypoint fails closed when a mount did not take. That is a real
        # result about the apparatus, not a flake to retry around.
        aws logs tail "$LOG_GROUP" --region "$REGION" --log-stream-name-prefix "$prefix" --since 10m || true
        echo "$arm task failed - not collecting a result from a failed mount check" >&2
        return 1
    fi
    echo "${task_arn##*/}"
}

# Pull one arm's results out of the bucket and verify every tier the task said it
# would upload actually arrived. A missing tier must fail here, loudly, rather than
# be discovered as a gap during analysis weeks later.
collect_arm() {
    local arm="$1" dest="$2"
    mkdir -p "$dest"
    aws s3 sync "s3://$BUCKET/$arm/" "$dest/" --only-show-errors
    if [ ! -f "$dest/manifest.txt" ]; then
        echo "FATAL: no manifest for arm $arm - the task did not finish uploading" >&2
        exit 1
    fi
    local missing=0
    while read -r tier; do
        [ -z "$tier" ] && continue
        if [ ! -s "$dest/$tier.csv" ]; then
            echo "FATAL: arm $arm declared tier '$tier' but its CSV is missing or empty" >&2
            missing=1
        elif [ ! -s "$dest/$tier.conformance.csv" ]; then
            # H6 makes the conformance gate a precondition for a tier's latency number
            # meaning anything. A missing gate result must fail here for the same
            # reason a missing CSV does, rather than surface during analysis.
            echo "FATAL: arm $arm tier '$tier' has no conformance result" >&2
            missing=1
        else
            # No header row - bench writes bare "op,ns" lines, so every line is an op.
            conf=$(grep -c ',FAIL' "$dest/$tier.conformance.csv" || true)
            log "  $arm/$tier: $(wc -l < "$dest/$tier.csv" | tr -d ' ') ops, conformance failures: $conf"
        fi
    done < "$dest/manifest.txt"
    # Throughput is graded for prediction 1, so a tier listed for it and missing its
    # result fails here too. An "error" row is a recorded probe failure, which the
    # grader reports as ERROR - it is kept, and logged, but it is not a gap.
    if [ ! -f "$dest/throughput-manifest.txt" ]; then
        echo "FATAL: arm $arm has no throughput-manifest.txt" >&2
        missing=1
    else
        while read -r tier; do
            [ -z "$tier" ] && continue
            if [ ! -s "$dest/$tier.tput.csv" ]; then
                echo "FATAL: arm $arm tier '$tier' has no throughput result" >&2
                missing=1
            elif grep -q '^error,' "$dest/$tier.tput.csv"; then
                log "  $arm/$tier: throughput probe ERROR (recorded, will grade as ERROR)"
            else
                log "  $arm/$tier: throughput $(grep -c '^read,' "$dest/$tier.tput.csv") read phases"
            fi
        done < "$dest/throughput-manifest.txt"
    fi
    if [ ! -s "$dest/mount-facts.csv" ]; then
        echo "FATAL: arm $arm has no mount-facts.csv - the negotiated mount options," >&2
        echo "       run order, MTU and kernel are the evidence that the tiers are" >&2
        echo "       comparable. Without it the comparison is asserted, not measured." >&2
        missing=1
    fi
    [ "$missing" -eq 0 ] || exit 1
}

for rep in $(seq 1 "$REPS"); do
    log "=== replication $rep/$REPS ==="
    REP_DIR="$OUT_ROOT/rep-$rep"
    mkdir -p "$REP_DIR"

    trap destroy EXIT
    log "deploying $STACK"
    (cd "$REPO/infra" && ./node_modules/.bin/cdk deploy "$STACK" --require-approval never)
    capture_fsx_ids

    CLUSTER=$(stack_output ClusterName)
    SUBNET=$(stack_output SubnetId)
    SG=$(stack_output SecurityGroupId)
    LOG_GROUP=$(stack_output LogGroupName)
    EC2_TD=$(stack_output Ec2TaskDefinitionArn)
    FARGATE_TD=$(stack_output FargateTaskDefinitionArn)
    CAPACITY_PROVIDER=$(stack_output CapacityProviderName)
    ASG=$(stack_output AsgName)
    INSTANCE_TYPE=$(stack_output InstanceType)
    BUCKET=$(stack_output ResultsBucketName)

    # What FSx actually built, from the API at run time rather than the CDK source:
    # type version, throughput, capacity, deployment type. The source says what was
    # asked for; this says what was delivered, which is what the numbers belong to.
    fs_ids=$(printf '%s\n' $FSX_SOURCE_IDS | grep '^fs-' | tr '\n' ' ' || true)
    if [ -n "$fs_ids" ]; then
        # shellcheck disable=SC2086
        aws fsx describe-file-systems --region "$REGION" --file-system-ids $fs_ids \
            --output json > "$REP_DIR/fsx-provenance.json"
        log "  FSx provenance captured for: $fs_ids"
    fi

    # --- provenance, read from the running instance, not assumed --------------
    INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups --region "$REGION" \
        --auto-scaling-group-names "$ASG" \
        --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)
    AZ=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)
    AMI=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].ImageId' --output text)

    log "  instance $INSTANCE_ID ($INSTANCE_TYPE) in $AZ"
    CMD_ID=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE_ID" \
        --document-name AWS-RunShellScript \
        --parameters 'commands=["uname -r","curl -s localhost:51678/v1/metadata || true","lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT","findmnt -o TARGET,SOURCE,FSTYPE /mnt/instance-store"]' \
        --query 'Command.CommandId' --output text 2>/dev/null) || CMD_ID=""
    if [ -n "$CMD_ID" ]; then
        sleep 8
        aws ssm get-command-invocation --region "$REGION" --command-id "$CMD_ID" \
            --instance-id "$INSTANCE_ID" --query 'StandardOutputContent' --output text \
            > "$REP_DIR/host-provenance.txt" 2>/dev/null || true
        log "  host provenance captured"
    fi

    # --- EC2 arm -------------------------------------------------------------
    log "running EC2 arm (instance store / EBS / EFS)"
    EC2_TASK=$(run_task ec2 "$EC2_TD" \
        "--capacity-provider-strategy capacityProvider=$CAPACITY_PROVIDER,weight=1" "e2-ec2")
    require_task_id "$EC2_TASK" ec2
    EC2_DIGEST=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$EC2_TASK" \
        --query 'tasks[0].containers[0].imageDigest' --output text)
    collect_arm ec2 "$REP_DIR/ec2"

    # --- Fargate arm ---------------------------------------------------------
    log "running Fargate arm (task ephemeral / EFS)"
    FARGATE_TASK=$(run_task fargate "$FARGATE_TD" "--launch-type FARGATE" "e2-fargate")
    require_task_id "$FARGATE_TASK" fargate
    FARGATE_DIGEST=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$FARGATE_TASK" \
        --query 'tasks[0].containers[0].imageDigest' --output text)
    # The two arms' EFS readings stay in separate directories: same filesystem,
    # different client, and collapsing them would hide exactly that difference.
    collect_arm fargate "$REP_DIR/fargate"

    cat > "$REP_DIR/meta.json" <<META
{
  "experiment": "E2",
  "run_id": "$RUN_ID",
  "replication": $rep,
  "utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "region": "$REGION",
  "availability_zone": "$AZ",
  "instance_type": "$INSTANCE_TYPE",
  "instance_id": "$INSTANCE_ID",
  "ami_id": "$AMI",
  "stack": "$STACK",
  "git_sha": "$(git -C "$REPO" rev-parse HEAD)",
  "git_dirty": $(git -C "$REPO" diff --quiet && echo false || echo true),
  "ec2_task": "$EC2_TASK",
  "fargate_task": "$FARGATE_TASK",
  "ec2_image_digest": "$EC2_DIGEST",
  "fargate_image_digest": "$FARGATE_DIGEST",
  "fsx_source_ids": "$(echo $FSX_SOURCE_IDS)",
  "cdk_cli_version": "$(cd "$REPO/infra" && ./node_modules/.bin/cdk --version 2>/dev/null | head -1)",
  "aws_cdk_lib_version": "$(node -p "require('$REPO/infra/node_modules/aws-cdk-lib/package.json').version")",
  "aws_cli_version": "$(aws --version 2>&1 | head -1)",
  "pricing_snapshot": "$(basename "$(ls -d "$REPO"/results/pricing/*/ | tail -1)")"
}
META

    destroy
    log "replication $rep complete -> results/E2/$RUN_ID/rep-$rep"
done

log "all $REPS replications complete: results/E2/$RUN_ID"
