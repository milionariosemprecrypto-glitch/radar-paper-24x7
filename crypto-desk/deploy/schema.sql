-- TimescaleDB (PC dedicado). Mesmo modelo do SQLite local.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE TABLE IF NOT EXISTS candles (sym TEXT, tf TEXT, ts TIMESTAMPTZ, o DOUBLE PRECISION, h DOUBLE PRECISION, l DOUBLE PRECISION, c DOUBLE PRECISION, vol_usd DOUBLE PRECISION, PRIMARY KEY(sym,tf,ts));
SELECT create_hypertable('candles','ts', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS derivs (sym TEXT, exch TEXT, ts TIMESTAMPTZ, oi_usd DOUBLE PRECISION, funding DOUBLE PRECISION, ls_ratio DOUBLE PRECISION, basis DOUBLE PRECISION, PRIMARY KEY(sym,exch,ts));
SELECT create_hypertable('derivs','ts', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS liquidations (id TEXT, sym TEXT, exch TEXT, ts TIMESTAMPTZ, side TEXT, px DOUBLE PRECISION, usd DOUBLE PRECISION, PRIMARY KEY(id, ts));
SELECT create_hypertable('liquidations','ts', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS whale_events (id TEXT PRIMARY KEY, ts TIMESTAMPTZ, symbol TEXT, usd DOUBLE PRECISION, from_owner TEXT, to_owner TEXT, kind TEXT, classification TEXT, text TEXT, url TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, ts TIMESTAMPTZ, source TEXT, author TEXT, title TEXT, url TEXT, sentiment TEXT, impact TEXT, keywords JSONB);
CREATE TABLE IF NOT EXISTS scores (sym TEXT, ts TIMESTAMPTZ, score DOUBLE PRECISION, status TEXT, factors JSONB, PRIMARY KEY(sym,ts));
SELECT create_hypertable('scores','ts', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, sym TEXT, ts TIMESTAMPTZ, kind TEXT, direction TEXT, score DOUBLE PRECISION, entry TEXT, stop DOUBLE PRECISION, t1 DOUBLE PRECISION, t2 DOUBLE PRECISION, risk_pct DOUBLE PRECISION, confluences JSONB, reason TEXT);
CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, ts TIMESTAMPTZ, level TEXT, sym TEXT, text TEXT, sent INT);
CREATE TABLE IF NOT EXISTS paper_trades (id TEXT PRIMARY KEY, sym TEXT, side TEXT, opened_ts TIMESTAMPTZ, entry DOUBLE PRECISION, stop DOUBLE PRECISION, t1 DOUBLE PRECISION, t2 DOUBLE PRECISION, risk_pct DOUBLE PRECISION, closed_ts TIMESTAMPTZ, exit DOUBLE PRECISION, result_r DOUBLE PRECISION, status TEXT);
