"""Backtest PROXY da estratégia FOMO (não existe histórico gratuito do 'trending' da CoinGecko nem das narrativas).
Proxy: todo dia 00:00 UTC (21:00 BRT) preenche as vagas livres (máx. 3) com as maiores altas do dia anterior
entre as ~200 moedas de maior volume na Binance HOJE (=> viés de sobrevivência), exigindo volume do dia
anterior >= US$20M na Binance. Saídas (-10% / +20% / 72h) checadas em candles de 1h; se stop e alvo
caem na mesma vela, assume o stop (conservador). Taxa 0,1% + slippage 0,3% por lado.
Requer ter rodado backtest.py antes (usa o mesmo período). Uso: .venv/bin/python fomo_backtest.py [--db data/backtest.db]"""
import os, sys
import engine as E, fomo as F

HERE = os.path.dirname(os.path.abspath(__file__))
D = 86400_000; H = 3600_000; MIN_PREV_VOL = 20e6
db = E.open_db(sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else os.path.join(HERE, "data", "backtest.db"))
for t in ("trades", "equity"): db.execute(f"DELETE FROM {t} WHERE strategy='fomo'")
db.execute("DELETE FROM picks WHERE strategy='fomo'")
meta = E.kv_get(db, "meta"); start, end = meta["start"], meta["end"]

bn = F.binance_24h()
cg = set()
for page in (1, 2):
    cg |= {m["symbol"].upper() + "USDT" for m in F._cg("/coins/markets", vs_currency="usd", order="volume_desc", per_page=250, page=page) if not F.is_stock(m)}
syms = sorted((s for s in bn if s.endswith("USDT") and s[:-4] not in F.EXCLUDE and s in cg),
              key=lambda s: -float(bn[s]["quoteVolume"]))[:200]
print("universo:", len(syms), "símbolos", file=sys.stderr)

from concurrent.futures import ThreadPoolExecutor
def fetch(s):
    try:
        d = {b["t"]: b for b in E.klines("1d", start - 3 * D, end, symbol=s)}
        out, cur = [], start - D
        for _ in range(5):
            b = E.klines("1h", cur, end, symbol=s); out += b
            if len(b) < 1000: break
            cur = b[-1]["t"] + 1
        return s, d, {b["t"]: b for b in out}
    except Exception as e:
        print("falha", s, e, file=sys.stderr); return s, None, None
daily, hourly = {}, {}
with ThreadPoolExecutor(8) as ex:
    for s, d, h in ex.map(fetch, syms):
        if d: daily[s], hourly[s] = d, h
print("baixado:", len(daily), file=sys.stderr)
hbars = lambda s: hourly.get(s, {})

f = F.Fomo(on_trade=E.make_trade_logger(db))
lp = lambda ts, s, sc, why: db.execute("INSERT INTO picks(ts,symbol,score,reason,strategy) VALUES(?,?,?,?,?)", (ts, s, sc, why, "fomo"))
t = start - (start % H)
while t <= end:
    if t % D == 0 and t > start:
        prev = t - D
        ranked = sorted(((s, (b[prev]["c"] / b[prev]["o"] - 1) * 100) for s, b in daily.items()
                         if prev in b and b[prev]["o"] > 0 and b[prev]["qv"] >= MIN_PREV_VOL), key=lambda x: -x[1])[:10]
        opens = {s: hbars(s)[t]["o"] for s, _ in ranked if t in hbars(s)}
        f.fill(t, [(s, round(r, 2), f"proxy: alta do dia anterior {r:+.1f}% (vol Binance US$ {daily[s][prev]['qv']/1e6:.0f}M)".replace(".", ",")) for s, r in ranked],
               opens, "FOMO proxy", lp)
    for s in list(f.pf.positions):
        hb = hbars(s).get(t)
        if not hb: continue
        f.pf.marks[s] = hb["c"]; p = f.pf.positions[s]
        if hb["l"] <= p["entry"] * (1 - F.SL): f.pf.sell(hb["ct"], s, min(hb["o"], p["entry"] * (1 - F.SL)), "stop loss -10%")
        elif hb["h"] >= p["entry"] * (1 + F.TP): f.pf.sell(hb["ct"], s, max(hb["o"], p["entry"] * (1 + F.TP)), "take profit +20%")
        elif hb["ct"] - p["ts"] >= F.MAX_H * H: f.pf.sell(hb["ct"], s, hb["c"], "saída por tempo (3 dias)")
    db.execute("INSERT INTO equity VALUES(?,?,?,?,?,?)", (t + H - 1, "fomo", f.pf.equity(), 0, f.pf.usdt, 0)); t += H
st = E.kv_get(db, "state"); st["fomo"] = f.to_dict(); E.kv_set(db, "state", st)
meta["fomo"] = {"proxy": True, "universe": len(syms), "slip": F.SLIP, "min_prev_day_binance_vol": MIN_PREV_VOL}
E.kv_set(db, "meta", meta); db.commit()
ex = dict(db.execute("SELECT substr(note,1,instr(note,' (')-1), COUNT(*) FROM trades WHERE strategy='fomo' AND side='SELL' GROUP BY 1").fetchall())
print(f"fomo equity={f.pf.equity():.2f} trades={f.pf.ntrades} fees={f.pf.fees:.2f} saídas={ex}")
