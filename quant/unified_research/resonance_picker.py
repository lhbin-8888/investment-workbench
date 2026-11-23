# -*- coding: utf-8 -*-
"""
共振优选 —— 分层过滤整合选股（A方案落地）
=============================================
依据《三维度共振验证报告_v2.md》3.2 分层过滤结构：
  层1 定方向：读通达信「热点股池」RDGP（今日17:00更新的强势板块成分股）
  层2 验真伪：东财实时主力净流入 f62 > 0 作否决闸门（净流出剔除）
  层3 排雷  ：ST/*ST、北交所、亏损、超买(涨幅>9.5%)、破位(收盘<MA10)、
              近5日连跌、近10日回撤>12%、近13周涨幅>30%
  层4 业绩质量：剔除业绩暴雷(利润同比<-50% 或 营收同比<-30%)、微利高估(PE>200)，
              避免"净利润微正躲过亏损过滤但利润同比崩塌/PE畸高"的伪成长票（如儒意电影）
产出：
  1) 写入通达信新板块「共振优选」(GXYX.blk)
  2) 生成带完整基本面的 JSON → 供上线平台「个股深度」板块表格渲染
     字段：名称/代码/所属板块/自由现金流/利润同比/营收同比/PE/PB/当日涨幅/换手率

数据源（全部已实测可用，2026-11-23）：
  - RDGP.blk（9字节记录格式）
  - 东财批量快照 push2 ulist.np（f62主力净流入/f9 PE/f23 PB/f3涨幅/f8换手/f14名称）
  - 东财三大报表 datacenter-web RPT_DMSK_FN_{INCOME,CASHFLOW}（营收同比/利润同比/自由现金流/行业）
  - 本地 .day 日线（排雷用）

⚠ 网络接口需沙箱豁免（dangerouslyDisableSandbox）运行。
"""
import os
import re
import json
import time
import struct
import urllib.request
import urllib.parse
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
TDX = r"D:\TDX"
BLOCK_DIR = os.path.join(TDX, "T0002", "blocknew")
DAY_DIRS = {"sh": os.path.join(TDX, "vipdoc", "sh", "lday"),
            "sz": os.path.join(TDX, "vipdoc", "sz", "lday")}
HQ = os.path.join(TDX, "T0002", "hq_cache")
TDXHY = os.path.join(HQ, "tdxhy.cfg")
INFOHARBOR = os.path.join(TDX, "T0002", "hq_cache", "infoharbor_ex.code")
BENCH = os.path.join(TDX, "vipdoc", "sh", "lday", "sh000001.day")

OUT_JSON = os.path.join(DATA, "resonance-picks.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://quote.eastmoney.com/"}

# 排雷阈值
MAX_PCT = 9.5          # 当日涨幅上限（超买不追）
MA_SHORT = 10          # 破位判定均线
CONSEC_DOWN = 3        # 连跌天数
DD_LIMIT = 0.12        # 近10日回撤上限
GAIN13W_LIMIT = 0.30   # 近13周涨幅上限
# 层4 业绩质量阈值（剔除"微利躲过亏损过滤"的伪成长票）
MIN_NP_YOY = -50.0     # 利润同比下限%，低于此视为业绩暴雷（儒意电影-99.2%）
MIN_REV_YOY = -30.0    # 营收同比下限%，低于此视为主营萎缩
MAX_PE = 200.0         # PE上限，高于此视为微利/估值泡沫（儒意电影2859）


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# ---------------- 层1：读 RDGP ----------------
def read_rdgp():
    """读热点股池 RDGP，返回 [(market, code)]，market: 1=沪 0=深"""
    p = os.path.join(BLOCK_DIR, "RDGP.blk")
    d = open(p, "rb").read()
    n = len(d) // 9
    out = []
    for i in range(n):
        rec = d[i * 9:(i + 1) * 9]
        mk = rec[0:1].decode("ascii", "replace")
        code = rec[1:7].decode("ascii", "replace")
        if code.isdigit() and len(code) == 6:
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
        out[vals[b]] = {"c": vals[b + 4] / 100.0, "o": vals[b + 1] / 100.0,
                        "amt": vals[b + 5], "vol": vals[b + 6]}
    return out


def is_st(code):
    """从 infoharbor_ex.code 判定 ST/*ST"""
    try:
        raw = open(INFOHARBOR, "rb").read().decode("gbk", "ignore")
        for ln in raw.splitlines():
            if code in ln:
                # 名称字段通常含 ST 标记
                return ("ST" in ln.upper())
    except Exception:
        pass
    return False


def is_loss(code):
    """从东财报表净利润判定亏损（在基本面阶段取，这里占位返回False）"""
    return False  # 实际在 fetch_fundamentals 里用 PARENT_NETPROFIT<0 剔除


def dedup_check(day):
    """返回 (是否 violent, 说明)。violent=True 表示应剔除"""
    if not day:
        return True, "无日线数据"
    dates = sorted(day.keys())
    if len(dates) < 65:
        return True, "日线不足"
    closes = [day[d]["c"] for d in dates]
    c = closes[-1]
    # 破位
    ma10 = sum(closes[-10:]) / 10
    if c < ma10:
        return True, f"破MA10({c:.2f}<{ma10:.2f})"
    # 连跌
    if len(closes) >= CONSEC_DOWN and all(closes[-i] < closes[-i - 1] for i in range(1, CONSEC_DOWN + 1)):
        return True, f"连跌{CONSEC_DOWN}日"
    # 近10日回撤
    hi10 = max(closes[-10:])
    dd = (hi10 - c) / hi10 if hi10 > 0 else 0
    if dd > DD_LIMIT:
        return True, f"10日回撤{dd*100:.1f}%"
    # 近13周涨幅
    if len(closes) > 65:
        g13 = c / closes[-66] - 1
        if g13 > GAIN13W_LIMIT:
            return True, f"13周涨{g13*100:.1f}%"
    return False, ""


# ---------------- 层2 + 基本面：东财数据 ----------------
def fetch_quotes(codes_markets):
    """东财批量快照，返回 {code: {...}}"""
    secids = ",".join(secid(m, c) for m, c in codes_markets)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?secids=" + secids +
           "&fields=f12,f14,f2,f3,f8,f9,f23,f62,f184,f20,f21"
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
            "pct": num("f3", 100),      # 当日涨幅%
            "turnover": num("f8", 100), # 换手率%
            "pe": num("f9", 100),       # PE动态
            "pb": num("f23", 100),      # PB
            "main_net": num("f62"),     # 主力净流入(元)
            "main_ratio": num("f184", 100),  # 主力净占比%
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
    """三大报表：行业/自由现金流/营收同比/利润同比/净利润"""
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
    rev_yoy = cur.get("TOI_RATIO")          # 营收同比%
    np_yoy = cur.get("PARENT_NETPROFIT_RATIO")  # 利润同比%
    np = cur.get("PARENT_NETPROFIT")
    industry = cur.get("INDUSTRY_NAME") or "—"
    report_date = (cur.get("REPORT_DATE") or "")[:10]
    fcf = None
    if cf:
        op = cf[0].get("NETCASH_OPERATE")
        capex = cf[0].get("CONSTRUCT_LONG_ASSET")
        if op is not None and capex is not None:
            fcf = op - capex
    return {"industry": industry, "rev_yoy": rev_yoy, "np_yoy": np_yoy,
            "net_profit": np, "fcf": fcf, "report_date": report_date}


def market_of(market):
    return "沪" if market == "1" else "深"


def main():
    log("=" * 70)
    log("共振优选 · 分层过滤整合选股（RDGP定方向 → 资金闸门 → 排雷）")
    log("=" * 70)

    # 层1
    rdgp = read_rdgp()
    log(f"层1 定方向：RDGP热点股池 {len(rdgp)} 只")
    markets = {c: m for m, c in rdgp}

    # 层2：资金闸门（东财批量快照）
    log("层2 验真伪：拉取东财实时资金 + 估值快照...")
    quotes = fetch_quotes(rdgp)
    log(f"  获取快照 {len(quotes)} 只")

    # 层3：排雷 + 资金闸门判定
    log("层3 排雷：ST/北交所/亏损/超买/破位/连跌/回撤/13周涨幅...")
    passed = []
    for mk, code in rdgp:
        q = quotes.get(code, {})
        reasons = []
        # 北交所
        if code[:2] in ("83", "87", "88", "43", "92"):
            reasons.append("北交所")
        # ST（快照名称含ST更可靠）
        name = q.get("name") or ""
        if "ST" in name.upper() or is_st(code):
            reasons.append("ST")
        # 资金闸门：主力净流入 > 0
        main_net = q.get("main_net")
        if main_net is None or main_net <= 0:
            reasons.append(f"主力净流出({(main_net or 0)/1e8:.2f}亿)")
        # 当日涨幅超买
        pct = q.get("pct")
        if pct is not None and pct > MAX_PCT:
            reasons.append(f"超买({pct:.1f}%)")
        # 本地排雷
        day = parse_day(code, mk)
        violent, why = dedup_check(day)
        if violent:
            reasons.append(why)
        if reasons:
            log(f"  ✗ {code} {name}: {'; '.join(reasons)}")
        else:
            passed.append((mk, code, q))
    log(f"  通过 {len(passed)}/{len(rdgp)} 只")

    # 基本面补全 + 亏损剔除
    log("补全基本面（营收同比/利润同比/自由现金流/行业）...")
    rows = []
    for mk, code, q in passed:
        fund = fetch_fundamentals(code)
        if fund is None:
            rows.append({"code": code, "name": q.get("name") or code,
                         "sector": "—", "fcf": None, "np_yoy": None, "rev_yoy": None,
                         "pe": q.get("pe"), "pb": q.get("pb"),
                         "pct": q.get("pct"), "turnover": q.get("turnover"),
                         "main_net": q.get("main_net"), "market": market_of(mk),
                         "report_date": "—", "note": "财务数据缺失"})
            continue
        # 亏损剔除
        if fund.get("net_profit") is not None and fund["net_profit"] < 0:
            log(f"  ✗ {code} 亏损(净利润{fund['net_profit']/1e8:.2f}亿)")
            continue
        # 层4 业绩质量过滤：剔除微利暴雷/主营萎缩/高PE伪成长票
        def fnum(v):
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None
        np_yoy_v = fnum(fund.get("np_yoy"))
        rev_yoy_v = fnum(fund.get("rev_yoy"))
        pe_v = fnum(q.get("pe"))
        q_reasons = []
        if np_yoy_v is not None and np_yoy_v < MIN_NP_YOY:
            q_reasons.append(f"业绩暴雷(利润同比{np_yoy_v:.1f}%)")
        if rev_yoy_v is not None and rev_yoy_v < MIN_REV_YOY:
            q_reasons.append(f"主营萎缩(营收同比{rev_yoy_v:.1f}%)")
        if pe_v is not None and pe_v > MAX_PE:
            q_reasons.append(f"微利高估(PE{pe_v:.0f})")
        if q_reasons:
            log(f"  ✗ {code} {q.get('name') or ''}: {'; '.join(q_reasons)}")
            continue
        rows.append({
            "code": code, "name": q.get("name") or fund.get("industry") or code,
            "sector": fund["industry"], "fcf": fund["fcf"],
            "np_yoy": fund["np_yoy"], "rev_yoy": fund["rev_yoy"],
            "pe": q.get("pe"), "pb": q.get("pb"),
            "pct": q.get("pct"), "turnover": q.get("turnover"),
            "main_net": q.get("main_net"), "market": market_of(mk),
            "report_date": fund["report_date"], "note": "",
        })
        time.sleep(0.15)

    log(f"最终入选 {len(rows)} 只")

    # 写出 JSON（供上线平台用）
    out = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "strategy": "共振优选(热点定方向+主力资金验真+多因子排雷)",
        "fields": ["name", "code", "market", "sector", "fcf", "np_yoy", "rev_yoy",
                   "pe", "pb", "pct", "turnover", "main_net", "report_date"],
        "rows": rows,
    }
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"基本面数据 → {OUT_JSON}")

    # 写通达信板块
    if rows:
        codes = [("1" if r["market"] == "沪" else "0") + r["code"] for r in rows]
        # 用 tdx_writer 的 write_block 需要纯6位代码+自动判市场，这里直接写 blk
        write_resonance_block(codes)
    else:
        log("无入选，不写板块（清空由人工决定）")

    log("完成")


def write_resonance_block(codes_market):
    """直接写 GXYX.blk（9字节记录：市场标志+6位代码+\\r\\n），并注册板块"""
    fname = "GXYX"
    p = os.path.join(BLOCK_DIR, fname + ".blk")
    # 备份
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

    # 注册到 blocknew.cfg（若未注册）
    try:
        import sys
        sys.path.insert(0, r"D:\投研工作台\quant\tdx_autopick")
        import tdx_writer
        cfg = tdx_writer.CFG_PATH
        raw = open(cfg, "rb").read()
        if b"GXYX" not in raw:
            ok, msg = tdx_writer.register_block("共振优选", "GXYX")
            log(f"  注册板块: {ok} {msg}")
        else:
            log("  板块已注册")
    except Exception as e:
        log(f"  ⚠ 注册检查失败(不影响.blk): {e}")


if __name__ == "__main__":
    main()
