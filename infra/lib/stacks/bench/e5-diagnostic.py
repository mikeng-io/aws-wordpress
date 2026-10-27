#!/usr/bin/env python3
"""Single short diagnostic, never a registered E5 replication. No AWS deployment."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

CTL = Path(os.environ.get('CACHE_CTL_DIR','/bench/cache-ctl'))
OUT = Path('/tmp/e5-diagnostic')
TIERS = ['ebs','efs_host_plain','efs_host_tls','fsx_openzfs','fsx_ontap','fsx_lustre']
DELTAS = ['0.1','1','10']


def host(verb, **fields):
    path = CTL / f'diag-{uuid.uuid4().hex}.request'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(verb=verb, **fields))); tmp.replace(path)
    deadline = time.monotonic()+30
    response = path.with_suffix('.response')
    while time.monotonic() < deadline:
        if response.exists():
            value = json.loads(response.read_text()); response.unlink()
            if not value['ok']:
                raise RuntimeError(f'host {verb}: {value["error"]}')
            return value['data']
        time.sleep(.05)
    raise TimeoutError(f'host {verb}')


def cell(tier, delta, suffix):
    if tier in ('ebs','fsx_lustre'):
        directory = f'/bench/{tier}/ss-{delta}/{suffix}'
    else:
        directory = f'/bench/{tier}.ss-{delta}/{suffix}'
    c = dict(tier=tier, directory=directory, delta=delta)
    if tier not in ('ebs','fsx_lustre'):
        c['nfs_mount'] = f'/bench/{tier}.ss-{delta}'
    return c


def main():
    profile = os.environ.get('E5_DIAGNOSTIC_PROFILE','legacy')
    if profile not in ('legacy','isolation-candidate-v1'):
        raise ValueError('unsupported diagnostic profile')
    OUT.mkdir(exist_ok=False)
    seed = int(Path('/bench/host-facts/seed-utc').read_text())
    age = int(time.time())-seed
    if age < 0:
        raise ValueError('future seed')
    if age < 120:
        time.sleep(120-age)
    shutil.copy('/tmp/mount-facts.csv',OUT/'mount-facts.csv')
    receipt = dict(study_replication=False, warmup_s=60, measured_s=180,
                   seed_age_at_start_s=int(time.time())-seed, phases=[])
    if profile == 'isolation-candidate-v1':receipt['method']=profile
    (OUT/'protocol.json').write_text(json.dumps(receipt,indent=2)+'\n')
    for tier in TIERS:
        conf = f'/bench/{tier}/conf' if tier in ('ebs','fsx_lustre') else f'/bench/{tier}.default/conf'
        with (OUT/f'conformance-{tier}.csv').open('w') as log:
            subprocess.run(['conformance',conf],check=True,stdout=log,stderr=subprocess.STDOUT)
    spec = importlib.util.spec_from_file_location('runner','/usr/local/bin/diagnostic-serve.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    if profile == 'isolation-candidate-v1':
        spec = importlib.util.spec_from_file_location('isolation','/usr/local/bin/e5-isolation-validation.py')
        isolation = importlib.util.module_from_spec(spec); spec.loader.exec_module(isolation)
        isolation.run(host,runner,OUT,receipt['seed_age_at_start_s'])
        (OUT/'diagnostic-complete.json').write_text(json.dumps(dict(completed=True,study_replication=False,method=profile))+'\n')
        return
    def save():
        (OUT/'protocol.json').write_text(json.dumps(receipt,indent=2)+'\n')
    try:
        # Short counterbalanced idle control, actual watchdog traced only here.
        reference = None
        for index, mode in enumerate(('on','off','off','on')):
            meta = host(mode)
            if reference is None:
                reference = meta['read_ahead_kb']
            if meta['read_ahead_kb'] != reference:
                raise ValueError('readahead value changed between arms')
            phase = dict(kind='tls-idle',mode=mode,host=meta,snapshots=[])
            receipt['phases'].append(phase); save()
            host('trace-start',label=f'idle{index}')
            for k in range(121):
                phase['snapshots'].append(host('snapshot'))
                if k < 120:
                    time.sleep(1)
            host('trace-stop'); save()
        # No ptrace during performance captures. Fresh TLS subtree per arm.
        for mode in ('on','off'):
            meta = host(mode)
            if meta['read_ahead_kb'] != reference:
                raise ValueError('readahead value changed')
            phase = dict(kind='tls-active',mode=mode,host=meta)
            receipt['phases'].append(phase); save()
            if runner.run([cell('efs_host_tls',d,f'diag-tls-{mode}') for d in DELTAS],
                          OUT/f'tls-{mode}', 'concurrent',60,180,'agebench'):
                raise RuntimeError('TLS diagnostic failed')
        host('restore')
        # Fresh target subtrees, ABBA order; background subtrees fresh per round.
        for index, mode in enumerate(('isolated','concurrent','concurrent','isolated'),1):
            plan = ([cell('fsx_lustre','0.1',f'diag-round-{index}')] if mode == 'isolated' else
                    [cell(t,d,f'diag-round-{index}') for t in TIERS for d in DELTAS])
            receipt['phases'].append(dict(kind='lustre-concurrency',round=index,mode=mode)); save()
            if runner.run(plan,OUT/f'round-{index}',mode,60,180,'agebench'):
                raise RuntimeError('concurrency diagnostic failed')
    finally:
        host('trace-stop')
        host('restore')
        for path in CTL.glob('trace-*.txt'):
            shutil.copy(path,OUT/path.name)
        save()
    (OUT/'diagnostic-complete.json').write_text(json.dumps(dict(completed=True, study_replication=False))+'\n')


if __name__ == '__main__':
    rc = 0
    try:
        main()
    except Exception as exc:
        OUT.mkdir(exist_ok=True)
        (OUT/'failure.json').write_text(json.dumps(dict(error=type(exc).__name__, detail=str(exc)))+'\n')
        rc = 1
    # Partial data are evidence too. Never substitute a failed run with a retry.
    subprocess.run(['aws','s3','cp',str(OUT)+'/',f"s3://{os.environ['BENCH_S3_BUCKET']}/diagnostic/",
                    '--recursive','--only-show-errors'],check=True)
    raise SystemExit(rc)
