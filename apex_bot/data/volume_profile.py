"""
Volume Profile: вычисляет POC, VAH, VAL из свечей.

POC  (Point of Control)  — цена с максимальным объёмом
VAH  (Value Area High)   — верхняя граница 70% объёма
VAL  (Value Area Low)    — нижняя граница 70% объёма

Используется в signal_engine как дополнительный score:
- Цена у POC/VAH/VAL → сильный уровень → +score в нужном направлении
- Цена выше VAH → нет сопротивления до следующего VAH → бычий сигнал
- Цена ниже VAL → нет поддержки до следующего VAL → медвежий сигнал
"""
from __future__ import annotations
import numpy as np
from collections import deque
import dataclasses
import config
from models import Candle

def calculate(candles: deque, bins: int = None, value_area_pct: float = None
              ) -> tuple[float, float, float]:
    """
    Вычислить Volume Profile.
    Возвращает (poc, vah, val). Если данных недостаточно — (0.0, 0.0, 0.0).

    Args:
        candles: deque свечей
        bins: количество ценовых уровней (по умолчанию из config.VP_BINS)
        value_area_pct: доля объёма для Value Area (по умолчанию config.VP_VALUE_AREA_PCT)
    """
    if bins is None:        bins          = config.VP_BINS
    if value_area_pct is None: value_area_pct = config.VP_VALUE_AREA_PCT
    if len(candles) < 20:
        return 0.0, 0.0, 0.0

    highs  = np.array([c.high   for c in candles], dtype=float)
    lows   = np.array([c.low    for c in candles], dtype=float)
    vols   = np.array([c.volume for c in candles], dtype=float)
    closes = np.array([c.close  for c in candles], dtype=float)

    price_min = float(lows.min())
    price_max = float(highs.max())
    if price_max <= price_min:
        return 0.0, 0.0, 0.0

    edges      = np.linspace(price_min, price_max, bins + 1)
    vol_profile = np.zeros(bins, dtype=float)

    for i in range(len(candles)):
        candle_range = highs[i] - lows[i]
        if candle_range <= 0:
            # Точечная свеча: весь объём в одном бине
            idx = int((closes[i] - price_min) / (price_max - price_min) * (bins - 1))
            idx = max(0, min(bins - 1, idx))
            vol_profile[idx] += vols[i]
            continue
        # Распределяем объём свечи по пересекаемым бинам пропорционально перекрытию
        for b in range(bins):
            bin_low  = edges[b]
            bin_high = edges[b + 1]
            overlap  = min(highs[i], bin_high) - max(lows[i], bin_low)
            if overlap > 0:
                vol_profile[b] += vols[i] * (overlap / candle_range)

    # POC: бин с максимальным объёмом
    poc_bin  = int(np.argmax(vol_profile))
    poc      = float((edges[poc_bin] + edges[poc_bin + 1]) / 2)

    # Value Area: расширяем от POC пока не наберём value_area_pct от общего объёма
    total_vol    = float(vol_profile.sum())
    if total_vol <= 0:
        return poc, poc, poc
    target_vol   = total_vol * value_area_pct

    lower_idx = poc_bin
    upper_idx = poc_bin
    accumulated  = float(vol_profile[poc_bin])

    while accumulated < target_vol:
        can_go_lower = lower_idx > 0
        can_go_upper = upper_idx < bins - 1
        if not can_go_lower and not can_go_upper:
            break
        add_lower = vol_profile[lower_idx - 1] if can_go_lower else -1
        add_upper = vol_profile[upper_idx + 1] if can_go_upper else -1
        if add_lower >= add_upper:
            lower_idx   -= 1
            accumulated += float(vol_profile[lower_idx])
        else:
            upper_idx   += 1
            accumulated += float(vol_profile[upper_idx])

    val = float(edges[lower_idx])
    vah = float(edges[upper_idx + 1])
    return poc, vah, val

