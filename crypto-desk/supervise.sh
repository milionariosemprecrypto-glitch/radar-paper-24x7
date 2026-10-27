#!/usr/bin/env bash
# Supervisor do crypto-desk (Fase 6) — NÃO ATIVO por padrão. Ver docs/SUPERVISAO.md para ativar numa janela.
# - checa /health a cada CHECK_EVERY_S; reinicia só após FAILS_BEFORE_RESTART falhas seguidas
# - grace de START_GRACE_S após cada start; backoff exponencial; máx MAX_RESTARTS_PER_HOUR, depois pausa COOLDOWN_S
# - se já existe um desk saudável que NÃO foi iniciado por este script, só monitora; não mata processo externo
#   (a menos que ADOPT_KILL_EXTERNAL=1, decisão explícita de janela)
cd "$(dirname "$0")"
PORT=${PORT:-8000}; HOST=${HOST:-0.0.0.0}; URL=${DESK_URL:-http://127.0.0.1:$PORT}
CHECK_EVERY_S=${CHECK_EVERY_S:-30}; FAILS_BEFORE_RESTART=${FAILS_BEFORE_RESTART:-3}; START_GRACE_S=${START_GRACE_S:-90}
BACKOFF_MIN_S=${BACKOFF_MIN_S:-10}; BACKOFF_MAX_S=${BACKOFF_MAX_S:-600}; MAX_RESTARTS_PER_HOUR=${MAX_RESTARTS_PER_HOUR:-5}; COOLDOWN_S=${COOLDOWN_S:-1800}
DESK_CMD=${DESK_CMD:-".venv/bin/uvicorn app.main:app --host $HOST --port $PORT"}
LOG=${SUP_LOG:-logs/desk_supervisor.log}; mkdir -p "$(dirname "$LOG")" data
log() { echo "$(date '+%F %T %z') [desk-sup $$] $*" >> "$LOG"; }
CHILD=""; trap 'log "sinal recebido; parando filho ${CHILD:-nenhum}"; [ -n "$CHILD" ] && kill $CHILD 2>/dev/null && wait $CHILD 2>/dev/null; exit 0' TERM INT
health() { python3 desk_health.py "$URL" 5; }
port_pid() { ss -ltnp 2>/dev/null | grep ":$PORT " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1; }
backoff=$BACKOFF_MIN_S; starts=(); fails=0; attempt=0
while true; do
  if [ -z "$CHILD" ] || ! kill -0 "$CHILD" 2>/dev/null; then
    ext=$(port_pid)
    if [ -n "$ext" ] && [ "$ext" != "$CHILD" ]; then
      out=$(health)
      if [ $? -eq 0 ]; then [ "$last_ext" != "ok$ext" ] && log "desk externo pid $ext saudável ($out) — só monitorando (loga só na mudança)"; last_ext="ok$ext"; fails=0; sleep "$CHECK_EVERY_S"; continue; fi
      last_ext=fail; fails=$((fails+1)); log "desk externo pid $ext falhou ($out) [$fails/$FAILS_BEFORE_RESTART]"
      if (( fails < FAILS_BEFORE_RESTART )); then sleep "$CHECK_EVERY_S"; continue; fi
      if [ "${ADOPT_KILL_EXTERNAL:-0}" != 1 ]; then log "NÃO mato processo externo (ADOPT_KILL_EXTERNAL!=1) — intervenção manual"; sleep "$CHECK_EVERY_S"; continue; fi
      log "ADOPT_KILL_EXTERNAL=1: TERM no pid externo $ext"; kill "$ext"; sleep 5
    fi
    now=$(date +%s); r=(); for t in "${starts[@]}"; do (( now - t < 3600 )) && r+=("$t"); done; starts=("${r[@]}")
    if (( ${#starts[@]} >= MAX_RESTARTS_PER_HOUR )); then log "LIMITE ${#starts[@]} starts/h — pausa ${COOLDOWN_S}s"; sleep "$COOLDOWN_S"; starts=(); continue; fi
    (( attempt > 0 )) && { log "aguardando backoff ${backoff}s"; sleep "$backoff"; backoff=$((backoff*2)); (( backoff > BACKOFF_MAX_S )) && backoff=$BACKOFF_MAX_S; }
    attempt=$((attempt+1)); $DESK_CMD >> logs/desk_uvicorn.log 2>&1 & CHILD=$!; start=$(date +%s); starts+=("$start"); fails=0
    echo "$CHILD" > data/desk_child.pid; log "tentativa #$attempt: desk iniciado pid $CHILD ($DESK_CMD)"
  fi
  sleep "$CHECK_EVERY_S"
  kill -0 "$CHILD" 2>/dev/null || { log "desk pid $CHILD morreu"; continue; }
  (( $(date +%s) - start < START_GRACE_S )) && continue
  out=$(health)
  if [ $? -eq 0 ]; then fails=0; (( $(date +%s) - start > 1800 )) && backoff=$BACKOFF_MIN_S; continue; fi
  fails=$((fails+1)); log "health falhou ($out) [$fails/$FAILS_BEFORE_RESTART]"
  if (( fails >= FAILS_BEFORE_RESTART )); then log "reiniciando pid $CHILD"; kill "$CHILD"; sleep 5; kill -9 "$CHILD" 2>/dev/null; wait "$CHILD" 2>/dev/null; fi
done
