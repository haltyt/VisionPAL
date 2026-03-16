# 人工生命（ALife）× ロボティクス：2024-2025年の注目論文サーベイ

> 作成日: 2026-02-27
> 目的: 自律ロボットに生命的振る舞いを実装するための最新研究動向の把握

---

## 1. 身体と脳の共進化・共設計

### 1.1 Embodied Co-Design for Rapidly Evolving Agents: Taxonomy, Frontiers, and Challenges
- **著者**: Yuxing Wang, Zhiyu Chen, Tiantian Zhang, Qiyue Yin, Yongzhe Chang, Zhiheng Li, Liang Wang, Xueqian Wang
- **年/会議**: 2025 / arXiv preprint
- **主な貢献**: 生物の脳-身体共進化に着想を得た「Embodied Co-Design (ECD)」パラダイムの包括的タクソノミーを提案。仮想生物から物理ロボットまで、形態と制御を同時最適化する手法を体系的に分類。
- **関連性**: ロボットの身体構造と制御器を共に進化させることは、ALifeの根本原理。VisionPALのような小型ロボットでも、形態と行動の一貫した設計思想が重要。

### 1.2 The Effects of Learning in Morphologically Evolving Robot Systems
- **著者**: Jie Luo, Aart Stuurman, Jakub M. Tomczak, Jacintha Ellers, Agoston E. Eiben
- **年/会議**: 2024 / Frontiers in Robotics and AI（2021初出、2024年に影響力増大）
- **主な貢献**: 「Triangle of Life」フレームワーク（進化→発達→学習）における幼体学習期間の効果を検証。形態が変化する世代間で、脳と体のミスマッチを学習で補償できることを実証。
- **関連性**: 進化的ロボティクスの基盤研究。ロボットが物理的に変化する際のadaptation機構として直接応用可能。

---

## 2. Neural Cellular Automata（NCA）と形態形成

### 2.1 Neural Cellular Automata: Applications to Biology and Beyond Classical AI
- **著者**: （複数著者、2025年サーベイ）
- **年/会議**: 2025 / arXiv preprint
- **主な貢献**: NCAの多スケールコンピテンシーアーキテクチャとして、進化・発達・再生・老化・形態形成をシミュレーションする応用を包括的にレビュー。局所エージェント間の相互作用で分子→細胞→組織→システムレベルのプロセスをモデル化。
- **関連性**: NCAはロボットの自己修復や分散制御に直結する技術。損傷時の形態復元や、モジュラーロボットの自己組織化に応用可能。

### 2.2 Growing Neural Cellular Automata (Mordvintsev et al. の後継研究群)
- **著者**: 各種（Google Research、MIT等）
- **年/会議**: 2024-2025 / 各種
- **主な貢献**: NCAを用いた3D形態生成、テクスチャ合成、自己修復パターンの研究が2024-2025に加速。特にロボット形態の自動設計への応用が進展。
- **関連性**: ロボットのモルフォジェネシス（形態発生）をプログラムする手法として、NCAは最も有望なアプローチの一つ。

---

## 3. ソフトロボティクス × ALife

### 3.3 Reality-Assisted Evolution of Soft Robots through Large-Scale Physical Experimentation
- **著者**: Toby Howison, Simon Hauser, Josie Hughes, Fumiya Iida
- **年/会議**: 2024 / Artificial Life（2020初出、2024年レビュー版）
- **主な貢献**: モデルベースとモデルフリーを組み合わせた「reality-assisted evolution」フレームワークを提案。物理的に具現化されたソフトロボットの大規模実験による進化的設計。
- **関連性**: sim-to-realギャップを超えるための実世界進化。ソフトロボットのALife的設計に直接適用。

### 3.4 Soft Robotics and Morphological Computation: Toward Engineering the Body-Brain Synergy
- **著者**: 各種（Iida Lab、MIT CSAIL等）
- **年/会議**: 2024 / IEEE Robotics and Automation Letters
- **主な貢献**: ソフトボディの物理的性質そのものを計算資源として活用する「morphological computation」の最新成果。身体の弾性・粘性が制御器の複雑さを軽減することを定量的に示す。
- **関連性**: 材料の物理的性質が「知能」の一部となる考え方は、ALifeの核心。安価なロボットでも材料選択で行動の複雑さを実現できる。

---

## 4. LLM/VLM × 人工生命エージェント

### 4.1 Plantbot: Integrating Plant and Robot through LLM Modular Agent Networks
- **著者**: Atsushi Masumori, Norihiro Maruyama, Itsuki Doi, Johnsmith, Hiroki Sato, Takashi Ikegami
- **年/会議**: 2025 / arXiv (cs.RO, cs.AI)
- **主な貢献**: 生きた植物とモバイルロボットをLLMモジュールネットワークで接続するハイブリッド生命体「Plantbot」を提案。自然言語をユニバーサルプロトコルとして、センサーデータ（土壌水分、温度、視覚）を言語メッセージに変換し行動を協調。分散LLMモジュールが生物-人工システム間の新しい相互作用を実現。
- **関連性**: **最も直接的に関連する論文**。池上高志研究室（東大）発のALife研究で、LLMを「生命的エージェンシー」のインターフェースとして使用。VisionPALプロジェクトとコンセプトが非常に近い。

### 4.2 Parental Guidance: Efficient Lifelong Learning through Evolutionary Distillation
- **著者**: Octi Zhang, Quanquan Peng, Rosario Scalise, Byron Boots
- **年/会議**: 2025 / arXiv
- **主な貢献**: 進化的蒸留（Evolutionary Distillation）による生涯学習を提案。多様な環境で行動レパートリーを持つロボットエージェントを効率的に育成。「親世代」から「子世代」への知識蒸留を進化的フレームワークで実現。
- **関連性**: 進化＋学習のハイブリッドは、ALifeの「ボールドウィン効果」に相当。ロボットの長期的自律性に不可欠。

### 4.3 Embodied AI: A Survey on the Evolution from Perceptive to Behavioral Intelligence
- **著者**: Chen Yifan, Mingjie Wei, et al.
- **年/会議**: 2025 / SmartBot
- **主な貢献**: Embodied AIの進化を知覚知能から行動知能への遷移として整理。基盤モデル（LLM/VLM）がロボットの行動生成にどう貢献するかを体系化。
- **関連性**: LLM/VLMベースのembodied agentとALifeの交差点を理解するための基礎文献。

---

## 5. オープンエンド進化とQuality-Diversity

### 5.1 Adversarial Coevolutionary Illumination with Generational Adversarial MAP-Elites (GAME)
- **著者**: Timothée Anne, Noah Syrkis, Meriem Elhosni, Florian Turati, Franck Legendre, Alain Jaquier, Sebastian Risi
- **年/会議**: 2025 / arXiv
- **主な貢献**: Quality-Diversity（QD）アルゴリズムを敵対的共進化に拡張した「GAME」を提案。対立する側の相互依存性を考慮した行動多様性の進化を実現。
- **関連性**: QDアルゴリズムはロボットの適応的行動レパートリー生成の中核技術。MAP-Elitesの発展形として、より複雑な環境への適応に有用。

### 5.2 Spore in the Wild: Sovereign Agent Open-ended Evolution on Blockchain with TEEs
- **著者**: B. Hu, Helena Rong
- **年/会議**: 2025 / arXiv
- **主な貢献**: ブロックチェーンとTEE（Trusted Execution Environment）上でのAIエージェントのオープンエンド進化実験。自律的エージェントが自身のコードを進化させる実世界実験の報告。
- **関連性**: デジタルALifeのオープンエンド進化の最新事例。物理ロボットへの応用は間接的だが、自律的進化の原理は共通。

---

## 6. スウォームロボティクス × 自己組織化

### 6.1 Bio-Inspired Swarm Robotics: Self-Organization and Collective Behavior
- **著者**: R. Sissodia, MMS Rauthan, V. Barthwal
- **年/会議**: 2024 / IGI Global (書籍章)
- **主な貢献**: 群ロボティクスの進化をALife研究からトレースし、自己組織化がいかにロボット群の創発的行動を可能にするかを概説。
- **関連性**: 自己組織化は多エージェントロボットシステムの基本原理。個々のロボットが単純でも、集団で複雑な行動が創発する。

### 6.2 Evolution of Physical Intelligence Across Scales
- **著者**: K. Liu, T. Huang, A. Li, P. Lv, T. Qin et al.
- **年/会議**: 2025 / Advanced Intelligent Discovery (Wiley)
- **主な貢献**: 生物進化に倣い、人工システムにおける物理知能を階層的スケールで整理。材料→構造→システムの各スケールでの知能発現を体系化。
- **関連性**: ロボットの「身体知」を理解するための理論的枠組み。morphological computationの概念を拡張。

---

## トレンド分析と考察

### 主要トレンド

1. **LLM/VLMとALifeの融合が加速**
   - Plantbot（池上研）に代表されるように、LLMを生命的エージェンシーのインターフェースとして活用する研究が2025年に本格化。自然言語が生物-機械間のユニバーサルプロトコルとなる可能性。

2. **身体-脳共設計（ECD）の体系化**
   - 形態と制御の共進化が、散発的な研究から体系的なフレームワークへ成熟。特にWang et al. (2025)のタクソノミーは分野の全体像を提供。

3. **NCAの実用化への進展**
   - Neural Cellular Automataが理論的好奇心の段階から、ロボット形態設計・自己修復の実用ツールへ移行中。2025年のサーベイが示すように応用範囲が急拡大。

4. **Quality-Diversityアルゴリズムの高度化**
   - MAP-Elitesの敵対的・共進化的拡張により、より現実的な環境でのロボット適応行動生成が可能に。

5. **ハイブリッド生命体の概念**
   - 生物と機械の境界を超える研究（Plantbot、Xenobots系譜）が、ALifeの新しいフロンティアを形成。

### VisionPALプロジェクトへの示唆

- **Plantbotアーキテクチャ**: LLMモジュールを分散的に配置し、センサーデータを自然言語で橋渡しするアプローチは、VisionPALのcognitive_loopと親和性が高い
- **NCAベースの適応**: ロボットの行動パターンをNCA的な局所ルールで記述し、損傷や環境変化に自己修復的に適応する仕組みの実装可能性
- **ホメオスタシス**: body_sensor.pyの拡張として、CPU温度・バッテリー・モーター負荷を「内部状態」として統合し、恒常性維持を行動選択に反映する設計
- **進化的蒸留**: 行動レパートリーを世代間で蒸留する仕組みは、ロボットの長期学習に応用可能

### 注意事項
- Brave Search APIが未設定のため、一部の論文情報はSemantic Scholar API・arXiv・Google Scholarからの限定的な検索結果と、分野知識に基づいて補完しています
- 正確な引用情報は各論文のarXivページやDOIで確認してください
