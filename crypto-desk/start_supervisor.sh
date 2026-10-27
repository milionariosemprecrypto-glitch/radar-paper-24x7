#!/usr/bin/env bash
# Idempotente: inicia supervise.sh só se não houver um vivo. NÃO executado na Fase 6 (aguarda janela).
cd "$(dirname "$0")"; mkdir -p data logs
exec 9>data/supervise.lock; flock -n 9 || { echo "outro start em andamento"; exit 0; }
p=$(cat data/supervise.pid 2>/dev/null)
if [ -n "$p" ] && kill -0 "$p" 2>/dev/null && tr '\0' ' ' </proc/$p/cmdline | grep -q supervise.sh; then echo "já rodando (pid $p)"; exit 0; fi
setsid nohup ./supervise.sh >> "${SUP_LOG:-logs/desk_supervisor.log}" 2>&1 </dev/null 9>&- &
echo $! > data/supervise.pid; echo "iniciado (pid $!)"
