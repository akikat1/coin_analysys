import logging


async def set_leverage(leverage: int, symbol: str = "BTCUSDT") -> bool:
    """Set per-symbol leverage and return True on success."""
    from data.rest_client import _request
    import config

    lev = max(config.MIN_LEVERAGE, min(config.MAX_LEVERAGE, int(leverage)))
    r = await _request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})
    if not r:
        logging.warning("Leverage set failed: target=%sx", lev)
        return False
    logging.info("Leverage set: %sx", r.get("leverage", lev))
    return True


async def setup(symbol: str = "BTCUSDT"):
    from data.rest_client import _request
    import config

    r = await _request("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "false"})
    logging.info("One-Way Mode: " + ("already set" if r and r.get("_ignored") else "updated"))

    r = await _request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
    logging.info("ISOLATED: " + ("already set" if r and r.get("_ignored") else "updated"))

    await set_leverage(config.LEVERAGE, symbol)
