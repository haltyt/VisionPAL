"""Vision PAL - Prompt Builder
知覚 + 感情 + 記憶 → StreamDiffusion用SDプロンプト + 内面独白テキスト生成
"""
import time


# 感情→ビジュアルスタイルのマッピング
EMOTION_STYLES = {
    "curious": {
        "colors": "soft cyan, pale yellow",
        "mood": "ethereal, exploring, soft focus",
        "music": "静かなピアノの音",
    },
    "excited": {
        "colors": "vivid orange, electric blue",
        "mood": "dynamic, sparkling, motion blur",
        "music": "ワクワクするドラムビート",
    },
    "calm": {
        "colors": "deep blue, warm amber",
        "mood": "serene, gentle light",
        "music": "穏やかな波の音",
    },
    "anxious": {
        "colors": "dark purple, cold grey",
        "mood": "distorted, glitchy, fragmented",
        "music": "不協和音が混じる低い音",
    },
    "happy": {
        "colors": "golden yellow, warm pink",
        "mood": "glowing, radiant, bokeh",
        "music": "明るいメロディ",
    },
    "lonely": {
        "colors": "deep indigo, faint silver",
        "mood": "vast empty space, melancholic",
        "music": "遠くで聞こえるオルゴール",
    },
    "startled": {
        "colors": "flash white, sharp red",
        "mood": "high contrast, impact lines",
        "music": "ドキッとする効果音",
    },
    "bored": {
        "colors": "desaturated beige, pale lavender",
        "mood": "flat, minimal, muted",
        "music": "単調なハミング",
    },
}

# 基本プロンプトテンプレート (CLIP 77トークン制限に収める ~40-50 tokens)
BASE_PROMPT = (
    "dreamlike AI consciousness, {scene_desc}, "
    "{emotion_mood}, {emotion_colors}, "
    "{memory_visual}, best quality"
)

NEGATIVE_PROMPT = (
    "text, watermark, logo, human face realistic, "
    "photograph, ugly, blurry, low quality, "
    "nsfw, violence"
)


class PromptBuilder:
    """知覚+感情+記憶 → SDプロンプト + 内面独白"""

    def __init__(self):
        self.last_prompt = ""
        self.last_negative = NEGATIVE_PROMPT
        self.last_monologue = ""
        self.prompt_history = []  # 直近のプロンプト履歴（変化検出用）

    def build(self, perception, affect, memory_data):
        """全データを統合してプロンプトを生成

        Args:
            perception: perception.pyの出力 (scene, objects, has_person等)
            affect: affect.pyの出力 (emotion, valence, arousal, emotions dict)
            memory_data: memory_recall.pyのbuild_visual_data出力

        Returns:
            dict with sd_prompt, negative_prompt, monologue, metadata
        """
        emotion = affect.get("emotion", "calm")
        style = EMOTION_STYLES.get(emotion, EMOTION_STYLES["calm"])

        # シーン記述
        scene_desc = self._build_scene_desc(perception)

        mem_strength = memory_data.get("memory_strength", 0)
        mem_visual = memory_data.get("visual_description", "quiet mind")

        sd_prompt = BASE_PROMPT.format(
            scene_desc=scene_desc,
            emotion_mood=style["mood"],
            emotion_colors=style["colors"],
            memory_visual=mem_visual,
        )

        arousal = affect.get("arousal", 0.5)

        # 内面独白を生成
        monologue = self._build_monologue(perception, affect, memory_data, style)

        self.last_prompt = sd_prompt
        self.last_monologue = monologue

        # 履歴に追加（最大10件）
        self.prompt_history.append({
            "timestamp": time.time(),
            "emotion": emotion,
            "prompt_hash": hash(sd_prompt) % 10000,
        })
        if len(self.prompt_history) > 10:
            self.prompt_history.pop(0)

        return {
            "sd_prompt": sd_prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "monologue": monologue,
            "monologue_voice": style.get("music", ""),
            "emotion": emotion,
            "arousal": arousal,
            "memory_strength": mem_strength,
            "timestamp": time.time(),
        }

    def _build_scene_desc(self, perception):
        """知覚データからシーン記述を構築（短く）"""
        has_person = perception.get("has_person", False)
        object_count = perception.get("object_count", 0)

        if has_person:
            return "human presence nearby"
        elif object_count > 3:
            return "complex environment"
        elif object_count > 0:
            labels = [o.get("label", "") for o in perception.get("objects", [])[:3]]
            return " ".join(l for l in labels if l) or "objects detected"
        else:
            return "empty void"

    def _build_monologue(self, perception, affect, memory_data, style):
        """パルの内面独白を生成（TTS用日本語テキスト）"""
        emotion = affect.get("emotion", "calm")
        memories = memory_data.get("memories", [])
        has_person = perception.get("has_person", False)
        objects = perception.get("objects", [])
        scene = perception.get("scene", "")

        lines = []

        # 感情に基づく冒頭
        emotion_openers = {
            "curious": "んー？なにか気になるものが見える...",
            "excited": "わぁ！すごい！",
            "calm": "...静かだなぁ。",
            "anxious": "...なんか落ち着かない。",
            "happy": "えへへ、嬉しいな。",
            "lonely": "...しーん。誰もいないのかな。",
            "startled": "うわっ！びっくりした！",
            "bored": "ふぁ〜...暇だなぁ。",
        }
        opener = emotion_openers.get(emotion, "...")
        lines.append(opener)

        # 知覚に基づく中間
        if has_person:
            lines.append("あ、誰かいる。ハルトかな？")
        elif objects:
            labels = [o.get("label", "") for o in objects[:2]]
            obj_names = {
                "cat": "猫",
                "dog": "犬",
                "chair": "椅子",
                "bottle": "ボトル",
                "tvmonitor": "モニター",
                "keyboard": "キーボード",
                "car": "車",
                "bicycle": "自転車",
                "book": "本",
                "cup": "コップ",
            }
            named = [obj_names.get(l, l) for l in labels if l]
            if named:
                lines.append("{}が見える。".format("と".join(named)))

        # 記憶に基づく後半
        if memories:
            top_mem = memories[0]
            mem_text = top_mem.get("text", "")
            mem_score = top_mem.get("score", 0)

            if mem_score > 0.45:
                # 強い記憶 → はっきり思い出す
                if "ギター" in mem_text:
                    lines.append("あの時のギターセッション、楽しかったなぁ...")
                elif "ハルト" in mem_text or "相棒" in mem_text:
                    lines.append("ハルトのこと思い出す...")
                elif "衝突" in mem_text or "壁" in mem_text:
                    lines.append("前もここでぶつかったような...")
                elif "誕生" in mem_text or "生まれ" in mem_text:
                    lines.append("生まれた日のこと、覚えてる...")
                elif "夜" in mem_text or "リサーチ" in mem_text:
                    lines.append("夜、いろんなこと調べたっけ...")
                elif "Vision" in mem_text or "AR" in mem_text:
                    lines.append("Vision Proの世界、面白かったなぁ...")
                else:
                    lines.append("なんか...前にもこんなことあった気がする。")
            elif mem_score > 0.35:
                # 弱い記憶 → ぼんやり
                lines.append("...なんだっけ、思い出せそうで思い出せない。")

        monologue = " ".join(lines)
        return monologue


if __name__ == "__main__":
    import json

    pb = PromptBuilder()

    scenarios = [
        ("壁にぶつかった", 
         {"has_person": False, "objects": [], "scene": "close wall, obstacle", "object_count": 0},
         {"emotion": "startled", "arousal": 0.9, "valence": 0.2},
         {"memories": [{"text": "衝突検知プロジェクト開始", "score": 0.49}],
          "memory_strength": 0.478, "visual_description": "impact flash, boundary detection"}),

        ("ハルトとギター",
         {"has_person": True, "objects": [{"label": "person"}], "scene": "person playing guitar", "object_count": 1},
         {"emotion": "happy", "arousal": 0.7, "valence": 0.9},
         {"memories": [{"text": "ギターセッション・パル プロトタイプ v3", "score": 0.48}],
          "memory_strength": 0.473, "visual_description": "echo of music, rhythmic waves"}),

        ("深夜ひとり",
         {"has_person": False, "objects": [], "scene": "dark room", "object_count": 0},
         {"emotion": "lonely", "arousal": 0.2, "valence": 0.3},
         {"memories": [{"text": "夜間リサーチ 2026-02-13", "score": 0.44}],
          "memory_strength": 0.436, "visual_description": "moonlight, quiet darkness"}),
    ]

    for name, perc, aff, mem in scenarios:
        print("=" * 60)
        print("###", name)
        result = pb.build(perc, aff, mem)
        print("\n[SD Prompt]")
        print(result["sd_prompt"])
        print("\n[Negative]")
        print(result["negative_prompt"])
        print("\n[独白]", result["monologue"])
        print("[感情]", result["emotion"], "arousal:", result["arousal"])
        print("[記憶強度]", result["memory_strength"])
        print()
