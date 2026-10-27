"""Backtest PROXY da estratégia 6 (FOMO lançamentos). Não existe histórico gratuito de trending/narrativas da CoinGecko,
então o filtro de narrativa NÃO é aplicado: o proxy compra as novas listagens de cripto da Binance (par USDT, 1-30 dias
de idade) com volume do dia anterior >= US$5M, até 3 posições, cada uma = caixa livre / vagas livres; cada moeda 1 vez.
Checagem diária às 00:00 UTC (21:00 BRT); compra na abertura da vela de 1h. Saídas em velas de 1h: stop -25% (prioridade
se stop e alvo na mesma vela), alvo +50%, 14 dias; gaps executam na abertura. Taxa 0,1% + slippage 0,4% por lado.
Uso: .venv/bin/python fomo_lanc_backtest.py [--db data/backtest.db]   (precisa de backtest.py e fomo_backtest.py antes no mesmo db)"""
import os, sys, json, time, argparse
from concurrent.futures import ThreadPoolExecutor
import engine as E, fomo as F, fomo_lancamentos as FL

HERE = os.path.dirname(os.path.abspath(__file__)); D, H = FL.D, FL.H
ap = argparse.ArgumentParser(); ap.add_argument("--db", default=os.path.join(HERE, "data", "backtest.db")); a = ap.parse_args()
db = E.open_db(a.db); meta = E.kv_get(db, "meta"); start, end = meta["start"], meta["end"]
L = FL.listings()

# ---- universo: pares USDT cuja moeda estreou na Binance entre (início-30d) e o fim
uni = {s: v for s, v in L.items() if v.get("base_first") and start - 30 * D <= v["base_first"] <= end and v["base"] not in F.EXCLUDE}
mk = []
for p in (1, 2, 3, 4):
    mk += F._cg("/coins/markets", vs_currency="usd", order="volume_desc", per_page=250, page=p); time.sleep(2)
by = {}
for m in mk: by.setdefault((m["symbol"] or "").upper(), []).append(m)
cls = {}
for s, v in uni.items():
    ms = sorted(by.get(v["base"], []), key=lambda m: -(m.get("total_volume") or 0)); m = ms[0] if ms else None
    if m: cls[s] = {"name": m["name"], "kind": "stock" if FL.is_stock_like(m["name"], m["id"]) else "crypto",
                    "old": (m.get("atl_date") or "9999") < time.strftime("%Y-%m-%d", time.gmtime((v["base_first"] - 180 * D) / 1000))}
batch = {}
for s, c in cls.items():
    if c["kind"] == "stock": batch[uni[s]["base_first"]] = batch.get(uni[s]["base_first"], 0) + 1
for s, v in uni.items():   # sem match na CoinGecko (top 1000): heurística bStocks = ticker terminado em B (todos os casos vistos eram bStocks)
    if s not in cls:
        st = v["base"].endswith("B") and len(v["base"]) >= 3
        cls[s] = {"name": "?", "kind": "stock" if st else "crypto", "old": False}

def fetch(s):
    t0 = max(start, uni[s]["base_first"]) - 2 * D
    d = {b["t"]: b for b in E.klines("1d", t0, end, symbol=s)}
    out, cur = [], t0
    while True:
        b = E.klines("1h", cur, end, symbol=s); out += b
        if len(b) < 1000: break
        cur = b[-1]["t"] + 1
    return s, d, {b["t"]: b for b in out}
daily, hourly = {}, {}
with ThreadPoolExecutor(6) as ex:
    for s, d, h in ex.map(fetch, sorted(uni)): daily[s], hourly[s] = d, h
for s in uni:   # stablecoin: fechamentos diários todos entre 0,97 e 1,03
    cl = [b["c"] for b in daily[s].values()]
    if cl and all(0.97 < c < 1.03 for c in cl): cls[s]["kind"] = "stable"

def run(tp=FL.TP, sl=FL.SL, max_d=FL.MAX_D, min_age=FL.MIN_AGE_D, max_age=FL.MAX_AGE_D, kinds=("crypto",), only_new=False, record=False):
    FL.TP, FL.SL, FL.MAX_D = tp, sl, max_d
    tl = E.make_trade_logger(db) if record else None
    f = FL.FomoLancamentos(on_trade=tl); eq = []; closed = []; entry_q = {}
    elig = [s for s in uni if cls[s]["kind"] in kinds and not (only_new and cls[s]["old"])]
    t = start - start % H
    while t <= end:
        if t % D == 0:
            prev = t - D; ranked = []
            for s in elig:
                age = (t - uni[s]["base_first"]) / D
                b = daily[s].get(prev)
                if min_age <= age <= max_age and b and b["qv"] >= FL.MIN_BINANCE_VOL and t in hourly[s]:
                    ranked.append((s, round(b["qv"] / 1e6, 1), f"proxy: listada há {age:.0f}d, vol dia anterior US$ {b['qv']/1e6:.0f}M ({cls[s]['name']})"))
            ranked.sort(key=lambda x: -x[1])
            opens = {s: hourly[s][t]["o"] for s, _, _ in ranked}
            n0 = len(f.pf.positions); u0 = f.pf.usdt
            for s, sc, why in f.fill(t, ranked, opens, "LANC proxy",
                                     (lambda ts, s, sc, why: db.execute("INSERT INTO picks(ts,symbol,score,reason,strategy) VALUES(?,?,?,?,?)", (ts, s, sc, why, FL.NAME))) if record else None):
                pass
            for s in f.pf.positions:
                if s not in entry_q: entry_q[s] = None
        for s in list(f.pf.positions):
            hb = hourly[s].get(t)
            if not hb: continue
            f.pf.marks[s] = hb["c"]; u = f.pf.usdt
            f.check_exits(hb["ct"], s, hb["c"], hb["l"], hb["h"], hb["o"])
            if s not in f.pf.positions: closed.append((s, f.pf.usdt - u))
        e = f.pf.equity(); eq.append((t + H - 1, e))
        if record: db.execute("INSERT INTO equity VALUES(?,?,?,?,?,?)", (t + H - 1, FL.NAME, e, 0, f.pf.usdt, 0))
        t += H
    return f, eq, elig

def stats(f, eq, db_trades=None):
    peak, mdd = -1, 0
    for _, v in eq: peak = max(peak, v); mdd = max(mdd, (peak - v) / peak)
    return eq[-1][1], mdd * 100

def win_rate(strategy):
    rows = db.execute("SELECT symbol, side, quote, fee FROM trades WHERE strategy=? ORDER BY ts, id", (strategy,)).fetchall()
    openq, res = {}, []
    for sym, side, q, fee in rows:
        if side == "BUY": openq[sym] = q
        elif sym in openq: res.append((q - fee) - openq.pop(sym))
    return len(res), sum(1 for x in res if x > 0), res

for t_ in ("trades", "equity"): db.execute(f"DELETE FROM {t_} WHERE strategy=?", (FL.NAME,))
db.execute("DELETE FROM picks WHERE strategy=?", (FL.NAME,))
main = run(record=True)
st = E.kv_get(db, "state"); st[FL.NAME] = main[0].to_dict(); E.kv_set(db, "state", st)
meta[FL.NAME] = {"proxy": True, "slip": FL.SLIP, "tp": FL.TP, "sl": FL.SL, "max_d": FL.MAX_D,
                 "universe": {s: cls[s] for s in uni}}
E.kv_set(db, "meta", meta); db.commit()

out = {"window": [start, end], "days": round((end - start) / D, 1), "rows": [], "variants": [], "universe": []}
def row(name, final, n_trades, n_closed, wins, mdd, note=""):
    out["rows"].append(dict(name=name, final=final, pnl=final - 1000, pct=final / 10 - 100, trades=n_trades,
                            closed=n_closed, win=(100 * wins / n_closed) if n_closed else None, mdd=mdd, note=note))
# baselines no mesmo db
for s, label in (("hold", "Buy & Hold BTC"), ("fomo", "FOMO antigo (+20/-10/3d, proxy)")):
    e = db.execute("SELECT ts, equity FROM equity WHERE strategy=? ORDER BY ts", (s,)).fetchall()
    if not e: continue
    peak, mdd = -1, 0
    for _, v in e: peak = max(peak, v); mdd = max(mdd, (peak - v) / peak)
    nt = db.execute("SELECT COUNT(*) FROM trades WHERE strategy=?", (s,)).fetchone()[0]
    nc, w, _ = win_rate(s); row(label, e[-1][1], nt, nc, w, mdd * 100)
f, eq, elig = main; final, mdd = stats(f, eq); nc, w, res = win_rate(FL.NAME)
row("FOMO lançamentos (+50/-25/14d, proxy)", final, f.pf.ntrades, nc, w, mdd, f"{len(f.pf.positions)} posição(ões) aberta(s) no fim")
# benchmark: comprar TODAS as novas listagens elegíveis (cripto) no 1º dia elegível e segurar até o fim, pesos iguais
rets = []
for s in elig:
    for d0 in sorted(daily[s]):
        age = (d0 + D - uni[s]["base_first"]) / D; b = daily[s][d0]
        if 1 <= age <= 30 and b["qv"] >= FL.MIN_BINANCE_VOL and d0 + D >= start and (d0 + D) in hourly[s]:
            px0 = hourly[s][d0 + D]["o"] * (1 + FL.SLIP); last = hourly[s][max(hourly[s])]["c"] * (1 - FL.SLIP)
            rets.append((s, (1 - FL.FEE) ** 2 * last / px0 - 1)); break
if rets:
    row(f"Comprar todas as {len(rets)} novas e segurar (pesos iguais)", 1000 * (1 + sum(r for _, r in rets) / len(rets)), 2 * len(rets),
        len(rets), sum(1 for _, r in rets if r > 0), float("nan"), "benchmark com lookahead (precisa saber N)")
# sensibilidade
for label, kw in [("entrada só no dia 2+ (min_age=2)", dict(min_age=2)), ("entrada só no dia 3+ (min_age=3)", dict(min_age=3)),
                  ("só moedas realmente novas (sem renome/listagem tardia)", dict(only_new=True)),
                  ("alvo +20% / stop -10% / 3d", dict(tp=.2, sl=.1, max_d=3)), ("alvo +50% sem stop / 14d", dict(sl=.99)),
                  ("alvo +100% / stop -25% / 30d", dict(tp=1.0, max_d=30)), ("incluindo ações tokenizadas (bStocks)", dict(kinds=("crypto", "stock")))]:
    f2, eq2, _ = run(**kw); fv, md = stats(f2, eq2)
    out["variants"].append(dict(name=label, final=fv, pct=fv / 10 - 100, trades=f2.pf.ntrades, mdd=md, open=len(f2.pf.positions)))
FL.TP, FL.SL, FL.MAX_D = 0.50, 0.25, 14
for s in sorted(uni, key=lambda s: uni[s]["base_first"]):
    if cls[s]["kind"] == "stock": continue
    out["universe"].append(dict(sym=s, listed=time.strftime("%Y-%m-%d", time.gmtime(uni[s]["base_first"] / 1000)), kind=cls[s]["kind"],
                                old=cls[s]["old"], name=cls[s]["name"]))
out["n_stocks"] = sum(1 for s in uni if cls[s]["kind"] == "stock")
out["trades"] = db.execute("SELECT ts, symbol, side, price, quote, note FROM trades WHERE strategy=? ORDER BY ts, id", (FL.NAME,)).fetchall()
json.dump(out, open(os.path.splitext(a.db)[0] + "_lancamentos.json", "w"), ensure_ascii=False, indent=1, default=str)
for r in out["rows"]: print(r)
for v in out["variants"]: print(v)
for u in out["universe"]: print(u)
for t_ in out["trades"]: print(time.strftime("%Y-%m-%d %H:%M", time.gmtime(t_[0] / 1000)), t_[1:])
