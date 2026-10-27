"""Fase 7: persistência de paper_trades (upsert) e do RiskGuard após restart. Usa SQLite temporário."""
import sqlite3, pytest
from app import config
from app.state import Store
from app.engine.risk import RiskGuard, PaperLedger, trading_day

T0 = 1_793_012_400_000            # 2026-10-26 08:00 -03
H = 3600_000

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "d.sqlite"); monkeypatch.setattr(config, "DB_PATH", p); return p

def sig(sym="X", e=100.0, stop=98.0, t1=104.0, t2=106.0, ts=T0, d="ALTA"):
    return {"id": f"{sym}-{ts}", "sym": sym, "direction": d, "entry_px": e, "stop": stop, "t1": t1, "t2": t2, "risk_pct": 0.25, "ts": ts}

def boot(now=T0, **kw):
    st = Store(); g = RiskGuard(store=st, now=now); return st, g, PaperLedger(g, st, costs=True, fee_pct=0.1, slip_pct=0.05, now=now, **kw)

def rows(p): c = sqlite3.connect(p); c.row_factory = sqlite3.Row; return [dict(r) for r in c.execute("select * from paper_trades")]

def test_open_close_updates_row_not_ignored(dbpath):
    st, g, L = boot(); L.open_trade(sig())
    r = rows(dbpath); assert len(r) == 1 and r[0]["status"] == "aberta" and r[0]["result_r"] is None
    L.update("X", 95.0, T0 + 60_000)            # gap abaixo do stop
    r = rows(dbpath); assert len(r) == 1
    m = L.closed[0]; r = r[0]
    assert r["status"] == "fechada" and r["exit"] == 95.0 and r["closed_ts"] == T0 + 60_000
    assert r["result_r"] == m["result_r"] == r["result_r_gross"] == -1.0
    assert r["result_r_net"] == m["result_r_net"] < -2.5 and r["fees_r"] == m["fees_r"] > 0 and r["stop_initial"] == 98.0

def test_repeated_close_does_not_duplicate(dbpath):
    st, g, L = boot(); L.open_trade(sig()); L.update("X", 97.0, T0 + 60_000)
    pnl, cl = g.day_pnl_pct, g.consec_losses
    t = L.closed[0]
    assert g.register_close(t["result_r_net"], 0.25, trade_id=t["id"], now=T0 + 70_000) is False
    L._save(t); L._save(t)                       # regravar fechamento
    L.update("X", 90.0, T0 + 80_000)             # já não está aberta
    assert g.day_pnl_pct == pnl and g.consec_losses == cl and len(rows(dbpath)) == 1 and len(L.closed) == 1

def test_closed_row_never_reverts_to_open(dbpath):
    st, g, L = boot(); s = sig(); L.open_trade(s); L.update("X", 106.0, T0 + 1000)
    st.upsert_paper_trade(dict(id=s["id"], sym="X", side="ALTA", opened_ts=T0, entry=100, stop=98, t1=104, t2=106, risk_pct=.25, status="aberta"))
    assert rows(dbpath)[0]["status"] == "fechada" and rows(dbpath)[0]["result_r"] == 2.5

def test_restart_restores_risk_state_and_limits(dbpath, monkeypatch):
    monkeypatch.setattr(config, "COOLDOWN_MIN", 0)
    st, g, L = boot()
    L.open_trade(sig("A", ts=T0)); L.update("A", 97.0, T0 + 1000)
    L.open_trade(sig("B", ts=T0 + 2000)); L.update("B", 97.0, T0 + 3000)
    before = (g.day_pnl_pct, g.trades_today, g.consec_losses)
    assert before[1] == 2 and before[2] == 2 and g.check("C", T0 + 4000)[0] is False
    st2, g2, L2 = boot(now=T0 + 5000)          # "reinício": novo Store/Guard/Ledger no mesmo arquivo
    assert (g2.day_pnl_pct, g2.trades_today, g2.consec_losses) == before
    ok, why = g2.check("C", T0 + 6000); assert ok is False and "perdas seguidas" in why
    assert len(L2.closed) == 2 and L2.closed[0]["result_r_net"] == L.closed[0]["result_r_net"]
    # reaplicar fechamentos restaurados não duplica
    for t in L2.closed: assert g2.register_close(t["result_r_net"], .25, trade_id=t["id"], now=T0 + 7000) is False
    assert g2.day_pnl_pct == before[0]
    s = g2.state(T0 + 8000); assert s["estado"]["origem"] == "sqlite" and s["estado"]["atualizado_ts"] == T0 + 3000 and s["estado"]["idade_s"] == 5.0

def test_restart_with_open_position_keeps_tracking_and_no_double_open(dbpath):
    st, g, L = boot(); L.open_trade(sig()); L.update("X", 104.5, T0 + 1000)   # bate T1 -> stop na entrada
    st2, g2, L2 = boot(now=T0 + 2000)
    t = L2.open["X"]; assert t["hit_t1"] and t["stop"] == 100.0 and t["r_unit"] == 2.0 and g2.trades_today == 1
    L2.open_trade(sig()); assert g2.trades_today == 1                          # mesmo sinal: não reconta
    L2.update("X", 99.9, T0 + 3000)
    assert L2.closed[-1]["result_r_gross"] == 1.0 and rows(dbpath)[0]["status"] == "fechada"

def test_stale_open_rows_become_orphans_untouched(dbpath):
    st, g, L = boot(); L.open_trade(sig())
    st2, g2, L2 = boot(now=T0 + 5 * H)
    L2._restore.__func__  # noqa
    L3 = PaperLedger(g2, st2); L3.open.clear(); L3.orphans.clear(); L3._restore(now=T0 + 5 * H)
    assert L3.open == {} and L3.orphans[0]["id"] == "X-" + str(T0) and rows(dbpath)[0]["status"] == "aberta"

def test_day_rolls_in_sao_paulo(dbpath):
    assert trading_day(1_793_069_700_000) == "2026-10-26"           # 23:55 -03 (02:55 UTC do dia 27)
    assert trading_day(1_793_069_700_000 + 10 * 60_000) == "2026-10-27"
    st, g, L = boot(); L.open_trade(sig()); L.update("X", 97.0, T0 + 1000); assert g.trades_today == 1
    st2 = Store(); g2 = RiskGuard(store=st2, now=T0 + 20 * H)
    assert g2.day == "2026-10-27" and g2.trades_today == 0 and g2.day_pnl_pct == 0

def test_persist_failure_is_fail_closed(dbpath):
    st, g, L = boot(); st.db.close()
    L.open_trade(sig()); ok, why = g.check("Y", T0 + 99 * 60_000)
    assert ok is False and "inconsistente" in why and g.state(T0)["estado"]["consistente"] is False and st.persist_errors > 0

def test_corrupt_state_is_fail_closed(dbpath):
    st = Store(); st.kv_set("risk_guard_v1", {"day": "x"})
    g = RiskGuard(store=st, now=T0); assert g.check("X", T0)[0] is False

def test_migration_is_additive_and_preserves_old_rows(tmp_path, monkeypatch):
    p = str(tmp_path / "old.sqlite"); c = sqlite3.connect(p)
    c.execute("CREATE TABLE paper_trades (id TEXT PRIMARY KEY, sym TEXT, side TEXT, opened_ts INTEGER, entry REAL, stop REAL, t1 REAL, t2 REAL, risk_pct REAL, closed_ts INTEGER, exit REAL, result_r REAL, status TEXT)")
    c.execute("INSERT INTO paper_trades VALUES ('OLD-1','ETH','BAIXA',1,10,11,9,8,.25,NULL,NULL,NULL,'aberta')"); c.commit(); c.close()
    monkeypatch.setattr(config, "DB_PATH", p); Store(); Store()          # 2x: idempotente
    r = rows(p); assert len(r) == 1 and r[0]["id"] == "OLD-1" and r[0]["status"] == "aberta" and "result_r_net" in r[0]

def test_first_boot_rebuilds_day_from_paper_trades(dbpath):
    st, g, L = boot(); L.open_trade(sig()); L.update("X", 97.0, T0 + 1000)
    st.db.execute("DELETE FROM risk_state"); st.db.commit()          # simula 1º boot sem estado salvo (só no banco de teste)
    g2 = RiskGuard(store=Store(), now=T0 + 2000)
    assert g2.state(T0 + 2000)["estado"]["origem"] == "reconstruido_paper_trades"
    assert (g2.trades_today, g2.consec_losses, round(g2.day_pnl_pct, 6)) == (1, 1, round(g.day_pnl_pct, 6))
    t = L.closed[0]; assert g2.register_close(t["result_r_net"], .25, trade_id=t["id"]) is False
