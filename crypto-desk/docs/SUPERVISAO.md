# Supervisão do crypto-desk (Fase 6, 2026-10-26)

Estado atual: uvicorn pid 359652 (iniciado 25/10 19:45 BRT, `--host 0.0.0.0 --port 8000`) **sem supervisor**.
`supervise.sh` / `start_supervisor.sh` estão prontos e testados contra um servidor falso (porta 18777), **não ativados**.

## Comportamento
- `/health` (desk_health.py): HTTP 200, `ok=true` e ≥1 ativo ao vivo; senão falha.
- Reinicia só após `FAILS_BEFORE_RESTART` (3) falhas seguidas; grace `START_GRACE_S` (90s) após cada start.
- Backoff 10s→600s; máx `MAX_RESTARTS_PER_HOUR` (5) e depois pausa `COOLDOWN_S` (1800s). Log: `logs/desk_supervisor.log`.
- Se já houver desk saudável na porta que ele não iniciou: **só monitora**. Se o externo ficar ruim, **não mata** sem `ADOPT_KILL_EXTERNAL=1`.

## Ativar numa janela (manual)
1. Janela: anotar `curl -s localhost:8000/api/paper` (estado do RiskGuard/caderno é em memória e **zera** no restart).
2. Opção A (sem downtime): `./start_supervisor.sh` — adota o desk atual em modo monitoramento.
3. Opção B (supervisor dono do processo; aplica custos da Fase 6): `kill 359652`; esperar porta livre; `./start_supervisor.sh`;
   conferir `python3 desk_health.py` e `tail logs/desk_supervisor.log`. Rollback: `kill $(cat data/supervise.pid)`; `./run.sh` ou uvicorn manual.
4. `run.sh` liga em 127.0.0.1; o processo atual usa 0.0.0.0 — supervise.sh usa HOST=0.0.0.0 por padrão para manter igual.

## Pós-reboot
Não há cron/systemd => nada sobe sozinho. Rodar: `/workspace/radar/scripts/boot_all.sh` (idempotente; `DESK_SUPERVISED=1` para subir o desk via supervisor).

## Fase 7 (2026-10-26) — plano de ativação com o uvicorn REAL (NÃO executado)
Pré-condição: autorização explícita do Julio para a janela. Nada abaixo foi rodado no desk de produção.
1. **Pré-checagem** (sem impacto): `.venv/bin/python -m pytest -q tests` (esperado 32 passed); `python3 desk_health.py http://127.0.0.1:8000 5`.
2. **Backup**: `B=/workspace/radar/backups/$(date +%Y%m%d-%H%M%S)`; cópia online do SQLite via `sqlite3.backup` (ver relatório Fase 7) + `curl -s localhost:8000/api/paper > $B/api_paper_memoria.json` + `sha256sum`.
3. **Backfill de fechamentos** (só após o backup; só UPDATE de linhas 'aberta' que a memória mostra 'fechada'):
   `.venv/bin/python scripts/backfill_closes_phase7.py --paper-json $B/api_paper_memoria.json` (dry-run) → conferir → repetir com `--apply`.
   Fazer o backfill com o processo antigo PARADO não é necessário (SQLite aceita escrita concorrente), mas a migração de colunas acontece no boot novo.
4. **Parar o processo antigo** (só com autorização): `kill -TERM <pid do uvicorn na :8000>` (hoje 359652; confirmar com `ss -ltnp | grep :8000`). Esperar porta livre.
5. **Subir via supervisor**: `./start_supervisor.sh` (HOST=0.0.0.0, mesmo comando). O supervisor tem grace 90s, 3 falhas antes de reiniciar, backoff 10→600s, máx 5 starts/h e pausa 30 min ⇒ sem loop de restart. Nunca mata processo externo sem `ADOPT_KILL_EXTERNAL=1`.
6. **Validação pós-boot** (≤5 min): `/health` ok; `curl -s localhost:8000/api/paper` deve ter `risco.estado.persistido=true`, `consistente=true`, `origem` = `reconstruido_paper_trades` (1º boot) e depois `sqlite`; `caderno.soma_R_liquido` presente; `persistencia.erros=0`; Radar `python3 -m coordinator.run_once` sem o erro "pré-Fase 7".
7. **Teste de restart controlado** (opcional na mesma janela): `kill $(cat data/desk_child.pid)` → supervisor sobe de novo → `risco` idêntico ao anterior (mesmos pnl_dia_pct/operacoes_hoje/perdas_seguidas/atualizado_ts).
8. **Rollback**: `kill $(cat data/supervise.pid)`; restaurar arquivos de `$B` (state.py, risk.py, main.py) e subir `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`. As colunas novas do SQLite são aditivas e ignoradas pelo código antigo (não precisa reverter o banco).
Logs: `logs/desk_supervisor.log` (tentativas/falhas), `logs/desk_uvicorn.log`. Modo continua PAPER (fixo em config.py).
Janela recomendada: manhã de dia útil com o Julio disponível (ex.: 09:00–09:30 BRT), longe da meia-noite SP (virada do dia de risco) e fora do período de suspensão noturna da box.
