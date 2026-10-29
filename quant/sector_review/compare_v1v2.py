# -*- coding: utf-8 -*-
"""
v1 / v2 标准并行回测对比
=========================
在同一份重建数据上，分别用 v1（五维等权 + ebb 一票否决）与 v2（六维加权 + rebound）
跑一遍，输出可比的命中率/选中数指标，避免 Excel 里出现口径不一致的硬编码数字。
输出：v1v2_compare.json
"""
import json, os, statistics as st
from collections import defaultdict
from score import (calc_gate, score_time, score_money, score_breadth,
                   score_position, score_catalyst, score_launch, forward_stats)

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------- v1 原始实现（照抄 skill v1 口径，不做任何美化） ----------
def v1_gate(r):
    ma20, ma10, up3 = r["ma20"], r["ma10"], r["up3"]
    if ma20 is False:
        return "ebb", "跌破20日线"
    if r.get("br") is not None and r["br"]["zt"] < 2 and (r["f"] or 0) < 0:
        return "cold", "涨停<2且净流出"
    if not (ma10 and up3):
        return "weak", "未过10日线或连涨3天"
    return "pass", "全部通过"


def v1_conclude(gate, avg):
    if gate == "ebb":
        return "退潮观察"
    if gate == "cold":
        return "未入围"
    if gate == "weak":
        return "真热点" if avg >= 2.5 else "待验证"
    if avg >= 3.5:
        return "真主线"
    if avg >= 2.5:
        return "真热点"
    return "待验证"


def v1_score(r):
    """v1：五维等权算术平均。
    缺失维度处理：skill v1 原文未定义。按「判定就低不就高」原则记 0 分
    （缺失即无证据，不给中性分），此处理对 v1 更保守，是刻意的不利设定。
    """
    s_time = score_time(r.get("days", 1))
    s_money, _ = score_money(r, None)
    s_br, _ = score_breadth(r)
    s_pos, m_pos = score_position(r)
    s_cat, _ = score_catalyst(r)
    dims = [s_time, s_money, s_br, s_pos, s_cat]
    dims = [0 if x is None else x for x in dims]
    avg = round(sum(dims) / len(dims), 2)
    return dims, avg, m_pos


def v2_score(r):
    s_time = score_time(r.get("days", 1))
    s_money, _ = score_money(r, None)
    s_br, _ = score_breadth(r)
    s_pos, m_pos = score_position(r)
    s_cat, _ = score_catalyst(r)
    s_launch, _ = score_launch(r)
    dims = [s_time, s_money, s_br, s_pos, s_cat, s_launch]
    W = [1.0, 1.2, 1.2, 0.6, 0.8, 1.4]
    wk = [w for w, x in zip(W, dims) if x is not None]
    kv = [x for x in dims if x is not None]
    avg = round(sum(w * v for w, v in zip(wk, kv)) / sum(wk), 2) if kv else 0.0
    return dims, avg, m_pos


def main():
    daily = json.load(open(os.path.join(ROOT, "rebuild_daily.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(ROOT, "series_meta.json"), encoding="utf-8"))
    alldates = meta["alldates"]
    series = meta["series"]
    mkt = meta["market_ret"]
    aidx = {d: i for i, d in enumerate(alldates)}

    res = {"v1": [], "v2": []}
    for rec in daily:
        d = rec["date"]
        di = aidx[d]
        for r in rec["candidates"]:
            f = forward_stats(series, r["code"], di, alldates, mkt)
            if not f:
                continue
            # v1
            g1, _ = v1_gate(r)
            _, a1, _ = v1_score(r)
            c1 = v1_conclude(g1, a1)
            # v2（复用 score.calc_gate / conclude）
            from score import calc_gate, conclude
            g2 = calc_gate(r)[0]
            _, a2, _ = v2_score(r)
            c2 = conclude(g2, a2)
            base = {"date": d, "name": r["name"], "type": r["type"],
                    "z": r["z"], "gate1": g1, "avg1": a1, "concl1": c1,
                    "gate2": g2, "avg2": a2, "concl2": c2,
                    "r10": f["r10"], "ex": f["r10_excess"],
                    "hit": f["hit"], "hit_weak": f["hit_weak"]}
            res["v1"].append(base)
            res["v2"].append(base)

    def summ(rows, ck, gk):
        allrows = rows
        picks = [r for r in rows if r[ck] in ("真主线", "真热点")]
        hits = [r for r in picks if r["hit"]]
        weak = [r for r in picks if r["hit_weak"]]
        return {
            "cand_n": len(allrows),
            "picked_n": len(picks),
            "picked_ratio": round(len(picks) / len(allrows) * 100, 1) if allrows else 0,
            "mainline_n": sum(1 for r in picks if r[ck] == "真主线"),
            "hotspot_n": sum(1 for r in picks if r[ck] == "真热点"),
            "hit_rate": round(len(hits) / len(picks) * 100, 1) if picks else 0,
            "hit_rate_weak": round(len(weak) / len(picks) * 100, 1) if picks else 0,
            "avg_excess": round(st.mean(r["ex"] for r in picks), 2) if picks else 0,
            "avg_r10": round(st.mean(r["r10"] for r in picks), 2) if picks else 0,
            "by_gate": {g: {"n": sum(1 for r in picks if r[gk] == g),
                            "hit": round(sum(1 for r in picks if r[gk] == g and r["hit"])
                                        / max(1, sum(1 for r in picks if r[gk] == g)) * 100, 1),
                            "avg_excess": round(st.mean([r["ex"] for r in picks if r[gk] == g]), 2)
                            if any(r[gk] == g for r in picks) else 0}
                        for g in sorted(set(r[gk] for r in picks))},
        }

    out = {
        "v1": summ(res["v1"], "concl1", "gate1"),
        "v2": summ(res["v2"], "concl2", "gate2"),
        "rows": res["v2"],
    }
    json.dump(out, open(os.path.join(ROOT, "v1v2_compare.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    for k in ("v1", "v2"):
        s = out[k]
        print(f"=== {k} ===")
        print(f"  候选池 {s['cand_n']} → 入选 {s['picked_n']}（占比 {s['picked_ratio']}%）"
              f"  真主线 {s['mainline_n']} / 真热点 {s['hotspot_n']}")
        print(f"  命中率(强) {s['hit_rate']}%  (弱) {s['hit_rate_weak']}%")
        print(f"  10日平均涨幅 {s['avg_r10']}%  平均超额 {s['avg_excess']}pp")
        print(f"  按gate: {json.dumps(s['by_gate'], ensure_ascii=False)}")
        print()


if __name__ == "__main__":
    main()
