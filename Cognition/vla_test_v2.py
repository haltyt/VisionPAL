#!/usr/bin/env python3
"""AsyncVLA Pipeline Test v2
Edge層(CNN) + Cloud層(VLM+Survival Engine+LLM) の二層パイプラインをオフラインテスト。

Usage:
    python3 vla_test_v2.py --image /path/to/image.jpg
    python3 vla_test_v2.py --image /path/to/image.jpg --drives novelty=0.9,safety=0.3
    python3 vla_test_v2.py --image /path/to/image.jpg --blocked-prob 0.8  # Edge層シミュレーション
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from survival_engine import SurvivalEngine
from affect import Affect

# ─── VLM / LLM ──────────────────────────────────────────
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
    "あなたは自律ロボット「パル」です。AsyncVLA二層アーキテクチャで動いています。\n\n"
    "## Edge層（高速CNN、5ms）の判定\n{edge}\n\n"
    "## Cloud層（VLMシーン分析、5秒）\n{scene}\n\n"
    "## 欲求状態（Survival Engine）\n{drives}\n\n"
    "## 感情修飾\n{emotions}\n\n"
    "## ルール\n"
    "- Edge層がdanger/collisionならCloud層の提案より優先\n"
    "- 安全確認済みの場合のみ探索・社会行動を実行\n"
    "- 欲求が高い場合はその欲求を満たす行動を優先\n\n"
    "JSON形式で最終行動を決定:\n"
    '{{"action":"forward/stop/turn_left/turn_right/reverse/explore/retreat/idle",'
    '"speed":0.0-1.0,"duration_sec":0.5-3.0,'
    '"layer":"edge/cloud/hybrid","thought":"パルの内心独白（日本語1文）",'
    '"reason":"行動理由"}}'
)


def gemini_call(prompt, api_key, image_path=None, max_tokens=512):
    """Gemini API呼び出し"""
    parts = [{"text": prompt}]
    if image_path:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        ext = image_path.rsplit(".", 1)[-1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")
        parts.append({"inline_data": {"mime_type": mime, "data": img_data}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
    }
    url = GEMINI_URL.format(model=GEMINI_MODEL, key=api_key)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def bar(val, width=20):
    filled = int(val * width)
    return "█" * filled + "░" * (width - filled)


def main():
    parser = argparse.ArgumentParser(description="AsyncVLA Pipeline Test v2")
    parser.add_argument("--image", required=True)
    parser.add_argument("--drives", default="")
    parser.add_argument("--idle-sec", type=int, default=0)
    parser.add_argument("--blocked-prob", type=float, default=-1,
                        help="Edge層CNNのblocked確率をシミュレーション (0-1)")
    parser.add_argument("--no-action-llm", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY環境変数を設定してください")
        sys.exit(1)

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║     🧠 AsyncVLA Pipeline Test v2            ║")
    print("║     Edge (5ms) + Cloud (5-10s) 二層統合     ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # ═══ Edge層 ═══
    print("┌─────────────────────────────────────┐")
    print("│ 🛡️  EDGE LAYER (CNN, ~5ms)          │")
    print("└─────────────────────────────────────┘")

    if args.blocked_prob >= 0:
        blocked_prob = args.blocked_prob
        free_prob = 1.0 - blocked_prob
        print("  [シミュレーション] blocked={:.2f}, free={:.2f}".format(blocked_prob, free_prob))
    else:
        # 実際にはJetBot上でCNN推論するが、テストではVLMのdanger_levelで代替
        blocked_prob = 0.0
        free_prob = 1.0
        print("  [CNN未接続] VLMのdanger_levelで代替")

    edge_danger = blocked_prob > 0.5
    edge_collision = blocked_prob > 0.7
    print("  blocked  [{bar}] {val:.3f}{warn}".format(
        bar=bar(blocked_prob), val=blocked_prob,
        warn=" 🚨 COLLISION!" if edge_collision else (" ⚠️ DANGER" if edge_danger else " ✅ SAFE")))

    edge_decision = "pass"
    if edge_collision:
        edge_decision = "emergency_stop"
        print("  → Edge判定: 🛑 緊急停止（Cloud層をオーバーライド）")
    elif edge_danger:
        edge_decision = "slow_down"
        print("  → Edge判定: ⚠️ 減速＆警戒")
    else:
        print("  → Edge判定: ✅ 安全、Cloud層に委譲")
    print()

    # ═══ Cloud層 Step 1: Vision ═══
    print("┌─────────────────────────────────────┐")
    print("│ ☁️  CLOUD LAYER                      │")
    print("├─────────────────────────────────────┤")
    print("│ 📷 Step 1: VLM Scene Analysis       │")
    print("└─────────────────────────────────────┘")
    t0 = time.time()
    scene = gemini_call(VLM_PROMPT, api_key, image_path=args.image)
    print("  ({:.1f}秒)".format(time.time() - t0))
    print("  障害物: {}".format(scene.get("obstacles", [])))
    print("  人数: {}".format(scene.get("people", 0)))
    print("  概要: {}".format(scene.get("summary", "")))
    print("  危険度: {}".format(scene.get("danger_level", "?")))
    print("  VLM提案: {}".format(scene.get("suggested_action", "?")))
    print()

    # ═══ Cloud層 Step 2: Survival Engine ═══
    print("┌─────────────────────────────────────┐")
    print("│ 💓 Step 2: Survival Engine          │")
    print("└─────────────────────────────────────┘")
    engine = SurvivalEngine()

    if args.drives:
        for pair in args.drives.split(","):
            name, val = pair.split("=")
            if name in engine.drives:
                engine.drives[name].level = float(val)

    people = scene.get("people", 0)
    if people > 0:
        engine.drives["social"].satisfy(0.5)

    if args.idle_sec > 0:
        engine._process_body({"idle_sec": args.idle_sec})

    # Edge層の安全情報を注入
    if edge_collision:
        engine.drives["safety"].frustrate(0.5)
    elif edge_danger:
        engine.drives["safety"].frustrate(0.2)

    engine.tick()
    state = engine.get_state()

    for name, d in state["drives"].items():
        urgent = " 🚨" if d["urgent"] else ""
        print("  {n:10s} [{b}] {v:.3f}{u}".format(
            n=name, b=bar(d["level"]), v=d["level"], u=urgent))
    print("  支配的: {} ({:.3f})".format(state["dominant_drive"], state["dominant_level"]))
    print()

    # ═══ Cloud層 Step 3: Affect ═══
    print("┌─────────────────────────────────────┐")
    print("│ 🎭 Step 3: Emotion Modifiers        │")
    print("└─────────────────────────────────────┘")
    emotion_mods = engine.get_emotion_modifiers()
    if emotion_mods:
        for emo, val in emotion_mods.items():
            print("  {}: {:+.3f}".format(emo, val))
    else:
        print("  (修飾なし)")
    print()

    # ═══ Action Arbiter ═══
    print("┌─────────────────────────────────────┐")
    print("│ 🎯 ACTION ARBITER (二層統合)        │")
    print("└─────────────────────────────────────┘")

    # 優先度表示
    candidates = []
    if edge_collision:
        candidates.append(("Edge", "emergency_stop", 100))
    elif edge_danger:
        candidates.append(("Edge", "avoid", 60))

    urgent_drives = [(n, d) for n, d in engine.drives.items() if d.is_urgent()]
    for name, drive in urgent_drives:
        action_map = {
            "safety": ("retreat", 90),
            "thermal": ("cool_down", 80),
            "energy": ("seek_energy", 70),
            "novelty": ("explore", 40),
            "social": ("seek_social", 30),
            "territory": ("clean_space", 20),
        }
        if name in action_map:
            a, p = action_map[name]
            candidates.append(("Survival", a, p))

    vlm_action = scene.get("suggested_action", "")
    if vlm_action:
        candidates.append(("VLM", vlm_action, 10))

    candidates.sort(key=lambda x: x[2], reverse=True)
    print("  候補（優先度順）:")
    for src, act, pri in candidates:
        marker = " ← 採用" if candidates and (src, act, pri) == candidates[0] else ""
        print("    [{:>3d}] {}: {}{}".format(pri, src, act, marker))
    if not candidates:
        print("    [  0] idle")
    print()

    # ═══ LLM最終判断 ═══
    if not args.no_action_llm and edge_decision != "emergency_stop":
        print("┌─────────────────────────────────────┐")
        print("│ 🤖 LLM Final Decision               │")
        print("└─────────────────────────────────────┘")

        edge_info = {
            "blocked_prob": blocked_prob,
            "danger_zone": edge_danger,
            "collision": edge_collision,
            "decision": edge_decision,
        }
        drives_info = {n: {"level": round(d.level, 3), "urgent": d.is_urgent()}
                       for n, d in engine.drives.items()}

        t0 = time.time()
        action = gemini_call(
            ACTION_PROMPT.format(
                edge=json.dumps(edge_info, ensure_ascii=False, indent=2),
                scene=json.dumps(scene, ensure_ascii=False, indent=2),
                drives=json.dumps(drives_info, ensure_ascii=False, indent=2),
                emotions=json.dumps(emotion_mods, ensure_ascii=False, indent=2),
            ),
            api_key
        )
        print("  ({:.1f}秒)".format(time.time() - t0))
        print()
        print("  ╔════════════════════════════════════════╗")
        print("  ║ 行動: {:33s}║".format(action.get("action", "?")))
        print("  ║ 層:   {:33s}║".format(action.get("layer", "?")))
        print("  ║ 速度: {:33s}║".format(str(action.get("speed", 0))))
        print("  ║ 時間: {}秒{:s}║".format(action.get("duration_sec", 0),
              " " * (31 - len(str(action.get("duration_sec", 0))))))
        print("  ╚════════════════════════════════════════╝")
        print("  💭 「{}」".format(action.get("thought", "")))
        print("  📝 {}".format(action.get("reason", "")))
    elif edge_decision == "emergency_stop":
        print("  🛑 Edge層が緊急停止を発動 → LLM判断スキップ（安全最優先）")

    print()
    print("═" * 50)
    print("✅ AsyncVLA Pipeline Test v2 Complete")
    print("═" * 50)


if __name__ == "__main__":
    main()
