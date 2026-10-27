"""Estratégia 6: FOMO LANÇAMENTOS (paper). Compra só moedas LISTADAS RECENTEMENTE na Binance (par USDT <= 30 dias)
que tenham sinal de NARRATIVA atual e liquidez. Saída: +50% (alvo) / -25% (stop) / 14 dias.
Dinheiro fictício, só dados públicos (Binance data-api + CoinGecko pública). Nenhuma ordem real.

Regras (transparentes):
- Universo: pares XXX/USDT da Binance (status TRADING) cuja 1ª vela diária (USDT e qualquer outro par da mesma moeda)
  tem entre 1 e 30 dias. O dia da listagem (vela parcial, caos de abertura) é pulado.
- Fora: stablecoins, BTC/ETH, ações/ETFs tokenizados (bStocks etc.: o preço segue a ação, não é "lançamento" de cripto).
- Liquidez: volume 24h na Binance >= US$5M.
- Narrativa (precisa de >= 1): (a) está no trending da CoinGecko; (b) pertence a uma das 10 categorias CoinGecko que mais
  sobem em 24h (cap. > US$100M); (c) pertence a uma narrativa da lista quente (IA, agentes de IA, memes, RWA,
  ações tokenizadas/Robinhood, perps/derivativos, DePIN, predição...) E essa categoria está subindo em 24h.
- Score = trending (até +3) + categoria top-10 em alta (+2) + narrativa da lista subindo (+1) + quanto mais nova (até +1)
  + percentil do volume (até +1) + percentil da variação 24h (até +1). Moeda antiga só nova na Binance (ex.: renome,
  ou listagem tardia) leva -1 e fica marcada no motivo.
- Máx. 3 posições; cada compra = caixa livre / vagas livres (~1/3). Cada moeda é comprada no máx. 1 vez.
- Saídas checadas a cada ciclo (1 min): stop -25% (prioridade), alvo +50%, ou 14 dias.
- Custos: taxa 0,1% + slippage 0,4% por lado."""
import os, json, time, logging
from concurrent.futures import ThreadPoolExecutor
import engine as E, fomo as F

NAME = "fomo_lancamentos"
FEE = 0.001; SLIP = 0.004
TP = 0.50; SL = 0.25; MAX_D = 14
SLOTS = 3
MAX_AGE_D = 30; MIN_AGE_D = 1
MIN_BINANCE_VOL = 5e6
D = 86400_000; H = 3600_000
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "cache", "listings.json")
HOT_WORDS = ("artificial intelligence", "ai agent", "ai ", "meme", "real world asset", "rwa", "tokenized", "stock",
             "robinhood", "perpetual", "derivatives", "depin", "prediction market", "launchpad", "binance alpha",
             "binance hodler", "launchpool")
log = logging.getLogger("bot")

def is_stock_like(name, cid):
    t = f"{name} {cid}".lower()
    return any(k in t for k in ("stock", "tokenized", "bstock", "xstock", " etf", "-etf"))

# ---------------------------------------------------------------- datas de listagem (cache em arquivo)
def _first_kline(sym):
    for i in range(3):
        try:
            b = E._get("/api/v3/klines", {"symbol": sym, "interval": "1d", "startTime": 0, "limit": 1})
            return b[0][0] if b else None
        except Exception:
            time.sleep(2)
    return None

def listings(refresh=True):
    """{symbol USDT: {base, status, usdt_first, base_first}}. Só consulta a Binance para pares que ainda não estão no cache."""
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if not refresh and cache: return cache
    info = E._get("/api/v3/exchangeInfo", {})["symbols"]
    usdt = [x for x in info if x["quoteAsset"] == "USDT"]
    todo = [x for x in usdt if x["symbol"] not in cache or not cache[x["symbol"]].get("usdt_first")]
    if todo:
        with ThreadPoolExecutor(6) as ex: firsts = dict(zip([x["symbol"] for x in todo], ex.map(_first_kline, [x["symbol"] for x in todo])))
        now = time.time() * 1000
        for x in todo:
            t = firsts[x["symbol"]]; bf = t
            if t and now - t < 400 * D:   # par recente: a moeda já existia em outro par (BTC, FDUSD, USDC...)?
                others = [o["symbol"] for o in info if o["baseAsset"] == x["baseAsset"] and o["quoteAsset"] != "USDT"]
                for o in others:
                    ot = _first_kline(o)
                    if ot: bf = min(bf, ot)
            cache[x["symbol"]] = {"base": x["baseAsset"], "status": x["status"], "usdt_first": t, "base_first": bf}
    for x in usdt:
        if x["symbol"] in cache: cache[x["symbol"]]["status"] = x["status"]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"; json.dump(cache, open(tmp, "w")); os.replace(tmp, CACHE)
    return cache

def new_listings(L, now, max_age=MAX_AGE_D, min_age=MIN_AGE_D):
    out = []
    for s, v in L.items():
        if v.get("status") != "TRADING" or not v.get("base_first"): continue
        age = (now - v["base_first"]) / D
        if min_age <= age <= max_age and v["base"] not in F.EXCLUDE: out.append((s, v, age))
    return sorted(out, key=lambda x: x[2])

# ---------------------------------------------------------------- seleção ao vivo
def pick_live(done=(), now=None):
    """Retorna (ranked [(sym, score, motivo)], rejeitados [(sym, motivo)])."""
    now = now or int(time.time() * 1000)
    L = listings(); cands = new_listings(L, now)
    rejected = []
    if not cands: return [], [("-", "nenhum par USDT novo (1-30 dias) na Binance")]
    bn = F.binance_24h()
    trending = F._cg("/search/trending"); trend_rank = {c["item"]["id"]: i for i, c in enumerate(trending.get("coins", []))}
    cats = F._cg("/coins/categories", order="market_cap_change_24h_desc")
    chg = {c["name"]: c.get("market_cap_change_24h") or 0 for c in cats}
    top_cats = [c["name"] for c in cats if (c.get("market_cap") or 0) > 100e6 and (c.get("volume_24h") or 0) > 5e6][:10]
    mk = []
    for page in (1, 2, 3, 4):
        mk += F._cg("/coins/markets", vs_currency="usd", order="volume_desc", per_page=250, page=page, price_change_percentage="24h,7d")
        time.sleep(1.5)
    by_sym = {}
    for m in mk: by_sym.setdefault((m["symbol"] or "").upper(), []).append(m)
    rows = []
    for sym, v, age in cands:
        if sym in done: rejected.append((sym, "já operada antes")); continue
        t = bn.get(sym); bvol = float(t["quoteVolume"]) if t else 0
        ms = sorted(by_sym.get(v["base"], []), key=lambda m: -(m.get("total_volume") or 0))
        if not ms:
            rejected.append((sym, f"sem correspondência na CoinGecko (top 1000 por volume); vol Binance ${bvol/1e6:.1f}M")); continue
        m = ms[0]
        if is_stock_like(m["name"], m["id"]): rejected.append((sym, f"ação/ETF tokenizado ({m['name']})")); continue
        p = m.get("current_price") or 0
        if abs(p - 1) < 0.03 and abs(m.get("price_change_percentage_7d_in_currency") or 0) < 3: rejected.append((sym, "stablecoin")); continue
        if bvol < MIN_BINANCE_VOL: rejected.append((sym, f"liquidez baixa: vol 24h Binance ${bvol/1e6:.1f}M < $5M")); continue
        rows.append(dict(sym=sym, m=m, age=age, bvol=bvol, c24=m.get("price_change_percentage_24h_in_currency") or 0))
    out = []
    for r in rows:
        try:
            info = F._cg(f"/coins/{r['m']['id']}", localization="false", tickers="false", market_data="false",
                         community_data="false", developer_data="false")
            ccats = info.get("categories") or []
        except Exception as e:
            ccats = []; log.warning("LANC: categorias de %s indisponíveis (%s)", r["m"]["id"], e)
        time.sleep(1.5)
        in_top = [c for c in ccats if c in top_cats]
        hot = [c for c in ccats if any(w in (c.lower() + " ") for w in HOT_WORDS) and chg.get(c, 0) > 0]
        tr = trend_rank.get(r["m"]["id"])
        if tr is None and not in_top and not hot:
            rejected.append((r["sym"], f"sem sinal de narrativa (categorias: {', '.join(ccats[:4]) or '—'})")); continue
        vols = sorted(x["bvol"] for x in rows); c24s = sorted(x["c24"] for x in rows); n = max(1, len(rows) - 1)
        sc = 0.0; why = [f"listada na Binance há {r['age']:.0f} dias"]
        if tr is not None: sc += 3 - 0.1 * tr; why.append(f"trending CoinGecko #{tr+1}")
        if in_top: sc += 2; why.append("categoria entre as que mais sobem: " + ", ".join(f"{c} {chg[c]:+.1f}%" for c in in_top[:2]))
        if hot: sc += 1; why.append("narrativa quente subindo: " + ", ".join(f"{c} {chg[c]:+.1f}%" for c in hot[:3]))
        sc += 1 - r["age"] / MAX_AGE_D + vols.index(r["bvol"]) / n + c24s.index(r["c24"]) / n
        old = (r["m"].get("atl_date") or "9999") < time.strftime("%Y-%m-%d", time.gmtime((L[r["sym"]]["base_first"] - 180 * D) / 1000))
        if old: sc -= 1; why.append("ATENÇÃO: moeda antiga (histórico CoinGecko > 6 meses antes), nova só na Binance")
        why.append(f"24h {r['c24']:+.1f}%, vol Binance ${r['bvol']/1e6:.0f}M")
        out.append((r["sym"], round(sc, 3), "; ".join(why)))
    return sorted(out, key=lambda x: -x[1]), rejected

# ---------------------------------------------------------------- carteira e estratégia
class LancPortfolio(F.FomoPortfolio):
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

class FomoLancamentos:
    name = NAME
    def __init__(self, on_trade=None, st=None):
        st = st or {}; pf = dict(st.get("pf", {})); pf["name"] = NAME
        self.pf = LancPortfolio(**pf, on_trade=on_trade)
        self.next_pick = st.get("next_pick", 0); self.done = list(st.get("done", []))
    def to_dict(self): return {"pf": self.pf.to_dict(), "next_pick": self.next_pick, "done": self.done}
    def check_exits(self, ts, sym, price, low=None, high=None, open_=None):
        """Stop -25% tem prioridade (conservador); alvo +50%; 14 dias. low/high/open_ = vela (backtest)."""
        p = self.pf.positions[sym]; lo = price if low is None else low; hi = price if high is None else high
        o = price if open_ is None else open_
        sl, tp = p["entry"] * (1 - SL), p["entry"] * (1 + TP)
        if lo <= sl: return self.pf.sell(ts, sym, min(o, sl), "stop loss -25%")
        if hi >= tp: return self.pf.sell(ts, sym, max(o, tp), "take profit +50%")
        if ts - p["ts"] >= MAX_D * D: return self.pf.sell(ts, sym, price, "saída por tempo (14 dias)")
    def fill(self, ts, ranked, prices, note_prefix, log_pick=None):
        chosen = []
        for sym, sc, why in ranked:
            if len(self.pf.positions) >= SLOTS: break
            if sym in self.pf.positions or sym in self.done or sym not in prices: continue
            free = SLOTS - len(self.pf.positions)
            self.pf.buy(ts, sym, prices[sym], self.pf.usdt / free, f"{note_prefix}: {why}")
            self.done.append(sym); chosen.append((sym, sc, why))
            if log_pick: log_pick(ts, sym, sc, why)
        return chosen
