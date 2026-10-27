#!/usr/bin/env bash
# Idempotente: inicia o supervisor só se não estiver rodando (pid vivo E é run.sh deste diretório). flock evita corrida.
cd "$(dirname "$0")"; mkdir -p data logs
exec 9>data/start.lock; flock -n 9 || { echo "outro start.sh em andamento"; exit 0; }
alive() { local p=$1; [ -n "$p" ] && kill -0 "$p" 2>/dev/null && tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -q "run.sh" && [ "$(readlink /proc/$p/cwd)" = "$(pwd -P)" ]; }
if [ -f data/supervisor.pid ] && alive "$(cat data/supervisor.pid)"; then
  echo "já rodando (pid $(cat data/supervisor.pid))"; exit 0; fi
other=$(pgrep -f "bash ./run.sh" | while read p; do [ "$(readlink /proc/$p/cwd)" = "$(pwd -P)" ] && echo $p; done | head -1)
if [ -n "$other" ]; then echo "$other" > data/supervisor.pid; echo "já rodando (pid $other, pidfile corrigido)"; exit 0; fi
setsid nohup ./run.sh >> "${SUP_LOG:-logs/supervisor.log}" 2>&1 < /dev/null 9>&- &
echo $! > data/supervisor.pid; echo "iniciado (pid $!)"
