"""Linux integration tests for opt-in agebench telemetry; no NFS/AWS required.

Run inside the bench image with /repo mounted read-only. Compiles current source,
seeds temporary local files, then exercises real serve loops and output errors.
"""
import csv
import importlib.util
import os
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('gcc'),
                     'requires Linux and gcc; use make e5-instrument-selftest')
class InstrumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        repo = Path(__file__).resolve().parents[1]
        cls.exe = cls.root / 'agebench'
        subprocess.run(['gcc', '-O2', '-Wall', '-Werror', '-o', str(cls.exe),
                        str(repo / 'infra/lib/stacks/bench/agebench.c'), '-lm'], check=True)
        # Synthetic proc reader: exercises RPC wiring without a mounted NFS
        # server. Each read adds one op, making gap attribution observable.
        wrapper = cls.root / 'rpc-fixture.c'
        wrapper.write_text('''#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
static FILE *fixture_open(const char *path, const char *mode) {
    static long count;
    static char data[512];
    if (strcmp(path, "/proc/self/mountstats")) return fopen(path, mode);
    snprintf(data, sizeof data, "device fake mounted on /mock with fstype nfs4\\n"
             " per-op statistics\\n GETATTR: %ld\\n LOOKUP: 0\\n ACCESS: 0\\n", count++);
    return fmemopen(data, strlen(data), "r");
}
#define fopen fixture_open
#define main agebench_main
#include "''' + str(repo / 'infra/lib/stacks/bench/agebench.c') + '''"
#undef main
int main(int argc, char **argv) { return agebench_main(argc, argv); }
''')
        cls.rpc_exe = cls.root / 'agebench-rpc-fixture'
        subprocess.run(['gcc', '-O2', '-Wall', '-Werror', '-o', str(cls.rpc_exe),
                        str(wrapper), '-lm'], check=True)
        spec = importlib.util.spec_from_file_location('diagnostic_serve', repo /
                'experiments/E5-attribute-cache/scripts/diagnostic-serve.py')
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)
        cls.tree = cls.root / 'tree'
        subprocess.run(['python3', str(repo / 'infra/lib/stacks/bench/e5-seed.py'),
                        str(cls.tree)], check=True, stdout=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def serve(self, name, flag=None):
        prefix = self.root / name
        env = dict(os.environ)
        env.pop('E5_DIAGNOSTICS', None)
        if flag is not None:
            env['E5_DIAGNOSTICS'] = flag
        result = subprocess.run([str(self.exe), 'serve', str(self.tree), '.02', '.04', '.1',
                                 'B-test', str(prefix), '1'], env=env, capture_output=True)
        return prefix, result

    def test_telemetry_covers_real_work_and_preserves_request_schema(self):
        prefix, result = self.serve('enabled', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        with Path(f'{prefix}.diagnostics.csv').open() as f:
            rows = list(csv.DictReader(f))
        with Path(f'{prefix}.req.csv').open() as f:
            self.assertIn('method=rpc-phases-v2', next(f))
            requests = list(csv.DictReader(f))
        self.assertEqual(len(rows), 7)
        self.assertEqual([r['phase'] for r in rows], ['w']*2 + ['m']*5)
        for r, req in zip(rows, requests):
            self.assertEqual(r['k'], req['k'])
            wall = int(r['end_ns']) - int(r['start_ns'])
            self.assertGreaterEqual(wall, int(req['stat_sum_ns']) + int(req['enoent_sum_ns']))
            self.assertGreater(int(r['thread_cpu_ns']), 0)
            self.assertLessEqual(int(r['thread_cpu_ns']), wall)
            self.assertEqual((r['rpc_start'], r['rpc_end']), ('-', '-'))

    def test_default_has_no_diagnostic_output(self):
        prefix, result = self.serve('disabled')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(f'{prefix}.diagnostics.csv').exists())

    def test_invalid_opt_in_fails(self):
        _, result = self.serve('invalid', 'yes')
        self.assertEqual(result.returncode, 64)

    def test_diagnostic_write_error_fails_run(self):
        (self.root / 'full.diagnostics.csv').symlink_to('/dev/full')
        _, result = self.serve('full', '1')
        self.assertNotEqual(result.returncode, 0)

    def test_rpc_endpoints_use_existing_phase_reads_and_expose_gaps(self):
        prefix = self.root / 'rpc'
        result = subprocess.run([str(self.rpc_exe), 'serve', str(self.tree), '.02', '0', '.06',
                                 'B-test', str(prefix), '1', '/mock'],
                                env=dict(os.environ, E5_DIAGNOSTICS='1'), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with Path(f'{prefix}.diagnostics.csv').open() as f:
            rows = list(csv.DictReader(f))
        with Path(f'{prefix}.req.csv').open() as f:
            next(f)
            requests = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        for r, req in zip(rows, requests):
            start = int(r['rpc_start'].split(':')[0])
            end = int(r['rpc_end'].split(':')[0])
            self.assertEqual(end-start, 2)  # exactly r0,r1,r2, no extra reads
            self.assertEqual((req['stat_rpc'], req['enoent_rpc']), ('1:0:0', '1:0:0'))
        for a, b in zip(rows, rows[1:]):
            self.assertEqual(int(b['rpc_start'].split(':')[0])-int(a['rpc_end'].split(':')[0]), 1)

    def test_both_runner_modes_execute_real_instrument_and_record_failures(self):
        plan = [dict(tier=tier, directory=str(self.tree), delta='0.1') for tier in ('a','b')]
        for mode in ('isolated', 'concurrent'):
            out = self.root / mode
            self.assertEqual(self.runner.run(plan, out, mode, 0, .2, str(self.exe)), 0)
            for tier in ('a','b'):
                self.assertTrue((out / f'{tier}-0.1.diagnostics.csv').is_file())
        self.assertEqual(self.runner.run(plan, self.root / 'failed', 'concurrent', 0, .2, '/bin/false'), 1)

    def test_runner_refuses_existing_output_and_duplicate_cells(self):
        plan = [dict(tier='a', directory=str(self.tree), delta='0.1')]
        with self.assertRaises(FileExistsError):
            self.runner.run(plan, self.root, 'isolated', 0, .2, str(self.exe))
        with self.assertRaises(ValueError):
            self.runner.run(plan*2, self.root / 'duplicate', 'concurrent', 0, .2, str(self.exe))


if __name__ == '__main__':
    unittest.main()
