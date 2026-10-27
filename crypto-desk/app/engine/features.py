"""Extrai números simples do estado ao vivo para o motor de score (função pura sobre AssetState)."""
from .indicators import ema, atr, pct, cvd
from .heatmap import estimate
from ..state import now_ms

MACRO = {"tariff", "tarifa", "war", "guerra", "rate cut", "rate hike", "fomc", "powell", "cpi", "inflation", "inflação", "trump", "musk", "etf", "ban", "hack", "exploit", "bitcoin reserve", "strategic reserve", "regulation", "sec "}

def build(a, whales=(), news=(), now=None):
    now = now or now_ms(); f = {"sym": a.sym, "price": a.price}
    c15 = a.candles.get("15m", []); c1h = a.candles.get("1H", [])
    closes = [r[4] for r in c15]
    if len(closes) >= 50:
        e9, e21, e50 = ema(closes, 9)[-1], ema(closes, 21)[-1], ema(closes, 50)[-1]
        f.update(ema9=e9, ema21=e21, ema50=e50)
    if len(c1h) >= 21:
        h = [r[4] for r in c1h]; e = ema(h, 21)
        f["trend1h"] = 1 if h[-1] > e[-1] and e[-1] > e[-4] else -1 if h[-1] < e[-1] and e[-1] < e[-4] else 0
    f["atr15"] = atr(c15[-30:]) if c15 else None
    f["atr_pct"] = (f["atr15"] / a.price * 100) if f["atr15"] and a.price else None
    if len(c15) >= 21:
        vols = [r[5] for r in c15[-21:-1]]; f["vol_ratio"] = c15[-1][5] / (sum(vols) / len(vols)) if sum(vols) else None
        f["price_chg_1h"] = pct(closes[-1], closes[-5])
    # OI 1h (OKX 5m)
    oh = a.oi_hist
    if len(oh) >= 13: f["oi_chg_1h"] = pct(oh[-1][1], oh[-13][1])
    fr = [v for v in a.funding.values() if v is not None]
    f["funding_avg"] = sum(fr) / len(fr) if fr else None
    f["ls_ratio"] = a.ls_ratio
    # liquidações reais últimos 15 min
    t15 = now - 15 * 60_000
    f["liq_long_15m"] = sum(x[3] for x in a.liqs if x[0] >= t15 and x[1] == "long")
    f["liq_short_15m"] = sum(x[3] for x in a.liqs if x[0] >= t15 and x[1] == "short")
    # CVD 15m e 5m (trades WS) + taker 1h (rubik)
    f["cvd_15m"], b, s = cvd(a.trades, t15); f["cvd_15m_ratio"] = (b - s) / (b + s) if b + s else None
    f["cvd_ready"] = bool(a.trades) and a.trades[0][0] <= t15 + 60_000
    if not f["cvd_ready"]: f["cvd_15m_ratio"] = None   # ainda juntando 15 min de trades ao vivo
    f["cvd_5m"], _, _ = cvd(a.trades, now - 5 * 60_000)
    tk = a.taker[-12:]
    if tk:
        tb = sum(x[1] for x in tk); ts_ = sum(x[2] for x in tk); f["taker_ratio_1h"] = tb / (tb + ts_) if tb + ts_ else None
    band = (a.depth.get("bands") or {}).get("0.5%")
    f["book_imb"] = band["imbalance"] if band else None
    f["depth_usd"] = (band["bids_usd"] + band["asks_usd"]) if band else None
    # baleias 1h: efeito ponderado por US$ (do ativo ou stablecoins)
    w1h = [w for w in whales if w["ts"] >= now - 3600_000 and (w["symbol"] == a.sym or w["symbol"] in ("USDT", "USDC"))]
    f["whale_net_usd"] = sum(w["effect"] * w["usd"] for w in w1h); f["whale_count"] = len(w1h)
    # notícias 30 min
    n30 = [n for n in news if n["ts"] >= now - 30 * 60_000 and (a.sym in n.get("assets", []) or set(n.get("keywords", [])) & MACRO)]
    f["news_bias"] = sum(1 if n["sentiment"] == "positivo" else -1 if n["sentiment"] == "negativo" else 0 for n in n30 if n["impact"] != "baixo")
    f["news_high"] = [n["title"] for n in n30 if n["impact"] == "alto"][:3]
    f["heatmap"] = estimate(c15, a.oi_hist, a.price, a.ls_ratio, list(a.liqs))
    f["candles15"] = c15
    return f
