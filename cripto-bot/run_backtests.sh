#!/usr/bin/env bash
# Refaz os backtests (90 dias) das 6 estratégias e gera o relatório do backtest.
# Opcional: ./run_backtests.sh 180  -> janela de 180 dias em data/backtest180.db (relatório: use os JSON *_lancamentos.json)
cd "$(dirname "$0")"
if [ -n "$1" ] && [ "$1" != "90" ]; then DB=data/backtest$1.db
  .venv/bin/python backtest.py --days "$1" --db $DB && .venv/bin/python fomo_backtest.py --db $DB && .venv/bin/python fomo_lanc_backtest.py --db $DB
else
  .venv/bin/python backtest.py && .venv/bin/python fomo_backtest.py && .venv/bin/python fomo_lanc_backtest.py && .venv/bin/python report.py --backtest
fi
