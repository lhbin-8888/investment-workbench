# -*- coding: utf-8 -*-
"""
宏观研究页数据刷新脚本
----------------------
抓取近一周四类资产的日度数据，写入 data/macro-weekly.json，
并同步注入 index.html 的离线快照区（供 file:// 直接打开时使用）。

数据源：
  - COMEX黄金 / 布伦特原油 : 新浪财经 外盘期货日线
  - 美债 10Y / 30Y        : FRED (DGS10 / DGS30)
  - 人民币汇率 USD/CNY    : Frankfurter (ECB 参考汇率)

用法：
  python tools/refresh_macro.py
"""
import io, json, os, re, subprocess, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_JSON = os.path.join(DATA_DIR, "macro-weekly.json")
# 需要同步写入离线快照的页面（本地工作台 + GitHub 仓库副本，存在才写）
HTML_TARGETS = [
    os.path.join(ROOT, "index.html"),
    r"C:\Users\73873\investment-workbench\index.html",
]
N = 6  # 每个品种保留的最近观测点数

# ---------- 中国宏观政策信息（人工维护，新增/修改在此编辑） ----------
POLICIES = [
    {
        "date": "2026-09-07",
        "tag": "货币政策",
        "title": "央行等量续作 5000 亿元 3 个月买断式逆回购",
        "summary": "9 月 7 日央行开展 5000 亿元 3 个月期（89 天）买断式逆回购，同日 7 天期逆回购仅 5 亿元，"
                   "公开市场净回笼 45 亿元，结束此前连续两个月的加量续作。9 月中长期资金到期压力约 1.78 万亿元"
                   "（含 5000 亿 6 个月买断式逆回购、6000 亿 MLF、1800 亿国库现金定存）。机构解读为"
                   "“总量克制、结构优先”，短期降准降息概率偏低，视政府债发行节奏相机抉择。",
        "source": "中国经济网 / 证券日报",
    },
    {
        "date": "2026-09-07",
        "tag": "货币政策",
        "title": "央行行长潘功胜 G20 会议表态：继续实施适度宽松货币政策",
        "summary": "8 月 31 日至 9 月 1 日 G20 财长与央行行长会议在美召开。潘功胜表示，央行将持续推进货币政策"
                   "框架转型、完善利率体系，继续实施好适度宽松的货币政策，为中国经济稳定增长和金融市场平稳运行"
                   "营造良好的货币金融环境。",
        "source": "新华财经",
    },
    {
        "date": "2026-09-04",
        "tag": "财政政策",
        "title": "8000 亿元新型政策性金融工具开闸投放",
        "summary": "2026 年新型政策性金融工具首批资金已在浙江、云南、四川、福建、新疆、湖北等地落地，"
                   "额度由去年 5000 亿元增至 8000 亿元，投向扩至数字经济、人工智能、低空经济、商业航天等"
                   "新兴产业，并加大民间投资支持（福建申报项目中民资项目占比近四成）。"
                   "机构预计可撬动 8 万亿—11 万亿元项目总投资，9—10 月为集中落地窗口，央行以 PSL 配套支持。",
        "source": "上海证券报 / 证券时报 / 中国证券报",
    },
    {
        "date": "2026-09-02",
        "tag": "财政政策",
        "title": "财政部等优化财政金融协同促内需贴息政策（财金〔2026〕71 号）",
        "summary": "中小微民营企业新发放流动资金贷款纳入贴息（年化 1 个百分点、期限不超 2 年）；"
                   "信用卡分期等新发生业务纳入个人消费贷款贴息；经办机构扩至 21 家全国性银行及 3A 以上城商行等；"
                   "单户中小微贴息贷款上限 5000 万→7500 万元，个人消费贷及信用卡分期贴息上限 3000 元→5000 元/年。"
                   "自 2026 年 8 月 1 日起施行。",
        "source": "财政部 / 中国人民银行 / 金融监管总局",
    },
    {
        "date": "2026-09-01",
        "tag": "内需消费",
        "title": "七部门印发《关于推动商品消费扩容升级的实施意见》",
        "summary": "商务部、发改委、工信部、财政部、农业农村部、文旅部、市场监管总局联合发文，明确到 2030 年"
                   "社零总额达 60 万亿元左右，培育绿色消费、智能消费、健康消费等十万亿级市场；重点激活汽车、"
                   "家电等大宗消费，常态化推进以旧换新；强化财政金融支持（用好个人消费贷与服务业经营主体贷款贴息）。",
        "source": "光明日报 / 央广网",
    },
    {
        "date": "2026-08-31",
        "tag": "国务院部署",
        "title": "国常会部署城市地下管网建设与招商引资高质量发展",
        "summary": "8 月 31 日国常会听取城市地下管网建设情况汇报（我国管网总长约 390 万公里，"
                   "“十五五”将建设改造约 77 万公里，纳入《城市更新“十五五”规划》主要指标）；"
                   "研究促进招商引资高质量发展，要求明确政府招商鼓励与禁止行为清单，从“拼优惠”转向“拼生态”；"
                   "讨论并原则通过《税收征收管理法（修订草案）》，审议通过《审计法实施条例（修订草案）》。",
        "source": "新华社 / 中国政府网",
    },
    {
        "date": "2026-09-03",
        "tag": "产业政策",
        "title": "工信部等十部门印发《促进中小企业发展“十五五”规划》",
        "summary": "提出加大直接融资支持：建立优质中小企业上市培育库，深化区域性股权市场“专精特新”专板建设，"
                   "高质量建设债券市场“科技板”，设立国家中小企业发展基金二期，带动社会资本投早、投小、投长期、"
                   "投硬科技。同日工信部表态加快动力电池安全、循环寿命、碳足迹、回收利用等标准制定。",
        "source": "中国证券报 / 工业和信息化部",
    },
    {
        "date": "2026-09-02",
        "tag": "投资抓手",
        "title": "发改委推进“六张网”重大项目建设",
        "summary": "国家发改委召开“六张网”（水网、新型电网、算力网、新一代通信网、城市地下管网、物流网）"
                   "重大项目协调推进机制会，研究完善政银企协作机制与项目库建设。下半年着力推动“六张网”"
                   "从规划布局转向形成实物工作量，对产业链上下游形成拉动。",
        "source": "上海证券报",
    },
]

SINA_HDR = "-H", "Referer: https://finance.sina.com.cn"


def curl(url, extra=(), timeout=25, retries=2):
    """调用 curl 抓取。注意：FRED 会拒绝自定义 User-Agent，故默认不附加 UA。"""
    cmd = ["curl", "-s", "-m", str(timeout)] + list(extra) + [url]
    for _ in range(retries):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.stdout and r.stdout.strip():
            return r.stdout
        time.sleep(3)
    return ""


def sina_daily(symbol, field_map=None):
    """新浪外盘期货日线，返回 [{date, open, high, low, close}]"""
    url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t/"
           "GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=" + symbol)
    txt = curl(url, SINA_HDR)
    m = re.search(r"var t\((\[.*\])\)", txt, re.S)
    if not m:
        return []
    rows = json.loads(m.group(1))
    out = []
    for r in rows:
        try:
            out.append({"date": r["date"], "close": float(r["close"])})
        except Exception:
            continue
    return out


FRED_IDS = [("DGS10", "v10"), ("DGS30", "v30")]


def fred_csv(series_id):
    """FRED 日度收益率序列，返回 [(date, value)]，跳过缺失值 '.'"""
    txt = curl("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series_id,
               timeout=45, retries=3)
    out = []
    for line in txt.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        d, v = parts[0].strip(), parts[1].strip()
        if v in ("", ".", "NA"):
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


def frankfurter(days=14):
    """USD/CNY 日度参考汇率，返回 [(date, value)]"""
    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=days)
    url = ("https://api.frankfurter.dev/v1/{s}..{e}?base=USD&symbols=CNY"
           .format(s=start.strftime("%Y-%m-%d"), e=end.strftime("%Y-%m-%d")))
    txt = curl(url)
    try:
        rates = json.loads(txt).get("rates", {})
    except Exception:
        return []
    return sorted((d, float(v["CNY"])) for d, v in rates.items() if v.get("CNY"))


def md(datestr):
    return datestr[5:]  # 2026-09-08 -> 09-08


def build(prev=None):
    markets = []

    # 1) 黄金
    g = sina_daily("GC")[-N:]
    if g:
        markets.append({
            "key": "gold", "name": "国际黄金（COMEX 黄金连续）", "unit": "美元/盎司",
            "source": "新浪财经 · 外盘期货", "note": "",
            "lines": [{"label": "COMEX 黄金", "field": "v", "color": "#F5C542"}],
            "points": [{"d": md(x["date"]), "v": round(x["close"], 2)} for x in g],
        })

    # 2) 布伦特原油
    o = sina_daily("OIL")[-N:]
    if o:
        markets.append({
            "key": "brent", "name": "布伦特原油（ICE Brent 连续）", "unit": "美元/桶",
            "source": "新浪财经 · 外盘期货", "note": "",
            "lines": [{"label": "布伦特原油", "field": "v", "color": "#FF7A45"}],
            "points": [{"d": md(x["date"]), "v": round(x["close"], 2)} for x in o],
        })

    # 3) 美债 10Y / 30Y（FRED 偶发不可用，失败时沿用上次数据以保持曲线连续）
    t10 = dict(fred_csv("DGS10"))
    t30 = dict(fred_csv("DGS30"))
    common = sorted(set(t10) & set(t30))[-N:]
    if common:
        markets.append({
            "key": "ust", "name": "美债收益率（10 年期 / 30 年期）", "unit": "%",
            "source": "FRED · DGS10 / DGS30",
            "note": "美债数据公布较市场价滞后 1—2 个交易日",
            "lines": [{"label": "10 年期", "field": "v10", "color": "#00E5FF"},
                      {"label": "30 年期", "field": "v30", "color": "#8B5CF6"}],
            "points": [{"d": md(d), "v10": t10[d], "v30": t30[d]} for d in common],
        })
    elif prev:
        for m in (prev.get("markets") or []):
            if m.get("key") == "ust":
                m2 = json.loads(json.dumps(m))
                m2["note"] = "本次抓取失败，沿用上次数据"
                markets.append(m2)
                print("  ! 美债抓取失败，沿用上次数据")
                break

    # 4) 人民币汇率
    fx = frankfurter()[-N:]
    if fx:
        markets.append({
            "key": "cny", "name": "人民币汇率（USD/CNY）", "unit": "CNY",
            "source": "Frankfurter · ECB 参考汇率",
            "note": "数值上行代表人民币贬值、美元升值",
            "lines": [{"label": "USD/CNY", "field": "v", "color": "#10B981"}],
            "points": [{"d": md(d), "v": round(v, 4)} for d, v in fx],
        })

    order = {"gold": 0, "brent": 1, "ust": 2, "cny": 3}
    markets.sort(key=lambda m: order.get(m.get("key"), 9))

    return {
        "updated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "markets": markets,
        "policies": POLICIES,
    }


def inject_html(payload):
    """把快照注入所有存在的目标页面，返回成功数量。"""
    block_tpl = "/*MACRO_DATA_START*/" + json.dumps(payload, ensure_ascii=False) + "/*MACRO_DATA_END*/"
    ok = 0
    for path in HTML_TARGETS:
        if not os.path.exists(path):
            print("  - 跳过（不存在）:", path)
            continue
        try:
            src = io.open(path, encoding="utf-8").read()
        except Exception as e:
            print("  ! 读取失败:", path, e)
            continue
        new, cnt = re.subn(r"/\*MACRO_DATA_START\*/.*?/\*MACRO_DATA_END\*/",
                           lambda m: block_tpl, src, flags=re.S)
        if cnt == 0:
            print("  ! 未找到 MACRO_DATA 标记，跳过:", path)
            continue
        io.open(path, "w", encoding="utf-8").write(new)
        ok += 1
        print("  - 已注入:", path)
    return ok


if __name__ == "__main__":
    prev = None
    if os.path.exists(OUT_JSON):
        try:
            prev = json.load(open(OUT_JSON, encoding="utf-8"))
        except Exception:
            prev = None
    payload = build(prev)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("已写入", OUT_JSON)
    for m in payload["markets"]:
        pts = m["points"]
        rng = (pts[0]["d"] + " ~ " + pts[-1]["d"]) if pts else "-"
        print("  -", m["name"], "|", len(pts), "点 |", rng, "| 最新", pts[-1] if pts else "")
    print("  - 政策条目", len(payload["policies"]), "条")
    if inject_html(payload):
        print("已同步注入 index.html 离线快照")
