import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_position():
    from models import Position

    return Position(
        direction="LONG",
        entry_price=50000.0,
        avg_fill_price=50000.0,
        qty_btc=0.01,
        qty_remaining=0.01,
        stop_price=49000.0,
        tp1_price=51000.0,
        tp2_price=52000.0,
        tp3_price=53000.0,
        stop_order_id=0,
        tp1_order_id=0,
        tp2_order_id=0,
        tp3_order_id=0,
        qty_tp1=0.004,
        qty_tp2=0.0035,
        qty_tp3=0.0025,
        open_timestamp_ms=int(time.time() * 1000) - 30_000,
        mode="paper",
    )


@pytest.mark.asyncio
async def test_deadman_closes_in_paper(monkeypatch):
    import config
    from execution import position_tracker
    from state import PersistentState, RuntimeState

    config.DEADMAN_SWITCH_SEC = 5
    config.PAPER_MODE = True
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    rs.micro.last_updated_ms = int(time.time() * 1000) - 20_000
    rs.micro.mark_price = 49900.0

    calls = {"n": 0, "reason": ""}

    async def fake_close(reason, price, qty, ps_obj, rs_obj):
        calls["n"] += 1
        calls["reason"] = reason
        ps_obj.position = None

    monkeypatch.setattr(position_tracker, "_close_trade", fake_close)

    closed = await position_tracker.maybe_close_deadman_position(ps, rs)
    assert closed is True
    assert calls["n"] == 1
    assert calls["reason"] == "DEADMAN_SWITCH"
    assert ps.position is None


@pytest.mark.asyncio
async def test_deadman_noop_on_fresh_feed(monkeypatch):
    import config
    from execution import position_tracker
    from state import PersistentState, RuntimeState

    config.DEADMAN_SWITCH_SEC = 5
    config.PAPER_MODE = True
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    rs.micro.last_updated_ms = int(time.time() * 1000)
    rs.micro.mark_price = 50100.0

    async def fake_close(*args, **kwargs):
        raise AssertionError("_close_trade should not run for fresh data")

    monkeypatch.setattr(position_tracker, "_close_trade", fake_close)
    closed = await position_tracker.maybe_close_deadman_position(ps, rs)
    assert closed is False
    assert ps.position is not None


@pytest.mark.asyncio
async def test_deadman_places_market_close_in_live(monkeypatch):
    import config
    from execution import position_tracker
    from state import PersistentState, RuntimeState

    config.DEADMAN_SWITCH_SEC = 5
    config.PAPER_MODE = False
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    rs.micro.last_updated_ms = int(time.time() * 1000) - 20_000
    rs.micro.mark_price = 49800.0

    async def fake_request(method, path, params=None, **kwargs):
        if path == "/fapi/v1/order" and method == "POST":
            return {"orderId": 42, "avgPrice": "49750.0"}
        return {}

    calls = {"n": 0, "reason": "", "price": 0.0}

    async def fake_close(reason, price, qty, ps_obj, rs_obj):
        calls["n"] += 1
        calls["reason"] = reason
        calls["price"] = price
        ps_obj.position = None

    monkeypatch.setattr("data.rest_client._request", fake_request)
    monkeypatch.setattr(position_tracker, "_close_trade", fake_close)

    closed = await position_tracker.maybe_close_deadman_position(ps, rs)
    assert closed is True
    assert calls["n"] == 1
    assert calls["reason"] == "DEADMAN_SWITCH"
    assert calls["price"] == pytest.approx(49750.0, abs=0.01)
