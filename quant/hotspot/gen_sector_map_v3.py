# -*- coding: utf-8 -*-
"""
gen_sector_map_v3.py —— 生成 hotspot_trader_v3_ptrade.py 的板块静态池
====================================================================
数据来源（--src 控制，默认 mix）：
  mix = 行业走申万宏源官网（一级行业31 + 二级行业，券商投研标准口径），
        概念走东方财富（push2，题材宇宙唯一完整来源）。
  em  = 行业+概念全部走东方财富（旧行为，行业板 ~496 个偏杂）。
  sw  = 仅行业走申万，概念为空（诊断/对比用）。

纯标准库（urllib），无第三方依赖，可在任意联网 PC 直接运行：

  python gen_sector_map_v3.py                      # 默认 mix，输出 ./sector_map.json
  python gen_sector_map_v3.py --out sector_map.json
  python gen_sector_map_v3.py --delay 0.12        # 每板块请求间隔（秒），防限流
  python gen_sector_map_v3.py --src em            # 全东财（旧行为）
  python gen_sector_map_v3.py --src sw            # 仅申万行业（概念为空）
  python gen_sector_map_v3.py --sw-level l1       # 申万仅一级行业（默认 l1l2 = 一级+二级）
  python gen_sector_map_v3.py --selftest          # 离线验证解析逻辑（不联网）

输出格式（严格匹配 V3 load_sector_map 期望）：
  {
    "industry": { "行业名": ["600000", ...], ... },
    "concept":  { "概念名": ["600000", ...], ... },
    "source": "eastmoney+sw",
    "generated_at": "2026-09-24T10:00:00"
  }
  - 代码统一存 6 位纯数字字符串（无后缀），V3 的 _canon/_build_sector_index 会自行规范化。
  - schema 与 em 版完全一致，策略代码零改动。

申万接口（swsresearch.com 官方 JSON API，与 akshare 同源）：
  行业指数列表: GET https://www.swsresearch.com/institute-sw/api/index_publish/current/
                params: indextype=一级行业|二级行业, page, page_size
  成分股:       GET https://www.swsresearch.com/institute-sw/api/index_publish/details/component_stocks/
                params: swindexcode={指数代码}, page=1, page_size=10000
  请求需带 Chrome UA + Referer: https://www.swsresearch.com/

为什么行业换申万：东财行业板 ~496 个且口径杂（含大量细分/交叉标签），
申万 2021 版 31 一级 + 134 二级是券商投研标准口径，信号更干净、结构更稳定。
概念板必须保留东财：申万没有概念/题材板块体系，AI/低空/机器人等主线题材仅东财有。

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
import urllib.parse
import urllib.request

EM_BASE = "https://push2.eastmoney.com/api/qt/clist/get"
SW_LIST_BASE = "https://www.swsresearch.com/institute-sw/api/index_publish/current/"
SW_MEMBER_BASE = ("https://www.swsresearch.com/institute-sw/api/"
                  "index_publish/details/component_stocks/")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REFERER = "https://www.swsresearch.com/"
EM_REFERER = "https://quote.eastmoney.com/center/boardlist.html"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ============================================================
# 离线自测样本（已知响应结构，无需联网即可验证解析逻辑）
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
# 申万行业指数列表响应（官方 index_publish/current 结构：data.results 数组）
_SELFTEST_SW_LIST = {
    "data": {
        "count": 2,
        "results": [
            {"swindexcode": "801780", "swindexname": "银行"},
            {"swindexcode": "801790", "swindexname": "非银金融"},
        ],
    },
}
# 申万成分股响应（data.results 数组，stockcode/stockname）
_SELFTEST_SW_MEMBERS = {
    "data": {
        "count": 2,
        "results": [
            {"stockcode": "600036", "stockname": "招商银行", "newweight": 3.86},
            {"stockcode": "000001", "stockname": "平安银行", "newweight": 1.32},
            {"stockcode": "", "stockname": "无效行", "newweight": 0},
        ],
    },
}


def _http_get(url, retries=3, timeout=15, delay=0.12, referer=REFERER):
    """带 UA/Referer 与重试的 GET；连续失败抛最后异常。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": referer})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(delay * (i + 1))
    raise last


# ============================================================
# 东方财富（概念板块）—— push2 接口
# ============================================================
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


def fetch_boards(kind, pz=100, delay=0.12):
    """返回 {板块名: 板块代码}。分页抓全（东财单页上限现约 100，不可依赖 pz=1000 单页）。"""
    boards = {}
    pn = 1
    while True:
        txt = _http_get(_boardlist_url(kind, pz=pz, pn=pn), delay=delay,
                        referer=EM_REFERER)
        payload = json.loads(txt)
        if payload.get("rc") != 0:
            raise RuntimeError("板块列表 rc={} ({}): {}".format(
                payload.get("rc"), kind, str(payload)[:120]))
        rows = _parse_clist(payload)
        for code, name in rows:
            boards[name] = code
        data = payload.get("data") or {}
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if not rows or len(rows) < pz or (total and len(boards) >= total):
            break
        pn += 1
        time.sleep(delay)
    return boards


def fetch_members(board_code, delay=0.12):
    """返回某板块的成分股 6 位代码列表（分页抓全）。"""
    codes = []
    pn = 1
    while True:
        txt = _http_get(_members_url(board_code, pn=pn), delay=delay,
                        referer=EM_REFERER)
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
    return _uniq(codes)


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ============================================================
# 申万宏源（行业板块）—— swsresearch.com 官方 JSON API
# ============================================================
def _sw_parse_index_list(payload):
    """解析申万指数列表 -> [(指数代码, 指数名称), ...]。

    官方结构 data.results 为数组；data 可能是 dict（含 results）或直接是数组。
    指数字段兼容 swindexcode/swindexname 与 indexcode/indexname 两种命名。
    """
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        rows = data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    out = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        code = str(it.get("swindexcode") or it.get("indexcode") or "").strip()
        name = str(it.get("swindexname") or it.get("indexname") or "").strip()
        if code.isdigit() and name:
            out.append((code, name))
    return out


def _sw_parse_members(payload):
    """解析申万成分股 -> 6 位代码列表。字段 stockcode/stockname（兼容中文键名）。"""
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        rows = data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    codes = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        code = str(it.get("stockcode") or it.get("证券代码") or "").strip()
        if code.isdigit() and len(code) == 6:
            codes.append(code)
    return codes


def sw_fetch_industries(level="l1l2", delay=0.12):
    """抓申万行业指数列表。level: l1=仅一级, l2=仅二级, l1l2=一级+二级。

    返回 {行业名: 指数代码}。一级优先；二级重名（如与一级同名）时跳过并记录。
    """
    types = []
    if level in ("l1", "l1l2"):
        types.append("一级行业")
    if level in ("l2", "l1l2"):
        types.append("二级行业")
    boards = {}
    for indextype in types:
        page = 1
        collected = 0
        while True:
            qs = urllib.parse.urlencode({
                "indextype": indextype, "page": page, "page_size": 100})
            txt = _http_get(SW_LIST_BASE + "?" + qs, delay=delay)
            payload = json.loads(txt)
            rows = _sw_parse_index_list(payload)
            if not rows:
                break
            for code, name in rows:
                if name in boards:
                    print("  ! 申万{}指数重名已跳过: {}({})，保留 {}".format(
                        indextype, name, code, boards[name]))
                    continue
                boards[name] = code
            collected += len(rows)
            count = 0
            data = (payload or {}).get("data")
            if isinstance(data, dict):
                try:
                    count = int(data.get("count") or 0)
                except (TypeError, ValueError):
                    count = 0
            if collected >= count or len(rows) < 100:
                break
            page += 1
            time.sleep(delay)
        print("[申万] {}指数列表取回 {} 个（累计 {}）".format(
            indextype, len(rows), len(boards)))
    return boards


def sw_fetch_members(index_code, delay=0.12):
    """取申万指数成分股（page_size=10000 单页抓全，与 akshare 同法）。"""
    qs = urllib.parse.urlencode({
        "swindexcode": index_code, "page": 1, "page_size": 10000})
    txt = _http_get(SW_MEMBER_BASE + "?" + qs, delay=delay)
    payload = json.loads(txt)
    return _uniq(_sw_parse_members(payload))


# ============================================================
# 汇总与输出
# ============================================================
def run(src, out_path, delay=0.12, max_boards=0, sw_level="l1l2"):
    if src not in ("em", "mix", "sw"):
        raise SystemExit("--src 仅支持 em / mix / sw。")

    concept = {}
    industry = {}
    if src in ("em", "mix"):
        concept = fetch_boards("concept", delay=delay)
        print("[东财] 概念板 {} 个".format(len(concept)))
    if src == "em":
        industry = fetch_boards("industry", delay=delay)
        print("[东财] 行业板 {} 个（开始抓成分）".format(len(industry)))
    elif src in ("mix", "sw"):
        industry = sw_fetch_industries(level=sw_level, delay=delay)
        print("[申万] 行业指数 {} 个（开始抓成分）".format(len(industry)))

    def fill(group, fetcher):
        out = {}
        order = sorted(group.items())
        if max_boards:
            order = order[:max_boards]
        for i, (name, code) in enumerate(order):
            try:
                members = fetcher(code, delay=delay)
            except Exception as e:
                print("  ! 板块 {}({}) 成分抓取失败: {}".format(name, code, repr(e)[:80]))
                members = []
            out[name] = members
            if (i + 1) % 25 == 0 or i == 0:
                print("  ... {}/{} 板块已处理".format(i + 1, len(order)))
            time.sleep(delay)
        # 补抓轮：出口抖动导致成分抓取失败的板块，再补抓最多 2 轮
        for attempt in (2, 3):
            missing = [(n, c) for n, c in order if not out.get(n)]
            if not missing:
                break
            print("  [补抓{}] 上轮 {} 个板块缺成分，重试...".format(
                attempt, len(missing)))
            for name, code in missing:
                try:
                    members = fetcher(code, delay=delay)
                    if members:
                        out[name] = members
                        print("  + 补抓成功: {}({}) {} 只".format(
                            name, code, len(members)))
                    else:
                        print("  ? 补抓仍空: {}({})".format(name, code))
                except Exception as e:
                    print("  ! 补抓失败: {}({}): {}".format(
                        name, code, repr(e)[:60]))
                time.sleep(delay)
        return out

    concept_f = fill(concept, fetch_members) if concept else {}
    industry_f = fill(industry, fetch_members if src == "em" else sw_fetch_members) \
        if industry else {}

    source_tag = {"em": "eastmoney", "mix": "eastmoney+sw", "sw": "shenwan"}[src]
    pool = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source_tag,
        "industry": industry_f,
        "concept": concept_f,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False)
    nonempty_c = sum(1 for v in concept_f.values() if v)
    nonempty_i = sum(1 for v in industry_f.values() if v)
    print("[完成] 概念板 {}（含成分 {}）/ 行业板 {}（含成分 {}） -> {}".format(
        len(concept_f), nonempty_c, len(industry_f), nonempty_i, out_path))
    print("[source] {} | 请将产物上传 PTrade 只读目录（SECTOR_MAP_FALLBACK_PATHS）".format(source_tag))
    return pool


def selftest():
    """离线验证解析逻辑：不联网，用已知结构样本。"""
    fails = []
    # 东财板块列表解析
    bl = _parse_clist(_SELFTEST_BOARDLIST)
    if bl != [("BK0425", "机器人概念"), ("BK0967", "低空经济"), ("BK1136", "AI概念")]:
        fails.append("东财板块列表解析错误: {}".format(bl))
    # 东财成分解析 + 6 位过滤
    mb = fetch_members_from_payload(_SELFTEST_MEMBERS)
    if mb != ["600036", "000001"]:
        fails.append("东财成分解析错误: {}".format(mb))
    # 东财 diff 列表形态
    list_form = {"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK0001", "f14": "测试板"}]}}
    if _parse_clist(list_form) != [("BK0001", "测试板")]:
        fails.append("东财列表形态 diff 解析失败")
    # 申万指数列表解析
    swl = _sw_parse_index_list(_SELFTEST_SW_LIST)
    if swl != [("801780", "银行"), ("801790", "非银金融")]:
        fails.append("申万指数列表解析错误: {}".format(swl))
    # 申万成分解析 + 无效行过滤
    swm = _sw_parse_members(_SELFTEST_SW_MEMBERS)
    if swm != ["600036", "000001"]:
        fails.append("申万成分解析错误: {}".format(swm))
    # 申万 data 为数组形态
    arr_form = {"data": [{"swindexcode": "801010", "swindexname": "农林牧渔"}]}
    if _sw_parse_index_list(arr_form) != [("801010", "农林牧渔")]:
        fails.append("申万 data 数组形态解析失败")
    if fails:
        for x in fails:
            print("[FAIL]", x)
        sys.exit(1)
    print("[SELFTEST PASS] 东财 + 申万解析逻辑正确；mix 模式输出结构示例:")
    print(json.dumps({"concept": {"机器人概念": ["600036", "000001"]},
                      "industry": {"银行": ["600036", "000001"]},
                      "source": "eastmoney+sw",
                      "generated_at": "2026-09-24T10:00:00"},
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
    ap.add_argument("--src", default="mix", choices=["em", "mix", "sw"],
                    help="em=全东财；mix=行业申万+概念东财（默认）；sw=仅申万行业")
    ap.add_argument("--delay", type=float, default=0.12)
    ap.add_argument("--max-boards", type=int, default=0,
                    help="0=全部；>0=每种仅前 N 个（调试用）")
    ap.add_argument("--sw-level", default="l1l2", choices=["l1", "l2", "l1l2"],
                    help="申万行业层级：l1=31个一级；l1l2=一级+二级约165个（默认）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    run(args.src, args.out, delay=args.delay, max_boards=args.max_boards,
        sw_level=args.sw_level)


if __name__ == "__main__":
    main()
