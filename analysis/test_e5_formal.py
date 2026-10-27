"""Full-window synthetic protocol and mutation controls; never launches AWS."""
import copy
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import e5_formal_stats as g
import e5_selftest as fixture

REPO=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('formal',REPO/'infra/lib/stacks/bench/e5-formal.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)


def dump(path,value):path.write_text(json.dumps(value))


def build(run):
    rep=run/'rep-1';root=rep/'formal';root.mkdir(parents=True)
    fixture.write_rep(root,fixture.base_world())
    for t in g.legacy.TIERS:
        td=root/'ec2'/t
        (td/'conformance.csv').write_text(''.join(f'{name},PASS\n' for name in ('rename','in_place_write','append','truncate','fsync','hardlink','symlink','dir_rename','flock_excludes','root_not_squashed','mtime_advances'))+'TOTAL_FAILURES,0\nTOTAL_ERRORS,0\n')
        for c,op in [('A2','enoent'),('A4','enoent'),('A6','open_read'),('A7','open_read')]:
            p=td/f'{c}.csv';p.write_text(p.read_text().replace(',stat,',f',{op},'))
        if t in g.legacy.NFS_TIERS:
            (td/'A8w.csv').write_text(''.join(f'A8w,stat,{k},1000\n' for k in range(1000)))
    (root/'ec2/mount-facts.csv').write_text(''.join(f'tier_order,{t},{i+1}\na_wait,{t},{361_000_000_000+i*150_000_000_000},{436_000_000_000+i*150_000_000_000}\na_wait,{t},{436_000_000_000+i*150_000_000_000},{511_000_000_000+i*150_000_000_000}\n' for i,t in enumerate(g.legacy.TIERS)))
    baseline=dict(config={'mount':{'optimize_readahead':'true'},'mount-watchdog':{'enabled':'true','poll_interval_sec':'1','stunnel_health_check_enabled':'true'}},read_ahead_kb={k:'15360' for k in ('default','forced','ss-0.1','ss-1','ss-10')},watchdog_pid=42)
    quiet=copy.deepcopy(baseline);quiet['config']['mount']['optimize_readahead']='false';quiet['config']['mount-watchdog']['stunnel_health_check_enabled']='false'
    p=dict(method=g.METHOD,study_replication=True,seed_age_at_start_s=200,apparatus_sha256={k:'a'*64 for k in g.ARTIFACTS},baseline=baseline,quiet=quiet,after_workload=quiet,restored=dict(baseline,restored_bytes_match=True),bindings=[],phases=[],idle_snapshots=[dict(monotonic_ns=n,roots={f'/mnt/e5/efs_host_tls/{family}':dict.fromkeys(g.OPS,0) for family in baseline['read_ahead_kb']}) for n in (0,360_000_000_000)])
    clock=361_000_000_000;p['phases'].append(dict(kind='cohort-a',start_ns=clock,end_ns=clock+1500_000_000_000));clock+=1501_000_000_000
    for plan in f.plans():
        folder=plan['folder'];directory=root/'batches'/folder;directory.mkdir(parents=True)
        job=dict(schema='e5-formal-batch-v1',study_replication=True,mode='concurrent',warmup=300,measure=600,plan=plan['cells'],cells=[])
        for c in plan['cells']:
            t,d=c['tier'],c['delta'];stem=directory/f'{t}-{d}';nfs=t in g.legacy.NFS_TIERS;rpc='0:0:0' if nfs else '-'
            delta=round(float(d)*1e9);nw=round(300/float(d));nm=round(600/float(d));mount=c.get('nfs_mount','-')
            with Path(str(stem)+'.req.csv').open('w') as req,Path(str(stem)+'.diagnostics.csv').open('w') as diag:
                req.write(f'# cohort=B-{d} delta_ns={delta} warm_requests={nw} measured_requests={nm} raw_every=1 bins_per_decade=20 bin0_ns=100 method=rpc-phases-v2 rpc_mount={mount}\n')
                req.write('k,phase,lateness_ns,stat_sum_ns,enoent_sum_ns,stat_bins,enoent_bins,stat_rpc,enoent_rpc,counter_ns\n')
                diag.write('k,phase,start_ns,end_ns,thread_cpu_ns,rpc_start,rpc_end\n')
                for k in range(nw+nm):
                    phase='w' if k<nw else 'm';start=clock+1_000_000+k*delta
                    req.write(f'{k},{phase},0,1000000,1000000,20:1000,20:1000,{rpc},{rpc},10\n')
                    diag.write(f'{k},{phase},{start},{start+3_000_000},2500000,{rpc},{rpc}\n')
            if nfs:
                for when in ('warm','end'):
                    Path(str(stem)+'.mountstats.'+when).write_text(fixture.mountstats({},'/other')+fixture.mountstats({},mount))
            command=['agebench','serve',c['directory'],d,'300','600',f'B-{d}',f'/tmp/e5-formal/batches/{folder}/{t}-{d}',{'0.1':'100','1':'10','10':'1'}[d]]
            if nfs:command.append(mount)
            job['cells'].append(dict(cell=f'{t}-{d}',command=command,exit_code=0,started_monotonic_ns=clock+1,reaped_monotonic_ns=clock+900_000_000_000))
        dump(directory/'diagnostic-run.json',job)
        p['bindings']+=f.export_batch(plan,directory,root)
        p['phases'].append(dict(kind='batch',folder=folder,start_ns=clock,end_ns=clock+901_000_000_000));clock+=902_000_000_000
    p['phases'].append(dict(kind='expiry-probes',start_ns=clock,end_ns=clock+80_000_000_000))
    dump(root/'protocol.json',p);dump(root/'formal-complete.json',dict(method=g.METHOD,study_replication=True,completed=True));(root/'trace-quiet.txt').write_text('')
    dump(rep/'meta.json',dict(experiment='E5-formal-isolation',study_replication=True,task_failed=False,protocol_method=g.METHOD,source_commit='b'*40,image_digest='sha256:'+'c'*64,deployment_id='d'*64,run_id=run.name))
    return root


class FormalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)/'base';build(cls.base)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmpcase=tempfile.TemporaryDirectory();self.run=Path(self.tmpcase.name)/'run';shutil.copytree(self.base,self.run)
        self.root=self.run/'rep-1/formal';self.meta=json.loads((self.run/'rep-1/meta.json').read_text());self.meta['run_id']='run';dump(self.run/'rep-1/meta.json',self.meta)
    def tearDown(self):self.tmpcase.cleanup()
    def report(self):return g.analyse([self.run])['replications']['run/rep-1']
    def protocol_mutation(self,fn):
        p=json.loads((self.root/'protocol.json').read_text());fn(p);dump(self.root/'protocol.json',p)
    def test_complete_formal_fixture_passes_but_n1_cannot_issue_aggregate_verdict(self):
        r=g.analyse([self.run]);self.assertEqual(self.report()['protocol']['status'],'ELIGIBLE');self.assertEqual(self.report()['full_method_validation'],'PASS')
        self.assertTrue(all(v['status']=='NOT EVALUABLE' for v in r['predictions'].values()))
        self.assertEqual(self.report()['grades']['7']['grade'],'SUPPORTED')
    def test_profile_idle_restore_and_phase_negative_controls(self):
        original=(self.root/'protocol.json').read_bytes()
        mutations=[lambda p:p['quiet']['config']['mount-watchdog'].update(enabled='false'),lambda p:p['restored'].update(restored_bytes_match=False),lambda p:p['idle_snapshots'][-1].update(monotonic_ns=359_000_000_000),lambda p:p['idle_snapshots'][-1]['roots'].pop('/mnt/e5/efs_host_tls/default'),lambda p:p['phases'][2].update(start_ns=p['phases'][1]['start_ns']),lambda p:p['apparatus_sha256'].pop('agebench')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                (self.root/'protocol.json').write_bytes(original);self.protocol_mutation(mutate);self.assertEqual(self.report()['protocol']['status'],'ERROR')
    def test_short_windows_missing_reference_and_wrong_command_are_rejected(self):
        path=self.root/'batches/lustre-1/diagnostic-run.json';original=path.read_bytes()
        for change in (lambda j:j.update(measure=180),lambda j:j['cells'].pop(),lambda j:j['cells'][1]['command'].__setitem__(2,'/bench/ebs/ss-1')):
            path.write_bytes(original);job=json.loads(original);change(job);dump(path,job);self.assertEqual(self.report()['protocol']['status'],'ERROR')
    def test_short_a_wait_and_wrong_a_operation_are_rejected(self):
        facts=self.root/'ec2/mount-facts.csv';original=facts.read_bytes();facts.write_text(facts.read_text().replace(',361000000000,436000000000',',361000000000,435000000000'));self.assertEqual(self.report()['protocol']['status'],'ERROR');facts.write_bytes(original)
        p=self.root/'ec2/efs_host_plain/A2.csv';p.write_text(p.read_text().replace(',enoent,',',stat,'));self.assertEqual(self.report()['protocol']['status'],'ERROR')
    def test_conformance_and_missing_probe_are_rejected(self):
        p=self.root/'ec2/ebs/conformance.csv';original=p.read_bytes();p.write_text(p.read_text().replace('rename,PASS','rename,FAIL'));self.assertEqual(self.report()['protocol']['status'],'ERROR');p.write_bytes(original)
        (self.root/'ec2/efs_host_plain/D-1.csv').unlink();self.assertEqual(self.report()['protocol']['status'],'ERROR')
    def test_trace_root_call_is_rejected(self):
        (self.root/'trace-quiet.txt').write_text('statx(AT_FDCWD, "/mnt/e5/efs_host_tls/ss-1", 0) = 0\n');self.assertEqual(self.report()['protocol']['status'],'ERROR')
    def noise(self,folder):
        stem=self.root/'batches'/folder/'ebs-0.1';p=Path(str(stem)+'.req.csv')
        p.write_text(p.read_text().replace(',1000000,1000000,20:1000,',',50500000,1000000,20:500|60:500,'))
        diag=Path(str(stem)+'.diagnostics.csv');rows=list(csv.DictReader(diag.read_text().splitlines()))
        with diag.open('w') as file:
            writer=csv.DictWriter(file,fieldnames=rows[0].keys());writer.writeheader()
            for row in rows:row['end_ns']=str(int(row['start_ns'])+60_000_000);row['thread_cpu_ns']='55000000';writer.writerow(row)
        f.export_batch(next(p for p in f.plans() if p['folder']==folder),stem.parent,self.root)
    def test_p7_uses_same_time_control_not_non_lustre_ebs(self):
        self.noise('non-lustre');self.assertEqual(self.report()['grades']['7']['grade'],'SUPPORTED')
        self.noise('lustre-0.1');self.assertEqual(self.report()['protocol']['status'],'ELIGIBLE');self.assertEqual(self.report()['grades']['7']['grade'],'ERROR')
    def test_rpc_residual_and_lateness_keep_original_cell_gates(self):
        raw=self.root/'batches/non-lustre/efs_host_tls-0.1.mountstats.end';raw.write_text(raw.read_text().replace('GETATTR: 0','GETATTR: 1'))
        f.export_batch(f.plans()[0],raw.parent,self.root);self.assertEqual(self.report()['b']['efs_host_tls']['0.1']['status'],'ERROR');self.assertEqual(self.report()['full_method_validation'],'NOT_READY')
    def test_exact_five_percent_lateness_boundary_is_preserved(self):
        raw=self.root/'batches/lustre-0.1/fsx_lustre-0.1.req.csv';original=raw.read_text()
        for late,expected in ((300,'OK'),(301,'ERROR')):
            raw.write_text(original.replace(',m,0,',',m,60000000,',late))
            f.export_batch(f.plans()[1],raw.parent,self.root)
            self.assertEqual(self.report()['b']['fsx_lustre']['0.1']['status'],expected)
    def test_duplicate_deployments_and_apparatus_drift_cannot_be_pooled(self):
        other=Path(self.tmpcase.name)/'other';shutil.copytree(self.run,other);meta=copy.deepcopy(self.meta);meta['run_id']='other';dump(other/'rep-1/meta.json',meta)
        with self.assertRaisesRegex(ValueError,'duplicate deployment'):g.analyse([self.run,other])
        meta['deployment_id']='e'*64;meta['image_digest']='sha256:'+'f'*64;dump(other/'rep-1/meta.json',meta)
        with self.assertRaisesRegex(ValueError,'drift'):g.analyse([self.run,other])
    def test_three_independent_identical_apparatus_can_aggregate(self):
        runs=[self.run]
        for i in (1,2):
            other=Path(self.tmpcase.name)/f'other{i}';shutil.copytree(self.run,other);meta=copy.deepcopy(self.meta);meta.update(run_id=other.name,deployment_id=str(i)*64);dump(other/'rep-1/meta.json',meta);runs.append(other)
        self.assertEqual(g.analyse(runs)['predictions']['7']['status'],'SUPPORTED')
    def test_legacy_grader_and_mixed_method_pooling_are_refused(self):
        with self.assertRaisesRegex(ValueError,'e5_formal_stats'):g.legacy.analyse(self.run)
        self.meta['protocol_method']='isolation-candidate-v1';dump(self.run/'rep-1/meta.json',self.meta)
        with self.assertRaisesRegex(ValueError,'only isolation-formal'):g.analyse([self.run])
    def test_coordinator_success_path_exports_all_batches_and_restores(self):
        p=json.loads((self.root/'protocol.json').read_text());calls=[]
        out_run=Path(self.tmpcase.name)/'coordinator';out=out_run/'rep-1/formal';out.mkdir(parents=True)
        ctl=Path(self.tmpcase.name)/'ctl';ctl.mkdir()
        source=self.root
        class Runner:
            def run(self,cells,dest,mode,warm,measure,exe,**kwargs):
                self_outer.assertEqual((mode,warm,measure,exe,kwargs),('concurrent',300,600,'agebench',{'study_replication':True}))
                calls.append(dest.name);shutil.copytree(source/'batches'/dest.name,dest);return 0
        class Idle:
            def idle(self,host):
                (ctl/'trace-quiet.txt').write_text('')
                return p['idle_snapshots']
            def require_quiet(self,b,q):
                self_outer.assertEqual(q['read_ahead_kb'],b['read_ahead_kb'])
        self_outer=self
        def host(verb):
            calls.append(verb)
            if verb=='metadata':return p['quiet'] if 'D' in calls else p['baseline']
            return p.get({'quiet':'quiet','restore':'restored'}.get(verb,''))
        def phase(kind,dest):
            calls.append(kind)
            if kind=='A':shutil.copytree(source/'ec2',dest)
        times=[n for phase in p['phases'] for n in (phase['start_ns'],phase['end_ns'])]
        with patch.object(f,'apparatus_hashes',return_value=p['apparatus_sha256']),patch.object(f.time,'monotonic_ns',side_effect=times),patch.dict('os.environ',{'CACHE_CTL_DIR':str(ctl)}):
            f.run(host,Runner(),Idle(),out,phase,200)
        shutil.copyfile(source/'ec2/mount-facts.csv',out/'ec2/mount-facts.csv')
        meta=copy.deepcopy(self.meta);meta['run_id']=out_run.name;dump(out.parent/'meta.json',meta)
        self.assertEqual([x for x in calls if x in ('A','D',*g.BATCHES)],['A',*g.BATCHES,'D'])
        self.assertEqual(g.analyse([out_run])['replications']['coordinator/rep-1']['full_method_validation'],'PASS')
        self.assertEqual(calls[-1],'restore')

    def test_runner_restores_even_when_a_or_trace_shutdown_fails(self):
        p=json.loads((self.root/'protocol.json').read_text());calls=[]
        class Idle:
            def idle(self,host):return p['idle_snapshots']
            def require_quiet(self,b,q):pass
        def host(verb):
            calls.append(verb)
            if verb=='metadata':return p['baseline']
            if verb=='quiet':return p['quiet']
            if verb=='restore':return p['restored']
            if verb=='trace-stop':raise RuntimeError('trace stop failed')
        def phase(*args):raise RuntimeError('A failed')
        out=Path(self.tmpcase.name)/'failed';out.mkdir()
        with patch.object(f,'apparatus_hashes',return_value=p['apparatus_sha256']),patch.dict('os.environ',{'CACHE_CTL_DIR':str(out)}):
            with self.assertRaises(RuntimeError):f.run(host,None,Idle(),out,phase,200)
        self.assertIn('restore',calls);self.assertTrue(json.loads((out/'protocol.json').read_text())['restored']['restored_bytes_match']);self.assertFalse((out/'formal-complete.json').exists())


if __name__=='__main__':unittest.main()
