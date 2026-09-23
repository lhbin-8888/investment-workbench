# -*- coding: utf-8 -*-
# 行业层口径对撞模拟器（第九轮产物，2026-09-22）
# 用途：量化「融合现行(东财496细分板块)」vs「lhb888(申万31一级行业)」的精选层命中率。
# 改完行业层口径后复跑本脚本，命中率应显著抬升。
"""模拟：两种行业口径下，「103 只粗筛过关候选」最终能活下来几只。

口径 A = 融合现行（东财 496 细分板块 + 只用候选池算均值 + 共振要求候选数>=2）
口径 B = lhb888（申万 31 一级行业 + 全市场算均值 + 行业内样本>=5 才参评）
"""
import io
import json
import random
from collections import Counter

random.seed(20260922)

# ---------- 载入两张表 ----------
em = json.load(io.open(r"D:\投研工作台\quant\hotspot\sector_map.json", encoding="utf-8"))
em_ind = em["industry"]
sw = json.load(io.open(
    r"D:\投研工作台\06-投资策略分析\策略回测\热点追踪lhb888\industry_map.json",
    encoding="utf-8"))

# ---------- 口径 A：复刻 _load_sector_index 的「首次出现优先」 ----------
rev_em = {}
for name, codes in em_ind.items():
    for c in codes:
        k = str(c)
        if k and k not in rev_em:
            rev_em[k] = name

# 全市场股票池（用两张表的并集近似）
pool = sorted(set(rev_em.keys()) | set(sw.keys()))
print("全市场池 = %d 只" % len(pool))
print("东财归属覆盖 = %d 只 | 申万归属覆盖 = %d 只" % (len(rev_em), len(sw)))
print()

N_CAND = 103          # 06-16 实测的粗筛过关数
TOP_N = 10
TRIALS = 3000

def sim_A(n_cand):
    """融合现行口径"""
    cands = random.sample(pool, n_cand)
    pct = {c: random.uniform(0.035, 0.060) for c in cands}
    ind_pct = {}
    ind_cnt = Counter()
    for c in cands:
        ind = rev_em.get(c, "")
        ind_pct.setdefault(ind, []).append(pct[c])
        ind_cnt[ind] += 1
    ind_avg = {k: sum(v) / len(v) for k, v in ind_pct.items()}
    ranked = sorted([(k, v) for k, v in ind_avg.items() if v > 0.0],
                    key=lambda x: -x[1])[:TOP_N]
    strong = set(k for k, _ in ranked)
    # 幸存 = 在强势榜 且 同板块候选数 >= 2
    surv = [c for c in cands
            if rev_em.get(c, "") in strong and ind_cnt[rev_em.get(c, "")] >= 2]
    # 统计：强势榜里有多少个板块满足候选数>=2
    ok_boards = sum(1 for k in strong if ind_cnt[k] >= 2)
    return len(surv), ok_boards, len(ind_pct)


def sim_B(n_cand):
    """lhb888 口径：全市场算行业均值，行业内样本>=5 才参评"""
    # 全市场行业均值（真实收益分布，无截断）
    mkt_pct = {c: random.gauss(0, 0.02) for c in pool}
    ind_bucket = {}
    for c, p in mkt_pct.items():
        n = sw.get(c)
        if n:
            ind_bucket.setdefault(n, []).append(p)
    ind_avg = {k: sum(v) / len(v) for k, v in ind_bucket.items() if len(v) >= 5}
    ranked = sorted(ind_avg.items(), key=lambda x: -x[1])[:TOP_N]
    strong = set(k for k, _ in ranked)
    # 候选（涨幅同口径）
    cands = random.sample(pool, n_cand)
    surv = [c for c in cands if sw.get(c, "") in strong]
    return len(surv), len(strong), len(ind_avg)


a_surv, a_boards, a_inds = [], [], []
b_surv = []
for _ in range(TRIALS):
    s, ok, k = sim_A(N_CAND)
    a_surv.append(s); a_boards.append(ok); a_inds.append(k)
    s2, _, _ = sim_B(N_CAND)
    b_surv.append(s2)

def show(label, arr):
    arr = sorted(arr)
    n = len(arr)
    print("%-28s 均值 %6.2f | 中位 %5.1f | P10 %5.1f | P90 %5.1f | 最大 %5.1f | 为0占比 %5.1f%%"
          % (label, sum(arr) / n, arr[n // 2], arr[int(n * .10)], arr[int(n * .90)],
             arr[-1], 100.0 * sum(1 for x in arr if x == 0) / n))

print("=== %d 只粗筛过关候选 → 精选层幸存的期望值（%d 次模拟）===" % (N_CAND, TRIALS))
show("口径A 融合现行(东财)", a_surv)
show("口径B lhb888(申万一级)", b_surv)
print()
print("=== 口径A 的中间量 ===")
show("  候选池涉及的细分板块数", a_inds)
show("  强势榜Top10里候选数>=2的板块数", a_boards)
print()
print("=== 命中率（均值） ===")
print("口径A = %.2f%%   |  口径B = %.2f%%   |  倍数 = %.1fx"
      % (100.0 * sum(a_surv) / TRIALS / N_CAND,
         100.0 * sum(b_surv) / TRIALS / N_CAND,
         (sum(b_surv) / max(1.0, sum(a_surv)))))
