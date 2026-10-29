# -*- coding: utf-8 -*-
"""
板块轮动复盘核心引擎 v3（东财主池）
===================================
主数据源：东财 em_kline.json —— 510 个板块（126 行业 + 384 概念）日线，
          2026-06-01 ~ 2026-10-29，100% 覆盖 8/3~10/28
辅助数据源：
  - raw_flow_ind.json   东财行业板块逐日资金流（128 行业，7/1~10/28 全历史）
  - raw_flow_con.json   东财概念板块资金流（仅当日）
  - stock_kline.json    个股日线（4919 只，来自同花顺成分股）
  - ths_members.json    同花顺板块成分股（90 个行业板块）
输出：rebuild_daily.json / series_meta.json
"""
import json, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
START, END = "20260803", "20261028"


def main():
    em = json.load(open(os.path.join(ROOT, "em_kline.json"), encoding="utf-8"))
    flow_ind = json.load(open(os.path.join(ROOT, "raw_flow_ind.json"), encoding="utf-8"))
    flow_con = json.load(open(os.path.join(ROOT, "raw_flow_con.json"), encoding="utf-8"))
    stock = json.load(open(os.path.join(ROOT, "stock_kline.json"), encoding="utf-8"))
    members = json.load(open(os.path.join(ROOT, "ths_members.json"), encoding="utf-8"))

    # ---- 交易日轴（统一为 YYYYMMDD） ----
    alldates = sorted(set(d.replace("-", "") for v in em.values() for d in v["bars"]))
    alldates = [d for d in alldates if START <= d <= END]
    print(f"区间交易日 {len(alldates)}: {alldates[0]} ~ {alldates[-1]}")

    # ---- 板块序列 ----
    series = {}
    for bk, v in em.items():
        bars = v["bars"]
        ds = sorted(d.replace("-", "") for d in bars)
        series[bk] = {
            "name": v["name"], "type": None, "dates": ds,
            "closes": {d.replace("-", ""): bars[dd]["c"] for dd, d in
                       [(x, x.replace("-", "")) for x in bars]},
            "amts": {d.replace("-", ""): bars[dd].get("amt", 0) for dd, d in
                     [(x, x.replace("-", "")) for x in bars]},
        }

    # ---- 板块类型：行业（来自 flow_ind）/ 概念 ----
    ind_codes = set(x["BOARD_CODE"] for x in flow_ind)
    for bk in series:
        series[bk]["type"] = "industry" if bk in ind_codes else "concept"

    # ---- 资金流索引：(BK, YYYYMMDD) ----
    flowmap = {}
    for x in flow_ind:
        d = x["TRADE_DATE"][:10].replace("-", "")
        bk = x["BOARD_CODE"]
        if bk not in series:
            continue
        flowmap[(bk, d)] = {
            "netin": (x.get("NET_INFLOW") or 0) / 1e8,
            "super": (x.get("SUPERDEAL_NET") or 0) / 1e8,
            "big": (x.get("BIGDEAL_NET") or 0) / 1e8,
            "mid": (x.get("MIDDEAL_NET") or 0) / 1e8,
            "maxsec": x.get("MAX_NETINFLOW_SEC"),
        }
    for x in flow_con:
        d = x["TRADE_DATE"][:10].replace("-", "")
        bk = x["BOARD_CODE"]
        if bk not in series:
            continue
        flowmap.setdefault((bk, d), {
            "netin": (x.get("NET_INFLOW") or 0) / 1e8,
            "super": (x.get("SUPERDEAL_NET") or 0) / 1e8,
            "big": (x.get("BIGDEAL_NET") or 0) / 1e8,
            "mid": (x.get("MIDDEAL_NET") or 0) / 1e8,
            "maxsec": x.get("MAX_NETINFLOW_SEC"),
        })

    # ---- 同花顺成分股 → 东财板块名映射（广度用） ----
    # 东财板块名 → 同花顺 code（借 name_map.json 的反查）
    namemap = json.load(open(os.path.join(ROOT, "name_map.json"), encoding="utf-8"))
    ths_code_of_name = {}
    for nm_, m in namemap.items():
        ths_code_of_name.setdefault(m["name"], m["code"])
    em_name_of_ths = {}
    for nm_, m in namemap.items():
        em_name_of_ths.setdefault(m["code"], nm_)
    # 东财板块名 → 同花顺成分股 key
    stock_members = {}
    for bk, v in series.items():
        nm_ = v["name"]
        # 先精确，再用归一化
        cand = None
        for k, mm in namemap.items():
            if k == nm_:
                cand = mm["code"]; break
        if cand is None:
            import re
            n_norm = re.sub(r"[ⅠⅡⅢ]", "", nm_).replace("概念", "").replace("板块", "").replace("行业", "")
            for k, mm in namemap.items():
                k_norm = re.sub(r"[ⅠⅡⅢ]", "", k).replace("概念", "").replace("板块", "").replace("行业", "")
                if k_norm == n_norm:
                    cand = mm["code"]; break
        if cand and cand in members:
            stock_members[bk] = members[cand]["stocks"]

    # ---- 个股数据归一化 ----
    stock_norm = {s: {dd.replace("-", ""): v for dd, v in k.items()}
                  for s, k in stock.items()}

    def limit_threshold(code):
        if code.startswith(("30", "68")):
            return 19.8
        if code.startswith(("43", "83", "87", "88", "92")):
            return 29.8
        return 9.8

    def breadth(bk, date):
        sts = stock_members.get(bk)
        if not sts:
            return None
        ups = downs = flats = zt = 0
        pcts = []
        for s in sts:
            k = stock_norm.get(s)
            if not k or date not in k:
                continue
            p = k[date].get("pct")
            if p is None:
                continue
            pcts.append(p)
            if p > 0.05:
                ups += 1
            elif p < -0.05:
                downs += 1
            else:
                flats += 1
            if p >= limit_threshold(s):
                zt += 1
        n = len(pcts)
        if n == 0:
            return None
        pcts.sort()
        return {"n": n, "up": ups, "down": downs, "flat": flats, "zt": zt,
                "up_ratio": round(ups / n, 3),
                "med_pct": round(pcts[n // 2], 3),
                "mean_pct": round(sum(pcts) / n, 3)}

    # ---- 市场基准：全板块等权 ----
    market_ret = {}
    for d in alldates:
        rs = []
        for bk, s in series.items():
            c, ds = s["closes"], s["dates"]
            if d in c:
                i = ds.index(d)
                if i > 0:
                    rs.append((c[d] / c[ds[i - 1]] - 1) * 100)
        market_ret[d] = round(sum(rs) / len(rs), 4) if rs else 0.0

    # ---- 逐日重建 ----
    daily = []
    for d in alldates:
        rows = []
        for bk, s in series.items():
            c, ds = s["closes"], s["dates"]
            if d not in c:
                continue
            i = ds.index(d)
            if i < 1:
                continue
            chg = (c[d] / c[ds[i - 1]] - 1) * 100
            m20 = (sum(c[ds[i - 20 + k]] for k in range(20)) / 20) if i >= 20 else None
            m10 = (sum(c[ds[i - 10 + k]] for k in range(10)) / 10) if i >= 10 else None
            fl = flowmap.get((bk, d))
            amt = s["amts"].get(d, 0) or 0
            prev5 = [s["amts"].get(ds[i - k], 0) or 0 for k in range(1, 6)]
            vb = round(amt / (sum(prev5) / 5), 2) if sum(prev5) > 0 and amt > 0 else None
            hist20 = round((c[d] / c[ds[i - 20]] - 1) * 100, 2) if i >= 20 else None
            rows.append({
                "code": bk, "name": s["name"], "type": s["type"],
                "z": round(chg, 2),
                "ma20": (m20 is not None and c[d] >= m20),
                "ma10": (m10 is not None and c[d] >= m10),
                "up3": (i >= 3 and c[d] > c[ds[i - 1]] > c[ds[i - 2]] > c[ds[i - 3]]),
                "vb": vb, "hist20": hist20,
                "f": round(fl["netin"], 2) if fl else None,
                "fs": round(fl["super"], 2) if fl else None,
                "fb": round(fl["big"], 2) if fl else None,
                "fm": round(fl["mid"], 2) if fl else None,
                "has_flow": fl is not None,
                "maxsec": fl["maxsec"] if fl else None,
                "br": breadth(bk, d),
                "close": c[d], "i": i,
            })
        by_z = sorted(rows, key=lambda r: -r["z"])[:10]
        wf = [r for r in rows if r["has_flow"]]
        by_f = sorted(wf, key=lambda r: -(r["f"] or 0))[:5]
        by_rebound = sorted([r for r in rows if r["z"] > 3 and r["ma20"] is False],
                            key=lambda r: -r["z"])[:3]
        cand = {r["code"]: r for r in by_z}
        for r in by_f:
            cand.setdefault(r["code"], r)
        for r in by_rebound:
            cand.setdefault(r["code"], r)
        daily.append({"date": d, "market_ret": market_ret[d],
                      "candidates": list(cand.values()), "all_rows": len(rows)})

    # ---- 连续上榜天数 ----
    streak = defaultdict(int)
    for rec in daily:
        cur = {c["code"] for c in rec["candidates"]}
        for code in list(streak.keys()):
            if code not in cur:
                streak[code] = 0
        for c in rec["candidates"]:
            streak[c["code"]] += 1
            c["days"] = streak[c["code"]]

    # ---- 资金连续性 ----
    flow_by_code = defaultdict(list)
    for rec in daily:
        for c in rec["candidates"]:
            if c["has_flow"]:
                flow_by_code[c["code"]].append((rec["date"], c["f"]))
    fh = {k: dict(v) for k, v in flow_by_code.items()}
    for idx, rec in enumerate(daily):
        prevdates = [r["date"] for r in daily[:idx]][-3:]
        for c in rec["candidates"]:
            h = fh.get(c["code"], {})
            prev = [h.get(x) for x in prevdates]
            prev = [p for p in prev if p is not None]
            c["f_consec_pos"] = sum(1 for p in prev if p > 0)
            c["f_prev3"] = prev

    json.dump(daily, open(os.path.join(ROOT, "rebuild_daily.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    meta = {
        "alldates": alldates,
        "market_ret": market_ret,
        "series": {c: {"name": s["name"], "type": s["type"], "dates": s["dates"],
                       "closes": s["closes"]} for c, s in series.items()},
        "stock_members_n": len(stock_members),
    }
    json.dump(meta, open(os.path.join(ROOT, "series_meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    nb = sum(1 for r in daily for c in r["candidates"] if c.get("br"))
    print(f"重建完成：{len(daily)} 个交易日，候选池均值 "
          f"{sum(len(r['candidates']) for r in daily)/len(daily):.1f} 个/日，"
          f"有广度数据的候选 {nb} 个")


if __name__ == "__main__":
    main()
