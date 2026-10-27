"""FASE 9 — PROPOSTA (NÃO importado pela produção). Função pura de saída do PaperLedger.
mode="current": replica exatamente PaperLedger.update (risk.py, sha a26ca01c...).
mode="proposed" (B): time-stop com hit_t1 honra 50% em T1 + 50% no preço do time-stop.
gap_gross=True (C, opcional): stop bruto também usa preço observado (gap), alinhado ao líquido."""
TIME_STOP_MS = 4 * 3600_000

def _r(t, px):
    long = t["direction"] == "ALTA"
    return ((px - t["entry_px"]) if long else (t["entry_px"] - px)) / t["r_unit"]

def decide_exit(t, price, now, mode="current", gap_gross=False):
    """t: dict da operação (muta hit_t1/stop como o ledger). Retorna None ou (motivo, result_r_bruto, legs)."""
    long = t["direction"] == "ALTA"
    hit_stop = price <= t["stop"] if long else price >= t["stop"]
    hit_t1 = price >= t["t1"] if long else price <= t["t1"]
    hit_t2 = price >= t["t2"] if long else price <= t["t2"]
    if hit_t1 and not t["hit_t1"]:
        t["hit_t1"] = True; t["stop"] = t["entry_px"]
    if hit_t2:
        legs = [(0.5, t["t1"]), (0.5, t["t2"])]; return "T2", 0.5 * _r(t, t["t1"]) + 0.5 * _r(t, t["t2"]), legs
    if hit_stop:
        if t["hit_t1"]:
            legs = [(0.5, t["t1"]), (0.5, price)]
            return "STOP_POS_T1", 0.5 * _r(t, t["t1"]) + (0.5 * _r(t, price) if gap_gross else 0.0), legs
        return "STOP", (_r(t, price) if gap_gross else -1.0), [(1.0, price)]
    if now - t["opened_ts"] > TIME_STOP_MS:
        if t["hit_t1"] and mode == "proposed":
            legs = [(0.5, t["t1"]), (0.5, price)]
            return "TIME_STOP_POS_T1", 0.5 * _r(t, t["t1"]) + 0.5 * _r(t, price), legs
        return "TIME_STOP", _r(t, price), [(1.0, price)]
    return None
