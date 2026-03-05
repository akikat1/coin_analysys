"""
Бэктестер v12.
Изменения vs v11:
- Добавлен параметр start_offset_days: int = 0 в run() и _fetch_klines().
  end_ts = now - start_offset_days * 86400_000.
  Используется walk_forward для тестирования разных исторических окон.
"""
import asyncio, logging, dataclasses
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
import numpy as np

@dataclass
class BacktestResult:
    total_trades: int=0; wins: int=0; losses: int=0
    total_net_pnl: float=0.0; max_drawdown_pct: float=0.0
    win_rate: float=0.0; avg_win: float=0.0; avg_loss: float=0.0
    profit_factor: float=0.0; sharpe_ratio: float=0.0
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)

async def run(days: int=30, start_offset_days: int=0) -> BacktestResult:
    """
    Запустить бэктест.
    start_offset_days: сколько дней назад от сейчас заканчивается окно.
    Например start_offset_days=30 → тестируем данные от -60d до -30d.
    """
    import config
    config.BACKTEST_MODE = True
    from data.rest_client import _request, get_session, close as close_session, sync_server_time
    from data.indicators import calculate
    from strategy.signal_engine import evaluate_signal
    from strategy.fee_calculator import calculate_net_pnl
    from state import PersistentState, RuntimeState
    from execution import exchange_info
    from models import MicrostructureData
    import time

    await sync_server_time()

    sess = await get_session()
    candles_15m = await _fetch_klines("15m", days, sess, start_offset_days)
    candles_5m  = await _fetch_klines("5m",  days, sess, start_offset_days)
    candles_1m  = await _fetch_klines("1m",  days, sess, start_offset_days)
    candles_1h  = await _fetch_klines("1h",  days, sess, start_offset_days)
    await close_session()

    if not candles_15m:
        logging.error("Бэктест: не удалось загрузить свечи 15m. Проверь интернет и TESTNET.")
        return BacktestResult()

    logging.info(
        f"Загружено свечей: 1h={len(candles_1h)}, 15m={len(candles_15m)}, "
        f"5m={len(candles_5m)}, 1m={len(candles_1m)}"
    )

    cache_path = Path("data") / "cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([dataclasses.asdict(c) for c in candles_15m]).to_parquet(
        cache_path / f"btcusdt_15m_{days}d_off{start_offset_days}d.parquet")

    ps = PersistentState(available_balance=10000.0, equity_peak=10000.0)
    rs = RuntimeState()
    exchange_info.tick_size = 0.1; exchange_info.step_size = 0.001
    exchange_info.min_notional = 5.0; exchange_info._tick_prec = 1; exchange_info._step_prec = 3

    result = BacktestResult()
    equity_curve: list[float] = [ps.available_balance]
    pnl_list: list[float] = []
    closed_trades: list[dict] = []

    w1h: deque = deque(maxlen=200)
    w15: deque = deque(maxlen=500)
    w5:  deque = deque(maxlen=500)
    w1:  deque = deque(maxlen=500)

    candles_1h_idx = 0; candles_5m_idx = 0; candles_1m_idx = 0
    total = len(candles_15m)

    for i, c15 in enumerate(candles_15m):
        if i % 100 == 0:  # прогресс ВНУТРИ цикла (исправлено в v11)
            logging.info(f"Бэктест: {i}/{total} свечей 15m обработано")
        w15.append(c15)
        while candles_1h_idx < len(candles_1h) and candles_1h[candles_1h_idx].close_time <= c15.close_time:
            w1h.append(candles_1h[candles_1h_idx]); candles_1h_idx += 1
        while candles_5m_idx < len(candles_5m) and candles_5m[candles_5m_idx].close_time <= c15.close_time:
            w5.append(candles_5m[candles_5m_idx]); candles_5m_idx += 1
        while candles_1m_idx < len(candles_1m) and candles_1m[candles_1m_idx].close_time <= c15.close_time:
            w1.append(candles_1m[candles_1m_idx]); candles_1m_idx += 1

        if len(w15) < 50: continue

        if len(w1h) >= config.HTF_MIN_CANDLES:
            rs.indicators["1h"] = calculate(w1h, "1h")
        rs.indicators["15m"] = calculate(w15, "15m")
        if len(w5) >= 50:  rs.indicators["5m"]  = calculate(w5,  "5m")
        if len(w1) >= 50:  rs.indicators["1m"]  = calculate(w1,  "1m")

        from data.market_context import _build_regime
        rs.context = _build_regime(rs.indicators.get("15m"), 0.0)
        rs.micro.mark_price  = c15.close
        rs.micro.best_bid    = c15.close * 0.9998
        rs.micro.best_ask    = c15.close * 1.0002
        rs.micro.spread_pct  = 0.0004
        rs.micro.last_updated_ms = c15.close_time

        if ps.position:
            pos = ps.position; mark = c15.close
            if pos.direction == "LONG":
                if mark <= pos.stop_price:
                    _close_bt(ps, rs, "STOP", pos.stop_price, pnl_list, equity_curve, result, closed_trades)
                elif not pos.tp1_filled and mark >= pos.tp1_price:
                    _tp_bt(ps, 1, pos.tp1_price, pnl_list, result)
                elif pos.tp1_filled and not pos.tp2_filled and mark >= pos.tp2_price:
                    _tp_bt(ps, 2, pos.tp2_price, pnl_list, result)
                elif pos.tp1_filled and pos.tp2_filled and mark >= pos.tp3_price:
                    _close_bt(ps, rs, "TP3", pos.tp3_price, pnl_list, equity_curve, result, closed_trades)
            else:
                if mark >= pos.stop_price:
                    _close_bt(ps, rs, "STOP", pos.stop_price, pnl_list, equity_curve, result, closed_trades)
                elif not pos.tp1_filled and mark <= pos.tp1_price:
                    _tp_bt(ps, 1, pos.tp1_price, pnl_list, result)
                elif pos.tp1_filled and not pos.tp2_filled and mark <= pos.tp2_price:
                    _tp_bt(ps, 2, pos.tp2_price, pnl_list, result)
                elif pos.tp1_filled and pos.tp2_filled and mark <= pos.tp3_price:
                    _close_bt(ps, rs, "TP3", pos.tp3_price, pnl_list, equity_curve, result, closed_trades)

        if not ps.position:
            sig = await evaluate_signal(ps, rs)
            if sig:
                from models import Position
                import time as _t
                ps.position = Position(
                    direction=sig.direction, entry_price=sig.levels.entry,
                    avg_fill_price=sig.levels.entry, qty_btc=sig.levels.qty_btc,
                    qty_remaining=sig.levels.qty_btc, stop_price=sig.levels.stop,
                    tp1_price=sig.levels.tp1, tp2_price=sig.levels.tp2, tp3_price=sig.levels.tp3,
                    stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
                    qty_tp1=sig.levels.qty_tp1, qty_tp2=sig.levels.qty_tp2, qty_tp3=sig.levels.qty_tp3,
                    confidence_at_entry=sig.confidence, adx_at_entry=0.0,
                    regime_at_entry=rs.context.regime, funding_rate_at_entry=0.0,
                    open_timestamp_ms=c15.close_time, mode="paper",
                    leverage_used=config.LEVERAGE)

    pnl = pnl_list
    result.equity_curve = equity_curve
    result.trades = closed_trades
    if not pnl: return result
    result.total_trades = len(pnl)
    wins  = [x for x in pnl if x>0]; losses = [x for x in pnl if x<=0]
    result.wins=len(wins); result.losses=len(losses)
    result.total_net_pnl = sum(pnl)
    result.win_rate = len(wins)/len(pnl) if pnl else 0
    result.avg_win  = sum(wins)/len(wins)   if wins   else 0
    result.avg_loss = sum(losses)/len(losses) if losses else 0
    gross_p = sum(wins); gross_l = abs(sum(losses))
    result.profit_factor = gross_p/gross_l if gross_l>0 else float("inf")
    equity = np.array(equity_curve)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak; result.max_drawdown_pct = float(dd.max())
        rets = np.diff(equity) / equity[:-1]
        result.sharpe_ratio = float(rets.mean()/rets.std()*np.sqrt(252)) if rets.std() > 0 else 0
    result.equity_curve = equity_curve
    result.trades = closed_trades
    return result

def _tp_bt(ps, tp_num: int, price: float, pnl_list: list, result) -> None:
    """Частичное закрытие в бэктесте: TP1 или TP2 без изменения total_trades."""
    import config
    from strategy.fee_calculator import calculate_net_pnl
    pos = ps.position
    if not pos: return
    qty = pos.qty_tp1 if tp_num == 1 else pos.qty_tp2
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = calculate_net_pnl(pos.direction, pos.avg_fill_price, price, qty, lev)
    pos.realized_pnl_usd += pnl.net_pnl
    pos.qty_remaining -= qty
    if tp_num == 1:
        pos.tp1_filled = True
        # ← ПРАВИЛО 24 (v12): перенос стопа на безубыток после TP1 в бэктесте тоже
        pos.stop_price = pos.avg_fill_price
    elif tp_num == 2:
        pos.tp2_filled = True

def _close_bt(ps, rs, reason: str, price: float, pnl_list: list, equity_curve: list, result,
              closed_trades: list[dict]) -> None:
    import config
    from strategy.fee_calculator import calculate_net_pnl
    pos = ps.position
    if not pos: return
    lev = pos.leverage_used if pos.leverage_used > 0 else config.LEVERAGE
    pnl = calculate_net_pnl(pos.direction, pos.avg_fill_price, price, pos.qty_remaining, lev)
    total_net = pos.realized_pnl_usd + pnl.net_pnl
    ps.daily_pnl_usd += total_net
    if ps.available_balance > 0: ps.daily_pnl_pct = ps.daily_pnl_usd / ps.available_balance
    ps.available_balance += total_net; ps.trades_today += 1
    if total_net > 0:
        ps.wins_today += 1; ps.consecutive_losses = 0; ps.reduced_size_active = False
    else:
        ps.losses_today += 1; ps.consecutive_losses += 1
    if ps.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        ps.reduced_size_active = True; ps.pause_until = float("inf")
    if ps.available_balance > ps.equity_peak: ps.equity_peak = ps.available_balance
    if ps.equity_peak > 0:
        ps.equity_drawdown_pct = (ps.equity_peak - ps.available_balance) / ps.equity_peak
    pnl_list.append(total_net)
    equity_curve.append(ps.available_balance)
    duration_sec = 0
    if rs.micro.last_updated_ms and pos.open_timestamp_ms:
        duration_sec = max(0, int((rs.micro.last_updated_ms - pos.open_timestamp_ms) / 1000))
    closed_trades.append({
        "direction": pos.direction,
        "entry": pos.entry_price,
        "exit": price,
        "reason": reason,
        "pnl": total_net,
        "duration": f"{duration_sec//60}m{duration_sec%60}s",
        "confidence": f"{pos.confidence_at_entry:.1f}",
    })
    ps.position = None

async def _fetch_klines(tf: str, days: int, session, start_offset_days: int = 0) -> list:
    """
    Загрузить свечи через REST с пагинацией.
    start_offset_days: окно заканчивается (now - start_offset_days) дней назад.
    Например: days=30, start_offset_days=30 → загружает данные 60d..30d назад.
    """
    import config, time
    from models import Candle
    import aiohttp

    interval_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}[tf]
    now_ms   = int(time.time() * 1000)
    end_ts   = now_ms - start_offset_days * 86_400_000  # ← НОВЫЙ v12: сдвиг окна
    start_ts = end_ts - days * 86_400_000
    url      = f"{config.REST_BASE}/fapi/v1/klines"
    all_candles: list = []
    current_start = start_ts

    timeout = aiohttp.ClientTimeout(total=30)

    while current_start < end_ts:
        try:
            async with session.get(url, params={
                "symbol": "BTCUSDT", "interval": tf,
                "startTime": current_start,
                "endTime": end_ts,   # ← НОВЫЙ v12: ограничение по верхней границе
                "limit": 1500
            }, timeout=timeout) as r:
                if r.status != 200:
                    logging.warning(f"_fetch_klines {tf}: HTTP {r.status}")
                    break
                data = await r.json()
        except Exception as e:
            logging.warning(f"_fetch_klines {tf}: {e}")
            break

        if not data:
            break

        batch = [Candle(open_time=int(k[0]), open=float(k[1]), high=float(k[2]),
                        low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                        close_time=int(k[6]), is_closed=True) for k in data]
        all_candles.extend(batch)
        current_start = int(data[-1][0]) + interval_ms

        if len(data) < 1500:
            break

        await asyncio.sleep(0.1)

    logging.info(f"Загружено {len(all_candles)} свечей {tf} за {days}д (offset={start_offset_days}д)")
    return all_candles

