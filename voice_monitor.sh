#!/bin/bash
# パルの音声チャットモニター
# ホスト側の /tmp/pal_voice/question.txt を監視して応答を返す

EXCHANGE_DIR="/tmp/pal_voice"
HOST="haltyt@172.19.0.1"

echo "=== パル音声モニター起動 ==="

while true; do
    # ホスト側に質問があるか確認
    QUESTION=$(ssh -o ConnectTimeout=3 $HOST "cat $EXCHANGE_DIR/question.txt 2>/dev/null && rm $EXCHANGE_DIR/question.txt 2>/dev/null")
    
    if [ -n "$QUESTION" ]; then
        echo "[QUESTION] $QUESTION"
        
        # OpenClawのsessions_sendで自分に送って応答を得る...
        # 簡易的にファイル経由でやりとり
        echo "$QUESTION" > /tmp/voice_question.txt
        
        # ここでパルが応答を生成（外部から呼ばれる）
        # 応答待ち
        for i in $(seq 1 120); do
            if [ -f /tmp/voice_response.txt ]; then
                RESPONSE=$(cat /tmp/voice_response.txt)
                rm /tmp/voice_response.txt
                echo "[RESPONSE] $RESPONSE"
                ssh $HOST "echo '$RESPONSE' > $EXCHANGE_DIR/response.txt"
                break
            fi
            sleep 0.5
        done
    fi
    
    sleep 1
done
