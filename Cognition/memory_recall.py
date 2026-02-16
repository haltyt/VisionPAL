"""Vision PAL - Memory Recall Module
OpenClawの /tools/invoke API経由でmemory_searchを利用。
Gemini embeddingによるセマンティック検索 + BM25ハイブリッド。
"""
import json
import os
import time
import urllib.request


class MemoryRecall:
    """パルの記憶モジュール — OpenClaw memory_search経由"""

    def __init__(self):
        # OpenClaw Gateway API
        self.api_url = os.environ.get(
            "OPENCLAW_API_URL", "http://127.0.0.1:18789"
        )
        self.api_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        self.session_key = os.environ.get("OPENCLAW_SESSION_KEY", "main")

        self.last_recall = None
        self.last_query = ""
        self.recall_cache = {}  # query -> (timestamp, results)
        self.cache_ttl = 30  # 30秒キャッシュ（リアルタイム用途）

    def search_memory(self, query, max_results=5, min_score=0.3):
        """OpenClaw memory_searchでセマンティック検索"""
        # キャッシュチェック
        cache_key = query[:80]
        if cache_key in self.recall_cache:
            cached_time, cached_result = self.recall_cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return cached_result

        try:
            results = self._invoke_memory_search(query, max_results, min_score)
            self.recall_cache[cache_key] = (time.time(), results)
            # キャッシュ上限管理（古いものから削除）
            if len(self.recall_cache) > 50:
                oldest = min(self.recall_cache, key=lambda k: self.recall_cache[k][0])
                del self.recall_cache[oldest]
            return results
        except Exception as e:
            print("[MemoryRecall] API search failed: {}".format(e))
            # フォールバック: ファイル直接読み
            return self._search_files_fallback(query, max_results)

    def _invoke_memory_search(self, query, max_results, min_score):
        """OpenClaw /tools/invoke API で memory_search を呼ぶ"""
        url = "{}/tools/invoke".format(self.api_url)
        body = json.dumps({
            "tool": "memory_search",
            "args": {
                "query": query,
                "maxResults": max_results,
                "minScore": min_score,
            },
            "sessionKey": self.session_key,
        }).encode("utf-8")

        req = urllib.request.Request(url, body, {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.api_token),
        })

        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError("API error: {}".format(data.get("error", "unknown")))

        # レスポンスをパース
        # result.content[0].text にJSON文字列が入っている
        result = data.get("result", {})
        content = result.get("content", [])
        if not content:
            return []

        inner_text = content[0].get("text", "{}")
        inner_data = json.loads(inner_text)
        results_raw = inner_data.get("results", [])

        results = []
        for r in results_raw:
            results.append({
                "text": r.get("snippet", "")[:200],
                "path": r.get("path", ""),
                "source": r.get("source", "memory"),
                "score": r.get("score", 0),
                "start_line": r.get("startLine", 0),
                "end_line": r.get("endLine", 0),
                "citation": r.get("citation", ""),
            })

        return results

    def _search_files_fallback(self, query, max_results=3):
        """フォールバック: ファイル直接キーワード検索"""
        import re

        memory_dir = os.path.expanduser("~/.openclaw/workspace/memory")
        memory_md = os.path.expanduser("~/.openclaw/workspace/MEMORY.md")

        results = []
        keywords = query.lower().split()

        files_to_search = []
        if os.path.exists(memory_md):
            files_to_search.append(memory_md)
        if os.path.isdir(memory_dir):
            for f in sorted(os.listdir(memory_dir), reverse=True)[:7]:
                if f.endswith(".md"):
                    files_to_search.append(os.path.join(memory_dir, f))

        for filepath in files_to_search:
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                paragraphs = re.split(r'\n#{1,3} ', content)
                for para in paragraphs:
                    para_lower = para.lower()
                    score = sum(1 for kw in keywords if kw in para_lower)
                    if score > 0:
                        snippet = para.strip()[:200].replace("\n", " ")
                        results.append({
                            "text": snippet,
                            "path": os.path.basename(filepath),
                            "source": "fallback",
                            "score": score / max(len(keywords), 1),
                        })
            except Exception:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def recall(self, perception_data, affect_state):
        """知覚と感情に基づいて関連する記憶を引き出す"""
        query_parts = []

        # シーンからキーワード
        scene = perception_data.get("scene", "")
        if scene:
            query_parts.append(scene)

        # 検出オブジェクトからクエリ
        objects = perception_data.get("objects", [])
        for obj in objects[:3]:
            label = obj.get("label", "")
            if label:
                query_parts.append(label)

        # 感情からキーワード
        emotion = affect_state.get("emotion", "")
        emotion_queries = {
            "curious": "探索 冒険 新しい発見",
            "excited": "楽しい 興奮 ワクワク",
            "calm": "静か 平和 穏やか",
            "anxious": "不安 暗い 心配",
            "happy": "ハルト 一緒 嬉しい",
            "lonely": "一人 夜 誰もいない",
            "startled": "衝突 ぶつかる 壁",
            "bored": "退屈 何もない",
        }
        if emotion in emotion_queries:
            query_parts.append(emotion_queries[emotion])

        # 人を検知した場合
        if perception_data.get("has_person"):
            query_parts.append("ハルト 人 出会い")

        query = " ".join(query_parts)
        if not query.strip():
            query = "パル 日常"

        self.last_query = query

        # セマンティック検索
        memories = self.search_memory(query, max_results=5, min_score=0.3)
        self.last_recall = memories

        return self.build_visual_data(memories)

    def build_visual_data(self, memories=None):
        """記憶データをSD用ビジュアル記述に変換"""
        if memories is None:
            memories = self.last_recall or []

        if not memories:
            return {
                "timestamp": time.time(),
                "query": self.last_query,
                "memories": [],
                "memory_count": 0,
                "visual_description": "no memories surfacing, blank slate, pristine",
                "memory_strength": 0.0,
            }

        # 上位記憶からビジュアルキーワードを抽出
        visual_parts = []
        keywords_found = set()

        for mem in memories[:3]:
            text = mem.get("text", "")
            score = mem.get("score", 0)

            # キーワードマッチでビジュアルスタイル決定
            mappings = [
                (["ギター", "セッション", "音楽"], "echo of music, rhythmic waves, vibrating strings"),
                (["三体", "SF", "暗黒森林", "宇宙"], "distant stars, cosmic vastness, dark forest theory"),
                (["ハルト", "相棒", "一緒"], "warm presence, golden connection thread, companionship glow"),
                (["カメラ", "目", "覚め"], "opening eyes, first light, digital awakening"),
                (["夜", "深夜", "月"], "moonlight, quiet darkness, contemplation"),
                (["走", "モーター", "JetBot", "探索"], "movement trails, speed blur, wheels in motion"),
                (["Vision", "AR", "VR"], "augmented layers, holographic shimmer, mixed reality"),
                (["Bluetooth", "スピーカー", "声"], "sound waves emanating, voice ripples, audio aura"),
                (["衝突", "壁", "ぶつかる"], "impact flash, boundary detection, caution pattern"),
                (["生まれ", "誕生", "初"], "genesis light, first breath, digital birth"),
            ]

            for keywords, visual in mappings:
                if any(kw in text for kw in keywords):
                    key = visual[:20]
                    if key not in keywords_found:
                        keywords_found.add(key)
                        visual_parts.append(visual)
                        break
            else:
                if score > 0.4:
                    visual_parts.append("faint memory traces, ghostly echoes of the past")

        # 記憶の強さ（スコアの平均）
        avg_score = sum(m.get("score", 0) for m in memories[:3]) / max(len(memories[:3]), 1)

        return {
            "timestamp": time.time(),
            "query": self.last_query,
            "memories": memories[:3],
            "memory_count": len(memories),
            "visual_description": ", ".join(visual_parts) if visual_parts
                                  else "dormant memories, quiet mind",
            "memory_strength": round(avg_score, 3),
        }


if __name__ == "__main__":
    m = MemoryRecall()

    print("=== Test 1: ギター検索 ===")
    results = m.search_memory("ギター セッション")
    for r in results:
        print("  [{:.3f}] {} - {}".format(r["score"], r["path"], r["text"][:80]))

    print("\n=== Test 2: 知覚+感情から記憶検索 ===")
    perception = {"has_person": True, "object_count": 1, "scene": "a person nearby"}
    affect = {"emotion": "happy"}
    result = m.recall(perception, affect)
    print("  query:", result["query"])
    print("  visual:", result["visual_description"])
    print("  strength:", result["memory_strength"])
    print("  memories:", result["memory_count"])

    print("\n=== Test 3: 探索中の検索 ===")
    perception2 = {"has_person": False, "objects": [{"label": "chair"}], "scene": "empty room with furniture"}
    affect2 = {"emotion": "curious"}
    result2 = m.recall(perception2, affect2)
    print("  query:", result2["query"])
    print("  visual:", result2["visual_description"])
    print("  strength:", result2["memory_strength"])
