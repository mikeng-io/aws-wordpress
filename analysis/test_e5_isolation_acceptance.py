"""Synthetic candidate acceptance, including rejection of weakened controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import e5_diagnostic_stats as a


class IsolationAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        baseline=dict(config={'mount':{'optimize_readahead':'true'},'mount-watchdog':{
            'enabled':'true','poll_interval_sec':'1','stunnel_health_check_enabled':'true'}},
            read_ahead_kb={'root':'15360'},watchdog_pid=42)
        quiet=copy.deepcopy(baseline)
        quiet['config']['mount']['optimize_readahead']='false'
        quiet['config']['mount-watchdog']['stunnel_health_check_enabled']='false'
        protocol=dict(method='isolation-candidate-v1',study_replication=False,
            seed_age_at_start_s=201,baseline=baseline,quiet=quiet,after_workload=quiet,
            restored=dict(baseline,restored_bytes_match=True),phases=[dict(kind='isolation-idle',mode='quiet',host=quiet,
            snapshots=[dict(monotonic_ns=n,roots={f'/mnt/e5/efs_host_tls/{family}':{op:0 for op in a.OPS}
                       for family in ('default','forced','ss-0.1','ss-1','ss-10')}) for n in (0,360_000_000_000)])])
        jobs=[('non-lustre',[(t,d) for t in ('ebs','efs_host_plain','efs_host_tls','fsx_openzfs','fsx_ontap') for d in ('0.1','1','10')],360)]
        jobs += [(f'lustre-{d}',[(t,d) for t in ('fsx_lustre','ebs')],180) for d in ('0.1','1','10')]
        start=361_000_000_000
        for folder,cells,measure in jobs:
            directory=cls.root/folder;directory.mkdir()
            protocol['phases'].append(dict(kind='isolation-batch',folder=folder))
            job=dict(mode='concurrent',warmup=60,measure=measure,cells=[])
            for tier,d in cells:
                name=f'{tier}-{d}';delta=round(float(d)*1e9)
                nw,nm=round(60/float(d)),round(measure/float(d))
                nfs=tier not in ('ebs','fsx_lustre');mount=f'/bench/{tier}.ss-{d}' if nfs else '-'
                with (directory/f'{name}.req.csv').open('w') as req,(directory/f'{name}.diagnostics.csv').open('w') as diag:
                    req.write(f'# method=rpc-phases-v2 delta_ns={delta} warm_requests={nw} measured_requests={nm} rpc_mount={mount}\n')
                    req.write('k,phase,lateness_ns,stat_sum_ns,enoent_sum_ns,stat_bins,enoent_bins,stat_rpc,enoent_rpc,counter_ns\n')
                    diag.write('k,phase,start_ns,end_ns,thread_cpu_ns,rpc_start,rpc_end\n')
                    for k in range(nw+nm):
                        phase='w' if k<nw else 'm';rpc='0:0:0' if nfs else '-';t=start+k*delta
                        req.write(f'{k},{phase},0,100000,100000,0:1000,0:1000,{rpc},{rpc},10\n')
                        diag.write(f'{k},{phase},{t},{t+1000000},400000,{rpc},{rpc}\n')
                if nfs:
                    for when in ('warm','end'):
                        (directory/f'{name}.mountstats.{when}').write_text(f'device fake mounted on {mount} with fstype nfs4\n GETATTR: 0\n LOOKUP: 0\n ACCESS: 0\n')
                job['cells'].append(dict(cell=name,exit_code=0,started_monotonic_ns=start,
                    reaped_monotonic_ns=start+(60+measure)*1_000_000_000))
            (directory/'diagnostic-run.json').write_text(json.dumps(job))
            start+=(60+measure+1)*1_000_000_000
        (cls.root/'protocol.json').write_text(json.dumps(protocol))
        (cls.root/'diagnostic-complete.json').write_text(json.dumps(dict(method=protocol['method'],completed=True,study_replication=False)))
        (cls.root/'trace-quiet.txt').write_text('')
        cls.protocol=protocol;cls.report=a.analyze(cls.root)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_full_candidate_fixture_passes_without_study_verdict(self):
        self.assertEqual(len(self.report['cells']),21)
        self.assertEqual(self.report['candidate_acceptance']['status'],'PASS_CANDIDATE_ONLY')
        self.assertFalse(self.report['candidate_acceptance']['study_verdict'])

    def test_candidate_rejects_weakened_controls_and_gates(self):
        cases={
            'health probe':lambda p,r:p['quiet']['config']['mount-watchdog'].update(stunnel_health_check_enabled='true'),
            'lifecycle':lambda p,r:p['quiet']['config']['mount-watchdog'].update(enabled='false'),
            'readahead':lambda p,r:p['quiet']['read_ahead_kb'].update(root='1'),
            'restart':lambda p,r:p['quiet'].update(watchdog_pid=99),
            'restore':lambda p,r:p['restored'].update(restored_bytes_match=False),
            'late':lambda p,r:r['cells']['lustre-0.1/fsx_lustre-0.1.req.csv'].update(late_share=.051),
            'rpc':lambda p,r:r['cells']['non-lustre/efs_host_tls-1.req.csv']['rpc']['window_minus_phase'].update(GETATTR=1),
            'missing rpc':lambda p,r:r['cells']['non-lustre/efs_host_tls-1.req.csv'].pop('rpc'),
            'idle traffic':lambda p,r:next(iter(r['idle_controls'][0]['deltas'].values())).update(GETATTR=1),
            'short idle':lambda p,r:r['idle_controls'][0].update(elapsed_seconds=359),
            'missing reference':lambda p,r:r['cells'].pop('lustre-1/ebs-1.req.csv'),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name):
                p=copy.deepcopy(self.protocol);r=copy.deepcopy(self.report);mutate(p,r)
                self.assertEqual(a.candidate_acceptance(self.root,p,r)['status'],'NOT_READY')

    def test_candidate_rejects_schedule_overlap(self):
        path=self.root/'lustre-1/diagnostic-run.json';original=path.read_bytes()
        try:
            job=json.loads(original);job['cells'][0]['started_monotonic_ns']=0;path.write_text(json.dumps(job))
            self.assertEqual(a.candidate_acceptance(self.root,self.protocol,self.report)['status'],'NOT_READY')
        finally:path.write_bytes(original)


if __name__=='__main__':unittest.main()
