import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
config.MAX_RISK_PER_TRADE_PCT=0.01; config.LEVERAGE=10
config.REDUCED_SIZE_MULTIPLIER=0.5; config.TAKER_FEE=0.0004
config.MAKER_FEE=0.0002; config.SLIPPAGE_ESTIMATE=0.0002; config.BNB_DISCOUNT=False
from execution import exchange_info
exchange_info.tick_size=0.1; exchange_info.step_size=0.001
exchange_info.min_notional=5.0; exchange_info._tick_prec=1; exchange_info._step_prec=3

from strategy.risk_manager import calculate_levels
from models import MarketContext

def _ctx(regime="TREND", trend_dir="BULL", mult=1.0):
    c = MarketContext(); c.regime=regime; c.trend_dir=trend_dir; c.size_multiplier=mult
    return c

def test_long_levels():
    lvl = calculate_levels(50000, "LONG", 500, 10000, _ctx(), False)
    assert lvl is not None
    assert lvl.stop < lvl.entry < lvl.tp1 < lvl.tp2 < lvl.tp3
    assert lvl.rr >= 2.0
    assert lvl.leverage == config.LEVERAGE

def test_short_levels():
    lvl = calculate_levels(50000, "SHORT", 500, 10000, _ctx(trend_dir="BEAR"), False)
    assert lvl is not None
    assert lvl.stop > lvl.entry > lvl.tp1 > lvl.tp2 > lvl.tp3

def test_reduced_size():
    lvl_full = calculate_levels(50000, "LONG", 500, 10000, _ctx(), False)
    lvl_red  = calculate_levels(50000, "LONG", 500, 10000, _ctx(), True)
    assert lvl_red.qty_btc < lvl_full.qty_btc

def test_qty_split():
    lvl = calculate_levels(50000, "LONG", 500, 10000, _ctx(), False)
    assert abs(lvl.qty_tp1 + lvl.qty_tp2 + lvl.qty_tp3 - lvl.qty_btc) < 0.001

def test_none_on_insufficient_balance():
    lvl = calculate_levels(50000, "LONG", 500, 1.0, _ctx(), False)
    assert lvl is None

