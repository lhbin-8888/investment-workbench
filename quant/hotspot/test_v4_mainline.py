# -*- coding: utf-8 -*-
"""V4.1 主线评选修复聚焦验证（不依赖 PTrade / 行情）。

复现回测暴露的结构性缺陷：旧版按归一强度排序，1 成分封板板块（zt_rate=1 → 强度≈90~100）
永远霸榜，但其唯一标的已封板、在 _pick_candidates 中被剔除 → 永远 0 候选。
验证：
  A. 1 成分封板板块不再进入主线；
  B. 多成分、有封板龙头 + 足够跟涨标的的板块进入主线，并产出 >= MIN_MAIN_FOLLOWERS 候选；
  C. 退化复现：50 个 1 成分封板板块 + 1 个多成分热点，热点必须当选。
退出码 0 = 全部通过。
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "hotspot_trader_v4_ptrade.py")

fails = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS  {}".format(name))
    else:
        print("  FAIL  {}  {}".format(name, detail))
        fails.append(name)


def load():
    src = open(V4, encoding="utf-8").read()
    ns = {"__name__": "__v4test__"}
    ns["log"] = types.SimpleNamespace(info=lambda *a: None,
                                       warning=lambda *a: None,
                                       error=lambda *a: None)
    ns["get_positions"] = lambda: {}
    ns["get_position"] = lambda: None
    ns["get_history"] = lambda *a, **k: {}
    ns["get_current_data"] = lambda *a, **k: {}
    exec(compile(src, V4, "exec"), ns)
    return ns


def feat(code, pct, zt_line, above20=True, lianban=0, vol_ratio=1.0, amt=5e8):
    return {"code": code, "pct": pct, "lianban": lianban,
            "vol_ratio": vol_ratio, "above20": above20,
            "amt": amt, "close": 10.0, "zt_line": zt_line, "is_st": False}


def main():
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    ns["REQUIRE_NO_ST"] = False  # 跳过 ST 查名，聚焦评选逻辑

    build = ns["build_sector_signal"]
    classify = ns["classify_stage"]
    pick = ns["_main_line_groups"]
    cand = ns["_pick_candidates"]

    # ---- 构造板块 ----
    # 1) 单成分封板板块（回测每天霸榜的"主线"退化形态）
    one_code = "000001"
    g.sector_codes = {"微盘精选": [one_code]}
    g.feat = {one_code: feat(one_code, 10.0, 10.0, lianban=3)}

    onesig = build("微盘精选", [one_code])
    onesig["stage"] = classify(onesig, [])

    # 2) 多成分热点：60 成分，5 封板龙头 + 55 跟涨（均 +5%，站上20线）
    robot = ["30{:04d}".format(i) for i in range(60)]
    g.sector_codes["机器人概念"] = robot
    g.feat = {}
    leaders = []
    for i in range(5):
        c = robot[i]
        g.feat[c] = feat(c, 20.0, 20.0, lianban=2)  # 创业/科创 20% 板
        leaders.append(c)
    for i in range(5, 60):
        c = robot[i]
        g.feat[c] = feat(c, 5.0, 20.0, vol_ratio=1.2)  # 跟涨 +5%

    rsig = build("机器人概念", robot)
    rsig["stage"] = classify(rsig, [])

    g.prev_signal = {}
    g.sector_map = {"industry": {}, "concept": {}}
    g.cool_down = set()

    print("== A. 单成分封板板块不应进入主线 ==")
    mains_a = pick([onesig, rsig])
    ok(onesig not in mains_a, "单成分封板板块被排除",
       "mains={}".format([m["sector"] for m in mains_a]))
    ok(rsig in mains_a, "多成分热点进入主线")

    print("== B. 多成分热点应产出 >= MIN_MAIN_FOLLOWERS 候选，且不含封板龙头 ==")
    g.pending_buy = None
    cands_b = cand(mains_a)
    ok(len(cands_b) >= ns["MIN_MAIN_FOLLOWERS"],
       "候选数 >= MIN_MAIN_FOLLOWERS({})".format(ns["MIN_MAIN_FOLLOWERS"]),
       "got {}".format(len(cands_b)))
    ok(all(c["code"] not in leaders for c in cands_b),
       "候选不含已封板龙头", "leaders 仍出现")
    ok(all(c["pct"] < c["zt_line"] for c in cands_b),
       "候选均为未封板标的")

    print("== C. 退化复现：50 个 1 成分封板板块 + 1 个多成分热点 ==")
    many = [onesig]
    g.sector_codes = {"微盘精选": [one_code]}
    g.feat = {one_code: feat(one_code, 10.0, 10.0, lianban=3)}
    for i in range(50):
        nm = "退化板{:02d}".format(i)
        cc = "{:06d}".format(100000 + i)
        g.sector_codes[nm] = [cc]
        g.feat[cc] = feat(cc, 10.0, 10.0, lianban=1)
        s = build(nm, [cc])
        s["stage"] = classify(s, [])
        many.append(s)
    # 重新并入热点
    g.sector_codes["机器人概念"] = robot
    for c in robot:
        if c not in g.feat:
            g.feat[c] = feat(c, 5.0 if c not in leaders else 20.0,
                             20.0, vol_ratio=1.2)
    many.append(rsig)
    mains_c = pick(many)
    ok(rsig in mains_c, "海量 1 成分封板噪声中，多成分热点仍当选",
       "mains={}".format([m["sector"] for m in mains_c]))
    ok("微盘精选" not in [m["sector"] for m in mains_c], "单成分板未混入主线")
    ok(len([m for m in mains_c if m is rsig]) == 1, "热点唯一当选（无重复）")

    print()
    if fails:
        print("结果: 失败 {} 项 -> {}".format(len(fails), fails))
        sys.exit(1)
    print("结果: 全部通过 (A/B/C)")


if __name__ == "__main__":
    main()
