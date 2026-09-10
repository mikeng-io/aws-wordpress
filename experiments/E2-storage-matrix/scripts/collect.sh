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

# stderr, not stdout: run_task returns its task id on stdout, and a progress line
# landing there gets captured into the caller's variable instead of being read.
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }

destroy() {
    log "destroying $STACK"
    (cd "$REPO/infra" && ./node_modules/.bin/cdk destroy "$STACK" --force) || {
        echo "TEARDOWN FAILED - check the console, this is billing now" >&2
        exit 2
    }
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
        else
            # No header row - bench writes bare "op,ns" lines, so every line is an op.
            log "  $arm/$tier: $(wc -l < "$dest/$tier.csv" | tr -d ' ') ops"
        fi
    done < "$dest/manifest.txt"
    [ "$missing" -eq 0 ] || exit 1
}

for rep in $(seq 1 "$REPS"); do
    log "=== replication $rep/$REPS ==="
    REP_DIR="$OUT_ROOT/rep-$rep"
    mkdir -p "$REP_DIR"

    log "deploying $STACK"
    (cd "$REPO/infra" && ./node_modules/.bin/cdk deploy "$STACK" --require-approval never)

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

    trap destroy EXIT

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
    collect_arm ec2 "$REP_DIR/ec2"

    # --- Fargate arm ---------------------------------------------------------
    log "running Fargate arm (task ephemeral / EFS)"
    FARGATE_TASK=$(run_task fargate "$FARGATE_TD" "--launch-type FARGATE" "e2-fargate")
    require_task_id "$FARGATE_TASK" fargate
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
  "pricing_snapshot": "$(basename "$(ls -d "$REPO"/results/pricing/*/ | tail -1)")"
}
META

    trap - EXIT
    destroy
    log "replication $rep complete -> results/E2/$RUN_ID/rep-$rep"
done

log "all $REPS replications complete: results/E2/$RUN_ID"
