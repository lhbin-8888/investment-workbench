#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷新每日盘面指数数据
- 拉取上证指数、深证成指、创业板指、科创50 最近15个交易日收盘价
- 计算沪深两市总成交额
    - 输出到 D:\\投研工作台\\data\\index-daily.json
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "index-daily.json"
DAYS = 15

# 东方财富K线接口
# secid: 上海=1.xxxxx, 深圳=0.xxxxx
INDEXES = [
    {"name": "上证指数", "code": "000001", "secid": "1.000001", "color": "#FF4D4F"},
    {"name": "深证成指", "code": "399001", "secid": "0.399001", "color": "#00E5FF"},
    {"name": "创业板指", "code": "399006", "secid": "0.399006", "color": "#8B5CF6"},
    {"name": "科创50",   "code": "000688", "secid": "1.000688", "color": "#F5C542"},
]

SH_CODE = "000001"
SZ_CODE = "399001"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def fetch_kline(secid: str, beg: str, end: str):
    """从东方财富获取日K线数据。"""
    url = (
        "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        "&klt=101&fqt=1"
        f"&beg={beg}&end={end}"
    )
    try:
        # 若系统代理未启动，避免代理导致连接失败
        proxies = {"http": None, "https": None}
        resp = requests.get(url, headers=HEADERS, timeout=30, proxies=proxies)
        resp.raise_for_status()
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        return [line.split(",") for line in klines]
    except Exception as e:
        print(f"[WARN] 获取 {secid} 数据失败: {e}", file=sys.stderr)
        return []


def parse_kline(rows):
    """解析K线数据，返回 {date: {open, close, high, low, volume, amount}}。"""
    # fields2: f51日期,f52开盘,f53收盘,f54最高,f55最低,f56成交量,f57成交额,...
    out = {}
    for row in rows:
        if len(row) < 7:
            continue
        try:
            out[row[0]] = {
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
                "amount": float(row[6]),
            }
        except ValueError:
            continue
    return out


def main():
    today = datetime.now().date()
    # 向前多取一段，确保能覆盖最近15个交易日（含节假日空档）
    beg = (today - timedelta(days=45)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    records = {}
    for idx in INDEXES:
        rows = fetch_kline(idx["secid"], beg, end)
        records[idx["code"]] = parse_kline(rows)

    # 取所有指数共有的最近15个交易日
    common_dates = sorted(set(records[SH_CODE]) & set(records[SZ_CODE]))
    if not common_dates:
        print("[ERROR] 未获取到有效数据", file=sys.stderr)
        sys.exit(1)

    dates = common_dates[-DAYS:]

    # 格式化横轴日期 MM-DD
    chart_dates = [d[5:] for d in dates]

    indices_out = []
    for idx in INDEXES:
        code = idx["code"]
        closes = [round(records[code][d]["close"], 2) for d in dates]
        indices_out.append({
            "name": idx["name"],
            "code": code,
            "color": idx["color"],
            "closes": closes,
        })

    # 沪深两市总成交额（亿元）
    turnover = []
    for d in dates:
        sh_amount = records[SH_CODE][d]["amount"] / 1e8
        sz_amount = records[SZ_CODE][d]["amount"] / 1e8
        turnover.append({
            "date": d[5:],
            "total": round(sh_amount + sz_amount, 2),
            "shanghai": round(sh_amount, 2),
            "shenzhen": round(sz_amount, 2),
        })

    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period": f"{dates[0]} ~ {dates[-1]}",
        "days": DAYS,
        "dates": chart_dates,
        "indices": indices_out,
        "turnover": turnover,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[OK] 已更新 {OUTPUT}，区间 {payload['period']}")


if __name__ == "__main__":
    main()
