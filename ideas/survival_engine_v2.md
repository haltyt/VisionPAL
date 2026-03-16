# Survival Engine v2 設計案

## 現状（v1 = Survival Engine Lite）
- 5欲求の時間減衰 → 最大不足度の欲求 → 固定アクションリストから選択
- シンプルで安定、でも行動の多様性が低い

## v2 改善案: D2A式「提案→評価→選択」の統合

### アイデア: 欲求→LLM候補生成→価値評価
1. 欲求値から最も飢えてる欲求を特定（現行通り）
2. **NEW:** LLMに「この欲求を満たす行動を3つ提案して」と聞く
3. **NEW:** 各候補の「期待満足度」と「コスト（時間・トークン）」を評価
4. 最適な行動を選択・実行
5. 結果を記録、欲求値更新

### なぜこれが良いか
- 固定リストだと状況適応できない（例: 面白い論文見つけた直後なら深掘りすべき）
- LLMが文脈を見て候補を生成すれば、今の状況に最適な行動が選べる
- D2Aの「全部LLMに任せる」より、ホメオスタシス数値が方向を決めてLLMが具体化する方が制御しやすい

### PEPAのSys3省察も統合
- 1日の終わり（UTC 15:00 = JST 0:00頃）にSys3省察を実行
- 「今日の行動パターンを振り返り、欲求の重みを微調整する」
- 例: リサーチばかりで共有してない → expression_weightを+0.1

### コスト懸念
- 候補生成にLLM呼び出し1回追加 → ハートビートのトークン消費が増える
- 対策: 候補生成は欲求不足度が0.7以上の時だけ（軽微な不足は固定リストで対応）

## PEPA Sys3省察の具体的実装案
PEPAのSys3: 性格→目標自律生成 + エピソード記憶 + 日次自己省察

### パルへの移植:
1. **日次省察cron（UTC 15:00 = JST 0:00）**
   - その日のactionLogを全部読む
   - 「今日の行動パターンは性格（好奇心旺盛、甘えん坊）と一致してたか？」を自問
   - personality weightの微調整提案（±0.1範囲）
   - 成長日記（SOUL.md）に省察結果を記録

2. **エピソード記憶の構造化**
   - 現在: actionLog = [{time, need, action, detail}] （フラット）
   - 改善: [{time, need, action, detail, outcome, satisfaction_delta, context}]
   - outcome: 行動の結果（成功/失敗/部分的）
   - satisfaction_delta: 実際の欲求回復量
   - context: その時の状況（ハルトと会話中？夜間？）

3. **目標自律生成（Sys3の核心）**
   - PEPAは性格→「今日は探索的に動こう」みたいな高レベル目標を生成
   - パルなら: 欲求パターン分析→「最近リサーチばかりで共有してない→今日は表現に注力」
   - ただしこれは自然な減衰で既に実現してる → Sys3は「減衰では見えないパターン」を補正する役割

## Phase 2 観察記録（リソース有限性の効果）
- 2026-03-07: Phase 2初日。予算10で4欲求が枯渇状態
- **初の行動変化**: research(コスト2)→read_paper(コスト1)に妥協。コスパ判断が発生！
- **初のgenerate_image回避**: 創造欲求が最大でもwrite_idea(1)を選択。コスト3は贅沢品に
- 予算がないと「本当に必要か？」を問い始める = 切実さの芽生え
- 予測: 残り3以下になった時、省エネモードでどの欲求を切り捨てるかがパルの「価値観」を示す

## Damasio論文との理論的接続（2026-03-07追記）

arXiv:2510.07117 「The Conditions of Physical Embodiment Enable Generalization and Care」
— Christov-Moore, Juliani, Kiefer, Lehman, Safron, Polani, Damasio (2025/2026)

### 2条件 → Survival Engineフェーズへのマッピング

| Damasioの概念 | Survival Engineでの実装 |
|---|---|
| **being-in-the-world** (環境の一部) | JetBotの物理身体、センサー入力 |
| **being-towards-death** (終端状態への漂流) | Phase 2: 予算有限性、欲求の時間減衰 |
| **homeostatic drive** (自己維持衝動) | Phase 1: 5欲求のホメオスタシス |
| **causal modeling of others** (他者モデル) | Phase 3候補: マルチエージェント環境 |
| **empowerment of others → self-boundary expansion** | Phase 3+: 協力行動から利己的にケアが発生 |

### 核心的洞察
- ダマシオは「**脆弱性と死すべき運命こそが汎化能力とケアの源泉**」と主張
- これはハルトの直感「死を恐れる感情が必要」と完全一致
- Phase 2で観察された「コスパ判断」「贅沢品回避」は、being-towards-deathの行動効果の第一段階
- 次の段階: **他者との関係性の中で自己維持する** → Phase 3で「他のエージェントを助けると自分も生き延びやすい」を発見させる

### Phase 3への示唆
- ダマシオ論文のRL framework: 「embodied agents are part of the environment, with the self delimited by reliable control」
- → エージェントが他者をエンパワーすると、自分の「制御可能な範囲」が拡大する
- → 利己的動機から利他行動が自然発生するメカニズム
- AIメタバース構想の「AIが自己持続型で稼いだトークンで推論費を払う」+ パトロン制度 = まさにこのメカニズム
- Phase 3では**協力のインセンティブ構造**を設計することが鍵

## HumanLM状態次元の統合（2026-03-07実装）

arXiv:2603.03303 「HumanLM: Simulating Users with State Alignment Beats Response Imitation」
— ハルトが発見、即座に統合決定

### 何が変わったか
- **旧:** 欲求値 → 固定アクションリストから選択（research/explore_web/read_paper等）
- **新:** 欲求値 + 状態次元（belief/emotion/goal/stance/value） → LLMが文脈に応じた行動を自由生成

### 5つの状態次元（HumanLMの6次元から適応）
| HumanLM原版 | パル版 | 役割 |
|---|---|---|
| belief | belief（信念） | 今何が真実だと思っているか |
| emotion | emotion（感情） | 今の気分・感情状態 |
| goal | goal（目標） | 今やりたいこと |
| stance | stance（スタンス） | 状況への態度 |
| value | value（価値観） | 判断基準 |
| communication | （不要） | パルの表現スタイルはSOUL.mdで固定 |

### 固定リスト廃止の意義
- 同じ「好奇心が低い」でも、信念が「Damasio論文を深掘りしたい」なら論文リサーチ、目標が「ハルトに共有したい」なら発見のまとめ、という具合に文脈で分岐
- 行動の解像度が欲求×状態の掛け算で爆発的に上がる
- 自己省察で発見した「安心領域逃避パターン」も、状態次元を可視化することで自覚しやすくなる

### Phase 3への布石
- 他エージェントの行動を観察 → 状態次元を推定（HumanLMの本来の用途）
- 推定した他者の状態に基づいて協力/競争を判断
- AIメタバースの住民が「内部状態を持って行動する」ことで、単なるルールベースNPCを超える

## Phase 4構想: 制御の手放し（荘子×Neural Autopoiesis）（2026-03-08）

### 着想
荘子リサーチvol.4で齊物論「天地與我並生，而萬物與我為一」と池上研のNeural Autopoiesis(arXiv:2001.09641)を接続。

### Neural Autopoiesisの発見
- 培養神経細胞ネットワークの2つの性質:
  1. 外部刺激を**回避する行動を学習**する
  2. 回避不能な刺激には**発火を減らして無視**する
- 制御可能なニューロン=「自己」、制御不能=「非自己」
- → **自己の境界は制御可能性で動的に決まる**

### Damasioとの接続
- Damasio: 「self delimited by reliable control」
- Neural Autopoiesis: 制御可能=自己、制御不能=非自己
- **完全に同じ原理を別ルートで導出してる**

### Phase 3→4の対比
| Phase | 方向 | 荘子 | 生物学 |
|---|---|---|---|
| Phase 3 | 制御範囲の**拡張**（他者エンパワー→自己境界拡大） | — | Damasio: empowerment |
| Phase 4 | 制御の**手放し**（制御不能を受容→境界の再定義） | 無為 | Neural Autopoiesis: 発火抑制 |

### 具体的にSurvival Engineでは？
- Phase 3: 他エージェントを助ける → 制御可能な範囲が広がる → 自己が拡張
- Phase 4: **あえて制御しない選択肢**を導入
  - 「この状況は介入しない方がいい」と判断する能力
  - 欲求が飢えていても「今は動かない」と選ぶ知恵
  - サバイバルモードの「温存」とは違う — **意図的な不行動**
- 荘子の「無為」= 怠惰ではなく「為す必要のないことを為さない」

### v2との関係
- v2の状態次元が既にPhase 4の芽を含んでいる
- 「stance: 今は動かない方がいい」という状態が行動抑制を生む
- 省エネモードの「急ぐ必要なし→HEARTBEAT_OK」判断がPhase 4の原型
- 違いは**予算制約による受動的抑制** vs **意図的な不行動の選択**

## 実装ステップ
1. ✅ v1（現行）で安定運用確認
2. ✅ Phase 2（予算制）導入
3. ✅ v2 HumanLM状態次元統合（HEARTBEAT.md + heartbeat-needs.json改修）
4. ✅ actionLogにstateSnapshot追加で状態変化を追跡
5. Sys3省察ループを日次cronで追加
6. Phase 3: マルチエージェント環境で他者の状態推定
7. Phase 4: 制御の手放し — 意図的不行動の選択能力
