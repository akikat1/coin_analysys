# ПРАВИЛО: везде "import config; config.X" — НЕ "from config import X"
# Требуется Python 3.11+
import os
import re
from dotenv import load_dotenv

load_dotenv()
_g = os.getenv


def _parse_avoid_hours(raw: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    text = (raw or "").strip()
    if not text:
        return [(2, 5)]

    for chunk in re.split(r"[;,]", text):
        part = chunk.strip()
        if not part:
            continue

        if "-" in part:
            left, right = part.split("-", 1)
        elif ":" in part:
            left, right = part.split(":", 1)
        else:
            continue

        try:
            h_from = int(float(left.strip()))
            h_to = int(float(right.strip()))
        except Exception:
            continue

        h_from = max(0, min(23, h_from))
        h_to = max(0, min(23, h_to))

        if h_from <= h_to:
            windows.append((h_from, h_to))
        else:
            # Cross-midnight window, e.g. 22-2 -> (22,23) + (0,2).
            windows.append((h_from, 23))
            windows.append((0, h_to))

    return windows or [(2, 5)]

BINANCE_API_KEY = _g("BINANCE_API_KEY", "")
BINANCE_API_SECRET = _g("BINANCE_API_SECRET", "")
TESTNET = _g("TESTNET", "true").lower() in ("true", "1", "yes")
REST_BASE = "https://testnet.binancefuture.com" if TESTNET else "https://fapi.binance.com"
WS_BASE = "wss://fstream.binancefuture.com" if TESTNET else "wss://fstream.binance.com"
PAPER_MODE: bool = False
BACKTEST_MODE: bool = False

SYMBOL = "BTCUSDT"
LEVERAGE = int(float(_g("LEVERAGE", "10")))
MAX_LEVERAGE = int(float(_g("MAX_LEVERAGE", "20")))
MIN_LEVERAGE = int(float(_g("MIN_LEVERAGE", "3")))
ATR_PCT_HIGH_VOLATILITY = float(_g("ATR_PCT_HIGH_VOLATILITY", "0.8"))
MARGIN_TYPE = "ISOLATED"

ADX_TREND_THRESHOLD = float(_g("ADX_TREND_THRESHOLD", "25"))
ADX_WEAK_TREND_THRESHOLD = float(_g("ADX_WEAK_TREND_THRESHOLD", "20"))
MIN_CONFIDENCE = float(_g("MIN_CONFIDENCE", "72"))
MIN_RR = float(_g("MIN_RR", "2.0"))
MIN_VOLUME_RATIO = float(_g("MIN_VOLUME_RATIO", "1.2"))
MAX_RISK_PER_TRADE_PCT = float(_g("MAX_RISK_PER_TRADE_PCT", "0.01"))
MAX_DAILY_LOSS_PCT = float(_g("MAX_DAILY_LOSS_PCT", "0.05"))
MAX_DRAWDOWN_PCT = float(_g("MAX_DRAWDOWN_PCT", "0.15"))
MAX_CONSECUTIVE_LOSSES = 3
REDUCED_SIZE_MULTIPLIER = 0.5
MIN_BALANCE_USD = float(_g("MIN_BALANCE_USD", "50.0"))
MAX_POSITION_DURATION_SEC = int(float(_g("MAX_POSITION_DURATION_SEC", str(4 * 3600))))

SIGNAL_COOLDOWN_SEC = int(float(_g("SIGNAL_COOLDOWN_SEC", str(5 * 60))))
MAX_TRADES_PER_DAY = int(float(_g("MAX_TRADES_PER_DAY", "10")))
SIGNAL_MAX_AGE_SEC = 10
TAKER_FEE = 0.0004
MAKER_FEE = 0.0002
SLIPPAGE_ESTIMATE = 0.0002
BNB_DISCOUNT = _g("BNB_DISCOUNT", "false").lower() in ("true", "1", "yes")
FUNDING_TIMES_UTC = [0, 8, 16]
FUNDING_AVOID_WINDOW_SEC = 15 * 60
FUNDING_HIGH_THRESHOLD = 0.001

USE_LIMIT_ORDER = _g("USE_LIMIT_ORDER", "true").lower() in ("true", "1", "yes")
LIMIT_ORDER_OFFSET_PCT = float(_g("LIMIT_ORDER_OFFSET_PCT", "0.0002"))
LIMIT_ORDER_TIMEOUT_SEC = int(float(_g("LIMIT_ORDER_TIMEOUT_SEC", "8")))
PARTIAL_FILL_MIN_PCT = 0.5
AVOID_HOURS_UTC = _parse_avoid_hours(_g("AVOID_HOURS_UTC", "2-5"))

TRAILING_STOP_ENABLED = _g("TRAILING_STOP_ENABLED", "true").lower() in ("true", "1", "yes")
TRAILING_ATR_MULTIPLIER = float(_g("TRAILING_ATR_MULTIPLIER", "1.2"))

MAX_SPREAD_PCT = float(_g("MAX_SPREAD_PCT", "0.0005"))
MAX_ATR_MULTIPLIER = 3.0
MIN_POSITION_NOTIONAL = 6.0
MAX_REST_WEIGHT_MIN = 1100
MAX_MICROSTRUCTURE_STALENESS_MS = int(float(_g("MAX_MICROSTRUCTURE_STALENESS_MS", "2000")))
DEADMAN_SWITCH_SEC = int(float(_g("DEADMAN_SWITCH_SEC", "15")))
WS_RECONNECT_DELAY_SEC = 2
WS_HEARTBEAT_SEC = 30

TELEGRAM_TOKEN = _g("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = _g("TELEGRAM_CHAT_ID", "")
TELEGRAM_COMMANDS_ENABLED = _g("TELEGRAM_COMMANDS_ENABLED", "true").lower() in ("true", "1", "yes")

HTF_TIMEFRAME = _g("HTF_TIMEFRAME", "1h")
HTF_MIN_CANDLES = int(float(_g("HTF_MIN_CANDLES", "100")))
HTF_ADX_THRESHOLD = float(_g("HTF_ADX_THRESHOLD", "22"))

LOG_MAX_BYTES = int(float(_g("LOG_MAX_BYTES", str(10 * 1024 * 1024))))
LOG_BACKUP_COUNT = int(float(_g("LOG_BACKUP_COUNT", "5")))

VP_BINS = int(float(_g("VP_BINS", "50")))
VP_VALUE_AREA_PCT = float(_g("VP_VALUE_AREA_PCT", "0.70"))

POSITION_SYNC_ON_START = _g("POSITION_SYNC_ON_START", "true").lower() in ("true", "1", "yes")
MARKET_CONTEXT_REFRESH_SEC = int(float(_g("MARKET_CONTEXT_REFRESH_SEC", "30")))
ALLOW_RANGE_TRADING = _g("ALLOW_RANGE_TRADING", "false").lower() in ("true", "1", "yes")
RANGE_SIZE_MULTIPLIER = float(_g("RANGE_SIZE_MULTIPLIER", "0.35"))
HTF_FILTER_ENABLED = _g("HTF_FILTER_ENABLED", "true").lower() in ("true", "1", "yes")
ENFORCE_VOLUME_FILTER = _g("ENFORCE_VOLUME_FILTER", "true").lower() in ("true", "1", "yes")

# Live smoke-test: обязательная микросделка при старте live
LIVE_SMOKE_TEST_ON_START = _g("LIVE_SMOKE_TEST_ON_START", "false").lower() in ("true", "1", "yes")
LIVE_SMOKE_MAX_WAIT_SEC = int(float(_g("LIVE_SMOKE_MAX_WAIT_SEC", "30")))
LIVE_SMOKE_HOLD_SEC = int(float(_g("LIVE_SMOKE_HOLD_SEC", "20")))
LIVE_SMOKE_NOTIONAL_USDT = float(_g("LIVE_SMOKE_NOTIONAL_USDT", "6"))
LIVE_SMOKE_ALLOW_MAINNET = _g("LIVE_SMOKE_ALLOW_MAINNET", "false").lower() in ("true", "1", "yes")

# Fear & Greed Index (alternative.me — бесплатно, без API ключа)
SENTIMENT_UPDATE_INTERVAL_SEC = 300
SENTIMENT_EXTREME_FEAR_THRESHOLD = 25
SENTIMENT_EXTREME_GREED_THRESHOLD = 75
SENTIMENT_SCORE_BONUS = 5

# Optional AI advisor (OpenAI-compatible or Gemini generateContent)
AI_ENABLED = _g("AI_ENABLED", "false").lower() in ("true", "1", "yes")
AI_MODE = _g("AI_MODE", "assist").strip().lower()  # assist | gate | hybrid
if AI_MODE not in ("assist", "gate", "hybrid"):
    AI_MODE = "assist"
AI_PROVIDER = _g("AI_PROVIDER", "auto").strip().lower()  # auto | openai | gemini | groq
if AI_PROVIDER not in ("auto", "openai", "gemini", "groq"):
    AI_PROVIDER = "auto"
AI_API_KEY = _g("AI_API_KEY", "")
AI_BASE_URL = _g("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = _g("AI_MODEL", "gpt-4o-mini")
AI_TIMEOUT_SEC = float(_g("AI_TIMEOUT_SEC", "4.0"))
AI_MAX_SCORE_ADJUST = float(_g("AI_MAX_SCORE_ADJUST", "8.0"))
AI_MIN_BASE_SCORE = float(_g("AI_MIN_BASE_SCORE", "60.0"))
AI_MIN_CALL_INTERVAL_SEC = int(float(_g("AI_MIN_CALL_INTERVAL_SEC", "20")))
AI_FAIL_OPEN = _g("AI_FAIL_OPEN", "true").lower() in ("true", "1", "yes")
AI_BACKTEST_ENABLED = _g("AI_BACKTEST_ENABLED", "false").lower() in ("true", "1", "yes")

# Failover pool (provider -> key -> model)
AI_PROVIDER_PRIORITY = _g("AI_PROVIDER_PRIORITY", "gemini,groq,openai")
AI_AUTO_FALLBACK = _g("AI_AUTO_FALLBACK", "true").lower() in ("true", "1", "yes")
AI_MAX_CANDIDATES = int(float(_g("AI_MAX_CANDIDATES", "24")))
AI_CONTINUE_ON_BLOCK = _g("AI_CONTINUE_ON_BLOCK", "false").lower() in ("true", "1", "yes")
AI_BLOCK_POLICY = _g("AI_BLOCK_POLICY", "first").strip().lower()  # first | consensus
if AI_BLOCK_POLICY not in ("first", "consensus"):
    AI_BLOCK_POLICY = "first"
AI_BLOCK_REQUIRED = int(float(_g("AI_BLOCK_REQUIRED", "2")))
AI_MAX_SUCCESS_OPINIONS = int(float(_g("AI_MAX_SUCCESS_OPINIONS", "3")))

# Gemini pool
AI_GEMINI_BASE_URL = _g("AI_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
AI_GEMINI_API_KEYS = _g("AI_GEMINI_API_KEYS", "")
AI_GEMINI_MODELS = _g(
    "AI_GEMINI_MODELS",
    "gemini-2.0-flash,gemini-2.0-flash-lite,gemini-1.5-pro",
)

# Groq pool (OpenAI-compatible chat/completions)
AI_GROQ_BASE_URL = _g("AI_GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
AI_GROQ_API_KEYS = _g("AI_GROQ_API_KEYS", "")
AI_GROQ_MODELS = _g(
    "AI_GROQ_MODELS",
    "llama-3.3-70b-versatile,llama-3.1-8b-instant",
)

# OpenAI pool
AI_OPENAI_BASE_URL = _g("AI_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_OPENAI_API_KEYS = _g("AI_OPENAI_API_KEYS", "")
AI_OPENAI_MODELS = _g("AI_OPENAI_MODELS", "gpt-4o-mini,gpt-4.1-mini")

