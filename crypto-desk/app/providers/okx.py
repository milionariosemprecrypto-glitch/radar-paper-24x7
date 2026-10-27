"""OKX – fonte principal GRÁTIS (REST + WebSocket públicos, sem chave).
Docs: https://www.okx.com/docs-v5/en/  (endpoints testados ao vivo)."""
import asyncio, json, time
import websockets
from ..state import STORE, now_ms
from .. import config, logs
from .base import get_json, loop_forever
log = logs.get("okx")
REST = "https://www.okx.com/api/v5"
WS = "wss://ws.okx.com:443/ws/v5/public"
CTVAL = {}  # instId -> tamanho do contrato (em moeda base)

def inst(sym): return f"{sym}-USDT-SWAP"

async def load_instruments():
    d = await get_json(f"{REST}/public/instruments", {"instType": "SWAP"})
    for x in d["data"]:
        CTVAL[x["instId"]] = float(x["ctVal"] or 1)

async def candles():
    for sym in config.ASSETS:
        a = STORE.assets[sym]
        for tf in ("1m", "5m", "15m", "1H"):
            d = await get_json(f"{REST}/market/candles", {"instId": inst(sym), "bar": tf, "limit": 300})
            rows = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in d["data"]]
            rows.reverse()
            a.candles[tf] = rows
            if tf == "15m" and rows:
                STORE.persist("candles", dict(sym=sym, tf=tf, ts=rows[-1][0], o=rows[-1][1], h=rows[-1][2], l=rows[-1][3], c=rows[-1][4], vol_usd=rows[-1][5]))
            await asyncio.sleep(0.12)
        a.updated["candles"] = now_ms()

async def derivs():
    for sym in config.ASSETS:
        a = STORE.assets[sym]
        oi = await get_json(f"{REST}/public/open-interest", {"instType": "SWAP", "instId": inst(sym)})
        a.oi["OKX"] = {"usd": float(oi["data"][0]["oiUsd"]), "ts": now_ms()}
        fr = await get_json(f"{REST}/public/funding-rate", {"instId": inst(sym)})
        a.funding["OKX"] = float(fr["data"][0]["fundingRate"])
        mk = await get_json(f"{REST}/public/mark-price", {"instType": "SWAP", "instId": inst(sym)})
        ix = await get_json(f"{REST}/market/index-tickers", {"instId": f"{sym}-USDT"})
        mark = float(mk["data"][0]["markPx"]); idx = float(ix["data"][0]["idxPx"])
        a.basis = (mark - idx) / idx if idx else None
        STORE.persist("derivs", dict(sym=sym, exch="OKX", ts=now_ms(), oi_usd=a.oi["OKX"]["usd"], funding=a.funding["OKX"], ls_ratio=a.ls_ratio, basis=a.basis))
        await asyncio.sleep(0.2)

async def rubik():
    """Estatísticas OKX (limite 5 req/2s): histórico OI 5m, long/short contas, taker buy/sell."""
    for sym in config.ASSETS:
        a = STORE.assets[sym]
        d = await get_json(f"{REST}/rubik/stat/contracts/open-interest-volume", {"ccy": sym, "period": "5m"})
        a.oi_hist = sorted([(int(r[0]), float(r[1])) for r in d["data"]])
        await asyncio.sleep(0.5)
        d = await get_json(f"{REST}/rubik/stat/contracts/long-short-account-ratio", {"ccy": sym, "period": "5m"})
        a.ls_hist = sorted([(int(r[0]), float(r[1])) for r in d["data"]])
        a.ls_ratio = a.ls_hist[-1][1] if a.ls_hist else None
        await asyncio.sleep(0.5)
        d = await get_json(f"{REST}/rubik/stat/taker-volume", {"ccy": sym, "instType": "CONTRACTS", "period": "5m"})
        a.taker = sorted([(int(r[0]), float(r[2]), float(r[1])) for r in d["data"]])  # (ts, buy, sell)
        await asyncio.sleep(0.5)
        fh = await get_json(f"{REST}/public/funding-rate-history", {"instId": inst(sym), "limit": 30})
        a.funding_hist = sorted([(int(r["fundingTime"]), float(r["realizedRate"] or r["fundingRate"])) for r in fh["data"]])
        await asyncio.sleep(0.5)

async def depth():
    for sym in config.ASSETS:
        a = STORE.assets[sym]
        d = await get_json(f"{REST}/market/books", {"instId": inst(sym), "sz": 400})
        b = d["data"][0]; cv = CTVAL.get(inst(sym), 1)
        bids = [(float(p), float(s) * cv) for p, s, *_ in b["bids"]]
        asks = [(float(p), float(s) * cv) for p, s, *_ in b["asks"]]
        if not bids or not asks: continue
        mid = (bids[0][0] + asks[0][0]) / 2
        bands = {}
        for pct in (0.1, 0.5, 1.0):
            bu = sum(p * s for p, s in bids if p >= mid * (1 - pct / 100))
            au = sum(p * s for p, s in asks if p <= mid * (1 + pct / 100))
            bands[f"{pct}%"] = {"bids_usd": bu, "asks_usd": au, "imbalance": (bu - au) / (bu + au) if bu + au else 0}
        # maiores "paredes" (níveis com mais liquidez) – usadas para absorção
        walls_b = sorted(bids, key=lambda x: -x[1] * x[0])[:3]; walls_a = sorted(asks, key=lambda x: -x[1] * x[0])[:3]
        a.depth = {"mid": mid, "bands": bands, "bid_walls": [(p, p * s) for p, s in walls_b], "ask_walls": [(p, p * s) for p, s in walls_a], "ts": now_ms()}
        await asyncio.sleep(0.15)

async def liq_seed():
    for sym in config.ASSETS:
        d = await get_json(f"{REST}/public/liquidation-orders", {"instType": "SWAP", "uly": f"{sym}-USDT", "state": "filled", "limit": 100})
        for blk in d.get("data", []):
            _add_liqs(blk.get("instId", inst(sym)), blk.get("details", []))
        await asyncio.sleep(0.3)

_seen = set()
def _add_liqs(instid, details):
    sym = instid.split("-")[0]
    if sym not in STORE.assets or not instid.endswith("USDT-SWAP"): return
    cv = CTVAL.get(instid, 1)
    for x in details:
        key = f"okx-{instid}-{x.get('ts')}-{x.get('sz')}-{x.get('bkPx')}"
        if key in _seen: continue
        _seen.add(key)
        side = x.get("posSide") or ("long" if x.get("side") == "sell" else "short")
        px = float(x["bkPx"]); usd = float(x["sz"]) * cv * px
        row = (int(x["ts"]), side, px, usd, "OKX")
        STORE.assets[sym].liqs.append(row)
        STORE.persist("liquidations", dict(id=key, sym=sym, exch="OKX", ts=row[0], side=side, px=px, usd=usd))

async def ws_loop():
    """WebSocket público OKX: trades (CVD/agressão), books5 (topo do book), liquidation-orders, tickers."""
    args = [{"channel": "liquidation-orders", "instType": "SWAP"}]
    for s in config.ASSETS:
        args += [{"channel": "trades", "instId": inst(s)}, {"channel": "books5", "instId": inst(s)}, {"channel": "tickers", "instId": inst(s)}]
    backoff = 1
    for _ in range(40):
        if CTVAL: break
        await asyncio.sleep(0.5)
    while True:
        try:
            async with websockets.connect(WS, ping_interval=None, open_timeout=15, max_size=2**22) as w:
                await w.send(json.dumps({"op": "subscribe", "args": args}))
                STORE.source("OKX WebSocket", "ok", "tempo real (trades, book, liquidações)", "real"); backoff = 1
                last = time.time()
                while True:
                    try:
                        msg = await asyncio.wait_for(w.recv(), timeout=25)
                    except asyncio.TimeoutError:
                        await w.send("ping"); continue
                    if msg == "pong": continue
                    m = json.loads(msg); arg = m.get("arg", {}); ch = arg.get("channel"); data = m.get("data")
                    if not data: continue
                    if ch == "trades":
                        sym = arg["instId"].split("-")[0]; a = STORE.assets[sym]; cv = CTVAL.get(arg["instId"], 1)
                        for t in data:
                            px = float(t["px"]); usd = float(t["sz"]) * cv * px
                            a.trades.append((int(t["ts"]), px, usd, t["side"])); a.price = px
                    elif ch == "books5":
                        sym = arg["instId"].split("-")[0]; b = data[0]
                        STORE.assets[sym].book = {"bids": [(float(p), float(s)) for p, s, *_ in b["bids"]], "asks": [(float(p), float(s)) for p, s, *_ in b["asks"]], "ts": int(b["ts"])}
                    elif ch == "tickers":
                        sym = arg["instId"].split("-")[0]; STORE.assets[sym].price = float(data[0]["last"])
                    elif ch == "liquidation-orders":
                        for blk in data: _add_liqs(blk.get("instId", ""), blk.get("details", []))
        except Exception as e:
            STORE.source("OKX WebSocket", "reconectando", f"{type(e).__name__}: {str(e)[:80]} – nova tentativa em {backoff}s", "real")
            logs.ev(log, "ws_reconnect", erro=str(e)[:200], backoff=backoff)
            await asyncio.sleep(backoff); backoff = min(backoff * 2, 60)

def tasks():
    async def boot():
        await load_instruments(); await liq_seed()
    return [boot(), ws_loop(), loop_forever("OKX velas (1m/5m/15m/1h)", candles, 20), loop_forever("OKX OI/funding/basis", derivs, 30),
            loop_forever("OKX estatísticas (OI hist, L/S, taker)", rubik, 60), loop_forever("OKX profundidade do book", depth, 10)]
