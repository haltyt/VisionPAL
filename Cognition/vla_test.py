#!/usr/bin/env python3
"""VLA (Vision-Language-Action) テスト
画像 → VLM解析 → Survival Engine → 行動決定 のパイプラインをオフラインでテスト。
MQTT不要、画像ファイルを直接入力。

Usage:
    python vla_test.py --image /path/to/image.jpg
    python vla_test.py --image /path/to/image.jpg --drives novelty=0.9,safety=0.3
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from survival_engine import SurvivalEngine, Drive
from scene_memory import SceneMemory
from affect import Affect


# ─── VLM (Gemini) ───────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

VLM_PROMPT = (
    "ロボットの目として画像を分析。全て日本語で返して。JSON形式。"
    '{"obstacles":["自然な日本語の説明"],"people":数,"summary":"日本語1文",'
    '"danger_level":"safe/caution/danger","suggested_action":"forward/stop/turn_left/turn_right/reverse",'
    '"reason":"行動理由を1文で"}'
)

ACTION_PROMPT = (
    "あなたは自律ロボット「パル」です。以下のセンサー情報と欲求状態から、次の行動を決定してください。\n\n"
    "## シーン分析\n{scene}\n\n"
    "## 欲求状態（0=満足, 1=緊急）\n{drives}\n\n"
    "## 感情状態\n{emotions}\n\n"
    "以下のJSON形式で回答:\n"
    '{{"action":"forward/stop/turn_left/turn_right/reverse/explore/retreat/idle",'
    '"speed":0.0-1.0,"duration_sec":0.5-3.0,'
    '"thought":"パルの内心の独白（日本語、1文）",'
    '"reason":"行動理由"}}'
)


def vlm_analyze(image_path, api_key):
    """画像をGemini VLMで解析"""
    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()

    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")

    payload = {
        "contents": [{
            "parts": [
                {"text": VLM_PROMPT},
                {"inline_data": {"mime_type": mime, "data": img_data}},
            ]
        }],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }

    url = GEMINI_URL.format(model=GEMINI_MODEL, key=api_key)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    print("[VLM] 画像解析中...")
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    elapsed = time.time() - t0

    text = result["candidates"][0]["content"]["parts"][0]["text"]
    # JSONブロック抽出
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    scene = json.loads(text.strip())
    print(f"[VLM] 解析完了 ({elapsed:.1f}秒)")
    return scene


def action_decide(scene, drives_state, emotion_state, api_key):
    """LLMで行動決定（VLA の Action 部分）"""
    scene_str = json.dumps(scene, ensure_ascii=False, indent=2)
    drives_str = json.dumps(drives_state, ensure_ascii=False, indent=2)
    emotion_str = json.dumps(emotion_state, ensure_ascii=False, indent=2)

    prompt = ACTION_PROMPT.format(scene=scene_str, drives=drives_str, emotions=emotion_str)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 256},
    }

    url = GEMINI_URL.format(model=GEMINI_MODEL, key=api_key)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    print("[Action] 行動決定中...")
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    elapsed = time.time() - t0

    text = result["candidates"][0]["content"]["parts"][0]["text"]
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    action = json.loads(text.strip())
    print(f"[Action] 決定完了 ({elapsed:.1f}秒)")
    return action


def main():
    parser = argparse.ArgumentParser(description="VLA Pipeline Test")
    parser.add_argument("--image", required=True, help="入力画像パス")
    parser.add_argument("--drives", default="", help="欲求初期値 (例: novelty=0.9,safety=0.3)")
    parser.add_argument("--idle-sec", type=int, default=0, help="アイドル秒数シミュレーション")
    parser.add_argument("--no-action-llm", action="store_true", help="LLM行動決定をスキップ")
    args = parser.parse_args()

    # APIキー
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY環境変数を設定してください")
        sys.exit(1)

    print("=" * 60)
    print("🐾 VLA Pipeline Test")
    print("=" * 60)
    print(f"📷 画像: {args.image}")
    print()

    # ═══ Step 1: Vision (VLM解析) ═══
    print("━" * 40)
    print("📷 Step 1: Vision (VLM Scene Analysis)")
    print("━" * 40)
    scene = vlm_analyze(args.image, api_key)
    print(json.dumps(scene, ensure_ascii=False, indent=2))
    print()

    # ═══ Step 2: Survival Engine (欲求計算) ═══
    print("━" * 40)
    print("💓 Step 2: Survival Engine (Drives)")
    print("━" * 40)
    engine = SurvivalEngine()
    engine.autonomous_actions = True

    # カスタム欲求設定
    if args.drives:
        for pair in args.drives.split(","):
            name, val = pair.split("=")
            if name in engine.drives:
                engine.drives[name].level = float(val)
                print(f"  [設定] {name} = {val}")

    # シーンデータを注入
    people = scene.get("people", 0)
    if people > 0:
        engine.drives["social"].satisfy(0.5)
        print(f"  [社会性] 人検出 ({people}人) → social satisfy 0.5")

    # アイドル時間シミュレーション
    if args.idle_sec > 0:
        body = {"idle_sec": args.idle_sec}
        engine._process_body(body)
        print(f"  [退屈] idle {args.idle_sec}秒 シミュレーション")

    # tick
    engine.tick()
    state = engine.get_state()

    for name, d in state["drives"].items():
        bar = "█" * int(d["level"] * 20) + "░" * (20 - int(d["level"] * 20))
        urgent = " 🚨" if d["urgent"] else ""
        print(f"  {name:10s} [{bar}] {d['level']:.3f}{urgent}")

    print(f"\n  支配的欲求: {state['dominant_drive']} ({state['dominant_level']:.3f})")
    print()

    # ═══ Step 3: Affect (感情計算) ═══
    print("━" * 40)
    print("🎭 Step 3: Affect (Emotion Modifiers)")
    print("━" * 40)
    affect = Affect()
    emotion_mods = engine.get_emotion_modifiers()
    if emotion_mods:
        for emo, val in emotion_mods.items():
            sign = "+" if val > 0 else ""
            print(f"  {emo}: {sign}{val:.3f}")
    else:
        print("  (修飾なし — 全欲求が低い)")

    # VLMのdanger_levelから感情を追加
    danger = scene.get("danger_level", "safe")
    if danger == "danger":
        emotion_mods["startled"] = emotion_mods.get("startled", 0) + 0.5
        print(f"  startled: +0.500 (danger detected)")
    elif danger == "caution":
        emotion_mods["anxious"] = emotion_mods.get("anxious", 0) + 0.2
        print(f"  anxious: +0.200 (caution)")
    print()

    # ═══ Step 4: Action Decision ═══
    print("━" * 40)
    print("🎯 Step 4: Action Decision")
    print("━" * 40)

    # Survival Engineの自律行動
    urgent_drives = [(n, d) for n, d in engine.drives.items() if d.is_urgent()]
    if urgent_drives:
        print("  [Survival] 緊急欲求あり:")
        for name, drive in urgent_drives:
            print(f"    → {name}: {drive.level:.3f} (threshold: {drive.threshold})")

    # VLMの提案アクション
    vlm_action = scene.get("suggested_action", "idle")
    vlm_reason = scene.get("reason", "")
    print(f"  [VLM提案] {vlm_action}: {vlm_reason}")

    # LLM行動決定
    if not args.no_action_llm:
        drives_for_llm = {n: {"level": d.level, "urgent": d.is_urgent()} for n, d in engine.drives.items()}
        action = action_decide(scene, drives_for_llm, emotion_mods, api_key)
        print()
        print("  ╔══════════════════════════════════╗")
        print(f"  ║ 行動: {action.get('action', '?'):26s} ║")
        print(f"  ║ 速度: {action.get('speed', 0):<26} ║")
        print(f"  ║ 時間: {action.get('duration_sec', 0)}秒{' ' * 23}║")
        print(f"  ╚══════════════════════════════════╝")
        print(f"  💭 「{action.get('thought', '')}」")
        print(f"  📝 理由: {action.get('reason', '')}")
    else:
        print(f"\n  [最終行動] VLM提案を採用: {vlm_action}")

    print()
    print("=" * 60)
    print("✅ VLA Pipeline Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
