# -*- coding: utf-8 -*-
"""热点融合 · 成交台账重建器（不管钱，只算账）

用途：回测日志里只有"逐笔委托 + 每笔卖出的平台报浮盈%"，没有成交回报表。
      本脚本据此重建一张台账，按【退出原因】分组，算出真正的
      单笔胜率 / 盈亏比 / 单笔期望 —— 这是判断"收益率为什么更差"的第一把尺。

用法：
    python trade_ledger.py [日志路径]        默认读 热点融合回测1.txt

关键口径（踩过坑，别改）：
  ① 股数取委托行的真实股数 `数量：买入N股`，**不能**用 `分配÷限价` 估
     —— 那是策略的名义下单量。实测把 700 股算成 771 股，单笔亏损被放大 10%。
  ② 部分平仓（减半 / 赢家锁利）按持仓批次 FIFO 扣减，不能当全平。
  ③ 台账实现盈亏须与日志末尾的 [净值] 期末值对账，差 <1pp 才算可信。
  ④ 【2026-09-22 修正】[买入] 行里的"限价"是**委托价**，不是成交价！
     源码 L2023 `limit = min(cur*1.02, hi_guard)`，而 `entry_px = cur` ——
     即策略内部成本价 = 限价 ÷ 1.02。旧版直接把限价当成本价，导致每笔
     成本额被系统性高估 2%、盈亏被放大、台账与净值对账产生偏差。
     验证：41 笔买入的 限价÷1.02 全部落在当日真实价格区间内；而限价本身
     有 22/41 笔高于当日最高价 —— 这曾让我误判为"买入价虚构"。
"""
import io
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.join(ROOT, "热点融合回测1.txt")
START_CAPITAL = 100000          # 回测起始资金；对账基准
BUY_ORDER_PREMIUM = 1.02        # 委托限价 = 当日价 × 1.02（源码 L2023），故成本价 = 限价 ÷ 1.02

RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})")
RE_ORDER = re.compile(r"股票代码：(\S+\.(?:XSHE|XSHG))，数量：买入(\d+)股")
RE_BUY = re.compile(r"\[买入\]\s+(\S+\.(?:SZ|SS))\s+行业=(\S+)\s+强度([\d.]+)\s+分配(\d+)\s+限价([\d.]+)")
RE_SELL = re.compile(r"\[卖出\]\s+(\S+\.(?:SZ|SS))\s+(?:数量(\d+)\s+)?(.*?)浮盈(-?[\d.]+)%")
RE_STATE = re.compile(r"\[日初\].*大市=(\w+)")
RE_NAV = re.compile(r"\[净值\]\s+(\d{4}-\d{2}-\d{2})\s+总资产=(\d+)")


def parse(path):
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    day_state, cur_date, cur_ts = {}, "", ""
    pending_sh, events, navs = None, [], []
    for l in lines:
        tm = RE_TS.match(l)
        if tm:
            cur_date, cur_ts = tm.group(1), tm.group(0)
        m = RE_STATE.search(l)
        if m:
            day_state[cur_date] = m.group(1)
        m = RE_NAV.search(l)
        if m:
            navs.append((m.group(1), int(m.group(2))))
        mo = RE_ORDER.search(l)
        if mo:
            pending_sh = int(mo.group(2))
        mb = RE_BUY.search(l)
        if mb:
            # 限价是委托价（cur×1.02），成本价必须还原回 cur，见文件头 ④
            cur_px = float(mb.group(5)) / BUY_ORDER_PREMIUM
            nsh = pending_sh if pending_sh else int(mb.group(4)) // max(1, int(round(cur_px)))
            events.append((cur_ts, "BUY", (mb.group(1), mb.group(2), float(mb.group(3)),
                                            nsh, cur_px)))
            pending_sh = None
        ms = RE_SELL.search(l)
        if ms:
            events.append((cur_ts, "SELL", (ms.group(1),
                                            int(ms.group(2)) if ms.group(2) else None,
                                            ms.group(3).replace("——", "").strip(),
                                            float(ms.group(4)))))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "BUY" else 1))
    return events, day_state, navs


def build(events, day_state):
    pos = defaultdict(list)
    buystate = {}
    rows = []
    n_buy = n_sell = 0
    for ts, kind, pl in events:
        if kind == "BUY":
            n_buy += 1
            code, _ind, _stren, nsh, px = pl
            pos[code].append([ts[:10], nsh, px])
            buystate[code] = day_state.get(ts[:10], "?")
        else:
            n_sell += 1
            code, sh, note, pf = pl
            left = sh
            cost_sh, cost_amt, keep = 0, 0.0, []
            for lot in pos[code]:
                if left is not None and left <= 0:
                    keep.append(lot)
                    continue
                take = lot[1] if left is None else min(left, lot[1])
                cost_sh += take
                cost_amt += take * lot[2]
                if left is not None:
                    left -= take
                if lot[1] - take > 0:
                    keep.append([lot[0], lot[1] - take, lot[2]])
            pos[code] = keep
            rows.append((ts[:10], code, cost_sh, cost_amt / max(1, cost_sh), note, pf,
                         cost_amt, cost_amt * pf / 100.0, buystate.get(code, "?")))
    return rows, n_buy, n_sell, pos


def report(path):
    events, day_state, navs = parse(path)
    rows, n_buy, n_sell, pos = build(events, day_state)
    if not rows:
        print("[X] 没解析到任何成交 —— 先确认日志版本与 [买入]/[卖出] 行格式")
        return

    print("=" * 96)
    print("成交台账重建   日志: %s" % os.path.basename(path))
    print("买入 %d 笔   卖出 %d 笔   期末未平仓 %d 只" %
          (n_buy, n_sell, sum(1 for c in pos if pos[c])))
    print("=" * 96)
    print("%-11s %-11s %7s %8s %-10s %7s %9s %9s %6s" %
          ("卖出日", "代码", "股数", "成本价", "退出原因", "浮盈%", "成本额", "盈亏", "买入档"))
    tot = sum(r[7] for r in rows)
    for r in rows:
        print("%-11s %-11s %7d %8.2f %-10s %+6.1f%% %9.0f %+9.0f %6s" %
              (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
    print("-" * 96)
    print("已实现盈亏合计（估） = %+.0f" % tot)

    if navs:
        base = START_CAPITAL
        print("对账：[净值] 首日 %s=%d  末日 %s=%d  →  净值口径相对起始 %d 为 %+.2f%%" %
              (navs[0][0], navs[0][1], navs[-1][0], navs[-1][1], base,
               100.0 * (navs[-1][1] - base) / base))
        peak = max(n for _, n in navs)
        print("      峰值 %d  →  峰终回撤 %+.2f%%" % (peak, 100.0 * (navs[-1][1] - peak) / peak))
        gap = abs(100.0 * (navs[-1][1] - base) / base - 100.0 * tot / base)
        print("      台账 %+.2f%%  vs  净值 %+.2f%%  →  差 %.2fpp %s" %
              (100.0 * tot / base, 100.0 * (navs[-1][1] - base) / base, gap,
               "OK" if gap < 1.0 else "⚠ 超 1pp，查成本价口径或部分平仓匹配"))

    byreason = defaultdict(list)
    for r in rows:
        byreason[re.sub(r"\s+", "", r[4])].append(r)
    print()
    print("=== 按退出原因归类 ===")
    print("%-12s %5s %10s %9s" % ("原因", "笔数", "合计盈亏", "均值浮盈%"))
    for k in sorted(byreason, key=lambda x: -len(byreason[x])):
        v = byreason[k]
        print("%-12s %5d %10.0f %+8.2f%%" %
              (k, len(v), sum(x[7] for x in v), sum(x[5] for x in v) / len(v)))

    wins = [r for r in rows if r[5] > 0.5]
    losses = [r for r in rows if r[5] < -0.5]
    flat = [r for r in rows if -0.5 <= r[5] <= 0.5]
    gp = sum(r[7] for r in wins)
    gl = -sum(r[7] for r in losses)
    print()
    print("=== 三个决定性指标 ===")
    print("单笔胜率          = %d/%d = %.1f%%" % (len(wins), len(rows), 100.0 * len(wins) / len(rows)))
    print("盈亏比(毛额口径)   = %.3f   [毛盈 %+.0f / 毛亏 %+.0f]" % (gp / gl if gl else 0, gp, -gl))
    print("单笔期望          = %+.0f 元/笔" % (tot / len(rows)))
    if len(wins) and len(losses):
        aw = sum(r[5] for r in wins) / len(wins)
        al = sum(r[5] for r in losses) / len(losses)
        p = len(wins) / float(len(rows))
        print("赔率(单笔均值口径) = %.2f   [平均盈 %+.2f%% / 平均亏 %+.2f%%]" % (aw / -al, aw, al))
        print("自洽检查          : 期望 ≈ %.1f%%×(%+.2f%%) + %.1f%%×(%+.2f%%) + %.1f%%×0 = %+.2f%%/笔" %
              (100 * p, aw, 100 * len(losses) / len(rows), al, 100 * len(flat) / len(rows),
               (len(wins) * aw + len(losses) * al) / len(rows)))
        print("── 打平需任一条成立（现结构）──")
        print("   ① 胜率 %.1f%% → %.1f%%（把亏损单砍掉 %d 笔）" %
              (100 * p, 100 * -al / (aw - al),
               len(losses) - int(round(len(rows) * -al / (aw - al)))))
        print("   ② 平均盈利 %+.2f%% → %+.2f%%（放大 %.1f 倍）" %
              (aw, (1 - p) * (-al) / p, ((1 - p) * (-al) / p) / aw))
        print("   ③ 平均亏损 %+.2f%% → %+.2f%%（把止损收紧 %.1f 倍）" %
              (al, -p * aw / (1 - p), (-al) / max(0.01, p * aw / (1 - p))))
    print("平单(±0.5%%)      = %d 笔" % len(flat))

    stop_n = sum(len(byreason.get(k, [])) for k in ["硬止损", "保本止损", "时间止损"])
    take_n = len(rows) - stop_n
    print("退出结构          : 止损类 %d 笔 (%.0f%%)  vs  止盈类 %d 笔 (%.0f%%)" %
          (stop_n, 100.0 * stop_n / len(rows), take_n, 100.0 * take_n / len(rows)))

    print()
    print("=== 按买入日大市档位拆分（找结构性隐患）===")
    for st in ["NORMAL", "HALF", "HALT"]:
        codes = set(r[1] for r in rows if r[8] == st)
        nb = len(set(r[1] for r in rows if r[8] == st))
        if not nb:
            continue
        sub = [r for r in rows if r[1] in codes]
        s = sum(r[7] for r in sub)
        print("%-7s : 已平仓 %2d 笔, 合计 %+7.0f, 单笔均值 %+7.0f" %
              (st, len(sub), s, s / max(1, len(sub))))
    print("（注：每笔平仓按其买入当日的大市档位归组；买入笔数见上方汇总）")


if __name__ == "__main__":
    report(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG)
