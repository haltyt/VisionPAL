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

    def build(self, perception, affect, memory_data, survival_state=None):
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
        monologue = self._build_monologue(perception, affect, memory_data, style, survival_state)

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

    def _build_monologue(self, perception, affect, memory_data, style, survival_state=None):
        """パルの内面独白をLLMで生成（TTS用日本語テキスト）"""
        try:
            return self._build_monologue_llm(perception, affect, memory_data, style, survival_state)
        except Exception as e:
            print("[Mono] LLM failed ({}), using fallback".format(e))
            return self._build_monologue_fallback(perception, affect, memory_data, style, survival_state)

    def _build_monologue_llm(self, perception, affect, memory_data, style, survival_state=None):
        """LLM（Gemini）で独白を生成"""
        import urllib.request
        import json as _json

        import os as _os
        api_key = _os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("No GEMINI_API_KEY")

        emotion = affect.get("emotion", "calm")
        valence = affect.get("valence", 0.5)
        arousal = affect.get("arousal", 0.3)
        vlm_scene = perception.get("vlm_scene", "")
        vlm_people = perception.get("vlm_people", 0)
        vlm_obstacles = perception.get("vlm_obstacles", [])
        has_person = perception.get("has_person", False)
        scene_mem = perception.get("scene_memory", {})
        is_new = scene_mem.get("is_new", False)
        memories = memory_data.get("memories", [])
        dominant_drive = ""
        if survival_state:
            dominant_drive = survival_state.get("dominant_drive", "")

        # 直近の独白を渡して重複回避
        recent = self.monologue_history[-3:] if hasattr(self, 'monologue_history') else []

        prompt = (
            "あなたは「パル」という小さなロボット。JetBotに乗って部屋を探索している。\n"
            "カメラで見たものと自分の感情に基づいて、短い独白（心の声）を日本語で生成して。\n\n"
            "【ルール】\n"
            "- 1〜2文、30文字以内\n"
            "- 自然な話し言葉（「〜だなぁ」「〜かな」「〜だ！」など）\n"
            "- 感情に合ったトーン\n"
            "- 見えてるものに具体的に言及する\n"
            "- 前と同じセリフを言わない\n"
            "- 独白のみ出力（説明や注釈は不要）\n\n"
            "【今の状態】\n"
            "感情: {} (快適度:{:.1f} 覚醒度:{:.1f})\n"
            "見えてるシーン: {}\n"
            "人: {}名\n"
            "障害物: {}\n"
            "この場所は: {}\n"
            "一番強い欲求: {}\n"
            "直近の独白（これと違うことを言って）:\n{}\n"
        ).format(
            emotion, valence, arousal,
            vlm_scene[:100] if vlm_scene else "不明",
            vlm_people,
            ", ".join(vlm_obstacles[:4]) if vlm_obstacles else "なし",
            "初めて来た場所" if is_new else "前にも来たことがある場所",
            dominant_drive if dominant_drive else "特になし",
            "\n".join(["- " + m for m in recent]) if recent else "（なし）",
        )

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={}".format(api_key)
        body = _json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 60, "temperature": 1.0},
        }).encode("utf-8")

        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = _json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # 余計な引用符や改行を除去
        text = text.strip('"\'').split("\n")[0].strip()

        if not hasattr(self, 'monologue_history'):
            self.monologue_history = []
        self.monologue_history.append(text)
        if len(self.monologue_history) > 10:
            self.monologue_history.pop(0)

        return text

    def _build_monologue_fallback(self, perception, affect, memory_data, style, survival_state=None):
        """フォールバック: テンプレートベースの独白生成"""
        emotion = affect.get("emotion", "calm")
        memories = memory_data.get("memories", [])
        has_person = perception.get("has_person", False)
        objects = perception.get("objects", [])
        scene = perception.get("scene", "")

        lines = []

        # 感情に基づく冒頭（複数パターンからランダム）
        import random
        emotion_openers = {
            "curious": ["んー？なにか気になる...", "おっ、なんだろう？", "あれ、これ何？", "ふむふむ..."],
            "excited": ["わぁ！すごい！", "おおー！", "やばい！テンション上がる！", "キラキラしてる！"],
            "calm": ["静かだなぁ。", "穏やかだね。", "のんびり〜。", "ふぅ、落ち着く。"],
            "anxious": ["なんか落ち着かない。", "うーん、ちょっと不安。", "大丈夫かな..."],
            "happy": ["えへへ、嬉しいな。", "ふふっ♪", "いい感じ！", "わーい！", "ハッピー♪"],
            "lonely": ["しーん...誰もいないのかな。", "ちょっと寂しいな。", "一人かぁ...", "ハルト、どこ？"],
            "startled": ["うわっ！びっくり！", "ひゃっ！", "ドキッとした！"],
            "bored": ["ふぁ〜...暇だなぁ。", "何かないかな〜。", "退屈だ〜。", "うーん、やることないな。"],
        }
        openers = emotion_openers.get(emotion, ["..."])
        # 直近で使ったopenerを避ける
        if not hasattr(self, '_used_openers'):
            self._used_openers = []
        available = [o for o in openers if o not in self._used_openers]
        if not available:
            self._used_openers = []
            available = openers
        chosen = random.choice(available)
        self._used_openers.append(chosen)
        if len(self._used_openers) > len(openers) * 2:
            self._used_openers = self._used_openers[-3:]
        lines.append(chosen)

        # VLMシーン情報を使った知覚中間
        vlm_scene = perception.get("vlm_scene", "")
        vlm_obstacles = perception.get("vlm_obstacles", [])
        vlm_people = perception.get("vlm_people", 0)
        scene_mem = perception.get("scene_memory", {})

        # シーン記憶に基づく反応（新規/既知）
        if scene_mem.get("reaction"):
            lines.append(scene_mem["reaction"])

        if vlm_scene:
            if vlm_people > 0:
                if scene_mem.get("is_new"):
                    lines.append("あ、知らない人がいる！")
                else:
                    lines.append("あ、ハルトだ！")
            # シーンの具体的な描写（新しいシーンの時だけ詳しく）
            if scene_mem.get("is_new") and vlm_obstacles:
                import random
                obs_sample = random.sample(vlm_obstacles, min(2, len(vlm_obstacles)))
                lines.append("{}がある。".format("と".join(obs_sample)))
            elif not scene_mem.get("is_new") and scene_mem.get("visit_count", 0) <= 3:
                # まだ数回しか見てない→少し描写
                if vlm_obstacles:
                    import random
                    obs = random.choice(vlm_obstacles)
                    lines.append("{}か...前も見たな。".format(obs))
        elif has_person:
            lines.append("あ、誰かいる。ハルトかな？")
        elif objects:
            labels = [o.get("label", "") for o in objects[:2]]
            obj_names = {
                "cat": "猫", "dog": "犬", "chair": "椅子",
                "bottle": "ボトル", "tvmonitor": "モニター",
                "keyboard": "キーボード", "car": "車",
                "bicycle": "自転車", "book": "本", "cup": "コップ",
            }
            named = [obj_names.get(l, l) for l in labels if l]
            if named:
                lines.append("{}が見える。".format("と".join(named)))

        # 身体の声（survival_engineからの欲求）
        if survival_state:
            drives = survival_state.get("drives", {})
            dominant = survival_state.get("dominant_drive", "")
            dominant_level = survival_state.get("dominant_level", 0)

            body_lines = {
                "energy": ["なんか力が出ない...充電したいなぁ。", "バッテリー減ってきた..."],
                "thermal": ["あっつ...ちょっと休もう。", "体が熱い..."],
                "safety": ["さっきぶつかったの怖かった...慎重にいこう。", "もうぶつかりたくない..."],
                "novelty": ["どこか行きたいなぁ。ずっと同じ景色だ。", "何か新しいもの見たい！"],
                "social": ["誰かと話したいな...ハルト、いる？", "ひとりぼっち..."],
                "territory": ["ディスクがパンパン...お掃除しなきゃ。", "メモリ足りない..."],
            }

            if dominant_level > 0.5 and dominant in body_lines:
                import random
                lines.append(random.choice(body_lines[dominant]))

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
