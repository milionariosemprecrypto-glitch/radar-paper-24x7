"""Indicadores simples e transparentes."""
def ema(vals, n):
    if not vals: return []
    k = 2 / (n + 1); out = [vals[0]]
    for v in vals[1:]: out.append(v * k + out[-1] * (1 - k))
    return out

def atr(rows, n=14):
    """rows: [ts,o,h,l,c,vol]"""
    if len(rows) < 2: return None
    trs = [max(r[2] - r[3], abs(r[2] - p[4]), abs(r[3] - p[4])) for p, r in zip(rows, rows[1:])]
    return sum(trs[-n:]) / min(n, len(trs))

def pct(a, b):
    return (a - b) / b * 100 if a and b else 0.0

def cvd(trades, since_ms):
    """Soma (compras agressivas - vendas agressivas) em USD desde since_ms. trades: (ts, px, usd, side)."""
    b = s = 0.0
    for ts, px, usd, side in reversed(trades):
        if ts < since_ms: break
        if side == "buy": b += usd
        else: s += usd
    return b - s, b, s

def cvd_series(trades, bucket_ms, n):
    """CVD cumulativo por balde (para gráfico)."""
    if not trades: return []
    end = trades[-1][0]; start = end - bucket_ms * n
    buckets = {}
    for ts, px, usd, side in trades:
        if ts < start: continue
        k = (ts // bucket_ms) * bucket_ms
        buckets[k] = buckets.get(k, 0) + (usd if side == "buy" else -usd)
    out = []; acc = 0
    for k in sorted(buckets): acc += buckets[k]; out.append([k, acc])
    return out

def swing(rows, n=8):
    w = rows[-n:]
    return (min(r[3] for r in w), max(r[2] for r in w)) if w else (None, None)
