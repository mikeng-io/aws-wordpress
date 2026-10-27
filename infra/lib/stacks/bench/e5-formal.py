#!/usr/bin/env python3
"""Opt-in isolation-formal-v3 apparatus. Deployment is owned by the host guard."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

METHOD = 'isolation-formal-v3'
OUT = Path('/tmp/e5-formal')


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def plans():
    tiers = ('ebs','efs_host_plain','efs_host_tls','fsx_openzfs','fsx_ontap')
    def cell(t, d, control=False):
        nfs = t not in ('ebs','fsx_lustre')
        directory = f'/bench/{t}.ss-{d}' if nfs else f'/bench/{t}/ss-{d}'
        if control: directory += '/formal-lustre-control'
        return dict(tier=t,delta=d,directory=directory,**({'nfs_mount':directory} if nfs else {}))
    return [dict(folder='non-lustre',cells=[cell(t,d) for t in tiers for d in ('0.1','1','10')])] + [
        dict(folder=f'lustre-{d}',cells=[cell('fsx_lustre',d),cell('ebs',d,True)]) for d in ('0.1','1','10')]


def export_batch(plan, source, output):
    """Keep the full raw batch, and bind exact bytes into the legacy cell parser layout."""
    bindings = []
    for c in plan['cells']:
        t,d = c['tier'],c['delta']
        dest = output/'ec2'/t if plan['folder']=='non-lustre' or t=='fsx_lustre' else output/'controls'/d
        dest.mkdir(parents=True,exist_ok=True)
        stem = f'{t}-{d}'
        for p in source.glob(stem+'.*'):
            suffix = p.name[len(stem):]
            target = dest/(f'B-{d}'+suffix)
            if suffix in ('.req.csv','.raw.csv'):
                with gzip.open(str(target)+'.gz','wb') as f: f.write(p.read_bytes())
            elif suffix in ('.mountstats.warm','.mountstats.end') and c.get('nfs_mount'):
                active=False;lines=[]
                for line in p.read_text().splitlines(keepends=True):
                    if line.startswith('device '):active=line.split()[4]==c['nfs_mount']
                    if active:lines.append(line)
                if not lines:raise ValueError('measurement mount missing from snapshot')
                target.write_text(''.join(lines))
            else: shutil.copyfile(p,target)
        with (dest/'status.csv').open('a') as f: f.write(f'B-{d},ok\n')
        bindings.append(dict(tier=t,delta=d,reference=plan['folder']!='non-lustre' and t=='ebs',
                             raw=f"batches/{plan['folder']}/{stem}",export=str(dest.relative_to(output))+f'/B-{d}'))
    return bindings


def apparatus_hashes():
    hashes={}
    for name in ('e5-formal.py','e5-run','diagnostic-serve.py','e5-isolation-validation.py',
                 'e5-diagnostic.py','e5-diagnostic-host.py','cache-dropper','agebench'):
        hashes[name] = hashlib.sha256((Path('/usr/local/bin')/name).read_bytes()).hexdigest()
    return hashes


def run(host, runner, isolation, output, phase, seed_age):
    if seed_age < 120: raise ValueError('seed younger than 120 seconds')
    receipt = dict(method=METHOD,study_replication=True,seed_age_at_start_s=seed_age,
                   phases=[],bindings=[],apparatus_sha256=apparatus_hashes())
    def save(): (output/'protocol.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    baseline = host('metadata');receipt['baseline']=baseline;save()
    try:
        receipt['quiet']=host('quiet');isolation.require_quiet(baseline,receipt['quiet']);save()
        receipt['idle_snapshots']=isolation.idle(host);save()
        first,last=receipt['idle_snapshots'][0],receipt['idle_snapshots'][-1]
        if any(last['roots'][k]!=v for k,v in first['roots'].items()):
            raise ValueError('quiet idle RPCs remain')
        start=time.monotonic_ns();phase('A',output/'ec2')
        receipt['phases'].append(dict(kind='cohort-a',start_ns=start,end_ns=time.monotonic_ns()));save()
        for plan in plans():
            start=time.monotonic_ns();dest=output/'batches'/plan['folder']
            if runner.run(plan['cells'],dest,'concurrent',300,600,'agebench',study_replication=True):
                raise RuntimeError('formal batch child failed')
            receipt['bindings']+=export_batch(plan,dest,output)
            receipt['phases'].append(dict(kind='batch',folder=plan['folder'],start_ns=start,end_ns=time.monotonic_ns()));save()
        start=time.monotonic_ns();phase('D',output/'ec2')
        receipt['phases'].append(dict(kind='expiry-probes',start_ns=start,end_ns=time.monotonic_ns()));save()
        receipt['after_workload']=host('metadata');isolation.require_quiet(baseline,receipt['after_workload'])
    finally:
        try:
            try: host('trace-stop')
            finally:
                receipt['restored']=host('restore');save()
                restored=receipt['restored']
                if not restored.get('restored_bytes_match') or restored['config']!=baseline['config'] or restored['read_ahead_kb']!=baseline['read_ahead_kb'] or restored['watchdog_pid']!=baseline['watchdog_pid']:
                    raise ValueError('helper restoration failed')
        finally:
            for p in Path(os.environ.get('CACHE_CTL_DIR','/bench/cache-ctl')).glob('trace-*.txt'):
                shutil.copyfile(p,output/p.name)
            save()
    (output/'formal-complete.json').write_text(json.dumps(dict(method=METHOD,study_replication=True,completed=True))+'\n')


def main():
    OUT.mkdir(exist_ok=False)
    diag=module('diag','e5-diagnostic.py');isolation=module('isolation','e5-isolation-validation.py')
    runner=module('runner','diagnostic-serve.py')
    seed=int(Path('/bench/host-facts/seed-utc').read_text());age=int(time.time())-seed
    if age<0: raise ValueError('future seed')
    if age<120: time.sleep(120-age)
    def phase(kind, output):
        env=dict(os.environ,E5_FORMAL_PHASE=kind,E5_FORMAL_METHOD=METHOD,E5_FORMAL_OUT=str(output),
                 E5_WAIT_S='75',E5_PROBE_WAIT_S='75',E5_AGE_MIN_S='120',E5_A8_PASSES='10',
                 E5_DELTAS='0.1 1 10',E5_WARMUP_S='300',E5_MEASURE_S='600')
        subprocess.run(['/usr/local/bin/e5-run'],env=env,check=True)
    run(diag.host,runner,isolation,OUT,phase,int(time.time())-seed)
    shutil.copyfile('/tmp/mount-facts.csv',OUT/'ec2/mount-facts.csv')


if __name__=='__main__':
    rc=0
    try: main()
    except Exception as exc:
        OUT.mkdir(exist_ok=True)
        (OUT/'formal-complete.json').unlink(missing_ok=True)
        (OUT/'failure.json').write_text(json.dumps(dict(error=type(exc).__name__,detail=str(exc)))+'\n');rc=1
    subprocess.run(['aws','s3','cp',str(OUT)+'/',f"s3://{os.environ['BENCH_S3_BUCKET']}/formal/",
                    '--recursive','--only-show-errors'],check=True)
    raise SystemExit(rc)
