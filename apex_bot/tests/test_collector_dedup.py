import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.mark.asyncio
async def test_closed_kline_duplicate_is_skipped():
    from data.collector import CollectorState, _dispatch

    cs = CollectorState()
    msg = {
        "stream": "btcusdt@kline_1m",
        "data": {
            "k": {
                "i": "1m",
                "x": True,
                "t": 1_700_000_000_000,
                "T": 1_700_000_059_999,
                "o": "100000",
                "h": "100100",
                "l": "99900",
                "c": "100050",
                "v": "12.3",
            }
        },
    }

    await _dispatch(msg, cs)
    await _dispatch(msg, cs)

    assert len(cs.candles["1m"]) == 1
    assert cs.last_candle_open_time["1m"] == 1_700_000_000_000
