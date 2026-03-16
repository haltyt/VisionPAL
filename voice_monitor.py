#!/usr/bin/env python3
"""パルの音声チャット v6 - 常時録音版
変更点(v6):
- face_watcher不要！常時VAD録音 + ウェイクワード「パル」方式
- ホスト上で直接実行（SSH不要）
- エネルギーベースVAD（適応的閾値）
- ゼロ交差率による音声/ノイズ判別
- Whisper幻聴の追加フィルタ
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
MIC_DEVICE = "plughw:3,0"
AUDIO_DEVICE = "bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink"
TALK_RECORD_SEC = 5
LOCAL_WAV = "/tmp/pal_stt_input.wav"

# OpenClaw Gateway API
OPENCLAW_URL = "http://172.19.0.2:18789/v1/chat/completions"
OPENCLAW_TOKEN = ""

# 会話履歴
CONVERSATION = []
MAX_HISTORY = 10
LAST_EXCHANGE = ""  # 直前の会話をWhisperプロンプトに使う

# === VAD設定 ===
VAD_FRAME_MS = 30          # フレーム長(ms)
VAD_SAMPLE_RATE = 16000    # 16kHz mono
VAD_FRAME_SAMPLES = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 480 samples

# 適応的閾値: 環境ノイズの倍率
VAD_ENERGY_MULTIPLIER = 2.0
VAD_MIN_ENERGY = 100       # 最低エネルギー閾値
VAD_ZCR_MAX = 0.4          # ゼロ交差率上限（高すぎ=ノイズ）
VAD_MIN_SPEECH_FRAMES = 8  # 最低発話フレーム数（240ms以上の発話が必要）
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
    "以上です", "以上",
    "パルとハルトの日常会話です", "日常会話",
    "短い日本語の話し言葉です",
]

FACE_COOLDOWN = 10

NORMALIZE_TARGET = 0.8  # ピーク音量をこの割合に正規化 (0.0-1.0)


# === 音声処理関数 ===

def denoise_wav(wav_path):
    """ffmpegでノイズ除去（highpass+lowpass+音量増幅）"""
    tmp_path = wav_path + ".denoised.wav"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path,
             "-af", "highpass=f=100,lowpass=f=8000,volume=2.0",
             "-ar", "16000", "-ac", "1", tmp_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100:
            os.rename(tmp_path, wav_path)
            print("[DENOISE] OK")
        else:
            print("[DENOISE] Failed, using original")
    except Exception as e:
        print("[DENOISE] Error: {}".format(e))


def normalize_wav(wav_path, out_path=None):
    """WAVの音量をノーマライズ（ピークをNORMALIZE_TARGETに）"""
    if out_path is None:
        out_path = wav_path
    try:
        w = wave.open(wav_path, "rb")
        params = w.getparams()
        frames = w.readframes(w.getnframes())
        w.close()

        samples = list(struct.unpack("<%dh" % (len(frames) // 2), frames))
        if not samples:
            return False

        peak = max(abs(s) for s in samples)
        if peak < 100:  # ほぼ無音
            return False

        target = int(32767 * NORMALIZE_TARGET)
        factor = target / peak
        if factor <= 1.05:  # 既に十分な音量
            return True

        normalized = [max(-32767, min(32767, int(s * factor))) for s in samples]
        out_frames = struct.pack("<%dh" % len(normalized), *normalized)

        w = wave.open(out_path, "wb")
        w.setparams(params)
        w.writeframes(out_frames)
        w.close()
        print("[NORM] peak:{} → factor:{:.2f}".format(peak, factor))
        return True
    except Exception as e:
        print("[ERROR] normalize: {}".format(e))
        return False


def extract_speech_region(wav_path, out_path=None, threshold_mult=1.5, margin_frames=3):
    """VADで音声がある最初〜最後の区間だけ切り出す（前後マージン付き）"""
    if out_path is None:
        out_path = wav_path
    try:
        w = wave.open(wav_path, "rb")
        params = w.getparams()
        raw = w.readframes(w.getnframes())
        w.close()

        samples = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
        if not samples:
            return False

        frame_size = VAD_FRAME_SAMPLES
        frames = []
        for i in range(0, len(samples) - frame_size + 1, frame_size):
            frames.append(samples[i:i + frame_size])

        if len(frames) < VAD_NOISE_FRAMES + 2:
            return False

        noise = sum(frame_energy(f) for f in frames[:VAD_NOISE_FRAMES]) / VAD_NOISE_FRAMES
        thresh = max(noise * threshold_mult, VAD_MIN_ENERGY)

        # speechフレームのインデックスを収集
        speech_indices = [i for i, f in enumerate(frames) if frame_energy(f) > thresh]
        if not speech_indices:
            return False

        # 最初と最後のspeechフレーム ± マージン
        start_idx = max(0, speech_indices[0] - margin_frames)
        end_idx = min(len(frames) - 1, speech_indices[-1] + margin_frames)

        start_sample = start_idx * frame_size
        end_sample = (end_idx + 1) * frame_size
        trimmed = samples[start_sample:end_sample]

        original_len = len(samples) / params.framerate
        trimmed_len = len(trimmed) / params.framerate

        if trimmed_len < original_len * 0.90:  # 10%以上カットした場合のみ
            out_frames = struct.pack("<%dh" % len(trimmed), *trimmed)
            w = wave.open(out_path, "wb")
            w.setparams(params)
            w.setnframes(len(trimmed))
            w.writeframes(out_frames)
            w.close()
            print("[EXTRACT] {:.1f}s → {:.1f}s (音声区間のみ)".format(original_len, trimmed_len))
        return True
    except Exception as e:
        print("[ERROR] extract: {}".format(e))
        return False


def trim_trailing_silence(wav_path, out_path=None, threshold_mult=1.5, min_silence_frames=10):
    """WAVの後ろの無音をカット（前は残す、途中の無音も残す）"""
    if out_path is None:
        out_path = wav_path
    try:
        w = wave.open(wav_path, "rb")
        params = w.getparams()
        raw = w.readframes(w.getnframes())
        w.close()

        samples = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
        if not samples:
            return False

        frame_size = VAD_FRAME_SAMPLES
        frames = []
        for i in range(0, len(samples) - frame_size + 1, frame_size):
            frames.append(samples[i:i + frame_size])

        if len(frames) < VAD_NOISE_FRAMES + 2:
            return False

        # ノイズレベル推定（冒頭フレーム）
        noise = sum(frame_energy(f) for f in frames[:VAD_NOISE_FRAMES]) / VAD_NOISE_FRAMES
        thresh = max(noise * threshold_mult, VAD_MIN_ENERGY)

        # 最後のspeechフレームを見つける
        last_speech_idx = -1
        for i, f in enumerate(frames):
            if frame_energy(f) > thresh:
                last_speech_idx = i

        if last_speech_idx < 0:
            return False  # 音声なし

        # 最後のspeechフレーム + 少しマージン（3フレーム≒90ms）
        cut_idx = min(last_speech_idx + 3, len(frames) - 1)
        cut_sample = (cut_idx + 1) * frame_size
        trimmed = samples[:cut_sample]

        original_len = len(samples) / params.framerate
        trimmed_len = len(trimmed) / params.framerate
        if trimmed_len < original_len * 0.95:  # 5%以上カットした場合のみ書き出し
            out_frames = struct.pack("<%dh" % len(trimmed), *trimmed)
            w = wave.open(out_path, "wb")
            w.setparams(params)
            w.setnframes(len(trimmed))
            w.writeframes(out_frames)
            w.close()
            print("[TRIM] {:.1f}s → {:.1f}s (後ろ{:.1f}sカット)".format(
                original_len, trimmed_len, original_len - trimmed_len))
        return True
    except Exception as e:
        print("[ERROR] trim: {}".format(e))
        return False


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
    # 環境変数優先、なければconfigファイル
    OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
    if OPENCLAW_TOKEN:
        print("[CONFIG] OPENCLAW_TOKEN: 環境変数から取得")
        return
    for path in ["/home/node/.openclaw/openclaw.json", os.path.expanduser("~/.openclaw/openclaw.json")]:
        try:
            with open(path) as f:
                config = json.load(f)
            OPENCLAW_TOKEN = config["gateway"]["auth"]["token"]
            print("[CONFIG] OPENCLAW_TOKEN: {}から取得".format(path))
            return
        except Exception:
            pass
    print("[WARN] OPENCLAW_TOKEN未設定（応答不可）")


def ssh_run(cmd, timeout=15):
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no", HOST, cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout,
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
    # Check if already running
    result = ssh_run("pgrep -f 'python3.*face_watcher' && echo RUNNING", timeout=5)
    if result and "RUNNING" in result:
        print("[SETUP] face_watcher.py 既に稼働中、スキップ")
        return
    ssh_run("pkill -f face_watcher 2>/dev/null", timeout=5)
    time.sleep(3)
    ssh_run("cd ~ && nohup python3 -u face_watcher.py > /tmp/face_watcher.log 2>&1 &", timeout=5)
    print("[SETUP] face_watcher.py 起動完了")


def record_on_host(duration):
    """固定時間録音（pal_record.py、無音タイムアウト長め）"""
    try:
        result = subprocess.run(
            ["python3", os.path.expanduser("~/PAL/voice/pal_record.py"), str(duration), "3.0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
            timeout=duration + 5,
        )
        print("[REC] {}".format(result.stdout.strip()))
    except Exception as e:
        print("[ERROR] record: {}".format(e))


def check_face_detected():
    result = ssh_run("cat /tmp/pal_voice/face_detected 2>/dev/null && rm /tmp/pal_voice/face_detected 2>/dev/null")
    return bool(result)


def copy_from_host(remote_path, local_path):
    """ホスト上で直接実行 — ファイルコピー（同一マシン）"""
    try:
        import shutil
        shutil.copy2(remote_path, local_path)
        return os.path.exists(local_path)
    except Exception:
        return False


def whisper_stt(wav_path):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        for env_path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.openai"),
            os.path.expanduser("~/.openclaw/workspace/.env.openai"),
            os.path.expanduser("~/.env.openai"),
        ]:
            try:
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("OPENAI_API_KEY="):
                            api_key = line.strip().split("=", 1)[1]
                if api_key:
                    break
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
             "-F", "model=gpt-4o-transcribe",
             "-F", "language=ja",
             "-F", "prompt={}".format(LAST_EXCHANGE if LAST_EXCHANGE else "")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30,
        )
        data = json.loads(result.stdout)
        text = data.get("text", "")
        print("[WHISPER] '{}'".format(text))
        return text
    except Exception as e:
        print("[ERROR] Whisper API: {} stdout={}".format(e, result.stdout[:200] if 'result' in dir() else '?'))
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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=35,
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


def beep_on_host(kind="ok"):
    """ビープ音: rec=ピピッ(録音開始), ok=ピコピコ(Whisper投げる), skip=ブッ(スキップ)"""
    files = {"ok": "/tmp/beep.wav", "skip": "/tmp/beep_skip.wav", "rec": "/tmp/beep.wav"}
    f = files.get(kind, "/tmp/beep.wav")
    try:
        subprocess.run(
            ["bash", "-c", "paplay --device=bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink {} 2>/dev/null || paplay {} 2>/dev/null".format(f, f)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
        )
    except Exception:
        pass


def speak_elevenlabs(text):
    """ElevenLabs TTS → BTスピーカー再生（フォールバック: Open JTalk）"""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print("[TTS] No ElevenLabs key, falling back to Open JTalk")
        return speak_jtalk(text)

    voice_id = "fUjY9K2nAIwlALOwSiwc"  # Yui
    url = "https://api.elevenlabs.io/v1/text-to-speech/{}".format(voice_id)
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        }
    }).encode("utf-8")

    try:
        import urllib.request
        req = urllib.request.Request(url, data=payload, headers=headers)
        mp3_path = "/tmp/pal_tts_elevenlabs.mp3"
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(mp3_path, "wb") as f:
                f.write(resp.read())

        if os.path.getsize(mp3_path) < 100:
            print("[TTS] ElevenLabs returned empty, falling back")
            return speak_jtalk(text)

        # mp3→wav変換してpaplayで再生（BT→フォールバック）
        wav_path = "/tmp/pal_tts_elevenlabs.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "2", wav_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        subprocess.run(
            ["bash", "-c",
             "paplay --device={dev} {wav} 2>/dev/null || paplay {wav} 2>/dev/null".format(
                 dev=AUDIO_DEVICE, wav=wav_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        print("[TTS] ElevenLabs OK: {}".format(text[:40]))
    except Exception as e:
        print("[TTS] ElevenLabs error: {}, falling back".format(e))
        speak_jtalk(text)


def speak_jtalk(text):
    """Open JTalk フォールバック"""
    try:
        subprocess.run(
            [os.path.expanduser("~/PAL/scripts/pal_speak.sh"), text, "happy"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except Exception as e:
        print("[ERROR] jtalk speak: {}".format(e))


def speak_on_host(text):
    text = clean_for_tts(text)
    if not text:
        return
    speak_elevenlabs(text)


def send_to_discord(user_text, pal_text):
    try:
        bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not bot_token:
            for path in ["/home/node/.openclaw/openclaw.json", os.path.expanduser("~/.openclaw/openclaw.json")]:
                try:
                    config = json.load(open(path))
                    bot_token = config["channels"]["discord"]["token"]
                    break
                except Exception:
                    pass
        dm_channel = "1469326108322168943"

        msg = "🎤 **ハルト**: {}\n🐾 **パル**: {}".format(user_text, pal_text)
        payload = json.dumps({"content": msg}, ensure_ascii=False)
        subprocess.run(
            ["curl", "-s", "-m", "10",
             "https://discord.com/api/v10/channels/{}/messages".format(dm_channel),
             "-H", "Authorization: Bot {}".format(bot_token),
             "-H", "Content-Type: application/json",
             "-d", payload],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        print("[DISCORD] 送信完了")
    except Exception as e:
        print("[ERROR] Discord送信: {}".format(e))


def send_debug_to_discord(text):
    """デバッグ用: STT結果等をDiscordに通知"""
    try:
        bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not bot_token:
            for path in ["/home/node/.openclaw/openclaw.json", os.path.expanduser("~/.openclaw/openclaw.json")]:
                try:
                    config = json.load(open(path))
                    bot_token = config["channels"]["discord"]["token"]
                    break
                except Exception:
                    pass
        if not bot_token:
            print("[DEBUG] Discord token not found")
            return
        dm_channel = "1469326108322168943"
        payload = json.dumps({"content": "🔍 {}".format(text)}, ensure_ascii=False)
        subprocess.run(
            ["curl", "-s", "-m", "10",
             "https://discord.com/api/v10/channels/{}/messages".format(dm_channel),
             "-H", "Authorization: Bot {}".format(bot_token),
             "-H", "Content-Type: application/json",
             "-H", "User-Agent: DiscordBot (https://openclaw.ai, 1.0)",
             "-d", payload],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
    except Exception:
        pass


def main():
    print("=" * 40)
    print("  パル音声チャット v6 (常時録音)")
    print("  VAD常時監視 + OpenClaw")
    print("=" * 40)

    load_config()

    speak_on_host("はーい、パルだよ。いつでも話しかけてね！")
    print("[READY] 常時録音モード開始！話しかけてね🎤")

    while True:
        try:
            beep_on_host("rec")  # ピピッ♪ 録音開始合図
            print("[REC] 録音中... ({}秒)".format(TALK_RECORD_SEC))
            record_on_host(TALK_RECORD_SEC)

            if copy_from_host("/tmp/pal_rec.wav", LOCAL_WAV):
                # ノイズ除去（VADの前にやる！カメラマイクのノイズフロアが高いため）
                denoise_wav(LOCAL_WAV)
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
                    # speech_ratioチェックは緩め（gpt-4o-transcribe+区間切り出しで幻聴対策済み）
                    if vad.get('speech_ratio', 0) < 0.05:
                        print("[SKIP] speech_ratio低すぎ ({:.1%})".format(vad['speech_ratio']))
                        continue

                    # 音声区間切り出し → 音量ノーマライズ → Whisperへ
                    extract_speech_region(LOCAL_WAV)
                    # 切り出し後が短すぎたらスキップ（Whisperが幻聴する）
                    try:
                        w = wave.open(LOCAL_WAV, "rb")
                        duration = w.getnframes() / w.getframerate()
                        w.close()
                        if duration < 0.5:
                            print("[SKIP] 音声が短すぎ ({:.1f}s)".format(duration))
                            continue
                    except Exception:
                        pass
                    normalize_wav(LOCAL_WAV)
                    text = whisper_stt(LOCAL_WAV)

                    # デバッグ: Whisper結果をDiscordに通知
                    send_debug_to_discord("[STT] {} (frames:{}/{})".format(
                        text if text else "(空)",
                        vad.get('speech_frames', 0),
                        vad.get('total_frames', 0),
                    ))

                    if is_hallucination(text):
                        print("[SKIP] 幻聴フィルタ: {}".format(text))
                        continue

                    # ウェイクワード「パル」チェック（デバッグ中: 一時的に無効化）
                    # TODO: 安定したらウェイクワードチェック復活
                    query = text.strip(" 、,。.!？?")

                    if not query:
                        continue

                    print("[YOU] {}".format(query))
                    print("[THINK] パルが考え中...")
                    response = ask_pal(query)

                    if response:
                        # エラー応答はTTSに渡さない
                        skip_tts = any(x in response for x in [
                            "No response", "error", "ERROR", "HEARTBEAT",
                        ])
                        print("[PAL] {}".format(response))
                        if not skip_tts:
                            speak_on_host(response)
                        else:
                            print("[SKIP-TTS] エラー応答のためTTSスキップ")
                        send_to_discord(query, response)
                        LAST_EXCHANGE = "{}。{}".format(query, response)
                        time.sleep(1.5)  # TTS音がマイクに回り込むのを待つ
                    else:
                        print("[SKIP] OpenClawから空応答")

            time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n=== 終了！ ===")
            break
        except Exception as e:
            print("[ERROR] {}".format(e))
            time.sleep(3)


if __name__ == "__main__":
    main()
