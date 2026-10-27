"""Gera resumo em pt-BR (markdown) + gráfico PNG + CSV de trades.
Uso: .venv/bin/python report.py            # paper-trading ao vivo (data/live.db)
     .venv/bin/python report.py --backtest # backtest (data/backtest.db)"""
import argparse, os, sqlite3, csv, json, time
from datetime import datetime, timezone, timedelta
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
import engine as E, fomo_lancamentos as FL

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); a = ap.parse_args()
mode = "backtest" if a.backtest else "live"
db = E.open_db(os.path.join(HERE, "data", f"{mode}.db"))
meta = E.kv_get(db, "meta", {})
BRT = timezone(timedelta(hours=-3))
fmt = lambda ms: datetime.fromtimestamp(ms / 1000, BRT).strftime("%d/%m/%Y %H:%M")
br = lambda x, d=2: f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
NAMES = {"grid": "Grid (faixa 30d)", "dca": "DCA semanal", "ema_20_50": "Tendência EMA 20/50 (1h)", "hold": "Buy & Hold (base)", "fomo": "FOMO/narrativas (altcoins)", FL.NAME: "FOMO lançamentos (novas listagens)"}
SLIPS = {"fomo": 0.003, FL.NAME: FL.SLIP}

# preço atual / última marcação
last_ts, price = db.execute("SELECT ts, price FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
if mode == "live":
    try: price = E.ticker(); last_ts = int(time.time() * 1000)
    except Exception: pass
try: brl = E.ticker("USDTBRL")
except Exception: brl = None
state = E.kv_get(db, "state", {})

rows, series = [], {}
prices_all = {}
if mode == "live":
    try: prices_all = {x["symbol"]: float(x["price"]) for x in E._get("/api/v3/ticker/price", {})}
    except Exception: pass
for s in ["grid", "dca", "ema_20_50", "hold", "fomo", FL.NAME]:
    eq = db.execute("SELECT ts, equity FROM equity WHERE strategy=? ORDER BY ts", (s,)).fetchall()
    if not eq: continue
    pf = state.get(s, {}).get("pf", {"usdt": 0, "btc": 0})
    if "positions" in pf:
        cur = pf["usdt"] + sum(p["qty"] * prices_all.get(sym, p["entry"]) for sym, p in pf.get("positions", {}).items()) if mode == "live" else eq[-1][1]
        pf = {**pf, "btc": 0}
    else:
        cur = pf["usdt"] + pf["btc"] * price
    eq = eq + [(last_ts, cur)]
    peak, mdd = -1, 0.0
    for _, v in eq:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak)
    n, fees, vol = db.execute("SELECT COUNT(*), COALESCE(SUM(fee),0), COALESCE(SUM(quote),0) FROM trades WHERE strategy=?", (s,)).fetchone()
    series[s] = eq
    rows.append(dict(s=s, eq=cur, pnl=cur - E.CAPITAL, pct=(cur / E.CAPITAL - 1) * 100, n=n, fees=fees, slip=vol * SLIPS.get(s, E.SLIP), mdd=mdd * 100, pos=pf.get("positions"),
                     btc=pf["btc"], usdt=pf["usdt"]))
hold_pct = next(r["pct"] for r in rows if r["s"] == "hold")

os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
png = os.path.join(HERE, "reports", f"grafico_{mode}.png"); md = os.path.join(HERE, "reports", f"relatorio_{mode}.md")
csvp = os.path.join(HERE, "reports", f"trades_{mode}.csv")

# gráfico
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
for s, eq in series.items():
    ax1.plot([datetime.fromtimestamp(t / 1000, BRT) for t, _ in eq], [v for _, v in eq], label=NAMES[s], lw=1.4)
ax1.axhline(E.CAPITAL, color="gray", ls="--", lw=0.8); ax1.set_ylabel("Patrimônio (USDT)"); ax1.legend(); ax1.grid(alpha=.3)
ax1.set_title(f"Paper-trading BTC/USDT – {'Backtest' if mode=='backtest' else 'Ao vivo'} (dinheiro fictício)")
pr = db.execute("SELECT ts, price FROM equity WHERE strategy='hold' ORDER BY ts").fetchall()
ax2.plot([datetime.fromtimestamp(t / 1000, BRT) for t, _ in pr], [p for _, p in pr], color="black", lw=1)
if meta.get("grid_lo"):
    ax2.axhspan(meta["grid_lo"], meta["grid_hi"], color="orange", alpha=.15, label="faixa do grid")
    ax2.legend(loc="upper left")
ax2.set_ylabel("BTC (USDT)"); ax2.grid(alpha=.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m", tz=BRT)); fig.tight_layout(); fig.savefig(png, dpi=110); plt.close(fig)

# CSV de trades
with open(csvp, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["data_hora_BRT", "estrategia", "moeda", "lado", "preco", "qtd_btc", "valor_usdt", "taxa_usdt", "nota"])
    for ts, s, sym, side, p, q, quote, fee, note in db.execute("SELECT ts,strategy,symbol,side,price,qty,quote,fee,note FROM trades ORDER BY ts, id"):
        w.writerow([fmt(ts), s, sym, side, round(p, 6), round(q, 8), round(quote, 2), round(fee, 4), note])

start = meta.get("start", series["hold"][0][0])
L = [f"# Relatório de paper-trading – {'BACKTEST' if mode=='backtest' else 'AO VIVO'}",
     "", "> **Simulação com dinheiro fictício e preços reais.** Nenhuma ordem real, nenhuma chave de corretora.", "",
     f"- Período: {fmt(start)} → {fmt(last_ts)} (horário de Brasília) — {br((last_ts-start)/86400000,1)} dias",
     f"- BTC: {br(pr[0][1])} → **{br(price)} USDT** ({br((price/pr[0][1]-1)*100)}%)",
     f"- Capital inicial: {br(E.CAPITAL)} USDT por estratégia · taxa {br(E.FEE*100,1)}% por trade · slippage {br(E.SLIP*100)}%",
     f"- Faixa do grid (mín/máx 30 dias antes do início): {br(meta.get('grid_lo',0),0)} – {br(meta.get('grid_hi',0),0)} USDT, 20 faixas",
     f"- DCA: {br(meta.get('dca_amount',0))} USDT por semana", "",
     "| Estratégia | Patrimônio (USDT) | P&L (USDT) | P&L % | vs Hold (p.p.) | Trades | Taxas pagas | Slippage (est.) | Drawdown máx. |",
     "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
for r in rows:
    L.append(f"| {NAMES[r['s']]} | {br(r['eq'])} | {br(r['pnl'])} | {br(r['pct'])}% | {br(r['pct']-hold_pct)} | {r['n']} | {br(r['fees'])} | {br(r['slip'])} | {br(r['mdd'])}% |")
L += ["", "**Posição atual:** " + " · ".join(
    f"{NAMES[r['s']]}: " + (", ".join(f"{k} ({br(v['qty'],4)})" for k, v in r["pos"].items()) or "nenhuma moeda") + f" + {br(r['usdt'])} USDT"
    if r["pos"] is not None else f"{NAMES[r['s']]}: {br(r['btc'],6)} BTC + {br(r['usdt'])} USDT" for r in rows)]
fr = next((r for r in rows if r["s"] == "fomo"), None)
if fr:
    ex = db.execute("SELECT CASE WHEN note LIKE 'stop%' THEN 'stop -10%' WHEN note LIKE 'take%' THEN 'alvo +20%' ELSE 'tempo 3d' END, COUNT(*) FROM trades WHERE strategy='fomo' AND side='SELL' GROUP BY 1").fetchall()
    L += ["", "## FOMO/narrativas",
          "- Regras: escolha diária às 21:00 BRT (00:00 UTC) de até 3 altcoins (cotas iguais do caixa livre); saída em +20%, -10% ou 3 dias. Taxa 0,1% + slippage 0,3% por lado.",
          "- Seleção ao vivo: CoinGecko trending + percentil de alta 24h/7d + top moedas das 5 narrativas/categorias que mais subiram; exige volume global > US$50M, par USDT na Binance com volume > US$5M e alta em 24h. BTC/ETH e stablecoins ficam de fora.",
          "- Saídas: " + (", ".join(f"{k}: {v}" for k, v in ex) or "nenhuma ainda")]
    if mode == "backtest":
        L += ["- **Backtest é um PROXY**, não a estratégia real: não há histórico gratuito do trending da CoinGecko/narrativas. "
              "Proxy = comprar as 3 maiores altas do dia anterior entre ~200 moedas de maior volume na Binance (volume do dia anterior ≥ US$20M na Binance).",
              "- **Viés de sobrevivência:** o universo é o das moedas listadas e com volume HOJE; moedas que foram deslistadas ou morreram no período não entram, o que tende a deixar o resultado MELHOR do que seria na realidade.",
              "- Stop e alvo checados em velas de 1h; se ambos na mesma vela, assume-se o stop (conservador). Gaps executam no preço de abertura."]
    pk = db.execute("SELECT ts, symbol, score, reason FROM picks WHERE strategy='fomo' ORDER BY ts DESC LIMIT 12").fetchall()
    if pk:
        L += ["", "Últimas escolhas:", "", "| Data/hora (BRT) | Moeda | Score | Motivo |", "|---|---|---:|---|"]
        L += [f"| {fmt(ts)} | {sym} | {br(sc)} | {why} |" for ts, sym, sc, why in pk]
lr = next((r for r in rows if r["s"] == FL.NAME), None)
if lr:
    ex = db.execute("SELECT CASE WHEN note LIKE 'stop%' THEN 'stop -25%' WHEN note LIKE 'take%' THEN 'alvo +50%' ELSE 'tempo 14d' END, COUNT(*) FROM trades WHERE strategy=? AND side='SELL' GROUP BY 1", (FL.NAME,)).fetchall()
    L += ["", "## FOMO lançamentos (novas listagens)",
          "- Regras: só moedas cujo par USDT (e qualquer outro par) estreou na Binance há 1–30 dias; fora stablecoins e ações/ETFs tokenizados (bStocks). "
          "Exige volume 24h na Binance ≥ US$5M e sinal de narrativa (trending CoinGecko, ou categoria entre as 10 que mais sobem em 24h, ou narrativa quente — IA, memes, RWA, ações tokenizadas/Robinhood, perps, DePIN… — subindo em 24h).",
          "- Máx. 3 posições (caixa livre ÷ vagas livres), cada moeda 1 vez; escolha diária às 21:00 BRT. Saída: alvo +50%, stop -25%, ou 14 dias. Taxa 0,1% + slippage 0,4% por lado.",
          "- Saídas: " + (", ".join(f"{k}: {v}" for k, v in ex) or "nenhuma ainda")]
    if mode == "backtest":
        L += ["- **Backtest é um PROXY**: o filtro de narrativa não pode ser reproduzido no passado (sem histórico gratuito); o proxy compra as novas listagens de cripto com volume do dia anterior ≥ US$5M. "
              "Universo pequeno (poucas listagens de cripto no período) ⇒ resultado estatisticamente fraco. Classificação cripto/ação/renome usa dados de HOJE da CoinGecko; pares deslistados que sumiram da Binance não entram (viés de sobrevivência)."]
    else:
        sc = E.kv_get(db, "lanc_last_scan")
        if sc:
            L += ["", f"Última varredura ({fmt(sc['ts'])} BRT): {len(sc['ranked'])} aprovada(s), {len(sc['rejected'])} rejeitada(s)."]
            L += [f"- ✅ {sym} (score {br(scr)}): {why}" for sym, scr, why in sc["ranked"][:5]]
            L += [f"- ❌ {sym}: {why}" for sym, why in sc["rejected"] if "ação/ETF" not in why][:10]
            ns = sum(1 for _, why in sc["rejected"] if "ação/ETF" in why)
            if ns: L += [f"- ❌ {ns} ações/ETFs tokenizados (bStocks) ignorados"]
    pk = db.execute("SELECT ts, symbol, score, reason FROM picks WHERE strategy=? ORDER BY ts DESC LIMIT 12", (FL.NAME,)).fetchall()
    if pk:
        L += ["", "Últimas escolhas:", "", "| Data/hora (BRT) | Moeda | Score | Motivo |", "|---|---|---:|---|"]
        L += [f"| {fmt(ts)} | {sym} | {br(sc_)} | {why} |" for ts, sym, sc_, why in pk]
if brl: L += ["", f"Cotação USDT/BRL: {br(brl)} → patrimônio aprox. em R$: " + ", ".join(f"{NAMES[r['s']]} R$ {br(r['eq']*brl)}" for r in rows)]
best = max(rows, key=lambda r: r["pct"])
L += ["", "## Leitura honesta",
      f"- Melhor no período: **{NAMES[best['s']]}** ({br(best['pct'])}%).",
      "- Drawdown = maior queda do pico ao vale do patrimônio no período.",
      "- 'Taxas pagas' = só a taxa de 0,1%; o slippage já está embutido nos preços de execução (coluna estimada à parte).",
      "- Período curto não prova nada: o resultado depende muito da direção do mercado (alta favorece hold/DCA; lateral favorece grid).",
      "- Grid fica parado se o preço sai da faixa (acima: tudo em USDT; abaixo: tudo em BTC).",
      "- O DCA não investe todo o capital no início; o USDT parado conta no patrimônio.",
      "", f"![gráfico]({os.path.basename(png)})", "", f"Trades detalhados: `{os.path.basename(csvp)}`"]
open(md, "w").write("\n".join(L) + "\n")
print(open(md).read()); print("PNG:", png); print("CSV:", csvp)
