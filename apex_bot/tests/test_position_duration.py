import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_position(open_age_sec: int):
    from models import Position

    now_ms = int(time.time() * 1000)
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
        open_timestamp_ms=now_ms - open_age_sec * 1000,
        mode="paper",
    )


@pytest.mark.asyncio
async def test_close_expired_position(monkeypatch):
    import config
    from execution import position_tracker
    from state import PersistentState, RuntimeState

    config.MAX_POSITION_DURATION_SEC = 10
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position(open_age_sec=15)
    rs = RuntimeState()
    rs.micro.mark_price = 49900.0

    calls = {"n": 0, "reason": ""}

    async def fake_close(reason, price, qty, ps_obj, rs_obj):
        calls["n"] += 1
        calls["reason"] = reason
        ps_obj.position = None

    monkeypatch.setattr(position_tracker, "_close_trade", fake_close)
    closed = await position_tracker.maybe_close_expired_position(ps, rs)

    assert closed is True
    assert calls["n"] == 1
    assert calls["reason"] == "MAX_POSITION_DURATION"
    assert ps.position is None


@pytest.mark.asyncio
async def test_keep_fresh_position(monkeypatch):
    import config
    from execution import position_tracker
    from state import PersistentState, RuntimeState

    config.MAX_POSITION_DURATION_SEC = 10
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position(open_age_sec=3)
    rs = RuntimeState()
    rs.micro.mark_price = 50100.0

    async def fake_close(*args, **kwargs):
        raise AssertionError("_close_trade should not be called for fresh position")

    monkeypatch.setattr(position_tracker, "_close_trade", fake_close)
    closed = await position_tracker.maybe_close_expired_position(ps, rs)

    assert closed is False
    assert ps.position is not None
