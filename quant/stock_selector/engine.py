"""市场总闸、板块资格、角色分类与双通道筛选。"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .analytics import clipped_score, safe_div, sma, stock_features
from .data_access import (
    SECTOR_JSON,
    enrich_candidates,
    is_risk_name,
    load_all_candidates,
    load_index_bars,
    load_names,
    load_sectors,
    load_sentiment,
    load_stock_bars,
)
from .models import Bar, Candidate, Evaluation, SectorState


def determine_market_regime(
    index_bars: list[Bar],
    breadth_bars: list[Bar],
    sentiment: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    ma_short = int(config["market"]["ma_short"])
    ma_long = int(config["market"]["ma_long"])
    closes = [bar.close for bar in index_bars]
    breadth_closes = [bar.close for bar in breadth_bars]
    short_ma = sma(closes, ma_short)
    long_ma = sma(closes, ma_long)
    breadth_short_ma = sma(breadth_closes, ma_short)
    breadth_long_ma = sma(breadth_closes, ma_long)
    above_short = bool(short_ma and closes[-1] > short_ma)
    breadth_above_short = bool(breadth_short_ma and breadth_closes[-1] > breadth_short_ma)
    above_long = bool(long_ma and closes[-1] > long_ma)
    breadth_above_long = bool(breadth_long_ma and breadth_closes[-1] > breadth_long_ma)
    up = int(sentiment.get("up") or 0)
    down = int(sentiment.get("down") or 0)
    limit_up = int(sentiment.get("limit_up") or 0)
    failed = int(sentiment.get("failed") or 0)
    failed_ratio = safe_div(failed, limit_up + failed, 0.0) or 0.0
    cycle = str(sentiment.get("cycle") or "")
    breadth_positive = up > down
    negative_votes = sum(
        (
            not above_short,
            not breadth_above_short,
            not breadth_positive,
            failed_ratio >= float(config["market"]["max_failed_ratio"]),
            cycle in {"退潮", "衰退"},
        )
    )
    if above_short and breadth_above_short and above_long and breadth_above_long and breadth_positive:
        regime = "进攻"
        position_multiplier = 1.0
    elif negative_votes >= 2:
        regime = "防守"
        position_multiplier = 0.0
    else:
        regime = "中性"
        position_multiplier = 0.5
    reasons = [
        f"沪深300 {'站上' if above_short else '跌破'} MA{ma_short}",
        f"中证500 {'站上' if breadth_above_short else '跌破'} MA{ma_short}",
        f"涨跌家数 {up}:{down}",
        f"炸板率 {failed_ratio:.1%}",
        f"情绪周期 {cycle or '未知'}",
    ]
    return {
        "regime": regime,
        "trade_allowed": regime != "防守",
        "position_multiplier": position_multiplier,
        "negative_votes": negative_votes,
        "above_ma_short": above_short,
        "breadth_above_ma_short": breadth_above_short,
        "above_ma_long": above_long,
        "breadth_above_ma_long": breadth_above_long,
        "failed_ratio": round(failed_ratio, 4),
        "reasons": reasons,
        "sentiment": sentiment,
    }


def apply_sector_gates(sectors: list[SectorState], config: dict[str, Any]) -> list[SectorState]:
    swing_gates = set(config["sector"]["swing_gates"])
    short_gates = set(config["sector"]["short_gates"])
    excluded = set(config["sector"]["exclude_gates"])
    rebound_requires_ma20 = bool(config["sector"]["rebound_requires_ma20"])
    for sector in sectors:
        sector.swing_eligible = sector.gate in swing_gates
        if sector.gate == "rebound" and rebound_requires_ma20:
            sector.swing_eligible = bool(sector.ma20)
        sector.short_eligible = sector.gate in short_gates and sector.gate not in excluded
        if sector.gate in excluded:
            sector.swing_eligible = False
            sector.short_eligible = False
        sector.reasons.append(
            f"波段资格={'通过' if sector.swing_eligible else '不通过'}；"
            f"短线资格={'通过' if sector.short_eligible else '不通过'}"
        )
    return sectors


def fundamental_quality(candidate: Candidate) -> tuple[str, list[str]]:
    if not candidate.fundamentals_available:
        return "unknown", ["基本面数据缺失"]
    tags: list[str] = []
    red = False
    yellow = False
    if candidate.net_profit_billion is not None and candidate.net_profit_billion < 0:
        red = True
        tags.append("净利润为负")
    if candidate.pe is not None and candidate.pe > 500:
        red = True
        tags.append("PE>500")
    if candidate.net_profit_yoy is not None and candidate.net_profit_yoy < -50:
        yellow = True
        tags.append("利润同比<-50%")
    if candidate.revenue_yoy is not None and candidate.revenue_yoy < -30:
        yellow = True
        tags.append("营收同比<-30%")
    if candidate.pe is not None and 200 < candidate.pe <= 500:
        yellow = True
        tags.append("PE位于200~500")
    if red:
        return "red", tags
    if yellow:
        return "yellow", tags
    return "green", tags


def _role_metrics(
    candidate: Candidate,
    features: dict[str, Any],
) -> dict[str, float]:
    live_pct = candidate.pct if candidate.pct is not None else float(features.get("pct") or 0.0)
    rs20 = features.get("rs20")
    return20 = float(features.get("return20") or 0.0)
    distance_high = float(features.get("distance_high20") or -100.0)
    momentum = (
        clipped_score(float(rs20) if rs20 is not None else 0.0, -20, 30) * 0.45
        + clipped_score(return20, -20, 40) * 0.30
        + clipped_score(distance_high, -20, 8) * 0.15
        + clipped_score(live_pct, -3, 10) * 0.10
    )
    recognition = 0.0
    if candidate.tier == 1:
        recognition += 50
    elif candidate.tier == 2:
        recognition += 30
    if "板" in candidate.status and "未封板" not in candidate.status:
        recognition += 30
    return {
        "momentum": round(momentum, 2),
        "recognition": round(min(100.0, recognition), 2),
        "role_score": round(momentum * 0.7 + min(100.0, recognition) * 0.3, 2),
    }


def assign_roles(
    candidates_by_sector: dict[str, list[Candidate]],
    features_by_code: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    min_float_cap = float(config["liquidity"]["min_float_cap"])
    for sector_candidates in candidates_by_sector.values():
        if not sector_candidates:
            continue
        metrics = {
            candidate.code: _role_metrics(candidate, features_by_code.get(candidate.code, {}))
            for candidate in sector_candidates
        }
        ranked = sorted(
            sector_candidates,
            key=lambda item: metrics[item.code]["role_score"],
            reverse=True,
        )
        leader = ranked[0]
        roles[leader.code] = "波段龙头"
        mid_pool = []
        for candidate in ranked[1:]:
            features = features_by_code.get(candidate.code, {})
            quality, _ = fundamental_quality(candidate)
            close = float(features.get("close") or candidate.close or 0.0)
            ma20 = features.get("ma20")
            float_cap = candidate.float_cap or 0.0
            if (
                candidate.code != leader.code
                and float_cap >= min_float_cap
                and quality in {"green", "yellow"}
                and ma20 is not None
                and close >= float(ma20)
            ):
                mid_pool.append(candidate)
        if mid_pool:
            mid = max(mid_pool, key=lambda item: item.float_cap or 0.0)
            roles[mid.code] = "趋势中军"
        for candidate in ranked:
            roles.setdefault(candidate.code, "跟随股")
    return roles


def _score_trend(features: dict[str, Any], lane: str) -> float:
    close = float(features.get("close") or 0.0)
    ma10 = features.get("ma10")
    ma20 = features.get("ma20")
    ma60 = features.get("ma60")
    rs20 = features.get("rs20")
    breakout = bool(features.get("breakout20"))
    pieces = [
        80.0 if ma10 is not None and close > float(ma10) else 20.0,
        85.0 if ma20 is not None and close > float(ma20) else 15.0,
        80.0 if ma60 is not None and close > float(ma60) else 30.0,
        80.0 if features.get("ma20_rising") else 35.0,
        clipped_score(float(rs20) if rs20 is not None else 0.0, -20, 30),
        85.0 if breakout else clipped_score(float(features.get("distance_high20") or 0.0), -15, 2),
    ]
    weights = [0.15, 0.20, 0.15, 0.15, 0.25, 0.10]
    if lane == "short":
        weights = [0.30, 0.20, 0.05, 0.10, 0.25, 0.10]
    return round(sum(value * weight for value, weight in zip(pieces, weights)), 2)


def _score_volume(features: dict[str, Any], candidate: Candidate) -> float:
    volume_ratio = candidate.volume_ratio
    if volume_ratio is None:
        volume_ratio = features.get("volume_ratio")
    volume_ratio = float(volume_ratio or 0.0)
    if 1.2 <= volume_ratio <= 3.0:
        base = 100.0
    elif 0.8 <= volume_ratio < 1.2:
        base = 60.0
    elif 3.0 < volume_ratio <= 4.5:
        base = 55.0
    elif volume_ratio > 4.5:
        base = 25.0
    else:
        base = 20.0
    amount_ratio = float(features.get("amount_ratio") or 0.0)
    amount_score = clipped_score(amount_ratio, 0.5, 2.5)
    return round(base * 0.75 + amount_score * 0.25, 2)


def _score_fund(candidate: Candidate) -> float:
    if candidate.main_net is None:
        return 50.0
    if candidate.main_net <= 0:
        return 10.0
    main_pct = candidate.extra.get("main_pct")
    if main_pct is None:
        return 75.0
    return round(55.0 + clipped_score(float(main_pct), 0, 15) * 0.45, 2)


def _score_fundamental(candidate: Candidate) -> float:
    quality, _ = fundamental_quality(candidate)
    if quality == "green":
        return 100.0
    if quality == "yellow":
        return 55.0
    if quality == "red":
        return 10.0
    return 50.0


def _score_macd(features: dict[str, Any], lane: str) -> float:
    dif = features.get("macd_daily_dif")
    dea = features.get("macd_daily_dea")
    hist = features.get("macd_daily_hist")
    weekly_hist = features.get("macd_weekly_hist")
    score = 50.0
    if dif is not None and dea is not None:
        if float(dif) > float(dea):
            score += 25.0
        else:
            score -= 20.0
        if float(dif) > 0:
            score += 15.0
    if hist is not None and float(hist) > 0:
        score += 10.0
    if weekly_hist is not None and float(weekly_hist) > 0:
        score += 10.0
    if lane == "short" and weekly_hist is not None and float(weekly_hist) <= 0:
        score -= 5.0
    return round(max(0.0, min(100.0, score)), 2)


def _weighted_score(
    parts: dict[str, float],
    weights: dict[str, float],
) -> float:
    total_weight = sum(weights.values()) or 1.0
    return round(sum(parts[key] * weights.get(key, 0.0) for key in parts) / total_weight, 2)


def _grade(
    lane: str,
    score: float,
    hard_fails: list[str],
    market: dict[str, Any],
    sector: SectorState,
    config: dict[str, Any],
) -> tuple[str, str]:
    if hard_fails:
        return "淘汰", "淘汰"
    if lane == "swing":
        a = float(config["swing"]["min_score_a"])
        b = float(config["swing"]["min_score_b"])
    else:
        a = float(config["short"]["min_score_a"])
        b = float(config["short"]["min_score_b"])
    if not market["trade_allowed"] or sector.days <= 1:
        return "C", "观察"
    if score >= a:
        return "A", "候选"
    if score >= b:
        return "B", "候选"
    return "C", "观察"


def build_trade_plan(
    lane: str,
    candidate: Candidate,
    features: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    close = float(features.get("close") or candidate.close or 0.0)
    atr = float(features.get("atr14") or 0.0)
    if lane == "swing":
        ma10 = float(features.get("ma10") or close)
        ma20 = float(features.get("ma20") or close)
        entry_low = max(ma10 * 0.99, close - max(atr, close * 0.015))
        entry_high = close + max(atr * 0.6, close * 0.01)
        stop_pct = float(config["risk"]["swing_stop_pct"])
        stop = max(min(close * (1.0 - stop_pct), ma20 * 0.98), close - 1.8 * max(atr, 0.01))
        stop = min(stop, close * 0.995)
        return {
            "entry_zone": [round(entry_low, 2), round(entry_high, 2)],
            "trigger": "板块维持强势；个股回踩 MA10/MA20 不破并重新放量，或放量突破 20 日高点",
            "confirmation": "收盘站上 MA20；量比 1.2~3.0；主力资金不为负；板块未转 ebb",
            "stop": round(stop, 2),
            "time_stop_days": int(config["risk"]["swing_time_stop_days"]),
            "exit": "跌破 MA20 或计划止损；板块转退潮；资金连续两日转负",
        }
    stop_pct = float(config["risk"]["short_stop_pct"])
    stop = min(close * (1.0 - stop_pct), close - max(atr, close * 0.01))
    return {
        "entry_zone": [round(close * 0.99, 2), round(close * 1.01, 2)],
        "trigger": "09:35~10:00 回踩不破开盘价或 MA5，随后放量上穿；高开超过 2% 不追",
        "confirmation": "当日涨幅 0.2%~9.5%；量比 1.2~4.0；主力净流入为正；板块未退潮",
        "stop": round(stop, 2),
        "time_stop_days": int(config["risk"]["short_time_stop_days"]),
        "exit": "跌破当日关键低点或止损价；破 MA5/MA10；板块转弱；持有 5 日无进展",
    }


def _hard_gates(
    lane: str,
    candidate: Candidate,
    features: dict[str, Any],
    role: str,
    sector: SectorState,
    market: dict[str, Any],
    quality: str,
    config: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if lane == "swing":
        if not sector.swing_eligible:
            failures.append(f"板块不满足波段资格({sector.gate})")
        if role not in {"波段龙头", "趋势中军"}:
            failures.append(f"个股角色不合格({role})")
        if int(features.get("bars") or 0) < int(config["swing"]["min_bars"]):
            failures.append("日线数据不足120根")
        close = float(features.get("close") or 0.0)
        ma20 = features.get("ma20")
        ma60 = features.get("ma60")
        if ma20 is None or close < float(ma20):
            failures.append("收盘未站上MA20")
        if ma60 is None or close < float(ma60):
            failures.append("收盘未站上MA60")
        if not features.get("ma20_rising"):
            failures.append("MA20未向上")
        if float(features.get("pct") or 0.0) > float(config["swing"]["max_daily_pct"]):
            failures.append("当日涨幅过热")
        if quality == "red" and role == "趋势中军":
            failures.append("中军基本面红色风险")
    else:
        if not sector.short_eligible:
            failures.append(f"板块不满足短线资格({sector.gate})")
        if int(features.get("bars") or 0) < int(config["short"]["min_bars"]):
            failures.append("日线数据不足30根")
        close = float(features.get("close") or 0.0)
        ma10 = features.get("ma10")
        if ma10 is None or close < float(ma10):
            failures.append("收盘未站上MA10")
        pct = candidate.pct if candidate.pct is not None else float(features.get("pct") or 0.0)
        if not float(config["short"]["min_daily_pct"]) <= pct <= float(config["short"]["max_daily_pct"]):
            failures.append("当日涨幅不在短线区间")
        volume_ratio = candidate.volume_ratio or features.get("volume_ratio")
        if volume_ratio is None:
            failures.append("量比缺失")
        elif not float(config["short"]["min_volume_ratio"]) <= float(volume_ratio) <= float(config["short"]["max_volume_ratio"]):
            failures.append("量比不在短线区间")
    if is_risk_name(candidate.name):
        failures.append("ST或退市风险")
    avg_amount = float(features.get("avg_amount20") or 0.0)
    if avg_amount < float(config["liquidity"]["min_avg_amount_20"]):
        failures.append("20日平均成交额不足")
    if features.get("recent3_down"):
        failures.append("连续3日下跌")
    if candidate.main_net is not None and candidate.main_net <= 0:
        failures.append("主力资金净流出")
    if lane == "swing" and not market["trade_allowed"]:
        # 市场防守不进入“淘汰”，而是保留观察；评分阶段会限制为 C。
        pass
    return failures


def _risk_tags(
    candidate: Candidate,
    features: dict[str, Any],
    quality: str,
    quality_tags: list[str],
    sector: SectorState,
) -> list[str]:
    tags = list(quality_tags)
    if quality == "red":
        tags.append("基本面红灯")
    elif quality == "yellow":
        tags.append("基本面黄灯")
    if candidate.main_net is None:
        tags.append("个股资金缺失")
    if features.get("macd_weekly_hist") is None:
        tags.append("周线MACD数据不足")
    if sector.days <= 1:
        tags.append("板块持续性未确认")
    if sector.gate == "rebound":
        tags.append("超跌反弹待趋势修复")
    if candidate.volume_ratio and float(candidate.volume_ratio) > 4.0:
        tags.append("量比过大")
    return sorted(set(tags))


def evaluate_lane(
    lane: str,
    candidate: Candidate,
    features: dict[str, Any],
    role: str,
    sector: SectorState,
    market: dict[str, Any],
    config: dict[str, Any],
) -> Evaluation:
    quality, quality_tags = fundamental_quality(candidate)
    hard_fails = _hard_gates(
        lane, candidate, features, role, sector, market, quality, config
    )
    sector_component = clipped_score(sector.avg_score, 0, 5)
    parts = {
        "sector": round(sector_component, 2),
        "trend": _score_trend(features, lane),
        "volume": _score_volume(features, candidate),
        "fund": _score_fund(candidate),
        "fundamental": _score_fundamental(candidate),
        "macd": _score_macd(features, lane),
    }
    if lane == "swing":
        weights = config["swing"]["weights"]["mid" if role == "趋势中军" else "leader"]
    else:
        weights = config["short"]["weights"]
    score = _weighted_score(parts, weights)
    grade, decision = _grade(lane, score, hard_fails, market, sector, config)
    trade_plan = (
        build_trade_plan(lane, candidate, features, config)
        if decision != "淘汰"
        else {}
    )
    return Evaluation(
        code=candidate.code,
        name=candidate.name,
        sector=candidate.sector,
        lane=lane,
        role=role,
        grade=grade,
        decision=decision,
        score=score,
        score_parts=parts,
        features=features,
        hard_fail_reasons=hard_fails,
        risk_tags=_risk_tags(candidate, features, quality, quality_tags, sector),
        trade_plan=trade_plan,
        candidate={
            "source": candidate.source,
            "tier": candidate.tier,
            "pct": candidate.pct,
            "close": candidate.close,
            "float_cap": candidate.float_cap,
            "amount": candidate.amount,
            "turnover": candidate.turnover,
            "volume_ratio": candidate.volume_ratio,
            "main_net": candidate.main_net,
            "pe": candidate.pe,
            "pb": candidate.pb,
            "roe": candidate.roe,
            "revenue_yoy": candidate.revenue_yoy,
            "net_profit_yoy": candidate.net_profit_yoy,
            "status": candidate.status,
        },
        sector_state=sector.to_dict(),
    )


def analyze(config: dict[str, Any], offline: bool = False) -> dict[str, Any]:
    sectors = apply_sector_gates(load_sectors(), config)
    sector_map = {sector.name: sector for sector in sectors}
    index_bars = load_index_bars(config["market"]["primary_index"])
    breadth_bars = load_index_bars(config["market"]["breadth_index"])
    market = determine_market_regime(index_bars, breadth_bars, load_sentiment(), config)
    candidates, report_path = load_all_candidates()
    online_ok = False
    if not offline and candidates:
        candidates, online_ok = enrich_candidates(candidates)

    names = load_names()
    for candidate in candidates:
        if not candidate.name:
            candidate.name = names.get(candidate.code, "")

    features_by_code: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        features_by_code[candidate.code] = stock_features(
            load_stock_bars(candidate.code), breadth_bars
        )

    candidates_by_sector: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        candidates_by_sector[candidate.sector].append(candidate)
    roles = assign_roles(candidates_by_sector, features_by_code, config)

    swing: list[Evaluation] = []
    short: list[Evaluation] = []
    rejected: list[Evaluation] = []
    for candidate in candidates:
        sector = sector_map.get(candidate.sector)
        if sector is None:
            features = features_by_code.get(candidate.code, {})
            evaluation = Evaluation(
                code=candidate.code,
                name=candidate.name,
                sector=candidate.sector,
                lane="none",
                role="未知",
                grade="淘汰",
                decision="淘汰",
                score=0.0,
                score_parts={},
                features=features,
                hard_fail_reasons=["板块不在最新日报候选池"],
                risk_tags=["板块映射失败"],
                trade_plan={},
                candidate={"source": candidate.source, "tier": candidate.tier},
                sector_state={},
            )
            rejected.append(evaluation)
            continue
        features = features_by_code.get(candidate.code, {})
        if not features.get("enough_data"):
            rejected.append(
                Evaluation(
                    code=candidate.code,
                    name=candidate.name,
                    sector=candidate.sector,
                    lane="none",
                    role=roles.get(candidate.code, "未知"),
                    grade="淘汰",
                    decision="淘汰",
                    score=0.0,
                    score_parts={},
                    features=features,
                    hard_fail_reasons=["本地日线不足"],
                    risk_tags=["行情数据不足"],
                    trade_plan={},
                    candidate={"source": candidate.source, "tier": candidate.tier},
                    sector_state=sector.to_dict(),
                )
            )
            continue
        role = roles.get(candidate.code, "跟随股")
        swing_eval = evaluate_lane(
            "swing", candidate, features, role, sector, market, config
        )
        short_eval = evaluate_lane(
            "short", candidate, features, role, sector, market, config
        )
        for evaluation in (swing_eval, short_eval):
            if evaluation.decision == "淘汰":
                rejected.append(evaluation)
            elif evaluation.lane == "swing":
                swing.append(evaluation)
            else:
                short.append(evaluation)

    swing.sort(key=lambda item: (item.grade, -item.score))
    short.sort(key=lambda item: (item.grade, -item.score))
    rejected.sort(key=lambda item: (item.code, item.lane))
    latest_bar_date = ""
    dates = [
        int(features["date"])
        for features in features_by_code.values()
        if isinstance(features, dict) and features.get("date")
    ]
    if dates:
        latest_bar_date = str(max(dates))
    elif index_bars:
        latest_bar_date = str(index_bars[-1].date)
    raw_date = latest_bar_date or dt.date.today().strftime("%Y%m%d")
    current_date = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        if len(raw_date) == 8 and raw_date.isdigit()
        else raw_date
    )
    return {
        "version": config.get("version", ""),
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": current_date,
        "market": market,
        "sectors": [sector.to_dict() for sector in sectors],
        "source": {
            "sector_report": str(SECTOR_JSON),
            "leader_report": str(report_path) if report_path else "",
            "online_quotes": online_ok,
        },
        "summary": {
            "sector_count": len(sectors),
            "swing_eligible_sectors": sum(sector.swing_eligible for sector in sectors),
            "short_eligible_sectors": sum(sector.short_eligible for sector in sectors),
            "candidate_count": len(candidates),
            "swing_count": len(swing),
            "short_count": len(short),
            "rejected_count": len(rejected),
        },
        "swing": [item.to_dict() for item in swing],
        "short": [item.to_dict() for item in short],
        "rejected": [item.to_dict() for item in rejected],
    }
