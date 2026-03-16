#!/usr/bin/env python3
"""人を検出したら時間帯に合わせて挨拶するスクリプト"""

import cv2
import subprocess
import time
import random
from datetime import datetime

# 設定
CAMERA_ID = 0
AUDIO_DEVICE = "plughw:2,0"
DICT = "/var/lib/mecab/dic/open-jtalk/naist-jdic"
COOLDOWN = 10
CONFIDENCE_THRESHOLD = 0.2
SILENCE_SEC = 2

# DNN顔検出モデル
PROTOTXT = "/home/haltyt/models/deploy.prototxt"
CAFFEMODEL = "/home/haltyt/models/res10_300x300_ssd_iter_140000.caffemodel"

# 声のパス
VOICES = {
    "happy": "/usr/share/hts-voice/mei/mei_happy.htsvoice",
    "normal": "/usr/share/hts-voice/mei/mei_normal.htsvoice",
    "bashful": "/usr/share/hts-voice/mei/mei_bashful.htsvoice",
}

# 時間帯別の挨拶
def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 10:
        # 朝
        voice = VOICES["happy"]
        greetings = [
            "おはようございます！",
            "おはよー！今日もいい天気だね！",
            "おはよう！今日も頑張ろう！",
            "おはよー！よく眠れた？",
        ]
    elif 10 <= hour < 17:
        # 昼
        voice = VOICES["happy"]
        greetings = [
            "こんにちは！",
            "やっほー！元気？",
            "いらっしゃい！",
            "はろー！調子どう？",
            "こんにちは！いい一日だね！",
        ]
    elif 17 <= hour < 21:
        # 夕方
        voice = VOICES["normal"]
        greetings = [
            "こんばんは！",
            "おかえり！お疲れ様！",
            "こんばんはー！今日はどうだった？",
            "おつかれさま！ゆっくりしてね！",
        ]
    else:
        # 夜（21時〜5時）
        voice = VOICES["bashful"]
        greetings = [
            "こんばんは、まだ起きてるの？",
            "夜更かしさんだね。",
            "おやすみ前かな？",
            "遅くまでお疲れ様。",
        ]
    return random.choice(greetings), voice


def speak(text, voice):
    """Open JTalkで喋る"""
    try:
        subprocess.run(
            ["open_jtalk", "-m", voice, "-x", DICT,
             "-ow", "/tmp/greeter_hello.wav", "-r", "0.9", "-fm", "1"],
            input=text.encode("utf-8"),
            timeout=10,
        )
        subprocess.run(
            ["aplay", "-D", AUDIO_DEVICE, "/dev/zero",
             "-d", str(SILENCE_SEC), "-f", "S16_LE", "-r", "48000"],
            timeout=5, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["aplay", "-D", AUDIO_DEVICE, "/tmp/greeter_hello.wav"],
            timeout=15, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )
        print("[SPEAK] {}".format(text))
    except Exception as e:
        print("[ERROR] speak: {}".format(e))


def main():
    print("=== パルの挨拶カメラ起動！ ===")
    print("  朝(5-10時):   おはよう    (happy)")
    print("  昼(10-17時):  こんにちは  (happy)")
    print("  夕(17-21時):  こんばんは  (normal)")
    print("  夜(21-5時):   夜更かし    (bashful)")
    print("Ctrl+C で終了")
    print()

    net = cv2.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("[ERROR] カメラが開けません")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    last_greet_time = 0
    frame_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                continue

            frame_count += 1
            if frame_count % 10 != 0:
                time.sleep(0.05)
                continue

            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)), 1.0,
                (300, 300), (104.0, 177.0, 123.0)
            )
            net.setInput(blob)
            detections = net.forward()

            face_found = False
            for i in range(detections.shape[2]):
                if detections[0, 0, i, 2] > CONFIDENCE_THRESHOLD:
                    face_found = True
                    break

            if face_found:
                now = time.time()
                if now - last_greet_time > COOLDOWN:
                    greeting, voice = get_greeting()
                    print("[DETECT] 顔検出！({}) → {}".format(
                        datetime.now().strftime("%H:%M"), greeting))
                    speak(greeting, voice)
                    last_greet_time = now

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n=== 終了！ ===")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
