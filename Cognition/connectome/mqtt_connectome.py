#!/usr/bin/env python3
"""VisionPAL camera -> neural circuit -> MQTT bridge.

The service publishes neural proposals but never writes directly to the motors.
AsyncVLA remains the single action arbiter and safety boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import Any, Dict

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vp_env import env, env_float, env_int
from Cognition.connectome.connectome_backend import ConnectomeBackend
from Cognition.connectome.neural_dynamics import NeuralConfig
from Cognition.connectome.sensory_encoder import SensoryEncoder

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised only on incomplete deployments
    mqtt = None


TOPIC_SENSORY = "vision_pal/neural/sensory"
TOPIC_ACTIVITY = "vision_pal/neural/activity"
TOPIC_ACTION = "vision_pal/neural/action"
TOPIC_BODY = "vision_pal/body/state"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_MODULATION = "vision_pal/neural/modulation"

running = True


def _stop(*_args: Any) -> None:
    global running
    running = False


class ConnectomeService:
    def __init__(self, source: str, mqtt_enabled: bool = True, population_size: int = 96):
        self.source = source
        self.encoder = SensoryEncoder(
            width=env_int("NEURAL_FRAME_WIDTH", 160),
            height=env_int("NEURAL_FRAME_HEIGHT", 120),
            smoothing=env_float("NEURAL_SMOOTHING", 0.55),
        )
        self.backend = ConnectomeBackend(NeuralConfig(
            neurons_per_population=population_size,
            motion_reflex_threshold=env_float("NEURAL_MOTION_THRESHOLD", 0.28),
            looming_reflex_threshold=env_float("NEURAL_LOOMING_THRESHOLD", 0.24),
            looming_escape_threshold=env_float("NEURAL_ESCAPE_THRESHOLD", 0.72),
        ))
        self.body_state: Dict[str, Any] = {}
        self.modulation: Dict[str, Any] = {}
        self.collision_until = 0.0
        self.client = None
        if mqtt_enabled:
            self._connect_mqtt()

    def _connect_mqtt(self) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt is required unless --no-mqtt is used")
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "connectome_service")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("connectome_service")
        self.client.on_connect = self._on_connect
        self.client.connect(env("MQTT_HOST", "192.168.3.12"), env_int("MQTT_PORT", 1883), 60)
        self.client.loop_start()

    def _on_connect(self, client: Any, *_args: Any) -> None:
        client.subscribe(TOPIC_BODY)
        client.subscribe(TOPIC_COLLISION)
        client.subscribe(TOPIC_MODULATION)
        client.message_callback_add(TOPIC_BODY, self._on_body)
        client.message_callback_add(TOPIC_COLLISION, self._on_collision)
        client.message_callback_add(TOPIC_MODULATION, self._on_modulation)
        print("[NEURAL] MQTT connected")

    def _on_body(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            self.body_state.update(json.loads(msg.payload))
        except (TypeError, ValueError):
            pass

    def _on_collision(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            payload = json.loads(msg.payload)
            if payload.get("collision", False):
                # Collision topics are events, not continuous state.  Let the
                # neural drive decay instead of latching escape forever.
                self.collision_until = time.monotonic() + 1.0
        except (TypeError, ValueError):
            pass

    def _on_modulation(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            self.modulation.update(json.loads(msg.payload))
        except (TypeError, ValueError):
            pass

    def process(self, frame: Any, dt: float) -> Dict[str, Any]:
        sensory = self.encoder.encode(frame)
        self.body_state["collision"] = time.monotonic() < self.collision_until
        result = self.backend.step(sensory, self.body_state, dt, self.modulation)
        if self.client:
            self.client.publish(TOPIC_SENSORY, json.dumps(sensory))
            self.client.publish(TOPIC_ACTIVITY, json.dumps({
                "activity": result["activity"],
                "backend": result["backend"],
                "timestamp": result["timestamp"],
            }))
            if result["action"]["reflex"]:
                self.client.publish(TOPIC_ACTION, json.dumps(result["action"]))
        return result

    def run(self, fps: float = 15.0, max_frames: int = 0) -> None:
        cap = cv2.VideoCapture(int(self.source) if self.source.isdigit() else self.source)
        if not cap.isOpened():
            raise RuntimeError("Could not open camera/video source: {}".format(self.source))
        interval = 1.0 / max(1.0, fps)
        previous = time.monotonic()
        frame_count = 0
        try:
            while running:
                ok, frame = cap.read()
                if not ok:
                    if self.source.startswith("http"):
                        time.sleep(0.5)
                        continue
                    break
                now = time.monotonic()
                result = self.process(frame, max(0.001, now - previous))
                previous = now
                frame_count += 1
                if frame_count % int(max(1, fps)) == 0 or result["action"]["reflex"]:
                    action = result["action"]
                    print("[NEURAL] action={} confidence={:.2f} looming={:.2f}".format(
                        action["direction"], action["confidence"], result["sensory"]["looming"]
                    ))
                if max_frames and frame_count >= max_frames:
                    break
                elapsed = time.monotonic() - now
                if elapsed < interval:
                    time.sleep(interval - elapsed)
        finally:
            cap.release()
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionPAL connectome-inspired neural service")
    parser.add_argument("--source", default=env("CAMERA_URL", "0"), help="camera index, video, or MJPEG URL")
    parser.add_argument("--fps", type=float, default=env_float("NEURAL_FPS", 15.0))
    parser.add_argument("--population-size", type=int, default=env_int("NEURAL_POPULATION_SIZE", 96))
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N frames (test utility)")
    parser.add_argument("--no-mqtt", action="store_true", help="print only; do not connect to MQTT")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print("[NEURAL] source={} populations={}x7 MQTT={}".format(
        args.source, args.population_size, "off" if args.no_mqtt else "on"
    ))
    ConnectomeService(args.source, not args.no_mqtt, args.population_size).run(args.fps, args.max_frames)


if __name__ == "__main__":
    main()
