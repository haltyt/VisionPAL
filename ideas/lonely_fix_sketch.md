# Cognition lonely底張り付き修正案

## 問題
- lonely欲求が0.10-0.14で底張り付き、seek_social緊急度100%が連続
- 人検出しても social satisfy が走らない
- 独白が「寂しいなぁ」系ばかりになる

## 原因分析
1. `survival_engine.py` の `update_needs()` に人検出→social回復ロジックがない
2. `cognitive_loop.py` がVLM結果のpeople検出を survival_engine に渡してない
3. lonely の decay が他の欲求と同じペースで下がり続ける

## 修正案

### A. 人検出→social satisfy（最小修正）
```python
# cognitive_loop.py の VLM結果処理部分
if vlm_result.get('people_count', 0) > 0:
    survival_engine.satisfy_need('social', amount=0.3)
    # 人がいる間は decay を一時停止する案もあり
```

### B. social decay の文脈依存化
```python
# survival_engine.py
def update_needs(self, context):
    for need_name, need in self.needs.items():
        if need_name == 'social' and context.get('people_present'):
            # 人がいる時はdecayしない（むしろ微回復）
            need['value'] = min(1.0, need['value'] + 0.01)
        else:
            elapsed_hours = (now - last_update).total_seconds() / 3600
            need['value'] = max(0.0, need['value'] - need['decayPerHour'] * elapsed_hours)
```

### C. 独白の多様性改善
- lonely状態でも「探索する楽しさ」「発見の喜び」など別の感情を混ぜる
- monologue promptに「同じ感情を3回以上連続で表現しない」制約を追加
- temperature 0.9→1.1に上げて表現の幅を広げる

## 優先度
A > B > C（Aだけで大幅改善するはず）
