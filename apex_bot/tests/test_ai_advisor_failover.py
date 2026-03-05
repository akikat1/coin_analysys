import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.mark.asyncio
async def test_ai_failover_uses_next_candidate(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 0)
    monkeypatch.setattr(config, "AI_AUTO_FALLBACK", True)
    monkeypatch.setattr(config, "AI_FAIL_OPEN", True)

    c1 = aa.AICandidate("gemini", "https://g", "k1", "m1")
    c2 = aa.AICandidate("groq", "https://o", "k2", "m2")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1, c2])

    async def fake_query(candidate, system_msg, user_msg):
        if candidate.model == "m1":
            req = httpx.Request("POST", "https://example.invalid")
            resp = httpx.Response(429, request=req)
            raise httpx.HTTPStatusError("429", request=req, response=resp)
        return aa.AIAdvice(decision="ALLOW", score_delta=3.0, reason="ok")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert advice is not None
    assert advice.decision == "ALLOW"
    assert rs.last_ai_note.startswith("groq:m2:")


@pytest.mark.asyncio
async def test_ai_fail_closed_when_all_candidates_fail(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 0)
    monkeypatch.setattr(config, "AI_AUTO_FALLBACK", True)
    monkeypatch.setattr(config, "AI_FAIL_OPEN", False)

    c1 = aa.AICandidate("gemini", "https://g", "k1", "m1")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1])

    async def fake_query(candidate, system_msg, user_msg):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert advice is not None
    assert advice.decision == "BLOCK"
    assert advice.reason == "AI_ERROR_FAIL_CLOSED"


@pytest.mark.asyncio
async def test_ai_continue_on_block_returns_next_non_block(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 0)
    monkeypatch.setattr(config, "AI_AUTO_FALLBACK", True)
    monkeypatch.setattr(config, "AI_FAIL_OPEN", True)
    monkeypatch.setattr(config, "AI_CONTINUE_ON_BLOCK", True)
    monkeypatch.setattr(config, "AI_BLOCK_POLICY", "first")
    monkeypatch.setattr(config, "AI_BLOCK_REQUIRED", 2)
    monkeypatch.setattr(config, "AI_MAX_SUCCESS_OPINIONS", 3)

    c1 = aa.AICandidate("gemini", "https://g", "k1", "m1")
    c2 = aa.AICandidate("groq", "https://o", "k2", "m2")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1, c2])

    async def fake_query(candidate, system_msg, user_msg):
        if candidate.model == "m1":
            return aa.AIAdvice(decision="BLOCK", score_delta=0.0, reason="first_block")
        return aa.AIAdvice(decision="ALLOW", score_delta=2.0, reason="second_allow")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert advice is not None
    assert advice.decision == "ALLOW"
    assert advice.reason == "second_allow"
    assert rs.last_ai_note.startswith("groq:m2:ALLOW")


@pytest.mark.asyncio
async def test_ai_consensus_not_reached_returns_pass(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 0)
    monkeypatch.setattr(config, "AI_AUTO_FALLBACK", True)
    monkeypatch.setattr(config, "AI_FAIL_OPEN", True)
    monkeypatch.setattr(config, "AI_CONTINUE_ON_BLOCK", True)
    monkeypatch.setattr(config, "AI_BLOCK_POLICY", "consensus")
    monkeypatch.setattr(config, "AI_BLOCK_REQUIRED", 2)
    monkeypatch.setattr(config, "AI_MAX_SUCCESS_OPINIONS", 2)

    c1 = aa.AICandidate("gemini", "https://g", "k1", "m1")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1])

    async def fake_query(candidate, system_msg, user_msg):
        return aa.AIAdvice(decision="BLOCK", score_delta=0.0, reason="single_block")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert advice is not None
    assert advice.decision == "PASS"
    assert advice.reason == "AI_BLOCK_NOT_CONFIRMED"
    assert "not confirmed" in rs.last_ai_note.lower()


@pytest.mark.asyncio
async def test_ai_consensus_reached_returns_block(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 0)
    monkeypatch.setattr(config, "AI_AUTO_FALLBACK", True)
    monkeypatch.setattr(config, "AI_FAIL_OPEN", True)
    monkeypatch.setattr(config, "AI_CONTINUE_ON_BLOCK", True)
    monkeypatch.setattr(config, "AI_BLOCK_POLICY", "consensus")
    monkeypatch.setattr(config, "AI_BLOCK_REQUIRED", 2)
    monkeypatch.setattr(config, "AI_MAX_SUCCESS_OPINIONS", 2)

    c1 = aa.AICandidate("gemini", "https://g", "k1", "m1")
    c2 = aa.AICandidate("groq", "https://o", "k2", "m2")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1, c2])

    async def fake_query(candidate, system_msg, user_msg):
        if candidate.model == "m1":
            return aa.AIAdvice(decision="BLOCK", score_delta=0.0, reason="block_1")
        return aa.AIAdvice(decision="BLOCK", score_delta=0.0, reason="block_2")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert advice is not None
    assert advice.decision == "BLOCK"
    assert advice.reason == "block_1"
    assert "block_consensus" in rs.last_ai_note.lower()


@pytest.mark.asyncio
async def test_ai_skip_note_when_base_score_too_low(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 80.0)

    rs = RuntimeState()
    advice = await aa.get_trade_advice("LONG", 70.0, rs, None, "BULL")

    assert advice is None
    assert "AI skip: base 70.0 < min 80.0" == rs.last_ai_note


@pytest.mark.asyncio
async def test_ai_skip_note_on_cooldown(monkeypatch):
    import config
    import strategy.ai_advisor as aa
    from state import RuntimeState

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "BACKTEST_MODE", False)
    monkeypatch.setattr(config, "AI_BACKTEST_ENABLED", False)
    monkeypatch.setattr(config, "AI_MIN_BASE_SCORE", 0.0)
    monkeypatch.setattr(config, "AI_MIN_CALL_INTERVAL_SEC", 60)

    c1 = aa.AICandidate("openai", "https://o", "k1", "m1")
    monkeypatch.setattr(aa, "_build_candidates", lambda: [c1])

    async def fake_query(candidate, system_msg, user_msg):
        return aa.AIAdvice(decision="PASS", score_delta=0.0, reason="ok")

    monkeypatch.setattr(aa, "_query_candidate", fake_query)

    rs = RuntimeState()
    first = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")
    second = await aa.get_trade_advice("LONG", 100.0, rs, None, "BULL")

    assert first is not None
    assert second is None
    assert rs.last_ai_note.startswith("AI cooldown:")
