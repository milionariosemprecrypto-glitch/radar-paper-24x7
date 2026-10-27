#!/usr/bin/env python3
"""Health check do desk: GET /health deve ser 200 com ok=true e >=1 ativo ao vivo. Uso: desk_health.py URL [timeout]
Exit 0 = saudável; 1 = falha (motivo em stdout)."""
import json, sys, urllib.request
def check(url, timeout=5):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as r:
            if r.status != 200: return False, f"HTTP {r.status}"
            d = json.loads(r.read())
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if d.get("ok") is not True: return False, "ok != true"
    if not d.get("assets_live"): return False, "nenhum ativo ao vivo"
    return True, f"ok ({len(d['assets_live'])} ativos)"
if __name__ == "__main__":
    ok, why = check(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000", float(sys.argv[2]) if len(sys.argv) > 2 else 5)
    print(("OK " if ok else "FAIL ") + why); sys.exit(0 if ok else 1)
