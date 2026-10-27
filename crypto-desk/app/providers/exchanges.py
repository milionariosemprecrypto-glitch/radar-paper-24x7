"""Outras exchanges GRÁTIS para OI/funding por exchange e liquidações extras.
Binance e Bybit bloqueiam alguns países/datacenters (HTTP 451/403): o coletor se
desativa sozinho e mostra 'bloqueado' no painel. No Brasil normalmente funcionam."""
import asyncio, json
import websockets
from ..state import STORE, now_ms
from .. import config, logs
from .base import get_json, loop_forever, client
log = logs.get("exch")

async def bitget():
    for sym in config.ASSETS:
        d = await get_json("https://api.bitget.com/api/v2/mix/market/ticker", {"symbol": f"{sym}USDT", "productType": "usdt-futures"})
        x = d["data"][0]; a = STORE.assets[sym]
        a.oi["Bitget"] = {"usd": float(x["holdingAmount"]) * float(x["markPrice"]), "ts": now_ms()}
        a.funding["Bitget"] = float(x["fundingRate"])
        await asyncio.sleep(0.1)

async def gate():
    for sym in config.ASSETS:
        x = await get_json(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{sym}_USDT")
        a = STORE.assets[sym]
        a.oi["Gate"] = {"usd": float(x["position_size"]) * float(x["quanto_multiplier"]) * float(x["mark_price"]), "ts": now_ms()}
        a.funding["Gate"] = float(x["funding_rate"])
        await asyncio.sleep(0.1)

async def binance():
    for sym in config.ASSETS:
        s = f"{sym}USDT"; a = STORE.assets[sym]
        oi = await get_json("https://fapi.binance.com/fapi/v1/openInterest", {"symbol": s})
        pi = await get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": s})
        a.oi["Binance"] = {"usd": float(oi["openInterest"]) * float(pi["markPrice"]), "ts": now_ms()}
        a.funding["Binance"] = float(pi["lastFundingRate"])
        await asyncio.sleep(0.1)

async def bybit():
    for sym in config.ASSETS:
        d = await get_json("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": f"{sym}USDT"})
        x = d["result"]["list"][0]; a = STORE.assets[sym]
        a.oi["Bybit"] = {"usd": float(x["openInterestValue"]), "ts": now_ms()}
        a.funding["Bybit"] = float(x["fundingRate"])
        await asyncio.sleep(0.1)

async def hyperliquid():
    """POST https://api.hyperliquid.xyz/info {"type":"metaAndAssetCtxs"} (grátis). Funding da Hyperliquid é por HORA: multiplicamos por 8 p/ comparar com 8h."""
    r = await client().post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}, timeout=15)
    r.raise_for_status(); meta, ctx = r.json()
    names = [u["name"] for u in meta["universe"]]
    for sym in config.ASSETS:
        if sym in names:
            c = ctx[names.index(sym)]; a = STORE.assets[sym]
            a.oi["Hyperliquid"] = {"usd": float(c["openInterest"]) * float(c["markPx"]), "ts": now_ms()}
            a.funding["Hyperliquid"] = float(c["funding"]) * 8

async def binance_liq_ws():
    """wss://fstream.binance.com/ws/!forceOrder@arr – Binance envia no máx. 1 liquidação por símbolo/segundo (amostra)."""
    backoff = 2
    for attempt in range(1000):
        try:
            async with websockets.connect("wss://fstream.binance.com/ws/!forceOrder@arr", open_timeout=10) as w:
                STORE.source("Binance liquidações WS", "ok", "tempo real (amostra 1/s por par)"); backoff = 2
                async for msg in w:
                    o = json.loads(msg).get("o", {}); s = o.get("s", "")
                    sym = s[:-4] if s.endswith("USDT") else None
                    if sym in STORE.assets:
                        side = "long" if o["S"] == "SELL" else "short"; px = float(o["ap"] or o["p"])
                        STORE.assets[sym].liqs.append((int(o["T"]), side, px, float(o["z"]) * px, "Binance"))
        except Exception as e:
            if attempt >= 3:
                STORE.source("Binance liquidações WS", "bloqueado", f"sem conexão ({type(e).__name__}) – desativado neste computador"); return
            await asyncio.sleep(backoff); backoff *= 2

async def bybit_liq_ws():
    """wss://stream.bybit.com/v5/public/linear tópico allLiquidation.{symbol}; S=Buy => long liquidado."""
    for attempt in range(1000):
        try:
            async with websockets.connect("wss://stream.bybit.com/v5/public/linear", open_timeout=10) as w:
                await w.send(json.dumps({"op": "subscribe", "args": [f"allLiquidation.{s}USDT" for s in config.ASSETS]}))
                STORE.source("Bybit liquidações WS", "ok", "tempo real")
                while True:
                    try:
                        msg = await asyncio.wait_for(w.recv(), 20)
                    except asyncio.TimeoutError:
                        await w.send(json.dumps({"op": "ping"})); continue
                    m = json.loads(msg)
                    for x in m.get("data", []) if isinstance(m.get("data"), list) else []:
                        sym = x["s"][:-4]
                        if sym in STORE.assets:
                            px = float(x["p"]); side = "long" if x["S"] == "Buy" else "short"
                            STORE.assets[sym].liqs.append((int(x["T"]), side, px, float(x["v"]) * px, "Bybit"))
        except Exception as e:
            if attempt >= 3:
                STORE.source("Bybit liquidações WS", "bloqueado", f"sem conexão ({type(e).__name__}) – desativado neste computador"); return
            await asyncio.sleep(2 * (attempt + 1))

def tasks():
    t = []
    ex = config.EXCHANGES
    if "bitget" in ex: t.append(loop_forever("Bitget OI/funding", bitget, 30))
    if "gate" in ex: t.append(loop_forever("Gate OI/funding", gate, 30))
    t.append(loop_forever("Hyperliquid OI/funding", hyperliquid, 30))
    if "binance" in ex: t += [loop_forever("Binance OI/funding", binance, 30), binance_liq_ws()]
    if "bybit" in ex: t += [loop_forever("Bybit OI/funding", bybit, 30), bybit_liq_ws()]
    return t
