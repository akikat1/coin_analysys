import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _position_payload(entry_price: float, qty_btc: float) -> dict:
    return {
        "direction": "LONG",
        "entry_price": entry_price,
        "avg_fill_price": entry_price,
        "qty_btc": qty_btc,
        "qty_remaining": qty_btc,
        "stop_price": entry_price * 0.98,
        "tp1_price": entry_price * 1.01,
        "tp2_price": entry_price * 1.02,
        "tp3_price": entry_price * 1.03,
        "stop_order_id": 0,
        "tp1_order_id": 0,
        "tp2_order_id": 0,
        "tp3_order_id": 0,
        "qty_tp1": qty_btc * 0.4,
        "qty_tp2": qty_btc * 0.35,
        "qty_tp3": qty_btc * 0.25,
        "mode": "live",
        "open_timestamp_ms": 0,
    }


def test_state_load_resets_invalid_position(monkeypatch, tmp_path):
    import state

    state_file = tmp_path / "state.json"
    tmp_file = tmp_path / "state.json.tmp"
    monkeypatch.setattr(state, "STATE_FILE", str(state_file))
    monkeypatch.setattr(state, "STATE_FILE_TMP", str(tmp_file))

    payload = {
        "state_version": state.STATE_VERSION,
        "available_balance": 1000.0,
        "position": _position_payload(entry_price=5000.0, qty_btc=0.01),
    }
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    ps = state.load()
    assert ps.position is None


def test_state_load_keeps_valid_position(monkeypatch, tmp_path):
    import state

    state_file = tmp_path / "state.json"
    tmp_file = tmp_path / "state.json.tmp"
    monkeypatch.setattr(state, "STATE_FILE", str(state_file))
    monkeypatch.setattr(state, "STATE_FILE_TMP", str(tmp_file))

    payload = {
        "state_version": state.STATE_VERSION,
        "available_balance": 1000.0,
        "position": _position_payload(entry_price=50000.0, qty_btc=0.01),
    }
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    ps = state.load()
    assert ps.position is not None
    assert ps.position.entry_price == 50000.0
