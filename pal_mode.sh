#!/bin/bash
# パル モード切替スクリプト
# Usage: pal_mode.sh [talk|guitar|stop|status]

MODE=${1:-status}

stop_guitar() {
    echo "🎸 ギターセッション停止中..."
    touch /tmp/guitar_session_stop
    ps aux | grep -E 'guitar_session|start_guitar' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    killall -9 aplay 2>/dev/null
    rm -f /tmp/guitar_session.lock /tmp/guitar_session_py.lock
    sleep 1
    echo "   ✅ 停止完了"
}

stop_talk() {
    echo "💬 会話モード停止中..."
    ps aux | grep -E 'face_watcher|voice_monitor' | grep -v grep | awk '{print $2}' | xargs -r kill 2>/dev/null
    rm -f /tmp/face_detected
    sleep 1
    echo "   ✅ 停止完了"
}

start_guitar() {
    rm -f /tmp/guitar_session_stop /tmp/guitar_session.lock /tmp/guitar_session_py.lock
    echo "🎸 ギターセッション起動中..."
    nohup bash ~/start_guitar.sh > /tmp/guitar_session.log 2>&1 &
    disown
    sleep 8
    tail -3 /tmp/guitar_session.log
}

start_talk() {
    echo "💬 会話モード起動中..."
    nohup python3 ~/face_watcher.py > /tmp/face_watcher.log 2>&1 &
    disown
    # voice_monitorはコンテナ側で起動する必要あり
    echo "   ✅ face_watcher 起動"
    echo "   ⚠️  voice_monitorはコンテナ側で起動してね"
}

show_status() {
    echo "📊 パル モード状態:"
    if ps aux | grep -E 'guitar_session\.py' | grep -v grep > /dev/null 2>&1; then
        echo "   🎸 ギターセッション: 稼働中"
    else
        echo "   🎸 ギターセッション: 停止"
    fi
    if ps aux | grep 'face_watcher' | grep -v grep > /dev/null 2>&1; then
        echo "   👁️  face_watcher: 稼働中"
    else
        echo "   👁️  face_watcher: 停止"
    fi
    if ps aux | grep 'voice_monitor' | grep -v grep > /dev/null 2>&1; then
        echo "   🎤 voice_monitor: 稼働中"
    else
        echo "   🎤 voice_monitor: 停止"
    fi
}

case "$MODE" in
    guitar)
        stop_talk
        stop_guitar
        start_guitar
        ;;
    talk)
        stop_guitar
        stop_talk
        start_talk
        ;;
    stop)
        stop_guitar
        stop_talk
        echo "🔇 全停止完了"
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: pal_mode.sh [talk|guitar|stop|status]"
        ;;
esac
