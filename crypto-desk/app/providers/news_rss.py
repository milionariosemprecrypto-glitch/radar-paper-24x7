"""Notícias GRÁTIS via RSS (Cointelegraph + buscas do Google News como 'proxy' de Trump/Musk/macro).
Sentimento e impacto por palavras‑chave (regras simples e transparentes, não é IA)."""
import re, html, hashlib, asyncio
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from ..state import STORE, now_ms
from .base import client

FEEDS = [("Cointelegraph", "https://cointelegraph.com/rss")] + [
    ("Google News: " + q, "https://news.google.com/rss/search?q=" + quote(q) + "&hl=en-US&gl=US&ceid=US:en") for q in [
        "bitcoin when:1h", "crypto Trump when:1d", "Elon Musk crypto OR dogecoin when:1d",
        "Federal Reserve rate cut OR inflation OR CPI when:1d", "crypto regulation OR SEC OR ETF when:1d",
        "crypto hack OR exploit when:1d", "tariffs OR war markets when:1d"]]

# palavra-chave -> (peso de impacto, viés: +1 altista, -1 baixista, 0 depende)
KEYWORDS = {
    "tariff": (3, -1), "tarifa": (3, -1), "war": (3, -1), "guerra": (3, -1), "missile": (3, -1), "sanction": (2, -1),
    "regulation": (2, 0), "regulamenta": (2, 0), "sec ": (2, 0), "lawsuit": (2, -1), "ban": (3, -1), "proíbe": (3, -1),
    "etf": (3, 1), "approval": (2, 1), "approved": (2, 1), "rate cut": (3, 1), "corte de juros": (3, 1), "rate hike": (3, -1),
    "inflation": (2, 0), "inflação": (2, 0), "cpi": (2, 0), "fomc": (3, 0), "powell": (2, 0), "hack": (3, -1), "exploit": (3, -1),
    "stolen": (3, -1), "adoption": (2, 1), "adoção": (2, 1), "stablecoin": (1, 0), "bitcoin reserve": (3, 1), "strategic reserve": (3, 1),
    "trump": (2, 0), "musk": (2, 0), "liquidat": (2, 0), "bankrupt": (3, -1), "falência": (3, -1), "record high": (2, 1), "all-time high": (2, 1),
}
POS = ["surge", "rally", "soar", "jump", "gain", "bull", "approve", "inflow", "record", "rise", "climb", "buy", "adopt", "cut rates", "sobe", "alta"]
NEG = ["crash", "plunge", "drop", "fall", "bear", "outflow", "sell-off", "selloff", "slump", "slide", "fear", "hack", "ban", "lawsuit", "war", "tariff", "dump", "queda", "cai"]
ASSET_WORDS = {"BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "ether", " eth"], "SOL": ["solana", " sol "], "XRP": ["xrp", "ripple"], "DOGE": ["dogecoin", "doge"]}
SEEN = set()

def analyze(title: str):
    t = " " + title.lower() + " "
    has = lambda w: re.search(r"(?<![a-zà-ú])" + re.escape(w.strip()), t) is not None
    kws = [k for k in KEYWORDS if has(k)]
    impact_pts = sum(KEYWORDS[k][0] for k in kws)
    bias = sum(KEYWORDS[k][1] for k in kws) + sum(1 for w in POS if has(w)) - sum(1 for w in NEG if has(w))
    sentiment = "positivo" if bias > 0 else "negativo" if bias < 0 else "neutro"
    impact = "alto" if impact_pts >= 5 else "médio" if impact_pts >= 2 else "baixo"
    assets = [a for a, ws in ASSET_WORDS.items() if any(has(w) for w in ws)]
    return sentiment, impact, kws, assets

def parse_rss(src, xml):
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S) or [None, ""])[1]
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", g("title"))).strip()
        link = re.sub(r"<!\[CDATA\[|\]\]>", "", g("link")).strip()
        try: ts = int(parsedate_to_datetime(g("pubDate").strip()).timestamp() * 1000)
        except Exception: ts = now_ms()
        if not title: continue
        s, imp, kws, assets = analyze(title)
        out.append({"id": hashlib.sha1(title.encode()).hexdigest()[:16], "ts": ts, "source": src, "author": src.split(":")[0],
                    "title": title, "url": link, "sentiment": s, "impact": imp, "keywords": kws, "assets": assets, "kind": "notícia"})
    return out

async def poll():
    for src, url in FEEDS:
        try:
            r = await client().get(url, timeout=15); r.raise_for_status()
        except Exception:
            continue
        for n in parse_rss(src, r.text):
            if n["id"] in SEEN or n["ts"] < now_ms() - 2 * 86400e3: continue
            SEEN.add(n["id"]); STORE.news.append(n)
            STORE.persist("news", {k: n[k] for k in ("id","ts","source","author","title","url","sentiment","impact","keywords")})
        await asyncio.sleep(1)
    items = sorted(STORE.news, key=lambda n: n["ts"])[-400:]
    STORE.news.clear(); STORE.news.extend(items)
