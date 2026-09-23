import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Cognition.jev.decider import BEHAVIORS, build_questions, decide, legal_behaviors
from Cognition.jev.jev_client import JevClient, normalize_answers
from Cognition.jev.jev_decider import JevDeciderService, TOPIC_COLLISION, TOPIC_DECISION, TOPIC_EDGE
from Cognition.jev.state_builder import build_state

NOW = 1000.0

RAW_RESPONSE = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 300, "output_tokens": 0},
    "answers": {
        "behavior": {
            "type": "choice", "choice": "scan_left", "confidence": 0.8,
            "probabilities": {"scan_left": 0.8, "rest": 0.2},
        },
        "hazard_ahead": {"type": "noul", "noul": 0.1},
        "interest": {
            "type": "score", "score": 1.4, "confidence": 0.6,
            "legend": {"0": "a", "1": "b", "2": "c"},
            "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
        },
        "future": {"type": "ranking", "order": []},
    },
}


def result(choice, confidence=0.9, hazard=0.1):
    return {
        "answers": {
            "behavior": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {}},
            "hazard_ahead": {"type": "noul", "noul": hazard},
        },
        "model": "jev-1.13.0",
        "latency_ms": 120,
    }


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeJev:
    def __init__(self, response):
        self.response = response
        self.last_error = None
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        return self.response


class FakeMQTT:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        self.messages.append((topic, json.loads(payload)))


class LegalBehaviorTests(unittest.TestCase):
    def test_all_behaviors_legal_when_clear(self):
        self.assertEqual(legal_behaviors({"edge": {"blocked_prob": 0.1}}, NOW), list(BEHAVIORS))

    def test_forward_masked_when_blocked(self):
        legal = legal_behaviors({"edge": {"blocked_prob": 0.7}}, NOW)
        self.assertNotIn("explore_forward", legal)
        self.assertNotIn("approach_target", legal)
        self.assertIn("back_off", legal)

    def test_forward_masked_after_recent_collision(self):
        self.assertNotIn("explore_forward", legal_behaviors({"last_collision_ts": NOW - 1.0}, NOW))
        self.assertIn("explore_forward", legal_behaviors({"last_collision_ts": NOW - 5.0}, NOW))

    def test_forward_masked_when_looming(self):
        self.assertNotIn("explore_forward", legal_behaviors({"sensory": {"looming": 0.8}}, NOW, 0.72))

    def test_questions_only_offer_legal_behaviors(self):
        questions = build_questions(["scan_left", "rest"])
        self.assertEqual(set(questions["behavior"]["criteria"]), {"scan_left", "rest"})
        self.assertEqual(questions["hazard_ahead"]["type"], "noul")
        self.assertEqual(questions["interest"]["type"], "score")


class DecideTests(unittest.TestCase):
    def test_confident_legal_choice_is_proposed(self):
        decision = decide(result("scan_left"), list(BEHAVIORS), 0.55, now=NOW)
        self.assertEqual(decision["behavior"], "scan_left")
        self.assertEqual(decision["ts"], NOW)
        self.assertEqual(decision["model"], "jev-1.13.0")

    def test_low_confidence_is_silent(self):
        self.assertIsNone(decide(result("scan_left", confidence=0.4), list(BEHAVIORS), 0.55))

    def test_other_and_illegal_are_silent(self):
        self.assertIsNone(decide(result("other"), list(BEHAVIORS)))
        self.assertIsNone(decide(result("explore_forward"), ["scan_left", "rest"]))

    def test_hazard_vetoes_forward_only(self):
        self.assertIsNone(decide(result("explore_forward", hazard=0.9), list(BEHAVIORS)))
        self.assertIsNotNone(decide(result("back_off", hazard=0.9), list(BEHAVIORS)))

    def test_failed_call_is_silent(self):
        self.assertIsNone(decide(None, list(BEHAVIORS)))


class StateBuilderTests(unittest.TestCase):
    def test_state_summarizes_snapshot(self):
        state = build_state({
            "edge": {"blocked_prob": 0.62, "motor_running": True},
            "sensory": {"motion_left": 0.4, "motion_right": 0.1, "looming": 0.3, "luminance": 0.5},
            "survival": {"drives": {"novelty": {"level": 0.812, "urgent": True}}, "dominant_drive": "novelty"},
            "scene": {"summary": "人が手を振っている", "people": 1, "timestamp": NOW - 5},
            "body": {"cpu_temp": 78.0},
            "last_collision_ts": NOW - 3.0,
            "recent_behaviors": ["scan_left", "rest"],
        }, NOW)
        self.assertEqual(state["path_ahead"]["assessment"], "blocked")
        self.assertEqual(state["vision"]["motion_balance"], "more motion on the left")
        self.assertEqual(state["vision"]["approaching_object"], "possible")
        self.assertEqual(state["drives"]["novelty"], {"level": 0.81, "urgent": True})
        self.assertEqual(state["people_visible"], 1)
        self.assertEqual(state["body"]["thermal"], "hot")
        self.assertEqual(state["seconds_since_collision"], 3.0)
        self.assertEqual(state["recent_behaviors_oldest_first"], ["scan_left", "rest"])
        json.dumps(state)  # must be JSON-serializable for the API

    def test_stale_scene_is_dropped(self):
        state = build_state({"scene": {"summary": "old", "timestamp": NOW - 120}}, NOW)
        self.assertNotIn("scene_summary", state)


class ClientTests(unittest.TestCase):
    def test_normalizes_answers_and_skips_unknown_types(self):
        answers = normalize_answers(RAW_RESPONSE)
        self.assertEqual(answers["behavior"]["choice"], "scan_left")
        self.assertEqual(answers["hazard_ahead"]["noul"], 0.1)
        self.assertEqual(answers["interest"]["score"], 1.4)
        self.assertNotIn("future", answers)

    def test_request_wire_format(self):
        session = FakeSession([FakeResponse(200, RAW_RESPONSE)])
        client = JevClient("key", "jev-1.13.0", base_url="https://api.example/", timeout=1.0, session=session)
        out = client.system_one({"a": 1}, {"q": {"type": "noul"}})
        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.example/v1/systemone")
        self.assertEqual(call["headers"]["Authorization"], "Bearer key")
        self.assertEqual(call["json"], {"state": {"a": 1}, "model": "jev-1.13.0", "questions": {"q": {"type": "noul"}}})
        self.assertEqual(call["timeout"], 1.0)
        self.assertEqual(out["model"], "jev-1.13.0")
        self.assertEqual(out["answers"]["behavior"]["choice"], "scan_left")

    def test_timeout_returns_none_after_retry(self):
        sleeps = []
        session = FakeSession([TimeoutError("slow"), TimeoutError("slow")])
        client = JevClient("key", "m", session=session, max_retries=1, sleep=sleeps.append)
        self.assertIsNone(client.system_one("s", {}))
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [0.25])
        self.assertIn("TimeoutError", client.last_error)

    def test_rate_limit_is_retried(self):
        session = FakeSession([FakeResponse(429, {"error": "slow down"}), FakeResponse(200, RAW_RESPONSE)])
        client = JevClient("key", "m", session=session, max_retries=1, sleep=lambda _s: None)
        self.assertIsNotNone(client.system_one("s", {}))

    def test_client_error_is_not_retried(self):
        session = FakeSession([FakeResponse(401, {"error": "bad key"})])
        client = JevClient("key", "m", session=session, max_retries=3, sleep=lambda _s: None)
        self.assertIsNone(client.system_one("s", {}))
        self.assertEqual(len(session.calls), 1)
        self.assertIn("401", client.last_error)

    def test_missing_key_rejected(self):
        with self.assertRaises(ValueError):
            JevClient("", "m", session=FakeSession([]))


class ServiceTests(unittest.TestCase):
    def make_service(self, response, dry_run=False):
        service = JevDeciderService(FakeJev(response), mqtt_enabled=False, dry_run=dry_run)
        service.client = FakeMQTT()
        return service

    def test_step_publishes_decision_and_remembers_behavior(self):
        service = self.make_service(result("scan_right"))
        decision = service.step(NOW)
        self.assertEqual(decision["behavior"], "scan_right")
        self.assertEqual(service.client.messages[-1][0], TOPIC_DECISION)
        self.assertEqual(list(service.recent_behaviors), ["scan_right"])

    def test_dry_run_does_not_publish(self):
        service = self.make_service(result("scan_right"), dry_run=True)
        service.step(NOW)
        self.assertEqual(service.client.messages, [])

    def test_collision_masks_forward_in_request(self):
        service = self.make_service(result("rest"))
        service.ingest(TOPIC_EDGE, {"blocked_prob": 0.1}, now=NOW)
        service.ingest(TOPIC_COLLISION, {"collision": True}, now=NOW - 0.5)
        service.step(NOW)
        _state, questions = service.jev.calls[-1]
        self.assertNotIn("explore_forward", questions["behavior"]["criteria"])


if __name__ == "__main__":
    unittest.main()
