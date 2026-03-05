import logging
import time
from datetime import datetime, timezone

import config
from models import Indicators, MarketContext

_oi_history: list[float] = []
_last_enrich_ts: float = 0.0
_cached_oi_signal: str = "NEUTRAL"
_cached_ls_ratio: float = 0.5
_cached_ls_warning: bool = False
_ls_skip_warned: bool = False
_ls_fail_count: int = 0
_ls_permanently_disabled: bool = False
_ls_disabled_warned: bool = False


async def update(rs, cs) -> None:
    ind_15 = rs.indicators.get("15m")
    ctx = _build_regime(ind_15, cs.micro.funding_rate)
    ctx = await _enrich(ctx)
    rs.context = ctx
    rs.micro.funding_rate = cs.micro.funding_rate


def _build_regime(ind: Indicators | None, funding_rate: float) -> MarketContext:
    ctx = MarketContext()
    if ind and ind.adx is not None:
        if ind.adx >= config.ADX_TREND_THRESHOLD:
            ctx.regime = "TREND"
            ctx.size_multiplier = 1.0
            if ind.di_plus and ind.di_minus:
                ctx.trend_dir = "BULL" if ind.di_plus > ind.di_minus else "BEAR"
        elif ind.adx >= config.ADX_WEAK_TREND_THRESHOLD:
            ctx.regime = "WEAK_TREND"
            ctx.size_multiplier = 0.7
        else:
            ctx.regime = "RANGE"
            ctx.size_multiplier = 1.0

    if ctx.regime == "RANGE" and config.ALLOW_RANGE_TRADING:
        ctx.size_multiplier = config.RANGE_SIZE_MULTIPLIER

    now = datetime.now(timezone.utc)
    for fh in config.FUNDING_TIMES_UTC:
        sec_to = (fh - now.hour) * 3600 - now.minute * 60 - now.second
        if sec_to < 0:
            sec_to += 86400
        if sec_to <= config.FUNDING_AVOID_WINDOW_SEC and abs(funding_rate) > config.FUNDING_HIGH_THRESHOLD:
            ctx.funding_filter_active = True
            break

    h = now.hour
    for h_from, h_to in config.AVOID_HOURS_UTC:
        if h_from <= h <= h_to:
            ctx.session_filter_active = True
            break

    if config.ALLOW_RANGE_TRADING:
        ctx.should_trade = (not ctx.funding_filter_active and not ctx.session_filter_active)
    else:
        ctx.should_trade = (
            ctx.regime != "RANGE"
            and not ctx.funding_filter_active
            and not ctx.session_filter_active
        )
    return ctx


async def _enrich(ctx: MarketContext) -> MarketContext:
    global _last_enrich_ts, _cached_oi_signal, _cached_ls_ratio, _cached_ls_warning
    global _ls_skip_warned, _ls_fail_count, _ls_permanently_disabled, _ls_disabled_warned

    now = time.time()
    if now - _last_enrich_ts < config.MARKET_CONTEXT_REFRESH_SEC:
        ctx.oi_signal = _cached_oi_signal
        ctx.ls_ratio = _cached_ls_ratio
        ctx.ls_warning = _cached_ls_warning
        return ctx

    from data.rest_client import _request

    try:
        oi = await _request("GET", "/fapi/v1/openInterest", {"symbol": config.SYMBOL}, signed=False, weight=1)
        if oi:
            _oi_history.append(float(oi["openInterest"]))
            if len(_oi_history) > 5:
                _oi_history.pop(0)
            if len(_oi_history) >= 2 and _oi_history[0] > 0:
                delta = (_oi_history[-1] - _oi_history[0]) / _oi_history[0]
                ctx.oi_signal = (
                    "BULL_CONFIRMING"
                    if delta > 0.01
                    else "BEAR_CONFIRMING"
                    if delta < -0.01
                    else "NEUTRAL"
                )
    except Exception as e:
        logging.warning(f"OI: {e}")

    # This endpoint is often unavailable on Binance testnet (returns HTML instead of JSON).
    if config.TESTNET:
        if not _ls_skip_warned:
            logging.info("L/S ratio skipped on TESTNET (endpoint unavailable)")
            _ls_skip_warned = True
    elif _ls_permanently_disabled:
        pass
    else:
        try:
            ls = await _request(
                "GET",
                "/futures/data/globalLongShortAccountRatio",
                {"symbol": config.SYMBOL, "period": "5m", "limit": "1"},
                signed=False,
                weight=1,
            )
            if not isinstance(ls, list) or not ls:
                raise ValueError("empty or invalid L/S response")
            la = float(ls[0]["longAccount"])
            sa = float(ls[0]["shortAccount"])
            ctx.ls_ratio = la / (la + sa) if (la + sa) > 0 else 0.5
            ctx.ls_warning = ctx.ls_ratio > 0.72 or ctx.ls_ratio < 0.28
            _ls_fail_count = 0
        except Exception as e:
            _ls_fail_count += 1
            if _ls_fail_count >= 3:
                _ls_permanently_disabled = True
                if not _ls_disabled_warned:
                    logging.warning("L/S ratio endpoint disabled after 3 failures")
                    _ls_disabled_warned = True
            else:
                logging.warning("L/S: %s (failure %s/3)", e, _ls_fail_count)

    _last_enrich_ts = now
    _cached_oi_signal = ctx.oi_signal
    _cached_ls_ratio = ctx.ls_ratio
    _cached_ls_warning = ctx.ls_warning
    return ctx
