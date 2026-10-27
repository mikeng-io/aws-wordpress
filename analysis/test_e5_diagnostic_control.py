"""Offline tests of config restoration, restricted metadata and mount identity."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_control',ROOT/'infra/lib/stacks/bench/e5-diagnostic-host.py')
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
spec = importlib.util.spec_from_file_location('diagnostic',ROOT/'infra/lib/stacks/bench/e5-diagnostic.py')
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
spec = importlib.util.spec_from_file_location('isolation',ROOT/'infra/lib/stacks/bench/e5-isolation-validation.py')
i = importlib.util.module_from_spec(spec); spec.loader.exec_module(i)


class ControlTests(unittest.TestCase):
    def test_quiet_profile_controls_both_probes_and_preserves_lifecycle(self):
        original=b'[mount]\noptimize_readahead=true\n[mount-watchdog]\nenabled=true\nstunnel_health_check_enabled=true\n'
        with tempfile.TemporaryDirectory() as name:
            config=Path(name)/'config';config.write_bytes(original);config.chmod(0o640)
            with patch.object(h,'CONFIG',config):
                h.apply_profile(original,'quiet')
                c=h.configparser.ConfigParser();c.read(config)
                self.assertFalse(c.getboolean('mount','optimize_readahead'))
                self.assertFalse(c.getboolean('mount-watchdog','stunnel_health_check_enabled'))
                self.assertTrue(c.getboolean('mount-watchdog','enabled'))
                self.assertEqual(config.stat().st_mode & 0o777,0o640)
                h.apply_profile(original,'restore')
                self.assertEqual(config.read_bytes(),original)
                with self.assertRaises(ValueError):h.apply_profile(original.replace(b'enabled=true',b'enabled=false'),'quiet')
                self.assertEqual(config.read_bytes(),original)

    def test_candidate_schedule_pairs_each_lustre_interval_with_fresh_ebs(self):
        jobs=i.phases()
        self.assertEqual(len(jobs),4)
        self.assertEqual(len(jobs[0]['cells']),15)
        self.assertNotIn('fsx_lustre',{c['tier'] for c in jobs[0]['cells']})
        self.assertEqual(sum(len(j['cells']) for j in jobs),21)
        for job,delta in zip(jobs[1:],('0.1','1','10')):
            self.assertEqual({c['tier'] for c in job['cells']},{'fsx_lustre','ebs'})
            self.assertEqual({c['delta'] for c in job['cells']},{delta})
            reference=next(c for c in job['cells'] if c['tier']=='ebs')
            self.assertIn('diag-lustre-control',reference['directory'])

    def test_candidate_restores_even_when_trace_stop_fails(self):
        baseline=dict(config={'mount':{'optimize_readahead':'true'},'mount-watchdog':{
            'enabled':'true','poll_interval_sec':'1','stunnel_health_check_enabled':'true'}},
            read_ahead_kb={'root':'15360'},watchdog_pid=42)
        quiet=json.loads(json.dumps(baseline))
        quiet['config']['mount']['optimize_readahead']='false'
        quiet['config']['mount-watchdog']['stunnel_health_check_enabled']='false'
        restored=dict(baseline,restored_bytes_match=True)
        calls=[]
        def host(verb):
            calls.append(verb)
            if verb=='metadata':return baseline
            if verb=='quiet':return quiet
            if verb=='trace-stop':raise RuntimeError('trace shutdown failure')
            if verb=='restore':return restored
            raise AssertionError(verb)
        class Runner:
            def run(self,*args):raise AssertionError('must not run after idle failure')
        with tempfile.TemporaryDirectory() as name,patch.object(i,'idle',side_effect=RuntimeError('idle failed')):
            with self.assertRaises(RuntimeError):i.run(host,Runner(),Path(name),201)
            self.assertEqual(calls[-1],'restore')
            receipt=json.loads((Path(name)/'protocol.json').read_text())
            self.assertTrue(receipt['restored']['restored_bytes_match'])

    def test_candidate_runs_batches_in_order_then_restores(self):
        baseline=dict(config={'mount':{'optimize_readahead':'true'},'mount-watchdog':{
            'enabled':'true','poll_interval_sec':'1','stunnel_health_check_enabled':'true'}},
            read_ahead_kb={'root':'15360'},watchdog_pid=42)
        quiet=json.loads(json.dumps(baseline));quiet['config']['mount']['optimize_readahead']='false'
        quiet['config']['mount-watchdog']['stunnel_health_check_enabled']='false'
        state={'quiet':False};jobs=[]
        def host(verb):
            if verb=='metadata':return quiet if state['quiet'] else baseline
            if verb=='quiet':state['quiet']=True;return quiet
            if verb=='restore':state['quiet']=False;return dict(baseline,restored_bytes_match=True)
            if verb=='trace-stop':return {}
            raise AssertionError(verb)
        test=self
        class Runner:
            def run(self,cells,output,*args):
                test.assertTrue(state['quiet']);jobs.append((output.name,len(cells)));return 0
        samples=[dict(monotonic_ns=n,roots={'root':{op:0 for op in ('GETATTR','LOOKUP','ACCESS')}}) for n in (0,360_000_000_000)]
        with tempfile.TemporaryDirectory() as name,patch.object(i,'idle',return_value=samples),patch.object(i.diagnostic,'CTL',Path(name)):
            receipt=i.run(host,Runner(),Path(name),201)
            self.assertEqual(jobs,[('non-lustre',15),('lustre-0.1',2),('lustre-1',2),('lustre-10',2)])
            self.assertFalse(state['quiet'])
            self.assertTrue(receipt['restored']['restored_bytes_match'])
    def test_config_change_is_restored_on_exit_and_metadata_is_whitelisted(self):
        original = b'[mount]\noptimize_readahead = true\nprivate_value = NEVER_EXPORT\n[mount-watchdog]\nenabled = true\npoll_interval_sec = 1\n'
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); config = root/'config'; config.write_bytes(original)
            (root/'diag-test.request').write_text('{"verb":"off"}')
            seen = []
            def sleep(seconds):
                if seconds == .05:
                    raise SystemExit()
            def metadata():
                seen.append(config.read_text())
                return {'config':{'mount':{'optimize_readahead':'false'}}}
            with patch.object(h,'CONFIG',config), patch.object(h,'CTL',root), \
                 patch.object(h,'config_metadata',metadata), patch.object(h.time,'sleep',sleep):
                with self.assertRaises(SystemExit): h.serve()
            self.assertIn('optimize_readahead = false',seen[0])
            self.assertEqual(config.read_bytes(),original)
            response=(root/'diag-test.response').read_text()
            self.assertTrue(json.loads(response)['ok'])
            self.assertNotIn('NEVER_EXPORT',response)

    def test_unknown_command_fails_and_restores_config(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); config=root/'config'; config.write_text('original')
            (root/'diag-test.request').write_text('{"verb":"shell"}')
            with patch.object(h,'CONFIG',config), patch.object(h,'CTL',root), \
                 patch.object(h.time,'sleep',side_effect=SystemExit):
                with self.assertRaises(SystemExit): h.serve()
            self.assertFalse(json.loads((root/'diag-test.response').read_text())['ok'])
            self.assertEqual(config.read_text(),'original')

    def test_snapshots_require_all_five_exact_mount_roots(self):
        sections=[f'device fake mounted on {h.ROOT}{f} with fstype nfs4\n GETATTR: 1\n LOOKUP: 0\n ACCESS: 0\n' for f in h.FAMILIES]
        with patch.object(Path,'read_text',return_value=''.join(sections)):
            self.assertEqual(len(h.rpc_snapshot()['roots']),5)
        for text in (''.join(sections[:-1]),''.join(sections+sections[:1])):
            with patch.object(Path,'read_text',return_value=text):
                with self.assertRaises(ValueError):h.rpc_snapshot()

    def test_cell_plan_keeps_target_subtrees_fresh_and_nfs_mount_explicit(self):
        cells=[d.cell(t,delta,'diag-round-2') for t in d.TIERS for delta in d.DELTAS]
        self.assertEqual(len(cells),18)
        self.assertEqual(len({c['directory'] for c in cells}),18)
        for c in cells:
            self.assertIn('diag-round-2',c['directory'])
            self.assertEqual('nfs_mount' in c,c['tier'] not in ('ebs','fsx_lustre'))
        self.assertNotEqual(d.cell('fsx_lustre','0.1','diag-round-1')['directory'],
                            d.cell('fsx_lustre','0.1','diag-round-4')['directory'])


if __name__ == '__main__': unittest.main()
