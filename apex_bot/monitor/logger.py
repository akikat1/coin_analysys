import csv, os, time
from models import Position, PnlResult

TRADES_LOG  = "logs/trades_log.csv"
SIGNALS_LOG = "logs/signals_log.csv"

TRADES_HDR = ["ts_open","ts_close","direction","entry_price","avg_fill","exit_price",
              "qty_btc","closed_qty","leverage","margin_usd","gross_pnl","entry_fee",
              "exit_fee","slippage","net_pnl_partial","realized_total","net_pct_margin",
              "duration_sec","exit_reason","confidence","adx_entry","regime_entry",
              "funding_entry","mode"]
SIGNALS_HDR = ["timestamp","direction","score","s15","s5","s1","passed","rejection",
               "rr","adx","regime","spread_pct","vol_ratio","fear_greed","score_breakdown"]

def _init(path, header):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)

def log_trade(pos: Position, exit_price: float, closed_qty: float,
              reason: str, pnl: PnlResult, total_net: float):
    _init(TRADES_LOG, TRADES_HDR)
    import config
    lev = pos.leverage_used if getattr(pos, "leverage_used", 0) > 0 else config.LEVERAGE
    now = int(time.time()*1000); dur = (now - pos.open_timestamp_ms) // 1000
    with open(TRADES_LOG, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            pos.open_timestamp_ms, now, pos.direction, pos.entry_price, pos.avg_fill_price,
            exit_price, pos.qty_btc, closed_qty, lev,
            (pos.qty_btc*pos.entry_price)/lev,
            pnl.gross_pnl, pnl.entry_fee, pnl.exit_fee, pnl.slippage,
            pnl.net_pnl, total_net, pnl.net_pct_on_margin, dur, reason,
            pos.confidence_at_entry, pos.adx_at_entry, pos.regime_at_entry,
            pos.funding_rate_at_entry, pos.mode])

def log_signal(direction: str, score: float, s15: float, s5: float, s1: float,
               passed: bool, rejection: str, rr: float,
               adx: float, regime: str, spread: float, vol_ratio: float,
               fear_greed: int = -1, score_breakdown: str = ""):
    _init(SIGNALS_LOG, SIGNALS_HDR)
    with open(SIGNALS_LOG, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([int(time.time()*1000), direction, score, s15, s5, s1,
                                 passed, rejection, rr, adx, regime, spread, vol_ratio,
                                 fear_greed, score_breakdown])

