import os
import sys
import time

import aiohttp
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


@pytest.mark.asyncio
async def test_close_uses_paper_close_in_paper_mode(monkeypatch):
    import config
    from state import PersistentState, RuntimeState
    import monitor.telegram_commands as tc

    config.PAPER_MODE = True
    ps = PersistentState(available_balance=1000.0)
    ps.position = _make_position()
    rs = RuntimeState()
    rs.micro.mark_price = 50100.0
    called = {"paper_close": False}
    messages: list[str] = []

    async def fake_send(text: str):
        messages.append(text)

    async def fake_paper_close(_ps, _rs, reason, price):
        called["paper_close"] = True
        assert reason == "MANUAL_CLOSE"
        assert price == 50100.0
        _ps.position = None

    async def fail_live_close(*args, **kwargs):
        raise AssertionError("live close should not be used in paper mode")

    monkeypatch.setattr("monitor.notifier._send", fake_send)
    monkeypatch.setattr("backtest.paper_engine._paper_close", fake_paper_close)
    monkeypatch.setattr("execution.position_tracker._close_trade", fail_live_close)

    await tc._handle_command("/close", ps, rs)

    assert called["paper_close"] is True
    assert ps.position is None
    assert any("position closed" in m.lower() for m in messages)
    config.PAPER_MODE = False


@pytest.mark.asyncio
async def test_poll_once_uses_finite_timeout(monkeypatch):
    from state import PersistentState, RuntimeState
    import monitor.telegram_commands as tc

    got_timeout = {"value": None}

    class _Resp:
        status = 200

        async def json(self, content_type=None):
            return {"result": []}

    class _ReqCtx:
        def __init__(self):
            self._resp = _Resp()

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sess:
        def get(self, url, params=None, timeout=None):
            got_timeout["value"] = timeout
            return _ReqCtx()

    async def fake_get_session():
        return _Sess()

    monkeypatch.setattr("data.rest_client.get_session", fake_get_session)

    ps = PersistentState()
    rs = RuntimeState()
    await tc._poll_once(ps, rs)

    assert isinstance(got_timeout["value"], aiohttp.ClientTimeout)
    assert got_timeout["value"].total == 5
