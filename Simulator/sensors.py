"""Virtual JetBot sensors producing the same MQTT payloads as the real robot.

- EdgeSensor   ≈ JetBot/collision_detect_v2.py  (vision_pal/edge/state + predicted collisions)
- body_state() ≈ Cognition/body_sensor.py       (vision_pal/body/state)
- bump events  ≈ JetBot/imu_collision.py        (vision_pal/perception/collision)
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, Optional

import numpy as np

from .world import ROBOT_RADIUS, World

CONE = np.radians(np.linspace(-30, 30, 9))


class EdgeSensor:
    """Emulates the ResNet18 blocked/free classifier from forward ray distances."""

    def __init__(self, threshold: float = 0.85, noise: float = 0.03, rng: Optional[random.Random] = None):
        self.threshold = threshold
        self.noise = noise
        self.rng = rng or random.Random(0)
        self.frames = 0
        self.collisions = 0
        self.cooldown_until = 0.0
        self.last_min_distance = math.inf

    @staticmethod
    def blocked_from_distance(distance: float) -> float:
        """~0.5 at 30 cm of free space in front of the bumper, ~0.95 at 10 cm."""
        clearance = distance - ROBOT_RADIUS
        return 1.0 / (1.0 + math.exp((clearance - 0.22) / 0.05))

    def sense(self, world: World) -> Dict[str, Any]:
        self.frames += 1
        dists = world.cast_rays(world.robot.theta + CONE)
        self.last_min_distance = float(dists.min())
        blocked = self.blocked_from_distance(self.last_min_distance)
        blocked = min(1.0, max(0.0, blocked + self.rng.gauss(0.0, self.noise)))
        return {
            "blocked_prob": round(blocked, 4),
            "free_prob": round(1.0 - blocked, 4),
            "danger_zone": blocked > 0.5,
            "inference_ms": 0.0,
            "avg_inference_ms": 0.0,
            "total_frames": self.frames,
            "collisions": self.collisions,
            "motor_running": world.robot.direction != "stop" and world.robot.speed > 0,
            "timestamp": time.time(),
            "simulated": True,
        }

    def predicted_collision(self, edge: Dict[str, Any], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Same rule as collision_detect_v2: blocked > threshold while moving, 3 s cooldown."""
        now = time.time() if now is None else now
        if not edge["motor_running"] or edge["blocked_prob"] <= self.threshold or now < self.cooldown_until:
            return None
        self.cooldown_until = now + 3.0
        self.collisions += 1
        return {
            "collision": True,
            "blocked_prob": edge["blocked_prob"],
            "severity": "predicted",
            "method": "sim_cnn",
            "timestamp": now,
        }


class BodyModel:
    """Slowly varying body signals for the Survival Engine."""

    def __init__(self, battery_minutes: float = 45.0):
        self.boot = time.time()
        self.motor_load = 0.0
        self.battery = 1.0
        self.battery_minutes = battery_minutes
        self.motor_last_active = 0.0

    def update(self, world: World, dt: float) -> None:
        active = world.robot.direction != "stop" and world.robot.speed > 0
        load = world.robot.speed if active else 0.0
        self.motor_load += (load - self.motor_load) * min(1.0, dt / 20.0)
        drain = dt / (self.battery_minutes * 60.0) * (0.4 + load)
        self.battery = max(0.0, self.battery - drain)
        if active:
            self.motor_last_active = time.time()

    def recharge(self) -> None:
        self.battery = 1.0

    def state(self, world: World) -> Dict[str, Any]:
        now = time.time()
        idle_ref = self.motor_last_active or self.boot
        collision_ago = now - world.last_collision_time if world.last_collision_time else -1
        return {
            "timestamp": now,
            "cpu_temp": round(46.0 + 22.0 * self.motor_load + random.uniform(-0.5, 0.5), 1),
            "disk_percent": 61.0,
            "memory_percent": round(55.0 + 10.0 * self.motor_load, 1),
            "voltage": round(10.8 + 1.8 * self.battery, 2),
            "battery": round(self.battery, 3),
            "motor_active": world.robot.direction != "stop" and world.robot.speed > 0,
            "idle_sec": round(now - idle_ref, 1),
            "collision_ago_sec": round(collision_ago, 1),
            "uptime_sec": round(now - self.boot, 1),
            "simulated": True,
        }
