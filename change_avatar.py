#!/usr/bin/env python3
"""Change Discord bot avatar based on system load, time, and disk usage."""
import json, base64, urllib.request, urllib.error, os, sys, subprocess, datetime, tempfile

FACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pal_faces")
CONFIG_PATH = os.path.expanduser("~/.openclaw/openclaw.json")
STATE_FILE = os.path.join(FACES_DIR, ".last_state")
JST_OFFSET = 9

def get_token():
    with open(CONFIG_PATH) as f:
        return json.load(f)["channels"]["discord"]["token"]

def get_host_stats():
    """Get CPU, memory, and disk usage from host."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             "haltyt@172.19.0.1",
             "cat /proc/loadavg; free -m | grep Mem; df / | tail -1"],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split("\n")
        load_1min = float(lines[0].split()[0])
        cpu_result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             "haltyt@172.19.0.1", "nproc"],
            capture_output=True, text=True, timeout=10
        )
        ncpu = int(cpu_result.stdout.strip())
        cpu_pct = (load_1min / ncpu) * 100

        mem_parts = lines[1].split()
        mem_pct = (int(mem_parts[2]) / int(mem_parts[1])) * 100

        # Disk: /dev/mmcblk0p1  29G  18G  9.4G  66% /
        disk_str = lines[2].split()[-2].replace('%', '')
        disk_pct = int(disk_str)

        return cpu_pct, mem_pct, disk_pct
    except Exception as e:
        print(f"Stats error: {e}")
        return 50, 50, 50

def choose_face(cpu_pct, mem_pct):
    """Choose expression based on CPU, memory, and time."""
    jst_hour = (datetime.datetime.utcnow().hour + JST_OFFSET) % 24

    if cpu_pct > 70:
        return "tired.png", f"CPU高負荷({cpu_pct:.0f}%)"
    elif mem_pct > 80:
        return "sad.png", f"メモリ逼迫({mem_pct:.0f}%)"
    elif 23 <= jst_hour or jst_hour < 7:
        return "sleepy.png", f"深夜({jst_hour}時)"
    elif cpu_pct < 20 and mem_pct < 50:
        return "excited.png", "低負荷で元気！"
    elif cpu_pct > 40:
        return "thinking.png", f"考え中(CPU {cpu_pct:.0f}%)"
    else:
        return "happy.png", "通常"

def add_water_overlay(face_path, disk_pct):
    """Add blue transparent water overlay based on disk usage."""
    out_path = tempfile.mktemp(suffix='.png')
    try:
        # Get image dimensions
        result = subprocess.run(
            ["identify", "-format", "%wx%h", face_path],
            capture_output=True, text=True, timeout=5
        )
        w, h = map(int, result.stdout.strip().split('x'))

        # Water height from bottom
        water_h = int(h * disk_pct / 100)
        water_y = h - water_h

        # Overlay blue transparent rectangle
        subprocess.run([
            "convert", face_path,
            "-fill", "rgba(100,180,255,0.35)",
            "-draw", f"rectangle 0,{water_y} {w},{h}",
            out_path
        ], check=True, timeout=10)

        return out_path
    except Exception as e:
        print(f"Overlay error: {e}")
        return face_path

def change_avatar():
    cpu_pct, mem_pct, disk_pct = get_host_stats()
    face, reason = choose_face(cpu_pct, mem_pct)
    face_path = os.path.join(FACES_DIR, face)

    if not os.path.exists(face_path):
        print(f"File not found: {face_path}")
        return False

    state_key = f"{face}:{disk_pct}"
    print(f"CPU: {cpu_pct:.0f}%, MEM: {mem_pct:.0f}%, DISK: {disk_pct}%, Face: {face}, Reason: {reason}")

    # Skip if same state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                if f.read().strip() == state_key:
                    print("Same state, skipping API call.")
                    return True
    except:
        pass

    # Add water overlay for disk usage
    avatar_path = add_water_overlay(face_path, disk_pct)

    try:
        with open(avatar_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()

        token = get_token()
        payload = json.dumps({"avatar": f"data:image/png;base64,{img_data}"}).encode()
        req = urllib.request.Request(
            "https://discord.com/api/v10/users/@me",
            data=payload,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://openclaw.ai, 1.0)"
            },
            method="PATCH"
        )
        resp = urllib.request.urlopen(req)
        json.loads(resp.read())
        print(f"Avatar → {face} + 💧{disk_pct}% ({reason})")
        with open(STATE_FILE, "w") as f:
            f.write(state_key)
        return True
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}")
        return False
    finally:
        if avatar_path != face_path:
            try: os.unlink(avatar_path)
            except: pass

if __name__ == "__main__":
    change_avatar()
