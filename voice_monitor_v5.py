#!/usr/bin/env python3
"""パルの音声チャット v5 - VAD強化版
変更点:
- エネルギーベースVAD（適応的閾値）
- ゼロ交差率による音声/ノイズ判別
- 発話区間検出（音声フレーム数チェック）
- Whisper幻聴の追加フィルタ（短すぎ・繰り返し検出）
"""

import json
import subprocess
import time
import os
import struct
import wave
import math
import re
import collections

HOST = "haltyt@172.19.0.1"
MIC_DEVICE = "plughw:2,0"
AUDIO_DEVICE = "bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink"
TALK_RECORD_SEC = 5
LOCAL_WAV = "/tmp/pal_stt_input.wav"

# OpenClaw Gateway API
OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_TOKEN = ""

# 会話履歴
CONVERSATION = []
MAX_HISTORY = 10

# === VAD設定 ===
VAD_FRAME_MS = 30          # フレーム長(ms)
VAD_SAMPLE_RATE = 16000    # 16kHz mono
VAD_FRAME_SAMPLES = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 480 samples

# 適応的閾値: 環境ノイズの倍率
VAD_ENERGY_MULTIPLIER = 3.0
VAD_MIN_ENERGY = 100       # 最低エネルギー閾値
VAD_ZCR_MAX = 0.4          # ゼロ交差率上限（高すぎ=ノイズ）
VAD_MIN_SPEECH_FRAMES = 5  # 最低発話フレーム数（150ms以上の発話が必要）
VAD_NOISE_FRAMES = 10      # 冒頭Nフレームをノイズレベル推定に使用

# Whisperの幻聴フィルタ
HALLUCINATIONS = [
    "字幕", "エンディング", "フォロー", "ご視聴", "サブタイトル",
    "チャンネル登録", "ありがとうございました", "MBSニュース",
    "最後まで", "おやすみなさい", "チャンネル", "作詞", "作曲",
    "編曲", "初音ミク", "この動画", "視聴者", "登録",
    "提供", "スポンサー", "コメント欄", "BGM", "SE",
    "ご覧いただき", "お疲れ様", "次の動画", "いいね",
    "お便り", "リスナー", "ラジオ", "番組",
]

FACE_COOLDOWN = 10


# === VAD関数 ===

def read_wav_samples(wav_path):
    """WAVファイルからサンプル列を読み込む（16bit signed）"""
    try:
        w = wave.open(wav_path, "rb")
        nframes = w.getnframes()
        frames = w.readframes(nframes)
        w.close()
        samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
        return list(samples)
    except Exception as e:
        print("[VAD] WAV読み込みエラー: {}".format(e))
        return []


def frame_energy(samples):
    """フレームのRMSエネルギー"""
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def frame_zcr(samples):
    """フレームのゼロ交差率 (0.0-1.0)"""
    if len(samples) < 2:
        return 0.0
    crossings = sum(
        1 for i in range(1, len(samples))
        if (samples[i] >= 0) != (samples[i - 1] >= 0)
    )
    return crossings / (len(samples) - 1)


def vad_analyze(wav_path):
    """VAD解析: 音声が含まれているか判定
    
    Returns:
        dict: {
            'has_speech': bool,
            'speech_frames': int,
            'total_frames': int,
            'noise_energy': float,
            'max_energy': float,
            'speech_ratio': float,
            'reason': str,
        }
    """
    samples = read_wav_samples(wav_path)
    if not samples:
        return {'has_speech': False, 'reason': 'WAV読み込み失敗'}

    # フレームに分割
    frames = []
    for i in range(0, len(samples) - VAD_FRAME_SAMPLES + 1, VAD_FRAME_SAMPLES):
        chunk = samples[i:i + VAD_FRAME_SAMPLES]
        frames.append(chunk)

    if len(frames) < VAD_NOISE_FRAMES + VAD_MIN_SPEECH_FRAMES:
        return {'has_speech': False, 'reason': '音声が短すぎ'}

    # 冒頭フレームからノイズレベルを推定
    noise_energies = [frame_energy(f) for f in frames[:VAD_NOISE_FRAMES]]
    noise_energy = sum(noise_energies) / len(noise_energies)

    # 適応的閾値
    energy_threshold = max(noise_energy * VAD_ENERGY_MULTIPLIER, VAD_MIN_ENERGY)

    # 各フレームを判定
    speech_frames = 0
    max_energy = 0.0
    for chunk in frames:
        e = frame_energy(chunk)
        z = frame_zcr(chunk)
        if e > max_energy:
            max_energy = e

        # 音声判定: エネルギーが閾値以上 AND ゼロ交差率が適切範囲
        if e > energy_threshold and z < VAD_ZCR_MAX:
            speech_frames += 1

    total_frames = len(frames)
    speech_ratio = speech_frames / total_frames if total_frames > 0 else 0.0

    has_speech = speech_frames >= VAD_MIN_SPEECH_FRAMES

    reason = ""
    if not has_speech:
        if max_energy < energy_threshold:
            reason = "エネルギー不足 (max:{:.0f} < thresh:{:.0f})".format(max_energy, energy_threshold)
        else:
            reason = "発話フレーム不足 ({}/{})".format(speech_frames, VAD_MIN_SPEECH_FRAMES)

    return {
        'has_speech': has_speech,
        'speech_frames': speech_frames,
        'total_frames': total_frames,
        'noise_energy': noise_energy,
        'energy_threshold': energy_threshold,
        'max_energy': max_energy,
        'speech_ratio': speech_ratio,
        'reason': reason,
    }


def is_hallucination(text):
    """幻聴フィルタ（強化版）"""
    if not text or len(text.strip()) < 2:
        return True

    text_clean = text.strip()

    # 既知の幻聴パターン
    if any(h in text_clean for h in HALLUCINATIONS):
        return True

    # 短すぎる（1-2文字のひらがな/カタカナ）
    if len(text_clean) <= 2 and re.match(r'^[\u3040-\u30FF]+$', text_clean):
        return True

    # 同じ文字/フレーズの繰り返し（「ああああ」「うんうんうん」）
    if len(set(text_clean)) <= 2 and len(text_clean) >= 3:
        return True

    # 句読点・記号のみ
    if re.match(r'^[\s。、！？…・\.\,\!\?]+$', text_clean):
        return True

    # 「...」や無意味な感嘆
    if text_clean in ["...", "…", "。", "、", "ん", "え", "あ"]:
        return True

    return False


# === 既存関数（v4から継承） ===

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
    result = ssh_run("test -f ~/face_watcher.py && echo OK", timeout=5)
    if "OK" in result:
        print("[SETUP] face_watcher.py 確認OK")
    else:
        print("[ERROR] face_watcher.py がホストにありません")


def start_face_watcher():
    ssh_run("pkill -f face_watcher 2>/dev/null", timeout=5)
    time.sleep(1)
    ssh_run("cd ~ && nohup python3 -u face_watcher.py > /tmp/face_watcher.log 2>&1 &", timeout=5)
    print("[SETUP] face_watcher.py 起動完了")


def record_on_host(duration):
    ssh_run(
        "arecord -D {} -d {} -f S16_LE -r 48000 -c 2 /tmp/pal_rec_raw.wav 2>/dev/null && "
        "ffmpeg -y -i /tmp/pal_rec_raw.wav -ar 16000 -ac 1 -filter:a 'volume=3.0' /tmp/pal_rec.wav 2>/dev/null".format(
            MIC_DEVICE, duration
        ),
        timeout=duration + 10,
    )


def check_face_detected():
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
    print("  パル音声チャット v5 (VAD強化)")
    print("  顔検出トリガー + 適応VAD + OpenClaw")
    print("=" * 40)

    load_config()

    print("[SETUP] ホスト側セットアップ中...")
    setup_face_detection_on_host()
    start_face_watcher()
    time.sleep(3)

    log = ssh_run("tail -5 /tmp/face_watcher.log")
    print("[HOST] face_watcher: {}".format(log))

    speak_on_host("はーい、パルだよ。顔を見せてくれたらお話しようね！")
    print("[READY] カメラに顔を見せてね！")

    while True:
        try:
            if check_face_detected():
                print("[FACE] 顔検出！")
                speak_on_host("なになに？")

                print("[REC] 録音中... ({}秒)".format(TALK_RECORD_SEC))
                record_on_host(TALK_RECORD_SEC)

                if copy_from_host("/tmp/pal_rec.wav", LOCAL_WAV):
                    # === VAD解析 ===
                    vad = vad_analyze(LOCAL_WAV)
                    print("[VAD] speech_frames:{}/{} noise:{:.0f} thresh:{:.0f} max:{:.0f} ratio:{:.1%} → {}".format(
                        vad.get('speech_frames', 0),
                        vad.get('total_frames', 0),
                        vad.get('noise_energy', 0),
                        vad.get('energy_threshold', 0),
                        vad.get('max_energy', 0),
                        vad.get('speech_ratio', 0),
                        "SPEECH" if vad['has_speech'] else "SKIP: " + vad.get('reason', ''),
                    ))

                    if vad['has_speech']:
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
                    else:
                        print("[SKIP] VAD: 音声なし")
                        speak_on_host("あれ、何も聞こえなかったよ。もう一回言って？")

                print("[READY] カメラに顔を見せてね！")

            time.sleep(1)

        except KeyboardInterrupt:
            print("\n=== 終了！ ===")
            ssh_run("pkill -f face_watcher 2>/dev/null")
            break
        except Exception as e:
            print("[ERROR] {}".format(e))
            time.sleep(3)


if __name__ == "__main__":
    main()
