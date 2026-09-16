import os
import sys
import unittest

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Cognition.connectome.connectome_backend import ConnectomeBackend


@unittest.skipUnless(HAS_CV2, "opencv-python is not installed")
class SensoryEncoderTests(unittest.TestCase):
    def test_expanding_square_produces_looming(self):
        from Cognition.connectome.sensory_encoder import SensoryEncoder
        encoder = SensoryEncoder(width=160, height=120, smoothing=0.0)
        small = np.zeros((240, 320, 3), dtype=np.uint8)
        large = np.zeros_like(small)
        cv2.rectangle(small, (130, 90), (190, 150), (255, 255, 255), -1)
        cv2.rectangle(large, (90, 50), (230, 190), (255, 255, 255), -1)
        encoder.encode(small)
        state = encoder.encode(large)
        self.assertTrue(state["frame_valid"])
        self.assertGreater(state["looming"], 0.05)

    def test_static_frame_has_little_motion(self):
        from Cognition.connectome.sensory_encoder import SensoryEncoder
        encoder = SensoryEncoder(smoothing=0.0)
        frame = np.full((120, 160, 3), 128, dtype=np.uint8)
        encoder.encode(frame)
        state = encoder.encode(frame.copy())
        self.assertLess(state["motion_left"] + state["motion_right"], 0.01)

    def test_service_pipeline_detects_expansion(self):
        from Cognition.connectome.mqtt_connectome import ConnectomeService
        service = ConnectomeService("unused", mqtt_enabled=False)
        small = np.zeros((240, 320, 3), dtype=np.uint8)
        large = np.zeros_like(small)
        cv2.rectangle(small, (130, 90), (190, 150), (255, 255, 255), -1)
        cv2.rectangle(large, (90, 50), (230, 190), (255, 255, 255), -1)
        service.process(small, 1.0 / 15.0)
        result = service.process(large, 1.0 / 15.0)
        self.assertTrue(result["action"]["reflex"])
        self.assertGreater(result["sensory"]["looming"], 0.2)


class ConnectomeBackendTests(unittest.TestCase):
    def test_right_motion_turns_left(self):
        result = ConnectomeBackend().step({
            "motion_left": 0.05,
            "motion_right": 0.8,
            "looming": 0.3,
            "luminance": 0.5,
            "contrast": 0.5,
            "frame_valid": True,
        })
        self.assertEqual(result["action"]["direction"], "left")
        self.assertTrue(result["action"]["reflex"])

    def test_strong_looming_retreats(self):
        result = ConnectomeBackend().step({
            "motion_left": 0.7,
            "motion_right": 0.7,
            "looming": 0.9,
            "frame_valid": True,
        })
        self.assertEqual(result["action"]["direction"], "backward")

    def test_safe_scene_does_not_command_forward(self):
        result = ConnectomeBackend().step({
            "motion_left": 0.0,
            "motion_right": 0.0,
            "looming": 0.0,
            "frame_valid": True,
        })
        self.assertEqual(result["action"]["direction"], "forward")
        self.assertFalse(result["action"]["reflex"])


if __name__ == "__main__":
    unittest.main()
