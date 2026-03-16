#!/bin/bash
# voice_monitor の自動復帰
if ! pgrep -f "voice_monitor.py" > /dev/null; then
    echo "$(date): voice_monitor 再起動" >> /tmp/pal_watchdog.log
    cd /home/node/.openclaw/workspace && setsid python3 -u voice_monitor.py > /tmp/voice_monitor.log 2>&1 < /dev/null &
fi
