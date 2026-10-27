"""Utilitários comuns: HTTP com retry/backoff e marcação de fonte."""
import asyncio, random, httpx
from ..state import STORE
from .. import logs
log = logs.get("provider")

class Blocked(Exception):
    pass

_client = None
def client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "CryptoAntecipationDesk/1.0 (paper)"}, follow_redirects=True)
    return _client

async def get_json(url, params=None, headers=None, retries=3):
    delay = 1.0
    for i in range(retries):
        try:
            r = await client().get(url, params=params, headers=headers)
            if r.status_code in (403, 451):
                raise Blocked(f"HTTP {r.status_code} (bloqueio geográfico/permissão)")
            if r.status_code == 429:
                await asyncio.sleep(delay * 3); delay *= 2; continue
            r.raise_for_status()
            return r.json()
        except Blocked:
            raise
        except Exception as e:
            if i == retries - 1:
                raise
            await asyncio.sleep(delay + random.random()); delay *= 2

async def loop_forever(name, fn, every, kind="real"):
    """Roda fn periodicamente; marca a fonte como ok/erro; desliga se bloqueada."""
    fails = 0
    while True:
        try:
            await fn()
            STORE.source(name, "ok", f"atualiza a cada {every}s", kind); fails = 0
        except Blocked as e:
            STORE.source(name, "bloqueado", str(e) + " – desativado neste computador", kind)
            logs.ev(log, "fonte_bloqueada", fonte=name, erro=str(e)); return
        except Exception as e:
            fails += 1
            STORE.source(name, "erro", f"{type(e).__name__}: {str(e)[:120]} (tentativa {fails})", kind)
            logs.ev(log, "fonte_erro", fonte=name, erro=str(e)[:200], tentativas=fails)
        await asyncio.sleep(every if fails == 0 else min(every * (2 ** fails), 300))
