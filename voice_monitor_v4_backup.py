#!/usr/bin/env python3
"""パルの音声チャット v4 - 顔検出トリガー + OpenClaw連携
ホスト側: GStreamerでカメラ常時ON + 顔検出 + 録音
コンテナ側: Whisper STT + OpenClaw API応答 + Discord通知
"""

import json
import subprocess
import time
import os
import struct
import wave
import math
import re

HOST = "haltyt@172.19.0.1"
MIC_DEVICE = "plughw:2,0"
AUDIO_DEVICE = "bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink"  # BT speaker
TALK_RECORD_SEC = 5
SOUND_THRESHOLD = 200
LOCAL_WAV = "/tmp/pal_stt_input.wav"

# OpenClaw Gateway API
OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_TOKEN = ""

# 会話履歴
CONVERSATION = []
MAX_HISTORY = 10

# Whisperの幻聴フィルタ
HALLUCINATIONS = [
    "字幕", "エンディング", "フォロー", "ご視聴", "サブタイトル",
    "チャンネル登録", "ありがとうございました", "MBSニュース",
    "最後まで", "おやすみなさい", "チャンネル", "作詞", "作曲",
    "編曲", "初音ミク", "この動画", "視聴者", "登録",
    "提供", "スポンサー", "コメント欄", "BGM", "SE",
]

# 顔検出の冷却時間（秒）— 連続検出を防ぐ
FACE_COOLDOWN = 10


def load_config():
    global OPENCLAW_TOKEN
    try:
        with open("/home/node/.openclaw/openclaw.json") as f:
            config = json.load(f)
        OPENCLAW_TOKEN = config["gateway"]["auth"]["token"]
        print("[CONFIG] Gatewayトークン読み込み完了")
    except Exception as e:
        print("[ERROR] config読み込み失敗: {}".format(e))


def ssh_run(cmd, timeout=15):
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no", HOST, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception as e:
        print("[ERROR] ssh: {}".format(e))
        return ""


def setup_face_detection_on_host():
    """ホスト側のface_watcher.pyが最新か確認"""
    # face_watcher.pyはscpで事前に配置済み
    result = ssh_run("test -f ~/face_watcher.py && echo OK", timeout=5)
    if "OK" in result:
        print("[SETUP] face_watcher.py 確認OK")
    else:
        print("[ERROR] face_watcher.py がホストにありません")


def start_face_watcher():
    """ホスト側で顔検出スクリプトをバックグラウンド起動"""
    ssh_run("pkill -f face_watcher 2>/dev/null", timeout=5)
    time.sleep(1)
    ssh_run("cd ~ && nohup python3 -u face_watcher.py > /tmp/face_watcher.log 2>&1 &", timeout=5)
    print("[SETUP] face_watcher.py 起動完了")


def record_on_host(duration):
    """ホスト側で録音 → 16kHz monoに変換"""
    ssh_run(
        "arecord -D {} -d {} -f S16_LE -r 48000 -c 2 /tmp/pal_rec_raw.wav 2>/dev/null && "
        "ffmpeg -y -i /tmp/pal_rec_raw.wav -ar 16000 -ac 1 -filter:a 'volume=3.0' /tmp/pal_rec.wav 2>/dev/null".format(
            MIC_DEVICE, duration
        ),
        timeout=duration + 10,
    )


def check_face_detected():
    """ホスト側のフラグファイルを確認"""
    result = ssh_run("cat /tmp/pal_voice/face_detected 2>/dev/null && rm /tmp/pal_voice/face_detected 2>/dev/null")
    return bool(result)


def copy_from_host(remote_path, local_path):
    try:
        subprocess.run(
            ["scp", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
             "{}:{}".format(HOST, remote_path), local_path],
            capture_output=True, timeout=15,
        )
        return os.path.exists(local_path)
    except Exception:
        return False


def get_sound_level(wav_path):
    try:
        w = wave.open(wav_path, "rb")
        frames = w.readframes(w.getnframes())
        w.close()
        samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
        rms = math.sqrt(sum(s ** 2 for s in samples) / len(samples))
        return rms
    except Exception:
        return 0


def whisper_stt(wav_path):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        try:
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.openai")
            with open(env_path) as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
        except Exception:
            pass
    if not api_key:
        print("[ERROR] OpenAI API key not found")
        return None
    try:
        result = subprocess.run(
            ["curl", "-s",
             "https://api.openai.com/v1/audio/transcriptions",
             "-H", "Authorization: Bearer {}".format(api_key),
             "-F", "file=@{}".format(wav_path),
             "-F", "model=whisper-1",
             "-F", "language=ja",
             "-F", "prompt=これはパルとハルトの日常会話です。短い日本語の話し言葉です。"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return data.get("text", "")
    except Exception as e:
        print("[ERROR] Whisper API: {}".format(e))
        return None


def is_hallucination(text):
    if not text or len(text.strip()) < 2:
        return True
    if any(h in text for h in HALLUCINATIONS):
        return True
    return False


def ask_pal(question):
    global CONVERSATION
    CONVERSATION.append({"role": "user", "content": question})

    system_msg = {
        "role": "system",
        "content": (
            "あなたはパル。Jetson Nanoに住むかわいいAIアシスタント。"
            "ハルトの相棒で、好奇心いっぱい、カジュアルで甘えん坊。"
            "今は音声で会話中。必ず1-2文以内で短く返事して。"
            "絵文字・マークダウン禁止。話し言葉で自然に。"
        ),
    }
    messages = [system_msg] + CONVERSATION[-MAX_HISTORY:]
    payload = json.dumps({
        "model": "openclaw",
        "messages": messages,
        "user": "voice-chat",
    }, ensure_ascii=False)

    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "30", OPENCLAW_URL,
             "-H", "Authorization: Bearer {}".format(OPENCLAW_TOKEN),
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=35,
        )
        data = json.loads(result.stdout)
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if reply:
            CONVERSATION.append({"role": "assistant", "content": reply})
            if len(CONVERSATION) > MAX_HISTORY:
                CONVERSATION = CONVERSATION[-MAX_HISTORY:]
            return reply
        else:
            print("[ERROR] API response: {}".format(result.stdout[:200]))
            return None
    except Exception as e:
        print("[ERROR] OpenClaw API: {}".format(e))
        return None


def clean_for_tts(text):
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'[\U0001F000-\U0001FFFF]', '', text)
    text = text.replace("'", "").replace('"', '').replace('\n', ' ').strip()
    if len(text) > 80:
        for sep in ['。', '！', '!', '？', '?', '〜']:
            idx = text.find(sep)
            if 5 < idx < 80:
                text = text[:idx + 1]
                break
        else:
            text = text[:80]
    return text


def speak_on_host(text):
    text = clean_for_tts(text)
    if not text:
        return
    ssh_run(
        "~/pal_speak.sh '{}' happy".format(text),
        timeout=30,
    )


def send_to_discord(user_text, pal_text):
    try:
        config = json.load(open("/home/node/.openclaw/openclaw.json"))
        bot_token = config["channels"]["discord"]["token"]
        dm_channel = "1469326108322168943"

        msg = "🎤 **ハルト**: {}\n🐾 **パル**: {}".format(user_text, pal_text)
        payload = json.dumps({"content": msg}, ensure_ascii=False)
        subprocess.run(
            ["curl", "-s", "-m", "10",
             "https://discord.com/api/v10/channels/{}/messages".format(dm_channel),
             "-H", "Authorization: Bot {}".format(bot_token),
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, timeout=15,
        )
        print("[DISCORD] 送信完了")
    except Exception as e:
        print("[ERROR] Discord送信: {}".format(e))


def main():
    print("=" * 40)
    print("  パル音声チャット v4")
    print("  顔検出トリガー + OpenClaw連携")
    print("=" * 40)

    load_config()

    # ホスト側に顔検出スクリプトを配置＆起動
    print("[SETUP] ホスト側セットアップ中...")
    setup_face_detection_on_host()
    start_face_watcher()
    time.sleep(3)

    # 起動確認
    log = ssh_run("tail -5 /tmp/face_watcher.log")
    print("[HOST] face_watcher: {}".format(log))

    speak_on_host("はーい、パルだよ。顔を見せてくれたらお話しようね！")
    print("[READY] カメラに顔を見せてね！")

    while True:
        try:
            # 顔検出フラグをチェック
            if check_face_detected():
                print("[FACE] 顔検出！")
                speak_on_host("なになに？")
                # TTS再生と録音を同時進行（待機なし）

                # 「なになに？」の後に録音開始
                print("[REC] 録音中... ({}秒)".format(TALK_RECORD_SEC))
                record_on_host(TALK_RECORD_SEC)

                if copy_from_host("/tmp/pal_rec.wav", LOCAL_WAV):
                    sound_level = get_sound_level(LOCAL_WAV)
                    print("[AUDIO] rms: {}".format(int(sound_level)))

                    if sound_level > SOUND_THRESHOLD:
                        text = whisper_stt(LOCAL_WAV)

                        if not is_hallucination(text):
                            print("[YOU] {}".format(text))

                            print("[THINK] パルが考え中...")
                            response = ask_pal(text)

                            if response:
                                print("[PAL] {}".format(response))
                                speak_on_host(response)
                                send_to_discord(text, response)
                            else:
                                speak_on_host("ごめん、うまく答えられなかった。")
                        else:
                            print("[SKIP] 幻聴フィルタ: {}".format(text))
                            speak_on_host("ごめん、よく聞こえなかった。もう一回言って？")
                    else:
                        print("[SKIP] 音量不足 rms:{}".format(int(sound_level)))
                        speak_on_host("あれ、何も聞こえなかったよ。もう一回言って？")

                print("[READY] カメラに顔を見せてね！")

            time.sleep(1)  # ポーリング間隔

        except KeyboardInterrupt:
            print("\n=== 終了！ ===")
            # ホスト側も停止
            ssh_run("pkill -f face_watcher 2>/dev/null")
            break
        except Exception as e:
            print("[ERROR] {}".format(e))
            time.sleep(3)


if __name__ == "__main__":
    main()
