"""Gestão de risco e 'caderno' de operações SIMULADAS (paper). Nunca envia ordem real."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from .. import config

SP_TZ = ZoneInfo("America/Sao_Paulo")
STATE_KEY = "risk_guard_v1"

def trading_day(now_ms):
    """Dia de negociação = data civil em America/Sao_Paulo (independe do TZ do processo)."""
    return datetime.fromtimestamp(now_ms / 1000, SP_TZ).date().isoformat()

class RiskGuard:
    """Fase 7: estado persistido no SQLite (tabela risk_state) e recarregado no __init__.
    Idempotente por id de operação: abrir/fechar a mesma operação duas vezes não conta duas vezes.
    Se a persistência falhar ou o estado carregado for inválido => consistente=False => check() bloqueia (NÃO OPERAR)."""
    def __init__(self, equity=None, store=None, now=None):
        self.equity = equity or config.PAPER_EQUITY; self.store = store
        self.day = None; self.day_pnl_pct = 0.0; self.trades_today = 0; self.consec_losses = 0; self.last_signal_ts = {}
        self.opened_ids = []; self.closed_ids = []; self.updated_ts = None; self.consistent = True; self.problems = []
        self.loaded_from = "novo"
        if store is not None: self._load(now)
        self._roll(now or int(time.time() * 1000))

    def _load(self, now=None):
        try:
            v, ts = self.store.kv_get(STATE_KEY)
        except Exception as e:
            self.consistent = False; self.problems.append(f"falha ao ler estado: {e!r}"[:200]); return
        if v is None: self._rebuild_from_trades(now); return
        try:
            self.day = v["day"]; self.day_pnl_pct = float(v["day_pnl_pct"]); self.trades_today = int(v["trades_today"])
            self.consec_losses = int(v["consec_losses"]); self.last_signal_ts = {k: int(x) for k, x in v.get("last_signal_ts", {}).items()}
            self.opened_ids = list(v.get("opened_ids", [])); self.closed_ids = list(v.get("closed_ids", []))
            self.updated_ts = int(v.get("updated_ts") or ts); self.loaded_from = "sqlite"
        except Exception as e:
            self.consistent = False; self.problems.append(f"estado persistido inválido: {e!r}"[:200])

    def _rebuild_from_trades(self, now=None):
        """Sem estado salvo (1º boot pós-Fase 7): reconstrói o dia (America/Sao_Paulo) a partir de paper_trades."""
        if not hasattr(self.store, "paper_rows"): return
        now = now or int(time.time() * 1000); d = trading_day(now)
        try: rows = self.store.paper_rows()
        except Exception as e:
            self.consistent = False; self.problems.append(f"falha ao ler paper_trades: {e!r}"[:200]); return
        opened = [r for r in rows if trading_day(r["opened_ts"]) == d]
        closed = sorted([r for r in rows if r["status"] == "fechada" and r.get("closed_ts") and trading_day(r["closed_ts"]) == d], key=lambda r: r["closed_ts"])
        self.day = d; self.trades_today = len(opened); self.opened_ids = [r["id"] for r in opened]
        for r in opened: self.last_signal_ts[r["sym"]] = max(self.last_signal_ts.get(r["sym"], 0), r["opened_ts"])
        use_net = config.PAPER_COSTS
        for r in closed:
            res = r.get("result_r_net") if (use_net and r.get("result_r_net") is not None) else r["result_r"]
            self.day_pnl_pct += res * r["risk_pct"]; self.consec_losses = self.consec_losses + 1 if res < 0 else 0
            self.closed_ids.append(r["id"])
        self.loaded_from = "reconstruido_paper_trades"
        if any(r["status"] == "aberta" and r.get("result_r") is None for r in opened) and not closed and opened:
            self.problems.append("aviso: aberturas de hoje sem fechamento no SQLite (histórico pré-Fase 7)")
        self._save(now)

    def _save(self, now=None):
        self.updated_ts = now or int(time.time() * 1000)
        if self.store is None: return
        ok = self.store.kv_set(STATE_KEY, {"day": self.day, "day_pnl_pct": self.day_pnl_pct, "trades_today": self.trades_today,
                                           "consec_losses": self.consec_losses, "last_signal_ts": self.last_signal_ts,
                                           "opened_ids": self.opened_ids[-500:], "closed_ids": self.closed_ids[-2000:], "updated_ts": self.updated_ts})
        if not ok:
            self.consistent = False; self.problems.append("falha ao persistir estado de risco")

    def _roll(self, now):
        d = trading_day(now)
        if d != self.day:
            # consec_losses zera na virada do dia (comportamento original preservado)
            self.day, self.day_pnl_pct, self.trades_today, self.consec_losses = d, 0.0, 0, 0; self._save(now)

    def check(self, sym, now=None):
        now = now or int(time.time() * 1000); self._roll(now)
        if config.TRADING_MODE != "PAPER": return False, "modo diferente de PAPER bloqueado por segurança"
        if not self.consistent: return False, "estado de risco inconsistente/não persistido – NÃO OPERAR: " + "; ".join(self.problems[-3:])
        if self.day_pnl_pct <= -config.DAILY_LOSS_LIMIT_PCT: return False, f"perda diária de {config.DAILY_LOSS_LIMIT_PCT}% atingida – pare por hoje"
        if self.trades_today >= config.MAX_TRADES_PER_DAY: return False, f"limite de {config.MAX_TRADES_PER_DAY} operações/dia atingido"
        if self.consec_losses >= config.MAX_CONSEC_LOSSES: return False, f"{self.consec_losses} perdas seguidas – pausa obrigatória"
        last = self.last_signal_ts.get(sym)
        if last and now - last < config.COOLDOWN_MIN * 60_000: return False, f"cooldown de {config.COOLDOWN_MIN} min em {sym}"
        return True, "ok"

    def register_open(self, sym, now=None, trade_id=None):
        now = now or int(time.time() * 1000); self._roll(now)
        if trade_id is not None:
            if trade_id in self.opened_ids: return False
            self.opened_ids.append(trade_id)
        self.trades_today += 1; self.last_signal_ts[sym] = now; self._save(now); return True

    def register_close(self, result_r, risk_pct, trade_id=None, now=None):
        now = now or int(time.time() * 1000)
        if trade_id is not None:
            if trade_id in self.closed_ids: return False   # fechamento repetido: não duplica PnL
            self.closed_ids.append(trade_id)
        self._roll(now)
        self.day_pnl_pct += result_r * risk_pct
        self.consec_losses = self.consec_losses + 1 if result_r < 0 else 0
        self._save(now); return True

    def state(self, now=None):
        now = now or int(time.time() * 1000); self._roll(now)   # virada do dia SP mesmo sem sinal
        return {"modo": config.TRADING_MODE, "pnl_dia_pct": round(self.day_pnl_pct, 3), "operacoes_hoje": self.trades_today,
                "perdas_seguidas": self.consec_losses, "dia_negociacao": self.day, "fuso": "America/Sao_Paulo",
                "estado": {"atualizado_ts": self.updated_ts, "idade_s": round((now - self.updated_ts) / 1000, 1) if self.updated_ts else None,
                           "lido_em_ts": now, "persistido": self.store is not None, "origem": self.loaded_from,
                           "consistente": self.consistent, "problemas": self.problems[-5:]},
                "limites": {"perda_diaria_pct": config.DAILY_LOSS_LIMIT_PCT, "max_operacoes": config.MAX_TRADES_PER_DAY,
                "cooldown_min": config.COOLDOWN_MIN, "max_perdas_seguidas": config.MAX_CONSEC_LOSSES, "alavancagem_max": config.MAX_LEVERAGE},
                "limites_atingidos": {"perda_diaria": self.day_pnl_pct <= -config.DAILY_LOSS_LIMIT_PCT, "operacoes": self.trades_today >= config.MAX_TRADES_PER_DAY,
                                      "perdas_seguidas": self.consec_losses >= config.MAX_CONSEC_LOSSES}}

def net_result(t, legs, fee_pct, slip_pct, funding_rate=None, now=None):
    """Resultado LÍQUIDO em R. legs = [(fração, preço_bruto_de_saída)]. Entrada/saídas pioradas pelo slippage,
    taxa sobre o notional de cada lado; funding (perp) pro-rata por 8h se funding_rate (fração/8h) for dado:
    long paga quando rate>0, short recebe (e vice-versa). Spread não modelado (sem bid/ask no desk)."""
    long = t["direction"] == "ALTA"; sg = 1 if long else -1; sl, fee = slip_pct / 100, fee_pct / 100
    e_fill = t["entry_px"] * (1 + sg * sl); pnl = 0.0; fees = fee * e_fill
    for frac, px in legs:
        x = px * (1 - sg * sl); pnl += frac * sg * (x - e_fill); fees += frac * fee * x
    fund = 0.0
    if funding_rate is not None and now is not None:
        fund = sg * funding_rate * t["entry_px"] * max(0, now - t["opened_ts"]) / (8 * 3600_000)
    return (pnl - fees - fund) / t["r_unit"], {"fees_r": fees / t["r_unit"], "funding_r": fund / t["r_unit"], "entry_fill": e_fill}

class PaperLedger:
    """Abre uma operação simulada a cada sinal de ENTRADA e fecha no stop/alvo usando o preço ao vivo.
    Fase 6: result_r = BRUTO (fill perfeito, igual ao histórico); result_r_net = com taxa+slippage, stop executado
    no preço observado (gap) e funding opcional. Com config.PAPER_COSTS=1 o RiskGuard recebe o LÍQUIDO."""
    def __init__(self, guard, store=None, costs=None, fee_pct=None, slip_pct=None, funding=None, funding_rate_fn=None, now=None):
        self.guard = guard; self.store = store; self.open = {}; self.closed = []
        self.costs = config.PAPER_COSTS if costs is None else costs
        self.fee_pct = config.PAPER_FEE_PCT_PER_SIDE if fee_pct is None else fee_pct
        self.slip_pct = config.PAPER_SLIPPAGE_PCT_PER_SIDE if slip_pct is None else slip_pct
        self.funding = config.PAPER_FUNDING if funding is None else funding
        self.funding_rate_fn = funding_rate_fn   # sym -> fração/8h ou None
        self.orphans = []                        # abertas antigas no SQLite que não podem ser fechadas com segurança
        if store is not None and hasattr(store, "paper_rows"): self._restore(now)

    STALE_OPEN_MS = 4 * 3600_000

    def _restore(self, now=None):
        """Recarrega o caderno do SQLite após restart. Fechadas => self.closed (sem re-somar no guard: o guard tem estado próprio
        idempotente). Abertas recentes (< 4h, janela de time-stop) voltam a ser acompanhadas; abertas mais velhas viram
        'órfãs' (reportadas, NUNCA alteradas nem fechadas automaticamente com preço atual)."""
        now = now or int(time.time() * 1000)
        for r in self.store.paper_rows():
            if r["status"] == "fechada" and r.get("result_r") is not None:
                t = {"id": r["id"], "sym": r["sym"], "direction": r["side"], "entry_px": r["entry"], "stop": r["stop"], "t1": r["t1"], "t2": r["t2"],
                     "risk_pct": r["risk_pct"], "opened_ts": r["opened_ts"], "closed_ts": r["closed_ts"], "exit": r["exit"], "status": "fechada",
                     "result_r": r["result_r"], "result_r_gross": r.get("result_r_gross", r["result_r"]), "result_r_net": r.get("result_r_net"),
                     "fees_r": r.get("fees_r"), "funding_r": r.get("funding_r"), "restaurada": True}
                if r.get("costs_model"):
                    try: t["costs_model"] = json.loads(r["costs_model"])
                    except Exception: pass
                self.closed.append(t)
            elif r["status"] == "aberta":
                if now - r["opened_ts"] < self.STALE_OPEN_MS and r["sym"] not in self.open:
                    ru = r.get("r_unit") or abs(r["entry"] - (r.get("stop_initial") or r["stop"])) or 1e-9
                    self.open[r["sym"]] = {"id": r["id"], "sym": r["sym"], "direction": r["side"], "entry_px": r["entry"], "stop": r["stop"],
                                           "t1": r["t1"], "t2": r["t2"], "risk_pct": r["risk_pct"], "opened_ts": r["opened_ts"], "status": "aberta",
                                           "hit_t1": bool(r.get("hit_t1")), "r_unit": ru, "stop_initial": r.get("stop_initial"), "restaurada": True}
                else:
                    self.orphans.append({"id": r["id"], "sym": r["sym"], "opened_ts": r["opened_ts"]})

    def open_trade(self, sig):
        if sig["sym"] in self.open: return
        if any(c["id"] == sig["id"] for c in self.closed[-200:]): return   # mesmo sinal já fechado: não reabre
        t = {**{k: sig[k] for k in ("id", "sym", "direction", "entry_px", "stop", "t1", "t2", "risk_pct")}, "opened_ts": sig["ts"], "status": "aberta", "hit_t1": False, "stop_initial": sig["stop"], "r_unit": abs(sig["entry_px"] - sig["stop"]) or 1e-9}
        self.open[sig["sym"]] = t; self.guard.register_open(sig["sym"], sig["ts"], trade_id=t["id"]); self._save(t)

    def update(self, sym, price, now):
        t = self.open.get(sym)
        if not t or not price: return
        long = t["direction"] == "ALTA"; r_unit = t["r_unit"]
        hit_stop = price <= t["stop"] if long else price >= t["stop"]
        hit_t1 = price >= t["t1"] if long else price <= t["t1"]
        hit_t2 = price >= t["t2"] if long else price <= t["t2"]
        if hit_t1 and not t["hit_t1"]:
            t["hit_t1"] = True; t["stop"] = t["entry_px"]; self._save(t)   # move stop p/ entrada (sem risco); persiste p/ restart
        res = None; legs = None
        if hit_t2: legs = [(0.5, t["t1"]), (0.5, t["t2"])]
        elif hit_stop: legs = [(0.5, t["t1"]), (0.5, price)] if t["hit_t1"] else [(1.0, price)]   # stop no preço OBSERVADO (gap)
        elif now - t["opened_ts"] > 4 * 3600_000: legs = [(1.0, price)]
        if hit_t2: res = ((t["t2"] - t["entry_px"]) if long else (t["entry_px"] - t["t2"])) / r_unit * 0.5 + ((t["t1"] - t["entry_px"]) if long else (t["entry_px"] - t["t1"])) / r_unit * 0.5
        elif hit_stop: res = (((t["t1"] - t["entry_px"]) if long else (t["entry_px"] - t["t1"])) / r_unit * 0.5) if t["hit_t1"] else -1.0
        elif now - t["opened_ts"] > 4 * 3600_000: res = ((price - t["entry_px"]) if long else (t["entry_px"] - price)) / r_unit
        if res is not None:
            fr = self.funding_rate_fn(sym) if (self.funding and self.funding_rate_fn) else None
            net, info = net_result(t, legs, self.fee_pct, self.slip_pct, fr, now)
            t.update(status="fechada", closed_ts=now, exit=price, result_r=round(res, 2), result_r_gross=round(res, 2), result_r_net=round(net, 2),
                     fees_r=round(info["fees_r"], 3), funding_r=round(info["funding_r"], 3) if fr is not None else None,
                     costs_model={"on": self.costs, "fee_pct": self.fee_pct, "slip_pct": self.slip_pct, "funding": fr is not None, "spread": "não modelado"})
            self.closed.append(t); del self.open[sym]
            self.guard.register_close(t["result_r_net"] if self.costs else t["result_r_gross"], t["risk_pct"], trade_id=t["id"], now=now); self._save(t)

    def _save(self, t):
        if self.store is None: return
        row = dict(id=t["id"], sym=t["sym"], side=t["direction"], opened_ts=t["opened_ts"], entry=t["entry_px"], stop=t["stop"],
                   t1=t["t1"], t2=t["t2"], risk_pct=t["risk_pct"], closed_ts=t.get("closed_ts"), exit=t.get("exit"), result_r=t.get("result_r"), status=t["status"],
                   result_r_gross=t.get("result_r_gross"), result_r_net=t.get("result_r_net"), fees_r=t.get("fees_r"), funding_r=t.get("funding_r"),
                   costs_model=t.get("costs_model"), hit_t1=int(bool(t.get("hit_t1"))), r_unit=t.get("r_unit"))
        if t.get("stop_initial") is not None: row["stop_initial"] = t["stop_initial"]
        if hasattr(self.store, "upsert_paper_trade"): self.store.upsert_paper_trade(row)
        else: self.store.persist("paper_trades", row)

    def stats(self):
        c = self.closed; wins = [t for t in c if t["result_r"] > 0]
        return {"abertas": list(self.open.values()), "fechadas": c[-30:], "total": len(c), "acertos": len(wins),
                "taxa_acerto": round(len(wins) / len(c) * 100, 1) if c else None, "soma_R": round(sum(t["result_r"] for t in c), 2),
                "soma_R_bruto": round(sum(t["result_r"] for t in c), 2),
                "soma_R_liquido": round(sum(t["result_r_net"] for t in c if t.get("result_r_net") is not None), 2) if any(t.get("result_r_net") is not None for t in c) else None,
                "orfas_sqlite": self.orphans, "custos": {"ativo": self.costs, "taxa_pct_lado": self.fee_pct, "slippage_pct_lado": self.slip_pct, "funding": self.funding, "spread": "não modelado (sem bid/ask)"}}
