import logging
import time

import config
from execution import exchange_info
from models import Position
from state import PersistentState


async def sync_on_startup(ps: PersistentState) -> None:
    """One-shot sync between persisted state and real exchange position."""
    if not config.POSITION_SYNC_ON_START:
        logging.info("position_sync: disabled (POSITION_SYNC_ON_START=False)")
        return
    if config.BACKTEST_MODE:
        return

    from data.rest_client import _request

    try:
        positions = await _request(
            "GET",
            "/fapi/v2/positionRisk",
            {"symbol": config.SYMBOL},
            signed=True,
            weight=5,
        )
    except Exception as e:
        logging.warning("position_sync: positionRisk failed: %s", e)
        return

    if not positions or not isinstance(positions, list):
        logging.warning("position_sync: empty positionRisk response")
        return

    real_pos = next((p for p in positions if p.get("symbol") == config.SYMBOL), None)
    real_qty = float(real_pos.get("positionAmt", 0)) if real_pos else 0.0
    real_entry = float(real_pos.get("entryPrice", 0)) if real_pos else 0.0
    state_has_pos = ps.position is not None

    # Case 1: state has position, exchange has none -> clear stale state.
    if state_has_pos and abs(real_qty) < 0.0001:
        logging.warning(
            "position_sync mismatch: state has %s @ %.2f, exchange has no position",
            ps.position.direction,
            ps.position.entry_price,
        )
        ps.position = None
        import state as _state

        _state.save(ps)
        return

    # Case 2: exchange has position, state has none -> restore minimal position.
    if (not state_has_pos) and abs(real_qty) > 0.0001:
        direction = "LONG" if real_qty > 0 else "SHORT"
        logging.warning(
            "position_sync mismatch: exchange has %s qty=%.4f @ %.2f, state is empty",
            direction,
            abs(real_qty),
            real_entry,
        )

        atr_estimate = real_entry * 0.005
        stop_dist = atr_estimate * 1.5
        if direction == "LONG":
            stop = exchange_info.round_price(real_entry - stop_dist)
            tp1 = exchange_info.round_price(real_entry + stop_dist * 2.0)
            tp2 = exchange_info.round_price(real_entry + stop_dist * 3.5)
            tp3 = exchange_info.round_price(real_entry + stop_dist * 6.0)
        else:
            stop = exchange_info.round_price(real_entry + stop_dist)
            tp1 = exchange_info.round_price(real_entry - stop_dist * 2.0)
            tp2 = exchange_info.round_price(real_entry - stop_dist * 3.5)
            tp3 = exchange_info.round_price(real_entry - stop_dist * 6.0)

        qty = abs(real_qty)
        qty_tp1 = exchange_info.round_qty(qty * 0.40)
        qty_tp2 = exchange_info.round_qty(qty * 0.35)
        qty_tp3 = exchange_info.round_qty(max(0.0, qty - qty_tp1 - qty_tp2))
        if qty_tp3 <= 0:
            qty_tp2 = exchange_info.round_qty(max(0.0, qty - qty_tp1))
            qty_tp3 = exchange_info.round_qty(max(0.0, qty - qty_tp1 - qty_tp2))

        ps.position = Position(
            direction=direction,
            entry_price=real_entry,
            avg_fill_price=real_entry,
            qty_btc=qty,
            qty_remaining=qty,
            stop_price=stop,
            tp1_price=tp1,
            tp2_price=tp2,
            tp3_price=tp3,
            stop_order_id=0,
            tp1_order_id=0,
            tp2_order_id=0,
            tp3_order_id=0,
            qty_tp1=qty_tp1,
            qty_tp2=qty_tp2,
            qty_tp3=qty_tp3,
            open_timestamp_ms=int(time.time() * 1000),
            mode="live",
            leverage_used=config.LEVERAGE,
        )
        import state as _state

        _state.save(ps)
        await _restore_orders(ps)
        await _ensure_protective_stop(ps)
        return

    # Case 3: both have position -> check qty consistency and stop protection.
    if state_has_pos and abs(real_qty) > 0.0001:
        state_qty = ps.position.qty_remaining
        qty_diff = abs(state_qty - abs(real_qty))
        qty_diff_pct = (qty_diff / max(abs(real_qty), 1e-9)) * 100.0
        if qty_diff_pct > 1.0:
            logging.warning(
                "position_sync qty mismatch: state=%.4f exchange=%.4f diff=%.2f%%",
                state_qty,
                abs(real_qty),
                qty_diff_pct,
            )
            ps.position.qty_remaining = abs(real_qty)
            import state as _state

            _state.save(ps)
        else:
            logging.info("position_sync: OK %s qty=%.4f", ps.position.direction, state_qty)

        await _ensure_protective_stop(ps)


async def _restore_orders(ps: PersistentState) -> None:
    """Load existing exchange protective orders into state fields."""
    from data.rest_client import _request

    try:
        open_orders = await _request(
            "GET",
            "/fapi/v1/openOrders",
            {"symbol": config.SYMBOL},
            signed=True,
            weight=1,
        )
    except Exception as e:
        logging.warning("position_sync._restore_orders: %s", e)
        return

    if not open_orders or not isinstance(open_orders, list) or not ps.position:
        return

    for o in open_orders:
        otype = o.get("type", "")
        oid = int(o.get("orderId", 0))
        stop_p = float(o.get("stopPrice", 0))
        if otype == "STOP_MARKET":
            ps.position.stop_order_id = oid
            ps.position.stop_price = stop_p
            logging.info("position_sync: restored STOP order %s @ %.2f", oid, stop_p)
        elif otype == "TAKE_PROFIT_MARKET":
            if ps.position.tp1_order_id == 0:
                ps.position.tp1_order_id = oid
                ps.position.tp1_price = stop_p
            elif ps.position.tp2_order_id == 0:
                ps.position.tp2_order_id = oid
                ps.position.tp2_price = stop_p

    import state as _state

    _state.save(ps)


async def _ensure_protective_stop(ps: PersistentState) -> None:
    """
    If position exists but no STOP order is tracked, place one reduce-only STOP_MARKET.
    """
    pos = ps.position
    if not pos:
        return
    if pos.stop_order_id > 0:
        return
    if pos.qty_remaining <= 0 or pos.stop_price <= 0:
        return

    from data.rest_client import _request

    side = "SELL" if pos.direction == "LONG" else "BUY"
    qty = exchange_info.round_qty(pos.qty_remaining)
    stop_price = exchange_info.round_price(pos.stop_price)
    if qty <= 0 or stop_price <= 0:
        return

    r = await _request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": config.SYMBOL,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": stop_price,
            "quantity": qty,
            "reduceOnly": "true",
            "timeInForce": "GTE_GTC",
        },
        signed=True,
    )
    if r and not r.get("_ignored") and r.get("orderId"):
        pos.stop_order_id = int(r["orderId"])
        logging.warning(
            "position_sync: created protective STOP order %s @ %.2f",
            pos.stop_order_id,
            stop_price,
        )
        import state as _state

        _state.save(ps)
