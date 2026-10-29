#!/usr/bin/env python3
"""E4 — task-start hydration on Fargate.

Reads the committed raw CSVs; writes summary.json and summary.md next to them.
Every number here is recomputable from the raw per-syscall lines.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

from e3_clusters import analyse as cluster_analysis
from e2_stats import median_ci95, geo_mean

OPS = ("stat", "stat_enoent", "open_read")
E0_OPS_PER_REQUEST = 4300.0
P1_STAT_MAX = 0.10
P1_OPEN_MAX = 0.20
P2_MIN_HYDRATION_S = 0.5


def pct(values: list[int], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    # Nearest-rank: no interpolation, and the maximum for p100.
    k = max(0, min(len(s) - 1, math.ceil(p * len(s)) - 1))
    return float(s[k])


def read_bench(path: Path) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) != 2:
            continue
        op, raw = parts
        if op not in OPS:
            continue
        try:
            ns = int(raw)
        except ValueError:
            continue
        if ns >= 0:
            out.setdefault(op, []).append(ns)
    return out


def read_conformance(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or parts[0].startswith("TOTAL_"):
            continue
        if parts[1] in {"PASS", "FAIL", "ERROR"}:
            out[parts[0]] = parts[1]
    return out


def read_hydration(path: Path) -> tuple[float, int] | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) == 3 and parts[0] == "hydrate":
            try:
                return int(parts[1]) / 1e9, int(parts[2])
            except ValueError:
                return None
    return None


def arm_tier(rep_dir: Path, arm: str) -> str:
    """The task's arm label and its tier label differ: hydrated -> ephemeral."""
    manifest = rep_dir / arm / "manifest.txt"
    if manifest.exists():
        tiers = [line.strip() for line in manifest.read_text().splitlines() if line.strip()]
        if tiers:
            return tiers[0]
    return "efs" if arm == "efs" else "ephemeral"


def task_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        task = json.loads(path.read_text())["tasks"][0]
        start = datetime.fromisoformat(task["startedAt"].replace("Z", "+00:00"))
        stop = datetime.fromisoformat(task["stoppedAt"].replace("Z", "+00:00"))
        return (stop - start).total_seconds()
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def start_to_benchmark_seconds(path: Path) -> float | None:
    """From the task's first log line to the line that starts the benchmark.

    Total task duration includes the benchmark itself (and EFS is slower), so it is
    not the hydration overhead. The pre-registered comparison is start-to-benchmark.
    """
    if not path.exists():
        return None
    first = None
    benchmark = None
    for line in path.read_text().splitlines():
        if not line or line[0].isdigit() is False:
            continue
        stamp = line.split(" ", 1)[0]
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if first is None:
            first = when
        if "benchmarking " in line:
            benchmark = when
            break
    if first is None or benchmark is None:
        return None
    return (benchmark - first).total_seconds()


def conformance_verdict(conf: dict[str, str]) -> tuple[str, list[str], list[str]]:
    if not conf:
        return "ERROR", [], ["no conformance rows"]
    fails = sorted(k for k, v in conf.items() if v == "FAIL")
    errors = sorted(k for k, v in conf.items() if v == "ERROR")
    if errors:
        return "INCONCLUSIVE", fails, errors
    if fails:
        return "REFUTED", fails, errors
    return "SUPPORTED", fails, errors


def distribution(vals: list[int]) -> dict:
    p50 = pct(vals, 0.50)
    return {
        "n": len(vals),
        "p25_ns": pct(vals, 0.25),
        "p50_ns": p50,
        "p75_ns": pct(vals, 0.75),
        "p95_ns": pct(vals, 0.95),
        "p99_ns": pct(vals, 0.99),
        "median_ci95_ns": list(median_ci95(vals)),
        "geomean_ns": geo_mean(vals),
        "iqr_over_median": (pct(vals, 0.75) - pct(vals, 0.25)) / p50,
        "p99_over_p50": pct(vals, 0.99) / p50,
        "clusters": cluster_analysis(vals),
    }


def stat_block(bench: dict[str, list[int]]) -> dict[str, dict]:
    return {op: distribution(bench[op]) for op in OPS if bench.get(op)}


def main(root: Path) -> int:
    rep_dirs = sorted(
        (p for p in root.glob("rep-*") if p.is_dir()),
        key=lambda p: int(p.name.split("-")[1]),
    )
    if not rep_dirs:
        print(f"no rep-* under {root}", file=sys.stderr)
        return 2

    reps: list[dict] = []
    for rep_dir in rep_dirs:
        efs_tier = arm_tier(rep_dir, "efs")
        hyd_tier = arm_tier(rep_dir, "hydrated")
        efs = read_bench(rep_dir / "efs" / f"{efs_tier}.csv")
        hyd = read_bench(rep_dir / "hydrated" / f"{hyd_tier}.csv")
        efs_conf = read_conformance(rep_dir / "efs" / f"{efs_tier}.conformance.csv")
        hyd_conf = read_conformance(rep_dir / "hydrated" / f"{hyd_tier}.conformance.csv")
        hydration = read_hydration(rep_dir / "hydrated" / "hydration.csv")
        efs_task_s = task_seconds(rep_dir / "efs.task.json")
        hyd_task_s = task_seconds(rep_dir / "hydrated.task.json")
        efs_start_bench_s = start_to_benchmark_seconds(rep_dir / "efs.task.log")
        hyd_start_bench_s = start_to_benchmark_seconds(rep_dir / "hydrated.task.log")
        efs_stat = stat_block(efs)
        hyd_stat = stat_block(hyd)

        ratios = {}
        for op in OPS:
            a = efs_stat.get(op, {}).get("p50_ns")
            b = hyd_stat.get(op, {}).get("p50_ns")
            ratios[op] = (b / a) if a and b else None

        hyd_s = hydration[0] if hydration else None
        hyd_bytes = hydration[1] if hydration else None
        delta_s = (efs_task_s - hyd_task_s) if (efs_task_s is not None and hyd_task_s is not None) else None
        # Sign: hydrated task should be LONGER. Report the difference in the
        # direction prediction 2 states, so a negative value is a failure.
        task_extra_s = (hyd_task_s - efs_task_s) if (efs_task_s is not None and hyd_task_s is not None) else None
        start_extra_s = (
            (hyd_start_bench_s - efs_start_bench_s)
            if (efs_start_bench_s is not None and hyd_start_bench_s is not None)
            else None
        )

        penalty_s = None
        breakeven = None
        if efs_stat.get("stat") and hyd_stat.get("stat"):
            delta_ns = efs_stat["stat"]["p50_ns"] - hyd_stat["stat"]["p50_ns"]
            if delta_ns > 0:
                penalty_s = E0_OPS_PER_REQUEST * efs_stat["stat"]["p50_ns"] / 1e9
                if hyd_s is not None:
                    breakeven = hyd_s / (E0_OPS_PER_REQUEST * delta_ns / 1e9)

        reps.append({
            "replication": int(rep_dir.name.split("-")[1]),
            "efs_tier": efs_tier,
            "hydrated_tier": hyd_tier,
            "efs": efs_stat,
            "hydrated": hyd_stat,
            "ratios": ratios,
            "hydration_s": hyd_s,
            "hydration_bytes": hyd_bytes,
            "efs_task_s": efs_task_s,
            "hydrated_task_s": hyd_task_s,
            "efs_start_to_benchmark_s": efs_start_bench_s,
            "hydrated_start_to_benchmark_s": hyd_start_bench_s,
            "start_extra_s": start_extra_s,
            "task_extra_s": task_extra_s,
            "efs_task_minus_hydrated_s": delta_s,
            "efs_conformance": conformance_verdict(efs_conf)[0],
            "efs_conformance_fails": conformance_verdict(efs_conf)[1],
            "efs_conformance_errors": conformance_verdict(efs_conf)[2],
            "hydrated_conformance": conformance_verdict(hyd_conf)[0],
            "hydrated_conformance_fails": conformance_verdict(hyd_conf)[1],
            "hydrated_conformance_errors": conformance_verdict(hyd_conf)[2],
            "one_request_efs_penalty_s": penalty_s,
            "breakeven_requests": breakeven,
        })

    # Prediction 1: every replication, both thresholds. Missing data is
    # INCONCLUSIVE, not REFUTED: absence of a number is not a verdict about the tier.
    p1_fail: list[str] = []
    p1_missing: list[str] = []
    for r in reps:
        for op, cap in (("stat", P1_STAT_MAX), ("open_read", P1_OPEN_MAX)):
            ratio = r["ratios"].get(op)
            if ratio is None:
                p1_missing.append(f"rep-{r['replication']}: {op} missing")
            elif ratio > cap:
                p1_fail.append(f"rep-{r['replication']}: {op} {ratio:.3f} > {cap:.2f}")
    p1_status = "REFUTED" if p1_fail else ("INCONCLUSIVE" if p1_missing else "SUPPORTED")

    # Prediction 2: hydration >= 0.5 s and task extra >= hydration time.
    p2_fail: list[str] = []
    p2_missing: list[str] = []
    for r in reps:
        if r["hydration_s"] is None:
            p2_missing.append(f"rep-{r['replication']}: no hydration.csv")
        elif r["hydration_s"] < P2_MIN_HYDRATION_S:
            p2_fail.append(f"rep-{r['replication']}: hydration {r['hydration_s']:.3f}s < {P2_MIN_HYDRATION_S}s")
        if r["start_extra_s"] is None:
            p2_missing.append(f"rep-{r['replication']}: missing start-to-benchmark timing")
        elif r["hydration_s"] is not None and r["start_extra_s"] < r["hydration_s"]:
            p2_fail.append(
                f"rep-{r['replication']}: start extra {r['start_extra_s']:.3f}s < hydration {r['hydration_s']:.3f}s"
            )
    p2_status = "REFUTED" if p2_fail else ("INCONCLUSIVE" if p2_missing else "SUPPORTED")

    # Prediction 3: both arms conformant in every replication.
    p3_fail: list[str] = []
    p3_missing: list[str] = []
    for r in reps:
        for arm in ("efs", "hydrated"):
            verdict = r[f"{arm}_conformance"]
            if verdict == "REFUTED":
                p3_fail.append(f"rep-{r['replication']}: {arm} REFUTED")
            elif verdict != "SUPPORTED":
                p3_missing.append(f"rep-{r['replication']}: {arm} {verdict}")
    p3_status = "REFUTED" if p3_fail else ("INCONCLUSIVE" if p3_missing else "SUPPORTED")

    # H2 gate: P1 holds and hydration is cheaper than one E0-sized request's EFS
    # stat penalty. This is explicitly a proxy, not end-to-end request latency.
    h2_reasons = []
    if p1_status != "SUPPORTED":
        h2_reasons.append("prediction 1 did not hold")
    for r in reps:
        if r["one_request_efs_penalty_s"] is None or r["hydration_s"] is None:
            h2_reasons.append(f"rep-{r['replication']}: missing penalty/hydration")
        elif r["hydration_s"] >= r["one_request_efs_penalty_s"]:
            h2_reasons.append(
                f"rep-{r['replication']}: hydration {r['hydration_s']:.3f}s >= one-request penalty {r['one_request_efs_penalty_s']:.3f}s"
            )
    h2_gate = "MET" if not h2_reasons else "NOT MET"

    def pooled(op: str, arm: str) -> dict[str, float]:
        vals: list[int] = []
        for rep_dir in rep_dirs:
            vals.extend(read_bench(rep_dir / arm / f"{arm_tier(rep_dir, arm)}.csv").get(op, []))
        return distribution(vals) if vals else {"n": 0, "p50_ns": float("nan")}

    pooled_stats = {arm: {op: pooled(op, arm) for op in OPS} for arm in ("efs", "hydrated")}
    pooled_ratio = {}
    for op in OPS:
        a = pooled_stats["efs"][op]["p50_ns"]
        b = pooled_stats["hydrated"][op]["p50_ns"]
        pooled_ratio[op] = (b / a) if a and b else None

    summary = {
        "experiment": "E4",
        "run_id": root.name,
        "reps": len(reps),
        "measures": "per-syscall latency for an existing read-only tree + hydration wall time; not end-to-end request latency",
        "prediction_1": {
            "status": p1_status,
            "rule": "hydrated stat p50 <= 0.10x EFS and open_read p50 <= 0.20x EFS, every replication",
            "failures": p1_fail,
            "missing": p1_missing,
        },
        "prediction_2": {
            "status": p2_status,
            "rule": "hydration >= 0.5 s and hydrated start-to-benchmark exceeds EFS start-to-benchmark by at least hydration time",
            "failures": p2_fail,
            "missing": p2_missing,
        },
        "prediction_3": {
            "status": p3_status,
            "rule": "single-node conformance passes on both EFS and hydrated arms, every replication",
            "failures": p3_fail,
            "missing": p3_missing,
        },
        "h2_gate": {
            "status": h2_gate,
            "reasons": h2_reasons,
            "note": "proxy: E0's 4300 ops/request times EFS stat p50; not end-to-end request latency",
        },
        "statistical_method": {
            "median": "nearest rank, unchanged from pre-registered grader",
            "median_ci95": "distribution-free order-statistic interval, normal approximation to binomial rank bounds; operation-level, not between-deployment CI",
            "clusters": "deterministic log10 k-means, 10th/90th initialisation; separation >= 0.5 and both shares >= 2%",
        },
        "between_replication": {
            arm: {
                op: {
                    "p50_ns": [r[arm][op]["p50_ns"] for r in reps if op in r[arm]],
                    "max_over_min": max(r[arm][op]["p50_ns"] for r in reps if op in r[arm]) / min(r[arm][op]["p50_ns"] for r in reps if op in r[arm]),
                }
                for op in OPS if all(op in r[arm] for r in reps)
            }
            for arm in ("efs", "hydrated")
        },
        "pooled": pooled_stats,
        "pooled_ratio_hydrated_over_efs": pooled_ratio,
        "per_replication": reps,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    def us(ns: float | None) -> str:
        if ns is None or math.isnan(ns):
            return "—"
        return f"{ns / 1000:.1f} µs" if ns < 1e6 else f"{ns / 1e6:.2f} ms"

    lines = [
        f"# E4 hydration — {root.name}",
        "",
        f"{len(reps)} replication(s). Lower is better. Hydrated = task-start copy of the read-only tree; EFS = fresh client reading the same tree over NFS.",
        "",
        "## Per-replication p50",
        "",
        "| Rep | stat EFS | stat hydrated | ratio | open_read EFS | open_read hydrated | ratio | hydration |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for r in reps:
        def ratio_text(value: float | None) -> str:
            return f"{value:.3f}" if value is not None else "—"

        hydration_text = f"{r['hydration_s']:.2f} s" if r["hydration_s"] is not None else "—"
        lines.append(
            f"| {r['replication']} | {us(r['efs'].get('stat',{}).get('p50_ns'))} | "
            f"{us(r['hydrated'].get('stat',{}).get('p50_ns'))} | "
            f"{ratio_text(r['ratios'].get('stat'))} | "
            f"{us(r['efs'].get('open_read',{}).get('p50_ns'))} | "
            f"{us(r['hydrated'].get('open_read',{}).get('p50_ns'))} | "
            f"{ratio_text(r['ratios'].get('open_read'))} | "
            f"{hydration_text} |"
        )
    lines += [
        "",
        "## Grades",
        "",
        f"- **P1, hydration removes the metadata penalty:** `{p1_status}`",
        f"- **P2, hydration is not free:** `{p2_status}`",
        f"- **P3, conformance:** `{p3_status}`",
        f"- **H2 kill-condition proxy:** `{h2_gate}`",
        "",
    ]
    if p1_fail:
        lines += ["P1 failures:"] + [f"- {x}" for x in p1_fail] + [""]
    if p1_missing:
        lines += ["P1 missing:"] + [f"- {x}" for x in p1_missing] + [""]
    if p2_fail:
        lines += ["P2 failures:"] + [f"- {x}" for x in p2_fail] + [""]
    if p2_missing:
        lines += ["P2 missing:"] + [f"- {x}" for x in p2_missing] + [""]
    if p3_fail:
        lines += ["P3 failures:"] + [f"- {x}" for x in p3_fail] + [""]
    if p3_missing:
        lines += ["P3 missing:"] + [f"- {x}" for x in p3_missing] + [""]
    if h2_reasons:
        lines += ["H2 gate reasons:"] + [f"- {x}" for x in h2_reasons] + [""]
    lines += [
        "## Pooled",
        "",
        "| op | EFS p50 | hydrated p50 | ratio |",
        "|---|--:|--:|--:|",
    ]
    for op in OPS:
        ratio = pooled_ratio[op]
        ratio_text = f"{ratio:.3f}" if ratio is not None and not math.isnan(ratio) else "—"
        lines.append(
            f"| `{op}` | {us(pooled_stats['efs'][op]['p50_ns'])} | "
            f"{us(pooled_stats['hydrated'][op]['p50_ns'])} | {ratio_text} |"
        )
    lines += [
        "",
        "## Hydration and break-even",
        "",
        "| Rep | bytes | hydration s | EFS start→bench | hydrated start→bench | start extra | one-request penalty | break-even requests |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for r in reps:
        def fmt(v, d=2):
            return f"{v:.{d}f}" if v is not None else "—"
        lines.append(
            f"| {r['replication']} | {r['hydration_bytes'] or '—'} | {fmt(r['hydration_s'],3)} | "
            f"{fmt(r['efs_start_to_benchmark_s'],2)} | {fmt(r['hydrated_start_to_benchmark_s'],2)} | {fmt(r['start_extra_s'],2)} | "
            f"{fmt(r['one_request_efs_penalty_s'],2)} | {fmt(r['breakeven_requests'],2)} |"
        )
    lines += [
        "",
        "Break-even uses E0's 4,300 filesystem syscalls per warm request and the measured",
        "`stat` p50 difference; it is an extrapolation, not an end-to-end request measurement.",
        "",
        "## Per-replication conformance",
        "",
        "| Rep | EFS | hydrated | EFS fails | hydrated fails |",
        "|---|--:|--:|---|---|",
    ]
    for r in reps:
        lines.append(
            f"| {r['replication']} | {r['efs_conformance']} | {r['hydrated_conformance']} | "
            f"{', '.join(r['efs_conformance_fails']) or '—'} | {', '.join(r['hydrated_conformance_fails']) or '—'} |"
        )
    lines += [
        "", "## Distribution and replication diagnostics", "",
        "CIs below are operation-level order-statistic intervals (binomial-rank normal",
        "approximation); they do not quantify uncertainty across three deployments.", "",
        "| Arm | op | n | p50 CI95 | geometric mean | p95 | p99 | IQR/p50 | p99/p50 | rep p50 max/min | modes |",
        "|---|---|--:|---|--:|--:|--:|--:|--:|--:|---|",
    ]
    for arm in ("efs", "hydrated"):
        for op in OPS:
            d = pooled_stats[arm][op]
            if not d["n"]:
                continue
            ci = d["median_ci95_ns"]
            spread = summary["between_replication"][arm][op]["max_over_min"]
            lines.append(
                f"| {arm} | {op} | {d['n']} | {us(ci[0])}–{us(ci[1])} | "
                f"{us(d['geomean_ns'])} | {us(d['p95_ns'])} | {us(d['p99_ns'])} | "
                f"{d['iqr_over_median']:.3f} | {d['p99_over_p50']:.3f} | {spread:.3f} | {d['clusters']['verdict']} |"
            )
            if d["clusters"]["verdict"] == "bimodal":
                for name, c in d["clusters"]["clusters"].items():
                    lines.append(f"<!-- {arm}/{op} {name}: share={c['share']}, median_ns={c['median_ns']}, CI95_ns={c['median_ci95_ns']} -->")
    lines += ["", "Per-replication distributions and cluster diagnostics are in summary.json.", ""]
    (root / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: e4_stats.py results/E4/<run-id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
