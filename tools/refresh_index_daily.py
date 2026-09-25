#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷新每日盘面指数数据
- 拉取上证指数、深证成指、创业板指、科创50 最近15个交易日收盘价
- 计算沪深两市总成交额
- 输出到 D:\\投研工作台\\data\\index-daily.json

数据源策略（2026-09-14 加固）：
- 主源：东方财富 push2his K线接口（fields2 含 f56 成交额，口径最准）。
- 兜底源：新浪财经 getKLineData（本机到东财 push2his 主机常被 TCP 重置，
  新浪接口稳定）。新浪仅返回 OHLC+成交量，不含成交额，故用「当日真实
  沪深成交额」(akshare stock_zh_a_spot) 反推量纲，对历史成交量做换算，
  保证 turnover 口径接近真实。
"""
import json
import os
import sys
import time
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
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

PROXIES = {"http": None, "https": None}


def fetch_kline_em(secid: str, beg: str, end: str):
    """主源：东方财富日K线。返回 [[date, open, close, high, low, volume, amount], ...]。"""
    url = (
        "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        "&klt=101&fqt=1"
        f"&beg={beg}&end={end}"
    )
    for _ in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25, proxies=PROXIES)
            resp.raise_for_status()
            klines = resp.json().get("data", {}).get("klines", [])
            rows = []
            for line in klines:
                p = line.split(",")
                if len(p) < 7:
                    continue
                rows.append([p[0], float(p[1]), float(p[2]), float(p[3]),
                             float(p[4]), float(p[5]), float(p[6])])
            if rows:
                return rows
        except Exception as e:
            print(f"[WARN] 东财 {secid} 失败: {e}", file=sys.stderr)
            time.sleep(1.5)
    return []


def _sina_symbol(secid: str) -> str:
    prefix, code = secid.split(".")
    return ("sh" if prefix == "1" else "sz") + code


def fetch_kline_sina(secid: str, beg: str, end: str):
    """兜底源：新浪财经日K线。返回 [[date, open, close, high, low, volume, 0.0], ...]，
    amount 暂置 0，待校准。"""
    sym = _sina_symbol(secid)
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=80"
    )
    for _ in range(3):
        try:
            resp = requests.get(url, headers=SINA_HEADERS, timeout=25, proxies=PROXIES)
            resp.raise_for_status()
            data = resp.json()
            rows = []
            for item in data:
                d = item["day"].replace("-", "")
                if not (beg <= d <= end):
                    continue
                rows.append([
                    item["day"],
                    float(item["open"]), float(item["close"]),
                    float(item["high"]), float(item["low"]),
                    float(item["volume"]), 0.0,
                ])
            if rows:
                return rows
        except Exception as e:
            print(f"[WARN] 新浪 {secid} 失败: {e}", file=sys.stderr)
            time.sleep(1.5)
    return []


def parse_kline(rows):
    out = {}
    for row in rows:
        out[row[0]] = {
            "open": row[1], "close": row[2], "high": row[3],
            "low": row[4], "volume": row[5], "amount": row[6],
        }
    return out


def _real_amount_sina():
    """新浪实时行情：返回 (沪市成交额元, 深市成交额元)。
    s_sh000001 字段: 名称,当前点数,涨跌,涨跌幅,成交量(万股),成交额(万元)"""
    url = "https://hq.sinajs.cn/list=s_sh000001,s_sz399001"
    resp = requests.get(url, headers=SINA_HEADERS, timeout=15, proxies=PROXIES)
    resp.encoding = "gbk"
    resp.raise_for_status()
    out = {}
    for line in resp.text.strip().splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.split("_")[-1].strip()
        parts = val.strip().strip('";').split(",")
        if len(parts) >= 6:
            out[key] = float(parts[5]) * 1e4  # 万元 → 元
    return out.get("sh000001", 0.0), out.get("sz399001", 0.0)


def _real_amount_tencent():
    """腾讯行情兜底：v_sh000001 中 "close/volume(手)/amount(元)" 段。"""
    url = "http://qt.gtimg.cn/q=sh000001,sz399001"
    resp = requests.get(url, headers=HEADERS, timeout=15, proxies=PROXIES)
    resp.encoding = "gbk"
    resp.raise_for_status()
    out = {}
    for line in resp.text.strip().splitlines():
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().replace("v_", "")
        body = line.split('"', 1)[-1].strip('";')
        for seg in body.split("~"):
            if seg.count("/") == 2:
                out[key] = float(seg.split("/")[2])
                break
    return out.get("sh000001", 0.0), out.get("sz399001", 0.0)


def _tencent_symbol(secid: str) -> str:
    prefix, code = secid.split(".")
    return ("sh" if prefix == "1" else "sz") + code


def fetch_tencent_latest(secid: str, beg: str, end: str):
    """腾讯日K + 实时快照。返回 dict 或 None。
    kline 的 day 数组为 [日期, 开, 收, 高, 低, 成交量(手)]（无成交额）；
    快照 qt 段含 "收盘/成交量(手)/成交额(元)" 复合字段，成交额口径为全市场。
    """
    sym = _tencent_symbol(secid)
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={sym},day,{beg},{end},20,qfq"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, proxies=PROXIES)
        resp.raise_for_status()
        node = resp.json().get("data", {}).get(sym, {}) or {}
    except Exception as e:
        print(f"[WARN] 腾讯 {secid} 失败: {e}", file=sys.stderr)
        return None

    days = node.get("day") or node.get("qfqday") or []
    if not days:
        return None
    row = days[-1]
    out = {
        "date": row[0],
        "open": float(row[1]), "close": float(row[2]),
        "high": float(row[3]), "low": float(row[4]),
        "volume": float(row[5]) * 100.0 if len(row) > 5 else 0.0,  # 手 → 股
        "amount": 0.0,
    }
    for seg in (node.get("qt", {}) or {}).get(sym, []) or []:
        if isinstance(seg, str) and seg.count("/") == 2:
            try:
                out["amount"] = float(seg.split("/")[2])
            except ValueError:
                pass
            break
    return out


def _realtime_amounts_sina(secids):
    """新浪实时快照，返回 {code: 成交额(元)}。字段: 名称,点位,涨跌,涨跌幅,成交量,成交额(万元)。"""
    syms = ",".join("s_" + _tencent_symbol(s) for s in secids)
    resp = requests.get("https://hq.sinajs.cn/list=" + syms,
                        headers=SINA_HEADERS, timeout=15, proxies=PROXIES)
    resp.encoding = "gbk"
    resp.raise_for_status()
    out = {}
    for line in resp.text.strip().splitlines():
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().replace("var hq_str_", "").replace("s_", "")
        parts = line.split('"', 1)[-1].strip('";').split(",")
        if len(parts) >= 6:
            try:
                out[key] = float(parts[5]) * 1e4  # 万元 → 元
            except ValueError:
                pass
    return out


def append_latest_bar(records):
    """新浪兜底源不含「当日」K线（滞后一个交易日），导致 JSON 缺当日、且成交额
    校准因子跨日错配（曾把当日成交额错误地写成前一交易日值）。
    收盘后用腾讯行情补齐当日：收盘价取腾讯日K，成交额取腾讯快照（全市场口径），
    成交量统一换算为「股」以对齐新浪 K 线量纲，使校准因子建立在同一交易日上。"""
    now = datetime.now()
    if not (now.hour > 15 or (now.hour == 15 and now.minute >= 1)):
        print("[INFO] 未到收盘时点，跳过当日补齐", file=sys.stderr)
        return False

    today = now.strftime("%Y-%m-%d")
    beg = (now.date() - timedelta(days=45)).strftime("%Y-%m-%d")
    latest = {}
    for idx in INDEXES:
        info = fetch_tencent_latest(idx["secid"], beg, today)
        if info and info.get("date") == today:
            latest[idx["code"]] = info
    if len(latest) != len(INDEXES):
        print(f"[WARN] 腾讯当日数据不全（{len(latest)}/{len(INDEXES)}），跳过补齐", file=sys.stderr)
        return False

    if today in records.get(SH_CODE, {}):
        print("[INFO] 主源已含当日数据，无需补齐")
        return False

    if any(v["amount"] <= 0 for v in latest.values()):
        try:
            amt = _realtime_amounts_sina([i["secid"] for i in INDEXES])
            for idx in INDEXES:
                if latest[idx["code"]]["amount"] <= 0 and idx["code"] in amt:
                    latest[idx["code"]]["amount"] = amt[idx["code"]]
        except Exception as e:
            print(f"[WARN] 新浪实时成交额兜底失败: {e}", file=sys.stderr)

    for code, v in latest.items():
        records.setdefault(code, {})[today] = {
            "open": v["open"], "close": v["close"], "high": v["high"],
            "low": v["low"], "volume": v["volume"], "amount": v["amount"],
        }
    print(f"[INFO] 已用腾讯行情补齐当日 {today}（成交额=全市场口径，成交量=股）")
    return True


def calibrate_amount(records):
    """用当日真实沪深成交额反推新浪成交量量纲，填充 amount。
    仅当存在 amount==0 的记录（即走了新浪兜底）时调用。
    校准源顺序：新浪实时行情 → 腾讯行情（2026-09-22 改造：
    原 akshare stock_zh_a_spot 走东财通道，通道被重置后返回空，导致成交额全为 0）。"""
    sh_real = sz_real = 0.0
    for name, fn in (("新浪", _real_amount_sina), ("腾讯", _real_amount_tencent)):
        try:
            sh_real, sz_real = fn()
            if sh_real > 0 and sz_real > 0:
                print(f"[INFO] 校准源={name} 今日真实成交额 沪={sh_real/1e8:.0f}亿 深={sz_real/1e8:.0f}亿")
                break
            print(f"[WARN] 校准源({name})返回空，尝试下一源", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] 校准源({name})失败: {e}", file=sys.stderr)

    if not (sh_real > 0 and sz_real > 0):
        print("[WARN] 两个校准源均失败，amount 保留 0", file=sys.stderr)
        return

    # 取最近交易日（末位）各指数成交量
    def latest_volume(code):
        rec = records.get(code, {})
        if not rec:
            return 0.0
        return rec[max(rec.keys())]["volume"]

    sh_vol = latest_volume(SH_CODE)
    sz_vol = latest_volume(SZ_CODE)
    f_sh = sh_real / sh_vol if sh_vol else 0.0
    f_sz = sz_real / sz_vol if sz_vol else 0.0
    print(f"[INFO] 量纲校准因子 sh={f_sh:.6g} sz={f_sz:.6g}")

    for code, rec in records.items():
        factor = f_sh if code.startswith(("000001", "000688")) else f_sz
        for v in rec.values():
            if v["amount"] == 0 and factor:
                v["amount"] = v["volume"] * factor


def main():
    today = datetime.now().date()
    beg = (today - timedelta(days=45)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    records = {}
    used_fallback = False
    for idx in INDEXES:
        rows = fetch_kline_em(idx["secid"], beg, end)
        if not rows:
            print(f"[INFO] {idx['name']} 改用新浪兜底", file=sys.stderr)
            rows = fetch_kline_sina(idx["secid"], beg, end)
            used_fallback = True
        if not rows:
            print(f"[ERROR] {idx['name']} 东西源均失败", file=sys.stderr)
            sys.exit(1)
        records[idx["code"]] = parse_kline(rows)

    if used_fallback:
        append_latest_bar(records)
        calibrate_amount(records)

    common_dates = sorted(set(records[SH_CODE]) & set(records[SZ_CODE]))
    if not common_dates:
        print("[ERROR] 未获取到有效数据", file=sys.stderr)
        sys.exit(1)

    dates = common_dates[-DAYS:]
    chart_dates = [d[5:] for d in dates]

    indices_out = []
    for idx in INDEXES:
        code = idx["code"]
        closes = [round(records[code][d]["close"], 2) for d in dates]
        indices_out.append({
            "name": idx["name"], "code": code,
            "color": idx["color"], "closes": closes,
        })

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

    src = "东财" if not used_fallback else "东财+新浪兜底(已校准成交额)"
    print(f"[OK] 已更新 {OUTPUT}，区间 {payload['period']} 源={src}")


if __name__ == "__main__":
    main()
