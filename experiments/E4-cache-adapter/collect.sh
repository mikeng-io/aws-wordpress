#!/usr/bin/env bash
# E4 collection: one stack, three one-shot Fargate tasks (seed, EFS, hydrated),
# then destroy. Each replication is an independent deployment, per the protocol.
#
# The EFS arm runs in a FRESH task, not after the seed task in the same container:
# otherwise the client attribute/page cache warmed by building the tree would turn
# the EFS reading into a cache-hit measurement (the exact E2/E5 confound).
set -euo pipefail

REPS="${1:-3}"
STACK="E4-CacheAdapter-dev"
REGION="${AWS_DEFAULT_REGION:-ap-southeast-1}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STOP_AFTER_REP="${STOP_AFTER_REP:-0}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$REPO" rev-parse --short HEAD)"
OUT_ROOT="$REPO/results/E4/$RUN_ID"
if [ -e "$OUT_ROOT" ]; then
    echo "run $RUN_ID already exists - results are immutable, refusing" >&2
    exit 1
fi
mkdir -p "$OUT_ROOT"

AWS_BIN=""
for candidate in $(type -ap aws); do
    if "$candidate" --version 2>&1 | grep -q '^aws-cli/2'; then AWS_BIN="$candidate"; break; fi
done
if [ -z "$AWS_BIN" ]; then
    echo "FATAL: no working AWS CLI v2 on PATH (found: $(type -ap aws | tr '\n' ' '))" >&2
    exit 1
fi
aws() { "$AWS_BIN" "$@"; }

if [ -z "${ALLOW_DIRTY:-}" ] && ! git -C "$REPO" diff --quiet HEAD -- . \
        ':!results' ':!docs' ':!experiments/E4-cache-adapter/README.md'; then
    echo "FATAL: working tree is dirty - commit first (ALLOW_DIRTY=1 to override)" >&2
    git -C "$REPO" diff --stat HEAD -- . ':!results' ':!docs' >&2
    exit 1
fi

if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
    echo "FATAL: $STACK already exists - inspect and destroy it by hand first" >&2
    exit 1
fi

log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }

stack_output() {
    aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

destroy() {
    trap - EXIT
    log "destroying $STACK"
    local bucket
    bucket=$(stack_output ResultsBucketName 2>/dev/null || true)
    if [ -n "$bucket" ] && [ "$bucket" != "None" ]; then
        aws s3 rm "s3://$bucket" --recursive --only-show-errors >/dev/null 2>&1 || true
    fi
    (cd "$REPO/infra" && ./node_modules/.bin/cdk destroy "$STACK" --force) \
        || log "cdk destroy exited non-zero; checking what is actually left"
    if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
        echo "TEARDOWN FAILED - $STACK still exists, this is billing now" >&2
        exit 2
    fi
    log "teardown verified: stack gone"
}

run_task() {
    local arm="$1" task_def="$2"
    local task_arn exit_code reason
    task_arn=$(aws ecs run-task --region "$REGION" \
        --cluster "$CLUSTER" --task-definition "$task_def" --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=DISABLED}" \
        --query 'tasks[0].taskArn' --output text)
    if [ -z "$task_arn" ] || [ "$task_arn" = "None" ]; then
        echo "failed to start $arm task" >&2
        return 1
    fi
    log "  $arm task started, waiting"
    aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn"

    exit_code=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
        --query "tasks[0].containers[?name=='$arm'] | [0].exitCode" --output text)
    # Containers are named lower-case in the task definitions: seed, efs, hydrated.
    if [ "$exit_code" = "None" ] || [ -z "$exit_code" ]; then
        exit_code=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
            --query 'tasks[0].containers[0].exitCode' --output text)
    fi
    reason=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
        --query 'tasks[0].stoppedReason' --output text)
    aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
        --output json > "$REP_DIR/$arm.task.json"
    log "  $arm exit=$exit_code ($reason)"
    aws logs tail "$LOG_GROUP" --region "$REGION" --log-stream-name-prefix "$arm" --since 2h \
        > "$REP_DIR/$arm.task.log" 2>&1 || log "  could not fetch $arm task log"
    if [ "$exit_code" != "0" ]; then
        tail -50 "$REP_DIR/$arm.task.log" >&2 || true
        echo "$arm task failed - not collecting a result" >&2
        return 1
    fi
    echo "${task_arn##*/}"
}

collect_arm() {
    local arm="$1" dest="$2"
    mkdir -p "$dest"
    aws s3 sync "s3://$BUCKET/$arm/" "$dest/" --only-show-errors
    if [ ! -f "$dest/manifest.txt" ]; then
        echo "FATAL: no manifest for arm $arm - the task did not finish uploading" >&2
        exit 1
    fi
    local tier missing=0
    while read -r tier; do
        [ -z "$tier" ] && continue
        if [ ! -s "$dest/$tier.csv" ]; then
            echo "FATAL: arm $arm declared tier '$tier' but its CSV is missing or empty" >&2
            missing=1
        elif [ ! -s "$dest/$tier.conformance.csv" ]; then
            echo "FATAL: arm $arm tier '$tier' has no conformance result" >&2
            missing=1
        else
            local conf
            conf=$(grep -c ',FAIL' "$dest/$tier.conformance.csv" || true)
            log "  $arm/$tier: $(wc -l < "$dest/$tier.csv" | tr -d ' ') ops, conformance failures: $conf"
        fi
    done < "$dest/manifest.txt"
    if [ ! -s "$dest/mount-facts.csv" ]; then
        echo "FATAL: arm $arm has no mount-facts.csv" >&2
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

    CLUSTER=$(stack_output ClusterName)
    SUBNET=$(stack_output SubnetId)
    SG=$(stack_output SecurityGroupId)
    LOG_GROUP=$(stack_output LogGroupName)
    SEED_TD=$(stack_output SeedTaskDefinitionArn)
    EFS_TD=$(stack_output EfsTaskDefinitionArn)
    HYDRATED_TD=$(stack_output HydratedTaskDefinitionArn)
    BUCKET=$(stack_output ResultsBucketName)
    FILE_SYSTEM=$(stack_output FileSystemId)

    log "running seed task (builds the EFS origin; its timing is not a result)"
    SEED_TASK=$(run_task seed "$SEED_TD")
    grep -q 'seed tar written' "$REP_DIR/seed.task.log" || {
        echo "FATAL: seed task did not report writing the tarball" >&2
        tail -40 "$REP_DIR/seed.task.log" >&2 || true
        exit 1
    }

    log "running EFS arm in a fresh task"
    EFS_TASK=$(run_task efs "$EFS_TD")
    collect_arm efs "$REP_DIR/efs"

    log "running hydrated arm in a fresh task"
    HYDRATED_TASK=$(run_task hydrated "$HYDRATED_TD")
    collect_arm hydrated "$REP_DIR/hydrated"
    [ -s "$REP_DIR/hydrated/hydration.csv" ] || {
        echo "FATAL: hydrated arm did not upload hydration.csv" >&2
        exit 1
    }

    EFS_DIGEST=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$EFS_TASK" \
        --query "tasks[0].containers[0].imageDigest" --output text)
    cat > "$REP_DIR/meta.json" <<META
{
  "experiment": "E4",
  "run_id": "$RUN_ID",
  "replication": $rep,
  "utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "region": "$REGION",
  "platform": "Fargate",
  "cpu_architecture": "ARM64",
  "cpu": "0.5 vCPU",
  "memory_mib": 1024,
  "availability_zone": "single-AZ (isolated subnet)",
  "stack": "$STACK",
  "file_system_id": "$FILE_SYSTEM",
  "efs_configuration": "elastic throughput, general purpose, encrypted, one-zone",
  "service_configuration": "one-shot Fargate tasks; no Service, ALB or NAT",
  "git_sha": "$(git -C "$REPO" rev-parse HEAD)",
  "git_dirty": $(git -C "$REPO" diff --quiet -- . ':!results' ':!docs' ':!experiments/E4-cache-adapter/README.md' && echo false || echo true),
  "seed_task": "$SEED_TASK",
  "efs_task": "$EFS_TASK",
  "hydrated_task": "$HYDRATED_TASK",
  "image_digest": "$EFS_DIGEST",
  "workload_shape": "20 dirs x 50 files, 2-50 KB, WordPress-shaped tree; read-only existing-tree benchmark",
  "measures": "per-syscall latency and hydration wall time, not end-to-end WordPress request latency",
  "reps": $REPS,
  "pricing_snapshot": "$(basename "$(ls -d "$REPO"/results/pricing/*/ | tail -1)")",
  "aws_cli_version": "$(aws --version 2>&1 | head -1)"
}
META

    destroy
    log "replication $rep complete -> results/E4/$RUN_ID/rep-$rep"

    if [ "$rep" -eq "$STOP_AFTER_REP" ] && [ "$rep" -lt "$REPS" ]; then
        log "STOPPED after replication $rep as asked; stack destroyed."
        exit 0
    fi
done

log "all $REPS replications complete: results/E4/$RUN_ID"
