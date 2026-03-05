import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def _make_ps(balance=10000.0):
    from state import PersistentState
    return PersistentState(available_balance=balance, equity_peak=balance)

@pytest.mark.asyncio
async def test_no_signal_stale_micro():
    import config; config.BACKTEST_MODE = False
    from state import RuntimeState
    from strategy.signal_engine import evaluate_signal
    ps=_make_ps(); rs=RuntimeState(); rs.micro.last_updated_ms=0
    result=await evaluate_signal(ps,rs)
    assert result is None
    assert rs.last_rejection_reason == "STALE_MICRO"

@pytest.mark.asyncio
async def test_no_signal_stale_micro_backtest_mode():
    import config; config.BACKTEST_MODE = True
    from state import RuntimeState
    from strategy.signal_engine import evaluate_signal
    ps=_make_ps(); rs=RuntimeState(); rs.micro.last_updated_ms=1000
    try:
        result=await evaluate_signal(ps,rs)
    finally:
        config.BACKTEST_MODE = False

@pytest.mark.asyncio
async def test_no_signal_daily_limit_hit():
    import config, time; config.BACKTEST_MODE = False
    from state import PersistentState, RuntimeState
    from strategy.signal_engine import evaluate_signal
    ps=_make_ps(); ps.daily_pnl_pct=-0.10
    rs=RuntimeState(); rs.micro.last_updated_ms=int(time.time()*1000)
    result=await evaluate_signal(ps,rs)
    assert result is None
    assert rs.last_rejection_reason == "DAILY_LIMIT"

@pytest.mark.asyncio
async def test_no_signal_position_open():
    import config, time; config.BACKTEST_MODE = False
    from state import PersistentState, RuntimeState
    from models import Position
    from strategy.signal_engine import evaluate_signal
    ps=_make_ps()
    ps.position=Position(
        direction="LONG",entry_price=50000,avg_fill_price=50000,
        qty_btc=0.001,qty_remaining=0.001,stop_price=49000,
        tp1_price=51000,tp2_price=52000,tp3_price=54000,
        stop_order_id=1,tp1_order_id=2,tp2_order_id=3,tp3_order_id=4,
        qty_tp1=0.0004,qty_tp2=0.00035,qty_tp3=0.00025)
    rs=RuntimeState(); rs.micro.last_updated_ms=int(time.time()*1000)
    result=await evaluate_signal(ps,rs)
    assert result is None
    assert rs.last_rejection_reason == "POSITION_OPEN"

@pytest.mark.asyncio
async def test_no_signal_low_balance():
    """Новый тест v12: LOW_BALANCE при balance < MIN_BALANCE_USD."""
    import config, time; config.BACKTEST_MODE = False; config.MIN_BALANCE_USD = 50.0
    from state import PersistentState, RuntimeState
    from strategy.signal_engine import evaluate_signal
    ps=_make_ps(balance=10.0)  # баланс ниже минимума
    rs=RuntimeState(); rs.micro.last_updated_ms=int(time.time()*1000)
    result=await evaluate_signal(ps,rs)
    assert result is None
    assert rs.last_rejection_reason == "LOW_BALANCE"

