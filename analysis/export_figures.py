#!/usr/bin/env python3
"""Export the pinned AWS filesystem study figures using only committed artifacts.

Run from any directory: python3 /path/to/analysis/export_figures.py [--out DIR].
The default output directory is analysis/out in this repository. No site checkout
is needed. Latencies use e2_chart.fmt, with its µs spelling encoded as unit "us".
Other numbers retain artifact precision; percent is an exact decimal conversion.

JSON Pointer cannot select disjoint leaves. For arrays, maps and derived ratios,
raw points to their common ancestor and raw.value preserves that entire subtree.
The definition enumerates the exact leaf pointers in output order; raw.unit
describes those selected leaves (the subtree can also contain other metadata).
E5 arrays follow the three explicitly pinned eligible replications, not JSON object
order. Each array or keyed map declares series_axis as replication or cadence.

produced_at uses SOURCE_DATE_EPOCH, or E4's last replication's recorded /utc.
All selectors are validated before either output file is touched. Existing
outputs are left untouched if validation fails; the nonzero exit is authoritative.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from e2_chart import fmt


ROOT = Path(__file__).resolve().parents[1]
E0 = "results/E0/20260902T105746Z-f62a686"
E0_SINGLE = E0
E2 = "results/E2/20260910T163206Z-66dcff8"
E4 = "results/E4/20261029T091909Z-842d596"
E5_RUNS = (
    "results/E5-formal/20261028T103017Z-342d6b4",
    "results/E5-formal/20261028T125412Z-f6659e0",
    "results/E5-formal/20261028T160106Z-dd5fce0",
)
E5 = E5_RUNS[-1]
E5_REPS = tuple(f"{run.rsplit('/', 1)[-1]}/rep-1" for run in E5_RUNS)
STUDY_RUNS_PATH = "docs/study-runs.json"
ELIGIBLE_ROLES = frozenset(("reference", "formal-v3"))
SERIES_AXES = frozenset(("replication", "cadence"))
TIMESTAMP_PATH = f"{E4}/rep-3/meta.json"
DATASET_ID = "aws-fs.summary"
DATASET_FILE = f"{DATASET_ID}.json"


class ExportError(ValueError):
    """An artifact or required export input is missing or invalid."""


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def resolve_pointer(document, pointer: str):
    """Resolve an RFC 6901 JSON Pointer, including escaped keys and array indices."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ExportError(f"invalid JSON pointer: {pointer!r}")
    value = document
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded):
            raise ExportError(f"invalid JSON pointer escape: {pointer!r}")
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                raise ExportError(f"missing JSON pointer {pointer}")
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            index = int(token)
            if index >= len(value):
                raise ExportError(f"missing JSON pointer {pointer}")
            value = value[index]
        else:
            raise ExportError(f"missing JSON pointer {pointer}")
    return value


@dataclass(frozen=True)
class Figure:
    name: str
    run: str
    file: str
    pointer: str
    definition: str
    raw_unit: str
    # Relative pointers beneath raw.pointer, in output order.
    leaves: tuple[str, ...] = ("",)
    transform: str = "identity"
    dimension: str = "metadata"
    keys: tuple[str, ...] = ()
    series_axis: str = ""

    @property
    def path(self) -> str:
        return f"{self.run}/{self.file}"


def figures() -> tuple[Figure, ...]:
    specs = [
        Figure("e0.warm.syscalls", E0, "aggregate.json",
               "/max~1home~1warm/total_file_syscalls/median",
               "Filesystem syscalls per warm WordPress home request, max profile; "
               "median of ten replications.", "count"),
        Figure("e0.warm.stat", E0, "aggregate.json",
               "/max~1home~1warm/stat_median",
               "Stat-family calls per warm home request, max profile "
               "(validate_timestamps=0); median of ten replications.", "count"),
        Figure("e0.warm.enoent", E0_SINGLE, "rep-1/max/home.warm.census.json",
               "/errno/ENOENT", "Filesystem calls returning ENOENT on a warm home "
               "request, max profile, reference run rep-1.", "count"),
        Figure("e2.block.stat.p50", E2, "summary.json",
               "/tiers/ec2~1instance_store/stat/p50_ns",
               "EC2 instance-store stat p50, pooled across three replications; "
               "the block baseline (EBS ties at displayed precision).", "ns",
               transform="latency"),
        Figure("e2.efs.stat.p50", E2, "summary.json",
               "/tiers/ec2~1efs/stat/p50_ns",
               "EC2 EFS direct TLS stat p50, pooled across three replications.",
               "ns", transform="latency"),
        Figure("e4.hydrated.stat.p50", E4, "summary.json",
               "/pooled/hydrated/stat/p50_ns",
               "Hydrated code-tree stat p50, pooled across three deployments.",
               "ns", transform="latency"),
    ]
    for op, dimension in (("stat", "metadata"), ("open_read", "bytes")):
        specs.append(Figure(
            f"e2.efs_over_block.{op}", E2, "summary.json", "/tiers",
            f"EC2 EFS direct TLS {op} p50 / EC2 instance-store {op} p50, "
            "pooled across three replications. Formula: raw numerator / raw "
            "denominator in ns, before display rounding; no ratio field exists "
            "in the pinned summary.", "ns",
            leaves=(f"/ec2~1efs/{op}/p50_ns", f"/ec2~1instance_store/{op}/p50_ns"),
            transform="divide", dimension=dimension,
        ))
    for name, field, unit, transform, description in (
        ("e5.efs_over_ebs.amortised", "efs_over_ebs", "ratio", "identity",
         "Reported amortised per-request stat-time EFS plain / EBS ratios"),
        ("e5.efs.request.median", "efs_per_request_ns/median", "ns", "latency",
         "Median per-request summed stat time on EFS plain"),
        ("e5.efs.request.p99", "efs_per_request_ns/p99", "ns", "latency",
         "P99 per-request summed stat time on EFS plain"),
        ("e5.ebs.request.median", "ebs_per_request_ns/median", "ns", "latency",
         "Median per-request summed stat time on the EBS control"),
    ):
        specs.append(Figure(
            name, E5, "analysis-pooled-3.json", "/predictions/9/per_replication",
            f"{description}, delta=1 s; the array is the three eligible formal-v3 "
            "replications in chronological order.",
            unit, leaves=tuple(f"/{escape(rep)}/{field}" for rep in E5_REPS),
            transform=transform, series_axis="replication",
        ))
    for variant in ("plain", "tls"):
        mount = "without TLS (plain)" if variant == "plain" else "with TLS"
        for delta in ("0.1", "1", "10"):
            specs.append(Figure(
                f"e5.rpc_per_stat.{variant}@{delta}", E5, "analysis-pooled-3.json",
                "/predictions/5/per_replication",
                f"Reported NFS RPC operations per positive stat on the EFS mount {mount} "
                f"at delta={delta} s; the array is the three eligible formal-v3 "
                "replications in chronological order.", "ratio",
                leaves=tuple(f"/{escape(rep)}/rpc_ops_per_stat/efs_host_{variant}@{delta}"
                             for rep in E5_REPS),
                transform="identity_exact", series_axis="replication",
            ))
    for delta in ("0.1", "1", "10"):
        specs.append(Figure(
            f"e5.lustre.slow_share@{delta}", E5, "analysis-pooled-3.json",
            "/predictions/7/per_replication",
            f"Lustre repeat-stat slow-cluster share at delta={delta} s; the array is "
            "the three eligible formal-v3 replications in chronological order; "
            "percent = recorded fraction * 100, without further rounding.", "ratio",
            leaves=tuple(f"/{escape(rep)}/slow_share/{delta}" for rep in E5_REPS),
            transform="percent", series_axis="replication",
        ))
    return tuple(sorted(specs, key=lambda spec: spec.name))


def load_json(root: Path, path: str):
    try:
        return json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"{path}: {exc}") from exc


def load_run_roles(root: Path) -> dict:
    document = load_json(root, STUDY_RUNS_PATH)
    try:
        runs = document["runs"]
        if not isinstance(runs, list):
            raise TypeError("runs is not a list")
        roles = {}
        for entry in runs:
            path = entry["path"]
            role = entry["role"]
            note = entry["note"]
            if not all(isinstance(value, str) and value for value in (path, role, note)):
                raise TypeError("run path, role and note must be nonempty strings")
            if path in roles:
                raise ExportError(f"{STUDY_RUNS_PATH}: duplicate run path {path}")
            roles[path] = {"role": role, "note": note}
    except (KeyError, TypeError) as exc:
        raise ExportError(f"{STUDY_RUNS_PATH}: invalid run classification: {exc}") from exc
    return roles


def present(value: float) -> float:
    """Presentation rule for ratios and shares, measured from the study's own documents
    rather than chosen: below 1 three significant figures (0.335%), from 1 to 10 two
    decimals (1.03x), from 10 up one decimal (163.1x, 637.2x, 32.7%). The exact quotient
    stays recoverable from raw; latency keeps the latency formatter instead."""
    if value == 0:
        return 0.0
    if abs(value) < 1:
        # No sub-1 sample exists in the study's documents to measure against, so this band
        # keeps all four significant digits the artifact carries: it preserves 0.003347 as
        # 0.3347 and keeps a plain-vs-TLS pair distinguishable at 1 s.
        return float(f"{value:.4g}")
    if abs(value) < 10:
        return round(value, 2)
    return round(value, 1)


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ExportError(f"expected a finite, nonnegative number, got {value!r}")
    return value


def export_selector(spec: Figure, document, run_role: str | None = None) -> dict:
    raw_value = resolve_pointer(document, spec.pointer)
    values = []
    errors = []
    for leaf in spec.leaves:
        pointer = spec.pointer + leaf
        try:
            values.append(number(resolve_pointer(document, pointer)))
        except ExportError as exc:
            errors.append(f"{pointer}: {exc}")
    if errors:
        raise ExportError("; ".join(errors))

    # Record only the leaves actually read; the parent node can be megabytes.
    raw_leaves = dict(zip(spec.leaves, values)) if spec.leaves != ("",) else raw_value

    unit = spec.raw_unit
    if spec.transform == "latency":
        formatted = [fmt(value).split() for value in values]
        units = {parts[1] for parts in formatted}
        if len(units) != 1:
            raise ExportError("latency array spans display units; cannot use one unit")
        unit = formatted[0][1].replace("µs", "us")
        values = [float(parts[0]) for parts in formatted]
    elif spec.transform == "divide":
        if values[1] == 0:
            raise ExportError("ratio denominator is zero")
        values = [present(number(values[0] / values[1]))]
        unit = "ratio"
    elif spec.transform == "percent":
        if any(value > 1 for value in values):
            raise ExportError("share is outside [0, 1]")
        values = [present(float(Decimal(str(value)) * 100)) for value in values]
        unit = "percent"
    elif spec.transform == "identity_exact":
        pass
    elif spec.transform == "identity" and unit == "ratio":
        values = [present(value) for value in values]
    elif spec.transform != "identity":
        raise ExportError(f"unknown transform {spec.transform}")

    value = values[0] if len(values) == 1 else values
    if spec.keys:
        if len(spec.keys) != len(values):
            raise ExportError("map keys and source leaves differ in length")
        value = dict(zip(spec.keys, values))
    if spec.series_axis and spec.series_axis not in SERIES_AXES:
        raise ExportError(f"{spec.name}: invalid series_axis {spec.series_axis!r}")
    if isinstance(value, (list, dict)) and not spec.series_axis:
        raise ExportError(f"{spec.name}: multi-element selector requires series_axis")
    definition = spec.definition
    if spec.leaves != ("",):
        order = "numerator, denominator" if spec.transform == "divide" else "output order"
        definition += f" Source JSON pointers ({order}): " + "; ".join(
            spec.pointer + leaf for leaf in spec.leaves
        ) + "."
    result = {
        "value": value, "unit": unit, "dimension": spec.dimension,
        "definition": definition, "run": spec.run,
        "raw": {"path": spec.path, "pointer": spec.pointer,
                "value": raw_leaves, "unit": spec.raw_unit},
    }
    if run_role is not None:
        result["run_role"] = run_role
    if isinstance(value, (list, dict)):
        result["series_axis"] = spec.series_axis
    if spec.transform == "divide":
        result["derived"] = True
    return result


def produced_at(root: Path) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None:
        if not re.fullmatch(r"[0-9]+", epoch):
            raise ExportError("SOURCE_DATE_EPOCH must be nonnegative integer seconds")
        try:
            stamp = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ExportError(f"invalid SOURCE_DATE_EPOCH: {epoch}") from exc
    else:
        raw = resolve_pointer(load_json(root, TIMESTAMP_PATH), "/utc")
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError("timestamp has no timezone")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExportError(f"{TIMESTAMP_PATH} /utc: invalid timestamp {raw!r}") from exc
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_dataset(root: Path = ROOT) -> dict:
    selectors = {}
    errors = []
    documents = {}
    try:
        run_roles = load_run_roles(root)
    except ExportError as exc:
        run_roles = {}
        errors.append(f"run selection: {exc}")
    specs = figures()
    selected_runs = {spec.run for spec in specs}
    if E5 in selected_runs:
        selected_runs.update(E5_RUNS)
    for run in sorted(selected_runs - {spec.run for spec in specs}):
        record = run_roles.get(run)
        if record is None:
            errors.append(f"run selection: run {run} is not listed in {STUDY_RUNS_PATH}")
        elif record["role"] not in ELIGIBLE_ROLES:
            errors.append(f"run selection: run {run} has ineligible role {record['role']}")
    for spec in specs:
        try:
            record = run_roles.get(spec.run)
            if record is None:
                raise ExportError(f"run {spec.run} is not listed in {STUDY_RUNS_PATH}")
            if record["role"] not in ELIGIBLE_ROLES:
                raise ExportError(
                    f"run {spec.run} has ineligible role {record['role']}; "
                    f"eligible roles are {', '.join(sorted(ELIGIBLE_ROLES))}"
                )
            if spec.path not in documents:
                documents[spec.path] = load_json(root, spec.path)
            selectors[spec.name] = export_selector(spec, documents[spec.path], record["role"])
        except ExportError as exc:
            errors.append(f"{spec.name}: {spec.path} {spec.pointer}: {exc}")
    try:
        timestamp = produced_at(root)
    except ExportError as exc:
        errors.append(f"produced_at: {exc}")
    if errors:
        raise ExportError("Export aborted; no output written:\n" + "\n".join(errors))

    # Assert actual provenance equality even when Python is run with -O.
    for name, selector in selectors.items():
        raw = selector["raw"]
        document = documents[raw["path"]]
        if isinstance(raw["value"], dict) and raw["value"] and all(k.startswith("/") for k in raw["value"]):
            # Multi-leaf selector: each recorded leaf must resolve to the number recorded.
            for leaf, recorded in raw["value"].items():
                if resolve_pointer(document, raw["pointer"] + leaf) != recorded:
                    raise ExportError(f"{name}: raw leaf {leaf} does not resolve to {recorded!r}")
        elif resolve_pointer(document, raw["pointer"]) != raw["value"]:
            raise ExportError(f"{name}: raw provenance does not resolve to raw.value")
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ExportError(f"cannot determine repository HEAD: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{4,40}", commit):
        raise ExportError(f"invalid repository HEAD: {commit!r}")
    run_selection = {run: run_roles[run] for run in sorted(selected_runs)}
    return {
        "id": DATASET_ID, "schema": "dataset/0",
        "produced_by": {"repo": "mikeng-io/aws-wordpress", "commit": commit,
                        "command": "python3 analysis/export_figures.py"},
        "produced_at": timestamp, "run_selection": run_selection, "selectors": selectors,
    }


def encode(document) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def write_outputs(dataset: dict, out: Path, root: Path = ROOT) -> None:
    # Reject results/ even when --out or an existing output is a symlink into it.
    protected = (root / "results").resolve()
    for target in (out, out / DATASET_FILE, out / "index.json"):
        resolved = target.resolve()
        if resolved == protected or protected in resolved.parents:
            raise ExportError(f"refusing to write under results/: {target}")
    data = encode(dataset)
    index = encode({DATASET_ID: {
        "path": f"src/data/figures/{DATASET_FILE}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "selectors": len(dataset["selectors"]),
    }})
    out.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for filename, content in ((DATASET_FILE, data), ("index.json", index)):
            with tempfile.NamedTemporaryFile(dir=out, delete=False) as handle:
                staged.append((Path(handle.name), out / filename))
                handle.write(content)
        for temporary, target in staged:
            temporary.replace(target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "analysis/out")
    args = parser.parse_args(argv)
    try:
        dataset = build_dataset()
        write_outputs(dataset, args.out)
    except (ExportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Exported {len(dataset['selectors'])} selectors to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
