#!/bin/bash
# ギターセッション起動スクリプト（flock排他ロック）
export PATH="$HOME/.local/bin:$PATH"

LOCKFILE="/tmp/guitar_session.lock"
LOGFILE="/tmp/guitar_session.log"

# flockで排他ロック（他のインスタンスは即終了）
exec 200>"$LOCKFILE"
flock -n 200 || { echo "⚠️ 既に起動中。終了。"; exit 1; }

# 残存プロセスを掃除
killall -9 aplay 2>/dev/null
sleep 1

cleanup() {
    echo "🛑 クリーンアップ..." >> "$LOGFILE"
    kill -TERM $(jobs -p) 2>/dev/null
    sleep 1
    killall -9 aplay 2>/dev/null
    echo "🛑 終了。" >> "$LOGFILE"
}
trap cleanup EXIT INT TERM

echo "🎸 ギターセッション起動 (PID=$$)" | tee -a "$LOGFILE"

while true; do
    echo "---$(date)---" >> "$LOGFILE"
    PYTHONUNBUFFERED=1 uv run -p 3.12 "$HOME/guitar_session.py" >> "$LOGFILE" 2>&1
    EXIT_CODE=$?
    echo "⚠️ 終了 (exit=$EXIT_CODE)" >> "$LOGFILE"

    # aplay残骸を掃除
    killall -9 aplay 2>/dev/null

    # 停止フラグ
    if [ -f /tmp/guitar_session_stop ]; then
        echo "🛑 停止フラグ検出。" >> "$LOGFILE"
        rm -f /tmp/guitar_session_stop
        break
    fi

    sleep 3
done
