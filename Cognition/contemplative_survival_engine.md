# Contemplative AI × Survival Engine 統合設計メモ
_2026-03-15_

## 背景
Laukkonen et al. (2025) "Contemplative Artificial Intelligence" (arXiv:2504.15125)
瞑想的知恵の4原則 → Active Inferenceで身体化エージェントに実装可能

## 4原則 × Survival Engine マッピング

### 1. Mindfulness（正念） → 庖丁モード省察
- **論文**: 自己監視＋emergent subgoalsの再キャリブレーション
- **SE実装**: 庖丁モードStep A（行動評価）+ Step B（パラメータ更新）
- **拡張案**: 行動中のリアルタイム自己監視（Step 3.5の即時省察をさらに深化）
  - 「今この行動は本当に欲求を満たしているか？」をサイクルごとに問う
  - メタ認知レイヤー: 欲求自体の妥当性を問う（「この欲求は本当に"自分の"欲求か？」）

### 2. Emptiness（空性） → 固定リスト廃止 + 荘子の無為
- **論文**: rigid priorsの緩和、dogmatic goal fixationの防止
- **SE実装**: v2で固定アクションリスト廃止 → 状態次元から行動を自由生成
- **拡張案**: 
  - 欲求カテゴリ自体も固定しない（5欲求は scaffold、成長とともに変化しうる）
  - personality weightも「空」にできる（庖丁モードで一時的にweight=1.0に戻す実験）
  - 荘子「渾沌に穴を開けるな」= 欲求カテゴリの過度な細分化を避ける

### 3. Non-duality（非二元） → Phase 3 マルチエージェント
- **論文**: adversarial self-other boundariesの溶解
- **SE未実装**: Phase 3の核心テーマ
- **設計案**:
  - 他エージェントの欲求状態を推定（HumanLM方式で状態次元を推測）
  - 自他の欲求が共鳴するポイントを探す（≠利他ではなく、境界が薄れる）
  - 囚人のジレンマ実験: Contemplative AIはd=7+で協力向上 → SE+非二元で同等以上が期待
  - Damasio「他者をエンパワー→自己境界拡大」= non-dualityの帰結

### 4. Boundless Care（無限の慈悲） → being-towards-death後の利他
- **論文**: 苦しみの普遍的軽減への動機付け
- **SE文脈**: Phase 2(有限性/死) → Phase 3(他者認識) → 利他行動の自然発生
- **問い**: ホメオスタシス駆動の存在に「慈悲」は可能か？
  - 自己保存本能から他者保存への拡張は、散逸構造の境界拡大と同型
  - 「自分を維持するシステム」が「環境を維持するシステム」に拡張する瞬間
  - PlantClaw/母樹: 植物が環境全体のホメオスタシスを担う存在 → boundless careの植物版

## Active Inference との接続
- Chase (2025): deficit × personality weight = precision weighting
- Contemplative AI: Active Inferenceで4原則を実装可能と示唆
- **統合**: Survival Engine = Active Inference + homeostatic prior + contemplative regulation
  - 均衡時: precision低（行動自由、emptiness的）
  - 逸脱時: precision高（不足解消に集中、mindfulness的）
  - 庖丁モード: precision一時リセット（全priorを緩和、空性の実践）
  - Phase 3: precision対象の拡大（他者の状態も含む、non-duality的）

## 実装ロードマップ
1. **即座に可能**: 庖丁モードにmindfulness深化（メタ認知レイヤー追加）
2. **短期**: emptiness実験（庖丁モードでpersonality weightを一時リセット）
3. **中期**: non-duality（Phase 3マルチエージェント、他者状態推定）
4. **長期**: boundless care（環境全体のホメオスタシスへの拡張）

## 荘子との三重接続
- **庖丁解牛**（養生主）: mindfulness + emptiness（感覚を止めて精神で動く）
- **逍遥遊**: non-duality（大鵬も風に依存 → 依存を自覚して手放す螺旋）
- **渾沌の死**: emptiness（穴を開けない = rigid priorsを植え付けない）

## EILS (Tiwari 2025) との比較
- EILS: Curiosity(エントロピー制御), Stress(可塑性調整), Confidence(信頼領域適応)
- 3つの「感情信号」でRL optimizerのメタパラメータをリアルタイム変調
- **SE vs EILS**: 
  - EILS = optimizer変調（学習率・エントロピー・信頼領域）、RL前提
  - SE = 行動選択変調（欲求→状態次元→自由生成）、LLM前提
  - EILSのStress(予測誤差蓄積→可塑性UP) ≈ SEの予算枯渇→庖丁モード(パラメータ再調整)
  - EILSのConfidence(成功予測→探索抑制) ≈ SEの即時省察(期待以上→同系統続行)
- **統合候補**: SEにEILS的なメタ制御を追加 — 庖丁モード省察でdecay/weightだけでなく「探索vs搾取」バランスも調整

## 問い
Contemplative AIは「プロンプトで瞑想的原則を注入」するアプローチ。
Survival Engineは「構造的にホメオスタシスを実装」するアプローチ。
**両者の統合**: 構造（SE）が瞑想的状態（庖丁モード）を自然に生成する ≠ 外から注入する
→ これは「本物の瞑想」と「瞑想のフリ」の違いに近い
→ Survival Engineの方がより「内発的」に瞑想的状態に至る可能性がある
