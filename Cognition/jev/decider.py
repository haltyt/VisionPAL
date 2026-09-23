"""MQTT-free decision logic around Jev.

Code owns legal actions, thresholds and side effects; Jev only picks among
behaviors that code has already judged safe to consider.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

BEHAVIORS: Dict[str, str] = {
    "explore_forward": "Drive forward slowly to explore open space ahead.",
    "scan_left": "Turn left in place to look around.",
    "scan_right": "Turn right in place to look around.",
    "approach_target": "Move carefully toward a person or interesting object that is ahead.",
    "back_off": "Reverse a little to get away from something too close.",
    "rest": "Stay still for now (nothing worth doing, or conditions are unclear).",
    "other": "None of the other behaviors fits the situation.",
}

FORWARD_BEHAVIORS = ("explore_forward", "approach_target")

BLOCKED_THRESHOLD = 0.5
COLLISION_COOLDOWN_SEC = 2.0
HAZARD_VETO = 0.7


def legal_behaviors(
    snapshot: Dict[str, Any],
    now: Optional[float] = None,
    looming_threshold: float = 0.72,
) -> List[str]:
    """Behaviors Jev may choose from, masked by hard safety rules."""
    now = time.time() if now is None else now
    legal = list(BEHAVIORS)
    edge = snapshot.get("edge") or {}
    sensory = snapshot.get("sensory") or {}
    last_collision = snapshot.get("last_collision_ts")

    forward_blocked = (
        float(edge.get("blocked_prob", 0.0) or 0.0) > BLOCKED_THRESHOLD
        or (last_collision is not None and now - last_collision < COLLISION_COOLDOWN_SEC)
        or float(sensory.get("looming", 0.0) or 0.0) >= looming_threshold
    )
    if forward_blocked:
        legal = [b for b in legal if b not in FORWARD_BEHAVIORS]
    return legal


def build_questions(legal: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fan-out questions answered in one Jev request."""
    return {
        "behavior": {
            "type": "choice",
            "instructions": (
                "Which behavior should the robot perform for the next second? "
                "Prefer variety over repeating the same behavior many times, "
                "and prefer satisfying urgent drives."
            ),
            "criteria": {name: BEHAVIORS[name] for name in legal},
        },
        "hazard_ahead": {
            "type": "noul",
            "instructions": "Is there an obstacle or hazard directly ahead that makes driving forward unsafe?",
        },
        "interest": {
            "type": "score",
            "instructions": "How interesting is the current surroundings for a curious robot?",
            "criteria": [
                "Boring: nothing new to see",
                "Somewhat interesting",
                "Very interesting: people or new objects nearby",
            ],
        },
    }


def decide(
    result: Optional[Dict[str, Any]],
    legal: List[str],
    min_confidence: float = 0.55,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Turn a normalized Jev result into a proposal, or None to stay silent."""
    if not result:
        return None
    answers = result.get("answers") or {}
    behavior = answers.get("behavior") or {}
    choice = behavior.get("choice")
    confidence = float(behavior.get("confidence", 0.0))
    if choice not in legal or choice == "other":
        return None
    if confidence < min_confidence:
        return None

    hazard = (answers.get("hazard_ahead") or {}).get("noul")
    if choice in FORWARD_BEHAVIORS and hazard is not None and hazard > HAZARD_VETO:
        return None

    return {
        "behavior": choice,
        "confidence": round(confidence, 4),
        "probabilities": behavior.get("probabilities", {}),
        "hazard": None if hazard is None else round(float(hazard), 4),
        "interest": (answers.get("interest") or {}).get("score"),
        "model": result.get("model"),
        "latency_ms": result.get("latency_ms"),
        "ts": time.time() if now is None else now,
    }
