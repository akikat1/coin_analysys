"""
Тесты _maybe_reset_daily из main.py.
Проверяет что дневная статистика сбрасывается при смене UTC-дня
и что бот может торговать после сброса (DAILY_LIMIT снимается).
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime, timezone

def _make_ps_at_daily_limit():
    from state import PersistentState
    ps = PersistentState(available_balance=9500.0, equity_peak=10000.0)
    ps.daily_pnl_pct  = -0.06   # превысил дневной лимит -5%
    ps.daily_pnl_usd  = -600.0
    ps.trades_today   = 5
    ps.wins_today     = 2
    ps.losses_today   = 3
    ps.daily_reset_date = "2020-01-01"  # очень старая дата → сброс сработает
    return ps

def _get_reset_fn():
    """Импортировать _maybe_reset_daily из main.py."""
    import importlib.util, os
    spec = importlib.util.spec_from_file_location("main", os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._maybe_reset_daily

def test_reset_clears_stats():
    """После сброса все дневные счётчики равны 0."""
    fn = _get_reset_fn()
    ps = _make_ps_at_daily_limit()
    fn(ps)
    assert ps.daily_pnl_pct  == 0.0
    assert ps.daily_pnl_usd  == 0.0
    assert ps.trades_today   == 0
    assert ps.wins_today     == 0
    assert ps.losses_today   == 0

def test_reset_updates_date():
    """После сброса daily_reset_date = сегодня UTC."""
    fn = _get_reset_fn()
    ps = _make_ps_at_daily_limit()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fn(ps)
    assert ps.daily_reset_date == today

def test_no_reset_if_same_day():
    """Если дата не изменилась — сброс не происходит, счётчики сохраняются."""
    fn = _get_reset_fn()
    from state import PersistentState
    ps = PersistentState(available_balance=9500.0)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ps.daily_reset_date = today
    ps.trades_today = 7
    ps.wins_today   = 4
    fn(ps)
    assert ps.trades_today == 7  # не сбросился
    assert ps.wins_today   == 4

@pytest.mark.asyncio
async def test_bot_can_trade_after_reset():
    """После сброса daily_pnl_pct = 0 → сигнал не блокируется DAILY_LIMIT."""
    import config, time; config.BACKTEST_MODE = False; config.MIN_BALANCE_USD = 50.0
    fn = _get_reset_fn()
    ps = _make_ps_at_daily_limit()
    assert ps.daily_pnl_pct <= -config.MAX_DAILY_LOSS_PCT  # до сброса — лимит
    fn(ps)
    assert ps.daily_pnl_pct == 0.0  # после сброса — лимит снят
    from state import RuntimeState
    from strategy.signal_engine import evaluate_signal
    rs = RuntimeState(); rs.micro.last_updated_ms = int(time.time()*1000)
    result = await evaluate_signal(ps, rs)
    # Может быть None по другим причинам, но НЕ из-за DAILY_LIMIT
    assert rs.last_rejection_reason != "DAILY_LIMIT"

