#!/usr/bin/env bash
# Static ownership-tag checks only. Dummy account/AZ context; networking disabled.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CHECK_VOLUME="aws-wordpress-watchdog-check-$$"
docker volume create "$CHECK_VOLUME" >/dev/null
trap 'docker volume rm "$CHECK_VOLUME" >/dev/null 2>&1 || true' EXIT
# Install locked public dependencies in an isolated temporary volume, without
# credentials. The actual synthesis/typecheck stage below has networking disabled.
docker run --rm -v "$REPO:/repo:ro" -v "$CHECK_VOLUME:/repo/infra/node_modules" \
  aws-wordpress-runner bash -c 'cd /repo/infra && npm ci --no-audit --no-fund --loglevel=error'
docker run --rm -i --network none \
  -v "$REPO:/repo:ro" -v "$CHECK_VOLUME:/repo/infra/node_modules" \
  aws-wordpress-runner bash -s <<'CHECK'
set -euo pipefail
node --version
[ "$(node --version)" = v22.17.0 ]
cd /repo && make build
mkdir -p /tmp/e5-synth
cp -r /repo/infra/bin /repo/infra/lib /repo/infra/cdk.json /repo/infra/tsconfig.json /repo/infra/package.json /tmp/e5-synth/
ln -s /repo/infra/node_modules /tmp/e5-synth/node_modules
cd /tmp/e5-synth
export CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=ap-southeast-1
export AWS_DEFAULT_REGION=ap-southeast-1 AWS_REGION=ap-southeast-1 AWS_EC2_METADATA_DISABLED=true
python3 - <<'PY'
import json
json.dump({'availability-zones:account=123456789012:region=ap-southeast-1':
           ['ap-southeast-1a','ap-southeast-1b','ap-southeast-1c']}, open('cdk.context.json','w'))
PY
export E5_WATCHDOG_TOKEN=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
./node_modules/.bin/cdk synth E5-AttributeCache-dev --no-lookups --output /tmp/tagged >/dev/null
unset E5_WATCHDOG_TOKEN
./node_modules/.bin/cdk synth E5-AttributeCache-dev --no-lookups -c e5Diagnostic=1 --output /tmp/diagnostic >/dev/null
./node_modules/.bin/cdk synth E5-AttributeCache-dev --no-lookups --output /tmp/bare >/dev/null
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('/tmp/tagged/manifest.json').read_text())
for name,a in m['artifacts'].items():
 if a['type'] == 'aws:cloudformation:stack':
  tag=a['properties'].get('tags',{}).get('E5WatchdogRun')
  assert tag == ('a'*32 if name == 'E5-AttributeCache-dev' else None), name
for mode,expected in [('tagged','a'*32),('bare',None)]:
 t=json.loads(Path(f'/tmp/{mode}/E5-AttributeCache-dev.template.json').read_text())
 checked=0
 for res in t['Resources'].values():
  if res['Type'] in ('AWS::FSx::FileSystem','AWS::FSx::Volume','AWS::S3::Bucket'):
   tags={v['Key']:v['Value'] for v in res['Properties'].get('Tags',[])}
   assert tags.get('E5WatchdogRun') == expected, res['Type']
   checked+=1
 assert checked>=5
print('PASS: token in E5 stack, FSx and S3 tags only; absent without token')
t=json.loads(Path('/tmp/diagnostic/E5-AttributeCache-dev.template.json').read_text())
task=next(r['Properties'] for r in t['Resources'].values() if r['Type']=='AWS::ECS::TaskDefinition')
assert task['PidMode']=='host'
containers={c['Name']:c for c in task['ContainerDefinitions']}
assert {v['Name']:v['Value'] for v in containers['bench']['Environment']}['BENCH_MODE']=='e5-diagnostic'
assert {v['Name']:v['Value'] for v in containers['cache-dropper']['Environment']}['E5_DIAGNOSTIC']=='1'
assert not containers['bench'].get('Privileged',False)
assert containers['cache-dropper']['Privileged']
assert {'helper-config','tls-roots'} <= {v['Name'] for v in task['Volumes']}
text=json.dumps(t)
for suffix in ('diag-round-1','diag-round-2','diag-round-3','diag-round-4','diag-tls-on','diag-tls-off'):
 assert suffix in text, suffix
normal=json.loads(Path('/tmp/bare/E5-AttributeCache-dev.template.json').read_text())
normal_task=next(r['Properties'] for r in normal['Resources'].values() if r['Type']=='AWS::ECS::TaskDefinition')
assert 'PidMode' not in normal_task
assert not {'helper-config','tls-roots'} & {v['Name'] for v in normal_task['Volumes']}
print('PASS: diagnostic-only PID/config mounts, fresh subtrees and unprivileged bench; study stays separate')
PY
if E5_WATCHDOG_TOKEN=invalid ./node_modules/.bin/cdk synth E5-AttributeCache-dev --no-lookups --output /tmp/invalid >/tmp/invalid.log 2>&1; then
    echo 'FAIL: invalid token accepted' >&2; exit 1
fi
grep -q 'Invalid E5 watchdog token' /tmp/invalid.log
echo 'PASS: invalid token refused before deployment'
CHECK
