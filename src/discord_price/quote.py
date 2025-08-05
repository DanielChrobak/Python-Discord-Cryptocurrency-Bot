import logging, requests, time
from typing import List, Dict
from dataclasses import dataclass
from asyncio import Lock

logger = logging.getLogger(__name__)

@dataclass
class PriceQuote:
    """Current price & metadata for a crypto symbol."""
    symbol: str         # e.g. 'BTC'
    name: str           # Full coin name
    slug: str           # CMC slug for linking
    price_usd: float    # Current USD price
    percent_change_1h: float   # Last hour change %
    market_cap: float

@dataclass
class TimestampedQuote:
    """Wrap quote+timestamp for caching."""
    quote: PriceQuote
    when: float

class PriceQuoteCache:
    """
    Caches crypto prices for each API key.
    Cache validity: 60s. Only one live API request/refresh per key at a time.
    Use .fetch() (cached, prefered) or .fetch_no_cache() (always network).
    """
    def __init__(self):
        self.liveness_seconds = 60.0
        self.cache: Dict[str, Dict[str, TimestampedQuote]] = {}
        self.lock = Lock()
        logger.info("💰 Price quote cache initialized (TTL %.1fs)", self.liveness_seconds)

    async def fetch(self, api_key: str, symbols: List[str], now: float) -> List[PriceQuote]:
        """Returns up-to-date prices for all symbols (cached within TTL if possible)."""
        if not api_key or not symbols: return []
        have, need = [], []
        async with self.lock:
            key_cache = self.cache.setdefault(api_key, {})
            for sym in symbols:
                c = key_cache.get(sym)
                if c and ((now - c.when) < self.liveness_seconds): have.append(c.quote)
                else: need.append(sym)
            if need:
                logger.info("🌐 Fetching CoinMarketCap for: %s", ', '.join(need))
                fresh = await fetch_crypto_data(api_key, need)
                now_ = time.time()
                for q in fresh: key_cache[q.symbol] = TimestampedQuote(q, now_)
                return have + fresh
            return have

    async def fetch_no_cache(self, api_key: str, symbols: List[str]) -> List[PriceQuote]:
        """Force-request from CoinMarketCap (bypasses cache), but cache result for later."""
        if not api_key or not symbols: return []
        async with self.lock:
            logger.info("🔍 Forcing fresh CoinMarketCap for: %s", ', '.join(symbols))
            fresh = await fetch_crypto_data(api_key, symbols)
            now_ = time.time()
            key_cache = self.cache.setdefault(api_key, {})
            for q in fresh: key_cache[q.symbol] = TimestampedQuote(q, now_)
            return fresh

async def fetch_crypto_data(api_key: str, symbols: List[str]) -> List[PriceQuote]:
    """
    Low-level poly-async call: queries CoinMarketCap for quotes.
    Returns empty list on API/network error.
    """
    if not api_key or not symbols: return []
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": api_key,
        "Accept": "application/json"
    }
    params = {"symbol": ",".join(symbols)}
    logger.debug("📡 API request: %s", ', '.join(symbols))
    try:
        start = time.time()
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        took = time.time() - start
        if resp.status_code == 200:
            data = resp.json()["data"]
            quotes = [quote_from_json_blob(s, item) for s, item in data.items()]
            logger.info("✅ API: %d quotes in %.2fs: %s",
                        len(quotes), took, ', '.join(s for s in symbols))
            return quotes
        else:
            logger.error("❌ CMC HTTP %d: %s", resp.status_code, resp.text)
            return []
    except requests.exceptions.Timeout:
        logger.error("⏰ CMC API timed out")
        return []
    except requests.exceptions.RequestException as e:
        logger.error("🌐 CMC API network error: %s", str(e))
        return []
    except Exception as e:
        logger.exception("❌ Unexpected CMC API error: %s", str(e))
        return []

def quote_from_json_blob(symbol: str, item: list) -> PriceQuote:
    """Convert raw CMC response for a symbol to PriceQuote object."""
    info = item[0]     # CoinMarketCap returns list, always take first entry.
    qd = info["quote"]["USD"]
    return PriceQuote(
        symbol=symbol,
        name=info["name"],
        slug=info["slug"],
        price_usd=qd["price"],
        percent_change_1h=qd["percent_change_1h"],
        market_cap=qd["market_cap"]
    )
