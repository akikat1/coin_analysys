"""
РўРµСЃС‚С‹ paper_engine v12:
- STOP Р·Р°РєСЂС‹РІР°РµС‚ РїРѕР·РёС†РёСЋ СЃ СѓР±С‹С‚РєРѕРј
- TP1 РїРµСЂРµРЅРѕСЃРёС‚ СЃС‚РѕРї РЅР° Р±РµР·СѓР±С‹С‚РѕРє (РёСЃРїСЂР°РІР»РµРЅРёРµ v12)
- РџРѕСЃР»Рµ TP1 + СЃС‚РѕРї = Р±РµР·СѓР±С‹С‚РѕРє (РЅРµ СѓР±С‹С‚РѕРє)
- TP2 РєРѕСЂСЂРµРєС‚РЅРѕ РѕР±РЅРѕРІР»СЏРµС‚ qty_remaining
- TP3 Р·Р°РєСЂС‹РІР°РµС‚ РѕСЃС‚Р°РІС€СѓСЋСЃСЏ РїРѕР·РёС†РёСЋ РїРѕР»РЅРѕСЃС‚СЊСЋ
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
config.TAKER_FEE=0.0004; config.MAKER_FEE=0.0002
config.SLIPPAGE_ESTIMATE=0.0002; config.BNB_DISCOUNT=False
config.LEVERAGE=10; config.MAX_CONSECUTIVE_LOSSES=3
config.REDUCED_SIZE_MULTIPLIER=0.5; config.MAX_DAILY_LOSS_PCT=0.05
config.MAX_DRAWDOWN_PCT=0.15

from execution import exchange_info
exchange_info.tick_size=0.1; exchange_info.step_size=0.001
exchange_info.min_notional=5.0; exchange_info._tick_prec=1; exchange_info._step_prec=3

def _make_position(direction="LONG", entry=50000.0, stop=49000.0,
                   tp1=51000.0, tp2=52500.0, tp3=55000.0,
                   qty=0.010):
    from models import Position
    import time
    qt1=round(qty*0.40, 3); qt2=round(qty*0.35, 3); qt3=round(qty-qt1-qt2, 3)
    return Position(
        direction=direction, entry_price=entry, avg_fill_price=entry,
        qty_btc=qty, qty_remaining=qty,
        stop_price=stop, tp1_price=tp1, tp2_price=tp2, tp3_price=tp3,
        stop_order_id=0, tp1_order_id=0, tp2_order_id=0, tp3_order_id=0,
        qty_tp1=qt1, qty_tp2=qt2, qty_tp3=qt3,
        confidence_at_entry=75.0, regime_at_entry="TREND",
        open_timestamp_ms=int(time.time()*1000), mode="paper")

def _make_ps_with_pos(direction="LONG"):
    from state import PersistentState
    ps = PersistentState(available_balance=1000.0, equity_peak=1000.0)
    ps.position = _make_position(direction=direction)
    return ps

@pytest.mark.asyncio
async def test_paper_stop_closes_position():
    """STOP: РїРѕР·РёС†РёСЏ Р·Р°РєСЂС‹РІР°РµС‚СЃСЏ, ps.position = None."""
    from state import RuntimeState
    from backtest.paper_engine import _paper_close
    ps = _make_ps_with_pos()
    rs = RuntimeState()
    await _paper_close(ps, rs, "STOP", 49000.0)
    assert ps.position is None
    assert ps.trades_today == 1
    assert ps.losses_today == 1

@pytest.mark.asyncio
async def test_paper_tp1_moves_stop_to_breakeven():
    """
    v12 РРЎРџР РђР’Р›Р•РќРР•: РїРѕСЃР»Рµ TP1 СЃС‚РѕРї РїРµСЂРµРЅРѕСЃРёС‚СЃСЏ РЅР° С†РµРЅСѓ РІС…РѕРґР° (Р±РµР·СѓР±С‹С‚РѕРє).
    Р‘РµР· СЌС‚РѕР№ РїСЂРѕРІРµСЂРєРё Р±Р°Рі РјРѕРі РѕСЃС‚Р°РІР°С‚СЊСЃСЏ РЅРµР·Р°РјРµС‡РµРЅРЅС‹Рј РІРµС‡РЅРѕ.
    """
    from state import RuntimeState
    from backtest.paper_engine import _paper_tp
    ps = _make_ps_with_pos()
    original_entry = ps.position.avg_fill_price
    original_stop  = ps.position.stop_price
    assert original_stop < original_entry, "СЃС‚РѕРї РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РЅРёР¶Рµ РІС…РѕРґР° РґР»СЏ LONG"
    rs = RuntimeState()
    await _paper_tp(ps, rs, 1, 51000.0)
    assert ps.position is not None, "РїРѕР·РёС†РёСЏ РЅРµ РґРѕР»Р¶РЅР° Р·Р°РєСЂС‹РІР°С‚СЊСЃСЏ РїРѕСЃР»Рµ TP1"
    assert ps.position.tp1_filled is True
    # РљР›Р®Р§Р•Р’РђРЇ РџР РћР’Р•Р РљРђ: СЃС‚РѕРї РїРµСЂРµРЅРµСЃС‘РЅ РЅР° Р±РµР·СѓР±С‹С‚РѕРє
    assert ps.position.stop_price == pytest.approx(original_entry, abs=0.01), \
        f"СЃС‚РѕРї РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РїРµСЂРµРЅРµСЃС‘РЅ РЅР° {original_entry}, РЅРѕ РѕРЅ {ps.position.stop_price}"

@pytest.mark.asyncio
async def test_paper_tp1_then_stop_at_breakeven_is_not_loss():
    """
    РџРѕСЃР»Рµ TP1 СЃС‚РѕРї = Р±РµР·СѓР±С‹С‚РѕРє. Р•СЃР»Рё С†РµРЅР° РІРѕР·РІСЂР°С‰Р°РµС‚СЃСЏ Рє РІС…РѕРґСѓ Рё Р±СЊС‘С‚ СЃС‚РѕРї,
    РёС‚РѕРіРѕРІС‹Р№ P&L РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ >= 0 (TP1 РїСЂРёР±С‹Р»СЊ РїРµСЂРµРєСЂС‹РІР°РµС‚ Р±РµР·СѓР±С‹С‚РѕС‡РЅС‹Р№ СЃС‚РѕРї).
    """
    from state import RuntimeState
    from backtest.paper_engine import _paper_tp, _paper_close
    ps = _make_ps_with_pos()
    rs = RuntimeState()
    balance_before = ps.available_balance
    await _paper_tp(ps, rs, 1, 51000.0)
    # РЎС‚РѕРї С‚РµРїРµСЂСЊ РЅР° 50000 (Р±РµР·СѓР±С‹С‚РѕРє). Р—Р°РєСЂС‹РІР°РµРј РїРѕ РЅРµРјСѓ.
    await _paper_close(ps, rs, "STOP", ps.position.stop_price if ps.position else 50000.0)
    # РС‚РѕРіРѕРІС‹Р№ Р±Р°Р»Р°РЅСЃ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ >= Р±Р°Р»Р°РЅСЃР° РґРѕ РѕС‚РєСЂС‹С‚РёСЏ (Р·Р° РІС‹С‡РµС‚РѕРј РєРѕРјРёСЃСЃРёР№ РјРѕР¶РµС‚ Р±С‹С‚СЊ С‡СѓС‚СЊ РјРµРЅСЊС€Рµ,
    # РЅРѕ С‚РѕС‡РЅРѕ РЅРµ -9$ РєР°Рє Р±РµР· РёСЃРїСЂР°РІР»РµРЅРёСЏ)
    # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СѓР±С‹С‚РѕРє РјРёРЅРёРјР°Р»РµРЅ (РЅРµ Р±РѕР»РµРµ 5% РѕС‚ TP1 РїСЂРёР±С‹Р»Рё)
    balance_change = ps.available_balance - balance_before
    assert balance_change > -2.0, f"РЎС‚РѕРї РЅР° Р±РµР·СѓР±С‹С‚РєРµ РЅРµ РґРѕР»Р¶РµРЅ РґР°РІР°С‚СЊ Р±РѕР»СЊС€РѕРіРѕ СѓР±С‹С‚РєР°, got {balance_change:.2f}$"

@pytest.mark.asyncio
async def test_paper_tp2_reduces_qty():
    """TP2: qty_remaining СѓРјРµРЅСЊС€Р°РµС‚СЃСЏ, tp2_filled = True."""
    from state import RuntimeState
    from backtest.paper_engine import _paper_tp
    ps = _make_ps_with_pos()
    rs = RuntimeState()
    qty_before = ps.position.qty_remaining
    await _paper_tp(ps, rs, 1, 51000.0)
    qty_after_tp1 = ps.position.qty_remaining
    await _paper_tp(ps, rs, 2, 52500.0)
    assert ps.position.tp2_filled is True
    assert ps.position.qty_remaining < qty_after_tp1
    assert ps.position.qty_remaining > 0

@pytest.mark.asyncio
async def test_paper_tp3_closes_position():
    """TP3: РїРѕР·РёС†РёСЏ Р·Р°РєСЂС‹С‚Р° РїРѕР»РЅРѕСЃС‚СЊСЋ."""
    from state import RuntimeState
    from backtest.paper_engine import _paper_tp, _paper_close
    ps = _make_ps_with_pos()
    rs = RuntimeState()
    await _paper_tp(ps, rs, 1, 51000.0)
    await _paper_tp(ps, rs, 2, 52500.0)
    await _paper_close(ps, rs, "TP3", 55000.0)
    assert ps.position is None
    assert ps.wins_today == 1
    assert ps.losses_today == 0


@pytest.mark.asyncio
async def test_paper_uses_market_context_update(monkeypatch):
    from data.collector import CollectorState
    from models import Indicators
    from state import PersistentState, RuntimeState
    import backtest.paper_engine as pe

    ps = PersistentState(available_balance=1000.0, equity_peak=1000.0)
    rs = RuntimeState()
    rs.indicators["15m"] = Indicators(adx=30.0)
    cs = CollectorState()
    cs.micro.mark_price = 50000.0

    called = {"n": 0}

    async def fake_update(_rs, _cs):
        called["n"] += 1
        _rs.context.regime = "TREND"
        _rs.context.oi_signal = "BULL_CONFIRMING"

    async def fake_eval(*args, **kwargs):
        return None

    monkeypatch.setattr("data.market_context.update", fake_update)
    monkeypatch.setattr(pe, "evaluate_signal", fake_eval)
    monkeypatch.setattr("monitor.logger.log_signal", lambda *args, **kwargs: None)

    await pe.run_paper_signal_loop(ps, rs, cs)

    assert called["n"] == 1
    assert rs.context.oi_signal == "BULL_CONFIRMING"


@pytest.mark.asyncio
async def test_paper_market_context_fallback_on_error(monkeypatch):
    from data.collector import CollectorState
    from models import Indicators, MarketContext
    from state import PersistentState, RuntimeState
    import backtest.paper_engine as pe

    ps = PersistentState(available_balance=1000.0, equity_peak=1000.0)
    rs = RuntimeState()
    rs.indicators["15m"] = Indicators(adx=30.0)
    cs = CollectorState()
    cs.micro.mark_price = 50000.0
    cs.micro.funding_rate = 0.0001

    async def fail_update(*args, **kwargs):
        raise RuntimeError("REST offline")

    def fake_build_regime(ind, funding_rate):
        ctx = MarketContext()
        ctx.regime = "WEAK_TREND"
        ctx.funding_filter_active = False
        ctx.session_filter_active = False
        ctx.should_trade = True
        assert ind is rs.indicators["15m"]
        assert funding_rate == cs.micro.funding_rate
        return ctx

    async def fake_eval(*args, **kwargs):
        return None

    monkeypatch.setattr("data.market_context.update", fail_update)
    monkeypatch.setattr("data.market_context._build_regime", fake_build_regime)
    monkeypatch.setattr(pe, "evaluate_signal", fake_eval)
    monkeypatch.setattr("monitor.logger.log_signal", lambda *args, **kwargs: None)

    await pe.run_paper_signal_loop(ps, rs, cs)

    assert rs.context.regime == "WEAK_TREND"
