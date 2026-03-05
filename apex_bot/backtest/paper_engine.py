"""
Бумажная торговля v12.
Изменения vs v11:
- _paper_tp теперь переносит stop_price на avg_fill_price (безубыток) после TP1.
  Это предотвращает ситуацию: TP1 +$5, стоп достигнут −$9 → итог −$4.
"""
import asyncio, logging, time
import config
from state import PersistentState, RuntimeState
from strategy.signal_engine import evaluate_signal
from strategy.fee_calculator import calculate_net_pnl
from execution import exchange_info
from models import Position
from monitor import logger as trade_logger

async def run_paper_signal_loop(ps: PersistentState, rs: RuntimeState, cs) -> None:
    from data.indicators import calculate
    from data.market_context import _build_regime, update as update_market_context

    for tf in ("1h","15m","5m","1m"):
        if cs.new_candle_flags.get(tf):
            min_len = config.HTF_MIN_CANDLES if tf == "1h" else 50
            if len(cs.candles[tf]) >= min_len:
                rs.indicators[tf] = calculate(cs.candles[tf], tf)
            cs.new_candle_flags[tf] = False

    rs.micro = cs.micro

    if rs.indicators.get("15m"):
        try:
            await update_market_context(rs, cs)
        except Exception as e:
            logging.warning(f"paper market_context.update failed, fallback to _build_regime: {e}")
            rs.context = _build_regime(rs.indicators["15m"], rs.micro.funding_rate)

    if ps.position:
        pos = ps.position; mark = rs.micro.mark_price
        if mark > 0:
            if pos.tp1_filled:
                from execution.position_tracker import update_trailing_stop
                await update_trailing_stop(ps, rs)
                pos = ps.position
                if not pos:
                    return
            if pos.direction == "LONG":
                if mark <= pos.stop_price:
                    await _paper_close(ps, rs, "STOP", pos.stop_price)
                elif not pos.tp1_filled and mark >= pos.tp1_price:
                    await _paper_tp(ps, rs, 1, pos.tp1_price)
                elif pos.tp1_filled and not pos.tp2_filled and mark >= pos.tp2_price:
                    await _paper_tp(ps, rs, 2, pos.tp2_price)
                elif pos.tp1_filled and pos.tp2_filled and mark >= pos.tp3_price:
                    await _paper_close(ps, rs, "TP3", pos.tp3_price)
            else:
                if mark >= pos.stop_price:
                    await _paper_close(ps, rs, "STOP", pos.stop_price)
                elif not pos.tp1_filled and mark <= pos.tp1_price:
                    await _paper_tp(ps, rs, 1, pos.tp1_price)
                elif pos.tp1_filled and not pos.tp2_filled and mark <= pos.tp2_price:
                    await _paper_tp(ps, rs, 2, pos.tp2_price)
                elif pos.tp1_filled and pos.tp2_filled and mark <= pos.tp3_price:
                    await _paper_close(ps, rs, "TP3", pos.tp3_price)

    if not ps.position:
        sig = await evaluate_signal(ps, rs)
        from monitor import logger as lg
        ind15 = rs.indicators.get("15m")
        if sig:
            ps.position = Position(
                direction=sig.direction, entry_price=sig.levels.entry,
                avg_fill_price=sig.levels.entry, qty_btc=sig.levels.qty_btc,
                qty_remaining=sig.levels.qty_btc, stop_price=sig.levels.stop,
                tp1_price=sig.levels.tp1, tp2_price=sig.levels.tp2,
                tp3_price=sig.levels.tp3, stop_order_id=0, tp1_order_id=0,
                tp2_order_id=0, tp3_order_id=0, qty_tp1=sig.levels.qty_tp1,
                qty_tp2=sig.levels.qty_tp2, qty_tp3=sig.levels.qty_tp3,
                confidence_at_entry=sig.confidence,
                adx_at_entry=ind15.adx if ind15 and ind15.adx else 0.0,
                regime_at_entry=rs.context.regime,
                funding_rate_at_entry=rs.micro.funding_rate,
                open_timestamp_ms=int(time.time()*1000), mode="paper",
                leverage_used=config.LEVERAGE)
            import state; state.save(ps)
            lg.log_signal(sig.direction, sig.confidence, sig.score_15m, sig.score_5m,
                          sig.score_1m, True, "", sig.levels.rr,
                          ind15.adx if ind15 and ind15.adx else 0,
                          rs.context.regime, rs.micro.spread_pct,
                          ind15.volume_ratio if ind15 and ind15.volume_ratio else 0,
                          rs.sentiment.value if rs.sentiment.available else -1,
                          rs.last_score_breakdown.to_str() if rs.last_score_breakdown else "")
            score_final = float(sig.confidence)
            score_ai_delta = (
                float(rs.last_score_breakdown.ai_adjustment)
                if rs.last_score_breakdown is not None
                else 0.0
            )
            score_base = score_final - score_ai_delta
            logging.info(
                f"PAPER ENTRY {sig.direction} @ {sig.levels.entry:.2f} "
                f"base_score={score_base:.1f} final_score={score_final:.1f} "
                f"(AI{score_ai_delta:+.1f}) RR={sig.levels.rr:.2f}"
            )
        else:
            rejection = rs.last_rejection_reason or "NO_SIGNAL"
            lg.log_signal(rejection, 0, 0, 0, 0, False, rejection,
                          0, ind15.adx if ind15 and ind15.adx else 0,
                          rs.context.regime, rs.micro.spread_pct,
                          ind15.volume_ratio if ind15 and ind15.volume_ratio else 0,
                          rs.sentiment.value if rs.sentiment.available else -1,
                          rs.last_score_breakdown.to_str() if rs.last_score_breakdown else "")

async def _paper_close(ps, rs, reason: str, price: float) -> None:
    pos = ps.position
    if not pos: return
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = calculate_net_pnl(pos.direction, pos.avg_fill_price, price,
                             pos.qty_remaining, lev)
    total_net = pos.realized_pnl_usd + pnl.net_pnl
    ps.daily_pnl_usd += total_net
    if ps.available_balance > 0: ps.daily_pnl_pct = ps.daily_pnl_usd / ps.available_balance
    ps.available_balance += total_net; ps.trades_today += 1
    if total_net > 0:
        ps.wins_today += 1; ps.consecutive_losses = 0; ps.reduced_size_active = False
    else:
        ps.losses_today += 1; ps.consecutive_losses += 1
    if ps.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        ps.reduced_size_active = True; ps.pause_until = time.time() + 30*60
    if ps.available_balance > ps.equity_peak: ps.equity_peak = ps.available_balance
    if ps.equity_peak > 0:
        ps.equity_drawdown_pct = (ps.equity_peak - ps.available_balance) / ps.equity_peak
    ps.last_trade_close = time.time()
    trade_logger.log_trade(pos, price, pos.qty_remaining, reason, pnl, total_net)
    ps.position = None; import state; state.save(ps)
    logging.info(f"PAPER ЗАКРЫТО [{reason}] @ {price:.2f} net={total_net:+.2f}$")

async def _paper_tp(ps, rs, tp_num: int, price: float) -> None:
    pos = ps.position
    if not pos: return
    qty = pos.qty_tp1 if tp_num == 1 else pos.qty_tp2
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = calculate_net_pnl(pos.direction, pos.avg_fill_price, price, qty, lev)
    pos.realized_pnl_usd += pnl.net_pnl
    pos.qty_remaining -= qty
    if tp_num == 1:
        pos.tp1_filled = True
        # ← ИСПРАВЛЕНО v12 (БАГ 3): перенос стопа на безубыток после TP1
        # Без этого TP1 +$5 → стоп −$9 → итог −$4, что нарушает логику управления рисками
        pos.stop_price = pos.avg_fill_price
        logging.info(f"PAPER TP1 @ {price:.2f} — стоп перенесён на безубыток {pos.avg_fill_price:.2f}")
    elif tp_num == 2:
        pos.tp2_filled = True
    trade_logger.log_trade(pos, price, qty, f"TP{tp_num}", pnl, pos.realized_pnl_usd)
    import state; state.save(ps)
    logging.info(f"PAPER TP{tp_num} @ {price:.2f} net_partial={pnl.net_pnl:+.2f}$")

