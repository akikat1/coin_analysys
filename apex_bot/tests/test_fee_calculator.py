import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config; config.TAKER_FEE=0.0004; config.MAKER_FEE=0.0002
config.SLIPPAGE_ESTIMATE=0.0002; config.BNB_DISCOUNT=False

from strategy.fee_calculator import calculate_net_pnl, is_tp1_profitable

def test_long_profitable():
    r = calculate_net_pnl("LONG", 50000, 51000, 0.01, 10)
    assert r.gross_pnl == pytest.approx(10.0, abs=0.01)
    assert r.net_pnl < r.gross_pnl
    assert r.net_pnl > 0

def test_short_profitable():
    r = calculate_net_pnl("SHORT", 50000, 49000, 0.01, 10)
    assert r.gross_pnl == pytest.approx(10.0, abs=0.01)
    assert r.net_pnl > 0

def test_bnb_discount_reduces_fee():
    config.BNB_DISCOUNT = False
    r1 = calculate_net_pnl("LONG", 50000, 50500, 0.01, 10)
    config.BNB_DISCOUNT = True
    r2 = calculate_net_pnl("LONG", 50000, 50500, 0.01, 10)
    config.BNB_DISCOUNT = False
    assert r2.entry_fee < r1.entry_fee

def test_breakeven_price_long():
    r = calculate_net_pnl("LONG", 50000, 50000, 0.01, 10)
    assert r.break_even_price > 50000

def test_tp1_profitable_check():
    assert is_tp1_profitable(50000, 50300, 0.01, 10, "LONG")
    assert not is_tp1_profitable(50000, 50010, 0.01, 10, "LONG")

