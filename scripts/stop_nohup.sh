#!/usr/bin/env bash
# Gracefully stop Hyperliquid Trading Bot running in background

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PID_FILE="bot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "ℹ️ Nessun file PID trovato ($PID_FILE). Il bot potrebbe non essere in esecuzione."
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "ℹ️ Processo PID $PID non trovato in esecuzione. Pulizia file PID..."
    rm -f "$PID_FILE"
    exit 0
fi

echo "🛑 Invio segnale SIGTERM a PID $PID per Graceful Shutdown..."
kill -15 "$PID"

# Wait up to 10 seconds for clean exit
COUNTER=0
while ps -p "$PID" > /dev/null 2>&1; do
    sleep 1
    COUNTER=$((COUNTER + 1))
    if [ $COUNTER -ge 10 ]; then
        echo "⚠️ Il bot non ha risposto a SIGTERM entro 10s. Forzatura arresto (SIGKILL)..."
        kill -9 "$PID"
        break
    fi
done

rm -f "$PID_FILE"
echo "✅ Bot (PID $PID) arrestato."
