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

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

destroy() {
    log "destroying $STACK"
    (cd "$REPO/infra" && ./node_modules/.bin/cdk destroy "$STACK" --force) || {
        echo "TEARDOWN FAILED - check the console, this is billing now" >&2
        exit 2
    }
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

# Split the task's stdout into one CSV per tier, using the entrypoint's markers.
extract() {
    local raw="$1" dest="$2"
    python3 - "$raw" "$dest" <<'PY'
import pathlib, re, sys
raw = pathlib.Path(sys.argv[1]).read_text()
dest = pathlib.Path(sys.argv[2]); dest.mkdir(parents=True, exist_ok=True)
blocks = re.findall(r"===CSV_START:(\w+)===\n(.*?)===CSV_END:\1===", raw, re.S)
if not blocks:
    print("no CSV blocks found in task output", file=sys.stderr); sys.exit(1)
for name, body in blocks:
    rows = [l for l in body.splitlines() if re.match(r"^[a-z_]+,\d+$", l.strip())]
    (dest / f"{name}.csv").write_text("op,ns\n" + "\n".join(rows) + "\n")
    print(f"  {name}: {len(rows)} ops -> {dest.name}/{name}.csv")
PY
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
    aws logs get-log-events --region "$REGION" --log-group-name "$LOG_GROUP" \
        --log-stream-name "e2-ec2/bench/$EC2_TASK" --start-from-head \
        --query 'events[].message' --output text > "$REP_DIR/ec2-raw.txt"
    extract "$REP_DIR/ec2-raw.txt" "$REP_DIR"

    # --- Fargate arm ---------------------------------------------------------
    log "running Fargate arm (task ephemeral / EFS)"
    FARGATE_TASK=$(run_task fargate "$FARGATE_TD" "--launch-type FARGATE" "e2-fargate")
    aws logs get-log-events --region "$REGION" --log-group-name "$LOG_GROUP" \
        --log-stream-name "e2-fargate/bench/$FARGATE_TASK" --start-from-head \
        --query 'events[].message' --output text > "$REP_DIR/fargate-raw.txt"
    # Fargate's EFS numbers land as efs_fargate so the two arms' EFS readings stay
    # distinguishable - they are the same filesystem but a different client.
    extract "$REP_DIR/fargate-raw.txt" "$REP_DIR/fargate"

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
