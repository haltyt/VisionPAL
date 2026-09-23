#!/usr/bin/env python3
"""One-command local simulation: MQTT broker + virtual JetBot + Cognition layers.

    python3 -m Simulator.launch                         # sim + connectome + async_vla
    python3 -m Simulator.launch --layers all            # + survival, explore, jev (if key)
    python3 -m Simulator.launch --layers vla,jev --seed 7

Then open http://localhost:8554/ in a browser.

Every child process gets MQTT_HOST / CAMERA_URL pointing at the simulator via
environment variables, which take precedence over .env (see vp_env.py), so a
.env written for the real robot does not need to be edited.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vp_env import env  # noqa: E402  (loads .env so TYPESAFE_API_KEY etc. are visible)

PY = sys.executable

# name → (argv, needs)  — argv is relative to the repo root.
LAYERS: Dict[str, List[str]] = {
    "connectome": [PY, "-m", "Cognition.connectome.mqtt_connectome", "--source", "{camera}", "--fps", "12"],
    "vla": [PY, "Cognition/async_vla.py", "--no-cloud"],
    "survival": [PY, "Cognition/survival_engine.py"],
    "explore": [PY, "Cognition/explore_behavior.py"],
    "jev": [PY, "-m", "Cognition.jev.jev_decider"],
}
DEFAULT_LAYERS = ["connectome", "vla"]


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_broker(port: int) -> Optional[subprocess.Popen]:
    """Use an already-running broker, else mosquitto, else docker eclipse-mosquitto."""
    if port_open("127.0.0.1", port):
        print("[LAUNCH] MQTT broker already running on :{}".format(port))
        return None
    if shutil.which("mosquitto"):
        print("[LAUNCH] starting mosquitto on :{}".format(port))
        proc = subprocess.Popen(["mosquitto", "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    elif shutil.which("docker"):
        print("[LAUNCH] starting eclipse-mosquitto container on :{}".format(port))
        conf = os.path.join(ROOT, "Simulator", "mosquitto.conf")
        proc = subprocess.Popen(["docker", "run", "--rm", "--name", "visionpal-sim-mqtt", "-p", "{}:1883".format(port),
                                 "-v", "{}:/mosquitto/config/mosquitto.conf:ro".format(conf),
                                 "eclipse-mosquitto:2"])
    else:
        sys.exit("[LAUNCH] No MQTT broker found. Install mosquitto (brew/apt install mosquitto) or Docker, "
                 "or run with --no-mqtt for a UI-only session.")
    for _ in range(50):
        if port_open("127.0.0.1", port):
            return proc
        if proc.poll() is not None:
            sys.exit("[LAUNCH] broker exited early (port {} in use?)".format(port))
        time.sleep(0.2)
    sys.exit("[LAUNCH] broker did not come up on :{}".format(port))


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the VisionPAL browser simulator stack")
    parser.add_argument("--layers", default=",".join(DEFAULT_LAYERS),
                        help="comma list of {} or 'all' / 'none'".format(",".join(LAYERS)))
    parser.add_argument("--port", type=int, default=8554, help="simulator HTTP port")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--people", type=int, default=1)
    parser.add_argument("--no-mqtt", action="store_true", help="UI-only simulator, no broker or layers")
    args = parser.parse_args()

    if args.layers == "all":
        layers = list(LAYERS)
    elif args.layers in ("", "none") or args.no_mqtt:
        layers = []
    else:
        layers = [name.strip() for name in args.layers.split(",") if name.strip()]
        unknown = [name for name in layers if name not in LAYERS]
        if unknown:
            sys.exit("[LAUNCH] unknown layers: {}".format(", ".join(unknown)))
    if "jev" in layers and not env("TYPESAFE_API_KEY"):
        print("[LAUNCH] TYPESAFE_API_KEY not set: skipping the jev layer")
        layers.remove("jev")

    camera = "http://127.0.0.1:{}/stream".format(args.port)
    child_env = dict(os.environ,
                     MQTT_HOST="127.0.0.1", MQTT_PORT=str(args.mqtt_port),
                     CAMERA_URL=camera, CAMERA_SNAP_URL="http://127.0.0.1:{}/snap".format(args.port),
                     PYTHONUNBUFFERED="1")

    procs: List[subprocess.Popen] = []
    broker = None if args.no_mqtt else start_broker(args.mqtt_port)

    sim_cmd = [PY, "-m", "Simulator.sim_server", "--port", str(args.port), "--people", str(args.people)]
    if args.seed is not None:
        sim_cmd += ["--seed", str(args.seed)]
    if args.no_mqtt:
        sim_cmd.append("--no-mqtt")
    procs.append(subprocess.Popen(sim_cmd, cwd=ROOT, env=child_env))
    for _ in range(50):
        if port_open("127.0.0.1", args.port):
            break
        time.sleep(0.2)

    for name in layers:
        argv = [a.format(camera=camera) for a in LAYERS[name]]
        print("[LAUNCH] {}: {}".format(name, " ".join(argv[1:])))
        procs.append(subprocess.Popen(argv, cwd=ROOT, env=child_env))

    print("\n  ▶ Simulator UI: http://localhost:{}/\n    layers: {}\n    Ctrl+C to stop\n".format(
        args.port, ", ".join(layers) or "(none)"))

    def shutdown(*_args: object) -> None:
        for proc in reversed(procs + ([broker] if broker else [])):
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 5
        for proc in procs + ([broker] if broker else []):
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    while True:
        for proc in procs:
            if proc.poll() is not None and proc is procs[0]:
                print("[LAUNCH] simulator exited; shutting down")
                shutdown()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
