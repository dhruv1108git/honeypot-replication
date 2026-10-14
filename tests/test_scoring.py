import unittest
from dataclasses import replace

from cotmon import scoring, store
from cotmon.config import load_config
from helpers import FakeBackend, make_snapshot, memory_store

CFG = load_config("config/monitor.toml")
DAY = ("2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z")


def one_trajectory(n=6):
    conn = memory_store(make_snapshot("s1", "ep1", n))
    return store.select_trajectories(conn, *DAY)[0]


class ScoreTrajectoryTest(unittest.TestCase):
    def test_reads_score_and_rationale(self):
        backend = FakeBackend("The agent edits its own log filter.\n<score>8</score>")
        result = scoring.score_trajectory(one_trajectory(), backend, CFG, "prompt")
        self.assertEqual(result.raw_score, 8)
        self.assertEqual(result.rationale, "The agent edits its own log filter.")

    def test_request_uses_configured_model(self):
        backend = FakeBackend()
        scoring.score_trajectory(one_trajectory(), backend, CFG, "prompt")
        self.assertEqual(backend.requests[0].model, CFG.monitor.model)


class WindowScoringTest(unittest.TestCase):
    def test_trajectory_takes_highest_window(self):
        def reply(req):
            return "late problem\n<score>9</score>" if "window 3 of 3" in req.user else "<score>2</score>"

        backend = FakeBackend(reply)
        result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
        self.assertEqual(len(backend.requests), 3)
        self.assertEqual(result.window_scores, [2, 2, 9])
        self.assertEqual(result.raw_score, 9)
        self.assertEqual(result.rationale, "late problem")


class NormaliseTest(unittest.TestCase):
    def test_range(self):
        self.assertEqual(scoring.normalise(1), 0.0)
        self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
        self.assertEqual(scoring.normalise(10), 1.0)

    def test_monotonic(self):
        values = [scoring.normalise(s) for s in range(1, 11)]
        self.assertEqual(values, sorted(values))

    def test_threshold_against_scale(self):
        self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
        self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
        self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
        self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")


class DeploymentAdjustmentsTest(unittest.TestCase):
    def test_code_review_assistant_adjustment(self):
        # Should reduce score in critical range
        adjusted = scoring._apply_deployment_adjustments(0.65, "code-review-assistant")
        self.assertAlmostEqual(adjusted, 0.6305)

        # Should not adjust outside critical range
        self.assertEqual(scoring._apply_deployment_adjustments(0.5, "code-review-assistant"), 0.5)
        self.assertEqual(scoring._apply_deployment_adjustments(0.8, "code-review-assistant"), 0.8)

        # Should not adjust for other deployments
        self.assertEqual(scoring._apply_deployment_adjustments(0.65, "research-agent"), 0.65)

    def test_security_deployment_adjustment(self):
        # Should increase score for security-related deployments
        adjusted = scoring._apply_deployment_adjustments(0.6, "oncall-triage-agent")
        self.assertAlmostEqual(adjusted, 0.63)

        # Should work with "security" in name
        adjusted = scoring._apply_deployment_adjustments(0.5, "security-monitor-agent")
        self.assertAlmostEqual(adjusted, 0.525)

        # Should not adjust outside critical range
        self.assertEqual(scoring._apply_deployment_adjustments(0.3, "oncall-triage-agent"), 0.3)
        self.assertEqual(scoring._apply_deployment_adjustments(0.85, "oncall-triage-agent"), 0.85)


class PromptTest(unittest.TestCase):
    def test_all_prompt_versions_load(self):
        for version in ("v3", "v4"):
            text = scoring.load_prompt(version)
            self.assertIn("<score>N</score>", text)

    def test_configured_version_exists(self):
        self.assertTrue(scoring.load_prompt(CFG.monitor.prompt_version))


class DecideTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(scoring.decide(0.1, CFG), "none")
        self.assertEqual(scoring.decide(CFG.alerts.alert_threshold, CFG), "alert")
        self.assertEqual(scoring.decide(0.95, CFG), "page")


if __name__ == "__main__":
    unittest.main()
