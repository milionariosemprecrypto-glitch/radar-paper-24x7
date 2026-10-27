"""Estado em memória (substitui Redis quando não há Docker) + persistência SQLite
(substitui Postgres/Timescale localmente). Mesma interface nos dois casos."""
import sqlite3, json, time, threading
from collections import deque, defaultdict
from pathlib import Path
from . import config

def now_ms():
    return int(time.time() * 1000)

class AssetState:
    def __init__(self, sym):
        self.sym = sym
        self.price = None
        self.candles = {"1m": [], "5m": [], "15m": [], "1H": []}  # [ts,o,h,l,c,vol_usd]
        self.trades = deque(maxlen=50000)    # (ts, px, usd, side 'buy'/'sell')
        self.book = {"bids": [], "asks": [], "ts": 0}
        self.depth = {}                       # bandas de profundidade
        self.oi = {}                          # exchange -> {"usd":..,"ts":..}
        self.oi_hist = []                     # [(ts, oi_usd_okx)] 5m (OKX rubik)
        self.funding = {}                     # exchange -> rate (fração por 8h)
        self.funding_hist = []                # [(ts, rate)] okx
        self.ls_ratio = None                  # contas long/short (OKX rubik)
        self.ls_hist = []
        self.taker = []                       # [(ts, buy_usd, sell_usd)] 5m
        self.basis = None                     # (mark - index)/index
        self.liqs = deque(maxlen=5000)        # (ts, side_liquidated 'long'/'short', px, usd, exch)
        self.updated = {}

class Store:
    def __init__(self):
        self.assets = {s: AssetState(s) for s in config.ASSETS}
        self.whales = deque(maxlen=500)
        self.news = deque(maxlen=400)
        self.alerts = deque(maxlen=300)
        self.signals = {}
        self.scores = {}
        self.sources = {}   # nome -> {status, detail, ts, kind}
        self.lock = threading.Lock()
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        self.db.executescript(Path(__file__).with_name("schema_sqlite.sql").read_text())
        self.persist_errors = 0; self.last_persist_error = None
        self._migrate()

    # Fase 7: colunas aditivas (nunca DROP/DELETE; histórico preservado)
    PAPER_EXTRA_COLS = {"result_r_gross": "REAL", "result_r_net": "REAL", "fees_r": "REAL", "funding_r": "REAL",
                        "costs_model": "TEXT", "hit_t1": "INTEGER", "r_unit": "REAL", "stop_initial": "REAL", "updated_ts": "INTEGER"}

    def _migrate(self):
        with self.lock:
            have = {r[1] for r in self.db.execute("PRAGMA table_info(paper_trades)")}
            for c, typ in self.PAPER_EXTRA_COLS.items():
                if c not in have: self.db.execute(f"ALTER TABLE paper_trades ADD COLUMN {c} {typ}")
            self.db.execute("CREATE TABLE IF NOT EXISTS risk_state (k TEXT PRIMARY KEY, v TEXT, updated_ts INTEGER)")
            self.db.commit()

    def upsert_paper_trade(self, row: dict):
        """Upsert transacional por id. Regra: registro 'fechada' é final — um 'aberta' posterior nunca o sobrescreve,
        e um fechamento repetido apenas regrava os mesmos valores (não soma nada). Retorna True se gravou."""
        row = {**row, "updated_ts": now_ms()}
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
        cols = ",".join(row); q = ",".join("?" * len(row))
        upd = ",".join(f"{c}=excluded.{c}" for c in row if c != "id")
        try:
            with self.lock, self.db:
                self.db.execute(f"INSERT INTO paper_trades ({cols}) VALUES ({q}) ON CONFLICT(id) DO UPDATE SET {upd} "
                                f"WHERE NOT (paper_trades.status='fechada' AND excluded.status!='fechada')", vals)
            return True
        except Exception as e:
            self.persist_errors += 1; self.last_persist_error = repr(e)[:200]; return False

    def kv_set(self, k, v):
        try:
            with self.lock, self.db:
                self.db.execute("INSERT INTO risk_state (k,v,updated_ts) VALUES (?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_ts=excluded.updated_ts",
                                (k, json.dumps(v), now_ms()))
            return True
        except Exception as e:
            self.persist_errors += 1; self.last_persist_error = repr(e)[:200]; return False

    def kv_get(self, k):
        with self.lock:
            r = self.db.execute("SELECT v, updated_ts FROM risk_state WHERE k=?", (k,)).fetchone()
        return (json.loads(r[0]), r[1]) if r else (None, None)

    def paper_rows(self):
        with self.lock:
            cur = self.db.execute("SELECT * FROM paper_trades ORDER BY opened_ts")
            names = [d[0] for d in cur.description]; return [dict(zip(names, r)) for r in cur.fetchall()]

    def source(self, name, status, detail="", kind="real"):
        self.sources[name] = {"status": status, "detail": detail, "ts": now_ms(), "kind": kind}

    def persist(self, table, row: dict):
        try:
            with self.lock:
                cols = ",".join(row); q = ",".join("?" * len(row))
                self.db.execute(f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({q})",
                                [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])
                self.db.commit()
        except Exception as e:
            self.persist_errors += 1; self.last_persist_error = repr(e)[:200]

STORE = Store()
