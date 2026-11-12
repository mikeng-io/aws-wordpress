"""Cache-window derivation: expected values computed independently from the raw
CSVs, fail-closed behaviour on malformed inputs, and determinism."""
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

import e2_cache_window as window
import e3_clusters


ROOT = Path(__file__).resolve().parents[1]


def load_op(path: Path, op: str) -> list[int]:
    values = []
    for row in csv.reader(path.open()):
        if len(row) == 2 and row[0] == op and row[1].strip().isdigit():
            values.append(int(row[1]))
    return values


class CacheWindowTests(unittest.TestCase):
    def test_derived_values_recomputed_independently(self):
        """Expected numbers come from reading the raw CSVs here, not from any
        function inside e2_cache_window."""
        document = window.derive()
        self.assertEqual(document["run"], window.RUN)
        self.assertEqual(len(document["inputs"]), 12)
        for tier, arm_tier in window.TIERS.items():
            arm, name = arm_tier.split("/")
            reps = document["tiers"][tier]["replications"]
            self.assertEqual(list(reps), ["rep-1", "rep-2", "rep-3"])
            for rep, entry in reps.items():
                csv_path = ROOT / window.RUN / rep / arm / f"{name}.csv"
                create = load_op(csv_path, "create")
                stat = load_op(csv_path, "stat")
                self.assertEqual(len(create), 1000)
                self.assertEqual(len(stat), 1000)
                self.assertAlmostEqual(entry["create_pass_s"],
                                       sum(create) / 1e9, places=12)
                lo, _, c_lo, c_hi = e3_clusters.kmeans2_log(stat)
                share = len(lo) / len(stat)
                bimodal = (share >= e3_clusters.MIN_CLUSTER_SHARE
                           and (1 - share) >= e3_clusters.MIN_CLUSTER_SHARE
                           and c_hi - c_lo >= e3_clusters.MIN_LOG10_SEPARATION)
                self.assertEqual(entry["bimodal"], bimodal, (tier, rep))
                if bimodal:
                    fast = [abs(math.log10(v) - c_lo)
                            <= abs(math.log10(v) - c_hi) for v in stat]
                    oldest = fast.index(True)
                    self.assertEqual(entry["fast_stat_share"], share)
                    self.assertEqual(entry["oldest_fast_index"], oldest)
                    self.assertAlmostEqual(
                        entry["boundary_age_s"],
                        sum(create[oldest + 1:]) / 1e9, places=12)
                    self.assertEqual(
                        entry["slow_in_tail"],
                        sum(1 for f in fast[oldest:] if not f))
                else:
                    self.assertIsNone(entry["fast_stat_share"])
                    self.assertIsNone(entry["boundary_age_s"])
                    self.assertIsNone(entry["oldest_fast_index"])
                    self.assertIn("unimodal", entry["undefined_reason"])

    def test_pinned_values_and_committed_file(self):
        """The committed derived file is what derive() produces, and the numbers
        land inside the ranges the finding states in prose."""
        document = window.derive()
        committed = json.loads((ROOT /
            "analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json")
            .read_text())
        self.assertEqual(committed, document)
        efs = document["tiers"]["efs"]["replications"]
        self.assertEqual([round(e["create_pass_s"], 3) for e in efs.values()],
                         [7.173, 6.502, 7.122])
        self.assertEqual([e["fast_stat_share"] for e in efs.values()],
                         [0.335, 0.378, 0.309])
        self.assertEqual([round(e["boundary_age_s"], 3) for e in efs.values()],
                         [2.383, 2.484, 2.299])
        openzfs = document["tiers"]["fsx_openzfs"]["replications"]
        self.assertEqual([e["fast_stat_share"] for e in openzfs.values()],
                         [0.696, 0.689, 0.679])
        self.assertEqual([round(e["boundary_age_s"], 3) for e in openzfs.values()],
                         [2.906, 2.922, 2.921])
        # The one recorded contiguity exception in the run: a single slow stat
        # inside openzfs rep-1's fast tail, kept rather than smoothed over.
        self.assertEqual(openzfs["rep-1"]["slow_in_tail"], 1)
        for tier in ("fsx_ontap", "fsx_lustre"):
            for entry in document["tiers"][tier]["replications"].values():
                self.assertFalse(entry["bimodal"])
                self.assertIsNone(entry["fast_stat_share"])
                self.assertIsNone(entry["boundary_age_s"])

    def test_derive_fails_closed_on_missing_and_malformed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(window.DeriveError):
                window.derive(Path(directory))
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.csv"
            with self.assertRaises(window.DeriveError):
                window.derive_rep(missing)
        with tempfile.TemporaryDirectory() as directory:
            short_stat = Path(directory) / "tier.csv"
            with short_stat.open("w") as fh:
                for _ in range(4):
                    fh.write("create,1000000\n")
                for _ in range(3):
                    fh.write("stat,2000\n")
            with self.assertRaises(window.DeriveError) as caught:
                window.derive_rep(short_stat)
            self.assertIn("file order", str(caught.exception))
            zero = Path(directory) / "zero.csv"
            with zero.open("w") as fh:
                fh.write("create,1000000\nstat,0\n")
            with self.assertRaises(window.DeriveError):
                window.derive_rep(zero)

    def test_contiguity_violations_are_recorded_not_corrected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tier.csv"
            with path.open("w") as fh:
                for _ in range(100):
                    fh.write("create,1000000\n")
                # 70 slow, then a fast tail - but two fast rows planted early.
                stats = ([1500] * 2 + [800000] * 70 + [1500] * 28)
                for ns in stats:
                    fh.write(f"stat,{ns}\n")
            entry = window.derive_rep(path)
            self.assertTrue(entry["bimodal"])
            self.assertEqual(entry["oldest_fast_index"], 0)
            self.assertEqual(entry["slow_in_tail"], 70)
            self.assertAlmostEqual(entry["fast_stat_share"], 0.30)
            # boundary_age_s is still the rule's value, not a repaired one.
            self.assertAlmostEqual(entry["boundary_age_s"], 0.099)
            self.assertAlmostEqual(entry["create_pass_s"], 0.1)

    def test_derive_and_output_are_deterministic(self):
        first = window.derive()
        self.assertEqual(first, window.derive())
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "derived.json"
            window.write_output(first, out)
            one = out.read_bytes()
            window.write_output(window.derive(), out)
            self.assertEqual(out.read_bytes(), one)

    def test_write_output_refuses_results(self):
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results"
            results.mkdir()
            with self.assertRaises(window.DeriveError):
                window.write_output({}, results / "x.json", Path(directory))


if __name__ == "__main__":
    unittest.main()
