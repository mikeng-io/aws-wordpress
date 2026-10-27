#!/usr/bin/env python3
"""Strict read-only E5 diagnostic analysis. Outputs JSON to stdout, never regrades E5."""
import csv,json,re,sys
from pathlib import Path
OPS=('GETATTR','LOOKUP','ACCESS')
def counts(text):
    if text=='-': return None
    values=[int(x) for x in text.split(':')]
    if len(values)!=3 or min(values)<0:raise ValueError('invalid RPC endpoint')
    return dict(zip(OPS,values))
def subtract(a,b):
    result={k:b[k]-a[k] for k in OPS}
    if min(result.values())<0:raise ValueError('counter reset')
    return result
def stats(values):
    s=sorted(values)
    if not s:raise ValueError('empty distribution')
    return dict(n=len(s),mean=sum(s)/len(s),p50=s[(len(s)-1)//2],p99=s[(len(s)*99+99)//100-1],maximum=s[-1])
def window(path,mount):
    active=False; result={}; sections=0
    for line in path.read_text().splitlines():
        if line.startswith('device '):
            active=line.split()[4]==mount
            sections+=active
        elif active:
            fields=line.split()
            if fields and fields[0] in [x+':' for x in OPS]:result[fields[0][:-1]]=int(fields[1])
    if sections!=1 or set(result)!=set(OPS):raise ValueError('missing/ambiguous independent mount window')
    return result

def analyze_cell(path):
    prefix=str(path)[:-len('.req.csv')]
    with path.open() as f:
        header=dict(p.split('=',1) for p in next(f).lstrip('#').split())
        rows=list(csv.DictReader(f))
    if header['method']!='rpc-phases-v2':raise ValueError('unsupported method')
    nw,nm=int(header['warm_requests']),int(header['measured_requests'])
    delta=int(header['delta_ns'])
    if len(rows)!=nw+nm:raise ValueError('incomplete request window')
    for k,r in enumerate(rows):
        if int(r['k'])!=k or r['phase']!=('w' if k<nw else 'm'):raise ValueError('request sequence/phase')
        for field in ('stat_bins','enoent_bins'):
            if sum(int(x.split(':')[1]) for x in r[field].split('|'))!=1000:raise ValueError('wrong op count')
        if min(int(r[x]) for x in ('lateness_ns','stat_sum_ns','enoent_sum_ns','counter_ns'))<0:raise ValueError('negative timing')
    with Path(prefix+'.diagnostics.csv').open() as f:telemetry=list(csv.DictReader(f))
    if len(telemetry)!=len(rows):raise ValueError('incomplete telemetry')
    for r,t in zip(rows,telemetry):
        if (r['k'],r['phase'])!=(t['k'],t['phase']):raise ValueError('telemetry alignment')
        wall=int(t['end_ns'])-int(t['start_ns']);cpu=int(t['thread_cpu_ns'])
        if not 0<=cpu<=wall or wall<int(r['stat_sum_ns'])+int(r['enoent_sum_ns']):raise ValueError('invalid CPU/wall timing')
    if any(int(b['start_ns'])<int(a['end_ns']) for a,b in zip(telemetry,telemetry[1:])):raise ValueError('non-monotonic telemetry')
    measured=rows[nw:]; timing=telemetry[nw:]
    wall=[int(t['end_ns'])-int(t['start_ns']) for t in timing]
    cpu=[int(t['thread_cpu_ns']) for t in timing]
    out=dict(status='VALID_DIAGNOSTIC_INPUT',requests=nm,delta_ns=delta,
        late_over_half_interval=sum(2*int(r['lateness_ns'])>delta for r in measured),
        syscall_sum_over_interval=sum(int(r['stat_sum_ns'])+int(r['enoent_sum_ns'])>delta for r in measured),
        lateness_ns=stats([int(r['lateness_ns']) for r in measured]),wall_ns=stats(wall),thread_cpu_ns=stats(cpu),
        off_cpu_ns=stats([w-c for w,c in zip(wall,cpu)]),service_thread_cpu_share=sum(cpu)/sum(wall))
    out['late_share']=out['late_over_half_interval']/nm
    mount=header['rpc_mount']
    if mount!='-':
        phase={k:0 for k in OPS};gap={k:0 for k in OPS};events=[]
        for r,t in zip(measured,timing):
            s,e=counts(r['stat_rpc']),counts(r['enoent_rpc'])
            endpoints=subtract(counts(t['rpc_start']),counts(t['rpc_end']))
            if endpoints!={k:s[k]+e[k] for k in OPS}:raise ValueError('phase/endpoint disagreement')
            for k in OPS:phase[k]+=endpoints[k]
        for a,b in zip(timing,timing[1:]):
            diff=subtract(counts(a['rpc_end']),counts(b['rpc_start']))
            for k in OPS:gap[k]+=diff[k]
            if any(diff.values()):events.append(dict(previous_k=int(a['k']),next_k=int(b['k']),previous_end_ns=int(a['end_ns']),next_start_ns=int(b['start_ns']),operations=diff))
        actual=subtract(window(Path(prefix+'.mountstats.warm'),mount),window(Path(prefix+'.mountstats.end'),mount))
        if any(actual[k]<phase[k] for k in OPS):raise ValueError('phase counts exceed independent window')
        if any(gap[k]>actual[k]-phase[k] for k in OPS):raise ValueError('gap counts exceed residual window')
        out['rpc']=dict(phase=phase,independent_window=actual,
            window_minus_phase={k:actual[k]-phase[k] for k in OPS},observed_between_measured_requests=gap,inter_request_events=events,
            limitation='first measured boundary and window tail not in inter-request gaps; no producer identity')
    return out

def analyze(root):
    protocol_error=None
    try:
        protocol=json.loads((root/'protocol.json').read_text())
        if protocol.get('study_replication') is not False:raise ValueError('not a diagnostic protocol')
    except (OSError,ValueError) as exc:
        protocol={'phases':[]};protocol_error=str(exc)
    try:
        marker=json.loads((root/'diagnostic-complete.json').read_text())
        complete=marker.get('completed') is True and marker.get('study_replication') is False and protocol_error is None
    except (OSError,ValueError):complete=False
    idle=[]
    for p in protocol['phases']:
        if p['kind'] not in ('tls-idle','isolation-idle'):continue
        snapshots=p['snapshots']
        if len(snapshots)<2:
            idle.append(dict(mode=p['mode'],status='INCOMPLETE',snapshots=len(snapshots)))
            continue
        before,after=snapshots[0],snapshots[-1]
        idle.append(dict(mode=p['mode'],elapsed_seconds=(after['monotonic_ns']-before['monotonic_ns'])/1e9,
            host=p['host'],deltas={mount:subtract(before['roots'][mount],values) for mount,values in after['roots'].items()}))
    cells={}
    for path in sorted(root.glob('*/*.req.csv')):
        key=str(path.relative_to(root))
        try:cells[key]=analyze_cell(path)
        except (ValueError,KeyError,OSError,TypeError,ZeroDivisionError,IndexError) as exc:cells[key]=dict(status='ERROR',reason=str(exc))
    integrity_errors=[]
    for phase in protocol['phases']:
        folder=(phase['folder'] if phase['kind']=='isolation-batch' else
                f"tls-{phase['mode']}" if phase['kind']=='tls-active' else
                f"round-{phase['round']}" if phase['kind']=='lustre-concurrency' else None)
        if folder is None:continue
        try:
            receipt=json.loads((root/folder/'diagnostic-run.json').read_text())
            for cell in receipt['cells']:
                key=f"{folder}/{cell['cell']}.req.csv"
                if key not in cells:cells[key]=dict(status='ERROR',reason='missing planned request file')
                if cell.get('exit_code')!=0:integrity_errors.append(f"{key}: child exit not zero")
        except (OSError,ValueError,KeyError) as exc:integrity_errors.append(f'{folder}: {exc}')
    all_valid=complete and bool(cells) and not integrity_errors and all(v['status']=='VALID_DIAGNOSTIC_INPUT' for v in cells.values())
    report = dict(schema='e5-diagnostic-analysis-v1',completed=complete,all_inputs_valid=all_valid,integrity_errors=integrity_errors,protocol_error=protocol_error,study_replication=False,idle_controls=idle,cells=cells,
        trace_root_syscalls_by_kind={p.name:{kind:sum(kind+'(' in line and '/mnt/e5/efs_host_tls/' in line for line in p.read_text().splitlines()) for kind in ('statx','newfstatat')} for p in sorted(root.glob('trace-*.txt'))},
        trace_root_stat_calls={p.name:sum(('statx(' in line or 'newfstatat(' in line) and '/mnt/e5/efs_host_tls/' in line for line in p.read_text().splitlines()) for p in sorted(root.glob('trace-*.txt'))},
        limitations=['n=1; short windows; no study verdict','off-CPU does not distinguish filesystem/lock waits from descheduling'])
    if protocol.get('method') == 'isolation-candidate-v1':
        report['candidate_acceptance'] = candidate_acceptance(root,protocol,report)
    return report


def candidate_acceptance(root, protocol, report):
    """Predeclared candidate checks; never changes the registered E5 grader."""
    reasons=[]
    try:
        marker=json.loads((root/'diagnostic-complete.json').read_text())
        if marker.get('method')!='isolation-candidate-v1':raise ValueError('wrong candidate marker')
    except (OSError,ValueError) as exc:reasons.append(f'method identity: {exc}')
    if not report['all_inputs_valid']:reasons.append('incomplete or invalid diagnostic inputs')
    if protocol.get('seed_age_at_start_s',0)<120:reasons.append('missing aged seed proof')
    try:
        baseline=protocol['baseline'];quiet=protocol['quiet'];after=protocol['after_workload']
        for meta in (quiet,after):
            c=meta['config']
            if c['mount']['optimize_readahead'].lower() not in ('false','no','off','0'):raise ValueError('readahead probe enabled')
            if c['mount-watchdog']['stunnel_health_check_enabled'].lower() not in ('false','no','off','0'):raise ValueError('health probe enabled')
            if c['mount-watchdog']['enabled'].lower() not in ('true','yes','on','1'):raise ValueError('lifecycle supervision disabled')
            if c['mount-watchdog']['poll_interval_sec']!='1':raise ValueError('unsupported watchdog poll interval')
            if meta['read_ahead_kb']!=baseline['read_ahead_kb']:raise ValueError('effective readahead changed')
            if meta['watchdog_pid']!=baseline['watchdog_pid']:raise ValueError('watchdog restarted')
        restored=protocol['restored']
        if not restored['restored_bytes_match'] or restored['config']!=baseline['config'] or restored['read_ahead_kb']!=baseline['read_ahead_kb']:
            raise ValueError('restoration unverified')
    except (KeyError,ValueError,TypeError,AttributeError) as exc:reasons.append(f'helper profile: {exc}')
    if len(report['idle_controls'])!=1 or report['idle_controls'][0].get('elapsed_seconds',0)<360:
        reasons.append('quiet idle window shorter than 360 seconds')
    elif len(report['idle_controls'][0]['deltas'])!=5:
        reasons.append('quiet idle control missing TLS mount roots')
    elif any(v for ops in report['idle_controls'][0]['deltas'].values() for v in ops.values()):
        reasons.append('background GETATTR/LOOKUP/ACCESS in idle control')
    if not (root/'trace-quiet.txt').is_file() or report['trace_root_stat_calls'].get('trace-quiet.txt',-1)!=0:
        reasons.append('quiet helper root trace not silent or absent')
    expected={f'non-lustre/{t}-{d}.req.csv':(d,360) for t in
              ('ebs','efs_host_plain','efs_host_tls','fsx_openzfs','fsx_ontap') for d in ('0.1','1','10')}
    expected.update({f'lustre-{d}/{t}-{d}.req.csv':(d,180) for d in ('0.1','1','10') for t in ('fsx_lustre','ebs')})
    if set(report['cells'])!=set(expected):reasons.append('candidate requires 18 target cells plus three matched EBS references')
    for key,(d,seconds) in expected.items():
        cell=report['cells'].get(key,{})
        if cell.get('status')!='VALID_DIAGNOSTIC_INPUT':continue
        tier=Path(key).name.rsplit('-',1)[0]
        nfs=tier not in ('ebs','fsx_lustre')
        if nfs and 'rpc' not in cell:reasons.append(f'{key}: missing NFS RPC instrumentation')
        if cell['delta_ns']!=round(float(d)*1e9) or cell['requests']!=round(seconds/float(d)):
            reasons.append(f'{key}: unexpected interval/window')
        try:
            with (root/key).open() as f:header=dict(p.split('=',1) for p in next(f).lstrip('#').split())
            if int(header['warm_requests'])!=round(60/float(d)):raise ValueError('wrong warmup')
            if header.get('rpc_mount')!=(f'/bench/{tier}.ss-{d}' if nfs else '-'):
                raise ValueError('wrong or missing measurement mount')
        except (OSError,KeyError,ValueError) as exc:reasons.append(f'{key} header: {exc}')
        if cell['late_share']>.05:reasons.append(f'{key}: >5% later than delta/2')
        if 'rpc' in cell and any(cell['rpc']['window_minus_phase'].values()):
            reasons.append(f'{key}: phase/window RPC disagreement')
    previous_end=None
    for folder,mode,count in [('non-lustre','concurrent',15)]+[(f'lustre-{d}','concurrent',2) for d in ('0.1','1','10')]:
        try:
            job=json.loads((root/folder/'diagnostic-run.json').read_text())
            if job['mode']!=mode or len(job['cells'])!=count:raise ValueError('wrong batch shape')
            names={Path(key).name.removesuffix('.req.csv') for key in expected if key.startswith(folder+'/')}
            if {c['cell'] for c in job['cells']}!=names:raise ValueError('wrong batch cell identities')
            if job['warmup']!=60 or job['measure']!=(360 if folder=='non-lustre' else 180):raise ValueError('wrong batch timing')
            start=min(c['started_monotonic_ns'] for c in job['cells'])
            end=max(c['reaped_monotonic_ns'] for c in job['cells'])
            if end<start or (previous_end is not None and start<previous_end):raise ValueError('overlapping batches')
            previous_end=end
        except (OSError,KeyError,ValueError) as exc:reasons.append(f'{folder} schedule: {exc}')
    return dict(status='PASS_CANDIDATE_ONLY' if not reasons else 'NOT_READY',reasons=reasons,
                study_verdict=False,note='An offline fixture pass is not live AWS acceptance or authorisation')
if __name__=='__main__':print(json.dumps(analyze(Path(sys.argv[1])),indent=2,sort_keys=True))
