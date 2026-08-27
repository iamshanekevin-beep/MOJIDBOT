#!/bin/sh
# Wrapper that runs the bot and monitors it for hangs.
# If the bot stops producing log output for STALE_TIMEOUT seconds,
# the watchdog kills it and exits — Docker's restart policy brings it back.
set -e

STALE_TIMEOUT="${STALE_TIMEOUT:-180}"   # 3 minutes with no log = hung
LOG_FILE="${BOT_LOG_FILE:-/logs/bot.log}"

mkdir -p "$(dirname "$LOG_FILE")"

# Start the bot in the background, writing directly to the log file.
python -u main.py > "$LOG_FILE" 2>&1 &
BOT_PID=$!

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [WATCHDOG] Started bot (pid=$BOT_PID), stale timeout=${STALE_TIMEOUT}s" >> "$LOG_FILE"

# Watchdog loop — runs while the bot process is alive.
while kill -0 "$BOT_PID" 2>/dev/null; do
    sleep 30
    if [ -f "$LOG_FILE" ]; then
        LAST_MOD=$(stat -c %Y "$LOG_FILE" 2>/dev/null || echo 0)
        NOW=$(date +%s)
        DIFF=$((NOW - LAST_MOD))
        if [ "$DIFF" -gt "$STALE_TIMEOUT" ]; then
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [WATCHDOG] Bot hung (no log for ${DIFF}s) — killing for restart" >> "$LOG_FILE"
            kill -9 "$BOT_PID" 2>/dev/null || true
            exit 1
        fi
    fi
done

# Bot exited on its own — propagate its exit code so Docker can restart.
wait "$BOT_PID"
exit $?
