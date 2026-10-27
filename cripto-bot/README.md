# cripto-bot — PAPER TRADING (dinheiro fictício, preços reais)
Sem chaves de API, sem ordens reais. Dados: Binance pública (data-api.binance.vision) + CoinGecko pública.

Estratégias (1000 USDT virtuais cada; taxa 0,1%/trade; slippage 0,05% BTC, 0,3% FOMO):
1. grid — 20 faixas geométricas entre mín/máx dos 30 dias anteriores ao início (fixas). Ao vivo usa candles de 1m.
2. dca — 100 USDT/semana em BTC (backtest: 1000/13 por semana).
3. ema_20_50 — 100% BTC quando EMA20>EMA50 (1h), zera no cruzamento para baixo.
4. hold — compra tudo no início.
5. fomo — diariamente 21:00 BRT até 3 altcoins (trending CoinGecko + altas 24h/7d + narrativas), saída +20% / -10% / 3 dias.
6. fomo_lancamentos (fomo_lancamentos.py) — só moedas LISTADAS na Binance há 1–30 dias (1ª vela do par USDT e de qualquer outro par),
   sem stablecoins e sem ações/ETFs tokenizados (bStocks); volume 24h Binance ≥ US$5M; precisa de sinal de narrativa
   (trending CoinGecko, categoria top-10 em alta 24h, ou narrativa quente — IA, memes, RWA, ações tokenizadas/Robinhood, perps, DePIN… — subindo).
   Máx. 3 posições (caixa ÷ vagas livres), cada moeda 1 vez, varredura diária 21:00 BRT. Saída: +50% alvo / -25% stop / 14 dias.
   Taxa 0,1% + slippage 0,4%. Última varredura (aprovadas/rejeitadas com motivo) fica em kv 'lanc_last_scan' e no relatório.
   Cache de datas de listagem: data/cache/listings.json. Backtest proxy: fomo_lanc_backtest.py (sem filtro de narrativa).

Comandos:
- ./start.sh            inicia (idempotente; rode após reboot do box)
- ./stop.sh             para
- .venv/bin/python report.py             relatório ao vivo -> reports/relatorio_live.md + grafico_live.png + trades_live.csv
- .venv/bin/python report.py --backtest  relatório do backtest
- ./run_backtests.sh    refaz os backtests de 90 dias (todas as 6) e o relatório; ./run_backtests.sh 180 = janela de 180 dias
Logs: logs/bot.log (todo trade, PICK e SNAP), logs/supervisor.log. Estado: data/live.db (SQLite), data/heartbeat.json.
