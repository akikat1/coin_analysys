"""
Обработка событий очереди ордеров (live-режим).
Отвечает за TP1, TP2 (partial close), закрытие по стопу, ликвидацию.
"""
import logging, time
import config
from state import PersistentState, RuntimeState
from strategy import fee_calculator
from monitor import logger as trade_logger

async def handle_queue_event(event: dict, ps: PersistentState, rs: RuntimeState) -> None:
    etype = event.get("_type")
    if etype == "ORDER":
        await _handle_order(event["data"], ps, rs)
    elif etype == "ACCOUNT":
        await _handle_account_update(event["data"], ps)
    elif etype == "LIQUIDATION":
        await _handle_liquidation(event["liq_price"], ps, rs)

async def _handle_order(o: dict, ps: PersistentState, rs: RuntimeState) -> None:
    if o.get("X") != "FILLED": return
    pos = ps.position
    if not pos: return
    oid = int(o.get("i", 0))
    fill_price = float(o.get("ap") or o.get("p") or 0)
    if fill_price <= 0: return

    if oid == pos.tp1_order_id:
        await _handle_tp1_filled(fill_price, ps, rs)
    elif oid == pos.tp2_order_id:
        await _handle_tp2_filled(fill_price, ps, rs)
    elif oid == pos.stop_order_id or oid == pos.tp3_order_id:
        reason = "TP3" if oid == pos.tp3_order_id else "STOP"
        await _close_trade(reason, fill_price, pos.qty_remaining, ps, rs)

async def _handle_tp1_filled(fill_price: float, ps: PersistentState, rs: RuntimeState) -> None:
    pos = ps.position
    if not pos: return
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = fee_calculator.calculate_net_pnl(pos.direction, pos.avg_fill_price, fill_price,
                                            pos.qty_tp1, lev)
    pos.realized_pnl_usd += pnl.net_pnl
    pos.qty_remaining -= pos.qty_tp1
    pos.tp1_filled = True
    # ← ПРАВИЛО 24 (v12): перенос стопа на безубыток после TP1
    pos.stop_price = pos.avg_fill_price
    trade_logger.log_trade(pos, fill_price, pos.qty_tp1, "TP1", pnl, pos.realized_pnl_usd)
    stop_side = "SELL" if pos.direction == "LONG" else "BUY"
    # Отменить старый стоп и выставить новый на безубыток
    from execution.order_manager import cancel_order
    from data import rest_client
    from execution import exchange_info
    if pos.stop_order_id > 0:
        await cancel_order(pos.stop_order_id)
    new_stop_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": stop_side, "type": "STOP_MARKET",
        "stopPrice": exchange_info.round_price(pos.avg_fill_price),
        "quantity": exchange_info.round_qty(pos.qty_remaining),
        "reduceOnly": "true", "timeInForce": "GTE_GTC"
    })
    if new_stop_r and not new_stop_r.get("_ignored"):
        pos.stop_order_id = int(new_stop_r.get("orderId", 0))
    # Выставить TP2
    tp2_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": stop_side, "type": "TAKE_PROFIT_MARKET",
        "stopPrice": exchange_info.round_price(pos.tp2_price),
        "quantity": exchange_info.round_qty(pos.qty_tp2),
        "reduceOnly": "true", "timeInForce": "GTE_GTC"
    })
    if tp2_r and not tp2_r.get("_ignored"):
        pos.tp2_order_id = int(tp2_r.get("orderId", 0))
    from monitor import notifier
    await notifier.send_tp_hit(1, fill_price, pos)
    import state; state.save(ps)

async def _handle_tp2_filled(fill_price: float, ps: PersistentState, rs: RuntimeState) -> None:
    pos = ps.position
    if not pos: return
    from execution import exchange_info
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = fee_calculator.calculate_net_pnl(pos.direction, pos.avg_fill_price, fill_price,
                                            pos.qty_tp2, lev)
    pos.realized_pnl_usd += pnl.net_pnl; pos.qty_remaining -= pos.qty_tp2; pos.tp2_filled = True
    trade_logger.log_trade(pos, fill_price, pos.qty_tp2, "TP2", pnl, pos.realized_pnl_usd)
    stop_side = "SELL" if pos.direction == "LONG" else "BUY"
    from data import rest_client
    tp3_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": stop_side, "type": "TAKE_PROFIT_MARKET",
        "stopPrice": exchange_info.round_price(pos.tp3_price),
        "quantity": exchange_info.round_qty(pos.qty_remaining),
        "reduceOnly": "true", "timeInForce": "GTE_GTC"
    })
    if tp3_r and not tp3_r.get("_ignored"):
        pos.tp3_order_id = int(tp3_r.get("orderId", 0))
    from monitor import notifier
    await notifier.send_tp_hit(2, fill_price, pos)
    import state; state.save(ps)

async def _close_trade(reason: str, price: float, qty: float,
                       ps: PersistentState, rs: RuntimeState) -> None:
    pos = ps.position
    if not pos: return
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = fee_calculator.calculate_net_pnl(pos.direction, pos.avg_fill_price, price, qty, lev)
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
        from monitor import notifier; await notifier.send_pause_notification(ps)
    if ps.available_balance > ps.equity_peak: ps.equity_peak = ps.available_balance
    if ps.equity_peak > 0:
        ps.equity_drawdown_pct = (ps.equity_peak - ps.available_balance) / ps.equity_peak
    ps.last_trade_close = time.time()
    trade_logger.log_trade(pos, price, qty, reason, pnl, total_net)
    from monitor import notifier
    await notifier.send_trade_closed(reason, price, pnl, total_net, ps)
    if not config.PAPER_MODE:
        from execution.order_manager import cancel_order
        for oid in [pos.stop_order_id, pos.tp1_order_id, pos.tp2_order_id, pos.tp3_order_id]:
            if oid > 0: await cancel_order(oid)
    ps.position = None; import state; state.save(ps)
    logging.info(f"ЗАКРЫТО [{reason}] @ {price:.2f}  net={total_net:+.2f}$")

async def _handle_account_update(data: dict, ps: PersistentState) -> None:
    for asset in data.get("a", {}).get("B", []):
        if asset.get("a") == "USDT":
            ps.available_balance = float(asset.get("wb", ps.available_balance)); break

async def _handle_liquidation(liq_price: float, ps: PersistentState, rs: RuntimeState) -> None:
    logging.critical(f"ЛИКВИДАЦИЯ @ {liq_price:.2f}")
    from monitor import notifier
    await notifier.send_liquidation_alert(liq_price, ps)
    ps.position = None; ps.consecutive_losses += 1; ps.losses_today += 1
    import state; state.save(ps)

async def update_trailing_stop(ps: PersistentState, rs: RuntimeState) -> None:
    """
    v13: подтягивает stop после TP1 на основе ATR.
    Для LONG: stop = max(old_stop, mark - ATR*mult)
    Для SHORT: stop = min(old_stop, mark + ATR*mult)
    """
    if not config.TRAILING_STOP_ENABLED:
        return
    pos = ps.position
    if not pos or not pos.tp1_filled:
        return

    ind_15 = rs.indicators.get("15m")
    atr = ind_15.atr if ind_15 else None
    mark = rs.micro.mark_price
    if not atr or atr <= 0 or mark <= 0:
        return

    from execution import exchange_info
    trail_offset = atr * config.TRAILING_ATR_MULTIPLIER
    updated = False

    if pos.direction == "LONG":
        candidate = exchange_info.round_price(mark - trail_offset)
        if candidate > pos.stop_price:
            pos.stop_price = candidate
            pos.trailing_stop_active = True
            pos.trailing_stop_price = candidate
            updated = True
    else:
        candidate = exchange_info.round_price(mark + trail_offset)
        if pos.stop_price <= 0 or candidate < pos.stop_price:
            pos.stop_price = candidate
            pos.trailing_stop_active = True
            pos.trailing_stop_price = candidate
            updated = True

    if not updated:
        return

    if not config.PAPER_MODE and pos.stop_order_id > 0:
        try:
            from execution.order_manager import cancel_order
            from data import rest_client
            stop_side = "SELL" if pos.direction == "LONG" else "BUY"
            await cancel_order(pos.stop_order_id)
            r = await rest_client._request("POST", "/fapi/v1/order", {
                "symbol": config.SYMBOL,
                "side": stop_side,
                "type": "STOP_MARKET",
                "stopPrice": exchange_info.round_price(pos.stop_price),
                "quantity": exchange_info.round_qty(pos.qty_remaining),
                "reduceOnly": "true",
                "timeInForce": "GTE_GTC",
            })
            if r and not r.get("_ignored"):
                pos.stop_order_id = int(r.get("orderId", pos.stop_order_id))
        except Exception as e:
            logging.warning(f"update_trailing_stop: не удалось обновить stop ордер: {e}")

    import state
    state.save(ps)

