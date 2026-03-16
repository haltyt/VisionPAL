#!/usr/bin/env python3
"""JetBot Data Collection - Collect free/blocked images for collision avoidance training.

Usage:
  python3 jetbot_collect.py --auto --duration 60      # Auto-collect while driving
  python3 jetbot_collect.py --snap free               # Single snapshot labeled 'free'
  python3 jetbot_collect.py --snap blocked             # Single snapshot labeled 'blocked'
  python3 jetbot_collect.py --count                    # Show dataset stats
"""
import os
import sys
import time
import uuid
import argparse
import atexit
import cv2
import numpy as np
from Adafruit_MotorHAT import Adafruit_MotorHAT

DATASET_DIR = '/home/jetbot/dataset_v2'


class PalBot:
    def __init__(self, i2c_bus=1, left_channel=1, right_channel=2):
        self._driver = Adafruit_MotorHAT(i2c_bus=i2c_bus)
        self._left = self._driver.getMotor(left_channel)
        self._right = self._driver.getMotor(right_channel)
        self._pins = {left_channel: (1, 0), right_channel: (2, 3)}
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

    def forward(self, speed=0.2, duration=None):
        self.set_motors(speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def backward(self, speed=0.2, duration=None):
        self.set_motors(-speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def left(self, speed=0.2, duration=None):
        self.set_motors(-speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def right(self, speed=0.2, duration=None):
        self.set_motors(speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def stop(self):
        self.set_motors(0, 0)


class Camera:
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
        ret, frame = self.cap.read()
        if not ret:
            return None
        return cv2.resize(frame, (self.width, self.height))

    def release(self):
        self.cap.release()


def ensure_dirs():
    for label in ['free', 'blocked']:
        d = os.path.join(DATASET_DIR, label)
        if not os.path.exists(d):
            os.makedirs(d)


def save_image(frame, label):
    ensure_dirs()
    filename = '{}.jpg'.format(uuid.uuid4())
    path = os.path.join(DATASET_DIR, label, filename)
    cv2.imwrite(path, frame)
    return path


def count_images():
    ensure_dirs()
    counts = {}
    for label in ['free', 'blocked']:
        d = os.path.join(DATASET_DIR, label)
        counts[label] = len([f for f in os.listdir(d) if f.endswith('.jpg')])
    return counts


def auto_collect(duration, interval=0.5):
    """Drive forward slowly, auto-collect 'free' images.
    When close to obstacle (user should place JetBot near obstacles),
    collect 'blocked' images.
    
    Protocol:
    - Drives forward slowly
    - Every {interval}s takes a 'free' photo
    - Prints count periodically
    """
    cam = Camera()
    bot = PalBot()
    
    print("[Collect] Auto-collecting for {}s (interval={}s)".format(duration, interval))
    print("[Collect] Phase 1: 'free' images - driving on clear path")
    
    start = time.time()
    count = 0
    
    try:
        # Collect free images while moving
        bot.forward(0.15)
        while time.time() - start < duration:
            frame = cam.capture()
            if frame is not None:
                save_image(frame, 'free')
                count += 1
                if count % 10 == 0:
                    print("[Collect] free: {} images".format(count))
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop()
        cam.release()
    
    print("[Collect] Done. Collected {} free images.".format(count))
    c = count_images()
    print("[Collect] Total: free={}, blocked={}".format(c['free'], c['blocked']))


def auto_collect_blocked(duration, interval=0.5):
    """Stay still, collect 'blocked' images.
    User should position JetBot facing obstacles before running.
    """
    cam = Camera()
    
    print("[Collect] Collecting BLOCKED images for {}s".format(duration))
    print("[Collect] Make sure JetBot is facing an obstacle!")
    
    start = time.time()
    count = 0
    
    try:
        while time.time() - start < duration:
            frame = cam.capture()
            if frame is not None:
                save_image(frame, 'blocked')
                count += 1
                if count % 10 == 0:
                    print("[Collect] blocked: {} images".format(count))
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        cam.release()
    
    print("[Collect] Done. Collected {} blocked images.".format(count))
    c = count_images()
    print("[Collect] Total: free={}, blocked={}".format(c['free'], c['blocked']))


def snap(label):
    """Take a single labeled snapshot."""
    cam = Camera()
    frame = cam.capture()
    cam.release()
    if frame is not None:
        path = save_image(frame, label)
        c = count_images()
        print("Saved: {} (free={}, blocked={})".format(path, c['free'], c['blocked']))
    else:
        print("Failed to capture")


def main():
    parser = argparse.ArgumentParser(description='JetBot Data Collection')
    parser.add_argument('--auto-free', type=int, metavar='SEC',
                        help='Auto-collect free images while driving (seconds)')
    parser.add_argument('--auto-blocked', type=int, metavar='SEC',
                        help='Auto-collect blocked images while stationary (seconds)')
    parser.add_argument('--snap', choices=['free', 'blocked'],
                        help='Take single labeled snapshot')
    parser.add_argument('--count', action='store_true',
                        help='Show dataset counts')
    parser.add_argument('--interval', type=float, default=0.5,
                        help='Capture interval in seconds')
    args = parser.parse_args()

    if args.count:
        c = count_images()
        print("free={}, blocked={}".format(c['free'], c['blocked']))
    elif args.snap:
        snap(args.snap)
    elif args.auto_free:
        auto_collect(args.auto_free, args.interval)
    elif args.auto_blocked:
        auto_collect_blocked(args.auto_blocked, args.interval)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
