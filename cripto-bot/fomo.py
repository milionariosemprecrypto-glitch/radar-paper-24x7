"""Estratégia 5: FOMO/narrativas (paper). Escolhe diariamente 3 moedas 'quentes' e segura com regras de saída.
Fontes públicas sem chave: CoinGecko (trending, mercados com variação 24h/7d, categorias/narrativas) + Binance (listagem/volume/preço)."""
import time, requests
import engine as E

FEE = 0.001; SLIP = 0.003         # taxa 0,1% + slippage 0,3% (small caps) por lado
TP = 0.20; SL = 0.10; MAX_H = 72  # +20% / -10% / 3 dias
SLOTS = 3
MIN_GLOBAL_VOL = 50e6             # volume 24h global (CoinGecko) mínimo
MIN_BINANCE_VOL = 5e6             # e precisa ter par USDT na Binance com liquidez mínima
EXCLUDE = {"BTC","ETH","USDT","USDC","FDUSD","USD1","DAI","TUSD","USDE","PYUSD","BUSD","USDS","EURC","EUR","WBTC","WETH","STETH","WBETH","WEETH","CBBTC","BFUSD","XUSD","RLUSD","USDD","FRAX","PAXG","XAUT","U"}
CG = "https://api.coingecko.com/api/v3"
def is_stock(m):  # ações tokenizadas (ex.: CRCLB "bStocks") não são cripto -> fora
    t = (m.get("name", "") + " " + m.get("id", "")).lower()
    return "stock" in t or "tokenized" in t

def _cg(path, **p):
    for i in range(3):
        r = requests.get(CG + path, params=p, timeout=20)
        if r.status_code == 429: time.sleep(20 * (i + 1)); continue
        r.raise_for_status(); return r.json()
    r.raise_for_status()

def binance_24h():
    return {x["symbol"]: x for x in E._get("/api/v3/ticker/24hr", {})}

def all_prices():
    return {x["symbol"]: float(x["price"]) for x in E._get("/api/v3/ticker/price", {})}

def pick_live(exclude_syms=()):
    """Retorna lista [(symbol, score, motivo)] ordenada. Pontuação transparente:
    BTC/ETH e quem caiu em 24h ficam de fora; trending CoinGecko (até +3), percentil da alta 24h (até +2), percentil da alta 7d (até +1),
    estar entre as top-3 moedas de uma das 5 narrativas/categorias que mais subiram em 24h (+1)."""
    trending = _cg("/search/trending")
    trend_rank = {c["item"]["id"]: i for i, c in enumerate(trending.get("coins", []))}
    mk = []
    for page in (1, 2):
        mk += _cg("/coins/markets", vs_currency="usd", order="volume_desc", per_page=250, page=page, price_change_percentage="24h,7d")
    cats = _cg("/coins/categories", order="market_cap_change_24h_desc")
    cats = [c for c in cats if (c.get("market_cap") or 0) > 300e6 and (c.get("volume_24h") or 0) > 50e6][:5]
    cat_of = {}
    for c in cats:
        for cid in c.get("top_3_coins_id") or []: cat_of.setdefault(cid, f"{c['name']} {c['market_cap_change_24h']:+.1f}%")
    bn = binance_24h()
    cands = []
    for m in mk:
        sym = (m["symbol"] or "").upper(); bsym = sym + "USDT"
        if sym in EXCLUDE or bsym in exclude_syms or bsym not in bn or is_stock(m): continue
        if (m.get("total_volume") or 0) < MIN_GLOBAL_VOL or float(bn[bsym]["quoteVolume"]) < MIN_BINANCE_VOL: continue
        p = m.get("current_price") or 0
        c24 = m.get("price_change_percentage_24h_in_currency"); c7 = m.get("price_change_percentage_7d_in_currency")
        if c24 is None or c7 is None or (abs(p - 1) < 0.03 and abs(c7) < 3): continue
        if c24 <= 0: continue  # FOMO = só persegue o que está subindo nas últimas 24h
        cands.append(dict(id=m["id"], bsym=bsym, c24=c24, c7=c7, vol=m["total_volume"], bvol=float(bn[bsym]["quoteVolume"])))
    if not cands: return []
    def pct(key, x): v = sorted(c[key] for c in cands); return v.index(x) / max(1, len(v) - 1)
    out = []
    for c in cands:
        sc = 2 * pct("c24", c["c24"]) + pct("c7", c["c7"]); why = [f"24h {c['c24']:+.1f}%", f"7d {c['c7']:+.1f}%"]
        if c["id"] in trend_rank: sc += 3 - 0.1 * trend_rank[c["id"]]; why.append(f"trending CoinGecko #{trend_rank[c['id']]+1}")
        if c["id"] in cat_of: sc += 1; why.append(f"narrativa: {cat_of[c['id']]}")
        why.append(f"vol global ${c['vol']/1e6:.0f}M, Binance ${c['bvol']/1e6:.0f}M")
        out.append((c["bsym"], round(sc, 3), "; ".join(why)))
    return sorted(out, key=lambda x: -x[1])

class FomoPortfolio:
    def __init__(self, name="fomo", usdt=E.CAPITAL, positions=None, fees=0.0, ntrades=0, on_trade=None, **_):
        self.name, self.usdt, self.positions, self.fees, self.ntrades = name, usdt, positions or {}, fees, ntrades
        self.btc = 0.0; self.marks = {}; self.on_trade = on_trade
    def buy(self, ts, sym, price, quote, note):
        quote = min(quote, self.usdt)
        if quote < 1: return
        px = price * (1 + SLIP); fee = quote * FEE; qty = (quote - fee) / px
        self.usdt -= quote; self.fees += fee; self.ntrades += 1
        self.positions[sym] = {"qty": qty, "entry": px, "ts": ts}; self.marks[sym] = price
        if self.on_trade: self.on_trade(self.name, ts, "BUY", px, qty, quote, fee, note, symbol=sym)
    def sell(self, ts, sym, price, note):
        p = self.positions.pop(sym); px = price * (1 - SLIP); gross = p["qty"] * px; fee = gross * FEE
        self.usdt += gross - fee; self.fees += fee; self.ntrades += 1
        if self.on_trade: self.on_trade(self.name, ts, "SELL", px, p["qty"], gross, fee, f"{note} ({(px/p['entry']-1)*100:+.1f}% bruto)", symbol=sym)
    def equity(self, _price=None):
        return self.usdt + sum(p["qty"] * self.marks.get(s, p["entry"]) for s, p in self.positions.items())
    def to_dict(self): return {"usdt": self.usdt, "positions": self.positions, "fees": self.fees, "ntrades": self.ntrades}

class Fomo:
    name = "fomo"
    def __init__(self, on_trade=None, st=None):
        st = st or {}; self.pf = FomoPortfolio(**st.get("pf", {}), on_trade=on_trade); self.next_pick = st.get("next_pick", 0)
    def to_dict(self): return {"pf": self.pf.to_dict(), "next_pick": self.next_pick}
    def check_exits(self, ts, sym, price, low=None, high=None):
        """Saídas: stop -10% (prioridade, conservador), alvo +20%, ou 72h."""
        p = self.pf.positions[sym]; low = price if low is None else low; high = price if high is None else high
        if low <= p["entry"] * (1 - SL): return self.pf.sell(ts, sym, min(price if low == price else p["entry"] * (1 - SL), p["entry"] * (1 - SL)), "stop loss -10%")
        if high >= p["entry"] * (1 + TP): return self.pf.sell(ts, sym, max(p["entry"] * (1 + TP), price if high == price else 0), "take profit +20%")
        if ts - p["ts"] >= MAX_H * 3600_000: return self.pf.sell(ts, sym, price, "saída por tempo (3 dias)")
    def fill(self, ts, ranked, prices, note_prefix, log_pick=None):
        empty = SLOTS - len(self.pf.positions); chosen = []
        for sym, sc, why in ranked:
            if len(chosen) >= empty: break
            if sym in self.pf.positions or sym not in prices: continue
            chosen.append((sym, sc, why))
        for i, (sym, sc, why) in enumerate(chosen):
            self.pf.buy(ts, sym, prices[sym], self.pf.usdt / (len(chosen) - i), f"{note_prefix}: {why}")
            if log_pick: log_pick(ts, sym, sc, why)
        return chosen
