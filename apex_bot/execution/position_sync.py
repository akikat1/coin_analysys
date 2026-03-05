"""
Синхронизация позиции с биржей при каждом старте live/paper режима.

ПРОБЛЕМА которую решает этот модуль:
  - Бот упал после отправки ордера, но до записи state.json
  - state.json содержит позицию, но биржа её уже закрыла (или наоборот)
  - Без синхронизации бот будет торговать на основе устаревших данных

ЛОГИКА:
  1. Запросить реальные открытые позиции с биржи (GET /fapi/v2/positionRisk)
  2. Запросить открытые ордера (GET /fapi/v1/openOrders)
  3. Сравнить с state.json
  4. Если расхождение → исправить state.json
  5. Залогировать все несоответствия

Работает только в live режиме (в paper/backtest нет реальных ордеров на бирже).
"""
import logging
import config
from execution import exchange_info
from models import Position
from state import PersistentState

async def sync_on_startup(ps: PersistentState) -> None:
    """
    Вызывается один раз при старте live-режима.
    Сверяет ps.position с реальной позицией на бирже.
    """
    if not config.POSITION_SYNC_ON_START:
        logging.info("position_sync: отключено (POSITION_SYNC_ON_START=False)")
        return
    if config.BACKTEST_MODE:
        return

    from data.rest_client import _request
    try:
        positions = await _request("GET", "/fapi/v2/positionRisk",
                                   {"symbol": config.SYMBOL}, signed=True, weight=5)
    except Exception as e:
        logging.warning(f"position_sync: не удалось получить positionRisk: {e}")
        return

    if not positions or not isinstance(positions, list):
        logging.warning("position_sync: пустой ответ от positionRisk")
        return

    real_pos = next((p for p in positions if p.get("symbol") == config.SYMBOL), None)
    real_qty  = float(real_pos.get("positionAmt", 0)) if real_pos else 0.0
    real_entry = float(real_pos.get("entryPrice", 0)) if real_pos else 0.0

    state_has_pos = ps.position is not None

    # КЕЙС 1: state говорит "есть позиция", биржа говорит "нет"
    if state_has_pos and abs(real_qty) < 0.0001:
        logging.warning(
            f"position_sync: РАСХОЖДЕНИЕ! "
            f"state.json содержит позицию {ps.position.direction} @ {ps.position.entry_price:.2f}, "
            f"но биржа показывает qty={real_qty:.4f} (позиции нет). "
            f"Сбрасываем ps.position = None."
        )
        ps.position = None
        import state as _state; _state.save(ps)
        return

    # КЕЙС 2: state говорит "нет позиции", биржа говорит "есть"
    if not state_has_pos and abs(real_qty) > 0.0001:
        direction = "LONG" if real_qty > 0 else "SHORT"
        logging.warning(
            f"position_sync: РАСХОЖДЕНИЕ! "
            f"state.json пустой, но биржа показывает {direction} qty={real_qty:.4f} "
            f"@ {real_entry:.2f}. Восстанавливаем позицию из данных биржи."
        )
        # Восстановить позицию с минимальными данными
        atr_estimate = real_entry * 0.005  # ~0.5% как безопасная оценка
        stop_dist    = atr_estimate * 1.5
        if direction == "LONG":
            stop  = exchange_info.round_price(real_entry - stop_dist)
            tp1   = exchange_info.round_price(real_entry + stop_dist * 2.0)
            tp2   = exchange_info.round_price(real_entry + stop_dist * 3.5)
            tp3   = exchange_info.round_price(real_entry + stop_dist * 6.0)
        else:
            stop  = exchange_info.round_price(real_entry + stop_dist)
            tp1   = exchange_info.round_price(real_entry - stop_dist * 2.0)
            tp2   = exchange_info.round_price(real_entry - stop_dist * 3.5)
            tp3   = exchange_info.round_price(real_entry - stop_dist * 6.0)
        qty     = abs(real_qty)
        qt1 = exchange_info.round_qty(qty * 0.40)
        qt2 = exchange_info.round_qty(qty * 0.35)
        qt3 = exchange_info.round_qty(qty - qt1 - qt2)
        import time
        ps.position = Position(
            direction=direction, entry_price=real_entry, avg_fill_price=real_entry,
            qty_btc=qty, qty_remaining=qty, stop_price=stop,
            tp1_price=tp1, tp2_price=tp2, tp3_price=tp3,
            stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
            qty_tp1=qt1, qty_tp2=qt2, qty_tp3=qt3,
            open_timestamp_ms=int(time.time()*1000), mode="live",
            leverage_used=config.LEVERAGE
        )
        import state as _state; _state.save(ps)
        # Попробовать найти open orders для этой позиции
        await _restore_orders(ps)
        return

    # КЕЙС 3: обе стороны согласны
    if state_has_pos and abs(real_qty) > 0.0001:
        state_qty = ps.position.qty_remaining
        if abs(state_qty - abs(real_qty)) > exchange_info.step_size * 2:
            logging.warning(
                f"position_sync: несоответствие qty! "
                f"state={state_qty:.4f}, биржа={abs(real_qty):.4f}. "
                f"Обновляем qty_remaining."
            )
            ps.position.qty_remaining = abs(real_qty)
            import state as _state; _state.save(ps)
        else:
            logging.info(f"position_sync: OK — {ps.position.direction} qty={state_qty:.4f}")

async def _restore_orders(ps: PersistentState) -> None:
    """После восстановления позиции попробовать найти TP/Stop ордера на бирже."""
    from data.rest_client import _request
    try:
        open_orders = await _request("GET", "/fapi/v1/openOrders",
                                     {"symbol": config.SYMBOL}, signed=True, weight=1)
    except Exception as e:
        logging.warning(f"position_sync._restore_orders: {e}")
        return
    if not open_orders or not isinstance(open_orders, list) or not ps.position:
        return
    for o in open_orders:
        otype = o.get("type",""); oid = int(o.get("orderId",0))
        stop_p = float(o.get("stopPrice",0))
        if otype == "STOP_MARKET":
            ps.position.stop_order_id = oid
            ps.position.stop_price    = stop_p
            logging.info(f"position_sync: восстановлен STOP ордер {oid} @ {stop_p:.2f}")
        elif otype == "TAKE_PROFIT_MARKET":
            if ps.position.tp1_order_id == 0:
                ps.position.tp1_order_id = oid
                ps.position.tp1_price    = stop_p
                logging.info(f"position_sync: восстановлен TP1 ордер {oid} @ {stop_p:.2f}")
            elif ps.position.tp2_order_id == 0:
                ps.position.tp2_order_id = oid
                ps.position.tp2_price    = stop_p
                logging.info(f"position_sync: восстановлен TP2 ордер {oid} @ {stop_p:.2f}")
    import state as _state; _state.save(ps)

