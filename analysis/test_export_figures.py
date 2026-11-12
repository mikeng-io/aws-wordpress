"""Provenance, reproducibility and fail-closed checks; no AWS or site dependency."""
import contextlib
import copy
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import export_figures as exporter


class ExportFiguresTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        os.environ.pop("SOURCE_DATE_EPOCH", None)
        self.addCleanup(self.environment.stop)

    def test_pinned_artifacts_and_independent_pointer_resolution(self):
        dataset = exporter.build_dataset()
        selectors = dataset["selectors"]
        self.assertEqual(len(selectors), len(exporter.figures()))
        self.assertEqual(len(selectors), 21)
        self.assertEqual(list(selectors), sorted(selectors))
        self.assertEqual(dataset["produced_at"], "2026-10-29T09:46:10Z")
        for selector in selectors.values():
            raw = selector["raw"]
            node = json.loads((exporter.ROOT / raw["path"]).read_text())
            for token in raw["pointer"].split("/")[1:]:
                key = token.replace("~1", "/").replace("~0", "~")
                node = node[int(key)] if isinstance(node, list) else node[key]
            leaves = raw["value"] if isinstance(raw["value"], dict) and all(k.startswith("/") for k in raw["value"]) else None
            if leaves is None:
                self.assertEqual(node, raw["value"])
            else:  # multi-leaf selector: every recorded leaf resolves in the document
                for leaf, recorded in leaves.items():
                    leaf_node = node
                    for token in leaf.split("/")[1:]:
                        key = token.replace("~1", "/").replace("~0", "~")
                        leaf_node = leaf_node[int(key)] if isinstance(leaf_node, list) else leaf_node[key]
                    self.assertEqual(leaf_node, recorded)
        self.assertEqual(selectors["e0.warm.syscalls"]["value"], 4324)
        self.assertEqual(selectors["e0.warm.syscalls"]["raw"]["value"], 4324)
        self.assertEqual(selectors["e0.warm.syscalls"]["run_role"], "reference")
        self.assertEqual(selectors["e0.warm.stat"]["value"], 3921)
        self.assertEqual(selectors["e0.warm.enoent"]["value"], 1579)
        self.assertEqual(selectors["e0.warm.enoent"]["run"], exporter.E0)
        self.assertEqual(dataset["run_selection"][exporter.E0], {
            "role": "reference",
            "note": "Corrected catalog/cart n=10 census (aged n=3); counts, not latency.",
        })
        self.assertEqual(selectors["e4.hydrated.stat.p50"]["value"], 3.1)
        self.assertEqual(selectors["e4.hydrated.stat.p50"]["raw"]["value"], 3061)
        self.assertEqual(selectors["e5.efs.request.median"]["value"], [2.14, 2.09, 1.88])
        self.assertEqual(selectors["e5.efs.request.p99"]["value"], [164.07, 216.55, 151.33])
        self.assertEqual(selectors["e5.ebs.request.median"]["value"], [1.77, 1.63, 1.5])
        self.assertEqual(selectors["e5.efs_over_ebs.amortised"]["value"], [3.91, 4.43, 5.19])
        self.assertEqual(selectors["e5.rpc_per_stat.plain@1"]["value"],
                         [0.017195, 0.017335, 0.0173])
        self.assertEqual(selectors["e5.rpc_per_stat.tls@1"]["value"],
                         [0.017275, 0.01732, 0.017348333333333334])
        self.assertEqual(selectors["e5.lustre.slow_share@0.1"]["value"],
                         [0.256, 0.2314, 0.3347])
        self.assertEqual(selectors["e5.lustre.slow_share@1"]["value"],
                         [0.2377, 0.231, 0.2848])
        self.assertEqual(selectors["e5.lustre.slow_share@10"]["value"],
                         [0.275, 0.2733, 0.1567])
        self.assertEqual(selectors["e2.efs_over_block.stat"]["value"], 638.2)
        self.assertEqual(selectors["e2.efs_over_block.open_read"]["value"], 173.7)
        self.assertEqual({name for name, s in selectors.items() if s.get("derived")},
                         {"e2.efs_over_block.stat", "e2.efs_over_block.open_read"})

    def test_ineligible_and_unlisted_runs_are_rejected(self):
        base = next(spec for spec in exporter.figures() if spec.name == "e0.warm.syscalls")
        for run, expected in (
            ("results/E0/20260826T105956Z-c16d429", "superseded"),
            ("results/E0/not-listed", "not listed"),
        ):
            with self.subTest(run=run), patch.object(
                exporter, "figures", return_value=(replace(base, run=run),)
            ):
                with self.assertRaises(exporter.ExportError) as caught:
                    exporter.build_dataset()
                self.assertIn(run, str(caught.exception))
                self.assertIn(expected, str(caught.exception))

    def test_every_multi_element_selector_declares_a_valid_axis(self):
        selectors = exporter.build_dataset()["selectors"]
        for name, selector in selectors.items():
            if isinstance(selector["value"], (list, dict)):
                self.assertIn(selector.get("series_axis"), {"replication", "cadence"}, name)
        base = next(spec for spec in exporter.figures()
                    if spec.name == "e5.efs.request.median")
        document = exporter.load_json(exporter.ROOT, base.path)
        for axis in ("", "interval"):
            with self.subTest(axis=axis), self.assertRaises(exporter.ExportError):
                exporter.export_selector(replace(base, series_axis=axis), document)

    def test_rpc_replications_match_raw_leaves_in_pinned_order(self):
        selector = exporter.build_dataset()["selectors"]["e5.rpc_per_stat.plain@1"]
        document = exporter.load_json(
            exporter.ROOT, f"{exporter.E5}/analysis-pooled-3.json"
        )
        expected = [document["predictions"]["5"]["per_replication"][rep]
                    ["rpc_ops_per_stat"]["efs_host_plain@1"] for rep in exporter.E5_REPS]
        self.assertEqual(len(selector["value"]), 3)
        self.assertEqual(selector["value"], expected)
        self.assertEqual(list(selector["raw"]["value"].values()), expected)
        self.assertEqual(selector["series_axis"], "replication")
        self.assertIn("delta=1 s", selector["definition"])
        self.assertIn("three eligible formal-v3 replications in chronological order",
                      selector["definition"])

    def test_deterministic_bytes_and_index_digest(self):
        os.environ["SOURCE_DATE_EPOCH"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            exporter.write_outputs(exporter.build_dataset(), out)
            first = {p.name: p.read_bytes() for p in out.iterdir()}
            exporter.write_outputs(exporter.build_dataset(), out)
            self.assertEqual(first, {p.name: p.read_bytes() for p in out.iterdir()})
            index = json.loads(first["index.json"])["aws-fs.summary"]
            self.assertEqual(index, {
                "path": "src/data/figures/aws-fs.summary.json",
                "sha256": hashlib.sha256(first["aws-fs.summary.json"]).hexdigest(),
                "selectors": len(exporter.figures()),
            })

    def test_source_date_epoch_and_invalid_epoch(self):
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            self.assertEqual(exporter.produced_at(exporter.ROOT), "1970-01-01T00:00:00Z")
        for value in ("", "-1", "1.5", "tomorrow", "999999999999999999999999"):
            with self.subTest(epoch=value), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": value}):
                with self.assertRaises(exporter.ExportError):
                    exporter.produced_at(exporter.ROOT)

    def test_missing_artifacts_lists_every_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(exporter.ExportError) as caught:
                exporter.build_dataset(Path(directory))
        message = str(caught.exception)
        for spec in exporter.figures():
            self.assertIn(f"{spec.name}: {spec.path} {spec.pointer}", message)

    def test_missing_nested_pointers_fail_together_without_touching_outputs(self):
        original = exporter.load_json

        def damaged(root, path):
            document = copy.deepcopy(original(root, path))
            if path == f"{exporter.E2}/summary.json":
                del document["tiers"]["ec2/efs"]["stat"]["p50_ns"]
                del document["tiers"]["ec2/instance_store"]["open_read"]["p50_ns"]
            if path == f"{exporter.E5}/analysis-pooled-3.json":
                del document["predictions"]["9"]["per_replication"][exporter.E5_REPS[1]]["efs_per_request_ns"]["p99"]
            return document

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for name in (exporter.DATASET_FILE, "index.json"):
                (out / name).write_bytes(b"previous output\n")
            stderr = io.StringIO()
            with patch.object(exporter, "load_json", side_effect=damaged), contextlib.redirect_stderr(stderr):
                self.assertEqual(exporter.main(["--out", directory]), 1)
            for name in ("e2.efs.stat.p50", "e2.efs_over_block.stat",
                         "e2.efs_over_block.open_read", "e5.efs.request.p99"):
                self.assertIn(name, stderr.getvalue())
            self.assertIn("/tiers/ec2~1efs/stat/p50_ns", stderr.getvalue())
            self.assertIn("/efs_per_request_ns/p99", stderr.getvalue())
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, {
                exporter.DATASET_FILE: b"previous output\n", "index.json": b"previous output\n",
            })

    def test_values_follow_changed_artifact_and_format_boundaries(self):
        spec = next(s for s in exporter.figures() if s.name == "e2.efs.stat.p50")
        for ns, value, unit in ((999, 999, "ns"), (1000, 1.0, "us"),
                                (3061, 3.1, "us"), (999999, 1000.0, "us"),
                                (1000000, 1.0, "ms"), (2140186, 2.14, "ms")):
            document = {"tiers": {"ec2/efs": {"stat": {"p50_ns": ns}}}}
            result = exporter.export_selector(spec, document)
            self.assertEqual((result["value"], result["unit"]), (value, unit))
            self.assertEqual(result["raw"]["value"], ns)
        for bad in (None, "814301", True, -1, float("nan"), float("inf")):
            with self.subTest(value=bad), self.assertRaises(exporter.ExportError):
                exporter.export_selector(spec, {"tiers": {"ec2/efs": {"stat": {"p50_ns": bad}}}})

    def test_pointer_escaping_and_invalid_array_indices(self):
        document = {"a/b": {"~key": [7, 8]}, "~1": 9}
        self.assertEqual(exporter.resolve_pointer(document, "/a~1b/~0key/1"), 8)
        self.assertEqual(exporter.resolve_pointer(document, "/~01"), 9)
        self.assertIs(exporter.resolve_pointer(document, ""), document)
        for pointer in ("oops", "/a~2b", "/missing", "/a~1b/~0key/-1",
                        "/a~1b/~0key/01", "/a~1b/~0key/2"):
            with self.subTest(pointer=pointer), self.assertRaises(exporter.ExportError):
                exporter.resolve_pointer(document, pointer)

    def test_results_write_protection_including_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            alias = root / "alias"
            alias.symlink_to(results, target_is_directory=True)
            for out in (results, results / "subdirectory", alias):
                with self.assertRaises(exporter.ExportError):
                    exporter.write_outputs({}, out, root)
            out = root / "out"
            out.mkdir()
            (out / exporter.DATASET_FILE).symlink_to(results / "protected.json")
            with self.assertRaises(exporter.ExportError):
                exporter.write_outputs({}, out, root)
            self.assertEqual(list(results.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
