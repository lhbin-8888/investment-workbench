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
import datetime

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
    # A/B/C 验证 V4.1 主线评选修复，与 V4.5「仅扩散可买」入口改造无关，
    # 故临时关闭 REQUIRE_DIFFUSE_ENTRY，由 test_v45_entry_ledger 专门验证扩散门。
    ns["REQUIRE_DIFFUSE_ENTRY"] = False

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


class _Tick(object):
    """模拟 get_current_data() 返回的个股行情对象。"""

    def __init__(self, lp, pc):
        self.last_price = lp
        self.pre_close = pc


def _ctx(dt):
    return types.SimpleNamespace(current_dt=dt)


def _backtest_fetch(codes, n, drop_today=False):
    """模拟回测 10:00：日 K 只到 T-1，无当日 bar（today=2026-09-16）。"""
    out = {}
    for c in codes:
        out[c] = [
            ("2026-09-14", 9.80, 9.90, 9.70, 1e6, 9.82),   # T-2
            ("2026-09-15", 10.00, 10.10, 9.90, 1e6, 9.95),  # T-1 收盘 = 10.00
        ]
    return out


def test_live_price():
    """验证 _live_price_and_ref 的日内源优先 + 回退告警（回测口径修正）。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    fn = ns["_live_price_and_ref"]

    ctx = _ctx(datetime.datetime(2026, 9, 16, 10, 0, 0))
    code = "600001"

    print("== D. get_current_data 提供日内价 -> p_now 用快照价、c_prev 用昨收、无告警 ==")
    ns["fetch"] = _backtest_fetch
    ns["get_current_data"] = lambda: {code: _Tick(10.50, 10.00)}
    ns["_HEALTH"]["degraded"] = []
    r = fn(ctx, [code])
    ok(code in r, "日内源可用时返回该票快照")
    ok(abs(r[code]["p_now"] - 10.50) < 1e-9, "p_now 取日内 last_price(10.50) 而非 T-1 收盘",
       "got {}".format(r[code]["p_now"]))
    ok(abs(r[code]["c_prev"] - 10.00) < 1e-9, "c_prev 取日内 pre_close(10.00)",
       "got {}".format(r[code]["c_prev"]))
    ok(r[code]["has_today"] is True, "has_today=True（日内源视为真当日价）")
    ok(len(ns["_HEALTH"]["degraded"]) == 0, "日内源可用时不告警（旧版此处必告警）",
       str(ns["_HEALTH"]["degraded"]))

    print("== E. get_current_data 不可用 -> 回退日 K + 显式告警 ==")
    def _boom(*a, **k):
        raise RuntimeError("no get_current_data in this env")
    ns["get_current_data"] = _boom
    ns["_HEALTH"]["degraded"] = []
    r2 = fn(ctx, [code])
    ok(code in r2, "回退日 K 仍返回该票")
    ok(abs(r2[code]["p_now"] - 10.00) < 1e-9, "回退时 p_now = T-1 收盘(10.00)",
       "got {}".format(r2[code]["p_now"]))
    ok(r2[code]["has_today"] is False, "回退且无当日 bar -> has_today=False")
    ok(any("未见当日 bar" in d for d in ns["_HEALTH"]["degraded"]),
       "回退时仍显式告警（不静默错口径）", str(ns["_HEALTH"]["degraded"]))

    print("== F. 护栏基准对比：日内源 vs 回退，证明回测死穴已解 ==")
    # 旧版（仅日 K）：p_now=c_prev=10.00 -> 护栏 [9.85,10.30]，快照价 10.00 永远通过（失效）
    # 新版（日内源）：p_now=10.50 真实快照，护栏 [9.85,10.30] -> 10.50>10.30 触发"涨过头不追"
    upper = round(10.00 * (1 + ns["BUY_PREMIUM_PCT"]), 2)
    lower = round(10.00 * (1 - ns["BUY_FLOOR_PCT"]), 2)
    ok(r[code]["p_now"] > upper, "日内快照 10.50 越过护栏上限 {} -> 真实触发不追高".format(upper))
    ok(r2[code]["p_now"] <= upper, "回退快照 10.00 在护栏内（与旧版一致，作为兜底不报错）")


def test_date_and_sector_kill():
    """V4.2：日期归一化(8位整数) + 板块kill阻尼，避免回测护栏失效与次日whipsaw。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g

    print("== G. _date_str 归一化 8 位整数日期 ==")
    ds = ns["_date_str"]
    ok(ds(20260908) == "2026-09-08", "8位整数 20260908 -> 2026-09-08", ds(20260908))
    ok(ds("2026-09-08") == "2026-09-08", "字符串 2026-09-08 不变", ds("2026-09-08"))
    ok(ds("2026-09-08 00:00:00") == "2026-09-08", "Timestamp 截断[:10]", ds("2026-09-08 00:00:00"))

    print("== H. _sector_killed 阻尼（仅真实退潮才砍，正常波动不砍）==")
    fn = ns["_sector_killed"]
    # 场景1：旧版会砍（峰值2、今日1、<0.5倍），新版不应砍（峰值<4）
    g.sector_state = [{"sector": "英伟达概念", "stage": "无", "zt_cnt": 1}]
    g.prev_signal = {"英伟达概念": [2, 1]}
    ok("英伟达概念" not in fn(), "峰值2→1 的正常波动不砍（旧版此处砍，造成次日whipsaw）", str(fn()))
    # 场景2：真实塌陷（前2日峰值≥4、今日≤1、历史≥3点）-> 砍
    g.sector_state = [{"sector": "稀缺资源", "stage": "无", "zt_cnt": 1}]
    g.prev_signal = {"稀缺资源": [4, 5, 1]}
    ok("稀缺资源" in fn(), "4→1 的真实退潮应砍", str(fn()))
    # 场景3：stage=衰退 -> 砍
    g.sector_state = [{"sector": "元件", "stage": "衰退", "zt_cnt": 0}]
    g.prev_signal = {"元件": [3, 2, 0]}
    ok("元件" in fn(), "stage=衰退 应砍", str(fn()))
    # 场景4：峰值5但今日3（未塌陷）-> 不砍
    g.sector_state = [{"sector": "黄金概念", "stage": "扩散", "zt_cnt": 3}]
    g.prev_signal = {"黄金概念": [5, 5, 3]}
    ok("黄金概念" not in fn(), "5→3 的正常波动不砍", str(fn()))


def test_monitor_risk():
    """V4.3：monitor_risk 不砍赢仓 + 破5日线短持仓不噪声止损。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    fn = ns["monitor_risk"]
    sold = []
    ns["_do_sell"] = lambda code, amt, reason: sold.append((code, amt, reason))

    def setup(sector_state, code_sector, posmap, closes_map, peaks, holds):
        g.sector_state = sector_state
        g.code_sector = code_sector
        g.prev_signal = {}
        g.peak = peaks
        g.hold_days = holds
        g.pos_hist = {c: [(d, cl, cl, cl, 1e6, cl)
                          for d, cl in enumerate(closes_map[c])] for c in closes_map}
        g.cool_down = {}
        ns["positions_map"] = lambda: posmap
        sold[:] = []

    base_pos = lambda cost, last: {
        "current_amount": 100, "enable_amount": 100,
        "cost_price": cost, "last_price": last}

    print("== I. 板块转衰退但持仓盈利(+3%) -> 不在此强平（交止盈处理）==")
    setup(
        [{"sector": "英伟达概念", "stage": "衰退", "zt_cnt": 0}],
        {"600001": "英伟达概念"},
        {"600001": base_pos(10.0, 10.30)},
        {"600001": [10, 10, 10, 10, 10]},
        {"600001": 10.30}, {"600001": 2})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(all("板块联动清仓" not in r for (_, _, r) in sold),
       "盈利仓不被板块kill强平", str(sold))
    ok(len(sold) == 0, "盈利仓(+3%)未被止盈/噪声止损，保留持仓", str(sold))

    print("== J. 板块转衰退且持仓亏损(-5%) -> 强平 ==")
    setup(
        [{"sector": "英伟达概念", "stage": "衰退", "zt_cnt": 0}],
        {"600001": "英伟达概念"},
        {"600001": base_pos(10.0, 9.50)},
        {"600001": [10, 10, 10, 10, 10]},
        {"600001": 10.0}, {"600001": 2})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(any("板块联动清仓" in r for (_, _, r) in sold),
       "亏损仓被板块kill强平", str(sold))

    print("== K. 破5日线：短持仓(<5日)不噪声止损；长持仓(>=5日)止损 ==")
    # 短持仓：跌破5MA，但持仓2日 -> 不砍
    setup([], {}, {"600002": base_pos(10.0, 9.85)},
          {"600002": [10, 10, 10, 10, 9.85]},
          {"600002": 10.0}, {"600002": 2})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(len(sold) == 0, "短持仓破5日线不噪声止损", str(sold))
    # 长持仓：同样跌破5MA，持仓10日 -> 砍（ATR 需>=15根，本测试5根故只破线触发）
    setup([], {}, {"600002": base_pos(10.0, 9.85)},
          {"600002": [10, 10, 10, 10, 9.85]},
          {"600002": 10.0}, {"600002": 10})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(any("破5日线" in r for (_, _, r) in sold),
       "长持仓破5日线正常止损", str(sold))


def test_v44_mainline_filters():
    """V4.4：主线涨停下限(zt_cnt<2不买) + 确认过滤板(昨日高换手不参选) + 信号日涨幅上限。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    ns["REQUIRE_NO_ST"] = False
    g.cool_down = {}
    g.sector_codes = {}
    g.feat = {}
    pick = ns["_main_line_groups"]
    cand = ns["_pick_candidates"]
    ns["positions_map"] = lambda: {}

    def codes(n, prefix):
        return ["{:06d}".format(int(prefix) * 100000 + i) for i in range(n)]

    def add_sector(name, n, prefix, n_lead, pct_lead=10.0, pct_follow=6.0):
        cs = codes(n, prefix)
        g.sector_codes[name] = cs
        for i, c in enumerate(cs):
            g.feat[c] = feat(c, pct_lead if i < n_lead else pct_follow, 9.8, lianban=2)
        return ns["build_sector_signal"](name, cs)

    # 脆弱板块：zt_cnt=1（< MIN_MAIN_ZT_CNT=2），即使成分够也不参选
    sig_weak = add_sector("脆弱板块", 5, 600, n_lead=1)
    # 真实热点：zt_cnt=3、成分 10、跟涨 7（主板，zt_line=9.8）
    sig_hot = add_sector("真实热点", 10, 601, n_lead=3)
    # 昨日高换手：很强（zt_cnt=5）但属确认过滤板，应被剔除主线
    sig_ht = add_sector("昨日高换手", 20, 603, n_lead=5)

    picks = pick([sig_weak, sig_hot, sig_ht])
    picked_names = [s["sector"] for s in picks]

    print("== L. 主线涨停下限：zt_cnt<2 的脆弱板块不参选 ==")
    ok("脆弱板块" not in picked_names, "zt_cnt=1 脆弱板块不进主线", str(picked_names))
    ok("真实热点" in picked_names, "zt_cnt=3 真实热点正常当选", str(picked_names))

    print("== M. 确认过滤板：昨日高换手即使很强也不参选 ==")
    ok("昨日高换手" not in picked_names, "昨日高换手(确认过滤板)不参选主线", str(picked_names))

    print("== N. 候选生成：剔除信号日已涨>8% 的；标记确认过滤 ==")
    # 主线 = 真实热点，含两只候选：A 信号日+9%(应剔除)、B 信号日+5%(属确认板,应保留)
    g.sector_codes["真实热点"] = ["000009", "000007"]
    g.sector_codes["昨日高换手"] = ["000007"]
    g.feat["000009"] = feat("000009", 9.0, 9.8, above20=True)   # +9% > 8 -> 剔除
    g.feat["000007"] = feat("000007", 3.0, 9.8, above20=True)   # +3% 落在扩散回踩区间[0,4%)-> 保留，且属确认板
    g.cool_down = {}
    # V4.5 仅「扩散」阶段主线可买，故此例用 扩散 阶段（启动阶段已在 R 用例专项验证不买）
    out = cand([{"sector": "真实热点", "stage": "扩散"}])
    kept = [d["code"] for d in out]
    ok("000009" not in kept, "信号日+9% 候选被剔除（入场滞后）", str(kept))
    ok("000007" in kept, "信号日+5% 候选保留", str(kept))
    b = [d for d in out if d["code"] == "000007"]
    ok(b and b[0].get("ht_confirm") is True, "候选标记 ht_confirm=True（属昨日高换手确认板）", str(b))


def test_v44_trailing():
    """V4.4：出场改为纯移动止盈（自高点回撤8%清仓），+10%/+15% 硬顶已移除。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    fn = ns["monitor_risk"]
    sold = []
    ns["_do_sell"] = lambda code, amt, reason: sold.append((code, amt, reason))

    def setup(code_sector, posmap, closes_map, peaks, holds):
        g.sector_state = []
        g.code_sector = code_sector
        g.prev_signal = {}
        g.peak = peaks
        g.hold_days = holds
        g.pos_hist = {c: [(d, cl, cl, cl, 1e6, cl)
                          for d, cl in enumerate(closes_map[c])] for c in closes_map}
        g.cool_down = {}
        ns["positions_map"] = lambda: posmap
        sold[:] = []

    base_pos = lambda cost, last: {
        "current_amount": 100, "enable_amount": 100,
        "cost_price": cost, "last_price": last}

    print("== O. 纯移动止盈：自高点回撤8%触发清仓 ==")
    # 高点=20、现价=18.4（=20*(1-8%)，恰好触线）-> 移动止盈
    setup({}, {"600100": base_pos(10.0, 18.4)},
          {"600100": [18, 18, 18, 18, 18]},
          {"600100": 20.0}, {"600100": 6})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(any("移动止盈" in r for (_, _, r) in sold), "自高点回撤8%触发移动止盈", str(sold))
    ok(not any("止盈2" in r or "止盈1" in r for (_, _, r) in sold), "+10%/+15% 硬顶已移除", str(sold))

    print("== P. 赢仓多跑：+20%未回撤不硬顶清仓 ==")
    # 成本10、现价12（+20%），高点=12、未回撤 -> 旧版会在+15%硬顶清仓；新版应保留
    setup({}, {"600101": base_pos(10.0, 12.0)},
          {"600101": [12, 12, 12, 12, 12]},
          {"600101": 12.0}, {"600101": 6})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(len(sold) == 0, "+20% 赢仓未回撤不硬顶清仓（让赢仓多跑）", str(sold))

    print("== Q. 微利(<3%)不挂移动止盈 ==")
    # 成本10、现价10.3（+3%恰好=武装阈值，未>），未回撤 -> 不卖
    setup({}, {"600102": base_pos(10.0, 10.3)},
          {"600102": [10, 10, 10, 10, 10]},
          {"600102": 10.3}, {"600102": 6})
    fn(_ctx(datetime.datetime(2026, 9, 16, 9, 31)))
    ok(len(sold) == 0, "微利(+3%)未回撤不触发移动止盈", str(sold))


def test_v45_entry_ledger():
    """V4.5：① 仅扩散阶段主线可买（启动一日游不买）；② 回退开关；③ 内置盈亏台账；④ 开盘不追高护栏。"""
    global fails
    ns = load()
    g = types.SimpleNamespace()
    ns["g"] = g
    ns["REQUIRE_NO_ST"] = False
    ns["REQUIRE_DIFFUSE_ENTRY"] = True   # 方向A 开
    cand = ns["_pick_candidates"]
    ns["positions_map"] = lambda: {}
    g.cool_down = set()
    g.sector_codes = {}
    g.feat = {}

    def codes(n, prefix):
        return ["{:06d}".format(int(prefix) * 100000 + i) for i in range(n)]

    def add_sector(name, n, prefix, n_lead, pct_lead=10.0, pct_follow=6.0):
        cs = codes(n, prefix)
        g.sector_codes[name] = cs
        for i, c in enumerate(cs):
            g.feat[c] = feat(c, pct_lead if i < n_lead else pct_follow, 9.8, lianban=2)
        return ns["build_sector_signal"](name, cs)

    add_sector("一日游热点", 10, 700, n_lead=3)
    # 扩散阶段只买回踩（0<=pct<4%）：跟涨标的落在回踩区间，龙头+10%封板不买
    add_sector("持续热点", 10, 701, n_lead=3, pct_lead=10.0, pct_follow=3.0)

    print("== R. 方向A①：仅扩散阶段主线可买，启动一日游不买 ==")
    out_r1 = cand([{"sector": "一日游热点", "stage": "启动"}])
    ok(len(out_r1) == 0, "启动阶段主线产出 0 候选（一日游不买）", str([d["code"] for d in out_r1]))
    out_r2 = cand([{"sector": "持续热点", "stage": "扩散"}])
    ok(len(out_r2) > 0, "扩散阶段主线正常产出候选", str([d["code"] for d in out_r2]))

    print("== S. 回退开关：REQUIRE_DIFFUSE_ENTRY=False 时启动主线恢复可买 ==")
    ns["REQUIRE_DIFFUSE_ENTRY"] = False
    out_s = cand([{"sector": "一日游热点", "stage": "启动"}])
    ok(len(out_s) > 0, "开关关闭后启动主线恢复产候选（可一键回退）", str([d["code"] for d in out_s]))
    ns["REQUIRE_DIFFUSE_ENTRY"] = True

    print("== T. 内置盈亏台账：平仓记录胜/负并更新累计 ==")
    rc = ns["_record_close"]
    g.closed_trades = []
    g.stat_wins = 0
    g.stat_losses = 0
    g.stat_pnl = 0.0
    g.peak_equity = 0.0
    g.max_dd = 0.0
    ns["get_total_assets"] = lambda: 100000.0
    rc("600300", 10.0, 11.0, 100, "移动止盈")
    ok(g.stat_wins == 1 and g.stat_losses == 0, "盈利平仓 -> wins+1", "w={} l={}".format(g.stat_wins, g.stat_losses))
    ok(abs(g.stat_pnl - (1.0 * 100 - 10.0 * 100 * ns["COST_PER_SIDE"])) < 1e-6, "累计盈亏=毛利-成本", "pnl={}".format(g.stat_pnl))
    rc("600301", 10.0, 9.0, 100, "板块联动清仓")
    ok(g.stat_losses == 1, "亏损平仓 -> losses+1", "w={} l={}".format(g.stat_wins, g.stat_losses))
    ok(len(g.closed_trades) == 2, "台账记录 2 笔平仓", "{}".format(len(g.closed_trades)))
    before = len(g.closed_trades)
    rc("600302", 0.0, 0.0, 0, "x")
    ok(len(g.closed_trades) == before, "cost<=0 不记（避免信号模式误记）", "{}".format(len(g.closed_trades)))

    print("== U. 开盘不追高护栏：buy_job 对高开>OPEN_CHASE_PCT 候选放弃 ==")
    ns["TRADE_ENABLED"] = True
    ns["_total_asset"] = lambda *a, **k: 100000.0
    ns["_cash_of"] = lambda *a, **k: 100000.0
    ns["turnover_ok"] = lambda *a, **k: True
    ns["market_regime_ok"] = lambda *a, **k: True
    ns["get_positions"] = lambda: {}
    bought = []
    ns["order_value"] = lambda code, val, limit_price=None: bought.append((code, val, limit_price)) or "OID"
    ns["_do_sell"] = lambda *a, **k: None

    class _Tick5(object):
        def __init__(self, lp, pc, op):
            self.last_price = lp
            self.pre_close = pc
            self.open = op

    def _fetch5(codes, n, drop_today=False):
        out = {}
        for c in codes:
            out[c] = [("2026-09-14", 9.80, 9.90, 9.70, 1e6, 9.82),
                      ("2026-09-15", 10.00, 10.10, 9.90, 1e6, 9.95)]
        return out

    ns["fetch"] = _fetch5

    def _gctx(dt):
        return types.SimpleNamespace(current_dt=dt, now=dt,
                                     blotter=types.SimpleNamespace(current_dt=dt),
                                     portfolio=types.SimpleNamespace(cash=100000.0, portfolio_value=100000.0))

    def run_buy(open_price):
        bought[:] = []
        g.now_str = "10:00"
        g.today = "2026-09-16"
        g.buy_today = set()
        g.hold_days = {}
        g.peak = {}
        g.code_sector = {}
        g.cool_down = set()
        g.pending_buy = [{"code": "600400", "sector": "题材股", "stage": "扩散",
                          "pct": 5.0, "zt_line": 9.8, "above20": True,
                          "vol_ratio": 1.0, "lianban": 0, "amt": 5e8}]
        ns["get_current_data"] = lambda: {"600400": _Tick5(10.10, 10.00, open_price)}
        ctx = _gctx(datetime.datetime(2026, 9, 16, 10, 0, 0))
        ns["buy_job"](ctx)
        return list(bought)

    hi = run_buy(10.25)   # 高开 2.5% > 2% -> 应放弃
    ok(len(hi) == 0, "开盘高开>2% -> 不买（追高放弃）", str(hi))
    lo = run_buy(10.08)   # 高开 0.8% < 2% -> 应买
    ok(len(lo) == 1, "开盘高开<2% -> 买入", str(lo))
    ns["TRADE_ENABLED"] = False


if __name__ == "__main__":
    main()
    test_live_price()
    test_date_and_sector_kill()
    test_monitor_risk()
    test_v44_mainline_filters()
    test_v44_trailing()
    test_v45_entry_ledger()
    if fails:
        print("\n结果: 存在失败项 -> {}".format(fails))
        sys.exit(1)
    print("\n结果: 全部通过 (A/B/C/D/E/F/G/H/I/J/K/L/M/N/O/P/Q/R/S/T/U)")
