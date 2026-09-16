import json
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
