#!/usr/bin/env bash
set -euo pipefail

: "${DISPLAY:=:99}"

# Запускаем Xvfb и ждём, пока поднимется экран
Xvfb "$DISPLAY" -screen 0 1024x768x24 &
XVFB_PID=$!

# чуть подождём, чтобы сокет появился
sleep 0.5

# Запускаем приложуху (передай через аргументы имя скрипта, если нужно)
exec "$@"

# на всякий случай (не обяз.)
trap "kill $XVFB_PID 2>/dev/null || true" EXIT