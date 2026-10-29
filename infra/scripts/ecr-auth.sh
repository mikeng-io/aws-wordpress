#!/usr/bin/env bash
# Put a short-lived ECR token in the Docker config CDK will use. This replaces
# `docker login`, whose credential-store write is what fails on macOS here.
set -euo pipefail

: "${DOCKER_CONFIG:?DOCKER_CONFIG must name the config directory}"
REGION="${AWS_REGION:-ap-southeast-1}"
AWS_CLI="${AWS_CLI:-/usr/local/bin/aws}"
ACCOUNT="$("$AWS_CLI" sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TOKEN="$("$AWS_CLI" ecr get-login-password --region "$REGION")"

mkdir -p "$DOCKER_CONFIG"
python3 - "$REGISTRY" "$TOKEN" "$DOCKER_CONFIG/config.json" <<'PY'
import base64, json, sys
registry, token, path = sys.argv[1], sys.argv[2], sys.argv[3]
auth = base64.b64encode(f"AWS:{token}".encode()).decode()
try:
    with open(path) as fh:
        cfg = json.load(fh)
except FileNotFoundError:
    cfg = {}
cfg.setdefault("auths", {})[registry] = {"auth": auth}
with open(path, "w") as fh:
    json.dump(cfg, fh)
PY
