#!/usr/bin/env python3
"""Candidate isolation validation, never a registered replication or AWS launcher."""
import importlib.util
import json
from pathlib import Path
import shutil
import time

spec = importlib.util.spec_from_file_location('diagnostic',Path(__file__).with_name('e5-diagnostic.py'))
diagnostic = importlib.util.module_from_spec(spec); spec.loader.exec_module(diagnostic)

METHOD = 'isolation-candidate-v1'


def require_quiet(baseline, current):
    c = current['config']
    truth = ('true','yes','on','1')
    if c['mount-watchdog']['enabled'].lower() not in truth:
        raise ValueError('lifecycle watchdog disabled')
    if c['mount-watchdog']['poll_interval_sec'] != '1':
        raise ValueError('candidate requires the validated one-second watchdog poll')
    if c['mount']['optimize_readahead'].lower() not in ('false','no','off','0'):
        raise ValueError('readahead verification is not disabled')
    if c['mount-watchdog']['stunnel_health_check_enabled'].lower() not in ('false','no','off','0'):
        raise ValueError('periodic health probe is not disabled')
    if current['read_ahead_kb'] != baseline['read_ahead_kb']:
        raise ValueError('effective readahead changed')
    if current['watchdog_pid'] != baseline['watchdog_pid']:
        raise ValueError('lifecycle watchdog restarted')


def phases():
    """One non-Lustre batch, then sequential Lustre/EBS reference pairs."""
    non_lustre = [diagnostic.cell(t,d,'diag-isolation') for t in diagnostic.TIERS
                  if t != 'fsx_lustre' for d in diagnostic.DELTAS]
    return [dict(folder='non-lustre',mode='concurrent',warmup=60,measure=360,cells=non_lustre)] + [
        dict(folder=f'lustre-{d}',mode='concurrent',warmup=60,measure=180,
             cells=[diagnostic.cell('fsx_lustre',d,'diag-isolation'),
                    diagnostic.cell('ebs',d,'diag-lustre-control')]) for d in diagnostic.DELTAS]


def idle(host, seconds=360):
    host('trace-start',label='quiet')
    samples = []
    try:
        start = time.monotonic()
        for k in range(seconds+1):
            time.sleep(max(0,start+k-time.monotonic()))
            samples.append(host('snapshot'))
        if samples[-1]['monotonic_ns']-samples[0]['monotonic_ns'] < seconds*1_000_000_000:
            time.sleep(1)
            samples.append(host('snapshot'))
        if samples[-1]['monotonic_ns']-samples[0]['monotonic_ns'] < seconds*1_000_000_000:
            raise ValueError('short idle clock window')
    finally:
        host('trace-stop')
    return samples


def run(host, runner, output, seed_age):
    if seed_age < 120:
        raise ValueError('candidate seed is not aged')
    receipt = dict(method=METHOD,study_replication=False,
                   seed_age_at_start_s=seed_age,phases=[])
    def save():
        (output/'protocol.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    baseline = host('metadata')
    receipt['baseline'] = baseline
    try:
        quiet = host('quiet'); require_quiet(baseline,quiet)
        receipt['quiet'] = quiet; save()
        phase = dict(kind='isolation-idle',mode='quiet',host=quiet,snapshots=[])
        receipt['phases'].append(phase); save()
        phase['snapshots'] = idle(host)
        save()
        first,last = phase['snapshots'][0],phase['snapshots'][-1]
        for mount,values in first['roots'].items():
            if last['roots'][mount] != values:
                raise ValueError('background RPCs remain in quiet idle control')
        for plan in phases():
            receipt['phases'].append(dict(kind='isolation-batch',**plan)); save()
            if runner.run(plan['cells'],output/plan['folder'],plan['mode'],
                          plan['warmup'],plan['measure'],'agebench'):
                raise RuntimeError('isolated diagnostic child failed')
        receipt['after_workload'] = host('metadata')
        require_quiet(baseline,receipt['after_workload'])
    finally:
        # Restore is attempted even if trace shutdown fails, and receipts survive
        # restoration errors. The host controller independently restores on exit.
        try:
            try:
                host('trace-stop')
            finally:
                restored = host('restore')
                receipt['restored'] = restored
                if not restored.get('restored_bytes_match'):
                    raise ValueError('original helper bytes not restored')
                if restored['config'] != baseline['config'] or restored['read_ahead_kb'] != baseline['read_ahead_kb']:
                    raise ValueError('original helper metadata not restored')
        finally:
            for path in diagnostic.CTL.glob('trace-*.txt'):
                shutil.copy(path,output/path.name)
            save()
    return receipt
