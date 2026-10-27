#!/usr/bin/env python3
"""Run explicit existing cells isolated or concurrently; never mounts/deploys.

Plan is a JSON list of {tier, directory, delta, nfs_mount?}. The same plan must be
used for each arm; callers prepare fresh mounts/trees and counterbalance arm order.
Output is diagnostic only and must not be passed off as a study replication.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time


def run(plan, output, mode, warmup, measure, executable):
    if (mode not in ('isolated', 'concurrent') or not plan or
            not math.isfinite(warmup) or not math.isfinite(measure) or warmup < 0 or measure <= 0):
        raise ValueError('invalid diagnostic plan/timing/mode')
    keys = []
    for c in plan:
        if c['delta'] not in ('0.1', '1', '10') or not c['tier'].replace('_', '').isalnum():
            raise ValueError('invalid cell identity')
        if not Path(c['directory']).is_dir():
            raise ValueError('missing cell directory')
        key = f"{c['tier']}-{c['delta']}"
        if key in keys:
            raise ValueError('duplicate cell')
        keys.append(key)
    output.mkdir(parents=True, exist_ok=False)
    children, receipt = [], []
    env = dict(os.environ, E5_DIAGNOSTICS='1')
    def reap(child):
        process, log, record = child
        remaining = (record['started_monotonic_ns'] / 1e9 + warmup + measure + 60) - time.monotonic()
        record['exit_code'] = process.wait(timeout=max(.001, remaining))
        record['reaped_monotonic_ns'] = time.monotonic_ns()
        log.close()
    try:
        for c, key in zip(plan, keys):
            prefix = output / key
            # Same raw sampling cadence as the pilot, per interval.
            raw_every = {'0.1':'100', '1':'10', '10':'1'}[c['delta']]
            command = [executable, 'serve', c['directory'], c['delta'], str(warmup),
                       str(measure), f"B-{c['delta']}", str(prefix), raw_every]
            if c.get('nfs_mount'):
                command.append(c['nfs_mount'])
            log = (output / f'{key}.stderr').open('w')
            record = dict(cell=key, command=command, started_monotonic_ns=time.monotonic_ns())
            receipt.append(record)
            try:
                process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=log)
            except BaseException:
                log.close()
                raise
            child = (process, log, record)
            children.append(child)
            if mode == 'isolated':
                reap(child)
        if mode == 'concurrent':
            for child in children:
                reap(child)
    finally:
        for process, log, record in children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            record['exit_code'] = process.returncode
            log.close()
        (output / 'diagnostic-run.json').write_text(json.dumps(dict(
            schema='e5-diagnostic-serve-v1', mode=mode, warmup=warmup, measure=measure,
            plan=plan, cells=receipt, study_replication=False), indent=2)+'\n')
    return int(any(c['exit_code'] != 0 for c in receipt))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--mode', choices=('isolated', 'concurrent'), required=True)
    p.add_argument('--warmup', type=float, default=300)
    p.add_argument('--measure', type=float, default=600)
    p.add_argument('--executable', default='agebench')
    a = p.parse_args()
    raise SystemExit(run(json.loads(a.plan.read_text()), a.output, a.mode,
                         a.warmup, a.measure, a.executable))
