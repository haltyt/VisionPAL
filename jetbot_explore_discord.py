#!/usr/bin/env python3
"""JetBot Explorer with real-time Discord notifications.
Strategy: Start explorer on JetBot via nohup, then tail -f the log for real-time events.
"""

import subprocess
import sys
import os
import re
import json
import uuid
import time
from urllib.request import Request, urlopen

DISCORD_CHANNEL = "1469326108322168943"
DISCORD_API = "https://discord.com/api/v10"
HEADERS = {}

SSH_HOST = ["ssh", "-o", "StrictHostKeyChecking=no", "haltyt@172.19.0.1"]
SSH_JETBOT = "ssh -o StrictHostKeyChecking=no jetbot@192.168.3.6"

def load_token():
    global HEADERS
    with open("/home/node/.openclaw/openclaw.json") as f:
        config = json.load(f)
    token = config["channels"]["discord"]["token"]
    HEADERS = {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://openclaw.ai, 1.0)"
    }

def send_discord(message):
    try:
        data = json.dumps({"content": message}).encode()
        req = Request(
            f"{DISCORD_API}/channels/{DISCORD_CHANNEL}/messages",
            data=data,
            headers={**HEADERS, "Content-Type": "application/json"},
            method="POST"
        )
        resp = urlopen(req, timeout=10)
        print(f"[Discord] Sent: {message[:50]}...")
    except Exception as e:
        print(f"[Discord] Send error: {e}")

def send_discord_photo(filepath, caption=""):
    try:
        local_path = f"/tmp/{os.path.basename(filepath)}"
        # SCP: JetBot → Host
        subprocess.run(
            SSH_HOST + [f"scp -o StrictHostKeyChecking=no jetbot@192.168.3.6:{filepath} /tmp/_jetbot_tmp.jpg"],
            timeout=15, capture_output=True
        )
        # SCP: Host → Container
        subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "haltyt@172.19.0.1:/tmp/_jetbot_tmp.jpg", local_path],
            timeout=15, capture_output=True
        )
        
        if not os.path.exists(local_path):
            print(f"[Discord] Photo SCP failed: {filepath}")
            return
        
        boundary = uuid.uuid4().hex
        with open(local_path, "rb") as f:
            file_data = f.read()
        
        body = b""
        if caption:
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"content\"\r\n\r\n"
            body += caption.encode() + b"\r\n"
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(filepath)}"\r\n'.encode()
        body += b"Content-Type: image/jpeg\r\n\r\n"
        body += file_data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        
        req = Request(
            f"{DISCORD_API}/channels/{DISCORD_CHANNEL}/messages",
            data=body,
            headers={**HEADERS, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )
        urlopen(req, timeout=30)
        print(f"[Discord] Photo sent: {filepath}")
        try:
            os.remove(local_path)
        except:
            pass
    except Exception as e:
        print(f"[Discord] Photo error: {e}")

def ssh_jetbot(cmd):
    """Run a command on JetBot via 2-hop SSH."""
    return subprocess.run(
        SSH_HOST + [f"{SSH_JETBOT} '{cmd}'"],
        capture_output=True, text=True, timeout=15
    )

def run_explorer(duration=60, speed=0.3):
    load_token()
    send_discord(f"🐾 探索モード開始！ {duration}秒 / スピード{speed}")
    
    # Kill PulseAudio and disable autospawn so aplay can access device directly
    ssh_jetbot("pulseaudio --kill 2>/dev/null; mkdir -p ~/.config/pulse; echo 'autospawn = no' > ~/.config/pulse/client.conf; amixer -c 2 set PCM 50%")
    time.sleep(2)
    
    # Clear old log and start explorer with nohup
    ssh_jetbot(f"rm -f /tmp/explorer_live.log; nohup python3 -u ~/jetbot_explorer.py --explore --duration {duration} --speed {speed} > /tmp/explorer_live.log 2>&1 & echo $!")
    
    send_discord("🔊 モデル読み込み中…🧠")
    
    # Wait for explorer to start (model loading takes time)
    time.sleep(5)
    
    # Use tail -f via SSH to get real-time log
    # Use -tt to force PTY for line-buffered output
    tail_cmd = SSH_HOST + ["-tt", f"{SSH_JETBOT} 'tail -n +1 -f /tmp/explorer_live.log'"]
    
    proc = subprocess.Popen(
        tail_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0
    )
    
    photo_count = 0
    blocked_count = 0
    done = False
    model_notified = False
    start_notified = False
    start_time = time.time()
    max_wait = duration + 180  # Extra time for model loading
    
    try:
        while not done and (time.time() - start_time) < max_wait:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            
            line = line.decode("utf-8", errors="replace").strip()
            # Remove ANSI escape codes from PTY
            line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
            line = re.sub(r'\r', '', line)
            if not line:
                continue
            
            print(line)
            
            if "Model loaded" in line or "CNN model loaded" in line:
                if not model_notified:
                    send_discord("🧠 CNNモデル読み込み完了！")
                    model_notified = True
            
            elif "[Explorer] Starting exploration" in line:
                if not start_notified:
                    send_discord("🟢 走り出すよ～！💨")
                    start_notified = True
            
            elif "[Explorer] Blocked!" in line:
                blocked_count += 1
                m = re.search(r'conf=(\d+\.\d+)', line)
                conf = m.group(1) if m else "?"
                send_discord(f"🔴 障害物検知！ (conf={conf}, #{blocked_count})")
            
            elif "[Explorer] STUCK" in line:
                send_discord("⚠️ スタック！180°ターン！")
            
            elif "[Explorer] Random turn" in line:
                m = re.search(r'turn (\w+) \((.+?)s\)', line)
                if m:
                    d = "⬅️" if m.group(1) == "left" else "➡️"
                    send_discord(f"{d} ランダムターン ({m.group(2)}s)")
            
            elif "[Explorer] Photo saved:" in line:
                photo_count += 1
                m = re.search(r'Photo saved: (.+)', line)
                if m:
                    filepath = m.group(1).strip()
                    # Small delay to let file finish writing
                    time.sleep(0.5)
                    emoji = "🔴" if "obstacle" in filepath else "📸"
                    send_discord_photo(filepath, f"{emoji} 写真 #{photo_count}")
            
            elif "[Explorer] Done." in line:
                m = re.search(r'Photos=(\d+), Free=(\d+), Blocked=(\d+)', line)
                if m:
                    send_discord(
                        f"✅ 探索完了！\n"
                        f"📸 写真: {m.group(1)}枚\n"
                        f"🟢 Free: {m.group(2)}回\n"
                        f"🔴 Blocked: {m.group(3)}回"
                    )
                done = True
    
    except KeyboardInterrupt:
        print("[Monitor] Interrupted")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except:
            proc.kill()
    
    print(f"[Monitor] Done. Photos={photo_count}, Blocked={blocked_count}")

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    speed = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    run_explorer(duration, speed)
