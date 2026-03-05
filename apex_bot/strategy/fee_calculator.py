import config
from models import PnlResult

def calculate_net_pnl(direction: str, entry: float, exit_price: float,
                      qty: float, leverage: int,
                      entry_taker: bool=True, exit_taker: bool=True) -> PnlResult:
    disc      = 0.9 if config.BNB_DISCOUNT else 1.0
    ef_rate   = (config.TAKER_FEE if entry_taker else config.MAKER_FEE)*disc
    xf_rate   = (config.TAKER_FEE if exit_taker  else config.MAKER_FEE)*disc
    entry_fee = qty*entry*ef_rate
    exit_fee  = qty*exit_price*xf_rate
    slippage  = qty*entry*config.SLIPPAGE_ESTIMATE*2
    costs     = entry_fee+exit_fee+slippage
    gross     = ((exit_price-entry) if direction=="LONG" else (entry-exit_price))*qty
    net       = gross-costs
    margin    = (qty*entry)/leverage
    be_off    = costs/qty if qty>0 else 0
    be_price  = entry+be_off if direction=="LONG" else entry-be_off
    return PnlResult(gross,entry_fee,exit_fee,slippage,costs,net,
                     (net/margin*100) if margin>0 else 0, be_price)

def is_tp1_profitable(entry: float, tp1: float, qty: float,
                      leverage: int, direction: str) -> bool:
    r=calculate_net_pnl(direction,entry,tp1,qty,leverage)
    return r.net_pnl>r.total_costs*1.5

