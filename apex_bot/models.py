from __future__ import annotations
import dataclasses
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Candle:
    open_time: int;  open: float;  high: float;  low: float
    close: float;    volume: float; close_time: int; is_closed: bool

@dataclass
class AggTrade:
    timestamp_ms: int; price: float; quantity: float; is_buyer_maker: bool

@dataclass
class Indicators:
    ema9: float|None=None; ema21: float|None=None; ema50: float|None=None
    ema200: float|None=None; vwap: float|None=None
    supertrend_dir: Literal["UP","DOWN"]|None=None
    ichimoku_above_cloud: bool|None=None
    adx: float|None=None; di_plus: float|None=None; di_minus: float|None=None
    rsi: float|None=None; stoch_k: float|None=None; stoch_d: float|None=None
    stoch_cross: Literal["bull","bear","none"]|None=None
    macd_line: float|None=None; macd_sig: float|None=None; macd_hist: float|None=None
    macd_cross: Literal["bull","bear","none"]|None=None; macd_cross_age: int|None=None
    atr: float|None=None; atr_pct: float|None=None; atr_avg_24h: float|None=None
    bb_upper: float|None=None; bb_lower: float|None=None; bb_pct_b: float|None=None
    bb_squeeze: bool|None=None
    obv: float|None=None; obv_prev_3: list[float]=field(default_factory=list)
    volume_ratio: float|None=None
    pivot_r1: float|None=None; pivot_s1: float|None=None; last_close: float|None=None
    # v13
    poc: float|None=None
    vah: float|None=None
    val: float|None=None
    htf_trend: Literal["BULL","BEAR","NEUTRAL"]|None=None

@dataclass
class MicrostructureData:
    best_bid: float=0.0; best_ask: float=0.0; spread_pct: float=0.0
    obi: float=0.0; trade_flow_60s: float=0.5
    cvd_60s: float=0.0; cvd_300s: float=0.0
    funding_rate: float=0.0; mark_price: float=0.0; last_updated_ms: int=0

@dataclass
class SentimentData:
    """Fear & Greed Index от alternative.me. 0=Extreme Fear, 100=Extreme Greed."""
    value: int=50
    label: str="Neutral"
    last_updated_ts: float=0.0
    available: bool=False

@dataclass
class MarketContext:
    regime: Literal["TREND","WEAK_TREND","RANGE"]="RANGE"
    trend_dir: Literal["BULL","BEAR","NEUTRAL"]="NEUTRAL"
    size_multiplier: float=1.0
    oi_signal: Literal["BULL_CONFIRMING","BEAR_CONFIRMING","NEUTRAL"]="NEUTRAL"
    ls_ratio: float=0.5; ls_warning: bool=False
    funding_filter_active: bool=False; session_filter_active: bool=False
    should_trade: bool=False

@dataclass
class TradeLevel:
    entry: float; stop: float; tp1: float; tp2: float; tp3: float
    qty_btc: float; qty_tp1: float; qty_tp2: float; qty_tp3: float
    notional_usd: float; margin_usd: float; rr: float; stop_dist_pct: float
    leverage: int

@dataclass
class Signal:
    direction: Literal["LONG","SHORT"]; confidence: float
    score_15m: float; score_5m: float; score_1m: float
    levels: TradeLevel; context: MarketContext; timestamp: int
    rejection_reason: str=""

@dataclass
class ScoreBreakdown:
    """Детальный разбор почему signal получил такой score."""
    direction: str
    ema_score: float=0.0
    vwap_score: float=0.0
    supertrend_score: float=0.0
    ichimoku_score: float=0.0
    macd_score: float=0.0
    rsi_score: float=0.0
    stoch_score: float=0.0
    cvd_score: float=0.0
    obv_score: float=0.0
    volume_score: float=0.0
    obi_score: float=0.0
    flow_score: float=0.0
    funding_score: float=0.0
    poc_score: float=0.0
    htf_score: float=0.0
    sentiment_bonus: float=0.0
    oi_bonus: float=0.0
    squeeze_bonus: float=0.0
    ls_penalty: float=0.0
    weak_trend_penalty: float=0.0
    ai_adjustment: float=0.0
    ai_decision: str=""
    ai_reason: str=""
    total: float=0.0

    def to_str(self) -> str:
        parts = []
        for f in dataclasses.fields(self):
            field_name = f.name
            if field_name in ("direction", "total", "ai_decision", "ai_reason"):
                continue
            val = getattr(self, field_name)
            if isinstance(val, float) and val != 0.0:
                parts.append(f"{field_name}={val:+.0f}")
        if self.ai_decision:
            parts.append(f"ai={self.ai_decision.lower()}")
        if self.ai_reason:
            parts.append(f"ai_reason={self.ai_reason[:24]}")
        return f"[{self.direction}] total={self.total:.1f} | " + " ".join(parts)

@dataclass
class Position:
    direction: Literal["LONG","SHORT"]
    entry_price: float; avg_fill_price: float
    qty_btc: float; qty_remaining: float
    stop_price: float; tp1_price: float; tp2_price: float; tp3_price: float
    stop_order_id: int; tp1_order_id: int; tp2_order_id: int; tp3_order_id: int
    qty_tp1: float; qty_tp2: float; qty_tp3: float
    tp1_filled: bool=False; tp2_filled: bool=False
    realized_pnl_usd: float=0.0; confidence_at_entry: float=0.0
    adx_at_entry: float=0.0; regime_at_entry: str=""
    funding_rate_at_entry: float=0.0; open_timestamp_ms: int=0
    mode: Literal["paper","live"]="paper"
    # v13
    trailing_stop_active: bool=False
    trailing_stop_price: float=0.0
    entry_order_id: int=0
    is_limit_entry: bool=False
    leverage_used: int=0

@dataclass
class PnlResult:
    gross_pnl: float; entry_fee: float; exit_fee: float
    slippage: float; total_costs: float; net_pnl: float
    net_pct_on_margin: float; break_even_price: float

