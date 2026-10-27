"""Classificação de movimentos de baleias (regras simples e explicáveis)."""
EXCHANGES = ["binance", "coinbase", "okx", "okex", "bybit", "kraken", "bitfinex", "huobi", "htx", "kucoin", "gate", "bitget",
             "bitstamp", "gemini", "crypto.com", "upbit", "bithumb", "mexc", "deribit", "bitmex", "poloniex", "robinhood", "bitso",
             "mercado bitcoin", "binanceus", "bitvavo", "hyperliquid", "cex.io"]
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "PYUSD", "TUSD", "USDE", "USDS", "RLUSD"}
MAJORS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "TRX", "LTC"}

def is_exchange(owner: str) -> bool:
    o = (owner or "").lower().replace("#", "").strip()
    return any(o == e or o.startswith(e + " ") or o.startswith(e) and len(o) <= len(e) + 3 for e in EXCHANGES)

def classify(symbol, usd, from_owner, to_owner, kind="transfer"):
    """Retorna (classe, impacto_texto, efeito) — efeito: -1 risco vendedor, +1 altista, 0 neutro."""
    s = (symbol or "").upper(); fe, te = is_exchange(from_owner), is_exchange(to_owner)
    big = usd >= 50e6
    if kind == "mint":
        return ("emissão stablecoin" if s in STABLES else "emissão", "Nova liquidez entrando no mercado (geralmente altista no médio prazo).", 1 if s in STABLES else 0)
    if kind == "burn":
        return ("queima stablecoin" if s in STABLES else "queima", "Liquidez saindo do mercado (levemente baixista).", -1 if s in STABLES else 0)
    if fe and te:
        return ("transferência interna/entre exchanges", "Movimento entre exchanges – normalmente neutro.", 0)
    if s in STABLES:
        if te: return ("stablecoin → exchange", "Dinheiro 'em caixa' chegando na exchange: poder de compra (pode virar compra).", 1)
        if fe: return ("stablecoin ← exchange", "Stablecoins saindo da exchange: menos poder de compra imediato.", -1 if big else 0)
        return ("carteira → carteira", "Movimento entre carteiras desconhecidas – neutro.", 0)
    if te:
        return ("entrada em exchange" + (" (GRANDE)" if big else ""), f"{s} indo para exchange: risco de venda (distribuição).", -1)
    if fe:
        return ("saída de exchange" + (" (GRANDE)" if big else ""), f"{s} saindo da exchange para carteira: sinal de acumulação/guarda.", 1)
    return ("carteira → carteira", "Movimento entre carteiras desconhecidas – neutro.", 0)
