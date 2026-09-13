#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷新 A 股市场情绪数据（涨停/跌停/炸板/连板/周期）。
产出：D:\\投研工作台\\data\\market-sentiment.json

字段规则（与用户表格一致）：
- 上涨/下跌：A股全天上涨/下跌家数（来自 stock_market_activity_legu，仅当天）。
- 涨停/跌停/炸板：对应东方财富涨停池/跌停池/炸板池，不含 ST/新股/退市。
- 连板 = 二连+三连+...+六连及以上。
- 实际涨停 = 涨停池中不含 ST/新股/退市的总家数。
- 一板 = 实际涨停 - 连板家数。
- 二连~六连+：连板数恰好为 N 的股票数（不含 ST/新股/退市）。
- 创业板涨停：代码以 300/301 开头；科创板涨停：代码以 688 开头。
- 周期：根据近几日指数涨跌幅、涨停数、炸板率、跌停数自动推断。

每日收盘后运行一次（建议 15:30），与 tools/refresh_index_daily.py 配合。
"""

import os
import re
import sys
import json
import time
import akshare as ak
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# 禁用代理，避免东方财富接口被重置
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("HTTP_PROXY", "")
os.environ.setdefault("HTTPS_PROXY", "")

ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = ROOT / "data" / "index-daily.json"
OUT_FILE = ROOT / "data" / "market-sentiment.json"


def to_int(x, default=0):
    """把 pandas/numpy 标量转成 Python int，失败返回 default。"""
    try:
        if x is None:
            return default
        if isinstance(x, (np.integer, np.floating)):
            return int(x)
        return int(x)
    except Exception:
        return default


def is_st_or_new(name):
    """名称是否包含 ST/*ST/N/退（新股、ST、退市）。"""
    if not isinstance(name, str):
        return False
    return bool(re.search(r"^(N|ST|\*ST|退)", name.strip()))


def today_str(fmt="%Y%m%d"):
    return datetime.now().strftime(fmt)


def parse_period_dates(period_str):
    """从 '2026-08-24 ~ 2026-09-11' 解析出起止日期，并补齐交易日（跳过周末）。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", period_str)
    if not m:
        return []
    start = datetime.strptime(m.group(1), "%Y-%m-%d")
    end = datetime.strptime(m.group(2), "%Y-%m-%d")
    dates = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return dates


def fetch_zt_pool(date_str):
    """date_str: '20260911'，返回 DataFrame 或 None。"""
    for attempt in range(2):
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            return df
        except Exception as e:
            err = e
            time.sleep(0.5)
    print(f"[warn] stock_zt_pool_em({date_str}) failed: {err}", file=sys.stderr)
    return None


def fetch_dt_pool(date_str):
    for attempt in range(2):
        try:
            return ak.stock_zt_pool_dtgc_em(date=date_str)
        except Exception as e:
            err = e
            time.sleep(0.5)
    print(f"[warn] stock_zt_pool_dtgc_em({date_str}) failed: {err}", file=sys.stderr)
    return None


def fetch_zbgc_pool(date_str):
    for attempt in range(2):
        try:
            return ak.stock_zt_pool_zbgc_em(date=date_str)
        except Exception as e:
            err = e
            time.sleep(0.5)
    print(f"[warn] stock_zt_pool_zbgc_em({date_str}) failed: {err}", file=sys.stderr)
    return None


def fetch_market_activity():
    """乐咕乐股市场活跃度，仅当天数据。"""
    try:
        df = ak.stock_market_activity_legu()
        mapping = {}
        for _, r in df.iterrows():
            mapping[str(r["item"]).strip()] = to_int(r["value"])
        return {
            "up": to_int(mapping.get("上涨")),
            "down": to_int(mapping.get("下跌")),
            "zt": to_int(mapping.get("涨停")),
            "actual_zt": to_int(mapping.get("真实涨停")),
            "st_zt": to_int(mapping.get("st st*涨停")),
        }
    except Exception as e:
        print(f"[warn] stock_market_activity_legu() failed: {e}", file=sys.stderr)
        return None


def calc_one_day(date_str, idx_closes):
    """计算某一天的情绪指标。"""
    date_ymd = date_str.replace("-", "")  # 2026-08-24 -> 20260824

    zt_df = fetch_zt_pool(date_ymd)
    if zt_df is None or zt_df.empty:
        return None

    # 过滤 ST/新股/退市
    zt_df = zt_df[~zt_df["名称"].apply(is_st_or_new)].copy()
    zt_df["连板数"] = zt_df["连板数"].fillna(1).astype(int)

    total_zt = len(zt_df)
    # 创业板、科创板
    code_str = zt_df["代码"].astype(str)
    cyb = to_int(code_str.str.startswith(("300", "301")).sum())
    kcb = to_int(code_str.str.startswith("688").sum())

    lb = zt_df["连板数"]
    first_board = to_int((lb == 1).sum())
    two = to_int((lb == 2).sum())
    three = to_int((lb == 3).sum())
    four = to_int((lb == 4).sum())
    five = to_int((lb == 5).sum())
    six_plus = to_int((lb >= 6).sum())
    continuous = two + three + four + five + six_plus

    dt_df = fetch_dt_pool(date_ymd)
    zbgc_df = fetch_zbgc_pool(date_ymd)

    return {
        "date": date_str[5:] if date_str.startswith("2026-") else date_str,
        "up": None,
        "down": None,
        "limit_up": total_zt,
        "limit_down": to_int(len(dt_df)) if dt_df is not None else None,
        "failed": to_int(len(zbgc_df)) if zbgc_df is not None else None,
        "continuous": continuous,
        "actual_limit_up": total_zt,
        "cyb_limit_up": cyb,
        "kcb_limit_up": kcb,
        "first_board": first_board,
        "two_board": two,
        "three_board": three,
        "four_board": four,
        "five_board": five,
        "six_plus": six_plus,
        "cycle": "",
    }


def judge_cycle(rows, idx, idx_closes):
    """基于近几日数据判断当天周期。"""
    if idx < 1 or not idx_closes:
        return "振荡"

    def pct(i):
        if i < 1 or i >= len(idx_closes):
            return 0.0
        return (idx_closes[i] - idx_closes[i - 1]) / idx_closes[i - 1] * 100

    cur = rows[idx]
    prev = rows[idx - 1]
    cur_pct = pct(idx)
    prev_pct = pct(idx - 1)

    # 窗口数据
    window = rows[max(0, idx - 4):idx + 1]
    zts = [(r.get("limit_up") or 0) for r in window]
    cur_zt = zts[-1]
    prev_zt = zts[-2]
    avg3 = sum(zts[:-1]) / max(1, len(zts) - 1)

    failed = cur.get("failed") or 0
    failed_rate = failed / (cur_zt + failed) if (cur_zt + failed) > 0 else 0
    dt = cur.get("limit_down") or 0

    # 1. 反转：深跌后连续大涨
    if idx >= 2:
        p2 = pct(idx - 2)
        if p2 < -1.0 and prev_pct > 0 and cur_pct > 0.8 and cur_zt > avg3 * 1.30:
            return "反转"

    # 2. 退潮：涨停数明显减少，跌停/炸板增多，指数下跌
    if cur_zt < avg3 * 0.78 and (dt >= 8 or failed_rate > 0.30) and cur_pct < -0.2:
        return "退潮"

    # 3. 分歧：涨停数多但指数滞涨或炸板率高
    if cur_zt >= 70 and (failed_rate >= 0.25 or cur_pct < -0.2):
        return "分歧"
    if cur_zt >= 60 and failed_rate >= 0.30:
        return "分歧"

    # 4. 衰退：指数与涨停连续走弱
    if prev_pct < -0.2 and cur_pct < 0 and cur_zt < prev_zt:
        return "衰退"

    # 5. 启动：连续上涨，涨停数放大，跌停少
    if cur_pct > 0.4 and cur_zt > avg3 * 1.15 and len(zts) >= 3 and prev_zt >= zts[-3] and dt <= 3:
        return "启动"

    # 6. 反弹：大跌后单日明显修复
    if prev_pct < -0.5 and cur_pct > 0.5 and cur_zt > prev_zt * 1.15:
        return "反弹"

    # 7. 回暖：低迷后修复
    if avg3 < 60 and cur_zt > avg3 * 1.20 and cur_pct > 0.2 and dt <= 3:
        return "回暖"

    # 8. 振荡：波动小，数据平稳
    if abs(cur_pct) < 0.6 and abs(cur_zt - avg3) < avg3 * 0.18:
        return "振荡"

    return "回暖" if cur_pct > 0.3 else "衰退" if cur_pct < -0.3 else "振荡"


def build_index_closes(index_data, dates):
    """返回与 dates 对齐的上证指数收盘价列表。"""
    for idx in index_data.get("indices", []):
        if idx.get("code") == "000001":
            return idx.get("closes", [])
    return []


def main():
    if not INDEX_FILE.exists():
        print(f"[error] {INDEX_FILE} 不存在，请先运行 refresh_index_daily.py", file=sys.stderr)
        sys.exit(1)

    index_data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    dates = parse_period_dates(index_data.get("period", ""))
    if not dates:
        # fallback：从 dates 字段反推
        dates = [f"2026-{d}" for d in index_data.get("dates", [])]

    idx_closes = build_index_closes(index_data, dates)

    # 尝试读取已有情绪数据，保留历史涨跌家数（如果能拿到的话）
    existing = {}
    if OUT_FILE.exists():
        try:
            existing = {r["date"]: r for r in json.loads(OUT_FILE.read_text(encoding="utf-8")).get("rows", [])}
        except Exception:
            existing = {}

    rows = []
    for i, d in enumerate(dates):
        # 如果已有数据且未要求强制刷新，可复用涨跌家数
        cached = existing.get(d[5:]) if d.startswith("2026-") else existing.get(d)
        new_row = calc_one_day(d, idx_closes)
        if new_row is None:
            # 拉取失败则回退到缓存
            if cached:
                rows.append(cached)
            continue
        # 复用缓存中的涨跌家数（若脚本之前某天跑过并抓到）
        if cached and cached.get("up") is not None:
            new_row["up"] = cached["up"]
            new_row["down"] = cached["down"]
        rows.append(new_row)

    # 对最后一天尝试抓当天涨跌家数
    if rows:
        last_date_full = dates[-1]
        activity = fetch_market_activity()
        if activity:
            last = rows[-1]
            last["up"] = activity.get("up")
            last["down"] = activity.get("down")
            # 如果乐咕数据里的涨停/跌停更全，也可以覆盖
            if activity.get("actual_zt") and not last.get("actual_limit_up"):
                last["actual_limit_up"] = activity.get("actual_zt")

    # 周期判断
    for i in range(len(rows)):
        rows[i]["cycle"] = judge_cycle(rows, i, idx_closes)

    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period": index_data.get("period", ""),
        "days": len(rows),
        "fields": [
            "date", "up", "down", "limit_up", "limit_down", "failed",
            "continuous", "actual_limit_up", "cyb_limit_up", "kcb_limit_up",
            "first_board", "two_board", "three_board", "four_board", "five_board", "six_plus", "cycle"
        ],
        "rows": rows,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 写入 {OUT_FILE}，共 {len(rows)} 天")


if __name__ == "__main__":
    main()
