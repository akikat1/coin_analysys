import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from collections import deque
from models import Candle
from data.volume_profile import calculate

def _make_candles(n=100, base_price=50000.0, vol=10.0):
    import random; random.seed(42)
    candles = deque(maxlen=500)
    price = base_price
    for i in range(n):
        o = price
        c = price + random.uniform(-100, 100)
        h = max(o, c) + random.uniform(0, 50)
        l = min(o, c) - random.uniform(0, 50)
        candles.append(Candle(open_time=i*60000, open=o, high=h, low=l, close=c,
                               volume=vol + random.uniform(0,5), close_time=(i+1)*60000,
                               is_closed=True))
        price = c
    return candles

def test_poc_in_price_range():
    candles = _make_candles()
    poc, vah, val = calculate(candles)
    all_prices = [c.close for c in candles]
    assert min(all_prices) <= poc <= max(all_prices)

def test_vah_above_poc():
    candles = _make_candles()
    poc, vah, val = calculate(candles)
    assert vah >= poc

def test_val_below_poc():
    candles = _make_candles()
    poc, vah, val = calculate(candles)
    assert val <= poc

def test_returns_zeros_on_insufficient_data():
    candles = deque([
        Candle(open_time=0, open=50000, high=50100, low=49900, close=50000,
               volume=1.0, close_time=60000, is_closed=True)
    ])
    poc, vah, val = calculate(candles)
    assert poc == 0.0 and vah == 0.0 and val == 0.0

def test_vah_val_encompass_poc():
    candles = _make_candles(200)
    poc, vah, val = calculate(candles)
    assert val <= poc <= vah

