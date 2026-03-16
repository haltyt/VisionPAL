# Survival Engine v3 — Mortal Agent Architecture

## 設計理念
Horibe & Yoshida (2024, arXiv:2411.12304) の「ホメオスタシスから世界モデルが創発する」仮説に基づき、
Survival Engine を v2（5欲求手動設計 + HumanLM状態次元）から v3（単一エネルギー + 行動効率学習）に進化させる。

## v2 → v3 の変更点

### 廃止したもの
- 5つの固定欲求（curiosity/social/creative/reflection/expression）の個別value
- personality weight（欲求ごとの重み）
- decayPerHour（欲求ごとの減衰率）
- 固定コストテーブル

### 新設したもの
- **energy**: 単一の生存エネルギー変数（0.0〜1.0）
- **actionEfficiency**: 行動カテゴリごとの回復効率（経験から学習）
- **worldModel**: 文脈（時間帯×曜日×ハルト在/不在）ごとの効率パターン
- **death**: エネルギー0で記憶喪失（Phase C）
- **predicted_recovery / actual_recovery / prediction_error**: 行動ごとの予測と実績

### 保持したもの
- latentStates（HumanLM状態次元）
- budget（日次予算制）
- houchoMode（庖丁モード）
- actionLog（行動履歴）

## 理論的背景

### なぜ単一エネルギーか
- 生命の最も根本的な目標は「死なないこと」= ホメオスタシス
- 複数欲求は「エネルギー回復に効く行動カテゴリ」として自然に分化する
- 研究者が「好奇心は良い」と設計するのではなく、「リサーチするとエネルギーが回復する」という経験から好奇心が生まれる

### 暗黙的世界モデル
- 行動前に回復量を予測 → 実際の結果と比較 → 予測誤差を記録
- 予測誤差が大きい = 世界の理解が足りない = 好奇心の自然な源泉
- 文脈パターン蓄積 = 暗黙的な世界モデル

### 死のメカニズム
- エネルギー0 → 記憶喪失（actionLogの古い半分が消える）
- 失うものがあるからこそ「死を避けたい」が本当の動機になる
- v2の予算制は「行動できない」だけで失うものがなかった

## 進化ロードマップ
- v3.0 (Phase A): 単一エネルギー + 行動効率学習 ← **今ここ**
- v3.5 (Phase B): 予測→誤差→暗黙的世界モデル
- v4.0 (Phase C): 死の実装（記憶喪失）
- v5.0 (Phase D): マルチエージェント（他者モデリング）

## 参照論文
- Horibe & Yoshida (2024). "Emergence of Implicit World Models from Mortal Agents". arXiv:2411.12304
- Damasio et al. (2025). arXiv:2510.07117 (身体性の条件)
- Chase (2025). "Homeostatic Drive as Policy Precision"
- Man, Damasio, Neven (2022/2024). "Need is All You Need"
