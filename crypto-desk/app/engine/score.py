"""Score de antecipação −100…+100. Cada fator tem peso fixo e uma explicação em português simples.
Positivo = viés de ALTA, negativo = viés de BAIXA. Pesos somam 100."""
W = {"tendencia": 20, "oi_preco": 15, "funding": 10, "long_short": 5, "liquidacoes": 10, "clusters": 10,
     "cvd": 15, "book": 5, "baleias": 5, "noticias": 5}
GROUP = {"tendencia": "estrutura de preço", "oi_preco": "derivativos", "funding": "derivativos", "long_short": "derivativos",
         "liquidacoes": "liquidações", "clusters": "liquidações", "cvd": "fluxo", "book": "fluxo", "baleias": "on-chain", "noticias": "notícias"}
FUND_HI, FUND_LO = 0.0005, -0.0003   # 0,05% / −0,03% por 8h = extremo

def clamp(x, m): return max(-m, min(m, x))

def compute(f):
    fx = []
    def add(k, frac, txt):
        if frac is None: fx.append({"key": k, "group": GROUP[k], "points": 0, "max": W[k], "text": "sem dados ainda"}); return
        fx.append({"key": k, "group": GROUP[k], "points": round(clamp(frac, 1) * W[k], 1), "max": W[k], "text": txt})
    p = f.get("price")
    # 1 tendência
    if f.get("ema50") and p:
        s = (1 if p > f["ema9"] > f["ema21"] > f["ema50"] else -1 if p < f["ema9"] < f["ema21"] < f["ema50"] else
             0.5 if p > f["ema21"] > f["ema50"] else -0.5 if p < f["ema21"] < f["ema50"] else 0)
        t1 = f.get("trend1h", 0) or 0
        frac = s * 0.7 + t1 * 0.3
        add("tendencia", frac, {1: "Médias de 15m alinhadas para cima", -1: "Médias de 15m alinhadas para baixo"}.get(s, "Médias de 15m " + ("acima" if s > 0 else "abaixo" if s < 0 else "embaralhadas (sem tendência clara)")) + (", 1h a favor" if t1 * s > 0 else ", 1h contra" if t1 * s < 0 else ""))
    else: add("tendencia", None, "")
    # 2 OI x preço
    oi, pc = f.get("oi_chg_1h"), f.get("price_chg_1h")
    if oi is not None and pc is not None:
        if oi > 0.3 and pc > 0.1: add("oi_preco", min(oi / 2, 1), f"OI +{oi:.1f}% e preço subindo: dinheiro novo comprando → continuação de alta")
        elif oi > 0.3 and pc < -0.1: add("oi_preco", -min(oi / 2, 1), f"OI +{oi:.1f}% e preço caindo: vendedores abrindo posição → pressão vendedora")
        elif oi < -0.3 and pc > 0.1: add("oi_preco", 0.3, f"OI {oi:.1f}% com preço subindo: shorts fechando (alta mais fraca, 'short covering')")
        elif oi < -0.3 and pc < -0.1: add("oi_preco", -0.3, f"OI {oi:.1f}% com preço caindo: longs desistindo (queda por desalavancagem)")
        else: add("oi_preco", 0, f"OI {oi:+.1f}% / preço {pc:+.2f}% em 1h: sem leitura forte")
    else: add("oi_preco", None, "")
    # 3 funding (contrário nos extremos)
    fr = f.get("funding_avg")
    if fr is not None:
        if fr >= FUND_HI: add("funding", -0.8, f"Funding alto ({fr*100:.3f}%/8h): muita gente comprada pagando caro → risco de queda/espremida de longs")
        elif fr <= FUND_LO: add("funding", 0.8, f"Funding negativo ({fr*100:.3f}%/8h): muitos vendidos → risco de 'short squeeze'")
        else: add("funding", 0, f"Funding normal ({fr*100:.3f}%/8h)")
    else: add("funding", None, "")
    # 4 long/short contas (contrário)
    ls = f.get("ls_ratio")
    if ls:
        if ls > 2.5: add("long_short", -0.8, f"Razão long/short {ls:.2f}: varejo muito comprado (sinal contrário)")
        elif ls < 0.8: add("long_short", 0.8, f"Razão long/short {ls:.2f}: varejo muito vendido (sinal contrário)")
        else: add("long_short", (1.6 - ls) / 2, f"Razão long/short {ls:.2f}: equilibrada")
    else: add("long_short", None, "")
    # 5 liquidações recentes (15m) – lado dominante liquidado sugere exaustão daquele movimento
    ll, ls_ = f.get("liq_long_15m", 0), f.get("liq_short_15m", 0); tot = ll + ls_
    if tot > 0:
        dom = (ls_ - ll) / tot
        big = tot >= max(1e6, (f.get("depth_usd") or 0) * 0.5)
        if big and abs(dom) > 0.7:
            # muitos longs liquidados = queda forçada, possível exaustão → leve viés de repique (contrário)
            add("liquidacoes", -dom * 0.6, f"ALERTA: ${tot/1e6:.1f}M liquidados quase só de {'shorts' if dom>0 else 'longs'} em 15m → possível exaustão/'squeeze' terminando")
            f["liq_exhaustion"] = "shorts" if dom > 0 else "longs"
        else: add("liquidacoes", dom * 0.5, f"Liquidações 15m: longs ${ll/1e3:.0f}k / shorts ${ls_/1e3:.0f}k")
    else: add("liquidacoes", 0, "Sem liquidações relevantes nos últimos 15 min")
    # 6 clusters (ímã) — ESTIMATIVA
    hm = f.get("heatmap")
    if hm:
        d = hm["above_share"] - hm["below_share"]
        add("clusters", d, f"[ESTIMATIVA] {'Mais' if d>0 else 'Menos'} liquidações estimadas ACIMA do preço ({hm['above_share']*100:.0f}% acima / {hm['below_share']*100:.0f}% abaixo): o preço costuma ser 'puxado' para onde há mais stops")
    else: add("clusters", None, "")
    # 7 CVD / agressão
    r, tr = f.get("cvd_15m_ratio"), f.get("taker_ratio_1h")
    if r is not None or tr is not None:
        frac = (r or 0) * 2.5 * 0.7 + (((tr or 0.5) - 0.5) * 5) * 0.3
        add("cvd", frac, (f"Agressão 15m: {'compradores' if r>0 else 'vendedores'} dominando (CVD {f.get('cvd_15m',0)/1e6:+.2f}M USD)" if r is not None else "CVD 15m aquecendo (juntando trades ao vivo)") + (f", taker 1h {tr*100:.0f}% compra" if tr else ""))
    else: add("cvd", None, "")
    # 8 book
    bi = f.get("book_imb")
    if bi is not None: add("book", bi * 2, f"Livro ±0,5%: {'mais ordens de compra' if bi>0 else 'mais ordens de venda'} ({bi*100:+.0f}%)")
    else: add("book", None, "")
    # 9 baleias
    wn = f.get("whale_net_usd", 0)
    if f.get("whale_count"): add("baleias", wn / 100e6, f"Baleias 1h: {'saídas de exchange/stablecoins entrando (acumulação)' if wn>0 else 'entradas em exchange (risco de venda)' if wn<0 else 'neutro'} (${wn/1e6:+.0f}M líquido)")
    else: add("baleias", 0, "Sem movimentos grandes de baleias na última hora")
    # 10 notícias (limitado)
    nb = f.get("news_bias", 0)
    add("noticias", clamp(nb / 3, 1), (f"Notícias 30min: viés {'positivo' if nb>0 else 'negativo' if nb<0 else 'neutro'}") + (f" — ALTO IMPACTO: {f['news_high'][0][:80]}" if f.get("news_high") else ""))

    raw = sum(x["points"] for x in fx)
    # multiplicador de confiança por volatilidade/liquidez
    mult = 1.0; notes = []
    ap = f.get("atr_pct")
    if ap is not None and ap < 0.08: mult *= 0.8; notes.append("mercado parado (ATR baixo)")
    if ap is not None and ap > 1.5: mult *= 0.8; notes.append("volatilidade extrema")
    if f.get("depth_usd") is not None and f["depth_usd"] < 200_000: mult *= 0.8; notes.append("livro raso (pouca liquidez)")
    # funding extremo reduz confiança na direção lotada
    if fr is not None and ((fr >= FUND_HI and raw > 0) or (fr <= FUND_LO and raw < 0)):
        mult *= 0.7; notes.append("funding extremo na mesma direção: confiança reduzida")
    score = round(clamp(raw * mult, 100), 1)
    # confluências: grupo concorda se soma do grupo tem o mesmo sinal e ≥35% do peso do grupo
    groups = {}
    for x in fx: groups.setdefault(x["group"], [0, 0]); groups[x["group"]][0] += x["points"]; groups[x["group"]][1] += x["max"]
    sign = 1 if score > 0 else -1 if score < 0 else 0
    agree = [g for g, (pts, mx) in groups.items() if sign and pts * sign >= 0.35 * mx]
    status = "FORTE" if abs(score) >= 60 else "MODERADO" if abs(score) >= 30 else "NEUTRO"
    direction = "ALTA" if score > 0 else "BAIXA" if score < 0 else "—"
    return {"score": score, "raw": round(raw, 1), "mult": round(mult, 2), "notes": notes, "status": status,
            "direction": direction, "factors": fx, "groups": {g: round(v[0], 1) for g, v in groups.items()}, "confluences": agree}
