# -*- coding: utf-8 -*-
"""
板块轮动复盘主流程
==================
1) 读 rebuild_daily.json（客观重建的候选池 + 指标）
2) 施加现行标准（bankuai-zhuxian v1）打分 → 结论
3) 对被判为「真主线/真热点」的板块做 10 个交易日指数跟踪
4) 与 git 历史日报的实际判定比对 → 准确率复盘
5) 输出 review_full.json
"""
import json, os, statistics as st
from collections import defaultdict
from score import (calc_gate, score_time, score_money, score_breadth,
                   score_position, score_catalyst, score_launch, conclude,
                   forward_stats, FWD)

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    daily = json.load(open(os.path.join(ROOT, "rebuild_daily.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    actual = json.load(open(os.path.join(ROOT, "actual_reports.json"), encoding="utf-8"))
    namemap = json.load(open(os.path.join(ROOT, "name_map.json"), encoding="utf-8"))

    alldates = meta["alldates"]
    series = meta["series"]
    market_ret = meta["market_ret"]
    date_index = {d: i for i, d in enumerate(alldates)}

    # ---------------- 逐日评分 ----------------
    picks = []          # 选中的（真主线/真热点）
    all_rows = []       # 全部候选池行（用于维度有效性统计）
    daily_summary = []

    for rec in daily:
        d = rec["date"]
        di = date_index[d]
        for c in rec["candidates"]:
            gate, gmsg, ma20, ma10, up3 = calc_gate(c)
            c["gate"], c["gateMsg"] = gate, gmsg
            s_time = score_time(c.get("days", 1))
            s_money, m_money = score_money(c, None)
            s_br, m_br = score_breadth(c)
            s_pos, m_pos = score_position(c)
            s_cat, m_cat = score_catalyst(c)
            s_launch, m_launch = score_launch(c)
            dims = [s_time, s_money, s_br, s_pos, s_cat, s_launch]
            known = [x for x in dims if x is not None]
            # v2 权重：实证显示「启动强度」「广度」有区分度，
            # 「位置」几乎无区分度（各档均值差 <1pp），故降权；
            # 「催化」为代理值，降权；时间/资金为主线必要条件，保权重。
            W = [1.0, 1.2, 1.2, 0.6, 0.8, 1.4]
            wk = [w for w, x in zip(W, dims) if x is not None]
            kv = [x for x in dims if x is not None]
            avg = round(sum(w * v for w, v in zip(wk, kv)) / sum(wk), 2) if kv else 0.0
            avg_raw = round(sum(kv) / len(kv), 2) if kv else 0.0
            concl = conclude(gate, avg)
            c["s"] = dims
            c["avg"] = avg
            c["avg_raw"] = avg_raw
            c["concl"] = concl
            c["msgs"] = {"money": m_money, "breadth": m_br,
                         "position": m_pos, "catalyst": m_cat, "launch": m_launch}
            c["pos"] = m_pos if isinstance(m_pos, str) and m_pos in (
                "低位启动", "趋势中段", "高位加速", "过热爆量") else "未知"
            # 10 日跟踪
            c["fwd"] = forward_stats(series, c["code"], di, alldates, market_ret)
            all_rows.append({"date": d, **{k: c[k] for k in (
                "code", "name", "type", "z", "f", "vb", "days", "gate", "s",
                "avg", "concl", "pos", "ma20", "ma10", "up3")},
                "fwd": c["fwd"], "br": c.get("br")})
            if concl in ("真主线", "真热点"):
                picks.append({"date": d, **{k: c[k] for k in (
                    "code", "name", "type", "z", "f", "vb", "days", "gate",
                    "s", "avg", "concl", "pos", "ma20", "ma10", "up3")},
                    "fwd": c["fwd"], "br": c.get("br"),
                    "msgs": c["msgs"]})

        cnt = defaultdict(int)
        for c in rec["candidates"]:
            cnt[c["concl"]] += 1
        daily_summary.append({
            "date": d, "market_ret": rec["market_ret"],
            "cand_n": len(rec["candidates"]),
            "concl": dict(cnt),
            "mainline": [c["name"] for c in rec["candidates"] if c["concl"] == "真主线"],
            "hotspot": [c["name"] for c in rec["candidates"] if c["concl"] == "真热点"],
        })

    # ---------------- 与日报实际判定比对 ----------------
    # 东财 BK 码 → 板块名 → 日报名对齐
    meta_all = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    bk_name = {bk: s["name"] for bk, s in meta_all["series"].items()}
    # 日报名 → BK 码：用 name_map 的「东财名 → 同花顺code」再反查东财BK
    # 直接用东财名集合做匹配（日报用申万二级名，东财行业板块同名）
    import re

    def norm(s):
        return re.sub(r"[ⅠⅡⅢ]", "", (s or "").strip()).replace("概念", "").replace("板块", "").replace("行业", "")

    # 东财板块名 → BK（优先行业）
    name2bks = {}
    for bk, nm_ in bk_name.items():
        name2bks.setdefault(nm_, []).append(bk)
    # 用 flow_ind 的 行业名→BK 作为权威
    flow_ind = json.load(open(os.path.join(ROOT, "raw_flow_ind.json"), encoding="utf-8"))
    for x in flow_ind:
        name2bks.setdefault(x["BOARD_NAME"], []).insert(0, x["BOARD_CODE"])

    def find_bk(name):
        if name in name2bks:
            return name2bks[name][0]
        n = norm(name)
        for nm_, bks in name2bks.items():
            if norm(nm_) == n:
                return bks[0]
        # 概念：东财概念名带"概念"后缀，日报名可能不带
        for nm_, bks in name2bks.items():
            if norm(nm_) == n or norm(nm_).replace("概念", "") == n:
                return bks[0]
        return None

    actual_by_date = {}
    for d, v in actual.items():
        dd = d.replace("-", "")
        recs = []
        for r in v["records"]:
            if not r.get("n"):
                continue
            nm_ = r["n"]
            bk = find_bk(nm_)
            s = r.get("s") or []
            avg = round(sum(s) / len(s), 2) if s else None
            g = r.get("gate")
            concl = None
            if g == "ebb":
                concl = "退潮观察"
            elif g == "cold":
                concl = "未入围"
            elif g == "weak":
                concl = "真热点" if (avg or 0) >= 2.5 else "待验证"
            elif g == "pass" and avg is not None:
                concl = "真主线" if avg >= 3.5 else ("真热点" if avg >= 2.5 else "待验证")
            elif g is None and avg is not None:
                # 早期日报（9/16~9/28）尚未引入 gate 字段，仅有五维分
                # 按当时的口径：均分≥3.5 主线；2.5-3.49 真热点；<2.5 待验证
                concl = ("真主线" if avg >= 3.5 else
                         ("真热点" if avg >= 2.5 else "待验证"))
                g = "(早期无gate字段)"
            recs.append({"name": nm_, "code": bk, "gate": g, "s": s,
                         "avg": avg, "concl": concl,
                         "z": r.get("z"), "f": r.get("f"),
                         "days": r.get("days"), "pos": r.get("pos")})
        actual_by_date[dd] = recs

    # 对齐：每日日报结论 vs 重建结论（按 BK 码匹配）
    align = []
    for d in alldates:
        if d not in actual_by_date:
            continue
        rec = next((r for r in daily if r["date"] == d), None)
        if not rec:
            continue
        rb = {c["code"]: c for c in rec["candidates"]}
        rows = []
        for ar in actual_by_date[d]:
            rbc = rb.get(ar["code"]) if ar["code"] else None
            if rbc:
                if rbc["concl"] == ar["concl"]:
                    same = "一致"
                else:
                    same = "不一致"
            else:
                same = "重建未覆盖"
            rows.append({
                "date": d, "name": ar["name"], "code": ar["code"],
                "actual_concl": ar["concl"], "actual_gate": ar["gate"],
                "actual_avg": ar["avg"], "actual_s": ar["s"],
                "actual_z": ar["z"], "actual_f": ar["f"],
                "actual_days": ar["days"], "actual_pos": ar["pos"],
                "rebuild_concl": rbc["concl"] if rbc else None,
                "rebuild_gate": rbc["gate"] if rbc else None,
                "rebuild_avg": rbc["avg"] if rbc else None,
                "rebuild_s": rbc["s"] if rbc else None,
                "rebuild_z": rbc["z"] if rbc else None,
            })
        align.append({"date": d, "rows": rows})

    # ---------------- 统计 ----------------
    stats = summarize(picks, all_rows, align, daily_summary)

    out = {
        "daily_summary": daily_summary,
        "picks": picks,
        "all_rows": all_rows,
        "align": align,
        "stats": stats,
    }
    json.dump(out, open(os.path.join(ROOT, "review_full.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print_pick_stats(stats)
    return out


def summarize(picks, all_rows, align, daily_summary):
    S = {}
    # 选中样本的 10 日跟踪表现
    fwd = [p["fwd"] for p in picks if p.get("fwd")]
    S["picks_total"] = len(picks)
    S["picks_with_fwd"] = len(fwd)
    S["mainline_n"] = sum(1 for p in picks if p["concl"] == "真主线")
    S["hotspot_n"] = sum(1 for p in picks if p["concl"] == "真热点")
    if fwd:
        S["hit_rate"] = round(sum(1 for f in fwd if f["hit"]) / len(fwd) * 100, 1)
        S["hit_rate_weak"] = round(sum(1 for f in fwd if f["hit_weak"]) / len(fwd) * 100, 1)
        S["avg_r10"] = round(st.mean(f["r10"] for f in fwd), 2)
        S["avg_r10_excess"] = round(st.mean(f["r10_excess"] for f in fwd), 2)
        S["median_r10"] = round(st.median(f["r10"] for f in fwd), 2)
        S["avg_mdd"] = round(st.mean(f["mdd"] for f in fwd), 2)
        S["stay_ma20_rate"] = round(
            sum(1 for f in fwd if f["still_above_ma20"]) / len(fwd) * 100, 1)
        # 分结论
        for cn in ("真主线", "真热点"):
            sub = [p["fwd"] for p in picks if p["concl"] == cn and p.get("fwd")]
            if sub:
                S[f"{cn}_hit"] = round(sum(1 for f in sub if f["hit"]) / len(sub) * 100, 1)
                S[f"{cn}_avg_excess"] = round(st.mean(f["r10_excess"] for f in sub), 2)
                S[f"{cn}_n"] = len(sub)
    # 按 gate 分
    byg = defaultdict(list)
    for p in picks:
        if p.get("fwd"):
            byg[p["gate"]].append(p["fwd"])
    S["by_gate"] = {g: {"n": len(v),
                        "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                        "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2)}
                    for g, v in byg.items()}
    # 按 days 分（时间持续性维度有效性）
    byd = defaultdict(list)
    for p in picks:
        if p.get("fwd"):
            byd[min(p["days"], 4)].append(p["fwd"])
    S["by_days"] = {str(k): {"n": len(v),
                             "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                             "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2)}
                     for k, v in sorted(byd.items())}
    # 按位置分
    byp = defaultdict(list)
    for p in picks:
        if p.get("fwd"):
            byp[p["pos"]].append(p["fwd"])
    S["by_pos"] = {k: {"n": len(v),
                       "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                       "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2)}
                   for k, v in byp.items()}
    # 每日覆盖
    S["days_with_mainline"] = sum(1 for d in daily_summary if d["mainline"])
    S["days_with_hotspot"] = sum(1 for d in daily_summary if d["hotspot"])
    S["days_total"] = len(daily_summary)
    # 重建 vs 日报 一致率
    tot = hit = 0
    gate_tot = gate_hit = 0
    cover = 0
    for blk in align:
        for r in blk["rows"]:
            if r["rebuild_concl"] and r["actual_concl"]:
                cover += 1
                tot += 1
                if r["rebuild_concl"] == r["actual_concl"]:
                    hit += 1
                gate_tot += 1
                if r["rebuild_gate"] == r["actual_gate"]:
                    gate_hit += 1
    S["align_days"] = len(align)
    S["align_rows"] = tot
    S["align_covered"] = cover
    S["align_concl_match"] = round(hit / tot * 100, 1) if tot else None
    S["align_gate_match"] = round(gate_hit / gate_tot * 100, 1) if gate_tot else None
    # 日报选中的板块，事后 10 日表现（日报口径的真实准确率）——核心指标
    alld = [r["date"] for r in daily_summary]
    aidx = {d: i for i, d in enumerate(alld)}
    aj = []
    miss_bk = 0
    for blk in align:
        d = blk["date"]
        di = aidx.get(d)
        if di is None:
            continue
        for r in blk["rows"]:
            if r["actual_concl"] in ("真主线", "真热点"):
                if not r["code"]:
                    miss_bk += 1
                    continue
                f = forward_stats(meta_series(), r["code"], di, meta_dates(), meta_mkt())
                if f:
                    aj.append({"date": d, "name": r["name"], "code": r["code"],
                               "concl": r["actual_concl"], "gate": r["actual_gate"],
                               "z": r["actual_z"], "f": r["actual_f"],
                               "days": r["actual_days"], "pos": r["actual_pos"],
                               "fwd": f})
    S["actual_miss_bk"] = miss_bk
    if aj:
        S["actual_picks_n"] = len(aj)
        S["actual_hit_rate"] = round(sum(1 for x in aj if x["fwd"]["hit"]) / len(aj) * 100, 1)
        S["actual_hit_rate_weak"] = round(
            sum(1 for x in aj if x["fwd"]["hit_weak"]) / len(aj) * 100, 1)
        S["actual_avg_r10"] = round(st.mean(x["fwd"]["r10"] for x in aj), 2)
        S["actual_avg_excess"] = round(st.mean(x["fwd"]["r10_excess"] for x in aj), 2)
        S["actual_median_r10"] = round(st.median(x["fwd"]["r10"] for x in aj), 2)
        S["actual_pos_rate"] = round(
            sum(1 for x in aj if x["fwd"]["r10"] > 0) / len(aj) * 100, 1)
        S["actual_stay_ma20"] = round(
            sum(1 for x in aj if x["fwd"]["still_above_ma20"]) / len(aj) * 100, 1)
        byc = defaultdict(list)
        for x in aj:
            byc[x["concl"]].append(x["fwd"])
        S["actual_by_concl"] = {k: {"n": len(v),
                                    "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                                    "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2),
                                    "avg_r10": round(st.mean(f["r10"] for f in v), 2)}
                                for k, v in byc.items()}
        byg = defaultdict(list)
        for x in aj:
            byg[x["gate"]].append(x["fwd"])
        S["actual_by_gate"] = {k: {"n": len(v),
                                   "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                                   "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2)}
                               for k, v in byg.items()}
        byz = defaultdict(list)
        for x in aj:
            z = x["z"]
            key = "z>5%" if (z or 0) > 5 else ("3~5%" if (z or 0) > 3 else
                   ("2~3%" if (z or 0) > 2 else ("0~2%" if (z or 0) > 0 else "z<=0")))
            byz[key].append(x["fwd"])
        S["actual_by_z"] = {k: {"n": len(v),
                                "hit": round(sum(1 for f in v if f["hit"]) / len(v) * 100, 1),
                                "avg_excess": round(st.mean(f["r10_excess"] for f in v), 2)}
                            for k, v in byz.items()}
    S["actual_picks"] = aj
    return S


# 全局缓存，避免重复加载
_META = None


def meta_series():
    global _META
    if _META is None:
        _META = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    return _META["series"]


def meta_dates():
    global _META
    if _META is None:
        _META = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    return _META["alldates"]


def meta_mkt():
    global _META
    if _META is None:
        _META = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    return _META["market_ret"]


def print_pick_stats(S):
    print("=" * 60)
    print(f"选中总数 {S['picks_total']}（真主线 {S['mainline_n']} / 真热点 {S['hotspot_n']}）")
    print(f"有完整10日窗口的样本 {S['picks_with_fwd']}")
    print(f"命中���(超额≥3pp) {S.get('hit_rate')}%  弱命中(超额≥0) {S.get('hit_rate_weak')}%")
    print(f"10日平均涨幅 {S.get('avg_r10')}%  平均超额 {S.get('avg_r10_excess')}%")
    print(f"10日平均最大回撤 {S.get('avg_mdd')}%  仍站上MA20比例 {S.get('stay_ma20_rate')}%")
    print(f"有主线的交易日 {S['days_with_mainline']}/{S['days_total']}，"
          f"有热点 {S['days_with_hotspot']}/{S['days_total']}")
    print("-" * 60)
    print(f"与日报对齐 {S.get('align_days')} 天 / {S.get('align_rows')} 行，"
          f"结论一致率 {S.get('align_concl_match')}%  门槛一致率 {S.get('align_gate_match')}%")
    if "actual_picks_n" in S:
        print(f"日报口径选中 {S['actual_picks_n']} 个，命中率 {S.get('actual_hit_rate')}%  "
              f"平均超额 {S.get('actual_avg_excess')}%")
    print("-" * 60)
    print("按 gate:", json.dumps(S.get("by_gate", {}), ensure_ascii=False))
    print("按 days:", json.dumps(S.get("by_days", {}), ensure_ascii=False))
    print("按位置:", json.dumps(S.get("by_pos", {}), ensure_ascii=False))
    print("=" * 60)


if __name__ == "__main__":
    main()
