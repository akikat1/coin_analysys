import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_round_price():
    from execution import exchange_info
    exchange_info.tick_size=0.1; exchange_info._tick_prec=1
    assert exchange_info.round_price(50000.15) == 50000.2

def test_round_qty_floor():
    from execution import exchange_info
    exchange_info.step_size=0.001; exchange_info._step_prec=3
    assert exchange_info.round_qty(0.0019)==0.001
    assert exchange_info.round_qty(0.0010)==0.001

def test_validate_pass():
    from execution import exchange_info
    exchange_info.step_size=0.001; exchange_info.min_notional=5.0
    assert exchange_info.validate(50000,0.001)

def test_validate_fail_notional():
    from execution import exchange_info
    exchange_info.min_notional=5.0; exchange_info.step_size=0.001
    assert not exchange_info.validate(1.0,0.001)

def test_dec_helper():
    from execution.exchange_info import _dec
    assert _dec(0.1)==1; assert _dec(0.001)==3; assert _dec(1.0)==0

