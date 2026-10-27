# Crypto Antecipation Desk — Plano técnico (pt-BR)

> **Somente PAPER/SIMULAÇÃO.** Nenhuma ordem real é enviada, não existe chave de corretora no sistema e a alavancagem máxima é 3x (`MAX_LEVERAGE`). Custo atual: **R$ 0**.

## 1. Objetivo e escopo
Ver antes de entrar: derivativos, liquidações, baleias, fluxo e notícias juntos, para scalp de 15m em BTC, ETH, SOL, XRP e DOGE (`ASSETS` no .env). O sistema gera **alertas de atenção** e **sinais de entrada** (simulados), e cada um vem com uma explicação simples.

## 2. Arquitetura
```
 Corretoras (REST+WS grátis)   Whale Alert (Telegram público)   RSS de notícias   [Pagos: Coinglass/WhaleAlert/X se houver chave]
        │                              │                              │                     │
        └──────────── providers/ (cada um em seu loop async; se a fonte bloquear → "bloqueado" e o resto segue) ─────┘
                                              │
                                     state.py (memória) + SQLite (data/desk.sqlite)
                                              │
                engine/ a cada 5s: features → score → sinais → risco → ledger paper → alertas
                                              │
                    FastAPI (main.py): /api/*, /ws (push 2s) → static/index.html (painel, 7 abas)
                                              │
                               alerts.py → Telegram/Discord (só se as chaves existirem)
```

## 3. Fontes de dados (verificadas na documentação oficial e testadas daqui)
| Dado | Fonte usada AGORA (grátis) | Status |
|---|---|---|
| Preço, candles 1m/5m/15m/1h/4h | OKX `/api/v5/market/candles`, WS `tickers` | ao vivo |
| Trades → CVD/agressão | OKX WS `trades` | ao vivo |
| Book | OKX WS `books5` + REST `/market/books` (sz 400) | ao vivo |
| OI | OKX `/public/open-interest` + `rubik/stat/contracts/open-interest-volume`; Bitget `/api/v2/mix/market/ticker`; Gate `/api/v4/futures/usdt/contracts/{c}` (OI = position_size × quanto_multiplier × mark); Hyperliquid `POST /info {"type":"metaAndAssetCtxs"}` | ao vivo |
| Funding (atual/histórico) | OKX `/public/funding-rate`, `/funding-rate-history`; Bitget; Gate; Hyperliquid (taxa horária, mostrada ×8) | ao vivo |
| Basis | OKX mark (`/public/mark-price`) vs índice (`/market/index-tickers`) | ao vivo |
| Long/Short | OKX `rubik/stat/contracts/long-short-account-ratio` | ao vivo |
| Liquidações | OKX WS `liquidation-orders` + REST `/public/liquidation-orders`; Binance WS `!forceOrder@arr`; Bybit WS `allLiquidation.{symbol}` | ao vivo (WS conectam) |
| Binance/Bybit REST (OI/funding) | `fapi.binance.com`, `api.bybit.com` | **bloqueado por região (451/403)** daqui; desliga sozinho. No PC do Julio no Brasil deve funcionar |
| Baleias | `t.me/s/whale_alert_io` (página pública do canal) | ao vivo (atraso de minutos) |
| Notícias/narrativa | RSS Cointelegraph + Google News (buscas: Trump crypto, tarifas, Fed, ETF…) | ao vivo |

### Fontes PAGAS (desligadas; ligam sozinhas se a chave existir no .env)
| Provedor | Endpoints | Preço (site oficial, out/2026) |
|---|---|---|
| Coinglass API V4 | `/api/futures/open-interest/exchange-list`, `/api/futures/funding-rate/exchange-list`, `/api/futures/liquidation/exchange-list` (todos os planos) | Hobbyist **US$ 29/mês** |
| Coinglass heatmap/mapa | `/api/futures/liquidation/aggregated-heatmap/model2`, `/aggregated-map` | só Professional **US$ 699/mês** |
| Coinglass baleias | `/api/chain/v2/whale-transfer`, `/api/hyperliquid/whale-alert` | Startup ou superior |
| Whale Alert | WS `wss://leviathan.whale-alert.io/ws` (mín. US$100k) | Alerts API **US$ 29,95/mês** |
| X (Twitter) API v2 | `/2/users/by`, `/2/users/:id/tweets` (a cada 5 min) | pay-per-use **~US$ 0,005 por post lido** |

**Recomendação:** não pague nada agora. A versão grátis cobre ~90%. Se for pagar algo um dia, o Coinglass Hobbyist (US$ 29) é o que mais agrega (OI/liquidações agregadas de muitas corretoras), mas o heatmap real continua fora desse plano.

## 4. Estrutura de pastas
```
crypto-desk/
  app/config.py        variáveis (.env); TRADING_MODE fixo = PAPER
  app/main.py          FastAPI, loops, API e WebSocket
  app/state.py, logs.py, schema_sqlite.sql, alerts.py
  app/providers/       okx, exchanges (bitget/gate/hyperliquid/binance/bybit), whales_free, whalealert*, news_rss, xapi*, coinglass*   (*pago)
  app/engine/          indicators, features, classify, heatmap, score, signals, risk
  app/static/index.html painel
  tests/test_engine.py  14 testes
  shots/                screenshots + take.py
  deploy/schema.sql     TimescaleDB p/ PC dedicado
  Dockerfile, docker-compose.yml, requirements.txt, run.sh, .env.example
```

## 5. Modelo de dados
O SQLite local (`app/schema_sqlite.sql`) e o TimescaleDB (`deploy/schema.sql`) têm as mesmas tabelas: candles, derivs, liquidations, whale_events, news, scores, signals, alerts, paper_trades. Os dados quentes (book, trades, CVD) ficam em memória (`state.py`). O Redis já está no compose para uma próxima etapa.

## 6. Motor de score (−100 a +100)
| Fator | Peso | Lógica |
|---|---|---|
| Tendência (EMA 9/21 em 15m, alinhamento com 1h) | 20 | |
| OI × preço | 15 | OI↑ preço↑ = continuação (+). OI↑ preço↓ = pressão vendedora (−). OI↓ = fechamento/short covering (fraco) |
| Funding | 10 | funding extremo = multidão de um lado = contra |
| Long/Short | 5 | contrário quando extremo |
| Liquidações | 10 | liquidação grande de um lado = exaustão / squeeze |
| Clusters (heatmap estimado) | 10 | ímã de liquidez acima/abaixo |
| CVD/agressão | 15 | ignorado nos primeiros 15 min ("aquecendo") |
| Book | 5 | desequilíbrio ±0,5% |
| Baleias | 5 | entrada em corretora = risco de venda; saída = acumulação |
| Notícias | 5 | só pesa com confirmação |

- **Status:** ≥60 LONG FORTE, ≥30 LONG MODERADO, entre −30 e 30 NEUTRO, ≤−30 SHORT MODERADO, ≤−60 SHORT FORTE.
- **Funding extremo** (≥0,05% ou ≤−0,03% a cada 8h) na direção da multidão: confiança ×0,7.
- **Multiplicadores de volatilidade e liquidez** (×0,8 cada): ATR <0,08%, ATR >1,5%, profundidade <US$200k.

## 7. Regras de sinais
1. **Confluência** = um dos 6 grupos independentes (estrutura, derivativos, liquidez, fluxo, on-chain, narrativa) que concorda com o sinal do score e soma ≥35% do seu peso máximo.
2. Para ser **sinal de entrada**, o sinal precisa de |score| ≥ 30 **e ≥ 3 confluências**. Abaixo disso, vira no máximo um **alerta de atenção**.
3. Uma notícia ou tweet de alto impacto gera só um **alerta** até que preço (tendência), volume (≥1,3× a média) e CVD confirmem.
4. **Entrada:** reteste da EMA21 ou rompimento com volume.
5. **Invalidação:** swing de 8 candles ± 0,25 ATR.
6. **Alvos:** T1/T2 nos clusters de liquidez; se não houver, 1R/2R.
7. **Risco:** 0,5% da banca (score ≥60 e ≥4 confluências), senão 0,25%. Alavancagem = min(3, risco/stop).

## 8. Heatmap de liquidações (ESTIMATIVA)
O heatmap real do Coinglass é pago (US$699). O nosso é feito assim: o OI novo das últimas ~24h, distribuído pelo preço em que entrou, é projetado em alavancagens típicas (5x 25%, 10x 35%, 25x 25%, 50x 15%). A divisão long/short usa a razão de contas da OKX, e as liquidações reais aparecem por cima, em amarelo. **O selo "ESTIMATIVA" aparece sempre.** É um mapa aproximado dos "ímãs" de liquidez, não dado real de posições.

## 9. Gestão de risco (paper)
- Limite de perda diária: 1,5%.
- Máximo de 4 trades por dia.
- Pausa de 30 min entre trades.
- Pausa após 2 perdas seguidas.
- O stop vai para o break-even quando o T1 é atingido.
- Timeout de 4h por trade.
- O ledger mede o resultado em R.

## 10. Alertas
- Canais: Telegram (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) e Discord (`DISCORD_WEBHOOK_URL`).
- Sem chave, os alertas aparecem só no painel.
- Anti-spam: o mesmo alerta não se repete por 30 min.

## 11. Implantação, limitações e próximos passos
- **Agora:** `./run.sh` (sem Docker) → http://localhost:8000.
- **PC dedicado:** `docker compose up -d --build`.
- Limitações:
  - Binance/Bybit REST bloqueados no servidor de teste.
  - Whale Alert pelo Telegram tem atraso e não informa mint/burn de stablecoin com detalhe.
  - O RSS substitui o X: posts do Trump e do Musk só chegam quando viram notícia.
  - O heatmap é estimado.
  - Os nomes dos campos do WS pago da Whale Alert não foram verificados com uma chave real.
- Próximos passos:
  - Persistir no Timescale.
  - Fazer backtest do score com o histórico salvo.
  - Calibrar os pesos com o ledger paper.
