"""
Движок сигналов v13.
"""
import logging
import time

import config
from execution import exchange_info
from models import ScoreBreakdown, Signal
from state import PersistentState, RuntimeState
from strategy import ai_advisor, fee_calculator, risk_manager


def _htf_trend(ind_1h) -> str:
    if not ind_1h:
        return "NEUTRAL"
    if all(x is not None for x in (ind_1h.ema9, ind_1h.ema21, ind_1h.ema50)):
        if ind_1h.ema9 > ind_1h.ema21 > ind_1h.ema50:
            return "BULL"
        if ind_1h.ema9 < ind_1h.ema21 < ind_1h.ema50:
            return "BEAR"
    return "NEUTRAL"


def _score_tf(ind, micro) -> tuple[float, float, dict]:
    if ind is None:
        return 0.0, 0.0, {"LONG": {}, "SHORT": {}}
    ls = 0.0
    ss = 0.0
    parts = {"LONG": {}, "SHORT": {}}

    def add(name: str, long_v: float = 0.0, short_v: float = 0.0) -> None:
        nonlocal ls, ss
        ls += long_v
        ss += short_v
        if long_v:
            parts["LONG"][name] = parts["LONG"].get(name, 0.0) + long_v
        if short_v:
            parts["SHORT"][name] = parts["SHORT"].get(name, 0.0) + short_v

    if all(x is not None for x in (ind.ema9, ind.ema21, ind.ema50)):
        if ind.ema9 > ind.ema21 > ind.ema50:
            add("ema", 10, 0)
        if ind.ema9 < ind.ema21 < ind.ema50:
            add("ema", 0, 10)

    if ind.vwap and ind.last_close:
        if ind.last_close > ind.vwap:
            add("vwap", 8, 0)
        if ind.last_close < ind.vwap:
            add("vwap", 0, 8)

    if ind.supertrend_dir == "UP":
        add("supertrend", 7, 0)
    if ind.supertrend_dir == "DOWN":
        add("supertrend", 0, 7)

    if ind.ichimoku_above_cloud is True:
        add("ichimoku", 5, 0)
    if ind.ichimoku_above_cloud is False:
        add("ichimoku", 0, 5)

    if ind.macd_cross == "bull" and ind.macd_cross_age and ind.macd_cross_age <= 3:
        if ind.macd_hist and ind.macd_hist > 0:
            add("macd", 10, 0)
    if ind.macd_cross == "bear" and ind.macd_cross_age and ind.macd_cross_age <= 3:
        if ind.macd_hist and ind.macd_hist < 0:
            add("macd", 0, 10)

    if ind.rsi is not None:
        if 30 <= ind.rsi < 40:
            add("rsi", 8, 0)
        elif 60 < ind.rsi <= 70:
            add("rsi", 0, 8)
        elif ind.rsi < 30:
            add("rsi", 5, 0)
        elif ind.rsi > 70:
            add("rsi", 0, 5)

    if ind.stoch_cross == "bull":
        add("stoch", 7, 0)
    if ind.stoch_cross == "bear":
        add("stoch", 0, 7)

    if micro.cvd_300s > 0:
        add("cvd", 10, 0)
    if micro.cvd_300s < 0:
        add("cvd", 0, 10)

    if ind.obv is not None and len(ind.obv_prev_3) == 3:
        if all(ind.obv_prev_3[i] < ind.obv_prev_3[i + 1] for i in range(2)) and ind.obv > ind.obv_prev_3[-1]:
            add("obv", 8, 0)
        if all(ind.obv_prev_3[i] > ind.obv_prev_3[i + 1] for i in range(2)) and ind.obv < ind.obv_prev_3[-1]:
            add("obv", 0, 8)

    if ind.volume_ratio and ind.volume_ratio >= config.MIN_VOLUME_RATIO:
        add("volume", 7, 7)

    if micro.obi > 0.15:
        add("obi", 8, 0)
    if micro.obi < -0.15:
        add("obi", 0, 8)

    if micro.trade_flow_60s > 0.60:
        add("flow", 7, 0)
    if micro.trade_flow_60s < 0.40:
        add("flow", 0, 7)

    if micro.funding_rate < config.FUNDING_HIGH_THRESHOLD:
        add("funding", 5, 0)
    if micro.funding_rate > 0:
        add("funding", 0, 5)

    return ls, ss, parts


def _best_direction(ls: float, ss: float) -> tuple[float, str]:
    if ls > ss and ls >= 30:
        return ls, "LONG"
    if ss > ls and ss >= 30:
        return ss, "SHORT"
    return max(ls, ss), "NEUTRAL"


def _apply_volume_profile_bonus(direction: str, ind_15, entry_est: float) -> float:
    if entry_est <= 0 or not ind_15:
        return 0.0
    bonus = 0.0
    if ind_15.poc and abs(entry_est - ind_15.poc) / entry_est < 0.0015:
        bonus += 4.0
    if direction == "LONG":
        if ind_15.val and entry_est <= ind_15.val * 1.001:
            bonus += 3.0
        if ind_15.vah and entry_est > ind_15.vah * 1.001:
            bonus += 2.0
    else:
        if ind_15.vah and entry_est >= ind_15.vah * 0.999:
            bonus += 3.0
        if ind_15.val and entry_est < ind_15.val * 0.999:
            bonus += 2.0
    return bonus


async def evaluate_signal(ps: PersistentState, rs: RuntimeState) -> Signal | None:
    ai_evaluated = False

    def _reject(reason: str) -> None:
        rs.last_rejection_reason = reason
        rs.last_signal_ts = time.time()
        if config.AI_ENABLED and not ai_evaluated and not reason.startswith("AI_VETO("):
            rs.last_ai_note = f"AI skip before signal: {reason}"

    rs.last_score_breakdown = None
    now_ms = int(time.time() * 1000)
    if not config.BACKTEST_MODE:
        if now_ms - rs.micro.last_updated_ms > config.MAX_MICROSTRUCTURE_STALENESS_MS:
            _reject("STALE_MICRO")
            return None

    ctx = rs.context
    ind_15 = rs.indicators.get("15m")
    ind_1h = rs.indicators.get("1h")

    if ps.daily_pnl_pct <= -config.MAX_DAILY_LOSS_PCT:
        _reject("DAILY_LIMIT")
        return None
    if ps.equity_drawdown_pct >= config.MAX_DRAWDOWN_PCT:
        _reject("MAX_DRAWDOWN")
        return None
    if ps.position is not None:
        _reject("POSITION_OPEN")
        return None
    if time.time() - ps.last_trade_close < config.SIGNAL_COOLDOWN_SEC:
        _reject("COOLDOWN")
        return None
    if ps.pause_until > time.time():
        _reject("LOSS_PAUSE")
        return None
    if ps.available_balance < config.MIN_BALANCE_USD:
        _reject("LOW_BALANCE")
        return None
    if not ctx.should_trade:
        reason = (
            "FUNDING_FILTER"
            if ctx.funding_filter_active
            else "SESSION_FILTER"
            if ctx.session_filter_active
            else "NO_TREND_RANGE"
        )
        _reject(reason)
        return None
    if rs.micro.spread_pct > config.MAX_SPREAD_PCT:
        _reject("HIGH_SPREAD")
        return None
    if ind_15 is None or ind_15.atr is None:
        _reject("NO_INDICATORS")
        return None
    if ind_15.atr_avg_24h and ind_15.atr > ind_15.atr_avg_24h * config.MAX_ATR_MULTIPLIER:
        _reject("HIGH_VOLATILITY")
        return None
    if config.ENFORCE_VOLUME_FILTER and ind_15.volume_ratio and ind_15.volume_ratio < config.MIN_VOLUME_RATIO:
        _reject("LOW_VOLUME")
        return None

    ls15, ss15, p15 = _score_tf(rs.indicators.get("15m"), rs.micro)
    ls5, ss5, _ = _score_tf(rs.indicators.get("5m"), rs.micro)
    ls1, ss1, _ = _score_tf(rs.indicators.get("1m"), rs.micro)
    s15, d15 = _best_direction(ls15, ss15)
    s5, d5 = _best_direction(ls5, ss5)
    s1, _ = _best_direction(ls1, ss1)
    if d15 == "NEUTRAL" or d15 != d5:
        _reject(f"NO_TF_CONFLUENCE({d15}/{d5})")
        return None

    direction = d15
    htf_dir = _htf_trend(ind_1h)
    if config.HTF_FILTER_ENABLED:
        if direction == "LONG" and htf_dir == "BEAR":
            _reject("HTF_COUNTER_TREND_LONG")
            return None
        if direction == "SHORT" and htf_dir == "BULL":
            _reject("HTF_COUNTER_TREND_SHORT")
            return None

    base = s15 * 0.50 + s5 * 0.35 + s1 * 0.15
    breakdown = ScoreBreakdown(direction=direction)
    p_dir = p15[direction]
    breakdown.ema_score = p_dir.get("ema", 0.0)
    breakdown.vwap_score = p_dir.get("vwap", 0.0)
    breakdown.supertrend_score = p_dir.get("supertrend", 0.0)
    breakdown.ichimoku_score = p_dir.get("ichimoku", 0.0)
    breakdown.macd_score = p_dir.get("macd", 0.0)
    breakdown.rsi_score = p_dir.get("rsi", 0.0)
    breakdown.stoch_score = p_dir.get("stoch", 0.0)
    breakdown.cvd_score = p_dir.get("cvd", 0.0)
    breakdown.obv_score = p_dir.get("obv", 0.0)
    breakdown.volume_score = p_dir.get("volume", 0.0)
    breakdown.obi_score = p_dir.get("obi", 0.0)
    breakdown.flow_score = p_dir.get("flow", 0.0)
    breakdown.funding_score = p_dir.get("funding", 0.0)

    if ind_15.bb_squeeze:
        base += 5
        breakdown.squeeze_bonus += 5
    if ctx.oi_signal == "BULL_CONFIRMING" and direction == "LONG":
        base += 5
        breakdown.oi_bonus += 5
    if ctx.oi_signal == "BEAR_CONFIRMING" and direction == "SHORT":
        base += 5
        breakdown.oi_bonus += 5
    if ctx.regime == "TREND":
        if ctx.trend_dir == "BULL" and direction == "LONG":
            base += 3
        if ctx.trend_dir == "BEAR" and direction == "SHORT":
            base += 3
    if ctx.ls_warning:
        base -= 10
        breakdown.ls_penalty -= 10
    if ctx.regime == "WEAK_TREND":
        base -= 5
        breakdown.weak_trend_penalty -= 5

    sent = rs.sentiment
    if sent.available:
        if sent.value < config.SENTIMENT_EXTREME_FEAR_THRESHOLD:
            if direction == "SHORT":
                _reject(f"SENTIMENT_EXTREME_FEAR({sent.value})")
                return None
            base += config.SENTIMENT_SCORE_BONUS
            breakdown.sentiment_bonus += config.SENTIMENT_SCORE_BONUS
        elif sent.value > config.SENTIMENT_EXTREME_GREED_THRESHOLD:
            if direction == "LONG":
                _reject(f"SENTIMENT_EXTREME_GREED({sent.value})")
                return None
            base += config.SENTIMENT_SCORE_BONUS
            breakdown.sentiment_bonus += config.SENTIMENT_SCORE_BONUS
        elif 25 <= sent.value <= 44 and direction == "LONG":
            base += 2
            breakdown.sentiment_bonus += 2
        elif 56 <= sent.value <= 74 and direction == "SHORT":
            base += 2
            breakdown.sentiment_bonus += 2

    entry_est = rs.micro.best_ask if direction == "LONG" else rs.micro.best_bid
    if entry_est > 0:
        if ind_15.pivot_r1 and direction == "LONG":
            if 0 < (ind_15.pivot_r1 - entry_est) / entry_est < 0.003:
                base -= 5
        if ind_15.pivot_s1 and direction == "SHORT":
            if 0 < (entry_est - ind_15.pivot_s1) / entry_est < 0.003:
                base -= 5
        vp_bonus = _apply_volume_profile_bonus(direction, ind_15, entry_est)
        base += vp_bonus
        breakdown.poc_score += vp_bonus

    if htf_dir != "NEUTRAL":
        breakdown.htf_score = 6.0
        base += 6.0

    ai_evaluated = True
    ai_advice = await ai_advisor.get_trade_advice(direction, base, rs, ind_15, htf_dir)
    if ai_advice:
        breakdown.ai_decision = ai_advice.decision
        breakdown.ai_reason = ai_advice.reason
        if config.AI_MODE in ("assist", "hybrid") and ai_advice.score_delta:
            base += ai_advice.score_delta
            breakdown.ai_adjustment += ai_advice.score_delta
        if ai_advice.decision == "BLOCK" and config.AI_MODE in ("gate", "hybrid"):
            breakdown.total = base
            rs.last_score_breakdown = breakdown
            reason = (ai_advice.reason or "AI_BLOCK").replace(")", "]").replace("(", "[")
            _reject(f"AI_VETO({reason[:80]})")
            return None

    breakdown.total = base
    rs.last_score_breakdown = breakdown

    if base < config.MIN_CONFIDENCE:
        _reject(f"LOW_SCORE({base:.1f}<{config.MIN_CONFIDENCE})")
        return None

    leverage_override = None
    if ind_15.atr_pct and ind_15.atr_pct > config.ATR_PCT_HIGH_VOLATILITY:
        leverage_override = config.MIN_LEVERAGE
        logging.info(
            "Dynamic leverage: atr_pct=%.3f > %.3f, leverage_override=MIN_LEVERAGE(%s)",
            ind_15.atr_pct,
            config.ATR_PCT_HIGH_VOLATILITY,
            config.MIN_LEVERAGE,
        )

    levels = risk_manager.calculate_levels(
        entry=entry_est,
        direction=direction,
        atr=ind_15.atr,
        balance=ps.available_balance,
        context=ctx,
        reduced_size_active=ps.reduced_size_active,
        leverage_override=leverage_override,
    )
    if levels is None or levels.rr < config.MIN_RR:
        _reject(f"LOW_RR({levels.rr if levels else 0:.2f}<{config.MIN_RR})")
        return None
    if levels.margin_usd > ps.available_balance * 0.9:
        _reject("INSUFFICIENT_MARGIN")
        return None

    eff_lev = levels.leverage if levels.leverage > 0 else config.LEVERAGE

    if not fee_calculator.is_tp1_profitable(entry_est, levels.tp1, levels.qty_btc, eff_lev, direction):
        _reject("TP1_NOT_PROFITABLE")
        return None

    rs.last_rejection_reason = "PASSED"
    rs.last_signal_ts = time.time()
    return Signal(
        direction=direction,
        confidence=base,
        score_15m=s15,
        score_5m=s5,
        score_1m=s1,
        levels=levels,
        context=ctx,
        timestamp=int(time.time() * 1000),
        rejection_reason="",
    )
