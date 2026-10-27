"""Fase 6: custos do PaperLedger (taxa, slippage, gap no stop, funding)."""
from app.engine.risk import RiskGuard, PaperLedger, net_result
T0 = 1_800_000_000_000
def sig(direction="ALTA", e=100.0, stop=98.0, t1=104.0, t2=106.0, sym="X"):
    return {"id": f"{sym}-1", "sym": sym, "direction": direction, "entry_px": e, "stop": stop, "t1": t1, "t2": t2, "risk_pct": 0.25, "ts": T0}
def led(**kw): return PaperLedger(RiskGuard(), None, **kw)

def test_zero_costs_equals_gross():
    L = led(costs=True, fee_pct=0, slip_pct=0); L.open_trade(sig()); L.update("X", 106.0, T0 + 1000)
    t = L.closed[0]; assert t["result_r_gross"] == t["result_r_net"] == 2.5

def test_fee_and_slippage_reduce_result_long_target():
    L = led(costs=True, fee_pct=0.1, slip_pct=0.05); L.open_trade(sig()); L.update("X", 106.0, T0 + 1000)
    t = L.closed[0]; ef = 100 * 1.0005; x1, x2 = 104 * 0.9995, 106 * 0.9995
    exp = (0.5 * (x1 - ef) + 0.5 * (x2 - ef) - 0.001 * (ef + 0.5 * x1 + 0.5 * x2)) / 2.0
    assert abs(t["result_r_net"] - round(exp, 2)) < 1e-9 and t["result_r_net"] < t["result_r_gross"] == 2.5

def test_stop_gap_fills_at_observed_price_not_stop():
    L = led(costs=True, fee_pct=0, slip_pct=0); L.open_trade(sig()); L.update("X", 95.0, T0 + 1000)   # gap de 98 -> 95
    t = L.closed[0]; assert t["result_r_gross"] == -1.0 and t["result_r_net"] == -2.5

def test_short_stop_gap_with_slippage():
    L = led(costs=True, fee_pct=0.1, slip_pct=0.05); L.open_trade(sig("BAIXA", 100, 102, 96, 94)); L.update("X", 103.0, T0 + 1000)
    t = L.closed[0]; ef = 100 * 0.9995; x = 103 * 1.0005; exp = (-(x - ef) - 0.001 * (ef + x)) / 2.0
    assert abs(t["result_r_net"] - round(exp, 2)) < 1e-9 and t["result_r_net"] < -1.5

def test_guard_receives_net_when_costs_on_and_gross_when_off():
    for on, key in ((True, "result_r_net"), (False, "result_r_gross")):
        L = led(costs=on, fee_pct=0.1, slip_pct=0.05); L.open_trade(sig()); L.update("X", 97.0, T0 + 1000)
        assert abs(L.guard.day_pnl_pct - L.closed[0][key] * 0.25) < 0.01

def test_funding_only_when_enabled_and_sign():
    t = {"direction": "ALTA", "entry_px": 100.0, "r_unit": 2.0, "opened_ts": T0}
    r0, _ = net_result(t, [(1.0, 100.0)], 0, 0, None, T0 + 8 * 3600_000)
    r1, i1 = net_result(t, [(1.0, 100.0)], 0, 0, 0.0001, T0 + 8 * 3600_000)
    assert r0 == 0 and abs(i1["funding_r"] - 0.005) < 1e-12 and r1 < 0          # long paga 0,01%/8h
    t["direction"] = "BAIXA"; r2, _ = net_result(t, [(1.0, 100.0)], 0, 0, 0.0001, T0 + 8 * 3600_000); assert r2 > 0   # short recebe
    L = led(costs=True, fee_pct=0, slip_pct=0, funding=False, funding_rate_fn=lambda s: 0.01); L.open_trade(sig()); L.update("X", 106, T0 + 1000)
    assert L.closed[0]["funding_r"] is None

def test_stats_keep_gross_and_net():
    L = led(costs=True); L.open_trade(sig()); L.update("X", 106.0, T0 + 1000); s = L.stats()
    assert s["soma_R_bruto"] == s["soma_R"] == 2.5 and s["soma_R_liquido"] < 2.5 and s["custos"]["spread"].startswith("não")
