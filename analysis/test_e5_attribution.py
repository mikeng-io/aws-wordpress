"""Regression checks for the phase-attributed E5 method; no AWS or Docker calls."""
import contextlib
import gzip
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import e5_selftest as fixture
import e5_stats as g


class AttributionTests(unittest.TestCase):
    def test_deployed_lustre_counter_names_from_frozen_pilot(self):
        td = (Path(__file__).resolve().parents[1] / "results/E5/20261026T152946Z-b1efcb2"
              / "rep-1/ec2/fsx_lustre")
        pre = g.lustre_counters(td / "A1.pre.lustre")
        post = g.lustre_counters(td / "A1.post.lustre")
        self.assertEqual(g.delta(pre, post, "ldlm_ibits_enqueue"), 1041)
        self.assertEqual(g.delta(pre, post, "mds_getattr"), 0)
        self.assertEqual(g.check_signature("fsx_lustre", "A1", td, 1000)[0], "PASS")

    @classmethod
    def setUpClass(cls):
        cls.seed = tempfile.TemporaryDirectory()
        cls.base = Path(cls.seed.name) / "rep-1"
        fixture.write_rep(cls.base, fixture.base_world())

    @classmethod
    def tearDownClass(cls):
        cls.seed.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.rep = self.run / "rep-1"
        shutil.copytree(self.base, self.rep)
        self.td = self.rep / "ec2" / "efs_host_plain"
        self.req = self.td / "B-1.req.csv.gz"

    def cell(self):
        return g.cohort_b_cell("efs_host_plain", "1", self.td)

    def edit_rows(self, transform):
        with gzip.open(self.req, "rt") as f:
            text = f.read()
        with gzip.open(self.req, "wt") as f:
            f.write(transform(text))

    def test_positive_negative_attribution_is_separate(self):
        cell = self.cell()
        self.assertEqual(cell["status"], "OK")
        self.assertAlmostEqual(cell["rpc_ops_per_stat"], .017)
        self.assertAlmostEqual(cell["rpc_ops_per_enoent"], .0085)
        self.assertNotIn("miss_fraction_ci95", cell)
        self.assertEqual(sum(cell["rpc_ops_per_request"]), 1700)

    def test_latency_noise_is_diagnostic_and_p5_uses_counters(self):
        world = fixture.base_world()
        world["b"][("efs_host_plain", "1")]["miss"] = .20
        fixture.write_rep(self.rep, world)
        cell = self.cell()
        self.assertEqual(cell["status"], "OK")
        self.assertEqual(cell["xcheck"]["status"], "DISAGREE")
        self.assertEqual(g.p5({}, g.cohort_b(self.rep))["grade"], g.S)
        self.assertEqual(g.p10({}, g.cohort_b(self.rep))["grade"], g.S)

    def test_rates_above_one_are_not_clamped_probabilities(self):
        world = fixture.base_world()
        world["b"][("efs_host_plain", "1")]["counter"] = 1.2
        fixture.write_rep(self.rep, world)
        self.assertEqual(self.cell()["rpc_ops_per_stat"], 1.2)

    def test_legacy_data_is_explicitly_ineligible(self):
        self.edit_rows(lambda s: s.replace("method=rpc-phases-v2", "method=legacy"))
        self.assertIn("legacy/unattributed", self.cell()["reason"])

    def test_missing_phase_counts_fail(self):
        self.edit_rows(lambda s: s.replace(":0:0", "", 1))
        self.assertEqual(self.cell()["status"], "ERROR")

    def test_counter_reset_fails(self):
        p = self.td / "B-1.mountstats.end"
        p.write_text(p.read_text().replace("GETATTR: 3450", "GETATTR: 0"))
        self.assertEqual(self.cell()["status"], "ERROR")

    def test_missing_required_counter_fails(self):
        p = self.td / "B-1.mountstats.end"
        p.write_text(p.read_text().replace("GETATTR:", "UNKNOWN:"))
        self.assertIn("missing required", self.cell()["reason"])

    def test_window_disagreement_fails(self):
        p = self.td / "B-1.mountstats.end"
        p.write_text(p.read_text().replace("GETATTR: 3450", "GETATTR: 3451"))
        self.assertIn("disagree", self.cell()["reason"])

    def test_wrong_mount_fails(self):
        p = self.td / "B-1.mountstats.end"
        p.write_text(p.read_text().replace("/bench/efs_host_plain.ss-1", "/other"))
        self.assertIn("measurement mount", self.cell()["reason"])

    def test_duplicate_mount_sections_fail(self):
        p = self.td / "B-1.mountstats.end"
        p.write_text(p.read_text() * 2)
        self.assertEqual(self.cell()["status"], "ERROR")

    def test_truncated_window_fails(self):
        self.edit_rows(lambda s: "\n".join(s.splitlines()[:-1]) + "\n")
        self.assertIn("request count", self.cell()["reason"])

    def test_wrong_phase_boundary_fails(self):
        self.edit_rows(lambda s: s.replace("2,m,", "2,w,"))
        self.assertIn("boundary", self.cell()["reason"])

    def test_wrong_histogram_count_fails(self):
        self.edit_rows(lambda s: s.replace(":1000,", ":999,", 1))
        self.assertIn("histogram operations", self.cell()["reason"])

    def test_negative_timing_fails(self):
        self.edit_rows(lambda s: s.replace(",10000\n", ",-1\n", 1))
        self.assertIn("negative request timing", self.cell()["reason"])

    def test_wrong_probe_mount_is_unknown(self):
        p = self.td / "D-1.post.mountstats"
        p.write_text(p.read_text().replace("/bench/efs_host_plain.ss-1", "/other"))
        self.assertEqual(self.cell()["expiry_probe"]["state"], "UNKNOWN")

    def test_duplicate_histogram_bins_fail(self):
        self.edit_rows(lambda s: s.replace(":1000,", ":1000|0:0,", 1).replace("|0:0", "|26:0", 1))
        # Fixture's 2 us warm stat uses bin 26; duplicate bins are invalid even
        # when the duplicate carries no observations.
        self.assertEqual(self.cell()["status"], "ERROR")

    def test_short_probe_does_not_prove_delegations_or_timer_model(self):
        (self.td / "D-1.idle-seconds").write_text("2.0")
        self.assertEqual(self.cell()["expiry_probe"]["state"], "UNKNOWN")
        self.assertEqual(g.p5({}, g.cohort_b(self.rep))["grade"], g.E)

    def test_missing_probe_does_not_veto_measured_cost(self):
        (self.td / "D-1.csv").unlink()
        cell = self.cell()
        self.assertEqual(cell["status"], "OK")
        self.assertEqual(cell["expiry_probe"]["state"], "UNKNOWN")
        b = g.cohort_b(self.rep)
        self.assertEqual(g.p5({}, b)["grade"], g.E)
        self.assertEqual(g.p9({}, b)["grade"], g.S)

    def test_suppression_excludes_timer_model_instead_of_refuting_it(self):
        (self.td / "D-1.post.mountstats").write_text((self.td / "D-1.pre.mountstats").read_text())
        cell = self.cell()
        self.assertEqual(cell["expiry_probe"]["state"], "REVALIDATION_SUPPRESSED")
        self.assertEqual(g.p5({}, g.cohort_b(self.rep))["grade"], g.E)

    def test_mixed_probe_is_unknown(self):
        p = self.td / "D-1.post.mountstats"
        p.write_text(p.read_text().replace("GETATTR: 1900", "GETATTR: 1400"))
        self.assertEqual(self.cell()["expiry_probe"]["state"], "UNKNOWN")

    def test_probe_checks_operation_identity(self):
        p = self.td / "D-1.csv"
        p.write_text(p.read_text().replace("D-1,stat,0", "A1,stat,0"))
        self.assertEqual(self.cell()["expiry_probe"]["state"], "UNKNOWN")

    def test_p6_reports_behaviour_without_causal_delegation_claim(self):
        pred = g.p6({}, g.cohort_b(self.rep))
        self.assertEqual(pred["grade"], g.S)
        self.assertEqual(pred["expiry_probes"]["1"]["state"], "REVALIDATION_SUPPRESSED")
        self.assertIn("no causal", pred["note"])

    def test_lustre_latency_is_ineligible_with_overlapping_control_noise(self):
        world = fixture.base_world()
        world["b"][("ebs", "1")].update(miss=.02, miss_ns=150000)
        fixture.write_rep(self.rep, world)
        self.assertEqual(g.p7({}, g.cohort_b(self.rep))["grade"], g.E)

    def test_physically_truncated_gzip_is_reported_as_cell_error(self):
        data = self.req.read_bytes()
        self.req.write_bytes(data[:-8])
        with contextlib.redirect_stdout(io.StringIO()):
            g.main(self.run)
        report = json.loads((self.run / "summary.json").read_text())
        self.assertEqual(report["cohorts"]["rep-1"]["b"]["efs_host_plain"]["1"]["status"], "ERROR")

    def test_malformed_input_still_produces_json_and_markdown(self):
        self.edit_rows(lambda s: s + "broken\n")
        with contextlib.redirect_stdout(io.StringIO()):
            g.main(self.run)
        report = json.loads((self.run / "summary.json").read_text())
        self.assertEqual(report["cohorts"]["rep-1"]["b"]["efs_host_plain"]["1"]["status"], "ERROR")
        self.assertIn("bad per-request column count", (self.run / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
