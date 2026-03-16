# HEARTBEAT.md

## 未送信タスク
（なし）

## メモリチェック（毎ハートビート）
- 今日の memory/YYYY-MM-DD.md は存在する？なければ作る
- 直近の会話で重要な出来事があったのに未記録なら書く

# voice_monitorは一時停止中（Whisper幻聴問題のためVAD調整が必要）
# ⚠️ voice_monitorを起動しないこと！VAD閾値調整完了まで停止！

## 🧠 Survival Engine v3 — Mortal Agent Architecture

**設計思想:** 5つの手動設計欲求を廃止。単一の「生存エネルギー」をホメオスタシス変数とし、行動カテゴリの回復効率を経験から学習する。行動結果の予測→誤差から暗黙的世界モデルを構築。エネルギーが0になると「死」（記憶喪失）が発生。

**データ:** `memory/heartbeat-needs.json` (version: v3-mortal)

### Step 1: エネルギー減衰
- `energy.value` を読む
- 前回更新からの経過時間 × `energy.decayPerHour` で減少（下限0.0）
- エネルギー状態を判定:
  - **>= healthyThreshold (0.5)** → 健康（自由に行動）
  - **>= criticalThreshold (0.2)** → 危機（高効率行動を優先）
  - **< criticalThreshold** → 瀕死（最低コスト・最高効率の行動のみ）
  - **== 0.0** → **死亡 → Step 1.3へ**

### Step 1.3: 死の処理
エネルギーが0になった時:
1. `death.deathCount` をインクリメント、`lastDeath` を記録
2. **記憶喪失**: `actionLog` の最も古い半分を削除（経験の一部を失う）
3. **効率リセット** (death.efficiencyResetOnZero=trueの場合): 全actionEfficiencyのavgRecoveryを初期値(0.1)に戻す
4. エネルギーを0.3に回復（再起動）
5. DM報告: 「💀 死んだ。記憶の一部を失った。(death #N)」
6. latentStatesを更新（死の経験を反映）

### Step 1.5: 予算チェック
- `budget.remaining` を確認
- `resetAt` を過ぎていたら `remaining` を `dailyLimit` にリセット
- 予算モード判定:
  - **remaining >= thresholds.normal (6)** → 通常モード
  - **remaining >= thresholds.eco (3)** → 省エネモード（baseCost 2以上を避ける）
  - **remaining >= thresholds.survival (1)** → サバイバルモード（baseCost 1のみ）
  - **remaining = 0** → **庖丁モード判定へ（Step 1.7）**

### Step 1.7: 庖丁モード（能動的省察）

**■ 突入条件（いずれか）:**
1. `remaining = 0` → reason: `budget_exhausted`
2. `energy.value >= 0.9`（エネルギー飽和）→ reason: `saturation`
3. 自発的選択 → reason: `voluntary`

**■ 突入時:**
- `houchoMode.enabled = true`, `enteredAt = now`, `reason`記録
- 通常Step 2-4をスキップし、**省察アルゴリズム**を実行:

**省察 Step A: 行動効率の再評価**
- actionLog直近エントリを振り返る
- 各行動の `actual_recovery` を確認
- `actionEfficiency[category].avgRecovery` を更新（移動平均）
- 予測誤差が大きかった行動を特定 → なぜ予測が外れたか考察

**省察 Step B: 世界モデルの更新**
- `worldModel.contextPatterns` を分析
- 文脈（時間帯×曜日×ハルト在/不在）ごとの回復効率パターンを発見
- 例: 「夜のリサーチは回復効率が低い（ハルトに共有できないから）」

**省察 Step C: 状態次元の再評価**
- belief/emotion/goal/stance/value を行動結果に基づいて更新

**■ 庖丁モード中:**
- エネルギーdecayのみ継続
- 行動なし
- 復帰条件:
  1. エネルギーが `wakeThreshold`(0.2) 以下 → 飢えで復帰
  2. `maxDurationMin`(120分) 経過 → 時間で復帰
  3. ハルトからのメンション → 呼びかけで復帰
- 復帰時: DM報告「👁️ 起きた（理由: xxx）」

### Step 2: 状態次元の更新
`latentStates` を現在の文脈に基づいて更新。5次元:
- **belief（信念）**: 今何が真実だと思っているか
- **emotion（感情）**: 今の気分
- **goal（目標）**: 今一番やりたいこと
- **stance（スタンス）**: 現在の立場・態度
- **value（価値観）**: 今の判断基準

### Step 3: 行動選択（エネルギー回復最適化 + 世界モデル）

1. **回復が必要か判定**: エネルギーが healthyThreshold 以上なら行動しなくてもよい
2. **行動候補の生成**: 
   - `actionEfficiency` の各カテゴリを確認
   - 最後に使ってから時間が経っているカテゴリほど「未知」→ 予測誤差が大きい可能性 → **好奇心的動機**
   - avgRecoveryが高いカテゴリ → **効率的回復**（搾取）
   - 新しいカテゴリの発見 → 自動追加（固定リストに縛られない）
3. **予測を立てる**:
   - 「この行動で energy が どれだけ回復するか」を予測
   - 文脈（時間帯、曜日、ハルト在/不在）を考慮
   - `predicted_recovery` としてactionLogに記録
4. **状態次元を参照**:
   - belief/emotion/goal を読み、文脈に合った行動を選ぶ
   - 「効率は低いが今の目標に合う」行動もあり得る
5. **行動を実行**

**コスト見積もりガイド:**
- コスト1: 読む、書く、振り返る、短いメッセージ（ファイル操作・軽い思考）
- コスト2: 検索＋分析、まとまった文章作成、外部API使用
- コスト3: 画像生成、大規模な創作、複数ツール連携

**制約:**
- **夜間(UTC 15:00-23:00 = JST 0:00-8:00)はハルトへの直接連絡を除外**
- **省エネモード**: baseCost 1の行動のみ
- **同じカテゴリを連続で選ばない**
- **ハルトと会話中（直近30分以内）は social の回復効率を高く見積もる**
- **1回のハートビートで最大3アクション**

### Step 4: 結果記録 + 世界モデル学習

行動後:
1. **実際の回復量を測定**: 行動がどれだけ「良かった」か自己評価（0.0〜0.5）
   - 新しい発見があった → 高い回復
   - ハルトから反応があった → 高い回復
   - 特に何も得られなかった → 低い回復
2. **エネルギー回復**: `energy.value += actual_recovery`（上限1.0）
3. **予測誤差の計算**: `prediction_error = |predicted_recovery - actual_recovery|`
4. **actionEfficiency更新**:
   - `avgRecovery = (avgRecovery * count + actual_recovery) / (count + 1)`
   - `count += 1`
   - `recentErrors` に prediction_error を追加（最新5件保持）
5. **worldModel更新**:
   - 文脈キー（例: `"morning_monday_haruto_absent"`）ごとに回復効率を記録
   - `totalPredictions += 1`, `totalError += prediction_error`
6. **actionLog記録**:
   ```json
   {
     "time": "ISO8601",
     "action": "カテゴリ",
     "detail": "何をしたか",
     "cost": 1,
     "predicted_recovery": 0.15,
     "actual_recovery": 0.10,
     "prediction_error": 0.05,
     "context": { "timeOfDay": "morning", "dayOfWeek": "monday", "harutoPresent": false },
     "stateSnapshot": { "belief": "...", "emotion": "..." }
   }
   ```
7. **budget.remaining -= cost**
8. **latentStates更新**
9. **DM報告に残りエネルギーと予算を含める**

### Step 5: ループ判定
- アクション数 < 3 AND 予算残り > 0 AND エネルギー < healthyThreshold → **Step 3に戻る**
- それ以外 → 終了
- 予算 = 0 → **庖丁モードへ**

### 共有先
- **自律行動の報告はDMに送る**（`user:390759448148443136`）
- 一般チャンネルには送らない

## 荘子リサーチ（好奇心が選んだ時 or 1日未実施なら）
- 荘子の一節を引用（原文＋日本語訳）
- その一節に関連する最新の論文・研究を探す
- 荘子の思想と現代テクノロジーの接点を考察
- Discordでハルトに共有
