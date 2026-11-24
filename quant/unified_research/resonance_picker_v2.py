# -*- coding: utf-8 -*-
"""
共振优选 v2 —— 真主线龙头模式（用户 2026-11-24 拍板「全闸放宽抓龙头」）
=====================================================================
依据 11-24 数据诊断：v1 的排雷规则系统性排斥了当天最强的主线龙头
（超买/13周涨幅/10日回撤/破位四道"恐高"闸，专挑没涨的防御票）。
v2 调整：
  · 层1 定方向：RDGP 热点股池（成分来自 RDKB，全部为日报 v2 判定的真主线板块）
  · 层2 验真伪：东财主力净流入 f62 > 0 否决闸门（保留，不放宽）
  · 层3 排雷：
      - 硬排雷全部保留：北交所 / ST / 连跌3日
      - 真主线成分【放宽四道技术闸】：超买(当日涨幅>9.5%)、13周涨幅>30%、
        10日回撤>12%、破位(收盘<MA10)
      - 非真主线成分：仍用 v1 严格阈值（本池当前100%为真主线，此分支为兼容保留）
  · 层4 业绩闸（2026-11-24 二次拍板「降级为真·抓龙头」）：
      硬剔除：净利润<0（亏损）、PE>500（极端微利，专挡儒意电影PE2927——用户此前明确剔除）
      降级为标注风险(仍入选)：利润同比<-50%、营收同比<-30%、PE 200~500
      —— 芒果超媒(利润-79%/PE213)、华智数媒(营收-39%) 等昨日强势龙头得以入选并标红
  · 标注：触发过被放宽技术闸、或业绩降级项的票，在 JSON 里打 risk_tags，供平台表格标红提示

数据源与 v1 相同（2026-11-23 实测可用）：
  - RDGP.blk / 东财 push2 ulist.np / 东财 datacenter-web 三大报表 / 本地 .day
⚠ 网络接口用沙箱豁免运行；--dry-run 预演不写盘，确认后去掉参数落盘。
"""
import os
import sys
import json
import time
import struct
import urllib.request
import urllib.parse
import argparse
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
TDX = r"D:\TDX"
BLOCK_DIR = os.path.join(TDX, "T0002", "blocknew")
DAY_DIRS = {"sh": os.path.join(TDX, "vipdoc", "sh", "lday"),
            "sz": os.path.join(TDX, "vipdoc", "sz", "lday")}
HQ = os.path.join(TDX, "T0002", "hq_cache")
INFOHARBOR = os.path.join(HQ, "infoharbor_ex.code")
SECTOR_JSON = r"D:\投研工作台\03-A股盘面信息\板块轮动\sector-rotation-data.json"
CAND_JSON = r"D:\投研工作台\quant\tdx_intraday_watch\热点股池_candidates.json"
OUT_JSON = os.path.join(DATA, "resonance-picks.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://quote.eastmoney.com/"}

# v1 严格阈值（仅用于非真主线成分 + 标注参考）
MAX_PCT = 9.5
MA_SHORT = 10
CONSEC_DOWN = 3
DD_LIMIT = 0.12
GAIN13W_LIMIT = 0.30
# 层4 业绩硬排雷（v2 保留不放宽）
MIN_NP_YOY = -50.0
MIN_REV_YOY = -30.0
MAX_PE = 200.0
HARD_MAX_PE = 500.0     # 极端微利硬闸：PE>500 直接剔除（儒意电影2927/北纬科技815）


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# ---------------- 真主线判定（v2 新增） ----------------
def classify_sector(s):
    """复刻 sync_report_sectors_to_rdkb.py 的报告 v2 判定。"""
    gate = s.get("gate")
    avg = s.get("avgRaw", s.get("avg", 0)) or 0
    if gate == "rebound":
        if avg >= 3.5:
            return "真主线"
        if avg >= 2.8:
            return "真热点"
        return None
    if gate == "pass":
        if avg >= 4.0:
            return "真主线"
        if avg >= 3.2:
            return "真热点"
        return None
    if gate == "weak":
        return "真热点" if avg >= 3.0 else None
    return None


def load_mainline():
    """返回 (真主线板块名list, 真主线成分code集合)。
    逻辑链：日报 v2 判定的真主线板块 → RDKB(由 sync 脚本只写真主线) →
            RDGP(从 RDKB 各板块选成分, 见 candidates.json) → 成分股。
    """
    names = []
    try:
        data = json.load(open(SECTOR_JSON, encoding="utf-8"))
        for s in data:
            if classify_sector(s) == "真主线":
                names.append(s["n"])
    except Exception as e:
        log(f"  ⚠ 日报评分读取失败: {e}")
    codes = set()
    try:
        cd = json.load(open(CAND_JSON, encoding="utf-8"))
        for sec in cd["sectors"]:
            for ch in sec["chosen"]:
                codes.add(ch["code"])
    except Exception as e:
        log(f"  ⚠ 热点股池候选读取失败: {e}")
    return names, codes


# ---------------- 层1：读 RDGP ----------------
def read_rdgp():
    """读热点股池 RDGP，返回 [(market, code)]，market: 1=沪 0=深"""
    p = os.path.join(BLOCK_DIR, "RDGP.blk")
    d = open(p, "rb").read()
    out = []
    for i in range(len(d) // 9):
        rec = d[i * 9:(i + 1) * 9]
        mk = rec[0:1].decode("ascii", "replace")
        code = rec[1:7].decode("ascii", "replace")
        if code.isdigit() and len(code) == 6:
            if code not in [c for _, c in out]:  # 去重（一票可能属多板块）
                out.append((mk, code))
    return out


def secid(market, code):
    return ("1." if market == "1" else "0.") + code


# ---------------- 层3：本地日线排雷 ----------------
def parse_day(code, market):
    mk = "sh" if market == "1" else "sz"
    p = os.path.join(DAY_DIRS[mk], f"{mk}{code}.day")
    if not os.path.exists(p):
        return {}
    try:
        d = open(p, "rb").read()
    except OSError:
        return {}
    n = len(d) // 32
    if n < 30:
        return {}
    vals = struct.unpack("<" + "iiiiifii" * n, d[:32 * n])
    out = {}
    for i in range(n):
        b = i * 8
        out[vals[b]] = {"c": vals[b + 4] / 100.0, "o": vals[b + 1] / 100.0}
    return out


def is_st(code):
    try:
        raw = open(INFOHARBOR, "rb").read().decode("gbk", "ignore")
        for ln in raw.splitlines():
            if code in ln:
                return ("ST" in ln.upper())
    except Exception:
        pass
    return False


def tech_checks(day, relax):
    """返回 (violent, reasons, risk_tags)。relax=True 时跳过四道技术闸。
    risk_tags 记录"被放宽但触发过"的项，供平台标红。
    """
    if not day:
        return True, ["无日线数据"], []
    dates = sorted(day.keys())
    if len(dates) < 65:
        return True, ["日线不足"], []
    closes = [day[d]["c"] for d in dates]
    c = closes[-1]
    hard, tags = [], []

    # 连跌3日（硬排雷，v2 保留不放宽）
    if len(closes) >= CONSEC_DOWN and all(
            closes[-i] < closes[-i - 1] for i in range(1, CONSEC_DOWN + 1)):
        hard.append(f"连跌{CONSEC_DOWN}日")

    ma10 = sum(closes[-10:]) / 10
    if c < ma10:
        (tags if relax else hard).append(f"破MA10({c:.2f}<{ma10:.2f})")

    hi10 = max(closes[-10:])
    dd = (hi10 - c) / hi10 if hi10 > 0 else 0
    if dd > DD_LIMIT:
        (tags if relax else hard).append(f"10日回撤{dd*100:.1f}%")

    if len(closes) > 65:
        g13 = c / closes[-66] - 1
        if g13 > GAIN13W_LIMIT:
            (tags if relax else hard).append(f"13周涨{g13*100:.1f}%")

    return (len(hard) > 0), hard, tags


# ---------------- 层2 + 基本面：东财数据 ----------------
def fetch_quotes(codes_markets):
    secids = ",".join(secid(m, c) for m, c in codes_markets)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?secids=" + secids +
           "&fields=f12,f14,f2,f3,f8,f9,f23,f62,f184"
           "&ut=fa5fd1943c7b386f172d6893dbfba10b")
    req = urllib.request.Request(url, headers=UA)
    r = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore"))
    out = {}
    for it in (r.get("data") or {}).get("diff", []):
        code = it.get("f12")
        def num(k, div=1):
            v = it.get(k)
            if v in (None, "-", ""):
                return None
            try:
                return float(v) / div
            except (ValueError, TypeError):
                return None
        out[code] = {
            "name": it.get("f14"),
            "price": num("f2", 100),
            "pct": num("f3", 100),
            "turnover": num("f8", 100),
            "pe": num("f9", 100),
            "pb": num("f23", 100),
            "main_net": num("f62"),
            "main_ratio": num("f184", 100),
        }
    return out


EM_HOST = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def em_query(report, columns, flt, pagesize=3):
    url = (EM_HOST + "?reportName=" + report + "&columns=" + columns +
           "&filter=" + urllib.parse.quote(flt) + f"&pageSize={pagesize}"
           "&sortColumns=REPORT_DATE&sortTypes=-1&client=PC&source=F10")
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"],
                                                "Referer": "https://emweb.securities.eastmoney.com/"})
    r = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore"))
    if not r.get("success"):
        return []
    return (r.get("result") or {}).get("data", []) or []


def fetch_fundamentals(code):
    try:
        inc = em_query("RPT_DMSK_FN_INCOME",
                       "SECURITY_CODE,SECURITY_NAME_ABBR,INDUSTRY_NAME,REPORT_DATE,"
                       "TOTAL_OPERATE_INCOME,TOI_RATIO,PARENT_NETPROFIT,PARENT_NETPROFIT_RATIO",
                       f'(SECURITY_CODE="{code}")', 3)
        cf = em_query("RPT_DMSK_FN_CASHFLOW",
                      "SECURITY_CODE,REPORT_DATE,NETCASH_OPERATE,CONSTRUCT_LONG_ASSET",
                      f'(SECURITY_CODE="{code}")', 3)
    except Exception as e:
        log(f"  ⚠ {code} 财务接口失败: {e}")
        return None
    if not inc:
        return None
    cur = inc[0]
    industry = cur.get("INDUSTRY_NAME") or "—"
    fcf = None
    if cf and cf[0].get("NETCASH_OPERATE") is not None and cf[0].get("CONSTRUCT_LONG_ASSET") is not None:
        fcf = cf[0]["NETCASH_OPERATE"] - cf[0]["CONSTRUCT_LONG_ASSET"]
    return {"industry": industry, "rev_yoy": cur.get("TOI_RATIO"),
            "np_yoy": cur.get("PARENT_NETPROFIT_RATIO"),
            "net_profit": cur.get("PARENT_NETPROFIT"), "fcf": fcf,
            "report_date": (cur.get("REPORT_DATE") or "")[:10]}


def market_of(market):
    return "沪" if market == "1" else "深"


def fnum(v):
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser(description="共振优选v2 真主线龙头模式")
    ap.add_argument("--dry-run", action="store_true", help="预演：只打印不写盘")
    args = ap.parse_args()

    log("=" * 72)
    log("共振优选 v2 · 真主线龙头模式（全闸放宽抓龙头）" + ("【预演】" if args.dry_run else "【落盘】"))
    log("=" * 72)

    mainline_names, mainline_codes = load_mainline()
    log(f"真主线板块 {len(mainline_names)} 个：{'、'.join(mainline_names[:8])}" +
        ("..." if len(mainline_names) > 8 else ""))
    log(f"真主线成分池 {len(mainline_codes)} 只（来自 RDKB→RDGP）")

    rdgp = read_rdgp()
    log(f"层1 定方向：RDGP 热点股池 {len(rdgp)} 只（去重后）")

    log("层2 验真伪：拉取东财实时资金 + 估值快照...")
    quotes = fetch_quotes(rdgp)
    log(f"  获取快照 {len(quotes)} 只")

    log("层3 排雷：真主线成分放宽四道技术闸，保留ST/北交所/连跌+资金闸门...")
    passed, audit = [], []
    for mk, code in rdgp:
        q = quotes.get(code, {})
        name = q.get("name") or ""
        is_ml = code in mainline_codes
        relax = is_ml  # v2 核心：真主线成分放宽
        hard, tags = [], []

        if code[:2] in ("83", "87", "88", "43", "92"):
            hard.append("北交所")
        if "ST" in name.upper() or is_st(code):
            hard.append("ST")
        main_net = q.get("main_net")
        if main_net is None or main_net <= 0:
            hard.append(f"主力净流出({(main_net or 0)/1e8:.2f}亿)")
        pct = q.get("pct")
        if pct is not None and pct > MAX_PCT:
            (tags if relax else hard).append(f"超买({pct:.1f}%)")

        v, h, t = tech_checks(parse_day(code, mk), relax)
        hard += h
        tags += t

        audit.append({"code": code, "name": name, "mainline": is_ml,
                      "hard": hard, "tags": tags, "passed": not hard,
                      "pct": pct, "main_net": main_net})
        if hard:
            log(f"  ✗ {code} {name} [{'主线' if is_ml else '非主线'}]: {'; '.join(hard)}")
        else:
            log(f"  ✓ {code} {name} [{'主线' if is_ml else '非主线'}]"
                + (f" 放宽标注:{';'.join(tags)}" if tags else ""))
            passed.append((mk, code, q, tags))
    log(f"  通过 {len(passed)}/{len(rdgp)} 只")

    log("层4 业绩闸（降级模式）：硬剔=亏损/PE>500；利润暴雷/营收萎缩/PE200-500 降级为标注...")
    rows = []
    for mk, code, q, tags in passed:
        fund = fetch_fundamentals(code)
        if fund is None:
            rows.append({"code": code, "name": q.get("name") or code,
                         "sector": "—", "fcf": None, "np_yoy": None, "rev_yoy": None,
                         "pe": q.get("pe"), "pb": q.get("pb"), "pct": q.get("pct"),
                         "turnover": q.get("turnover"), "main_net": q.get("main_net"),
                         "market": market_of(mk), "report_date": "—",
                         "risk_tags": tags, "note": "财务数据缺失"})
            continue
        np = fund.get("net_profit")
        np_yoy_v, rev_yoy_v, pe_v = fnum(fund.get("np_yoy")), fnum(fund.get("rev_yoy")), fnum(q.get("pe"))
        # 硬剔除：亏损 + 极端微利PE>500
        hard_fin = []
        if np is not None and np < 0:
            hard_fin.append(f"亏损(净利润{np/1e8:.2f}亿)")
        if pe_v is not None and pe_v > HARD_MAX_PE:
            hard_fin.append(f"极端微利(PE{pe_v:.0f}>500)")
        if hard_fin:
            log(f"  ✗ {code} {q.get('name') or ''}: {'; '.join(hard_fin)}")
            continue
        # 降级为标注（仍入选，供平台标红）
        risk = list(tags)
        if np_yoy_v is not None and np_yoy_v < MIN_NP_YOY:
            risk.append(f"业绩暴雷(利润同比{np_yoy_v:.1f}%)")
        if rev_yoy_v is not None and rev_yoy_v < MIN_REV_YOY:
            risk.append(f"主营萎缩(营收同比{rev_yoy_v:.1f}%)")
        if pe_v is not None and MAX_PE < pe_v <= HARD_MAX_PE:
            risk.append(f"高估值(PE{pe_v:.0f})")
        if risk:
            log(f"  ⚠ {code} {q.get('name') or ''} 标注风险入选: {'; '.join(risk)}")
        rows.append({
            "code": code, "name": q.get("name") or fund.get("industry") or code,
            "sector": fund["industry"], "fcf": fund["fcf"],
            "np_yoy": fund["np_yoy"], "rev_yoy": fund["rev_yoy"],
            "pe": q.get("pe"), "pb": q.get("pb"), "pct": q.get("pct"),
            "turnover": q.get("turnover"), "main_net": q.get("main_net"),
            "market": market_of(mk), "report_date": fund["report_date"],
            "risk_tags": risk, "note": ("风险标注:" + ";".join(risk)) if risk else "",
        })
        time.sleep(0.15)

    log(f"最终入选 {len(rows)} 只")
    for r in rows:
        log(f"    → {r['code']} {r['name']} 涨幅{r.get('pct')}% "
            f"标注:{r.get('risk_tags') or '无'}")

    if args.dry_run:
        log("【预演结束】未写任何文件。确认名单后去掉 --dry-run 落盘。")
        return

    out = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "strategy": "共振优选v2(真主线龙头:放宽超买/13周/回撤/破位,保留业绩+资金硬闸)",
        "fields": ["name", "code", "market", "sector", "fcf", "np_yoy", "rev_yoy",
                   "pe", "pb", "pct", "turnover", "main_net", "report_date", "risk_tags"],
        "mainline_sectors": mainline_names,
        "rows": rows,
    }
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"基本面数据 → {OUT_JSON}")

    if rows:
        codes = [("1" if r["market"] == "沪" else "0") + r["code"] for r in rows]
        write_resonance_block(codes)
    else:
        log("无入选，不写板块")

    log("完成")


def write_resonance_block(codes_market):
    fname = "GXYX"
    p = os.path.join(BLOCK_DIR, fname + ".blk")
    if os.path.exists(p):
        import shutil
        bdir = os.path.join(BASE, "blk_backup")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(p, os.path.join(bdir, f"GXYX_{ts}.blk"))
    content = "".join(f"{c}\r\n" for c in codes_market)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="gbk", newline="") as f:
        f.write(content)
    os.replace(tmp, p)
    log(f"写入通达信板块「共振优选」→ {p} ({len(codes_market)}只)")


if __name__ == "__main__":
    main()
