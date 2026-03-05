from __future__ import annotations
from dataclasses import dataclass, field
from models import (
    Position,
    Indicators,
    MarketContext,
    MicrostructureData,
    SentimentData,
    ScoreBreakdown,
)
import json, os, dataclasses, logging

STATE_FILE = "state.json"; STATE_FILE_TMP = "state.json.tmp"; STATE_VERSION = 9

@dataclass
class PersistentState:
    state_version: int=STATE_VERSION; position: Position|None=None
    daily_pnl_usd: float=0.0; daily_pnl_pct: float=0.0
    equity_peak: float=0.0; equity_drawdown_pct: float=0.0
    consecutive_losses: int=0; reduced_size_active: bool=False
    pause_until: float=0.0; last_trade_close: float=0.0
    available_balance: float=0.0; total_equity: float=0.0
    trades_today: int=0; wins_today: int=0; losses_today: int=0
    daily_reset_date: str=""

@dataclass
class RuntimeState:
    indicators: dict[str, Indicators] = field(default_factory=dict)
    context: MarketContext = field(default_factory=MarketContext)
    micro: MicrostructureData = field(default_factory=MicrostructureData)
    sentiment: SentimentData = field(default_factory=SentimentData)
    last_score_breakdown: ScoreBreakdown|None = None
    last_rejection_reason: str = ""
    last_signal_ts: float = 0.0
    last_ai_note: str = ""
    last_ai_ts: float = 0.0

def save(ps: PersistentState) -> None:
    data = dataclasses.asdict(ps)
    with open(STATE_FILE_TMP, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(STATE_FILE_TMP, STATE_FILE)

def load() -> PersistentState:
    if not os.path.exists(STATE_FILE): return PersistentState()
    try:
        with open(STATE_FILE, encoding="utf-8") as f: data = json.load(f)
        if data.get("state_version", 0) != STATE_VERSION:
            logging.warning("state.json устарел, сброс")
            os.replace(STATE_FILE, STATE_FILE + f".v{data.get('state_version',0)}.bak")
            return PersistentState()
        if data.get("position"):
            try: data["position"] = Position(**data["position"])
            except: data["position"] = None
        valid = PersistentState.__dataclass_fields__
        return PersistentState(**{k: v for k, v in data.items() if k in valid})
    except Exception as e:
        logging.error(f"Ошибка загрузки state: {e}")
        os.replace(STATE_FILE, STATE_FILE + ".corrupt")
        return PersistentState()

