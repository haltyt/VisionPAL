"""Vision PAL - Scene Memory
シーンを記憶し、新規/既知を判定する。
新しいシーン→好奇心、既知のシーン→既知感をaffect/survivalに返す。
"""
import time
import json
import re
from collections import Counter


class SceneMemory:
    """シーンの短期・中期記憶"""

    def __init__(self, max_scenes=100, similarity_threshold=0.45):
        self.scenes = []  # [{summary, keywords, first_seen, last_seen, count, reaction}]
        self.max_scenes = max_scenes
        self.similarity_threshold = similarity_threshold
        self.last_scene_id = -1  # 直前のシーンindex

    def _extract_keywords(self, summary):
        """シーンサマリーからキーワードを抽出（N-gram + 名詞的パターン）"""
        if not summary:
            return set()

        # ストップワード（助詞、接続詞、汎用動詞、VLM定型表現）
        stop = {
            'が', 'の', 'に', 'を', 'は', 'で', 'と', 'も', 'から', 'まで',
            'より', 'て', 'た', 'だ', 'な', 'い', 'よう', 'こと', 'もの',
            'ている', 'している', 'されている', 'いる', 'ある', 'おり',
            'ない', 'する', 'なる', 'れる', 'られる', 'です', 'ます',
            'the', 'a', 'an', 'is', 'are', 'in', 'on', 'at', 'to',
            '画面', '表示', '見える', '映って', 'には', 'ように', '表示されて',
            'そして', 'また', 'その', 'この', 'ここ', 'それ', 'これ',
        }

        keywords = set()

        # 1. 区切りでトークン分割
        tokens = re.split(r'[、。,.\s　（）()「」\-/\n]', summary)
        for t in tokens:
            t = t.strip()
            if t and t not in stop and len(t) >= 2:
                keywords.add(t)

        # 2. 2-gram, 3-gramも追加（日本語は形態素解析なしでも部分一致で効く）
        clean = re.sub(r'[、。,.\s　（）()「」\-/\n]', '', summary)
        for n in (2, 3, 4):
            for i in range(len(clean) - n + 1):
                gram = clean[i:i+n]
                # 助詞だけのgramは除外
                if gram not in stop and not all(c in 'がのにをはでともからまで' for c in gram):
                    keywords.add(gram)

        # 3. 重要な名詞パターンを抽出（漢字2文字以上の連続）
        kanji_pattern = re.findall(r'[\u4e00-\u9fff]{2,}', summary)
        keywords |= set(kanji_pattern)

        # 4. カタカナ語を抽出
        katakana_pattern = re.findall(r'[\u30a0-\u30ff]{2,}', summary)
        keywords |= set(katakana_pattern)

        return keywords

    def _similarity(self, kw1, kw2):
        """2つのキーワードセットのJaccard類似度"""
        if not kw1 or not kw2:
            return 0.0
        intersection = kw1 & kw2
        union = kw1 | kw2
        return len(intersection) / len(union) if union else 0.0

    def _find_similar(self, keywords):
        """記憶から類似シーンを探す。返り値: (index, similarity) or (-1, 0)"""
        best_idx = -1
        best_sim = 0.0
        for i, scene in enumerate(self.scenes):
            sim = self._similarity(keywords, scene["keywords"])
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        return best_idx, best_sim

    def observe(self, vlm_summary, vlm_obstacles=None, vlm_people=0):
        """シーンを観察し、新規/既知を判定

        Returns:
            dict: {
                is_new: bool,          # 新しいシーンか
                familiarity: float,    # 既知度 0.0-1.0
                visit_count: int,      # 見た回数
                novelty_delta: float,  # novelty欲求への影響 (正=満たす, 負=高める)
                reaction: str,         # 独白に使える反応テキスト
                scene_desc: str,       # シーン要約
            }
        """
        if not vlm_summary:
            return {
                "is_new": False, "familiarity": 0.0, "visit_count": 0,
                "novelty_delta": 0.0, "reaction": "", "scene_desc": "",
            }

        now = time.time()
        keywords = self._extract_keywords(vlm_summary)
        if vlm_obstacles:
            for obs in vlm_obstacles:
                keywords |= self._extract_keywords(obs)

        idx, similarity = self._find_similar(keywords)

        if similarity >= self.similarity_threshold:
            # 既知のシーン
            scene = self.scenes[idx]
            scene["last_seen"] = now
            scene["count"] += 1
            scene["keywords"] = scene["keywords"] | keywords  # キーワード拡張

            is_same_as_last = (idx == self.last_scene_id)
            self.last_scene_id = idx

            # 見た回数で反応を変える
            count = scene["count"]
            if is_same_as_last and count > 5:
                reaction = "ずっと同じ景色...どこか行きたい。"
                novelty_delta = -0.05  # 退屈が増す
            elif count > 10:
                reaction = "ここ、もう{}回目だ。".format(count)
                novelty_delta = -0.03
            elif count > 3:
                reaction = "あ、ここ見たことある。"
                novelty_delta = -0.01
            else:
                reaction = "ここ、前にも来たような..."
                novelty_delta = 0.0

            return {
                "is_new": False,
                "familiarity": similarity,
                "visit_count": count,
                "novelty_delta": novelty_delta,
                "reaction": reaction,
                "scene_desc": vlm_summary,
            }
        else:
            # 新しいシーン！
            new_scene = {
                "summary": vlm_summary[:200],
                "keywords": keywords,
                "first_seen": now,
                "last_seen": now,
                "count": 1,
                "people": vlm_people,
            }
            self.scenes.append(new_scene)
            self.last_scene_id = len(self.scenes) - 1

            # 上限超えたら古いのを削除
            if len(self.scenes) > self.max_scenes:
                self.scenes.pop(0)
                self.last_scene_id = max(0, self.last_scene_id - 1)

            # 新しいシーンの詳細度で反応を変える
            if vlm_people > 0:
                reaction = "おっ！新しい場所に人がいる！"
                novelty_delta = 0.4
            elif len(keywords) > 5:
                reaction = "わぁ、ここ初めて！いろんなものがある！"
                novelty_delta = 0.3
            elif len(keywords) > 2:
                reaction = "お、ここ初めてだ。"
                novelty_delta = 0.2
            else:
                reaction = "新しい景色...？"
                novelty_delta = 0.1

            return {
                "is_new": True,
                "familiarity": 0.0,
                "visit_count": 1,
                "novelty_delta": novelty_delta,
                "reaction": reaction,
                "scene_desc": vlm_summary,
            }

    def get_stats(self):
        """シーン記憶の統計"""
        if not self.scenes:
            return {"total": 0, "unique": 0, "most_visited": None}

        most = max(self.scenes, key=lambda s: s["count"])
        return {
            "total": sum(s["count"] for s in self.scenes),
            "unique": len(self.scenes),
            "most_visited": {
                "summary": most["summary"][:60],
                "count": most["count"],
            },
        }

    def get_recent(self, n=5):
        """最近見たシーンを返す"""
        sorted_scenes = sorted(self.scenes, key=lambda s: s["last_seen"], reverse=True)
        return [
            {"summary": s["summary"][:80], "count": s["count"],
             "first_seen": s["first_seen"], "last_seen": s["last_seen"]}
            for s in sorted_scenes[:n]
        ]


if __name__ == "__main__":
    sm = SceneMemory()

    # テスト
    scenes = [
        "部屋で眼鏡をかけた男性が座っている。",
        "部屋で眼鏡をかけた男性が椅子に座っている。",  # 類似
        "画面にアニメキャラクターが表示されている。",   # 新しい
        "室内でスライドドア、天井の照明、マイクスタンドが見える。",  # 新しい
        "部屋で眼鏡の男性が座っている。",  # 類似（最初のに）
        "画面にアニメキャラクターと日本語テキストが表示。",  # 類似（3番目に）
    ]

    for s in scenes:
        result = sm.observe(s)
        new_mark = "🆕" if result["is_new"] else "👀"
        print("{} {} | fam:{:.2f} visits:{} | {}".format(
            new_mark, s[:40], result["familiarity"],
            result["visit_count"], result["reaction"]))

    print("\n📊 Stats:", json.dumps(sm.get_stats(), ensure_ascii=False, indent=2))
