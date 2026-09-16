"""Stable backend interface between VisionPAL and neural simulations."""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping

from .neural_dynamics import LIFConnectome, NeuralConfig


class ConnectomeBackend:
    """Run neural dynamics and decode population activity into an action proposal."""

    def __init__(self, config: NeuralConfig | None = None):
        self.brain = LIFConnectome(config)

    def _decode(self, sensory: Mapping[str, Any], activity: Mapping[str, Any]) -> Dict[str, Any]:
        cfg = self.brain.config
        motor = activity["motor"]
        looming = float(sensory.get("looming", 0.0))
        left_motion = float(sensory.get("motion_left", 0.0))
        right_motion = float(sensory.get("motion_right", 0.0))
        escape = float(motor["escape"])

        if looming >= cfg.looming_escape_threshold or escape >= 0.82:
            direction = "backward"
            confidence = max(looming, escape)
        elif (looming >= cfg.looming_reflex_threshold or
              max(left_motion, right_motion) >= cfg.motion_reflex_threshold):
            direction = "left" if right_motion >= left_motion else "right"
            confidence = max(looming, left_motion, right_motion)
        else:
            direction = "forward"
            confidence = float(motor["forward"])

        # Only avoidance/escape is proposed to the arbiter. Forward remains an
        # observable tendency so the neural layer cannot start the robot alone.
        reflex = direction in ("left", "right", "backward")
        return {
            "direction": direction,
            "speed": round(float(np_clip(0.22 + confidence * 0.28, 0.22, 0.5)), 3),
            "duration": 0.65 if direction == "backward" else 0.4,
            "confidence": round(float(np_clip(confidence, 0.0, 1.0)), 4),
            "reflex": reflex,
            "reason": "looming_escape" if direction == "backward" else (
                "lateral_avoidance" if reflex else "baseline_forward_tendency"
            ),
        }

    def step(
        self,
        sensory_state: Mapping[str, Any],
        body_state: Mapping[str, Any] | None = None,
        dt: float = 0.02,
        modulation: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        activity = self.brain.step(sensory_state, body_state, modulation, dt)
        action = self._decode(sensory_state, activity)
        return {
            "sensory": dict(sensory_state),
            "activity": activity,
            "action": action,
            "backend": "lif_prototype",
            "timestamp": time.time(),
        }


def np_clip(value: float, low: float, high: float) -> float:
    """Small scalar clip helper that keeps the public backend dependency-light."""
    return max(low, min(high, value))
