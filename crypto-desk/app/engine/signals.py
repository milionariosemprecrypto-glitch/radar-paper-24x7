"""Transforma score em: SINAL DE ENTRADA (paper) ou ALERTA DE ATENÇÃO, com explicação simples.
Regra de ouro: nunca há sinal com menos de 3 confluências independentes."""
from .. import config
from .indicators import swing
MIN_CONF = 3

def build(f, sc, guard=None, now=0):
    sym, p = f["sym"], f.get("price")
    alerts = []
    if f.get("liq_exhaustion"):
        alerts.append(f"Liquidação grande de {f['liq_exhaustion']} em 15m: cuidado com exaustão/reversão rápida (squeeze).")
    if f.get("news_high"):
        alerts.append("Notícia/post de alto impacto: " + f["news_high"][0][:120] + " — esperar confirmação de preço, volume e CVD.")
    base = {"sym": sym, "ts": now, "score": sc["score"], "direction": sc["direction"], "status": sc["status"], "confluences": sc["confluences"],
            "price": p, "alerts": alerts}
    why = [x["text"] for x in sorted(sc["factors"], key=lambda x: -abs(x["points"])) if x["points"] != 0][:5]
    n = len(sc["confluences"])
    if abs(sc["score"]) < 30 or n < MIN_CONF or not p or not f.get("atr15"):
        reason = ("Score fraco (|score| < 30)" if abs(sc["score"]) < 30 else f"Só {n} confluência(s) – o mínimo é {MIN_CONF}") if p else "sem preço"
        kind = "alerta" if (alerts or abs(sc["score"]) >= 30) else "nenhum"
        return {**base, "kind": kind, "title": "ALERTA DE ATENÇÃO" if kind == "alerta" else "Sem sinal", "explain": reason + ". Não é hora de entrar; só observe.", "why": why}
    long = sc["score"] > 0
    # notícia de alto impacto só vira entrada se tendência, CVD e volume confirmarem
    if f.get("news_high"):
        tr = next(x for x in sc["factors"] if x["key"] == "tendencia")["points"]; cv = next(x for x in sc["factors"] if x["key"] == "cvd")["points"]
        vol_ok = (f.get("vol_ratio") or 0) >= 1.3
        if not (tr * sc["score"] > 0 and cv * sc["score"] > 0 and vol_ok):
            return {**base, "kind": "alerta", "title": "ALERTA DE ATENÇÃO (notícia)", "why": why,
                    "explain": "Há notícia de alto impacto, mas preço, volume e fluxo (CVD) ainda não confirmaram. Espere."}
    if guard:
        ok, msg = guard.check(sym, now)
        if not ok:
            return {**base, "kind": "alerta", "title": "ALERTA (risco bloqueou entrada)", "explain": "Setup existe, mas a gestão de risco bloqueou: " + msg, "why": why}
    atr = f["atr15"]; lo, hi = swing(f.get("candles15", []), 8)
    e21 = f.get("ema21") or p
    if long:
        entry_px = min(p, e21) if p - e21 < 0.6 * atr else p; entry_txt = f"Reteste da EMA21 (~{e21:.6g}) com CVD comprador, ou rompimento acima de {hi:.6g}" if hi else "preço atual"
        stop = (lo or p - atr) - 0.25 * atr
    else:
        entry_px = max(p, e21) if e21 - p < 0.6 * atr else p; entry_txt = f"Reteste da EMA21 (~{e21:.6g}) com CVD vendedor, ou perda de {lo:.6g}" if lo else "preço atual"
        stop = (hi or p + atr) + 0.25 * atr
    r = abs(entry_px - stop)
    if r <= 0: r = atr
    t1, t2 = (entry_px + r, entry_px + 2 * r) if long else (entry_px - r, entry_px - 2 * r)
    hm = f.get("heatmap"); target_note = "alvos 1R/2R"
    if hm:
        cl = sorted([c["price"] for c in (hm["short_clusters"] if long else hm["long_clusters"])], reverse=not long)
        cl = [c for c in cl if (c > entry_px + 0.5 * r if long else c < entry_px - 0.5 * r)]
        if cl:
            t1 = cl[0]; t2 = cl[1] if len(cl) > 1 and abs(cl[1] - entry_px) > abs(t1 - entry_px) else (entry_px + 2 * r if long else entry_px - 2 * r)
            if abs(t2 - entry_px) < abs(t1 - entry_px): t1, t2 = t2, t1
            target_note = "alvos nos clusters de liquidação ESTIMADOS"
    risk_pct = config.RISK_MAX_PCT if abs(sc["score"]) >= 60 and n >= 4 else config.RISK_MIN_PCT
    stop_pct = abs(entry_px - stop) / entry_px * 100
    lev = min(config.MAX_LEVERAGE, max(1, round(risk_pct / stop_pct, 1))) if stop_pct else 1
    return {**base, "kind": "entrada", "title": f"SINAL DE ENTRADA (simulado) – {'COMPRA' if long else 'VENDA'}",
            "entry": entry_txt, "entry_px": entry_px, "stop": stop, "t1": t1, "t2": t2, "risk_pct": risk_pct, "leverage_max": lev,
            "invalidation": f"Fechamento de 15m {'abaixo' if long else 'acima'} de {stop:.6g} invalida a ideia.",
            "why": why, "id": f"{sym}-{now}",
            "explain": f"{n} confluências a favor de {'ALTA' if long else 'BAIXA'} ({', '.join(sc['confluences'])}). Risco sugerido {risk_pct}% da banca, alavancagem no máximo {lev}x; {target_note}. É SIMULAÇÃO: não envia ordem."}
