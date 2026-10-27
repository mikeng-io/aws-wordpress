"""Strict separation and malformed-input checks for diagnostic-only analysis."""
import json
from pathlib import Path
import tempfile
import unittest

import e5_diagnostic_stats as a


class DiagnosticAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.cell=self.root/'cell';self.cell.mkdir()
        self.req=self.cell/'B-1.req.csv'
        self.text=('# method=rpc-phases-v2 warm_requests=0 measured_requests=2 delta_ns=100 rpc_mount=/mock\n'
          'k,phase,lateness_ns,stat_sum_ns,enoent_sum_ns,stat_bins,enoent_bins,stat_rpc,enoent_rpc,counter_ns\n'
          '0,m,0,10,10,0:1000,0:1000,1:0:0,1:0:0,1\n'
          '1,m,0,10,10,0:1000,0:1000,1:0:0,1:0:0,1\n')
        self.req.write_text(self.text)
        self.diag=self.cell/'B-1.diagnostics.csv'
        self.dt=('k,phase,start_ns,end_ns,thread_cpu_ns,rpc_start,rpc_end\n'
                 '0,m,0,100,40,0:0:0,2:0:0\n1,m,100,200,40,5:0:0,7:0:0\n')
        self.diag.write_text(self.dt)
        for when,n in [('warm',0),('end',7)]:
            (self.cell/f'B-1.mountstats.{when}').write_text(
              f'device fake mounted on /mock with fstype nfs4\n GETATTR: {n}\n LOOKUP: 0\n ACCESS: 0\n')

    def test_phase_window_gap_and_cpu_are_distinct(self):
        x=a.analyze_cell(self.req)
        self.assertEqual(x['rpc']['phase']['GETATTR'],4)
        self.assertEqual(x['rpc']['window_minus_phase']['GETATTR'],3)
        self.assertEqual(x['rpc']['observed_between_measured_requests']['GETATTR'],3)
        self.assertEqual(x['service_thread_cpu_share'],.4)

    def test_incomplete_requests_fail(self):
        self.req.write_text(self.text.rsplit('1,m,',1)[0])
        with self.assertRaises(ValueError):a.analyze_cell(self.req)

    def test_impossible_cpu_clock_fails(self):
        self.diag.write_text(self.dt.replace('0,m,0,100,40','0,m,0,100,101'))
        with self.assertRaises(ValueError):a.analyze_cell(self.req)

    def test_inter_request_reset_fails(self):
        self.diag.write_text(self.dt.replace('5:0:0,7:0:0','1:0:0,3:0:0'))
        with self.assertRaises(ValueError):a.analyze_cell(self.req)

    def test_independent_window_must_cover_both_phases_and_gaps(self):
        end=self.cell/'B-1.mountstats.end'
        original=end.read_text()
        for value in (3,5):
            end.write_text(original.replace('GETATTR: 7',f'GETATTR: {value}'))
            with self.subTest(value=value),self.assertRaises(ValueError):a.analyze_cell(self.req)

    def test_missing_planned_cell_is_an_error(self):
        (self.root/'protocol.json').write_text(json.dumps(dict(study_replication=False,
          phases=[dict(kind='tls-active',mode='on')])))
        (self.root/'diagnostic-complete.json').write_text('{"completed":true,"study_replication":false}')
        folder=self.root/'tls-on';folder.mkdir()
        (folder/'diagnostic-run.json').write_text(json.dumps(dict(cells=[dict(cell='missing',exit_code=0)])))
        x=a.analyze(self.root)
        self.assertFalse(x['all_inputs_valid'])
        self.assertEqual(x['cells']['tls-on/missing.req.csv']['status'],'ERROR')

    def test_partial_protocol_is_reported_without_success_claim(self):
        (self.root/'protocol.json').write_text(json.dumps(dict(study_replication=False,
          phases=[dict(kind='tls-idle',mode='on',snapshots=[])])))
        x=a.analyze(self.root)
        self.assertFalse(x['completed'])
        self.assertEqual(x['idle_controls'][0]['status'],'INCOMPLETE')
        (self.root/'protocol.json').write_text('broken')
        (self.root/'diagnostic-complete.json').write_text('{"completed":true,"study_replication":false}')
        x=a.analyze(self.root)
        self.assertFalse(x['completed'])
        self.assertIsNotNone(x['protocol_error'])


if __name__=='__main__':unittest.main()
