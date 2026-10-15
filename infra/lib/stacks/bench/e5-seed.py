#!/usr/bin/env python3
"""E5 seeder. Runs on the HOST at boot, through a `seed` mount that is unmounted
afterwards, so no measurement mount ever sees these files being created.

Writes bench.c's tree under each subtree root given on argv: 20 plugin-NNN/includes/
directories x 50 class-NNN.php files, each sized by bench.c's file_size() formula and
filled with 'e', exactly as bench.c fills them. Missing names (missing-NNN.php) are
not created; that is the point of them. Each root also gets an empty conf/ directory,
created now so that the conformance gate's writes later land in conf/ and never
change the change attribute of a directory the cohorts read.

agebench re-derives every size from the same formula and fails the run on any
mismatch, so this file and agebench.c cannot drift apart silently.

Usage: e5-seed.py <subtree-root> [<subtree-root> ...]
"""
import os
import sys

DIRS, FILES_PER_DIR = 20, 50


def file_size(dir_i: int, file_i: int) -> int:
    # bench.c: unsigned h = (unsigned)(dir_i * 9973 + file_i * 7919);
    h = (dir_i * 9973 + file_i * 7919) & 0xFFFFFFFF
    return 2048 + (h % (51200 - 2048))


def seed(root: str) -> int:
    os.makedirs(os.path.join(root, "conf"), exist_ok=True)
    n = 0
    for d in range(DIRS):
        inc = os.path.join(root, f"plugin-{d:03d}", "includes")
        os.makedirs(inc, exist_ok=True)
        for f in range(FILES_PER_DIR):
            with open(os.path.join(inc, f"class-{f:03d}.php"), "wb") as fh:
                fh.write(b"e" * file_size(d, f))
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: e5-seed.py <subtree-root> [...]")
    for root in sys.argv[1:]:
        print(f"seeded {seed(root)} files under {root}", flush=True)
