# -*- coding: utf-8 -*-
"""
个股财务数据分析引擎  ·  投研工作台「财务分析」板块
=================================================
参照《个股财务数据分析.docx》的核心框架与"中国巨石"案例模板，输入个股名称或代码，
自动拉取东方财富三大财务报表 + 同业数据、腾讯行情估值，计算文档定义的全部核心指标，
输出结构化 HTML 分析报告（页面展示 / 静态文件两种模式）。

数据来源（均无需 API Key）：
  - 东方财富 datacenter-web.eastmoney.com  → 利润表 / 资产负债表 / 现金流量表 / 同业
  - 腾讯 qt.gtimg.cn                      → 实时行情、PE(TTM)、总市值、换手率
  - 新浪智能提示 suggest                  → 股票名称 → 代码 解析

启动方式：
  python stock_analyzer.py 600176                  # 生成静态 HTML 报告
  python stock_analyzer.py 中国巨石                 # 支持名称输入
  python stock_analyzer.py 600176 --out D:/报告     # 指定输出目录
  python stock_analyzer.py --serve 8800             # 启动本地网页（浏览器打开 http://localhost:8800）
"""

import sys
import os
import json
import ssl
import urllib.request
import urllib.parse
import datetime

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
    raise RuntimeError("网络请求失败: %s | %s" % (url[:80], last_err))


def em_query(report, columns, flt, pagesize=12, sort_col="REPORT_DATE", sort_type=-1):
    url = (f"{EM_HOST}?reportName={report}&columns={columns}&filter={urllib.parse.quote(flt)}"
           f"&pageSize={pagesize}&sortColumns={sort_col}&sortTypes={sort_type}&client=PC&source=F10")
    d = json.loads(http_get(url))
    if not d.get("success"):
        return []
    res = d.get("result") or {}
    return res.get("data") or []


# ---------------------------------------------------------------------------
# PDF 导出（复用工作台 Edge 无头打印，与 tools/md2pdf.py 同口径）
# ---------------------------------------------------------------------------
import subprocess
import shutil

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
    """用本机 Edge/Chrome 无头模式把 HTML 渲染为 PDF，返回 pdf 路径。"""
    if not EDGE:
        raise RuntimeError("未找到 Edge/Chrome 浏览器，无法导出 PDF（请安装 Microsoft Edge）")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp_dir = os.path.join(repo_root, "archive", "temp_fa")
    os.makedirs(tmp_dir, exist_ok=True)
    html_path = os.path.join(tmp_dir, "_fa_tmp.html")
    # Edge 命令行参数按系统 ANSI 编码，含中文会失败；故输出先用 ASCII 名，再改名到最终路径
    edge_out = os.path.join(tmp_dir, "_fa_out.pdf")
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
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    try:
        if not keep_html:
            os.remove(html_path)
    except OSError:
        pass
    if not os.path.exists(edge_out) or os.path.getsize(edge_out) < 1024:
        err = (r.stderr.decode("utf-8", "ignore") or r.stdout.decode("utf-8", "ignore"))[-500:]
        raise RuntimeError("PDF 渲染失败: %s" % err)
    # 移动到最终（可能含中文）路径，避开命令行中文编码问题
    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    except OSError:
        pass
    shutil.move(edge_out, pdf_path)
    try:
        if not any(os.scandir(tmp_dir)):
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
    # 通过财务数据接口按证券简称精确反查代码（无需外部搜索服务，沙箱可用）
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
    # 字段索引参考腾讯行情协议
    price = float(f[3]) if f[3] else None
    prev_close = float(f[4]) if f[4] else None
    change_pct = float(f[32]) if f[32] else None
    turnover = float(f[38]) if len(f) > 38 and f[38] else None   # 换手率 %
    pe_ttm = float(f[39]) if len(f) > 39 and f[39] else None      # 市盈率(TTM)
    mktcap_yi = float(f[44]) if len(f) > 44 and f[44] else None   # 总市值(亿元)
    t = f[30] if len(f) > 30 else ""                              # 时间
    return {
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "turnover": turnover,
        "pe_ttm": pe_ttm,
        "mktcap_yi": mktcap_yi,
        "quote_time": t,
    }


# ---------------------------------------------------------------------------
# 财务报表拉取
# ---------------------------------------------------------------------------
def fetch_income(code, pagesize=12):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,INDUSTRY_CODE,INDUSTRY_NAME,REPORT_DATE,"
            "TOTAL_OPERATE_INCOME,OPERATE_COST,PARENT_NETPROFIT,DEDUCT_PARENT_NETPROFIT,"
            "TOI_RATIO,PARENT_NETPROFIT_RATIO,DPN_RATIO,OPERATE_PROFIT,TOTAL_PROFIT,INCOME_TAX")
    flt = '(SECURITY_CODE="%s")' % code
    return em_query("RPT_DMSK_FN_INCOME", cols, flt, pagesize)


def fetch_balance(code, pagesize=12):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,TOTAL_ASSETS,TOTAL_LIABILITIES,"
            "TOTAL_EQUITY,DEBT_ASSET_RATIO,CURRENT_RATIO,ACCOUNTS_RECE,INVENTORY,MONETARYFUNDS,FIXED_ASSET")
    flt = '(SECURITY_CODE="%s")' % code
    return em_query("RPT_DMSK_FN_BALANCE", cols, flt, pagesize)


def fetch_cashflow(code, pagesize=12):
    cols = ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,NETCASH_OPERATE,NETCASH_INVEST,"
            "NETCASH_FINANCE,CONSTRUCT_LONG_ASSET,SALES_SERVICES")
    flt = '(SECURITY_CODE="%s")' % code
    return em_query("RPT_DMSK_FN_CASHFLOW", cols, flt, pagesize)


def fetch_industry(report, ind_code, cols, pagesize=80):
    flt = '(INDUSTRY_CODE="%s")' % ind_code
    return em_query(report, cols, flt, pagesize)


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
    """返回比 cur_date 更早的一条（用于期初值 / 同比基期）。"""
    earlier = [r for r in rows if (r.get("REPORT_DATE") or "")[:10] < (cur_date or "")[:10]]
    if not earlier:
        return None
    return max(earlier, key=lambda r: (r.get("REPORT_DATE") or ""))


def latest_by(rows):
    if not rows:
        return None
    return max(rows, key=lambda r: (r.get("REPORT_DATE") or ""))


def yi(v):
    """元 -> 亿元字符串"""
    if v is None:
        return "—"
    return "%.2f" % (v / 1e8)


def pct(v, digits=2):
    if v is None:
        return "—"
    return ("%.2f" % v) + "%"


# ---------------------------------------------------------------------------
# 核心分析
# ---------------------------------------------------------------------------
def analyze(code):
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

    # ---- 当前报告期核心指标 ----
    rev = cur_inc.get("TOTAL_OPERATE_INCOME")
    cost = cur_inc.get("OPERATE_COST")
    np_ = cur_inc.get("PARENT_NETPROFIT")
    dpn = cur_inc.get("DEDUCT_PARENT_NETPROFIT")
    gp = (rev - cost) if (rev is not None and cost is not None) else None
    gp_margin = safe_div(gp, rev)
    net_margin = safe_div(np_, rev)
    rev_yoy = cur_inc.get("TOI_RATIO")
    np_yoy = cur_inc.get("PARENT_NETPROFIT_RATIO")
    dpn_yoy = cur_inc.get("DPN_RATIO")

    debt_ratio = cur_bal.get("DEBT_ASSET_RATIO")
    cur_ratio = cur_bal.get("CURRENT_RATIO")
    if cur_ratio is not None and cur_ratio > 10:
        cur_ratio = cur_ratio / 100.0
    ar = cur_bal.get("ACCOUNTS_RECE")
    inv = cur_bal.get("INVENTORY")
    ar_turnover = safe_div(rev, ar)           # 应收账款周转率（报告期口径）
    inv_turnover = safe_div(cost, inv)         # 存货周转率（营业成本/存货）

    op_cf = cur_cf.get("NETCASH_OPERATE") if cur_cf else None
    capex = cur_cf.get("CONSTRUCT_LONG_ASSET") if cur_cf else None
    fcf = (op_cf - capex) if (op_cf is not None and capex is not None) else None
    sales_cash = cur_cf.get("SALES_SERVICES") if cur_cf else None
    net_cf_ratio = safe_div(op_cf, np_)        # 净现比
    rev_cf_ratio = safe_div(sales_cash, rev)   # 收入现金比

    # ROE：归母净利 / 平均净资产（期初=上一期资产负债表权益）
    prior_bal = find_prior(bal, cur_date)
    equity = cur_bal.get("TOTAL_EQUITY")
    equity0 = prior_bal.get("TOTAL_EQUITY") if prior_bal else None
    avg_equity = (equity + equity0) / 2 if (equity is not None and equity0 is not None) else equity
    roe = safe_div(np_, avg_equity)
    month = cur_date[5:7] if len(cur_date) >= 7 else "12"
    annual_factor = {"03": 4, "06": 2, "09": 4 / 3.0, "12": 1}.get(month, 1)
    roe_ann = (roe * annual_factor) if roe is not None else None

    # 行情估值
    q = fetch_quote(code)
    mktcap = q.get("mktcap_yi")
    shares = safe_div(mktcap and mktcap * 1e8, q.get("price"))
    eps = safe_div(np_, shares) if shares else None
    pb = safe_div((mktcap * 1e8) if mktcap else None, equity) if equity else None

    current = {
        "rev": rev, "rev_yoy": rev_yoy, "np": np_, "np_yoy": np_yoy, "dpn": dpn, "dpn_yoy": dpn_yoy,
        "gp_margin": gp_margin, "net_margin": net_margin,
        "roe": roe, "roe_ann": roe_ann, "debt_ratio": debt_ratio,
        "current_ratio": cur_ratio, "ar_turnover": ar_turnover, "inv_turnover": inv_turnover,
        "op_cf": op_cf, "fcf": fcf, "net_cf_ratio": net_cf_ratio, "rev_cf_ratio": rev_cf_ratio,
        "eps": eps, "equity": equity, "assets": cur_bal.get("TOTAL_ASSETS"),
    }

    # ---- 成长性（年报序列 + CAGR）----
    annual_inc = sorted([r for r in inc if (r.get("REPORT_DATE") or "")[5:7] == "12"],
                        key=lambda r: r.get("REPORT_DATE") or "")
    annual_bal = {r.get("REPORT_DATE")[:4]: r for r in bal if (r.get("REPORT_DATE") or "")[5:7] == "12"}
    trend = []
    for r in annual_inc:
        y = (r.get("REPORT_DATE") or "")[:4]
        rv = r.get("TOTAL_OPERATE_INCOME")
        npp = r.get("PARENT_NETPROFIT")
        d = r.get("DEDUCT_PARENT_NETPROFIT")
        c = r.get("OPERATE_COST")
        g = (rv - c) if (rv is not None and c is not None) else None
        gm = safe_div(g, rv)
        nm = safe_div(npp, rv)
        be = annual_bal.get(y)
        eq = be.get("TOTAL_EQUITY") if be else None
        be0 = annual_bal.get(str(int(y) - 1)) if be else None
        eq0 = be0.get("TOTAL_EQUITY") if be0 else None
        avgeq = (eq + eq0) / 2 if (eq is not None and eq0 is not None) else eq
        rk = safe_div(npp, avgeq)
        dr = be.get("DEBT_ASSET_RATIO") if be else None
        trend.append({"period": y + "年报", "rev": rv, "np": npp, "dpn": d,
                      "gp_margin": gm, "net_margin": nm, "roe": rk, "debt_ratio": dr})

    cagr = {}
    if len(annual_inc) >= 2:
        yrs = [(r.get("REPORT_DATE") or "")[:4] for r in annual_inc]
        n = len(annual_inc) - 1
        rev0, rev1 = annual_inc[0]["TOTAL_OPERATE_INCOME"], annual_inc[-1]["TOTAL_OPERATE_INCOME"]
        np0, np1 = annual_inc[0]["PARENT_NETPROFIT"], annual_inc[-1]["PARENT_NETPROFIT"]
        if rev0 and rev1:
            cagr["rev_cagr"] = ((rev1 / rev0) ** (1 / n) - 1) * 100
        if np0 and np1:
            cagr["np_cagr"] = ((np1 / np0) ** (1 / n) - 1) * 100
        cagr["years"] = n

    # ---- 同业横向对比 ----
    industry = {"ind_name": ind_name, "peers": [], "avg": {}, "rank_np": None,
                "rank_gp": None, "count": 0, "top3": []}
    if ind_code:
        peer_inc = fetch_industry("RPT_DMSK_FN_INCOME", ind_code,
                                 "SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,TOTAL_OPERATE_INCOME,"
                                 "OPERATE_COST,PARENT_NETPROFIT,DEDUCT_PARENT_NETPROFIT")
        peer_bal = fetch_industry("RPT_DMSK_FN_BALANCE", ind_code,
                                  "SECURITY_CODE,REPORT_DATE,TOTAL_EQUITY,DEBT_ASSET_RATIO")
        # 每家公司取最新一期
        inc_map, bal_map = {}, {}
        for r in peer_inc:
            c = r["SECURITY_CODE"]
            if c not in inc_map or (r.get("REPORT_DATE") or "") > inc_map[c].get("REPORT_DATE"):
                inc_map[c] = r
        for r in peer_bal:
            c = r["SECURITY_CODE"]
            if c not in bal_map or (r.get("REPORT_DATE") or "") > bal_map[c].get("REPORT_DATE"):
                bal_map[c] = r
        peers = []
        rev_sum = cost_sum = np_sum = dpn_sum = 0.0
        debt_list, roe_list = [], []
        for c, r in inc_map.items():
            rv = r.get("TOTAL_OPERATE_INCOME"); cst = r.get("OPERATE_COST")
            npp = r.get("PARENT_NETPROFIT"); d = r.get("DEDUCT_PARENT_NETPROFIT")
            b = bal_map.get(c)
            dr = b.get("DEBT_ASSET_RATIO") if b else None
            eq = b.get("TOTAL_EQUITY") if b else None
            g = (rv - cst) if (rv is not None and cst is not None) else None
            gm = safe_div(g, rv)
            nm = safe_div(npp, rv)
            if rv: rev_sum += rv
            if cst: cost_sum += cst
            if npp: np_sum += npp
            if d: dpn_sum += d
            if dr is not None: debt_list.append(dr)
            if npp is not None and eq:
                roe_list.append(npp / eq)
            peers.append({"code": c, "name": r.get("SECURITY_NAME_ABBR"), "rev": rv,
                          "np": npp, "dpn": d, "gp_margin": gm, "net_margin": nm,
                          "debt_ratio": dr, "is_target": c == code})
        # 行业平均（作为同业基准）：剔除标的自身，并在盈利企业中取中位数，
        # 避免亏损/平板玻璃企业拉低均值，更贴近"可比同业"口径
        excl = [p for p in peers if not p["is_target"]]
        profit_base = [p for p in excl if (p["np"] or 0) > 0]
        base = profit_base if profit_base else (excl if excl else peers)
        def median(vals):
            vals = [v for v in vals if v is not None]
            if not vals:
                return None
            vals.sort()
            n = len(vals)
            return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        avg = {
            "gp_margin": median([p["gp_margin"] for p in base]),
            "net_margin": median([p["net_margin"] for p in base]),
            "debt_ratio": median([p["debt_ratio"] for p in base]),
        }
        # 排名（含自身）
        ranked_np = sorted(peers, key=lambda p: p["np"] or -1e18, reverse=True)
        ranked_gp = sorted([p for p in peers if p["gp_margin"] is not None],
                           key=lambda p: p["gp_margin"], reverse=True)
        industry["peers"] = peers
        industry["avg"] = avg
        industry["count"] = len(peers)
        industry["rank_np"] = next((i + 1 for i, p in enumerate(ranked_np) if p["is_target"]), None)
        industry["rank_gp"] = next((i + 1 for i, p in enumerate(ranked_gp) if p["is_target"]), None)
        industry["top3"] = ranked_np[:3]
        industry["avg_roe"] = (sum(roe_list) / len(roe_list)) if roe_list else None

    # ---- 综合评分（文档评判标准）----
    score = score_health(current, cagr, industry)

    return {
        "meta": {
            "code": code, "name": name, "ind_name": ind_name, "ind_code": ind_code,
            "period": period_label(cur_date), "report_date": cur_date,
            "price": q.get("price"), "pe_ttm": q.get("pe_ttm"), "pb": pb,
            "mktcap_yi": mktcap, "change_pct": q.get("change_pct"),
            "turnover": q.get("turnover"), "quote_time": q.get("quote_time"),
        },
        "current": current, "trend": trend, "cagr": cagr,
        "industry": industry, "score": score,
    }


def score_health(cur, cagr, industry):
    pos, neg = 0.0, 0.0
    good, warn = [], []

    def judge(cond_pos, w_pos, w_neg, g_txt, w_txt):
        nonlocal pos, neg
        if cond_pos:
            pos += w_pos; good.append(g_txt)
        else:
            neg += w_neg; warn.append(w_txt)

    gm = cur["gp_margin"] or 0
    nm = cur["net_margin"] or 0
    ra = cur["roe_ann"] or 0
    dr = cur["debt_ratio"]
    ncr = cur["net_cf_ratio"]
    ry = cur["rev_yoy"]
    ny = cur["np_yoy"]
    cr = cur["current_ratio"]

    # 盈利能力
    if gm >= 0.50: judge(True, 2, 0, "毛利率≥50%（卓越级盈利能力）", "")
    elif gm >= 0.30: judge(True, 1, 0, "毛利率≥30%（盈利达标）", "")
    else: judge(False, 0, 1, "", "毛利率<30%，盈利能力偏弱")
    if nm >= 0.25: judge(True, 2, 0, "净利率≥25%（卓越）", "")
    elif nm >= 0.15: judge(True, 1, 0, "净利率≥15%（优秀）", "")
    else: judge(False, 0, 1, "", "净利率<15%，盈利质量一般")
    if ra >= 0.20: judge(True, 2, 0, "年化ROE≥20%（卓越）", "")
    elif ra >= 0.15: judge(True, 1, 0, "年化ROE≥15%（优秀）", "")
    else: judge(False, 0, 1, "", "年化ROE<15%，资本回报不足")
    # 财务健康
    if dr is not None:
        if 30 <= dr <= 60: judge(True, 1, 0, "资产负债率30-60%（稳健）", "")
        elif dr < 30: judge(True, 1, 0, "资产负债率<30%（杠杆极低）", "")
        elif dr > 70: judge(False, 0, 2, "", "资产负债率>70%，杠杆偏高")
        else: judge(False, 0, 1, "", "资产负债率60-70%，需关注")
    if (cur["op_cf"] or 0) > 0: judge(True, 1, 0, "经营现金流为正", "")
    else: judge(False, 0, 1, "", "经营现金流为负")
    if ncr is not None:
        if ncr >= 1.0: judge(True, 1, 0, "净现比≥1（利润含金量高）", "")
        elif ncr >= 0.8: judge(True, 0.5, 0, "净现比0.8-1.0（尚可）", "")
        else: judge(False, 0, 1, "", "净现比<0.8，利润含水分")
    if cr is not None:
        if cr >= 1.5: judge(True, 1, 0, "流动比率≥1.5（短期偿债充裕）", "")
        elif cr >= 1.0: judge(True, 0.5, 0, "流动比率1.0-1.5（中性）", "")
        else: judge(False, 0, 1, "", "流动比率<1，短期偿债偏紧")
    # 成长
    if ry is not None:
        if ry > 15: judge(True, 1, 0, "营收同比>15%（高成长）", "")
        elif ry < 0: judge(False, 0, 1, "", "营收同比负增长")
    if ny is not None:
        if ny > 15: judge(True, 1, 0, "净利同比>15%（高成长）", "")
        elif ny < 0: judge(False, 0, 1, "", "净利同比负增长")
    # 行业地位
    if industry.get("avg", {}).get("gp_margin") is not None and gm is not None:
        if gm > industry["avg"]["gp_margin"]:
            judge(True, 1, 0, "毛利率高于行业平均（成本优势）", "")
        else:
            judge(False, 0, 0.5, "", "毛利率低于行业平均")

    max_pos = 2 + 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1  # 各正向满分之和
    ratio = pos / max_pos if max_pos else 0
    stars = round(min(5.0, max(0.0, ratio * 5)) * 2) / 2
    return {"stars": stars, "pos": pos, "neg": neg, "good": good, "warn": warn}


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------
def verdict_badge(text, kind):
    return '<span class="badge %s">%s</span>' % (kind, text)


def fmt_badge(v, good_thr=None, warn_thr=None, unit="", inv=False):
    """按阈值给数值上色（inv=True 表示越小越好）。"""
    if v is None:
        return "—", "neu"
    if good_thr is not None:
        if inv:
            kind = "good" if v <= good_thr else ("warn" if (warn_thr is not None and v >= warn_thr) else "neu")
        else:
            kind = "good" if v >= good_thr else ("warn" if (warn_thr is not None and v <= warn_thr) else "neu")
    else:
        kind = "neu"
    return ("%.2f%s" % (v, unit)), kind


def render_html(R):
    m = R["meta"]; cur = R["current"]; ind = R["industry"]; sc = R["score"]
    up = (m["change_pct"] or 0) >= 0
    chg_cls = "up" if up else "down"
    star_str = "★" * int(sc["stars"]) + ("½" if sc["stars"] % 1 else "") + "☆" * (5 - int(sc["stars"]) - (1 if sc["stars"] % 1 else 0))

    # 核心数据表
    def core_rows():
        rows = []
        rows.append(("营业总收入", yi(cur["rev"]) + " 亿", pct(cur["rev_yoy"]),
                     verdict_badge("优秀" if (cur["rev_yoy"] or 0) > 15 else "观察", "good" if (cur["rev_yoy"] or 0) > 15 else "neu")))
        rows.append(("归母净利润", yi(cur["np"]) + " 亿", pct(cur["np_yoy"]),
                     verdict_badge("优秀" if (cur["np_yoy"] or 0) > 15 else "观察", "good" if (cur["np_yoy"] or 0) > 15 else "neu")))
        rows.append(("扣非净利润", yi(cur["dpn"]) + " 亿", pct(cur["dpn_yoy"]),
                     verdict_badge("无水分" if (cur["dpn_yoy"] or 0) > 0 else "观察", "good" if (cur["dpn_yoy"] or 0) > 0 else "neu")))
        gm_t, gm_k = fmt_badge(cur["gp_margin"] * 100, 50, 30, "%")
        rows.append(("毛利率", gm_t, "—", verdict_badge("卓越" if (cur["gp_margin"] or 0) >= 0.5 else ("优秀" if (cur["gp_margin"] or 0) >= 0.3 else "观察"), gm_k)))
        nm_t, nm_k = fmt_badge(cur["net_margin"] * 100, 25, 15, "%")
        rows.append(("净利率", nm_t, "—", verdict_badge("卓越" if (cur["net_margin"] or 0) >= 0.25 else ("优秀" if (cur["net_margin"] or 0) >= 0.15 else "观察"), nm_k)))
        ra_t, ra_k = fmt_badge((cur["roe_ann"] or 0) * 100, 20, 15, "%")
        rows.append(("ROE(年化)", ra_t, "—", verdict_badge("卓越" if (cur["roe_ann"] or 0) >= 0.2 else ("优秀" if (cur["roe_ann"] or 0) >= 0.15 else "观察"), ra_k)))
        dr_t, dr_k = fmt_badge(cur["debt_ratio"], None, None, "%")
        dr_kind = "good" if (cur["debt_ratio"] is not None and 30 <= cur["debt_ratio"] <= 60) else ("warn" if (cur["debt_ratio"] is not None and cur["debt_ratio"] > 70) else "neu")
        rows.append(("资产负债率", dr_t, "—", verdict_badge("健康" if dr_kind == "good" else ("偏高" if dr_kind == "warn" else "观察"), dr_kind)))
        rows.append(("经营现金流净额", yi(cur["op_cf"]) + " 亿", "—",
                     verdict_badge("优秀" if (cur["op_cf"] or 0) > 0 else "警惕", "good" if (cur["op_cf"] or 0) > 0 else "warn")))
        ncr_t, ncr_k = fmt_badge((cur["net_cf_ratio"] or 0) * 100, 100, 80, "%")
        rows.append(("净现比", ncr_t, "—", verdict_badge("优秀" if (cur["net_cf_ratio"] or 0) >= 1 else ("尚可" if (cur["net_cf_ratio"] or 0) >= 0.8 else "警惕"), ncr_k)))
        rows.append(("自由现金流", yi(cur["fcf"]) + " 亿", "—",
                     verdict_badge("为正" if (cur["fcf"] or 0) > 0 else "为负", "good" if (cur["fcf"] or 0) > 0 else "warn")))
        rows.append(("基本EPS", ("%.4f" % cur["eps"]) if cur["eps"] else "—", "—", "—"))
        return rows

    core_html = "".join(
        '<tr><td class="k">%s</td><td class="v">%s</td><td class="yoy">%s</td><td>%s</td></tr>' % r
        for r in core_rows())

    # 成长性表
    trend_html = ""
    if R["trend"]:
        head = "".join("<th>%s</th>" % t["period"] for t in R["trend"])
        def trow(label, fn):
            cells = "".join("<td>%s</td>" % (yi(fn(t)) + " 亿" if fn(t) is not None else "—") for t in R["trend"])
            return "<tr><td class='k'>%s</td>%s</tr>" % (label, cells)
        def trow_pct(label, fn):
            cells = "".join("<td>%s</td>" % (pct(fn(t) * 100) if fn(t) is not None else "—") for t in R["trend"])
            return "<tr><td class='k'>%s</td>%s</tr>" % (label, cells)
        trend_html = (
            "<table class='grid'><thead><tr><th>指标</th>%s</tr></thead><tbody>"
            % head +
            trow("营业收入", lambda t: t["rev"]) +
            trow("归母净利润", lambda t: t["np"]) +
            trow("扣非净利润", lambda t: t["dpn"]) +
            trow_pct("毛利率", lambda t: t["gp_margin"]) +
            trow_pct("净利率", lambda t: t["net_margin"]) +
            trow_pct("ROE", lambda t: t["roe"]) +
            trow_pct("资产负债率", lambda t: t["debt_ratio"]) +
            "</tbody></table>"
        )
    cagr_txt = ""
    if R.get("cagr"):
        c = R["cagr"]
        cagr_txt = ("近 %d 年营收 CAGR <b>%s</b> ｜ 净利润 CAGR <b>%s</b>"
                    % (c.get("years", 0), pct(c.get("rev_cagr")), pct(c.get("np_cagr"))))

    # 财务健康核查
    hb = []
    hb.append(("资产负债率", pct(cur["debt_ratio"]), "✅ 杠杆安全" if (cur["debt_ratio"] is not None and cur["debt_ratio"] <= 60) else "⚠ 偏高"))
    hb.append(("经营现金流", yi(cur["op_cf"]) + " 亿", "✅ 与利润同向" if (cur["op_cf"] or 0) > 0 else "⚠ 为负"))
    hb.append(("净现比", pct(cur["net_cf_ratio"] * 100), "✅ 利润含金量高" if (cur["net_cf_ratio"] or 0) >= 1 else ("中性偏可" if (cur["net_cf_ratio"] or 0) >= 0.8 else "⚠ 低于1，需警惕")))
    hb.append(("收入现金比", pct(cur["rev_cf_ratio"] * 100), "✅ 回款良好" if (cur["rev_cf_ratio"] or 0) >= 1 else "中性偏可"))
    hb.append(("自由现金流", yi(cur["fcf"]) + " 亿", "✅ 真正赚钱" if (cur["fcf"] or 0) > 0 else "⚠ 为负"))
    hb.append(("流动比率", ("%.2f" % cur["current_ratio"]) if cur["current_ratio"] else "—", "✅ 充裕" if (cur["current_ratio"] or 0) >= 1.5 else ("中性" if (cur["current_ratio"] or 0) >= 1 else "⚠ 偏紧")))
    hb.append(("应收账款周转率", ("%.2f" % cur["ar_turnover"]) if cur["ar_turnover"] else "—", "越高回款越快"))
    hb.append(("存货周转率", ("%.2f" % cur["inv_turnover"]) if cur["inv_turnover"] else "—", "越高周转越快"))
    hb.append(("资本开支(投资现金流)", yi((cur.get("op_cf") and None) or (R["current"].get("fcf")) and None) if False else "—", "见投资现金流"))
    health_html = "".join("<tr><td class='k'>%s</td><td class='v'>%s</td><td>%s</td></tr>" % x for x in hb)

    # 行业对比
    if ind.get("avg"):
        avg = ind["avg"]
        ind_html = (
            "<table class='grid'><thead><tr><th>对比项</th><th>%s</th><th>行业平均</th><th>结论</th></tr></thead><tbody>"
            % m["name"] +
            "<tr><td class='k'>毛利率</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (pct(cur["gp_margin"] * 100), pct(avg["gp_margin"] * 100),
               "✅ 成本优势" if (cur["gp_margin"] or 0) > (avg["gp_margin"] or 0) else "低于行业") +
            "<tr><td class='k'>净利率</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (pct(cur["net_margin"] * 100), pct(avg["net_margin"] * 100),
               "✅ 更优" if (cur["net_margin"] or 0) > (avg["net_margin"] or 0) else "低于行业") +
            "<tr><td class='k'>资产负债率</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (pct(cur["debt_ratio"]), pct(avg["debt_ratio"]),
               "✅ 更稳健" if (cur["debt_ratio"] is not None and cur["debt_ratio"] < (avg["debt_ratio"] or 999)) else "高于行业") +
            "<tr><td class='k'>归母净利润</td><td>%s 亿</td><td>—</td><td>行业第 %s / 共 %s 家</td></tr>"
            % (yi(cur["np"]), ind.get("rank_np"), ind.get("count")) +
            "</tbody></table>"
        )
        top3 = ind.get("top3") or []
        peers_html = "<div class='peers'><span class='lbl'>同业龙头(按净利)：</span>" + " ｜ ".join(
            "%s(%s亿)" % (p["name"], yi(p["np"])) for p in top3) + "</div>"
    else:
        ind_html = "<p class='muted'>未获取到同业数据。</p>"
        peers_html = ""

    # 估值
    val_html = (
        "<table class='grid'><thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead><tbody>"
        "<tr><td class='k'>股价</td><td>%s 元</td><td>当日涨跌 %s%%</td></tr>"
        "<tr><td class='k'>PE(TTM)</td><td>%s</td><td>%s</td></tr>"
        "<tr><td class='k'>PB</td><td>%s</td><td>市净率</td></tr>"
        "<tr><td class='k'>总市值</td><td>%s 亿</td><td>换手率 %s%%</td></tr>"
        "</tbody></table>"
        % ((("%.2f" % m["price"]) if m["price"] else "—"),
           ("%.2f" % m["change_pct"]) if m["change_pct"] is not None else "—",
           ("%.2f" % m["pe_ttm"]) if m["pe_ttm"] else "—",
           "估值分位需结合历史" if m["pe_ttm"] else "—",
           ("%.2f" % m["pb"]) if m["pb"] else "—",
           ("%.2f" % m["mktcap_yi"]) if m["mktcap_yi"] else "—",
           ("%.2f" % m["turnover"]) if m["turnover"] is not None else "—")
    )

    good_html = "".join("<li>%s</li>" % g for g in sc["good"]) or "<li>—</li>"
    warn_html = "".join("<li>%s</li>" % w for w in sc["warn"]) or "<li>—</li>"

    # 自动生成的关键判断 / 潜力判断
    trend_note = ""
    if R["trend"]:
        last = R["trend"][-1]; first = R["trend"][0]
        if len(R["trend"]) >= 2:
            rev_g = (last["rev"] or 0) > (first["rev"] or 0)
            np_g = (last["np"] or 0) > (first["np"] or 0)
            trend_note = ("近 %d 个年报窗口，营收%s、归母净利润%s；毛利率由 %s 变动至 %s，%s。"
                          % (len(R["trend"]), "持续增长" if rev_g else "回落", "持续增长" if np_g else "回落",
                             pct(first["gp_margin"] * 100), pct(last["gp_margin"] * 100),
                             "竞争力增强" if (last["gp_margin"] or 0) > (first["gp_margin"] or 0) else "承压"))

    potential = ("综合盈利能力、财务健康度与行业地位，%s 在%s板块中%s。%s"
                 % (m["name"], ind["ind_name"],
                    ("处于领先梯队" if (ind.get("rank_np") and ind["rank_np"] <= 3) else "具备一定竞争力"),
                    trend_note or "建议结合行业周期进一步研判。"))

    today = datetime.date.today().strftime("%Y-%m-%d")
    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    watermark = "投研工作台 · 仅供研究参考　" * 60
    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>个股财务分析 · %(name)s(%(code)s)</title>
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
td.yoy{color:var(--sub)}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:700}
.badge.good{background:#dcfce7;color:#15803d}
.badge.warn{background:#fee2e2;color:#b91c1c}
.badge.neu{background:#e0f2fe;color:#0369a1}
.score{display:flex;align-items:center;gap:16px;margin-bottom:8px}
.stars{font-size:34px;color:var(--accent);letter-spacing:4px}
.score .num{font-size:15px;color:var(--sub)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.cols h3{font-size:15px;margin-bottom:8px;color:#334155}
.cols ul{list-style:none}
.cols li{padding:6px 0;border-bottom:1px dashed var(--line);font-size:13.5px}
.cols li:before{content:"•";color:var(--accent);margin-right:8px}
.peers{margin-top:12px;font-size:13px;color:var(--sub)}
.peers .lbl{color:#334155;font-weight:600}
.note{font-size:13.5px;color:var(--sub);background:#fff7ed;border-left:3px solid var(--accent);
padding:10px 14px;border-radius:8px;margin-top:12px}
.muted{color:var(--sub);font-size:13px}
footer{text-align:center;color:var(--sub);font-size:12px;margin:20px 0;padding-top:10px}
.tag{display:inline-block;background:#fef3e2;color:var(--accent);padding:2px 8px;border-radius:6px;font-size:12px;margin-left:8px}
.export-btn{margin-top:14px;display:inline-block;padding:8px 16px;border:0;border-radius:10px;
background:#fdba74;color:#1e293b;font-size:14px;font-weight:700;cursor:pointer}
.export-btn:hover{background:#fcd34d}
/* 以下三要素仅打印（导出 PDF）时显示，屏幕交互视图保持干净 */
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
  /* 水印：每页重复，极淡，置于内容之下 */
  .pdf-watermark{display:block;position:fixed;top:-30%%;left:-30%%;width:160%%;height:160%%;
    z-index:-1;pointer-events:none;overflow:hidden;
    font-size:20px;line-height:2.6;color:rgba(15,23,42,0.05);
    transform:rotate(-28deg);word-break:break-all;letter-spacing:1px}
  /* 页眉：每页固定显示 */
  .pdf-runninghead{display:flex;position:fixed;top:0;left:0;right:0;height:9mm;
    align-items:center;justify-content:space-between;padding:0 12mm;
    font-size:8.5px;color:#64748b;border-bottom:0.4px solid #cbd5e1;background:#fff;z-index:60}
  /* 封面：独立首页 */
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
<div class="pdf-runninghead"><span>投研工作台 · 个股财务分析</span><span>%(name)s（%(code)s）· %(period)s</span><span>%(today)s</span></div>
<div class="pdf-cover">
  <div class="kicker">投研工作台 · 个股财务分析报告</div>
  <div class="title">%(name)s</div>
  <div class="sub">%(code)s · %(ind_name)s · %(period)s 报告期</div>
  <div class="meta">财务健康度评分 %(starnum)s / 5　｜　数据截止 %(report_date)s<br>生成时间 %(gen_time)s</div>
  <div class="note">本报告由 AI 依据公开财务数据自动生成，仅供研究参考，不构成投资建议。</div>
</div>
<div class="wrap">
<header>
<h1>%(name)s <span class="code">%(code)s · %(ind_name)s</span></h1>
<div>财务分析报告　报告期：<b>%(period)s</b>（数据截止 %(report_date)s）</div>
<div class="meta">
<div><b>%(price)s</b>股价(元) <span class="%(chgcls)s">%(chg)s%%</span></div>
<div><b>%(pe)s</b>PE(TTM)</div>
<div><b>%(pb)s</b>PB</div>
<div><b>%(mktcap)s</b>总市值(亿)</div>
<div><b>%(turn)s%%</b>换手率</div>
<button class="no-print export-btn" onclick="exportFA('%(code)s')">&#11015; 导出 PDF</button>
</div></header>

<section><h2>一、最新报告期核心数据 <span class="tag">盈利能力 · 财务健康</span></h2>
<table class="grid"><thead><tr><th>指标</th><th>数值</th><th>同比</th><th>评判</th></tr></thead>
<tbody>%(core)s</tbody></table></section>

<section><h2>二、成长性 <span class="tag">CAGR · 趋势</span></h2>
%(trend)s
<div class="note">%(cagr)s　%(trendnote)s</div></section>

<section><h2>三、财务健康度核查 <span class="tag">现金流 · 偿债 · 周转</span></h2>
<table class="grid"><thead><tr><th>维度</th><th>数据</th><th>结论</th></tr></thead>
<tbody>%(health)s</tbody></table></section>

<section><h2>四、行业横向对比 <span class="tag">%(ind_name)s</span></h2>
%(ind_html)s
%(peers_html)s</section>

<section><h2>五、估值水平</h2>
%(val_html)s</section>

<section><h2>六、综合结论</h2>
<div class="score"><div class="stars">%(stars)s</div>
<div class="num">财务健康度评分 %(starnum)s / 5　（依据文档评判标准自动测算）</div></div>
<div class="cols">
<div><h3>✅ 健康方面</h3><ul>%(good)s</ul></div>
<div><h3>⚠ 需警惕方面</h3><ul>%(warn)s</ul></div>
</div>
<div class="note"><b>发展潜力判断：</b>%(potential)s</div></section>

<section><h2>七、后续跟踪清单</h2>
<table class="grid"><thead><tr><th>跟踪指标</th><th>观察意义</th></tr></thead><tbody>
<tr><td class='k'>毛利率趋势（是否维持高位）</td><td>盈利拐点信号</td></tr>
<tr><td class='k'>净现比是否回升至 1 以上</td><td>利润质量验证</td></tr>
<tr><td class='k'>经营现金流 vs 资本开支差额</td><td>自由现金流转正能力</td></tr>
<tr><td class='k'>行业新增产能投产节奏</td><td>决定景气延续时长</td></tr>
<tr><td class='k'>下游需求与订单边际变化</td><td>需求端验证</td></tr>
</tbody></table></section>

<footer>本报告由「投研工作台·财务分析」自动生成，数据来源：东方财富 / 腾讯财经，生成于 %(today)s。
财务数据仅作研究参考，不构成投资建议。</footer>
<script>function exportFA(code){if(location.protocol==='file:'){window.print();return;}window.location.href='/fa/export_pdf?code='+encodeURIComponent(code);}</script>
</div></body></html>""" % {
        "name": m["name"], "code": m["code"], "ind_name": m["ind_name"],
        "period": m["period"], "report_date": m["report_date"],
        "price": ("%.2f" % m["price"]) if m["price"] else "—",
        "chg": ("%.2f" % m["change_pct"]) if m["change_pct"] is not None else "—",
        "chgcls": chg_cls,
        "pe": ("%.2f" % m["pe_ttm"]) if m["pe_ttm"] else "—",
        "pb": ("%.2f" % m["pb"]) if m["pb"] else "—",
        "mktcap": ("%.2f" % m["mktcap_yi"]) if m["mktcap_yi"] else "—",
        "turn": ("%.2f" % m["turnover"]) if m["turnover"] is not None else "—",
        "core": core_html, "trend": trend_html, "cagr": cagr_txt, "trendnote": trend_note,
        "health": health_html, "ind_html": ind_html, "peers_html": peers_html,
        "val_html": val_html, "stars": star_str, "starnum": ("%.1f" % sc["stars"]),
        "good": good_html, "warn": warn_html, "potential": potential,
        "today": today, "gen_time": gen_time, "watermark": watermark,
    }
    return html


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def write_report(code, out_dir=None):
    R = analyze(code)
    html = render_html(R)
    out_dir = out_dir or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    fn = "财务分析_%s_%s_%s.html" % (R["meta"]["code"], R["meta"]["name"], R["meta"]["report_date"][:7].replace("-", ""))
    path = os.path.join(out_dir, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path, R


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>个股财务分析 · 投研工作台</title>
<style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{background:#1e293b;padding:40px;border-radius:18px;max-width:560px;box-shadow:0 12px 40px rgba(0,0,0,.4);text-align:center}
h1{font-size:24px;color:#fdba74;margin-bottom:6px}
p{color:#94a3b8;font-size:14px;margin:10px 0 24px}
form{display:flex;gap:10px}
input{flex:1;padding:12px 14px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:#fff;font-size:15px}
button{padding:12px 22px;border:0;border-radius:10px;background:#ed7d31;color:#fff;font-size:15px;font-weight:700;cursor:pointer}
button:hover{background:#f0883e}
.tip{margin-top:18px;font-size:12px;color:#64748b}
</style></head><body><div class="box">
<h1>个股财务分析</h1>
<p>输入个股名称或代码，自动生成《个股财务数据分析》框架下的结构化报告</p>
<form action="/fa/analyze" method="get">
<input name="code" placeholder="如 600176 或 中国巨石" required>
<button>生成报告</button></form>
<div class="tip">数据来源：东方财富财务三大报表 + 腾讯行情估值 ｜ 覆盖盈利能力/财务健康/现金流/成长性/同业/估值/综合评分 ｜ 报告页可一键导出 PDF</div>
</div></body></html>"""


def serve(port=8848):
    """同端口托管投研工作台（静态文件）与财务分析工具（/fa/ 路由）。"""
    import http.server
    import socketserver
    import urllib.parse as _up

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=ROOT, **k)

        def end_headers(self):
            # HTML 等页面禁用浏览器缓存，避免改版后用户端仍跑旧代码
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            super().end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path.startswith("/fa/"):
                return self.handle_fa()
            return super().do_GET()

        def do_POST(self):
            self.send(405, b"method not allowed", "text/plain")

        def handle_fa(self):
            u = _up.urlparse(self.path)
            route = u.path
            qs = _up.parse_qs(u.query)
            if route in ("/fa/", "/fa/index.html"):
                self.send_html(INDEX_HTML)
                return
            if route == "/fa/analyze":
                code = (qs.get("code") or ["600176"])[0].strip()
                try:
                    R = analyze(code)
                    self.send_html(render_html(R))
                except Exception as e:
                    self.send_html("<h2>分析失败</h2><p>%s</p><p><a href='/fa/'>返回</a></p>" % e)
                return
            if route == "/fa/export_pdf":
                code = (qs.get("code") or [""])[0].strip()
                if not code:
                    self.send(400, b"missing code", "text/plain")
                    return
                try:
                    R = analyze(code)
                    html = render_html(R)
                    out_dir = os.path.join(ROOT, "archive", "temp_fa")
                    os.makedirs(out_dir, exist_ok=True)
                    pdf_name = "财务分析_%s_%s_%s.pdf" % (
                        R["meta"]["code"], R["meta"]["name"],
                        R["meta"]["report_date"][:7].replace("-", ""))
                    pdf_path = os.path.join(out_dir, pdf_name)
                    render_pdf(html, pdf_path, keep_html=False)
                    with open(pdf_path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    # http.server 用 latin-1 编码响应头，中文文件名必须走 RFC5987 编码
                    disp = 'attachment; filename="financial_report_%s.pdf"; filename*=UTF-8\'\'%s' % (
                        R["meta"]["code"], _up.quote(pdf_name))
                    self.send_header("Content-Disposition", disp)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    try:
                        os.remove(pdf_path)
                    except OSError:
                        pass
                except Exception as e:
                    self.send(500, ("导出失败: %s" % e).encode("utf-8"),
                              "text/plain; charset=utf-8")
                return
            self.send(404, b"not found", "text/plain")

        def send_html(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    print("投研工作台（含财务分析）已启动： http://localhost:%d  (Ctrl+C 停止)" % port)
    print("财务分析工具入口： http://localhost:%d/fa/" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--serve", "-s"):
        port = 8848
        for i, a in enumerate(args):
            if a in ("--serve", "-s") and i + 1 < len(args):
                try: port = int(args[i + 1])
                except Exception: pass
        serve(port)
        return
    if args[0] in ("--help", "-h"):
        print(__doc__)
        return
    code = args[0]
    out_dir = None
    do_pdf = "--pdf" in args
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out_dir = args[idx + 1]
    path, R = write_report(code, out_dir)
    print("已生成报告：%s" % path)
    print("标的：%s(%s) 报告期：%s 评分：%.1f/5" % (
        R["meta"]["name"], R["meta"]["code"], R["meta"]["period"], R["score"]["stars"]))
    if do_pdf:
        pdf_path = os.path.splitext(path)[0] + ".pdf"
        try:
            render_pdf(open(path, encoding="utf-8").read(), pdf_path)
            print("已导出 PDF：%s" % pdf_path)
        except Exception as e:
            print("PDF 导出失败：%s" % e)


if __name__ == "__main__":
    main()
