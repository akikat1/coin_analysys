from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

import config
from state import RuntimeState


@dataclass
class AIAdvice:
    decision: str = "PASS"  # ALLOW | BLOCK | PASS
    score_delta: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class AICandidate:
    provider: str  # gemini | groq | openai
    base_url: str
    api_key: str
    model: str


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _split_list(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    out = []
    for p in parts:
        item = p.strip().strip('"').strip("'")
        if item:
            out.append(item)
    return out


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    raw = text.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    block = re.search(r"\{.*\}", raw, flags=re.S)
    if not block:
        return None
    try:
        obj = json.loads(block.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _parse_advice(content: str) -> AIAdvice:
    obj = _extract_json(content)
    if not obj:
        raise ValueError("AI response is not JSON")

    decision = str(obj.get("decision", "PASS")).strip().upper()
    if decision not in {"ALLOW", "BLOCK", "PASS"}:
        decision = "PASS"

    try:
        score_delta = float(obj.get("score_delta", 0.0) or 0.0)
    except Exception:
        score_delta = 0.0
    score_delta = _clamp(score_delta, -config.AI_MAX_SCORE_ADJUST, config.AI_MAX_SCORE_ADJUST)

    reason = str(obj.get("reason", "") or "").replace("\n", " ").strip()
    if len(reason) > 140:
        reason = reason[:140]

    return AIAdvice(decision=decision, score_delta=score_delta, reason=reason)


def _make_prompt_payload(direction: str, base_score: float, rs: RuntimeState, ind_15, htf_dir: str) -> dict:
    return {
        "direction": direction,
        "base_score": round(base_score, 2),
        "market_regime": rs.context.regime,
        "trend_dir": rs.context.trend_dir,
        "htf_dir": htf_dir,
        "micro": {
            "spread_pct": round(rs.micro.spread_pct, 6),
            "obi": round(rs.micro.obi, 4),
            "flow_60s": round(rs.micro.trade_flow_60s, 4),
            "cvd_300s": round(rs.micro.cvd_300s, 4),
            "funding_rate": round(rs.micro.funding_rate, 6),
            "mark_price": round(rs.micro.mark_price, 2),
        },
        "ind_15m": {
            "adx": round(ind_15.adx, 2) if ind_15 and ind_15.adx is not None else None,
            "rsi": round(ind_15.rsi, 2) if ind_15 and ind_15.rsi is not None else None,
            "atr_pct": round(ind_15.atr_pct, 4) if ind_15 and ind_15.atr_pct is not None else None,
            "volume_ratio": round(ind_15.volume_ratio, 4)
            if ind_15 and ind_15.volume_ratio is not None
            else None,
        },
        "sentiment": {
            "available": rs.sentiment.available,
            "value": rs.sentiment.value if rs.sentiment.available else None,
            "label": rs.sentiment.label if rs.sentiment.available else None,
        },
        "rules": {
            "mode": config.AI_MODE,
            "max_score_adjust": config.AI_MAX_SCORE_ADJUST,
            "min_confidence": config.MIN_CONFIDENCE,
        },
    }


def _detect_provider() -> str:
    provider = (config.AI_PROVIDER or "auto").strip().lower()
    if provider in ("openai", "gemini", "groq"):
        return provider

    base = (config.AI_BASE_URL or "").strip().lower()
    if "generativelanguage.googleapis.com" in base and "/openai" not in base:
        return "gemini"
    if "groq.com" in base:
        return "groq"
    return "openai"


def _extract_openai_content(data: dict) -> str:
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if isinstance(content, list):
        txt = "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict)
        )
        content = txt
    content = str(content or "").strip()
    if not content:
        raise ValueError("OpenAI-compatible response content is empty")
    return content


def _extract_gemini_content(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason", "NO_CANDIDATES")
        raise ValueError(f"Gemini returned no candidates ({block_reason})")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if text:
        return text

    finish_reason = candidates[0].get("finishReason", "EMPTY")
    raise ValueError(f"Gemini empty response ({finish_reason})")


def _build_openai_request(candidate: AICandidate, system_msg: str, user_msg: str) -> tuple[str, dict, dict]:
    body = {
        "model": candidate.model,
        "temperature": 0,
        "max_tokens": 180,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }
    base = candidate.base_url.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {candidate.api_key}",
        "Content-Type": "application/json",
    }
    return url, headers, body


def _build_gemini_request(candidate: AICandidate, system_msg: str, user_msg: str) -> tuple[str, dict, dict]:
    base = candidate.base_url.rstrip("/")
    if not re.search(r"/v\d+(beta)?$", base):
        base = f"{base}/v1beta"

    url = f"{base}/models/{candidate.model}:generateContent"
    headers = {
        "x-goog-api-key": candidate.api_key,
        "Content-Type": "application/json",
    }
    body = {
        "systemInstruction": {"parts": [{"text": system_msg}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 220,
        },
    }
    return url, headers, body


def _build_candidates() -> list[AICandidate]:
    def add_candidate(
        out: list[AICandidate],
        seen: set[tuple[str, str, str, str]],
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        if not (provider and base_url and api_key and model):
            return
        key = (provider.strip().lower(), base_url.strip(), api_key.strip(), model.strip())
        if key in seen:
            return
        seen.add(key)
        out.append(
            AICandidate(
                provider=provider.strip().lower(),
                base_url=base_url.strip().rstrip("/"),
                api_key=api_key.strip(),
                model=model.strip(),
            )
        )

    candidates: list[AICandidate] = []
    seen: set[tuple[str, str, str, str]] = set()

    # Backward compatible primary candidate.
    primary_provider = _detect_provider()
    add_candidate(candidates, seen, primary_provider, config.AI_BASE_URL, config.AI_API_KEY, config.AI_MODEL)

    priority = [p.lower() for p in _split_list(config.AI_PROVIDER_PRIORITY) if p.lower() in ("gemini", "groq", "openai")]
    if not priority:
        priority = ["gemini", "groq", "openai"]

    for provider in priority:
        if provider == "gemini":
            base_url = config.AI_GEMINI_BASE_URL
            keys = _split_list(config.AI_GEMINI_API_KEYS)
            models = _split_list(config.AI_GEMINI_MODELS)
            if not keys and primary_provider == "gemini" and config.AI_API_KEY:
                keys = [config.AI_API_KEY]
            if not models:
                models = [config.AI_MODEL] if (primary_provider == "gemini" and config.AI_MODEL) else ["gemini-2.0-flash"]
        elif provider == "groq":
            base_url = config.AI_GROQ_BASE_URL
            keys = _split_list(config.AI_GROQ_API_KEYS)
            models = _split_list(config.AI_GROQ_MODELS)
            if not models:
                models = ["llama-3.1-8b-instant"]
        else:
            base_url = config.AI_OPENAI_BASE_URL
            keys = _split_list(config.AI_OPENAI_API_KEYS)
            models = _split_list(config.AI_OPENAI_MODELS)
            if not keys and primary_provider == "openai" and config.AI_API_KEY:
                keys = [config.AI_API_KEY]
            if not models:
                models = [config.AI_MODEL] if (primary_provider == "openai" and config.AI_MODEL) else ["gpt-4o-mini"]

        for key in keys:
            for model in models:
                add_candidate(candidates, seen, provider, base_url, key, model)

    max_n = max(1, int(config.AI_MAX_CANDIDATES))
    return candidates[:max_n]


async def _query_candidate(candidate: AICandidate, system_msg: str, user_msg: str) -> AIAdvice:
    if candidate.provider == "gemini":
        url, headers, body = _build_gemini_request(candidate, system_msg, user_msg)
        parser = _extract_gemini_content
    else:
        # groq uses OpenAI-compatible endpoint.
        url, headers, body = _build_openai_request(candidate, system_msg, user_msg)
        parser = _extract_openai_content

    async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_SEC) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    content = parser(data)
    return _parse_advice(content)


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        return status in {400, 401, 403, 404, 408, 409, 425, 429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError, ValueError))


async def get_trade_advice(
    direction: str,
    base_score: float,
    rs: RuntimeState,
    ind_15,
    htf_dir: str,
) -> AIAdvice | None:
    if not config.AI_ENABLED:
        rs.last_ai_note = "AI disabled: AI_ENABLED=false"
        return None
    if config.BACKTEST_MODE and not config.AI_BACKTEST_ENABLED:
        rs.last_ai_note = "AI disabled in backtest"
        return None
    if base_score < config.AI_MIN_BASE_SCORE:
        rs.last_ai_note = (
            f"AI skip: base {base_score:.1f} < min {config.AI_MIN_BASE_SCORE:.1f}"
        )
        return None

    now = time.time()
    if rs.last_ai_ts and (now - rs.last_ai_ts) < config.AI_MIN_CALL_INTERVAL_SEC:
        wait_left = config.AI_MIN_CALL_INTERVAL_SEC - (now - rs.last_ai_ts)
        rs.last_ai_note = f"AI cooldown: {max(wait_left, 0.0):.1f}s left"
        return None
    rs.last_ai_ts = now

    candidates = _build_candidates()
    if not candidates:
        rs.last_ai_note = "AI disabled: no configured provider/key/model"
        return None

    rs.last_ai_note = f"AI querying: {len(candidates)} candidate(s)"

    payload = _make_prompt_payload(direction, base_score, rs, ind_15, htf_dir)
    system_msg = (
        "You are a strict BTCUSDT futures scalping risk assistant. "
        "Return only JSON with keys: decision, score_delta, reason. "
        "decision must be one of ALLOW, BLOCK, PASS. "
        "score_delta must be numeric in range [-max_score_adjust, max_score_adjust]. "
        "Use BLOCK only on strong contradiction or danger."
    )
    user_msg = json.dumps(payload, ensure_ascii=False)

    continue_on_block = bool(config.AI_CONTINUE_ON_BLOCK)
    block_policy = (config.AI_BLOCK_POLICY or "first").strip().lower()
    if block_policy not in ("first", "consensus"):
        block_policy = "first"
    block_required = max(1, int(config.AI_BLOCK_REQUIRED))
    max_success_opinions = max(1, int(config.AI_MAX_SUCCESS_OPINIONS))

    errors: list[str] = []
    successful_opinions = 0
    block_opinions: list[tuple[AICandidate, AIAdvice]] = []
    for idx, candidate in enumerate(candidates, start=1):
        try:
            advice = await _query_candidate(candidate, system_msg, user_msg)
            successful_opinions += 1

            # Default behavior: first successful answer decides.
            if advice.decision != "BLOCK" or not continue_on_block:
                rs.last_ai_note = f"{candidate.provider}:{candidate.model}:{advice.decision}"
                if idx > 1:
                    logging.info(
                        "ai_advisor: fallback success on #%s %s/%s",
                        idx,
                        candidate.provider,
                        candidate.model,
                    )
                return advice

            # Optional second-opinion mode: collect BLOCK and keep querying.
            block_opinions.append((candidate, advice))
            rs.last_ai_note = (
                f"{candidate.provider}:{candidate.model}:BLOCK "
                f"({len(block_opinions)}/{successful_opinions})"
            )
            logging.info(
                "ai_advisor: block opinion #%s from %s/%s (%s/%s)",
                len(block_opinions),
                candidate.provider,
                candidate.model,
                len(block_opinions),
                max_success_opinions,
            )

            if successful_opinions >= max_success_opinions:
                break
        except Exception as e:
            err_label = f"{candidate.provider}:{candidate.model}:{e.__class__.__name__}"
            if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                err_label = f"{candidate.provider}:{candidate.model}:HTTP{e.response.status_code}"
            errors.append(err_label)
            logging.warning(f"ai_advisor: {err_label}")

            is_last = idx >= len(candidates)
            if is_last:
                break
            if not config.AI_AUTO_FALLBACK:
                break
            if not _is_retryable_error(e):
                break

    if block_opinions:
        first_candidate, first_block = block_opinions[0]
        if block_policy == "consensus":
            if len(block_opinions) >= block_required:
                rs.last_ai_note = (
                    f"{first_candidate.provider}:{first_candidate.model}:"
                    f"BLOCK_CONSENSUS({len(block_opinions)}/{successful_opinions})"
                )
                return first_block
            rs.last_ai_note = (
                f"AI block not confirmed ({len(block_opinions)}/{successful_opinions}); PASS"
            )
            return AIAdvice(decision="PASS", score_delta=0.0, reason="AI_BLOCK_NOT_CONFIRMED")

        rs.last_ai_note = (
            f"{first_candidate.provider}:{first_candidate.model}:"
            f"BLOCK_FIRST({len(block_opinions)}/{successful_opinions})"
        )
        return first_block

    rs.last_ai_note = f"AI exhausted: {errors[0]}" if errors else "AI exhausted"
    if config.AI_FAIL_OPEN:
        return None
    return AIAdvice(decision="BLOCK", score_delta=0.0, reason="AI_ERROR_FAIL_CLOSED")
