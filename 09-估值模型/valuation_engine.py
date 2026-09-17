# -*- coding: utf-8 -*-
"""
个股估值引擎  ·  投研工作台「估值模型」板块
=========================================
依据用户「个股估值」技能（《估值的底层逻辑和具体的应用方法》）的框架实现：
  第一步：判断公司类型（6 类）
  第二步：按类型选主估值尺（DCF / PE / PEG / PS / PB）
  第三步：至少两把尺子交叉验证，划出内在价值区间与安全边际

数据来源（均无需 API Key，与财务分析模块同源）：
  - 东方财富 datacenter-web.eastmoney.com  → 三大财务报表 / 同业 / 分红
  - 腾讯 qt.gtimg.cn                      → 实时行情、PE(TTM)、总市值、换手率

启动方式（命令行 / 离线参考实现；网页版请直接用 09-估值模型/vm.html，纯前端无需本文件）：
  python valuation_engine.py 600176                  # 生成静态 HTML 报告
  python valuation_engine.py 中国巨石                 # 支持名称输入
  python valuation_engine.py 600176 --pdf            # 同时导出 PDF
  python valuation_engine.py 600176 --out D:/报告     # 指定输出目录
"""

import sys
import os
import json
import ssl
import urllib.request
import urllib.parse
import urllib.error
import datetime
import subprocess
import shutil

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/",
}

EM_HOST = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def http_get(url, enc="utf-8", ref=None, timeout=25):
    headers = dict(HEADERS)
    if ref:
        headers["Referer"] = ref
    last_err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode(enc)
        except Exception as e:
            last_err = e
    raise RuntimeError("网络请求失败: %s | %s" % (url[:90], last_err))


def em_query(report, columns, flt, pagesize=14, sort_col="REPORT_DATE", sort_type=-1):
    url = (f"{EM_HOST}?reportName={report}&columns={columns}&filter={urllib.parse.quote(flt)}"
           f"&pageSize={pagesize}&sortColumns={sort_col}&sortTypes={sort_type}&client=PC&source=F10")
    d = json.loads(http_get(url))
    if not d.get("success"):
        return []
    res = d.get("result") or {}
    return res.get("data") or []


# ---------------------------------------------------------------------------
# PDF 导出（复用工作台 Edge 无头打印，与 08-财务分析/stock_analyzer.py 同口径）
# ---------------------------------------------------------------------------
def find_edge():
    for c in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.isfile(c):
            return c
    return None


EDGE = find_edge()


def render_pdf(html_text, pdf_path, keep_html=False):
    """用本机 Edge/Chrome 无头模式把 HTML 渲染为 PDF。"""
    if not EDGE:
        raise RuntimeError("未找到 Edge/Chrome 浏览器，无法导出 PDF（请安装 Microsoft Edge）")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp_dir = os.path.join(repo_root, "archive", "temp_vm")
    os.makedirs(tmp_dir, exist_ok=True)
    html_path = os.path.join(tmp_dir, "_vm_tmp.html")
    edge_out = os.path.join(tmp_dir, "_vm_out.pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    cmd = [
        EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        "--no-first-run", "--disable-extensions",
        # 独立配置目录：避免与用户正在使用的 Edge 实例抢 profile 导致打印失败
        "--user-data-dir=%s" % os.path.join(tmp_dir, "_edge_profile"),
        "--run-all-compositor-stages-before-draw",
        "--print-to-pdf=%s" % os.path.abspath(edge_out),
        html_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=180)
    try:
        if not keep_html:
            os.remove(html_path)
    except OSError:
        pass
    if not os.path.exists(edge_out) or os.path.getsize(edge_out) < 1024:
        raise RuntimeError("PDF 渲染失败（Edge 无头打印未输出有效文件）")
    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    except OSError:
        pass
    shutil.move(edge_out, pdf_path)
    try:
        if not list(os.scandir(tmp_dir)):
            os.rmdir(tmp_dir)
    except OSError:
        pass
    return pdf_path


# ---------------------------------------------------------------------------
# 名称 / 代码 解析
# ---------------------------------------------------------------------------
def market_prefix(code):
    if code.startswith("6") or code.startswith("9"):
        return "sh"
    if code.startswith("0") or code.startswith("3"):
        return "sz"
    if code.startswith("8") or code.startswith("4"):
        return "bj"
    return "sh"


def resolve_code(query):
    q = query.strip()
    if q.isdigit() and len(q) == 6:
        return q
    flt = '(SECURITY_NAME_ABBR="%s")' % q
    rows = em_query("RPT_DMSK_FN_INCOME", "SECURITY_CODE,SECURITY_NAME_ABBR", flt, 5)
    if rows:
        return rows[0]["SECURITY_CODE"]
    raise ValueError("未匹配到股票：%s（请确认证券简称，或直接输入 6 位代码，如 600176）" % query)


# ---------------------------------------------------------------------------
# 行情 / 估值（腾讯）
# ---------------------------------------------------------------------------
def fetch_quote(code):
    prefix = market_prefix(code)
    url = "https://qt.gtimg.cn/q=%s%s" % (prefix, code)
    txt = http_get(url, enc="gbk", ref="https://gu.qq.com/")
    part = txt.split('="')[1].rstrip('";\n')
    f = part.split("~")
    num = lambda i: (f[i] and float(f[i])) if len(f) > i and f[i] else None
    return {
        "price": num(3), "prev_close": num(4), "change_pct": num(32),
        "turnover": num(38), "pe_ttm": num(39), "mktcap_yi": num(44),
        "quote_time": f[30] if len(f) > 30 else "",
    }


# ---------------------------------------------------------------------------
# 财务报表拉取
# ---------------------------------------------------------------------------
def fetch_income(code, pagesize=14):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,INDUSTRY_CODE,INDUSTRY_NAME,REPORT_DATE,"
            "TOTAL_OPERATE_INCOME,OPERATE_COST,PARENT_NETPROFIT,DEDUCT_PARENT_NETPROFIT,"
            "TOI_RATIO,PARENT_NETPROFIT_RATIO,DPN_RATIO")
    return em_query("RPT_DMSK_FN_INCOME", cols, '(SECURITY_CODE="%s")' % code, pagesize)


def fetch_balance(code, pagesize=14):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,TOTAL_ASSETS,TOTAL_LIABILITIES,"
            "TOTAL_EQUITY,DEBT_ASSET_RATIO,CURRENT_RATIO,ACCOUNTS_RECE,INVENTORY,MONETARYFUNDS,FIXED_ASSET")
    return em_query("RPT_DMSK_FN_BALANCE", cols, '(SECURITY_CODE="%s")' % code, pagesize)


def fetch_cashflow(code, pagesize=14):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,NETCASH_OPERATE,NETCASH_INVEST,"
            "CONSTRUCT_LONG_ASSET,SALES_SERVICES")
    return em_query("RPT_DMSK_FN_CASHFLOW", cols, '(SECURITY_CODE="%s")' % code, pagesize)


def fetch_industry(report, ind_code, cols, pagesize=80):
    return em_query(report, cols, '(INDUSTRY_CODE="%s")' % ind_code, pagesize)


def fetch_dividend(code):
    """尝试获取最新每股股利（税前，TTM），用于股息率估算。失败返回 None。"""
    try:
        rows = em_query("RPT_F10_FN_DIVIDEND",
                        "SECURITY_CODE,REPORT_DATE,DIVIDEND_RATIO,DIVIDEND_RATIO_TTM",
                        '(SECURITY_CODE="%s")' % code, 6)
        if not rows:
            return None
        rows.sort(key=lambda r: (r.get("REPORT_DATE") or ""), reverse=True)
        for r in rows:
            for k in ("DIVIDEND_RATIO_TTM", "DIVIDEND_RATIO"):
                v = r.get(k)
                if v not in (None, 0):
                    return float(v)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def safe_div(a, b):
    try:
        if b in (None, 0):
            return None
        return a / b
    except Exception:
        return None


def period_label(date_str):
    d = (date_str or "")[:10]
    if len(d) < 7:
        return d
    y, m = d.split("-")[:2]
    return {"03": f"{y}Q1", "06": f"{y}半年", "09": f"{y}Q3", "12": f"{y}年报"}.get(m, d)


def find_prior(rows, cur_date):
    earlier = [r for r in rows if (r.get("REPORT_DATE") or "")[:10] < (cur_date or "")[:10]]
    return max(earlier, key=lambda r: (r.get("REPORT_DATE") or "")) if earlier else None


def latest_by(rows):
    return max(rows, key=lambda r: (r.get("REPORT_DATE") or "")) if rows else None


def yi(v):
    return "—" if v is None else "%.2f" % (v / 1e8)


def pct(v, digits=2):
    return "—" if v is None else ("%.2f" % v) + "%"


def median(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


# ---------------------------------------------------------------------------
# 第一步：判断公司类型
# ---------------------------------------------------------------------------
FINANCIAL_KW = ["银行", "保险", "证券", "信托", "期货", "基金"]
CYCLICAL_KW = ["钢铁", "有色", "煤炭", "航运", "水泥", "工程机械", "化工", "石油", "天然气",
               "电力", "地产", "券商", "养殖", "面板", "光伏", "机场", "港口", "造纸", "玻纤",
               "航运", "海运", "铜", "铝", "锂", "镍", "锌", "黄金", "石化", "航运"]

# 无形资产型（品牌 / 网络效应）关键词：PB 会失真
INTANGIBLE_KW = ["白酒", "啤酒", "饮料", "互联网", "软件", "传媒", "品牌", "化妆品", "医美",
                 "院线", "游戏", "社交", "电商"]


def classify(cur, annual_inc, ind_name):
    """返回 (类型代码, 类型名, 生命周期/周期位置描述, 判定依据列表)。"""
    reasons = []
    np_ = cur["np"]
    nm = cur["net_margin"] or 0
    gp = cur["gp_margin"] or 0
    roe = cur["roe_ann"] or 0
    # 近年净利增速（年报序列）
    g = None
    if len(annual_inc) >= 2:
        n0 = annual_inc[0]["np"]; n1 = annual_inc[-1]["np"]
        yrs = len(annual_inc) - 1
        if n0 and n1 and n0 > 0:
            g = ((n1 / n0) ** (1.0 / yrs) - 1) * 100
    # ROE 波动（周期性强弱代理）
    roes = [a["roe"] for a in annual_inc if a.get("roe") is not None]
    roe_vol = (max(roes) - min(roes)) if len(roes) >= 2 else 0

    if any(k in ind_name for k in FINANCIAL_KW):
        stage = "重资产 / 金融，资产负债表是核心，关注资产质量与资本回报"
        return "financial", "重资产/金融型", stage, ["所属行业为银行/保险/证券等金融业态，适用 PB + 股息率"]
    if (np_ is not None and np_ <= 0):
        stage = "利润仍未转正，市场讲的是 PS 语言（看增速/份额/用户）；跨越盈亏平衡后才会切到 PE"
        return "loss", "亏损高增长型", stage, ["最新报告期归母净利润 <= 0，PE 失效，改用 PS（合理PS = 终局净利率 × 终局PE）"]
    if any(k in ind_name for k in CYCLICAL_KW):
        stage = "强周期行业，盈利随周期大幅波动；亏损期 PE 失效，用 PS+PB，并判断朱格拉周期位置"
        return "cyclical", "强周期型", stage, ["所属行业为强周期行业，盈利波动大，用 PS（亏损期）+ PB 双尺验证"]
    if g is not None and g >= 20 and roe_vol < 0.25:
        stage = "净利润持续中高速增长，适用 PEG（彼得·林奇修正指标）"
        return "growth", "稳定成长型", stage, ["近 %d 年净利 CAGR≈%.0f%%（≥20%%）且 ROE 波动较小，适用 PEG" % (len(annual_inc) - 1, g)]
    if any(k in ind_name for k in INTANGIBLE_KW) and nm >= 0.15 and gp >= 0.40:
        stage = "品牌/网络效应驱动，最值钱的资产不在账面，PB 会失真；用 PE/DCF，PB 跌破 1 反而是机会"
        return "intangible", "无形资产型", stage, ["高毛利+高净利且属品牌/平台类，PB 失真，主尺 PE/DCF，副尺警惕 PB 误判"]
    # 默认：成熟稳定盈利
    stage = "利润稳定、现金流好、已过成长期，适用 PE + DCF 两阶段模型"
    return "mature", "成熟稳定盈利型", stage, ["利润稳定、经营现金流为正，适用 PE + DCF 双尺交叉验证"]


# ---------------------------------------------------------------------------
# 第二步：用主尺计算
# ---------------------------------------------------------------------------
def value_dcf(cur, shares, net_cash, ind_name, pessimistic=False):
    """两阶段 DCF。需要 FCF 与总股本。返回 (每股价值, 明细dict)。"""
    fcf0 = cur.get("fcf")
    if fcf0 is None or fcf0 <= 0 or shares is None or shares <= 0:
        return None, {"ok": False, "reason": "FCF 缺失或非正，跳过 DCF（改用相对估值）"}
    # 保守增速：取近年净利 CAGR 与 12% 的较小值，亏损期不适用
    R = 0.12 if pessimistic else 0.09
    G = 0.01 if pessimistic else 0.015
    N = 3
    # 用历史 FCF 序列趋势推断增速，缺省 8%
    g = 0.08
    # 简易：以净利润增速代理（若更优数据可得可替换）
    fcf_series = cur.get("fcf_series") or []
    if len(fcf_series) >= 2:
        try:
            g0 = ((fcf_series[-1] / fcf_series[0]) ** (1.0 / (len(fcf_series) - 1)) - 1)
            g = min(max(g0, 0.0), 0.15)
        except Exception:
            pass
    if pessimistic:
        g = min(g, 0.05)
    # 各年 FCF 折现值
    pv_sum = 0.0
    fcf_n = fcf0
    details = []
    for n in range(1, N + 1):
        fcf_n = fcf_n * (1 + g)
        pv = fcf_n / ((1 + R) ** n)
        pv_sum += pv
        details.append({"year": n, "fcf_yi": fcf_n / 1e8, "pv_yi": pv / 1e8})
    # 永续期
    fcf_terminal = fcf_n * (1 + G)
    tv = fcf_terminal / (R - G)
    tv_pv = tv / ((1 + R) ** N)
    ev = pv_sum + tv_pv
    equity = ev + (net_cash or 0)
    per_share = equity / shares
    return per_share, {
        "ok": True, "R": R, "G": G, "N": N, "g": g, "fcf0_yi": fcf0 / 1e8,
        "pv_sum_yi": pv_sum / 1e8, "tv_pv_yi": tv_pv / 1e8,
        "net_cash_yi": (net_cash or 0) / 1e8, "ev_yi": ev / 1e8,
        "equity_yi": equity / 1e8, "per_share": per_share, "details": details,
    }


def value_pe(cur, mktcap, price, shares, ind_name, growth=None):
    """PE 主尺：给合理 PE 区间，算合理股价，并与国债利率比。"""
    np_ = cur["np"]
    if np_ is None or np_ <= 0 or shares is None:
        return None, {"ok": False}
    eps = np_ / shares
    R = 0.09
    # 成熟/稳定：合理 PE 中枢 ~ 1/R（≈11）；成长用 PEG=1 → 合理PE=增速%
    pe_mid = round(1.0 / R, 1)
    if growth is not None and growth > 0:
        pe_growth = growth  # PEG=1
        pe_mid = round(median([pe_mid, pe_growth, 20]) if growth >= 12 else median([pe_mid, pe_growth]), 1)
    pe_low = round(pe_mid * 0.85, 1)
    pe_high = round(pe_mid * 1.15, 1)
    price_mid = eps * pe_mid
    price_low = eps * pe_low
    price_high = eps * pe_high
    return price_mid, {
        "ok": True, "eps": eps, "pe_mid": pe_mid, "pe_low": pe_low, "pe_high": pe_high,
        "price_low": price_low, "price_high": price_high,
        "rf_note": "盈利收益率(1/PE) 与十年期国债(~2.5%)比较：PE<40 即收益率>2.5%，有吸引力",
    }


def value_peg(cur, pe_ttm, growth):
    """PEG 主尺：PEG=1 为合理，算合理 PE 与股价。"""
    if pe_ttm is None or growth is None or growth <= 0:
        return None, {"ok": False}
    peg = pe_ttm / growth
    fair_pe = growth  # PEG=1
    eps = cur.get("eps")
    if eps is None or eps <= 0:
        return None, {"ok": False, "reason": "无 EPS 无法算 PEG 股价"}
    fair_price = eps * fair_pe
    return fair_price, {"ok": True, "peg": peg, "fair_pe": fair_pe, "eps": eps, "fair_price": fair_price}


def value_ps(cur, mktcap, price, shares, ind_name, terminal_margin=None, terminal_pe=18):
    """PS 主尺：合理PS = 终局净利率 × 终局PE。"""
    rev = cur["rev"]
    if rev is None or rev <= 0 or shares is None:
        return None, {"ok": False}
    nm = terminal_margin if terminal_margin is not None else (cur["net_margin"] or 0.05)
    # 封顶/兜底：避免用周期峰值净利率高估 PS（终局净利率上限 20%，下限 3%）
    nm = min(max(nm, 0.03), 0.20)
    fair_ps = nm * terminal_pe
    rev_per_share = rev / shares
    fair_price = rev_per_share * fair_ps
    return fair_price, {"ok": True, "rev_per_share": rev_per_share, "terminal_margin": nm,
                        "terminal_pe": terminal_pe, "fair_ps": fair_ps, "fair_price": fair_price}


def value_pb(cur, mktcap, price, equity, roe, ind_name):
    """PB 主尺（重资产/金融/周期）：用 ROE 推导合理 PB。"""
    if equity is None or equity <= 0:
        return None, {"ok": False}
    R = 0.09
    fair_pb = (roe / R) if (roe and roe > 0) else 1.0
    fair_price = (equity / (mktcap * 1e8 / price if mktcap and price else (equity / (price or 1)))) \
        if (mktcap and price) else None
    # 直接用净资产/股 * 合理PB
    shares = (mktcap * 1e8 / price) if (mktcap and price) else None
    if shares:
        bvps = equity / shares
        fair_price = bvps * fair_pb
        return fair_price, {"ok": True, "bvps": bvps, "fair_pb": fair_pb, "roe": roe, "R": R, "fair_price": fair_price}
    return None, {"ok": False}


# ---------------------------------------------------------------------------
# 第三步：交叉验证 + 结论组装
# ---------------------------------------------------------------------------
def analyze_valuation(code):
    code = resolve_code(code)
    inc = fetch_income(code, 14)
    bal = fetch_balance(code, 14)
    cf = fetch_cashflow(code, 14)
    if not inc or not bal:
        raise RuntimeError("未获取到 %s 的财务数据，可能已退市或非 A 股" % code)

    cur_inc = latest_by(inc)
    cur_bal = latest_by(bal)
    cur_cf = latest_by(cf)
    cur_date = (cur_inc.get("REPORT_DATE") or "")[:10]
    name = cur_inc.get("SECURITY_NAME_ABBR") or cur_bal.get("SECURITY_NAME_ABBR") or code
    ind_code = cur_inc.get("INDUSTRY_CODE")
    ind_name = cur_inc.get("INDUSTRY_NAME") or "—"

    rev = cur_inc.get("TOTAL_OPERATE_INCOME")
    cost = cur_inc.get("OPERATE_COST")
    np_ = cur_inc.get("PARENT_NETPROFIT")
    gp = (rev - cost) if (rev is not None and cost is not None) else None
    gp_margin = safe_div(gp, rev)
    net_margin = safe_div(np_, rev)

    op_cf = cur_cf.get("NETCASH_OPERATE") if cur_cf else None
    capex = cur_cf.get("CONSTRUCT_LONG_ASSET") if cur_cf else None
    fcf = (op_cf - capex) if (op_cf is not None and capex is not None) else None

    equity = cur_bal.get("TOTAL_EQUITY")
    monetary = cur_bal.get("MONETARYFUNDS")
    # 有息债务近似：用负债合计 - 无息部分不可得，简化取 0（保守按净现金=货币资金）
    net_cash = monetary if monetary is not None else None

    q = fetch_quote(code)
    price = q.get("price")
    pe_ttm = q.get("pe_ttm")
    mktcap = q.get("mktcap_yi")
    shares = safe_div(mktcap * 1e8, price) if (mktcap and price) else None
    pb = safe_div((mktcap * 1e8) if mktcap else None, equity) if equity else None

    # 年报序列（用于成长性 + 估值）
    annual_inc = sorted([r for r in inc if (r.get("REPORT_DATE") or "")[5:7] == "12"],
                        key=lambda r: r.get("REPORT_DATE") or "")
    trend = []
    for r in annual_inc:
        y = (r.get("REPORT_DATE") or "")[:4]
        rv = r.get("TOTAL_OPERATE_INCOME"); npp = r.get("PARENT_NETPROFIT"); c = r.get("OPERATE_COST")
        g = (rv - c) if (rv is not None and c is not None) else None
        trend.append({"period": y + "年报", "rev": rv, "np": npp,
                      "gp_margin": safe_div(g, rv), "net_margin": safe_div(npp, rv),
                      "roe": safe_div(npp, r.get("TOTAL_EQUITY"))})

    # 历史增速
    g_np = None
    if len(trend) >= 2:
        n0 = trend[0]["np"]; n1 = trend[-1]["np"]; yrs = len(trend) - 1
        if n0 and n1 and n0 > 0:
            g_np = ((n1 / n0) ** (1.0 / yrs) - 1) * 100
    fcf_series = [r.get("NETCASH_OPERATE") for r in sorted(cf, key=lambda r: r.get("REPORT_DATE") or "") if r.get("NETCASH_OPERATE")]

    roe_ann = safe_div(np_, equity)
    cur = {
        "rev": rev, "np": np_, "gp_margin": gp_margin, "net_margin": net_margin,
        "fcf": fcf, "fcf_series": fcf_series, "equity": equity, "roe_ann": roe_ann,
        "eps": safe_div(np_, shares) if shares else None,
    }

    ctype, cname, stage, reasons = classify(cur, trend, ind_name)

    # ---- 估值计算（按类型选主尺 + 副尺） ----
    methods = {}
    # 通用 PE
    pe_res = value_pe(cur, mktcap, price, shares, ind_name, growth=g_np)
    # DCF（现金流可预测时）
    dcf_neu, dcf_neu_d = value_dcf(cur, shares, net_cash, ind_name, pessimistic=False)
    dcf_pes, dcf_pes_d = value_dcf(cur, shares, net_cash, ind_name, pessimistic=True)
    # PEG
    peg_res = value_peg(cur, pe_ttm, g_np) if g_np else (None, {"ok": False})
    # PS
    ps_res = value_ps(cur, mktcap, price, shares, ind_name)
    # PB
    pb_res = value_pb(cur, mktcap, price, equity, roe_ann, ind_name)

    main = {}; cross = []
    if ctype in ("mature", "intangible"):
        main = {"尺": "PE + DCF", "pe": pe_res[1], "dcf_neu": dcf_neu_d, "dcf_pes": dcf_pes_d}
        if dcf_neu: cross.append(("DCF(中性)", dcf_neu))
        if dcf_pes: cross.append(("DCF(悲观)", dcf_pes))
        if pe_res[0]: cross.append(("PE 中枢", pe_res[0]))
    elif ctype == "growth":
        main = {"尺": "PEG", "peg": peg_res[1], "pe": pe_res[1]}
        if peg_res[0]: cross.append(("PEG 合理价", peg_res[0]))
        if pe_res[0]: cross.append(("PE 中枢", pe_res[0]))
    elif ctype == "loss":
        main = {"尺": "PS", "ps": ps_res[1]}
        if ps_res[0]: cross.append(("PS 合理价", ps_res[0]))
    elif ctype == "cyclical":
        main = {"尺": "PS + PB", "ps": ps_res[1], "pb": pb_res[1]}
        if ps_res[0]: cross.append(("PS 合理价", ps_res[0]))
        if pb_res[0]: cross.append(("PB 合理价", pb_res[0]))
    elif ctype == "financial":
        main = {"尺": "PB + 股息率", "pb": pb_res[1]}
        if pb_res[0]: cross.append(("PB 合理价", pb_res[0]))

    # 内在价值区间：仅取本类型实际使用的交叉验证方法（避免把不适用的方法拉偏区间）
    vals = [v for (_, v) in cross if v is not None and v > 0]
    if vals:
        low = min(vals); high = max(vals)
    else:
        low = high = None
    # 区间标签按类型区分（DCF 型用悲观/中性情景；相对估值型用上下沿）
    if ctype in ("mature", "intangible"):
        low_label, high_label = "悲观情景 DCF（下限）", "中性情景 DCF（上限）"
    else:
        low_label, high_label = "相对估值下沿", "相对估值上沿"

    # 当前股价位置
    pos = "—"
    if price and low is not None and high is not None:
        if price > high * 1.05:
            pos = "高于区间（可能高估）"
        elif price < low * 0.95:
            pos = "远低于下限（厚安全垫机会）"
        else:
            pos = "处于内在价值区间内（相对合理）"

    # 股息率（附）
    div_ps = fetch_dividend(code)
    div_yield = safe_div(div_ps, price) * 100 if (div_ps and price) else None

    return {
        "meta": {
            "code": code, "name": name, "ind_name": ind_name, "ind_code": ind_code,
            "period": period_label(cur_date), "report_date": cur_date,
            "price": price, "pe_ttm": pe_ttm, "pb": pb, "mktcap_yi": mktcap,
            "change_pct": q.get("change_pct"), "turnover": q.get("turnover"),
            "quote_time": q.get("quote_time"),
        },
        "type": {"code": ctype, "name": cname, "stage": stage, "reasons": reasons},
        "current": cur,
        "trend": trend, "g_np": g_np, "div_yield": div_yield, "div_ps": div_ps,
        "main": main, "cross": cross,
        "range": {"low": low, "high": high, "price": price, "pos": pos,
                   "low_label": low_label, "high_label": high_label},
        "assumptions": {
            "R": "9%（折现率=无风险利率~2.5% + 风险溢价~6.5%）",
            "G": "1.5%（永续增长率，不高于长期 GDP 增速）",
            "pessimistic": "折现率 12% / 永续 1%",
            "net_cash": "以货币资金近似净现金（未扣有息债务，偏乐观）",
        },
    }


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------
def render_html(R):
    m = R["meta"]; t = R["type"]; cur = R["current"]; rng = R["range"]; main = R["main"]
    up = (m["change_pct"] or 0) >= 0
    chg_cls = "up" if up else "down"

    # 公司类型判定
    reasons_html = "".join("<li>%s</li>" % r for r in t["reasons"])

    # 主尺明细
    main_detail = ""
    if "pe" in main and main["pe"].get("ok"):
        pe = main["pe"]
        main_detail += ("<tr><td class='k'>PE 主尺（合理 PE 中枢）</td><td>%s</td>"
                        "<td>EPS %.2f 元 ｜ 合理价区间 %.2f~%.2f 元</td></tr>"
                        % (pe["pe_mid"], pe["eps"], pe["price_low"], pe["price_high"]))
    if "dcf_neu" in main and main["dcf_neu"].get("ok"):
        d = main["dcf_neu"]
        main_detail += ("<tr><td class='k'>DCF 两阶段（中性）</td><td>%.2f 元/股</td>"
                        "<td>折现率 %.0f%% ｜ 永续 %.1f%% ｜ 预测期 %d 年 ｜ 基期FCF %s 亿</td></tr>"
                        % (d["per_share"], d["R"] * 100, d["G"] * 100, d["N"], yi(d["fcf0_yi"] * 1e8)))
    if "peg" in main and main["peg"].get("ok"):
        pg = main["peg"]
        main_detail += ("<tr><td class='k'>PEG 主尺</td><td>合理价 %.2f 元</td>"
                        "<td>PEG=%.2f（PE_TTM/增速）｜ 合理PE=%s%%</td></tr>"
                        % (pg["fair_price"], pg["peg"], pg["fair_pe"]))
    if "ps" in main and main["ps"].get("ok"):
        ps = main["ps"]
        main_detail += ("<tr><td class='k'>PS 主尺</td><td>合理价 %.2f 元</td>"
                        "<td>合理PS=%.2f（终局净利率 %.1f%% × 终局PE %s）｜ 每股营收 %.2f 元</td></tr>"
                        % (ps["fair_price"], ps["fair_ps"], ps["terminal_margin"] * 100,
                           ps["terminal_pe"], ps["rev_per_share"]))
    if "pb" in main and main["pb"].get("ok"):
        pb = main["pb"]
        main_detail += ("<tr><td class='k'>PB 主尺</td><td>合理价 %.2f 元</td>"
                        "<td>每股净资产 %.2f 元 ｜ 合理PB=ROE/R=%.2f（ROE %.1f%%）｜ 当前PB %s</td></tr>"
                        % (pb["fair_price"], pb["bvps"], pb["fair_pb"], (pb.get("roe") or 0) * 100,
                           ("%.2f" % m["pb"]) if m["pb"] else "—"))

    # 交叉验证表
    cross_rows = ""
    for label, val in R["cross"]:
        cross_rows += "<tr><td class='k'>%s</td><td><b>%.2f</b> 元</td><td>%s</td></tr>" % (
            label, val, "支持同一结论" if (m["price"] and abs(val - m["price"]) / m["price"] < 0.4) else "参考")
    cross_html = cross_rows or "<tr><td colspan='3' class='muted'>当前类型暂以单一主尺为主（亏损/数据不足），建议补充同业对比后二次验证</td></tr>"

    # 内在价值区间
    rng_html = ("<table class='grid'><tbody>"
                "<tr><td class='k'>%s</td><td><b>%s</b> 元</td></tr>"
                "<tr><td class='k'>%s</td><td><b>%s</b> 元</td></tr>"
                "<tr><td class='k'>当前股价</td><td>%s 元（%s%%）</td></tr>"
                "<tr><td class='k'>股价位置判断</td><td><b>%s</b></td></tr>"
                "</tbody></table>" % (
                    rng.get("low_label", "估值区间下限"),
                    ("%.2f" % rng["low"]) if rng["low"] else "—",
                    rng.get("high_label", "估值区间上限"),
                    ("%.2f" % rng["high"]) if rng["high"] else "—",
                    ("%.2f" % m["price"]) if m["price"] else "—",
                    ("%.2f" % m["change_pct"]) if m["change_pct"] is not None else "—",
                    rng["pos"]))

    # 关键假设与风险
    asm = R["assumptions"]
    asm_items = "".join("<li><b>%s</b>：%s</li>" % (k, v) for k, v in asm.items())
    if R.get("div_yield") is not None:
        asm_items += "<li><b>股息率（附）</b>：%.2f%%（每股股利 %.3f 元，仅供参考，以公司公告为准）</li>" % (R["div_yield"], R["div_ps"] or 0)
    asm_items += ("<li><b>敏感性提示</b>：折现率 ±1pct 会使 DCF 每股价值同向变动约 ±8%~12%；"
                  "永续增长率每 ±0.5pct 影响约 ±5%；增速假设变化对成长/周期股影响最大。</li>")
    asm_html = "<ul>" + asm_items + "</ul>"

    # 当前核心估值指标速览
    snap = ("<table class='grid'><thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead><tbody>"
            "<tr><td class='k'>股价</td><td>%s 元</td><td>当日涨跌 %s%%</td></tr>"
            "<tr><td class='k'>PE(TTM)</td><td>%s</td><td>%s</td></tr>"
            "<tr><td class='k'>PB</td><td>%s</td><td>市净率</td></tr>"
            "<tr><td class='k'>总市值</td><td>%s 亿</td><td>换手率 %s%%</td></tr>"
            "</tbody></table>" % (
                ("%.2f" % m["price"]) if m["price"] else "—",
                ("%.2f" % m["change_pct"]) if m["change_pct"] is not None else "—",
                ("%.2f" % m["pe_ttm"]) if m["pe_ttm"] else "—",
                "成长股需结合 PEG 看" if m["pe_ttm"] else "—",
                ("%.2f" % m["pb"]) if m["pb"] else "—",
                ("%.2f" % m["mktcap_yi"]) if m["mktcap_yi"] else "—",
                ("%.2f" % m["turnover"]) if m["turnover"] is not None else "—"))

    today = datetime.date.today().strftime("%Y-%m-%d")
    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    watermark = "投研工作台 · 仅供研究参考　" * 60

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>个股估值报告 · %(name)s(%(code)s)</title>
<style>
:root{--bg:#0f172a;--card:#ffffff;--ink:#1e293b;--sub:#64748b;--line:#e2e8f0;
--accent:#ed7d31;--good:#16a34a;--warn:#dc2626;--neu:#0ea5e9;--up:#dc2626;--down:#16a34a;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif;
background:#f1f5f9;color:var(--ink);line-height:1.6;padding:24px}
.wrap{max-width:980px;margin:0 auto}
header{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;border-radius:16px;
padding:26px 30px;margin-bottom:20px;box-shadow:0 8px 24px rgba(15,23,42,.18)}
header h1{font-size:26px;margin-bottom:6px}
header .code{color:#fdba74;font-size:15px;font-weight:600}
header .meta{margin-top:14px;display:flex;flex-wrap:wrap;gap:18px;font-size:14px;color:#cbd5e1}
header .meta b{color:#fff;font-size:18px;display:block}
.up{color:#fca5a5}.down{color:#86efac}
section{background:var(--card);border-radius:14px;padding:22px 26px;margin-bottom:18px;
box-shadow:0 2px 10px rgba(15,23,42,.06);border:1px solid var(--line)}
section h2{font-size:19px;margin-bottom:14px;padding-left:12px;border-left:4px solid var(--accent);color:#0f172a}
table{width:100%%;border-collapse:collapse;font-size:14px}
table.grid th,table.grid td{border:1px solid var(--line);padding:9px 10px;text-align:center}
table.grid th{background:#f8fafc;color:#475569;font-weight:600}
td.k{text-align:left;color:#334155;font-weight:600;background:#fafafa}
td.v{font-weight:700;color:#0f172a}
.badge{display:inline-block;padding:3px 12px;border-radius:20px;font-size:13px;font-weight:700}
.badge.good{background:#dcfce7;color:#15803d}
.badge.warn{background:#fee2e2;color:#b91c1c}
.badge.neu{background:#e0f2fe;color:#0369a1}
.note{font-size:13.5px;color:var(--sub);background:#fff7ed;border-left:3px solid var(--accent);
padding:10px 14px;border-radius:8px;margin-top:12px}
.muted{color:var(--sub);font-size:13px}
footer{text-align:center;color:var(--sub);font-size:12px;margin:20px 0;padding-top:10px}
.tag{display:inline-block;background:#fef3e2;color:var(--accent);padding:2px 8px;border-radius:6px;font-size:12px;margin-left:8px}
.export-btn{margin-top:14px;display:inline-block;padding:8px 16px;border:0;border-radius:10px;
background:#fdba74;color:#1e293b;font-size:14px;font-weight:700;cursor:pointer}
.export-btn:hover{background:#fcd34d}
.pdf-watermark,.pdf-runninghead,.pdf-cover{display:none}
@media print{
  @page{size:A4;margin:12mm 12mm 14mm 12mm}
  body{background:#fff;padding:0}
  header{box-shadow:none;border-radius:0}
  section{box-shadow:none;border:1px solid #e2e8f0;break-inside:avoid;page-break-inside:avoid;margin-bottom:12px}
  .no-print{display:none!important}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  table.grid{break-inside:auto}
  tr,td,th{break-inside:avoid;page-break-inside:avoid}
  .wrap{padding-top:6mm}
  .pdf-watermark{display:block;position:fixed;top:-30%%;left:-30%%;width:160%%;height:160%%;
    z-index:-1;pointer-events:none;overflow:hidden;
    font-size:20px;line-height:2.6;color:rgba(15,23,42,0.05);
    transform:rotate(-28deg);word-break:break-all;letter-spacing:1px}
  .pdf-runninghead{display:flex;position:fixed;top:0;left:0;right:0;height:9mm;
    align-items:center;justify-content:space-between;padding:0 12mm;
    font-size:8.5px;color:#64748b;border-bottom:0.4px solid #cbd5e1;background:#fff;z-index:60}
  .pdf-cover{display:flex;flex-direction:column;justify-content:center;
    page-break-after:always;height:260mm;padding:18mm 16mm 0;
    border-bottom:3px solid var(--accent)}
  .pdf-cover .kicker{font-size:13px;color:var(--accent);letter-spacing:3px;font-weight:700;margin-bottom:20px}
  .pdf-cover .title{font-size:44px;font-weight:800;color:#0f172a}
  .pdf-cover .sub{font-size:18px;color:#475569;margin-top:10px}
  .pdf-cover .meta{font-size:13px;color:#64748b;margin-top:28px;line-height:2}
  .pdf-cover .note{font-size:11px;color:#94a3b8;margin-top:auto;border-top:1px solid #e2e8f0;padding-top:14px}
}
</style></head>
<body>
<div class="pdf-watermark">%(watermark)s</div>
<div class="pdf-runninghead"><span>投研工作台 · 个股估值报告</span><span>%(name)s（%(code)s）· %(period)s</span><span>%(today)s</span></div>
<div class="pdf-cover">
  <div class="kicker">投研工作台 · 个股估值分析报告</div>
  <div class="title">%(name)s</div>
  <div class="sub">%(code)s · %(ind_name)s · %(period)s 报告期</div>
  <div class="meta">估值类型：%(ctype)s　｜　主尺：%(mainscale)s<br>数据截止 %(report_date)s　｜　生成时间 %(gen_time)s</div>
  <div class="note">本报告依据「个股估值」技能框架自动测算，仅供研究参考，不构成投资建议。</div>
</div>
<div class="wrap">
<header>
<h1>%(name)s <span class="code">%(code)s · %(ind_name)s</span></h1>
<div>个股估值报告　报告期：<b>%(period)s</b>（数据截止 %(report_date)s）</div>
<div class="meta">
<div><b>%(price)s</b>股价(元) <span class="%(chgcls)s">%(chg)s%%</span></div>
<div><b>%(pe)s</b>PE(TTM)</div>
<div><b>%(pb)s</b>PB</div>
<div><b>%(mktcap)s</b>总市值(亿)</div>
<div><b>%(pos)s</b>位置判断</div>
<button class="no-print export-btn" onclick="window.print()">&#11015; 导出 PDF</button>
</div></header>

<section><h2>一、公司类型判断 <span class="tag">第一步 · 选对尺子</span></h2>
<div class="badge neu">%(ctype)s</div>
<p class="note">%(stage)s</p>
<ul style="margin-top:10px">%(reasons)s</ul></section>

<section><h2>二、估值快照 <span class="tag">当前市场定价</span></h2>
%(snap)s</section>

<section><h2>三、主尺结论 <span class="tag">第二步 · 核心估值</span></h2>
<table class="grid"><thead><tr><th>估值方法</th><th>结论</th><th>关键锚点</th></tr></thead>
<tbody>%(main_detail)s</tbody></table></section>

<section><h2>四、交叉验证 <span class="tag">第三步 · 两把尺子</span></h2>
<table class="grid"><thead><tr><th>验证方法</th><th>每股价值</th><th>结论</th></tr></thead>
<tbody>%(cross)s</tbody></table></section>

<section><h2>五、内在价值区间与安全边际 <span class="tag">区间而非点位</span></h2>
%(rng)s
<p class="note">区间下界由悲观情景（折现率 12%% / 永续 1%%）锚定，构成安全垫底线；上界为中性情景。股价远低于下界才谈得上"厚安全垫"。</p></section>

<section><h2>六、关键假设与风险 <span class="tag">口径说明</span></h2>
%(asm)s</section>

<section><h2>七、免责声明</h2>
<p class="muted">本报告由「投研工作台·估值模型」依据公开财务与市场数据、按「个股估值」技能框架自动测算。估值是区间判断而非精确点位，所有结论建立在增速、折现率、永续增长率等主观假设之上；参数变化会显著改变结论。本报告仅供研究学习，<b>不构成任何投资建议</b>，据此操作风险自担。</p></section>

<footer>本报告由「投研工作台·估值模型」自动生成，数据来源：东方财富 / 腾讯财经，生成于 %(today)s。</footer>
</div>
</body></html>""" % {
        "name": m["name"], "code": m["code"], "ind_name": m["ind_name"],
        "period": m["period"], "report_date": m["report_date"],
        "ctype": t["name"], "mainscale": main.get("尺", "—"),
        "price": ("%.2f" % m["price"]) if m["price"] else "—",
        "chg": ("%.2f" % m["change_pct"]) if m["change_pct"] is not None else "—",
        "chgcls": chg_cls,
        "pe": ("%.2f" % m["pe_ttm"]) if m["pe_ttm"] else "—",
        "pb": ("%.2f" % m["pb"]) if m["pb"] else "—",
        "mktcap": ("%.2f" % m["mktcap_yi"]) if m["mktcap_yi"] else "—",
        "pos": rng["pos"],
        "stage": t["stage"], "reasons": reasons_html,
        "snap": snap, "main_detail": main_detail, "cross": cross_html,
        "rng": rng_html, "asm": asm_html,
        "today": today, "gen_time": gen_time, "watermark": watermark,
    }
    return html


# ---------------------------------------------------------------------------
# 写入文档列表（更新 data/manifest.json）
# ---------------------------------------------------------------------------
def update_manifest(repo_root, title, html_file, pdf_file):
    manifest_path = os.path.join(repo_root, "data", "manifest.json")
    section = "估值模型"
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data.setdefault(section, [])
    # 去重（同名同文件不重复添加）
    exists = any(d.get("title") == title and d.get("file") == html_file for d in data[section])
    if not exists:
        data[section].insert(0, {
            "title": title, "file": html_file, "type": "html", "desc": "个股估值报告（HTML 版）"
        })
    pdf_exists = any(d.get("title") == title and d.get("file") == pdf_file for d in data[section])
    if not pdf_exists:
        data[section].insert(0, {
            "title": title, "file": pdf_file, "type": "pdf", "desc": "个股估值报告（PDF 版）"
        })
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 生成报告文件 + 可选 PDF + 注册文档列表
# ---------------------------------------------------------------------------
def write_report(code, out_dir=None, do_pdf=False, register=True):
    R = analyze_valuation(code)
    html = render_html(R)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = out_dir or os.path.join(repo_root, "09-估值模型")
    os.makedirs(out_dir, exist_ok=True)
    ym = R["meta"]["report_date"][:7].replace("-", "")
    base = "估值模型_%s_%s_%s" % (R["meta"]["code"], R["meta"]["name"], ym)
    html_path = os.path.join(out_dir, base + ".html")
    pdf_path = os.path.join(out_dir, base + ".pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    result = {"html": html_path, "pdf": None, "R": R}
    if do_pdf:
        try:
            render_pdf(html, pdf_path)
            result["pdf"] = pdf_path
        except Exception as e:
            result["pdf_error"] = str(e)
    if register:
        rel_html = "09-估值模型/" + os.path.basename(html_path)
        rel_pdf = "09-估值模型/" + os.path.basename(pdf_path) if result.get("pdf") else None
        title = "估值报告_%s_%s_%s" % (R["meta"]["code"], R["meta"]["name"], ym)
        update_manifest(repo_root, title, rel_html, rel_pdf) if rel_pdf else update_manifest(repo_root, title, rel_html, rel_html)
        result["registered"] = title
    return result



def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--help", "-h"):
        print(__doc__)
        return
    code = args[0]
    out_dir = None
    do_pdf = "--pdf" in args
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out_dir = args[idx + 1]
    res = write_report(code, out_dir, do_pdf=do_pdf, register=False)
    print("已生成报告：%s" % res["html"])
    if res.get("pdf"):
        print("已导出 PDF：%s" % res["pdf"])
    if res.get("pdf_error"):
        print("PDF 导出失败：%s" % res["pdf_error"])
    R = res["R"]
    print("标的：%s(%s) 类型：%s 区间：%.2f~%.2f 元"
          % (R["meta"]["name"], R["meta"]["code"], R["type"]["name"],
             R["range"]["low"] or 0, R["range"]["high"] or 0))


if __name__ == "__main__":
    main()
