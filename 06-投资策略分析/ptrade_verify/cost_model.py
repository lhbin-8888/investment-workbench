# -*- coding: utf-8 -*-
"""策略可行性的成本敏感度测算（不依赖行情，纯费用/换手数学）"""
import io, sys, os

out = io.StringIO()
def w(s=""): out.write(s + "\n")

# ---- 单次往返成本明细（A股，保守口径）----
COMM = 0.00025 * 2        # 佣金 万2.5 双边
STAMP = 0.0005            # 印花税 卖出单边（2023-08 起 0.05%）
TRANSFER = 0.00001 * 2    # 过户费 双边 0.001%
SLIP_OPT = 0.001 * 2      # 滑点 乐观 0.1% 单边
SLIP_REAL = 0.003 * 2     # 滑点 保守 0.3% 单边（追高/涨停排队实际更差）

w("=" * 68)
w("一、单次完整往返（买+卖）交易成本")
w("=" * 68)
for tag, slip in (("乐观（滑点0.1%/单边）", SLIP_OPT), ("保守（滑点0.3%/单边）", SLIP_REAL)):
    c = (COMM + STAMP + TRANSFER + slip) * 100
    w("  {:<22} 佣金{:.3f}% + 印花{:.3f}% + 过户{:.4f}% + 滑点{:.1f}%  =>  往返 {:.2f}%".format(
        tag, COMM * 100, STAMP * 100, TRANSFER * 100, slip * 100, c))
w("")

# ---- 换手率 ----
POS = 5                     # MAX_POSITIONS
w("=" * 68)
w("二、换手率与年化成本（5 只等权、满仓滚动）")
w("=" * 68)
w("  平均持仓天数   年清仓轮数   年化成本(乐观)   年化成本(保守)")
for hold in (1, 2, 3, 5, 10):
    rounds = 250.0 / hold
    for_pack = (COMM + STAMP + TRANSFER + SLIP_OPT) * 100
    for_pack_r = (COMM + STAMP + TRANSFER + SLIP_REAL) * 100
    w("     {:>3d} 天        {:>6.0f} 轮        {:>7.1f}%        {:>7.1f}%".format(
        hold, rounds, rounds * for_pack, rounds * for_pack_r))
w("")

# ---- 保本所需胜率 ----
w("=" * 68)
w("三、保本胜率：止盈 +10% / 止损 -3%（未计滑点与已计滑点对比）")
w("=" * 68)
TP, SL = 10.0, 3.0
w("  单次往返成本   实际止盈   实际止损   保本胜率")
for tag, cost in (("0.00%（无成本）", 0.0), ("0.30%（乐观）", 0.30),
                  ("0.70%（保守）", 0.70), ("1.00%（追宽停板）", 1.00)):
    tp, sl = TP - cost, SL + cost
    p = sl / (tp + sl) * 100
    w("    {:<14}  {:>6.2f}%    {:>6.2f}%     {:>5.1f}%".format(tag, tp, sl, p))
w("")

# ---- 期望收益敏感性 ----
w("=" * 68)
w("四、不同胜率下的单笔期望（止盈10/止损3，成本0.7%）")
w("=" * 68)
w("  胜率    单笔期望    250日/持仓2.5天≈100笔后资金倍数")
for p in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55):
    exp = p * (10 - 0.7) - (1 - p) * (3 + 0.7)
    mult = (1 + exp / 100) ** 100
    w("   {:>3.0f}%    {:>+7.3f}%     {:>8.2f}x".format(p * 100, exp, mult))
w("")
w("  注：以上未考虑「涨停买不进」导致的逆向选择，实际胜率会低于理论值。")

txt = out.getvalue()
with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "cost_out.txt"), "w", encoding="utf-8") as f:
    f.write(txt)
print("OK")
