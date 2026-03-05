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
        stop_order_id=1,
        tp1_order_id=2,
        tp2_order_id=3,
        tp3_order_id=4,
        qty_tp1=0.004,
        qty_tp2=0.0035,
        qty_tp3=0.0025,
        open_timestamp_ms=int(time.time() * 1000),
        mode="live",
    )


@pytest.mark.asyncio
async def test_reset_rejected_when_exchange_position_exists(monkeypatch):
    import config
    from state import PersistentState, RuntimeState
    import monitor.telegram_commands as tc

    config.SYMBOL = "BTCUSDT"
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    messages: list[str] = []

    async def fake_send(text: str):
        messages.append(text)

    async def fake_request(method, path, params=None, signed=True, weight=1):
        assert method == "GET"
        assert path == "/fapi/v2/positionRisk"
        return [{"symbol": "BTCUSDT", "positionAmt": "0.01"}]

    monkeypatch.setattr("monitor.notifier._send", fake_send)
    monkeypatch.setattr("data.rest_client._request", fake_request)

    await tc._handle_command("/reset", ps, rs)

    assert ps.position is not None
    assert any("open position" in m.lower() for m in messages)


@pytest.mark.asyncio
async def test_reset_clears_local_state_when_exchange_position_absent(monkeypatch):
    import config
    from state import PersistentState, RuntimeState
    import monitor.telegram_commands as tc

    config.SYMBOL = "BTCUSDT"
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    messages: list[str] = []
    saved = {"called": False}

    async def fake_send(text: str):
        messages.append(text)

    async def fake_request(method, path, params=None, signed=True, weight=1):
        assert method == "GET"
        assert path == "/fapi/v2/positionRisk"
        return [{"symbol": "BTCUSDT", "positionAmt": "0"}]

    def fake_save(_ps):
        saved["called"] = True

    monkeypatch.setattr("monitor.notifier._send", fake_send)
    monkeypatch.setattr("data.rest_client._request", fake_request)
    monkeypatch.setattr("state.save", fake_save)

    await tc._handle_command("/reset", ps, rs)

    assert ps.position is None
    assert saved["called"] is True
    assert any("state reset" in m.lower() for m in messages)
