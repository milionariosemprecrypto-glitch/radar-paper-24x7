#!/usr/bin/env bash
# Supervisor (Fase 6 + mitigaçao suspend): reinicia o bot se cair OU se o heartbeat ficar ausente/ilegível/antigo.
# - grace: nos primeiros HB_GRACE_S após cada start, ausência/heartbeat antigo NÃO causa restart (inicialização legítima)
# - backoff exponencial entre reinícios (BACKOFF_MIN_S..BACKOFF_MAX_S), zera após rodar saudável por HEALTHY_RESET_S
# - sleep por relógio de parede (date +%s): se o box suspender no meio do sleep, ao acordar o restante é pulado
# - STALE com idade >> HB_MAX_AGE_S: trata como wake de suspend → backoff volta ao mínimo
# - limite: >MAX_RESTARTS_PER_HOUR reinícios em 1h => pausa COOLDOWN_S (sem loop infinito) e loga
# - cada tentativa vai para logs/supervisor.log
cd "$(dirname "$0")"
HB_FILE=${HB_FILE:-data/heartbeat.json}
HB_MAX_AGE_S=${HB_MAX_AGE_S:-600}
HB_GRACE_S=${HB_GRACE_S:-300}
CHECK_EVERY_S=${CHECK_EVERY_S:-30}
BACKOFF_MIN_S=${BACKOFF_MIN_S:-15}
BACKOFF_MAX_S=${BACKOFF_MAX_S:-600}
HEALTHY_RESET_S=${HEALTHY_RESET_S:-1800}
MAX_RESTARTS_PER_HOUR=${MAX_RESTARTS_PER_HOUR:-6}
COOLDOWN_S=${COOLDOWN_S:-1800}
BOT_CMD=${BOT_CMD:-".venv/bin/python bot.py"}
PY=${PY:-python3}
LOG=${SUP_LOG:-logs/supervisor.log}
mkdir -p "$(dirname "$LOG")"
log() { echo "$(date '+%F %T %z') [sup $$] $*" >> "$LOG"; }
# sleep que respeita relógio de parede (sobrevive a suspend do host)
sleep_wall() {
  local secs=$1 end
  end=$(( $(date +%s) + secs ))
  while (( $(date +%s) < end )); do
    sleep 5
  done
}
trap 'log "sinal recebido, parando bot pid $CHILD"; kill $CHILD 2>/dev/null; wait $CHILD 2>/dev/null; exit 0' TERM INT
backoff=$BACKOFF_MIN_S; starts=()
attempt=0
while true; do
  now=$(date +%s); recent=()
  for t in "${starts[@]}"; do (( now - t < 3600 )) && recent+=("$t"); done; starts=("${recent[@]}")
  if (( ${#starts[@]} >= MAX_RESTARTS_PER_HOUR )); then
    log "LIMITE: ${#starts[@]} starts na última hora (max $MAX_RESTARTS_PER_HOUR) — pausa ${COOLDOWN_S}s antes de tentar de novo"
    sleep_wall "$COOLDOWN_S"; starts=(); continue
  fi
  attempt=$((attempt+1)); start=$(date +%s); starts+=("$start")
  $BOT_CMD & CHILD=$!
  log "tentativa #$attempt: bot iniciado pid $CHILD (grace ${HB_GRACE_S}s, max_age ${HB_MAX_AGE_S}s)"
  reason="saiu sozinho"
  while kill -0 "$CHILD" 2>/dev/null; do
    sleep_wall "$CHECK_EVERY_S"
    kill -0 "$CHILD" 2>/dev/null || break
    out=$($PY hb_check.py "$HB_FILE" "$CHILD" "$start" "$HB_MAX_AGE_S" "$HB_GRACE_S" 2>&1); rc=$?
    if (( rc != 0 )); then
      reason="watchdog: $out"; log "$reason — matando pid $CHILD"
      kill "$CHILD" 2>/dev/null; sleep 5; kill -9 "$CHILD" 2>/dev/null; break
    fi
  done
  wait "$CHILD" 2>/dev/null; code=$?
  ran=$(( $(date +%s) - start ))
  (( ran >= HEALTHY_RESET_S )) && backoff=$BACKOFF_MIN_S
  # Suspend wake: STALE com idade muito maior que o limite → não é crash loop, zera backoff
  if [[ "$reason" =~ idade[[:space:]]+([0-9]+) ]]; then
    stale_age=${BASH_REMATCH[1]}
    if (( stale_age > HB_MAX_AGE_S * 2 )); then
      log "suspeita de suspend (STALE idade ${stale_age}s) — reset backoff para ${BACKOFF_MIN_S}s"
      backoff=$BACKOFF_MIN_S
    fi
  fi
  log "bot pid $CHILD terminou (code $code, rodou ${ran}s, motivo: $reason); reinício em ${backoff}s"
  sleep_wall "$backoff"
  backoff=$(( backoff * 2 )); (( backoff > BACKOFF_MAX_S )) && backoff=$BACKOFF_MAX_S
done
