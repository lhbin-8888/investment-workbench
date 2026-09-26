# -*- coding: utf-8 -*-
"""热点融合「预登记判据」自动校验器（第十一轮产物，2026-09-22）

为什么要有这个东西
    第九轮用 3000 次蒙特卡洛预测了 [精选] 层的行为（诊断文档第十二章），
    第十轮把 v1.7 传上去之前，先把预测「预登记」成可证伪的阈值（文档第十四章）。
    跑完回测后用本脚本一键判定，避免"事后看图找理由"。

判定对象 = 诊断文档第十四章 P1 ~ P6

用法
    python check_funnel_prediction.py                     # 默认读 热点融合回测1.txt
    python check_funnel_prediction.py <日志路径>

输出
    ① 版本自证（指纹 / [大市] / [行业] 来源）
    ② 逐日漏斗表（大市 | 粗筛过关 | 六道闸各自淘汰 | 候选 | 买入）
    ③ P1~P6 逐条命中/证伪
    ④ 闸门腿与 v1.5 基线的对照
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.join(HERE, u"热点融合回测1.txt")

# ---------------------------------------------------------------- 基线（v1.5 真机 39 天）
BASE = {
    "regime": {"NORMAL": 19, "HALF": 4, "HALT": 14, "PAUSE": 2},
    "util": 29.7,                       # 全周期平均仓位利用率 %
    "in_halt": 1.3, "in_normal": 51.5,  # HALT日 / NORMAL日 平均仓位 %
    "zero_buy_normal": ["2026-05-21", "2026-06-16", "2026-06-22", "2026-06-25"],
    "zero_buy_rough": 106,              # 上述 4 天粗筛过关均值
    "sim": {"hit": 1.72, "survive": 1.77, "empty": 42.9,
            "spread_boards": 77.8, "align_boards": 0.84},
}

RE_REGIME = re.compile(r"\[日初\] 持仓 (\d+) 只 \| 大市=(\w+) \| 情绪=(\w+)")
RE_ROUGH = re.compile(r"\[粗筛\] 池(\d+) \S+ 涨幅区间淘汰(\d+) \S+ 成交额淘汰(\d+) "
                      r"\S+ MA20淘汰(\d+) \S+ 过关(\d+)")
# 尾注兼容 v1.7「| 行业榜10个」与 v1.8「| 行业榜10/31(全市场样本,门槛>=5,过滤=ON,Top3=[...」
RE_SEL = re.compile(r"\[精选\] 粗筛(\d+) \S+ 行业榜淘汰(\d+) \S+ 共振淘汰(\d+) "
                    r"\S+ MA60淘汰(\d+) \S+ 形态淘汰(\d+) \S+ 回撤淘汰(\d+) "
                    r"\S+ 回踩淘汰(\d+) \S+ 涨停剔除(\d+) \S+ 候选(\d+)\(截前(\d+)\)"
                    r" \| 行业榜(\d+)(?:个|/\d+)")
RE_ZERO = re.compile(r"\[精选\] 候选为0：粗筛过关(\d+) 只")
RE_HB = re.compile(r"\[净值\] (\S+) 总资产=(\d+) 现金=(\d+) 持仓=(\d+) 只"
                   r"(?: 持仓市值=(\d+))?")
RE_MKT = re.compile(r"\[大市\] 中证1000 close=([\d.]+) MA20=([\d.]+) 偏离=([+\-\d.]+)% "
                    r"破MA20=(\w+) \| 沪深300 close=([\d.]+) MA20=([\d.]+) "
                    r"偏离=([+\-\d.]+)% 破MA20=(\w+)")
RE_FP = re.compile(r"FUSION (v[0-9.]+)")
NOBUY = (u"暂停新建仓", u"当日候选为0", u"持仓已满", u"账户总资产<=0", u"不建仓")

GATES = ["行业榜", "共振", "MA60", "形态", "回撤", "回踩", "涨停"]


def day_of(line):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", line)
    return m.group(1) if m else None


def parse(path):
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    D = {}
    info = {"fp": set(), "mkt": 0, "ind": [], "zero": [], "buy_err": [],
            "datacount": 0}
    for ln in lines:
        d = day_of(ln)
        if not d:
            continue
        e = D.setdefault(d, {"regime": None, "rough": None, "sel": None,
                             "zero": False, "buy": 0, "net": None, "mkt": None})
        for m in RE_FP.finditer(ln):
            info["fp"].add(m.group(1))
        if u"[行业]" in ln:
            info["ind"].append(ln.strip()[-120:])
        m = RE_REGIME.search(ln)
        if m:
            e["regime"] = m.group(2)
        m = RE_MKT.search(ln)
        if m:
            e["mkt"] = m.groups()
            info["mkt"] += 1
        m = RE_ROUGH.search(ln)
        if m:
            e["rough"] = int(m.group(5))
        m = RE_SEL.search(ln)
        if m:
            g = [int(x) for x in m.groups()]
            e["sel"] = {"rough": g[0], "gates": dict(zip(GATES, g[1:8])),
                        "cands": g[8], "cap": g[9], "boards": g[10]}
        if RE_ZERO.search(ln):
            e["zero"] = True
            info["zero"].append((d, int(RE_ZERO.search(ln).group(1))))
        if u"INFO - [买入]" in ln and not any(k in ln for k in NOBUY):
            e["buy"] += 1
        if u"ERROR" in ln and (u"[大市]" in ln or u"[行业]" in ln or u"[口径]" in ln):
            info["buy_err"].append(ln.strip()[-140:])
        m = RE_HB.search(ln)
        if m:
            mv = int(m.group(5)) if m.group(5) else 0
            e["net"] = (int(m.group(2)), mv)
            info["datacount"] += 1
    # 剔除噪声行：PTrade 自带 harness 行的日期是"跑回测那天"（如 2026-09-22 20:26:00
    # 开始运行回测），会被误当成一个交易日。只保留有实质记录的日子。
    for d in list(D):
        e = D[d]
        if not (e["regime"] or e["sel"] or e["rough"] is not None
                or e["net"] or e["mkt"] or e["buy"] or e["zero"]):
            del D[d]
    return D, info


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    if not os.path.isfile(path):
        print(u"[错] 找不到日志: %s" % path)
        return 2
    D, info = parse(path)
    days = sorted(D)

    # 版本门槛：判据能否"被观测"取决于日志版本。
    # 「无法判定」与「证伪」必须严格区分 —— 旧版日志没有观测点，不代表预测错了。
    def vt(v):
        try:
            return tuple(int(x) for x in v.lstrip(u"v").split(u"."))
        except Exception:
            return (0,)
    vmax = max([vt(x) for x in info["fp"]] or [(0,)])
    has_funnel = vmax >= (1, 6, 1)   # [精选] 六道闸漏斗行
    has_layer = vmax >= (1, 6)       # [大市] 自证行 + 分层闸门
    vtxt = u"v" + u".".join(str(x) for x in vmax) if vmax != (0,) else u"<未知>"

    print(u"=" * 78)
    print(u"热点融合 「预登记判据」自动校验      日志: %s" % os.path.basename(path))
    print(u"天数 %d   %s ~ %s" % (len(days), days[0], days[-1]))
    print(u"=" * 78)

    # ① 版本自证
    print(u"\n【① 版本自证】")
    print(u"  指纹         : %s" % (sorted(info["fp"]) or u"<未找到→上传的不是新版>"))
    print(u"  [大市]自证行 : %d 行" % info["mkt"])
    for t in info["ind"][:3]:
        print(u"  [行业]       : ...%s" % t)
    if info["buy_err"]:
        print(u"  相关 ERROR (%d):" % len(info["buy_err"]))
        for t in info["buy_err"][:5]:
            print(u"     %s" % t)

    # ② 逐日漏斗
    print(u"\n【② 逐日漏斗】")
    hdr = u"%-11s %-7s %5s | %s | %5s %5s %s" % (
        u"日期", u"大市", u"过关",
        u" ".join(u"%5s" % g for g in GATES), u"候选", u"买入", u"仓位%")
    print(hdr)
    print(u"-" * len(hdr))
    for d in days:
        e = D[d]
        s = e["sel"]
        if s:
            gs = u" ".join(u"%5d" % s["gates"][g] for g in GATES)
            cand, rough = s["cands"], s["rough"]
        else:
            gs, cand, rough = u" ".join([u"    -"] * 7), u"-", (e["rough"] or 0)
        util = u"-"
        if e["net"] and e["net"][0]:
            util = u"%.0f" % pct(e["net"][1], e["net"][0])
        flag = u" <0候选" if e["zero"] else u""
        print(u"%-11s %-7s %5s | %s | %5s %5d %5s%s" % (
            d, e["regime"] or u"?", rough, gs, cand, e["buy"], util, flag))

    tradable = [d for d in days if D[d]["regime"] in (u"NORMAL", u"HALF")]
    sel_days = [d for d in days if D[d]["sel"]]
    zero_buy = [d for d in tradable if D[d]["buy"] == 0]

    cnt = {}
    for d in days:
        cnt[D[d]["regime"]] = cnt.get(D[d]["regime"], 0) + 1
    frozen = cnt.get(u"HALT", 0) + cnt.get(u"PAUSE", 0)
    half = cnt.get(u"HALF", 0)

    # ③ 判据
    print(u"\n【③ 预登记判据判定】")
    res = []

    # P1
    hits = []
    for d in zero_buy:
        s = D[d]["sel"]
        if not s or not s["rough"]:
            continue
        r = pct(s["gates"][u"行业榜"] + s["gates"][u"共振"], s["rough"])
        hits.append((d, r, s[
            "rough"]))
    if not has_funnel:
        res.append((u"P1", None,
                    u"日志为 %s（缺 [精选] 行）→ 无法判定。可交易却0买入的天 = %d 天%s"
                    % (vtxt, len(zero_buy),
                       (u"：" + u", ".join(zero_buy)) if zero_buy else u"")))
    elif hits:
        mn = min(r for _, r, _ in hits)
        ok = mn >= 85.0
        res.append((u"P1", ok, u"可交易却0买入的 %d 天里，行业榜+共振合计淘汰占比最低 %.1f%%"
                    u"（阈值>=85%%）" % (len(hits), mn)))
        for d, r, rr in hits[:6]:
            print(u"      %s 过关%d → 行业榜+共振淘汰 %.1f%%" % (d, rr, r))
    else:
        res.append((u"P1", None,
                    u"该次运行没有「可交易却0买入」的天 → 无法判定（不代表预测错）"))

    # P2
    if sel_days:
        rs = sorted(pct(D[d]["sel"]["gates"][u"行业榜"], D[d]["sel"]["rough"])
                    for d in sel_days if D[d]["sel"]["rough"])
        med = rs[len(rs) // 2]
        res.append((u"P2", med >= 70.0,
                    u"「行业榜淘汰/过关」中位数 %.1f%%（阈值>=70%%，%d 天）"
                    % (med, len(rs))))
        # P3
        gtb = sum(1 for d in sel_days
                  if D[d]["sel"]["gates"][u"行业榜"] > D[d]["sel"]["gates"][u"共振"])
        res.append((u"P3", pct(gtb, len(sel_days)) >= 80.0,
                    u"行业榜淘汰 > 共振淘汰 的天占 %.0f%%（阈值>=80%%）"
                    % pct(gtb, len(sel_days))))
    else:
        res.append((u"P2", None, u"日志为 %s，无 [精选] 行 → 无法判定" % vtxt))
        res.append((u"P3", None, u"同上"))

    # P4
    res.append((u"P4", (len(info["zero"]) >= 3) if has_funnel else None,
                u"「候选为0」出现 %d 天（阈值>=3）: %s%s"
                % (len(info["zero"]),
                   u", ".join(d for d, _ in info["zero"]) or u"无",
                   u"" if has_funnel else u"  ← 日志为 %s，无该观测点" % vtxt)))

    # P5（v1.8 起停用：上一轮已证伪 —— "松闸/冻结天数"方向错误，不再是验收目标）
    if vmax >= (1, 8):
        res.append((u"P5", None,
                    u"v1.8 起停用（上一轮已证伪：松闸会放大负期望）→ 改由 Q1-Q5 判定"))
    else:
        res.append((u"P5", (frozen <= 6 and half >= 8) if has_layer else None,
                    u"冻结(HALT+PAUSE)=%d 天（阈值<=6，v1.5 为 %d）｜HALF=%d 天"
                    u"（阈值>=8，v1.5 为 %d）%s"
                    % (frozen, BASE["regime"]["HALT"] + BASE["regime"]["PAUSE"],
                       half, BASE["regime"]["HALF"],
                       u"" if has_layer else u"  ← 日志为 %s，分层闸门未生效" % vtxt)))

    # P6
    res.append((u"P6", (info["mkt"] >= int(len(days) * 0.9)) if has_layer else None,
                u"[大市] 自证行 %d 行（应 >=%.0f）%s"
                % (info["mkt"], len(days) * 0.9,
                   u"" if has_layer else u"  ← 日志为 %s，无该观测点" % vtxt)))

    for name, ok, msg in res:
        mark = u"✅命中" if ok else (u"❌证伪" if ok is False else u"⚠️无法判定")
        print(u"  %s %-12s" % (mark, msg))

    # ③b v1.8 判据 Q1-Q5（台账口径：硬止损占比 / 胜率 / 单笔期望 / 笔数上限）
    if vmax >= (1, 8):
        print(u"\n【③b v1.8 判据 Q1-Q5】")
        try:
            import trade_ledger as _TL
            _ev, _ds, _navs = _TL.parse(path)
            _rows, _nb, _ns, _pos = _TL.build(_ev, _ds)
        except Exception as _e:
            _rows, _nb = [], 0
            print(u"  [X] 台账模块不可用: %s" % _e)
        if _rows:
            _w = [r for r in _rows if r[5] > 0.5]
            _hard = [r for r in _rows if u"硬止损" in r[4]]
            _tot = sum(r[7] for r in _rows)
            _wr = 100.0 * len(_w) / len(_rows)
            _hp = 100.0 * len(_hard) / len(_rows)
            _ex = _tot * 1.0 / len(_rows)
            _sw = any((u"申万一级" in t) and (u"行业数=31" in t) for t in info["ind"])
            q = [
                (u"Q1", _hp <= 35.0,
                 u"硬止损占比 %.1f%% (阈值<=35%%, v1.7 为 50%%) [%d/%d 笔]"
                 % (_hp, len(_hard), len(_rows))),
                (u"Q2", _wr >= 30.0,
                 u"单笔胜率 %.1f%% (阈值>=30%%, v1.7 为 15.6%%)" % _wr),
                (u"Q3", _ex >= 0.0,
                 u"单笔期望 %+.0f 元/笔 (阈值>=0, v1.7 为 -310) ← 唯一真正重要的判据" % _ex),
                (u"Q4", _nb <= 45,
                 u"买入 %d 笔 (阈值<=45, v1.7 为 31) ← 防放开行业闸后笔数暴涨" % _nb),
                (u"Q5", _sw,
                 u"[行业] 自证 申万一级 / 行业数=31 → %s" % (u"命中" if _sw else u"未命中")),
            ]
            for _name, _ok, _msg in q:
                _mark = u"✅命中" if _ok else (u"❌证伪" if _ok is False else u"⚠️无法判定")
                print(u"  %s %-5s %s" % (_mark, _name, _msg))
            if not q[2][1] and not (q[0][1] or q[1][1]):
                print(u"  ⚠️证伪条件触发：Q3 为负 且 Q1/Q2 未改善 → 参数对齐这层已用尽，"
                      u"停止调参，转入场逻辑 alpha 检验")
        elif vmax >= (1, 8):
            print(u"  [X] 台账未解析到成交（日志太短或无成交）")

    # ④ 闸门腿对照
    print(u"\n【④ 闸门腿对照】")
    print(u"  档位分布  : %s" % (u" ".join(u"%s=%d" % (k, cnt[k]) for k in
                                          (u"NORMAL", u"HALF", u"HALT", u"PAUSE") if k in cnt)))
    print(u"  v1.5 基线 : NORMAL=19 HALF=4 HALT=14 PAUSE=2（冻结 %d 天）"
          % (BASE["regime"]["HALT"] + BASE["regime"]["PAUSE"]))
    tot = {}
    for d in sel_days:
        for g, v in D[d]["sel"]["gates"].items():
            tot[g] = tot.get(g, 0) + v
    pool = sum(tot.values())
    if pool:
        print(u"\n  全周期各道闸淘汰总量占比:")
        for g in sorted(tot, key=lambda x: -tot[x]):
            print(u"     %-6s %7d  %5.1f%%" % (g, tot[g], pct(tot[g], pool)))
        print(u"  → 最大杀手 = %s" % sorted(tot, key=lambda x: -tot[x])[0])

    # 仓位
    us = [pct(e["net"][1], e["net"][0]) for d, e in D.items()
          if e["net"] and e["net"][0]]
    if us:
        print(u"\n  平均仓位利用率 = %.1f%%  (v1.5 基线 %.1f%%)"
              % (sum(us) / len(us), BASE["util"]))
        for rg in (u"NORMAL", u"HALF", u"HALT", u"PAUSE"):
            v = [pct(D[d]["net"][1], D[d]["net"][0]) for d in days
                 if D[d]["regime"] == rg and D[d]["net"] and D[d]["net"][0]]
            if v:
                print(u"     %-7s %5.1f%%  (%d 天)" % (rg, sum(v) / len(v), len(v)))

    print(u"\n【⑤ 对照：第九轮蒙特卡洛预测 vs v1.5 实测基线】")
    s = BASE["sim"]
    print(u"  预测 行业层命中率 %.2f%% / 精选层幸存 %.2f 只 / 清空概率 %.1f%%"
          % (s["hit"], s["survive"], s["empty"]))
    if sel_days:
        sv = [D[d]["sel"]["cands"] for d in sel_days]
        print(u"  实测 精选层候选 中位 %d / 均值 %.2f 只 / 候选为0 占 %.0f%%"
              % (sorted(sv)[len(sv) // 2], sum(sv) * 1.0 / len(sv),
                 pct(sum(1 for d in sel_days if D[d]["sel"]["cands"] == 0),
                     len(sel_days))))
    print(u"  → 若实测「候选」中位数 <= 5 且 P1/P2 命中，则第九轮机理判断成立。")
    return 0


if __name__ == u"__main__":
    sys.exit(main())
