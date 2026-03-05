from models import TradeLevel, MarketContext
from execution import exchange_info
import config

def calculate_levels(entry: float, direction: str, atr: float,
                     balance: float, context: MarketContext,
                     reduced_size_active: bool,
                     leverage_override: int|None = None) -> TradeLevel|None:
    lev = leverage_override if leverage_override is not None else config.LEVERAGE
    lev = max(config.MIN_LEVERAGE, min(config.MAX_LEVERAGE, int(lev)))
    stop_dist=min(atr*1.5, entry*0.015); stop_dist_pct=stop_dist/entry
    lp=exchange_info.round_price
    if direction=="LONG":
        stop=lp(entry-stop_dist); tp1=lp(entry+stop_dist*2.0)
        tp2=lp(entry+stop_dist*3.5); tp3=lp(entry+stop_dist*6.0)
        rr=(tp1-entry)/stop_dist
    else:
        stop=lp(entry+stop_dist); tp1=lp(entry-stop_dist*2.0)
        tp2=lp(entry-stop_dist*3.5); tp3=lp(entry-stop_dist*6.0)
        rr=(entry-tp1)/stop_dist
    size_mult=context.size_multiplier
    if reduced_size_active: size_mult*=config.REDUCED_SIZE_MULTIPLIER
    qty_raw=(balance*config.MAX_RISK_PER_TRADE_PCT*size_mult)/(entry*stop_dist_pct)
    qty_raw=min(qty_raw,(balance*0.20*lev)/entry)
    qty=exchange_info.round_qty(qty_raw)
    if qty<=0 or not exchange_info.validate(entry,qty): return None
    qt1=exchange_info.round_qty(qty*0.40); qt2=exchange_info.round_qty(qty*0.35)
    qt3=exchange_info.round_qty(qty-qt1-qt2)
    if qt3<=0: qt3=exchange_info.step_size
    return TradeLevel(entry=entry,stop=stop,tp1=tp1,tp2=tp2,tp3=tp3,
                      qty_btc=qty,qty_tp1=qt1,qty_tp2=qt2,qty_tp3=qt3,
                      notional_usd=qty*entry,margin_usd=(qty*entry)/lev,
                      rr=rr,stop_dist_pct=stop_dist_pct)

