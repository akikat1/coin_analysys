"""
Размещение ордеров на Binance Futures (live-режим).
Использует MARKET для входа, STOP_MARKET и TAKE_PROFIT_MARKET для стопа и TP.
"""
import asyncio, logging, time
import config
from models import Signal, Position, TradeLevel
from state import PersistentState, RuntimeState
from execution import exchange_info
from strategy import fee_calculator
from data import rest_client

async def enter_trade(sig: Signal, ps: PersistentState, rs: RuntimeState) -> Position|None:
    """Открыть позицию (LIMIT+fallback или MARKET). Возвращает Position или None."""
    lvl: TradeLevel = sig.levels
    side = "BUY" if sig.direction == "LONG" else "SELL"
    stop_side = "SELL" if sig.direction == "LONG" else "BUY"
    target_leverage = max(
        config.MIN_LEVERAGE,
        min(config.MAX_LEVERAGE, int(getattr(lvl, "leverage", config.LEVERAGE))),
    )
    from execution import exchange_setup
    if not await exchange_setup.set_leverage(target_leverage, config.SYMBOL):
        logging.warning("enter_trade: failed to set leverage=%s, skip entry", target_leverage)
        return None

    entry_info = await _execute_entry(sig.direction, lvl)
    if not entry_info:
        return None
    avg_fill = entry_info["avg_fill"]
    filled_qty = entry_info["filled_qty"]
    entry_order_id = entry_info["entry_order_id"]
    is_limit_entry = entry_info["is_limit_entry"]
    if filled_qty < lvl.qty_btc * config.PARTIAL_FILL_MIN_PCT:
        logging.warning(f"enter_trade: частичное заполнение {filled_qty:.4f}/{lvl.qty_btc:.4f}")
        return None

    # 2. Стоп-лосс
    stop_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": stop_side, "type": "STOP_MARKET",
        "stopPrice": exchange_info.round_price(lvl.stop),
        "quantity": exchange_info.round_qty(filled_qty),
        "reduceOnly": "true", "timeInForce": "GTE_GTC"
    })
    stop_id = int(stop_r.get("orderId", 0)) if stop_r and not stop_r.get("_ignored") else 0

    # 3. TP1
    tp1_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": stop_side, "type": "TAKE_PROFIT_MARKET",
        "stopPrice": exchange_info.round_price(lvl.tp1),
        "quantity": exchange_info.round_qty(lvl.qty_tp1),
        "reduceOnly": "true", "timeInForce": "GTE_GTC"
    })
    tp1_id = int(tp1_r.get("orderId", 0)) if tp1_r and not tp1_r.get("_ignored") else 0

    from monitor import logger as trade_logger
    ind15 = rs.indicators.get("15m")
    pos = Position(
        direction=sig.direction, entry_price=lvl.entry, avg_fill_price=avg_fill,
        qty_btc=filled_qty, qty_remaining=filled_qty,
        stop_price=lvl.stop, tp1_price=lvl.tp1, tp2_price=lvl.tp2, tp3_price=lvl.tp3,
        stop_order_id=stop_id, tp1_order_id=tp1_id, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=lvl.qty_tp1, qty_tp2=lvl.qty_tp2, qty_tp3=lvl.qty_tp3,
        confidence_at_entry=sig.confidence,
        adx_at_entry=ind15.adx if ind15 and ind15.adx else 0.0,
        regime_at_entry=rs.context.regime,
        funding_rate_at_entry=rs.micro.funding_rate,
        open_timestamp_ms=int(time.time()*1000), mode="live",
        entry_order_id=entry_order_id, is_limit_entry=is_limit_entry,
        leverage_used=target_leverage
    )
    trade_logger.log_signal(sig.direction, sig.confidence, sig.score_15m, sig.score_5m,
                            sig.score_1m, True, "", lvl.rr,
                            pos.adx_at_entry, rs.context.regime, rs.micro.spread_pct,
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
        f"LIVE ENTRY {sig.direction} @ {avg_fill:.2f} qty={filled_qty:.4f} "
        f"base_score={score_base:.1f} final_score={score_final:.1f} "
        f"(AI{score_ai_delta:+.1f}) RR={lvl.rr:.2f}"
    )
    return pos

async def cancel_order(order_id: int) -> None:
    if order_id <= 0: return
    await rest_client._request("DELETE", "/fapi/v1/order",
                               {"symbol": config.SYMBOL, "orderId": order_id})

async def _execute_entry(direction: str, lvl: TradeLevel) -> dict | None:
    side = "BUY" if direction == "LONG" else "SELL"
    qty = exchange_info.round_qty(lvl.qty_btc)
    if qty <= 0:
        logging.warning("enter_trade: qty после round = 0")
        return None

    if not config.USE_LIMIT_ORDER:
        m = await rest_client._request("POST", "/fapi/v1/order", {
            "symbol": config.SYMBOL, "side": side, "type": "MARKET",
            "quantity": qty, "newOrderRespType": "RESULT"
        })
        if not m or "orderId" not in m:
            logging.warning("enter_trade: рыночный ордер не прошёл")
            return None
        return {
            "avg_fill": float(m.get("avgPrice", lvl.entry) or lvl.entry),
            "filled_qty": float(m.get("executedQty", qty) or qty),
            "entry_order_id": int(m.get("orderId", 0)),
            "is_limit_entry": False,
        }

    offset = max(config.LIMIT_ORDER_OFFSET_PCT, 0.0)
    raw_limit = lvl.entry * (1 - offset if direction == "LONG" else 1 + offset)
    limit_price = exchange_info.round_price(raw_limit)
    logging.info(
        "LIMIT entry: side=%s qty=%.6f price=%.2f timeout=%ss",
        side, qty, limit_price, config.LIMIT_ORDER_TIMEOUT_SEC
    )
    limit_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTX",
        "price": limit_price,
        "quantity": qty,
        "newOrderRespType": "RESULT",
    })
    if not limit_r:
        logging.warning("LIMIT entry: запрос неуспешен, fallback на MARKET")
        return await _execute_entry_market_fallback(side, qty, lvl.entry)
    if limit_r.get("_gtx_rejected"):
        logging.info("LIMIT entry: GTX отклонён биржей, fallback на MARKET")
        return await _execute_entry_market_fallback(side, qty, lvl.entry)
    limit_oid = int(limit_r.get("orderId", 0))
    if limit_oid <= 0:
        logging.warning("LIMIT entry: orderId отсутствует, fallback на MARKET")
        return await _execute_entry_market_fallback(side, qty, lvl.entry)

    filled_qty = 0.0
    fill_cost = 0.0
    status = ""
    timeout_at = time.time() + max(1, int(config.LIMIT_ORDER_TIMEOUT_SEC))
    while time.time() < timeout_at:
        o = await rest_client._request(
            "GET", "/fapi/v1/order", {"symbol": config.SYMBOL, "orderId": limit_oid}
        )
        if o:
            status = o.get("status", "")
            executed = float(o.get("executedQty", 0) or 0)
            avg = float(o.get("avgPrice", 0) or 0)
            filled_qty = executed
            if executed > 0 and avg > 0:
                fill_cost = executed * avg
            if status == "FILLED":
                break
        await asyncio.sleep(1.0)

    if status != "FILLED":
        logging.info("Лимитный ордер истёк, переключаюсь на рыночный")
        await cancel_order(limit_oid)
        remaining = exchange_info.round_qty(max(0.0, qty - filled_qty))
        if remaining > 0:
            m = await rest_client._request("POST", "/fapi/v1/order", {
                "symbol": config.SYMBOL, "side": side, "type": "MARKET",
                "quantity": remaining, "newOrderRespType": "RESULT"
            })
            if not m or "orderId" not in m:
                logging.warning("LIMIT fallback: MARKET для остатка не прошёл")
                return None
            m_qty = float(m.get("executedQty", remaining) or remaining)
            m_avg = float(m.get("avgPrice", lvl.entry) or lvl.entry)
            filled_qty += m_qty
            fill_cost += m_qty * m_avg
    else:
        logging.info("LIMIT entry: FILLED")

    if filled_qty <= 0:
        logging.warning("LIMIT entry: нулевое исполнение")
        return None
    avg_fill = fill_cost / filled_qty if fill_cost > 0 else lvl.entry
    return {
        "avg_fill": avg_fill,
        "filled_qty": filled_qty,
        "entry_order_id": limit_oid,
        "is_limit_entry": True,
    }

async def _execute_entry_market_fallback(side: str, qty: float, default_price: float) -> dict | None:
    m = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL, "side": side, "type": "MARKET",
        "quantity": qty, "newOrderRespType": "RESULT"
    })
    if not m or "orderId" not in m:
        logging.warning("MARKET fallback: ордер не прошёл")
        return None
    return {
        "avg_fill": float(m.get("avgPrice", default_price) or default_price),
        "filled_qty": float(m.get("executedQty", qty) or qty),
        "entry_order_id": int(m.get("orderId", 0)),
        "is_limit_entry": False,
    }

async def run_smoke_test_trade(ps: PersistentState,
                               max_wait_sec: int|None = None,
                               hold_sec: int|None = None) -> bool:
    """
    Выполнить 1 микросделку в live:
    - открыть MARKET в сторону с лучшим микросигналом;
    - удерживать позицию hold_sec;
    - закрыть MARKET reduceOnly вне зависимости от результата.
    """
    if config.BACKTEST_MODE or config.PAPER_MODE:
        logging.warning("smoke_test: пропуск (режим не live)")
        return False
    if ps.position is not None:
        logging.warning("smoke_test: есть открытая позиция, пропускаю тест")
        return False

    wait_s = max_wait_sec if max_wait_sec is not None else config.LIVE_SMOKE_MAX_WAIT_SEC
    hold_s = hold_sec if hold_sec is not None else config.LIVE_SMOKE_HOLD_SEC
    wait_s = max(1, int(wait_s))
    hold_s = max(1, int(hold_s))

    deadline = time.time() + wait_s
    snapshot = None
    while time.time() < deadline:
        snapshot = await _fetch_smoke_snapshot()
        if snapshot:
            break
        await asyncio.sleep(1.0)

    if not snapshot:
        logging.error(f"smoke_test: не удалось получить market snapshot за {wait_s}s")
        return False

    direction, score = _choose_smoke_direction(snapshot)
    entry_ref = snapshot["ask"] if direction == "LONG" else snapshot["bid"]
    qty = _calc_smoke_qty(entry_ref)
    if qty <= 0:
        logging.error("smoke_test: не удалось рассчитать qty под minNotional")
        return False

    side = "BUY" if direction == "LONG" else "SELL"
    close_side = "SELL" if direction == "LONG" else "BUY"
    open_ts = int(time.time() * 1000)

    logging.info(
        f"smoke_test: OPEN {direction} score={score:+.4f} "
        f"entry_ref={entry_ref:.2f} qty={qty:.6f}"
    )
    entry_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL,
        "side": side,
        "type": "MARKET",
        "quantity": exchange_info.round_qty(qty),
        "newOrderRespType": "RESULT",
    })
    if not entry_r or "orderId" not in entry_r:
        logging.error("smoke_test: входной MARKET ордер не прошёл")
        return False

    # На Binance может прийти ACK/нулевой executedQty сразу после MARKET.
    # В таком случае подтверждаем фактический объём через positionRisk.
    filled_qty = float(entry_r.get("executedQty", 0) or 0)
    avg_fill = float(entry_r.get("avgPrice", 0) or 0) or entry_ref
    if filled_qty <= 0:
        await asyncio.sleep(1.0)
        live_qty, live_entry = await _get_live_position_snapshot()
        if live_qty > 0:
            filled_qty = live_qty
            if live_entry > 0:
                avg_fill = live_entry
    filled_qty = exchange_info.round_qty(filled_qty)
    if filled_qty <= 0:
        logging.error("smoke_test: входной ордер дал нулевой объём")
        return False

    await asyncio.sleep(hold_s)

    # Перед закрытием берём актуальный объём с биржи, чтобы reduceOnly сработал точно.
    live_qty, _ = await _get_live_position_snapshot()
    if live_qty > 0:
        filled_qty = exchange_info.round_qty(live_qty)
    if filled_qty <= 0:
        logging.warning("smoke_test: к моменту закрытия позиция уже отсутствует")
        return True

    close_r = await rest_client._request("POST", "/fapi/v1/order", {
        "symbol": config.SYMBOL,
        "side": close_side,
        "type": "MARKET",
        "quantity": exchange_info.round_qty(filled_qty),
        "reduceOnly": "true",
        "newOrderRespType": "RESULT",
    })
    if not close_r or "orderId" not in close_r:
        logging.error("smoke_test: выходной MARKET ордер не прошёл, проверь позицию вручную")
        return False

    exit_fill = float(close_r.get("avgPrice", 0) or 0) or snapshot["mark"] or avg_fill
    pnl = fee_calculator.calculate_net_pnl(direction, avg_fill, exit_fill, filled_qty, config.LEVERAGE)
    from monitor import logger as trade_logger
    log_pos = Position(
        direction=direction,
        entry_price=avg_fill,
        avg_fill_price=avg_fill,
        qty_btc=filled_qty,
        qty_remaining=filled_qty,
        stop_price=0.0,
        tp1_price=0.0,
        tp2_price=0.0,
        tp3_price=0.0,
        stop_order_id=0,
        tp1_order_id=0,
        tp2_order_id=0,
        tp3_order_id=0,
        qty_tp1=0.0,
        qty_tp2=0.0,
        qty_tp3=0.0,
        regime_at_entry="SMOKE_TEST",
        open_timestamp_ms=open_ts,
        mode="live",
    )
    trade_logger.log_trade(log_pos, exit_fill, filled_qty, f"SMOKE_EXIT_{hold_s}S", pnl, pnl.net_pnl)
    logging.info(
        f"smoke_test: CLOSED {direction} entry={avg_fill:.2f} exit={exit_fill:.2f} "
        f"qty={filled_qty:.6f} net={pnl.net_pnl:+.4f}$"
    )
    return True

async def _fetch_smoke_snapshot() -> dict|None:
    depth = await rest_client._request(
        "GET", "/fapi/v1/depth", {"symbol": config.SYMBOL, "limit": 20}, signed=False, weight=5
    )
    trades = await rest_client._request(
        "GET", "/fapi/v1/trades", {"symbol": config.SYMBOL, "limit": 50}, signed=False, weight=5
    )
    premium = await rest_client._request(
        "GET", "/fapi/v1/premiumIndex", {"symbol": config.SYMBOL}, signed=False, weight=1
    )
    if not isinstance(depth, dict):
        return None
    bids = depth.get("bids") or []
    asks = depth.get("asks") or []
    if not bids or not asks:
        return None

    bid = float(bids[0][0]); ask = float(asks[0][0])
    if bid <= 0 or ask <= 0:
        return None
    mark = float((premium or {}).get("markPrice", 0) or 0) or (bid + ask) / 2.0

    bid_vol = sum(float(b[1]) for b in bids[:10])
    ask_vol = sum(float(a[1]) for a in asks[:10])
    vol_sum = bid_vol + ask_vol
    obi = ((bid_vol - ask_vol) / vol_sum) if vol_sum > 0 else 0.0

    flow = 0.5
    momentum = 0.0
    if isinstance(trades, list) and len(trades) > 1:
        buy_aggr = sum(1 for t in trades if not bool(t.get("isBuyerMaker", True)))
        flow = buy_aggr / len(trades)
        first = float(trades[0].get("price", 0) or 0)
        last = float(trades[-1].get("price", 0) or 0)
        if first > 0 and last > 0:
            momentum = (last - first) / first

    return {"bid": bid, "ask": ask, "mark": mark, "obi": obi, "flow": flow, "momentum": momentum}

def _choose_smoke_direction(snapshot: dict) -> tuple[str, float]:
    score = snapshot["obi"] * 0.6 + (snapshot["flow"] - 0.5) * 0.8 + snapshot["momentum"] * 10.0
    if abs(score) < 0.02:
        mid = (snapshot["bid"] + snapshot["ask"]) / 2.0
        if mid > 0:
            score += ((snapshot["mark"] - mid) / mid) * 20.0
    return ("LONG", score) if score >= 0 else ("SHORT", score)

def _calc_smoke_qty(entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    target_notional = max(config.LIVE_SMOKE_NOTIONAL_USDT, exchange_info.min_notional * 1.05)
    qty = exchange_info.round_qty(target_notional / entry_price)
    if qty <= 0:
        qty = exchange_info.round_qty(exchange_info.step_size)
    guard = 0
    while qty > 0 and qty * entry_price < exchange_info.min_notional and guard < 10000:
        qty = exchange_info.round_qty(qty + exchange_info.step_size)
        guard += 1
    return qty if qty * entry_price >= exchange_info.min_notional else 0.0

async def _get_live_position_snapshot() -> tuple[float, float]:
    """
    Вернёт (abs_qty, entry_price) текущей позиции по SYMBOL через positionRisk.
    """
    data = await rest_client._request(
        "GET", "/fapi/v2/positionRisk", {"symbol": config.SYMBOL}, signed=True, weight=5
    )
    if not isinstance(data, list):
        return 0.0, 0.0
    row = next((p for p in data if p.get("symbol") == config.SYMBOL), None)
    if not row:
        return 0.0, 0.0
    qty = abs(float(row.get("positionAmt", 0) or 0))
    entry = float(row.get("entryPrice", 0) or 0)
    return qty, entry

