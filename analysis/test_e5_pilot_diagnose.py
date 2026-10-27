"""Scheduling lower-bound checks: deterministic, offline, no timing sleeps."""
import unittest

from e5_pilot_diagnose import scheduling


def row(k, late=0, stat=20, enoent=10, counter=0):
    return dict(k=k, phase="m", late=late, stat_sum=stat,
                enoent_sum=enoent, counter_ns=counter)


class SchedulingTests(unittest.TestCase):
    def summarize(self, rows):
        return scheduling(dict(delta_ns="100", measured_requests=str(len(rows))), rows)

    def test_single_overrun_propagates_and_backlog_drains(self):
        out = self.summarize([row(0, stat=180, enoent=0), row(1, late=80), row(2, late=10)])
        self.assertEqual(out["syscall_sum_over_interval"], 1)
        self.assertEqual(out["late_over_half_interval"], 1)
        self.assertEqual(out["following_late_forced_by_syscall_lower_bound"], 1)
        self.assertEqual(out["lower_bound_violations"], 0)

    def test_late_start_alone_is_not_evidence_of_long_work(self):
        out = self.summarize([row(0), row(1, late=90)])
        self.assertEqual(out["late_over_half_interval"], 1)
        self.assertEqual(out["syscall_sum_over_interval"], 0)
        self.assertEqual(out["following_late_forced_by_syscall_lower_bound"], 0)

    def test_exact_half_interval_and_exact_service_interval_are_not_over(self):
        out = self.summarize([row(0, late=50, stat=90), row(1, late=50)])
        self.assertEqual(out["late_over_half_interval"], 0)
        self.assertEqual(out["syscall_sum_over_interval"], 0)

    def test_impossible_next_start_is_visible(self):
        out = self.summarize([row(0, stat=200), row(1)])
        self.assertEqual(out["lower_bound_violations"], 1)

    def test_counter_overhead_is_not_confused_with_syscall_work(self):
        out = self.summarize([row(0, counter=200), row(1, late=130)])
        self.assertEqual(out["syscall_sum_over_interval"], 0)
        self.assertEqual(out["counter_ns"]["max"], 200)

    def test_warmup_is_excluded(self):
        warm = row(0, stat=9999)
        warm["phase"] = "w"
        out = scheduling(dict(delta_ns="100", measured_requests="1"), [warm, row(1)])
        self.assertEqual(out["requests"], 1)
        self.assertEqual(out["syscall_sum_over_interval"], 0)

    def test_missing_requests_and_negative_timings_fail(self):
        with self.assertRaises(ValueError):
            scheduling(dict(delta_ns="100", measured_requests="2"), [row(0)])
        with self.assertRaises(ValueError):
            self.summarize([row(0), row(2)])
        with self.assertRaises(ValueError):
            self.summarize([row(0, counter=-1)])


if __name__ == "__main__":
    unittest.main()
