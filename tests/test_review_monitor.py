"""Only monitor cache behavior; no server/model requests."""
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "review_monitor", Path(__file__).resolve().parents[1] / "scripts/watch_review_batch.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class ReviewMonitorTests(unittest.TestCase):
    def test_prior_failure_never_hides_a_resumed_workspace(self):
        for status in ("blocked", "partial"):
            result = {"status": status, "error_code": "old_failure"}
            self.assertTrue(monitor.should_read_workspace(
                {"status": "prepared", "execution": result}, json.dumps(result, sort_keys=True)))

    def test_only_unchanged_success_is_cached(self):
        for status in ("completed", "idle"):
            result = {"status": status}
            self.assertFalse(monitor.should_read_workspace(
                {"status": "completed", "execution": result}, json.dumps(result, sort_keys=True)))
            self.assertTrue(monitor.should_read_workspace(
                {"status": "completed", "execution": result}, None))
        self.assertFalse(monitor.should_read_workspace({"status": "open"}, None))
        self.assertTrue(monitor.should_read_workspace({"status": "running"}, None))
