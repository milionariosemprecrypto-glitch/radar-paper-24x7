#!/usr/bin/env python3
"""Classifica o heartbeat p/ o watchdog. Uso: hb_check.py <arquivo> <child_pid> <child_start_epoch> <max_age_s> <grace_s>
Imprime STATUS e sai 0 (OK/STARTING = não reiniciar) ou 1 (MISSING/UNREADABLE/STALE = reiniciar)."""
import json, sys, time
from datetime import datetime
def classify(path, pid, started, max_age, grace, now=None):
    now = now or time.time(); in_grace = now - started < grace
    try:
        raw = open(path).read()
    except FileNotFoundError:
        return ("STARTING", "heartbeat ausente (grace)") if in_grace else ("MISSING", "heartbeat ausente")
    except Exception as e:
        return ("STARTING", f"ilegível (grace): {e}") if in_grace else ("UNREADABLE", f"{type(e).__name__}: {e}")
    try:
        hb = json.loads(raw); ts = datetime.strptime(hb["ts"], "%Y-%m-%d %H:%M:%S %z").timestamp()
    except Exception as e:
        return ("STARTING", "ilegível (grace)") if in_grace else ("UNREADABLE", f"{type(e).__name__}: {e}")
    fresh_from_child = ts >= started - 1 and str(hb.get("pid")) == str(pid)
    if not fresh_from_child:   # heartbeat é do processo anterior
        return ("STARTING", "heartbeat antigo de outro pid (grace)") if in_grace else ("STALE", f"heartbeat não é do pid {pid} (pid={hb.get('pid')}, idade {now-ts:.0f}s)")
    age = now - ts
    return ("OK", f"idade {age:.0f}s") if age <= max_age else ("STALE", f"idade {age:.0f}s > {max_age}s")
if __name__ == "__main__":
    p, pid, st, ma, gr = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
    s, why = classify(p, pid, st, ma, gr); print(f"{s} {why}"); sys.exit(0 if s in ("OK", "STARTING") else 1)
