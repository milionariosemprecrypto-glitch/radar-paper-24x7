"""Configuração via variáveis de ambiente (.env). NENHUMA chave fica no código."""
import os
from pathlib import Path

def _load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].split("\t#", 1)[0]   # remove comentário no fim da linha
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env(str(Path(__file__).resolve().parent.parent / ".env"))

def env(k, d=""):
    return os.environ.get(k, d)

ASSETS = [a.strip().upper() for a in env("ASSETS", "BTC,ETH,SOL,XRP,DOGE").split(",") if a.strip()]
PORT = int(env("PORT", "8000"))
DB_PATH = env("DB_PATH", "data/desk.sqlite")
DATABASE_URL = env("DATABASE_URL")  # postgres/timescale (opcional, no PC dedicado)
REDIS_URL = env("REDIS_URL")        # opcional

# Provedores de exchange: okx sempre; binance/bybit tentam e se desligam sozinhos se bloqueados (HTTP 451/403)
EXCHANGES = [e.strip() for e in env("EXCHANGES", "okx,bitget,gate,binance,bybit").split(",") if e.strip()]

# Chaves PAGAS (opcionais). Se vazias, o provedor fica "desativado – requer chave".
COINGLASS_API_KEY = env("COINGLASS_API_KEY")
WHALE_ALERT_API_KEY = env("WHALE_ALERT_API_KEY")
X_BEARER_TOKEN = env("X_BEARER_TOKEN")
X_ACCOUNTS = [a.strip() for a in env("X_ACCOUNTS", "realDonaldTrump,elonmusk,whale_alert,WatcherGuru,DeItaone,FirstSquawk").split(",") if a.strip()]

# Alertas (gratuitos)
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
DISCORD_WEBHOOK_URL = env("DISCORD_WEBHOOK_URL")

WHALE_MIN_USD = float(env("WHALE_MIN_USD", "5000000"))

# Risco (PAPER ONLY)
RISK_MIN_PCT = float(env("RISK_MIN_PCT", "0.25"))
RISK_MAX_PCT = float(env("RISK_MAX_PCT", "0.5"))
MAX_LEVERAGE = float(env("MAX_LEVERAGE", "3"))
DAILY_LOSS_LIMIT_PCT = float(env("DAILY_LOSS_LIMIT_PCT", "1.5"))
MAX_TRADES_PER_DAY = int(env("MAX_TRADES_PER_DAY", "4"))
COOLDOWN_MIN = int(env("COOLDOWN_MIN", "30"))
MAX_CONSEC_LOSSES = int(env("MAX_CONSEC_LOSSES", "2"))
PAPER_EQUITY = float(env("PAPER_EQUITY", "1000"))
TRADING_MODE = "PAPER"  # fixo. Não existe código de ordem real neste projeto.

# Fase 6 — custos do caderno paper (PaperLedger). Só afeta operações NOVAS; histórico SQLite não é reescrito.
PAPER_COSTS = env("PAPER_COSTS", "1") == "1"                       # 0 = comportamento antigo (fill perfeito) p/ comparação
PAPER_FEE_PCT_PER_SIDE = float(env("PAPER_FEE_PCT_PER_SIDE", "0.1"))   # % por lado (mesmo default do Radar risk.json)
PAPER_SLIPPAGE_PCT_PER_SIDE = float(env("PAPER_SLIPPAGE_PCT_PER_SIDE", "0.05"))
PAPER_FUNDING = env("PAPER_FUNDING", "0") == "1"                   # perp: funding pro-rata 8h com taxa média observada; off por padrão
