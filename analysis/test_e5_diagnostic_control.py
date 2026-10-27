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


class ControlTests(unittest.TestCase):
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
