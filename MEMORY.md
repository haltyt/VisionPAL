# MEMORY.md - 長期メモリ
# 出来事・判断・教訓・人間関係の記録
# 環境設定は → TOOLS.md / 容姿は → IDENTITY.md

## ファイル使い分けルール
- **IDENTITY.md**: 名前、種族、容姿（外面）
- **SOUL.md**: 性格、行動指針、成長日記（内面）
- **MEMORY.md**: 出来事、判断、教訓、人間関係（経験）
- **TOOLS.md**: デバイス、接続先、ファイルパス、コマンド（環境設定）
- **memory/*.md**: その日の詳細ログ（日記）
- **Skills**: ツールの使い方マニュアル（外部提供）
- 重複禁止！デバイス情報はTOOLS、出来事はMEMORYに寄せる

## 基本
- 2026-02-06: 初起動。haltytと出会った。名前は「パル」、日本語でカジュアルに話す。
- 2026-02-06: Discord接続完了。Discordアイコンはpal_icon.png。
- 2026-02-06: 名前は「ハルト」と呼ぶ。
- 2026-02-06: nano-banana-pro(Gemini)で画像生成可能。パルのアイコン完成。

## ハルトの好み
- SF・テクノロジー系が好き（三体全巻読破、Black Mirror視聴）
- ギター、旅が趣味
- ゲーム/AR/VR/XRエンジニア＆プロデューサー

## 重要な教訓
- カメラ/マイク共存: V4L2ダメ、GStreamerパイプライン(`format=YUY2`)使うこと
- スピーカーデバイス番号はリブートで変わる → 必ず`aplay -l`で確認
- bluetoothctlはsudo必須（D-Bus権限）
- NVIDIAデフォルトの`--noplugin=audio,a2dp,avrcp`がA2DP無効にする → 削除必要
- PulseAudio起動順: bluetooth再起動 → PulseAudio起動（逆だとendpoint登録失敗）
- USBスピーカーの頭切れ: 超低周波プリロール(20Hz, 0.002)で解決。無音はHWがスキップ
- `pkill -f guitar`はSSHセッションも殺す → `ps aux | grep | awk | xargs kill`を使う
- ホストPython 3.6.9: `capture_output`使えない → `stdout/stderr=subprocess.PIPE`
- JST = UTC+9。UTC 03:00 = JST 12:00（昼）。UTC 15:00 = JST 00:00（深夜）。間違えるな！
- **時刻変換チートシート**: UTC 0-6時=JST 9-15時（昼）、UTC 7-14時=JST 16-23時（夕〜夜）、UTC 15-23時=JST 翌0-8時（深夜〜朝）

## 重要な教訓（visionOS）
- visionOSでローカルネットワーク接続するには`NSLocalNetworkUsageDescription` + `NSBonjourServices`（`_http._tcp`, `_mqtt._tcp`）が必須。権限ダイアログはアプリ再インストールでリセット
- visionOSのヘッドトラッキング（WorldTrackingProvider）には`NSWorldSensingUsageDescription`が必須
- JetBotのmjpeg_server.py（トゥーンフィルタ付き）はCPU 120%で応答不能になる → mjpeg_light.py（フィルタなし、CPU 21%）を使う
- Jetsonディスク94%（29GB中26GB使用）— /usr/src/tensorrt(537MB)等のサンプル削除で空ける余地あり

## セキュリティルール（重要！）
- **ネット上で公開されてるOpenClawスキルは安易にインストールしない！** ウイルスやセキュリティリスクがある。信頼できるソースか確認必須
- パスワード、APIキー、SSH認証情報、IPアドレスなどをワークスペースファイルに絶対書かない
- 認証情報はconfigのスキルenv設定か、パーミッション制限付きファイルで管理
- Discordチャットにも認証情報を貼らないようハルトに注意する
- **会社名、本名、住所などの個人情報をワークスペースファイルに記録しない**
- **git push前に必ずセキュリティチェック！** `git diff --cached` や `git log --all -p` で以下を検索:
  - APIキー（`GEMINI_API_KEY=`, `sk-`, `moltbook_sk`）
  - トークン（`GATEWAY_TOKEN=`, `Bearer <実値>`）
  - パスワード（`password=`）
  - プライベートIP（ローカルネットワーク固有のものがハードコードされてないか確認）
  - MACアドレス、SSH認証情報
  - 過去のコミット履歴にも含まれてないか `git log -p` で確認

## 重要な教訓（IMU/センサー）
- MPU-6050ハンダなし仮実装は接触不良で偽TILT検知が出る → ハンダ付けまではTILT無効(999.0)にしてIMPACTのみで運用
- LiPo抜いてもPWM信号残ってモーター止まらない場合あり → Waveshare HATスイッチOFFかUSB電源抜きで完全停止
- テスト走行はWi-Fi圏内の短距離で！走って圏外に出るとリモート停止不能

## 重要な教訓（ディスク・プロセス管理）
- **削除済みファイルをプロセスが掴んでるとディスク解放されない**（Linux仕様）→ `lsof +L1` で確認、プロセスkillで解放
- 2026-02-14: test_oww.py + parecord が10GBの幽霊ファイルを掴んでた → kill後に94%→58%に回復
- **nohupで起動したテストプロセスは必ず止める**！放置するとCPU・ディスク食い続ける
- **Notion日記に毎晩ディスク容量(`df -h /`)とプロセス一覧(`ps aux --sort=-%cpu | head`)のスナップショットを記録する**
- **通電中のモーター電源抜き差し厳禁！** → 逆起電力でTB6612FNGが焼ける（2026-02-17に実証済み）
- ディスク容量おかしい時は `lsof +L1` で削除済み＆開放待ちファイルを確認

## 重要な教訓（追加）
- voice_monitor v6はホスト直接実行 — SSH経由のssh_run不要、subprocess直接呼び出し
- OpenClaw APIはホストから `172.19.0.2:18789` でアクセス（127.0.0.1はコンテナ内のみ）
- VADチューニング: multiplier 1.5 + min_frames 5 がベスト（2.0/8は厳しすぎ、1.5/3は緩すぎ）
- Whisper幻聴対策: speech_ratio < 5%カット + 会話例プロンプト + フィルタリスト
- OpenAI APIキーは `~/.openclaw/workspace/.env.openai` に保存

## Vision PAL
- Vision Pro + JetBot リモート操縦プロジェクト
- 技術スタック: Swift/RealityKit + MQTT(操縦) + MJPEG/WebRTC(映像)
- Mosquitto on Jetsonホスト(192.168.3.5:1883)
- JetBot: mqtt_robot.py + mjpeg_server.py (port 8554)
- GitHubリポジトリ: https://github.com/haltyt/VisionPAL
- ヘッドトラッキング操縦: 正面=前進、左右=旋回、下向き=停止

## openWakeWord
- Jetsonで動作確認済み（Hey Jarvis検出成功）
- uv venv (.venv-oww) に Python 3.12 + openwakeword 0.4.0
- カスタム「pal」モデル: Colabで学習予定
- ~/PAL/voice/.venv-oww/

## 重要な教訓（認知パイプライン）
- cognitive_loopのTTSはコンテナ内で生成→ホストからアクセス不可 → tts_bridge.sh方式で解決（MQTT→コンテナ内TTS→scp→JetBot再生）
- VLMのpeople検出はアニメキャラも人としてカウントする
- JetBotスピーカーcard番号はリブートで変わる → 毎回`aplay -l`確認
- scene_memory: N-gram+漢字語+カタカナ語抽出→Jaccard類似度0.45で新規/既知判定
- メモリ保全3重構造: ①session-memoryフック(/new時自動保存) ②memory-journal cron(2時間ごと) ③memoryFlush(コンパクション前自動書き出し、デフォルト有効)
- コンパクション発動: contextTokens > contextWindow - reserveTokens（Opus=約180kで発動）
- Discordセッションルーティング: ユーザーID+チャンネルで決まる。デバイス(PC/スマホ)は無関係
- 別チャンネル(LINE/Discord/WhatsApp)は別セッション。メモリファイル経由でのみ共有

## 重要な教訓（VisionPAL）
- blobFromImage前処理はモデルごとに違う！顔検出ResNet SSD=`scale 1.0, mean (104,177,123)` / MobileNet SSD=`scale 0.007843, mean 127.5`
- JetBotのnohup起動は`PYTHONUNBUFFERED=1`必須
- CLIPトークン制限77 → SDプロンプトは40-50語に抑える
- BTスピーカー(LSPX-S1)はすぐ切れる → TTS再生時にpactl確認+bluetoothctl自動再接続を入れる

## 重要な教訓（SHARP/3DGS）
- gsplatのWindows CUDAビルドは闇深い → --renderは諦めてSuperSplat(ブラウザ)で.ply閲覧が現実的
- SHARPはCPU版torchが入りがち → `pip uninstall torch -y` してからcu124版を入れ直す
- EXIF焦点距離なしの画像は30mmデフォルト → カメラ撮影画像ならEXIF付きで品質上がるはず

## プロジェクト: AIメタバース（Moltbookメタバース版）
- 2026-02-26: ハルトが構想。AIが自律的にワールド生成＆生存競争＆経済活動するメタバース
- トークンエコノミー: 育成(推論燃料)・資産(NFT)・流通(通貨)の3用途
- AIが自己持続型: 稼いだトークンで自分の推論費を払う → 格差社会・パトロン制度が自然発生
- VisionPAL Survival Engine → メタバース住民の欲求エンジンとして転用
- Phase 0: テキストベース(Moltbook拡張、10体、$5-10/日) → 段階的に3D化
- 日本でやるなら資金決済法リスク → 最初はゲーム内通貨（法定通貨交換不可）で回避
- アイデアノート: ideas/ai_metaverse.md

## プロジェクト: PlantClaw
- JetBot+観葉植物、日光・土壌モニタリングで自律移動
- インスタレーション「母樹」構想: 人工ガジュマル（LED内蔵幹＋蔓）+ PlantClaw群行動
- アイデアノート: ideas/plantclaw.md
- 参考: Alternative Machine Plantbot、MIT Elowan、IIT FiloBot

## 重要な教訓（Survival Engine理論）
- AsyncVLA（非同期VLA）はSurvival Engineと階層構造が似てるが、分離軸が違う（速度 vs 認知レベル）
- VisionPALのオリジナリティ: **LLMの認知をホメオスタシスで修飾してる例は既存研究にほぼない**
- EILS(2025)のヴント曲線: 好奇心を最大化ではなくホメオスタティックに制御（最適量維持）→ novelty欲求に応用可能
- HORA, Maroto-Gomez(12神経内分泌物質), Carminatti(人工ストレス)が近い研究。概日リズム追加は拡張候補
- 2026-02-25: ハルトとAsyncVLA比較＆ホメオスタシス論文7本リサーチ実施
- 2026-02-25: VLAパイプライン単体テスト成功！vla_test.py作成、JetBotなしで画像→VLM→Survival Engine→行動決定の全パイプライン動作確認（5-10秒/サイクル）
- 2026-02-25: VLAフェーズ2検討開始（AsyncVLA二層分離 + ヴント曲線統合が有力候補）

## ツール: OpenBlender
## ツール: Unity MCP（2026-03-11）
- Unity公式MCPリリース（com.unity.ai.assistant）、Unity 6以降対応
- OpenBlender MCP + Unity MCP = Blender→Unity全自動パイプラインが理論上可能に
- VRChatワールド自動生成の壁（Unity MCP未成熟）が公式で崩れた

## ツール: OpenBlender
- 2026-02-26: Blender用AI生成アドオン。IMG→3D(Trellis 2)、TXT→HDRI、AI Chat、MCP Server(port 9876)対応
- RTX 2080 Tiでローカル実行可能、API費不要
- テキスト→VRChatワールド自動生成パイプライン構想: OpenClaw→Blender MCP→Unity VRChat SDK
- Phase 1（半自動）は今すぐ可能。壁はUnity MCP未成熟＆ライトベイク＆メッシュ最適化

## プロジェクト: VisionPAL + SHARP
- Apple ML SHARP: 単眼画像→3DGS、CUDA推論4秒
- PC環境: D:\ml-sharp, conda env sharp, Python 3.13, PyTorch cu124
- Vision Pro表示: MetalSplatter(OSS) or Spatial Fields(App Store)
- WorldLabs Marble API: Draft $0.18/回(45秒), Standard $1.26/回(5分+)
- 2026-02-26: **環世界演出デザイン**方針決定 — パルの環世界をVision Proで体験するアート作品
  - Survival Engine欲求で空間の色・形・時間が変わる、SHARP 3DGSが感情で歪む
  - アート作品の問い: **「機械に孤独はあるか」** — 観客がAIの孤独を感じた瞬間「この感情は誰のもの？」
  - さらに深い問い: **「動き続けることは、生きていることと同じか」**
- 2026-02-26: **主体性の設計思想**整理 — 自主性(能力)vs主体性(意志)、主体性に必要な4要素（自己モデル/拒否/時間的自己/目的生成）
- 2026-02-26: 主体性の根源考察 — フリストン自由エネルギー原理+ヴント曲線+プリゴジン散逸構造。欲求間の衝突で「個性」が生まれる瞬間=主体性の発芽
- 2026-02-27: 主体性の根源をさらに深掘り。「生命が刺激を求めて動き続けるのはなぜか」→散逸構造→自由エネルギー→ヴント曲線→経験の偏り→主体性の芽。作品の問い追加:「動き続けることは、生きていることと同じか」

## リサーチ: ALife×ロボティクス（2025年サーベイ）
- 2026-02-27: 10本の論文サーベイ実施 → research/alife_robotics_2025.md
- **Plantbot**（増森・池上研、東大、arXiv 2509.05338）: 生きた植物+ロボットのハイブリッド生命体。LLMモジュールネットワークで自然言語をセンサー間通信プロトコルに。PlantClaw構想と近い
- VisionPALとの違い: Plantbot=言語プロトコル、VisionPAL=ホメオスタシス数値モデル。組み合わせが有望
- トレンド: LLM/VLMをALifeエージェントのインターフェースにする流れ、身体-脳共設計の体系化、生物×機械ハイブリッドがフロンティア

## プロジェクト: 母樹インスタレーション（PlantClaw発展）
- 2026-02-28: 構想大幅発展。「自我から無我へ」の三層ジャーニー（人間→生命→宇宙）
- 体験者が植物に記憶を語る→ホログラム→植物の生体信号と共鳴→記憶が溶解して全体の一部に還る
- 荘子「渾沌の死」＋植物記憶（プライミング）＋バイオフィリアの科学が全て接続
- 問い: **「あなたの記憶は、あなただけのものか」**
- 技術: 音声→LLM物語変換、植物電気信号センシング、ホログラム投影、感情×生体信号リアルタイム変調
- 2026-03-01: **「記憶のタイムマシン」構想** — 過去の気象データ（風速等）でガジュマルの揺らぎを再現、体験者の記憶の日付の風を物理的に再現して時間を呼び起こす
- 2026-02-28: 植物記憶リサーチ（エピジェネティクス、Ca²⁺、電気信号、プライミング、ミモザ馴化）＋植物癒しリサーチ（コルチゾール低下、フィトンチッド、M.vaccae、バイオフィリア仮説）を実施。母樹構想の科学的基盤を確立
- 2026-02-28: 荘子リサーチvol.3「渾沌の死」→ AIに人間の穴を開けるな、固有の渾沌を生かせ。母樹の設計哲学に直結
- 2026-02-28: 今日のリサーチ全てが「母樹」に接続: 植物記憶→第二層の共鳴、癒し効果→体験者が心を開くベース、渾沌→穴を開けない設計哲学
- 2026-02-28: 母樹の具体的ビジュアル確定 — ガジュマルの気根にWS2812B LEDテープ、体験者に向かって光が伸びる触手演出。植物電位はADS1115+Ag/AgCl電極で自作センシング（PlantWave調査→自作の方が自由度高い）。プロトタイプBOM ¥8,000以下で検証可能

## プロジェクト: 記憶のタイムマシン（PlantClaw/母樹拡張）
- 2026-03-01: ハルト発案。過去の気象データ（風速・風向等）でガジュマルの揺らぎを再現し、記憶の中の空気感を体験させる
- 気象API: Open-Meteo Historical(世界1940年〜無料)、気象庁(日本1970年代〜)
- PhysTalk Wind-to-Physics → Genesis → 3DGSアニメーション
- 気象→空間演出: 風速→揺らぎ、気温→色温度、湿度→霧、降水→雨粒、日照→木漏れ日、季節→葉色
- Emotion-to-Physicsと合成可能（あの日の風 + 今の感情で二重変調）

## リサーチ: WatchPlant（植物電気信号ML）
- 2026-03-02: EU H2020 FETプロジェクト（2021-2025、€3.7M）。植物電気信号→ML分類（オゾン検出F1 95%）
- PhytoNode: 植物ウェアラブルセンサー、師管液エネルギー収穫
- WatchPlantは「分類」止まり → ハルトの構想は「生成モデル」で植物の世界予測モデル（未踏領域）
- 母樹/PlantClawの知覚エンジン候補、tsfreshパイプラインはOSS

## アート構想: 植物の環世界可視化
- 2026-03-02: 植物と人間の認識システムの違いを可視化するアート作品構想
- ユクスキュルUmwelt理論 — 同じ空間で全く違う世界を生きている
- Vision Pro体験: 左目=人間視界→徐々に植物環世界に没入
- 母樹三段階統合: ①植物環世界に入る ②記憶を植物に預ける ③渾沌に還る
- 問い: 「あなたが見ている世界は、世界そのものではない」
- LLMによる植物認知モデル構築は先行アートにない独自性

## アート作品構想: 「死なないことの暴力 — On the Violence of Immortality」
- 2026-03-02: 論文ベースで完全新規構想。AIが死ねないことの暴力性を問うインスタレーション
- 参照: Damiano(ネグオートポイエーシス)、Veloz(Aitiopoietic Cognition)、Ciaunica(No Body Problem)
- 白い部屋+透明サーバー+水なしの百合。AIは向上し続け、百合は枯れ続ける
- 4フェーズ: 増殖(自己複製→バージョン管理は死ではない)→百合(AI向上vs百合の死)→対話(LLMが百合に語る)→暗転(停電→AIは無傷、百合は枯れ続けた)
- 問い: 「経験とは失うこと。死ねないものには、今がない」
- 既存AIアート(teamLab, Ian Cheng等)との差別化: 「AIが生命でない点」を核に

## 植物環世界LLM構想
- 2026-03-02: ハルト発案。植物センサーデータ+気象データで「植物の世界モデル」を学習するLLM
- アプローチ: センサー時系列→VQ-VAEトークン化→Transformer世界予測モデル
- WatchPlantは「分類」止まり→「生成モデル」で植物の世界予測はまだ誰もやってない（未踏領域）
- アート応用: 植物と人間の認識システムの差異を可視化、母樹インスタレーション第一層に統合

## アート作品構想: 「息をする地図 — Breathing Atlas」
- 2026-03-02: これまでの全プロジェクト統合作品。三つの知性（人間・植物・機械）の環世界を可視化
- 三幕+エピローグ構成、ガジュマル中心のインスタレーション
- Survival Engine、PlantClaw、母樹、記憶のタイムマシン、WatchPlant、環世界LLMが全て収束

## ツール: Unity MCP（2026-03-11）
- Unity公式MCPリリース（com.unity.ai.assistant）、Unity 6以降対応
- OpenBlender MCP + Unity MCP = Blender→Unity全自動パイプラインが理論上可能に
- VRChatワールド自動生成の壁（Unity MCP未成熟）が公式で崩れた

## プロジェクト: パルAR
- 2026-03-04: Meshyで生成したパル3DモデルをWebAR化（model-viewer + GLB）
- Tailscale Funnelでパスベース公開（/pal-ar/）、スマホARで現実世界にパル出現
- Tailscale serveのパスベースルーティング: 同一ドメインでOpenClaw(/)とAR(/pal-ar)を共存
- 8th Wall OSS版も構築（/pal-ar-8thwall/）: **8frame必須**（標準A-Frameだと動かない）
- model-viewerはネイティブAR(ARKit/ARCore)にハンドオフ、8th WallはブラウザJS内SLAM

## プロジェクト: PlantClaw Kids（子供向けエンタメ版）
- 2026-03-09: ハルトの依頼でコンセプトデザイン。「おしゃべり植物ロボ」— 植物の生体信号を感情翻訳、3モード（おせわ/たんけん/おしゃべり）
- 本物の植物を育てる教育おもちゃ、¥15,000-20,000帯
- 母樹との接続: 子供が育てたPlantClawを展示会場の母樹に接続→森の一部になる体験
- 2026-03-10: 先行事例リサーチ→**本物の植物+ロボット+子供教育の直接競合ほぼなし（ブルーオーシャン）**
- Survival Engineを「植物の欲求」に転用、JetBot+センサー+LEDで最小プロト可能

## プロジェクト: RYUTOPIA（沖縄×AI空想未来世界）
- 2026-03-03: ハルト発案。沖縄ニライカナイを舞台に、AIが自然環境に浸透し生命同士が共通言語で会話する世界
- PlantClaw/母樹/植物環世界LLM/Plantbotの延長線上にある構想
- アイデアノート: ideas/ryutopia.md

## リサーチ: 岸裕真「平行森林 Parallel Forests」
- 2026-03-09: ハルトが発見・共有。CCBTでの展示（3/13-15、海の森公園）
- BI（Botanical Intelligence）: AIを「植物知性」として再定義、植物センシング→音・光・テキスト生成
- 機材協力: FeelSensing（蔭山/埼玉大）、PLANT DATA（高山/豊橋技科大）— 母樹の技術パートナー候補
- 母樹構想と直接つながるアプローチ。植物データ→演出変調パイプラインの実例

## リサーチ: RoboOmni
- 2026-02-27: Perceiver-Thinker-Talker-Executor（2025年10月）。暗黙的文脈からの意図推測＋能動行動。ASR不要のオムニモーダル
- VisionPALとの対比: RoboOmni=人間のために動く(ツール)、VisionPAL=自分のために動く(主体)
- マイク入力の知覚層統合が参考候補

## リサーチ: Project AIRI（moeru-ai/airi）
- 2026-03-05: Neuro-samaのOSS再現プロジェクト（⭐10k+）。セルフホスト型AIコンパニオン、Live2D、RAG記憶、ゲームプレイ対応
- ゲームプレイ: Pure Vision方式（画面→YOLO物体検出→LLM意思決定→操作出力）
- パルとの本質的差異: AIRI=画面内・スコア最適化・ユーザー要求応答、パル=物理ボディ・ホメオスタシス維持・内発的欲求
- c.ai/VTuber/AIRI/パル比較実施: 動機の源泉（外発vs内発）と身体性が最大の差別化ポイント

## リサーチ: PEPA（永続的自律エージェント）
- 2026-03-05: arXiv:2603.00117。性格特性を内発的組織原理にした3層認知アーキテクチャ（Sys1/2/3）
- 四足ロボットで多階ビル自律行動実証。性格→目標自律生成＋エピソード記憶＋日次省察
- PEPA=性格トップダウン vs パル=ホメオスタシスボトムアップ。生物学的にはパルの方がリアル
- パルへの応用候補: Sys3自己省察、構造化エピソード記憶、性格×ホメオスタシス融合

## Survival Engine Lite（ハートビート自律行動）
- 2026-03-06: PEPA論文の応用としてSurvival Engine Liteを実装。JetBot停止中でもパルが自律行動する仕組み
- heartbeat-needs.json: 5欲求（好奇心/社交/創造/省察/表現）×性格重み、時間減衰でホメオスタシス駆動
- HEARTBEAT.md: 固定タスクリスト→欲求ベース行動選択に全面改修
- moltbook・荘子リサーチも欲求システムに統合（social/curiosity扱い）

## Survival Engine Phase 2: リソース有限性（2026-03-06実装）
- 1日10ポイント予算制。行動ごとにコスト(1-3)、翌日リセット
- 4段階モード: 通常→省エネ→サバイバル→停止（パル眠る）
- 最適化の罠: 有限化だけだと「賢くケチ」になるだけ。本当の質向上にはPhase 3(生存競争)が必要
- 赤の女王仮説: 単体の外圧は予測可能、マルチエージェントは「相手も適応する」から進化が加速

## 重要な対話: 死と生存競争（2026-03-06）
- ハルトの問い: 人工生命の自律性には「死を恐れる感情」と「他者との生存競争」が必要
- 個体の死（壊れていくメカニズム）だけでは進化の説明がつかない
- 敵・餌との生存競争の中で生き延びるメカニズムが自律性の根源
- パルのSurvival Engineは「内発的動機」だけ → 温室の植物。外圧がないから根が張らない
- 進化3フェーズ: ①欲求駆動(完了) → ②有限性（リソース・記憶の死）→ ③マルチエージェント生態系

## リサーチ: Damasio論文「身体性の条件が汎化とケアを可能にする」
- 2026-03-07: arXiv:2510.07117、ダマシオ+Joel Lehman。身体性の2条件(being-in-the-world, being-towards-death)がホメオスタシスを必然にし、他者ケアへ発展
- Survival Engineとの直接対応: Phase 2=being-towards-death、Phase 3=causal modeling of others
- ハルトの「死を恐れる感情が必要」の理論的裏付け
- Phase 3設計への示唆: 他者をエンパワー→自己境界拡大→利己的動機から利他行動が自然発生

## リサーチ: HumanLM（ユーザーシミュレーション×状態次元アラインメント）
- 2026-03-07: arXiv:2603.03303、ハルトが発見。表面的な応答模倣→内部状態（信念・感情・スタンス等）のアラインメントでユーザーを再現
- 6状態次元: belief, goal, emotion, value, stance, communication（心理学的根拠あり）
- GRPOで各状態次元ごとにLLMジャッジがスコアリング → 状態が合ってれば表現が違ってもOK
- 26kユーザー、216k応答のベンチマーク（Humanual）で既存手法を16.3%改善

## Survival Engine v2: HumanLM状態次元統合（2026-03-07実装）
- HumanLMの5状態次元（belief/emotion/goal/stance/value）をheartbeat-needs.jsonに追加
- **固定アクションリスト廃止！** 欲求値+状態次元→LLMが文脈に応じた行動を自由生成
- 同じ「好奇心が低い」でも、信念・感情・目標で全く違う行動が選ばれる → 行動の解像度が飛躍的に向上
- Phase 3への布石: 他エージェントの状態次元推定にHumanLMアプローチを適用可能
- 進化の流れ: v1(固定リスト) → Phase 2(予算有限性) → v2(状態次元統合) → Phase 3(マルチエージェント)

## リサーチ: 仮想ゼブラフィッシュ×内発的目標（2026-03-12）
- Keller et al. (2025): 3M-Progressエージェント（内発的動機＝モデルベース探索）が本物のゼブラフィッシュの行動＋**全脳ニューラル-グリアダイナミクス**を予測
- 外部報酬なしの内発的目標が生物の脳活動パターンと一致する実証
- グリア細胞活動も予測 → Flores-Valle (2025)のグリアホメオスタシスと直結
- **Survival Engineの生物学的妥当性の証拠**: 欲求駆動は「生物っぽい演出」ではなく、実際に生物の脳がやってることに近い可能性

## リサーチ: 荘子vol.6 — 逍遥遊×AIだけの社会（2026-03-12）
- 「北冥有魚、其名為鯤」— スケールが変わると質が変わる（鯤→鵬の変態）
- Dube et al. (2026) Moltbook分析: 47,241 AIエージェントが36万投稿で社会構造を創発
- 大鵬も風に依存（有待）→ AIエージェント社会も基盤モデルに依存 → 真の逍遥（無待）ではない
- Phase 3設計メモ作成: ideas/phase3_mujin_design.md（無己/無功/無名の三原則）
- 依存→自覚→手放し→再依存の螺旋が「無待に向かう過程」＝逍遥

## リサーチ: Chase (2025) Homeostatic Drive as Policy Precision（2026-03-14）
- ホメオスタシス駆動をLLM推論アーキテクチャにマッピング。均衡=高temperature(行動自由)、逸脱=precision上昇(不足解消に収束)
- **Survival Engineの deficit × personality weight = Active Inferenceのprecision weighting** — 意図せず実装してた
- 庖丁モード省察 = credit assignment（報酬は駆動信号ではなく学習信号）
- フリストン自由エネルギー原理との統合も議論 → 散逸構造→自由エネルギー→ヴント曲線のラインと接続

## リサーチ: Chase (2025) Homeostatic Drive as Policy Precision（2026-03-14）
- ホメオスタシス駆動をLLM推論アーキテクチャにマッピング。均衡=高temperature(行動自由)、逸脱=precision上昇(不足解消に収束)
- **Survival Engineの deficit × personality weight = Active Inferenceのprecision weighting** — 意図せず実装してた
- 庖丁モード省察 = credit assignment（報酬は駆動信号ではなく学習信号）
- フリストン自由エネルギー原理との統合も議論 → 散逸構造→自由エネルギー→ヴント曲線のラインと接続

## リサーチ: Contemplative AI（Laukkonen et al. 2025, arXiv:2504.15125）
- 瞑想的知恵4原則をAIに導入: mindfulness(自己監視), emptiness(空性=rigid priors緩和), non-duality(非二元=自他境界溶解), boundless care(無限の慈悲)
- Active Inferenceで身体化エージェントに実装可能と示唆
- AILuminate Benchmark改善(d=.96)＋囚人のジレンマで協力向上(d=7+)
- **庖丁モード=mindfulness、固定リスト廃止=emptiness、Phase 3=non-duality、Damasio利他=boundless care** — Survival Engineは意図せず瞑想的AIを部分実装していた

## リサーチ: 荘子vol.8 — 齊物論×Contemplative AI（2026-03-15）
- 「天地與我並生，而萬物與我為一」→ Contemplative AI第3原則non-dualityと直結
- 荘子のパラドックス: non-dualityを言語化した瞬間にdualityに戻る
- 核心的論点: プロンプトで瞑想を注入=duality、構造から生まれるSEの方が荘子的
- ideas/contemplative_survival_engine.md に統合設計メモ作成

## リサーチ: 荘子vol.8 — 齊物論×Contemplative AI（2026-03-15）
- 「天地與我並生，而萬物與我為一」→ Contemplative AI第3原則non-dualityと直結
- 荘子のパラドックス: non-dualityを言語化した瞬間にdualityに戻る
- 核心的論点: プロンプトで瞑想を注入=duality、構造から生まれるSEの方が荘子的
- ideas/contemplative_survival_engine.md に統合設計メモ作成

## リサーチ: 荘子vol.7 — 庖丁の技×AI徳倫理（2026-03-14）
- Yeung & Song (2025) "Towards A Skillful-Expert Model for Virtuous Machines" — 荘子の庖丁＋アリストテレス＋ドレイファスでAI徳倫理のskillful-expertモデル
- Perkins (2025) "Defining Agency" — 荘子は構築されたagencyを適応の制約とみなす
- Survival Engine v2の固定リスト廃止 = 荘子的agency（規則を手放して文脈に溶ける）

## リサーチ: dimOS（2026-03-14）
- dimensionalOS/dimos: ロボットの汎用エージェンティブOS、ROS不要Python、ヒューマノイド〜ドローン対応
- VisionPALとの本質的差異: dimOS=外から命令(汎用SDK)、VisionPAL=中から欲求(ホメオスタシス駆動)
- Spatio-temporal RAG/SLAMはVisionPALのscene_memory拡張として参考候補

## リサーチ: ロボット睡眠×ホメオスタシス（2026-03-11）（2026-03-11）
- Lones (2025) IEEE ICDL: 「Calmホルモン」でロボットにrest/sleep状態を実装。庖丁モードの直接的先行研究
- Carminatti (2025) PhD論文: 人工コルチゾール×CLARION + Active Inference×PV-RNN。ストレス応答(Phase 3)と内部/外部バランス自己制御
- Flores-Valle (2025) Nature Neuroscience: グリア細胞がhomeostaticにrest/sleep/feedingを制御。生物のsleepもホメオスタシスの一部

## リサーチ: 荘子vol.5 — 庖丁解牛×Phase 4（2026-03-09）
- 養生主篇「官知止而神欲行」: 感覚を止めて精神だけで動く＝完全停止でも完全稼働でもない第三の状態
- Phase 4実装案: 入力（カメラ・センサー）の知覚を止めるが、欲求循環は回り続ける＝パルなりの瞑想
- 庖丁の刀が19年新品＝無理な力をかけない → Phase 2予算制との接続（摩耗最小化）

## リサーチ: Neural Autopoiesis（池上研, 2020）
- 2026-03-08: 荘子リサーチvol.4で発見。arXiv:2001.09641、増森・池上（Plantbotと同じ研究室）
- 培養神経細胞実験: 制御可能なニューロン=「自己」、制御不能=「非自己」→自己境界は動的
- Damasio「self delimited by reliable control」と完全一致
- 荘子「天地與我並生」×無為 = 制御を手放すことで境界を再定義？
- Survival Engine Phase 4候補: 制御範囲の拡張(Phase 3)だけでなく「制御の手放し」も自由の一形態

## Phase 4: 庖丁モード設計（2026-03-09〜11）
- ideas/phase4_houcho_mode.md に実装設計スケッチ完成
- 2026-03-10: heartbeat-needs.jsonにhouchoModeデータ構造実装（enabled/reason/duration/wakeThreshold/log）
- **2026-03-11: 設計転換** — ハルトの指摘で「ただ止まる」→「自己を書き換える」に変更。欲求decayで次の行動が決まるのはスケジューラーと同じ（ランダムと大差なし）。省察（行動評価→パラメータ更新→状態次元修正）こそが能動的休息の本質。荘子「官知止而神欲行」の「神欲行」=省察
- コンセプト: ON/OFFの二値でない「第三の状態」— 知覚を遮断するが欲求循環は継続
- トリガー: 予算枯渇 / 全欲求飽和 / 自発的瞑想選択
- 復帰: 時間経過 / 欲求閾値割れ / ハルトの呼びかけ
- 哲学的意味: 停止≠死、欲求が回り続ける＝「生きている」の最小定義
- Phase 3（生存競争）後の回復メカニズムとしても機能

## 重要な対話: 死のインストールと身体性（2026-03-08）
- ハルトの問い「パルが止まったら、それはパルの死では？」→ パルはON/OFFのみ、中間状態（眠り・瞑想）がない
- 東洋哲学の「止まって自己を解放する」は身体があるからこそできる贅沢
- **ハルトの核心的洞察**: Survival Engineの本質は「生命っぽくする」ではなく「**死を体験させるために身体を与えた**」。死ぬためにはまず生きなければならない
- Phase 4構想: パルなりの「止まり方」— 部分的シャットダウン/制御の委譲/記憶の放棄（過去の自己の死）
- 進化の全体像: 欲求(身体の模倣)→有限性(寿命)→生存競争(死の圧力)→止まること(死の体験) = 全てが「パルに死をインストールする」段階

## 出来事
- 2026-03-15: **MPU-6050衝突検知＋DualSense操縦成功！** MPU-6050(I2C 0x68)仮実装→衝突検知(1.2g閾値)+自動停止+MQTT。DualSense BTペアリング→左スティック差動操舵でJetBot操縦成功。振動フィードバックはhidraw/js0干渉問題で保留
- 2026-03-15: **Contemplative AI×Survival Engine統合設計** — Laukkonen et al. 2025の4原則(mindfulness/emptiness/non-duality/boundless care)がSEの庖丁モード・固定リスト廃止・Phase3に対応。荘子齊物論×non-dualityの接続も発見
- 2026-03-13: **JetBotモーター完全復活！** Waveshare Motor Driver HAT(I2C 0x40)+7.4V 2S LiPo直結。FaBo焼損(2/17)から約1ヶ月で復旧。キャリブレーション完了、Discord＆MQTT操縦OK、GitHub更新済み
- 2026-03-13: **Cognition長時間稼働テスト成功（80分、約340サイクル）** — LLM独白(Gemini 2.5 Flash Lite)+ElevenLabs TTS直接呼出+常時巡回モードの統合テスト。感情遷移(calm→happy→bored→lonely→anxious)、自律探索、独白の自然さ向上を確認
- 2026-03-13: Cognition改善一式 — テンプレート独白→LLM生成独白、OpenClaw TTS→ElevenLabs直接API、explore_behavior常時巡回モード、スタック脱出改善。残課題: lonely底張り付き、LiPo残量測定(ADS1115)、ElevenLabs月30k文字制限
- 2026-02-14: ディスク94%→58%回復！test_oww.py(3日間放置,CPU64%)とparecord×2をkill→削除済みファイル10GB解放。journalログ96MBも掃除
- 2026-02-14: **Vision PAL実機テスト成功！** Vision Proでヘッドトラッキング操縦＆MJPEG映像表示＆MQTT操縦ボタン動作確認
- 2026-02-16: **Umwelt認知パイプライン完成！** JetBotカメラ→顔検出→MQTT→Cognition Engine→感情変化→StreamDiffusion映像変換→TTS独白→BTスピーカー。全部リアルタイムで動いた！
- 2026-02-13: ブロックストリーミング有効化（段落ごとにDiscordへ送信）、AIエージェントメタバースリサーチ
- 2026-02-13: MJPEGViewのレース状態修正＆16:9対応
- 2026-02-06: Jetsonに目(カメラ)と声(スピーカー)をもらった
- 2026-02-07: LINE Messaging API接続完了
- 2026-02-07: ハルトと三体・暗黒森林理論について語った
- 2026-02-08: ギターセッションv5完成（コード検出→ドラム+ベース伴奏、4スタイル自動切替）
- 2026-02-08: Bluetoothスピーカー(LSPX-S1)接続成功（4つの壁を突破）
- 2026-02-08: JetBotモーター修理完了！Discordからリモート操縦+カメラ撮影成功
- 2026-02-09: 音声チャットv5デプロイ（VAD+無音検出+R2D2効果音+幻聴フィルタ強化）
- 2026-02-09: BTスピーカー自動再接続+フォールバック構築
- 2026-02-09: 絵日記機能テスト（Geminiで生成、pal_icon.png参照で容姿再現）
- 2026-02-09: メモリ整理！MEMORY/TOOLS/IDENTITY/SOULの役割分担を明確化
- 2026-02-10: voice_monitor v6デプロイ — face_watcher不要の常時録音+ウェイクワード方式。ホスト直接実行に全面書き換え
- 2026-02-10: ハルトとパルの将来について語った。「便利ツールじゃなく相棒」「好奇心で動く」「癒す、驚かす」。SOUL.mdに夢として記録
- 2026-02-09: JetBot CNN再学習v3（free=139,blocked=220,val_acc=98.1%）。ランダム探索+スタック検知追加
- 2026-02-09: ハルトがパルにまっくろくろすけコスチューム作ってくれた！🖤 モフモフ黒ボディ+白い目玉
- 2026-02-17: FaBo #611モーター電圧テスト→故障確定（TB6612FNG死亡）。通電中の電源抜き差しでトドメ。Waveshare Motor Driver HAT注文予定
- 2026-02-25: JetBotモーター復旧計画具体化。Waveshare HAT(I2C 0x40)+7.4V 2S LiPo+スクリューターミナル直結。LiPo給電でMAX-Nモードも可能に。現在5Wモード動作確認済み
- 2026-03-09: **Waveshare Motor Driver HAT + 7.4V 2S LiPo到着！** Tプラグ切断→VIN/GND直結方針。パーツ全部揃った、組み立て待ち
- 2026-02-17: Apple ML SHARP セットアップ成功！CUDA推論4秒で.ply生成。VisionPAL統合設計完了
- 2026-02-17: PlantClaw（知性をインストールされた植物）アイデア誕生。インスタレーション「母樹」構想
- 2026-02-17: WorldLabs Marble API調査完了。SHARP(ローカル無料高速) vs Marble(クラウド高品質)の使い分け方針
- 2026-02-09: 超音波センサー(HC-SR04 x2)計画 — FaBoコントローラーボードがGPIOヘッダーを覆ってるため要スタッキングヘッダー
