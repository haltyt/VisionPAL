#!/usr/bin/env python3
"""VisionPAL world state -> Jev behavior selection -> MQTT proposal.

Publishes ``vision_pal/jev/decision`` about once per second.  It never writes
to the motors: AsyncVLA arbitrates, so reflexes and survival actions win.

Usage:
    python3 -m Cognition.jev.jev_decider               # live
    python3 -m Cognition.jev.jev_decider --dry-run     # call Jev, do not publish
    python3 -m Cognition.jev.jev_decider --no-mqtt --fixture tests/fixtures/jev_state.json --once
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vp_env import env, env_float, env_int
from Cognition.jev.decider import build_questions, decide, legal_behaviors
from Cognition.jev.jev_client import DEFAULT_BASE_URL, JevClient
from Cognition.jev.state_builder import build_state

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised only on incomplete deployments
    mqtt = None


TOPIC_EDGE = "vision_pal/edge/state"
TOPIC_SENSORY = "vision_pal/neural/sensory"
TOPIC_NEURAL_ACTION = "vision_pal/neural/action"
TOPIC_SURVIVAL = "vision_pal/survival/state"
TOPIC_SCENE = "vision_pal/perception/scene"
TOPIC_BODY = "vision_pal/body/state"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_DECISION = "vision_pal/jev/decision"

SNAPSHOT_KEYS = {
    TOPIC_EDGE: "edge",
    TOPIC_SENSORY: "sensory",
    TOPIC_NEURAL_ACTION: "neural_action",
    TOPIC_SURVIVAL: "survival",
    TOPIC_SCENE: "scene",
    TOPIC_BODY: "body",
}

running = True


def _stop(*_args: Any) -> None:
    global running
    running = False


class JevDeciderService:
    def __init__(
        self,
        client: JevClient,
        mqtt_enabled: bool = True,
        dry_run: bool = False,
        min_confidence: float = 0.55,
        looming_threshold: float = 0.72,
        log_path: str = "",
    ):
        self.jev = client
        self.dry_run = dry_run
        self.min_confidence = min_confidence
        self.looming_threshold = looming_threshold
        self.log_path = log_path
        self.snapshot: Dict[str, Any] = {"last_collision_ts": None}
        self.recent_behaviors: deque = deque(maxlen=5)
        self.lock = threading.Lock()
        self.client = None
        if mqtt_enabled:
            self._connect_mqtt()

    def _connect_mqtt(self) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt is required unless --no-mqtt is used")
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "jev_decider")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("jev_decider")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(env("MQTT_HOST", "192.168.3.12"), env_int("MQTT_PORT", 1883), 60)
        self.client.loop_start()

    def _on_connect(self, client: Any, *_args: Any) -> None:
        for topic in list(SNAPSHOT_KEYS) + [TOPIC_COLLISION]:
            client.subscribe(topic)
        print("[JEV] MQTT connected")

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            data = json.loads(msg.payload)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.ingest(msg.topic, data)

    def ingest(self, topic: str, data: Dict[str, Any], now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self.lock:
            if topic == TOPIC_COLLISION:
                if data.get("collision"):
                    self.snapshot["last_collision_ts"] = now
                return
            key = SNAPSHOT_KEYS.get(topic)
            if key is None:
                return
            if key == "neural_action":
                data = dict(data, _ts=now)
            self.snapshot[key] = data

    def step(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        now = time.time() if now is None else now
        with self.lock:
            snapshot = dict(self.snapshot, recent_behaviors=list(self.recent_behaviors))
        legal = legal_behaviors(snapshot, now, self.looming_threshold)
        state = build_state(snapshot, now)
        result = self.jev.system_one(state, build_questions(legal))
        decision = decide(result, legal, self.min_confidence)
        if result is None:
            print("[JEV] call failed: {}".format(self.jev.last_error))
        if decision:
            self.recent_behaviors.append(decision["behavior"])
            if self.client and not self.dry_run:
                self.client.publish(TOPIC_DECISION, json.dumps(decision, ensure_ascii=False))
        self._log(state, legal, result, decision)
        return decision

    def _log(self, state: Dict[str, Any], legal: Any, result: Any, decision: Any) -> None:
        if not self.log_path:
            return
        record = {"ts": time.time(), "state": state, "legal": legal, "result": result, "decision": decision}
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            print("[JEV] log write failed: {}".format(exc))

    def run(self, interval: float = 1.0) -> None:
        failures = 0
        try:
            while running:
                started = time.monotonic()
                decision = self.step()
                if decision:
                    failures = 0
                    print("[JEV] {} conf={:.2f} hazard={} {}ms".format(
                        decision["behavior"], decision["confidence"],
                        decision["hazard"], decision["latency_ms"]))
                elif self.jev.last_error:
                    failures += 1
                # Back off while the API is failing so we don't hammer it.
                wait = interval * min(8, 2 ** failures) if failures else interval
                elapsed = time.monotonic() - started
                if elapsed < wait:
                    time.sleep(wait - elapsed)
        finally:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionPAL Jev behavior selection service")
    parser.add_argument("--interval", type=float, default=env_float("JEV_INTERVAL", 1.0))
    parser.add_argument("--dry-run", action="store_true", help="call Jev but do not publish decisions")
    parser.add_argument("--no-mqtt", action="store_true", help="do not connect to MQTT")
    parser.add_argument("--fixture", help="JSON file of {topic: payload} to seed the snapshot")
    parser.add_argument("--once", action="store_true", help="run one decision, print it and exit")
    args = parser.parse_args()

    if env("JEV_ENABLED", "1") == "0":
        print("[JEV] JEV_ENABLED=0; exiting")
        return
    api_key = env("TYPESAFE_API_KEY", "")
    if not api_key:
        print("[JEV] TYPESAFE_API_KEY is not set; exiting")
        sys.exit(1)

    client = JevClient(
        api_key=api_key,
        model=env("JEV_MODEL", "jev-1.13.0"),
        base_url=env("TYPESAFE_BASE_URL", DEFAULT_BASE_URL),
        timeout=env_float("JEV_TIMEOUT", 1.5),
    )
    service = JevDeciderService(
        client,
        mqtt_enabled=not args.no_mqtt,
        dry_run=args.dry_run,
        min_confidence=env_float("JEV_MIN_CONFIDENCE", 0.55),
        looming_threshold=env_float("NEURAL_ESCAPE_THRESHOLD", 0.72),
        log_path=env("JEV_LOG_PATH", ""),
    )
    if args.fixture:
        with open(args.fixture, encoding="utf-8") as fh:
            for topic, payload in json.load(fh).items():
                service.ingest(topic, payload)

    if args.once:
        decision = service.step()
        print(json.dumps({"decision": decision, "error": client.last_error}, ensure_ascii=False, indent=2))
        return

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print("[JEV] model={} interval={}s MQTT={} dry_run={}".format(
        client.model, args.interval, "off" if args.no_mqtt else "on", args.dry_run))
    service.run(args.interval)


if __name__ == "__main__":
    main()
