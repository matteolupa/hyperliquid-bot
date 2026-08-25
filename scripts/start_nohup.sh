#!/usr/bin/env bash
# Start Hyperliquid Trading Bot in background using nohup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PID_FILE="bot.pid"
LOG_FILE="logs/bot.log"
mkdir -p logs

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️ Il bot è già in esecuzione con PID: $PID"
        echo "Per visualizzare i log: tail -f $LOG_FILE"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Detect Python executable
if [ -f ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
elif command -v python3 > /dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "❌ Python 3 non trovato!"
    exit 1
fi

echo "🚀 Avvio Hyperliquid Bot in background (nohup)..."
echo "Comando: $PYTHON_BIN run_bot.py $@"

export PYTHONPATH="src:$PYTHONPATH"
nohup "$PYTHON_BIN" run_bot.py "$@" > logs/bot_stdout.log 2>&1 &
BOT_PID=$!

echo "$BOT_PID" > "$PID_FILE"
echo "✅ Bot avviato con successo! PID: $BOT_PID"
echo "📝 Log in tempo reale: tail -f $LOG_FILE"
echo "🛑 Per fermare il bot: bash scripts/stop_nohup.sh"
