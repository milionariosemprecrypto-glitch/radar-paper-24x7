"""Mapa de calor de liquidações — ESTIMATIVA PRÓPRIA (não é dado real de posições).
Ideia: posições abertas recentemente (candles de 15m onde o OI subiu) com alavancagens típicas
liquidariam em preços previsíveis. Somamos esse 'peso' numa grade de preços ±8%.
long liq ≈ entrada × (1 − 1/alav + mmr) · short liq ≈ entrada × (1 + 1/alav − mmr)."""
LEV = {5: 0.25, 10: 0.35, 25: 0.25, 50: 0.15}
MMR = 0.005

def estimate(candles15, oi_hist, price, ls_ratio=None, real_liqs=(), bins=64, span=0.08):
    if not price or len(candles15) < 10:
        return None
    lo, hi = price * (1 - span), price * (1 + span); step = (hi - lo) / bins
    longs = [0.0] * bins; shorts = [0.0] * bins
    # OI por candle: variação positiva de OI (5m somados por janela de 15m); sem OI usa volume
    oi = dict(oi_hist)
    def oi_at(ts):
        ks = [k for k in oi if k <= ts]
        return oi[max(ks)] if ks else None
    lf = 0.5
    if ls_ratio:
        lf = ls_ratio / (1 + ls_ratio)
    rows = candles15[-96:]  # ~24h
    for r in rows:
        ts, o, h, l, c, vol = r
        a, b = oi_at(ts), oi_at(ts + 15 * 60_000)
        w = max(b - a, 0) if a and b else vol * 0.02
        if w <= 0: continue
        entry = (h + l + c) / 3
        for lev, share in LEV.items():
            lp = entry * (1 - 1 / lev + MMR); sp = entry * (1 + 1 / lev - MMR)
            for p, arr, f in ((lp, longs, lf), (sp, shorts, 1 - lf)):
                # já liquidadas? se o preço depois cruzou, remove (aprox.: compara com preço atual)
                if (arr is longs and p >= price) or (arr is shorts and p <= price): continue
                i = int((p - lo) / step)
                if 0 <= i < bins: arr[i] += w * share * f
    grid = [round(lo + step * (i + 0.5), 8) for i in range(bins)]
    real = [0.0] * bins
    for ts, side, px, usd, ex in real_liqs:
        i = int((px - lo) / step)
        if 0 <= i < bins: real[i] += usd
    def top(arr, n=3):
        idx = sorted(range(bins), key=lambda i: -arr[i])[:n]
        return [{"price": grid[i], "usd_est": arr[i]} for i in idx if arr[i] > 0]
    tot = (sum(longs) + sum(shorts)) or 1
    return {"label": "ESTIMATIVA", "grid": grid, "longs": longs, "shorts": shorts, "real_liqs": real,
            "long_clusters": top(longs), "short_clusters": top(shorts),
            "above_share": sum(shorts) / tot, "below_share": sum(longs) / tot,
            "method": "OI novo dos últimos ~24h × alavancagens típicas (5x 25%, 10x 35%, 25x 25%, 50x 15%), divisão long/short pela razão de contas OKX."}
