import json
import math
import os
import sys
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Simulator.camera import Camera
from Simulator.sensors import BodyModel, EdgeSensor
from Simulator.sim_server import TOPIC_COLLISION, TOPIC_MOVE, Simulation, make_handler
from Simulator.world import MAX_LINEAR, Box, Person, World


def empty_world():
    world = World(width=4.0, height=3.0)
    world.robot.x, world.robot.y, world.robot.theta = 1.0, 1.5, 0.0
    return world


class WorldTests(unittest.TestCase):
    def test_forward_moves_along_heading(self):
        world = empty_world()
        world.set_command("forward", 1.0)
        for _ in range(30):
            world.step(1 / 30)
        self.assertAlmostEqual(world.robot.x, 1.0 + MAX_LINEAR, places=2)
        self.assertAlmostEqual(world.robot.y, 1.5, places=6)

    def test_left_turns_counter_clockwise_in_place(self):
        world = empty_world()
        world.set_command("left", 0.5)
        world.step(0.1)
        self.assertGreater(world.robot.theta, 0)
        self.assertEqual((world.robot.x, world.robot.y), (1.0, 1.5))

    def test_unknown_direction_stops(self):
        world = empty_world()
        world.set_command("dance", 1.0)
        self.assertEqual(world.robot.direction, "stop")

    def test_bump_reports_once_per_contact(self):
        world = empty_world()
        world.boxes.append(Box(1.5, 1.5, 0.3, 0.3, 0.45, (0, 0, 255)))
        world.set_command("forward", 1.0)
        events = [world.step(1 / 30) for _ in range(90)]
        bumps = [e for e in events if e]
        self.assertEqual(len(bumps), 1)
        self.assertEqual(bumps[0]["direction"], "front")
        self.assertLess(world.robot.x, 1.35 - 0.09 + 1e-6)
        self.assertEqual(world.collisions, 1)

    def test_rays_measure_distance_to_wall(self):
        world = empty_world()
        dist = world.cast_rays(np.array([0.0, math.pi]))
        np.testing.assert_allclose(dist, [3.0, 1.0], atol=1e-6)

    def test_rays_see_people(self):
        world = empty_world()
        world.people.append(Person(2.0, 1.5, (255, 0, 0)))
        self.assertAlmostEqual(float(world.cast_rays(np.array([0.0]))[0]), 1.0, places=6)

    def test_generated_world_is_reproducible_and_starts_free(self):
        a, b = World.generate(seed=5), World.generate(seed=5)
        self.assertEqual([(x.x, x.y) for x in a.boxes], [(x.x, x.y) for x in b.boxes])
        self.assertTrue(a._free(a.robot.x, a.robot.y, 0.09))


class CameraTests(unittest.TestCase):
    def test_render_shape_and_near_box_fills_view(self):
        world = empty_world()
        camera = Camera(160, 120, noise=0)
        far = camera.render(world)
        world.boxes.append(Box(1.35, 1.5, 0.3, 0.6, 0.45, (0, 0, 255)))
        near = camera.render(world)
        self.assertEqual(far.shape, (120, 160, 3))
        self.assertEqual(far.dtype, np.uint8)
        centre = near[40:60, 70:90].astype(int)
        self.assertGreater((centre[..., 2] - centre[..., 0]).mean(), 60)  # blue box dominates

    def test_forward_motion_changes_image(self):
        world = empty_world()
        world.boxes.append(Box(2.5, 1.5, 0.4, 0.4, 0.45, (200, 50, 50)))
        camera = Camera(160, 120, noise=0)
        before = camera.render(world)
        world.robot.x += 0.3
        after = camera.render(world)
        self.assertGreater(np.abs(before.astype(int) - after.astype(int)).mean(), 2.0)


class SensorTests(unittest.TestCase):
    def test_blocked_probability_rises_as_obstacle_nears(self):
        far = EdgeSensor.blocked_from_distance(1.0)
        mid = EdgeSensor.blocked_from_distance(0.4)
        near = EdgeSensor.blocked_from_distance(0.15)
        self.assertLess(far, 0.05)
        self.assertLess(far, mid)
        self.assertGreater(near, 0.9)

    def test_edge_payload_matches_real_edge_layer(self):
        world = empty_world()
        edge = EdgeSensor(noise=0).sense(world)
        for key in ("blocked_prob", "free_prob", "danger_zone", "motor_running", "timestamp"):
            self.assertIn(key, edge)

    def test_predicted_collision_needs_motion_and_has_cooldown(self):
        sensor = EdgeSensor(threshold=0.85)
        edge = {"blocked_prob": 0.95, "motor_running": False}
        self.assertIsNone(sensor.predicted_collision(edge, now=10.0))
        edge["motor_running"] = True
        self.assertEqual(sensor.predicted_collision(edge, now=10.0)["severity"], "predicted")
        self.assertIsNone(sensor.predicted_collision(edge, now=11.0))
        self.assertIsNotNone(sensor.predicted_collision(edge, now=13.5))

    def test_body_state_has_survival_engine_fields(self):
        world = empty_world()
        body = BodyModel(battery_minutes=1.0)
        world.set_command("forward", 1.0)
        body.update(world, 30.0)
        state = body.state(world)
        for key in ("cpu_temp", "voltage", "idle_sec", "collision_ago_sec", "disk_percent", "memory_percent"):
            self.assertIn(key, state)
        self.assertLess(state["voltage"], 12.6)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(seed=1, mqtt_host=None)

    def test_ui_drive_applies_locally_without_mqtt(self):
        self.sim.command({"action": "drive", "direction": "left", "speed": 0.3})
        self.assertEqual(self.sim.world.robot.direction, "left")
        self.assertEqual(self.sim.world.robot.source, "sim_ui")
        self.assertEqual(self.sim.move_log[-1]["direction"], "left")

    def test_bad_move_payload_stops(self):
        self.sim.apply_move({"direction": "forward", "speed": "fast"})
        self.assertEqual(self.sim.world.robot.speed, 0.0)

    def test_emit_records_non_move_topics(self):
        self.sim.emit(TOPIC_COLLISION, {"collision": True})
        self.assertTrue(self.sim.layers[TOPIC_COLLISION]["payload"]["collision"])

    def test_reset_keeps_seed_randomize_changes_it(self):
        seed = self.sim.world.seed
        self.sim.command({"action": "reset"})
        self.assertEqual(self.sim.world.seed, seed)
        self.sim.command({"action": "randomize", "seed": seed + 1})
        self.assertEqual(self.sim.world.seed, seed + 1)

    def test_unknown_command_rejected(self):
        self.assertFalse(self.sim.command({"action": "fly"})["ok"])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = Simulation(seed=2, mqtt_host=None, camera_fps=20)
        cls.sim.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.sim))
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.sim.stop()
        cls.server.shutdown()

    def test_snapshot_is_jpeg(self):
        with urllib.request.urlopen(self.base + "/snap", timeout=5) as resp:
            self.assertEqual(resp.headers["Content-Type"], "image/jpeg")
            self.assertEqual(resp.read(2), b"\xff\xd8")

    def test_stream_is_multipart_mjpeg(self):
        with urllib.request.urlopen(self.base + "/stream", timeout=5) as resp:
            self.assertIn("multipart/x-mixed-replace", resp.headers["Content-Type"])
            self.assertTrue(resp.read(13).startswith(b"--jpgboundary"))

    def test_command_and_state_api(self):
        req = urllib.request.Request(self.base + "/api/cmd", method="POST",
                                     data=json.dumps({"action": "drive", "direction": "right"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertTrue(json.load(resp)["ok"])
        time.sleep(0.1)
        with urllib.request.urlopen(self.base + "/api/state", timeout=5) as resp:
            state = json.load(resp)
        self.assertEqual(state["world"]["robot"]["direction"], "right")
        self.assertEqual(state["layers"][TOPIC_MOVE]["payload"]["source"], "sim_ui")

    def test_ui_is_served(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as resp:
            self.assertIn(b"VisionPAL Simulator", resp.read())


if __name__ == "__main__":
    unittest.main()
