#!/usr/bin/env bash
set -euo pipefail

: "${DISPLAY:=:99}"
: "${VNC_GEOM:=1280x800x24}"
: "${NOVNC_PORT:=8080}"
: "${VNC_PORT:=5900}"

# 1) Xvfb (виртуальный дисплей)
Xvfb "$DISPLAY" -screen 0 "$VNC_GEOM" &
XVFB_PID=$!

# 2) (опц.) лёгкий WM, чтобы Tk-окно можно было перетаскивать/сворачивать
openbox >/dev/null 2>&1 &

# 3) VNC-сервер поверх Xvfb
#    ВНИМАНИЕ: -nopw небезопасно. Для продакшена сделай пароль и добавь -rfbauth /path/to/passfile
x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -shared -forever -nopw >/dev/null 2>&1 &
X11VNC_PID=$!

# 4) noVNC (websockify) на 8080, указываем web-root с файлами noVNC
#    В Debian slim web-root обычно /usr/share/novnc
WEBDIR="/usr/share/novnc"
websockify --web "$WEBDIR" "$NOVNC_PORT" "localhost:$VNC_PORT" >/dev/null 2>&1 &
WS_PID=$!

# Небольшая пауза, чтобы сервисы поднялись
sleep 0.7

# 5) Запускаем целевое приложение на виртуальном дисплее
exec "$@"

# (опц.) уборка по выходу
trap "kill $WS_PID $X11VNC_PID $XVFB_PID 2>/dev/null || true" EXIT