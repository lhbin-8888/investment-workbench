# -*- coding: utf-8 -*-
"""
热点追踪量化策略 v6.0（第二轮修正版 · 山西证券 PTrade）
==========================================================
基线：v5.0 修正版（v3「热点追踪早盘10：30.py」、v4「_v4优化版.py」、v5「_v5修正版.py」
      三个前序文件均完整保留，本文件独立可跑，互不覆盖）

──────────────────────────────────────────────
一、v5 回测实测（40 个交易日，2026-05-06 ~ 06-30，预设 V5）
──────────────────────────────────────────────
  策略收益  -6.15%   基准 +3.58%   Alpha -0.43   最大回撤 12.47%
  胜率 30.14%        盈亏比 84.84%  平均持仓 2.66 天  盈利 22 / 亏损 51
  对照：v3 +6.67%（胜率 35.94%）｜ v4 -13.94%（胜率 17.78%）
  → v5 比 v4 好（+7.8pct），但仍比 v3 差 12.8pct。

  本次归因（v3 与 v5 区间完全一致，可逐笔配对；金额按「浮盈 × 建仓金额」加权）：

  原因                V3 贡献(元)     V5 贡献(元)     差        n(V5) 均值(V5)
  退潮 破3日线          -37,831        -16,411     +21,420     34    -2.26%
  峰值回撤8%                  0        -13,789     -13,789     11    -7.02%
  止损                  -2,340         -7,548      -5,208      7    -5.53%
  退潮 破20日线              0         -2,664      -2,664      3    -4.97%
  止盈                 +57,910        +52,053      -5,857     26   +16.27%
  ─────────────────────────────────────────────────────────────
  组合贡献合计         +17,739        +11,641      -6,098（≈ -6.1pct）

  四条根因（v6 据此修正）：

  (1)【补仓机制整体为负】REINVEST_ON_SELL 让「风控卖出后当日立即重扫建仓」，
      40 天内触发 21 次、产生 39 笔交易（占全部平仓的 46%）：
          主扫描建仓 43 笔：均值 +4.44%，胜率 53.5%
          补仓建仓   39 笔：均值 +0.48%，胜率 28.2%   ← 质量差 10 倍
      机制缺陷：卖出=风险信号，卖出后立刻买「当日最强势股」≈ 在日内高点接盘；
      且 15 次因当日买入触发 [T+1] 顺延（买完当天就被判要卖，卖不掉）。
      v3 没有这个机制 —— 这是 v5 相对 v3 最大的结构性伤害。

  (2)【巡检分级（HARD 模式）方向做反】v5-3 让 10:00 进入 HARD 模式：
      禁掉「破3日线/破20日线/保本止损/时间止损」（浅出场），
      却保留「峰值回撤 8%」并把「硬止损线从 -5% 放宽到 -8%」。
      实际效果 = 开盘半小时只允许「深亏出场」：
      11 笔峰值回撤中 9 笔在 10:00 触发，卖出浮盈 -1.9% ~ -14.6%（均值 -7.02%）。
      设计者假设「开盘半小时的深亏是噪声」被证伪 —— 隔夜跳空是真实亏损，越晚处理越糟；
      而浅亏才是噪声。两级规则应统一，不应分级。

  (3)【峰值回撤无武装线 + 抢在止损/止盈之前】判定顺序为 1)破均线 → 1b)峰值回撤 → 4)止损，
      且 peak 记录「持仓期间最高价」但不校验浮盈是否为正 ——
      只要买入后一路下跌（peak≈成本），跌 8% 即触发，抢走 -5% 止损的出场权；
      同时它也抢在止盈（步骤 6/7，排在最后）之前。
      对照：v3 同样有这条规则（TRAIL_PCT=0.08），但只有 10:30 单一时点且「破3日线」优先，
      被完全遮蔽 → 0 次触发。v5 拆成 8 个时点后，遮蔽效应失效。

  (4)【止盈质量小幅下降】止盈 26 笔比 v3 多 1 笔，但本金加权贡献少 5,857 元
      （均值 +16.27% vs +17.29%）。巡检时点前移使部分止盈在 10:00 触发（7 笔），
      未等到日内更高点。属次要因素，但方向明确：止盈端是全策略唯一正贡献
      （+5.8% 本金），「让利润奔跑」是后续最大杠杆。

  唯一被验证的正贡献（必须保留）：
      盘中风控巡检（v4-1）—— 破3日线贡献从 -37,831 改善到 -16,411（+21,420 元），
      说明「更早处理浅亏」是对的。v5 的问题不在巡检本身，而在「分级 + 深规则抢跑」把
      它的收益全部抵消（-21,661 元）。

──────────────────────────────────────────────
二、v6.0 修正内容（回到 v3 的出场纪律，保留巡检）
──────────────────────────────────────────────
【v6-1】关闭补仓机制（对应根因 1）
        REINVEST_ON_SELL=False：风控卖出释放的额度不再当日重扫建仓，次日主流程再用。
        建仓日内部的「跳单额度顺延 + 回填」保留（那是纯资金利用效率，不是换仓闭环）。
        预期：消除 39 笔低质量交易，同时把 15 次 T+1 顺延降为 0。

【v6-2】取消巡检分级（对应根因 2）
        OPEN_NOISE_CUTOFF=""：8 个巡检时点执行与 10:30 完全相同的规则集，
        止损线统一为 -5%（不再有 HARD 模式的 -8% 放宽）。
        理由：浅出场规则（破3日线）必须在所有时点可触发 —— 它是最早、最便宜的止损。

【v6-3】峰值回撤改为「武装式」并后移（对应根因 3）
        新增 TRAIL_ARM_PCT=+5%：只有峰值浮盈曾达到 +5%，峰值回撤才启用。
        判定位置从步骤 1b 移到步骤 8（止盈之后）。
        预期：消除 11 笔（-13,789 元）在浮亏状态下的「伪跟踪止盈」，
        把它们交还给 -5% 止损或破3日线（更浅）。

【v6-4】保留项
        盘中风控巡检 8 时点（唯一正贡献）、建仓日预算回收（顺延+回填）、
        情绪闸门（区间内空转但无害）、板块共振 SOFT（覆盖率不足自动降级 OFF）、
        按原因归因的平仓统计。

【v6-5】可选：让利润奔跑（RUN_PROFIT_MODE，仅预设 P6 开启）
        "OFF"（默认）：沿用 v3 的 +10% 减半 / +15% 清仓。
        "TRAIL"：+15% 不再直接清仓，改由移动止盈接管（峰值回撤 TP_TRAIL_PCT=5% 才走）。
        目的：止盈 26 笔是本策略唯一的正贡献来源，把它从均值 +16% 拉到 +20%+ 的杠杆
        远大于在亏损端抠参数。上线前必须与 V6 做 A/B 对比。

──────────────────────────────────────────────
三、参数预设（只改 PARAM_PRESET 一行）
──────────────────────────────────────────────
  "V6" 修正版（默认）—— v6-1 ~ v6-4 生效，出场框架回到 v3 纪律 + 保留巡检
  "P6" V6 + 让利润奔跑 —— 在 V6 基础上把 +15% 清仓改为移动止盈（单独验证收益杠杆）
  "R5" v5 结构复现     —— 复现 v5 的「巡检分级 + 当日补仓」两项结构特征
                          注意：v6-3 把峰值回撤的判定位置统一移到了步骤 8（全预设生效），
                          因此 R5 无法复现 v5 的「峰值回撤抢在止损之前」这一顺序缺陷。
                          若需完整复现 -6.15%，请直接使用「热点追踪早盘10：30_v5修正版.py」。
  "D"  v3 基线复现      —— 用于复核 +6.67%

  建议跑法（一次只验证一个变量）：
    第 1 步  D  vs  V6   → 检验「巡检 + 关补仓 + 峰值回撤武装」的净效果
    第 2 步  V6 vs  P6   → 检验「让利润奔跑」是否值得开

⚠️ 实盘自动交易风险自负。建议先以 TRADE_ENABLED=False 跑信号模式或模拟盘验证。
"""

# ============================================================
# 一、参数配置区（基础值 = 预设 A 推荐值）
# ============================================================
VERSION = "v6.0"
PARAM_PRESET = "V6"            # "V6"/"P6"/"R5"/"R0"/"D"，见文件头说明；只改这一行即可切换

TRADE_ENABLED = True           # True=自动下单；False=信号模式（只输出热点榜与风控信号）
SIGNAL_TIME = "10:30"          # 每日选股/买入执行时间（handle_data 触发）

# ---- 扫描方式 ----
SCAN_MODE = "FULL"             # FULL=全市场批量粗筛（推荐）；SAMPLE=抽样（慢环境兜底）
SAMPLE_RATIO = 0.5             # SAMPLE 模式下的抽样比例
SAMPLE_ROTATE = True           # 抽样是否按日期轮换（避免同一批票永远扫不到）
LOOKBACK_DETAIL = 90           # 细评回看天数（> MIN_HIST_BARS，留出停牌余量）
DETAIL_POOL = 60               # 粗筛后进入细评的候选数（v3=40；v4 提高以便板块聚合统计更稳）
BATCH_SIZE = 300               # 每批批量取数的标的数量

# ---- 标的过滤 ----
MIN_HIST_BARS = 60             # 上市历史最少 K 线数
MIN_AMOUNT = 5e8               # 【v4-4】当日成交额下限（元），v3=3e8，收紧过滤杂毛票
REQUIRE_NO_ST = True           # 剔除 ST / *ST / 退市整理
EXCLUDE_KCB = False            # 不剔除科创板（本版科创板有专属涨幅档，需开通权限）
ALLOW_BOARDS = ("SS", "SZ")    # 允许交易的交易所后缀；北交所("BJ")默认排除

# ---- 选股（按板块分档的当日涨幅区间）----
GAIN_RANGE = {
    "main": (3.0, 4.0),        # 主板（沪 60 / 深 00）：3%~4%，上限低于涨停，天然不追板
    "kcb":  (6.0, 8.0),        # 科创板 688：6%~8%
    "cyb":  (6.0, 8.0),        # 创业板 300/301：6%~8%
}
ALLOW_LIMIT_UP_BUY = False     # True=允许买入已封涨停的票（高风险，成交率低）
LIMIT_UP_BUFFER = 0.005        # 涨停判定缓冲：现价 >= 涨停价*(1-缓冲) 视为封板
MIN_VOL_RATIO = 1.5            # 【v4-4】量比下限（v3=1.2），放量确认更严格
REQUIRE_ABOVE_MA20 = True      # 必须站上 20 日线
MAX_OPEN_PCT = 0.0             # 【v5-2】当日开盘涨幅上限(%)；0=不限制（v4 为 5.0，40 天内误杀 261 次含 13.75% 高开龙头）
                               # 强势确认改由 BUY_PULLBACK_FILTER/PULLBACK_OPEN_BREAK 承担（要求 现价>=开盘价）
USE_INTRADAY_VOL_RATIO = False # 【v4-4】True=量比改用「今日 10:30 累计分时量 / 昨日全日量 × 节奏系数」
                               # 说明：默认 False 时沿用 v3 口径（昨日量/前5日均量）。v3 口径本质是
                               #      「昨日量比」，不是当日放量；打开本开关才是真正的当日放量确认，
                               #      但依赖分钟成交量的单位与完整性，建议先跑 D→A 对照再决定是否常开。
INTRADAY_VOL_PACE = 0.25       # 10:30 时点约完成全日成交的 25%（折算当日预期量比用）
INTRADAY_VOL_MIN_BARS = 30     # 分时 bars 少于该数时不折算（退化为日线近似，防数据缺失误判）

# ---- 仓位与风控 ----
MAX_POSITIONS = 6              # 【v4-5】最大同时持仓数（v3=5），提高额度周转
POSITION_VALUE_RATIO = 0.17    # 单票目标市值 / 总资产
CASH_BUFFER = 0.10             # 保留现金比例（1 - 此为可投上限）
STOP_LOSS_PCT = 0.05           # 单票浮亏止损

# ---- 分批止盈（+10% 减半，+15% 或破线清仓）----
TP_HALF_PCT = 0.10             # 浮盈达到 +10%：减半仓（仅触发一次）
TP_FULL_PCT = 0.15             # 浮盈达到 +15%：清仓
TP_MA = 5                      # 兼容保留
EXIT_MA = 3                    # 破 N 日线即清仓（预设 B 收紧到 2）
RETREAT_MA = 20                # 跌破 20 日线 = 退潮清仓（兜底）
TRAIL_PCT = 0.08               # 【v5-6】峰值回撤跟踪止盈；回归 v3 值（v4 的 6% 无正贡献：4 笔均值 -1.28%，属噪声触发）
TRAIL_ARM_PCT = 0.05           # 【v6-3】峰值回撤的「武装线」：仅当峰值浮盈曾 >= +5% 才启用该规则。
                               #   v5 实测：无武装线时 11 笔全部亏损、均值 -7.02%、贡献 -13,789 元
                               #   —— 买入后一路下跌的票（peak≈成本）也会在 -8% 触发，抢走 -5% 止损的出场权。
MAX_HOLD_DAYS = 5              # 【v5-6】时间止损（亏损票）：持有超过 N 个交易日无条件退出；回归 v3 值（v4=4）

# ---- 【v6-5】让利润奔跑（可选，仅预设 P6 开启）----
#   止盈是本策略唯一的正贡献来源（v5：26 笔、本金加权 +52,053 元 ≈ +5.2pct）。
#   "OFF"   = 沿用 v3：+10% 减半、+15% 清仓
#   "TRAIL" = +15% 不再直接清仓，改由移动止盈接管（自峰值回撤 TP_TRAIL_PCT 才走），让主升段跑完
RUN_PROFIT_MODE = "OFF"        # "OFF"（默认）/ "TRAIL"
TP_TRAIL_PCT = 0.05            # TRAIL 模式：自持仓峰值回撤该比例即清仓

# ---- 保本止损（减半后启用）----
BREAKEVEN_STOP = True          # True=减半后启用保本止损
BREAKEVEN_BUF = 0.0            # 保本价相对成本价的缓冲

# ---- 【v5-1】弱离场（默认关闭）----
# v4 实测：弱离场 47 笔、均值 -1.79%、累计 -83.9%、胜率 0%，其中 37 笔「持有1日」、30 笔在 10:00 触发
#          → 实为「买入次日开盘半小时内不赚即砍」，系统性地把正常震荡卖在局部低点。
# 且「破 EXIT_MA 日线」已覆盖「走弱」语义，本项冗余，默认关闭。
WEAK_EXIT_MODE = "OFF"         # "OFF"=关闭（默认，推荐）/ "CONFIRM"=确认式：持有>=2日 且 浮亏<=-2% 才砍
WEAK_EXIT_DAYS = 2             # CONFIRM 模式：持有 >= N 个自然日后开始判定
WEAK_EXIT_PCT = -0.02          # CONFIRM 模式：浮盈 <= 该阈值才清仓

# ---- 【v4-1】盘中风控巡检（v6-2：已废止分级，所有时点同规则）----
INTRADAY_RISK_ENABLED = True   # True=盘中按 INTRADAY_RISK_TIMES 多次跑风控
INTRADAY_RISK_TIMES = ("10:00", "11:00", "11:20", "13:10", "13:45", "14:15", "14:45", "14:55")
# 注：10:30 由主流程统一执行（扫描+风控+建仓），此处不再重复，避免重复日志与重复处理
# 【v6-2】OPEN_NOISE_CUTOFF 置空 = 取消 HARD 分级，所有巡检时点执行与 10:30 完全相同的规则集。
#   v5 实测：HARD 分级在 10:00 禁掉「破3日线/破20日线/保本止损/时间止损」（浅出场），
#   却保留「峰值回撤8%」、并把硬止损线从 -5% 放宽到 -8% → 开盘半小时只剩深亏出场，
#   11 笔峰值回撤中 9 笔在 10:00 以 -7.02% 均值成交。设计假设（开盘深亏是噪声）被证伪：
#   隔夜跳空是真实亏损、越晚处理越糟；浅亏才是噪声。故分级废止。
#   保留该参数仅为「R5」预设复现 v5 行为之用。
OPEN_NOISE_CUTOFF = ""
HARD_MODE_STOP_PCT = 0.08      # HARD 模式允许的硬止损线（仅 R5 预设复现用；V6 下永不进入 HARD 模式）

# ---- 【v4-2】大盘情绪闸门 ----
SENTIMENT_GATE_ENABLED = True  # True=启用情绪闸门
SENTIMENT_MODE = "HALF"        # "HALF"=冰点预算减半（默认，温和）；"STOP"=冰点当日不建仓
SENTIMENT_HALF_FACTOR = 0.5    # HALF 模式下的预算系数
ZT_PREMIUM_FLOOR = -2.0        # 昨日涨停股今日平均溢价(%)低于此 → 冰点
STRONG_GATE_MODE = "RATIO"     # 强势股判定口径："COUNT"=绝对家数（原设计）/ "RATIO"=占全市场比例
                               # 说明：绝对家数门槛与股票池容量强相关（5000 只市场与 1000 只市场不可比），
                               #      默认用比例口径，跨市场容量/跨年份更稳定。
MIN_STRONG_RATIO = 0.02        # RATIO 模式：涨幅 >= STRONG_GAIN_PCT 的家数占比低于此 → 冰点
MIN_STRONG_COUNT = 30          # COUNT 模式：绝对家数下限
STRONG_GAIN_PCT = 5.0          # 强势股涨幅定义(%)
MIN_ZT_COUNT_FOR_GATE = 5      # 昨日涨停股样本少于该数时不判定（数据不足，放行）
ZT_HIT_RATIO = 0.98            # 昨日涨幅 >= 涨停幅度*该系数 即计入「昨日涨停股」

# ---- 【v4-3】板块共振 ----
SECTOR_MODE = "SOFT"           # "OFF"=关闭 / "SOFT"=共振票加权（默认，不丢信号） / "HARD"=只留共振票
MIN_SECTOR_ALIGN = 2           # 同行业至少 N 只进候选池才算共振
SECTOR_BONUS_W = 2.0           # 软模式：每只共振成员给 score 的加分（上限见 SECTOR_BONUS_CAP）
SECTOR_BONUS_CAP = 4           # 软模式：共振人数计入加分的上限
SECTOR_PENALTY = 0.75          # 软模式：非共振票 score 折扣系数
SECTOR_COVERAGE_FLOOR = 0.5    # 行业字段解析覆盖率低于此 → 本次自动关闭板块过滤

# ---- 【v4-5 / v5-5】建仓预算回收 ----
BUDGET_RECYCLE = True          # True=跳单额度顺延/回填，尽量用满预算（v3 有 8 次因高价股空仓，保留）
RECYCLE_ROUNDS = 3             # 最多回填轮数（每轮对未触顶标的追加）
MAX_RECYCLE_BUYS_PER_DAY = 2   # 【v5-5】每日补建仓笔数上限，防止「砍仓→立刻买新票→次日再砍」的高频轮动闭环

# ---- 【v4-5 延伸】尾盘补仓（默认关闭，作为可选收益来源）----
TAIL_SCAN_ENABLED = False      # True=14:45 后若仍有空位/闲钱，用当日实时价重扫补建仓
TAIL_TIME = "14:45"

# ---- 【v4-1 延伸 / v6-1】风控卖出释放额度当日是否立即补仓 ----
# v6-1 改为 False。实测依据（v5，40 天）：
#   主扫描建仓 43 笔：均值 +4.44%、胜率 53.5%
#   补仓建仓   39 笔：均值 +0.48%、胜率 28.2%   ← 占全部平仓 46%，质量差 10 倍
# 机制缺陷：卖出本身是风险信号，卖出后立刻买「当日最强势股」= 在日内高点接盘；
#   且有 15 次因当日买入触发 [T+1] 顺延（买完当天就被判要卖、卖不掉）。
# 说明：「建仓日内部的跳单额度顺延 + 回填」不受此开关影响，仍由 BUDGET_RECYCLE 负责。
REINVEST_ON_SELL = False       # False=卖出释放的额度次日主流程再用（推荐）；True=v5 旧行为

# ---- 收益优化（沿用 v3 的两道开关）----
STRENGTH_WEIGHT = True         # True=按强度分档分配；False=等权
STRENGTH_EXP = 1.6             # 强度权重指数（越大越集中于最强票）
MAX_SINGLE_RATIO = 0.22        # 【v4-5】单票上限（占总资产比例），v3=0.30
BUY_PULLBACK_FILTER = True     # True=开启分时回踩过滤
PULLBACK_OPEN_BREAK = True     # True=要求 cur>=open（回踩不破开盘价）

# ---- 成本假设（回测用）----
SLIPPAGE = 0.003               # 滑点（追高品种偏保守加压）

# ---- 统计与日志 ----
STATS_DAILY_LOG = True         # True=每日收盘打印累计平仓统计（胜率/按原因分组）
QUIET_EMPTY_POSITION = True    # True=无持仓时不打印风控日志（盘中巡检会跑多次）

# ---- 成交量单位校准基准 ----
CALIB_CODES = ("600519.SS", "601318.SS", "600036.SS", "000001.SZ")


# ============================================================
# 一之二、参数预设（六项独立开关 + 参数网格）
# ============================================================
_PRESETS = {
    # V6 修正版（默认）：关补仓 + 取消巡检分级 + 峰值回撤武装 + 保留巡检
    "V6": dict(
        MAX_POSITIONS=6, POSITION_VALUE_RATIO=0.17, MAX_SINGLE_RATIO=0.22,
        MIN_VOL_RATIO=1.5, MIN_AMOUNT=5e8, MAX_OPEN_PCT=0.0,
        GAIN_RANGE={"main": (3.0, 4.0), "kcb": (6.0, 8.0), "cyb": (6.0, 8.0)},
        EXIT_MA=3, TRAIL_PCT=0.08, TRAIL_ARM_PCT=0.05, MAX_HOLD_DAYS=5,
        RUN_PROFIT_MODE="OFF", TP_TRAIL_PCT=0.05,
        WEAK_EXIT_MODE="OFF", WEAK_EXIT_DAYS=2, WEAK_EXIT_PCT=-0.02,
        INTRADAY_RISK_ENABLED=True, INTRADAY_RISK_TIMES=("10:00", "11:00", "11:20",
        "13:10", "13:45", "14:15", "14:45", "14:55"),
        OPEN_NOISE_CUTOFF="", HARD_MODE_STOP_PCT=0.08,
        REINVEST_ON_SELL=False,
        SENTIMENT_GATE_ENABLED=True, SENTIMENT_MODE="HALF",
        # 板块共振关闭：v5 实测该功能「假生效」——420 条候选记录的板块人数全为 x1
        # （416 条「行业名==股票名」，说明本平台的行业字段实际返回了名称），从未发生共振，
        # SOFT 加权对全部候选同比例施加，排序不变、只白白消耗 get_stock_info 调用。
        # 待确认平台的真实行业字段来源后，单独立项验证，不在本轮混改。
        SECTOR_MODE="OFF", MIN_SECTOR_ALIGN=2, DETAIL_POOL=60,
        BUDGET_RECYCLE=True, RECYCLE_ROUNDS=3, MAX_RECYCLE_BUYS_PER_DAY=2,
        TAIL_SCAN_ENABLED=False,
    ),
    # P6 让利润奔跑：在 V6 基础上把「+15% 清仓」改为移动止盈（单项 A/B，验证收益杠杆）
    "P6": dict(
        MAX_POSITIONS=6, POSITION_VALUE_RATIO=0.17, MAX_SINGLE_RATIO=0.22,
        MIN_VOL_RATIO=1.5, MIN_AMOUNT=5e8, MAX_OPEN_PCT=0.0,
        GAIN_RANGE={"main": (3.0, 4.0), "kcb": (6.0, 8.0), "cyb": (6.0, 8.0)},
        EXIT_MA=3, TRAIL_PCT=0.08, TRAIL_ARM_PCT=0.05, MAX_HOLD_DAYS=5,
        RUN_PROFIT_MODE="TRAIL", TP_TRAIL_PCT=0.05,
        WEAK_EXIT_MODE="OFF", WEAK_EXIT_DAYS=2, WEAK_EXIT_PCT=-0.02,
        INTRADAY_RISK_ENABLED=True, INTRADAY_RISK_TIMES=("10:00", "11:00", "11:20",
        "13:10", "13:45", "14:15", "14:45", "14:55"),
        OPEN_NOISE_CUTOFF="", HARD_MODE_STOP_PCT=0.08,
        REINVEST_ON_SELL=False,
        SENTIMENT_GATE_ENABLED=True, SENTIMENT_MODE="HALF",
        SECTOR_MODE="OFF", MIN_SECTOR_ALIGN=2, DETAIL_POOL=60,
        BUDGET_RECYCLE=True, RECYCLE_ROUNDS=3, MAX_RECYCLE_BUYS_PER_DAY=2,
        TAIL_SCAN_ENABLED=False,
    ),
    # R5 v5 复现：用于在同一次回测环境复核 -6.15% 这个基线（含 HARD 分级与补仓）
    "R5": dict(
        MAX_POSITIONS=6, POSITION_VALUE_RATIO=0.17, MAX_SINGLE_RATIO=0.22,
        MIN_VOL_RATIO=1.5, MIN_AMOUNT=5e8, MAX_OPEN_PCT=0.0,
        GAIN_RANGE={"main": (3.0, 4.0), "kcb": (6.0, 8.0), "cyb": (6.0, 8.0)},
        EXIT_MA=3, TRAIL_PCT=0.08, TRAIL_ARM_PCT=0.0, MAX_HOLD_DAYS=5,
        RUN_PROFIT_MODE="OFF", TP_TRAIL_PCT=0.05,
        WEAK_EXIT_MODE="OFF", WEAK_EXIT_DAYS=2, WEAK_EXIT_PCT=-0.02,
        INTRADAY_RISK_ENABLED=True, INTRADAY_RISK_TIMES=("10:00", "11:00", "11:20",
        "13:10", "13:45", "14:15", "14:45", "14:55"),
        OPEN_NOISE_CUTOFF="10:30", HARD_MODE_STOP_PCT=0.08,
        REINVEST_ON_SELL=True,
        SENTIMENT_GATE_ENABLED=True, SENTIMENT_MODE="HALF",
        SECTOR_MODE="SOFT", MIN_SECTOR_ALIGN=2, DETAIL_POOL=60,
        BUDGET_RECYCLE=True, RECYCLE_ROUNDS=3, MAX_RECYCLE_BUYS_PER_DAY=2,
        TAIL_SCAN_ENABLED=False,
    ),
    # R0 v4 预设 A 复现：用于在同一次回测环境复核 -13.94% 基线，确认定位无误
    "R0": dict(
        MAX_POSITIONS=6, POSITION_VALUE_RATIO=0.17, MAX_SINGLE_RATIO=0.22,
        MIN_VOL_RATIO=1.5, MIN_AMOUNT=5e8, MAX_OPEN_PCT=5.0,
        GAIN_RANGE={"main": (3.0, 4.0), "kcb": (6.0, 8.0), "cyb": (6.0, 8.0)},
        EXIT_MA=3, TRAIL_PCT=0.06, TRAIL_ARM_PCT=0.0, MAX_HOLD_DAYS=4,
        RUN_PROFIT_MODE="OFF", TP_TRAIL_PCT=0.05,
        WEAK_EXIT_MODE="ON", WEAK_EXIT_DAYS=1, WEAK_EXIT_PCT=0.0,
        INTRADAY_RISK_ENABLED=True, INTRADAY_RISK_TIMES=("10:00", "11:00", "11:20",
        "13:10", "13:45", "14:15", "14:45", "14:55"),
        OPEN_NOISE_CUTOFF="", HARD_MODE_STOP_PCT=0.08,
        REINVEST_ON_SELL=False,
        SENTIMENT_GATE_ENABLED=True, SENTIMENT_MODE="HALF",
        SECTOR_MODE="SOFT", MIN_SECTOR_ALIGN=2, DETAIL_POOL=60,
        BUDGET_RECYCLE=True, RECYCLE_ROUNDS=3, MAX_RECYCLE_BUYS_PER_DAY=0,
        TAIL_SCAN_ENABLED=False,
    ),
    # D v3 基线复现：六项改造全关、参数回 v3 原值（对照回测用）
    "D": dict(
        MAX_POSITIONS=5, POSITION_VALUE_RATIO=0.18, MAX_SINGLE_RATIO=0.30,
        MIN_VOL_RATIO=1.2, MIN_AMOUNT=3e8, MAX_OPEN_PCT=0.0,
        GAIN_RANGE={"main": (3.0, 4.0), "kcb": (6.0, 8.0), "cyb": (6.0, 8.0)},
        EXIT_MA=3, TRAIL_PCT=0.08, TRAIL_ARM_PCT=0.0, MAX_HOLD_DAYS=5,
        RUN_PROFIT_MODE="OFF", TP_TRAIL_PCT=0.05,
        WEAK_EXIT_MODE="OFF", DETAIL_POOL=40,
        INTRADAY_RISK_ENABLED=False,
        OPEN_NOISE_CUTOFF="",
        REINVEST_ON_SELL=False,
        SENTIMENT_GATE_ENABLED=False,
        SECTOR_MODE="OFF",
        BUDGET_RECYCLE=False, TAIL_SCAN_ENABLED=False,
    ),
}
PRESET_APPLIED = str(PARAM_PRESET).upper() if str(PARAM_PRESET).upper() in _PRESETS else "V6"
for _k, _v in _PRESETS[PRESET_APPLIED].items():
    globals()[_k] = _v


# ============================================================
# 二、通用工具
# ============================================================
def _suffix(code):
    """6 位代码 -> PTrade 代码。补齐北交所 43/83/87/88/92 段。"""
    code = str(code)
    if "." in code:
        return code
    if code.startswith(("60", "68", "51", "58", "11")):
        return code + ".SS"
    if code.startswith(("00", "30", "12", "15", "16")):
        return code + ".SZ"
    if code.startswith(("43", "83", "87", "88", "92", "8", "4")):
        return code + ".BJ"
    return code


def _pure(code):
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _board(code):
    c = _pure(code)
    if c.startswith(("43", "83", "87", "88", "92", "8", "4")):
        return "BJ"
    if c.startswith("68"):
        return "SS"
    if c.startswith(("60", "51", "58", "11")):
        return "SS"
    return "SZ"


def _is_kcb(code):
    return _pure(code).startswith("688")


def _limit_pct(code, name):
    """涨跌停幅度：ST 5% / 主板 10% / 创业板科创板 20% / 北交所 30%"""
    if "ST" in str(name).upper() or "退" in str(name):
        return 0.05
    return _limit_pct_by_code(code)


def _limit_pct_by_code(code):
    """【v4-2】不查名称的涨跌停幅度（用于全市场批量统计昨日涨停股，避免 5000 次名称调用）。
    副作用（已知且可接受）：ST 的 5% 涨停不会被计入「昨日涨停股」，等价于把 ST 排除出情绪样本。
    """
    c = _pure(code)
    if c.startswith(("43", "83", "87", "88", "92", "8", "4")):
        return 0.30
    if c.startswith(("30", "68")):
        return 0.20
    return 0.10


def _gain_range(code):
    """返回 (当日涨幅下限%, 上限%) 或 None（该板块不参与选股）。"""
    c = _pure(code)
    if c.startswith("688"):
        return GAIN_RANGE.get("kcb")
    if c.startswith(("300", "301")):
        return GAIN_RANGE.get("cyb")
    if c.startswith(("43", "83", "87", "88", "92", "8", "4")):
        return None          # 北交所默认排除
    return GAIN_RANGE.get("main")


def _ma(vals, n):
    if not vals or len(vals) < n:
        return None
    seg = vals[-n:]
    if any(v is None for v in seg):
        return None
    return sum(seg) / n


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def _mean(xs):
    return (sum(xs) / float(len(xs))) if xs else 0.0


def _has(name):
    return globals().get(name) is not None


# ---- 日志降级包装（不同 PTrade 版本 log 支持的方法不一致，避免因日志方法缺失中断策略）----
_WARNED = set()


def _warn(msg):
    try:
        log.warning(msg)
    except Exception:
        log.info(msg)


def _dbg(msg):
    try:
        log.debug(msg)
    except Exception:
        pass


def _warn_once(key, msg):
    if key in _WARNED:
        return
    _WARNED.add(key)
    _warn(msg)


# ============================================================
# 三、行情取数层（多签名容错 + 批量）
# ============================================================
def _to_panel(raw, fields):
    """把各种返回形态归一为 {code: {field: [values...], 'date': [...]}}"""
    out = {}

    def _from_df(code, df):
        cols = getattr(df, "columns", None)
        idx = getattr(df, "index", None)
        n = len(df)
        p = {}
        for f in fields:
            try:
                if cols is not None and f in list(cols):
                    p[f] = [float(x) for x in list(df[f])]
                else:
                    p[f] = []
            except Exception:
                p[f] = []
        if idx is not None:
            p["date"] = [str(x) for x in list(idx)][:n]
        if any(p.get(f) for f in fields):
            out[code] = p

    if raw is None:
        return out
    if isinstance(raw, dict):
        val_keys = [k for k, v in raw.items() if isinstance(v, (list, tuple))]
        if val_keys and all(k in fields or k == "date" for k in val_keys):
            return {"__single__": {k: list(v) for k, v in raw.items()}}
        for code, v in raw.items():
            if v is None:
                continue
            if isinstance(v, dict):
                p = {}
                for f in fields:
                    try:
                        p[f] = [float(x) for x in v.get(f, [])]
                    except Exception:
                        p[f] = []
                if "date" in v:
                    p["date"] = [str(x) for x in v["date"]]
                out[code] = p
            else:
                _from_df(code, v)
        return out
    if isinstance(raw, (list, tuple)):
        return out
    _from_df("__single__", raw)
    return out


def _fetch_panel(codes, count, fields, log_tag="", quiet=False, freq="1d"):
    """批量取数，多签名容错。返回 {code: panel}。freq: '1d' 日线 / '1m' 分钟线。"""
    codes = list(codes)
    if not codes or count <= 0:
        return {}
    err = []

    if _has("get_history"):
        try:
            raw = get_history(count, freq, list(fields), codes)
            p = _to_panel(raw, fields)
            p.pop("__single__", None)
            if p:
                return p
        except Exception as e:
            err.append("sig1:" + repr(e))
        merged = {}
        ok = False
        for f in fields:
            try:
                raw = get_history(count, freq, f, codes)
                p = _to_panel(raw, [f])
                p.pop("__single__", None)
                if p:
                    ok = True
                    for c, v in p.items():
                        merged.setdefault(c, {}).update(v)
            except Exception as e:
                err.append("sig2({}):".format(f) + repr(e))
        if ok and merged:
            return merged

    if _has("get_price"):
        try:
            raw = get_price(codes, None, None, freq, list(fields), count=count)
            p = _to_panel(raw, fields)
            p.pop("__single__", None)
            if p:
                return p
        except Exception as e:
            err.append("sig3:" + repr(e))
        merged = {}
        ok = False
        for c in codes:
            try:
                raw = get_price(c, None, None, freq, list(fields), fq="pre", count=count)
                p = _to_panel(raw, fields)
                s = p.get("__single__")
                if s:
                    merged[c] = s
                    ok = True
            except Exception as e:
                err.append("sig4:" + repr(e))
                break
        if ok and merged:
            return merged

    if log_tag and not quiet:
        log.error("[取数失败] {} : {}".format(log_tag, " | ".join(err[:4])))
    return {}


def _current_price(data, code):
    """从 handle_data 的 data 对象取「当日实时价」。多签名尝试，取不到返回 None。"""
    if data is None:
        return None
    for method in ("current", "get"):
        fn = getattr(data, method, None)
        if not callable(fn):
            continue
        for field in ("price", "close", "last_price", "lastPrice"):
            try:
                v = fn(code, field)
                if v:
                    return float(v)
            except Exception:
                pass
    try:
        d = data[code]
        if d is not None:
            if isinstance(d, (int, float)):
                return float(d)
            for attr in ("price", "close", "last_price", "lastPrice"):
                try:
                    v = d[attr] if isinstance(d, dict) else getattr(d, attr, None)
                    if v:
                        return float(v)
                except Exception:
                    pass
    except Exception:
        pass
    return None


def _diag_data(data):
    if data is None:
        log.info("[口径] handle_data 的 data 参数为 None（该平台可能不支持 data 取当日价）")
        return
    try:
        attrs = [a for a in dir(data) if not a.startswith("_")][:30]
        log.info("[口径] data 对象类型={} 可用方法={}".format(type(data).__name__, attrs))
    except Exception as e:
        log.info("[口径] data 对象诊断失败: {}".format(repr(e)))


# ============================================================
# 四、启动自检
# ============================================================
DIAG = {
    "vol_scale": 1.0,
    "has_today_bar": None,
    "api": {},
    "industry_api": None,
    "intraday_ok": None,
}


def _diag_api():
    names = ("get_history", "get_price", "get_Ashares", "get_all_stocks",
             "get_positions", "get_position", "order", "order_value",
             "order_target", "order_target_value", "run_daily",
             "get_stock_name", "get_total_assets", "get_datetime",
             "get_stock_industry", "get_industry", "get_stock_info")
    for n in names:
        DIAG["api"][n] = _has(n)
    missing = [n for n in ("get_Ashares", "get_history", "order") if not DIAG["api"].get(n)]
    if missing:
        log.error("[自检] 关键接口缺失: {} —— 策略无法工作，请核对 PTrade 版本".format(missing))
    else:
        log.info("[自检] 关键接口齐全")
    # 【v4-3】行业接口可用性对板块共振至关重要，单独明示
    ind = [n for n in ("get_stock_industry", "get_industry", "get_stock_info")
           if DIAG["api"].get(n)]
    DIAG["industry_api"] = ind[0] if ind else None
    if SECTOR_MODE != "OFF":
        if ind:
            log.info("[自检] 行业接口可用: {} → 板块共振({})生效".format(ind, SECTOR_MODE))
        else:
            _warn("[自检] 未发现行业接口（get_stock_industry / get_industry / get_stock_info）"
                  "→ 板块共振【v4-3】自动降级为关闭，其余改造不受影响")


def _diag_vol_scale():
    """用大盘蓝筹校准成交量单位。优先用真实成交额 money，取不到再用 volume*close。"""
    panel = _fetch_panel(list(CALIB_CODES), 1, ["close", "volume"], "成交量校准")
    mp = _fetch_panel(list(CALIB_CODES), 1, ["money"], "成交量校准", quiet=True)
    est = []
    for c, p in panel.items():
        try:
            mv = (mp.get(c) or {}).get("money") or []
            if mv and mv[-1]:
                est.append(float(mv[-1]))
            elif p.get("close") and p.get("volume"):
                est.append(float(p["close"][-1]) * float(p["volume"][-1]))
        except Exception:
            pass
    if not est:
        log.error("[自检] 无法校准成交量单位（基准票取数失败），按「股」处理；"
                  "若后续热点榜恒为空，请手工核对 MIN_AMOUNT")
        return
    med = _median(est)
    log.info("[自检] 基准票额估算中位数 = {:.2e} 元".format(med))
    if med < 5e7:
        DIAG["vol_scale"] = 100.0
        log.error("[自检] 成交量单位疑似「手」，已自动 x100 换算；"
                  "若你确认接口返回的就是股，请手工把 DIAG['vol_scale'] 改回 1.0")
    else:
        log.info("[自检] 成交量单位判定为「股」，无需换算")


def _diag_cutoff(context):
    """检测日线是否含当日 bar、分钟线是否可得（决定「当日涨幅」口径是否生效）。"""
    probe = _fetch_panel(list(CALIB_CODES)[:2], 2, ["close"], "cutoff检测")
    last_date = None
    for c, p in probe.items():
        if p.get("date"):
            last_date = p["date"][-1]
            break
    today = _context_date(context)
    has_today = (last_date is not None and today is not None
                 and str(last_date)[:10] == str(today)[:10])
    mprobe = _fetch_panel(list(CALIB_CODES)[:2], 1, ["close"], "cutoff检测", quiet=True, freq="1m")
    has_minute = bool(mprobe) and any((mprobe.get(c) or {}).get("close") for c in mprobe)
    DIAG["has_today_bar"] = has_today
    DIAG["intraday_ok"] = has_minute

    if has_today:
        log.info("[自检] 日线已含当日 bar：涨幅按「当日涨幅」计算")
    elif has_minute:
        log.info("[自检] 日线不含当日 bar，但分钟线可得 → 涨幅按「当日实时价/昨收」计算")
    else:
        log.error("[自检] 日线不含当日 bar 且分钟线不可得 → 涨幅实际是「昨日涨幅」，"
                  "与「当日涨幅」口径不符；请确认平台是否支持 1m 分钟数据")
    if INTRADAY_RISK_ENABLED and not has_minute:
        _warn("[自检] 分钟线不可得 → 盘中风控巡检【v4-1】将无法按 8 个时点触发，"
              "退化为每日一次；如需该功能请在分钟级回测/实盘运行")


def _context_date(context):
    for path in ("blotter.current_dt", "current_dt", "now"):
        try:
            obj = context
            for a in path.split("."):
                obj = getattr(obj, a)
            return str(obj)[:10]
        except Exception:
            continue
    try:
        return str(get_datetime())[:10]
    except Exception:
        return None


def _now_hhmm(context):
    """读取当前 HH:MM；取不到返回 ''（日频回测常见）。"""
    for path in ("blotter.current_dt", "current_dt", "now"):
        try:
            obj = context
            for a in path.split("."):
                obj = getattr(obj, a)
            s = str(obj)
            if len(s) >= 16:
                return s[11:16]
        except Exception:
            continue
    try:
        s = str(get_datetime())
        if len(s) >= 16:
            return s[11:16]
    except Exception:
        pass
    return ""


# ============================================================
# 五、股票池
# ============================================================
_POOL_CACHE = None


def _get_market_pool():
    global _POOL_CACHE
    if _POOL_CACHE:
        return _POOL_CACHE
    for fn_name in ("get_Ashares", "get_all_stocks"):
        if not _has(fn_name):
            continue
        try:
            pool = globals()[fn_name]()
            if isinstance(pool, dict):
                pool = list(pool.keys())
            if isinstance(pool, list) and pool and isinstance(pool[0], dict):
                pool = [x.get("code") or x.get("symbol") for x in pool]
            pool = [_suffix(str(x)) for x in pool if x]
            if EXCLUDE_KCB:
                pool = [c for c in pool if not _is_kcb(c)]
            pool = [c for c in pool if c.split(".")[-1] in ALLOW_BOARDS]
            if pool:
                _POOL_CACHE = pool
                excl_kcb = "已剔除科创板、" if EXCLUDE_KCB else ""
                log.info("[扫描] 股票池 {} 只（{}北交所(BJ)排除；ALLOW_BOARDS={}）".format(
                    len(pool), excl_kcb, ALLOW_BOARDS))
                return pool
        except Exception as e:
            log.error("[扫描] {} 不可用: {}".format(fn_name, repr(e)))
    log.error("[扫描] 无可用股票池接口（get_Ashares / get_all_stocks 均失败）")
    return []


# ============================================================
# 六、名称 / ST 过滤
# ============================================================
_NAME_CACHE = {}
_ST_WARNED = False


def _stock_name(code):
    global _ST_WARNED
    if code in _NAME_CACHE:
        return _NAME_CACHE[code]
    name = ""
    if _has("get_stock_name"):
        for arg in (code, _pure(code)):
            try:
                v = get_stock_name(arg)
                if v is None:
                    continue
                if isinstance(v, dict):
                    if arg in v:
                        v = v.get(arg)
                    elif v:
                        v = list(v.values())[0]
                    else:
                        v = ""
                if v:
                    name = str(v)
                    break
            except Exception:
                continue
    else:
        if not _ST_WARNED:
            _ST_WARNED = True
            log.error("[过滤] 平台无 get_stock_name，ST/退市过滤已失效！"
                      "请改用其它名称接口或维护一只黑名单")
    _NAME_CACHE[code] = name
    return _NAME_CACHE[code]


def _is_bad_name(code):
    if not REQUIRE_NO_ST:
        return False
    n = _stock_name(code).upper()
    return ("ST" in n) or ("退" in n) or ("PT" in n)


# ============================================================
# 七、【v4-3】行业解析层（板块共振的数据底座）
# ============================================================
_IND_CACHE = {}
_IND_FN = [None, False]      # [函数名, 是否已探测]


_IND_EMPTY = ("", "none", "nan", "nat", "null", "-", "unknown")


def _dig_industry(v, code):
    """从任意接口返回值里挖出行业名（dict/list/DataFrame/裸字符串都能吃）。取不到返回 ''。

    【v5-4】v4 的 _industry_of 只认 get_stock_industry/get_industry/get_industry_info，
    而本平台实际只提供 get_stock_info —— 取值全部落空，所有候选的行业同为空字符串，
    聚合后 sector_cnt 恒等于候选总数，板块共振形同虚设（436 次无效调用）。
    此处补齐 get_stock_info 的多签名调用与深度解析。
    """
    if v is None:
        return ""
    try:
        if not isinstance(v, (dict, list, tuple, set, str)) and hasattr(v, "to_dict"):
            v = v.to_dict()
    except Exception:
        pass
    if isinstance(v, dict):
        for k in ("industry", "industry_name", "sw_industry", "board", "industryCode"):
            if v.get(k):
                return str(v[k]).strip()
        for kk in (code, _pure(code)):
            if kk in v:
                r = _dig_industry(v[kk], code)
                if r:
                    return r
        for vv in v.values():
            r = _dig_industry(vv, code)
            if r:
                return r
        return ""
    if isinstance(v, (list, tuple, set)):
        for x in v:
            r = _dig_industry(x, code)
            if r:
                return r
        return ""
    s = str(v).strip()
    return "" if s.lower() in _IND_EMPTY else s


def _industry_of(code):
    """返回行业名（字符串）；解析不到返回 ''。多接口容错 + 缓存，绝不抛异常。"""
    if code in _IND_CACHE:
        return _IND_CACHE[code]
    ind = ""
    # 1) 专用行业接口（若平台提供）
    if not _IND_FN[1]:
        _IND_FN[1] = True
        _IND_FN[0] = None
        for fn in ("get_stock_industry", "get_industry", "get_industry_info"):
            if _has(fn):
                _IND_FN[0] = fn
                break
    if _IND_FN[0]:
        f = globals()[_IND_FN[0]]
        for arg in (code, _pure(code)):
            try:
                r = _dig_industry(f(arg), code)
                if r:
                    ind = r
                    break
            except Exception:
                continue
    # 2)【v5-4】get_stock_info 多签名兜底
    if not ind and _has("get_stock_info"):
        gsi = globals()["get_stock_info"]
        for args in ((code, ["industry"]), (code, "industry"), (code,)):
            try:
                r = _dig_industry(gsi(*args), code)
                if r:
                    ind = r
                    break
            except Exception:
                continue
    _IND_CACHE[code] = ind
    return ind


# ============================================================
# 八、主流程：粗筛 -> 细评 -> 【v4-3】板块聚合 -> 排序
# ============================================================
SCAN_META = {}      # 供 _daily_routine 读取（情绪/板块/粗筛快照摘要）


def scan_market(context, data=None):
    """返回候选列表（已按 score 降序）；同时把当日市场摘要写入 SCAN_META。"""
    global SCAN_META
    SCAN_META = {}
    pool = _get_market_pool()
    if not pool:
        log.error("[扫描] 股票池为空，本轮放弃（请查看上方接口自检）")
        return []

    if SCAN_MODE == "SAMPLE" and SAMPLE_RATIO < 1.0:
        step = max(1, int(round(1.0 / SAMPLE_RATIO)))
        if SAMPLE_ROTATE:
            d = _context_date(context) or ""
            off = sum(ord(ch) for ch in d) % step if d else 0
        else:
            off = 0
        codes = pool[off::step]
        log.info("[扫描] 抽样模式：{}/{}，日期偏移 {}".format(len(codes), len(pool), off))
    else:
        codes = pool

    # ---- Stage 1：批量粗筛（当日涨幅 + 成交额 + 【v4-2】昨日涨幅）----
    snap = {}
    n_batch = 0
    n_cur_ok = 0
    n_cur_miss = 0
    _sample_done = False
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        tag = "粗筛批次{}".format(i // BATCH_SIZE + 1)
        # count=3：多留一根，用于计算「昨日涨幅」（情绪闸门的关键输入）
        p = _fetch_panel(batch, 3, ["close", "price", "volume"], tag, freq="1d")
        mp = _fetch_panel(batch, 3, ["money"], tag, quiet=True, freq="1d")
        m1 = _fetch_panel(batch, 1, ["close"], tag, quiet=True, freq="1m")
        n_batch += 1
        for c, v in p.items():
            cl = v.get("close") or []
            pl = v.get("price") or []
            if len(cl) < 2 or not cl[-2]:
                continue
            prev_close = cl[-1]      # 日线不含当日，最后一根 = 昨收
            prev2_close = cl[-2]     # 前日收盘 → 昨日涨幅 = prev/prev2 - 1
            yest_pct = ((prev_close / prev2_close - 1) * 100.0) if prev2_close else None
            vol = (v.get("volume") or [0, 0])[-1] or 0
            mv = (mp.get(c) or {}).get("money") or []
            amt = float(mv[-1]) if mv and mv[-1] else 0.0
            if not amt:
                amt = float(vol) * DIAG["vol_scale"] * prev_close
            cur_data = _current_price(data, c) if data is not None else None
            cur = cur_data
            if not cur or abs(cur - prev_close) < 1e-9:
                cur = pl[-1] if pl else None
            if not cur or abs(cur - prev_close) < 1e-9:
                mcl = (m1.get(c) or {}).get("close") or []
                cur = mcl[-1] if mcl else None
            if not _sample_done:
                _sample_done = True
                log.info("[口径] 样本 {} 昨收={} data价={} price字段={} 分钟close={}".format(
                    c, prev_close, cur_data, pl[-1] if pl else None,
                    (m1.get(c) or {}).get("close", [None])[-1] if m1.get(c) else None))
            if cur and abs(cur - prev_close) > 1e-9:
                pct = (cur / prev_close - 1) * 100.0
                n_cur_ok += 1
            else:
                pct = (prev_close / prev2_close - 1) * 100.0
                cur = None
                n_cur_miss += 1
            snap[c] = {"pct": pct, "amt": amt, "cur": cur,
                       "prev_close": prev_close, "prev2_close": prev2_close,
                       "yest_pct": yest_pct}
    log.info("[扫描] 粗筛完成：{} 只，批量请求 {} 次（当日价{}只 / 回退昨日{}只）".format(
        len(snap), n_batch, n_cur_ok, n_cur_miss))
    if n_cur_miss and not n_cur_ok:
        log.error("[扫描] 当日价取不到（price 字段与分钟线均=昨收），已回退「昨日涨幅」；"
                  "请查看上方 [口径] 样本日志确认字段语义")

    if not snap:
        log.error("[扫描] 粗筛结果为空！通常是取数接口不兼容或成交额单位错误，请向上翻查看自检日志")
        return []

    # ---- 【v4-2】情绪指标（用粗筛快照零成本计算）----
    senti = _market_sentiment(snap)
    SCAN_META["sentiment"] = senti

    # ---- 粗筛条件：按板块涨幅区间 + 成交额 ----
    rough = []
    for c, s in snap.items():
        rng = _gain_range(c)
        if rng is None:
            continue
        lo, hi = rng
        if lo <= s["pct"] <= hi and s["amt"] >= MIN_AMOUNT:
            rough.append((c, s))
    if not rough:
        samp = sorted(snap.items(), key=lambda kv: -kv[1]["pct"])[:3]
        log.info("[扫描] 粗筛后无候选。当前市场最强 3 只参考: " + "；".join(
            "{} 涨幅{:.2f}% 额{:.2e}".format(c, s["pct"], s["amt"]) for c, s in samp))
        return []
    rough.sort(key=lambda kv: -kv[1]["pct"])
    detail_codes = [c for c, _ in rough[:DETAIL_POOL]]
    log.info("[扫描] 进入细评 {} 只（量比下限{}，成交额下限{:.1e}，高开上限{}%）".format(
        len(detail_codes), MIN_VOL_RATIO, MIN_AMOUNT,
        "不限" if MAX_OPEN_PCT <= 0 else MAX_OPEN_PCT))

    # ---- Stage 2：细评 ----
    cands = []
    for i in range(0, len(detail_codes), 20):
        batch = detail_codes[i:i + 20]
        p = _fetch_panel(batch, LOOKBACK_DETAIL,
                         ["close", "high", "low", "volume"], "细评批次")
        intraday = _intraday_ranges(batch)
        for c in batch:
            v = p.get(c)
            if not v:
                continue
            a = _assess(c, v, snap.get(c, {}), intraday.get(c))
            if a:
                cands.append(a)

    # ---- 【v4-3】板块共振聚合 ----
    cands, sec_note = _apply_sector_align(cands)
    SCAN_META["sector_note"] = sec_note

    cands.sort(key=lambda x: x["score"], reverse=True)
    top = cands[:MAX_POSITIONS * 2]
    log.info("=" * 60)
    log.info("[热点榜] 今日候选 Top{}（强度分|涨幅|连板|量比|MA20|板块x人数）:".format(len(top)))
    for a in top:
        log.info("  {} {} 分{} +{}% 连板{} 量比{} MA20:{} 板[{}x{}]".format(
            a["code"], a["name"], a["score"], a["pct"], a["lianban"],
            a["vol_ratio"], "是" if a["above20"] else "否",
            a.get("industry") or "-", a.get("sector_cnt", 0)))
    if not top:
        log.error("[扫描] 细评后无候选（全部被可买性/形态/门槛过滤），今日不建仓")
    return top


def _market_sentiment(snap):
    """【v4-2】用粗筛快照计算市场情绪。

    指标：
      zt_premium  昨日涨停股今日 10:30 平均涨幅(%)（经典「打板溢价」，情绪最灵敏的温度计）
      zt_count    昨日涨停股样本数
      strong_cnt  今日 10:30 涨幅 >= STRONG_GAIN_PCT 的只数（今日做多热情）
      median_pct  全市场当日涨幅中位数（广度）
      up_ratio    上涨家数占比
    只统计「当日价可得(cur 有效)」的标的，避免混入昨日口径污染。
    """
    zt_pcts = []
    strong_cnt = 0
    up_cnt = 0
    valid = []
    for c, s in snap.items():
        cur_ok = s.get("cur") is not None and s.get("pct") is not None
        if not cur_ok:
            continue
        pct = s["pct"]
        valid.append(pct)
        if pct >= STRONG_GAIN_PCT:
            strong_cnt += 1
        if pct > 0:
            up_cnt += 1
        yp = s.get("yest_pct")
        if yp is None:
            continue
        lim_pct = _limit_pct_by_code(c) * 100.0
        if yp >= lim_pct * ZT_HIT_RATIO:
            zt_pcts.append(pct)
    info = {
        "zt_count": len(zt_pcts),
        "zt_premium": _mean(zt_pcts),
        "strong_cnt": strong_cnt,
        "strong_ratio": (strong_cnt / float(len(valid))) if valid else 0.0,
        "median_pct": _median(valid),
        "up_ratio": (up_cnt / float(len(valid))) if valid else 0.0,
        "valid_cnt": len(valid),
    }
    log.info("[情绪] 昨日涨停 {} 只，今日均溢价 {:+.2f}%；今日涨幅>={}% 的 {} 只（占比{:.2%}）；"
             "中位涨幅 {:+.2f}%；上涨占比 {:.1%}（样本{}）".format(
                 info["zt_count"], info["zt_premium"], STRONG_GAIN_PCT,
                 info["strong_cnt"], info["strong_ratio"], info["median_pct"],
                 info["up_ratio"], info["valid_cnt"]))
    return info


def _sentiment_verdict(senti):
    """返回 (状态, 预算系数, 说明)。状态: OK / HALF / STOP。"""
    if not SENTIMENT_GATE_ENABLED:
        return "OK", 1.0, "闸门关闭"
    if not senti:
        return "OK", 1.0, "无情绪数据"
    if senti.get("zt_count", 0) < MIN_ZT_COUNT_FOR_GATE:
        return "OK", 1.0, "涨停样本不足({}<{})".format(
            senti.get("zt_count", 0), MIN_ZT_COUNT_FOR_GATE)
    cold_premium = senti.get("zt_premium", 0.0) < ZT_PREMIUM_FLOOR
    if STRONG_GATE_MODE == "COUNT":
        cold_strong = senti.get("strong_cnt", 0) < MIN_STRONG_COUNT
        strong_txt = "强势股{}只<{}只".format(senti.get("strong_cnt", 0), MIN_STRONG_COUNT)
    else:
        cold_strong = senti.get("strong_ratio", 0.0) < MIN_STRONG_RATIO
        strong_txt = "强势股占比{:.2%}<{:.2%}".format(
            senti.get("strong_ratio", 0.0), MIN_STRONG_RATIO)
    if not (cold_premium or cold_strong):
        return "OK", 1.0, "情绪健康"
    why = []
    if cold_premium:
        why.append("涨停溢价{:+.2f}%<{}%".format(senti["zt_premium"], ZT_PREMIUM_FLOOR))
    if cold_strong:
        why.append(strong_txt)
    detail = "；".join(why)
    if SENTIMENT_MODE == "STOP":
        return "STOP", 0.0, "情绪冰点({" + detail + "}) → 当日停买"
    return "HALF", SENTIMENT_HALF_FACTOR, "情绪冰点({" + detail + "}) → 预算减半"


def _apply_sector_align(cands):
    """【v4-3】板块共振。返回 (候选列表, 说明)。行业数据不可用/覆盖率过低时自动降级。"""
    if SECTOR_MODE == "OFF" or not cands:
        return cands, "关闭"
    cnt = {}
    known = 0
    for a in cands:
        ind = _industry_of(a["code"]) or ""
        a["industry"] = ind
        if ind:
            known += 1
            cnt[ind] = cnt.get(ind, 0) + 1
    cover = known / float(len(cands))
    if cover < SECTOR_COVERAGE_FLOOR:
        _warn_once("sector_low_cover",
                   "[板块] 行业字段覆盖率 {:.0%} < {:.0%} → 本次自动关闭板块共振（不干预选股）".format(
                       cover, SECTOR_COVERAGE_FLOOR))
        for a in cands:
            a["sector_cnt"] = 0
        return cands, "覆盖率{:.0%}降级".format(cover)
    for a in cands:
        a["sector_cnt"] = cnt.get(a.get("industry") or "", 0)
    groups = sorted([(v, k) for k, v in cnt.items() if v >= MIN_SECTOR_ALIGN], reverse=True)
    note = "覆盖{:.0%}；共振组{}个（最强{}x{}）".format(
        cover, len(groups), groups[0][1] if groups else "-", groups[0][0] if groups else 0)
    if SECTOR_MODE == "HARD":
        keep = [a for a in cands if a["sector_cnt"] >= MIN_SECTOR_ALIGN]
        if not keep:
            _warn("[板块] 硬过滤后无共振票（今日无板块效应）→ 本日不建仓")
            return [], note + "；硬过滤后为空"
        return keep, note + "；硬过滤{}只".format(len(keep))
    # SOFT：共振票加分、孤立票折价（不丢信号）
    for a in cands:
        n = min(a["sector_cnt"], SECTOR_BONUS_CAP)
        if a["sector_cnt"] >= MIN_SECTOR_ALIGN:
            a["score"] = a["score"] + n * SECTOR_BONUS_W
        else:
            a["score"] = a["score"] * SECTOR_PENALTY
    hit = sum(1 for a in cands if a["sector_cnt"] >= MIN_SECTOR_ALIGN)
    return cands, note + "；软加权（共振{}/{}）".format(hit, len(cands))


def _pass_pullback(cur, o, h, lo):
    """10:30 分时回踩过滤。无当日价/无开盘价数据时退化为「不过滤」，保证不静默丢信号。"""
    if not BUY_PULLBACK_FILTER:
        return True
    if not cur:
        return True
    if PULLBACK_OPEN_BREAK and o is not None and cur < o:
        return False
    return True


def _intraday_ranges(codes):
    """聚合当日分钟线，返回 {code: {"open","high","low","vol","bars"}}。
    vol = 当日截至当前时点的累计分钟成交量（用于【v4-4】真实量比折算）。"""
    out = {}
    if not codes:
        return out
    try:
        m = _fetch_panel(list(codes), 330, ["open", "high", "low", "close", "volume"],
                         "分时区间", quiet=True, freq="1m")
        for c in codes:
            d = m.get(c) or {}
            o = d.get("open") or []
            h = d.get("high") or []
            l = d.get("low") or []
            v = d.get("volume") or []
            if not h:
                continue
            out[c] = {"open": (float(o[0]) if o else None),
                      "high": float(max(h)),
                      "low": (float(min(l)) if l else None),
                      "vol": (float(sum(v)) if v else 0.0),
                      "bars": len(h)}
    except Exception:
        pass
    return out


def _assess(code, v, snap, intraday=None):
    """细评：形态/量能/可买性 + 【v4-4】高开防线。返回候选 dict 或 None。"""
    closes = [x for x in (v.get("close") or []) if x]
    vols = v.get("volume") or []
    if len(closes) < MIN_HIST_BARS:
        return None

    rng = _gain_range(code)
    if rng is None:
        return None
    lo, hi = rng

    cur = snap.get("cur")
    prev_close = snap.get("prev_close") or (closes[-1] if closes else None)
    if not prev_close:
        return None
    if not cur:
        cur = closes[-1]
    if not cur:
        return None

    name = _stock_name(code)
    if _is_bad_name(code):
        return None

    pct = (cur / prev_close - 1) * 100.0
    if pct < lo or pct < 0 or pct > hi:
        return None

    o = (intraday or {}).get("open")

    # ---- 【v4-4】高开防线：开盘涨幅过高 → 冲高回落风险大，不参与 ----
    open_pct = ((o / prev_close - 1) * 100.0) if (o and prev_close) else None
    if MAX_OPEN_PCT > 0 and open_pct is not None and open_pct > MAX_OPEN_PCT:
        log.info("[高开] {} 跳过（开盘{:+.2f}% > 上限{}%）".format(code, open_pct, MAX_OPEN_PCT))
        return None

    # ---- 分时回踩过滤 ----
    if not _pass_pullback(cur, o, None, None):
        _of = "{:.2f}".format(o) if o is not None else "NA"
        log.info("[回踩] {} 跳过（cur={:.2f} open={}：跌破开盘价，动量转弱）".format(
            code, cur, _of))
        return None

    # ---- 可买性：涨停判定 ----
    lim = _limit_pct(code, name)
    limit_up = round(prev_close * (1 + lim), 2)
    sealed = cur >= limit_up * (1 - LIMIT_UP_BUFFER)
    if sealed and not ALLOW_LIMIT_UP_BUY:
        return None

    # 量能：默认沿用 v3 口径（昨日量/前5日均量，实为「昨日量比」）；
    #       【v4-4】USE_INTRADAY_VOL_RATIO=True 时改用「今日分时累计量 / 昨日全日量 × 节奏系数」，
    #       这才是真正的「当日放量」确认。
    vs = [x for x in vols if x]
    ma5v = sum(vs[-6:-1]) / 5.0 if len(vs) >= 6 and sum(vs[-6:-1]) > 0 else 0.0
    vol_ratio = (vs[-1] / ma5v) if ma5v else 0.0
    vol_src = "昨日"
    if USE_INTRADAY_VOL_RATIO and vs:
        ivol = (intraday or {}).get("vol") or 0.0
        bars = (intraday or {}).get("bars") or 0
        yday_vol = vs[-1] or 0.0
        if ivol > 0 and bars >= INTRADAY_VOL_MIN_BARS and yday_vol > 0:
            pace = min(max(float(INTRADAY_VOL_PACE), 0.05), 1.0)
            vol_ratio = ivol / (yday_vol * pace)
            vol_src = "分时"
    if vol_ratio < MIN_VOL_RATIO:
        return None

    # 连板（日线历史，不含当日）
    lb = 0
    for i in range(len(closes) - 1, 0, -1):
        if not closes[i - 1]:
            break
        if (closes[i] / closes[i - 1] - 1) * 100.0 >= lim * 100 * 0.95:
            lb += 1
        else:
            break

    full = closes + [cur]
    ma10, ma20, ma60 = _ma(full, 10), _ma(full, 20), _ma(full, 60)
    above20 = bool(ma20 and cur > ma20)
    above60 = bool(ma60 and cur > ma60)
    if REQUIRE_ABOVE_MA20 and not above20:
        return None
    shape = (1 if (ma10 and cur > ma10) else 0) + (2 if above20 else 0) + (3 if above60 else 0)

    score = pct + lb * 6.0 + min(vol_ratio, 3.0) * 8.0 + shape * 1.5
    return {"code": code, "name": name, "pct": round(pct, 2), "lianban": lb,
            "vol_ratio": round(vol_ratio, 2), "vol_src": vol_src, "above20": above20,
            "above60": above60, "score": round(score, 2), "price": cur,
            "open_pct": (round(open_pct, 2) if open_pct is not None else None),
            "industry": "", "sector_cnt": 0}


# ============================================================
# 九、持仓与风控
# ============================================================
_CODE_FIELDS = ("security", "code", "stock_code", "symbol", "instrument",
                "order_book_id", "asset", "stock", "stockcode", "stockCode",
                "instrument_id", "sInfoCode")
_AMOUNT_FIELDS = ("current_amount", "total_amount", "amount", "position",
                  "volume", "current_quantity", "total_quantity",
                  "currentAmount", "totalAmount", "qty")
_ENABLE_FIELDS = ("enable_amount", "available_amount", "sellable_amount",
                  "avail_amount", "available_quantity", "sellable",
                  "enableAmount", "availableAmount", "sellableAmount")
_COST_FIELDS = ("cost_price", "avg_price", "cost_basis", "avg_cost",
                "open_cost", "pre_cost", "cost",
                "costPrice", "avgPrice", "costBasis", "avgCost")


def _pos_f(p, name):
    try:
        if isinstance(p, dict):
            return p.get(name)
        return getattr(p, name, None)
    except Exception:
        return None


def _pos_field(p, names):
    if p is None:
        return None
    if isinstance(p, dict):
        for n in names:
            v = p.get(n)
            if v is not None and v != "":
                return v
        return None
    for n in names:
        try:
            v = getattr(p, n)
            if v is not None and v != "":
                return v
        except Exception:
            continue
    return None


def _describe(p):
    if p is None:
        return "None"
    if isinstance(p, dict):
        keys = list(p.keys())[:15]
        return "dict keys={}".format(keys)
    try:
        attrs = [a for a in dir(p) if not a.startswith("_")][:30]
        return "obj<{}> attrs={}".format(type(p).__name__, attrs)
    except Exception:
        return repr(p)[:150]


def _first_item(raw):
    if isinstance(raw, dict):
        for k, v in raw.items():
            return v if v is not None else k
        return None
    if isinstance(raw, (list, tuple)):
        return raw[0] if raw else None
    return raw


def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def _parse_positions(raw):
    out = {}
    items = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            items.append((k, v))
    elif isinstance(raw, (list, tuple)):
        for v in raw:
            items.append((None, v))
    elif raw is not None:
        items.append((None, raw))

    for k, v in items:
        if v is None:
            continue
        code = None
        if not isinstance(v, (str, int, float)):
            code = _pos_field(v, _CODE_FIELDS)
        if not code and isinstance(k, str):
            c = _suffix(_pure(k))
            if c and c.split(".")[-1] in ("SS", "SZ", "BJ", "XSHE", "XSHG", "BSE"):
                code = k
        if not code and isinstance(k, str) and len(_pure(k)) == 6:
            code = k
        if code:
            out[_suffix(_pure(str(code)))] = v
    return out


def positions_map(context=None):
    out = {}
    try:
        out = _parse_positions(get_positions())
        if out:
            return out
    except Exception as e:
        log.error("[持仓] get_positions 异常: {}".format(repr(e)))

    if context is None:
        return out
    pf = getattr(context, "portfolio", None)
    if pf is None:
        return out

    for attr in ("positions", "long_positions"):
        pp = getattr(pf, attr, None)
        if pp:
            out = _parse_positions(pp)
            if out:
                log.info("[持仓] portfolio.{} 读到 {} 只".format(attr, len(out)))
                return out

    bp = getattr(pf, "base_portfolio", None)
    if bp is not None:
        for attr in ("positions", "long_positions"):
            pp = getattr(bp, attr, None)
            if pp:
                out = _parse_positions(pp)
                if out:
                    log.info("[持仓] base_portfolio.{} 读到 {} 只".format(attr, len(out)))
                    return out
        for acc_name in ("stock_account", "accounts"):
            acc = getattr(bp, acc_name, None)
            if acc is None:
                continue
            candidates = acc.items() if isinstance(acc, dict) else [(acc_name, acc)]
            for subname, sub in candidates:
                if sub is None:
                    continue
                pp = getattr(sub, "positions", None)
                if pp:
                    out = _parse_positions(pp)
                    if out:
                        log.info("[持仓] base_portfolio.{}.positions 读到 {} 只".format(
                            subname, len(out)))
                        return out

    if _has("get_position"):
        try:
            p = get_position()
            code = _pos_field(p, _CODE_FIELDS) if not isinstance(p, (str, int, float)) else None
            if code:
                out[_suffix(_pure(str(code)))] = p
        except Exception as e:
            log.error("[持仓] get_position 回退异常: {}".format(repr(e)))

    if not out:
        log.info("[持仓] 持仓为空（信号模式下属正常）")
    return out


# ---- 【v4-6】平仓统计（按原因归因，收盘打印）----
STATS = {"n": 0, "win": 0, "loss": 0, "sum": 0.0, "half_n": 0, "by_reason": {}}


def _record_trade(reason_key, rt):
    try:
        STATS["n"] += 1
        STATS["sum"] += rt
        if rt > 0:
            STATS["win"] += 1
        else:
            STATS["loss"] += 1
        d = STATS["by_reason"].get(reason_key)
        if d is None:
            d = [0, 0.0]
            STATS["by_reason"][reason_key] = d
        d[0] += 1
        d[1] += rt
    except Exception:
        pass


def report_stats():
    if not STATS_DAILY_LOG:
        return
    n = STATS["n"]
    if n <= 0:
        log.info("[统计] 尚无平仓记录")
        return
    wr = STATS["win"] / float(n)
    avg = STATS["sum"] / float(n)
    log.info("[统计] 累计平仓 {} 笔 | 胜率 {:.1%} | 平均单笔浮盈 {:+.2%} | 累计(未加权) {:+.1%}".format(
        n, wr, avg, STATS["sum"]))
    for k in sorted(STATS["by_reason"].keys(), key=lambda x: -STATS["by_reason"][x][0]):
        c, s = STATS["by_reason"][k]
        log.info("       {:<18} n={:<3} 均值{:+.2%} 累计{:+.1%}".format(k, c, s / float(c), s))


def _sell_all(code, px, reason, reason_key="", rt=0.0, entry_today=False):
    """清仓：只用可卖数量，优先 order_target。entry_today=True 时 T+1 不可卖属正常，降级为 INFO。"""
    enable = _to_int(_pos_field(px, _ENABLE_FIELDS))
    if enable <= 0:
        msg = "[T+1] {} 可卖数量 0（今日买入或已挂单），本次{}顺延至下一交易日".format(code, reason)
        if entry_today:
            log.info(msg)
        else:
            log.error("[卖出失败] " + msg)
        return False
    if not TRADE_ENABLED:
        log.info("[信号] 应清仓 {} —— {}".format(code, reason))
        _record_trade(reason_key or "信号", rt)
        return True
    try:
        if _has("order_target"):
            order_target(code, 0)
        else:
            order(code, -enable)
        log.info("[卖出] {} 数量{} —— {}".format(code, enable, reason))
        _record_trade(reason_key or "其它", rt)
        return True
    except Exception as e:
        log.error("[卖出异常] {} : {}".format(code, repr(e)))
        return False


def _sell_half(code, px, reason, reason_key="止盈减半", rt=0.0):
    """减半：卖出可卖量的一半（enable_amount），只触发一次。"""
    enable = _to_int(_pos_field(px, _ENABLE_FIELDS))
    if enable <= 0:
        log.error("[卖出失败] {} 可卖数量为 {}（T+1 未交收或已挂单），减半顺延至下一交易日".format(code, enable))
        return False
    qty = enable // 2
    if qty <= 0:
        log.error("[卖出失败] {} 可卖量 {} 过小，无法减半".format(code, enable))
        return False
    if not TRADE_ENABLED:
        log.info("[信号] 应减半 {} 卖{}股 —— {}".format(code, qty, reason))
        STATS["half_n"] += 1
        return True
    try:
        if _has("order"):
            order(code, -qty)
        elif _has("order_target"):
            cur = _to_int(_pos_field(px, _AMOUNT_FIELDS))
            order_target(code, max(0, cur - qty))
        log.info("[卖出] {} 减半卖{}股 —— {}".format(code, qty, reason))
        STATS["half_n"] += 1
        return True
    except Exception as e:
        log.error("[卖出异常] {} : {}".format(code, repr(e)))
        return False


def monitor_risk(context, data=None, quiet_empty=None, tag="", stage="NORMAL"):
    """逐票风控。判定优先级（命中即处理下一票）：

      1) 破 EXIT_MA 日线                     → 清仓（最早、最便宜的出场）
      2) 破 RETREAT_MA(20) 日线               → 清仓（兜底）
      3) 保本止损（仅已减半票）                → 清仓
      4) 浮亏 <= -STOP_LOSS_PCT(-5%)          → 清仓
      4b)【v5-1】弱离场（默认 OFF）            → 清仓
      5) 时间止损（亏损票）持有 >= MAX_HOLD_DAYS → 清仓
      6) 浮盈 >= TP_FULL_PCT(+15%)            → 清仓（RUN_PROFIT_MODE="TRAIL" 时跳过）
      7) 浮盈 >= TP_HALF_PCT(+10%) 且未减半    → 减半（仅一次）
      8)【v6-3】峰值回撤（武装式，置于最后）    → 清仓
          仅当 peak 对应浮盈曾 >= TRAIL_ARM_PCT(+5%) 才启用；
          RUN_PROFIT_MODE="TRAIL" 时由它接管 +15% 之后的持仓（回撤 TP_TRAIL_PCT 才走）。

    【v6-2 重要变更】本函数不再有「两级判定」。
      v5 曾在 OPEN_NOISE_CUTOFF 之前进入 HARD 模式（只做 峰值回撤/硬止损/止盈），
      实测结果是负向的：开盘半小时禁掉了所有「浅出场」（破3日线均值 -2.26%），
      却保留了「峰值回撤」（-7.02%）并把止损线放宽到 -8% —— 等于开盘只允许深亏出场。
      现统一为：所有巡检时点执行完全相同的规则集，止损线恒为 STOP_LOSS_PCT。
      参数 stage 保留仅为「R5」预设复现旧行为之用。

    盘中巡检（【v4-1】）会多次调用本函数，靠 halved / entry_date / 幂等标记防重复处理。
    """
    if quiet_empty is None:
        quiet_empty = QUIET_EMPTY_POSITION
    pm = positions_map(context)
    live_held = set(pm.keys())
    context.live_held = live_held
    peak = getattr(context, "peak", {})
    context.peak = peak
    if not pm:
        if not quiet_empty:
            log.info("[风控]{} 当前无持仓".format((" " + tag) if tag else ""))
        return
    entry = getattr(context, "entry_date", {})
    halved = getattr(context, "halved", {})
    context.halved = halved
    breakeven = getattr(context, "breakeven", {})
    context.breakeven = breakeven
    today = _context_date(context)
    need_bars = max(EXIT_MA, RETREAT_MA) + 5

    # 【v4-1 配套】日线缓存：盘中巡检一天要跑多次，日线收盘序列当天不变，
    # 缓存后取数次数从「持仓数 × 巡检次数」降到「持仓数 × 1」，显著降低回测耗时。
    bar_cache = getattr(context, "_bar_cache", None)
    if bar_cache is None or getattr(context, "_bar_cache_date", None) != today:
        bar_cache = {}
        context._bar_cache = bar_cache
        context._bar_cache_date = today

    def _clear(code):
        live_held.discard(code)
        peak.pop(code, None)
        entry.pop(code, None)
        halved.pop(code, None)
        breakeven.pop(code, None)

    sold_any = False
    _tag = (" " + tag) if tag else ""
    _hard = (str(stage).upper() == "HARD")      # 【v5-3】开盘噪声区：只做确定性判断
    for code, px in pm.items():
        amount = _to_int(_pos_field(px, _AMOUNT_FIELDS))
        cost = _pos_field(px, _COST_FIELDS) or 0
        if amount <= 0:
            continue
        closes = bar_cache.get(code)
        if closes is None:
            rows_p = _fetch_panel([code], need_bars, ["close"], "风控取数")
            closes = [x for x in ((rows_p.get(code) or {}).get("close") or []) if x]
            bar_cache[code] = closes
        if len(closes) < EXIT_MA:
            log.info("[风控] {} K线不足{}根，跳过".format(code, EXIT_MA))
            continue

        cur = _current_price(data, code)
        if cur is None:
            cur = closes[-1]
        rt = (cur / float(cost) - 1) if cost else 0.0
        ma_exit = _ma(closes, EXIT_MA)
        ma20 = _ma(closes, RETREAT_MA) if len(closes) >= RETREAT_MA else None
        d0 = entry.get(code)
        held_days = _days_between(d0, today) if (d0 and today) else 0
        is_new = bool(d0 and today and str(d0)[:10] == str(today)[:10])

        if cur:
            peak[code] = max(peak.get(code, cur), cur)

        # 1) 破 EXIT_MA 日线（【v5-3】HARD 模式跳过：均线类判断不做在开盘噪声区）
        if (not _hard) and ma_exit and cur < ma_exit:
            if _sell_all(code, px, "退潮 破{}日线 浮盈{:.1%}".format(EXIT_MA, rt),
                         "退潮破{}日线".format(EXIT_MA), rt, is_new):
                _clear(code); sold_any = True
            continue
        # 1b) 【v6-3】峰值回撤已从本位置移出（原 v5 在此判定，抢在止损/止盈之前）。
        #      现移到步骤 8，且必须通过「武装线」TRAIL_ARM_PCT 校验。
        # 2) 破 20 日线（【v5-3】HARD 跳过）
        if (not _hard) and ma20 and cur < ma20:
            if _sell_all(code, px, "退潮 破{}日线 浮盈{:.1%}".format(RETREAT_MA, rt),
                         "退潮破20日线", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 3) 保本止损（【v5-3】HARD 跳过）
        if (not _hard) and BREAKEVEN_STOP and halved.get(code) and code in breakeven \
                and cur <= breakeven[code]:
            if _sell_all(code, px, "保本止损 破保本价{:.2f} 浮盈{:.1%}".format(breakeven[code], rt),
                         "保本止损", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 4) 止损（两级都跑；【v5-3】HARD 模式放宽到 HARD_MODE_STOP_PCT，只兜深亏尾部）
        _stop_line = HARD_MODE_STOP_PCT if _hard else STOP_LOSS_PCT
        if rt <= -_stop_line:
            _rsn = ("硬止损(噪声区放宽) 浮亏{:.1%}".format(rt) if _hard
                    else "止损 浮亏{:.1%}".format(rt))
            if _sell_all(code, px, _rsn, "止损", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 4b)【v5-1】弱离场（默认 OFF；HARD 模式跳过）
        if (not _hard) and str(WEAK_EXIT_MODE).upper() != "OFF" \
                and held_days >= WEAK_EXIT_DAYS and rt <= WEAK_EXIT_PCT:
            if _sell_all(code, px, "弱离场 持有{}日 浮盈{:.1%}".format(held_days, rt),
                         "弱离场", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 5) 时间止损（【v5-3】HARD 跳过）
        if (not _hard) and held_days >= 1 and rt <= 0 and MAX_HOLD_DAYS > 0 \
                and held_days >= MAX_HOLD_DAYS:
            if _sell_all(code, px, "时间止损 亏损持仓{}天".format(MAX_HOLD_DAYS), "时间止损", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 6) +15% 清仓（【v6-5】RUN_PROFIT_MODE="TRAIL" 时跳过，改由步骤 8 的移动止盈接管）
        if rt >= TP_FULL_PCT and str(RUN_PROFIT_MODE).upper() != "TRAIL":
            if _sell_all(code, px, "止盈 浮盈{:.1%} 触+{}%清仓".format(rt, int(TP_FULL_PCT * 100)),
                         "止盈清仓", rt, is_new):
                _clear(code); sold_any = True
            continue
        # 7) +10% 减半
        if rt >= TP_HALF_PCT and not halved.get(code):
            ok = _sell_half(code, px, "止盈 浮盈{:.1%} 触+{}%减半".format(rt, int(TP_HALF_PCT * 100)),
                            "止盈减半", rt)
            halved[code] = True
            if cost:
                breakeven[code] = float(cost) * (1 - BREAKEVEN_BUF)
                log.info("[保本] {} 已减半，保本价设为 {:.2f}（成本价{:.2f}*({})）".format(
                    code, breakeven[code], float(cost), 1 - BREAKEVEN_BUF))
            continue
        # 8) 【v6-3】峰值回撤跟踪止盈（武装式，置于最后）
        #    v5 实测：无武装线时该规则在浮亏状态触发（11 笔全部亏损、均值 -7.02%、贡献 -13,789 元），
        #    因为它排在止损之前，抢走了「-5% 止损」的出场权。
        #    修正：① 必须 peak 浮盈曾 >= TRAIL_ARM_PCT 才启用（即「已涨过」才谈回撤）；
        #          ② 排在止盈之后，不再抢止损/止盈的出场权。
        if TRAIL_PCT > 0 and peak.get(code) and cost:
            _pk = float(peak[code])
            _pk_rt = (_pk / float(cost) - 1) if cost else 0.0
            _arm = TRAIL_ARM_PCT
            _trail = TRAIL_PCT
            if str(RUN_PROFIT_MODE).upper() == "TRAIL":
                # 让利润奔跑：+15% 后不再清仓，由移动止盈接管（回撤 TP_TRAIL_PCT 才走）
                _arm = min(TRAIL_ARM_PCT, TP_FULL_PCT)
                _trail = TP_TRAIL_PCT
            if _pk_rt >= _arm and cur <= _pk * (1 - _trail):
                _rsn = ("移动止盈 峰值{:+.1%}回撤{:.0%} 浮盈{:.1%}".format(_pk_rt, _trail, rt)
                        if str(RUN_PROFIT_MODE).upper() == "TRAIL"
                        else "峰值回撤{:.0%} 峰值{:+.1%} 浮盈{:.1%}".format(_trail, _pk_rt, rt))
                if _sell_all(code, px, _rsn, "峰值回撤", rt, is_new):
                    _clear(code); sold_any = True
                continue
    for c in list(halved.keys()):
        if c not in pm:
            halved.pop(c, None); breakeven.pop(c, None); peak.pop(c, None)
    if sold_any:
        _LAST_SELL_FLAG[0] = True
        log.info("[风控]{} 本轮有平仓动作（当日释放的额度可用于补建仓）".format(_tag))



def _days_between(d1, d2):
    try:
        import datetime as _dt
        a = _dt.date(*[int(x) for x in str(d1)[:10].split("-")])
        b = _dt.date(*[int(x) for x in str(d2)[:10].split("-")])
        return abs((b - a).days)
    except Exception:
        return 0


# ============================================================
# 十、建仓（按可用现金 + 【v4-5】预算回收）
# ============================================================
def build_orders(context, top):
    """挑出本轮建仓候选：受 MAX_POSITIONS 与自维护 live_held 约束。"""
    held = set(getattr(context, "live_held", set()))
    remaining = MAX_POSITIONS - len(held)
    if remaining <= 0:
        log.info("[买入] 持仓已满 {} 只，本轮不新增".format(len(held)))
        return []
    picks = []
    for a in top:
        if a["code"] in held:
            continue
        if REQUIRE_ABOVE_MA20 and not a["above20"]:
            continue
        picks.append(a)
        if len(picks) >= remaining:
            break
    return picks


def _cash(context):
    for attr in ("cash", "available_cash", "total_cash"):
        try:
            return float(getattr(context.portfolio, attr))
        except Exception:
            continue
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        return 0.0


def _total_asset(context):
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        pass
    if _has("get_total_assets"):
        try:
            return float(get_total_assets())
        except Exception:
            pass
    return 0.0


def _alloc_by_strength(picks, budget, total):
    """按热点强度分档分配预算（纯函数）。返回与 picks 等长的金额列表。"""
    if not picks:
        return []
    if not STRENGTH_WEIGHT:
        per = min(total * POSITION_VALUE_RATIO, budget / len(picks))
        return [per] * len(picks)
    scores = [max(float(a.get("score", 0.1)), 0.1) for a in picks]
    exp = STRENGTH_EXP
    weights = [s ** exp for s in scores]
    cap = total * MAX_SINGLE_RATIO
    n = len(picks)
    allocs = [0.0] * n
    remaining = budget
    active = set(range(n))
    for _ in range(20):
        if not active or remaining <= 1.0:
            break
        fw = sum(weights[i] for i in active) or 1.0
        moved = 0.0
        capped = []
        for i in active:
            add = remaining * (weights[i] / fw)
            if allocs[i] + add >= cap - 1e-6:
                moved += cap - allocs[i]
                allocs[i] = cap
                capped.append(i)
            else:
                allocs[i] += add
                moved += add
        for i in capped:
            active.discard(i)
        remaining -= moved
    return allocs


def execute_buy(context, picks, budget_factor=1.0, tag=""):
    """建仓。v4 相对 v3 的两处改动：

      【v4-5】预算回收：某票因「不足最小手数」或触及单票上限而用不满额度时，
              把剩余额度顺延给后续候选；全部候选走完后若仍有结余，再按 RECYCLE_ROUNDS
              轮对已成交标的追加（order_target_value 加仓），直到用满或全员触顶。
      【v4-5】单票上限 MAX_SINGLE_RATIO 在分配阶段与下单阶段双重校验，防过度集中。
    """
    total = _total_asset(context)
    cash = _cash(context)
    if total <= 0:
        log.error("[买入] 无法获取总资产，跳过建仓")
        return
    base_budget = min(cash * (1 - CASH_BUFFER), total * POSITION_VALUE_RATIO * MAX_POSITIONS)
    budget = base_budget * max(0.0, float(budget_factor))
    if budget <= 0 or cash <= 0:
        log.error("[买入] 本轮预算为 0（情绪闸门/现金不足），跳过建仓")
        return
    allocs = _alloc_by_strength(picks, budget, total)
    log.info("[买入]{} 总资产{:.0f} 可用现金{:.0f} 基准预算{:.0f} 实际预算{:.0f}（系数{:.2f}；"
             "强度分档 {} 只；回收={}）".format(
                 (" " + tag) if tag else "", total, cash, base_budget, budget,
                 budget_factor, len(picks), "开" if BUDGET_RECYCLE else "关"))

    entry = getattr(context, "entry_date", None)
    if entry is None:
        entry = {}
        context.entry_date = entry
    halved = getattr(context, "halved", None)
    if halved is None:
        halved = {}
        context.halved = halved
    breakeven = getattr(context, "breakeven", None)
    if breakeven is None:
        breakeven = {}
        context.breakeven = breakeven
    live_held = getattr(context, "live_held", set())
    context.live_held = live_held

    cap_value = total * MAX_SINGLE_RATIO
    leftover = 0.0
    booked = []          # [{a, code, price, lot, used}]

    for a, per in zip(picks, allocs):
        code = a["code"]
        price = a.get("price")
        if not price or price <= 0:
            log.error("[买入] {} 无可用现价，跳过".format(code))
            if BUDGET_RECYCLE:
                leftover += per
            continue
        lot = 200 if _is_kcb(code) else 100
        avail = per + (leftover if BUDGET_RECYCLE else 0.0)
        # 单票上限
        budgeted_room = cap_value
        avail = min(avail, budgeted_room)
        shares = int(avail // (price * lot)) * lot
        if shares < lot:
            log.info("[买入] {} 可用额度{:.0f}元 @现价{:.2f} 不足最小{}股，跳过（额度顺延）".format(
                code, avail, price, lot))
            if BUDGET_RECYCLE:
                leftover += per
                log.info("[回收] {} 的额度 {:.0f} 元顺延至后续候选（累计结余 {:.0f}）".format(
                    code, per, leftover))
            continue
        used = shares * price
        if per < 1000 and not BUDGET_RECYCLE:
            log.error("[买入] {} 分配金额过小({:.0f})，跳过".format(code, per))
            continue
        halved.pop(code, None)
        breakeven.pop(code, None)
        if TRADE_ENABLED:
            log.info("[买入] {} {} 现价+{}% 强度{} 分配{:.0f}元 目标{}股 ≈{:.0f}元{}".format(
                code, a["name"], a["pct"], a["score"], avail, shares, used,
                "（板块[{}x{}]）".format(a.get("industry") or "-", a.get("sector_cnt", 0))
                if a.get("sector_cnt") else ""))
            try:
                if _has("order_target_value"):
                    order_target_value(code, used)
                else:
                    order_value(code, used)
                entry[code] = _context_date(context)
                live_held.add(code)
                booked.append({"a": a, "code": code, "price": price, "lot": lot, "used": used})
            except Exception as e:
                log.error("[买入异常] {} : {}".format(code, repr(e)))
        else:
            log.info("[信号] 拟买入 {} {} 现价+{}% 强度{} 目标{}股（未下单）".format(
                code, a["name"], a["pct"], a["score"], shares))
            entry[code] = _context_date(context)
            live_held.add(code)
            booked.append({"a": a, "code": code, "price": price, "lot": lot, "used": used})
        if BUDGET_RECYCLE:
            leftover = max(0.0, avail - used)

    # ---- 【v4-5】结余回填：对已成交标的按强度顺序追加 ----
    if BUDGET_RECYCLE and leftover > 0 and booked:
        for r in range(RECYCLE_ROUNDS):
            if leftover < 1000:
                break
            progressed = False
            for b in booked:
                code, price, lot = b["code"], b["price"], b["lot"]
                room = cap_value - b["used"]
                if room <= 0:
                    continue
                add_avail = min(leftover, room)
                add_shares = int(add_avail // (price * lot)) * lot
                if add_shares < lot:
                    continue
                add_val = add_shares * price
                if not TRADE_ENABLED:
                    log.info("[信号] 拟追加 {} {} 股（用结余额度 {:.0f} 元）".format(
                        code, add_shares, add_val))
                else:
                    try:
                        if _has("order_target_value"):
                            order_target_value(code, b["used"] + add_val)
                        else:
                            order_value(code, add_val)
                        log.info("[回收] 第{}轮追加 {} {}股 用额{:.0f}元（结余剩 {:.0f}）".format(
                            r + 1, code, add_shares, add_val, leftover - add_val))
                    except Exception as e:
                        log.error("[回收异常] {} : {}".format(code, repr(e)))
                        continue
                b["used"] += add_val
                leftover -= add_val
                progressed = True
            if not progressed:
                break
        if leftover > 1000:
            log.info("[回收] 结余额度 {:.0f} 元未能用出（不足最小手数或全员触及单票上限"
                     "{}%）".format(leftover, int(MAX_SINGLE_RATIO * 100)))
        else:
            log.info("[回收] 预算基本用满（结余 {:.0f} 元）".format(leftover))


# ============================================================
# 十一、入口
# ============================================================
_LAST_DATE = [""]
_DIAG_DONE = [False]
_DAILY_FALLBACK_WARNED = [False]
_LAST_SELL_FLAG = [False]      # 【v4-1】本轮风控是否发生过平仓（用于「释放额度当日补建仓」）


def initialize(context):
    try:
        set_benchmark("000300.SS")
    except Exception as e:
        log.info("[配置] set_benchmark 失败: {}".format(repr(e)))
    try:
        set_slippage(slippage=SLIPPAGE)
    except Exception:
        try:
            set_slippage(SLIPPAGE)
        except Exception as e2:
            log.info("[配置] 滑点未设置: {}".format(repr(e2)))
    try:
        set_commission(commission_ratio=0.0003, min_commission=5.0, type="STOCK")
    except Exception:
        try:
            set_commission(PerTrade=0.0003, Min=5)
        except Exception as e2:
            log.info("[配置] 佣金未设置: {}".format(repr(e2)))

    log.info("=" * 60)
    log.info("[初始化] 热点追踪 {} 启动；预设={}；TRADE_ENABLED={}".format(
        VERSION, PRESET_APPLIED, TRADE_ENABLED))
    log.info("[初始化] v6 修正开关：[v6-1]盘后补仓={} [v6-2]巡检分级={}（{}） "
             "[v6-3]峰值回撤武装线={}（后移+需峰值浮盈达线） "
             "[v6-5]让利润奔跑={}（+{}%触发的后续处置）".format(
                 "开(旧行为)" if REINVEST_ON_SELL else "关(额度留至次日)",
                 "开" if str(OPEN_NOISE_CUTOFF or "") else "关(所有时点同规则)",
                 ("HARD 早于 " + str(OPEN_NOISE_CUTOFF)) if str(OPEN_NOISE_CUTOFF or "") else "全时点统一",
                 ("+{:.0%}".format(TRAIL_ARM_PCT) if TRAIL_ARM_PCT > 0 else "无(等于旧版)"),
                 str(RUN_PROFIT_MODE).upper(),
                 int(TP_FULL_PCT * 100)))
    log.info("[初始化] 出场参数：EXIT_MA={} 破20日线={} 止损={:.0%} 止盈={:.0%}减半/{:.0%}清仓 "
             "峰值回撤={:.0%} 时间止损={}日 弱离场={}".format(
                 EXIT_MA, RETREAT_MA, STOP_LOSS_PCT, TP_HALF_PCT, TP_FULL_PCT,
                 TRAIL_PCT, MAX_HOLD_DAYS, str(WEAK_EXIT_MODE).upper()))
    log.info("[初始化] 保留开关：[v4-1]盘中巡检={}（{}个时点） [v4-2]情绪闸门={}({}) "
             "量比{} 额{:.0f}亿 建仓日预算回收={} 持仓上限{}只".format(
                 "开" if INTRADAY_RISK_ENABLED else "关", len(INTRADAY_RISK_TIMES),
                 "开" if SENTIMENT_GATE_ENABLED else "关", SENTIMENT_MODE,
                 MIN_VOL_RATIO, MIN_AMOUNT / 1e8,
                 "开" if BUDGET_RECYCLE else "关", MAX_POSITIONS))
    if INTRADAY_RISK_ENABLED and INTRADAY_RISK_TIMES:
        _cut = str(OPEN_NOISE_CUTOFF or "")
        log.info("[初始化] 巡检时点分级：{}".format("，".join(
            "{}→{}".format(_t, "HARD(仅硬止损/止盈)"
                           if (_cut and str(_t) < _cut) else "全量")
            for _t in INTRADAY_RISK_TIMES)))
    _diag_api()
    log.info("[初始化] 行情/成交量/口径自检将延迟到首个交易日执行（PTrade 初始化阶段禁止取数）")
    log.info("=" * 60)

    context.halved = {}
    context.breakeven = {}
    context.peak = {}
    context.live_held = set()
    context._risk_seen = set()
    context._tail_done = set()


def _retreat_scan(context, data, reason_tag):
    """卖出后的额度立即参与建仓：重扫一次（【v4-1】配套，保证当日释放额度当日可用）。

    【v5-5】受 MAX_RECYCLE_BUYS_PER_DAY 限速：每日补建仓不超过 N 笔。v4 无此限制时，
    「风控砍仓 → 立即用释放额度买新票 → 次日再砍」形成高频轮动闭环
    （v4 建仓 109 笔 / 平均持仓 1.42 天，对照 v3 为 69 笔 / 3.94 天）。
    """
    top = scan_market(context, data)
    if not top:
        return
    picks = build_orders(context, top)
    if not picks:
        log.info("[补仓] 无符合建仓条件的候选")
        return
    if MAX_RECYCLE_BUYS_PER_DAY > 0:
        used = int(getattr(context, "_recycle_buys", 0) or 0)
        room = MAX_RECYCLE_BUYS_PER_DAY - used
        if room <= 0:
            log.info("[补仓] 已达当日补建仓上限 {} 笔 → 放弃本次补仓（防高频轮动）".format(
                MAX_RECYCLE_BUYS_PER_DAY))
            return
        if len(picks) > room:
            log.info("[补仓] 候选 {} 只 → 限速至 {} 只（当日上限 {} 笔，已用 {}）".format(
                len(picks), room, MAX_RECYCLE_BUYS_PER_DAY, used))
            picks = picks[:room]
    execute_buy(context, picks, tag=reason_tag)
    context._recycle_buys = int(getattr(context, "_recycle_buys", 0) or 0) + len(picks)


def _daily_routine(context, data=None):
    # 延迟自检：PTrade 初始化阶段禁止取数，改为首个交易日执行一次
    if not _DIAG_DONE[0]:
        _DIAG_DONE[0] = True
        try:
            _diag_vol_scale()
            _diag_cutoff(context)
            _diag_data(data)
        except Exception as e:
            log.error("[自检] 延迟自检异常: {}".format(repr(e)))
    today = _context_date(context)
    if today and _LAST_DATE[0] == today:
        return
    _LAST_DATE[0] = today
    _LAST_SELL_FLAG[0] = False      # 每轮开始重置（before_trading_start 未必被平台调用）
    context._recycle_buys = 0       # 【v5-5】当日补建仓计数清零
    log.info("=" * 60)
    log.info("[{}] 每日热点识别开始（预设 {}）".format(today, PRESET_APPLIED))
    try:
        top = scan_market(context, data)
    except Exception as e:
        log.error("[扫描] 异常: {}".format(repr(e)))
        top = []

    # ---- 【v4-2】情绪闸门判定 ----
    senti = SCAN_META.get("sentiment") or {}
    verdict, factor, why = _sentiment_verdict(senti)
    SCAN_META["verdict"] = verdict
    SCAN_META["verdict_msg"] = why
    if verdict == "OK":
        log.info("[闸门] 放行（{}）".format(why))
    else:
        _warn("[闸门] {} —— {}".format(verdict, why))

    try:
        monitor_risk(context, data)
    except Exception as e:
        log.error("[风控] 异常: {}".format(repr(e)))

    # 风控卖出后当日释放的额度：是否立即补建仓（REINVEST_ON_SELL）
    if _LAST_SELL_FLAG[0]:
        _LAST_SELL_FLAG[0] = False
        if not REINVEST_ON_SELL:
            # 【v6-1】默认关闭：实测补仓 39 笔、胜率 28.2%、均值 +0.48%
            #         （同期主扫描建仓 43 笔、胜率 53.5%、均值 +4.44%）
            #         额度留至次日主流程使用，避免「卖出→当日高位换股→次日再卖」的闭环。
            log.info("[补仓] 本日有风控平仓；按 v6-1 规则额度留至次日主流程使用"
                     "（REINVEST_ON_SELL=False），本日仍按下方正常流程建仓")
        elif verdict == "STOP":
            _warn("[闸门] 情绪冰点 → 本轮风控释放的额度不补仓（避免冰点加仓）")
        else:
            log.info("[补仓] 本轮风控有平仓动作，重新扫描并补足仓位")
            try:
                _retreat_scan(context, data, "补仓")
            except Exception as e:
                log.error("[补仓] 异常: {}".format(repr(e)))
            return

    if not top:
        if TRADE_ENABLED:
            log.error("[警告] 本轮热点榜为空，未建仓。若连续多日为空，"
                      "请检查取数接口、成交额单位与入场门槛（量比/成交额/高开上限）")
        else:
            log.info("[信号模式] 本轮热点榜为空，不下单")
        return

    if verdict == "STOP":
        _warn("[闸门] 情绪冰点，今日只做风控不建仓（这是有意为之，非故障）")
        return
    picks = build_orders(context, top)
    if not picks:
        log.info("[信号] 无符合建仓条件的候选")
        return
    if verdict == "HALF":
        keep = max(1, (len(picks) + 1) // 2)
        log.info("[闸门] 情绪冰点减半仓：候选 {} -> {} 只，预算系数 {:.2f}".format(
            len(picks), keep, factor))
        picks = picks[:keep]
    execute_buy(context, picks, budget_factor=factor)


def _risk_watch(context, data, hhmm):
    """【v4-1】盘中风控巡检：(日期, 时点) 幂等，只跑风控不下单。

    【v6-2】默认 OPEN_NOISE_CUTOFF="" → 所有时点均为 NORMAL（统一规则集）。
    仅当预设显式设置了 OPEN_NOISE_CUTOFF（如 R5 复现 v5）才会进入 HARD 模式。
    """
    today = _context_date(context)
    key = "{} {}".format(today, hhmm)
    seen = getattr(context, "_risk_seen", None)
    if seen is None:
        seen = set()
        context._risk_seen = seen
    if key in seen:
        return
    seen.add(key)
    _cut = str(OPEN_NOISE_CUTOFF or "")
    stage = "HARD" if (_cut and str(hhmm) < _cut) else "NORMAL"
    try:
        monitor_risk(context, data,
                     tag="巡检{}{}".format(hhmm, "(hard)" if stage == "HARD" else ""),
                     stage=stage)
    except Exception as e:
        log.error("[巡检] {} 异常: {}".format(hhmm, repr(e)))


def _tail_routine(context, data):
    """【v4-5 延伸】尾盘补仓：仅当仍有空位且仍有可投现金时执行，每日一次。"""
    today = _context_date(context)
    done = getattr(context, "_tail_done", None)
    if done is None:
        done = set()
        context._tail_done = done
    if today in done:
        return
    done.add(today)
    held = set(getattr(context, "live_held", set()))
    if len(held) >= MAX_POSITIONS:
        return
    cash = _cash(context)
    total = _total_asset(context)
    if cash <= total * CASH_BUFFER:
        return
    log.info("[尾盘] 空位 {} 个、可用现金 {:.0f}，执行 14:45 补仓扫描".format(
        MAX_POSITIONS - len(held), cash))
    try:
        top = scan_market(context, data)
        if not top:
            log.info("[尾盘] 无候选，放弃补仓")
            return
        picks = build_orders(context, top)
        if picks:
            execute_buy(context, picks, tag="尾盘")
    except Exception as e:
        log.error("[尾盘] 异常: {}".format(repr(e)))


def handle_data(context, data):
    hhmm = _now_hhmm(context)
    if not hhmm:
        # 日频回测：拿不到 HH:MM，按日执行（幂等），盘中巡检与尾盘补仓自动失效
        if not _DAILY_FALLBACK_WARNED[0]:
            _DAILY_FALLBACK_WARNED[0] = True
            _warn("[时间] 无法读取 HH:MM（日频回测或平台限制）→ 主流程按日执行；"
                  "【v4-1】盘中巡检 / 尾盘补仓 在日频下不生效，请在分钟级回测验证")
        _daily_routine(context, data)
        return
    if hhmm >= SIGNAL_TIME:
        _daily_routine(context, data)
    if INTRADAY_RISK_ENABLED and hhmm in INTRADAY_RISK_TIMES:
        _risk_watch(context, data, hhmm)
    if TAIL_SCAN_ENABLED and hhmm >= TAIL_TIME:
        _tail_routine(context, data)


def before_trading_start(context, data):
    _LAST_SELL_FLAG[0] = False


def after_trading_end(context, data):
    try:
        report_stats()
    except Exception as e:
        log.error("[统计] 异常: {}".format(repr(e)))
