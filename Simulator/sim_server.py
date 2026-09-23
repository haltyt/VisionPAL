#!/usr/bin/env python3
"""VisionPAL virtual JetBot: physics + camera + sensors + MQTT + browser UI.

Stands in for the real robot so the Cognition stack (connectome, Jev,
AsyncVLA, survival, explore) runs unchanged against a simulated room:

    subscribe  vision_pal/move                  → drives the virtual motors
    publish    vision_pal/edge/state            (≈ collision_detect_v2.py)
               vision_pal/perception/collision  (predicted + IMU bump)
               vision_pal/body/state            (≈ body_sensor.py)
               vision_pal/status                (ready)
    HTTP :8554 /stream /raw /snap /snapshot     (≈ mjpeg_server.py)
               /                                browser UI
               /events                          SSE: world + layer states
               /api/cmd                         POST: drive, reset, obstacles ...

Usage:
    python3 -m Simulator.sim_server                 # MQTT on $MQTT_HOST (use launch.py for local)
    python3 -m Simulator.sim_server --no-mqtt       # UI-only, drive from the browser
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vp_env import env, env_int
from Simulator.camera import Camera
from Simulator.sensors import BodyModel, EdgeSensor
from Simulator.world import World

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None

TOPIC_MOVE = "vision_pal/move"
TOPIC_STATUS = "vision_pal/status"
TOPIC_EDGE = "vision_pal/edge/state"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_BODY = "vision_pal/body/state"

# Topics shown in the browser's layer panel.
UI_TOPICS = [
    TOPIC_MOVE, TOPIC_EDGE, TOPIC_COLLISION, TOPIC_BODY,
    "vision_pal/neural/sensory", "vision_pal/neural/action",
    "vision_pal/jev/decision", "vision_pal/vla/state",
    "vision_pal/survival/state", "vision_pal/survival/action",
    "vision_pal/explore/state", "vision_pal/perception/scene",
]

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

TOPIC_NEURAL_ACTION = "vision_pal/neural/action"
TOPIC_NEURAL_SENSORY = "vision_pal/neural/sensory"
TOPIC_JEV = "vision_pal/jev/decision"
TOPIC_EXPLORE = "vision_pal/explore/state"
TOPIC_SCENE = "vision_pal/perception/scene"

# Freshness windows for "proposing" (match async_vla's arbiter ttls).
REFLEX_TTL = 0.75     # async_vla: neural_reflex proposal ttl
BEHAVIOR_TTL = 1.5    # async_vla: jev_behavior proposal ttl
THOUGHT_TTL = 5.0
TIMELINE_SEC = 60.0

SAFETY_REASONS = {"emergency_stop", "avoid"}
SURVIVAL_REASONS = {"retreat", "cool_down", "seek_energy", "explore", "seek_social", "clean_space"}


def classify_move(payload: Dict[str, Any], explore_planner: Optional[str] = None) -> Dict[str, str]:
    """Map a vision_pal/move command to the decision tier that issued it.

    explore_planner: planner of the last explore_vla step, so its intermediate
    stop commands (sent without a planner) stay attributed to the same tier.
    """
    source = str(payload.get("source", ""))
    reason = str(payload.get("reason", ""))
    if source == "connectome":
        return {"tier": "reflex", "label": "Connectome: {}".format(reason or payload.get("direction", ""))}
    if source == "jev":
        return {"tier": "behavior", "label": "Jev: {}".format(reason or payload.get("direction", ""))}
    if source == "async_vla_cloud":
        return {"tier": "thought", "label": "VLM の提案"}
    if source == "explore_vla":
        planner = payload.get("planner") or explore_planner
        if planner == "llm":
            return {"tier": "thought", "label": "LLM: {}".format(reason or payload.get("direction", ""))}
        return {"tier": "survival", "label": "ランダム探索"}
    if source in ("edge_layer", "imu_auto_stop"):
        return {"tier": "safety", "label": "安全停止 ({})".format(source)}
    if source == "async_vla_ttl":
        return {"tier": "idle", "label": "提案の期限切れ → 停止"}
    if source == "async_vla":
        if reason in SAFETY_REASONS:
            return {"tier": "safety", "label": "安全 ({})".format(reason)}
        if reason in SURVIVAL_REASONS:
            return {"tier": "survival", "label": "Survival ({})".format(reason)}
    if source == "sim_ui":
        return {"tier": "manual", "label": "手動操縦"}
    return {"tier": "other", "label": source or "不明"}


class Simulation:
    def __init__(self, seed: Optional[int] = None, people: int = 1, boxes: int = 5,
                 camera_fps: float = 12.0, physics_hz: float = 30.0,
                 mqtt_host: Optional[str] = None, mqtt_port: int = 1883, edge: bool = True):
        self.people, self.boxes = people, boxes
        self.world = World.generate(seed, n_boxes=boxes, n_people=people)
        self.camera = Camera()
        self.edge = EdgeSensor() if edge else None
        self.body = BodyModel()
        self.camera_fps = camera_fps
        self.physics_hz = physics_hz
        self.paused = False
        self.running = True
        self.lock = threading.RLock()
        self.frame_cond = threading.Condition()
        self.jpeg: Optional[bytes] = None
        self.frame_id = 0
        self.render_ms = 0.0
        self.layers: Dict[str, Dict[str, Any]] = {}
        self.move_log: deque = deque(maxlen=300)
        self.explore_planner: Optional[str] = None
        self.client = None
        self.mqtt_connected = False
        if mqtt_host:
            self._connect_mqtt(mqtt_host, mqtt_port)

    # ── MQTT ──

    def _connect_mqtt(self, host: str, port: int) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt is required unless --no-mqtt is used")
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "visionpal_sim")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("visionpal_sim")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.connect_async(host, port, 30)
        self.client.loop_start()

    def _on_connect(self, client: Any, *_args: Any) -> None:
        self.mqtt_connected = True
        client.subscribe("vision_pal/#")
        client.publish(TOPIC_STATUS, json.dumps({"status": "ready", "simulated": True, "timestamp": time.time()}))
        print("[SIM] MQTT connected")

    def _on_disconnect(self, *_args: Any) -> None:
        self.mqtt_connected = False
        print("[SIM] MQTT disconnected")

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            payload = json.loads(msg.payload)
        except (TypeError, ValueError):
            if msg.topic == TOPIC_MOVE:
                self.apply_move({"direction": "stop"})  # mqtt_robot stops on bad payloads
            return
        if not isinstance(payload, dict):
            return
        if msg.topic == TOPIC_MOVE:
            self.apply_move(payload)
        elif msg.topic in UI_TOPICS:
            self._record(msg.topic, payload)

    def emit(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish like the real robot would, and show it in the UI."""
        if self.client is not None and self.mqtt_connected:
            self.client.publish(topic, json.dumps(payload, ensure_ascii=False))
            if topic == TOPIC_MOVE:
                return  # applied when it comes back from the broker, exactly like the real robot
        if topic == TOPIC_MOVE:
            self.apply_move(payload)
        else:
            self._record(topic, payload)

    def _record(self, topic: str, payload: Dict[str, Any]) -> None:
        with self.lock:
            self.layers[topic] = {"payload": payload, "t": time.time()}

    def apply_move(self, payload: Dict[str, Any]) -> None:
        try:
            speed = float(payload.get("speed", 0.5))
        except (TypeError, ValueError):
            speed = 0.0
        direction = payload.get("direction", "stop")
        source = str(payload.get("source", ""))
        with self.lock:
            self.world.set_command(direction, speed, source)
            self.layers[TOPIC_MOVE] = {"payload": payload, "t": time.time()}
            if source == "explore_vla" and payload.get("planner"):
                self.explore_planner = payload.get("planner")
            tier = classify_move(payload, self.explore_planner if source == "explore_vla" else None)
            self.move_log.append({
                "t": round(time.time(), 2), "direction": self.world.robot.direction,
                "speed": round(self.world.robot.speed, 2), "source": source,
                "reason": str(payload.get("reason", "")),
                "tier": tier["tier"], "label": tier["label"],
            })

    # ── loops ──

    def physics_loop(self) -> None:
        dt = 1.0 / self.physics_hz
        next_edge = next_body = 0.0
        while self.running:
            started = time.monotonic()
            if not self.paused:
                with self.lock:
                    bump = self.world.step(dt)
                    self.body.update(self.world, dt)
                if bump:
                    # imu_collision.py auto-stops the motors locally, then reports.
                    with self.lock:
                        self.world.set_command("stop", 0.0, "imu_auto_stop")
                    self.emit(TOPIC_COLLISION, dict(bump, collision=True, severity="detected",
                                                    method="imu", timestamp=time.time()))
                now = time.monotonic()
                if self.edge and now >= next_edge:
                    next_edge = now + 0.33
                    with self.lock:
                        edge_state = self.edge.sense(self.world)
                    self.emit(TOPIC_EDGE, edge_state)
                    predicted = self.edge.predicted_collision(edge_state)
                    if predicted:
                        self.emit(TOPIC_COLLISION, predicted)
                        self.emit(TOPIC_MOVE, {"direction": "stop", "speed": 0.0, "source": "edge_layer",
                                               "reason": "collision_predicted"})
                if now >= next_body:
                    next_body = now + 1.0
                    with self.lock:
                        body = self.body.state(self.world)
                    self.emit(TOPIC_BODY, body)
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, dt - elapsed))

    def render_loop(self) -> None:
        interval = 1.0 / self.camera_fps
        while self.running:
            started = time.monotonic()
            with self.lock:
                img = self.camera.render(self.world)
            ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self.frame_cond:
                    self.jpeg = jpg.tobytes()
                    self.frame_id += 1
                    self.frame_cond.notify_all()
            self.render_ms = self.render_ms * 0.9 + (time.monotonic() - started) * 1000 * 0.1
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

    def start(self) -> None:
        for target in (self.physics_loop, self.render_loop):
            threading.Thread(target=target, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()

    # ── UI API ──

    def command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        action = cmd.get("action")
        if action == "drive":
            self.emit(TOPIC_MOVE, {"direction": cmd.get("direction", "stop"),
                                   "speed": cmd.get("speed", 0.4), "source": "sim_ui"})
        elif action in ("reset", "randomize"):
            seed = cmd.get("seed")
            if action == "reset" and seed is None:
                seed = self.world.seed
            with self.lock:
                self.world = World.generate(seed, n_boxes=int(cmd.get("boxes", self.boxes)),
                                            n_people=int(cmd.get("people", self.people)))
                self.body = BodyModel()
                self.move_log.clear()
                self.explore_planner = None
        elif action == "pause":
            self.paused = bool(cmd.get("paused", not self.paused))
        elif action == "add_box":
            with self.lock:
                self.world.add_box(float(cmd["x"]), float(cmd["y"]))
        elif action == "remove_box":
            with self.lock:
                self.world.remove_box_at(float(cmd["x"]), float(cmd["y"]))
        elif action == "place_robot":
            with self.lock:
                r = self.world.robot
                x, y = float(cmd["x"]), float(cmd["y"])
                if self.world._free(x, y, 0.09):
                    r.x, r.y = x, y
                if "theta" in cmd:
                    r.theta = float(cmd["theta"])
        elif action == "recharge":
            with self.lock:
                self.body.recharge()
        else:
            return {"ok": False, "error": "unknown action"}
        return {"ok": True}

    def _active(self) -> Dict[str, Any]:
        if not self.move_log:
            return {"tier": "idle", "label": "指令なし", "since": None}
        last = self.move_log[-1]
        return {"tier": last["tier"], "label": last["label"], "since": last["t"]}

    def _fresh(self, topic: str, ttl: float, now: float) -> Optional[Dict[str, Any]]:
        entry = self.layers.get(topic)
        if entry and now - entry["t"] <= ttl:
            return entry["payload"]
        return None

    def _tier_states(self, now: float) -> Dict[str, Dict[str, Any]]:
        """Per tier: driving / proposing / standby / offline, plus a one-line detail."""
        active = self._active()
        L = self.layers

        def age(*topics: str) -> Optional[float]:
            ts = [L[t]["t"] for t in topics if t in L]
            return round(now - max(ts), 1) if ts else None

        # 反射 (Connectome)
        reflex = self._fresh(TOPIC_NEURAL_ACTION, REFLEX_TTL, now)
        if reflex is not None and not reflex.get("reflex", False):
            reflex = None
        neural_seen = TOPIC_NEURAL_ACTION in L or TOPIC_NEURAL_SENSORY in L
        last_reflex = (L.get(TOPIC_NEURAL_ACTION) or {}).get("payload", {})
        reflex_state = {
            "status": "proposing" if reflex else ("standby" if neural_seen else "offline"),
            "detail": "{} ({}, conf {:.2f})".format(reflex.get("direction"), reflex.get("reason", ""),
                                                   float(reflex.get("confidence", 0)))
                      if reflex else ("最後の反射: {}".format(last_reflex.get("reason", "—")) if last_reflex
                                      else ("入力を監視中" if neural_seen else "connectome 未起動")),
            "age": age(TOPIC_NEURAL_ACTION, TOPIC_NEURAL_SENSORY),
        }

        # 行動 (Jev)
        jev = self._fresh(TOPIC_JEV, BEHAVIOR_TTL, now)
        last_jev = (L.get(TOPIC_JEV) or {}).get("payload", {})
        behavior_state = {
            "status": "proposing" if jev else ("standby" if last_jev else "offline"),
            "detail": "{} (conf {:.2f}, {} ms)".format(jev.get("behavior"), float(jev.get("confidence", 0)),
                                                     jev.get("latency_ms", "—"))
                      if jev else ("最後の判断: {}".format(last_jev.get("behavior")) if last_jev
                                   else "Jev 未起動 (TYPESAFE_API_KEY)"),
            "age": age(TOPIC_JEV),
        }

        # 思考 (LLM)
        explore = (L.get(TOPIC_EXPLORE) or {}).get("payload", {})
        explore_fresh = self._fresh(TOPIC_EXPLORE, THOUGHT_TTL, now)
        scene = self._fresh(TOPIC_SCENE, 10.0, now) or {}
        suggestion = scene.get("suggested_action", "")
        llm_enabled = bool(explore.get("vla_enabled")) or TOPIC_SCENE in L
        if explore_fresh and explore_fresh.get("status") == "vla_action":
            thought = {"status": "proposing", "detail": str(explore_fresh.get("description", ""))[:80]}
        elif suggestion and suggestion != "forward":
            thought = {"status": "proposing", "detail": "VLM: {}".format(suggestion)}
        elif llm_enabled:
            thought = {"status": "standby",
                       "detail": str(explore.get("description") or scene.get("summary") or "待機中")[:80]}
        else:
            thought = {"status": "offline",
                       "detail": "LLM 未設定 (explore はランダム探索)" if explore else "LLM 層 未起動"}
        thought["age"] = age(TOPIC_EXPLORE, TOPIC_SCENE)

        states = {"reflex": reflex_state, "behavior": behavior_state, "thought": thought}
        driving = states.get(active["tier"])
        if driving is not None:
            if driving["status"] != "proposing":
                driving["detail"] = active["label"]  # proposal already expired; show the command itself
            driving["status"] = "driving"
        return states

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        with self.lock:
            world = self.world.to_dict()
            edge_dist = self.edge.last_min_distance if self.edge else None
            return {
                "world": world,
                "layers": {k: v for k, v in self.layers.items()},
                "move_log": list(self.move_log)[-15:],
                "active": self._active(),
                "tiers": self._tier_states(now),
                "timeline": [[m["t"], m["tier"]] for m in self.move_log if now - m["t"] <= TIMELINE_SEC],
                "sim": {
                    "paused": self.paused,
                    "mqtt": self.client is not None,
                    "mqtt_connected": self.mqtt_connected,
                    "render_ms": round(self.render_ms, 1),
                    "frame": self.frame_id,
                    "front_distance": None if edge_dist is None else round(edge_dist, 3),
                    "battery": round(self.body.battery, 3),
                },
                "now": now,
            }


def make_handler(sim: Simulation):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args: Any) -> None:  # keep the console readable
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif path in ("/stream", "/raw"):
                self._stream()
            elif path in ("/snap", "/snapshot"):
                with sim.frame_cond:
                    sim.frame_cond.wait_for(lambda: sim.jpeg is not None, timeout=2.0)
                    jpg = sim.jpeg
                if jpg is None:
                    self._send(503, b"no frame yet", "text/plain")
                else:
                    self._send(200, jpg, "image/jpeg")
            elif path == "/events":
                self._events()
            elif path == "/api/state":
                self._send(200, json.dumps(sim.snapshot(), ensure_ascii=False).encode(), "application/json")
            elif path == "/status":
                self._send(200, json.dumps({"status": "ok", "simulated": True}).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/api/cmd":
                self._send(404, b"not found", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                cmd = json.loads(self.rfile.read(length) or b"{}")
                result = sim.command(cmd)
                self._send(200 if result.get("ok") else 400, json.dumps(result).encode(), "application/json")
            except (ValueError, KeyError, TypeError) as exc:
                self._send(400, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--jpgboundary")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while sim.running:
                    with sim.frame_cond:
                        sim.frame_cond.wait_for(lambda: sim.frame_id != last, timeout=1.0)
                        jpg, last = sim.jpeg, sim.frame_id
                    if jpg is None:
                        continue
                    self.wfile.write(b"--jpgboundary\r\n")
                    self.wfile.write(b"Content-type: image/jpeg\r\n")
                    self.wfile.write("Content-length: {}\r\n\r\n".format(len(jpg)).encode())
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while sim.running:
                    data = json.dumps(sim.snapshot(), ensure_ascii=False)
                    self.wfile.write("data: {}\n\n".format(data).encode())
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionPAL virtual JetBot simulator")
    parser.add_argument("--port", type=int, default=env_int("SIM_PORT", 8554), help="HTTP port (UI + MJPEG)")
    parser.add_argument("--host", default=env("SIM_BIND", "0.0.0.0"))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--people", type=int, default=1)
    parser.add_argument("--boxes", type=int, default=5)
    parser.add_argument("--fps", type=float, default=12.0, help="camera frame rate")
    parser.add_argument("--no-mqtt", action="store_true", help="UI-only: drive from the browser")
    parser.add_argument("--no-edge", action="store_true", help="do not emulate the Edge CNN layer")
    args = parser.parse_args()

    mqtt_host = None if args.no_mqtt else env("MQTT_HOST", "127.0.0.1")
    sim = Simulation(args.seed, people=args.people, boxes=args.boxes, camera_fps=args.fps,
                     mqtt_host=mqtt_host, mqtt_port=env_int("MQTT_PORT", 1883), edge=not args.no_edge)
    sim.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(sim))
    server.daemon_threads = True

    def shutdown(*_args: Any) -> None:
        sim.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print("[SIM] seed={} MQTT={} UI: http://localhost:{}/  camera: http://localhost:{}/stream".format(
        sim.world.seed, mqtt_host or "off", args.port, args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
