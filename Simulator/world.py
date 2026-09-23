"""2D world + differential-drive JetBot physics for the browser simulator.

Units are meters / seconds / radians.  The world is a room made of wall
segments, box obstacles (4 segments each) and wandering "people" (circles).
Motor commands follow JetBot/mqtt_robot.py semantics: the last command stays
active until a new one arrives ("duration" is metadata only).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROBOT_RADIUS = 0.09
MAX_LINEAR = 0.45      # m/s at speed=1.0 (JetBot TT motors, roughly)
MAX_ANGULAR = 3.2      # rad/s at speed=1.0 when spinning in place
WALL_HEIGHT = 2.4
PERSON_RADIUS = 0.16
PERSON_HEIGHT = 1.6

WALL_COLOR = (200, 190, 170)
BOX_COLORS = [(70, 110, 190), (190, 90, 60), (80, 160, 90), (170, 150, 60), (140, 80, 160)]
PERSON_COLORS = [(220, 70, 70), (60, 150, 220), (240, 170, 40)]


@dataclass
class Box:
    x: float
    y: float
    w: float
    d: float
    h: float
    color: Tuple[int, int, int]

    def corners(self) -> List[Tuple[float, float]]:
        hx, hy = self.w / 2, self.d / 2
        return [(self.x - hx, self.y - hy), (self.x + hx, self.y - hy),
                (self.x + hx, self.y + hy), (self.x - hx, self.y + hy)]


@dataclass
class Person:
    x: float
    y: float
    color: Tuple[int, int, int]
    heading: float = 0.0
    speed: float = 0.25
    next_turn: float = 0.0


@dataclass
class Robot:
    x: float = 0.6
    y: float = 0.6
    theta: float = 0.0
    direction: str = "stop"
    speed: float = 0.0
    source: str = ""
    bumped: bool = False


@dataclass
class World:
    width: float = 4.0
    height: float = 3.0
    boxes: List[Box] = field(default_factory=list)
    people: List[Person] = field(default_factory=list)
    robot: Robot = field(default_factory=Robot)
    seed: int = 0
    time: float = 0.0
    trail: List[Tuple[float, float]] = field(default_factory=list)
    distance_travelled: float = 0.0
    collisions: int = 0
    last_collision_time: Optional[float] = None

    # ── construction ──

    @classmethod
    def generate(cls, seed: Optional[int] = None, n_boxes: int = 5, n_people: int = 1) -> "World":
        seed = random.randrange(1 << 30) if seed is None else seed
        rng = random.Random(seed)
        world = cls(seed=seed)
        world.robot = Robot(x=0.5, y=0.5, theta=rng.uniform(0, math.pi / 2))
        attempts = 0
        while len(world.boxes) < n_boxes and attempts < 200:
            attempts += 1
            w, d = rng.uniform(0.25, 0.6), rng.uniform(0.25, 0.6)
            box = Box(rng.uniform(0.4 + w / 2, world.width - 0.2 - w / 2),
                      rng.uniform(0.2 + d / 2, world.height - 0.2 - d / 2),
                      w, d, rng.choice([0.3, 0.45, 0.8]), BOX_COLORS[len(world.boxes) % len(BOX_COLORS)])
            if math.hypot(box.x - world.robot.x, box.y - world.robot.y) < 0.8:
                continue
            if any(abs(box.x - o.x) < (box.w + o.w) / 2 + 0.3 and abs(box.y - o.y) < (box.d + o.d) / 2 + 0.3
                   for o in world.boxes):
                continue
            world.boxes.append(box)
        for i in range(n_people):
            for _ in range(100):
                px, py = rng.uniform(0.5, world.width - 0.5), rng.uniform(0.5, world.height - 0.5)
                if world._free(px, py, PERSON_RADIUS + 0.1) and math.hypot(px - 0.5, py - 0.5) > 1.2:
                    world.people.append(Person(px, py, PERSON_COLORS[i % len(PERSON_COLORS)],
                                               heading=rng.uniform(-math.pi, math.pi)))
                    break
        world._rng = rng
        return world

    def add_box(self, x: float, y: float, size: float = 0.35) -> bool:
        box = Box(x, y, size, size, 0.45, BOX_COLORS[len(self.boxes) % len(BOX_COLORS)])
        if math.hypot(x - self.robot.x, y - self.robot.y) < size / 2 + ROBOT_RADIUS + 0.05:
            return False
        self.boxes.append(box)
        return True

    def remove_box_at(self, x: float, y: float) -> bool:
        for i, b in enumerate(self.boxes):
            if abs(x - b.x) <= b.w / 2 and abs(y - b.y) <= b.d / 2:
                del self.boxes[i]
                return True
        return False

    # ── geometry ──

    def segments(self, include_people: bool = False, viewer: Optional[Tuple[float, float]] = None) -> Dict[str, np.ndarray]:
        """All vertical surfaces as arrays: a, b (N,2), zmin, zmax, color (N,3), kind (N,)."""
        W, H = self.width, self.height
        a, b, top, color, kind = [], [], [], [], []
        for p, q in [((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))]:
            a.append(p); b.append(q); top.append(WALL_HEIGHT); color.append(WALL_COLOR); kind.append(0)
        for box in self.boxes:
            c = box.corners()
            for i in range(4):
                a.append(c[i]); b.append(c[(i + 1) % 4]); top.append(box.h); color.append(box.color); kind.append(1)
        if include_people and viewer is not None:
            vx, vy = viewer
            for p in self.people:
                dx, dy = p.x - vx, p.y - vy
                dist = math.hypot(dx, dy) or 1e-6
                nx, ny = -dy / dist * PERSON_RADIUS, dx / dist * PERSON_RADIUS
                a.append((p.x - nx, p.y - ny)); b.append((p.x + nx, p.y + ny))
                top.append(PERSON_HEIGHT); color.append(p.color); kind.append(2)
        n = len(a)
        return {
            "a": np.asarray(a, dtype=np.float64).reshape(n, 2),
            "b": np.asarray(b, dtype=np.float64).reshape(n, 2),
            "zmin": np.zeros(n),
            "zmax": np.asarray(top, dtype=np.float64),
            "color": np.asarray(color, dtype=np.float64).reshape(n, 3),
            "kind": np.asarray(kind, dtype=np.int32),
        }

    def _clearance(self, x: float, y: float) -> float:
        """Distance from point to the nearest obstacle surface (walls, boxes, people)."""
        d = self._clearance_static(x, y)
        for p in self.people:
            d = min(d, math.hypot(x - p.x, y - p.y) - PERSON_RADIUS)
        return float(d)

    def _free(self, x: float, y: float, radius: float) -> bool:
        return self._clearance(x, y) > radius

    def cast_rays(self, angles: np.ndarray, x: Optional[float] = None, y: Optional[float] = None,
                  max_range: float = 5.0) -> np.ndarray:
        """Distances along world-frame angles from (x, y) to the first surface (incl. people)."""
        x = self.robot.x if x is None else x
        y = self.robot.y if y is None else y
        segs = self.segments(include_people=True, viewer=(x, y))
        dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        t = ray_segment_hits(np.array([x, y]), dirs, segs["a"], segs["b"])
        return np.minimum(t.min(axis=1), max_range)

    # ── simulation ──

    def set_command(self, direction: str, speed: float, source: str = "") -> None:
        if direction not in ("forward", "backward", "left", "right", "stop"):
            direction = "stop"
        self.robot.direction = direction
        self.robot.speed = max(0.0, min(1.0, float(speed)))
        self.robot.source = source

    def step(self, dt: float) -> Optional[Dict[str, Any]]:
        """Advance physics.  Returns a bump event dict when the robot hits something."""
        self.time += dt
        self._step_people(dt)
        r = self.robot
        v = w = 0.0
        if r.direction == "forward":
            v = MAX_LINEAR * r.speed
        elif r.direction == "backward":
            v = -MAX_LINEAR * r.speed
        elif r.direction == "left":
            w = MAX_ANGULAR * r.speed
        elif r.direction == "right":
            w = -MAX_ANGULAR * r.speed

        r.theta = (r.theta + w * dt + math.pi) % (2 * math.pi) - math.pi
        if v == 0.0:
            r.bumped = False
            return None
        nx = r.x + v * math.cos(r.theta) * dt
        ny = r.y + v * math.sin(r.theta) * dt
        if self._free(nx, ny, ROBOT_RADIUS):
            self.distance_travelled += math.hypot(nx - r.x, ny - r.y)
            r.x, r.y = nx, ny
            r.bumped = False
            if not self.trail or math.hypot(self.trail[-1][0] - r.x, self.trail[-1][1] - r.y) > 0.03:
                self.trail.append((round(r.x, 3), round(r.y, 3)))
                self.trail = self.trail[-400:]
            return None
        if r.bumped:
            return None  # already pressed against the obstacle; one event per contact
        r.bumped = True
        self.collisions += 1
        self.last_collision_time = time.time()
        impact = abs(v) / MAX_LINEAR
        return {
            "type": "collision",
            "severity": "hard" if impact > 0.7 else "medium" if impact > 0.4 else "light",
            "delta_g": round(0.8 + 2.5 * impact, 2),
            "direction": "front" if v > 0 else "back",
        }

    def _step_people(self, dt: float) -> None:
        rng = getattr(self, "_rng", random)
        for p in self.people:
            if self.time >= p.next_turn:
                p.heading += rng.uniform(-1.5, 1.5)
                p.speed = rng.choice([0.0, 0.15, 0.25, 0.3])
                p.next_turn = self.time + rng.uniform(1.5, 5.0)
            nx = p.x + p.speed * math.cos(p.heading) * dt
            ny = p.y + p.speed * math.sin(p.heading) * dt
            others = [q for q in self.people if q is not p]
            ok = self._clearance_static(nx, ny) > PERSON_RADIUS + 0.05
            ok = ok and math.hypot(nx - self.robot.x, ny - self.robot.y) > PERSON_RADIUS + ROBOT_RADIUS + 0.05
            ok = ok and all(math.hypot(nx - q.x, ny - q.y) > 2 * PERSON_RADIUS for q in others)
            if ok:
                p.x, p.y = nx, ny
            else:
                p.heading += math.pi * rng.uniform(0.5, 1.5)

    def _clearance_static(self, x: float, y: float) -> float:
        if not (0 < x < self.width and 0 < y < self.height):
            return 0.0
        for box in self.boxes:
            if abs(x - box.x) < box.w / 2 and abs(y - box.y) < box.d / 2:
                return 0.0
        segs = self.segments()
        return float(_point_segment_distance(np.array([x, y]), segs["a"], segs["b"]).min())

    def to_dict(self) -> Dict[str, Any]:
        r = self.robot
        return {
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "time": round(self.time, 2),
            "robot": {"x": round(r.x, 3), "y": round(r.y, 3), "theta": round(r.theta, 3),
                      "radius": ROBOT_RADIUS, "direction": r.direction, "speed": r.speed,
                      "source": r.source, "bumped": r.bumped},
            "boxes": [{"x": b.x, "y": b.y, "w": b.w, "d": b.d, "h": b.h, "color": b.color} for b in self.boxes],
            "people": [{"x": round(p.x, 3), "y": round(p.y, 3), "r": PERSON_RADIUS, "color": p.color}
                       for p in self.people],
            "trail": self.trail[-200:],
            "distance": round(self.distance_travelled, 2),
            "collisions": self.collisions,
        }


def _cross(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]


def ray_segment_hits(origin: np.ndarray, dirs: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Ray parameter t for every (ray, segment) pair; inf where there is no hit.

    With dirs scaled so their forward component is 1, t is the planar depth.
    """
    e = (b - a)[None, :, :]                 # (1, N, 2)
    r = dirs[:, None, :]                    # (W, 1, 2)
    ap = (a - origin)[None, :, :]           # (1, N, 2)
    denom = _cross(r, e)                    # (W, N)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = _cross(ap, e) / denom
        s = _cross(ap, r) / denom
    valid = (np.abs(denom) > 1e-12) & (t > 1e-6) & (s >= 0.0) & (s <= 1.0)
    return np.where(valid, t, np.inf)


def _point_segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    denom = np.maximum((ab * ab).sum(axis=1), 1e-12)
    t = np.clip(((p - a) * ab).sum(axis=1) / denom, 0.0, 1.0)
    closest = a + ab * t[:, None]
    return np.linalg.norm(closest - p, axis=1)
