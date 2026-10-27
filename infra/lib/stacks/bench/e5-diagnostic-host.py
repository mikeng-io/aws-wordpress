#!/usr/bin/env python3
"""Privileged diagnostic-only host controller; fixed verbs, no arbitrary commands.

Requires host PID mode, a directory bind of /etc/amazon/efs and TLS mount roots.
Never exports full helper config, state, certificates or credentials.
"""
import configparser
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

CTL = Path(os.environ.get('CACHE_CTL_DIR','/bench/cache-ctl'))
CONFIG = Path('/host-efs/efs-utils.conf')
ROOT = '/mnt/e5/efs_host_tls/'
FAMILIES = ['default','forced','ss-0.1','ss-1','ss-10']


def write_config(value):
    """Replace atomically so the polling watchdog never reads a truncated file."""
    info = CONFIG.stat()
    with tempfile.NamedTemporaryFile(dir=CONFIG.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            os.fchmod(f.fileno(), info.st_mode & 0o7777)
            os.fchown(f.fileno(), info.st_uid, info.st_gid)
            f.write(value); f.flush(); os.fsync(f.fileno())
            temporary.replace(CONFIG)
        finally:
            temporary.unlink(missing_ok=True)


def apply_profile(original, verb):
    if verb not in ('on','off','quiet','restore'):
        raise ValueError('unknown helper profile')
    if verb == 'restore':
        write_config(original)
        return
    c = configparser.ConfigParser(interpolation=None)
    c.read_string(original.decode())
    if verb == 'quiet' and not c.getboolean('mount-watchdog','enabled',fallback=True):
        raise ValueError('quiet profile requires lifecycle watchdog enabled')
    c.set('mount','optimize_readahead','true' if verb == 'on' else 'false')
    if verb == 'quiet':
        c.set('mount-watchdog','stunnel_health_check_enabled','false')
    value = io.StringIO(); c.write(value)
    write_config(value.getvalue().encode())


def rpc_snapshot():
    result, active = {}, None
    for line in Path('/proc/self/mountstats').read_text().splitlines():
        if line.startswith('device '):
            fields = line.split()
            mount = fields[4]
            active = mount if mount in [ROOT+f for f in FAMILIES] else None
            if active:
                if active in result:
                    raise ValueError('duplicate root mount')
                result[active] = {}
        elif active:
            fields = line.split()
            if fields and fields[0] in ('GETATTR:', 'LOOKUP:', 'ACCESS:'):
                result[active][fields[0][:-1]] = int(fields[1])
    if len(result) != 5 or any(len(v) != 3 for v in result.values()):
        raise ValueError('TLS root counters missing')
    return dict(monotonic_ns=time.monotonic_ns(), roots=result)


def watchdog_pid():
    matches = []
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            cmd = p.read_bytes().split(b'\0')
            if any(x.endswith(b'/amazon-efs-mount-watchdog') for x in cmd):
                matches.append(int(p.parent.name))
        except OSError:
            pass
    if len(matches) != 1:
        raise ValueError('need one watchdog PID')
    return matches[0]


def config_metadata():
    c = configparser.ConfigParser(interpolation=None)
    c.read(CONFIG)
    selected = {section:{key:c.get(section,key,fallback=None) for key in keys} for section,keys in {
        'mount':['optimize_readahead'], 'mount-watchdog':['enabled','poll_interval_sec',
        'stunnel_health_check_enabled','stunnel_health_check_interval_min']}.items()}
    readahead = {}
    for f in FAMILIES:
        dev = os.stat(ROOT+f).st_dev
        readahead[f] = Path(f'/sys/class/bdi/{os.major(dev)}:{os.minor(dev)}/read_ahead_kb').read_text().strip()
    return dict(config=selected, read_ahead_kb=readahead, watchdog_pid=watchdog_pid())


def serve():
    original = CONFIG.read_bytes()
    trace = None
    def stop_trace():
        nonlocal trace
        if trace is not None:
            trace.terminate()
            trace.wait(timeout=10)
            trace = None
    def terminate(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        while True:
            for job in sorted(CTL.glob('diag-*.request')):
                response = job.with_suffix('.response')
                try:
                    request = json.loads(job.read_text())
                    verb = request['verb']
                    if verb == 'snapshot':
                        data = rpc_snapshot()
                    elif verb == 'metadata':
                        data = config_metadata()
                    elif verb in ('on','off','quiet','restore'):
                        apply_profile(original,verb)
                        time.sleep(3)  # watchdog reloads the file each poll
                        data = config_metadata()
                        if verb == 'restore':
                            data['restored_bytes_match'] = CONFIG.read_bytes() == original
                    elif verb == 'trace-start':
                        if trace is not None:
                            raise ValueError('trace already running')
                        label = request['label']
                        if not label.isalnum():
                            raise ValueError('invalid trace label')
                        args = ['strace','-f','-ttt','-s','128','-e','trace=statx,newfstatat']
                        for f in FAMILIES:
                            args += ['-P',ROOT+f]
                        args += ['-p',str(watchdog_pid()),'-o',str(CTL/f'trace-{label}.txt')]
                        trace = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(1)
                        if trace.poll() is not None:
                            raise ValueError('strace attach failed')
                        data = {'attached':True}
                    elif verb == 'trace-stop':
                        stop_trace(); data = {'stopped':True}
                    else:
                        raise ValueError('unsupported diagnostic verb')
                    payload = dict(ok=True, data=data)
                except Exception as exc:
                    payload = dict(ok=False, error=type(exc).__name__)
                tmp = response.with_suffix('.tmp')
                tmp.write_text(json.dumps(payload)); tmp.replace(response)
                job.unlink()
            time.sleep(.05)
    finally:
        try:
            stop_trace()
        finally:
            write_config(original)


if __name__ == '__main__':
    serve()
