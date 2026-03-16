#!/usr/bin/env python3
"""パルと声で会話 - 全自動モード
顔検出 → 自動録音 → 音声認識 → パルが応答 → 音声再生
"""

import cv2
import subprocess
import time
import os
import json
import speech_recognition as sr
from datetime import datetime

# 設定
CAMERA_ID = 0
MIC_DEVICE = "plughw:3,0"
AUDIO_DEVICE = "plughw:2,0"
DICT = "/var/lib/mecab/dic/open-jtalk/naist-jdic"
SILENCE_SEC = 2
RECORD_SEC = 5
COOLDOWN = 15  # 連続会話防止（秒）
CONFIDENCE_THRESHOLD = 0.2

# DNN顔検出モデル
PROTOTXT = "/home/haltyt/models/deploy.prototxt"
CAFFEMODEL = "/home/haltyt/models/res10_300x300_ssd_iter_140000.caffemodel"

QUESTION_FILE = "/tmp/pal_voice/question.json"
RESPONSE_FILE = "/tmp/pal_voice/response.json"

VOICES = {
    "happy": "/usr/share/hts-voice/mei/mei_happy.htsvoice",
    "normal": "/usr/share/hts-voice/mei/mei_normal.htsvoice",
    "bashful": "/usr/share/hts-voice/mei/mei_bashful.htsvoice",
}


def get_voice():
    hour = datetime.now().hour
    if 5 <= hour < 17:
        return VOICES["happy"]
    elif 17 <= hour < 21:
        return VOICES["normal"]
    else:
        return VOICES["bashful"]


def speak(text):
    voice = get_voice()
    try:
        subprocess.run(
            ["open_jtalk", "-m", voice, "-x", DICT,
             "-ow", "/tmp/pal_response.wav", "-r", "0.9", "-fm", "1"],
            input=text.encode("utf-8"), timeout=10,
        )
        subprocess.run(
            ["aplay", "-D", AUDIO_DEVICE, "/dev/zero",
             "-d", str(SILENCE_SEC), "-f", "S16_LE", "-r", "48000"],
            timeout=5, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["aplay", "-D", AUDIO_DEVICE, "/tmp/pal_response.wav"],
            timeout=30, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )
    except Exception as e:
        print("[ERROR] speak: {}".format(e))


def detect_face(net, frame):
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)), 1.0,
        (300, 300), (104.0, 177.0, 123.0)
    )
    net.setInput(blob)
    detections = net.forward()
    for i in range(detections.shape[2]):
        if detections[0, 0, i, 2] > CONFIDENCE_THRESHOLD:
            return True
    return False


def record_audio():
    wav_path = "/tmp/pal_input.wav"
    print("[MIC] 録音中... ({}秒)".format(RECORD_SEC))
    try:
        subprocess.run(
            ["arecord", "-D", MIC_DEVICE, "-d", str(RECORD_SEC),
             "-f", "S16_LE", "-r", "16000", "-c", "1", wav_path],
            timeout=RECORD_SEC + 5, stderr=subprocess.DEVNULL,
        )
        return wav_path
    except Exception as e:
        print("[ERROR] record: {}".format(e))
        return None


def recognize(wav_path):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(wav_path) as source:
            audio = r.record(source)
        text = r.recognize_google(audio, language="ja-JP")
        return text
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print("[ERROR] STT: {}".format(e))
        return None


def send_question(text):
    os.makedirs(os.path.dirname(QUESTION_FILE), exist_ok=True)
    with open(QUESTION_FILE, "w") as f:
        json.dump({"text": text, "time": time.time()}, f, ensure_ascii=False)


def wait_for_response(timeout=60):
    for i in range(timeout * 2):
        if os.path.exists(RESPONSE_FILE):
            try:
                with open(RESPONSE_FILE, "r") as f:
                    data = json.load(f)
                os.remove(RESPONSE_FILE)
                return data.get("text", "")
            except Exception:
                pass
        time.sleep(0.5)
    return None


def main():
    print("=" * 40)
    print("  パルの音声チャット（全自動モード）")
    print("  顔を見せる → 自動で録音 → パルが応答")
    print("=" * 40)
    print()

    net = cv2.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("[ERROR] カメラが開けません")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    speak("はーい、パルだよ。顔を見せてくれたら、お話しようね！")
    print("[READY] 顔を見せてね！")

    last_interaction = 0
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

            if detect_face(net, frame):
                now = time.time()
                if now - last_interaction > COOLDOWN:
                    print("[DETECT] 顔検出！録音するよ！")
                    speak("なになに？")

                    # カメラ一旦解放して録音
                    cap.release()
                    wav_path = record_audio()
                    
                    if wav_path:
                        print("[STT] 認識中...")
                        text = recognize(wav_path)
                        
                        if text:
                            print("[YOU] {}".format(text))
                            send_question(text)
                            print("[WAIT] パルが考え中...")
                            response = wait_for_response(60)
                            
                            if response:
                                print("[PAL] {}".format(response))
                                speak(response)
                            else:
                                speak("ごめん、うまく答えられなかった。")
                        else:
                            print("[STT] 聞き取れず")
                            speak("ごめん、よく聞こえなかった。")
                    
                    last_interaction = time.time()
                    # カメラ再オープン
                    cap = cv2.VideoCapture(CAMERA_ID)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    print("[READY] また顔を見せてね！")

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n=== 終了！ ===")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
