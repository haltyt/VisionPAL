#!/usr/bin/env python3
"""Vision PAL - Effect Generator
感情+シーン情報からVision Pro用のビジュアルエフェクトパラメータを生成する。
Gemini flash-liteでエフェクトを選択し、JSONでMQTT publishする。
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

# Gemini API設定
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

# エフェクトパターン辞書（Vision Pro側と同期する）
EFFECT_PATTERNS = {
    "particles": [
        "sparkles",    # キラキラ光の粒子
        "fireflies",   # ホタルの光
        "snowfall",    # 雪・粉塵
        "bubbles",     # 泡
        "embers",      # 残り火
        "storm",       # 嵐の粒子
        "petals",      # 花びら
        "dust",        # 塵
        "stars",       # 星
        "rain",        # 雨粒
    ],
    "postProcess": [
        "warmGlow",    # 暖色グロー
        "coolFog",     # 寒色フォグ
        "vignette",    # ビネット
        "chromatic",   # 色収差
        "ripple",      # 波紋
        "blur",        # ボケ
        "none",        # なし
    ],
}

PROMPT_TEMPLATE = """あなたはAIロボット「パル」の感情をビジュアルエフェクトに変換するシステムです。
パルの現在の状態からVision Pro ARエフェクトのパラメータをJSON形式で返してください。

## パルの状態
- 感情: {emotion}
- valence(快-不快): {valence:.2f} (-1〜1)
- arousal(覚醒度): {arousal:.2f} (0〜1)
- シーン: {scene}
- 人数: {people}

## 使えるパーティクルタイプ
sparkles(キラキラ), fireflies(ホタル), snowfall(雪), bubbles(泡), embers(残り火), storm(嵐), petals(花びら), dust(塵), stars(星), rain(雨)

## 使えるポストプロセス
warmGlow(暖色), coolFog(寒色霧), vignette(周辺暗), chromatic(色収差), ripple(波紋), blur(ボケ), none(なし)

## 出力JSON形式（この形式のみ、説明文不要）
{{
  "particles": {{
    "type": "sparkles",
    "density": 0.5,
    "speed": 1.0,
    "color": [1.0, 0.9, 0.4, 0.7],
    "size": 0.02,
    "gravity": -0.1,
    "spread": 1.0
  }},
  "postProcess": {{
    "type": "warmGlow",
    "intensity": 0.5,
    "color": [1.0, 0.95, 0.8]
  }},
  "ambient": {{
    "colorShift": [0.0, 0.0, 0.0],
    "brightness": 1.0,
    "fog": 0.0
  }}
}}

ルール:
- density: 0.0-1.0（パーティクルの密度）
- speed: 0.1-3.0（動きの速さ）
- color: [R,G,B,A] 0.0-1.0
- size: 0.005-0.1（パーティクルサイズ）
- gravity: -1.0〜1.0（負=浮く、正=落ちる）
- spread: 0.1-3.0（拡散範囲）
- intensity: 0.0-1.0
- fog: 0.0-1.0（霧の濃さ）
- brightness: 0.5-1.5
- 感情に合った色と動きを選んで。happyなら暖色キラキラ、sadなら寒色の塵、など。
- JSON以外は出力しないで。
"""


def get_api_key():
    """GEMINI_API_KEYを取得"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    try:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                import json as _json
                cfg = _json.load(f)
            key = cfg.get("skills", {}).get("entries", {}).get(
                "nano-banana-pro", {}).get("env", {}).get("GEMINI_API_KEY", "")
            if key:
                return key
    except Exception:
        pass
    return ""


def generate_effect(emotion, valence, arousal, scene, people, api_key):
    """Gemini flash-liteでエフェクトパラメータを生成"""
    prompt = PROMPT_TEMPLATE.format(
        emotion=emotion,
        valence=valence,
        arousal=arousal,
        scene=scene or "不明",
        people=people,
    )

    url = GEMINI_URL.format(model=GEMINI_MODEL, key=api_key)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.8,
            "maxOutputTokens": 512,
        },
    }).encode("utf-8")

    req = urllib.request.Request(url, body, {
        "Content-Type": "application/json",
    })

    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("[Effect] Gemini request failed: {}".format(e))
        return None, 0

    elapsed = time.time() - t0

    # レスポンスからJSONを取得
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        effect = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        # 複数JSON対策: 最初の{}ブロックを抽出
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            start = text.index("{")
            depth = 0
            end = start
            for i, c in enumerate(text[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            effect = json.loads(text[start:end])
        except Exception:
            print("[Effect] Parse failed: {}".format(e))
            return None, elapsed

    # バリデーション: パーティクルタイプが辞書にあるか
    particles = effect.get("particles", {})
    ptype = particles.get("type", "sparkles")
    if ptype not in EFFECT_PATTERNS["particles"]:
        particles["type"] = "sparkles"

    pp = effect.get("postProcess", {})
    pptype = pp.get("type", "none")
    if pptype not in EFFECT_PATTERNS["postProcess"]:
        pp["type"] = "none"

    return effect, elapsed


def get_fallback_effect(emotion, valence, arousal):
    """LLM失敗時のフォールバック（ルールベース）"""
    effects = {
        "happy": {
            "particles": {"type": "sparkles", "density": 0.7, "speed": 1.2,
                          "color": [1.0, 0.9, 0.3, 0.8], "size": 0.02,
                          "gravity": -0.2, "spread": 1.5},
            "postProcess": {"type": "warmGlow", "intensity": 0.4,
                            "color": [1.0, 0.95, 0.85]},
            "ambient": {"colorShift": [0.05, 0.03, 0.0],
                        "brightness": 1.1, "fog": 0.0},
        },
        "calm": {
            "particles": {"type": "fireflies", "density": 0.3, "speed": 0.5,
                          "color": [0.4, 0.9, 0.6, 0.6], "size": 0.015,
                          "gravity": -0.05, "spread": 2.0},
            "postProcess": {"type": "none", "intensity": 0.0,
                            "color": [1.0, 1.0, 1.0]},
            "ambient": {"colorShift": [0.0, 0.02, 0.01],
                        "brightness": 1.0, "fog": 0.0},
        },
        "sad": {
            "particles": {"type": "dust", "density": 0.4, "speed": 0.3,
                          "color": [0.5, 0.5, 0.7, 0.5], "size": 0.01,
                          "gravity": 0.1, "spread": 1.0},
            "postProcess": {"type": "vignette", "intensity": 0.6,
                            "color": [0.3, 0.3, 0.5]},
            "ambient": {"colorShift": [-0.05, -0.03, 0.05],
                        "brightness": 0.85, "fog": 0.2},
        },
        "lonely": {
            "particles": {"type": "snowfall", "density": 0.3, "speed": 0.4,
                          "color": [0.7, 0.8, 1.0, 0.5], "size": 0.012,
                          "gravity": 0.15, "spread": 2.0},
            "postProcess": {"type": "coolFog", "intensity": 0.5,
                            "color": [0.7, 0.8, 1.0]},
            "ambient": {"colorShift": [-0.03, 0.0, 0.05],
                        "brightness": 0.9, "fog": 0.3},
        },
        "bored": {
            "particles": {"type": "embers", "density": 0.2, "speed": 0.3,
                          "color": [0.8, 0.4, 0.2, 0.4], "size": 0.008,
                          "gravity": -0.05, "spread": 1.0},
            "postProcess": {"type": "blur", "intensity": 0.2,
                            "color": [0.9, 0.9, 0.9]},
            "ambient": {"colorShift": [0.0, 0.0, 0.0],
                        "brightness": 0.95, "fog": 0.1},
        },
        "curious": {
            "particles": {"type": "bubbles", "density": 0.5, "speed": 0.8,
                          "color": [0.3, 0.8, 1.0, 0.6], "size": 0.025,
                          "gravity": -0.3, "spread": 1.5},
            "postProcess": {"type": "chromatic", "intensity": 0.3,
                            "color": [1.0, 1.0, 1.0]},
            "ambient": {"colorShift": [0.0, 0.02, 0.05],
                        "brightness": 1.05, "fog": 0.0},
        },
        "excited": {
            "particles": {"type": "stars", "density": 0.9, "speed": 2.0,
                          "color": [1.0, 0.8, 0.0, 0.9], "size": 0.03,
                          "gravity": -0.4, "spread": 2.5},
            "postProcess": {"type": "warmGlow", "intensity": 0.6,
                            "color": [1.0, 0.9, 0.7]},
            "ambient": {"colorShift": [0.1, 0.05, 0.0],
                        "brightness": 1.2, "fog": 0.0},
        },
    }
    return effects.get(emotion, effects["calm"])


class EffectGenerator:
    """感情→エフェクトパラメータ生成器"""

    def __init__(self, use_llm=True):
        self.api_key = get_api_key()
        self.use_llm = use_llm and bool(self.api_key)
        self.last_effect = None
        self.last_emotion = None
        self.generation_count = 0

        if self.use_llm:
            print("[Effect] LLM mode (Gemini flash-lite)")
        else:
            print("[Effect] Fallback mode (rule-based)")

    def generate(self, emotion, valence, arousal, scene="", people=0):
        """エフェクト生成（感情変化時に呼ぶ）"""
        # LLMモード
        if self.use_llm:
            effect, elapsed = generate_effect(
                emotion, valence, arousal, scene, people, self.api_key
            )
            if effect:
                self.generation_count += 1
                self.last_effect = effect
                self.last_emotion = emotion
                print("[Effect] #{} LLM {:.1f}s | {} → {} + {}".format(
                    self.generation_count, elapsed, emotion,
                    effect.get("particles", {}).get("type", "?"),
                    effect.get("postProcess", {}).get("type", "?"),
                ))
                return effect

        # フォールバック
        effect = get_fallback_effect(emotion, valence, arousal)
        self.last_effect = effect
        self.last_emotion = emotion
        self.generation_count += 1
        print("[Effect] #{} fallback | {} → {} + {}".format(
            self.generation_count, emotion,
            effect.get("particles", {}).get("type", "?"),
            effect.get("postProcess", {}).get("type", "?"),
        ))
        return effect


# テスト用
if __name__ == "__main__":
    gen = EffectGenerator(use_llm=True)

    test_cases = [
        ("happy", 0.9, 0.6, "部屋で男性がスマホを操作している", 1),
        ("lonely", 0.2, 0.2, "誰もいない暗い部屋", 0),
        ("curious", 0.6, 0.7, "窓の外に猫が見える", 0),
        ("sad", 0.1, 0.3, "雨が降っている窓", 0),
    ]

    for emotion, val, aro, scene, ppl in test_cases:
        print("\n--- {} ---".format(emotion))
        effect = gen.generate(emotion, val, aro, scene, ppl)
        print(json.dumps(effect, indent=2, ensure_ascii=False))
