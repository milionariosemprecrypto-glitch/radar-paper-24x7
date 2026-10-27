"""Núcleo do paper-trading: dados públicos, carteira simulada, estratégias e persistência.
NENHUMA ordem real é enviada. Só dados públicos de mercado (sem chaves de API)."""
import json, sqlite3, time, math, logging
import requests

SYMBOL = "BTCUSDT"
FEE = 0.001        # 0,1% por trade
SLIP = 0.0005      # 0,05% de slippage contra nós em toda execução
CAPITAL = 1000.0   # USDT virtuais por estratégia
BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
_SKIP_BASES = set()  # bases que responderam 451 (geo-block) nesta sessão
log = logging.getLogger("bot")

# ---------------------------------------------------------------- dados
def _get(path, params):
    """Dados públicos. Preferimos data-api.binance.vision; api.binance.com costuma dar 451 fora de região permitida."""
    last = None
    bases = [b for b in BASES if b not in _SKIP_BASES] or list(BASES)
    for base in bases:
        try:
            r = requests.get(base + path, params=params, timeout=15)
            if r.status_code == 451:
                _SKIP_BASES.add(base)
                log.warning("Binance 451 (região restrita) em %s — ignorando este base até reiniciar", base)
                last = requests.HTTPError(f"451 Restricted location: {base}{path}", response=r)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # tenta o próximo endpoint
            last = e
            log.debug("falha %s%s: %s", base, path, e)
    raise last

def klines(interval, start_ms=None, end_ms=None, limit=1000, symbol=SYMBOL):
    p = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None: p["startTime"] = int(start_ms)
    if end_ms is not None: p["endTime"] = int(end_ms)
    rows = _get("/api/v3/klines", p)
    return [{"t": r[0], "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
             "c": float(r[4]), "ct": r[6], "qv": float(r[7])} for r in rows]

def klines_range(interval, start_ms, end_ms=None):
    out, cur = [], int(start_ms)
    while True:
        b = klines(interval, cur, end_ms)
        if not b: break
        out += b
        if len(b) < 1000: break
        cur = b[-1]["t"] + 1
    return out

def closed(bars, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    return [b for b in bars if b["ct"] < now_ms]

def ticker(symbol=SYMBOL):
    return float(_get("/api/v3/ticker/price", {"symbol": symbol})["price"])

# ---------------------------------------------------------------- carteira
class Portfolio:
    def __init__(self, name, usdt=CAPITAL, btc=0.0, fees=0.0, ntrades=0, on_trade=None):
        self.name, self.usdt, self.btc, self.fees, self.ntrades = name, usdt, btc, fees, ntrades
        self.on_trade = on_trade

    def buy(self, ts, price, quote, note=""):
        quote = min(quote, self.usdt)
        if quote < 1: return 0.0
        px = price * (1 + SLIP); fee = quote * FEE; qty = (quote - fee) / px
        self.usdt -= quote; self.btc += qty; self.fees += fee; self.ntrades += 1
        self._log(ts, "BUY", px, qty, quote, fee, note); return qty

    def sell(self, ts, price, qty, note=""):
        qty = min(qty, self.btc)
        if qty * price < 1: return 0.0
        px = price * (1 - SLIP); gross = qty * px; fee = gross * FEE
        self.btc -= qty; self.usdt += gross - fee; self.fees += fee; self.ntrades += 1
        self._log(ts, "SELL", px, qty, gross, fee, note); return gross - fee

    def _log(self, *a):
        if self.on_trade: self.on_trade(self.name, *a)

    def equity(self, price): return self.usdt + self.btc * price
    def to_dict(self): return {"usdt": self.usdt, "btc": self.btc, "fees": self.fees, "ntrades": self.ntrades}

# ---------------------------------------------------------------- estratégias
class Strategy:
    name = "?"
    def __init__(self, on_trade=None, st=None):
        st = st or {}
        self.pf = Portfolio(self.name, **st.get("pf", {}), on_trade=on_trade)
        self.load(st)
    def load(self, st): pass
    def dump(self): return {}
    def to_dict(self): d = self.dump(); d["pf"] = self.pf.to_dict(); return d
    def start(self, ts, price, ctx): pass
    def on_fine_bar(self, bar): pass    # barras finas (1m ao vivo, 1h no backtest) – usado pelo grid
    def on_hour(self, bar): pass        # barra de 1h fechada

class Hold(Strategy):
    name = "hold"
    def start(self, ts, price, ctx): self.pf.buy(ts, price, self.pf.usdt, "compra inicial buy&hold")

class DCA(Strategy):
    name = "dca"
    WEEK = 7 * 24 * 3600 * 1000
    def load(self, st):
        self.amount = st.get("amount", 100.0); self.next_ts = st.get("next_ts", 0); self.n = st.get("n", 0)
    def dump(self): return {"amount": self.amount, "next_ts": self.next_ts, "n": self.n}
    def start(self, ts, price, ctx):
        self.amount = ctx.get("dca_amount", self.amount); self._buy(ts, price)
    def _buy(self, ts, price):
        self.n += 1
        self.pf.buy(ts, price, self.amount, f"DCA semanal #{self.n}")
        self.next_ts = ts + self.WEEK
    def on_hour(self, bar):
        if bar["ct"] >= self.next_ts and self.pf.usdt >= 1: self._buy(bar["ct"], bar["c"])

def ema_step(prev, x, n): return prev + (2 / (n + 1)) * (x - prev)

class EMACross(Strategy):
    """Tendência: comprado 100% quando EMA20 > EMA50 (1h), zerado quando cruza para baixo."""
    name = "ema_20_50"
    def load(self, st): self.e20 = st.get("e20"); self.e50 = st.get("e50")
    def dump(self): return {"e20": self.e20, "e50": self.e50}
    def start(self, ts, price, ctx):
        closes = ctx["closes_1h"]  # histórico p/ aquecer as médias
        self.e20 = self.e50 = closes[0]
        for c in closes[1:]: self.e20 = ema_step(self.e20, c, 20); self.e50 = ema_step(self.e50, c, 50)
        if self.e20 > self.e50: self.pf.buy(ts, price, self.pf.usdt, "início em tendência de alta (EMA20>EMA50)")
    def on_hour(self, bar):
        p20, p50 = self.e20, self.e50
        self.e20 = ema_step(self.e20, bar["c"], 20); self.e50 = ema_step(self.e50, bar["c"], 50)
        if p20 <= p50 and self.e20 > self.e50 and self.pf.usdt >= 1:
            self.pf.buy(bar["ct"], bar["c"], self.pf.usdt, "cruzamento de alta EMA20/50")
        elif p20 >= p50 and self.e20 < self.e50 and self.pf.btc > 0:
            self.pf.sell(bar["ct"], bar["c"], self.pf.btc, "cruzamento de baixa EMA20/50")

class Grid(Strategy):
    """Grid geométrico com N faixas entre mínima e máxima dos 30 dias anteriores.
    Faixa i: compra em L[i], vende em L[i+1]. Cada faixa usa CAPITAL/N USDT."""
    name = "grid"
    N = 20
    def load(self, st):
        self.levels = st.get("levels", []); self.slots = st.get("slots", []); self.slot_quote = st.get("slot_quote", 0)
        self.lo = st.get("lo"); self.hi = st.get("hi")
    def dump(self): return {"levels": self.levels, "slots": self.slots, "slot_quote": self.slot_quote, "lo": self.lo, "hi": self.hi}
    def start(self, ts, price, ctx):
        self.lo, self.hi = ctx["grid_lo"], ctx["grid_hi"]
        r = (self.hi / self.lo) ** (1 / self.N)
        self.levels = [self.lo * r ** i for i in range(self.N + 1)]
        self.slot_quote = self.pf.usdt / self.N
        # faixas cuja compra fica ACIMA do preço atual começam "compradas" (aguardando venda)
        above = [i for i in range(self.N) if self.levels[i] > price]
        self.slots = [None] * self.N  # None = em USDT aguardando compra; float = qtd BTC aguardando venda
        if above:
            qty = self.pf.buy(ts, price, self.slot_quote * len(above), f"compra inicial do grid ({len(above)} faixas acima do preço)")
            for i in above: self.slots[i] = qty / len(above)
    def _segment(self, ts, a, b):
        L = self.levels
        if b < a:   # caindo: executa compras nos níveis atravessados
            for i in range(self.N - 1, -1, -1):
                if self.slots[i] is None and b <= L[i] < a and self.pf.usdt >= 1:
                    self.slots[i] = self.pf.buy(ts, L[i], self.slot_quote, f"grid compra nível {i} ({L[i]:.0f})")
        elif b > a:  # subindo: executa vendas
            for i in range(self.N):
                if self.slots[i] is not None and a < L[i + 1] <= b:
                    self.pf.sell(ts, L[i + 1], self.slots[i], f"grid venda nível {i+1} ({L[i+1]:.0f})")
                    self.slots[i] = None
    def on_fine_bar(self, bar):
        # trajetória intrabarra aproximada: candle de alta O->L->H->C, de baixa O->H->L->C
        path = [bar["o"], bar["l"], bar["h"], bar["c"]] if bar["c"] >= bar["o"] else [bar["o"], bar["h"], bar["l"], bar["c"]]
        for a, b in zip(path, path[1:]): self._segment(bar["ct"], a, b)

STRATS = [Grid, DCA, EMACross, Hold]

# ---------------------------------------------------------------- persistência
SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, ts INTEGER, strategy TEXT, side TEXT, price REAL, qty REAL, quote REAL, fee REAL, note TEXT);
CREATE TABLE IF NOT EXISTS equity(ts INTEGER, strategy TEXT, equity REAL, price REAL, usdt REAL, btc REAL);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS picks(ts INTEGER, symbol TEXT, score REAL, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_eq ON equity(strategy, ts);
"""
def open_db(path):
    db = sqlite3.connect(path); db.executescript(SCHEMA)
    cols = [r[1] for r in db.execute("PRAGMA table_info(trades)")]
    if "symbol" not in cols: db.execute("ALTER TABLE trades ADD COLUMN symbol TEXT DEFAULT 'BTCUSDT'")
    pc = [r[1] for r in db.execute("PRAGMA table_info(picks)")]
    if "strategy" not in pc: db.execute("ALTER TABLE picks ADD COLUMN strategy TEXT DEFAULT 'fomo'")
    return db

def kv_get(db, k, default=None):
    r = db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default

def kv_set(db, k, v): db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))

def make_trade_logger(db, echo=False):
    def f(strategy, ts, side, px, qty, quote, fee, note, symbol=SYMBOL):
        db.execute("INSERT INTO trades(ts,strategy,side,price,qty,quote,fee,note,symbol) VALUES(?,?,?,?,?,?,?,?,?)",
                   (ts, strategy, side, px, qty, quote, fee, note, symbol))
        if echo: log.info("TRADE %-9s %-4s %.6f %s @ %.6g (USDT %.2f, taxa %.4f) %s", strategy, side, qty, symbol, px, quote, fee, note)
    return f

def snapshot(db, strats, ts, price):
    for s in strats:
        db.execute("INSERT INTO equity VALUES(?,?,?,?,?,?)", (ts, s.name, s.pf.equity(price), price, s.pf.usdt, s.pf.btc))
