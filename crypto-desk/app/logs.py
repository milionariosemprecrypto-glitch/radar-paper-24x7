"""Logs estruturados em JSON (uma linha por evento)."""
import json, logging, sys, time

class JsonFmt(logging.Formatter):
    def format(self, r):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "lvl": r.levelname, "mod": r.name, "msg": r.getMessage()}
        if hasattr(r, "extra_data"):
            d.update(r.extra_data)
        return json.dumps(d, ensure_ascii=False)

def get(name):
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = logging.StreamHandler(sys.stdout); h.setFormatter(JsonFmt())
        lg.addHandler(h); lg.setLevel(logging.INFO); lg.propagate = False
    return lg

def ev(lg, msg, **kw):
    lg.info(msg, extra={"extra_data": kw})
