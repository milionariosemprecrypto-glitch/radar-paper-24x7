CREATE TABLE IF NOT EXISTS candles (sym TEXT, tf TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, vol_usd REAL, PRIMARY KEY(sym,tf,ts));
CREATE TABLE IF NOT EXISTS derivs (sym TEXT, exch TEXT, ts INTEGER, oi_usd REAL, funding REAL, ls_ratio REAL, basis REAL, PRIMARY KEY(sym,exch,ts));
CREATE TABLE IF NOT EXISTS liquidations (id TEXT PRIMARY KEY, sym TEXT, exch TEXT, ts INTEGER, side TEXT, px REAL, usd REAL);
CREATE TABLE IF NOT EXISTS whale_events (id TEXT PRIMARY KEY, ts INTEGER, symbol TEXT, usd REAL, from_owner TEXT, to_owner TEXT, kind TEXT, classification TEXT, text TEXT, url TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, ts INTEGER, source TEXT, author TEXT, title TEXT, url TEXT, sentiment TEXT, impact TEXT, keywords TEXT);
CREATE TABLE IF NOT EXISTS scores (sym TEXT, ts INTEGER, score REAL, status TEXT, factors TEXT, PRIMARY KEY(sym,ts));
CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, sym TEXT, ts INTEGER, kind TEXT, direction TEXT, score REAL, entry TEXT, stop REAL, t1 REAL, t2 REAL, risk_pct REAL, confluences TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, ts INTEGER, level TEXT, sym TEXT, text TEXT, sent INTEGER);
CREATE TABLE IF NOT EXISTS paper_trades (id TEXT PRIMARY KEY, sym TEXT, side TEXT, opened_ts INTEGER, entry REAL, stop REAL, t1 REAL, t2 REAL, risk_pct REAL, closed_ts INTEGER, exit REAL, result_r REAL, status TEXT);
