#!/usr/bin/env python3
"""
Umwelt Battle Server — MQTT-based battle engine for Vision Pro AR
Listens for battle commands via MQTT, runs battles, publishes state updates.

MQTT Topics:
  Subscribe:
    vision_pal/battle/command  — {"action": "start"|"attack"|"special"|"dodge", ...}
  Publish:
    vision_pal/battle/state    — full battle state (monster, HP, turn log)
    vision_pal/battle/scene    — generated battle scene image path
    vision_pal/battle/monster_image — monster image path for AR display

Usage:
  python3 battle_server.py [--broker 192.168.3.5] [--image /tmp/jetbot_snap.jpg]
"""

import argparse
import json
import os
import sys
import time
import random
import subprocess
import threading

# Add parent for imports
sys.path.insert(0, os.path.dirname(__file__))
from umwelt_battle import (
    analyze_scene, generate_monster, PalStats, BattleEngine,
    generate_battle_image, gemini_text, get_gemini_key
)

# paho-mqtt v1/v2 compat
try:
    import paho.mqtt.client as mqtt
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        PAHO_V2 = True
    except ImportError:
        PAHO_V2 = False
except ImportError:
    print("pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)

# ── MQTT Topics ─────────────────────────────────────────

TOPIC_COMMAND = "vision_pal/battle/command"
TOPIC_STATE = "vision_pal/battle/state"
TOPIC_SCENE = "vision_pal/battle/scene"
TOPIC_MONSTER_IMG = "vision_pal/battle/monster_image"
TOPIC_ENCOUNTER = "vision_pal/battle/encounter"

# ── Battle Server ───────────────────────────────────────

class BattleServer:
    def __init__(self, broker: str, port: int, image_path: str = None):
        self.broker = broker
        self.port = port
        self.image_path = image_path
        self.engine: BattleEngine = None
        self.pal: PalStats = None
        self.monster: dict = None
        self.scene: dict = None
        self.battle_active = False
        self.turn_history = []

        # MQTT setup
        if PAHO_V2:
            self.client = mqtt.Client(CallbackAPIVersion.VERSION2,
                                      client_id="battle-server")
        else:
            self.client = mqtt.Client(client_id="battle-server")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, *args):
        print(f"[Battle] Connected to MQTT {self.broker}:{self.port}")
        self.client.subscribe(TOPIC_COMMAND, qos=1)
        print(f"[Battle] Subscribed to {TOPIC_COMMAND}")
        # Publish ready state
        self._publish_state({"status": "ready", "battle_active": False})

    def _on_message(self, *args):
        # paho v1: (client, userdata, msg), v2: same
        msg = args[-1] if len(args) >= 3 else args[1]
        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"[Battle] Parse error: {e}")
            return

        action = payload.get("action", "")
        print(f"[Battle] Command: {action} {payload}")

        if action == "start":
            self._handle_start(payload)
        elif action in ("attack", "special", "dodge"):
            self._handle_action(action)
        elif action == "status":
            self._publish_full_state()
        elif action == "reset":
            self._handle_reset()

    def _handle_start(self, payload):
        """Start a new battle — analyze scene, generate monster."""
        emotion = payload.get("emotion", "curious")
        image = payload.get("image", self.image_path)

        if not image or not os.path.exists(image):
            self._publish_state({"status": "error", "message": "No image available"})
            return

        self._publish_state({"status": "analyzing", "phase": "scene"})

        try:
            # Step 1: Analyze scene
            print("[Battle] Analyzing scene...")
            self.scene = analyze_scene(image)
            print(f"[Battle] Scene: {self.scene['environment']}")

            self._publish_state({"status": "analyzing", "phase": "monster"})

            # Step 2: Generate monster
            print("[Battle] Generating monster...")
            self.monster = generate_monster(self.scene)
            print(f"[Battle] Monster: {self.monster['name']}")

            # Step 3: Init battle
            self.pal = PalStats(emotion=emotion)
            self.engine = BattleEngine(self.pal, self.monster, self.scene)
            self.battle_active = True
            self.turn_history = []

            # Publish encounter data
            encounter = {
                "status": "encounter",
                "battle_active": True,
                "scene": self.scene,
                "monster": {
                    "name": self.monster["name"],
                    "name_en": self.monster.get("name_en", ""),
                    "type": self.monster["type"],
                    "description": self.monster["description"],
                    "hp": self.monster["hp"],
                    "max_hp": self.monster["hp"],
                    "attack": self.monster["attack"],
                    "defense": self.monster["defense"],
                    "special_move": self.monster["special_move"],
                    "special_desc": self.monster["special_desc"],
                    "weakness": self.monster["weakness"],
                    "personality": self.monster.get("personality", ""),
                },
                "pal": {
                    "hp": self.pal.hp,
                    "max_hp": self.pal.max_hp,
                    "emotion": self.pal.emotion,
                    "attack": self.pal.attack,
                    "defense": self.pal.defense,
                    "speed": self.pal.speed,
                    "luck": self.pal.luck,
                },
                "turn": 0,
                "log": [],
            }
            self.client.publish(TOPIC_ENCOUNTER, json.dumps(encounter, ensure_ascii=False), qos=1)
            self._publish_state(encounter)

            # Generate monster image in background
            threading.Thread(target=self._generate_monster_image, daemon=True).start()

        except Exception as e:
            print(f"[Battle] Error: {e}")
            self._publish_state({"status": "error", "message": str(e)})

    def _handle_action(self, action: str):
        """Process a battle action (attack/special/dodge)."""
        if not self.battle_active or not self.engine:
            self._publish_state({"status": "error", "message": "No active battle"})
            return

        # Pal's turn
        pal_msg = self.engine.pal_attack(action)
        turn_entry = {"turn": self.engine.turn, "pal_action": action, "pal_msg": pal_msg}

        if self.engine.is_over:
            turn_entry["monster_msg"] = None
            self.turn_history.append(turn_entry)
            self._finish_battle()
            return

        # Monster's turn
        monster_msg = self.engine.monster_attack()
        turn_entry["monster_msg"] = monster_msg
        self.turn_history.append(turn_entry)

        if self.engine.is_over:
            self._finish_battle()
            return

        # Publish updated state
        self._publish_full_state()

    def _finish_battle(self):
        """Battle ended — publish result."""
        won = self.engine.pal_won
        self.battle_active = False

        result = {
            "status": "victory" if won else "defeat",
            "battle_active": False,
            "monster_name": self.monster["name"],
            "turns": self.engine.turn,
            "pal_hp": self.pal.hp,
            "monster_hp": self.engine.monster_hp,
            "log": self.turn_history,
        }
        self._publish_state(result)
        print(f"[Battle] {'Victory!' if won else 'Defeat...'} in {self.engine.turn} turns")

        # Generate result image in background
        phase = "victory" if won else "defeat"
        threading.Thread(target=self._generate_scene_image, args=(phase,), daemon=True).start()

    def _handle_reset(self):
        """Reset battle state."""
        self.engine = None
        self.pal = None
        self.monster = None
        self.scene = None
        self.battle_active = False
        self.turn_history = []
        self._publish_state({"status": "ready", "battle_active": False})

    def _publish_full_state(self):
        """Publish complete battle state."""
        if not self.engine:
            self._publish_state({"status": "ready", "battle_active": False})
            return

        state = {
            "status": "battle",
            "battle_active": True,
            "turn": self.engine.turn,
            "pal": {
                "hp": self.pal.hp,
                "max_hp": self.pal.max_hp,
                "emotion": self.pal.emotion,
                "attack": self.pal.attack,
                "defense": self.pal.defense,
            },
            "monster": {
                "name": self.monster["name"],
                "type": self.monster["type"],
                "hp": self.engine.monster_hp,
                "max_hp": self.engine.monster_max_hp,
            },
            "log": self.turn_history[-3:],  # last 3 turns
        }
        self._publish_state(state)

    def _publish_state(self, data: dict):
        """Publish state to MQTT."""
        self.client.publish(TOPIC_STATE, json.dumps(data, ensure_ascii=False), qos=1)

    def _generate_monster_image(self):
        """Generate monster image using Nano Banana Pro."""
        try:
            monster_desc = self.monster.get("description", "")
            monster_name = self.monster.get("name_en", "cat monster")
            prompt = (
                f"A fantasy cat monster called {monster_name}. {monster_desc} "
                f"Environment: {self.scene.get('environment', '')}. "
                f"Full body, facing viewer, dramatic lighting, anime game art style, "
                f"transparent background, character design sheet style."
            )
            out_path = "/tmp/monster_current.png"
            script = "/app/skills/nano-banana-pro/scripts/generate_image.py"
            result = subprocess.run(
                ["uv", "run", script, "--prompt", prompt, "--filename", out_path, "--resolution", "1K"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self.client.publish(TOPIC_MONSTER_IMG,
                                    json.dumps({"path": out_path}), qos=1)
                print(f"[Battle] Monster image: {out_path}")
        except Exception as e:
            print(f"[Battle] Monster image gen failed: {e}")

    def _generate_scene_image(self, phase: str):
        """Generate battle scene image."""
        try:
            ts = time.strftime("%Y-%m-%d-%H-%M-%S")
            out_path = f"/tmp/battle_{ts}.png"
            media = generate_battle_image(self.scene, self.monster, phase, out_path)
            if media:
                self.client.publish(TOPIC_SCENE,
                                    json.dumps({"path": out_path, "phase": phase}), qos=1)
                print(f"[Battle] Scene image: {out_path}")
        except Exception as e:
            print(f"[Battle] Scene image gen failed: {e}")

    def run(self):
        """Start the battle server."""
        print(f"[Battle] Connecting to {self.broker}:{self.port}...")
        self.client.connect(self.broker, self.port, keepalive=60)
        print("[Battle] Server running. Waiting for commands...")
        self.client.loop_forever()


def main():
    parser = argparse.ArgumentParser(description="Umwelt Battle MQTT Server")
    parser.add_argument("--broker", default="192.168.3.5", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--image", default="/tmp/jetbot_snap.jpg", help="Default image path")
    args = parser.parse_args()

    server = BattleServer(args.broker, args.port, args.image)
    server.run()


if __name__ == "__main__":
    main()
