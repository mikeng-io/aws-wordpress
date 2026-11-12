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
order. Each array or keyed map declares series_axis as replication, cadence or
percentile; percentile ladders carry series_labels for their fixed element order.
Selectors may also read a committed derived document (analysis/derived/*.json);
its recorded input sha256s are re-verified against the raw files before export.

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
E2_FSX = "results/E2/20261015T000959Z-85382cc"
E4 = "results/E4/20261029T091909Z-842d596"
E5_RUNS = (
    "results/E5-formal/20261028T103017Z-342d6b4",
    "results/E5-formal/20261028T125412Z-f6659e0",
    "results/E5-formal/20261028T160106Z-dd5fce0",
)
E5 = E5_RUNS[-1]
E5_REPS = tuple(f"{run.rsplit('/', 1)[-1]}/rep-1" for run in E5_RUNS)
E2_FSX_REPS = ("rep-1", "rep-2", "rep-3")
CACHE_WINDOW_DOC = (f"analysis/derived/"
                    f"e2-cache-window-{E2_FSX.rsplit('/', 1)[-1]}.json")
CACHE_WINDOW_TIERS = ("efs", "fsx_openzfs", "fsx_ontap", "fsx_lustre")
STUDY_RUNS_PATH = "docs/study-runs.json"
ELIGIBLE_ROLES = frozenset(("reference", "formal-v3"))
SERIES_AXES = frozenset(("replication", "cadence", "percentile"))
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
    # A committed derived document outside results/ (e.g. analysis/derived/*.json).
    # When set it is the document read and the raw.path recorded, and its inputs
    # manifest is sha256-verified against the raw files before any value is emitted.
    document: str | None = None
    # Marks the selector derived even when the transform is not a ratio.
    derived: bool = False
    # null leaves are meaningful (an undefined metric), not a validation failure.
    nullable: bool = False
    undefined_reason: str | None = None
    # Element names for a series_axis="percentile" ladder, in output order.
    series_labels: tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"{self.run}/{self.file}"

    @property
    def document_path(self) -> str:
        return self.document or self.path


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
    for leaf in ("median", "p99"):
        specs.append(Figure(
            f"e5.efs_over_ebs.{leaf}", E5, "analysis-pooled-3.json",
            "/predictions/9/per_replication",
            f"EFS plain per-request summed stat time {leaf} / matched-EBS {leaf}, "
            "delta=1 s. Leaves are numerator, denominator pairs per replication in "
            "chronological order of the three eligible formal-v3 replications. "
            "Formula: raw numerator / raw denominator in ns, before display "
            "rounding; no ratio field exists in the pinned summary.", "ns",
            leaves=tuple(f"/{escape(rep)}/{arm}_per_request_ns/{leaf}"
                         for rep in E5_REPS for arm in ("efs", "ebs")),
            transform="divide_pairs", series_axis="replication",
        ))
    for index, rep in enumerate(E5_REPS, start=1):
        for arm in ("efs", "ebs"):
            specs.append(Figure(
                f"e5.{arm}.request.ladder@{index}", E5, "analysis-pooled-3.json",
                f"/predictions/9/per_replication/{escape(rep)}",
                f"Per-request summed stat time on "
                f"{'EFS plain' if arm == 'efs' else 'the matched-EBS control'}, "
                f"delta=1 s, eligible formal-v3 replication {index} in "
                "chronological order. Percentile ladder, element order median, "
                "mean (amortised), p99, max; every element ns/1000 at four "
                "significant figures, exact ns in raw.", "ns",
                leaves=tuple(f"/{arm}_per_request_ns/{leaf}"
                             for leaf in ("median", "amortised", "p99", "max")),
                transform="us_4sf", series_axis="percentile",
                series_labels=("median", "mean (amortised)", "p99", "max"),
            ))
    for arm, label in (("efs", "EFS"), ("hydrated", "Hydrated code-tree")):
        specs.append(Figure(
            f"e4.{arm}.stat.ladder", E4, "summary.json", f"/pooled/{arm}/stat",
            f"{label} stat percentile ladder, pooled across three deployments; "
            "element order p50, p95, p99; every element ns/1000 at four "
            "significant figures, exact ns in raw.", "ns",
            leaves=("/p50_ns", "/p95_ns", "/p99_ns"),
            transform="us_4sf", series_axis="percentile",
            series_labels=("p50", "p95", "p99"),
        ))
    specs.append(Figure(
        "e4.hydration.seconds", E4, "summary.json", "/per_replication",
        "Task-start hydration seconds for the identical 27,412,480-byte code-tree "
        "tar; the array is the three replications in order; values at four "
        "significant figures, artifact precision in raw.", "s",
        leaves=("/0/hydration_s", "/1/hydration_s", "/2/hydration_s"),
        transform="sig4", series_axis="replication", dimension="bytes",
    ))
    specs.append(Figure(
        "e4.hydration.bytes", E4, "summary.json", "/per_replication",
        "Uncompressed bytes hydrated at task start; the artifact records the "
        "same value in every replication and the export fails unless all three "
        "leaves agree.", "bytes",
        leaves=("/0/hydration_bytes", "/1/hydration_bytes", "/2/hydration_bytes"),
        transform="uniform", dimension="bytes",
    ))
    for tier in CACHE_WINDOW_TIERS:
        for metric, unit, transform, description in (
            ("create_pass_s", "s", "sig4",
             "duration of the 1,000-file create pass"),
            ("fast_stat_share", "ratio", "percent",
             "share of the 1,000 stat calls in the fast NFS attribute-cache "
             "cluster"),
            ("boundary_age_s", "s", "sig4",
             "age of the oldest fast file when the create pass ended"),
        ):
            specs.append(Figure(
                f"e2.cache_window.{tier}.{metric}", E2_FSX,
                f"e2-cache-window-{E2_FSX.rsplit('/', 1)[-1]}.json",
                f"/tiers/{tier}/replications",
                f"{description}, per replication; derived by "
                "analysis/e2_cache_window.py from the pinned FSx run's raw CSVs "
                "(E3 gated k-means fast cluster on per-file stat order); the "
                "array is the three replications.", unit,
                leaves=tuple(f"/{rep}/{metric}" for rep in E2_FSX_REPS),
                transform=transform, series_axis="replication",
                document=CACHE_WINDOW_DOC, derived=True, nullable=True,
                undefined_reason=(
                    "stat is unimodal under the E3 gates; the study defines no "
                    "fast cluster for a single population"
                    if metric != "create_pass_s" else None),
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


def sig4(value: float) -> float:
    """Four significant figures: the single rounding rule for values the dataset
    presents in a converted unit (ns -> us) or trimmed from artifact precision."""
    if value == 0:
        return 0.0
    return float(f"{value:.4g}")


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ExportError(f"expected a finite, nonnegative number, got {value!r}")
    return value


def verify_derived_document(root: Path, document, spec: Figure) -> None:
    """A selector sourced from a derived document verifies the document's own
    provenance before reading a value: the run it claims, and the recorded sha256
    of every raw input it was derived from. Any mismatch fails closed."""
    claimed_run = document.get("run")
    if claimed_run != spec.run:
        raise ExportError(
            f"{spec.document}: run {claimed_run!r} does not match {spec.run}")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or not inputs or not all(
            isinstance(path, str) and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
            for path, digest in inputs.items()):
        raise ExportError(f"{spec.document}: missing or invalid inputs manifest")
    for path, expected in sorted(inputs.items()):
        try:
            actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        except OSError as exc:
            raise ExportError(f"{spec.document}: input {path}: {exc}") from exc
        if actual != expected:
            raise ExportError(
                f"{spec.document}: input {path} sha256 changed; the derived "
                "file is stale or the raw artifact was tampered with")


def export_selector(spec: Figure, document, run_role: str | None = None) -> dict:
    raw_value = resolve_pointer(document, spec.pointer)
    values = []
    errors = []
    for leaf in spec.leaves:
        pointer = spec.pointer + leaf
        try:
            leaf_value = resolve_pointer(document, pointer)
            if leaf_value is None and spec.nullable:
                values.append(None)
            else:
                values.append(number(leaf_value))
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
    elif spec.transform == "divide_pairs":
        if len(values) % 2:
            raise ExportError("divide_pairs requires numerator/denominator leaf pairs")
        paired = []
        for offset in range(0, len(values), 2):
            numerator, denominator = values[offset], values[offset + 1]
            if denominator == 0:
                raise ExportError("ratio denominator is zero")
            paired.append(present(number(numerator / denominator)))
        values = paired
        unit = "ratio"
    elif spec.transform == "percent":
        if any(value is not None and value > 1 for value in values):
            raise ExportError("share is outside [0, 1]")
        values = [None if value is None
                  else present(float(Decimal(str(value)) * 100))
                  for value in values]
        unit = "percent"
    elif spec.transform == "us_4sf":
        # Ladder elements share one unit, so every ns leaf converts individually:
        # ns/1000 at four significant figures; the exact ns stays in raw.
        values = [None if value is None else sig4(value / 1000) for value in values]
        unit = "us"
    elif spec.transform == "sig4":
        values = [None if value is None else sig4(value) for value in values]
    elif spec.transform == "uniform":
        if len(set(values)) != 1:
            raise ExportError("leaves expected to be identical differ")
        values = values[:1]
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
        order = ("numerator, denominator"
                 if spec.transform in ("divide", "divide_pairs") else "output order")
        definition += f" Source JSON pointers ({order}): " + "; ".join(
            spec.pointer + leaf for leaf in spec.leaves
        ) + "."
    result = {
        "value": value, "unit": unit, "dimension": spec.dimension,
        "definition": definition, "run": spec.run,
        "raw": {"path": spec.document_path, "pointer": spec.pointer,
                "value": raw_leaves, "unit": spec.raw_unit},
    }
    if run_role is not None:
        result["run_role"] = run_role
    if isinstance(value, (list, dict)):
        result["series_axis"] = spec.series_axis
    if spec.series_labels:
        if not spec.series_axis:
            raise ExportError(f"{spec.name}: series_labels without series_axis")
        result["series_labels"] = list(spec.series_labels)
    if any(element is None for element in values):
        result["defined"] = False
        if spec.undefined_reason:
            result["undefined_reason"] = spec.undefined_reason
    if spec.transform in ("divide", "divide_pairs") or spec.derived:
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
    verified_documents = set()
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
            doc_path = spec.document_path
            if doc_path not in documents:
                documents[doc_path] = load_json(root, doc_path)
            if spec.document and doc_path not in verified_documents:
                verify_derived_document(root, documents[doc_path], spec)
                verified_documents.add(doc_path)
            selectors[spec.name] = export_selector(
                spec, documents[doc_path], record["role"])
        except ExportError as exc:
            errors.append(f"{spec.name}: {spec.document_path} {spec.pointer}: {exc}")
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
