import asyncio
import hashlib
import hmac
import logging
import time

import aiohttp

import config

_session: aiohttp.ClientSession | None = None
_time_offset_ms: int = 0
_used_weight: int = 0
_weight_reset_at: float = 0.0

_REST_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)
_CONNECTOR_LIMIT = 10


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=_CONNECTOR_LIMIT, limit_per_host=_CONNECTOR_LIMIT)
        _session = aiohttp.ClientSession(connector=connector, timeout=_REST_TIMEOUT)
    return _session


async def close() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def sync_server_time() -> None:
    global _time_offset_ms
    try:
        sess = await get_session()
        async with sess.get(f"{config.REST_BASE}/fapi/v1/time") as r:
            data = await r.json(content_type=None)
        _time_offset_ms = int(data["serverTime"]) - int(time.time() * 1000)
        logging.info("server time synced: offset=%+dms", _time_offset_ms)
    except Exception as e:
        logging.warning("sync_server_time: %s: %s", type(e).__name__, e)


def _sign(params: dict) -> str:
    params["timestamp"] = int(time.time() * 1000) + _time_offset_ms
    params["recvWindow"] = 5000
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sig = hmac.new(config.BINANCE_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return qs + f"&signature={sig}"


async def _request(
    method: str,
    path: str,
    params: dict | None = None,
    signed: bool = True,
    weight: int = 1,
) -> dict | list | None:
    global _used_weight, _weight_reset_at

    now = time.time()
    if _weight_reset_at <= 0 or now >= _weight_reset_at:
        _used_weight = 0
        _weight_reset_at = now + 60.0

    req_weight = max(1, int(weight))
    weight_guard = min(config.MAX_REST_WEIGHT_MIN, 1000)
    if _used_weight + req_weight > weight_guard:
        wait = max(0.0, _weight_reset_at - time.time() + 0.5)
        logging.warning(
            "Rate limit (%s/%s), wait %.1fs",
            _used_weight,
            config.MAX_REST_WEIGHT_MIN,
            wait,
        )
        await asyncio.sleep(wait)
        _used_weight = 0
        _weight_reset_at = time.time() + 60.0

    url = config.REST_BASE + path
    headers = {"X-MBX-APIKEY": config.BINANCE_API_KEY}
    body = _sign(dict(params or {})) if signed else (params or {})

    for attempt in range(4):
        try:
            sess = await get_session()
            meth = {
                "GET": sess.get,
                "POST": sess.post,
                "PUT": sess.put,
                "DELETE": sess.delete,
            }[method]
            kw = {"params": body} if method in ("GET", "DELETE") else {"data": body}

            async with meth(url, **kw, headers=headers) as r:
                wh = r.headers.get("X-MBX-USED-WEIGHT-1M")
                if wh:
                    try:
                        _used_weight = int(wh)
                        _weight_reset_at = time.time() + 60.0
                    except Exception:
                        pass

                if r.status == 200:
                    return await r.json(content_type=None)

                if r.status == 429:
                    logging.warning("429 rate limit, pause 60s")
                    await asyncio.sleep(60)
                    return None

                if r.status == 418:
                    logging.critical("418 IP banned by Binance")
                    raise SystemExit("IP blocked by Binance")

                if r.status >= 500:
                    raise aiohttp.ClientError(f"Server {r.status}")

                try:
                    err = await r.json(content_type=None)
                except Exception:
                    raw = await r.text()
                    logging.warning(
                        "REST %s %s failed: HTTP %s non-JSON response: %s",
                        method,
                        path,
                        r.status,
                        raw[:160],
                    )
                    return None

                code = int(err.get("code", 0) or 0)
                msg = str(err.get("msg", "") or "")

                if code == -1021:
                    await sync_server_time()
                    continue
                if code in (-2011, -4046, -4059):
                    return {"_ignored": True}
                if code == -4061:
                    logging.critical("-4061 Wrong positionSide")
                    raise SystemExit("-4061")
                if code == -5022:
                    return {"_gtx_rejected": True}
                if code == -1015:
                    await asyncio.sleep(1)
                    continue
                if code in (-2010, -1111):
                    logging.warning("Binance %s: %s", code, msg)
                    return None
                if code == -2014:
                    logging.critical("-2014 invalid API key format")
                    raise SystemExit("-2014")
                if code == -1022:
                    logging.critical("-1022 invalid signature")
                    raise SystemExit("-1022")

                logging.warning("Binance API %s: %s", code, msg)
                return None

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < 3:
                await asyncio.sleep(2**attempt)
            else:
                logging.error(
                    "REST %s %s failed: %s: %s",
                    method,
                    path,
                    type(e).__name__,
                    e,
                )
                return None
        except Exception as e:
            if attempt < 3:
                await asyncio.sleep(2**attempt)
            else:
                logging.error(
                    "REST %s %s unexpected: %s: %s",
                    method,
                    path,
                    type(e).__name__,
                    e,
                )
                return None

    return None