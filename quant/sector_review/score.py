# -*- coding: utf-8 -*-
"""
评分 + 10日跟踪 + 复盘 模块
================================
严格实现 bankuai-zhuxian skill 的现行标准（v1）：
  硬门槛 gate: ebb / weak / cold / pass / unknown
  五维打分 s = [时间, 资金, 广度, 位置, 催化]  0-5
  均分 ≥3.5 → 真主线；2.5–3.49 → 真热点；<2.5 → 待验证
  gate 优先：ebb → 退潮观察；cold → 未入围；weak → 封顶真热点
另含：
  - 10 日指数跟踪（真值检验）
  - 与日报实际判定比对
  - 评分维度有效性回溯（各维度与 10 日超额收益的相关性）
"""
import json, os, math, statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
FWD = 10


# ------------------------------------------------------------------ 硬门槛


def calc_gate(r):
    """返回 (gate, gateMsg, ma20, ma10, up3)
    v2 修订（2026-10-29 复盘驱动）：
      原「ebb=退潮一票否决」被证伪为负向——全市场 12810 样本下
      pass 组 10 日超额 -1.82%（t=-18.4，正占比仅 30%），
      ebb 组 -0.95%（正占比 41%）。跌破 20 日线不等于板块死。
      真正区分胜负的是「当日启动强度 z」，故：
        - z>3% 且跌破 20 日线 → 改判 rebound（超跌强反弹，最优信号）
        - z<=3% 且跌破 20 日线 → 仍为 ebb（弱势退潮）
    """
    ma20, ma10, up3 = r["ma20"], r["ma10"], r["up3"]
    z = r.get("z") or 0.0
    if ma20 is False:
        if z > 3:
            return ("rebound",
                    f"超跌强反弹：当日+{z:.2f}%但仍破20日线（趋势未修复、动能已启动）",
                    ma20, ma10, up3)
        return "ebb", f"跌破20日线且当日涨幅仅{z:.2f}%（弱势退潮）", ma20, ma10, up3
    if r.get("br") is not None and r["br"]["zt"] < 2 and (r["f"] or 0) < 0:
        return "cold", f"涨停<2（{r['br']['zt']}家）且主力净流出", ma20, ma10, up3
    if not (ma10 and up3):
        miss = []
        if not ma10:
            miss.append("未站上10日线")
        if not up3:
            miss.append("未连涨3天")
        return "weak", "或".join(miss), ma20, ma10, up3
    return "pass", "全部通过", ma20, ma10, up3


# ------------------------------------------------------------------ 五维打分


def score_time(days):
    if days >= 3:
        return 5
    if days == 2:
        return 4
    if days == 1:
        return 2
    return 1


def score_money(r, flow_hist):
    """资金质量：主力净流入连续 2-3 日为正且中军放量 → 5；单日大额 → 3；流出 → 0-2"""
    f = r.get("f")
    if f is None:
        return None, "无资金流数据"
    consec = r.get("f_consec_pos", 0)
    if f > 0 and consec >= 2:
        # 中军放量：领涨股净流入 + 大单净流入为正
        if (r.get("fs") or 0) > 0 and (r.get("fb") or 0) > 0:
            return 5, "连续净流入+大单同步流入"
        return 4, "连续净流入"
    if f > 0:
        if f >= 3:
            return 3, f"单日净流入{f}亿"
        return 2, f"单日小幅净流入{f}亿"
    if f == 0:
        return 1, "净流入为零"
    return 0, f"净流出{abs(f)}亿"


def score_breadth(r):
    """广度扩散：四位置齐→5；先锋+中军→4；孤龙头→2"""
    br = r.get("br")
    if br is None:
        return None, "无成分股数据"
    n = br["n"]
    if n < 5:
        return None, f"成分股仅{n}只，不足以判梯队"
    ur = br["up_ratio"]
    zt = br["zt"]
    if ur >= 0.85 and zt >= 3:
        return 5, f"普涨{ur:.0%}+涨停{zt}家"
    if ur >= 0.7 and zt >= 2:
        return 4, f"扩散{ur:.0%}+涨停{zt}家"
    if ur >= 0.55:
        return 3, f"扩散{ur:.0%}"
    if ur >= 0.4:
        return 2, f"仅{ur:.0%}上涨"
    return 1, f"上涨占比{ur:.0%}"


def score_position(r):
    """位置过热：低位启动5 / 趋势中段4 / 高位加速2 / 过热爆量1
    用「近 20 日累计涨幅」判定：
      <5% 低位启动 5；5~20% 趋势中段 4；20~45% 高位加速 2；>45% 过热爆量 1
    量比极高（>2.5）且涨幅也高 → 额外降一档
    """
    hist = r.get("hist20")
    if hist is None:
        return None, "无历史数据"
    h = hist
    if h < 5:
        s = 5
    elif h < 20:
        s = 4
    elif h < 45:
        s = 2
    else:
        s = 1
    vb = r.get("vb")
    if vb and vb > 2.5 and s > 1:
        s -= 1
    if s == 5:
        d = "低位启动"
    elif s == 4:
        d = "趋势中段"
    elif s == 2:
        d = "高位加速"
    else:
        d = "过热爆量"
    return s, d


def score_catalyst(r):
    """催化环境：客观代理（无新闻流数据时用可计算代理并标注）
    代理规则（保守，宁可低不高）：
      连续 3 日以上进入候选池 + 资金连续流入 → 4（题材有持续性但无法核业绩）
      仅单日 → 2
    如无法判断 cat 则返回 None，判定就低
    """
    days = r.get("days", 1)
    consec = r.get("f_consec_pos", 0)
    if days >= 3 and consec >= 2:
        return 4, "题材持续+资金持续（业绩/政策待人工核）"
    if days >= 2:
        return 3, "题材有持续性（催化成色待人工核）"
    return 2, "单日题材（催化成色待人工核）"


def score_launch(r):
    """启动强度（新增第 6 维，v2）
    依据全市场 12810 样本实证：当日涨幅 z 与后续 10 日超额呈非线性正相关，
    且在 z>3% 区间显著为正（z>5% 且 ebb 组 +10.88%，正占比 93%）。
    反之 z<3% 的板块无论 gate 如何均为负贡献（pass&z<3% 组 -1.88%，正占比 29%）。
    锚点：z>5 → 5；3<z<=5 → 4；2<z<=3 → 2；0<z<=2 → 1；z<=0 → 0
    """
    z = r.get("z")
    if z is None:
        return None, "无涨幅数据"
    if z > 5:
        return 5, f"强启动+{z:.2f}%"
    if z > 3:
        return 4, f"启动+{z:.2f}%"
    if z > 2:
        return 2, f"温和+{z:.2f}%"
    if z > 0:
        return 1, f"微涨+{z:.2f}%"
    return 0, f"下跌{z:.2f}%"


# ------------------------------------------------------------------ 结论


def conclude(gate, avg):
    """v2 结论分级
    修订要点：
      1) 新增 rebound（超跌强反弹）——实证最优信号，不再一票否决
      2) pass（趋势全确认）不再自动等于主线，需分数真正领先
      3) 门槛整体抬高：现行 2.5/3.5 在 2026-08~10 样本下把 469 个候选
         判成「真热点」，占候选池 73%，严重过宽
    """
    if gate == "cold":
        return "未入围"
    if gate == "ebb":
        return "退潮观察"
    if gate == "rebound":
        # 超跌强反弹：分数需达标方可入选
        return "真主线" if avg >= 3.5 else ("真热点" if avg >= 2.8 else "待验证")
    if gate == "weak":
        return "真热点" if avg >= 3.0 else "待验证"
    if gate == "unknown":
        return "待验证"
    # pass：需明显强于基准才给主线
    return "真主线" if avg >= 4.0 else ("真热点" if avg >= 3.2 else "待验证")


# ------------------------------------------------------------------ 10日跟踪


def forward_stats(series, code, di, alldates, market_ret):
    """选中日之后 FWD 个交易日的指数表现"""
    s = series.get(code)
    if not s:
        return None
    c, ds = s["closes"], s["dates"]
    if di >= len(alldates):
        return None
    end_i = di + FWD
    if end_i >= len(alldates):
        return None                      # 窗口不足 10 日
    d0, d1 = alldates[di], alldates[end_i]
    if d0 not in c or d1 not in c:
        return None
    r10 = (c[d1] / c[d0] - 1) * 100
    m0 = market_ret.get(d0, 0.0)
    # 基准：区间内全板块等权累计
    bench = 0.0
    for d in alldates[di + 1:end_i + 1]:
        bench += market_ret.get(d, 0.0)
    bench /= max(1, end_i - di)
    # 回撤区间内该板块自身的日期索引
    idx0 = ds.index(d0)
    idx1 = ds.index(d1)
    return {
        "d_start": d0, "d_end": d1,
        "r10": round(r10, 2),
        "r10_excess": round(r10 - bench, 2),
        "bench_avg_day": round(bench, 3),
        "mdd": round(_mdd(c, ds, idx0, idx1), 2),
        "still_above_ma20": _above_ma20(c, ds, idx1),
        "hit": (r10 - bench) >= 3.0,       # 超额≥3pp 视为命中
        "hit_weak": (r10 - bench) >= 0.0,
    }


def _mdd(closes, dates, i0, i1):
    peak = closes[dates[i0]]
    mdd = 0.0
    for i in range(i0, i1 + 1):
        v = closes[dates[i]]
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    return mdd


def _above_ma20(closes, dates, i):
    if i < 20:
        return None
    m = sum(closes[dates[i - 20 + k]] for k in range(20)) / 20
    return closes[dates[i]] >= m
