import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_ps():
    from state import PersistentState

    return PersistentState(available_balance=1000.0, equity_peak=1000.0)


def _make_rs():
    import time

    from models import Indicators, MarketContext
    from state import RuntimeState

    rs = RuntimeState()
    rs.context = MarketContext(regime="TREND", trend_dir="BULL", should_trade=True)
    rs.micro.last_updated_ms = int(time.time() * 1000)
    rs.micro.best_ask = 50000.0
    rs.micro.best_bid = 49999.9
    rs.micro.mark_price = 50000.0
    rs.micro.spread_pct = 0.0001
    rs.indicators["15m"] = Indicators(atr=500.0)
    rs.indicators["5m"] = Indicators(atr=300.0)
    rs.indicators["1m"] = Indicators(atr=100.0)
    rs.indicators["1h"] = Indicators()  # NEUTRAL htf
    return rs


def _patch_common(monkeypatch):
    from models import TradeLevel
    import strategy.signal_engine as se

    level = TradeLevel(
        entry=50000.0,
        stop=49500.0,
        tp1=51000.0,
        tp2=51500.0,
        tp3=52000.0,
        qty_btc=0.002,
        qty_tp1=0.0008,
        qty_tp2=0.0007,
        qty_tp3=0.0005,
        notional_usd=100.0,
        margin_usd=10.0,
        rr=2.0,
        stop_dist_pct=0.01,
    )
    monkeypatch.setattr(se.risk_manager, "calculate_levels", lambda **kwargs: level)
    monkeypatch.setattr(se.fee_calculator, "is_tp1_profitable", lambda *args, **kwargs: True)


def _patch_scores(monkeypatch):
    import strategy.signal_engine as se

    seq = [
        (70.0, 5.0, {"LONG": {"ema": 10.0}, "SHORT": {}}),
        (70.0, 5.0, {"LONG": {}, "SHORT": {}}),
        (40.0, 10.0, {"LONG": {}, "SHORT": {}}),
    ]

    def fake_score_tf(ind, micro):
        return seq.pop(0)

    monkeypatch.setattr(se, "_score_tf", fake_score_tf)


@pytest.mark.asyncio
async def test_ai_gate_can_veto(monkeypatch):
    import config
    import strategy.signal_engine as se
    from strategy.ai_advisor import AIAdvice

    monkeypatch.setattr(config, "BACKTEST_MODE", True)
    monkeypatch.setattr(config, "MIN_CONFIDENCE", 50.0)
    monkeypatch.setattr(config, "MIN_BALANCE_USD", 50.0)
    monkeypatch.setattr(config, "HTF_FILTER_ENABLED", False)
    monkeypatch.setattr(config, "ENFORCE_VOLUME_FILTER", False)
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODE", "gate")

    async def fake_ai(*args, **kwargs):
        return AIAdvice(decision="BLOCK", score_delta=0.0, reason="risk_mismatch")

    monkeypatch.setattr(se.ai_advisor, "get_trade_advice", fake_ai)
    _patch_common(monkeypatch)
    _patch_scores(monkeypatch)

    ps = _make_ps()
    rs = _make_rs()
    result = await se.evaluate_signal(ps, rs)

    assert result is None
    assert rs.last_rejection_reason.startswith("AI_VETO(")


@pytest.mark.asyncio
async def test_ai_assist_can_push_over_threshold(monkeypatch):
    import config
    import strategy.signal_engine as se
    from strategy.ai_advisor import AIAdvice

    monkeypatch.setattr(config, "BACKTEST_MODE", True)
    monkeypatch.setattr(config, "MIN_CONFIDENCE", 72.0)
    monkeypatch.setattr(config, "MIN_BALANCE_USD", 50.0)
    monkeypatch.setattr(config, "HTF_FILTER_ENABLED", False)
    monkeypatch.setattr(config, "ENFORCE_VOLUME_FILTER", False)
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODE", "assist")

    async def fake_ai(*args, **kwargs):
        return AIAdvice(decision="ALLOW", score_delta=5.0, reason="momentum_support")

    monkeypatch.setattr(se.ai_advisor, "get_trade_advice", fake_ai)
    _patch_common(monkeypatch)
    _patch_scores(monkeypatch)

    ps = _make_ps()
    rs = _make_rs()
    result = await se.evaluate_signal(ps, rs)

    assert result is not None
    assert result.confidence >= config.MIN_CONFIDENCE
    assert rs.last_score_breakdown is not None
    assert rs.last_score_breakdown.ai_adjustment == pytest.approx(5.0, abs=1e-6)

@pytest.mark.asyncio
async def test_ai_hybrid_can_veto(monkeypatch):
    import config
    import strategy.signal_engine as se
    from strategy.ai_advisor import AIAdvice

    monkeypatch.setattr(config, "BACKTEST_MODE", True)
    monkeypatch.setattr(config, "MIN_CONFIDENCE", 50.0)
    monkeypatch.setattr(config, "MIN_BALANCE_USD", 50.0)
    monkeypatch.setattr(config, "HTF_FILTER_ENABLED", False)
    monkeypatch.setattr(config, "ENFORCE_VOLUME_FILTER", False)
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODE", "hybrid")

    async def fake_ai(*args, **kwargs):
        return AIAdvice(decision="BLOCK", score_delta=5.0, reason="consensus_block")

    monkeypatch.setattr(se.ai_advisor, "get_trade_advice", fake_ai)
    _patch_common(monkeypatch)
    _patch_scores(monkeypatch)

    ps = _make_ps()
    rs = _make_rs()
    result = await se.evaluate_signal(ps, rs)

    assert result is None
    assert rs.last_rejection_reason.startswith("AI_VETO(")


@pytest.mark.asyncio
async def test_ai_hybrid_can_apply_delta_and_pass(monkeypatch):
    import config
    import strategy.signal_engine as se
    from strategy.ai_advisor import AIAdvice

    monkeypatch.setattr(config, "BACKTEST_MODE", True)
    monkeypatch.setattr(config, "MIN_CONFIDENCE", 72.0)
    monkeypatch.setattr(config, "MIN_BALANCE_USD", 50.0)
    monkeypatch.setattr(config, "HTF_FILTER_ENABLED", False)
    monkeypatch.setattr(config, "ENFORCE_VOLUME_FILTER", False)
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODE", "hybrid")

    async def fake_ai(*args, **kwargs):
        return AIAdvice(decision="ALLOW", score_delta=5.0, reason="consensus_allow")

    monkeypatch.setattr(se.ai_advisor, "get_trade_advice", fake_ai)
    _patch_common(monkeypatch)
    _patch_scores(monkeypatch)

    ps = _make_ps()
    rs = _make_rs()
    result = await se.evaluate_signal(ps, rs)

    assert result is not None
    assert result.confidence >= config.MIN_CONFIDENCE
    assert rs.last_score_breakdown is not None
    assert rs.last_score_breakdown.ai_adjustment == pytest.approx(5.0, abs=1e-6)
    assert rs.last_score_breakdown.ai_decision == "ALLOW"
