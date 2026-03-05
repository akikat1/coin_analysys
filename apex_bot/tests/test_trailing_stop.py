import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
config.TRAILING_STOP_ENABLED = True
config.TRAILING_ATR_MULTIPLIER = 1.2
config.PAPER_MODE = True  # чтобы не делать реальных запросов к бирже
config.LEVERAGE = 10
config.TAKER_FEE = 0.0004; config.MAKER_FEE = 0.0002
config.SLIPPAGE_ESTIMATE = 0.0002; config.BNB_DISCOUNT = False

from execution import exchange_info
exchange_info.tick_size=0.1; exchange_info.step_size=0.001
exchange_info.min_notional=5.0; exchange_info._tick_prec=1; exchange_info._step_prec=3

def _make_pos_with_tp1(direction="LONG", entry=50000.0, stop=49000.0):
    from models import Position
    import time
    return Position(
        direction=direction, entry_price=entry, avg_fill_price=entry,
        qty_btc=0.01, qty_remaining=0.006,  # после TP1
        stop_price=entry,  # стоп уже на безубытке (после TP1)
        tp1_price=51000, tp2_price=52500, tp3_price=55000,
        stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=0.004, qty_tp2=0.0035, qty_tp3=0.0025,
        tp1_filled=True,
        open_timestamp_ms=int(time.time()*1000), mode="paper")

@pytest.mark.asyncio
async def test_trailing_stop_moves_up_for_long():
    """LONG: при росте цены стоп должен двигаться вверх."""
    from state import PersistentState, RuntimeState
    from models import Indicators
    from execution.position_tracker import update_trailing_stop

    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_pos_with_tp1("LONG", stop=50000.0)
    initial_stop = ps.position.stop_price

    rs = RuntimeState()
    rs.indicators["15m"] = Indicators(atr=500.0)
    rs.micro.mark_price = 52000.0  # цена выросла

    await update_trailing_stop(ps, rs)

    expected_new_stop = exchange_info.round_price(52000.0 - 500.0 * 1.2)  # = 51400
    assert ps.position.stop_price > initial_stop
    assert ps.position.stop_price == pytest.approx(expected_new_stop, abs=0.2)
    assert ps.position.trailing_stop_active is True

@pytest.mark.asyncio
async def test_trailing_stop_does_not_move_down_for_long():
    """LONG: если цена упала ниже текущего стопа — стоп НЕ двигается вниз."""
    from state import PersistentState, RuntimeState
    from models import Indicators
    from execution.position_tracker import update_trailing_stop

    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_pos_with_tp1("LONG", stop=50000.0)
    ps.position.stop_price = 51000.0  # стоп уже поднят

    rs = RuntimeState()
    rs.indicators["15m"] = Indicators(atr=500.0)
    rs.micro.mark_price = 50500.0  # цена откатилась

    await update_trailing_stop(ps, rs)
    # new_stop = 50500 - 600 = 49900 < 51000 → НЕ обновляем
    assert ps.position.stop_price == pytest.approx(51000.0, abs=0.2)

@pytest.mark.asyncio
async def test_trailing_stop_not_active_before_tp1():
    """До TP1 trailing stop не должен активироваться."""
    from state import PersistentState, RuntimeState
    from models import Indicators, Position
    from execution.position_tracker import update_trailing_stop
    import time

    ps = PersistentState(available_balance=1000.0)
    ps.position = Position(
        direction="LONG", entry_price=50000, avg_fill_price=50000,
        qty_btc=0.01, qty_remaining=0.01, stop_price=49000,
        tp1_price=51000, tp2_price=52500, tp3_price=55000,
        stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=0.004, qty_tp2=0.0035, qty_tp3=0.0025,
        tp1_filled=False,  # TP1 НЕ выполнен
        open_timestamp_ms=int(time.time()*1000), mode="paper")

    rs = RuntimeState()
    rs.indicators["15m"] = Indicators(atr=500.0)
    rs.micro.mark_price = 55000.0  # цена сильно выросла

    original_stop = ps.position.stop_price
    await update_trailing_stop(ps, rs)
    assert ps.position.stop_price == original_stop  # стоп не изменился

