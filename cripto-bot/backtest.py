"""Backtest das 4 estratégias nos últimos 90 dias de candles de 1h (BTCUSDT, Binance pública).
Uso: .venv/bin/python backtest.py [--days 90]"""
import argparse, os, time
import engine as E

ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=90)
ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "data", "backtest.db"))
a = ap.parse_args()
H = 3600_000; now = int(time.time() * 1000)
bars = E.closed(E.klines_range("1h", now - (a.days + 32) * 24 * H))
win_start = now - a.days * 24 * H
pre = [b for b in bars if b["t"] < win_start]; win = [b for b in bars if b["t"] >= win_start]
hist30 = pre[-30 * 24:]
if os.path.exists(a.db): os.remove(a.db)
db = E.open_db(a.db); tl = E.make_trade_logger(db)
ctx = {"grid_lo": min(b["l"] for b in hist30), "grid_hi": max(b["h"] for b in hist30),
       "closes_1h": [b["c"] for b in pre[-300:]], "dca_amount": E.CAPITAL / -(-a.days // 7)}
strats = [S(on_trade=tl) for S in E.STRATS]
t0, p0 = win[0]["t"], win[0]["o"]
for s in strats: s.start(t0, p0, ctx)
E.snapshot(db, strats, t0, p0)
for b in win:
    for s in strats: s.on_fine_bar(b)
    for s in strats: s.on_hour(b)
    E.snapshot(db, strats, b["ct"], b["c"])
E.kv_set(db, "meta", {"mode": "backtest", "days": a.days, "start": t0, "end": win[-1]["ct"], "bars": len(win),
                      "grid_lo": ctx["grid_lo"], "grid_hi": ctx["grid_hi"], "dca_amount": ctx["dca_amount"],
                      "fee": E.FEE, "slip": E.SLIP, "capital": E.CAPITAL, "grid_bars": "1h"})
E.kv_set(db, "state", {s.name: s.to_dict() for s in strats}); db.commit()
for s in strats:
    print(f"{s.name:10s} equity={s.pf.equity(win[-1]['c']):9.2f} trades={s.pf.ntrades:4d} fees={s.pf.fees:7.2f}")
print("BTC", p0, "->", win[-1]["c"], "| grid", round(ctx["grid_lo"]), "-", round(ctx["grid_hi"]))
