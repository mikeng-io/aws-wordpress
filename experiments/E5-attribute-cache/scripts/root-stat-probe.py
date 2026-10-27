#!/usr/bin/env python3
"""Local NFS mechanism probe, not a TLS/EFS reproduction or study verdict.

Two independent mounts with identical options: warm both roots once, then leave
one idle and run the watchdog's `stat -c %d` command on the other every second.
Only /proc counter reads occur between polls; output belongs on local storage.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path


def counters(mount):
    active = False
    values = {}
    sections = 0
    for line in Path('/proc/self/mountstats').read_text().splitlines():
        if line.startswith('device '):
            active = f' mounted on {mount} with fstype nfs' in line
            sections += active
        elif active:
            parts = line.split()
            if parts and parts[0] in ('GETATTR:', 'LOOKUP:', 'ACCESS:'):
                values[parts[0][:-1]] = int(parts[1])
    if sections != 1 or len(values) != 3:
        raise ValueError('missing/ambiguous mount counters')
    return values


def run(idle, polled, seconds):
    if seconds < 65 or idle == polled:
        raise ValueError('need independent mounts and at least 65 seconds')
    for mount in (idle, polled):
        subprocess.run(['stat', '-c', '%d', mount], check=True, stdout=subprocess.DEVNULL)
    before = {m: counters(m) for m in (idle, polled)}
    timeline = []
    start = time.monotonic_ns()
    for k in range(seconds):
        target = start + k * 1_000_000_000
        time.sleep(max(0, (target - time.monotonic_ns()) / 1e9))
        t0 = time.monotonic_ns()
        subprocess.run(['stat', '-c', '%d', polled], check=True, stdout=subprocess.DEVNULL)
        timeline.append(dict(k=k, start_ns=t0, end_ns=time.monotonic_ns(),
                             idle=counters(idle), polled=counters(polled)))
    time.sleep(max(0, (start + seconds * 1_000_000_000 - time.monotonic_ns()) / 1e9))
    after = {m: counters(m) for m in (idle, polled)}
    delta = {m: {op: after[m][op] - before[m][op] for op in before[m]} for m in before}
    if any(v < 0 for ops in delta.values() for v in ops.values()):
        raise ValueError('counter reset')
    return dict(schema='e5-local-root-stat-v1', command=['stat', '-c', '%d'],
                seconds=seconds, elapsed_ns=time.monotonic_ns()-start,
                idle_mount=idle, polled_mount=polled, before=before, after=after,
                delta=delta, timeline=timeline,
                limitation='models one helper command; not actual watchdog, TLS or EFS attribution')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('idle_mount')
    parser.add_argument('polled_mount')
    parser.add_argument('--seconds', type=int, default=75)
    args = parser.parse_args()
    print(json.dumps(run(args.idle_mount, args.polled_mount, args.seconds), indent=2))
