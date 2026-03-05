"""
Fear & Greed Index от alternative.me
URL: https://api.alternative.me/fng/
Бесплатный API, без ключа, лимит ~1000 запросов/день.

Значения:
  0–24  → Extreme Fear   (хороший момент покупки, плохой для шорта)
  25–44 → Fear
  45–55 → Neutral
  56–74 → Greed
  75–100 → Extreme Greed (хороший момент шорта, плохой для лонга)
"""
import asyncio, logging, time
import aiohttp
from models import SentimentData

_SENTIMENT_URL = "https://api.alternative.me/fng/?limit=1"

async def fetch(session) -> SentimentData:
    """Получить текущий Fear & Greed Index. Никогда не бросает исключение."""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(_SENTIMENT_URL, timeout=timeout) as r:
            if r.status != 200:
                logging.warning(f"sentiment: HTTP {r.status}")
                return SentimentData()
            j = await r.json(content_type=None)
            d = j["data"][0]
            val = int(d["value"])
            lbl = d["value_classification"]
            logging.info(f"Fear&Greed: {val} ({lbl})")
            return SentimentData(value=val, label=lbl,
                                 last_updated_ts=time.time(), available=True)
    except Exception as e:
        logging.warning(f"sentiment fetch error: {e}")
        return SentimentData()

async def run_sentiment_loop(rs, session):
    """
    Фоновая задача: обновляет rs.sentiment каждые SENTIMENT_UPDATE_INTERVAL_SEC секунд.
    В BACKTEST_MODE не запускается (там sentiment = Neutral по умолчанию).
    """
    import config
    if config.BACKTEST_MODE:
        return
    while True:
        rs.sentiment = await fetch(session)
        await asyncio.sleep(config.SENTIMENT_UPDATE_INTERVAL_SEC)

