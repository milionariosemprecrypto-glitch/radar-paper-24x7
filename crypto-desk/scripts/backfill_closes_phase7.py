"""Fase 7 — backfill de FECHAMENTOS que o INSERT OR IGNORE nunca gravou. PAPER ONLY.
Default = DRY-RUN (só imprime). Fonte: /api/paper do desk em execução (memória). Só faz UPDATE de linhas
'aberta' cujo id aparece como 'fechada' na memória; nunca DELETE, nunca INSERT de linhas novas, nunca altera 'fechada'.
Uso: python scripts/backfill_closes_phase7.py [--url http://127.0.0.1:8000] [--db data/desk.sqlite] [--apply]
Faça backup (sqlite3 .backup) ANTES de --apply."""
import argparse, json, sqlite3, time, urllib.request
ap = argparse.ArgumentParser(); ap.add_argument("--url", default="http://127.0.0.1:8000"); ap.add_argument("--db", default="data/desk.sqlite")
ap.add_argument("--apply", action="store_true"); ap.add_argument("--paper-json", help="usar JSON salvo em vez da URL"); a = ap.parse_args()
paper = json.load(open(a.paper_json)) if a.paper_json else json.load(urllib.request.urlopen(a.url + "/api/paper", timeout=10))
mem = {t["id"]: t for t in paper["caderno"]["fechadas"]}
c = sqlite3.connect(a.db); c.row_factory = sqlite3.Row
cols = {r[1] for r in c.execute("PRAGMA table_info(paper_trades)")}
plan = []
for r in c.execute("SELECT * FROM paper_trades"):
    t = mem.get(r["id"])
    if not t: continue
    if r["status"] == "fechada":
        same = r["result_r"] == t["result_r"] and r["exit"] == t.get("exit"); print(f"OK   {r['id']} já fechada no SQLite (igual={same})"); continue
    if r["sym"] != t["sym"] or r["opened_ts"] != t["opened_ts"] or abs(r["entry"] - t["entry_px"]) > 1e-12:
        print(f"SKIP {r['id']} divergência de identidade sym/opened_ts/entry — revisar à mão"); continue
    upd = {"status": "fechada", "closed_ts": t["closed_ts"], "exit": t["exit"], "result_r": t["result_r"], "stop": t["stop"]}
    for k in ("result_r_gross", "result_r_net", "fees_r", "funding_r"):
        if k in cols: upd[k] = t.get(k, t["result_r"] if k == "result_r_gross" else None)
    if "hit_t1" in cols: upd["hit_t1"] = int(bool(t.get("hit_t1")))
    if "stop_initial" in cols: upd["stop_initial"] = r["stop"]
    if "updated_ts" in cols: upd["updated_ts"] = int(time.time() * 1000)
    plan.append((r["id"], upd)); print(f"PLAN {r['id']} aberta -> fechada exit={t['exit']} result_r={t['result_r']} closed_ts={t['closed_ts']}")
orph = [r["id"] for r in c.execute("SELECT id FROM paper_trades WHERE status='aberta'") if r["id"] not in mem and r["id"] not in {x['id'] for x in paper['caderno']['abertas']}]
print(f"ÓRFÃS (aberta no SQLite, ausentes da memória — NÃO alteradas): {orph}")
if a.apply and plan:
    with c:
        for i, u in plan:
            c.execute(f"UPDATE paper_trades SET {','.join(k+'=?' for k in u)} WHERE id=? AND status='aberta'", [*u.values(), i])
    print(f"APLICADO: {len(plan)} linhas")
else: print(f"DRY-RUN: {len(plan)} linhas seriam atualizadas")
