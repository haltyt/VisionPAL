#!/bin/bash
# パルTTS再生スクリプト
# Usage: pal_speak.sh "テキスト" [happy|normal|bashful|angry|sad]

TEXT="$1"
VOICE="${2:-happy}"

if [ -z "$TEXT" ]; then
    echo "Usage: pal_speak.sh 'テキスト' [voice]"
    exit 1
fi

DICT="/var/lib/mecab/dic/open-jtalk/naist-jdic"
HTS="/usr/share/hts-voice/mei/mei_${VOICE}.htsvoice"
BT_SINK="bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink"

# TTS生成
echo "$TEXT" | open_jtalk -m "$HTS" -x "$DICT" -ow /tmp/pal_say.wav -r 0.9 -fm 1 2>/dev/null

# Bluetooth スピーカーで再生（PulseAudio経由）
paplay --device="$BT_SINK" /tmp/pal_say.wav 2>/dev/null
