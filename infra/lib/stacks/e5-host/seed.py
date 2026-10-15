#!/usr/bin/env python3
"""E5 seeder, run on the HOST at boot, through a mount that is unmounted afterwards.

Writes the same tree bench.c builds - 20 plugin-NNN/includes directories x 50 files,
sized by bench.c's file_size() - so E5's workload is E2's workload. The measurement
mounts are made only after this mount is gone, so they meet every file as a client
that has never seen it: no new-inode attribute timer, no dirty pages, no delegation
left over from writing. That is the whole point; see experiments/E5-attribute-cache.

Also creates <dir>/conf (empty) when asked, so the conformance gate can run inside
the measured mount later without changing the tree's own directories.

Usage: seed.py [--conf] <dir> [<dir> ...]
Prints one "seeded,<dir>,<files>,<bytes>" line per tree. Exits non-zero on any error.
"""
import os
import sys

DIRS, FILES_PER_DIR = 20, 50


def file_size(d: int, f: int) -> int:
    # bench.c: unsigned h = dir_i * 9973 + file_i * 7919; 2048 + h % (51200 - 2048)
    h = (d * 9973 + f * 7919) & 0xFFFFFFFF
    return 2048 + h % (51200 - 2048)


def seed(root: str, conf: bool) -> None:
    files = total = 0
    for d in range(DIRS):
        inc = os.path.join(root, f"plugin-{d:03d}", "includes")
        os.makedirs(inc, exist_ok=True)
        for f in range(FILES_PER_DIR):
            size = file_size(d, f)
            with open(os.path.join(inc, f"class-{f:03d}.php"), "wb") as fh:
                fh.write(b"e" * size)
            files += 1
            total += size
    if conf:
        os.makedirs(os.path.join(root, "conf"), exist_ok=True)
        os.chmod(os.path.join(root, "conf"), 0o777)
    print(f"seeded,{root},{files},{total}", flush=True)


def main() -> int:
    args = sys.argv[1:]
    conf = "--conf" in args
    dirs = [a for a in args if a != "--conf"]
    if not dirs:
        print(__doc__, file=sys.stderr)
        return 64
    for d in dirs:
        seed(d, conf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
