# -*- coding: utf-8 -*-
"""
gen_sector_map.py —— 生成 hotspot_trader_v3_ptrade.py 的板块静态池
====================================================================
数据来源：东方财富（push2.eastmoney.com），覆盖概念板块 + 行业板块及成分股。
纯标准库（urllib），无第三方依赖，可在任意联网 PC 直接运行：

  python gen_sector_map.py                      # 输出到 ./sector_map.json
  python gen_sector_map.py --out sector_map.json
  python gen_sector_map.py --delay 0.12        # 每板块请求间隔（秒），防限流
  python gen_sector_map.py --src em            # em=东方财富（默认）；ths=同花顺（占位）
  python gen_sector_map.py --selftest          # 离线验证解析逻辑（不联网）

输出格式（严格匹配 V3 load_sector_map 期望）：
  {
    "industry": { "行业名": ["600000", ...], ... },
    "concept":  { "概念名": ["600000", ...], ... },
    "source": "eastmoney",
    "generated_at": "2026-09-14T22:00:00"
  }
  - 代码统一存 6 位纯数字字符串（无后缀），V3 的 _canon/_build_sector_index 会自行规范化。

为什么用东财而非 sina：
  sina 板块池缺少 AI/算力/低空/光模块等当下主线题材，且宽口径标签（融资融券/参股金融）
  占比过高导致强度公式长期偏向非题材板块。东财板块体系覆盖更全、时效性更好。

为什么日频刷新：
  V3 静态池会滞后热点周期（3~5 天）。本脚本应每日盘前运行一次，生成新 sector_map.json，
  再上传到 PTrade 的「只读」目录（见 V3 的 SECTOR_MAP_FALLBACK_PATHS）。V3 在
  before_trading_start 会每日失效板块池缓存、并按 SECTOR_MAP_MAX_AGE_DAYS 告警过期。

平台约束提示：
  PTrade 托管机房无外网，本脚本只能在本机/有网机器运行，再把产物上传，不能放在策略里跑。
"""
import argparse
import datetime
import json
import os
import ssl
import sys
import time
import urllib.request

EM_BASE = "https://push2.eastmoney.com/api/qt/clist/get"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REFERER = "https://quote.eastmoney.com/center/boardlist.html"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ============================================================
# 离线自测样本（已知 push2 响应结构，无需联网即可验证解析逻辑）
# ============================================================
_SELFTEST_BOARDLIST = {
    "rc": 0, "rt": 6, "data": {
        "total": 3,
        "diff": {
            "0": {"f12": "BK0425", "f13": "90", "f14": "机器人概念"},
            "1": {"f12": "BK0967", "f13": "90", "f14": "低空经济"},
            "2": {"f12": "BK1136", "f13": "90", "f14": "AI概念"},
        },
    },
}
_SELFTEST_MEMBERS = {
    "rc": 0, "rt": 6, "data": {
        "total": 2,
        "diff": {
            "0": {"f12": "600036", "f13": "1", "f14": "招商银行"},
            "1": {"f12": "000001", "f13": "0", "f14": "平安银行"},
        },
    },
}


def _http_get(url, retries=3, timeout=15, delay=0.12):
    """带 UA/Referer 与重试的 GET；连续失败抛最后异常。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": REFERER})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(delay * (i + 1))
    raise last


def _parse_clist(payload):
    """从 push2 列表响应解析出 [(code, name), ...]。

    响应两种形态都要兼容：
      data.diff = {"0": {f12,f13,f14}, ...}   （字典，按序号索引）
      data.diff = [ {f12,f13,f14}, ... ]        （列表）
    f12 = 代码（板块 BKxxxx 或个股 6 位）；f14 = 名称。
    """
    data = (payload or {}).get("data") or {}
    diff = data.get("diff")
    if diff is None:
        return []
    items = diff.values() if isinstance(diff, dict) else (diff if isinstance(diff, list) else [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("f12") or "").strip()
        name = str(it.get("f14") or "").strip()
        if code and name:
            out.append((code, name))
    return out


def _boardlist_url(kind, pz=1000, pn=1):
    """kind: 'concept' -> m:90+t:3 ; 'industry' -> m:90+t:2。"""
    fs = "m:90+t:3+f:!50" if kind == "concept" else "m:90+t:2+f:!50"
    return "{base}?pn={pn}&pz={pz}&fs={fs}&fields=f12,f13,f14&_={ts}".format(
        base=EM_BASE, pn=pn, pz=pz, fs=fs, ts=int(time.time() * 1000))


def _members_url(board_code, pz=1000, pn=1):
    return "{base}?pn={pn}&pz={pz}&fs=b:{bc}&fields=f12,f13,f14&_={ts}".format(
        base=EM_BASE, pn=pn, pz=pz, bc=board_code, ts=int(time.time() * 1000))


def fetch_boards(kind, pz=1000, delay=0.12):
    """返回 {板块名: 板块代码}。"""
    txt = _http_get(_boardlist_url(kind, pz=pz), delay=delay)
    payload = json.loads(txt)
    if payload.get("rc") != 0:
        raise RuntimeError("板块列表 rc={} ({}): {}".format(
            payload.get("rc"), kind, str(payload)[:120]))
    boards = {}
    for code, name in _parse_clist(payload):
        boards[name] = code
    return boards


def fetch_members(board_code, delay=0.12):
    """返回某板块的成分股 6 位代码列表（分页抓全）。"""
    codes = []
    pn = 1
    while True:
        txt = _http_get(_members_url(board_code, pn=pn), delay=delay)
        payload = json.loads(txt)
        if payload.get("rc") != 0:
            break
        rows = _parse_clist(payload)
        if not rows:
            break
        for code, _ in rows:
            if code.isdigit() and len(code) == 6:
                codes.append(code)
        total = (payload.get("data") or {}).get("total") or 0
        if len(codes) >= total or len(rows) < 1000:
            break
        pn += 1
    # 去重保序
    seen, uniq = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def run(src, out_path, delay=0.12, max_boards=0):
    if src != "em":
        raise SystemExit("当前仅实现东财(em)数据源；同花顺(ths)接口需 JS 渲染/鉴权，"
                         "暂未接入。东财已覆盖概念+行业双体系，题材完整度满足 V3 需求。")
    concept = fetch_boards("concept", delay=delay)
    industry = fetch_boards("industry", delay=delay)
    print("[板块] 概念 {} 行业 {}（开始抓成分）".format(len(concept), len(industry)))

    def fill(group):
        out = {}
        for i, (name, bk) in enumerate(sorted(group.items())):
            if max_boards and i >= max_boards:
                break
            try:
                members = fetch_members(bk, delay=delay)
            except Exception as e:
                print("  ! 板块 {}({}) 成分抓取失败: {}".format(name, bk, repr(e)[:80]))
                members = []
            out[name] = members
            if (i + 1) % 25 == 0 or i == 0:
                print("  ... {}/{} 板块已处理".format(i + 1, len(group)))
            time.sleep(delay)
        return out

    concept_f = fill(concept)
    industry_f = fill(industry)

    pool = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "eastmoney",
        "industry": industry_f,
        "concept": concept_f,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False)
    nonempty_c = sum(1 for v in concept_f.values() if v)
    nonempty_i = sum(1 for v in industry_f.values() if v)
    print("[完成] 概念板 {}（含成分 {}）/ 行业板 {}（含成分 {}） -> {}".format(
        len(concept_f), nonempty_c, len(industry_f), nonempty_i, out_path))
    return pool


def selftest():
    """离线验证解析逻辑：不联网，用已知结构样本。"""
    fails = []
    # 板块列表解析
    bl = _parse_clist(_SELFTEST_BOARDLIST)
    if bl != [("BK0425", "机器人概念"), ("BK0967", "低空经济"), ("BK1136", "AI概念")]:
        fails.append("板块列表解析错误: {}".format(bl))
    # 成分解析 + 6 位过滤
    mb = fetch_members_from_payload(_SELFTEST_MEMBERS)
    if mb != ["600036", "000001"]:
        fails.append("成分解析错误: {}".format(mb))
    # diff 为列表形态也要能解析
    list_form = {"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK0001", "f14": "测试板"}]}}
    if _parse_clist(list_form) != [("BK0001", "测试板")]:
        fails.append("列表形态 diff 解析失败")
    if fails:
        for x in fails:
            print("[FAIL]", x)
        sys.exit(1)
    print("[SELFTEST PASS] 解析逻辑正确；输出结构示例:")
    print(json.dumps({"concept": {"机器人概念": ["600036", "000001"]},
                      "industry": {}, "source": "eastmoney",
                      "generated_at": "2026-09-14T22:00:00"},
                     ensure_ascii=False, indent=2))


def fetch_members_from_payload(payload):
    codes = []
    for code, _ in _parse_clist(payload):
        if code.isdigit() and len(code) == 6:
            codes.append(code)
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sector_map.json")
    ap.add_argument("--src", default="em", choices=["em", "ths"])
    ap.add_argument("--delay", type=float, default=0.12)
    ap.add_argument("--max-boards", type=int, default=0,
                    help="0=全部；>0=每种仅前 N 个（调试用）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    run(args.src, args.out, delay=args.delay, max_boards=args.max_boards)


if __name__ == "__main__":
    main()
