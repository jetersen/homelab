import importlib.util
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "controller_schedule", Path(__file__).with_name("controller-schedule.py")
)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


def plan(phase="Completed", generation=2, observed=2):
    return {
        "metadata": {"generation": generation},
        "status": {"phase": phase, "observedGeneration": observed},
    }


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        output = patch("builtins.print")
        output.start()
        self.addCleanup(output.stop)

    def test_sleep_requires_both_current_plans_to_complete(self):
        for incomplete in (
            plan(phase="Upgrading"),
            plan(phase="Failed"),
            plan(phase="Pending"),
            plan(generation=3),
            {"metadata": {"generation": 2}},
        ):
            for plans in ([plan(), incomplete], [incomplete, plan()]):
                with self.subTest(plans=plans):
                    request = Mock(side_effect=plans)
                    schedule.run("sleep", request)
                    self.assertEqual(request.call_count, 2)

    def test_missing_plan_fails_without_scaling(self):
        error = urllib.error.HTTPError("", 404, "", {}, None)
        self.addCleanup(error.close)
        request = Mock(side_effect=[plan(), error])
        with self.assertRaises(urllib.error.HTTPError):
            schedule.run("sleep", request)
        self.assertEqual(request.call_count, 2)

    def test_completed_plans_scale_down_with_concurrency_guard(self):
        scale = {"metadata": {"resourceVersion": "123"}, "spec": {"replicas": 1}}
        request = Mock(side_effect=[plan(), plan(), scale, {}])
        schedule.run("sleep", request)
        body = request.call_args.args[1]
        self.assertEqual(body["spec"]["replicas"], 0)
        self.assertEqual(body["metadata"]["resourceVersion"], "123")

    def test_wake_does_not_wait_for_plan_status(self):
        request = Mock(side_effect=[{"spec": {"replicas": 0}}, {}])
        schedule.run("wake", request)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[1]["spec"]["replicas"], 1)


if __name__ == "__main__":
    unittest.main()
