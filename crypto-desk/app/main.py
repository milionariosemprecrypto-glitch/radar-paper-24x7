"""Crypto Antecipation Desk – servidor FastAPI (painel + API somente leitura). Modo PAPER apenas."""
import asyncio, json, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config, logs, alerts
from .state import STORE, now_ms
from .providers import okx, exchanges, whales_free, news_rss
from .providers.base import loop_forever
from .engine import features, score, signals
from .engine.risk import RiskGuard, PaperLedger
from .engine.indicators import cvd_series
log = logs.get("main")
def _funding_rate(sym):  # média das exchanges (fração/8h); None se sem dado => funding não aplicado
    a = STORE.assets.get(sym); v = [x for x in (a.funding or {}).values() if isinstance(x, (int, float))] if a else []
    return sum(v) / len(v) if v else None
GUARD = RiskGuard(store=STORE); LEDGER = PaperLedger(GUARD, STORE, funding_rate_fn=_funding_rate)
FEAT = {}

async def engine_loop():
    await asyncio.sleep(20)
    while True:
        try:
            now = now_ms()
            for sym, a in STORE.assets.items():
                if not a.price: continue
                f = features.build(a, list(STORE.whales), list(STORE.news), now); FEAT[sym] = f
                sc = score.compute(f); STORE.scores[sym] = sc
                LEDGER.update(sym, a.price, now)
                sig = signals.build(f, sc, GUARD, now); prev = STORE.signals.get(sym)
                STORE.signals[sym] = sig
                if sig["kind"] == "entrada" and (not prev or prev.get("kind") != "entrada"):
                    LEDGER.open_trade(sig)
                    STORE.persist("signals", dict(id=sig["id"], sym=sym, ts=now, kind="entrada", direction=sig["direction"], score=sig["score"], entry=sig["entry"],
                                  stop=sig["stop"], t1=sig["t1"], t2=sig["t2"], risk_pct=sig["risk_pct"], confluences=sig["confluences"], reason=sig["explain"]))
                    await alerts.push("SINAL", sym, f"{sig['title']} | entrada {sig['entry']} | stop {sig['stop']:.6g} | alvos {sig['t1']:.6g}/{sig['t2']:.6g} | {sig['explain']}")
                for al in sig.get("alerts", []):
                    await alerts.push("ATENÇÃO", sym, al)
                if now // 60000 != getattr(engine_loop, "last_min", {}).get(sym):
                    engine_loop.__dict__.setdefault("last_min", {})[sym] = now // 60000
                    STORE.persist("scores", dict(sym=sym, ts=now, score=sc["score"], status=sc["status"], factors=sc["factors"]))
            for w in list(STORE.whales)[-20:]:
                if w["usd"] >= config.WHALE_MIN_USD * 10 and w["effect"] != 0 and w["ts"] > now - 600_000:
                    await alerts.push("BALEIA", w["symbol"], f"${w['usd']/1e6:.0f}M {w['classification']}: {w['impact']}", 600)
            STORE.source("Motor de score/sinais", "ok", "recalcula a cada 5s", "cálculo")
        except Exception as e:
            logs.ev(log, "engine_erro", erro=repr(e)[:300]); STORE.source("Motor de score/sinais", "erro", repr(e)[:150], "cálculo")
        await asyncio.sleep(5)

def paid_status():
    STORE.source("Coinglass (pago)", "ok" if config.COINGLASS_API_KEY else "desligado", "Chave presente" if config.COINGLASS_API_KEY else "Sem COINGLASS_API_KEY – a partir de US$29/mês (heatmap oficial só US$699/mês)", "pago")
    STORE.source("Whale Alert API (paga)", "ok" if config.WHALE_ALERT_API_KEY else "desligado", "Chave presente" if config.WHALE_ALERT_API_KEY else "Sem WHALE_ALERT_API_KEY – US$29,95/mês (usando Telegram público grátis)", "pago")
    STORE.source("X/Twitter API (paga)", "ok" if config.X_BEARER_TOKEN else "desligado", "Chave presente" if config.X_BEARER_TOKEN else "Sem X_BEARER_TOKEN – pago por uso (~US$0,005/post lido); usando Google News RSS", "pago")
    en = alerts.enabled()
    STORE.source("Alertas Telegram", "ok" if en["telegram"] else "desligado", "configurado" if en["telegram"] else "defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (grátis)", "alerta")
    STORE.source("Alertas Discord", "ok" if en["discord"] else "desligado", "configurado" if en["discord"] else "defina DISCORD_WEBHOOK_URL (grátis)", "alerta")

@asynccontextmanager
async def lifespan(app):
    paid_status()
    t = okx.tasks() + exchanges.tasks() + [loop_forever("Baleias – Telegram público Whale Alert (grátis)", whales_free.poll, 60, "real (atraso possível)"),
         loop_forever("Notícias RSS (Cointelegraph + Google News)", news_rss.poll, 120, "real"), engine_loop()]
    if config.COINGLASS_API_KEY:
        from .providers import coinglass; t.append(loop_forever("Coinglass (pago)", coinglass.poll, 120))
    if config.WHALE_ALERT_API_KEY:
        from .providers import whalealert; t.append(whalealert.ws_loop())
    if config.X_BEARER_TOKEN:
        from .providers import xapi; t.append(loop_forever("X/Twitter API (paga)", xapi.poll, 300))
    tasks = [asyncio.create_task(c) for c in t]
    logs.ev(log, "iniciado", ativos=config.ASSETS, modo=config.TRADING_MODE)
    yield
    for x in tasks: x.cancel()

app = FastAPI(title="Crypto Antecipation Desk", lifespan=lifespan, docs_url="/api/docs")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

def asset_summary(sym):
    a = STORE.assets[sym]; sc = STORE.scores.get(sym, {}); f = FEAT.get(sym, {})
    c15 = a.candles.get("15m", [])
    return {"sym": sym, "price": a.price, "chg_24h": ((a.price / a.candles["1H"][-24][4] - 1) * 100) if a.price and len(a.candles.get("1H", [])) >= 24 else None,
            "score": sc.get("score"), "status": sc.get("status"), "direction": sc.get("direction"), "confluences": sc.get("confluences", []),
            "oi_total": sum(v["usd"] for v in a.oi.values()), "funding_avg": f.get("funding_avg"), "atr_pct": f.get("atr_pct"),
            "signal": STORE.signals.get(sym, {}).get("kind"), "vol_15m": c15[-1][5] if c15 else None}

def snapshot():
    return {"ts": now_ms(), "mode": config.TRADING_MODE, "assets": [asset_summary(s) for s in config.ASSETS],
            "signals": list(STORE.signals.values()), "alerts": list(STORE.alerts)[-30:][::-1], "sources": STORE.sources}

@app.get("/")
def index(): return FileResponse(STATIC / "index.html")

@app.get("/api/snapshot")
def api_snapshot(): return snapshot()

@app.get("/api/asset/{sym}")
def api_asset(sym: str):
    sym = sym.upper()
    if sym not in STORE.assets: return JSONResponse({"erro": "ativo desconhecido"}, 404)
    a = STORE.assets[sym]; f = FEAT.get(sym, {})
    liqs = list(a.liqs)
    return {"sym": sym, "price": a.price, "candles15": a.candles.get("15m", [])[-120:], "candles1h": a.candles.get("1H", [])[-72:],
            "oi": a.oi, "oi_hist": a.oi_hist[-288:], "funding": a.funding, "funding_hist": a.funding_hist[-60:], "ls_ratio": a.ls_ratio, "ls_hist": a.ls_hist[-288:],
            "taker": a.taker[-72:], "basis": a.basis, "depth": a.depth, "liqs": sorted(liqs, key=lambda x: -x[0])[:200],
            "liq_1h": {"long": sum(x[3] for x in liqs if x[0] > now_ms() - 3600e3 and x[1] == "long"), "short": sum(x[3] for x in liqs if x[0] > now_ms() - 3600e3 and x[1] == "short")},
            "cvd_series": cvd_series(list(a.trades), 60_000, 120), "cvd_15m": f.get("cvd_15m"), "cvd_5m": f.get("cvd_5m"), "taker_ratio_1h": f.get("taker_ratio_1h"),
            "vol_ratio": f.get("vol_ratio"), "heatmap": f.get("heatmap"), "score": STORE.scores.get(sym), "signal": STORE.signals.get(sym),
            "ema": {k: f.get(k) for k in ("ema9", "ema21", "ema50")}, "trades_buffer": len(a.trades)}

@app.get("/api/whales")
def api_whales(): return list(STORE.whales)[-150:][::-1]

@app.get("/api/news")
def api_news(): return sorted(STORE.news, key=lambda n: -n["ts"])[:150]

@app.get("/api/paper")
def api_paper(): return {"risco": GUARD.state(), "caderno": LEDGER.stats(), "persistencia": {"erros": STORE.persist_errors, "ultimo_erro": STORE.last_persist_error}}

@app.get("/api/sources")
def api_sources(): return STORE.sources

@app.get("/health")
def health(): return {"ok": True, "assets_live": [s for s, a in STORE.assets.items() if a.price]}

@app.websocket("/ws")
async def ws(w: WebSocket):
    await w.accept()
    try:
        while True:
            await w.send_text(json.dumps(snapshot(), default=str)); await asyncio.sleep(2)
    except (WebSocketDisconnect, Exception):
        return
