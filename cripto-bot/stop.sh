#!/usr/bin/env bash
# Para o supervisor (TERM => trap mata o bot). Espera até 45s; se o bot (filho) sobrar, TERM nele.
cd "$(dirname "$0")"
[ -f data/supervisor.pid ] || { echo "sem pidfile"; exit 0; }
p=$(cat data/supervisor.pid); kids=$(pgrep -P "$p")
kill "$p" 2>/dev/null || { echo "não estava rodando"; rm -f data/supervisor.pid; exit 0; }
for i in $(seq 45); do kill -0 "$p" 2>/dev/null || break; sleep 1; done
for k in $kids; do kill -0 "$k" 2>/dev/null && kill "$k"; done
rm -f data/supervisor.pid; echo "parado"
