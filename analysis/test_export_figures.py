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
        self.assertEqual(len(selectors), 45)
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
                         {"e2.efs_over_block.stat", "e2.efs_over_block.open_read",
                          "e5.efs_over_ebs.median", "e5.efs_over_ebs.p99",
                          *{f"e2.cache_window.{tier}.{metric}"
                            for tier in exporter.CACHE_WINDOW_TIERS
                            for metric in ("create_pass_s", "fast_stat_share",
                                           "boundary_age_s")}})

    def test_pre_existing_selectors_are_byte_identical_to_golden(self):
        """The 21 selectors that existed before the cache-window/ladder additions
        must not move: value, unit, raw provenance and definition all pinned by a
        golden snapshot taken from the pre-change exporter."""
        golden = json.loads((exporter.ROOT /
                             "analysis/testdata/export-golden-21.json").read_text())
        self.assertEqual(len(golden), 21)
        selectors = exporter.build_dataset()["selectors"]
        for name, expected in golden.items():
            with self.subTest(selector=name):
                self.assertEqual(selectors[name], expected)

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
                self.assertIn(selector.get("series_axis"),
                              {"replication", "cadence", "percentile"}, name)
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
            self.assertIn(f"{spec.name}: {spec.document_path} {spec.pointer}", message)

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

    def test_e5_derived_ratios_computed_independently(self):
        selectors = exporter.build_dataset()["selectors"]
        document = exporter.load_json(
            exporter.ROOT, f"{exporter.E5}/analysis-pooled-3.json")
        per_rep = document["predictions"]["9"]["per_replication"]
        for leaf, expected in (("median", [1.21, 1.29, 1.25]),
                               ("p99", [88.7, 125.9, 87.6])):
            quotients = [per_rep[rep]["efs_per_request_ns"][leaf]
                         / per_rep[rep]["ebs_per_request_ns"][leaf]
                         for rep in exporter.E5_REPS]
            rounded = [round(q, 2) if q < 10 else round(q, 1) for q in quotients]
            self.assertEqual(rounded, expected)
            selector = selectors[f"e5.efs_over_ebs.{leaf}"]
            self.assertEqual(selector["value"], expected)
            self.assertEqual(selector["unit"], "ratio")
            self.assertEqual(selector["series_axis"], "replication")
            self.assertTrue(selector["derived"])
            self.assertEqual(list(selector["raw"]["value"].values()),
                             [per_rep[rep][f"{arm}_per_request_ns"][leaf]
                              for rep in exporter.E5_REPS
                              for arm in ("efs", "ebs")])

    def test_request_ladder_values_labels_and_raw_ns(self):
        selectors = exporter.build_dataset()["selectors"]
        document = exporter.load_json(
            exporter.ROOT, f"{exporter.E5}/analysis-pooled-3.json")
        per_rep = document["predictions"]["9"]["per_replication"]
        for index, rep in enumerate(exporter.E5_REPS, start=1):
            for arm in ("efs", "ebs"):
                raw = [per_rep[rep][f"{arm}_per_request_ns"][leaf]
                       for leaf in ("median", "amortised", "p99", "max")]
                expected = [float(f"{ns / 1000:.4g}") for ns in raw]
                selector = selectors[f"e5.{arm}.request.ladder@{index}"]
                with self.subTest(selector=selector):
                    self.assertEqual(selector["value"], expected)
                    self.assertEqual(selector["unit"], "us")
                    self.assertEqual(selector["series_axis"], "percentile")
                    self.assertEqual(selector["series_labels"],
                                     ["median", "mean (amortised)", "p99", "max"])
                    self.assertEqual(list(selector["raw"]["value"].values()), raw)

    def test_e4_stat_ladders_and_hydration(self):
        selectors = exporter.build_dataset()["selectors"]
        document = exporter.load_json(exporter.ROOT, f"{exporter.E4}/summary.json")
        for arm in ("efs", "hydrated"):
            raw = [document["pooled"][arm]["stat"][leaf]
                   for leaf in ("p50_ns", "p95_ns", "p99_ns")]
            selector = selectors[f"e4.{arm}.stat.ladder"]
            self.assertEqual(selector["value"],
                             [float(f"{ns / 1000:.4g}") for ns in raw])
            self.assertEqual(selector["series_axis"], "percentile")
            self.assertEqual(selector["series_labels"], ["p50", "p95", "p99"])
            self.assertEqual(selector["unit"], "us")
        self.assertEqual(selectors["e4.hydrated.stat.ladder"]["value"],
                         [3.061, 3.938, 6.023])
        self.assertEqual(selectors["e4.efs.stat.ladder"]["value"],
                         [1388, 1745, 5106])
        hydration = [rep["hydration_s"] for rep in document["per_replication"]]
        self.assertEqual(selectors["e4.hydration.seconds"]["value"],
                         [float(f"{v:.4g}") for v in hydration])
        self.assertEqual(selectors["e4.hydration.seconds"]["value"],
                         [0.2177, 0.4437, 0.4293])
        self.assertEqual(selectors["e4.hydration.seconds"]["series_axis"],
                         "replication")
        self.assertEqual(selectors["e4.hydration.bytes"]["value"], 27412480)
        self.assertEqual(selectors["e4.hydration.bytes"]["unit"], "bytes")

    def test_uniform_scalar_fails_closed_when_replications_disagree(self):
        spec = next(s for s in exporter.figures()
                    if s.name == "e4.hydration.bytes")
        document = exporter.load_json(exporter.ROOT, spec.document_path)
        document["per_replication"][1]["hydration_bytes"] += 1
        with self.assertRaises(exporter.ExportError):
            exporter.export_selector(spec, document)

    def test_cache_window_selectors_match_independent_derivation(self):
        import e2_cache_window
        selectors = exporter.build_dataset()["selectors"]
        derived = e2_cache_window.derive()
        for tier in exporter.CACHE_WINDOW_TIERS:
            reps = derived["tiers"][tier]["replications"]
            expected = {
                "create_pass_s": [float(f"{reps[r]['create_pass_s']:.4g}")
                                  for r in exporter.E2_FSX_REPS],
                "fast_stat_share": [
                    round(reps[r]["answered_local_share"] * 100, 1)
                    for r in exporter.E2_FSX_REPS],
                "boundary_age_s": [
                    None if reps[r]["boundary_age_s"] is None
                    else float(f"{reps[r]['boundary_age_s']:.4g}")
                    for r in exporter.E2_FSX_REPS],
            }
            for metric, values in expected.items():
                selector = selectors[f"e2.cache_window.{tier}.{metric}"]
                with self.subTest(selector=selector["definition"][:60]):
                    self.assertEqual(selector["value"], values)
                    self.assertEqual(selector["series_axis"], "replication")
                    self.assertTrue(selector["derived"])
                    self.assertEqual(
                        selector["raw"]["path"], exporter.CACHE_WINDOW_DOC)
            for metric in ("fast_stat_share", "boundary_age_s"):
                definition = selectors[
                    f"e2.cache_window.{tier}.{metric}"]["definition"]
                self.assertIn("post-hoc", definition)
                self.assertIn("15-30 us", definition)
                self.assertIn("registered", definition)
                self.assertIn("ONTAP", definition)
                self.assertIn("Lustre", definition)
        self.assertEqual(
            selectors["e2.cache_window.efs.create_pass_s"]["value"],
            [7.173, 6.502, 7.122])
        self.assertEqual(
            selectors["e2.cache_window.efs.fast_stat_share"]["value"],
            [33.5, 37.8, 30.9])
        self.assertEqual(
            selectors["e2.cache_window.efs.boundary_age_s"]["value"],
            [2.383, 2.484, 2.299])
        self.assertEqual(
            selectors["e2.cache_window.fsx_ontap.fast_stat_share"]["value"],
            [100.0, 100.0, 100.0])
        self.assertEqual(
            selectors["e2.cache_window.fsx_lustre.fast_stat_share"]["value"],
            [0.0, 0.0, 0.0])
        self.assertNotIn(
            "defined",
            selectors["e2.cache_window.fsx_lustre.fast_stat_share"])
        self.assertEqual(
            selectors["e2.cache_window.fsx_ontap.boundary_age_s"]["value"],
            [0.9926, 0.9654, 0.9863])
        # The one truly undefined metric: Lustre answered nothing locally.
        selector = selectors["e2.cache_window.fsx_lustre.boundary_age_s"]
        self.assertEqual(selector["value"], [None, None, None])
        self.assertFalse(selector["defined"])
        self.assertIn("no stat sample", selector["undefined_reason"])
        # The raw leaf the fast_stat_share selector now reads.
        self.assertEqual(
            selectors["e2.cache_window.fsx_ontap.fast_stat_share"]
            ["raw"]["value"],
            {"/rep-1/answered_local_share": 1.0,
             "/rep-2/answered_local_share": 1.0,
             "/rep-3/answered_local_share": 1.0})

    def test_derived_document_verification_fails_closed(self):
        original = exporter.load_json
        spec = next(s for s in exporter.figures()
                    if s.name == "e2.cache_window.efs.create_pass_s")
        base = original(exporter.ROOT, spec.document_path)
        bad_sha = copy.deepcopy(base)
        bad_sha["inputs"][next(iter(bad_sha["inputs"]))] = "0" * 64
        wrong_run = copy.deepcopy(base)
        wrong_run["run"] = "results/E2/20260910T163206Z-66dcff8"
        missing_input = copy.deepcopy(base)
        missing_input["inputs"]["results/E2/none.csv"] = "0" * 64
        renamed_reps = copy.deepcopy(base)
        for tier in renamed_reps["tiers"].values():
            tier["replications"] = {
                key.replace("rep-", "run-"): value
                for key, value in tier["replications"].items()}
        for variant, expected in (
            (bad_sha, "sha256"),
            (wrong_run, "does not match"),
            (missing_input, "none.csv"),
            (renamed_reps, "missing JSON pointer"),
        ):
            with self.subTest(expected=expected), patch.object(
                exporter, "load_json",
                side_effect=lambda root, path, v=variant: (
                    v if path == exporter.CACHE_WINDOW_DOC else original(root, path))
            ), self.assertRaises(exporter.ExportError) as caught:
                exporter.build_dataset()
            self.assertIn(expected, str(caught.exception))

    def test_untampered_raw_csv_still_matches_derived_manifest(self):
        """Guard that the committed manifest really does pin the raw CSVs: every
        recorded sha256 resolves to a file that hashes identically right now."""
        document = exporter.load_json(exporter.ROOT, exporter.CACHE_WINDOW_DOC)
        self.assertEqual(len(document["inputs"]), 12)
        spec = next(s for s in exporter.figures()
                    if s.name == "e2.cache_window.efs.create_pass_s")
        exporter.verify_derived_document(exporter.ROOT, document, spec)


if __name__ == "__main__":
    unittest.main()
