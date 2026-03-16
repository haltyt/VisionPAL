#!/usr/bin/env python3
"""JetBot Explorer - Autonomous exploration with CNN obstacle avoidance.
Uses ResNet18 trained model for collision detection + CSI camera.

Usage: python3 jetbot_explorer.py [--explore] [--patrol] [--duration 60]
"""
import sys
import time
import argparse
import atexit
import cv2
import numpy as np
from Adafruit_MotorHAT import Adafruit_MotorHAT

# PyTorch imports (optional - falls back to simple detection)
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    print("[WARNING] PyTorch not available, using simple obstacle detection")

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _make_resnet18(num_classes=2):
    """Build ResNet18 without torchvision dependency."""

    class BasicBlock(nn.Module):
        expansion = 1
        def __init__(self, in_ch, out_ch, stride=1, downsample=None):
            super().__init__()
            self.conv1 = nn.Conv2d(in_ch, out_ch, 3, stride, 1, bias=False)
            self.bn1 = nn.BatchNorm2d(out_ch)
            self.conv2 = nn.Conv2d(out_ch, out_ch, 3, 1, 1, bias=False)
            self.bn2 = nn.BatchNorm2d(out_ch)
            self.downsample = downsample

        def forward(self, x):
            identity = x
            out = F.relu(self.bn1(self.conv1(x)))
            out = self.bn2(self.conv2(out))
            if self.downsample is not None:
                identity = self.downsample(x)
            out += identity
            return F.relu(out)

    class ResNet18(nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.in_ch = 64
            self.conv1 = nn.Conv2d(3, 64, 7, 2, 3, bias=False)
            self.bn1 = nn.BatchNorm2d(64)
            self.maxpool = nn.MaxPool2d(3, 2, 1)
            self.layer1 = self._make_layer(64, 2)
            self.layer2 = self._make_layer(128, 2, stride=2)
            self.layer3 = self._make_layer(256, 2, stride=2)
            self.layer4 = self._make_layer(512, 2, stride=2)
            self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
            self.fc = nn.Linear(512, num_classes)

        def _make_layer(self, out_ch, blocks, stride=1):
            downsample = None
            if stride != 1 or self.in_ch != out_ch:
                downsample = nn.Sequential(
                    nn.Conv2d(self.in_ch, out_ch, 1, stride, bias=False),
                    nn.BatchNorm2d(out_ch),
                )
            layers = [BasicBlock(self.in_ch, out_ch, stride, downsample)]
            self.in_ch = out_ch
            for _ in range(1, blocks):
                layers.append(BasicBlock(out_ch, out_ch))
            return nn.Sequential(*layers)

        def forward(self, x):
            x = self.maxpool(F.relu(self.bn1(self.conv1(x))))
            x = self.layer4(self.layer3(self.layer2(self.layer1(x))))
            x = self.avgpool(x)
            x = torch.flatten(x, 1)
            return self.fc(x)

    return ResNet18(num_classes)


class PalBot:
    """JetBot motor controller (traitlets-free)."""

    def __init__(self, i2c_bus=1, left_channel=1, right_channel=2):
        self._driver = Adafruit_MotorHAT(i2c_bus=i2c_bus)
        self._left = self._driver.getMotor(left_channel)
        self._right = self._driver.getMotor(right_channel)
        self._pins = {
            left_channel:  (1, 0),
            right_channel: (2, 3),
        }
        self._left_ch = left_channel
        self._right_ch = right_channel
        atexit.register(self.stop)

    def _set_motor(self, motor, channel, speed):
        speed = max(-1.0, min(1.0, speed))
        pwm_val = int(abs(speed) * 255)
        ina, inb = self._pins[channel]
        motor.setSpeed(pwm_val)
        if speed < 0:
            motor.run(Adafruit_MotorHAT.FORWARD)
            self._driver._pwm.setPWM(ina, 0, 0)
            self._driver._pwm.setPWM(inb, 0, pwm_val * 16)
        elif speed > 0:
            motor.run(Adafruit_MotorHAT.BACKWARD)
            self._driver._pwm.setPWM(ina, 0, pwm_val * 16)
            self._driver._pwm.setPWM(inb, 0, 0)
        else:
            motor.run(Adafruit_MotorHAT.RELEASE)
            self._driver._pwm.setPWM(ina, 0, 0)
            self._driver._pwm.setPWM(inb, 0, 0)

    def set_motors(self, left, right):
        self._set_motor(self._left, self._left_ch, left)
        self._set_motor(self._right, self._right_ch, right)

    def forward(self, speed=0.3, duration=None):
        self.set_motors(speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def backward(self, speed=0.3, duration=None):
        self.set_motors(-speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def left(self, speed=0.3, duration=None):
        self.set_motors(-speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def right(self, speed=0.3, duration=None):
        self.set_motors(speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def stop(self):
        self.set_motors(0, 0)


class Camera:
    """CSI camera via GStreamer (224x224 for CNN input)."""

    def __init__(self, width=224, height=224):
        self.width = width
        self.height = height
        pipeline = (
            'nvarguscamerasrc ! '
            'video/x-raw(memory:NVMM),width=640,height=480,framerate=21/1 ! '
            'nvvidconv ! video/x-raw,format=BGRx ! '
            'videoconvert ! video/x-raw,format=BGR ! '
            'appsink drop=true max-buffers=1'
        )
        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.cap.isOpened():
            raise RuntimeError("Failed to open CSI camera")
        for _ in range(5):
            self.cap.read()

    def capture(self):
        """Capture a frame, return BGR image resized for CNN."""
        ret, frame = self.cap.read()
        if not ret:
            return None
        return cv2.resize(frame, (self.width, self.height))

    def capture_full(self):
        """Capture full resolution frame."""
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def capture_corrected(self):
        """Capture with percentile WB v4 (70% corrected + 30% original) + CLAHE."""
        frame = self.capture_full()
        if frame is None:
            return None
        # Percentile WB with lower target
        result = frame.astype(np.float32)
        for i in range(3):
            ch = result[:,:,i]
            p95 = np.percentile(ch, 95)
            if p95 > 10:
                result[:,:,i] = np.clip(ch * (180.0 / p95), 0, 255)
        # Blend 70% corrected + 30% original for natural warmth
        frame = (result * 0.7 + frame.astype(np.float32) * 0.3).astype(np.uint8)
        # CLAHE for contrast without color shift
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        frame = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        return frame

    def save(self, path='/tmp/jetbot_cam.jpg'):
        frame = self.capture_corrected()
        if frame is not None:
            cv2.imwrite(path, frame)
            return path
        return None

    def release(self):
        self.cap.release()


class CNNObstacleDetector:
    """ResNet18-based obstacle detection using pre-trained JetBot model."""

    MODEL_PATH = '/home/jetbot/best_model_resnet18_v2.pth'

    def __init__(self, model_path=None, threshold=0.5):
        if not HAS_TORCH:
            raise RuntimeError("PyTorch required for CNN detector")

        self.threshold = threshold
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"[CNNDetector] Using device: {self.device}")

        # Load ResNet18 (custom implementation, no torchvision needed)
        model_path = model_path or self.MODEL_PATH
        self.model = _make_resnet18(num_classes=2)
        state_dict = torch.load(model_path, map_location=self.device)
        self.model.load_state_dict(state_dict)
        self.model = self.model.to(self.device)
        self.model = self.model.eval().half()
        print(f"[CNNDetector] Model loaded from {model_path}")

        # Normalization (ImageNet standard)
        self.mean = torch.Tensor([0.485, 0.456, 0.406]).to(self.device).half()
        self.std = torch.Tensor([0.229, 0.224, 0.225]).to(self.device).half()

    def preprocess(self, frame):
        """Convert BGR OpenCV frame to PyTorch tensor."""
        # BGR → RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # HWC uint8 → CHW float16
        image = torch.from_numpy(rgb.transpose(2, 0, 1).copy()).float().div(255.0)
        image = image.to(self.device).half()

        image.sub_(self.mean[:, None, None]).div_(self.std[:, None, None])
        return image[None, ...]  # Add batch dimension

    def detect(self, frame):
        """Returns (is_blocked, prob_blocked, direction_hint).
        
        frame should be 224x224 BGR image.
        """
        with torch.no_grad():
            x = self.preprocess(frame)
            y = self.model(x)
            y = F.softmax(y, dim=1)
            prob_blocked = float(y.flatten()[0])

        is_blocked = prob_blocked > self.threshold

        # Direction hint from left/right halves
        h, w = frame.shape[:2]
        left_half = frame[:, :w//2]
        right_half = frame[:, w//2:]
        # Darker side likely has the obstacle
        left_dark = np.mean(cv2.cvtColor(left_half, cv2.COLOR_BGR2GRAY))
        right_dark = np.mean(cv2.cvtColor(right_half, cv2.COLOR_BGR2GRAY))
        # Turn toward brighter side (away from obstacle)
        hint = 'right' if left_dark < right_dark else 'left'

        return is_blocked, prob_blocked, hint


class SimpleObstacleDetector:
    """Fallback: edge density + dark region detection (no PyTorch needed)."""

    def __init__(self, threshold=0.5):
        self.threshold = threshold

    def detect(self, frame):
        h, w = frame.shape[:2]
        bottom = frame[h*2//3:, :]
        gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        dark_ratio = np.sum(gray < 40) / gray.size

        confidence = min(1.0, edge_density * 3 + dark_ratio * 0.5)
        is_blocked = confidence > self.threshold

        third = w // 3
        left_e = np.sum(edges[:, :third] > 0)
        right_e = np.sum(edges[:, third*2:] > 0)
        hint = 'right' if left_e > right_e else 'left'

        return is_blocked, confidence, hint


class Explorer:
    """Autonomous exploration behavior."""

    SOUND_FORWARD = '/tmp/pal_forward.wav'
    SOUND_BLOCKED = '/tmp/pal_blocked.wav'
    SOUND_PHOTO = '/tmp/pal_photo.wav'
    SPEAKER_DEV = 'plughw:2,0'

    def __init__(self, bot, camera, detector, speed=0.25):
        self.bot = bot
        self.camera = camera
        self.detector = detector
        self.speed = speed
        self.photo_count = 0
        self.running = False
        self._generate_sounds()

    def _generate_sounds(self):
        """Generate 3 distinct sound patterns for exploration."""
        import wave, struct, math
        sr = 44100

        def _write_wav(filename, freqs):
            try:
                with wave.open(filename, 'w') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(sr)
                    frames = []
                    for freq, dur in freqs:
                        n = int(sr * dur)
                        for i in range(n):
                            v = int(8000 * math.sin(2 * math.pi * freq * i / sr))
                            frames.append(struct.pack('<h', v))
                        # tiny gap between notes
                        frames.extend([struct.pack('<h', 0)] * int(sr * 0.015))
                    w.writeframes(b''.join(frames))
            except Exception as e:
                print(f"[Explorer] Sound generation failed ({filename}): {e}")

        # Pattern 1: Forward/moving - ascending pico pico
        _write_wav(self.SOUND_FORWARD, [(800,0.1),(1200,0.1),(1600,0.1),(2000,0.15)])
        # Pattern 2: Blocked/obstacle - bouncy alert
        _write_wav(self.SOUND_BLOCKED, [(1000,0.08),(600,0.08),(1200,0.08),(800,0.08),(1500,0.12)])
        # Pattern 3: Photo taken - happy trill
        _write_wav(self.SOUND_PHOTO, [(1200,0.06),(1400,0.06),(1200,0.06),(1400,0.06),(1600,0.06),(1800,0.06),(2000,0.1)])
        print("[Explorer] Sounds generated: forward/blocked/photo")

    def _play_sound(self, sound_file):
        """Play a sound via aplay direct device (non-blocking). PulseAudio autospawn must be off."""
        import subprocess
        try:
            subprocess.Popen(
                ['aplay', '-D', self.SPEAKER_DEV, sound_file],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def explore(self, duration=60):
        """Explore autonomously for given duration (seconds).
        
        Strategy: Random walk with obstacle avoidance.
        - Move forward normally
        - Every 5-8s, do a random turn (explore different directions)
        - On obstacle: back up, turn away, continue
        - On repeated obstacles: bigger turns, eventually 180°
        """
        import random
        print(f"[Explorer] Starting exploration for {duration}s at speed {self.speed}")
        self._play_sound(self.SOUND_FORWARD)
        self.running = True
        start = time.time()
        last_photo = 0
        last_turn = time.time()
        next_turn_interval = random.uniform(5, 8)
        consecutive_blocked = 0
        total_blocked = 0
        total_free = 0
        prev_frame = None
        stuck_count = 0

        try:
            while self.running and (time.time() - start) < duration:
                frame = self.camera.capture()
                if frame is None:
                    time.sleep(0.1)
                    continue

                blocked, conf, hint = self.detector.detect(frame)

                # Stuck detection: if frame barely changes, we're pressed against something
                gray_curr = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_frame is not None:
                    diff = np.mean(np.abs(gray_curr.astype(float) - prev_frame.astype(float)))
                    if diff < 1.0:  # Nearly identical frames = pressed against wall
                        stuck_count += 1
                        if stuck_count > 20:  # ~1s of no change while "moving"
                            blocked = True
                            conf = 0.99
                            hint = random.choice(['left', 'right'])
                            print(f"[Explorer] STUCK detected! Frame diff={diff:.1f}, forcing blocked")
                            stuck_count = 0
                    else:
                        stuck_count = 0
                prev_frame = gray_curr

                if blocked:
                    self.bot.stop()
                    self._play_sound(self.SOUND_BLOCKED)
                    consecutive_blocked += 1
                    total_blocked += 1
                    print(f"[Explorer] Blocked! conf={conf:.2f}, hint={hint}, streak={consecutive_blocked}")

                    # Take photo of obstacle (max once per 10s)
                    if time.time() - last_photo > 10:
                        self._save_photo("obstacle")
                        last_photo = time.time()

                    # Back up
                    self.bot.backward(self.speed, 0.4)
                    time.sleep(0.1)

                    # Turn away — longer turn if stuck repeatedly
                    turn_time = 0.4 + min(consecutive_blocked * 0.3, 1.2)
                    if hint == 'left':
                        self.bot.left(self.speed, turn_time)
                    else:
                        self.bot.right(self.speed, turn_time)
                    time.sleep(0.1)

                    # If stuck too long, try 180° turn
                    if consecutive_blocked >= 5:
                        print("[Explorer] Stuck! Doing 180° turn")
                        self.bot.right(self.speed, 1.5)
                        consecutive_blocked = 0
                        time.sleep(0.2)

                    # Reset turn timer after obstacle avoidance
                    last_turn = time.time()
                    next_turn_interval = random.uniform(4, 7)
                    # Play forward sound when resuming after obstacle
                    self._play_sound(self.SOUND_FORWARD)
                else:
                    consecutive_blocked = 0
                    total_free += 1

                    # Random exploration turn every 5-8 seconds
                    if time.time() - last_turn > next_turn_interval:
                        # Random turn: 30-90 degrees in random direction
                        turn_time = random.uniform(0.3, 0.9)
                        direction = random.choice(['left', 'right'])
                        print(f"[Explorer] Random turn {direction} ({turn_time:.1f}s)")
                        self.bot.stop()
                        time.sleep(0.05)
                        if direction == 'left':
                            self.bot.left(self.speed, turn_time)
                        else:
                            self.bot.right(self.speed, turn_time)
                        time.sleep(0.1)
                        last_turn = time.time()
                        next_turn_interval = random.uniform(5, 8)
                    else:
                        # Slight random drift to avoid perfectly straight lines
                        drift = random.uniform(-0.03, 0.03)
                        self.bot.set_motors(self.speed + drift, self.speed - drift)

                # Periodic photo + sound every 10 seconds
                if time.time() - last_photo > 10:
                    self._play_sound(self.SOUND_PHOTO)
                    self._save_photo("explore")
                    last_photo = time.time()

                time.sleep(0.05)  # ~20Hz control loop

        except KeyboardInterrupt:
            print("[Explorer] Interrupted")
        finally:
            self.bot.stop()
            self.running = False
            print(f"[Explorer] Done. Photos={self.photo_count}, Free={total_free}, Blocked={total_blocked}")

    def patrol(self, waypoints=4, duration=120):
        """Simple patrol: go forward, turn, repeat. Takes photos at each waypoint."""
        print(f"[Explorer] Patrol mode: {waypoints} waypoints, {duration}s max")
        self.running = True
        start = time.time()

        try:
            for i in range(waypoints):
                if not self.running or (time.time() - start) > duration:
                    break

                print(f"[Explorer] Waypoint {i+1}/{waypoints}")

                # Move forward with collision check
                move_start = time.time()
                while time.time() - move_start < 2.0:
                    frame = self.camera.capture()
                    if frame is not None:
                        blocked, conf, hint = self.detector.detect(frame)
                        if blocked:
                            self.bot.stop()
                            print(f"[Explorer] Blocked at waypoint {i+1}, conf={conf:.2f}")
                            self.bot.backward(self.speed, 0.3)
                            break
                    self.bot.forward(self.speed)
                    time.sleep(0.05)

                self.bot.stop()
                time.sleep(0.3)

                # Take photo
                self._save_photo(f"waypoint_{i+1}")

                # Turn 90° 
                self.bot.right(0.3, 0.8)
                time.sleep(0.3)

        except KeyboardInterrupt:
            print("[Explorer] Interrupted")
        finally:
            self.bot.stop()
            self.running = False

    def _save_photo(self, label):
        self.photo_count += 1
        path = f"/tmp/jetbot_explore_{self.photo_count:03d}_{label}.jpg"
        frame = self.camera.capture_corrected()
        if frame is not None:
            cv2.imwrite(path, frame)
            print(f"[Explorer] Photo saved: {path}")
        return path

    def stop(self):
        self.running = False
        self.bot.stop()


def main():
    parser = argparse.ArgumentParser(description='JetBot Explorer')
    parser.add_argument('--explore', action='store_true', help='Autonomous exploration')
    parser.add_argument('--patrol', action='store_true', help='Patrol waypoints')
    parser.add_argument('--duration', type=int, default=60, help='Duration in seconds')
    parser.add_argument('--speed', type=float, default=0.25, help='Movement speed (0-1)')
    parser.add_argument('--waypoints', type=int, default=4, help='Patrol waypoints')
    parser.add_argument('--snap', action='store_true', help='Just take a photo')
    parser.add_argument('--threshold', type=float, default=0.5, help='Blocked threshold (0-1)')
    parser.add_argument('--model', type=str, default=None, help='Path to model .pth file')
    parser.add_argument('--simple', action='store_true', help='Use simple detector (no PyTorch)')
    args = parser.parse_args()

    if args.snap:
        cam = Camera()
        path = cam.save()
        cam.release()
        if path:
            print(f"Photo saved: {path}")
        return

    # Load detector FIRST (takes ~30s for CUDA init), then open camera
    if args.simple or not HAS_TORCH:
        print("[Explorer] Using simple obstacle detector")
        detector = SimpleObstacleDetector(threshold=args.threshold)
    else:
        print("[Explorer] Using CNN (ResNet18) obstacle detector")
        detector = CNNObstacleDetector(
            model_path=args.model,
            threshold=args.threshold
        )

    # Camera and motors AFTER model is loaded (avoids GStreamer timeout)
    bot = PalBot()
    print("[Explorer] Opening camera...")
    cam = Camera(width=224, height=224)
    print("[Explorer] Ready!")
    explorer = Explorer(bot, cam, detector, speed=args.speed)

    try:
        if args.patrol:
            explorer.patrol(waypoints=args.waypoints, duration=args.duration)
        elif args.explore:
            explorer.explore(duration=args.duration)
        else:
            # Quick test: just check one frame
            print("[Explorer] Quick test mode - checking one frame")
            frame = cam.capture()
            if frame is not None:
                blocked, conf, hint = detector.detect(frame)
                print(f"  Blocked: {blocked}, Confidence: {conf:.3f}, Hint: {hint}")
                explorer._save_photo("test")
            else:
                print("  Failed to capture frame")
    finally:
        cam.release()


if __name__ == '__main__':
    main()
