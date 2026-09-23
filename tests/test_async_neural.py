import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGNITION = os.path.join(ROOT, "Cognition")
for path in (ROOT, COGNITION):
    if path not in sys.path:
        sys.path.insert(0, path)

from Cognition.async_vla import ActionArbiter, AsyncVLAOrchestrator


class FakeMQTT:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        self.messages.append((topic, json.loads(payload)))


class Message:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()


def make_orchestrator():
    orchestrator = AsyncVLAOrchestrator.__new__(AsyncVLAOrchestrator)
    orchestrator.arbiter = ActionArbiter()
    orchestrator.edge_state = {}
    orchestrator.cloud_state = {"scene": {}, "dominant_drive": "none"}
    orchestrator.neural_state = {}
    orchestrator.jev_state = {}
    orchestrator.cycle = 0
    orchestrator.last_action = None
    orchestrator.action_log = []
    orchestrator.mqtt = FakeMQTT()
    return orchestrator


class NeuralArbitrationTests(unittest.TestCase):
    def test_direction_change_is_forwarded_even_with_same_action_type(self):
        orchestrator = make_orchestrator()
        orchestrator._on_neural_action(None, None, Message({
            "direction": "left", "speed": 0.3, "confidence": 0.7,
            "duration": 0.4, "reflex": True,
        }))
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["direction"], "left")

        orchestrator._on_neural_action(None, None, Message({
            "direction": "right", "speed": 0.3, "confidence": 0.7,
            "duration": 0.4, "reflex": True,
        }))
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["direction"], "right")

    def test_expired_reflex_sends_stop(self):
        orchestrator = make_orchestrator()
        orchestrator._on_neural_action(None, None, Message({
            "direction": "left", "speed": 0.3, "confidence": 0.7,
            "duration": 0.4, "reflex": True,
        }))
        orchestrator.tick()
        orchestrator.arbiter.pending_actions["connectome"]["proposed_at"] -= 2.0
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["direction"], "stop")
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["reason"], "action_expired")


def jev_msg(behavior="scan_left", confidence=0.8, ts=None):
    return Message({"behavior": behavior, "confidence": confidence,
                    "ts": time.time() if ts is None else ts})


class JevArbitrationTests(unittest.TestCase):
    def test_jev_behavior_publishes_move(self):
        orchestrator = make_orchestrator()
        orchestrator._on_jev_decision(None, None, jev_msg("explore_forward"))
        orchestrator.tick()
        move = orchestrator.mqtt.messages[-1][1]
        self.assertEqual(move["direction"], "forward")
        self.assertEqual(move["source"], "jev")
        self.assertLessEqual(move["speed"], 0.4)

    def test_behavior_change_is_forwarded(self):
        orchestrator = make_orchestrator()
        orchestrator._on_jev_decision(None, None, jev_msg("scan_left"))
        orchestrator.tick()
        orchestrator._on_jev_decision(None, None, jev_msg("scan_right"))
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["direction"], "right")

    def test_reflexes_override_jev(self):
        orchestrator = make_orchestrator()
        orchestrator._on_jev_decision(None, None, jev_msg("explore_forward"))
        orchestrator._on_neural_action(None, None, Message({
            "direction": "backward", "speed": 0.3, "confidence": 0.9,
            "duration": 0.6, "reflex": True,
        }))
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["source"], "connectome")

        orchestrator._on_collision(None, None, Message({"collision": True}))
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["reason"], "emergency_stop")

    def test_invalid_jev_proposals_are_ignored(self):
        orchestrator = make_orchestrator()
        orchestrator._on_jev_decision(None, None, jev_msg("dance"))
        orchestrator._on_jev_decision(None, None, jev_msg("scan_left", confidence=0.1))
        orchestrator._on_jev_decision(None, None, jev_msg("scan_left", ts=time.time() - 10))
        self.assertNotIn("jev", orchestrator.arbiter.pending_actions)

    def test_expired_jev_behavior_sends_stop(self):
        orchestrator = make_orchestrator()
        orchestrator._on_jev_decision(None, None, jev_msg("explore_forward"))
        orchestrator.tick()
        orchestrator.arbiter.pending_actions["jev"]["proposed_at"] -= 2.0
        orchestrator.tick()
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["direction"], "stop")
        self.assertEqual(orchestrator.mqtt.messages[-1][1]["reason"], "action_expired")


if __name__ == "__main__":
    unittest.main()
