#!/usr/bin/env python3
"""
Umwelt Battle RPG - パルの環世界モンスターバトル
JetBotカメラ → VLM環境解析 → モンスター生成 → ターン制バトル → 画像生成

Usage:
  # テスト（ローカル画像）
  python3 umwelt_battle.py --image /tmp/jetbot_snap.jpg

  # JetBotライブ
  python3 umwelt_battle.py --live

  # Discordインタラクティブ（cognitive_loopと連携）
  python3 umwelt_battle.py --image /tmp/jetbot_snap.jpg --discord
"""

import argparse
import json
import os
import sys
import random
import subprocess
import base64
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Gemini API ──────────────────────────────────────────

def get_gemini_key():
    """Get GEMINI_API_KEY from env or openclaw config."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        key = (cfg.get("skills", {}).get("entries", {})
               .get("nano-banana-pro", {}).get("env", {})
               .get("GEMINI_API_KEY"))
        if key:
            return key
    raise RuntimeError("GEMINI_API_KEY not found")


def gemini_vlm(image_path: str, prompt: str) -> str:
    """Call Gemini flash-lite with image for scene analysis."""
    key = get_gemini_key()
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={key}"
    body = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {"temperature": 0.8}
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    return text


def gemini_text(prompt: str) -> str:
    """Call Gemini flash-lite text-only."""
    key = get_gemini_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0}
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


# ── Scene Analysis ──────────────────────────────────────

def analyze_scene(image_path: str) -> dict:
    """Analyze image → environment type, mood, elements."""
    prompt = """この画像を分析して、RPGゲームの環境として解釈してください。
JSON形式で回答：
{
  "environment": "環境タイプ（例：暗い洞窟、明るい草原、水辺、廃墟など）",
  "mood": "雰囲気（例：不気味、穏やか、神秘的など）",
  "elements": ["目立つ要素1", "要素2", "要素3"],
  "danger_level": 1-5の数値,
  "color_theme": "主要な色調"
}
JSONのみ出力。説明不要。"""

    text = gemini_vlm(image_path, prompt)
    # Extract JSON
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


# ── Monster Generation ──────────────────────────────────

def generate_monster(scene: dict) -> dict:
    """Generate a cat-type monster based on scene."""
    prompt = f"""あなたはファンタジーRPGのモンスターデザイナーです。
以下の環境に合ったネコ型モンスターを1体生成してください。

環境: {scene['environment']}
雰囲気: {scene['mood']}
要素: {', '.join(scene['elements'])}
危険度: {scene['danger_level']}/5
色調: {scene['color_theme']}

JSON形式で回答：
{{
  "name": "モンスター名（日本語、かっこいい名前）",
  "name_en": "English name for image generation",
  "type": "属性（火/水/闇/光/風/雷/氷/毒）",
  "description": "外見の詳細描写（2-3文）",
  "hp": 適切なHP（30-100）,
  "attack": 攻撃力（5-20）,
  "defense": 防御力（3-15）,
  "special_move": "必殺技の名前",
  "special_desc": "必殺技の演出描写",
  "weakness": "弱点属性",
  "personality": "性格（1文）"
}}
JSONのみ出力。"""

    text = gemini_text(prompt)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


# ── Pal Stats ───────────────────────────────────────────

class PalStats:
    """パルのバトルステータス（感情ベース）"""

    EMOTION_BUFFS = {
        "curious":  {"attack": 2, "defense": 0, "speed": 3, "luck": 5},
        "excited":  {"attack": 5, "defense": -2, "speed": 4, "luck": 2},
        "calm":     {"attack": 0, "defense": 5, "speed": 0, "luck": 3},
        "anxious":  {"attack": -2, "defense": 2, "speed": 5, "luck": -2},
        "happy":    {"attack": 3, "defense": 2, "speed": 2, "luck": 5},
        "lonely":   {"attack": -3, "defense": -2, "speed": -1, "luck": 0},
        "startled": {"attack": 4, "defense": -3, "speed": 6, "luck": -1},
        "bored":    {"attack": -1, "defense": 0, "speed": -3, "luck": 1},
    }

    def __init__(self, emotion: str = "curious"):
        self.max_hp = 80
        self.hp = 80
        self.base_attack = 12
        self.base_defense = 8
        self.base_speed = 10
        self.base_luck = 5
        self.emotion = emotion
        self.level = 1

    @property
    def buffs(self):
        return self.EMOTION_BUFFS.get(self.emotion, {})

    @property
    def attack(self):
        return max(1, self.base_attack + self.buffs.get("attack", 0))

    @property
    def defense(self):
        return max(1, self.base_defense + self.buffs.get("defense", 0))

    @property
    def speed(self):
        return max(1, self.base_speed + self.buffs.get("speed", 0))

    @property
    def luck(self):
        return max(0, self.base_luck + self.buffs.get("luck", 0))

    def status_text(self):
        return (f"🐾 パル [HP: {self.hp}/{self.max_hp}] "
                f"感情: {self.emotion} | "
                f"攻撃:{self.attack} 防御:{self.defense} "
                f"速度:{self.speed} 運:{self.luck}")


# ── Battle Engine ───────────────────────────────────────

class BattleEngine:
    """ターン制バトルエンジン"""

    def __init__(self, pal: PalStats, monster: dict, scene: dict):
        self.pal = pal
        self.monster = monster
        self.monster_hp = monster["hp"]
        self.monster_max_hp = monster["hp"]
        self.scene = scene
        self.turn = 0
        self.log = []

    def pal_attack(self, action: str = "attack") -> str:
        """パルの攻撃ターン"""
        self.turn += 1

        if action == "attack":
            # 通常攻撃
            damage = max(1, self.pal.attack - self.monster.get("defense", 5) // 2)
            # クリティカル判定（luck依存）
            crit = random.random() < (self.pal.luck / 30)
            if crit:
                damage = int(damage * 1.8)
                msg = f"⚡ **クリティカル！** パルの突撃！ {damage}ダメージ！"
            else:
                msg = f"🐾 パルの突撃！ {damage}ダメージ！"
            self.monster_hp = max(0, self.monster_hp - damage)

        elif action == "special":
            # 必殺技（感情パワー）
            damage = int(self.pal.attack * 1.5) + random.randint(2, 8)
            self.monster_hp = max(0, self.monster_hp - damage)
            emotion_moves = {
                "curious": "🔍 好奇心ビーム",
                "excited": "🔥 テンションバースト",
                "calm": "🌊 静寂の一撃",
                "anxious": "⚡ パニックラッシュ",
                "happy": "✨ ハッピースマッシュ",
                "startled": "💥 びっくりアタック",
                "bored": "😪 あくびキャノン",
                "lonely": "💫 さみしさの波動",
            }
            move_name = emotion_moves.get(self.pal.emotion, "🌟 パルアタック")
            msg = f"{move_name}！ {damage}ダメージ！"

        elif action == "dodge":
            # 回避（次の被ダメ半減フラグ）
            msg = "🌀 パルは身構えた！（次の被ダメ半減）"
            self._dodge_next = True
            self.log.append(msg)
            return msg

        self.log.append(msg)
        return msg

    def monster_attack(self) -> str:
        """モンスターの攻撃ターン"""
        m_atk = self.monster.get("attack", 10)

        # 必殺技確率（HP低いほど高い）
        hp_ratio = self.monster_hp / self.monster_max_hp
        special_chance = 0.3 if hp_ratio < 0.4 else 0.1

        dodge = getattr(self, "_dodge_next", False)
        self._dodge_next = False

        if random.random() < special_chance:
            damage = max(1, int(m_atk * 1.5) - self.pal.defense // 2)
            if dodge:
                damage = damage // 2
            self.pal.hp = max(0, self.pal.hp - damage)
            msg = (f"😼 {self.monster['name']}の **{self.monster['special_move']}**！ "
                   f"{damage}ダメージ！{'（半減！）' if dodge else ''}")
        else:
            damage = max(1, m_atk - self.pal.defense // 2)
            if dodge:
                damage = damage // 2
            self.pal.hp = max(0, self.pal.hp - damage)
            msg = (f"😼 {self.monster['name']}の攻撃！ "
                   f"{damage}ダメージ！{'（半減！）' if dodge else ''}")

        self.log.append(msg)
        return msg

    def status_bar(self) -> str:
        """HP バー表示"""
        def bar(hp, max_hp, length=15):
            filled = int(hp / max_hp * length)
            return "█" * filled + "░" * (length - filled)

        pal_bar = bar(self.pal.hp, self.pal.max_hp)
        mon_bar = bar(self.monster_hp, self.monster_max_hp)

        return (f"```\n"
                f"🐾 パル    [{pal_bar}] {self.pal.hp}/{self.pal.max_hp}\n"
                f"😼 {self.monster['name'][:6]} [{mon_bar}] {self.monster_hp}/{self.monster_max_hp}\n"
                f"```")

    @property
    def is_over(self) -> bool:
        return self.pal.hp <= 0 or self.monster_hp <= 0

    @property
    def pal_won(self) -> bool:
        return self.monster_hp <= 0


# ── Image Generation ────────────────────────────────────

def generate_battle_image(scene: dict, monster: dict, battle_phase: str = "encounter",
                          output_path: str = "/tmp/battle_scene.png") -> str:
    """Nano Banana Pro でバトルシーン画像生成"""
    phase_desc = {
        "encounter": "facing each other, tension, dramatic lighting",
        "battle": "mid-combat, energy effects, dynamic action poses",
        "victory": "triumphant pose, defeated enemy fading, golden light",
        "defeat": "exhausted hero, looming enemy, dark atmosphere",
    }

    prompt = (
        f"Fantasy RPG battle scene. A cute small blue-white fluffy cat creature with star antenna "
        f"(the hero 'Pal') {phase_desc.get(battle_phase, '')}. "
        f"Enemy: {monster.get('name_en', 'cat monster')}, {monster.get('description', '')}. "
        f"Environment: {scene.get('environment', 'mysterious')}, {scene.get('mood', '')} atmosphere. "
        f"Color theme: {scene.get('color_theme', 'dark')}. "
        f"Anime game art style, vibrant colors, dramatic composition, HP bars overlay."
    )

    script = "/app/skills/nano-banana-pro/scripts/generate_image.py"
    cmd = ["uv", "run", script, "--prompt", prompt, "--filename", output_path, "--resolution", "1K"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        # find MEDIA: line
        for line in result.stdout.split("\n"):
            if line.startswith("MEDIA:"):
                return line
        return f"MEDIA:{output_path}"
    else:
        print(f"Image generation failed: {result.stderr[:200]}", file=sys.stderr)
        return ""


# ── Auto Battle (non-interactive) ──────────────────────

def auto_battle(pal: PalStats, monster: dict, scene: dict) -> list:
    """自動バトル → テキストログ返却"""
    engine = BattleEngine(pal, monster, scene)
    lines = []

    lines.append(f"## ⚔️ {monster['name']} が現れた！")
    lines.append(f"> *{monster['description']}*")
    lines.append(f"> 属性: {monster['type']} | 弱点: {monster['weakness']}")
    lines.append(f"> HP: {monster['hp']} 攻撃: {monster['attack']} 防御: {monster['defense']}")
    lines.append(f"> 必殺技: **{monster['special_move']}** — {monster['special_desc']}")
    lines.append("")
    lines.append(pal.status_text())
    lines.append("")

    while not engine.is_over:
        # パルのAI行動選択
        if pal.hp < pal.max_hp * 0.3:
            action = random.choice(["attack", "dodge", "special"])
        elif engine.monster_hp < engine.monster_max_hp * 0.3:
            action = random.choice(["attack", "special"])
        else:
            action = random.choices(["attack", "special", "dodge"], weights=[5, 2, 1])[0]

        lines.append(f"**ターン {engine.turn + 1}**")
        lines.append(engine.pal_attack(action))

        if engine.is_over:
            break

        lines.append(engine.monster_attack())
        lines.append(engine.status_bar())
        lines.append("")

    if engine.pal_won:
        lines.append(f"## 🎉 勝利！ パルは{monster['name']}を倒した！")
        lines.append(f"ターン数: {engine.turn}")
    else:
        lines.append(f"## 💀 敗北… {monster['name']}に負けてしまった…")
        lines.append(f"ターン数: {engine.turn}")

    return lines, engine.pal_won


# ── Main ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Umwelt Battle RPG")
    parser.add_argument("--image", type=str, help="Input image path")
    parser.add_argument("--live", action="store_true", help="Use JetBot live camera")
    parser.add_argument("--emotion", type=str, default="curious", help="Pal's current emotion")
    parser.add_argument("--output-dir", type=str, default="/tmp", help="Output directory for images")
    parser.add_argument("--no-image", action="store_true", help="Skip battle image generation")
    args = parser.parse_args()

    # Get image
    if args.live:
        snap_url = "http://192.168.3.8:8554/snap"
        img_path = "/tmp/battle_snap.jpg"
        try:
            resp = urllib.request.urlopen(snap_url, timeout=5)
            with open(img_path, "wb") as f:
                f.write(resp.read())
            print(f"📸 JetBotスナップ取得: {img_path}")
        except Exception as e:
            print(f"❌ JetBot接続失敗: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.image:
        img_path = args.image
    else:
        print("--image or --live required", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(img_path):
        print(f"❌ 画像が見つかりません: {img_path}", file=sys.stderr)
        sys.exit(1)

    print("🔍 環世界を解析中...")
    scene = analyze_scene(img_path)
    print(f"📍 環境: {scene['environment']}")
    print(f"🎭 雰囲気: {scene['mood']}")
    print(f"⚠️ 危険度: {scene['danger_level']}/5")
    print()

    print("😼 モンスター生成中...")
    monster = generate_monster(scene)
    print(f"🐱 {monster['name']} ({monster['name_en']}) 出現！")
    print()

    # Battle
    pal = PalStats(emotion=args.emotion)
    battle_log, won = auto_battle(pal, monster, scene)

    for line in battle_log:
        print(line)
    print()

    # Generate battle image
    if not args.no_image:
        phase = "victory" if won else "defeat"
        ts = time.strftime("%Y-%m-%d-%H-%M-%S")
        out_path = f"{args.output_dir}/battle_{ts}.png"
        print(f"🎨 バトルシーン画像生成中...")
        media_line = generate_battle_image(scene, monster, phase, out_path)
        if media_line:
            print(media_line)

    # Output JSON summary
    summary = {
        "scene": scene,
        "monster": monster,
        "result": "victory" if won else "defeat",
        "pal_emotion": args.emotion,
        "pal_hp_remaining": pal.hp,
    }
    summary_path = f"{args.output_dir}/battle_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n📊 サマリー: {summary_path}")


if __name__ == "__main__":
    main()
