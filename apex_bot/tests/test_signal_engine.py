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


@pytest.mark.asyncio
async def test_no_signal_max_trades_day():
    import config, time
    config.BACKTEST_MODE = False
    config.MAX_TRADES_PER_DAY = 3
    from state import RuntimeState
    from strategy.signal_engine import evaluate_signal

    ps = _make_ps(balance=1000.0)
    ps.trades_today = 3
    rs = RuntimeState()
    rs.micro.last_updated_ms = int(time.time() * 1000)

    result = await evaluate_signal(ps, rs)
    assert result is None
    assert rs.last_rejection_reason == "MAX_TRADES_DAY"


@pytest.mark.asyncio
async def test_reject_insufficient_margin(monkeypatch):
    import config
    import strategy.signal_engine as se
    from models import Indicators, TradeLevel
    from state import RuntimeState

    config.BACKTEST_MODE = True
    config.MIN_BALANCE_USD = 50.0
    config.HTF_FILTER_ENABLED = False
    config.ENFORCE_VOLUME_FILTER = False
    config.MIN_CONFIDENCE = 10.0
    ps = _make_ps(balance=100.0)
    rs = RuntimeState()
    rs.context.should_trade = True
    rs.context.regime = "TREND"
    rs.context.trend_dir = "BULL"
    rs.micro.last_updated_ms = 1
    rs.micro.best_ask = 50000.0
    rs.micro.best_bid = 49999.0
    rs.micro.mark_price = 50000.0
    rs.micro.spread_pct = 0.0001
    rs.indicators["15m"] = Indicators(atr=500.0, atr_avg_24h=1000.0, volume_ratio=2.0)
    rs.indicators["5m"] = Indicators(atr=400.0)
    rs.indicators["1m"] = Indicators(atr=300.0)

    seq = [
        (80.0, 10.0, {"LONG": {"ema": 10.0}, "SHORT": {}}),
        (70.0, 10.0, {"LONG": {}, "SHORT": {}}),
        (60.0, 10.0, {"LONG": {}, "SHORT": {}}),
    ]
    monkeypatch.setattr(se, "_score_tf", lambda ind, micro: seq.pop(0))
    async def _no_ai(*args, **kwargs):
        return None
    monkeypatch.setattr(se.ai_advisor, "get_trade_advice", _no_ai)
    monkeypatch.setattr(se.fee_calculator, "is_tp1_profitable", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        se.risk_manager,
        "calculate_levels",
        lambda **kwargs: TradeLevel(
            entry=50000.0,
            stop=49500.0,
            tp1=51000.0,
            tp2=51500.0,
            tp3=52000.0,
            qty_btc=0.002,
            qty_tp1=0.0008,
            qty_tp2=0.0007,
            qty_tp3=0.0005,
            notional_usd=1000.0,
            margin_usd=95.0,
            rr=2.0,
            stop_dist_pct=0.01,
            leverage=10,
        ),
    )

    result = await se.evaluate_signal(ps, rs)
    assert result is None
    assert rs.last_rejection_reason == "INSUFFICIENT_MARGIN"

