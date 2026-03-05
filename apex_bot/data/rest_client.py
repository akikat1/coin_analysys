import asyncio, hashlib, hmac, time, logging
import aiohttp
import config

_session: aiohttp.ClientSession|None = None
_time_offset_ms: int = 0
_used_weight: int = 0
_weight_reset_at: float = 0.0

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def close():
    global _session
    if _session and not _session.closed:
        await _session.close(); _session = None

async def sync_server_time():
    global _time_offset_ms
    sess = await get_session()
    async with sess.get(f"{config.REST_BASE}/fapi/v1/time") as r:
        data = await r.json()
    _time_offset_ms = data["serverTime"] - int(time.time()*1000)
    logging.info(f"Время синхронизировано: {_time_offset_ms:+d}ms")

def _sign(params: dict) -> str:
    params["timestamp"]  = int(time.time()*1000) + _time_offset_ms
    params["recvWindow"] = 5000
    qs  = "&".join(f"{k}={v}" for k,v in params.items())
    sig = hmac.new(config.BINANCE_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return qs + f"&signature={sig}"

async def _request(method: str, path: str, params: dict|None=None,
                   signed: bool=True, weight: int=1) -> dict|list|None:
    global _used_weight, _weight_reset_at
    if _used_weight + weight > config.MAX_REST_WEIGHT_MIN:
        wait = max(0.0, _weight_reset_at - time.time() + 0.5)
        logging.warning(f"Rate limit ({_used_weight}/{config.MAX_REST_WEIGHT_MIN}), ждём {wait:.1f}с")
        await asyncio.sleep(wait)
    url     = config.REST_BASE + path
    headers = {"X-MBX-APIKEY": config.BINANCE_API_KEY}
    body    = _sign(dict(params or {})) if signed else (params or {})
    for attempt in range(4):
        try:
            sess = await get_session()
            meth = {"GET":sess.get,"POST":sess.post,"PUT":sess.put,"DELETE":sess.delete}[method]
            kw = {"params":body} if method in ("GET","DELETE") else {"data":body}
            async with meth(url, **kw, headers=headers) as r:
                wh = r.headers.get("X-MBX-USED-WEIGHT-1M")
                if wh: _used_weight = int(wh); _weight_reset_at = time.time()+60
                if r.status == 200: return await r.json()
                if r.status == 429:
                    logging.warning("429 Rate Limit, пауза 60с"); await asyncio.sleep(60); return None
                if r.status == 418:
                    logging.critical("418 IP БАН Binance"); raise SystemExit("IP заблокирован Binance")
                if r.status >= 500: raise aiohttp.ClientError(f"Server {r.status}")
                err = await r.json(); code = err.get("code",0); msg = err.get("msg","")
                if code == -1021: await sync_server_time(); break
                if code in (-2011,-4046,-4059): return {"_ignored":True}
                if code == -4061: logging.critical("-4061 Wrong positionSide"); raise SystemExit("-4061")
                if code == -5022: return {"_gtx_rejected":True}
                if code == -1015: await asyncio.sleep(1); break
                if code in (-2010,-1111): logging.warning(f"Binance {code}: {msg}"); return None
                if code == -2014:
                    logging.critical("❌ -2014: Неверный формат API ключа. Проверь BINANCE_API_KEY в .env")
                    raise SystemExit("-2014: Неверный API ключ")
                if code == -1022:
                    logging.critical("❌ -1022: Неверная подпись. Проверь BINANCE_API_SECRET в .env")
                    raise SystemExit("-1022: Неверный API секрет")
                logging.warning(f"Binance API {code}: {msg}"); return None
        except aiohttp.ClientError as e:
            if attempt < 3:
                await asyncio.sleep(2**attempt)
            else:
                logging.error(f"REST {method} {path} failed: {e}"); return None
    return None

