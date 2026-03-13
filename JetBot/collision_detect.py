#!/usr/bin/env python3
"""
JetBot 衝突検知 - カメラフレーム差分方式
モーター動作中に映像変化が止まったら衝突と判定
Python 3.6対応
"""

import cv2
import numpy as np
import time
import subprocess
import sys

# --- 設定 ---
COLLISION_THRESHOLD = 1.0    # フレーム差分の平均がこれ以下なら「動いてない」
COLLISION_FRAMES = 3         # 連続N フレーム動きなしで衝突判定
CHECK_INTERVAL = 0.1         # フレーム取得間隔(秒)
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240

# GStreamer パイプライン (JetBot IMX219 CSI)
GST_PIPELINE = (
    "nvarguscamerasrc ! "
    "video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1 ! "
    "nvvidconv ! video/x-raw,width=320,height=240,format=BGRx ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink drop=1"
)


def log(msg):
    print(msg, flush=True)

def open_camera():
    log("[INFO] カメラ起動中...")
    cap = cv2.VideoCapture(GST_PIPELINE, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        log("[ERROR] カメラ開けない！")
        sys.exit(1)
    log("[INFO] パイプライン開いた、ウォームアップ中...")
    # 最初の数フレーム捨てる（露出安定待ち）
    for i in range(10):
        ret, _ = cap.read()
        if i == 0:
            log("[INFO] 最初のread: ret={}".format(ret))
        time.sleep(0.05)
    log("[OK] カメラ起動")
    return cap


def frame_diff(prev_gray, curr_gray):
    """2フレーム間の差分の平均値を返す"""
    diff = cv2.absdiff(prev_gray, curr_gray)
    return np.mean(diff)


def on_collision():
    """衝突時のアクション"""
    log("💥 衝突検知！！！")
    # モーター停止
    try:
        from Adafruit_MotorHAT import Adafruit_MotorHAT
        mh = Adafruit_MotorHAT(addr=0x60, i2c_bus=1)
        mh.getMotor(1).run(Adafruit_MotorHAT.RELEASE)
        mh.getMotor(2).run(Adafruit_MotorHAT.RELEASE)
        log("[STOP] モーター停止")
    except Exception as e:
        log("[WARN] モーター停止失敗: {}".format(e))

    # スピーカーでブザー音（あれば）
    try:
        subprocess.Popen(
            ["aplay", "-D", "plughw:2,0", "/tmp/beep.wav"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception:
        pass


MOTOR_STATE_FILE = "/tmp/jetbot_motor_state"

def is_motor_running():
    """モーターが動作中かチェック（状態ファイル or プロセス存在で判定）"""
    # 状態ファイル方式（jetbot_control.pyが書き込む）
    try:
        with open(MOTOR_STATE_FILE, "r") as f:
            state = f.read().strip()
            return state == "running"
    except Exception:
        pass
    # フォールバック: プロセス存在チェック
    try:
        result = subprocess.Popen(
            ["pgrep", "-f", "jetbot_control"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out, _ = result.communicate()
        return len(out.strip()) > 0
    except Exception:
        return False


def main():
    log("=== JetBot 衝突検知スタート ===")
    log("閾値: {}, 連続フレーム: {}".format(COLLISION_THRESHOLD, COLLISION_FRAMES))

    cap = open_camera()
    ret, frame = cap.read()
    if not ret:
        log("[ERROR] 最初のフレーム取得失敗")
        return

    prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    still_count = 0
    collision_cooldown = 0

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            ret, frame = cap.read()
            if not ret:
                continue

            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff_val = frame_diff(prev_gray, curr_gray)
            prev_gray = curr_gray

            # クールダウン中
            if collision_cooldown > 0:
                collision_cooldown -= 1
                continue

            # モーター動いてる時だけチェック
            # (常時チェックモードにしたい場合はこの条件外す)
            if not is_motor_running():
                still_count = 0
                continue

            if diff_val < COLLISION_THRESHOLD:
                still_count += 1
                log("  静止検知 ({}/{}) diff={:.2f}".format(
                    still_count, COLLISION_FRAMES, diff_val))
            else:
                if still_count > 0:
                    log("  動き復帰 diff={:.2f}".format(diff_val))
                still_count = 0

            if still_count >= COLLISION_FRAMES:
                on_collision()
                still_count = 0
                collision_cooldown = 30  # 3秒クールダウン

    except KeyboardInterrupt:
        log("\n終了")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
