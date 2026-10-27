"""Coinglass API V4 (PAGA) – liga só se COINGLASS_API_KEY existir. Base https://open-api-v4.coinglass.com, header CG-API-KEY.
Planos: Hobbyist US$29/mês (30 req/min) · Startup US$79 · Standard US$299 · Professional US$699 (único com heatmap/mapa de liquidação).
Usamos só endpoints que existem no Hobbyist; o heatmap oficial é tentado e, se o plano não permitir, fica a ESTIMATIVA própria."""
import asyncio
from ..state import STORE
from .. import config
from .base import get_json
BASE = "https://open-api-v4.coinglass.com"
CG = {}   # sym -> {"oi_exchanges":..., "liq_exchanges":..., "heatmap":...}

async def poll():
    h = {"CG-API-KEY": config.COINGLASS_API_KEY, "accept": "application/json"}
    for sym in config.ASSETS:
        d = CG.setdefault(sym, {})
        r = await get_json(f"{BASE}/api/futures/open-interest/exchange-list", {"symbol": sym}, h); d["oi_exchanges"] = r.get("data"); await asyncio.sleep(2.5)
        r = await get_json(f"{BASE}/api/futures/liquidation/exchange-list", {"symbol": sym, "range": "1h"}, h); d["liq_exchanges"] = r.get("data"); await asyncio.sleep(2.5)
        r = await get_json(f"{BASE}/api/futures/funding-rate/exchange-list", {"symbol": sym}, h); d["funding_exchanges"] = r.get("data"); await asyncio.sleep(2.5)
        if d.get("heatmap_ok", True):
            try:
                r = await get_json(f"{BASE}/api/futures/liquidation/aggregated-heatmap/model2", {"symbol": sym, "range": "3d"}, h)
                if str(r.get("code")) == "0": d["heatmap"] = r.get("data")
                else: d["heatmap_ok"] = False; d["heatmap_msg"] = r.get("msg", "plano sem acesso (precisa Professional US$699)")
            except Exception as e:
                d["heatmap_ok"] = False; d["heatmap_msg"] = str(e)[:100]
            await asyncio.sleep(2.5)
