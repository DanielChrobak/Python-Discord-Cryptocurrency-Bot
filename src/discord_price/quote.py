import logging
import requests
from typing import List, Dict
from dataclasses import dataclass
import time


logger = logging.getLogger(__name__)


@dataclass
class PriceQuote:
    symbol: str
    name: str
    slug: str
    price_usd: float
    percent_change_1h: float
    market_cap: float


@dataclass
class TimestampedQuote:
    quote: PriceQuote
    when: float


class PriceQuoteCache:
    api_key: str
    liveness_seconds: float
    cache: Dict[str,TimestampedQuote]

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.liveness_seconds = 60.0
        self.cache = {}

    async def fetch(self, symbols: List[str], now: float) -> List[PriceQuote]:
        have = []
        need = []
        for symbol in symbols:
            quote = self.cache.get(symbol)
            if quote is not None and ((now - quote.when) < self.liveness_seconds):
                have.append(quote.quote)
            else:
                need.append(symbol)
        refreshed = await fetch_crypto_data(self.api_key, need)
        now = time.time()
        for new_quote in refreshed:
            self.cache[new_quote.symbol] = TimestampedQuote(quote=new_quote, when=now)
        return have + refreshed

    async def fetch_no_cache(self, symbols: List[str]) -> List[PriceQuote]:
        return fetch_crypto_data(self.api_key, symbols)


# Fetch crypto data from CoinMarketCap
async def fetch_crypto_data(api_key: str, symbols: List[str]) -> List[PriceQuote]:
    if not symbols:
        return []

    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": api_key,
        "Accept": "application/json"
    }
    params = {
        "symbol": ",".join(symbols)
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        data: dict = response.json()
        return [
            quote_from_json_blob(symbol, item)
            for symbol, item in data.items()
        ]
    except Exception as e:
        logger.exception("Error fetching crypto data")
        return {}


def quote_from_json_blob(symbol: str, item: Dict) -> PriceQuote:
    first = item[0]["quote"]["USD"]
    quote = PriceQuote(
        symbol=symbol,
        name=first["name"],
        slug=first["slug"],
        price_usd=first["price"],
        percent_change_1h=first["percent_change_1h"],
        market_cap=first["market_cap"],
    )
