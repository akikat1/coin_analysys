from __future__ import annotations
import math
from collections import deque
import pandas as pd
import pandas_ta
import dataclasses
from datetime import datetime, timezone
from models import Candle, Indicators
from data.volume_profile import calculate as calculate_volume_profile

def calculate(candles: deque, timeframe: str) -> Indicators:
    if len(candles) < 50: return Indicators()
    df    = pd.DataFrame([dataclasses.asdict(c) for c in candles])
    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"]
    last  = float(close.iloc[-1])

    ema9=_fl(pandas_ta.ema(close,9)); ema21=_fl(pandas_ta.ema(close,21))
    ema50=_fl(pandas_ta.ema(close,50))
    ema200=_fl(pandas_ta.ema(close,200)) if len(candles)>=200 else None

    today_ms = int(datetime.now(timezone.utc).replace(
        hour=0,minute=0,second=0,microsecond=0).timestamp()*1000)
    dt = df[df["open_time"]>=today_ms]; vwap=None
    if len(dt)>=2:
        tp=(dt["high"]+dt["low"]+dt["close"])/3; cv=dt["volume"].sum()
        vwap=float((tp*dt["volume"]).sum()/cv) if cv>0 else None

    st=pandas_ta.supertrend(high,low,close,length=10,multiplier=3.0); st_dir=None
    if st is not None:
        dc=[c for c in st.columns if "SUPERTd" in c]
        if dc: v=st[dc[0]].iloc[-1]; st_dir="UP" if v==1 else "DOWN"

    ichi=pandas_ta.ichimoku(high,low,close) if len(candles)>=52 else (None,None)
    ich_above=None
    if ichi and ichi[0] is not None:
        isa_c=[c for c in ichi[0].columns if "ISA" in c]
        isb_c=[c for c in ichi[0].columns if "ISB" in c]
        if isa_c and isb_c:
            isa=float(ichi[0][isa_c[0]].iloc[-1]); isb=float(ichi[0][isb_c[0]].iloc[-1])
            if not (math.isnan(isa) or math.isnan(isb)): ich_above=last>max(isa,isb)

    adx_df=pandas_ta.adx(high,low,close,length=14)
    adx=_fl(adx_df.get("ADX_14") if adx_df is not None else None)
    dip=_fl(adx_df.get("DMP_14") if adx_df is not None else None)
    dim=_fl(adx_df.get("DMN_14") if adx_df is not None else None)

    rsi=_fl(pandas_ta.rsi(close,length=14))

    sk=sd=scross=None
    sr=pandas_ta.stochrsi(close,length=14,rsi_length=14,k=3,d=3)
    if sr is not None and len(sr)>=2:
        kc=[c for c in sr.columns if "STOCHRSIk" in c]
        dc_=[c for c in sr.columns if "STOCHRSId" in c]
        if kc and dc_:
            kn,kp=float(sr[kc[0]].iloc[-1]),float(sr[kc[0]].iloc[-2])
            dn,dp=float(sr[dc_[0]].iloc[-1]),float(sr[dc_[0]].iloc[-2])
            sk,sd=kn,dn
            if kp<dp and kn>=dn and kn<20:   scross="bull"
            elif kp>dp and kn<=dn and kn>80: scross="bear"
            else:                             scross="none"

    ml=ms_=mh=None; mc="none"; mca=None
    md=pandas_ta.macd(close,fast=12,slow=26,signal=9)
    if md is not None and len(md)>=2:
        mc_c=[c for c in md.columns if c.startswith("MACD_")]
        ms_c=[c for c in md.columns if c.startswith("MACDs_")]
        mh_c=[c for c in md.columns if c.startswith("MACDh_")]
        if mc_c and ms_c and mh_c:
            m=md[mc_c[0]]; s=md[ms_c[0]]
            ml=float(m.iloc[-1]); ms_=float(s.iloc[-1]); mh=_fl(md[mh_c[0]])
            for i in range(1,min(10,len(m)-1)):
                p_,c_=-(i+1),-i
                if m.iloc[p_]<s.iloc[p_] and m.iloc[c_]>=s.iloc[c_]: mc="bull"; mca=i; break
                if m.iloc[p_]>s.iloc[p_] and m.iloc[c_]<=s.iloc[c_]: mc="bear"; mca=i; break

    at=pandas_ta.atr(high,low,close,length=14); atr=_fl(at)
    atr_pct=(atr/last*100) if atr and last>0 else None
    atr_avg_24h=None
    if timeframe=="15m" and at is not None and len(candles)>=96:
        atr_avg_24h=float(at.dropna().tail(96).mean())

    bb=pandas_ta.bbands(close,length=20,std=2.0)
    kc_=pandas_ta.kc(high,low,close,length=20,scalar=2.0)
    bbu=bbl=bbp=None; bbs=None
    if bb is not None and not bb.empty:
        bbu_c=[c for c in bb.columns if "BBU" in c]
        bbl_c=[c for c in bb.columns if "BBL" in c]
        bbp_c=[c for c in bb.columns if "BBP" in c]
        if bbu_c and bbl_c and bbp_c:
            bbu=float(bb[bbu_c[0]].iloc[-1]); bbl=float(bb[bbl_c[0]].iloc[-1])
            bbp=float(bb[bbp_c[0]].iloc[-1])
            if kc_ is not None and not kc_.empty and len(kc_.columns)>=3:
                bbs=(bbu<float(kc_.iloc[-1,0])) and (bbl>float(kc_.iloc[-1,2]))

    obv_s=pandas_ta.obv(close,vol); obv=_fl(obv_s)
    obv3=(list(obv_s.iloc[-4:-1].astype(float))
          if obv_s is not None and len(obv_s)>=4 else [])
    va=float(vol.tail(20).mean()) if len(candles)>=20 else None
    vr=float(vol.iloc[-1])/va if va and va>0 else None

    pr1=ps1=None
    if len(candles)>=2:
        prev=candles[-2]; pp=(prev.high+prev.low+prev.close)/3
        pr1=round(2*pp-prev.low,2); ps1=round(2*pp-prev.high,2)

    poc=vah=val=None
    vp_poc, vp_vah, vp_val = calculate_volume_profile(candles)
    if vp_poc > 0:
        poc, vah, val = vp_poc, vp_vah, vp_val

    htf_trend = None
    if all(x is not None for x in (ema9, ema21, ema50)):
        if ema9 > ema21 > ema50:
            htf_trend = "BULL"
        elif ema9 < ema21 < ema50:
            htf_trend = "BEAR"
        else:
            htf_trend = "NEUTRAL"

    return Indicators(
        ema9=ema9,ema21=ema21,ema50=ema50,ema200=ema200,
        vwap=vwap,supertrend_dir=st_dir,ichimoku_above_cloud=ich_above,
        adx=adx,di_plus=dip,di_minus=dim,
        rsi=rsi,stoch_k=sk,stoch_d=sd,stoch_cross=scross,
        macd_line=ml,macd_sig=ms_,macd_hist=mh,macd_cross=mc,macd_cross_age=mca,
        atr=atr,atr_pct=atr_pct,atr_avg_24h=atr_avg_24h,
        bb_upper=bbu,bb_lower=bbl,bb_pct_b=bbp,bb_squeeze=bbs,
        obv=obv,obv_prev_3=obv3,volume_ratio=vr,
        pivot_r1=pr1,pivot_s1=ps1,last_close=last,
        poc=poc,vah=vah,val=val,htf_trend=htf_trend)

def _fl(series) -> float|None:
    if series is None: return None
    if hasattr(series,"iloc"):
        if series.empty: return None
        v=series.iloc[-1]; return float(v) if not pd.isna(v) else None
    return None

