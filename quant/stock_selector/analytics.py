"""纯标准库技术指标计算，确保本工具在离线环境可运行。"""

from __future__ import annotations

import math
from collections import OrderedDict
from statistics import fmean
from typing import Iterable, Sequence

from .models import Bar


def safe_div(a: float | None, b: float | None, default: float | None = None) -> float | None:
    if a is None or b in (None, 0):
        return default
    try:
        return a / b
    except (TypeError, ZeroDivisionError):
        return default


def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def macd(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, float | None]:
    if len(closes) < slow + signal:
        return {"dif": None, "dea": None, "hist": None}
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    dif = [a - b for a, b in zip(fast_ema, slow_ema)]
    dea = ema_series(dif, signal)
    hist = [(a - b) * 2.0 for a, b in zip(dif, dea)]
    return {
        "dif": round(dif[-1], 6),
        "dea": round(dea[-1], 6),
        "hist": round(hist[-1], 6),
    }


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(closes[-period - 1 : -1], closes[-period:]):
        diff = cur - prev
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 2)


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    trs: list[float] = []
    for prev, cur in zip(bars[-period - 1 : -1], bars[-period:]):
        trs.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return sum(trs) / period


def return_pct(closes: Sequence[float], period: int) -> float | None:
    if len(closes) <= period or closes[-period - 1] <= 0:
        return None
    return (closes[-1] / closes[-period - 1] - 1.0) * 100.0


def weekly_closes(bars: Sequence[Bar]) -> list[float]:
    """按 ISO 年周聚合，周收盘取该周最后一个交易日收盘。"""
    weeks: OrderedDict[tuple[int, int], float] = OrderedDict()
    for bar in bars:
        try:
            dt = __import__("datetime").datetime.strptime(str(bar.date), "%Y%m%d").date()
        except ValueError:
            continue
        iso = dt.isocalendar()
        weeks[(iso.year, iso.week)] = bar.close
    return list(weeks.values())


def clipped_score(value: float | None, low: float, high: float) -> float:
    """把 value 线性映射到 0~100，边界外截断。"""
    if value is None or high <= low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def avg(values: Iterable[float]) -> float:
    items = list(values)
    return fmean(items) if items else 0.0


def stock_features(
    bars: Sequence[Bar],
    market_bars: Sequence[Bar] | None = None,
) -> dict[str, object]:
    """从日线计算波段和短线共用的无未来函数特征。"""
    if len(bars) < 20:
        return {"bars": len(bars), "enough_data": False}
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]
    amounts = [b.amount for b in bars]
    current = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else current
    pct = safe_div(current - prev, prev, 0.0) * 100.0
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    ma120 = sma(closes, 120)
    ma20_prev = sma(closes[:-5], 20)
    avg_volume5 = avg(volumes[-6:-1]) if len(volumes) >= 6 else avg(volumes[-5:])
    avg_amount20 = avg(amounts[-20:])
    volume_ratio = safe_div(float(volumes[-1]), avg_volume5)
    amount_ratio = safe_div(amounts[-1], avg_amount20)
    high20 = max(highs[-21:-1]) if len(highs) >= 21 else max(highs[:-1])
    low20 = min(lows[-20:])
    distance_high20 = safe_div(current - high20, high20, 0.0) * 100.0
    daily_macd = macd(closes)
    weekly_macd = macd(weekly_closes(bars))
    recent3_down = len(closes) >= 4 and closes[-1] < closes[-2] < closes[-3] < closes[-4]
    rs20 = None
    if market_bars and len(market_bars) >= 21 and len(closes) >= 21:
        market_closes = [b.close for b in market_bars]
        stock_ret = safe_div(closes[-1], closes[-21], 1.0) - 1.0
        market_ret = safe_div(market_closes[-1], market_closes[-21], 1.0) - 1.0
        rs20 = (stock_ret - market_ret) * 100.0
    return {
        "bars": len(bars),
        "enough_data": True,
        "date": bars[-1].date,
        "close": round(current, 4),
        "pct": round(pct, 4),
        "ma5": round(ma5, 4) if ma5 else None,
        "ma10": round(ma10, 4) if ma10 else None,
        "ma20": round(ma20, 4) if ma20 else None,
        "ma60": round(ma60, 4) if ma60 else None,
        "ma120": round(ma120, 4) if ma120 else None,
        "ma20_rising": bool(ma20 is not None and ma20_prev is not None and ma20 > ma20_prev),
        "ma60_rising": bool(ma60 is not None and sma(closes[:-5], 60) is not None and ma60 > sma(closes[:-5], 60)),
        "volume_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
        "amount_ratio": round(amount_ratio, 4) if amount_ratio is not None else None,
        "avg_amount20": round(avg_amount20, 2),
        "high20": round(high20, 4),
        "low20": round(low20, 4),
        "distance_high20": round(distance_high20, 4),
        "breakout20": current > high20,
        "pullback_depth": round((current / high20 - 1.0) * 100.0, 4) if high20 else None,
        "rsi14": rsi(closes),
        "atr14": round(atr(bars) or 0.0, 4),
        "macd_daily_dif": daily_macd["dif"],
        "macd_daily_dea": daily_macd["dea"],
        "macd_daily_hist": daily_macd["hist"],
        "macd_weekly_hist": weekly_macd["hist"],
        "return20": round(return_pct(closes, 20) or 0.0, 4),
        "return60": round(return_pct(closes, 60) or 0.0, 4),
        "rs20": round(rs20, 4) if rs20 is not None else None,
        "recent3_down": recent3_down,
    }
