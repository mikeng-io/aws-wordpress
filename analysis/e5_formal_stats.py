#!/usr/bin/env python3
"""Strict isolation-formal-v3 protocol gate, then unchanged P1-P10 with matched P7.

Read-only JSON output. Inputs are one or more E5-formal run directories; never
pool the pilot/diagnostic/candidate or duplicate deployments. No AWS calls.
"""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib
import e5_stats as legacy
import e5_diagnostic_stats as telemetry

METHOD='isolation-formal-v3'
BATCHES=('non-lustre','lustre-0.1','lustre-1','lustre-10')
ARTIFACTS={'e5-formal.py','e5-run','diagnostic-serve.py','e5-isolation-validation.py',
           'e5-diagnostic.py','e5-diagnostic-host.py','cache-dropper','agebench'}
OPS=('GETATTR','LOOKUP','ACCESS')


def require(condition, message):
    if not condition:raise ValueError(message)


def expected(folder):
    if folder=='non-lustre': return [(t,d) for t in legacy.TIERS if t!='fsx_lustre' for d in legacy.DELTAS]
    return [('fsx_lustre',folder[7:]),('ebs',folder[7:])]


def prefix(root,folder,t,d):
    return root/('controls/'+d if folder!='non-lustre' and t=='ebs' else 'ec2/'+t)/f'B-{d}'


def protocol_gate(root,meta):
    """Structure/config provenance is global; validity gates stay per cell."""
    reasons=[]
    try:
        require(meta['experiment']=='E5-formal-isolation' and meta['study_replication'] is True and meta['task_failed'] is False, 'collector identity/completion')
        require(meta['protocol_method']==METHOD, 'collector method')
        require(meta['run_id']==root.parent.parent.name, 'collector run identity')
        require(re.fullmatch('[0-9a-f]{40}',meta['source_commit']), 'source commit')
        require(re.fullmatch('sha256:[0-9a-f]{64}',meta['image_digest']), 'runtime image digest')
        require(re.fullmatch('[0-9a-f]{64}',meta['deployment_id']), 'deployment identity')
        p=json.loads((root/'protocol.json').read_text())
        marker=json.loads((root/'formal-complete.json').read_text())
        require(marker==dict(method=METHOD,study_replication=True,completed=True), 'completion marker')
        require(not (root/'failure.json').exists(), 'apparatus failure')
        require(p['method']==METHOD and p['study_replication'] is True and p['seed_age_at_start_s']>=120, 'protocol identity/age')
        hashes=p['apparatus_sha256']
        require(set(hashes)==ARTIFACTS and all(re.fullmatch('[0-9a-f]{64}',v) for v in hashes.values()), 'apparatus hashes')
        baseline=p['baseline']
        roots={f'/mnt/e5/efs_host_tls/{f}' for f in ('default','forced','ss-0.1','ss-1','ss-10')}
        families={r.rsplit('/',1)[-1] for r in roots}
        require(set(baseline['read_ahead_kb'])==families and int(baseline['watchdog_pid'])>0, 'baseline TLS roots/PID')
        for m in (p['quiet'],p['after_workload']):
            c=m['config'];w=c['mount-watchdog']
            require(c['mount']['optimize_readahead']=='false' and w['stunnel_health_check_enabled']=='false', 'quiet profile')
            require(w['enabled']=='true' and w['poll_interval_sec']=='1', 'lifecycle supervision')
            require(m['read_ahead_kb']==baseline['read_ahead_kb'] and m['watchdog_pid']==baseline['watchdog_pid'], 'readahead/PID drift')
        restored=p['restored']
        require(restored['restored_bytes_match'] is True, 'restoration bytes')
        require(all(restored[k]==baseline[k] for k in ('config','read_ahead_kb','watchdog_pid')), 'restoration metadata')
        snaps=p['idle_snapshots'];first,last=snaps[0],snaps[-1]
        require(last['monotonic_ns']-first['monotonic_ns']>=360_000_000_000, 'idle shorter than 360s')
        require(all(b['monotonic_ns']>a['monotonic_ns'] for a,b in zip(snaps,snaps[1:])), 'idle clock order')
        for snap in snaps:
            require(set(snap['roots'])==roots, 'missing idle TLS root')
            require(all(set(v)==set(OPS) and all(isinstance(x,int) and x>=0 for x in v.values()) for v in snap['roots'].values()), 'idle counters')
            require(snap['roots']==first['roots'], 'background idle RPCs')
        trace=(root/'trace-quiet.txt').read_text()
        require(not any(('statx(' in line or 'newfstatat(' in line) and '/mnt/e5/efs_host_tls/' in line for line in trace.splitlines()), 'helper root stat calls')
        phases=p['phases']
        require([(x['kind'],x.get('folder')) for x in phases]==[('cohort-a',None)]+[('batch',f) for f in BATCHES]+[('expiry-probes',None)], 'phase identities/order')
        previous=last['monotonic_ns'];bindings=[]
        for phase in phases:
            require(previous<=phase['start_ns']<phase['end_ns'], 'phase overlap/clock order')
            previous=phase['end_ns']
            if phase['kind']!='batch': continue
            folder=phase['folder'];job=json.loads((root/'batches'/folder/'diagnostic-run.json').read_text())
            require(job['schema']=='e5-formal-batch-v1' and job['study_replication'] is True, 'batch identity')
            require(job['mode']=='concurrent' and job['warmup']==300 and job['measure']==600, 'formal windows')
            pairs=expected(folder);require(len(job['cells'])==len(pairs), 'batch size')
            require(len(job['plan'])==len(pairs), 'plan size')
            for c,plan,(t,d) in zip(job['cells'],job['plan'],pairs):
                nfs=t in legacy.NFS_TIERS;directory=f'/bench/{t}.ss-{d}' if nfs else f'/bench/{t}/ss-{d}'
                reference=folder!='non-lustre' and t=='ebs'
                if reference:directory+='/formal-lustre-control'
                want=dict(tier=t,delta=d,directory=directory,**({'nfs_mount':directory} if nfs else {}))
                require(plan==want, 'measurement directory/reference plan')
                require(c['cell']==f'{t}-{d}' and c['exit_code']==0, 'child identity/exit')
                require(phase['start_ns']<=c['started_monotonic_ns']<c['reaped_monotonic_ns']<=phase['end_ns'], 'child lifetime/order')
                stem=root/'batches'/folder/f'{t}-{d}'
                command=['agebench','serve',directory,d,'300','600',f'B-{d}',str('/tmp/e5-formal/batches/'+folder+f'/{t}-{d}'),{'0.1':'100','1':'10','10':'1'}[d]]
                if nfs:command.append(directory)
                require(c['command']==command, 'instrument command/binding')
                export=prefix(root,folder,t,d)
                require(gzip.open(str(export)+'.req.csv.gz','rb').read()==Path(str(stem)+'.req.csv').read_bytes(), 'request export differs from batch')
                for suffix in ('.diagnostics.csv',):
                    require(Path(str(export)+suffix).read_bytes()==Path(str(stem)+suffix).read_bytes(), 'telemetry export differs from batch')
                if nfs:
                    for suffix in ('.mountstats.warm','.mountstats.end'):
                        active=False;lines=[]
                        for line in Path(str(stem)+suffix).read_text().splitlines(keepends=True):
                            if line.startswith('device '):active=line.split()[4]==directory
                            if active:lines.append(line)
                        require(lines and Path(str(export)+suffix).read_text()==''.join(lines), 'mount snapshot export differs from batch')
                header,rows=legacy.load_req(Path(str(export)+'.req.csv.gz'))
                require(int(header['warm_requests'])==round(300/float(d)) and int(header['measured_requests'])==round(600/float(d)), 'short request windows')
                require(header['rpc_mount']==(directory if nfs else '-'), 'measurement mount')
                # CPU/wall endpoint validation is independent of the histogram grader.
                telemetry.analyze_cell(Path(str(stem)+'.req.csv'))
                bindings.append(dict(tier=t,delta=d,reference=reference,raw=f'batches/{folder}/{t}-{d}',export=str(export.relative_to(root))))
        require(p['bindings']==bindings, 'reference/export binding receipt')
        facts=list(csv.reader((root/'ec2/mount-facts.csv').read_text().splitlines()))
        waits=[x for x in facts if x[0]=='a_wait']
        require(len(waits)==12 and all(sum(x[1]==t for x in waits)==2 for t in legacy.TIERS), 'cohort A wait coverage')
        a_phase=phases[0]
        require(all(a_phase['start_ns']<=int(x[2])<int(x[3])<=a_phase['end_ns'] and
                    int(x[3])-int(x[2])>=75_000_000_000 for x in waits), 'short or unbound A expiry wait')
        ordered=sorted(waits,key=lambda x:int(x[2]))
        require(all(int(a[3])<=int(b[2]) for a,b in zip(ordered,ordered[1:])), 'overlapping A expiry waits')
        orders=[x[1] for x in facts if x[0]=='tier_order'];require(len(orders)==6 and set(orders)==set(legacy.TIERS), 'cohort A tier order')
        for t in legacy.TIERS:
            td=root/'ec2'/t
            conf=dict(csv.reader((td/'conformance.csv').read_text().splitlines()))
            require(conf.get('TOTAL_FAILURES')=='0' and conf.get('TOTAL_ERRORS')=='0', 'conformance totals')
            require(len(conf)==13 and all(v=='PASS' for k,v in conf.items() if not k.startswith('TOTAL_')), 'conformance checks')
            operations=dict(A1='stat',A2='enoent',A3='stat',A4='enoent',A5='stat',A6='open_read',A7='open_read')
            if t in legacy.NFS_TIERS:operations.update(A8w='stat',A8='stat')
            for c,op in operations.items():
                rows=list(csv.reader((td/f'{c}.csv').read_text().splitlines()))
                require(len(rows)==(10000 if c=='A8' else 1000), 'cohort A count')
                require(all(x[0]==c and x[1]==op and int(x[2])==k and int(x[3])>=0 for k,x in enumerate(rows)), 'cohort A operation/sequence')
            if t in legacy.NFS_TIERS:
                for d in legacy.DELTAS:
                    require(float((td/f'D-{d}.idle-seconds').read_text())>=75, 'short post-B idle')
                    probe=legacy.expiry_probe(td,d,f'/bench/{t}.ss-{d}')
                    require('reason' not in probe, 'invalid expiry-probe input')
        return dict(status='ELIGIBLE',reasons=[],apparatus_sha256=hashes)
    except (OSError,ValueError,KeyError,TypeError,IndexError,ZeroDivisionError,
            EOFError,zlib.error,UnicodeError,OverflowError,AttributeError) as exc:
        reasons.append(str(exc) or type(exc).__name__)
        return dict(status='ERROR',reasons=reasons)


def analyse(run_dirs):
    per_rep={};identities=set();fingerprint=None
    for run in run_dirs:
        for rep in sorted(run.glob('rep-*')):
            key=run.name+'/'+rep.name
            if key in per_rep:raise ValueError('duplicate input run/replication')
            root=rep/'formal'
            try:meta=json.loads((rep/'meta.json').read_text())
            except (OSError,ValueError):meta={}
            if meta.get('experiment')!='E5-formal-isolation' or meta.get('protocol_method')!=METHOD:
                raise ValueError('only isolation-formal-v3 inputs may be pooled')
            gate=protocol_gate(root,meta)
            if gate['status']=='ELIGIBLE':
                identity=meta['deployment_id'];f=(meta['image_digest'],gate['apparatus_sha256'])
                if identity in identities:raise ValueError('duplicate deployment cannot be an independent replication')
                if fingerprint is not None and f!=fingerprint:raise ValueError('apparatus/runtime drift across replications')
                identities.add(identity);fingerprint=f
                a,b=legacy.cohort_a(root),legacy.cohort_b(root)
                controls={d:legacy.cohort_b_cell('ebs',d,root/'controls'/d) for d in legacy.DELTAS}
                control_hists={d:(legacy.stat_histogram('ebs',d,root/'controls'/d)
                                  if controls[d].get('status')=='OK' else None) for d in legacy.DELTAS}
                grades={k:fn(a,b) for k,fn in legacy.PREDICTIONS.items() if k!='7'}
                matched={**b,'ebs':controls};grades['7']=legacy.p7(a,matched,control_hists)
                grades['7']['reference_binding']='same-time EBS from the corresponding Lustre batch'
                valid=all(c['status']=='OK' for t in a.values() for c in t.values()) and all(c['status']=='OK' for t in b.values() for c in t.values()) and all(c['status']=='OK' for c in controls.values())
                for cells in [*b.values(),controls]:
                    for cell in cells.values():cell.pop('rpc_ops_per_request',None)
                entry=dict(protocol=gate,full_method_validation='PASS' if valid else 'NOT_READY',a=a,b=b,matched_controls=controls,grades=grades,
                           source_commit=meta['source_commit'],image_digest=meta['image_digest'],deployment_id=identity)
            else:
                entry=dict(protocol=gate,full_method_validation='NOT_READY',grades={k:legacy.err('; '.join(gate['reasons'])) for k in legacy.PREDICTIONS})
            per_rep[key]=entry
    if not per_rep:raise ValueError('no formal replications found')
    return dict(method=METHOD,study_replication=True,replications=per_rep,
                predictions={k:dict(status=legacy.combine([r['grades'][k] for r in per_rep.values()]),per_replication={n:r['grades'][k] for n,r in per_rep.items()}) for k in legacy.PREDICTIONS},
                grader_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(legacy.__file__),Path(telemetry.__file__))})


if __name__=='__main__':
    if len(sys.argv)<2:raise SystemExit('usage: e5_formal_stats.py <E5-formal-run> [other independent runs ...]')
    print(json.dumps(analyse([Path(p) for p in sys.argv[1:]]),indent=2))
