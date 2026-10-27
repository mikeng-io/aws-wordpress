#!/usr/bin/env python3
"""Read-only E5 scheduling diagnostics; stdout only, never regrades a run.

Request syscall sums exclude path formatting, histograms, output and scheduling.
They are lower bounds on elapsed service time, not CPU time. A long syscall can
include descheduling; this report cannot isolate filesystem/server latency.
"""
import argparse
import hashlib
import json
from pathlib import Path

import e5_stats as g


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty measured window")
    return {"p50": ordered[(len(ordered) - 1) // 2],
            "p99": ordered[((len(ordered) * 99 + 99) // 100) - 1],
            "max": ordered[-1]}


def scheduling(header, rows):
    delta = int(header["delta_ns"])
    measured = [r for r in rows if r["phase"] == "m"]
    if delta <= 0 or len(measured) != int(header["measured_requests"]):
        raise ValueError("invalid interval or measured request count")
    if not measured or any(b["k"] != a["k"] + 1 for a, b in zip(measured, measured[1:])):
        raise ValueError("empty or non-contiguous measured window")
    if any(min(r["late"], r["stat_sum"], r["enoent_sum"], r["counter_ns"]) < 0 for r in measured):
        raise ValueError("negative timing")
    work = [r["stat_sum"] + r["enoent_sum"] for r in measured]
    # Absolute deadline scheduling: the next request cannot begin before the
    # current syscall work finishes. Counters/output only add to this bound.
    bounds = [max(0, r["late"] + w - delta) for r, w in zip(measured[:-1], work[:-1])]
    following = measured[1:]
    return {
        "requests": len(measured), "delta_ns": delta,
        "late_over_half_interval": sum(2 * r["late"] > delta for r in measured),
        "syscall_sum_over_interval": sum(w > delta for w in work),
        "stat_sum_ns": distribution([r["stat_sum"] for r in measured]),
        "enoent_sum_ns": distribution([r["enoent_sum"] for r in measured]),
        "syscall_sum_ns": distribution(work),
        "counter_ns": distribution([r["counter_ns"] for r in measured]),
        "lateness_ns": distribution([r["late"] for r in measured]),
        "following_requests": len(following),
        "following_late_forced_by_syscall_lower_bound": sum(2 * b > delta for b in bounds),
        "lower_bound_violations": sum(r["late"] < b for r, b in zip(following, bounds)),
    }


def diagnose(run):
    report = {"schema": "e5-pilot-scheduling-v1", "run": run.name,
              "interpretation": "diagnostic only; syscall elapsed time includes descheduling; no regrading",
              "inputs_sha256": {}, "cells": {}}
    paths = sorted(run.glob("rep-*/ec2/*/B-*.req.csv.gz"))
    if not paths:
        raise ValueError("no request files")
    for path in paths:
        key = str(path.relative_to(run))
        report["inputs_sha256"][key] = hashlib.sha256(path.read_bytes()).hexdigest()
        header, rows = g.load_req(path)
        if header.get("method") != "rpc-phases-v2":
            raise ValueError(f"unsupported request method: {key}")
        report["cells"][key] = scheduling(header, rows)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.run), indent=2, sort_keys=True))
