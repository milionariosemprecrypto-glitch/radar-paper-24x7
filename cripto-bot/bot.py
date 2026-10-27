"""Paper-trading AO VIVO (dinheiro fictício, preços reais). Sem chaves, sem ordens reais.
Estado salvo em data/live.db (SQLite) a cada ciclo -> seguro para reiniciar (retoma e processa candles perdidos)."""
import os, time, signal, logging, json
from logging.handlers import RotatingFileHandler
import engine as E, fomo as F, fomo_lancamentos as FL

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "live.db")
LOOP_S = 60; SNAP_EVERY_S = 300; DCA_WEEKLY = 100.0
H = 3600_000; M = 60_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[RotatingFileHandler(os.path.join(HERE, "logs", "bot.log"), maxBytes=5_000_000, backupCount=3)])
log = E.log
stop = False
def _stop(*_):
    global stop; stop = True
signal.signal(signal.SIGTERM, _stop); signal.signal(signal.SIGINT, _stop)

def init(db, tl):
    now = int(time.time() * 1000)
    h = E.closed(E.klines_range("1h", now - 32 * 24 * H)); last30 = h[-30 * 24:]
    m = E.closed(E.klines("1m", limit=5))
    price = E.ticker()
    ctx = {"grid_lo": min(b["l"] for b in last30), "grid_hi": max(b["h"] for b in last30),
           "closes_1h": [b["c"] for b in h[-300:]], "dca_amount": DCA_WEEKLY}
    strats = [S(on_trade=tl) for S in E.STRATS]
    for s in strats: s.start(now, price, ctx)
    E.kv_set(db, "meta", {"mode": "live", "start": now, "start_price": price, "grid_lo": ctx["grid_lo"], "grid_hi": ctx["grid_hi"],
                          "dca_amount": DCA_WEEKLY, "fee": E.FEE, "slip": E.SLIP, "capital": E.CAPITAL, "grid_bars": "1m"})
    cur = {"last_1h": h[-1]["t"], "last_1m": m[-1]["t"], "last_snap": 0, "last_price": price}
    log.info("INIT preço=%.2f grid=%.0f-%.0f", price, ctx["grid_lo"], ctx["grid_hi"])
    return strats, cur

def main():
    db = E.open_db(DB); tl = E.make_trade_logger(db, echo=True)
    st = E.kv_get(db, "state")
    if st is None:
        strats, cur = init(db, tl)
    else:
        strats = [S(on_trade=tl, st=st[S.name]) for S in E.STRATS]; cur = st["_cursor"]
        log.info("RETOMADO do estado salvo; último 1m=%s", time.strftime("%Y-%m-%d %H:%M", time.localtime(cur["last_1m"] / 1000)))
    st = E.kv_get(db, "state") or {}
    fomo = F.Fomo(on_trade=tl, st=st.get("fomo"))
    if "fomo" not in st: log.info("FOMO: estratégia nova iniciada com %.0f USDT", fomo.pf.usdt)
    lanc = FL.FomoLancamentos(on_trade=tl, st=st.get(FL.NAME))
    if FL.NAME not in st: log.info("FOMO LANÇAMENTOS: estratégia nova iniciada com %.0f USDT", lanc.pf.usdt)
    def log_pick(ts, sym, sc, why, strategy="fomo"):
        db.execute("INSERT INTO picks(ts,symbol,score,reason,strategy) VALUES(?,?,?,?,?)", (ts, sym, sc, why, strategy))
        log.info("PICK %s %s score=%.2f %s", strategy, sym, sc, why)
    def save():
        E.kv_set(db, "state", {**{s.name: s.to_dict() for s in strats}, "fomo": fomo.to_dict(), FL.NAME: lanc.to_dict(), "_cursor": cur}); db.commit()
    save()
    while not stop:
        try:
            # 1) candles de 1m fechados desde o último processado -> grid
            for b in E.closed(E.klines_range("1m", cur["last_1m"] + M)):
                for s in strats: s.on_fine_bar(b)
                cur["last_1m"] = b["t"]; cur["last_price"] = b["c"]
            # 2) candles de 1h fechados -> EMA, DCA
            for b in E.closed(E.klines_range("1h", cur["last_1h"] + H)):
                for s in strats: s.on_hour(b)
                cur["last_1h"] = b["t"]
            now = int(time.time() * 1000)
            prices = {}
            # 3) FOMO/narrativas: saídas a cada ciclo; escolha diária às 00:00 UTC (21:00 BRT)
            try:
                prices = F.all_prices()
                for sym in list(fomo.pf.positions):
                    if sym in prices: fomo.pf.marks[sym] = prices[sym]; fomo.check_exits(now, sym, prices[sym])
                if now >= fomo.next_pick:
                    ranked = F.pick_live(); log.info("FOMO ranking top5: %s", ranked[:5])
                    fomo.fill(now, ranked, prices, "FOMO", log_pick)
                    fomo.next_pick = (now // 86400_000 + 1) * 86400_000
            except Exception as e:
                log.warning("FOMO: falha neste ciclo (%s); tenta de novo no próximo", e)
            # 4) FOMO LANÇAMENTOS: saídas a cada ciclo (+50% / -25% / 14d); escolha diária às 00:00 UTC (e logo ao iniciar)
            try:
                if not prices: prices = F.all_prices()
                for sym in list(lanc.pf.positions):
                    if sym in prices: lanc.pf.marks[sym] = prices[sym]; lanc.check_exits(now, sym, prices[sym])
                if now >= lanc.next_pick:
                    if len(lanc.pf.positions) < FL.SLOTS:
                        ranked, rej = FL.pick_live(done=lanc.done, now=now)
                        log.info("LANC candidatos: %s", ranked[:5]); log.info("LANC rejeitados: %s", rej)
                        E.kv_set(db, "lanc_last_scan", {"ts": now, "ranked": ranked, "rejected": rej})
                        lanc.fill(now, ranked, prices, "FOMO LANÇAMENTOS", lambda *x: log_pick(*x, strategy=FL.NAME))
                    lanc.next_pick = (now // 86400_000 + 1) * 86400_000
            except Exception as e:
                log.warning("FOMO LANÇAMENTOS: falha neste ciclo (%s); tenta de novo no próximo", e)
            if now - cur["last_snap"] >= SNAP_EVERY_S * 1000:
                try: cur["last_price"] = E.ticker()
                except Exception: pass
                E.snapshot(db, strats + [fomo, lanc], now, cur["last_price"]); cur["last_snap"] = now
                log.info("SNAP preço=%.2f %s", cur["last_price"], " ".join(f"{s.name}={s.pf.equity(cur['last_price']):.2f}" for s in strats + [fomo, lanc]))
            save()
            with open(os.path.join(HERE, "data", "heartbeat.json"), "w") as f:
                json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S %z"), "price": cur["last_price"], "pid": os.getpid()}, f)
        except Exception as e:
            db.rollback(); log.exception("erro no ciclo (tentará de novo): %s", e)
            st = E.kv_get(db, "state")  # recarrega estado consistente
            if st:
                strats = [S(on_trade=tl, st=st[S.name]) for S in E.STRATS]; cur = st["_cursor"]
                fomo = F.Fomo(on_trade=tl, st=st.get("fomo")); lanc = FL.FomoLancamentos(on_trade=tl, st=st.get(FL.NAME))
        for _ in range(LOOP_S):
            if stop: break
            time.sleep(1)
    save(); log.info("encerrado")

if __name__ == "__main__":
    main()
