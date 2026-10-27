"""Envio de alertas para Telegram/Discord – só funciona se as chaves estiverem no .env. Sem chave = só painel."""
import hashlib
from . import config, logs
from .state import STORE, now_ms
from .providers.base import client
log = logs.get("alerts")
SENT = {}

def enabled():
    return {"telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID), "discord": bool(config.DISCORD_WEBHOOK_URL)}

async def push(level, sym, text, dedup_min=30):
    key = hashlib.sha1(f"{level}{sym}{text[:60]}".encode()).hexdigest()[:16]
    now = now_ms()
    if key in SENT and now - SENT[key] < dedup_min * 60_000: return
    SENT[key] = now
    a = {"id": f"{key}-{now}", "ts": now, "level": level, "sym": sym, "text": text, "sent": 0}
    msg = f"[{level}] {sym}: {text}\n(Crypto Antecipation Desk – SIMULAÇÃO, não é recomendação)"
    en = enabled()
    try:
        if en["telegram"]:
            await client().post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}); a["sent"] = 1
        if en["discord"]:
            await client().post(config.DISCORD_WEBHOOK_URL, json={"content": msg[:1900]}); a["sent"] = 1
    except Exception as e:
        logs.ev(log, "alerta_falhou", erro=str(e)[:120])
    STORE.alerts.append(a); STORE.persist("alerts", a)
