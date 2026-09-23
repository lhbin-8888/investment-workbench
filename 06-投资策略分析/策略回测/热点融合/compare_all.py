# -*- coding: utf-8 -*-
"""四策略对照：三份原始真实回测日志 + 融合策略（代理/真实）回测结果。

产出：
  - 策略对照_统计表.md      （Markdown 对照表）
  - 策略对照_净值曲线.html  （净值曲线 + 回撤曲线可视化）
口径说明见文件末尾 REPORT_NOTE。
"""
import os
import re
import json
import datetime
import math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 06-投资策略分析/策略回测

LOGS = [
    # (显示名, 文件路径, 净值口径)
    ("热点早盘001", os.path.join(ROOT, "热点早盘001", "001优化方案回测1.txt"), "net"),
    ("热点追踪lhb888", os.path.join(ROOT, "热点追踪lhb888", "策略名称 lhb888.txt"), "buy"),
    ("热点追踪早盘1030", os.path.join(ROOT, "热点追踪早盘1030", "优化版回测1.txt"), "buy"),
]

# 净值行：[净值] 2026-05-06 总资产=100058
PAT_NET = re.compile(r"\[净值\]\s+(\d{4}-\d{2}-\d{2})\s+总资产=(\d+)")
# 买入快照行：2026-05-06 09:32:00 - INFO - [买入] 总资产100000
PAT_BUY = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}.*\[买入\]\s+总资产(\d+)")
# 卖出行格式在三份日志里不统一，分两段宽容解析：
#   早盘1030/lhb888: [卖出] 600001 —— 止盈全清 浮盈12.3%
#   001:            [卖出] 000815 500 股 原因:止损:浮亏-7.4% (模式atr)
#                   [卖出] 000977 100 股 原因:破10日线清仓(尾盘确认) 浮亏 0.9%
PAT_PNL = re.compile(r"浮(盈|亏)\s*(-?[\d.]+)%")
PAT_REASON_A = re.compile(r"——\s*(\S+?)\s+浮")
PAT_REASON_B = re.compile(r"原因[:：]\s*([^\s(（]+)")


def parse_sell_line(ln):
    """返回 (原因, 盈亏小数)；解析失败返回 None"""
    m = PAT_PNL.search(ln)
    if not m:
        return None
    sign, num = m.groups()
    v = float(num) / 100.0
    if sign == "亏":
        v = -abs(v)
    mr = PAT_REASON_A.search(ln) or PAT_REASON_B.search(ln)
    reason = mr.group(1) if mr else "其他"
    return (reason, v)


def parse_log(path, mode):
    """返回 (每日净值序列 [(day, value)], 卖出盈亏列表 [float])"""
    if not os.path.isfile(path):
        return [], []
    series = {}
    sells = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if mode == "net":
                m = PAT_NET.search(ln)
            else:
                m = PAT_BUY.search(ln)
            if m:
                series[m.group(1)] = float(m.group(2))
                continue
            if "[卖出]" in ln:
                got = parse_sell_line(ln)
                if got:
                    sells.append(got[1])
    return sorted(series.items()), sells


def stats_from(series, sells, name, tag):
    if not series:
        return None
    vals = [v for _, v in series]
    days = [d for d, _ in series]
    start, end = vals[0], vals[-1]
    total_ret = end / start - 1.0
    # 最大回撤
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    # 年化（按自然日）
    try:
        span = (datetime.date(*map(int, days[-1].split("-"))) -
                datetime.date(*map(int, days[0].split("-")))).days / 365.0
    except Exception:
        span = 0.0
    ann = (end / start) ** (1.0 / span) - 1.0 if span > 0 else 0.0
    # 夏普（日收益，无风险利率 0）
    rets = []
    for i in range(1, len(vals)):
        if vals[i - 1] > 0:
            rets.append(vals[i] / vals[i - 1] - 1.0)
    if len(rets) > 1:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        sharpe = (mu / sd) * math.sqrt(250.0) if sd > 0 else 0.0
    else:
        sharpe = 0.0
    calmar = (ann / abs(mdd)) if mdd < 0 else 0.0
    wins = [s for s in sells if s > 0]
    losses = [s for s in sells if s <= 0]
    win_rate = len(wins) / float(len(sells)) if sells else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf = (avg_win / abs(avg_loss)) if avg_loss != 0 and wins else 0.0
    return {
        "name": name, "tag": tag, "days": len(series),
        "start": start, "end": end, "total_ret": total_ret,
        "ann": ann, "mdd": mdd, "sharpe": sharpe, "calmar": calmar,
        "trades": len(sells), "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss, "profit_factor": pf,
        "series": series,
    }


REPORT_NOTE = """\
> **口径提醒**：001 用盘后 `[净值]`（每日收盘总资产）；lhb888 / 早盘1030 用
> `[买入]` 时点快照总资产（仅记录有买入动作的交易日）。三者**不是同一口径**，
> 收益数字可比较，但不宜逐日相减。融合策略为本地引擎跑出的**合成行情代理结果**，
> 仅用于验证策略逻辑与出场分支，不代表真实收益。
"""


def main():
    rows = []
    for name, path, mode in LOGS:
        series, sells = parse_log(path, mode)
        st = stats_from(series, sells, name,
                        "真实(盘后净值)" if mode == "net" else "真实(买入快照)")
        if st:
            rows.append(st)

    # 融合策略：优先真实（REAL），回落代理（PROXY）
    fusion = None
    for tag, label in (("REAL", "本地引擎·真实数据"), ("PROXY", "本地引擎·合成代理")):
        csv = os.path.join(HERE, "融合_v1_每日净值_%s.csv" % tag)
        if not os.path.isfile(csv):
            csv = os.path.join(HERE, "融合_v1_每日净资产_%s.csv" % tag)
        if not os.path.isfile(csv):
            continue
        series = []
        with open(csv, encoding="utf-8") as fh:
            for i, ln in enumerate(fh):
                if i == 0 or not ln.strip():
                    continue
                d, v = ln.strip().split(",")[:2]
                series.append((d, float(v)))
        logf = os.path.join(HERE, "融合_v1_回测日志_%s.txt" % tag)
        sells = []
        if os.path.isfile(logf):
            txt = open(logf, encoding="utf-8", errors="replace").read().splitlines()
            sells = [s[3] for s in parse_strategy_sells(txt)]
        st = stats_from(series, sells, "热点融合 v1.8", label)
        if st:
            rows.append(st)
            fusion = st
        break

    # ---- Markdown 对照表 ----
    lines = []
    lines.append("# 四策略回测对照（2026-05-06 ~ 2026-06-30）\n")
    lines.append(REPORT_NOTE)
    lines.append("")
    lines.append("| 策略 | 数据口径 | 样本天数 | 起始 | 期末 | 累计收益 | 年化 | 最大回撤 | 夏普 | 卡玛 | 平仓笔数 | 胜率 | 盈亏比 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        # 无亏损单时盈亏比无意义，显示 n/a
        pf = "n/a" if (r["profit_factor"] == 0.0 and r["avg_loss"] == 0.0) \
            else "%.2f" % r["profit_factor"]
        lines.append("| %s | %s | %d | %.0f | %.0f | %.2f%% | %.2f%% | %.2f%% | %.2f | %.2f | %d | %.1f%% | %s |" % (
            r["name"], r["tag"], r["days"], r["start"], r["end"],
            r["total_ret"] * 100, r["ann"] * 100, r["mdd"] * 100,
            r["sharpe"], r["calmar"], r["trades"], r["win_rate"] * 100, pf))
    lines.append("")
    lines.append("## 结论要点\n")
    real = [r for r in rows if "真实" in r["tag"]]
    if real:
        best_ret = max(real, key=lambda r: r["total_ret"])
        # 回撤为负数，"最小回撤"= 最接近 0（绝对值最小）
        best_dd = max(real, key=lambda r: r["mdd"])
        best_calmar = max(real, key=lambda r: r["calmar"])
        lines.append("- 真实日志中**收益最高**：%s（%.2f%%，回撤 %.2f%%）"
                     % (best_ret["name"], best_ret["total_ret"] * 100, best_ret["mdd"] * 100))
        lines.append("- 真实日志中**回撤最小**：%s（%.2f%%，收益 %.2f%%）"
                     % (best_dd["name"], best_dd["mdd"] * 100, best_dd["total_ret"] * 100))
        lines.append("- 真实日志中**风险调整收益最佳（卡玛）**：%s（%.2f）"
                     % (best_calmar["name"], best_calmar["calmar"]))
    if fusion:
        lines.append("- 融合策略（%s）：累计 %.2f%%，最大回撤 %.2f%%，平仓 %d 笔"
                     % (fusion["tag"], fusion["total_ret"] * 100,
                        fusion["mdd"] * 100, fusion["trades"]))
        lines.append("  - **该结果仅证明策略逻辑与出场分支可跑通**，真实收益需导入真实行情后重跑。")
    lines.append("")

    md_path = os.path.join(HERE, "策略对照_统计表.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # ---- 净值曲线 HTML ----
    html = build_html(rows)
    html_path = os.path.join(HERE, "策略对照_净值曲线.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    print("对照表 :", md_path)
    print("净值图 :", html_path)
    print("")
    for r in rows:
        print("%-18s %-16s 天数%3d 收益 %7.2f%% 回撤 %7.2f%% 夏普 %6.2f 交易%3d 胜率%5.1f%%" % (
            r["name"], r["tag"], r["days"], r["total_ret"] * 100, r["mdd"] * 100,
            r["sharpe"], r["trades"], r["win_rate"] * 100))
    return rows


def parse_strategy_sells(log_lines):
    pat = re.compile(
        r"\[(\d{4}-\d{2}-\d{2})\].*\[卖出\]\s+(\S+)"
        r"(?:\s+数量\d+)?\s*(?:——)?\s*(\S+?)\s+浮(盈|亏)(-?[\d.]+)%")
    out = []
    for ln in log_lines:
        m = pat.search(ln)
        if not m:
            continue
        day, code, reason, sign, num = m.groups()
        v = float(num) / 100.0
        out.append((day, code, reason, -abs(v) if sign == "亏" else v))
    return out


def build_html(rows):
    """纯前端折线图（无外部依赖，SVG 手绘）"""
    colors = ["#ED7D31", "#2E75B6", "#548235", "#C00000", "#7030A0"]
    # 归一化到 1.0 起点
    series_js = []
    labels = []
    for r in rows:
        vals = [v for _, v in r["series"]]
        if not vals:
            continue
        base = vals[0]
        norm = [v / base for v in vals]
        series_js.append({"name": r["name"], "color": colors[len(labels) % len(colors)],
                          "vals": norm})
        if not labels:
            labels = [d for d, _ in r["series"]]
    import json as _j
    payload = _j.dumps({"labels": labels, "series": series_js}, ensure_ascii=False)
    return u"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>四策略净值对照</title>
<style>
 body{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#fff;color:#222;margin:0;padding:24px}
 h1{font-size:20px;color:#ED7D31;margin:0 0 4px}
 .note{font-size:12px;color:#888;margin-bottom:16px;line-height:1.6}
 .legend{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0;font-size:13px}
 .legend span{display:flex;align-items:center;gap:6px}
 .dot{width:10px;height:10px;border-radius:50%}
 table{border-collapse:collapse;font-size:13px;margin-top:18px}
 th,td{border:1px solid #e3e3e3;padding:6px 10px;text-align:right}
 th{background:#ED7D31;color:#fff}
 td:first-child,th:first-child{text-align:left}
</style></head><body>
<h1>四策略净值对照（2026-05-06 ~ 2026-06-30，起点归一化为 1.00）</h1>
<div class="note">口径：001 为盘后净值；lhb888 / 早盘1030 为买入时点快照；融合策略为本地引擎结果。<b>三者口径不同，收益可比较，不宜逐日相减。</b></div>
<div class="legend" id="lg"></div>
<svg id="cv" width="1080" height="420"></svg>
<table id="tb"></table>
<script>
const D = __DATA__;
const W=1080,H=420,PL=56,PR=20,PT=20,PB=44;
const iw=W-PL-PR, ih=H-PT-PB;
let lo=1e9, hi=-1e9;
D.series.forEach(s=>s.vals.forEach(v=>{lo=Math.min(lo,v);hi=Math.max(hi,v);}));
lo=Math.min(lo,0.97); hi=Math.max(hi,1.03);
const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
const X=i=>PL+iw*i/Math.max(D.labels.length-1,1);
const Y=v=>PT+ih*(hi-v)/(hi-lo);
let svg='';
// 网格
for(let g=0;g<=5;g++){const v=lo+(hi-lo)*g/5;const y=Y(v);
 svg+=`<line x1="${PL}" y1="${y}" x2="${W-PR}" y2="${y}" stroke="#eee"/>`;
 svg+=`<text x="${PL-8}" y="${y+4}" font-size="11" fill="#999" text-anchor="end">${v.toFixed(2)}</text>`;}
// 基准线 1.00
svg+=`<line x1="${PL}" y1="${Y(1)}" x2="${W-PR}" y2="${Y(1)}" stroke="#ccc" stroke-dasharray="4 3"/>`;
// x 轴标签
D.labels.forEach((d,i)=>{ if(i%4===0||i===D.labels.length-1)
 svg+=`<text x="${X(i)}" y="${H-PB+18}" font-size="10" fill="#999" text-anchor="middle">${d.slice(5)}</text>`;});
// 曲线
D.series.forEach(s=>{let p='';
 s.vals.forEach((v,i)=>{p+=(i?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1);});
 svg+=`<path d="${p}" fill="none" stroke="${s.color}" stroke-width="2"/>`;});
document.getElementById('cv').innerHTML=svg;
document.getElementById('lg').innerHTML=D.series.map(s=>
 `<span><i class="dot" style="background:${s.color}"></i>${s.name}</span>`).join('');
const rows=[['策略','期末净值倍数','累计收益','最大回撤']];
D.series.forEach(s=>{const e=s.vals[s.vals.length-1];let pk=1,mdd=0;
 s.vals.forEach(v=>{pk=Math.max(pk,v);mdd=Math.min(mdd,v/pk-1);});
 rows.push([s.name,e.toFixed(3),((e-1)*100).toFixed(2)+'%',(mdd*100).toFixed(2)+'%']);});
document.getElementById('tb').innerHTML=rows.map((r,i)=>
 '<tr>'+r.map(c=>i===0?`<th>${c}</th>`:`<td>${c}</td>`).join('')+'</tr>').join('');
</script></body></html>""".replace("__DATA__", payload)


if __name__ == "__main__":
    main()
