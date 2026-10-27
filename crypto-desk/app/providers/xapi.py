"""X/Twitter OFICIAL (pago por uso: ~US$0,005 por post lido, US$0,010 por usuário lido) – liga só se X_BEARER_TOKEN existir.
Endpoints v2: GET /2/users/by?usernames=...  e  GET /2/users/:id/tweets. Poll econômico (a cada 5 min)."""
import asyncio
from ..state import STORE, now_ms
from .. import config
from .base import get_json
from .news_rss import analyze
from datetime import datetime
BASE = "https://api.x.com/2"
IDS = {}; SINCE = {}

async def poll():
    h = {"Authorization": f"Bearer {config.X_BEARER_TOKEN}"}
    accts = [a.lstrip("@") for a in config.X_ACCOUNTS]
    missing = [a for a in accts if a not in IDS]
    if missing:
        d = await get_json(f"{BASE}/users/by", {"usernames": ",".join(missing[:100])}, h)
        for u in d.get("data", []): IDS[u["username"]] = u["id"]
    for name, uid in IDS.items():
        p = {"max_results": 5, "tweet.fields": "created_at", "exclude": "retweets,replies"}
        if uid in SINCE: p["since_id"] = SINCE[uid]
        d = await get_json(f"{BASE}/users/{uid}/tweets", p, h)
        for t in d.get("data", []):
            SINCE[uid] = max(SINCE.get(uid, "0"), t["id"], key=int)
            s, imp, kws, assets = analyze(t["text"])
            STORE.news.append({"id": "x-" + t["id"], "ts": int(datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).timestamp() * 1000),
                               "source": "X", "author": "@" + name, "title": t["text"][:280], "url": f"https://x.com/{name}/status/{t['id']}",
                               "sentiment": s, "impact": imp, "keywords": kws, "assets": assets, "kind": "post X"})
        await asyncio.sleep(1)
