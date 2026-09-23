"""Build a compact English state for Jev from the latest MQTT snapshot.

The snapshot is a plain dict maintained by ``jev_decider.JevDeciderService``:

    {
        "edge": {...},            # vision_pal/edge/state
        "sensory": {...},         # vision_pal/neural/sensory
        "neural_action": {...},   # vision_pal/neural/action (+ "_ts")
        "survival": {...},        # vision_pal/survival/state
        "scene": {...},           # vision_pal/perception/scene
        "body": {...},            # vision_pal/body/state
        "last_collision_ts": float or None,
        "recent_behaviors": [str, ...],
    }

Jev is English-first, so labels are English; free text from the VLM scene
(often Japanese) is passed through as-is but truncated.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


def _level(value: float, low: float, high: float, words=("low", "medium", "high")) -> str:
    if value < low:
        return words[0]
    if value < high:
        return words[1]
    return words[2]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_state(snapshot: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    state: Dict[str, Any] = {
        "robot": "Small two-wheeled indoor robot with a forward-facing camera. "
                 "It explores a room, avoids obstacles and approaches people or interesting things.",
    }

    edge = snapshot.get("edge") or {}
    blocked = _num(edge.get("blocked_prob"))
    state["path_ahead"] = {
        "blocked_probability": round(blocked, 2),
        "assessment": _level(blocked, 0.3, 0.5, ("clear", "uncertain", "blocked")),
        "moving": bool(edge.get("motor_running", False)),
    }

    sensory = snapshot.get("sensory") or {}
    if sensory.get("frame_valid", True) and sensory:
        left = _num(sensory.get("motion_left"))
        right = _num(sensory.get("motion_right"))
        looming = _num(sensory.get("looming"))
        side = "balanced"
        if left - right > 0.1:
            side = "more motion on the left"
        elif right - left > 0.1:
            side = "more motion on the right"
        state["vision"] = {
            "looming": round(looming, 2),
            "approaching_object": _level(looming, 0.24, 0.5, ("none", "possible", "likely")),
            "motion_balance": side,
            "brightness": _level(_num(sensory.get("luminance")), 0.25, 0.6, ("dark", "normal", "bright")),
        }

    neural = snapshot.get("neural_action") or {}
    if neural and now - _num(neural.get("_ts"), 0.0) < 3.0:
        state["recent_reflex"] = {
            "direction": neural.get("direction"),
            "reason": neural.get("reason", ""),
        }

    last_collision = snapshot.get("last_collision_ts")
    if last_collision:
        state["seconds_since_collision"] = round(max(0.0, now - last_collision), 1)

    survival = snapshot.get("survival") or {}
    drives = survival.get("drives") or {}
    if drives:
        state["drives"] = {
            name: {"level": round(_num(d.get("level")), 2), "urgent": bool(d.get("urgent", False))}
            for name, d in drives.items() if isinstance(d, dict)
        }
        state["dominant_drive"] = survival.get("dominant_drive", "none")

    scene = snapshot.get("scene") or {}
    if scene and now - _num(scene.get("timestamp"), now) < 30.0:
        summary = str(scene.get("summary", ""))[:160]
        if summary:
            state["scene_summary"] = summary
        obstacles = scene.get("obstacles")
        if isinstance(obstacles, list) and obstacles:
            state["scene_obstacles"] = [str(o)[:60] for o in obstacles[:4]]
        people = scene.get("people")
        if isinstance(people, (int, float)):
            state["people_visible"] = int(people)

    body = snapshot.get("body") or {}
    if body:
        body_state: Dict[str, Any] = {}
        if "cpu_temp" in body:
            temp = _num(body.get("cpu_temp"), -1)
            if temp >= 0:
                body_state["cpu_temp_c"] = round(temp, 1)
                body_state["thermal"] = _level(temp, 60, 75, ("cool", "warm", "hot"))
        if "idle_sec" in body:
            body_state["idle_seconds"] = round(_num(body.get("idle_sec")), 0)
        if "tilt_deg" in body:
            body_state["tilt_deg"] = round(_num(body.get("tilt_deg")), 1)
        if body_state:
            state["body"] = body_state

    recent = snapshot.get("recent_behaviors") or []
    if recent:
        state["recent_behaviors_oldest_first"] = list(recent)[-5:]

    return state
