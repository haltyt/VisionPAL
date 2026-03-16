# TOOLS.md - 環境設定メモ
# デバイス、接続先、ファイルパス、使い方
# 出来事・教訓は → MEMORY.md

## ハルトPC
- GPU: RTX 2080 Ti（VRAM 11GB）
- OS: Windows（D:\ml-sharp等）

## SSH
- Jetsonホスト → コンテナのゲートウェイ経由（認証情報はTOOLS.mdに記載しない）
- JetBot → ed25519キー登録済み、パスワードなしSSH接続OK（IP: 192.168.3.8 ※DHCP変動あり）
- JetBot sudoers: `jetbot ALL=(ALL) NOPASSWD: ALL` 設定済み → `sudo shutdown -h now` がSSH経由で使える

## JetBot
- OS: Ubuntu 18.04.5, Python 3.6.9, jetbot 0.4.3, Adafruit-MotorHAT 1.4.0
- 電力モード: 5W（`sudo nvpmodel -m 1`）、LiPo給電後MAX-N(`-m 0`)も可
- モーター: FaBo #611 TB6612FNG **故障** → Waveshare Motor Driver HAT (I2C 0x40) 注文済み
- バッテリー: MINSHI 7.4V 1500mAh 2S LiPo ×2 + Tプラグ延長コード + USB充電器 注文済み
- IMU: GY-521 MPU-6050（I2C 0x68）装着済み（ハンダなし仮実装）— imu_collision.py で衝突検知
  - 設定: +-4g, +-500dps, DLPF 44Hz, impact閾値1.2g
  - TILT検知は仮実装の接触不良で偽検知→TILT_THRESHOLD=999.0で無効化中
  - ハンダ付け後にTILT復活予定
- コントローラー: DualSense（CFI-ZCT2J）— Jetsonホストに**BT接続済み**、MAC `D4:2F:4B:50:29:6B`、/dev/input/js0
- DualSense操縦: ~/dualsense_drive.py（Jetsonホスト）→ MQTT(vision_pal/move) → JetBot mqtt_robot.py
- 左スティック差動操舵（タンク式）、R2ブースト、×緊急停止、○終了
- ⚠️ BT接続時 `Enabled=0` 問題: 毎回 `echo 1 | sudo tee /sys/.../input/inputXXXX/enabled` が必要
  - `for f in /sys/devices/70090000.xusb/usb1/1-2/1-2.4/1-2.4:1.0/bluetooth/hci0/hci0:*/0005:054C:0CE6.*/input/input*/enabled; do echo 1 | sudo tee $f; done`
- ⚠️ DualSense BT振動: hidraw1を開くとjs0入力が完全停止する（kernel 4.9問題）→ **USB有線接続で解決予定**
- 起動手順: ①PSボタンでコントローラー起動 ②bluetoothctl connect ③Enabled=1設定 ④`PYTHONUNBUFFERED=1 python3 ~/dualsense_drive.py`
- カメラ: USBカメラ（/dev/video0、1280x720）+ IMX219 CSI（GStreamer nvarguscamerasrc）
- MJPEG配信: mjpeg_server.py（USB優先、CSIフォールバック、フィルタなし、マルチスレッド）:8554
  - `python3 ~/mjpeg_server.py --usb` で起動
  - エンドポイント: /stream /raw /snap /status
  - ⚠️ mjpeg_light.pyはCSI専用の旧版 → mjpeg_server.pyを使う
- collision_detect.py: MJPEG経由(http://127.0.0.1:8554/raw) + MQTT publish(vision_pal/perception/collision)
- モーター: Waveshare Motor Driver HAT (PCA9685 I2C 0x40)、smbus2直接制御
- マッピング: Motor A(ch0,1,2)=右、Motor B(ch5,3,4)=左
- キャリブレーション(speed 2000): 90度回転=0.675秒、10cm前進=1.0秒
- jetbot_control.py: ~/jetbot_control.py（前後左右+テスト+停止）
- jetbot_snap.py: ~/jetbot_snap.py（WB v4: パーセンタイルWB 70%+オリジナル30%ブレンド+CLAHE、wbmode=1、ISPゲイン固定）
- Discord操縦: 「前」「後」「左」「右」+スピード+秒数

## カメラ
- USBカメラ → /dev/video0（1920x1080）
- カメラ内蔵マイクは使わない！→ card 3 (USB_Camera) は不使用

## マイク
- **USBカメラ内蔵マイク → card 3, `plughw:3,0`**（これを使う！クリアな音質）
- PulseAudio: `alsa_input.usb-KYE_Systems_Corp._USB_Camera_200901010001-02.analog-stereo`
- USB PnP Sound Device(card 2)はノイズ激しいので使わない
- ⚠️ カメラマイクもノイズフロア高め → ノイズ除去(highpass+lowpass)必須

## スピーカー
- **Bluetooth: Sony LSPX-S1** → `bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink`（PulseAudio経由）
- USBスピーカー → 現在取り外し中（BTアダプタにポート使用）
- pal_speak.sh: BT→内蔵フォールバック付き、自動再接続あり

## Bluetooth
- アダプタ: CSR BT4.0 (0a12:0001) → hci0
- スピーカー: Sony LSPX-S1 MAC `AC:9B:0A:AA:B8:F6`（ペアリング＆信頼済み）
- bluetoothd: `/usr/lib/bluetooth/bluetoothd -d`（`--noplugin`なし、NVIDIAデフォルトから変更）
- D-Bus: `/etc/dbus-1/system.d/bluetooth.conf` にhaltytユーザー許可追加済み
- PulseAudio: bluetooth再起動後に起動する順番が重要
- 接続: `sudo bluetoothctl` → `connect AC:9B:0A:AA:B8:F6`
- スキャン時: `menu scan` → `transport bredr` → `back` → `scan on`（LEだとLSPX-S1見えない）
- 自動再接続: bt_connect.sh + cron 3分ごと

## TTS
- **ElevenLabs** (Starter $5/月): Yuiボイス、eleven_multilingual_v2、日本語
  - APIキーはconfig保存済み、OpenClawのttsツールで使える
  - voiceId: fUjY9K2nAIwlALOwSiwc
  - 30,000文字/月
- Open JTalk + meiボイス（happy/normal/bashful/angry/sad）→ ホスト側ローカルTTS
- ~/pal_speak.sh "テキスト" [voice] でホストから再生（BT/内蔵スピーカー）

## 顔検出
- DNN ResNet SSD（~/models/deploy.prototxt + caffemodel）
- confidence > 0.2
- ~/greeter.py で時間帯別挨拶

## 画像生成
- **nano-banana-pro（Gemini 3 Pro Image）**: モデル `gemini-3-pro-image-preview`、$0.134/枚(1K)
- **Nano Banana 2（Gemini 3.1 Flash Image）**: モデル `gemini-3.1-flash-image-preview`、$0.067/枚(1K)、Proより速い＆半額 ← こっち推奨
- APIキーはconfig保存済み（共通GEMINI_API_KEY）
- uv run /app/skills/nano-banana-pro/scripts/generate_image.py（Proモデル）
- Flash版は /tmp/gen_flash.py で対応（モデル名だけ違う）

## 動画生成
- **Veo 3.1 Fast**: モデル `veo-3.1-fast-generate-preview`、Image-to-Video対応
- Veo 3.1 / Veo 3.0 / Veo 2.0 も利用可能
- コスト: 約$2-3/本（8秒、プレビュー中は無料の可能性）
- APIキーはGEMINI_API_KEY共通
- 生成スクリプト: /tmp/gen_video4.py（image→types.Image変換、httpxでDL）
- DL時は `alt=media` と `key=API_KEY` をパラメータで渡す（URI直接だと認証エラー）

## Notion
- APIキー: configのスキルenv設定に保存済み
- 日記ページID: 300c4938-5513-80e8-a97c-ea431eb78744
- 食事記録DB: 300c4938-5513-81f0-a20c-f3d34715b564

## Meshy (Image to 3D)
- APIキー: configのスキルenv設定に保存済み（skills.entries.meshy.env.MESHY_API_KEY）
- meshy_img2mesh.py: VisionPAL/Cognition/meshy_img2mesh.py
- Meshy-6: 30 credits/回（テクスチャ付き）、PBR対応
- 出力: GLB, FBX, USDZ, OBJ+MTL
- USDZはVision Pro RealityKitで直接読込可能

## 表情アイコン
- 6種: happy/excited/sleepy/thinking/sad/tired（pal_faces/）
- change_avatar.py: CPU/メモリ/時間帯で表情選択+ディスク水位オーバーレイ
- cron avatar-rotate: 5分ごと自動切替
- Discord APIにはUser-Agent必須（ないと403）

## 音声チャット（voice_monitor v5）
- face_watcher.py: ホスト側（DNN+Haar投票、GStreamerカメラ）
- voice_monitor.py: コンテナ側（VAD+Whisper+OpenClaw+TTS+Discord通知）
- pal_record.py: ホスト側（parecord、無音0.8秒で自動停止）
- 効果音: /tmp/beep.wav(ピコピコ) /tmp/beep_skip.wav(ブッ) /tmp/pal_naninani.wav(なになに)

## ギターセッション
- ~/guitar_session.py（ホスト）、workspace/guitar_session.py（マスター）
- uv run -p 3.12 ~/guitar_session.py で実行
- ~/start_guitar.sh で起動、~/pal_mode.sh guitar で切替

## LINE
- dmPolicy: allowlist、チャンネルIDとトークンはconfig保存済み
- Webhook: Tailscale Funnel経由

## Tailscale
- Funnel有効化済み、LINE Webhook稼働中

## JetBot スピーカー
- USBスピーカー: card 2, `plughw:2,0`
- PulseAudio sink: `alsa_output.usb-Generic_USB2.0_Device_20130100ph0-00.analog-stereo`
- **⚠️ 音量50%が上限！絶対に超えない！** `amixer -c 2 set PCM 50%`
- PulseAudioのautospawnを切れば`aplay -D plughw:2,0`で直接再生可能
- PulseAudio有効時は`paplay`経由（aplayはdevice busy）
- Open JTalk: 男性声のみ（nitech-jp-atr503-m001）

## Vision PAL
- MQTTブローカー: Mosquitto on Jetsonホスト(192.168.3.5:1883)、`/etc/mosquitto/conf.d/vision_pal.conf`
- JetBot mqtt_robot.py: ~/mqtt_robot.py、MQTT→モーター制御
- JetBot mjpeg_light.py: ~/mjpeg_light.py、port 8554（マルチスレッド、フィルタなし、CPU軽量）
- 旧mjpeg_server.py: トゥーンフィルタ付き（CPU 134%で使用不可）
- StreamDiffusion server.py: PC側 port 8555（未セットアップ）
- GitHub: https://github.com/haltyt/VisionPAL
- git push方法: bundle → ホスト経由 → SSH push
- モーター方向: FORWARD/BACKWARD反転済み（配線逆）

## VisionPAL Cognition起動
- 起動順: ①MJPEGサーバー → ②body_sensor → ③collision_detect（JetBot） → ④vlm_watcher → ⑤cognitive_loop（Jetson）
- **cognitive_loopに必須環境変数**: `OPENCLAW_GATEWAY_TOKEN`（openclaw.jsonのgateway.auth.tokenから取得）+ `OPENCLAW_API_URL=http://172.19.0.2:18789`
- TTSファイルはコンテナ内生成 → docker cpでホストに取り出し（cognitive_loop.py修正済み）
- body_sensor.pyはJetBotにない場合があるのでscp必要
- Cognitionコード: VisionPAL/Cognition/ （workspace直下）
- 詳細手順: memory/2026-02-24.md「VisionPAL起動手順」セクション

## 定期タスク（cron）
- hourly-time-announce: 毎時時報（寝る時オフ）
- daily-notion-diary: 毎晩23時JST
- avatar-rotate: 5分ごとアバター切替
- bt_connect.sh: 3分ごとBT再接続チェック

## GeometrySync visionOS
- GitHub: https://github.com/haltyt/GeometrySync
- Blender Geometry Nodes → バイナリメッシュストリーミング → Vision Pro (RealityKit)
- 元はUnity版（Phase 1完成）、2026-03-02にvisionOS版を追加＆実機動作確認済み
- バイナリプロトコル: [Type:1B][Length:4B][Payload] / 頂点32B (pos+normal+uv)
- 座標変換: Blender(Z-up) → (x,z,-y)
- Blenderアドオン: depsgraph_update_post → extractor → serializer → TCP server

## Jetson Inference
- ~/jetson-inference にクローン済み、cmake成功
- make時にPython bindingsエラー → 要修正
