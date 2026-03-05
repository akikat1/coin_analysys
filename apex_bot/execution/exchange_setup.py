import logging

async def setup(symbol: str = "BTCUSDT"):
    from data.rest_client import _request
    import config
    r = await _request("POST","/fapi/v1/positionSide/dual",{"dualSidePosition":"false"})
    logging.info("One-Way Mode: "+("уже был" if r and r.get("_ignored") else "установлен"))
    r = await _request("POST","/fapi/v1/marginType",{"symbol":symbol,"marginType":"ISOLATED"})
    logging.info("ISOLATED: "+("уже был" if r and r.get("_ignored") else "установлен"))
    r = await _request("POST","/fapi/v1/leverage",{"symbol":symbol,"leverage":config.LEVERAGE})
    if r: logging.info(f"Плечо: {r.get('leverage')}x")

