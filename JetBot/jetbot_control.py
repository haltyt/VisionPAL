#!/usr/bin/env python3
"""JetBot motor control - Waveshare Motor Driver HAT (PCA9685 @ I2C 0x40)
Motor A (ch0,1,2) = RIGHT, Motor B (ch5,3,4) = LEFT
"""
import sys
import time
import atexit

try:
    import smbus
except ImportError:
    import smbus2 as smbus


class PalBot:
    """JetBot controller for Waveshare Motor Driver HAT."""

    PCA9685_ADDR = 0x40
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    # Channel mapping (confirmed 2026-03-13)
    # Motor A = RIGHT, Motor B = LEFT
    CH_R = {'pwm': 0, 'in1': 1, 'in2': 2}
    CH_L = {'pwm': 5, 'in1': 3, 'in2': 4}

    def __init__(self):
        self._bus = smbus.SMBus(1)
        self._init_pca9685()
        atexit.register(self.stop)

    def _init_pca9685(self):
        self._bus.write_byte_data(self.PCA9685_ADDR, self.MODE1, 0x00)
        time.sleep(0.005)
        old_mode = self._bus.read_byte_data(self.PCA9685_ADDR, self.MODE1)
        self._bus.write_byte_data(self.PCA9685_ADDR, self.MODE1, (old_mode & 0x7F) | 0x10)
        self._bus.write_byte_data(self.PCA9685_ADDR, self.PRESCALE, 121)  # ~50Hz
        self._bus.write_byte_data(self.PCA9685_ADDR, self.MODE1, old_mode)
        time.sleep(0.005)
        self._bus.write_byte_data(self.PCA9685_ADDR, self.MODE1, old_mode | 0xA0)

    def _set_pwm(self, channel, on, off):
        reg = self.LED0_ON_L + 4 * channel
        self._bus.write_byte_data(self.PCA9685_ADDR, reg, on & 0xFF)
        self._bus.write_byte_data(self.PCA9685_ADDR, reg + 1, on >> 8)
        self._bus.write_byte_data(self.PCA9685_ADDR, reg + 2, off & 0xFF)
        self._bus.write_byte_data(self.PCA9685_ADDR, reg + 3, off >> 8)

    def _motor(self, ch, speed):
        """Drive one motor. speed: -1.0 to 1.0."""
        pwm_val = int(abs(speed) * 4095)
        pwm_val = min(pwm_val, 4095)
        if speed > 0:
            self._set_pwm(ch['in1'], 0, 4095)
            self._set_pwm(ch['in2'], 0, 0)
            self._set_pwm(ch['pwm'], 0, pwm_val)
        elif speed < 0:
            self._set_pwm(ch['in1'], 0, 0)
            self._set_pwm(ch['in2'], 0, 4095)
            self._set_pwm(ch['pwm'], 0, pwm_val)
        else:
            self._set_pwm(ch['in1'], 0, 0)
            self._set_pwm(ch['in2'], 0, 0)
            self._set_pwm(ch['pwm'], 0, 0)

    def set_motors(self, left, right):
        """Set both motors. Values: -1.0 to 1.0."""
        left = max(-1.0, min(1.0, left))
        right = max(-1.0, min(1.0, right))
        self._motor(self.CH_L, left)
        self._motor(self.CH_R, right)

    def forward(self, speed=0.5, duration=None):
        self.set_motors(speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def backward(self, speed=0.5, duration=None):
        self.set_motors(-speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def left(self, speed=0.5, duration=None):
        self.set_motors(-speed, speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def right(self, speed=0.5, duration=None):
        self.set_motors(speed, -speed)
        if duration:
            time.sleep(duration)
            self.stop()

    def stop(self):
        self.set_motors(0, 0)


def main():
    if len(sys.argv) < 2:
        print("Usage: jetbot_control.py <forward|backward|left|right|stop|test> [speed] [duration]")
        sys.exit(1)

    cmd = sys.argv[1]
    speed = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

    bot = PalBot()

    if cmd == "test":
        print("Forward...")
        bot.forward(0.4, 0.5)
        time.sleep(0.3)
        print("Backward...")
        bot.backward(0.4, 0.5)
        time.sleep(0.3)
        print("Left...")
        bot.left(0.4, 0.5)
        time.sleep(0.3)
        print("Right...")
        bot.right(0.4, 0.5)
        time.sleep(0.3)
        print("All done!")
    elif cmd == "forward":
        bot.forward(speed, duration)
    elif cmd == "backward":
        bot.backward(speed, duration)
    elif cmd == "left":
        bot.left(speed, duration)
    elif cmd == "right":
        bot.right(speed, duration)
    elif cmd == "stop":
        bot.stop()
    else:
        print("Unknown command: {}".format(cmd))
        sys.exit(1)

    print("OK: {}".format(cmd))


if __name__ == "__main__":
    main()
