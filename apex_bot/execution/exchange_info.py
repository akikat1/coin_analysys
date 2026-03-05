import math
from data.rest_client import _request

tick_size: float=0.1; step_size: float=0.001; min_notional: float=5.0
_tick_prec: int=1; _step_prec: int=3

async def load(symbol: str="BTCUSDT"):
    global tick_size,step_size,min_notional,_tick_prec,_step_prec
    info = await _request("GET","/fapi/v1/exchangeInfo",signed=False,weight=1)
    sym = next((s for s in info["symbols"] if s["symbol"]==symbol),None)
    if not sym: raise RuntimeError(f"Символ {symbol} не найден")
    for f in sym["filters"]:
        if f["filterType"]=="PRICE_FILTER":
            tick_size=float(f["tickSize"]); _tick_prec=_dec(tick_size)
        elif f["filterType"]=="LOT_SIZE":
            step_size=float(f["stepSize"]); _step_prec=_dec(step_size)
        elif f["filterType"]=="MIN_NOTIONAL":
            min_notional=float(f["notional"])
    import logging
    logging.info(f"exchange_info: tick={tick_size}, step={step_size}, minNotional={min_notional}")

def _dec(v: float) -> int:
    s = f"{v:.10f}".rstrip("0"); return len(s.split(".")[1]) if "." in s else 0

def round_price(price: float) -> float:
    return round(round(price/tick_size)*tick_size, _tick_prec)

def round_qty(qty: float) -> float:
    return round(math.floor(qty/step_size)*step_size, _step_prec)

def validate(price: float, qty: float) -> bool:
    return qty*price >= min_notional and qty >= step_size

