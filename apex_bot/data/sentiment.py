"""Fear & Greed index fetcher (alternative.me)."""

import asyncio
import logging
import time

import aiohttp

from models import SentimentData

_SENTIMENT_URL = "https://api.alternative.me/fng/?limit=1"


async def fetch(session) -> SentimentData:
    """Fetch current Fear & Greed value. Never raises."""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        req = session.get(_SENTIMENT_URL, timeout=timeout)
        if not hasattr(req, "__aenter__"):
            req = await req

        async with req as r:
            if r.status != 200:
                logging.warning("sentiment: HTTP %s", r.status)
                return SentimentData(last_error=f"HTTP {r.status}")

            payload = await r.json(content_type=None)
            row = payload["data"][0]
            value = int(row["value"])
            label = str(row["value_classification"])
            logging.info("Fear&Greed: %s (%s)", value, label)
            return SentimentData(
                value=value,
                label=label,
                last_updated_ts=time.time(),
                available=True,
                last_error="",
            )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logging.warning("sentiment fetch error: %s", err)
        return SentimentData(last_error=err)


async def run_sentiment_loop(rs, session):
    """Background loop that refreshes rs.sentiment."""
    import config

    if config.BACKTEST_MODE:
        return

    unavailable_since = 0.0
    while True:
        fresh = await fetch(session)
        if fresh.available:
            rs.sentiment = fresh
            unavailable_since = 0.0
        else:
            now = time.time()
            if unavailable_since <= 0.0:
                unavailable_since = now

            if rs.sentiment.available and (now - unavailable_since) <= 600:
                # Keep previous valid value for up to 10 minutes.
                rs.sentiment.last_error = fresh.last_error
            else:
                rs.sentiment = fresh

        await asyncio.sleep(config.SENTIMENT_UPDATE_INTERVAL_SEC)
