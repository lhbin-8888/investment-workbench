# -*- coding: utf-8 -*-
"""热点融合 · 入场 alpha 检验器（剥离出场规则）

为什么需要它
------------
当策略长期亏损时，有两个完全不同的病因，处理方式相反：
  (A) 出场规则太紧 → 好票被砍在半路 → 解法是"放松/优化出场"，继续调参有意义
  (B) 入场信号本身无 alpha（甚至负 alpha）→ 出场再怎么优化都只是放大器 → 必须换入场逻辑
只看"净值亏了多少"永远分不清这两者。本工具的做法是：
  把每一笔买入当作一个独立的赌注，**完全忽略策略的止损/止盈**，
  只用真实日线算"买入后 T+N 收盘"以及"持有窗口内的 MFE/MAE"，
  再穷举若干条候选出场规则做反事实，看**出场端的天花板**在哪里。

判读标准（先定死，跑完不许改）
------------------------------
  · T+5 裸持有均值 > +0.5%      → 属 (A)：出场在毁钱，去优化出场
  · T+5 裸持有均值 ∈ [-0.5%,+0.5%] → 无 alpha：赚不到也亏不多，是成本+噪声游戏
  · T+5 裸持有均值 < -0.5%      → 属 (B)：入场负漂移。**此时若遍历所有出场规则
                                   的最大均值仍 < 0，则调参这条路已封死**（本工具
                                   会在输出里直接给出这句结论）。

口径（踩过坑，别改）
--------------------
  ① 成本价 = 日志 [买入] 行的"限价" ÷ 1.02。源码 L2023 `limit = min(cur*1.02, hi_guard)`，
     而 `entry_px = cur`，所以限价是**委托价**不是成交价。
     实测：限价÷1.02 全部落在当日真实价格区间内；直接用限价则有 22/41 笔
     "高于当日最高价"，会得出"买入价虚构"的错误结论。
  ② 行情用腾讯**不复权**日线（`param=...,day,...` 尾参留空）。
     用前复权会在除权票上引入偏差。
  ③ MFE/MAE 指持有窗口内相对成本价的最高/最低浮盈，是"盘中瞬时"口径，
     只在精确卖在极值点时才可实现 —— 它衡量机会，不衡量收益。

用法
----
    python entry_alpha_check.py [日志路径] [--json 输出.json]
    默认读同目录 热点融合回测1.txt
"""
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.join(ROOT, "热点融合回测1.txt")
BUY_ORDER_PREMIUM = 1.02          # 见口径 ①
TX_TPL = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
          "?param=%s,day,%s,%s,320,")   # 尾参留空 = 不复权
START, END = "2026-04-20", "2026-07-25"

RE_BUY = re.compile(r"\[买入\]\s+(\S+\.(?:SZ|SS))\s+行业=(\S+)\s+强度([\d.]+)\s+分配(\d+)\s+限价([\d.]+)")
RE_SELL = re.compile(r"\[卖出\]\s+(\S+\.(?:SZ|SS))\s+(?:数量(\d+)\s+)?(?:——\s*)?(\S+?)\s+浮盈(-?[\d.]+)%")
RE_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


# ------------------------------------------------------------------ 取数
_ctx = ssl.create_default_context()


def tx_kline(code6, start=START, end=END):
    """腾讯日线（不复权）-> [(日期, 开, 收, 高, 低)]；失败返回 []"""
    pre = "sh" if code6[0] in "69" else ("bj" if code6[0] == "8" else "sz")
    sym = pre + code6
    req = urllib.request.Request(TX_TPL % (sym, start, end))
    req.add_header("User-Agent", "Mozilla/5.0")
    d = json.loads(urllib.request.urlopen(req, timeout=20, context=_ctx).read().decode("utf-8"))
    k = d.get("data", {}).get(sym, {})
    rows = k.get("day") or k.get("qfqday") or []
    return [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]


def index_return(sym, start="2026-05-06", end="2026-06-30"):
    try:
        rows = tx_kline_index(sym, start, end)
        if rows:
            return rows[0][1], rows[-1][2], 100.0 * (rows[-1][2] - rows[0][1]) / rows[0][1]
    except Exception:
        pass
    return None, None, None


def tx_kline_index(sym, start, end):
    req = urllib.request.Request(TX_TPL % (sym, start, end))
    req.add_header("User-Agent", "Mozilla/5.0")
    d = json.loads(urllib.request.urlopen(req, timeout=20, context=_ctx).read().decode("utf-8"))
    k = d.get("data", {}).get(sym, {})
    rows = k.get("day") or k.get("qfqday") or []
    return [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]


# ------------------------------------------------------------------ 解析
def parse_log(path):
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    buys, state, cur = [], {}, None
    for l in lines:
        m = RE_DATE.match(l)
        if m:
            cur = m.group(1)
        m = re.search(r"\[日初\] 持仓 (\d+) 只 \| 大市=(\w+)", l)
        if m and cur:
            state[cur] = m.group(2)
        m = RE_BUY.search(l)
        if m:
            buys.append({"date": cur, "disp": m.group(1), "code6": m.group(1).split(".")[0],
                         "ind": m.group(2), "strength": float(m.group(3)),
                         "alloc": int(m.group(4)),
                         "limit": float(m.group(5)),
                         "cur": float(m.group(5)) / BUY_ORDER_PREMIUM})
    sells = {}
    cur = None
    for l in lines:
        m = RE_DATE.match(l)
        if m:
            cur = m.group(1)
        m = RE_SELL.search(l)
        if m:
            c6 = m.group(1).split(".")[0]
            if c6 not in sells:
                sells[c6] = {"date": cur, "reason": m.group(3), "pnl": float(m.group(4))}
    return buys, sells, state


# ------------------------------------------------------------------ 主逻辑
def analyse(kl, b):
    """单笔：返回各持有期收益与 MFE/MAE；kl 已按日期升序"""
    days = [r[0] for r in kl]
    if b["date"] not in days:
        return None
    i0 = days.index(b["date"])
    o0, c0, h0, l0 = kl[i0][1], kl[i0][2], kl[i0][3], kl[i0][4]
    base = b["cur"]
    prev = kl[i0 - 1][2] if i0 > 0 else 0
    rng = h0 - l0
    seg = [{"d": n + 1, "o": r[1], "c": r[2], "h": r[3], "l": r[4],
            "rh": 100.0 * (r[3] - base) / base,
            "rl": 100.0 * (r[4] - base) / base,
            "rc": 100.0 * (r[2] - base) / base}
           for n, r in enumerate(kl[i0 + 1:i0 + 11])]
    out = {"buy": b, "i0": i0, "seg": seg,
           "range_pos": 100.0 * (base - l0) / rng if rng > 0 else None,
           "to_close_d0": 100.0 * (c0 - base) / base,
           "to_high_d0": 100.0 * (h0 - base) / base,
           "day_chg": 100.0 * (c0 - prev) / prev if prev else None}
    for n in (1, 2, 3, 5, 10):
        out["T%d" % n] = seg[n - 1]["rc"] if len(seg) >= n else None
    w = seg[:5]
    out["mfe5"] = max(x["rh"] for x in w) if w else None
    out["mae5"] = min(x["rl"] for x in w) if w else None
    if w:
        out["mfe_day"] = max(range(len(w)), key=lambda i: w[i]["rh"]) + 1
    return out


def stat(name, v):
    v = [x for x in v if x is not None]
    if not v:
        return None
    v2 = sorted(v)
    return {"name": name, "n": len(v), "mean": sum(v) / len(v),
            "median": v2[len(v2) // 2],
            "win": 100.0 * sum(1 for x in v if x > 0) / len(v),
            "best": v2[-1], "worst": v2[0]}


def fmt(s):
    if not s:
        return "  (n=0)"
    return ("n=%-3d 均值 %+6.2f%%  中位 %+6.2f%%  胜率 %5.1f%%  最差 %+6.1f%%  最好 %+6.1f%%"
            % (s["n"], s["mean"], s["median"], s["win"], s["worst"], s["best"]))


def rule_hold(n):
    def f(seg):
        return seg[n - 1]["rc"] if len(seg) >= n else None
    return f


def rule_touch(trigger, exit_n):
    def f(seg):
        for x in seg[:5]:
            if x["rh"] >= trigger:
                return x["rc"]
        return seg[exit_n - 1]["rc"] if len(seg) >= exit_n else None
    return f


def rule_trail(trigger, back, maxn=10):
    def f(seg):
        armed, hi = False, 0.0
        for x in seg[:maxn]:
            hi = max(hi, x["rh"])
            if not armed and x["rh"] >= trigger:
                armed = True
            if armed and (hi - x["rc"]) >= back:
                return x["rc"]
        return seg[maxn - 1]["rc"] if len(seg) >= maxn else None
    return f


def rule_hardstop(stop, n=5):
    def f(seg):
        for x in seg[:n]:
            if x["rl"] <= stop:
                return stop
        return seg[n - 1]["rc"] if len(seg) >= n else None
    return f


def simulate(items, rule):
    out = [rule(it["seg"]) for it in items]
    out = [x for x in out if x is not None]
    if not out:
        return None
    v = sorted(out)
    return {"n": len(out), "mean": sum(out) / len(out), "median": v[len(v) // 2],
            "win": 100.0 * sum(1 for x in out if x > 0) / len(out),
            "best": v[-1], "worst": v[0]}


def main():
    argv = sys.argv[1:]
    log = argv[0] if (argv and not argv[0].startswith("--")) else DEFAULT_LOG
    js_out = None
    if "--json" in argv:
        j = argv.index("--json")
        if j + 1 < len(argv):
            js_out = argv[j + 1]

    buys, sells, state = parse_log(log)
    if not buys:
        print("[X] 没解析到 [买入] 行 —— 确认日志版本与行格式")
        return
    print("=" * 116)
    print("入场 alpha 检验（剥离出场规则）   日志: %s   买入 %d 笔" % (os.path.basename(log), len(buys)))
    print("=" * 116)
    print("成本价口径: [买入]行限价 ÷ %.2f（委托价→成交价还原）   行情: 腾讯不复权日线" % BUY_ORDER_PREMIUM)

    kl_cache = {}
    items = []
    for b in buys:
        c = b["code6"]
        if c not in kl_cache:
            try:
                kl_cache[c] = tx_kline(c)
            except Exception as e:
                kl_cache[c] = []
                print("  [WARN] %s 取数失败: %s" % (c, e))
            time.sleep(0.22)
        it = analyse(kl_cache.get(c) or [], b)
        if it:
            it["sell"] = sells.get(c)
            it["state"] = state.get(b["date"], "?")
            items.append(it)

    if not items:
        print("[X] 无可用样本（行情取数全部失败？）")
        return

    # ---- 逐笔 ----
    print()
    print("%-11s %-11s %8s %6s | %6s %6s %6s %6s | %7s %7s | %-7s %s" % (
        "买入日", "代码", "成本价", "区间位", "T+1", "T+3", "T+5", "T+10", "MFE5", "MAE5", "大市", "实际出场"))
    print("-" * 116)
    for it in items:
        b, sl = it["buy"], it.get("sell")
        g = lambda k: ("%+6.1f%%" % it[k]) if it.get(k) is not None else "   -   "
        print("%-11s %-11s %8.2f %5.0f%% | %s %s %s %s | %s %s | %-7s %s" % (
            b["date"], b["disp"], b["cost"] if "cost" in b else b["cur"], it["range_pos"] or 0,
            g("T1"), g("T3"), g("T5"), g("T10"), g("mfe5"), g("mae5"), it["state"],
            ("%s %+.1f%%" % (sl["reason"], sl["pnl"])) if sl else "未平仓"))

    # ---- 汇总 ----
    print("-" * 116)
    print()
    print("【A】剥离出场规则：裸持有收益（这是入场信号的真实 alpha）")
    rows = {}
    for n in (1, 2, 3, 5, 10):
        s = stat("T+%d" % n, [it["T%d" % n] for it in items])
        rows["T%d" % n] = s
        print("  持有到 T+%-2d 收盘       %s" % (n, fmt(s)))
    s = stat("实际出场", [it["sell"]["pnl"] for it in items if it.get("sell")])
    rows["actual"] = s
    print("  策略实际出场收益        %s   ← 出场规则相对裸持有的贡献" % fmt(s))
    print()
    print("  5日 MFEmax（盘中最好）  %s" % fmt(stat("mfe", [it["mfe5"] for it in items])))
    print("  5日 MAEmin（盘中最差）  %s" % fmt(stat("mae", [it["mae5"] for it in items])))
    print("  入场价在当日区间位置    %s   ← 越高越说明追在半山腰" % fmt(stat("pos", [it["range_pos"] for it in items])))
    print("  10:30 → 当日收盘        %s" % fmt(stat("d0", [it["to_close_d0"] for it in items])))

    # ---- 反事实 ----
    print()
    print("【B】出场规则反事实（同一批入场，只换出场）")
    cand = []
    for n in (1, 2, 3, 5, 10):
        cand.append(("固定持有 T+%d" % n, rule_hold(n)))
    for tr in (2, 3, 4, 5, 6, 8, 10):
        cand.append(("触及 +%d%% 卖(收盘)，否则 T+5" % tr, rule_touch(tr, 5)))
    for tr, bk in ((3, 2), (4, 2), (4, 3), (5, 2)):
        cand.append(("达 +%d%% 后回撤 %d%% 卖" % (tr, bk), rule_trail(tr, bk)))
    for sp in (-3, -4, -5, -6, -8, -10):
        cand.append(("硬止损 %d%%（5日上限）" % sp, rule_hardstop(sp, 5)))

    best_name, best_mean = None, -1e9
    res = []
    for name, rule in cand:
        r = simulate(items, rule)
        if not r:
            continue
        res.append((name, r))
        tag = ""
        if r["mean"] > best_mean:
            best_mean, best_name = r["mean"], name
            tag = ""
        print("  %-34s 均值 %+6.2f%%  中位 %+6.2f%%  胜率 %5.1f%%  最差 %+6.1f%%" % (
            name, r["mean"], r["median"], r["win"], r["worst"]))

    # ---- 基准 ----
    print()
    print("【C】同期基准")
    base = {}
    for nm, sym in (("沪深300", "sh000300"), ("中证1000", "sh000852")):
        a, bb, rr = index_return(sym)
        if rr is not None:
            base[nm] = rr
            print("  %-9s %s → %s   %+.2f%%" % (nm, a, bb, rr))

    # ---- 判定 ----
    t5 = rows.get("T5")
    print()
    print("=" * 116)
    print("【判定】")
    if t5:
        if t5["mean"] > 0.5:
            print("  ✅ T+5 裸持有均值 %+.2f%% > +0.5%% → 入场有正漂移，出场规则在毁钱 → 该修出场" % t5["mean"])
        elif t5["mean"] >= -0.5:
            print("  ⚠️ T+5 裸持有均值 %+.2f%% ∈ [-0.5%%,+0.5%%] → 入场无 alpha，是成本+噪声游戏" % t5["mean"])
        else:
            print("  ❌ T+5 裸持有均值 %+.2f%% < -0.5%% → 入场负漂移" % t5["mean"])
            if best_mean < 0:
                print("  ❌ 且遍历 %d 条出场规则，最好的一条「%s」仍只有 %+.2f%%。" % (
                    len(res), best_name, best_mean))
                print("     ⇒ **出场端天花板为负：调参这条路已封死，必须改入场信号。**")
            else:
                print("  ⚠️ 但存在正期望的出场规则「%s」(%+.2f%%) → 出场端仍有空间，可继续调" % (
                    best_name, best_mean))
    act = rows.get("actual")
    if act and t5:
        d = act["mean"] - t5["mean"]
        print("  · 出场规则的实测贡献 = 实际 %+.2f%% − 裸持T+5 %+.2f%% = %+.2fpp（%s）" % (
            act["mean"], t5["mean"], d, "出场在减亏" if d > 0 else "出场反而放大亏损"))

    if js_out:
        payload = {"log": os.path.basename(log), "n_buy": len(items),
                   "summary": rows, "baseline": base,
                   "counterfactual": [{"name": n, "mean": r["mean"], "win": r["win"]} for n, r in res],
                   "best_rule": {"name": best_name, "mean": best_mean},
                   "per_trade": [{"date": it["buy"]["date"], "code": it["buy"]["disp"],
                                  "cur": it["buy"]["cur"], "T1": it["T1"], "T5": it["T5"],
                                  "mfe5": it["mfe5"], "mae5": it["mae5"],
                                  "state": it["state"],
                                  "actual": it["sell"]["pnl"] if it.get("sell") else None}
                                 for it in items]}
        io.open(js_out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(payload, ensure_ascii=False, indent=1))
        print("  [json] 已写出 %s" % js_out)


if __name__ == "__main__":
    main()
