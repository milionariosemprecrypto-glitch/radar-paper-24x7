"""Testes das regras de score/sinal/risco (sem rede)."""
import time
from app.engine import score, signals
from app.engine.risk import RiskGuard, PaperLedger
from app.engine.classify import classify
from app.engine.heatmap import estimate
from app.providers.news_rss import analyze
from app.providers.whales_free import parse

NOW = int(time.time() * 1000)

def candles(n=60, start=100.0, step=0.1):
    out = []; p = start
    for i in range(n):
        o = p; p = p + step; out.append([NOW - (n - i) * 900_000, o, max(o, p) + 0.05, min(o, p) - 0.05, p, 1e6])
    return out

def bull_features(**kw):
    c = candles()
    f = {"sym": "TEST", "price": c[-1][4] + 0.05, "ema9": c[-1][4] - 0.2, "ema21": c[-1][4] - 0.8, "ema50": c[-1][4] - 2.0, "trend1h": 1,
         "atr15": 0.3, "atr_pct": 0.3, "oi_chg_1h": 2.0, "price_chg_1h": 0.8, "funding_avg": 0.0001, "ls_ratio": 1.0,
         "liq_long_15m": 0, "liq_short_15m": 0, "cvd_15m": 5e6, "cvd_15m_ratio": 0.4, "taker_ratio_1h": 0.6, "book_imb": 0.3,
         "depth_usd": 5e6, "whale_net_usd": 0, "whale_count": 0, "news_bias": 0, "news_high": [], "heatmap": None, "candles15": c, "vol_ratio": 1.5}
    f.update(kw); return f

def test_strong_bull_gives_entry():
    f = bull_features(); sc = score.compute(f)
    assert sc["score"] >= 30 and len(sc["confluences"]) >= 3
    s = signals.build(f, sc, RiskGuard(), NOW)
    assert s["kind"] == "entrada" and s["direction"] == "ALTA"
    assert s["stop"] < s["entry_px"] < s["t1"] < s["t2"]
    assert s["risk_pct"] <= 0.5 and s["leverage_max"] <= 3
    assert s["explain"] and s["why"]

def test_less_than_3_confluences_never_signals():
    # só tendência + derivativos fortes; resto neutro/ausente => 2 grupos
    f = bull_features(cvd_15m_ratio=None, taker_ratio_1h=None, book_imb=None, liq_long_15m=0, liq_short_15m=0)
    sc = score.compute(f)
    sc["score"] = 80  # mesmo forçando score alto
    sc["confluences"] = [g for g in sc["confluences"] if g in ("estrutura de preço", "derivativos")]
    assert len(sc["confluences"]) < 3
    s = signals.build(f, sc, RiskGuard(), NOW)
    assert s["kind"] != "entrada"

def test_extreme_funding_reduces_confidence_in_crowded_direction():
    normal = score.compute(bull_features())
    crowded = score.compute(bull_features(funding_avg=0.001))
    assert crowded["mult"] <= 0.7 and crowded["score"] < normal["score"]
    assert any("funding extremo" in n for n in crowded["notes"])

def test_oi_price_rules():
    up = score.compute(bull_features(oi_chg_1h=2, price_chg_1h=1))
    dn = score.compute(bull_features(oi_chg_1h=2, price_chg_1h=-1))
    g = lambda sc: next(x for x in sc["factors"] if x["key"] == "oi_preco")
    assert g(up)["points"] > 0 and "continuação" in g(up)["text"]
    assert g(dn)["points"] < 0 and "pressão vendedora" in g(dn)["text"]

def test_one_sided_liquidation_is_exhaustion_alert():
    f = bull_features(liq_short_15m=20e6, liq_long_15m=0.2e6)
    sc = score.compute(f); s = signals.build(f, sc, RiskGuard(), NOW)
    assert f.get("liq_exhaustion") == "shorts"
    assert any("exaustão" in a for a in s["alerts"])

def test_high_impact_news_without_confirmation_is_only_alert():
    f = bull_features(news_high=["Trump announces tariffs"], vol_ratio=0.8)
    sc = score.compute(f); s = signals.build(f, sc, RiskGuard(), NOW)
    assert s["kind"] == "alerta" and "notícia" in s["title"].lower()

def test_high_impact_news_with_confirmation_can_enter():
    f = bull_features(news_high=["SEC approves ETF"], vol_ratio=2.0)
    sc = score.compute(f); s = signals.build(f, sc, RiskGuard(), NOW)
    assert s["kind"] == "entrada"

def test_whale_classification():
    assert classify("BTC", 80e6, "unknown wallet", "#Binance")[2] == -1
    assert classify("BTC", 80e6, "#Coinbase", "unknown wallet")[2] == 1
    assert classify("USDT", 80e6, "unknown wallet", "#Binance")[2] == 1
    assert classify("USDC", 80e6, "USDC Treasury", "USDC Treasury", "mint")[2] == 1
    assert classify("ETH", 80e6, "#Binance", "#OKX")[2] == 0

def test_risk_guard_limits():
    g = RiskGuard()
    ok, _ = g.check("BTC", NOW); assert ok
    g.register_open("BTC", NOW); ok, msg = g.check("BTC", NOW + 60_000); assert not ok and "cooldown" in msg
    g.register_close(-1, 0.5); g.register_close(-1, 0.5); ok, msg = g.check("ETH", NOW); assert not ok
    g2 = RiskGuard(); g2._roll(NOW); g2.day_pnl_pct = -1.6; assert not g2.check("SOL", NOW)[0]

def test_paper_ledger_stop_and_target():
    g = RiskGuard(); L = PaperLedger(g)
    L.open_trade({"id": "a", "sym": "BTC", "direction": "ALTA", "entry_px": 100, "stop": 99, "t1": 101, "t2": 102, "risk_pct": 0.25, "ts": NOW})
    L.update("BTC", 98.9, NOW + 1000); assert L.stats()["fechadas"][0]["result_r"] == -1
    L.open_trade({"id": "b", "sym": "ETH", "direction": "BAIXA", "entry_px": 100, "stop": 101, "t1": 99, "t2": 98, "risk_pct": 0.25, "ts": NOW})
    L.update("ETH", 98.9, NOW + 2000); L.update("ETH", 97.9, NOW + 3000)
    assert L.stats()["fechadas"][-1]["result_r"] == 1.5

def test_heatmap_is_labelled_estimate():
    h = estimate(candles(96), [], 106.0, 1.5)
    assert h["label"] == "ESTIMATIVA" and len(h["grid"]) == len(h["longs"]) == len(h["shorts"])
    assert all(p < 106 for p in [c["price"] for c in h["long_clusters"]])

def test_news_keywords_word_boundary():
    assert "war" not in analyze("Bitcoin slides toward $80k")[2]
    s, imp, kws, assets = analyze("Trump announces new tariffs, bitcoin plunges")
    assert s == "negativo" and imp == "alto" and "BTC" in assets

def test_whale_telegram_parser():
    page = '<div data-post="whale_alert_io/1"><div class="tgme_widget_message_text js-message_text" dir="auto">🚨 1,000 #BTC (80,000,000 USD) transferred from unknown wallet to #Binance<br/><br/>Details</div><time datetime="2026-10-24T12:00:00+00:00"></time></div>'
    ev = parse(page)[0]
    assert ev["symbol"] == "BTC" and ev["usd"] == 80e6 and ev["effect"] == -1

def test_env_inline_comment_does_not_enable_paid_key(tmp_path, monkeypatch):
    from app import config
    e = tmp_path / ".env"; e.write_text("COINGLASS_TEST_KEY=        # Hobbyist US$29\n")
    monkeypatch.delenv("COINGLASS_TEST_KEY", raising=False)
    config._load_env(str(e)); import os
    assert os.environ.get("COINGLASS_TEST_KEY") == ""
