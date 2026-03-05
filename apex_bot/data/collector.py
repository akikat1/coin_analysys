import asyncio, logging
from collections import deque
from dataclasses import dataclass, field
from models import Candle, AggTrade, MicrostructureData

@dataclass
class CollectorState:
    candles: dict = field(default_factory=lambda: {
        "1h": deque(maxlen=200), "15m": deque(maxlen=500), "5m": deque(maxlen=500), "1m": deque(maxlen=500)})
    new_candle_flags: dict = field(default_factory=lambda: {"1h":False,"15m":False,"5m":False,"1m":False})
    agg_trades: deque = field(default_factory=lambda: deque(maxlen=10000))
    order_book: dict = field(default_factory=lambda: {"bids":[], "asks":[]})
    ob_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    micro: MicrostructureData = field(default_factory=MicrostructureData)
    order_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    listen_key: str = ""

async def preload_candles(cs: CollectorState, symbol: str = "BTCUSDT") -> None:
    """
    Предзагрузить исторические свечи через REST, чтобы индикаторы были доступны сразу
    после старта (без ожидания 10+ часов закрытия новых свечей).
    """
    from data.rest_client import _request

    tf_limits = {"1h": 200, "15m": 200, "5m": 300, "1m": 300}
    loaded = {}
    for tf, limit in tf_limits.items():
        try:
            data = await _request(
                "GET",
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": tf, "limit": limit},
                signed=False,
                weight=5,
            )
            if not isinstance(data, list):
                loaded[tf] = 0
                continue
            cs.candles[tf].clear()
            for k in data:
                cs.candles[tf].append(
                    Candle(
                        open_time=int(k[0]),
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        volume=float(k[5]),
                        close_time=int(k[6]),
                        is_closed=True,
                    )
                )
            cs.new_candle_flags[tf] = True
            loaded[tf] = len(data)
        except Exception as e:
            loaded[tf] = 0
            logging.warning(f"preload_candles {tf}: {e}")
        await asyncio.sleep(0.2)
    logging.info(
        "preload_candles: 1h=%s 15m=%s 5m=%s 1m=%s",
        loaded.get("1h", 0),
        loaded.get("15m", 0),
        loaded.get("5m", 0),
        loaded.get("1m", 0),
    )

async def run_market_stream(cs: CollectorState):
    import aiohttp, json, config
    from data.rest_client import get_session
    url = (config.WS_BASE + "/stream?streams=" +
           "btcusdt@kline_1m/btcusdt@kline_5m/btcusdt@kline_15m/btcusdt@kline_1h/"
           "btcusdt@aggTrade/btcusdt@depth20@100ms/"
           "btcusdt@bookTicker/btcusdt@markPrice@1s")
    sess = await get_session()
    async with sess.ws_connect(url, heartbeat=config.WS_HEARTBEAT_SEC) as ws:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await _dispatch(json.loads(msg.data), cs)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

async def run_user_stream(cs: CollectorState):
    import aiohttp, json, config
    from data.rest_client import get_session, _request
    r = await _request("POST", "/fapi/v1/listenKey", {})
    if not r: raise RuntimeError("Не удалось получить listenKey")
    cs.listen_key = r["listenKey"]
    sess = await get_session()
    async with sess.ws_connect(
        config.WS_BASE + f"/ws/{cs.listen_key}",
        heartbeat=config.WS_HEARTBEAT_SEC
    ) as ws:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await _dispatch_user(json.loads(msg.data), cs)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

async def run_keepalive(cs: CollectorState):
    import asyncio, config
    from data.rest_client import _request, sync_server_time
    while True:
        await asyncio.sleep(29 * 60)
        if cs.listen_key:
            await _request("PUT", "/fapi/v1/listenKey", {"listenKey": cs.listen_key})
        await sync_server_time()

async def _dispatch(data: dict, cs: CollectorState):
    import time
    stream = data.get("stream", ""); ev = data.get("data", data)
    if "kline" in stream:
        k = ev["k"]; tf = k.get("i")
        if tf in cs.candles and k["x"]:
            cs.candles[tf].append(Candle(
                open_time=k["t"], open=float(k["o"]), high=float(k["h"]),
                low=float(k["l"]), close=float(k["c"]), volume=float(k["v"]),
                close_time=k["T"], is_closed=True))
            cs.new_candle_flags[tf] = True
    elif "aggTrade" in stream:
        cs.agg_trades.append(AggTrade(
            timestamp_ms=ev["T"], price=float(ev["p"]),
            quantity=float(ev["q"]), is_buyer_maker=ev["m"]))
        _update_cvd(cs)
    elif "depth" in stream:
        async with cs.ob_lock:
            cs.order_book["bids"] = [(float(p),float(q)) for p,q in ev["b"]]
            cs.order_book["asks"] = [(float(p),float(q)) for p,q in ev["a"]]
            bv = sum(q for _,q in cs.order_book["bids"][:10])
            av = sum(q for _,q in cs.order_book["asks"][:10])
            cs.micro.obi = (bv-av)/(bv+av) if (bv+av)>0 else 0.0
    elif "bookTicker" in stream:
        cs.micro.best_bid = float(ev["b"]); cs.micro.best_ask = float(ev["a"])
        cs.micro.spread_pct = ((cs.micro.best_ask - cs.micro.best_bid) / cs.micro.best_bid
                               if cs.micro.best_bid > 0 else 0.0)
        import time
        cs.micro.last_updated_ms = int(time.time() * 1000)
    elif "markPrice" in stream:
        cs.micro.funding_rate = float(ev["r"]); cs.micro.mark_price = float(ev["p"])

def _update_cvd(cs: CollectorState):
    import time
    now = int(time.time() * 1000); t = cs.agg_trades
    r60  = [x for x in t if x.timestamp_ms > now - 60_000]
    r300 = [x for x in t if x.timestamp_ms > now - 300_000]
    b60  = sum(x.quantity for x in r60  if not x.is_buyer_maker)
    s60  = sum(x.quantity for x in r60  if     x.is_buyer_maker)
    b300 = sum(x.quantity for x in r300 if not x.is_buyer_maker)
    s300 = sum(x.quantity for x in r300 if     x.is_buyer_maker)
    t60  = b60 + s60
    cs.micro.cvd_60s = b60 - s60
    cs.micro.trade_flow_60s = b60/t60 if t60>0 else 0.5
    cs.micro.cvd_300s = b300 - s300

async def _dispatch_user(ev: dict, cs: CollectorState):
    etype = ev.get("e")
    if etype == "ORDER_TRADE_UPDATE":
        await cs.order_queue.put({"_type":"ORDER","data":ev["o"]})
    elif etype == "ACCOUNT_UPDATE":
        await cs.order_queue.put({"_type":"ACCOUNT","data":ev})
    elif etype == "FORCE_ORDER":
        o = ev.get("o",{}); liq_price = float(o.get("ap") or o.get("p") or cs.micro.mark_price)
        await cs.order_queue.put({"_type":"LIQUIDATION","liq_price":liq_price})

