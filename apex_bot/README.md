## APEX BOT (v13 merge)

Р РµР¶РёРјС‹:
- `backtest`
- `walkforward`
- `paper`
- `live`

Р—Р°РїСѓСЃРє:
```bat
cd C:\Users\akika\Downloads\VS_code_projects\coin_analysys\apex_bot
python -m pip install -r requirements.txt
python -m pytest -q
python main.py --mode backtest --days 30
python main.py --mode paper
python main.py --mode live
```

### Р§С‚Рѕ СЂРµР°Р»РёР·РѕРІР°РЅРѕ РІ live
- РњРЅРѕРіРѕС‚Р°Р№РјС„СЂРµР№Рј Р°РЅР°Р»РёР· `1h/15m/5m/1m`.
- HTF master filter (РЅРµ С‚РѕСЂРіСѓРµС‚ РїСЂРѕС‚РёРІ С‚СЂРµРЅРґР° `1h`).
- Volume Profile (`POC/VAH/VAL`) РІ scoring.
- Dynamic leverage (С‡РµСЂРµР· `leverage_override` РІ risk manager).
- Limit entry (`GTX`) СЃ fallback РІ market РїРѕ С‚Р°Р№РјР°СѓС‚Сѓ.
- Position sync РїСЂРё СЃС‚Р°СЂС‚Рµ (`/fapi/v2/positionRisk` + open orders).
- Trailing stop РїРѕСЃР»Рµ TP1 (`ATR * TRAILING_ATR_MULTIPLIER`).
- Telegram commands: `/status /close /pause /resume /report /help`.
- Rotating logs (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`).
- Hot reload `.env` (`mtime` polling + `SIGHUP`).
- Optional AI advisor for signal assist/gate/hybrid (OpenAI-compatible or Gemini API).
- Paper mode now enriches market context via `OI/L-S` like live (with safe fallback on API errors).

### AI advisor (optional)
Р’ `.env`:
```env
AI_ENABLED=true
AI_MODE=hybrid          # assist | gate | hybrid
AI_PROVIDER=auto        # auto | openai | gemini | groq
AI_PROVIDER_PRIORITY=gemini,groq,openai
AI_AUTO_FALLBACK=true
AI_MAX_CANDIDATES=24
AI_CONTINUE_ON_BLOCK=true   # keep asking next model after BLOCK
AI_BLOCK_POLICY=consensus   # first | consensus
AI_BLOCK_REQUIRED=2         # for consensus mode
AI_MAX_SUCCESS_OPINIONS=3   # max successful answers per decision
AI_API_KEY=              # keep empty to avoid sticky primary candidate
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
AI_TIMEOUT_SEC=10
AI_MAX_SCORE_ADJUST=8
AI_MIN_BASE_SCORE=58
AI_MIN_CALL_INTERVAL_SEC=2
AI_FAIL_OPEN=true
AI_BACKTEST_ENABLED=false
```

Р РµР¶РёРјС‹:
- `assist`: РР РґРѕР±Р°РІР»СЏРµС‚/СЃРЅРёРјР°РµС‚ РѕС‡РєРё confidence.
- `gate`: РР С‚РѕР»СЊРєРѕ veto/allow (Р±РµР· score_delta).
- `hybrid`: Рё score_delta, Рё veto.

Failover:
- `AI_CONTINUE_ON_BLOCK=true`: BLOCK from one model is not final, ask next model.
- `AI_BLOCK_POLICY=first`: if all successful answers are BLOCK, return first BLOCK.
- `AI_BLOCK_POLICY=consensus`: BLOCK only when collected at least `AI_BLOCK_REQUIRED` BLOCK answers.
- Р±РѕС‚ РїРµСЂРµР±РёСЂР°РµС‚ РєР°РЅРґРёРґР°С‚РѕРІ РІ РїРѕСЂСЏРґРєРµ `AI_PROVIDER_PRIORITY`;
- РІРЅСѓС‚СЂРё РєР°Р¶РґРѕРіРѕ РїСЂРѕРІР°Р№РґРµСЂР° РїРµСЂРµР±РёСЂР°СЋС‚СЃСЏ РІСЃРµ `API_KEYS x MODELS`;
- РїСЂРё `429/timeout/5xx/invalid key/model` РёРґРµС‚ РЅР° СЃР»РµРґСѓСЋС‰РёР№ РєР°РЅРґРёРґР°С‚;
- РµСЃР»Рё РёСЃС‡РµСЂРїР°Р» СЃРїРёСЃРѕРє: РїСЂРё `AI_FAIL_OPEN=true` РїСЂРѕРґРѕР»Р¶Р°РµС‚ Р±РµР· РР, РёРЅР°С‡Рµ Р±Р»РѕРєРёСЂСѓРµС‚ РІС…РѕРґ.

Gemini РїСЂРёРјРµСЂ:
```env
AI_ENABLED=true
AI_MODE=assist
AI_PROVIDER=gemini
AI_API_KEY=...
AI_BASE_URL=https://generativelanguage.googleapis.com
AI_MODEL=gemini-2.5-flash
```

Gemini + Groq multi-key/multi-model РїСЂРёРјРµСЂ:
```env
AI_ENABLED=true
AI_MODE=assist
AI_PROVIDER_PRIORITY=gemini,groq,openai
AI_AUTO_FALLBACK=true
AI_FAIL_OPEN=true

AI_GEMINI_API_KEYS=gem_key_a,gem_key_b
AI_GEMINI_MODELS=gemini-2.0-flash,gemini-1.5-pro

AI_GROQ_API_KEYS=groq_key_a,groq_key_b
AI_GROQ_MODELS=llama-3.3-70b-versatile,llama-3.1-8b-instant
```

### РћС‚С‡С‘С‚С‹
- РџРѕСЃР»Рµ `backtest` Рё `walkforward` РіРµРЅРµСЂРёСЂСѓСЋС‚СЃСЏ HTML-РѕС‚С‡С‘С‚С‹ РІ `reports/`.
- Р¤Р°Р№Р» РѕС‚РєСЂС‹РІР°РµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.

### Р’Р°Р¶РЅРѕ
- `TESTNET=true` РґР»СЏ Р±РµР·РѕРїР°СЃРЅРѕР№ РїСЂРѕРІРµСЂРєРё.
- Р”Р»СЏ РѕР±С‹С‡РЅРѕР№ С‚РѕСЂРіРѕРІР»Рё РѕС‚РєР»СЋС‡Рё СЃС‚Р°СЂС‚РѕРІС‹Р№ smoke-test:
  `LIVE_SMOKE_TEST_ON_START=false`
- Р”Р»СЏ smoke-test (РїСЂРѕРІРµСЂРєР° РїР°Р№РїР»Р°Р№РЅР°):
  `LIVE_SMOKE_TEST_ON_START=true`  
  Р’С…РѕРґ РґРѕ `LIVE_SMOKE_MAX_WAIT_SEC`, РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕРµ Р·Р°РєСЂС‹С‚РёРµ С‡РµСЂРµР· `LIVE_SMOKE_HOLD_SEC`.

Recommended runtime profile (Gemini -> Groq failover, hybrid + consensus):
```env
AI_ENABLED=true
AI_MODE=hybrid
AI_PROVIDER=auto
AI_PROVIDER_PRIORITY=gemini,groq,openai
AI_AUTO_FALLBACK=true
AI_FAIL_OPEN=true
AI_CONTINUE_ON_BLOCK=true
AI_BLOCK_POLICY=consensus
AI_BLOCK_REQUIRED=2
AI_MAX_SUCCESS_OPINIONS=3
AI_API_KEY=
AI_TIMEOUT_SEC=10
AI_MIN_BASE_SCORE=58
AI_MIN_CALL_INTERVAL_SEC=2

AI_GEMINI_API_KEYS=gem_key_a,gem_key_b
AI_GEMINI_MODELS=gemini-2.0-flash,gemini-2.0-flash-lite,gemini-1.5-pro

AI_GROQ_API_KEYS=groq_key_a,groq_key_b
AI_GROQ_MODELS=llama-3.3-70b-versatile,llama-3.1-8b-instant
```
