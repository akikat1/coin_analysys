# TZ Audit v12+v13

Generated: 2026-03-05

## Summary

- Overall: mostly compliant with v12+v13.
- Key gap fixed in this iteration: `paper` now uses market-context enrichment (`OI` + `Long/Short`) with safe fallback.
- AI runtime profile aligned to `hybrid + consensus + failover`.

## Checklist

### PASS

- 1-second signal loop (`paper/live`): `main.py:216`, `main.py:355`
- Multi-timeframe analysis `1h/15m/5m/1m`: `main.py:322`, `backtest/paper_engine.py:21`
- Orderbook/microstructure ingestion (`depth20@100ms`, `bookTicker`, `markPrice@1s`, `aggTrade`): `data/collector.py:71`, `data/collector.py:72`, `data/collector.py:118`, `data/collector.py:130`
- Indicator stack (ADX/RSI/MACD/Supertrend/Ichimoku/StochRSI/OBV/VP): `data/indicators.py:28`, `data/indicators.py:42`, `data/indicators.py:47`, `data/indicators.py:63`, `data/indicators.py:107`
- HTF filter + score breakdown + dynamic leverage: `strategy/signal_engine.py:222`, `strategy/signal_engine.py:303`, `strategy/signal_engine.py:317`
- Limit entry with timeout fallback: `execution/order_manager.py:86`, `execution/order_manager.py:106`, `execution/order_manager.py:131`
- Position sync on startup: `main.py:292`, `execution/position_sync.py:24`
- Trailing stop after TP1: `main.py:331`, `execution/position_tracker.py:142`
- Telegram commands: `main.py:236`, `monitor/telegram_commands.py:28`
- HTML reports for backtest/walkforward: `main.py:165`, `backtest/walk_forward.py:44`
- Log rotation + hot reload: `main.py:46`, `main.py:47`, `main.py:125`

### PARTIAL (before this patch)

- Paper mode was using `_build_regime` only and missed `OI/L-S` enrichment.
  - Previous location: `backtest/paper_engine.py:30`
  - Fixed now: `backtest/paper_engine.py:31`

### FIXED IN THIS PATCH

- `paper` now calls `data.market_context.update(rs, cs)` and falls back to `_build_regime(...)` on exception:
  - `backtest/paper_engine.py:18`
  - `backtest/paper_engine.py:31`
  - `backtest/paper_engine.py:34`
- Added testnet-safe handling for Long/Short endpoint (skip noisy unsupported call on TESTNET):
  - `data/market_context.py:99`
  - `data/market_context.py:101`
- AI configuration profile normalized in local runtime `.env`:
  - `AI_MODE=hybrid`
  - `AI_CONTINUE_ON_BLOCK=true`
  - `AI_BLOCK_POLICY=consensus`
  - `AI_BLOCK_REQUIRED=2`
  - `AI_MAX_SUCCESS_OPINIONS=3`
  - `AI_PROVIDER_PRIORITY=gemini,groq,openai`
  - `AI_AUTO_FALLBACK=true`
  - `AI_TIMEOUT_SEC=10`
  - `AI_MIN_CALL_INTERVAL_SEC=2`
  - `AI_MIN_BASE_SCORE=58`
  - `AI_FAIL_OPEN=true`
  - `AI_API_KEY=` (primary candidate disabled intentionally)
- `.env.example` updated to reflect recommended profile defaults:
  - `\.env.example:63`
  - `\.env.example:68`
  - `\.env.example:75`
- `README.md` updated with recommended `hybrid + consensus` runtime profile:
  - `README.md:36`
  - `README.md:41`

## Tests

- Existing AI failover/consensus unit tests cover:
  - fallback to next candidate on transport/provider errors
  - `continue-on-block` behavior
  - consensus block thresholds
  - file: `tests/test_ai_advisor_failover.py`
- Added in this iteration:
  - `paper` uses `market_context.update`: `tests/test_paper_engine.py`
  - `paper` fallback to `_build_regime` on update error: `tests/test_paper_engine.py`
  - `hybrid` integration (veto + score adjustment): `tests/test_ai_advisor_integration.py`
