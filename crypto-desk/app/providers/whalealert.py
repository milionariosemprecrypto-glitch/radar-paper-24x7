"""Whale Alert PAGO (Alerts API, US$ 29,95/mês, teste 7 dias) – liga só se WHALE_ALERT_API_KEY existir.
WebSocket oficial: wss://leviathan.whale-alert.io/ws?api_key=KEY  (mín. US$100k, 2 conexões, 100 alertas/h)."""
import json, asyncio, websockets
from ..state import STORE
from .. import config
from ..engine.classify import classify

async def ws_loop():
    url = f"wss://leviathan.whale-alert.io/ws?api_key={config.WHALE_ALERT_API_KEY}"
    while True:
        try:
            async with websockets.connect(url, open_timeout=15) as w:
                await w.send(json.dumps({"type": "subscribe_alerts", "min_value_usd": max(100000, int(config.WHALE_MIN_USD)),
                                         "tx_types": ["transfer", "mint", "burn"]}))
                STORE.source("Whale Alert API (paga)", "ok", "WebSocket em tempo real", "real")
                async for msg in w:
                    m = json.loads(msg)
                    if m.get("type") != "alert": continue
                    am = (m.get("amounts") or [{}])[0]
                    fr = (m.get("from") or ""); to = (m.get("to") or "")
                    usd = float(am.get("value_usd") or 0); sym = (am.get("symbol") or "").upper()
                    kind = m.get("transaction_type", "transfer")
                    cls, txt, eff = classify(sym, usd, fr, to, kind)
                    ev = {"id": "wa-" + str(m.get("id") or m.get("timestamp")), "ts": int(m.get("timestamp", 0)) * 1000, "symbol": sym, "usd": usd,
                          "from_owner": fr, "to_owner": to, "kind": kind, "classification": cls, "impact": txt, "effect": eff,
                          "text": m.get("text", ""), "url": "", "source": "Whale Alert API"}
                    STORE.whales.append(ev)
        except Exception as e:
            STORE.source("Whale Alert API (paga)", "erro", f"{type(e).__name__}: {str(e)[:100]}", "real")
            await asyncio.sleep(30)
