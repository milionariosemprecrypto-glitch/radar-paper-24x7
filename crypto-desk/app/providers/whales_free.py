"""Baleias GRÁTIS: lê o canal público do Telegram do Whale Alert (https://t.me/s/whale_alert_io).
É um 'scrape' de página pública: pode atrasar, perder posts e mudar formato. Sem chave."""
import re, html, asyncio
from datetime import datetime
from ..state import STORE
from ..engine.classify import classify
from .base import client
URL = "https://t.me/s/whale_alert_io"
POST_RE = re.compile(r'data-post="(whale_alert_io/\d+)".*?<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>.*?datetime="([^"]+)"', re.S)
TX_RE = re.compile(r"([\d,\.]+)\s+#?\$?([A-Za-z0-9]+)\s+\(([\d,\.]+)\s+USD\)\s+(transferred|minted|burned|locked|unlocked)\s*(?:from\s+(.+?))?\s*(?:to\s+(.+?))?\s*(?:at\s+(.+?))?$", re.I)
SEEN = set()

def parse(page):
    out = []
    for post, body, dt in POST_RE.findall(page):
        text = html.unescape(re.sub(r"<br\s*/?>", " ", body)); text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        line = re.sub(r"^[^\w\d]+", "", text.split(" Details")[0]).strip()
        m = TX_RE.search(line)
        if not m:
            continue
        amt, sym, usd, verb, fr, to, at = m.groups()
        kind = {"minted": "mint", "burned": "burn"}.get(verb.lower(), "transfer")
        fr = (fr or at or "").strip(); to = (to or at or "").strip()
        usd_v = float(usd.replace(",", ""))
        cls, txt, eff = classify(sym, usd_v, fr, to, kind)
        ts = int(datetime.fromisoformat(dt).timestamp() * 1000)
        out.append({"id": post, "ts": ts, "symbol": sym.upper(), "usd": usd_v, "from_owner": fr, "to_owner": to, "kind": kind,
                    "classification": cls, "impact": txt, "effect": eff, "text": line[:300], "url": "https://t.me/" + post,
                    "source": "Whale Alert (Telegram público, grátis)"})
    return out

async def poll():
    r = await client().get(URL, timeout=15); r.raise_for_status()
    for ev in sorted(parse(r.text), key=lambda e: e["ts"]):
        if ev["id"] in SEEN: continue
        SEEN.add(ev["id"]); STORE.whales.append(ev)
        STORE.persist("whale_events", {k: ev[k] for k in ("id","ts","symbol","usd","from_owner","to_owner","kind","classification","text","url","source")})
