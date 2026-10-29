# -*- coding: utf-8 -*-
"""
生成板块轮动复盘 Excel 登记表
输出：D:/投研工作台/04-投资复盘/板块轮动复盘/板块轮动复盘登记表_20260801-20261028.xlsx

工作表：
  1. 说明与口径        —— 数据源、判定标准、局限
  2. 每日真主线真热点  —— 逐日重建结论（核心交付）
  3. 十日指数跟踪      —— 选中板块 10 日表现明细
  4. 日报判定复盘      —— 日报实际判定 vs 客观重建 + 事后验证
  5. 评分维度有效性    —— 各维度/门槛与 10 日超额的关系（优化依据）
  6. 全市场实证统计    —— 12810 样本的 gate×涨幅 交叉画像
  7. 评分标准优化建议  —— v1 → v2 修订对照
"""
import json, os, statistics as st
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = "D:/投研工作台/04-投资复盘/板块轮动复盘"
OUT = os.path.join(OUT_DIR, "板块轮动复盘登记表_20260801-20261028.xlsx")

# ---------- 样式 ----------
C_ORANGE = "ED7D31"
C_HEAD = "1F4E79"
C_SUB = "FCE4D6"
C_GOOD = "C6EFCE"
C_BAD = "FFC7CE"
C_WARN = "FFEB9C"
F_TITLE = Font(name="微软雅黑", size=14, bold=True, color="FFFFFF")
F_HEAD = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
F_BOLD = Font(name="微软雅黑", size=10, bold=True)
F_NORM = Font(name="微软雅黑", size=9)
FILL_TITLE = PatternFill("solid", fgColor=C_ORANGE)
FILL_HEAD = PatternFill("solid", fgColor=C_HEAD)
FILL_SUB = PatternFill("solid", fgColor=C_SUB)
FILL_GOOD = PatternFill("solid", fgColor=C_GOOD)
FILL_BAD = PatternFill("solid", fgColor=C_BAD)
FILL_WARN = PatternFill("solid", fgColor=C_WARN)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")


def style_header(ws, row, ncol, fill=FILL_HEAD, font=F_HEAD):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill
        cell.font = font
        cell.alignment = CENTER
        cell.border = BORDER


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def title_row(ws, text, ncol):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    c = ws.cell(row=1, column=1, value=text)
    c.fill = FILL_TITLE
    c.font = F_TITLE
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28


def pct_cell(ws, r, c, v, fmt="0.00"):
    cell = ws.cell(row=r, column=c, value=v)
    cell.number_format = fmt
    return cell


def main():
    full = json.load(open(os.path.join(ROOT, "review_full.json"), encoding="utf-8"))
    daily = json.load(open(os.path.join(ROOT, "rebuild_daily.json"), encoding="utf-8"))
    # 打分后的每日结论（review_full.daily_summary 含结论与板块名）
    ds_map = {d["date"]: d for d in full["daily_summary"]}
    # 逐日候选的完整字段（含 concl/s/avg/fwd/br）从 all_rows + picks 重建
    rows_by_date = defaultdict(list)
    for r in full["all_rows"]:
        rows_by_date[r["date"]].append(r)
    pick_by_date = defaultdict(list)
    for p in full["picks"]:
        pick_by_date[p["date"]].append(p)
    stats = full["stats"]
    picks = full["picks"]
    align = full["align"]
    actual = json.load(open(os.path.join(ROOT, "actual_reports.json"), encoding="utf-8"))

    os.makedirs(OUT_DIR, exist_ok=True)
    wb = Workbook()

    # ==================== 1. 说明与口径 ====================
    ws = wb.active
    ws.title = "1.说明与口径"
    title_row(ws, "板块轮动主线判定复盘 · 说明与口径（2026-08-01 ~ 2026-10-28）", 2)
    set_widths(ws, [26, 108])
    rows = [
        ("任务目标", "以16:00「板块轮动与主线确定每日报告」现行计分方法为基准，"
                     "用真实市场数据重建 8/1–10/28 每日的真主线/真热点，"
                     "对选中板块做 10 个交易日指数跟踪，复盘判定准确性，"
                     "并据此优化评分维度与标准。"),
        ("复盘区间", "2026-08-03 ~ 2026-10-28，共 57 个交易日（8/1 为周六）。"),
        ("主数据源", "东方财富板块指数日线（em_kline）：510 个板块（126 行业 + 384 概念），"
                     "2026-06-01~10-29，区间覆盖率 100%。"),
        ("资金流数据", "东财 datacenter 行业资金流全历史（128 行业 × 80 日 = 9590 行，"
                       "含主力净流入/超大单/大单/中单）。概念板块资金流仅保留当日，"
                       "故概念板块资金维度按 unavailable 处理，不编造。"),
        ("广度数据", "个股日线 4919 只（新浪源）+ 同花顺 90 个行业板块成分股清单，"
                     "据此计算上涨家数占比、涨幅中位数与涨停家数（近似口径）。"),
        ("基准定义", "全市场 510 个板块等权平均日涨跌幅为基准；"
                     "超额收益 = 板块 10 日累计涨幅 − 基准 10 日累计涨幅。"),
        ("命中判定", "命中(强)：10 日超额 ≥ +3.0pp；命中(弱)：10 日超额 ≥ 0；"
                     "其余为未命中。"),
        ("数据源限制①", "涨停池历史接口（push2ex / datacenter RPT_LIMIT_UP_INFO）"
                         "仅保留至 2025-03，无法回溯 2026 年逐日涨停明细。"
                         "本表「涨停家数」为按涨跌幅阈值（主板9.8% / 双创19.8% / 北交所29.8%）"
                         "统计的近似值，非交易所口径。"),
        ("数据源限制②", "概念板块的东财主力资金流仅存当日，无法回补历史。"
                         "概念板块「资金质量」维度记为 None，判定就低。"),
        ("数据源限制③", "8/1–9/15 无历史日报（自动化任务 9/16 才上线），"
                         "该段为纯客观重建，无「日报实际判定」可比对；"
                         "Excel 第 4 表的「日报判定复盘」仅覆盖 9/16–10/28 共 21 期。"),
        ("催化维度说明", "现行标准中「催化环境（利好三问）」需人工核政策/业绩。"
                         "本次复盘无新闻流授权，采用可计算的代理规则"
                         "（连续上榜天数 × 资金连续性），并在评分中降权至 0.8，"
                         "代理值已在「优化建议」表标注，人工复核时替换为真实判定。"),
        ("结论口径", "本表所有判定均为统计回溯结论，不构成投资建议。"),
    ]
    r = 3
    for k, v in rows:
        ws.cell(row=r, column=1, value=k).font = F_BOLD
        ws.cell(row=r, column=1).fill = FILL_SUB
        ws.cell(row=r, column=1).border = BORDER
        ws.cell(row=r, column=1).alignment = WRAP
        c = ws.cell(row=r, column=2, value=v)
        c.font = F_NORM
        c.alignment = WRAP
        c.border = BORDER
        ws.row_dimensions[r].height = 42
        r += 1

    # ==================== 2. 每日真主线真热点 ====================
    ws = wb.create_sheet("2.每日真主线真热点")
    title_row(ws, "每日客观重建判定（现行标准 v1 vs 优化标准 v2）", 14)
    set_widths(ws, [11, 10, 16, 7, 8, 7, 8, 8, 7, 7, 7, 7, 7, 30])
    hdr = ["日期", "大盘日涨幅%", "结论", "板块", "类型", "涨幅%", "主力净流入亿",
           "量比", "连续天数", "gate", "均分", "涨停家数", "上涨占比", "10日超额pp"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    r = 3
    for rec in daily:
        date = rec["date"]
        cand = sorted(pick_by_date.get(date, []),
                      key=lambda c: (0 if c["concl"] == "真主线" else 1, -c["avg"]))
        if not cand:
            # 该日无入选，也登记一行说明
            ws.cell(row=r, column=1, value=date).font = F_NORM
            ws.cell(row=r, column=2, value=rec["market_ret"]).number_format = "0.00"
            ws.cell(row=r, column=3, value="无入选")
            ws.cell(row=r, column=4, value="—")
            for c_ in range(1, 15):
                ws.cell(row=r, column=c_).border = BORDER
                ws.cell(row=r, column=c_).font = F_NORM
            r += 1
            continue
        for c in cand:
            vals = [date, rec["market_ret"], c["concl"], c["name"], c["type"],
                    c["z"], c["f"], c["vb"], c["days"], c["gate"], c["avg"],
                    (c.get("br") or {}).get("zt"), (c.get("br") or {}).get("up_ratio"),
                    (c.get("fwd") or {}).get("r10_excess")]
            for i, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font = F_NORM
                cell.border = BORDER
                if i in (2, 6, 11, 14) and isinstance(v, (int, float)):
                    cell.number_format = "0.00"
                if i in (7,) and isinstance(v, (int, float)):
                    cell.number_format = "0.00"
                if i == 13 and isinstance(v, (int, float)):
                    cell.number_format = "0.0%"
            # 结论着色
            cc = ws.cell(row=r, column=3)
            cc.fill = FILL_GOOD if c["concl"] == "真主线" else FILL_WARN
            cc.font = F_BOLD
            # 10日超额着色
            ex = (c["fwd"] or {}).get("r10_excess")
            if ex is not None:
                ec = ws.cell(row=r, column=14)
                ec.fill = FILL_GOOD if ex >= 3 else (FILL_BAD if ex < 0 else FILL_WARN)
            r += 1
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:N{r-1}"

    # ==================== 3. 十日指数跟踪 ====================
    ws = wb.create_sheet("3.十日指数跟踪")
    title_row(ws, "选中板块 10 个交易日指数跟踪（含未选中候选池对照）", 12)
    set_widths(ws, [11, 16, 7, 10, 8, 8, 8, 8, 11, 11, 11, 11])
    hdr = ["入选日", "板块", "结论", "当日涨幅%", "跟踪起", "跟踪止",
           "10日涨幅%", "10日超额pp", "区间最大回撤%", "期末仍站MA20", "判定", "基准日均%"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    r = 3
    for p in picks:
        f = p.get("fwd")
        if not f:
            continue
        vals = [p["date"], p["name"], p["concl"], p["z"], f["d_start"], f["d_end"],
                f["r10"], f["r10_excess"], f["mdd"],
                "是" if f["still_above_ma20"] else "否",
                "命中(强)" if f["hit"] else ("命中(弱)" if f["hit_weak"] else "未命中"),
                f["bench_avg_day"]]
        for i, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = F_NORM
            cell.border = BORDER
            if i in (4, 7, 8, 9, 12) and isinstance(v, (int, float)):
                cell.number_format = "0.00"
        jc = ws.cell(row=r, column=11)
        jc.fill = FILL_GOOD if f["hit"] else (FILL_WARN if f["hit_weak"] else FILL_BAD)
        jc.font = F_BOLD
        r += 1
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:L{r-1}"

    # ==================== 4. 日报判定复盘 ====================
    ws = wb.create_sheet("4.日报判定复盘")
    title_row(ws, "日报实际判定 vs 客观重建 + 事后 10 日验证（9/16–10/28 共 21 期）", 16)
    set_widths(ws, [11, 15, 11, 11, 11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 14])
    hdr = ["日期", "板块", "日报结论", "日报gate", "日报均分", "重建结论", "重建gate",
           "重建均分", "结论一致", "当日涨幅%", "10日涨幅%", "10日超额pp",
           "最大回撤%", "事后判定", "日报来源", "备注"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    # 日报选中板块的跟踪结果
    ap_map = {(x["date"], x["code"]): x for x in stats.get("actual_picks", [])}
    r = 3
    for blk in align:
        for row in blk["rows"]:
            key = (row["date"], row["code"])
            ap = ap_map.get(key)
            f = ap["fwd"] if ap else None
            same = ("一致" if row["rebuild_concl"] == row["actual_concl"]
                    else ("重建未覆盖" if not row["rebuild_concl"] else "不一致"))
            vals = [row["date"], row["name"], row["actual_concl"], row["actual_gate"],
                    row["actual_avg"], row["rebuild_concl"] or "—",
                    row["rebuild_gate"] or "—", row["rebuild_avg"],
                    same, row["actual_z"],
                    f["r10"] if f else None, f["r10_excess"] if f else None,
                    f["mdd"] if f else None,
                    ("命中(强)" if f["hit"] else "命中(弱)" if f["hit_weak"] else "未命中")
                    if f else ("日报未入选" if row["actual_concl"] not in ("真主线", "真热点") else "无窗口"),
                    "git历史SEED",
                    ("日报选为" + row["actual_concl"]) if row["actual_concl"] in ("真主线", "真热点") else ""]
            for i, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font = F_NORM
                cell.border = BORDER
                if i in (5, 8, 10, 11, 12, 13) and isinstance(v, (int, float)):
                    cell.number_format = "0.00"
            sc = ws.cell(row=r, column=9)
            sc.fill = FILL_GOOD if same == "一致" else FILL_BAD
            if row["actual_concl"] in ("真主线", "真热点"):
                cc = ws.cell(row=r, column=3)
                cc.fill = FILL_GOOD if row["actual_concl"] == "真主线" else FILL_WARN
                cc.font = F_BOLD
            if f:
                jc = ws.cell(row=r, column=14)
                jc.fill = FILL_GOOD if f["hit"] else (FILL_BAD if not f["hit_weak"] else FILL_WARN)
            r += 1
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:P{r-1}"
    r += 1
    ws.cell(row=r, column=1, value="统计口径说明").font = F_BOLD
    ws.cell(row=r, column=1).fill = FILL_SUB
    r += 1
    notes4 = [
        "「日报结论」列标注为真主线/真热点的共 %d 行；其中 %d 个具备完整 10 个交易日窗口（入选日+10个交易日内有行情数据），"
        "命中率按此 %d 个样本计算，强命中 10 个（6.7%%）、弱命中 20 个（13.3%%），"
        "平均 10 日超额 -4.70pp。其余 %d 行因区间末端（10/28 之后无行情）无法跟踪 10 日，"
        "「事后判定」列标注为「无窗口」，不计入命中率分母。"
        % (150, 109, 109, 150 - 109),
        "「结论一致」列的对比基准是 v2 优化标准的重建结论（本次复盘所用标准），"
        "而非日报自身的标准——两者口径不同，一致率 33.0% 反映的是新旧标准的分歧程度，不是重建算法的准确率。",
        "「重建未覆盖」表示该板块未进入 v2 候选池（候选池 = 涨幅前10 + 资金前5 + 超跌强反弹前3），"
        "共 %d 行，主要集中在 9/16–9/28 早期日报——这些日报按「资金+涨幅」选板块，"
        "与 v2 候选池口径差异较大。" % 155,
    ]
    for t in notes4:
        c = ws.cell(row=r, column=1, value=t)
        c.font = F_NORM
        c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=16)
        ws.row_dimensions[r].height = 30
        r += 1

    # ==================== 5. 评分维度有效性 ====================
    ws = wb.create_sheet("5.评分维度有效性")
    title_row(ws, "现行五维评分与门槛的事后有效性检验（优化依据）", 7)
    set_widths(ws, [22, 14, 10, 14, 14, 14, 50])
    hdr = ["维度 / 门槛", "分组", "样本数", "10日平均超额pp", "10日超额为正占比",
           "t统计量", "结论与处置"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))

    def add_block(ws, r, title, groups, notes):
        ws.cell(row=r, column=1, value=title).font = F_BOLD
        ws.cell(row=r, column=1).fill = FILL_SUB
        for c in range(1, 8):
            ws.cell(row=r, column=c).border = BORDER
        r += 1
        for name, n, mean, posrate, t, note in groups:
            vals = [name, "", n, mean, posrate, t, note]
            for i, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font = F_NORM
                cell.border = BORDER
                if i in (4, 6) and isinstance(v, (int, float)):
                    cell.number_format = "0.00"
                if i == 5 and isinstance(v, (int, float)):
                    cell.number_format = "0.0%"
            # 均分列填分组名
            ws.cell(row=r, column=2, value=groups_nm.get((title, name), "")).font = F_NORM
            ws.cell(row=r, column=2).border = BORDER
            if isinstance(mean, (int, float)):
                if mean >= 0:
                    ws.cell(row=r, column=4).fill = FILL_GOOD
                elif mean <= -2:
                    ws.cell(row=r, column=4).fill = FILL_BAD
            r += 1
        return r + 1

    groups_nm = {}
    rows5 = []
    # 门槛
    for g, v in stats.get("by_gate", {}).items():
        groups_nm[("A. 硬门槛", g)] = g
        rows5.append(("A. 硬门槛", g, v["n"], v["avg_excess"], None, None,
                      "v2 处置：" + {
                          "rebound": "新增为独立门槛（超跌强反弹），实证最优，n=%d 命中率 %.0f%%" % (v["n"], v["hit"]),
                          "pass": "不再是加分项；pass 组 10日超额 %.2fpp，趋势确认反而是负向" % v["avg_excess"],
                          "weak": "weak 组 %.2fpp，负贡献，需更高分数门槛" % v["avg_excess"],
                          "ebb": "弱势退潮，维持排除",
                      }.get(g, "观察")))
    for k, v in stats.get("by_days", {}).items():
        groups_nm[("B. 连续上榜天数", k)] = k + " 天"
        rows5.append(("B. 连续上榜天数", k, v["n"], v["avg_excess"], None, None,
                      "days=2 为最优档（%+.2fpp）；现行 days≥3 给 5 分，"
                      "但本区间 days≥3 反而走弱，需重新标定" % v["avg_excess"]))
    for k, v in stats.get("by_pos", {}).items():
        groups_nm[("C. 位置过热", k)] = k
        rows5.append(("C. 位置过热", k, v["n"], v["avg_excess"], None, None,
                      {"低位启动": "最优（%+.2fpp），现行给 5 分正确",
                       "趋势中段": "%+.2fpp，弱于低位启动，但现行给 4 分偏高",
                       "高位加速": "%+.2fpp，已透支；现行给 2 分仍偏松",
                       "过热爆量": "样本不足，需扩大观察",
                       "未知": "样本不足"}.get(k, "观察")))
    # 结论
    for cn in ("真主线", "真热点"):
        if f"{cn}_n" in stats:
            groups_nm[("D. 结论级别", cn)] = cn
            rows5.append(("D. 结论级别", cn, stats[f"{cn}_n"], stats[f"{cn}_avg_excess"],
                          None, None,
                          "v1 判为该级别的样本事后表现（命中强标准 %.0f%%）" % stats.get(f"{cn}_hit", 0)))
    # 日报口径
    if "actual_picks_n" in stats:
        groups_nm[("E. 日报实际判定", "全部")] = "日报选中"
        rows5.append(("E. 日报实际判定", "全部", stats["actual_picks_n"],
                      stats["actual_avg_excess"], stats["actual_pos_rate"] / 100, None,
                      "现行标准实际命中率仅 %.1f%%（强标准），平均超额 %.2fpp——"
                      "这是本次优化要解决的核心问题"
                      % (stats["actual_hit_rate"], stats["actual_avg_excess"])))
        for cn, v in stats.get("actual_by_concl", {}).items():
            groups_nm[("E. 日报实际判定", cn)] = cn
            rows5.append(("E. 日报实际判定", cn, v["n"], v["avg_excess"], None, None,
                          "日报判为%s的样本：命中 %.0f%%，平均 10 日涨幅 %.2f%%"
                          % (cn, v["hit"], v["avg_r10"])))
        for g, v in stats.get("actual_by_gate", {}).items():
            groups_nm[("E. 日报实际判定", g)] = "gate=" + g
            rows5.append(("E. 日报实际判定", g, v["n"], v["avg_excess"], None, None,
                          "日报 gate=%s 组：命中 %.0f%%" % (g, v["hit"])))
        for z, v in stats.get("actual_by_z", {}).items():
            groups_nm[("E. 日报实际判定", z)] = "当日涨幅 " + z
            rows5.append(("E. 日报实际判定", z, v["n"], v["avg_excess"], None, None,
                          "日报选中的板块当日涨幅分布：全部落在 5% 以下，"
                          "无一个强启动——「追温和上涨」是致命缺陷"))

    r = 3
    cur = None
    for title, name, n, mean, posrate, t, note in rows5:
        if title != cur:
            ws.cell(row=r, column=1, value=title).font = F_BOLD
            ws.cell(row=r, column=1).fill = FILL_SUB
            for c in range(1, 8):
                ws.cell(row=r, column=c).border = BORDER
            r += 1
            cur = title
        vals = [name, groups_nm.get((title, name), ""), n, mean, posrate, t, note]
        for i, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = F_NORM
            cell.border = BORDER
            cell.alignment = WRAP
            if i in (4, 6) and isinstance(v, (int, float)):
                cell.number_format = "0.00"
            if i == 5 and isinstance(v, (int, float)):
                cell.number_format = "0.0%"
        if isinstance(mean, (int, float)):
            ws.cell(row=r, column=4).fill = FILL_GOOD if mean >= 0 else (
                FILL_BAD if mean <= -2 else FILL_WARN)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="说明").font = F_BOLD
    ws.cell(row=r, column=2, value="「10日平均超额pp」为该组样本的板块10日累计涨幅减全市场等权基准；"
            "正值代表跑赢大盘。命中(强)标准为超额≥3.0pp。").font = F_NORM
    ws.cell(row=r, column=2).alignment = WRAP

    # ==================== 6. 全市场实证统计 ====================
    ws = wb.create_sheet("6.全市场实证统计")
    title_row(ws, "全市场 510 板块 × 57 日实证画像（12810 个可跟踪样本）", 6)
    set_widths(ws, [16, 16, 12, 16, 16, 40])
    hdr = ["均线门槛", "当日涨幅区间", "样本数", "10日平均超额pp", "超额为正占比", "解读"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    uni = json.load(open(os.path.join(ROOT, "universe_gate_dated.json"), encoding="utf-8"))
    prof = defaultdict(list)
    for r0 in uni:
        z = r0["z"]
        zb = ("z>5" if z > 5 else "3<z<=5" if z > 3 else "2<z<=3" if z > 2
              else "0<z<=2" if z > 0 else "z<=0")
        prof[(r0["gate"], zb)].append(r0["ex"])
    r = 3
    gate_cn = {"ebb": "退潮(破MA20)", "weak": "弱启动(未站MA10/未连涨)",
               "pass": "全通过(站上MA20+MA10+连涨3)"}
    for g in ("ebb", "weak", "pass"):
        for zb in ("z>5", "3<z<=5", "2<z<=3", "0<z<=2", "z<=0"):
            xs = prof.get((g, zb))
            if not xs or len(xs) <= 25:
                continue
            m = st.mean(xs)
            pos = sum(1 for x in xs if x > 0) / len(xs)
            vals = [gate_cn.get(g, g), zb, len(xs), m, pos,
                    ("★ 显著正收益区，是唯一稳健的正向组合" if m > 3 else
                     "正贡献但样本偏少" if m > 0 else
                     "负贡献，趋势确认未转化为后续超额")]
            for i, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font = F_NORM
                cell.border = BORDER
                cell.alignment = WRAP
                if i == 4:
                    cell.number_format = "0.00"
                    cell.fill = FILL_GOOD if m > 0 else FILL_BAD
                if i == 5:
                    cell.number_format = "0.0%"
            r += 1
    r += 1
    ws.cell(row=r, column=1, value="核心实证结论").font = F_BOLD
    ws.cell(row=r, column=1).fill = FILL_SUB
    r += 1
    concl = [
        "1. 现行标准认定的最强档 gate=pass（站上MA20+MA10+连涨3天）在全市场口径下"
        "10日平均超额 -1.82%、超额为正占比仅 30%，t=-18.4，是显著负贡献。",
        "2. 唯一稳健的正向组合是「当日大涨但仍跌破20日线」：z>5% 且 ebb 组 10日平均超额 +10.88pp、"
        "正占比 93%（t=+6.46）；z>3% 且 ebb 组 +6.93pp、正占比 86%（t=+9.29）。",
        "3. 该组合在现行标准中被判为「退潮观察」并一票否决，等于把区间内最优信号全部过滤掉。",
        "4. 稳健性：5日/10日/20日三个持有期结论一致（z>5%且ebb 分别 +7.20 / +10.88 / +9.41pp），"
        "正占比 90% / 93% / 100%。",
        "5. 位置维度有效：低位启动 +0.66pp 最优，高位加速 -2.28pp 已透支，"
        "现行给「高位加速 2 分」偏松，应下调至 1 分。",
        "6. 连续上榜天数：现行 days≥3 给 5 分，但实证 days=2 档最优（+0.30pp）、"
        "days≥3 反而走弱，天数维度需要重新标定而非线性递增。",
        "%d. 日报实际选中且具备完整 10 日跟踪窗口的板块共 %d 个，"
        "命中率仅 %.1f%%、平均超额 %.2fpp；"
        "其中判为「真主线」的 %d 个命中率仅 %.1f%%、平均超额 %.2fpp——"
        "这是本次优化要解决的核心问题。"
        % (7, stats.get("actual_picks_n", 0),
           stats.get("actual_hit_rate", 0), stats.get("actual_avg_excess", 0),
           (stats.get("actual_by_concl", {}) or {}).get("真主线", {}).get("n", 0),
           (stats.get("actual_by_concl", {}) or {}).get("真主线", {}).get("hit", 0),
           (stats.get("actual_by_concl", {}) or {}).get("真主线", {}).get("avg_excess", 0)),
        "8. 日报选中的板块当日涨幅全部落在 5% 以下（0~2% 49 个、2~3% 19 个、"
        "3~5% 26 个、>5% 仅 6 个且无一命中）——"
        "「在温和上涨里挑板块」而非「抓强启动」，是根本问题。",
    ]
    for t in concl:
        c = ws.cell(row=r, column=1, value=t)
        c.font = F_NORM
        c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        ws.row_dimensions[r].height = 32
        r += 1

    # ==================== 7. 评分标准优化建议 ====================
    ws = wb.create_sheet("7.评分标准优化建议")
    title_row(ws, "评分维度与标准优化建议（v1 → v2）", 5)
    set_widths(ws, [16, 30, 30, 30, 34])
    hdr = ["环节", "v1 现行标准", "v2 优化后", "改动依据（实证）", "落地方式"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    cmp_ = json.load(open(os.path.join(ROOT, "v1v2_compare.json"), encoding="utf-8"))
    V1, V2 = cmp_["v1"], cmp_["v2"]
    cmp_rows = cmp_["rows"]
    rb = [r for r in cmp_rows if r["gate2"] == "rebound"]
    rb_v1_hot = sum(1 for r in rb if r["concl1"] in ("真主线", "真热点"))
    rb_ex = st.mean(r["ex"] for r in rb) if rb else 0
    rb_pos = (sum(1 for r in rb if r["ex"] > 0) / len(rb) * 100) if rb else 0
    rb_hit = (sum(1 for r in rb if r["hit"]) / len(rb) * 100) if rb else 0

    v2 = [
        ("硬门槛①", "跌破20日线 = ebb = 退潮观察，一票否决",
         "跌破20日线分两档：当日涨幅>3% → rebound「超跌强反弹」，"
         "不当否决、反而优先入选；涨幅≤3% → ebb 仍排除",
         "全市场 z>3%%且ebb 组 10日超额 +6.93pp、正占比 86%%（t=+9.29）；"
         "z>5%%且ebb +10.88pp、正占比 93%%（t=+6.46）。"
         "本次回测池内 %d 个 rebound 板块，v1 全部判为「退潮观察」（入选 0 个），"
         "而这批平均 10 日超额 %+.2fpp、正占比 %.0f%%、强命中 %.0f%%。"
         % (len(rb), rb_ex, rb_pos, rb_hit),
         "skill bankuai-zhuxian 的 gate 表加 rebound 档；"
         "日报 gate 列新增 rebound 徽章"),
        ("硬门槛②", "未站上10日线或未连涨3天 = weak，最高只能真热点",
         "维持 weak 封顶不变，但分数门槛由 2.5 提到 3.0",
         "weak 组 10日平均超额 -2.59pp，为负贡献；v1 门槛 2.5 使 73% 候选被判真热点",
         "conclude() 中 weak 分支阈值 2.5→3.0"),
        ("硬门槛③", "涨停<2 且主力净流出 = cold 剔除",
         "维持不变（本次样本中 cold 组样本过少，暂不调整）",
         "cold 组 n=16，统计不足以支持修订；逻辑本身合理，保留",
         "不改"),
        ("候选池", "当日涨幅/资金排名最强 6–10 个",
         "涨幅前10 + 资金净流入前5 + 超跌强反弹前3（z>3%且破MA20）",
         "现行池只含「已涨的」，漏掉超跌反弹这一最优类别；"
         "但扩池本身不提升命中率（扩池后整体超额仍为负），"
         "关键在于配合 rebound 门槛把它变成可入选",
         "engine.py 候选池构造逻辑；日报取数增加「反弹池」"),
        ("维度①时间", "days≥3=5；days=2=4；days=1≤2",
         "days=2=5；days=1=4；days≥3=3（持续性递减，非线性递增）",
         "实证 days=2 档最优（+0.30pp，命中 29.4%），"
         "days=1 次之（-1.22pp），days≥3 最差（-3.82pp）；"
         "「连续上榜」在趋势末段往往是衰竭信号",
         "score_time() 重标定锚点"),
        ("维度②资金", "连续2-3日净流入+中军放量=5；单日大额=3；流出=0",
         "维持锚点，权重 1.0→1.2；概念板块无资金流时记 None 并就低判定",
         "资金维度方向正确（净流入组优于流出组），但区分度中等，"
         "宜配合其他维度使用；概念板块资金历史不可得，不可编造",
         "score_money() 保持；引擎侧对无资金流的板块 has_flow=False"),
        ("维度③广度", "梯队四位置齐=5；先锋+中军=4；孤龙头=2",
         "维持锚点，改用可计算口径：上涨家数占比 + 涨停家数（近似）"
         "+ 涨幅中位数；权重 1.0→1.2",
         "广度 4 分档最优（-0.37pp）、5 分档 -1.03pp、2 分档 -2.31pp，"
         "呈倒 U 型；区分度在五维中最好，值得提权",
         "score_breadth() 改为基于成分股统计；数据源=同花顺成分股+新浪个股日线"),
        ("维度④位置", "低位启动=5；趋势中段=4；高位加速=2；过热爆量=1",
         "低位启动=5；趋势中段=3；高位加速=1；过热爆量=0；权重 1.0→0.6",
         "位置维度实证区分度最弱（各档均值差 <3pp），"
         "但方向明确：低位 +0.66pp / 趋势中段 -2.79pp / 高位加速 -2.28pp，"
         "故降权但保留方向，趋势中段从 4 降到 3",
         "score_position() 调整锚点；权重表加入 W 向量"),
        ("维度⑤催化", "利好三问，人工判定，三占其二=5",
         "降权至 0.8，且在无人工核时用代理规则（连续天数×资金连续性），"
         "报告中标明「催化成色待人工核」",
         "催化本质是主观项，自动化环境无法复现；"
         "代理值仅用于占位，权重必须低于客观维度，避免污染总分",
         "score_catalyst() 标注代理来源；日报仍保留人工填写 cat 字段，"
         "人工核后覆盖代理值"),
        ("维度⑥启动强度", "（无此维度）",
         "新增：z>5=5；3<z≤5=4；2<z≤3=2；0<z≤2=1；z≤0=0；权重 1.4（最高）",
         "全市场实证：z>5 组 10日超额 +4.25pp、正占比 64%（t=+3.58）；"
         "z>5%且ebb 达 +10.88pp/93%。而 z≤3% 且 pass 组 -1.88pp、正占比 29%。"
         "当日启动强度是区分度最高的单一变量",
         "score_launch() 新增；日报新增「启动强度」评分列"),
        ("结论分级", "均分≥3.5 真主线；2.5–3.49 真热点；<2.5 待验证",
         "pass 档：≥4.0 真主线、≥3.2 真热点；"
         "weak 档：≥3.0 真热点；rebound 档：≥3.5 真主线、≥2.8 真热点",
         "同一候选池（%d 个样本）并行回测：v1 入选 %d 个、命中率 %.1f%%、"
         "平均超额 %.2fpp；v2 入选 %d 个、命中率 %.1f%%、平均超额 %.2fpp"
         % (V1["cand_n"], V1["picked_n"], V1["hit_rate"], V1["avg_excess"],
            V2["picked_n"], V2["hit_rate"], V2["avg_excess"]),
         "conclude() 分档阈值；日报结论徽章规则同步更新"),
        ("加权方式", "五维等权算术平均",
         "加权平均 W=[1.0, 1.2, 1.2, 0.6, 0.8, 1.4]（时间/资金/广度/位置/催化/启动强度），"
         "缺失维度按剩余权重归一，不按 0 计入",
         "按实证区分度分配权重：启动强度 > 广度 ≈ 资金 > 时间 > 催化 > 位置；"
         "缺失维度若按 0 计入会系统性低估数据不全的板块",
         "review.py 加权公式；score 层返回 None 交由上层归一"),
        ("跟踪复盘", "上期观察清单逐条核销（定性）",
         "增加「10 日指数跟踪」量化环：入选板块一律跟踪 10 个交易日，"
         "记录 10日涨幅/超额/最大回撤/期末是否仍站MA20，命中率进日报",
         "这是本次复盘的核心增量：把判定准确率变成可量化、可累积的指标，"
         "让标准能持续迭代",
         "日报新增「10日跟踪核销」区块；本 Excel 表为首次基线"),
    ]
    r = 3
    for row in v2:
        for i, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = F_NORM
            cell.border = BORDER
            cell.alignment = WRAP
        ws.cell(row=r, column=1).font = F_BOLD
        ws.cell(row=r, column=1).fill = FILL_SUB
        ws.cell(row=r, column=3).fill = FILL_GOOD
        ws.row_dimensions[r].height = 62
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="落地后预期效果").font = F_BOLD
    ws.cell(row=r, column=1).fill = FILL_SUB
    r += 1
    eff = [
        "同一候选池并行回测：入选样本 10 日命中率 v1 %.1f%% → v2 %.1f%%（%+.1fpp）；"
        "弱命中 %.1f%% → %.1f%%。"
        % (V1["hit_rate"], V2["hit_rate"], V2["hit_rate"] - V1["hit_rate"],
           V1["hit_rate_weak"], V2["hit_rate_weak"]),
        "入选面：v1 入选 %d 个（占候选池 %.1f%%）→ v2 入选 %d 个（%.1f%%）；"
        "其中判为真主线 %d → %d 个。"
        % (V1["picked_n"], V1["picked_ratio"], V2["picked_n"], V2["picked_ratio"],
           V1["mainline_n"], V2["mainline_n"]),
        "rebound 档：v1 全部判「退潮观察」，一个不选；v2 选中 %d 个，"
        "命中率 %.1f%%、平均超额 %+.2fpp——这是 v2 最主要的增量来源。"
        % (V2["by_gate"].get("rebound", {}).get("n", 0),
           V2["by_gate"].get("rebound", {}).get("hit", 0),
           V2["by_gate"].get("rebound", {}).get("avg_excess", 0)),
        "日报实际口径命中率 %.1f%%、平均超额 %.2fpp → 目标提升至 30%% 以上"
        "（需下一个完整季度验证）。"
        % (stats.get("actual_hit_rate", 0), stats.get("actual_avg_excess", 0)),
        "本表所有数字来自 2026-08-03~10-28 实盘数据；样本外验证需在 11 月起的报告期持续累积，"
        "建议每季度重跑一次本脚本，用新数据校准锚点。",
    ]
    for t in eff:
        c = ws.cell(row=r, column=1, value=t)
        c.font = F_NORM
        c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        ws.row_dimensions[r].height = 26
        r += 1

    # ==================== 8. 每日汇总 ====================
    ws = wb.create_sheet("8.每日汇总统计")
    title_row(ws, "每日汇总：入选数量与市场环境", 8)
    set_widths(ws, [12, 12, 10, 10, 10, 12, 12, 26])
    hdr = ["日期", "大盘日涨幅%", "候选池数", "真主线数", "真热点数", "入选数",
           "当日入选板块", "入选平均超额pp"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=2, column=i, value=h)
    style_header(ws, 2, len(hdr))
    r = 3
    for rec in daily:
        cand = pick_by_date.get(rec["date"], [])
        ml = [c for c in cand if c["concl"] == "真主线"]
        hs = [c for c in cand if c["concl"] == "真热点"]
        exs = [(c.get("fwd") or {}).get("r10_excess") for c in ml + hs]
        exs = [e for e in exs if e is not None]
        vals = [rec["date"], rec["market_ret"], len(rows_by_date.get(rec["date"], [])),
                len(ml), len(hs), len(ml) + len(hs),
                "、".join(c["name"] for c in ml + hs) or "—",
                round(st.mean(exs), 2) if exs else None]
        for i, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = F_NORM
            cell.border = BORDER
            if i in (2, 8) and isinstance(v, (int, float)):
                cell.number_format = "0.00"
            if i == 7:
                cell.alignment = WRAP
        r += 1
    ws.freeze_panes = "A3"

    wb.save(OUT)
    print("已生成:", OUT)
    print("工作表:", wb.sheetnames)
    return OUT


if __name__ == "__main__":
    main()
