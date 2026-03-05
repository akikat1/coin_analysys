import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
config.BACKTEST_MODE = False; config.PAPER_MODE = False
config.POSITION_SYNC_ON_START = True; config.SYMBOL = "BTCUSDT"
config.LEVERAGE = 10

from execution import exchange_info
exchange_info.tick_size=0.1; exchange_info.step_size=0.001
exchange_info.min_notional=5.0; exchange_info._tick_prec=1; exchange_info._step_prec=3

@pytest.mark.asyncio
async def test_sync_clears_stale_position(monkeypatch):
    """state имеет позицию, биржа говорит qty=0 → сброс."""
    from state import PersistentState
    from models import Position
    import time
    ps = PersistentState(available_balance=1000.0)
    ps.position = Position(
        direction="LONG", entry_price=50000, avg_fill_price=50000,
        qty_btc=0.01, qty_remaining=0.01, stop_price=49000,
        tp1_price=51000, tp2_price=52000, tp3_price=54000,
        stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=0.004, qty_tp2=0.0035, qty_tp3=0.0025,
        open_timestamp_ms=int(time.time()*1000), mode="live")

    async def mock_request(method, path, params=None, **kw):
        if "positionRisk" in path:
            return [{"symbol": "BTCUSDT", "positionAmt": "0.0", "entryPrice": "0.0"}]
        return {}
    monkeypatch.setattr("data.rest_client._request", mock_request)

    from execution.position_sync import sync_on_startup
    await sync_on_startup(ps)
    assert ps.position is None

@pytest.mark.asyncio
async def test_sync_restores_missing_position(monkeypatch):
    """state пустой, биржа показывает LONG qty=0.01 → восстановление."""
    from state import PersistentState
    ps = PersistentState(available_balance=1000.0)
    assert ps.position is None

    async def mock_request(method, path, params=None, **kw):
        if "positionRisk" in path:
            return [{"symbol": "BTCUSDT", "positionAmt": "0.01", "entryPrice": "50000.0"}]
        if "openOrders" in path:
            return []
        return {}
    monkeypatch.setattr("data.rest_client._request", mock_request)

    from execution.position_sync import sync_on_startup
    await sync_on_startup(ps)
    assert ps.position is not None
    assert ps.position.direction == "LONG"
    assert ps.position.qty_remaining == pytest.approx(0.01, abs=0.0001)

@pytest.mark.asyncio
async def test_sync_ok_when_consistent(monkeypatch):
    """state и биржа согласны → ps.position не меняется."""
    from state import PersistentState
    from models import Position
    import time
    ps = PersistentState(available_balance=1000.0)
    ps.position = Position(
        direction="LONG", entry_price=50000, avg_fill_price=50000,
        qty_btc=0.01, qty_remaining=0.01, stop_price=49000,
        tp1_price=51000, tp2_price=52000, tp3_price=54000,
        stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=0.004, qty_tp2=0.0035, qty_tp3=0.0025,
        open_timestamp_ms=int(time.time()*1000), mode="live")

    async def mock_request(method, path, params=None, **kw):
        if "positionRisk" in path:
            return [{"symbol": "BTCUSDT", "positionAmt": "0.01", "entryPrice": "50000.0"}]
        return {}
    monkeypatch.setattr("data.rest_client._request", mock_request)

    from execution.position_sync import sync_on_startup
    await sync_on_startup(ps)
    assert ps.position is not None
    assert ps.position.direction == "LONG"


@pytest.mark.asyncio
async def test_sync_creates_protective_stop_on_restore(monkeypatch):
    """If exchange has a position and no open orders, sync should create a STOP order."""
    from state import PersistentState

    ps = PersistentState(available_balance=1000.0)
    calls = {"stop_created": 0}

    async def mock_request(method, path, params=None, **kw):
        if "positionRisk" in path:
            return [{"symbol": "BTCUSDT", "positionAmt": "0.01", "entryPrice": "50000.0"}]
        if "openOrders" in path:
            return []
        if path == "/fapi/v1/order" and method == "POST":
            calls["stop_created"] += 1
            return {"orderId": 777}
        return {}

    monkeypatch.setattr("data.rest_client._request", mock_request)

    from execution.position_sync import sync_on_startup

    await sync_on_startup(ps)
    assert ps.position is not None
    assert ps.position.stop_order_id == 777
    assert calls["stop_created"] == 1

