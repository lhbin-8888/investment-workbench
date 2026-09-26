# -*- coding: utf-8 -*-
"""
热点追踪量化程序 V4.9（补丁版）—— 盘前选股 + 早盘 09:32 建仓（山西证券 PTrade 版）
=====================================================================
本文件 = 热点早盘001_V4.8.py 基础上叠加"V4.9 改动清单"，仅供回测对照；
V4.4 / V4.5 / V4.6 / V4.7 / V4.8 五个版本文件均原位保留、未做任何改动。

V4.9 依据：《热点早盘001-选股质量归因.md》（用真实行情重算 26 笔买入，把"选股"与"出场"剥离）
  归因结论：**选股不是瓶颈** —— 同期中证1000 跌 3.85%、上涨概率仅 11.5%，
  而策略挑出的票持有 5 日仅 −0.53%、胜率 42.3% ⇒ **选股超额 +3.32pp**。
  真正病灶在出场端：**前 3 笔贡献 +87.3pp，其余 23 笔合计 −19.7pp**，
  且前两名（301366 持 25 天 +40.6% / 300747 持 18 天 +29.3%）都是
  **没触发任何规则、一路持有到最后**的票，而平均持仓仅 6.50 天。

  ── P0：本版核心 ──────────────────────────────────
   P0-1 ⚠️ 修正：**不降低入场限价**（推翻上一版归因的 P0-1，理由见下方"入场价校准"）
   P0-2 主线分散：MAINLINE_MAX_ENTRIES = 4（滚动 20 交易日）
        稀缺资源独占 8/26 笔、均值仅 +0.3%；但**不做板块名黑名单**（会过拟合本区间），
        改用通用的"同一主线近期建仓次数"约束，让额度自然流向其他主线
   P0-3 赢家宽管（让利润奔跑）：浮盈 ≥15% → 移动止盈回撤放宽到 15%×1.6 = 24%、
        趋势线由 MA10 放宽到 MA20；⚠️ 是"放宽"不是"豁免"（最长宽管 30 日）

  ── P1：结构性修复 ────────────────────────────────
   P1-1 阈值比例重置（★盈亏比自洽★）：ATR_STOP_MAX 0.12→**0.06**、MIN 0.05→**0.04**、
        分批止盈 0.10→**0.15**、TRAIL 0.10→**0.15**
        ⇒ 可达盈亏比上限由 0.83 提升到 **2.50**（保本需 2.50；V4.8 面板实测仅 0.56）
        同时：判据改用**策略自有成本** g.entry_px，不再读会被摊薄的 cost_price；
        删除两段式止损 STOP_STAGED=False（V4.8 实证 3/3 在同一分钟内走完两段）
   P1-2 `_do_sell` 统一追加浮盈亏 —— 补齐 V4.8 缺失的 19/31 笔观测盲区

  ═══ 入场价校准（本版最重要的一段：它推翻了上一版归因的建议）═══
  上一版归因称"入场价口径值 +1.75pp、零风险白送"，**这个处方是错的**。原因：
    归因比的是"用 c_prev×1.01 计价" vs "用 T 日开盘价计价"，但策略实际走的是
    order_value + limit_price 撮合 —— **成交价由引擎撮合决定，与 assumed 假设价无关**。
  用真实 OHLC 重算 V4.8 的实际成交路径后：
    · V4.8 限价被护栏封顶在 c_prev×1.03；因 **77% 的票 T 日低开**，
      实际成交均价已 ≈ c_prev×0.9919（≈开盘价）—— "低开成交"的好处早已在享受
    · 再把限价压到 c_prev×1.005 只能多赚 0.36pp，却会筛掉 **301366（开 +1.7% → +40.6%）**
      和 **300747（开 +1.8% → +29.3%）** 这两笔最大的赢家
  ⇒ 故 ASSUME_ENTRY_PREMIUM / BUY_LIMIT_SLIP / BUY_PREMIUM_PCT 三项**一律维持 V4.8 原值**。
    教训：归因口径必须与策略的**实际成交机制**对齐，否则会给出方向相反的处方。

（以下为历史版本说明，保留以便对照）
---------------------------------------------------------------------
本文件 = 热点早盘001_V4.7.py 基础上叠加"V4.8 改动清单"，仅供回测对照；
V4.4 / V4.5 / V4.6 / V4.7 四个版本文件均原位保留、未做任何改动。

V4.8 依据：《热点早盘001_V4.7-回测复盘与结论.md》（2026-05-06~06-30 区间，31 笔平仓）
  复盘结论：**出场时点修对了**（09:45 前出场 46%→11%、破均线 9 笔全部 14:45 尾盘确认、
  分批止盈 7 笔全部生效、日志 5061→1749 行），但**出口换了名字继续砍人**：
  · 破均线被治住 → 出口被 **ATR 止损** 接管（16 笔，均值 −5.57%）
  · ATR 止损已**退化为固定 5%**：阈值 = clamp(1.8×ATR/成本, 0.03, 0.05)，
    热点票 ATR/价格常态 3~5% ⇒ 1.8×3.5%≈6.3% 被 MAX=0.05 截断
  · 折年双边换手 **23.7 → 28.2 次（+19%）**、成本 2.59% → 3.08%（提仓位的副作用）
  · 双护栏仍 **100% 空转**（42/42 笔全走 assumed(+1.0%)）→ 入场价实为 T-1收盘×1.01
  · 产业链簇约束拦截建仓 **17 次**，仓位被自己的规则锁死在 2~3 只
  · 主跌段（5/13~6/15，−10.62%）无任何避险档，市场级开关一次未触发

  ── P0：决定策略生死 ────────────────────────────────
   P0-1 ATR 止损放宽 + 两段式宽限（本版核心）：
        · ATR_STOP_MIN_PCT 0.03 → **0.05**、ATR_STOP_MAX_PCT 0.05 → **0.12**
          —— 让 1.8×ATR 的自适应真正自适应，不再被上限压成"固定 5%"一刀切
        · 新增 STOP_STAGED 两段式：首次触发**减半**（而非一次清仓），记 stage1；
          若价格收窄到 阈值×STOP_RECOVER_RATIO 以内则**撤销**标记（重新武装）；
          再次触发（且已有标记）才清仓剩余 —— 用半仓换"插针不被全砍"
   P0-2 折年双边换手压降：
        · MAX_NEW_POSITIONS_PER_DAY 3 → **2**（V4.7 实测换手不降反升 19%）
        · DIFFUSE_POSITION_RATIO 0.15 → **0.12**（扩散期是候选主力，0.15 太贵）
        · 目标：折年双边 ≤ 20 次（V4.7 = 28.2 次），成本 ≈2.2%
   P0-3 修"日内价捕获"（护栏空转的根因）：
        · 新增 set_universe(候选) —— 让回测引擎把候选票纳入 handle_data 的 data，
          这是 V4.5 引入 `g.intraday_px` 通道后**仍 42/42 走 assumed** 的直接原因
          （data 里根本没有这些票，`_capture_intraday` 无从取值）
        · `_capture_intraday` 扩为多字段（close / price / last_price）× 多键探测
        · 新增 [口径-探测] 日志：首次打印 data 的键样本与命中情况，下轮可定位

  ── P1：收益弹性 ──────────────────────────────────
   P1-1 产业链簇约束放松：CLUSTER_JACCARD 0.3 → **0.5**
        （0.3 把"稀缺资源/元件/中芯概念"全划成一簇，40% 上限拦截 17 次建仓）
   P1-2 分批止盈提前：PARTIAL_TAKE_PCT 0.12 → **0.10**
        （V4.7 实测 7 笔分批全部集中在 +12.0%~+13.0%，说明 12% 偏高、锁利太晚）
        ⚠️ TRAIL_PCT 保持 **0.10**（用户指定值，本版未动）
   P1-3 市场级避险档（新增）：指数跌破 MA20 ⇒ 新建仓仓位 ×0.5、每日新建上限降到 1 笔
        · REGIME_RISK_OFF_SCALE = 0.5 / REGIME_RISK_OFF_MAX_NEW = 1
        · 数据源 = 盘前取的 g.index_rows（T-1 口径，与 market_regime_ok 一致）
        · 与旧开关的区别：旧 REGIME_USE_INDEX_MA20 是"全停"（曾误杀唯一候选），
          本档是"减速"——**主跌段继续参与但只用半仓**，避免 V4.7 那样在跌段里
          全仓连着挨 14 笔止损

  ── P2：可观测性 ──────────────────────────────────
   P2-1 建仓成交率统计：`[成交] 本日委托 N 笔 / 成交 M 笔` —— V4.7 拒单率 23.8%
        无法从日志直接读出，只能靠 Order Rejected 计数
   P2-2 两段式止损日志：减半/清仓/撤销三态各自可查

  ⚠️ 本版基线 = V4.7（其基线为 V4.6）。V4.7 相对 V4.6 新增 182 行 / 删除 40 行。
  ⚠️ 回测可比性提示：换手口径为 **成交额 ÷ (2×总资产)**（策略内部定义），
     与"成交额 ÷ 资产"差 2 倍 —— 复盘对账时务必统一，否则会得出"换手上升/下降"相反结论。

## V4.7 演进说明（保留备查）
V4.7 = V4.6 + "P0 + P1 全改"
V4.7 依据：《热点早盘001_V4.5-回测复盘与结论.md》
  复盘结论：V4.5 的**结构指标全面改善**（板块清仓 40→0 笔、平均持仓 2.46→3.60 日、
  折年双边换手 68→50 次、最大回撤 12.0%→7.5%），但**收益反而更差（-2.6%）**。
  根因：出场被"破 10 日线"接管 —— 21/35 笔（60%）仍成交于 09:35 前、4 笔 ATR 止损
  全落在 09:31，而 14:48 的板块清仓**执行了 0 笔**。即：只给一个出场分支加闸门无效，
  必须对**所有趋势类出场**统一设闸。附带发现 3 个 bug（分批止盈失效 / 拒单 22.5% /
  噪声日志占 52%）+ 仓位利用率仅 40.4%。

  ── P0：决定策略生死（不改则调任何参数都是白调）────────────────
   P0-1 统一出场时间闸门（本版核心）：
        · EXIT_BREAK_TIME = 14:45 —— 破均线清仓改为**尾盘确认**，只在此时点后判定
          （旧：盘中每分钟判定，V4.5 中 11 笔成交于 09:35 前，用隔夜均线砍在开盘噪声区）
        · STOP_TIME_FLOOR = 09:45 —— 硬止损最早执行时点，避开开盘 15 分钟集合竞价噪声区
        · 与板块级清仓（14:48）的先后：个股破位先走 → 板块清仓兜底
   P0-2 换手熔断真正可用：
        · TURNOVER_WINDOW_DAYS 20 → 60（交易日），MAX_ANNUAL_TURNS 30 → 6
        · 旧值 20 日窗口 × 阈值 30 次 = 折年 ≈375 次，等于常年不触发；新值折年 ≈25 次
        · ⚠️ 39 天回测窗口 < 60 交易日 → **本次回测熔断仍不会触发**，它是为实盘长周期
          设计的护栏；回测内的换手压降主要来自 P0-1 + P1-3（出场笔数减少 → 换手自然下降）
   P0-3 硬止损豁免最短持有期：V4.6 仅在注释中声称"ATR 止损永不受最短持有期约束"、
        代码并未实现（L1967 仍是 held_days >= MIN_HOLD_FOR_TIGHT_STOP）→ 本版真正落地

  ── P1：收益弹性 ──────────────────────────────────
   P1-1 修"分批止盈失效"bug：旧判据 `0 < half < amount` 在"仅剩 1 手"时永不成立
        （_round_lot(100×0.5, 100) = 100 == amount）→ 5/20 11:21–11:30 连刷 10 次
        "可卖100股/需100股"、浮盈 12%+ 的单子始终未减仓。改为"**减仓后至少保留 1 手**"：
        仓位不足 2 手时永久标记完成、交移动止盈（不刷屏）；可卖量不足（T+1 未解禁）时
        本日不减、留待下次。
   P1-2 放宽入场限价治拒单：BUY_LIMIT_SLIP 0.5% → 2%（仍由护栏上限 +3% 封顶）
        V4.5 中 9 笔 `can not match` = 限价(昨收×1.015)挡掉了跳空高开超 1.5% 的最强票，
        成交样本被逆向筛选成"次日没高开"的那批。放宽后限价 ≈ 昨收×1.03 = 护栏上限，
        跳空 0~3% 均可成交，价格约束统一由 BUY_PREMIUM_PCT 承担。
   P1-3 提升仓位利用率：MAX_NEW_POSITIONS_PER_DAY 2 → 3 笔（V4.5 实测平均仓位仅 40.4%：
        平均持仓 3.41 只 / 上限 6，叠加扩散期半仓与每日 2 笔上限）
   P1-4 移动止盈放宽：TRAIL_PCT 0.07 → **0.10**（用户指定，覆盖 V4.6 的收紧决定）。
        V4.5 回测中移动止盈仅触发 4 次，但 6/29 那两笔是区间内唯一兑现大利润的出口
        （赢仓量级 +40%~+53%），7% 会在趋势未走完时提前砍掉；放宽到 10% 换取赢仓多跑，
        代价是单笔回吐幅度加大。**建议回测单跑 0.07 / 0.10 / 0.12 三档对比后再定稿。**

  ── P2：可观测性 ──────────────────────────────────
   P2-1 噪声日志去重：同一标的、同一类出场噪声**每日最多一条**
        （V4.5 日志 52% 被"破10日线但持仓仅N日"一条刷屏，单票最高 482 次）
   P2-2 日终净值打印：`[净值] 日期 总资产=xxx 持仓=N 只` → 下次不必再从"目标金额 ÷ 仓位
        比例"反推净值（V4.5 复盘时该方法系统性低估约 2pp，无法与面板直接对账）

  ⚠️ 本版基线 = V4.6，V4.6 相对 V4.5 共 6 处改动（此前误述为"仅 TRAIL_PCT 一处"，
     现更正）：MAX_PER_SECTOR 2→3 / DIFFUSE_POSITION_RATIO 0.10→0.15 /
     ATR_STOP_MIN_PCT 0.04→0.03 / ATR_STOP_MAX_PCT 0.08→0.05 /
     TRAIL_PCT 0.10→0.07 / MAX_CANDIDATES 6→10
     ⚠️ 其中 TRAIL_PCT 已由本版 P1-4 覆盖回 **0.10**，故 V4.7 相对 V4.5 实际只继承
        V4.6 的其余 5 处；其余 4 项（MAX_PER_SECTOR / DIFFUSE_POSITION_RATIO /
        ATR_STOP 上下限 / MAX_CANDIDATES）按 V4.6 值保留。

  ⚠️ 回测可比性提示：入场价口径（V4.5 的 B-6）与出场时点（本版 P0-1）均已变化，
     请只看"改动前后的差值"，不要与 V4.4 及更早版本的收益绝对值直接比较。

## V4.5 演进说明（保留备查）
V4.5 = V4.4 + 两类改动（**只针对"回测诊断"确认的问题，不动选股主线逻辑**）：
  依据：《热点早盘001-收益提升诊断.md》（2026-05-06~06-30 区间，46 笔平仓逐笔还原）
  诊断结论：选股有效、出场致命 —— 40 笔亏损 100% 出自"板块联动清仓"一个分支，
  平仓 72% 集中在 09:31~09:35；折年双边换手约 68 次（预算 21 次），成本吃掉全部毛利。

  ── A 组：参数级（低风险，改常量） ──────────────────────────────
    BUY_TIME              10:00   → 09:32   避开 09:35-10:00 冲高段
    EARLY_TIME            09:35   → 09:31   保证"补卖/信号重试"先于建仓执行
    RISK_FALLBACK_TIME    14:58   → 14:48   承接板块清仓时点迁移
    SIGNAL_DAY_GAIN_MAX   8.0     → 5.0     信号日涨幅越大，次日高开回落概率越高
    TRAIL_ARM_PCT         0.03    → 0.05    3% 就在噪声区武装移动止盈
    TRAIL_PCT             0.08    → 0.10    8% 相对 3% 武装线过紧 → 小赚变大亏
    RETREAT_MA            5       → 10      5 日线对热点票噪声过大
    MIN_HOLD_FOR_TIGHT_STOP 5     → 3       并首次应用到"板块级清仓"
    MAX_POSITIONS         5       → 6       分散度提升
    POSITION_RATIO        0.18    → 0.15    单票冲击成本下降
    MAX_CANDIDATES        10      → 6       配合"每日最多建仓 2 笔"降频
    TURNOVER_WINDOW_DAYS  365(自然日) → 20(交易日)  旧值使熔断在数学上永不触发
    MAX_ANNUAL_TURNS      21      → 30      按新持仓周期重算（旧值与实际严重脱节）

  ── B 组：逻辑级（7 项） ────────────────────────────────────
    B-1 classify_stage：衰退改为"≤前 5 日均值×50% + 连续 2 日确认"
        （旧：z < max(1, 昨日×0.5) → 2→1 的常态波动即判"退潮"，今天主线明天衰退）
    B-2 _sector_killed：主判据由 zt_cnt（离散小整数）改为 zt_rate（连续比率）
    B-3 monitor_risk 分支①：清仓条件由"仅浮亏"改为"浮亏 且 跌破破位线
        （入场日最低价 / T-1收盘-3% 取更深者）"，并加"最短持有 ≥3 日"保护
    B-4 板块级清仓执行时点：09:31（盘中每分钟）→ 14:48（盘内一次判定）
    B-5 _do_sell 内同步记账 → 换手统计不再低估一半，熔断真正可用
    B-6 _live_price_and_ref：无日内价时禁止静默退化，改"显式保守假设
        （成交价 = T-1 收盘 ×(1+1%)）+ 显式告警"，并尽力从 handle_data 捕获日内价
    B-7 持仓层新增"产业链簇"约束（Jaccard>0.3 同簇合计仓位 ≤40%）
    B-8 新增分批止盈状态机（浮盈 ≥12% 减半，剩余跟移动止盈）

  ── 新增可观测性（这次是"改完能验证"的关键） ─────────────────────
    [候选漏斗] 逐项打印候选被哪一道条件剔除（已封板/涨幅过大/量比不足/振幅下半…），
              下次回测不必再靠逐笔反推就能看出"候选死在哪"。
    [口径-假设] 明确标注有多少笔建仓用的是"假设价"而非真实快照价；该假设下
              双护栏不构成过滤，结论与实盘不可直接比。
    [初始化] 打印 V4.5 全部关键参数 + "信号日涨幅带宽过窄"自检告警。

  ⚠️ 回测可比性提示：B-6 生效后，V4.5 的收益绝对值与 V4.4 之前**不可直接比较**
     （入场价口径变了）。请以"平仓笔数 / 平均持仓天数 / 换手次数 / 最大回撤"四项
     硬指标的先降后升来判改进是否有效。

## V4.1 数据层补丁（2026-09-14 回测发现"0 成交"后修复）
  回测现象：连续多日 `[信号] 批量取数 0/5645 只成功` → 全池无信号、零成交。
  根因：`_hist_call` 只在 `fq="pre"` 抛**异常**时才降级不复权；而本券商
  `get_history(..., fq="pre")` 返回**空结果（无异常）**，被误判为"fq 可用"，
  永久用 fq='pre' 取数 → 每批皆空。这违反 ptrade-strategy-dev 的 R4（降级须显式告警、
  绝不静默换口径）。
  修复：
    - 新增 `_has_data()`：空结果（含空 dict）视为"fq 不支持"，自动改不复权重试并告警；
    - `fetch` 首批次新增 `[诊断]` 日志，打印真实 get_history 返回形态（type/keys/首值 repr），
      若补丁后仍 0 行，凭此日志即可定位是返回形态不匹配（再修 `_rows_from_any`）。

## 已确认的平台口径（V4.5 按此实现，不再猜测）
  1) get_history **含当日 bar** —— 盘前无当日 bar，建仓时点最后一根为进行中 bar；
  2) volume 单位为 **股**（成交额 = volume × close，不乘 100）；
  3) order_value 限价参数名为 **limit_price**（下划线式）；
  4) 代码后缀 .SS/.SZ/.BJ；持仓可卖字段 enable_amount；Python3.5（无 f-string/无 os）。

## V4.8 时间线（★ = 相对 V4.7 变动）
```
T 日 盘前   before_trading_start
              ① 冷静期衰减 / 持仓天数+1 / 持仓日K缓存（供盘中零取数风控）
              ② ★信号层★ 全池批量取数（drop_today=True）→ 板块强度
                 → 三阶段 → 主线(3条) → 候选(每板块只取前3只) + [候选漏斗] 日志
              ③ ★V4.8★ set_universe(候选 + 持仓)  ← 护栏空转的根因修复
       ↓ 候选只存代码与特征，不存成交价
T 日 09:31  early_job   ① 补卖昨日"可卖=0"的排队单 ② 盘前信号层失败时重试一次
T 日 09:32  buy_job
              ① ★V4.8★ 避险档判定（指数<MA20 ⇒ 仓位×0.5、每日新建 1 笔）
              ② 取当日进行中价 = p_now（来源 current_data → handle_data 的 data →
                 当日 bar → 显式保守假设 T-1收盘×(1+1%)）+ [口径-探测] 诊断日志
              ③ 双护栏（仅当取到真实日内价时生效）：走弱不接刀 / 涨过头不追
              ④ 每板块限 3 只 + 产业链簇 ≤50% + 每日新建 ≤2 笔 → order_value(..., limit_price=)
              ⑤ ★V4.8★ [成交] 递交 N 笔 / 受理 M 笔（成交率可观测）
T 日 盘中    handle_data
              ① 捕获候选日内价（多字段 × 多键探测）
              ② 移动止盈 / 分批止盈（★V4.8★ 浮盈≥10% 减至留 1 手）随时执行
              ③ 硬止损：仅当 now ≥ STOP_TIME_FLOOR(09:45) 执行；豁免最短持有期
                 ★V4.8★ 两段式：首次触发只减半 → 次日仍触发才清仓；
                           同日跌破阈值×1.5 立即清仓；收窄至阈值×0.5 撤销标记
              ④ 破均线清仓：仅当 now ≥ EXIT_BREAK_TIME(14:45) 判定（尾盘确认）
T 日 14:48  risk_fallback_job
              ① 板块级清仓唯一判定时点（当日一次）
              ② 盘内兜底风控
              ③ [净值] 日终总资产打印
```

## 实现状态表（V4.8 逐条自检，杜绝"声称已修"）
  | 项 | 状态 |
  |----|------|
  | ★两段式止损（首次减半 / 次日确认 / 深跌兜底 / 收窄撤销） | ★V4.8 新增 P0-1★ 已实现 |
  | ★ATR 止损带放宽至 clamp(1.8×ATR/成本, 5%, 12%)（原被 5% 上限压成固定阈值） | ★V4.8 修正 P0-1★ 已实现 |
  | ★降换手（每日新建 2 笔 / 扩散期 12%） | ★V4.8 调整 P0-2★ 已实现 |
  | ★set_universe 注册候选+持仓（修护栏 100% 空转的根因） | ★V4.8 新增 P0-3★ 已实现 |
  | ★[口径-探测] 诊断日志（data 键样本 + 命中数） | ★V4.8 新增 P0-3★ 已实现 |
  | ★产业链簇约束放松（Jaccard 0.3→0.5、同簇上限 40%→50%） | ★V4.8 调整 P1-1★ 已实现 |
  | ★分批止盈阈值 12%→10%（V4.7 实测 7 笔全挤在 12.0~13.0%） | ★V4.8 调整 P1-2★ 已实现 |
  | ★市场级避险档（指数<MA20 ⇒ 半仓减速 + 每日 1 笔） | ★V4.8 新增 P1-3★ 已实现 |
  | ★[成交] 递交/受理笔数统计 | ★V4.8 新增 P2-1★ 已实现 |
  | ★统一出场时间闸门（破均线 14:45 尾盘确认 + 硬止损 09:45 起） | ★V4.7 新增 P0-1★ 已实现 |
  | ★换手熔断真正可用（60 交易日窗口 × 6 次 ⇒ 折年 ≈25 次） | ★V4.7 修正 P0-2★ 已实现 |
  | ★硬止损豁免最短持有期 | ★V4.7 修正 P0-3★ 已实现（V4.6 仅注释声称） |
  | ★分批止盈"减仓后至少留 1 手"（原判据在仅剩 1 手时永不成立） | ★V4.7 修复 P1-1★ 已实现 |
  | ★入场限价放宽至快照×1.02（护栏 +3% 封顶） | ★V4.7 修正 P1-2★ 已实现 |
  | ★噪声日志去重 / [净值] 打印 | ★V4.7 新增 P2-1/P2-2★ 已实现 |
  | R1 可成交性优先（快照价成交 + 双护栏 + 不接刀 + 可交易性过滤） | 已实现（护栏在无日内价时明确标注"不生效"，不再假装已过滤） |
  | R2 口径清晰（T-1 完整收盘选股 + 建仓时点快照成交 + 护栏基准已收盘） | 已实现（全链路无未来函数） |
  | R3 换手预算（滚动统计 + 超预算停开新仓） | ★V4.5 双向记账 + 交易日窗口；★V4.7 阈值改为可触发的 6 次/60 交易日★ |
  | R4 降级显式告警（含取数为空、下单返回空、护栏基准退化） | 已实现（[口径-假设] / [口径-来源] 双日志；★V4.7 噪声去重后不再被淹没） |
  | ★每板块最多 3 只（候选层截断 + 持仓层二次计数） | 已实现（V4.6 由 2 调整） |
  | ★产业链簇约束（Jaccard>0.5 同簇 ≤50%） | ★V4.8 放松 P1-1★ 已实现（V4.5 新增 B-7） |
  | ★建仓时点 09:32（run_daily 注册 + 容错窗口 + 盘内兜底） | 已实现（V4.5 由 10:00 前移） |
  | ★板块级清仓 14:48 单点判定 + 最短持有 3 日 + 破位线 | 已实现（V4.5 新增 B-1/B-2/B-3/B-4） |
  | ★分批止盈（★V4.8 浮盈 10% 减半，剩余跟移动止盈） | 已实现（V4.5 新增 B-8；V4.7 修失效 bug） |
  | P0-4 T+1 可卖量（卖出取可卖；可卖=0 排队次日；取整到 100 股） | 已实现 |
  | 静默降级（订单回执 on_order + 空结果必告警） | 已实现 |
  | 量纲（按"股"，并打印标定） | 已实现 |
  | 标识符统一（全链路 6 位，修复持仓排除/冷静期失效） | 已实现 |
  | 涨跌幅自适应（主板10/创业科创20/北交所30/ST5） | 已实现 |
  | 板块强度归一化（剔除规模偏置）+ 宽口径剔除 + Jaccard 去重 | 已实现 |
  | 三阶段接入交易决策（启动买/扩散半仓回踩/衰退否决） | 已实现（V4.5 衰退判据升级） |
  | 移动止盈 + ATR 动态止损（★V4.8 两段式）+ 最短持有期 | 已实现（止损模式可切回固定 -3%） |
  | 市场级开关（涨停家数 + 指数 MA20）+ ★V4.8 避险档（半仓减速）★ | 已实现 |
  | 相对流动性约束 | 已实现 |
  | 批量取数 + 缓存（全池约 20 次调用；盘中零取数） | 已实现 |
  | 板块池题材陈旧（source=sina） | 已解决：已用东方财富 push2delay 重生成真实板块池（496 行业 + 504 概念 / 5645 标的），见 output/sector_map.json |
  | 已知未解决：静态池滞后（建议日频刷新） | 需本地流程，见变更说明 |
  | 已知未解决：建仓当日被 T+1 锁定至次日 | 制度约束，见变更说明第七节 |
  | 已知未解决：板块池生成时点偏差（sector_map 生成于 2026-09-14 却用于 5~6 月回测） | 需保留历史快照，本轮仅在结论中标注 |

## 平台约束
  托管机房、内网无外网、Python3.5（代码无 f-string / 无类型注解 / 无 os）、
  仅内置 API；证券尾缀 .SS/.SZ/.BJ；持仓可卖字段 enable_amount。

## 运行模式
  TRADE_ENABLED=False = 信号模式（只输出不下单）；核对无误再改 True。

⚠️ 实盘自动交易风险自负。建议：信号模式跑 3-5 日 → 比对盘面 → 模拟盘 → 小资金实盘。
"""

import json
import datetime

try:
    import pandas as pd
except Exception:
    pd = None

# ============================================================
# 一、参数配置区
# ============================================================
TRADE_ENABLED = True                # True=自动交易；False=信号模式
SECTOR_MAP_FILE = "sector_map.json"

SECTOR_MAP_FALLBACK_PATHS = [
    "sector_map.json",
    "只读/sector_map.json",
    "../只读/sector_map.json",
    "readonly/sector_map.json",
    "user/19264938/files/sector_map.json",
    "/user/19264938/files/sector_map.json",
]

# ---- 调度时刻（V4.7：盘前选股 + 09:31 早盘准备 + 09:32 建仓 + 尾盘出场闸门）----
SIGNAL_AT_PREMARKET = True          # ★V4★ 选股在 before_trading_start（T-1 完整数据）
EARLY_TIME = "09:31"                # ★V4.5★ 补卖队列 + 盘前信号失败时重试（必须早于建仓）
BUY_TIME = "09:32"                  # ★V4.5★ 建仓时点：10:00 → 09:32，避开 09:35-10:00 冲高段
RISK_FALLBACK_TIME = "14:48"        # ★V4.5★ 兜底风控 + 板块级清仓的唯一时点（原 14:58）
SCHED_GRACE_MIN = 3                 # 容错窗口（分钟）；run_daily 不可用时按窗口兜底
# ★V4.7★ P0-1 统一出场时间闸门（本版核心：把所有"趋势类出场"从开盘噪声区迁出）
EXIT_BREAK_TIME = "14:45"           # 破均线清仓只在此时点后判定（尾盘确认；早于板块清仓 14:48）
STOP_TIME_FLOOR = "09:45"           # 硬止损最早执行时点（避开 09:30-09:45 集合竞价后噪声区）

# ---- 仓位与限价 ----
MAX_POSITIONS = 6                   # ★V4.5★ 同时在仓上限（原 5）→ 分散度提升
MAX_PER_SECTOR = 3                  # ★V4.6★ 2 → 3：回测中候选池与持仓板块高度重合（中芯概念/元件/稀缺资源），
                                    #         上限 2 使得"同板块候选全被跳过 → 全天 0 建仓"（6/12 两只候选全跳）。
POSITION_RATIO = 0.15               # ★V4.5★ 单票目标市值 / 总资产（原 0.18；6×15%=90%）
DIFFUSE_POSITION_RATIO = 0.12       # ★V4.8★ P0-2 0.15 → 0.12：V4.7 实测换手不降反升
                                    #         （折年 23.7 → 28.2 次、成本 2.59% → 3.08%），
                                    #         根因正是 V4.6 这两处"提仓位"改动。回测窗口内候选
                                    #         几乎全是扩散期，0.15 等于常态满仓 → 保留减仓语义、
                                    #         回到 0.12（V4.6 注释本身也建议过 0.12）。
MAX_NEW_POSITIONS_PER_DAY = 2       # ★V4.8★ P0-2 3 → 2：V4.7 每日 3 笔使换手升 19%。
                                    #         与"降换手"相比，"提仓位"是次要目标（毛利仅 1% 时
                                    #         提仓位 = 提成本）；先压频率，仓位利用率靠延长持有解决。
BUY_PREMIUM_PCT = 0.03              # 护栏上限 = T-1 收盘×(1+3%)，快照价高于此放弃（涨过头不追）
BUY_FLOOR_PCT = 0.015               # 护栏下限 = T-1 收盘×(1-1.5%)，快照价低于此放弃（走弱不接刀）
BUY_LIMIT_SLIP = 0.02               # ★V4.7★ P1-2 0.5% → 2%：治"跳空高开买不到"的拒单
                                    #   （限价 = min(快照×(1+2%), 护栏上限)，最终由 +3% 护栏封顶；
                                    #    旧值 0.5% 使限价≈昨收×1.015，跳空 >1.5% 的最强票一律买不到）
MAX_AMT_SHARE = 0.005               # 单票买入额 <= T-1 成交额 × 0.5%（相对流动性约束）
# ★V4.5★ B-6：无日内价时的显式保守成交价假设（禁止静默退化为"昨收+0.5%"）
ASSUME_ENTRY_PREMIUM = 0.01         # 假设成交价 = T-1 收盘 ×(1+1%)（比昨收更高的保守口径）

# ---- 出场纪律 ----
# ★V4.9★ P1-1 出场判据改用策略自有成本，不再读平台 cost_price
#   证据：V4.8 三段两式止损的"第二段 ÷ 第一段"浮亏比值 = 1.69 / 1.79 / 1.78
#   （三个独立样本高度一致）⇒ 指向平台在**部分卖出后改写 cost_price（摊薄成本）**，
#   于是同一价格下算出的浮亏百分比被放大，所有基于百分比的止盈/止损阈值都会随之漂移。
#   做法：建仓时记录 g.entry_px[code] = 本次实际采用的入场价，盈亏一律按它计算；
#        cost_price 仅用于对账，不参与任何出场判定。
#   ⚠️ 关键性质：分批减仓后**自有成本保持不变** —— 这正是我们想要的，
#      分批减仓不应改变剩余仓位的成本基准（平台的摊薄成本正是把这一点做错了）。
USE_OWN_COST = True                 # True：用 g.entry_px；False：沿用旧的 cost_price 口径
STOP_MODE = "atr"                   # "atr"=ATR动态止损（默认）；"fixed"=固定百分比
STOP_LOSS_PCT = 0.03                # STOP_MODE="fixed" 时生效
ATR_N = 14
ATR_STOP_MULT = 1.8                 # 止损 = 成本 - 1.8×ATR(14)
ATR_STOP_MIN_PCT = 0.04             # ★V4.9★ 0.05 → 0.04：给自适应留出 [4%,6%] 的有效窗口
                                    #         （V4.8 的 0.05~0.12 配合过宽的上限，等于放宽了亏损端）
ATR_STOP_MAX_PCT = 0.06             # ★V4.9★ P1-1 0.12 → 0.06（★核心★）：
                                    #         V4.8 实测三笔止损真实亏损 −10.2%/−10.2%/−16.2%，
                                    #         三笔合计吃掉约 −4.1pp 权益，而全窗只亏 1.90%
                                    #         （其余 25 笔净 +2.2pp）⇒ 亏损端才是决定项。
                                    #         收回到 6% 后，可达盈亏比上限 = 15%/6% = 2.5，
                                    #         首次具备保本可能（V4.8 为 10%/12% = 0.83）。
# ★V4.9★ P1-1 删除两段式止损，回归单段一次性清仓
#   V4.8 实证 3/3 完全失败：601001 / 300493 / 002449 全部在**同一分钟内**走完两段
#   （"首次只减半、留到次日"在真实行情中根本不成立），第二段只是多付一次滑点与手续费。
#   更隐蔽的是平台 cost_price 在部分卖出后被摊薄 ⇒ 同一价格下浮亏百分比被放大，
#   三个独立样本的"第二段/第一段"比值 = 1.69 / 1.79 / 1.78（高度一致 ⇒ 口径改写而非真实跌价）。
#   前置条件（成本口径不受分批影响）未满足 ⇒ 直接关闭，留待改用自有成本后再议。
STOP_STAGED = False                 # ★V4.9★ True → False：回归"一次清仓"（旧行为）
STOP_STAGE1_RATIO = 0.5             # 首次触发减仓比例（余仓继续跟移动止盈/止损）
STOP_RECOVER_RATIO = 0.5            # 浮亏收窄到 阈值×该比例 以内 → 撤销 stage1 标记（重新武装）
STOP_STAGE1_MIN_LOT = 2             # 仓位不足该手数时不做两段式（直接一次清仓）
STOP_STAGE1_HARD_MULT = 1.5         # 同日浮亏跌到 阈值×该倍数 → 无视两段式，立即清掉剩余
MIN_HOLD_FOR_TIGHT_STOP = 3         # ★V4.5★ 未满 3 个交易日不做紧止损/破均线（原 5）
# ★V4.6★ 硬止损豁免：最短持有期只保护"破均线"这类噪声信号，硬止损（ATR）永不受其约束。
# ★V4.4★ 出场改为纯移动止盈（自持仓最高价回撤 TRAIL_PCT 清仓），不再设 +10%/+15% 硬顶。
TRAIL_PCT = 0.15                    # ★V4.9★ P1-1 0.10 → 0.15：
                                    #         V4.8 归因实证 —— 全部利润集中在 3 笔，且它们都是
                                    #         **没触发任何规则、一路持有到最后**的票
                                    #         （301366 持 25 天 +40.6% / 300747 持 18 天 +29.3%），
                                    #         而平均持仓仅 6.50 天 ⇒ 盈利端被截断得太早。
                                    #         放宽回撤到 15%，与 6% 止损配对形成 2.5 的可达盈亏比。
TRAIL_ARM_PCT = 0.05                # ★V4.5★ 武装阈值：浮盈≥5% 后才挂移动止盈（原 0.03）
RETREAT_MA = 10                     # ★V4.5★ 破 10 日线清仓（原 5；5 日线对热点票噪声过大）
# ★V4.5★ B-8 分批止盈：浮盈达 PARTIAL_TAKE_PCT 先减半锁利，剩余跟移动止盈跑趋势
PARTIAL_TAKE_PCT = 0.15             # ★V4.9★ P1-1 0.10 → 0.15（与止损 6% 配对）：
                                    #         V4.8 是"赚 10% 就减半"，等于在赢仓刚起步时砍掉一半；
                                    #         提到 15% 让赢仓保留更多仓位跑趋势（≤0 关闭该功能）
PARTIAL_TAKE_RATIO = 0.5            # 单次减仓比例
COOL_DOWN_DAYS = 3                  # 止损后冷静期（交易日）

# ---- ★V4.9★ P0-3 赢家宽管（本版核心：让利润奔跑）----
#   归因实证：26 笔买入里 **前 3 笔合计 +87.3pp，其余 23 笔合计 −19.7pp**。
#   这三笔的共同点不是"选得特别准"，而是**没有被任何出场规则打断**、一路持有到最后；
#   而策略平均持仓只有 6.50 天。⇒ "赚钱的全是被忘了管的"是本节的设计依据。
#   ⚠️ 注意：这里**不是不卖**，而是对已证明自己在跑的持仓**放宽卖出条件**——只放宽，不豁免。
#      完全豁免会让赢仓最终回吐（V4.8 持有 10 日口径均值 −3.85% 即为反证）。
WINNER_EXEMPT_PCT = 0.15            # 浮盈 ≥ 该值进入"赢家状态"（≤0 关闭本功能）
WINNER_TRAIL_MULT = 1.6             # 赢家状态下移动止盈回撤的放宽倍数（0.15×1.6 = 24% 才走）
                                    #   常规 15% 回撤对能走趋势的热点票仍偏紧，赢仓需容忍更大自然震荡
WINNER_RETREAT_MA = 20              # 赢家状态改用更长均线判定趋势（≤0 则与 RETREAT_MA 一致）
                                    #   强势票沿 MA10 上行时经常被"贴着均线被震出"，改用 MA20 给它呼吸空间
WINNER_MAX_HOLD = 30                # 赢家状态的最长宽管交易日数（超过后恢复常规监管，防无限持有）

# ---- 板块级清仓（★V4.5★ B-1/B-2/B-3/B-4 新增参数）----
SECTOR_FADE_RATIO = 0.5             # 衰退判定：涨停家数 ≤ 前 5 日均值 × 该比例（并需连续 2 日成立）
SECTOR_COLLAPSE_BASE_RATE = 0.08    # 广度塌陷判定：前 5 日平均封板率须 ≥ 此值才算"真热点"
SECTOR_COLLAPSE_RATIO = 0.35        # 广度塌陷：今日封板率 ≤ 前 5 日均值 × 该比例（≤0 关闭该分支）
SECTOR_CLEAR_MIN_HOLD = 3           # 板块级清仓的最短持有交易日（防"建仓次日即砍"）
SECTOR_CLEAR_DROP = 0.03            # 破位线 = T-1 收盘 ×(1-3%)（与"入场日最低价"取更深者）

# ---- 产业链簇约束（★V4.5★ B-7）----
CLUSTER_JACCARD = 0.5               # ★V4.8★ P1-1 0.3 → 0.5：0.3 把"稀缺资源/元件/
                                    #         中芯概念"这类重叠板块全部划进同一簇，
                                    #         V4.7 实测该约束拦截建仓 **17 次**，仓位被自己
                                    #         的规则锁死在 2~3 只（候选日入选 5.3 只、
                                    #         实际只买 1~2 笔）。0.5 只拦"真同一题材"。
CLUSTER_MAX_WEIGHT = 0.50           # 同一簇合计目标仓位上限（≤0 关闭该约束）
                                    # ★V4.8★ 0.40 → 0.50：6 仓 × 15% = 90%，同簇 40% 只够
                                    #         2.6 只；压到 50% 允许 3 只，弱化"顺手把仓位锁死"。

# ---- 信号层 ----
STAGE_ZT_MIN = 2                    # 进入启动期所需最小当日涨停家数
TOP_MAIN_LINES = 3                  # 主线板块数量
MAX_SECTOR_SIZE = 80                # 成分数超过此值的板块不参与主线评选
# ★V4.1 修复★ 主线规模准入：1~2 成分板块无"跟涨"空间（其唯一/少数标的若封板即被剔除），
# 在回测中导致"主线 3 条全是 1 成分封板板块 → 每天 0 候选 → 整段 0 成交"。
MIN_MAIN_SECTOR_SIZE = 3            # 主线最低成分数（全量口径，来自 sector_map）
MIN_MAIN_FOLLOWERS = 2             # 封板龙头之外至少要有这么多可买跟涨标的（n_feat - zt_cnt）
# ★V4.4★ 主线最低涨停家数：zt_cnt<2 的脆弱板块（1→0 即"退潮"假信号）干脆不参选、不买。
MIN_MAIN_ZT_CNT = 2
# ★V4.9★ P0-2 主线分散约束（替代"按名字拉黑"的过拟合做法）
#   归因实证：26 笔买入里「稀缺资源」一条主线独占 8 笔（占样本 31%、也是最大一块仓位），
#   均值仅 +0.3%、中位 −3.3%、胜率 38%；而元件 +11.0% / 玻璃基板 +12.8%。
#   ⇒ 拖累来自"过度押注同一条主线"，而不是"板块内部选错了个股"。
#   但按板块名拉黑只会过拟合本区间（换个时期主线完全不同），
#   故改成通用的次数约束：同一主线在滚动窗口内超限即跳过，把额度留给其他主线。
MAINLINE_MAX_ENTRIES = 4            # ★V4.9★ 同一主线滚动窗口内最多建仓笔数（≤0 关闭）
MAINLINE_WINDOW_DAYS = 20           # ★V4.9★ 滚动窗口长度（交易日）
# ★V4.4★ 滞后题材板：只作确认过滤（确认候选动量），禁止成为主线驱动选股。
#         回测中"昨日高换手"约 10/12 天是主线，本质是买"昨天已涨的"，入场即滞后。
MAINLINE_BLOCKLIST = ("昨日高换手",)
# ★V4.4★ 剔除信号日已涨 >8% 的候选：次日高开买在阶段高点，易均值回归（入场滞后问题）。
SIGNAL_DAY_GAIN_MAX = 5.0           # ★V4.5★ 8.0 → 5.0（单位与 f["pct"] 一致，百分点）
# ★V4.5★ 入场质量硬条件（原实现只剔除"放量收低"，见 _stock_feat 的 REQUIRE_MAIN_INFLOW）
SIGNAL_DAY_POS_MIN = 0.5            # 信号日必须收在当日振幅上半（(C-L)/(H-L) ≥ 该值；≤0 关闭）
SIGNAL_DAY_VR_MIN = 1.2             # 启动期候选量比下限（≤0 关闭；扩散期另有缩量上限约束）
MAX_CANDIDATES = 10                 # ★V4.6★ 6 → 10：候选池过浅时，"板块满 / 高价股不足一手"跳过后
                                    #         当天就没得买了（6/12、6/17 均全天 0 建仓）。恢复 10 做缓冲。
HOT_GAIN_MIN = 4.0                  # 成分入选板块强度统计 / 启动期候选的最小区间涨幅(%)
DIFFUSE_VR_MAX = 1.5                # 扩散期"回踩"要求：量比下限（缩量）
REQUIRE_NO_ST = True                # 剔除 ST/*ST
MIN_HIST_BARS = 60                  # 剔除次新（并保 MA60 计算）
MIN_AMOUNT = 3e8                    # 成交额下限 3 亿元（volume 单位=股，真实生效）
REQUIRE_MAIN_INFLOW = True          # 剔除主力净流出近似（放量 + 收在振幅下半）
FLOW_LAG_VR = 2.0                   # 净流出近似量比阈值
VOL_RATIO_ADJUST = False            # ★V4★ 选股用 T-1 完整日K，量比本身就是全日量比，
                                    #        不需要 V3 那种"按已交易分钟折算"的补偿。
                                    #        （V3 因为取的是尾盘快照的残缺量才必须折算）

BROAD_TAG_BLACKLIST = (             # 宽口径属性标签（非题材），禁止参与主线评选
    "融资融券", "参股金融", "金融参股", "专精特新", "股权激励",
    "业绩预升", "业绩预降", "重组概念", "次新股", "其它行业",
    "超大盘", "含GDR", "含H股", "央企50", "基金重仓", "保险重仓", "股期概念",
)

# ---- 市场级开关 ----
MARKET_ZT_FLOOR = 25                # 板块池内涨停家数低于此值 → 停开新仓
INDEX_FOR_REGIME = "000300.SS"
INDEX_BARS = 60
# ★V4.1★ 市场开关：是否额外要求沪深300 站上 MA20 才开仓。
# 纯热点/情绪策略对宽基趋势不敏感（热点常在震荡/弱势中更活跃），该硬开关曾把回测中
# 唯一一只候选（002815）也拦掉。弱势市想放开，可设 False，仅保留涨停家数广度地板。
REGIME_USE_INDEX_MA20 = False
# ★V4.8★ P1-3 市场级避险档（"减速"而非"急停"）
#   背景：V4.7 主跌段 5/13~6/15 跌 10.62%，其间 16 笔止损有 14 笔落在这段，
#   而 MARKET_ZT_FLOOR（池内涨停<25 家）与 REGIME_USE_INDEX_MA20 一次都没触发。
#   与 V4.1 那个"全停"硬开关的区别：本档在主跌段**继续参与但只用半仓**，
#   避免"要么满仓挨打、要么完全踏空"的二值困境。
#   口径：用盘前取的 g.index_rows（截至 T-1 的 60 根日K），与 market_regime_ok 一致。
REGIME_RISK_OFF_SCALE = 0.5         # 避险档下单票目标仓位缩放（≤0 或 ≥1 则关闭缩放）
REGIME_RISK_OFF_MAX_NEW = 1         # 避险档下每日新建仓笔数上限（≤0 则不改）
REGIME_RISK_OFF_MA_FAST = 5         # 快线（用于辅助判定下行趋势）

# ---- 经济性预算 ----
COST_PER_SIDE = 0.0035              # 单边成本（佣金0.03%+滑点0.2%+冲击0.1%+印花税均摊）
TARGET_ANNUAL_COST = 0.15           # 目标年化成本 ≤15%
# ★V4.7★ P0-2 修好核弹级口径 bug：旧值是"20【交易日】窗口 × 阈值 30 次"，而 30 次/20 日
# 折年 ≈375 次双边 —— 等于常年不触发（V4.5 实测年换手 50 次 → 20 日窗口仅约 4 次）。改：
#   窗口 20 → 60 交易日（约 3 个月），阈值 30 → 6 次（60 日 6 次 ⇒ 折年 ≈25 次，与目标一致）
# ⚠️ 39 天回测窗口 < 60 交易日 ⇒ 本次回测熔断仍不会触发；它是实盘长周期护栏，
#    回测内的换手压降由 P0-1（出场笔数下降）+ P1-3 实现。
MAX_ANNUAL_TURNS = 6                # 滚动窗口内允许的双边换手次数（超限则停开新仓）
TURNOVER_WINDOW_DAYS = 60           # ★V4.7★ 20 → 60 个【交易日】
                                    #（原 365【自然日】→ 38 天回测在数学上永不触发熔断）
MAX_BUYS_PER_MONTH = 20             # ★V4.5★ 每月建仓硬熔断（按自然月统计；≤0 关闭）
LOOKBACK = 70                       # 日K回看天数（>MIN_HIST_BARS，留新股余量）
POS_BARS = 30                       # 持仓日K缓存根数（供 MA5 / ATR14）

HIST_FIELDS = ["open", "close", "high", "low", "volume"]
FETCH_CHUNK = 200                   # 批量取数每批证券数
FETCH_CHUNK_SINGLE = 1              # 逐票降级时的批大小

# ============================================================
# 二、健康状态表（R4：禁止静默降级）
# ============================================================
_HEALTH = {"degraded": []}


def _degrade(tag, msg):
    _HEALTH["degraded"].append("[{}] {}".format(tag, msg))


def _dump_health(prefix):
    d = _HEALTH["degraded"]
    if d:
        log.info("{} 降级/异常 {} 项:".format(prefix, len(d)))
        for x in d[:20]:
            log.info("   - {}".format(x))
        if len(d) > 20:
            log.info("   - ... 另有 {} 项".format(len(d) - 20))
        _HEALTH["degraded"] = []


# ============================================================
# 三、基础工具
# ============================================================
def _pure(code):
    """提取 6 位数字代码。"""
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _suffix(code):
    """6 位代码 -> PTrade 代码（沪 .SS / 深 .SZ / 北交所 .BJ）。"""
    code = str(code)
    if "." in code:
        return code
    if code.startswith(("68", "60")):
        return code + ".SS"
    if code.startswith(("00", "30")):
        return code + ".SZ"
    if code.startswith(("8", "4")):
        return code + ".BJ"
    return code


def _canon(code):
    """★全策略唯一内部标识：6 位纯数字★
    持仓 map 的 key 与板块成分表必须同口径，否则 `code in held` / `code in cool_down`
    永不命中，排除持仓与冷静期会全部失效。全链路统一走本函数。"""
    return _pure(code)


def _limit_pct(code, is_st=False):
    """该标的当日涨跌幅限制（小数）。一刀切会导致创业板/科创/北交所/ST 双向失真。"""
    if is_st:
        return 0.05
    c = _canon(code)
    if c.startswith(("30", "68")):
        return 0.20
    if c.startswith(("8", "4")):
        return 0.30
    return 0.10


def _zt_line(code, is_st=False):
    """该标的"近似涨停"判定线（%），留 2% 容差。"""
    return _limit_pct(code, is_st) * 100.0 * 0.98


def _ma(vals, n):
    if len(vals) < n or not all(vals[-n:]):
        return None
    return sum(vals[-n:]) / float(n)


def _atr(rows, n=ATR_N):
    """ATR(n)：rows = [(date, close, high, low, vol, open), ...]。"""
    if len(rows) < n + 1:
        return None
    trs = []
    for i in range(len(rows) - n, len(rows)):
        _, c, h, l, _, _ = rows[i]
        pc = rows[i - 1][1]
        if not pc:
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return None
    return sum(trs) / float(len(trs))


def _pos_f(p, name):
    try:
        if isinstance(p, dict):
            return p.get(name)
        return getattr(p, name, None)
    except Exception:
        return None


def _tradeable_amount(px):
    """T+1 可卖量。
    ★只以 enable_amount 为准★：该字段存在但为 0（当日新仓）时必须返回 0 →
    记入次日队列，绝不回退到 current_amount 发废单。
    仅当字段完全不存在时才回退 current_amount。"""
    a = _pos_f(px, "enable_amount")
    if a is None:
        a = _pos_f(px, "current_amount")
    return a or 0


def _round_lot(amount, held):
    """卖出量取整到 100 股；不足一手则全卖。"""
    a = int(amount / 100) * 100
    if a <= 0 and amount > 0:
        a = held
    return min(int(a), int(held))


def _now_str(context):
    for getter in (lambda: context.blotter.current_dt,
                   lambda: context.now,
                   lambda: get_datetime()):
        try:
            return getter().strftime("%H:%M")
        except Exception:
            continue
    return ""


def _now_dt(context):
    for getter in (lambda: context.blotter.current_dt,
                   lambda: context.now,
                   lambda: get_datetime()):
        try:
            return getter()
        except Exception:
            continue
    return None


def _today_str(context):
    dt = _now_dt(context)
    try:
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _mm(s):
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return -1


def _in_window(now, target, grace=SCHED_GRACE_MIN):
    t, n = _mm(target), _mm(now)
    if t < 0 or n < 0:
        return False
    return 0 <= n - t < grace


def _elapsed_min(now):
    """当日已交易分钟数（09:30-11:30 + 13:00-15:00，共 240）。"""
    n = _mm(now)
    if n < 0:
        return 240
    am = max(0, min(n, 11 * 60 + 30) - (9 * 60 + 30))
    pm = max(0, min(n, 15 * 60) - 13 * 60)
    return max(1, am + pm)


def _date_str(x):
    """K 线日期标签 -> 'YYYY-MM-DD'（兼容 8位整数 20260908 / 字符串 2026-09-08 / Timestamp）。

    ★V4.2 修复★ 回测数据 get_history 返回的日期是 8 位整数（如 20260908），而 _today_str
    产出 '2026-09-08'。旧实现直接 str(x)[:10]='20260908' 与 today 永远不等，导致 _is_today_row
    恒为 False —— "未见当日 bar" 是**误报**，且护栏基准 c_prev 被错当成当日价、开盘越界护栏整体失效。
    归一化 8 位整数后，回测若含当日 bar 则护栏恢复精确；若确实不含，误报消失、真实告警保留。
    """
    s = str(x).strip()
    if len(s) == 8 and s.isdigit():
        return "{}-{}-{}".format(s[0:4], s[4:6], s[6:8])
    return s[:10]


def _is_today_row(row, today):
    """该行是否为"当日进行中 bar"。"""
    if not today:
        return False
    return _date_str(row[0]) == today


def _cash_of(context, total_asset, held_cnt):
    c = 0.0
    try:
        c = float(context.portfolio.cash)
    except Exception:
        pass
    if c <= 0:
        try:
            c = float(get_cash())
        except Exception:
            pass
    if c <= 0:
        c = total_asset * (1.0 - held_cnt * POSITION_RATIO)
    return c


def _total_asset(context):
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        pass
    try:
        return float(get_total_assets())
    except Exception as e:
        _degrade("asset", "总资产获取失败: {}".format(repr(e)))
    return 0.0


def positions_map():
    """持仓快照 {6位code: position}。key 统一为 6 位，与板块成分表同口径。"""
    out = {}
    try:
        gp = get_positions()
        if isinstance(gp, dict):
            for k, p in gp.items():
                code = _pos_f(p, "security") or k
                if code:
                    out[_canon(code)] = p
            if out:
                return out
        for p in gp or []:
            code = _pos_f(p, "security")
            if code:
                out[_canon(code)] = p
        if out:
            return out
    except Exception as e:
        _degrade("positions", "get_positions fail: {}".format(repr(e)))
    try:
        p = get_position()
        code = _pos_f(p, "security")
        if code:
            out[_canon(code)] = p
    except Exception as e:
        _degrade("positions", "get_position fail: {}".format(repr(e)))
    return out


def _held_sector_count(held_codes, sector):
    """★V4 新增★ 持仓中属于该板块的只数（每板块限额用）。
    优先用买入时记录的 g.code_sector；策略重启导致该记录丢失时，
    退化为用板块反查索引 g.code_sectors 判断，绝不静默漏计。"""
    if not sector:
        return 0
    n = 0
    for c in held_codes:
        s = g.code_sector.get(c)
        if s is not None:
            if s == sector:
                n += 1
            continue
        if sector in (g.code_sectors.get(c) or set()):
            n += 1
    return n


def _mainline_recent_entries(sec):
    """★V4.9★ P0-2 主线滚动窗口内的建仓次数。

    背景：V4.8 归因发现「稀缺资源」一条主线独占 26 笔买入中的 **8 笔（占样本 31%）**，
    均值仅 +0.3%、中位 −3.3%、胜率 38%；而元件 +11.0% / 玻璃基板 +12.8%。
    ⇒ 拖累来自"过度押注同一条主线"，而不是"板块内部选错了个股"。

    ⚠️ 实现要点：**不按板块名做黑名单**。把"稀缺资源"写死进配置只会过拟合这一个
    回测区间（换个时期主线完全不同），换来的"改善"账面很好看但不可迁移。
    这里限制的是同一主线的**近期建仓次数**，属于对任何时期都成立的通用约束。
    """
    hist = getattr(g, "mainline_entries", None) or []
    if not sec or not hist or MAINLINE_MAX_ENTRIES <= 0:
        return 0
    today = getattr(g, "today", "") or ""
    # 交易日窗口 → 自然日窗口（一周 5 个交易日 ⇒ 乘 7/5）
    limit_days = MAINLINE_WINDOW_DAYS * 7.0 / 5.0
    n = 0
    for item in hist:
        try:
            dt, name = item[0], item[1]
        except Exception:
            continue
        if name != sec:
            continue
        if today and dt:
            try:
                d0 = datetime.datetime.strptime(str(dt)[:10], "%Y-%m-%d").date()
                d1 = datetime.datetime.strptime(str(today)[:10], "%Y-%m-%d").date()
                if (d1 - d0).days > limit_days:
                    continue
            except Exception:
                pass
        n += 1
    return n


def _cluster_held_count(held_codes, sector):
    """★V4.5★ B-7 持仓中与 sector 属同一"产业链簇"的只数。

    背景：同板块限 2 只（MAX_PER_SECTOR）挡不住**跨板块重叠**——回测中
    中芯概念 / 元件 / 数字芯片设计 / 玻璃基板 / 汽车芯片 高度重叠，
    6/8~6/11 一度同时持有 元件×2 + 中芯概念×2，实为同一个 "芯片" 风险敞口。
    判据：与持仓板块的成分 Jaccard > CLUSTER_JACCARD 即视为同簇。
    """
    if not sector or CLUSTER_JACCARD <= 0:
        return 0
    a = set(g.sector_codes.get(sector, []))
    if not a:
        return 0
    n = 0
    for c in held_codes:
        s = g.code_sector.get(c)
        if s and s == sector:
            n += 1
            continue
        if not s:
            # 买入记录缺失（策略重启）→ 用反查索引挑一个代表板块
            ss = g.code_sectors.get(c) or set()
            for x in ss:
                if x != sector:
                    s = x
                    break
        if not s:
            continue
        b = set(g.sector_codes.get(s, []))
        if not b:
            continue
        j = len(a & b) / float(len(a | b))
        if j > CLUSTER_JACCARD:
            n += 1
    return n


def _entry_breach_ref(code):
    """★V4.5★ 板块级清仓的"破位线" = min(入场日最低价, T-1收盘×(1-SECTOR_CLEAR_DROP))。

    取更深者（min）是有意为之：板块级清仓是最重的出场动作，宁可漏砍也不要误砍，
    这与本补丁"先把噪声驱动的负期望交易清零"的目标一致。
    """
    vals = [x for x in (g.entry_ref.get(code), g.entry_low.get(code)) if x]
    if not vals:
        return 0.0
    return min(vals)


# ============================================================
# 四、板块静态池载入
# ============================================================
def load_sector_map():
    """读取 sector_map.json。失败必显式告警并列出全部尝试路径。"""
    if getattr(g, "sector_map", None):
        return g.sector_map
    paths = list(SECTOR_MAP_FALLBACK_PATHS)
    try:
        root = str(get_research_path()).rstrip("/")
        paths = [root + "/只读/" + SECTOR_MAP_FILE,
                 root + "只读/" + SECTOR_MAP_FILE,
                 root + "/" + SECTOR_MAP_FILE] + paths
    except Exception:
        pass
    tried = []
    for path in paths:
        tried.append(path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ind = data.get("industry", {}) or {}
            con = data.get("concept", {}) or {}
            if not ind and not con:
                _degrade("sector_map", "板块池为空 industry={} concept={}".format(len(ind), len(con)))
                continue
            g.sector_map = {"industry": ind, "concept": con}
            log.info("[板块池] 行业{} 概念{} source={} 生成={} 路径={}".format(
                len(ind), len(con), data.get("source"), data.get("generated_at"), path))
            return g.sector_map
        except Exception as e:
            _degrade("sector_map", "候选[{}]读取异常: {}".format(path, repr(e)))
    _degrade("sector_map", "全部 {} 个候选路径均失败: {}".format(len(tried), "; ".join(tried)))
    log.info("[板块池] !! 载入失败：请将 {} 上传到 PTrade 只读目录，"
             "或把实际绝对路径填入 SECTOR_MAP_FALLBACK_PATHS 后重启".format(SECTOR_MAP_FILE))
    return None


def _build_sector_index():
    """展开板块 -> {板块名: [6位code]}，并建 code -> 板块集合 反查索引。"""
    sm = load_sector_map()
    if not sm:
        return {}, {}
    fwd, rev = {}, {}
    for group in (sm.get("industry", {}), sm.get("concept", {})):
        for name, codes in group.items():
            lst = []
            for c in codes:
                k = _canon(c)
                if not k:
                    continue
                lst.append(k)
                rev.setdefault(k, set()).add(name)
            fwd[name] = lst
    g.sector_codes = fwd
    g.code_sectors = rev
    return fwd, rev


# ============================================================
# 五、数据层：批量取数 + 缓存 + 返回形态自适配
# ============================================================
def _has_data(r):
    """判断 get_history 返回是否含可用 K 线，避免'无异常但空结果'被当成成功。"""
    if r is None:
        return False
    if isinstance(r, dict):
        for v in r.values():
            if _rows_from_any(v):
                return True
        return False
    try:
        if getattr(r, "empty", None) is not None:
            return not bool(r.empty)
    except Exception:
        pass
    if isinstance(r, (list, tuple)):
        return len(r) > 0
    return bool(r)


def _hist_call(n, fields, part, is_dict=None):
    """调用 get_history，自动适配 fq / is_dict 参数是否被本券商版本支持。
    ★关键修正（V4.1）★：fq='pre' 返回为空（静默失败）也视为不支持，自动改不复权重试；
    绝不把'无异常但空结果'当成 fq 可用（R4：任何降级都要显式告警，绝不静默换口径）。
    一旦确认 fq='pre' 可用（取到非空数据）则后续直接复用，避免重复校验。"""
    kw = {}
    if is_dict is not None:
        kw["is_dict"] = is_dict
    if getattr(g, "fq_ok", None) is True:
        return get_history(n, "1d", fields, part, fq="pre", **kw)
    if getattr(g, "fq_ok", None) is not False:
        try:
            r = get_history(n, "1d", fields, part, fq="pre", **kw)
            if _has_data(r):
                g.fq_ok = True
                g.fq_fail = 0
                return r
            # 带 fq 返回为空 -> 疑似不支持前复权，降级不复权（显式告警）
            g.fq_fail = getattr(g, "fq_fail", 0) + 1
            _degrade("hist", "带 fq='pre' 取数为空（疑似不支持复权），改不复权重试")
        except Exception as e:
            g.fq_fail = getattr(g, "fq_fail", 0) + 1
            if g.fq_fail >= 2:
                g.fq_ok = False
            _degrade("hist", "带 fq='pre' 取数失败（第{}次{}）: {}".format(
                g.fq_fail,
                "，已永久改为不复权" if g.fq_ok is False else "，本次改为不复权",
                repr(e)))
    g.fq_ok = False
    return get_history(n, "1d", fields, part, **kw)


def _probe_hist_mode():
    """一次性探测多证券 get_history 的返回形态：dict / multiindex / single。"""
    if getattr(g, "hist_mode", None):
        return g.hist_mode
    probe = ["000001.SZ", "600000.SS"]
    mode = "single"
    try:
        r = _hist_call(3, HIST_FIELDS, probe, is_dict=True)
        if isinstance(r, dict):
            mode = "dict"
    except Exception as e:
        _degrade("hist_mode", "is_dict 探测失败: {}".format(repr(e)))
    if mode != "dict":
        try:
            r = _hist_call(3, HIST_FIELDS, probe)
            cols = getattr(r, "columns", None)
            if cols is not None and getattr(cols, "nlevels", 1) > 1:
                mode = "multiindex"
        except Exception as e:
            _degrade("hist_mode", "平铺探测失败: {}".format(repr(e)))
    g.hist_mode = mode
    log.info("[数据层] get_history 多证券返回形态 = {} {}".format(
        mode, "（批量可用，全池一次取）" if mode != "single" else
        "（仅逐票，将自动缩小扫描范围，见扫描范围日志）"))
    return mode


def _field_of_col(c):
    """列标签 -> 字段名：兼容平铺列名与 (code, field) / (field, code) 两种 MultiIndex。"""
    if isinstance(c, tuple):
        return str(c[-1]).lower()
    return str(c).lower()


def _extract_rows(df, col_of, idx, want_open=True):
    """按列向量化取值（避免逐行访问的慢写法）。
    col_of: {字段名: 列标签}。返回 [(date, close, high, low, vol, open), ...]。"""
    def col(name):
        key = col_of.get(name)
        if key is None:
            return None
        try:
            return [float(x or 0) for x in df[key].tolist()]
        except Exception:
            return None

    cl = col("close")
    if not cl:
        return []
    hi = col("high") or list(cl)
    lo = col("low") or list(cl)
    vo = col("volume") or [0.0] * len(cl)
    op = col("open") if want_open else None
    if not op:
        op = list(cl)
    out = []
    n = min(len(cl), len(hi), len(lo), len(vo), len(op))
    for i in range(n):
        c = cl[i]
        if not c:
            continue
        out.append((idx[i], c, hi[i] or c, lo[i] or c, vo[i], op[i] or c))
    return out


def _rows_from_any(obj):
    """归一化任意 K 线载体为 [(date, close, high, low, vol, open), ...] 升序。"""
    if obj is None:
        return []
    if pd is not None and isinstance(obj, pd.DataFrame):
        try:
            col_of = {}
            for c in obj.columns:
                col_of[_field_of_col(c)] = c
            need = ("close", "high", "low", "volume")
            miss = [k for k in need if k not in col_of]
            if miss:
                _degrade("krows", "列名缺失 {} <- {}".format(miss, [str(c) for c in obj.columns][:8]))
                return []
            return _extract_rows(obj, col_of, list(obj.index))
        except Exception as e:
            _degrade("krows", "DataFrame 归一化失败: {}".format(repr(e)))
            return []
    if isinstance(obj, dict):
        try:
            cl = list(obj.get("close") or [])
            if not cl:
                return []
            hi = list(obj.get("high") or cl)
            lo = list(obj.get("low") or cl)
            vo = list(obj.get("volume") or [0.0] * len(cl))
            op = list(obj.get("open") or cl)
            dt = list(obj.get("date") or range(len(cl)))
            out = []
            for i in range(len(cl)):
                c = float(cl[i] or 0)
                if not c:
                    continue
                out.append((dt[i], c, float(hi[i] or c), float(lo[i] or c),
                            float(vo[i] or 0.0), float(op[i] or c)))
            return out
        except Exception:
            return []
    # ---- numpy 结构化数组（PTrade get_history dict 模式每值）----
    # 真实返回：dtype.names=('date','open','close','high','low','volume')，
    # 按字段名提取最稳；无字段名（普通 2D 数组）则按位置 (date,open,close,high,low,volume)。
    if getattr(obj, "dtype", None) is not None:
        names = getattr(obj.dtype, "names", None)
        if names:
            i_d = names.index("date") if "date" in names else 0
            i_o = names.index("open") if "open" in names else 1
            i_c = names.index("close") if "close" in names else 2
            i_h = names.index("high") if "high" in names else 3
            i_l = names.index("low") if "low" in names else 4
            i_v = names.index("volume") if "volume" in names else 5
            out = []
            for row in obj:
                try:
                    c = float(row[i_c])
                except Exception:
                    c = 0.0
                if not c:
                    continue
                try:
                    out.append((row[i_d], c, float(row[i_h]),
                                float(row[i_l]), float(row[i_v] or 0.0),
                                float(row[i_o])))
                except Exception:
                    continue
            return out
        out = []
        for row in obj:
            try:
                c = float(row[2])
            except Exception:
                c = 0.0
            if not c:
                continue
            try:
                out.append((row[0], c, float(row[3]), float(row[4]),
                            float(row[5] if len(row) > 5 else 0.0),
                            float(row[1] if len(row) > 1 else c)))
            except Exception:
                continue
        return out
    if isinstance(obj, list) and obj:
        try:
            out = []
            if isinstance(obj[0], dict):
                for x in obj:
                    c = float(x.get("close", 0) or 0)
                    if not c:
                        continue
                    out.append((x.get("date"), c, float(x.get("high", c) or c),
                                float(x.get("low", c) or c),
                                float(x.get("volume", 0) or 0),
                                float(x.get("open", c) or c)))
            else:
                for x in obj:
                    c = float(x[2])
                    if not c:
                        continue
                    out.append((x[0], c, float(x[3]), float(x[4]),
                                float(x[5]) if len(x) > 5 else 0.0,
                                float(x[1]) if len(x) > 1 else c))
            return out
        except Exception:
            return []
    return []


def _split_multiindex(df, part):
    """MultiIndex 列 DataFrame -> {6位code: rows}，自动判断 code 在第几层。"""
    out = {}
    if df is None or pd is None or not isinstance(df, pd.DataFrame):
        return out
    try:
        cols = list(df.columns)
        if not cols or getattr(df.columns, "nlevels", 1) < 2:
            return out
        bare = set(_canon(p) for p in part)
        lvl0 = set(_canon(c[0]) for c in cols)
        lvl1 = set(_canon(c[1]) for c in cols)
        code_is_0 = len(lvl0 & bare) >= len(lvl1 & bare)
        ci, fi = (0, 1) if code_is_0 else (1, 0)
        groups = {}
        for c in cols:
            groups.setdefault(_canon(c[ci]), {})[_field_of_col(c[fi])] = c
        idx = list(df.index)
        for code, col_of in groups.items():
            if not all(k in col_of for k in ("close", "high", "low", "volume")):
                continue
            rows = _extract_rows(df, col_of, idx)
            if rows:
                out[code] = rows
    except Exception as e:
        _degrade("krows", "MultiIndex 拆分失败: {}".format(repr(e)))
    return out


def _api_code(code):
    """转平台请求代码：已带后缀（如指数 000300.SS）原样保留，避免被误改成 .SZ。"""
    code = str(code)
    if "." in code:
        return code
    return _suffix(code)


def _diag_hist(r, mode):
    """首批次一次性诊断：把真实 get_history 返回形态打进日志，便于定位'0 行'根因。"""
    try:
        log.info("[诊断] get_history 返回 type={} mode={}".format(type(r).__name__, mode))
        if isinstance(r, dict):
            ks = list(r.keys())
            log.info("[诊断] dict 共 {} 键 示例keys={}".format(len(ks), ks[:3]))
            if ks:
                v0 = r[ks[0]]
                ln = len(v0) if hasattr(v0, "__len__") else "?"
                log.info("[诊断] 首值 type={} len={} repr={}".format(type(v0).__name__, ln, repr(v0)[:240]))
        elif hasattr(r, "empty"):
            log.info("[诊断] DataFrame empty={} columns={}".format(
                getattr(r, "empty", None), [str(c) for c in list(getattr(r, "columns", []))[:8]]))
        else:
            log.info("[诊断] repr={}".format(repr(r)[:240]))
    except Exception as e:
        log.info("[诊断] 记录异常: {}".format(repr(e)))


def fetch(codes, n, drop_today=False):
    """批量取数 -> {6位code: rows}。三级降级：dict -> multiindex -> single。

    ★V4 新增 drop_today★：为 True 时剔除"当日进行中 bar"，只保留已收盘日K。
    选股层必须传 True（口径：只用 T-1 及以前的已收盘数据）；
    建仓层取快照价时必须传 False（就是要当日进行中 bar 的最新价）。
    """
    keys, api = [], {}
    for c in codes:
        k = _canon(c)
        if not k or k in api:
            continue
        keys.append(k)
        api[k] = _api_code(c)
    out = {}
    if not keys:
        return out
    mode = _probe_hist_mode()
    chunk = FETCH_CHUNK if mode != "single" else FETCH_CHUNK_SINGLE
    for i in range(0, len(keys), chunk):
        batch = keys[i:i + chunk]
        part = [api[c] for c in batch]
        try:
            if mode == "dict":
                r = _hist_call(n, HIST_FIELDS, part, is_dict=True)
            elif mode == "multiindex":
                r = _hist_call(n, HIST_FIELDS, part)
            else:
                r = None
            # 首批次诊断（仅一次）：把真实返回形态打进日志
            if not getattr(g, "_diag_done", False):
                g._diag_done = True
                _diag_hist(r, mode)
            if mode == "dict":
                if isinstance(r, dict):
                    for k, v in r.items():
                        rows = _rows_from_any(v)
                        if rows:
                            out[_canon(k)] = rows
                    continue
                _degrade("fetch", "dict 模式返回非 dict，降级为逐票处理本批")
            if mode == "multiindex":
                got = _split_multiindex(r, part)
                out.update(got)
                if not got:
                    _degrade("fetch", "multiindex 解析为空，批起始 {}".format(i))
                continue
            for c, a in zip(batch, part):
                rows = _rows_from_any(_hist_call(n, HIST_FIELDS, [a]))
                if rows:
                    out[c] = rows
        except Exception as e:
            _degrade("fetch", "批 {} 取数异常: {}".format(i, repr(e)))
    if drop_today:
        _strip_today(out)
    return out


def _strip_today(rows_map):
    """★V4★ 就地剔除各标的的"当日进行中 bar"（双保险）。
    盘前取数时当日 bar 本就不存在，此处为防御：万一平台时间口径导致当日 bar
    已生成，也不会把进行中的残缺 bar 当成已收盘数据用于选股。"""
    today = getattr(g, "today", None)
    if not today:
        return rows_map
    dropped = 0
    for k in list(rows_map.keys()):
        rows = rows_map[k]
        if rows and _is_today_row(rows[-1], today):
            rows_map[k] = rows[:-1]
            dropped += 1
    if dropped:
        log.info("[口径] 已剔除 {} 只标的的当日进行中 bar（选股仅用 T-1 及以前）".format(dropped))
    return rows_map


def _is_st(code):
    """ST 判定（带缓存）。只对通过量价筛选的少数标的调用，避免数千次查名。"""
    c = _canon(code)
    cache = g.st_name
    if c in cache:
        return cache[c]
    name = ""
    try:
        fn = globals().get("get_stock_name")
        if fn is not None:
            name = fn(_suffix(c)) or ""
    except Exception as e:
        _degrade("is_st", "get_stock_name({}) fail: {}".format(c, repr(e)))
    v = ("ST" in str(name).upper())
    cache[c] = v
    return v


# ============================================================
# 六、信号层：个股特征 -> 板块聚合 -> 主线 -> 三阶段
# ============================================================
def _stock_feat(code, rows, want_name=False):
    """单只个股特征。rows 来自缓存（V4 口径：T-1 及以前的完整日K）。
    最后一行即"最近一个已收盘交易日"，量比无需按已交易分钟折算。"""
    if not rows or len(rows) < MIN_HIST_BARS:
        return None
    closes = [r[1] for r in rows]
    vols = [r[4] for r in rows]
    c1, c0 = closes[-1], closes[-2]
    if not c0 or not c1:
        return None
    is_st = _is_st(code) if want_name else False
    zl = _zt_line(code, is_st)
    # 成交额：volume 单位=股，不乘 100
    amt = vols[-1] * c1
    if amt < MIN_AMOUNT:
        return None
    pct = (c1 / c0 - 1) * 100.0
    lb = 0
    for i in range(len(closes) - 1, 0, -1):
        pc = closes[i - 1]
        chg = (closes[i] / pc - 1) * 100.0 if pc else 0.0
        if chg >= zl:
            lb += 1
        else:
            break
    ma5v = sum(vols[-6:-1]) / 5.0 if len(vols) >= 6 and sum(vols[-6:-1]) > 0 else 0.0
    vol_ratio = (vols[-1] / ma5v) if ma5v else 0.0
    if VOL_RATIO_ADJUST:
        e = _elapsed_min(g.now_str)
        if 0 < e < 240:
            vol_ratio = vol_ratio * (240.0 / e)
    hi, lo = rows[-1][2], rows[-1][3]
    if REQUIRE_MAIN_INFLOW and hi > lo and c1 < (hi + lo) * 0.5 and vol_ratio >= FLOW_LAG_VR:
        return None
    # ★V4.5★ 信号日"收盘位置"：1=收在当日最高，0=收在当日最低。
    # 收在振幅下半（长上影/尾盘走弱）→ 次日高开回落概率显著偏高，入场质量差。
    pos_in_range = ((c1 - lo) / (hi - lo)) if hi > lo else 1.0
    ma20 = _ma(closes, 20)
    return {
        "code": _canon(code), "pct": round(pct, 2), "lianban": lb,
        "vol_ratio": round(vol_ratio, 2), "above20": bool(ma20 and c1 > ma20),
        "amt": amt, "close": c1, "zt_line": zl, "is_st": is_st,
        "pos_in_range": round(pos_in_range, 3),
    }


def build_sector_signal(sector_name, codes):
    """板块信号。强度全部归一化，剔除"成分越多越强"的规模偏置。"""
    feats = []
    for c in codes:
        f = g.feat.get(c)
        if f:
            feats.append(f)
    if not feats:
        return None
    n = float(len(feats))
    zt = [f for f in feats if f["pct"] >= f["zt_line"]]
    up = [f for f in feats if f["pct"] >= HOT_GAIN_MIN]
    avg_pct = sum(f["pct"] for f in feats) / n
    ratio_up = sum(1 for f in feats if f["above20"]) / n
    zt_rate = len(zt) / n
    up_rate = len(up) / n
    ladder = {"1": 0, "2": 0, "3": 0}
    for f in zt:
        if f["lianban"] >= 3:
            ladder["3"] += 1
        elif f["lianban"] == 2:
            ladder["2"] += 1
        else:
            ladder["1"] += 1
    strength = zt_rate * 50.0 + up_rate * 10.0 + ratio_up * 20.0 + avg_pct
    return {
        "sector": sector_name, "zt_cnt": len(zt), "up_cnt": len(up),
        "avg_pct": round(avg_pct, 2), "ratio_up": round(ratio_up, 3),
        "zt_rate": round(zt_rate, 4), "up_rate": round(up_rate, 4),
        "ladder": ladder, "strength": round(strength, 2), "n_feat": int(n),
    }


def classify_stage(sig, hist):
    """三阶段判定。

    ★V4.5★ B-1 修复★ 旧逻辑 `z < max(1.0, pz * 0.5)`（与"昨日单点"比减半）导致：
      zt_cnt 是四道过滤后的**离散小整数**（典型 2~5 家），日间 ±1~2 家纯属噪声，
      于是出现"5→2 判衰退 → 清仓 → 次日又成主线"的横跳。回测证据：被清仓最多的
      板块恰恰是反复当选主线的板块（稀缺资源 38 天里 17 天是主线，却被清 9 次）。

    新判定（两条同时成立才判"衰退"）：
      ① 相对量：今日 zt_cnt ≤ 前 5 个观测点均值 × SECTOR_FADE_RATIO（默认 0.5）
         —— 基准由"昨日一点"改为"前 5 日均值"，抗单日抖动；
      ② 连续性：昨日也必须满足各自基准下的衰减（连续 2 个交易日确认）
         —— 单日塌陷不再触发清仓。
    真实退潮（连续 4~5 日逐级下滑）依然会被抓到，只是不再被单日噪声触发。
    """
    z = sig["zt_cnt"]
    hist = [int(x) for x in (hist or [])]
    if not hist:
        return "启动" if z >= STAGE_ZT_MIN else "无"
    pz = hist[-1]
    avg5 = sum(hist) / float(len(hist))
    weak_now = z <= max(1.0, avg5 * SECTOR_FADE_RATIO)
    weak_prev = False
    if len(hist) >= 2:
        base_prev = sum(hist[:-1]) / float(len(hist) - 1)
        weak_prev = pz <= max(1.0, base_prev * SECTOR_FADE_RATIO)
    if weak_now and weak_prev:
        return "衰退"
    if pz < STAGE_ZT_MIN and z >= STAGE_ZT_MIN:
        return "启动"
    if z >= pz or avg5 >= STAGE_ZT_MIN:
        return "扩散"
    return "无"


def _main_line_groups(signals):
    """★V4.1 修复★ 主线：规模准入 + 跟涨标的下限 + 宽口径剔除 + Jaccard 去重 + 广度优先排序。

    旧版按归一化 strength 排序。strength 的 zt_rate 项给"封板率" 50 分上限，
    导致 1 成分板块（其唯一标的封板 → 封板率 100% → 强度≈90~100）永远霸榜。
    但 _pick_candidates 会剔除已封板标的，单成分板块因此永远产不出候选 →
    回测整段（8/26~9/11）每日 0 候选、0 成交。

    修复：
      ① 主线必须有足够成分（MIN_MAIN_SECTOR_SIZE）且封板龙头之外还有 >=
         MIN_MAIN_FOLLOWERS 只可买跟涨标的，否则不参与评选；
      ② 排序改用"广度优先评分"（封板龙头数×权重 + 可跟涨成分数×权重 + 板块均幅），
         让真正有广度的热点板块排到前面，而不是单票封板的小板块。
    """
    def ml_score(s):
        followers = max(0, s["n_feat"] - s["zt_cnt"])
        return s["zt_cnt"] * 3.0 + followers * 1.5 + s["avg_pct"] * 0.3

    sigs = sorted(signals, key=ml_score, reverse=True)
    picks, skipped = [], []
    for s in sigs:
        if len(picks) >= TOP_MAIN_LINES:
            break
        name = s["sector"]
        if s["zt_cnt"] < MIN_MAIN_ZT_CNT:
            skipped.append("{}(涨停{}<{})".format(name, s["zt_cnt"], MIN_MAIN_ZT_CNT))
            continue
        if name in BROAD_TAG_BLACKLIST:
            skipped.append(name + "(宽口径)")
            continue
        if name in MAINLINE_BLOCKLIST:
            skipped.append(name + "(确认过滤板)")
            continue
        cs = set(g.sector_codes.get(name, []))
        if not cs:
            continue
        if len(cs) > MAX_SECTOR_SIZE:
            skipped.append("{}(成分{})".format(name, len(cs)))
            continue
        if len(cs) < MIN_MAIN_SECTOR_SIZE:
            skipped.append("{}(成分{}<{})".format(name, len(cs), MIN_MAIN_SECTOR_SIZE))
            continue
        followers = s["n_feat"] - s["zt_cnt"]
        if followers < MIN_MAIN_FOLLOWERS:
            skipped.append("{}(可跟涨{}<{})".format(name, followers, MIN_MAIN_FOLLOWERS))
            continue
        dup = False
        for p in picks:
            ps = set(g.sector_codes.get(p["sector"], []))
            if not ps:
                continue
            if len(cs & ps) / float(len(cs | ps)) > 0.5:     # Jaccard
                dup = True
                break
        if not dup:
            picks.append(s)
    if skipped:
        log.info("[主线筛选] 剔除 {} 个: {}".format(len(skipped), skipped[:10]))
    return picks


def _pick_candidates(mains):
    """候选生成：三阶段接入决策 + 标识符统一 + ★V4 每板块只留前 2 只★。

    V4 新增：排序完成后按板块计数截断，每个板块最多进 MAX_PER_SECTOR 只。
    这是"每板块最多买 2 只"的**候选层**约束，与下单层的持仓计数形成双保险。
    """
    held = set(positions_map().keys())
    ht_set = set(g.sector_codes.get("昨日高换手", []))   # ★V4.4★ 确认过滤板（昨日高换手）成员
    cands, seen = [], set()
    # ★V4.5★ 候选漏斗：逐项统计"被哪一道条件剔除"，让"今天为什么没候选"一眼可见
    rej = {}

    def _rj(k):
        rej[k] = rej.get(k, 0) + 1

    n_raw = 0
    for s in mains:
        stage = s.get("stage", "无")
        if stage == "衰退":
            log.info("[候选] 板块 {} 处衰退期 → 一票否决".format(s["sector"]))
            continue
        for code in g.sector_codes.get(s["sector"], []):
            n_raw += 1
            if code in seen:
                _rj("跨板块/重复")
                continue
            if code in held:
                _rj("已持仓")
                continue
            f = g.feat.get(code)
            if not f:
                _rj("未过四道量价过滤")
                continue
            # 已封板/准封板不可成交 → 剔除（阈值按标的自适应）
            if f["pct"] >= f["zt_line"]:
                _rj("信号日已封板")
                continue
            if not f["above20"]:
                _rj("未站上MA20")
                continue
            if code in g.cool_down:
                _rj("冷静期")
                continue
            if stage == "扩散":
                # 扩散期只做回踩：温和涨幅 + 缩量，禁止高位追涨
                if not (0.0 <= f["pct"] < HOT_GAIN_MIN):
                    _rj("扩散期非回踩档")
                    continue
                if f["vol_ratio"] >= DIFFUSE_VR_MAX:
                    _rj("扩散期未缩量")
                    continue
            else:
                if f["pct"] < HOT_GAIN_MIN:
                    _rj("涨幅不足{:.0f}%".format(HOT_GAIN_MIN))
                    continue
                # ★V4.5★ 启动期新增"量比下限"硬条件（原实现只剔除"放量收低"）
                if SIGNAL_DAY_VR_MIN > 0 and f["vol_ratio"] < SIGNAL_DAY_VR_MIN:
                    _rj("启动期量比<{}".format(SIGNAL_DAY_VR_MIN))
                    continue
            # ★V4.4★ 剔除信号日涨幅超上限的候选（入场滞后：次日买高点易均值回归）
            if f["pct"] > SIGNAL_DAY_GAIN_MAX:
                _rj("涨幅>{:.0f}%".format(SIGNAL_DAY_GAIN_MAX))
                continue
            # ★V4.5★ 信号日必须收在振幅上半（长上影/尾盘走弱 → 次日高开回落概率高）
            if SIGNAL_DAY_POS_MIN > 0 and f.get("pos_in_range", 1.0) < SIGNAL_DAY_POS_MIN:
                _rj("收在振幅下半")
                continue
            # 量价已过关，最后才查名（省去数千次查名）
            if REQUIRE_NO_ST and _is_st(code):
                _rj("ST")
                seen.add(code)
                continue
            d = dict(f)
            d["sector"] = s["sector"]
            d["stage"] = stage
            d["ht_confirm"] = code in ht_set      # ★V4.4★ 是否同时属"昨日高换手"确认过滤板
            cands.append(d)
            seen.add(code)
    # ★V4.4★ 排序：涨幅 → 量比 → 确认过滤（同档优先"昨日高换手"确认标的）
    cands.sort(key=lambda x: (min(x["pct"], 9.0), min(x["vol_ratio"], 3.0), x.get("ht_confirm", False)), reverse=True)
    # ★V4：按板块截断，每个热点板块最多 MAX_PER_SECTOR 只★
    out, cnt = [], {}
    for c in cands:
        sec = c.get("sector")
        k = cnt.get(sec, 0)
        if k >= MAX_PER_SECTOR:
            continue
        cnt[sec] = k + 1
        out.append(c)
        if len(out) >= MAX_CANDIDATES:
            break
    if len(out) < len(cands):
        log.info("[候选] 每板块限 {} 只：{} → {} 只".format(
            MAX_PER_SECTOR, len(cands), len(out)))
    # ★V4.5★ 候选漏斗（一眼看出候选死在哪一步，省掉下一轮逐笔反推）
    if rej:
        top = sorted(rej.items(), key=lambda kv: -kv[1])[:8]
        log.info("[候选漏斗] 主线{}条 扫描成分{}只 → 过关{}只 → 入选{}只 | 剔除: {}".format(
            len(mains), n_raw, len(cands), len(out),
            ", ".join("{}={}".format(k, v) for k, v in top)))
    else:
        log.info("[候选漏斗] 主线{}条 扫描成分{}只 → 过关{}只 → 入选{}只（无剔除）".format(
            len(mains), n_raw, len(cands), len(out)))
    return out


# ============================================================
# 七、扫描范围（批量不可用时自动收缩，保证能跑完）
# ============================================================
def _scan_universe():
    """返回要扫描的 6 位代码列表。
    批量可用 -> 全池；逐票模式 -> 收缩到黑名单外 + 体量合规板块的并集（显式告警）。"""
    mode = _probe_hist_mode()
    allc = list(g.code_sectors.keys())
    if mode != "single":
        log.info("[扫描范围] 全池 {} 只（批量模式）".format(len(allc)))
        return allc
    cand_sectors = []
    for name, codes in g.sector_codes.items():
        if name in BROAD_TAG_BLACKLIST:
            continue
        if len(codes) > MAX_SECTOR_SIZE:
            continue
        cand_sectors.append((len(codes), name))
    cand_sectors.sort()
    picked, uni = [], set()
    for _, name in cand_sectors:
        if len(picked) >= 40:
            break
        picked.append(name)
        uni.update(g.sector_codes.get(name, []))
    log.info("[扫描范围] 逐票降级：仅扫 {} 个板块 / {} 只（原全池 {} 只）".format(
        len(picked), len(uni), len(allc)))
    _degrade("universe", "get_history 不支持批量，扫描范围已收缩至 {} 只".format(len(uni)))
    return sorted(uni)


# ============================================================
# 八、市场级开关
# ============================================================
def market_regime_ok():
    """① 池内涨停家数 >= 阈值；② 指数站上 MA20。数据全部用缓存，零额外请求。

    ⚠ 口径说明：判定用的是**最近一个已收盘交易日**的数据（T-1），不是建仓时点的
    实时状态。即"昨日市场是否处于可开仓状态"，与本策略"盘前定热点"的口径一致。
    """
    zt = 0
    for c, f in g.feat.items():
        if f["pct"] >= f["zt_line"]:
            zt += 1
    if g.feat and zt < MARKET_ZT_FLOOR:
        log.info("[市场开关] 昨日池内涨停约 {} 家 < 阈值 {} → 停开新仓".format(zt, MARKET_ZT_FLOOR))
        return False
    if REGIME_USE_INDEX_MA20:
        rows = g.index_rows
        if rows:
            closes = [r[1] for r in rows]
            ma20 = _ma(closes, 20)
            if ma20 and closes and closes[-1] < ma20:
                log.info("[市场开关] 指数 {:.1f} < MA20 {:.1f} → 停开新仓".format(closes[-1], ma20))
                return False
    return True


def market_risk_off():
    """★V4.8★ P1-3 市场级避险档判定（不做"急停"，只做"减速"）。

    触发条件（任一成立即进入避险档）：
      ① 沪深300 收盘 < MA20（宽基走弱）；或
      ② MA5 < MA20 且收盘 < MA5（快线下穿慢线 = 下行趋势确认，防"均线附近反复"）
    数据源：g.index_rows（_run_signal_layer 盘前取，drop_today=True，最新一根为 T-1）。
    结果缓存到 g.risk_off，供 buy_job 缩放仓位/降低每日新建上限。
    指数数据缺失时返回 False（不因数据问题误伤建仓）。
    """
    if REGIME_RISK_OFF_SCALE >= 1.0 and REGIME_RISK_OFF_MAX_NEW <= 0:
        return False
    rows = g.index_rows or []
    closes = [r[1] for r in rows if r[1]]
    if len(closes) < 20:
        return False
    c = closes[-1]
    ma20 = _ma(closes, 20)
    if not ma20:
        return False
    if c < ma20:
        log.info("[避险档] 指数 {:.1f} < MA20 {:.1f} → 本日新建仓仓位 ×{:.2f}、每日新建上限 {} 笔".format(
            c, ma20, REGIME_RISK_OFF_SCALE, REGIME_RISK_OFF_MAX_NEW))
        return True
    nf = max(2, int(REGIME_RISK_OFF_MA_FAST))
    if len(closes) >= nf:
        ma_fast = _ma(closes, nf)
        if ma_fast and ma_fast < ma20 and c < ma_fast:
            log.info("[避险档] MA{} {:.1f} < MA20 {:.1f} 且收盘 {:.1f} < 快线 → 下行趋势确认，"
                     "本日新建仓仓位 ×{:.2f}".format(nf, ma_fast, ma20, c, REGIME_RISK_OFF_SCALE))
            return True
    return False


# ============================================================
# 九、换手预算
# ============================================================
def _record_trade(value, side):
    """★V4.5★ B-5 修复★ 买入与卖出**都**记账（旧版只在买入调用 _record_trade，
    卖出不记账 → 换手统计低估约一半，"熔断"永远算不出真实换手）。
    日期取 g.today（before_trading_start / 建仓层均已维护），因此不再需要 context。"""
    try:
        d = getattr(g, "today", "") or ""
        g.trades.append((d, float(abs(value or 0)), side))
        if len(g.trades) > 8000:
            g.trades = g.trades[-4000:]
    except Exception:
        pass


def turnover_ok(context, total_asset):
    """滚动窗口双边换手 = 窗口内累计成交额 / (2×总资产)，超预算则停开新仓。

    ★V4.5★ 两处修复：
      ① 窗口由"365 自然日"改为"近 TURNOVER_WINDOW_DAYS 个交易日" —— 旧值使 38 天回测
         在数学上不可能触发熔断（日志中 [换手预算] 告警 0 次即为证）；
      ② 计价口径包含卖出（B-5 修好记账后），反映真实双边换手。
    ★V4.7★ P0-2★ 窗口 20 → 60 交易日、阈值 30 → 6 次（折年 ≈25 次）。旧阈值折年 ≈375 次，
      即使窗口已改交易日也仍然永不触发 —— 这才是"熔断形同虚设"的真正原因。
    """
    if not g.trades or total_asset <= 0:
        return True
    days = sorted(set(d for (d, v, s) in g.trades if d))
    if not days:
        return True
    keep = set(days[-TURNOVER_WINDOW_DAYS:]) if TURNOVER_WINDOW_DAYS > 0 else set(days)
    traded = sum(v for (d, v, _) in g.trades if d in keep)
    turns = traded / (2.0 * total_asset)
    if turns > MAX_ANNUAL_TURNS:
        log.info("[换手预算] 近 {} 个交易日双边换手 {:.1f} 次 > 预算 {} 次 → 停开新仓"
                 "（应放宽买入条件/延长持有，而非加止盈）".format(
                     min(len(days), TURNOVER_WINDOW_DAYS), turns, MAX_ANNUAL_TURNS))
        return False
    return True


def _buys_this_month_ok(context):
    """★V4.5★ 每月建仓硬熔断（按自然月，统计 g.trades 中 side=='buy' 的笔数）。"""
    if MAX_BUYS_PER_MONTH <= 0:
        return True
    m = (getattr(g, "today", "") or "")[:7]
    if not m:
        return True
    n = sum(1 for (d, v, s) in g.trades if s == "buy" and d[:7] == m)
    if n >= MAX_BUYS_PER_MONTH:
        log.info("[建仓上限] {} 已建仓 {} 笔 ≥ 上限 {} 笔 → 本月停开新仓".format(m, n, MAX_BUYS_PER_MONTH))
        return False
    return True


# ============================================================
# 十、信号主入口（V4：T 日盘前，用 T-1 完整收盘数据）
# ============================================================
def _run_signal_layer(context):
    """在盘前调用，全部数据为 T-1 及以前的完整已收盘日K。"""
    g.today = _today_str(context)
    if not _build_sector_index()[0]:
        log.info("[信号] 板块池不可用，本日不生成信号")
        g.pending_buy = []
        return
    uni = _scan_universe()
    g.hist = fetch(uni, LOOKBACK, drop_today=True)
    log.info("[信号] 批量取数 {}/{} 只成功".format(len(g.hist), len(uni)))
    if not g.hist:
        _degrade("signal", "全池取数为空（数据层故障），本日不生成信号")
        g.pending_buy = []
        return
    try:
        idx = fetch([INDEX_FOR_REGIME], INDEX_BARS, drop_today=True)
        g.index_rows = idx.get(_canon(INDEX_FOR_REGIME)) or []
    except Exception as e:
        _degrade("index", "指数取数失败: {}".format(repr(e)))
    g.feat = {}
    for c, rows in g.hist.items():
        f = _stock_feat(c, rows)
        if f:
            g.feat[c] = f
    log.info("[信号] 通过四道过滤的个股 {} 只（池内 {} 只）".format(len(g.feat), len(g.hist)))
    signals = []
    for name, codes in g.sector_codes.items():
        try:
            s = build_sector_signal(name, codes)
        except Exception as e:
            _degrade("signal", "板块 {} 信号异常: {}".format(name, repr(e)))
            continue
        if s:
            signals.append(s)
    for s in signals:
        h = g.prev_signal.get(s["sector"]) or []
        # ★V4.5★ 传入最近 5 个观测点（原只传 2 个）：衰退判定需要"前 5 日均值"作基准
        s["stage"] = classify_stage(s, h[-5:])
    mains = _main_line_groups(signals)
    if mains:
        log.info("[主线确定] " + " | ".join(
            "{}（成分{} 封板{} 可跟涨{} 阶段{}）".format(
                m["sector"], len(g.sector_codes.get(m["sector"], [])),
                m["zt_cnt"], max(0, m["n_feat"] - m["zt_cnt"]), m["stage"])
            for m in mains))
    for s in signals:
        s["is_main"] = s in mains
    # 信号榜
    log.info("-" * 72)
    log.info("[板块信号榜] 板块 | 归一强度 | 涨停/家数 | 涨停率 | 梯度 | 均幅 | >20线 | 阶段 | 主线")
    for s in sorted(signals, key=lambda x: x["strength"], reverse=True)[:12]:
        lb = s["ladder"]
        st = s["stage"] if s["stage"] in ("启动", "扩散", "衰退", "无") else "未知"
        log.info("  {:<8} {:>7} {:>4}/{:<4} {:>6.1%} [{}板{} 2板{} 3板+] {:>+6.1f}% {:>5.0%}  {} {}".format(
            s["sector"][:8], s["strength"], s["zt_cnt"], s["n_feat"], s["zt_rate"],
            lb["1"], lb["2"], lb["3"], s["avg_pct"], s["ratio_up"], st,
            "★主线" if s["is_main"] else ""))
    # 候选
    if mains:
        g.pending_buy = _pick_candidates(mains)
        log.info("[候选] 主线 {} 条 × 每板块限 {} 只 → 今日 09:32 建仓候选 {} 只".format(
            len(mains), MAX_PER_SECTOR, len(g.pending_buy)))
        for c in g.pending_buy:
            log.info("  {} {} [{}] +{:.1f}% 连板{} 量比{} 成交额{:.1f}亿".format(
                c["code"], c.get("sector", ""), c.get("stage", ""), c["pct"],
                c["lianban"], c["vol_ratio"], c["amt"] / 1e8))
    else:
        log.info("[候选] 今日无主线（可能全市场退潮），无候选")
        g.pending_buy = []
    if TRADE_ENABLED and not g.pending_buy:
        log.info("!! [告警] TRADE_ENABLED=True 但今日无候选/无主线，本轮不建仓（非信号模式）")
    for s in signals:
        g.prev_signal.setdefault(s["sector"], [])
        g.prev_signal[s["sector"]].append(s["zt_cnt"])
        g.prev_signal[s["sector"]] = g.prev_signal[s["sector"]][-6:]
        # ★V4.5★ 同步维护"封板率"历史（_sector_killed 的主判据由 zt_cnt 改为 zt_rate）
        g.prev_rate.setdefault(s["sector"], [])
        g.prev_rate[s["sector"]].append(s["zt_rate"])
        g.prev_rate[s["sector"]] = g.prev_rate[s["sector"]][-6:]
        g.prev_sig_day[s["sector"]] = g.today
    g.sector_state = signals
    # ★V4.8★ P0-3 把候选 + 持仓注册进 universe（handle_data 的 data 只覆盖 universe，
    #   这是 V4.7"护栏 100% 空转"的真因，见 _register_universe 的 docstring）
    _register_universe(g.pending_buy, positions_map())
    _log_unit_calibration()


def _log_unit_calibration():
    if getattr(g, "unit_logged", False):
        return
    for c, rows in g.hist.items():
        if len(rows) >= 2:
            _, cl, _, _, v, _ = rows[-1]
            log.info("[量纲标定] 样例 {} volume={} 收盘={} → 成交额={:.0f}元（按【股】口径，已确认）".format(
                c, v, cl, v * cl))
            g.unit_logged = True
            return


# ============================================================
# 十一、交易层：T 日 09:31 补卖 + T 日 09:32 建仓
# ============================================================
def _live_price_and_ref(context, codes):
    """取候选的【T 日建仓时点快照价 p_now】与【护栏基准 c_prev】。

    数据源优先级（★V4.5★ 新增第 2 级，配合 B-6）：
      1) get_current_data() 的 last_price / pre_close —— 实盘与回测引擎的当日真实快照价；
      2) g.intraday_px[c]（handle_data 的 data 参数捕获的当日进行中 bar 收盘）—— 回测可用时
         护栏才真正生效；
      3) 日 K 当日 bar close（get_history 若含当日 bar）；
      4) 以上全无 → **显式保守假设**：p_now = c_prev ×(1 + ASSUME_ENTRY_PREMIUM)，
         并打 [口径-假设] 日志 + 计入降级表。

    ★V4.5★ B-6 修复★ 旧实现第 4 级是"静默退化成 T-1 收盘"，后果有二：
      ① 快照价 ≡ 护栏基准（回测 72/72 笔），双护栏全程空转却无任何告警；
      ② 限价 = T-1收盘×1.005 → 只有当天回落到昨收附近的票才成交（约 29% 未成交），
         买到的样本被逆向筛选成"当日走弱的那批"。
    现在：假设价显式标注、来源逐笔可查（src 字段会打进 [买入] 日志），
    且明确提示"该假设下护栏不构成过滤，收益结论与实盘不可直接比"。
    """
    cur = None
    try:
        cur = get_current_data()
    except Exception:
        cur = None
    snap = fetch(codes, 2)
    today = _today_str(context)
    out = {}
    n_assumed = 0
    n_src = {}
    for c in codes:
        rows = snap.get(c, [])
        g_lp = 0.0
        g_pc = 0.0
        if cur:
            obj = cur.get(c)
            if obj is None:
                obj = cur.get(_suffix(c))
            if obj is not None:
                try:
                    g_lp = float(getattr(obj, "last_price", None) or 0)
                except Exception:
                    g_lp = 0.0
                try:
                    g_pc = float(getattr(obj, "pre_close", None) or 0)
                except Exception:
                    g_pc = 0.0
        has_today_bar = bool(rows) and len(rows) >= 2 and _is_today_row(rows[-1], today)
        live = float((g.intraday_px or {}).get(c) or 0.0)      # ★V4.5★ 第 2 级数据源
        # ---- p_now：日内快照 → handle_data 当日价 → 当日 bar → 留空待假设 ----
        src = ""
        p_now = 0.0
        if g_lp > 0:
            p_now, src = g_lp, "current_data"
        elif live > 0:
            p_now, src = live, "bar:handle_data"
        elif has_today_bar:
            p_now, src = rows[-1][1], "bar:history"
        # ---- c_prev：日内昨收 → T-1 收盘 ----
        if g_pc > 0:
            c_prev = g_pc
        elif has_today_bar:
            c_prev = rows[-2][1]
        elif rows:
            c_prev = rows[-1][1]
        else:
            c_prev = 0.0
        if not c_prev:
            continue
        assumed = False
        if not p_now:
            # ★V4.5★ 禁止静默退化：显式按保守假设定价
            p_now = c_prev * (1.0 + ASSUME_ENTRY_PREMIUM)
            src = "assumed(+{:.1%})".format(ASSUME_ENTRY_PREMIUM)
            assumed = True
            n_assumed += 1
        n_src[src] = n_src.get(src, 0) + 1
        out[c] = {
            "p_now": p_now,
            "c_prev": c_prev,
            "has_today": not assumed,
            "assumed": assumed,
            "src": src,
            # ★V4.5★ 假设价时护栏不构成过滤，建仓层据此降级告警（不再假装"护栏已生效"）
            "guard_active": not assumed,
        }
    if n_assumed:
        _degrade("anchor", "{} 只候选无可用日内价（回测通常不暴露当日 bar），"
                           "已按保守假设 成交价=T-1收盘×(1+{:.1%}) 计".format(
            n_assumed, ASSUME_ENTRY_PREMIUM))
        log.info("[口径-假设] {}/{} 只候选按保守假设定价（成交价=T-1收盘×{:.3f}）；"
                 "该假设下双护栏不构成过滤，收益绝对值不可与真实快照口径直接比较".format(
                     n_assumed, len(codes), 1 + ASSUME_ENTRY_PREMIUM))
    log.info("[口径-来源] 建仓价来源分布: {}".format(
        ", ".join("{}={}".format(k, v) for k, v in sorted(n_src.items())) or "无"))
    return out


def _do_sell(code, amount, reason, px_hint=None):
    """卖出。★V4.5★ B-5：卖出同步记账（_record_trade），使换手预算统计真实可用。

    ★V4.9★ P1-2 出场理由统一追加浮盈亏：
      V4.8 的 31 笔出场里有 **19 笔**（破均线 14 + 移动止盈 5）的 reason 不含浮盈亏，
      复盘时无法评估出场质量，只能靠面板汇总数字倒推 —— 这是当时最大的观测盲区。
      现在由 _do_sell **内部自动计算并追加**，调用方不必传（单点封装，杜绝遗漏）。
      止盈/止损类 reason 本身已带"浮盈/浮亏"字样 → 检测到即跳过，避免重复。
    """
    held_px = positions_map().get(code)
    held = (_pos_f(held_px, "current_amount") or _pos_f(held_px, "enable_amount") or 0) if held_px else amount
    amt = _round_lot(amount, held if held else amount)
    if amt <= 0:
        return
    # ★V4.9★ P1-2 缺失时才追加（盈亏数字用**策略自有成本**算，与出场判据同口径）
    try:
        if reason.find("浮") < 0:
            cost = 0.0
            if USE_OWN_COST:
                cost = (getattr(g, "entry_px", {}) or {}).get(code) or 0.0
            if not cost and held_px is not None:
                cost = _pos_f(held_px, "cost_price") or _pos_f(held_px, "avg_price") or 0.0
            px0 = 0.0
            if held_px is not None:
                px0 = (_pos_f(held_px, "last_price") or _pos_f(held_px, "price") or 0)
            px0 = float(px0 or 0) or float(px_hint or 0)
            if cost > 0 and px0 > 0:
                pr = px0 / cost - 1.0
                reason = "{} {} {:.1%}".format(reason, "浮盈" if pr >= 0 else "浮亏", abs(pr))
    except Exception:
        pass
    if TRADE_ENABLED:
        try:
            o = order(_suffix(code), -amt)
            log.info("[卖出] {} {} 股 原因:{} 委托={}".format(code, amt, reason, o))
        except Exception as e:
            _degrade("sell", "{} 下单异常: {}".format(code, repr(e)))
    else:
        log.info("[信号-卖] {} 应卖 {} 股 原因:{}".format(code, amt, reason))
    # ★V4.5★ 卖出计价：优先持仓最新价，其次调用方给的成交价提示，最后成本价
    try:
        px = 0.0
        if held_px is not None:
            px = (_pos_f(held_px, "last_price") or _pos_f(held_px, "price") or 0)
        px = float(px or 0) or float(px_hint or 0)
        _record_trade(amt * px, "sell")
    except Exception:
        pass


def early_job(context):
    """T 日 09:31：① 补处理昨日可卖=0 的止损队列；② 盘前信号失败时重试一次。

    ★V4.5★ 由 09:35 前移到 09:31：必须早于建仓时点（09:32），
    否则"补卖 + 信号重试"会落在建仓之后，重试出来的候选当天无人接手。
    """
    if not _is_trading_day_guard(context):
        return
    _HEALTH["degraded"] = []
    g.now_str = _now_str(context) or EARLY_TIME
    # ① 预埋卖出队列
    q = list(g.stop_queue)
    g.stop_queue = []
    for code, amount, reason in q:
        pm = positions_map()
        if code in pm:
            tr = _tradeable_amount(pm[code])
            if tr > 0:
                _do_sell(code, min(amount, tr), "队列补卖:" + reason)
            else:
                g.stop_queue.append((code, amount, reason))
                log.info("[队列] {} 仍不可卖，继续排队".format(code))
    # ② 盘前信号层若失败（无板块状态），此处重试一次（此时当日 bar 已生成，
    #    drop_today 会把它剔除，口径仍是 T-1 完整数据，不受影响）
    if SIGNAL_AT_PREMARKET and not g.sector_state:
        log.info("[早盘] 盘前信号层无产出 → 重试选股（口径仍为 T-1 完整日K）")
        try:
            _run_signal_layer(context)
        except Exception as e:
            _degrade("signal", "早盘重试信号层异常: {}".format(repr(e)))
    _dump_health("[早盘]")


def buy_job(context):
    """★V4.5★ 建仓层：T 日 09:32 取快照价 → 双护栏校验 → 每板块限 2 只 + 产业链簇约束
    → 每日最多 MAX_NEW_POSITIONS_PER_DAY 笔 → 限价建仓。

    相对 V4.4 的四点变化：
      ① 时点 10:00 → 09:32（避开 09:35-10:00 冲高段，降低"买在阶段高点"概率）；
      ② 每笔按所属阶段取仓位：启动期 POSITION_RATIO，扩散期 DIFFUSE_POSITION_RATIO；
      ③ 每日新建仓笔数硬上限（降频的核心手段，直接压降换手与成本）；
      ④ 产业链簇约束：与持仓板块 Jaccard>CLUSTER_JACCARD 视为同簇，同簇合计 ≤CLUSTER_MAX_WEIGHT。
    """
    if not _is_trading_day_guard(context):
        return
    _HEALTH["degraded"] = []
    g.now_str = _now_str(context) or BUY_TIME
    log.info("=" * 72)
    log.info("[{}] V4.5 建仓层（T-1 定热点 → {} 买入 | 每板块≤{}只 | 每日新建≤{}笔 | 单票{:.0%}）开始".format(
        g.now_str, BUY_TIME, MAX_PER_SECTOR, MAX_NEW_POSITIONS_PER_DAY, POSITION_RATIO))
    pending = list(g.pending_buy)
    if not pending:
        log.info("[买入] 今日无候选，不建仓")
        _dump_health("[建仓]")
        return
    pm = positions_map()
    held = set(pm.keys())
    remaining = MAX_POSITIONS - len(held)
    if remaining <= 0:
        log.info("[买入] 已满仓（{} 只），放弃本日 {} 笔候选".format(len(held), len(pending)))
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    # 已持仓的板块分布（每板块限额的持仓层约束）
    sec_now = {}
    for c in held:
        s = g.code_sector.get(c)
        if s:
            sec_now[s] = sec_now.get(s, 0) + 1
    log.info("[买入] 当前持仓 {} 只，额度 {} 只；板块分布 {}".format(
        len(held), remaining, sec_now if sec_now else "{}"))
    total = _total_asset(context)
    if total <= 0:
        _degrade("buy", "无法获取总资产，停止建仓")
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    # ★V4.8★ P1-3 市场级避险档：主跌段"减速"而非"急停"（仓位缩放 + 降低每日新建上限）
    risk_off = False
    try:
        risk_off = market_risk_off()
    except Exception as e:
        _degrade("regime", "避险档判定异常: {}".format(repr(e)))
    g.risk_off = risk_off
    risk_scale = REGIME_RISK_OFF_SCALE if (risk_off and 0 < REGIME_RISK_OFF_SCALE < 1) else 1.0
    # ★V4.5★ 单票目标分两档：启动期满仓、扩散期半仓（扩散期入场天然滞后）
    base_target = total * POSITION_RATIO * risk_scale
    cash = _cash_of(context, total, len(held))
    if base_target > cash:
        log.info("[买入] 停单兜底：单票目标 {:.0f} > 可用现金 {:.0f}，今日不建仓".format(base_target, cash))
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    if not turnover_ok(context, total):
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    if not _buys_this_month_ok(context):
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    if not market_regime_ok():
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    snap = _live_price_and_ref(context, [f["code"] for f in pending])
    if not snap:
        _degrade("buy", "候选全部无法取到快照价/T-1收盘价，放弃建仓")
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    idx = 0
    done = 0
    filled = 0
    n_sent = 0                      # ★V4.8★ P2-1 实际递交订单笔数（用于算成交率）
    # ★V4.5★ 每日新建仓笔数上限（降频 / 压换手的核心开关）
    daily_cap = MAX_NEW_POSITIONS_PER_DAY if MAX_NEW_POSITIONS_PER_DAY > 0 else remaining
    # ★V4.8★ P1-3 避险档：主跌段每日只建 1 笔
    if risk_off and REGIME_RISK_OFF_MAX_NEW > 0:
        daily_cap = min(daily_cap, REGIME_RISK_OFF_MAX_NEW)
    while idx < len(pending) and done < remaining and filled < daily_cap:
        f = pending[idx]
        idx += 1
        code = f["code"]
        if code in held:
            continue
        sec = f.get("sector")
        stage = f.get("stage", "启动")
        # ★V4.9★ P0-2 主线分散：同一主线滚动窗口内建仓次数超限 → 跳过，把额度让给其他主线
        if sec and MAINLINE_MAX_ENTRIES > 0:
            _n_sec = _mainline_recent_entries(sec)
            if _n_sec >= MAINLINE_MAX_ENTRIES:
                log.info("[买入] {} 主线「{}」近 {} 个交易日已建仓 {} 笔（≥上限{}）"
                         " → 跳过，额度留给其他主线".format(
                             code, sec, MAINLINE_WINDOW_DAYS, _n_sec, MAINLINE_MAX_ENTRIES))
                continue
        # ★V4：每个热点板块最多 MAX_PER_SECTOR 只（含已有持仓与本轮已买入）★
        if sec and _held_sector_count(held, sec) >= MAX_PER_SECTOR:
            log.info("[买入] {} 板块「{}」持仓已达 {} 只上限 → 跳过".format(
                code, sec, MAX_PER_SECTOR))
            continue
        # ★V4.5★ B-7 产业链簇约束
        if sec and CLUSTER_MAX_WEIGHT > 0:
            same = _cluster_held_count(held, sec)
            if (same + 1) * POSITION_RATIO > CLUSTER_MAX_WEIGHT:
                log.info("[买入] {} 板块「{}」与现有持仓同产业链簇(重叠{}只) → 同簇仓位将超 {:.0%}，跳过".format(
                    code, sec, same, CLUSTER_MAX_WEIGHT))
                continue
        sc = snap.get(code)
        if not sc:
            _degrade("buy", "{} 无快照价/T-1收盘价，放弃".format(code))
            continue
        p_now, c_prev = sc["p_now"], sc["c_prev"]
        # ★V4.5★ 单票目标：启动期满仓 / 扩散期半仓；★V4.8★ P1-3 避险档再乘缩放系数
        target = total * (DIFFUSE_POSITION_RATIO if stage == "扩散" else POSITION_RATIO) * risk_scale
        upper_ref = round(c_prev * (1 + BUY_PREMIUM_PCT), 2)
        lower_ref = round(c_prev * (1 - BUY_FLOOR_PCT), 2)
        if sc.get("guard_active", True):
            if p_now < lower_ref:
                log.info("[买入] {} 快照 {:.2f} < 下线 {:.2f}（早盘走弱不接刀）→ 放弃".format(
                    code, p_now, lower_ref))
                continue
            if p_now > upper_ref:
                log.info("[买入] {} 快照 {:.2f} > 上线 {:.2f}（早盘涨过头不追）→ 放弃".format(
                    code, p_now, upper_ref))
                continue
        else:
            log.info("[买入] {} 使用假设价（src={}），双护栏本笔不构成过滤".format(code, sc.get("src")))
        # 限价 = 快照价×(1+0.5%)，且不得超过护栏上限
        limit = min(round(p_now * (1 + BUY_LIMIT_SLIP), 2), upper_ref)
        cap = (f.get("amt") or 0) * MAX_AMT_SHARE
        if cap and target > cap:
            log.info("[买入] {} 目标 {:.0f} > 成交额×{:.1%}（{:.0f}）→ 放弃（流动性约束）".format(
                code, target, MAX_AMT_SHARE, cap))
            continue
        # ★V4.2 最小申报单位预检★ 避免科创板(<200股)/目标资金不足1手被拒（回测中 688123/688813
        # "下单返回空"、300852 "委托数量为0" 均属此类）。预检不通过直接跳过，不浪费下单额度。
        min_lot = 200 if code.startswith("688") else 100
        est_qty = int(target / limit) if limit > 0 else 0
        if est_qty < min_lot:
            _degrade("buy", "{} 目标{:.0f}/限价{:.2f}≈{}股<最小{}股，放弃（流动性不足）".format(
                code, target, limit, est_qty, min_lot))
            continue
        if TRADE_ENABLED:
            oid = None
            n_sent += 1                      # ★V4.8★ P2-1 递交订单计数
            try:
                oid = order_value(_suffix(code), target, limit_price=limit)
            except Exception as e:
                _degrade("buy", "{} 下单异常: {}".format(code, repr(e)))
            if oid:
                held.add(code)
                g.buy_today.add(code)
                g.hold_days[code] = 0
                g.peak[code] = 0.0
                g.code_sector[code] = sec
                # ★V4.9★ P1-1 记录策略自有成本：出场判据一律按它算；
                #        平台 cost_price 在部分卖出后会被摊薄，自 V4.9 起只用于对账。
                #        同一标的再次买入时会被重新赋值，因此无需额外清理。
                try:
                    if getattr(g, "entry_px", None) is None:
                        g.entry_px = {}
                    g.entry_px[code] = p_now
                except Exception:
                    pass
                # ★V4.9★ P0-2 主线建仓流水（支撑滚动窗口的主线次数约束）
                try:
                    if getattr(g, "mainline_entries", None) is None:
                        g.mainline_entries = []
                    g.mainline_entries.append((getattr(g, "today", "") or "", sec or ""))
                    if len(g.mainline_entries) > 400:      # 防止长期运行无限增长
                        g.mainline_entries = g.mainline_entries[-400:]
                except Exception:
                    pass
                # ★V4.5★ 板块级清仓的"破位线"：T-1 收盘 -SECTOR_CLEAR_DROP（入场日最低价次日再更新）
                g.entry_ref[code] = c_prev * (1.0 - SECTOR_CLEAR_DROP)
                g.entry_low[code] = g.entry_ref[code]
                g.partial_done.discard(code)
                if sec:
                    sec_now[sec] = sec_now.get(sec, 0) + 1
                _record_trade(target, "buy")
                filled += 1
                log.info("[买入] {} [{}|{}] {} 护栏[{:.2f},{:.2f}] 限价{:.2f} 目标{:.0f} 委托={}".format(
                    code, sec, stage,
                    ("假设价{:.2f}(src={})".format(p_now, sc.get("src")) if sc.get("assumed")
                     else "快照{:.2f}".format(p_now)),
                    lower_ref, upper_ref, limit, target, oid))
            else:
                _degrade("buy", "{} 下单返回空（未成交）".format(code))
        else:
            log.info("[信号-买] {} [{}|{}] src={} 快照{:.2f} 护栏[{:.2f},{:.2f}] 限价{:.2f} 目标{:.0f}".format(
                code, sec, stage, sc.get("src"), p_now, lower_ref, upper_ref, limit, target))
            filled += 1
        done += 1
    g.pending_buy = pending[idx:]
    if filled >= daily_cap and idx < len(pending):
        log.info("[买入] 已达每日新建仓上限 {} 笔 → 本日不再建仓（余 {} 只候选作废，未建仓不占用额度）".format(
            daily_cap, len(pending) - idx))
        g.pending_buy = []
    elif g.pending_buy:
        log.info("[买入] 本轮处理 {} 笔，剩余 {} 笔留待下次（切片用独立下标，不会错位）".format(
            done, len(g.pending_buy)))
    log.info("[买入] 本日成交建仓 {} 笔（上限 {}）".format(filled, daily_cap))
    # ★V4.8★ P2-1 成交率可观测：V4.7 拒单率 23.8% 只能靠 Order Rejected 计数才看得出
    if n_sent:
        log.info("[成交] 本日递交委托 {} 笔 / 受理 {} 笔 | 候选 {} 只 | 避险档={} | 单票缩放={:.2f}".format(
            n_sent, filled, len(pending), "ON" if risk_off else "off", risk_scale))
    _dump_health("[建仓]")


# ============================================================
# 十二、风控层（盘中每分钟；板块级清仓仅 14:48 一次）
# ============================================================
def _noise_once(code, kind):
    """★V4.7★ P2-1 噪声日志去重：同一标的、同一类噪声**每日最多打印一次**。

    R4 要求"降级必须显式告警"，但 V4.5 的日志 52% 被"破10日线但持仓仅N日"一条刷屏
    （单票最高 482 次、全局 2627 次），把真信号全淹了。这里做"每标的每类每日一次"，
    既保留可观测性又不刷屏。返回 True 表示"本次应当打印"。
    """
    try:
        day = getattr(g, "today", None)
        slot = g.noise_slot
        cur = slot.get(code)
        if cur is None:
            cur = {}
            slot[code] = cur
        if cur.get(kind) == day:
            return False
        cur[kind] = day
        return True
    except Exception:
        return True


def _hist_excl_today(name, store):
    """取历史序列并剔除"今日"那一笔（盘前信号层会把今日值 append 到末尾，
    盘中判定若不去掉就会把今日混进基准里）。"""
    h = list(store.get(name) or [])
    if h and g.prev_sig_day.get(name) == getattr(g, "today", None):
        h = h[:-1]
    return h


def _sector_killed():
    """板块级一票否决集合：仅当板块发生"真实退潮"才清仓。

    ★V4.5★ B-2 修复★ 主判据由 zt_cnt（离散小整数，典型 2~5 家）改为 zt_rate（封板率，
    连续比率），并把"前 2 日峰值"的绝对家数比较换成"前 5 日平均封板率的相对塌陷"：
      ① stage=="衰退"（classify_stage 已升级为"≤前 5 日均值×50% + 连续 2 日确认"）；或
      ② 广度真实塌陷：前 5 日平均封板率 ≥ SECTOR_COLLAPSE_BASE_RATE（确认它是真热点），
         且今日封板率 ≤ 该均值 × SECTOR_COLLAPSE_RATIO。
    真实退潮照抓，单日 +1/-1 家噪声不再触发。盈利持仓仍不在此层强平（交止盈处理）。
    """
    killed = set()
    for s in (g.sector_state or []):
        if s.get("stage") == "衰退":
            killed.add(s["sector"])
            continue
        if SECTOR_COLLAPSE_RATIO <= 0:
            continue
        rh = _hist_excl_today(s["sector"], g.prev_rate)
        if len(rh) >= 3:
            base = sum(rh[-5:]) / float(len(rh[-5:]))
            zr = float(s.get("zt_rate") or 0.0)
            if base >= SECTOR_COLLAPSE_BASE_RATE and zr <= base * SECTOR_COLLAPSE_RATIO:
                killed.add(s["sector"])
    return killed


def monitor_risk(context, sector_clear=False):
    """持仓风控（盘中每分钟 + 14:48 兜底）。

    ★V4.5★ B-4修复★ 板块级联动清仓只在"板块清仓窗口"（RISK_FALLBACK_TIME=14:48 之后）
    判定，且当日只判定一次；盘中每分钟只做止盈/止损/破均线。
    旧实现把板块清仓放在每分钟风控里、并以 T-1 盘后结论在 **09:31** 执行 —— 回测证据：
    46 笔平仓中 40 笔来自该分支、30 笔成交于 09:31，等于用昨天的结论砍在今天开盘的噪声区。
    """
    pm = positions_map()
    if not pm:
        return
    # ★V4.7★ P0-1 出场时间闸门的基准时钟（handle_data / risk_fallback_job 均已写入 g.now_str）
    now = getattr(g, "now_str", "") or _now_str(context) or ""
    if sector_clear:
        if g.sector_clear_slot == g.today:
            sector_clear = False     # 当日已判定过（run_daily 与 handle_data 可能同时触发）
        else:
            g.sector_clear_slot = g.today
            log.info("[风控] 进入板块级清仓窗口（{} 后仅判定一次）".format(RISK_FALLBACK_TIME))
    killed = _sector_killed() if sector_clear else set()
    for code, px in pm.items():
        amount = _pos_f(px, "current_amount") or _pos_f(px, "enable_amount") or 0
        if amount <= 0:
            continue
        cost = _pos_f(px, "cost_price") or _pos_f(px, "avg_price") or 0
        # ★V4.9★ P1-1 出场判据改用策略自有成本：
        #        平台 cost_price 在**部分卖出后会被摊薄**，导致同一价格下算出的浮亏百分比被放大
        #        （V4.8 实测两段式的"第二段÷第一段"比值 1.69/1.79/1.78，三个独立样本高度一致）。
        #        自有成本 g.entry_px 在建仓时锁定、分批减仓后**保持不变**，正是判据所需的性质。
        own_cost = (getattr(g, "entry_px", {}) or {}).get(code) or 0.0
        if USE_OWN_COST and own_cost > 0:
            cost = own_cost
        price_now = _pos_f(px, "last_price") or _pos_f(px, "price") or 0
        rows = g.pos_hist.get(code) or []
        closes = [r[1] for r in rows]
        if not price_now and closes:
            price_now = closes[-1]
        if not price_now:
            continue
        g.peak[code] = max(g.peak.get(code, 0.0), price_now)
        # ★V4.9★ P0-3 赢家状态：浮盈达标且未超最长宽管天数 → 对**移动止盈/破均线**放宽判据。
        #        注意是"放宽"不是"豁免"：完全豁免会让赢仓最终回吐
        #        （V4.8 持有 10 日口径均值 −3.85% 就是反证）。
        is_winner = False
        if cost and WINNER_EXEMPT_PCT > 0:
            _pr_now = price_now / cost - 1.0
            if _pr_now >= WINNER_EXEMPT_PCT and g.hold_days.get(code, 0) <= WINNER_MAX_HOLD:
                is_winner = True
                if _noise_once(code, "winner_on"):
                    log.info("[风控] {} 浮盈{:.1%}≥{:.0%} → 进入赢家宽管"
                             "（回撤放宽至{:.1%}、趋势线改用MA{}，最长{}日）".format(
                                 code, _pr_now, WINNER_EXEMPT_PCT,
                                 TRAIL_PCT * WINNER_TRAIL_MULT,
                                 WINNER_RETREAT_MA or RETREAT_MA, WINNER_MAX_HOLD))
        sell, reason = None, ""
        # ① 板块级联动清仓（★V4.5★ 仅 14:48 窗口判定；早于单票止损）
        # ★V4.3 修复★ 仅对【亏损】持仓强平；盈利持仓交由止盈/移动止盈处理，避免"起涨点砍赢仓"。
        # ★V4.5 B-3★ 光"浮亏"还不够，必须**真破位**：跌破 min(入场日最低价, T-1收盘-3%)；
        #             并加"最短持有 SECTOR_CLEAR_MIN_HOLD 个交易日"保护。
        #             旧逻辑"只要浮亏就砍"→ 建仓次日 09:31 被昨日盘后结论砍在起涨点（40 笔亏损全出于此）。
        sec = g.code_sector.get(code)
        if sec and sec in killed:
            pr_sec = (price_now / cost - 1.0) if cost else 0.0
            held_days_s = g.hold_days.get(code, 99)
            ref = _entry_breach_ref(code)
            if held_days_s < SECTOR_CLEAR_MIN_HOLD:
                log.info("[风控] {} 板块{}退潮，但持仓仅{}日(<{}日) → 不在此强平".format(
                    code, sec, held_days_s, SECTOR_CLEAR_MIN_HOLD))
            elif pr_sec > 0:
                log.info("[风控] {} 板块{}退潮但盈利{:.1%}，不在此强平（交止盈处理）".format(
                    code, sec, pr_sec))
            elif ref and price_now > ref:
                log.info("[风控] {} 板块{}退潮且浮亏{:.1%}，但未跌破破位线 {:.2f} → 暂不强平".format(
                    code, sec, pr_sec, ref))
            else:
                sell, reason = amount, "板块联动清仓:{}退潮+破位(亏{:.1%})".format(sec, pr_sec)
        # ② ★V4.5★ B-8 分批止盈：浮盈达 PARTIAL_TAKE_PCT 先把 PARTIAL_TAKE_RATIO 减掉锁利，
        #    剩余仓位继续跟移动止盈跑趋势（解决"6 笔盈利单被过早终止"的唯一正 alpha 来源）。
        #    ★V4.7★ P1-1 修复★ 原判据 `0 < half < amount` 使"仅剩 1 手"时永不成立：
        #      _round_lot(100×0.5, 100) = 100 == amount → 分批止盈形同虚设（5/20 连刷 10 次
        #      "可卖100股/需100股"，浮盈 12%+ 的单子始终没减仓）。改为"减仓后至少保留 1 手"。
        if sell is None and cost and PARTIAL_TAKE_PCT > 0 and code not in g.partial_done:
            pr_p = price_now / cost - 1
            if pr_p >= PARTIAL_TAKE_PCT:
                lot_min = 200 if code.startswith("688") else 100
                tr_half = _tradeable_amount(px)
                half = min(_round_lot(amount * PARTIAL_TAKE_RATIO, amount), amount - lot_min)
                if half < lot_min:
                    # 仓位不足 2 手 → 结构上无法分批；永久标记完成交移动止盈，杜绝刷屏
                    g.partial_done.add(code)
                    if _noise_once(code, "partial_small"):
                        log.info("[风控] {} 浮盈{:.1%}≥{:.0%} 但仓位仅 {} 股（可卖{}），"
                                 "不足 2 手无法分批 → 交移动止盈处理".format(
                                     code, pr_p, PARTIAL_TAKE_PCT, amount, tr_half))
                elif tr_half < half:
                    # T+1 尚未解禁（当日买入）→ 本日不减，留待下次；不标记，避免永久放弃
                    if _noise_once(code, "partial_unsellable"):
                        log.info("[风控] {} 浮盈{:.1%}≥{:.0%} 但可卖量不足（{}股/需{}股），"
                                 "本次不减仓，留待下次".format(
                                     code, pr_p, PARTIAL_TAKE_PCT, tr_half, half))
                else:
                    _do_sell(code, half, "分批止盈:浮盈{:.1%}减{}成".format(
                        pr_p, int(PARTIAL_TAKE_RATIO * 10)), price_now)
                    g.partial_done.add(code)
                    log.info("[风控] {} 浮盈{:.1%}≥{:.0%} → 减仓 {} 股（余 {} 股跟移动止盈）".format(
                        code, pr_p, PARTIAL_TAKE_PCT, half, amount - half))
                    continue
        # ③ 纯移动止盈（★V4.4★ 去掉 +10%/+15% 硬顶，全程只跟持仓最高价回撤 TRAIL_PCT 清仓）
        #    武装阈值 TRAIL_ARM_PCT：浮盈≥5% 后才挂上移动止盈（★V4.5★ 由 3% 上调），避免微利即砍；
        #    赢仓可一路多跑，直到自最高点回撤 10% 才离场（★V4.5★ 由 8% 放宽）。
        if sell is None and cost:
            pr = price_now / cost - 1
            peak = g.peak.get(code, 0.0)
            # ★V4.9★ P0-3 赢家宽管：已在跑的持仓容忍更大的自然回撤（0.15×1.6 = 24%）
            _trail = TRAIL_PCT * WINNER_TRAIL_MULT if is_winner else TRAIL_PCT
            if peak > 0 and pr >= TRAIL_ARM_PCT and price_now <= peak * (1 - _trail):
                sell, reason = amount, "移动止盈:自高点{:.1f}回撤{:.1%}{}".format(
                    peak, _trail, "(赢家宽管)" if is_winner else "")
        # ④ 止损（移动止盈未触发时）
        #    ★V4.7★ P0-3 硬止损是风险底线，**不受最短持有期约束**
        #      （V4.6 只在注释里声称"ATR 止损永不受其约束"，代码并未落地：仍是 held_days 门槛）
        #    ★V4.7★ P0-1 但设 09:45 保护线：09:30-09:45 为集合竞价后的噪声区，不在其中执行
        #    ★V4.8★ P0-1 两段式：首次触发只减半，次日仍未收窄才清剩余。
        #      V4.7 实测 16 笔 ATR 止损全部一次清仓、均值 −5.57%，且阈值被 MAX 截断成固定 5%
        #      —— 等于"任何 −5% 的插针都被全额砍掉"。两段式用半仓换取"插针不被全砍"，
        #      并用 STOP_STAGE1_HARD_MULT 兜住"同日继续深跌"的尾部风险。
        if sell is None and cost:
            pr = price_now / cost - 1
            stop_pct = 0.0
            if STOP_MODE == "fixed":
                stop_pct = STOP_LOSS_PCT
            elif rows:
                a = _atr(rows)
                if a and cost:
                    stop_pct = a * ATR_STOP_MULT / cost
                    stop_pct = max(ATR_STOP_MIN_PCT, min(ATR_STOP_MAX_PCT, stop_pct))
            if stop_pct:
                st1_day = g.stop_stage1.get(code)
                # ★V4.8★ 撤销机制：浮亏收窄到 阈值×STOP_RECOVER_RATIO 以内 → 重新武装
                if st1_day and pr > -stop_pct * STOP_RECOVER_RATIO:
                    g.stop_stage1.pop(code, None)
                    st1_day = None
                    log.info("[风控] {} 浮亏已收窄至 {:.1%}（>-{:.1%}）→ 撤销两段式第一阶段标记，重新武装".format(
                        code, pr, stop_pct * STOP_RECOVER_RATIO))
                if pr <= -stop_pct:
                    if now and now < STOP_TIME_FLOOR:
                        if _noise_once(code, "stop_floor"):
                            log.info("[风控] {} 触发硬止损(浮亏{:.1%})，但 {} 处在开盘噪声区"
                                     "（<{}）→ 顺延执行".format(code, pr, now, STOP_TIME_FLOOR))
                    elif st1_day and st1_day == g.today and pr > -stop_pct * STOP_STAGE1_HARD_MULT:
                        # 本日已减半且未深跌 → 等次日确认（不重复动作、不刷屏）
                        if _noise_once(code, "stop_wait_next"):
                            log.info("[风控] {} 本日已触发止损并减半，当前浮亏{:.1%}，"
                                     "等次日确认（未跌破 -{:.1%}）".format(
                                         code, pr, stop_pct * STOP_STAGE1_HARD_MULT))
                    else:
                        lot_min = 200 if code.startswith("688") else 100
                        tr_now = _tradeable_amount(px)
                        staged_half = False
                        if (STOP_STAGED and not st1_day
                                and amount >= lot_min * STOP_STAGE1_MIN_LOT):
                            half = min(_round_lot(amount * STOP_STAGE1_RATIO, amount),
                                       amount - lot_min)
                            if half >= lot_min and tr_now >= half:
                                _do_sell(code, half, "止损两段-减半:浮亏{:.1%}(阈值{:.1%})".format(
                                    pr, stop_pct), price_now)
                                g.stop_stage1[code] = g.today
                                staged_half = True
                                log.info("[风控] {} 首次触发止损（浮亏{:.1%} ≤ -{:.1%}）→ 两段式："
                                         "先减半 {} 股，余 {} 股留观"
                                         "（收窄至 -{:.1%} 以内自动撤销；同日跌破 -{:.1%} 或次日仍触发则清仓）".format(
                                             code, pr, stop_pct, half, amount - half,
                                             stop_pct * STOP_RECOVER_RATIO,
                                             stop_pct * STOP_STAGE1_HARD_MULT))
                        if not staged_half:
                            sell, reason = amount, "止损:浮亏{:.1%} (模式{}, 阈值{:.1%}{})".format(
                                pr, STOP_MODE, stop_pct,
                                "，两段式第二阶段" if st1_day else "")
        # ⑤ 破均值线清仓（短持仓不触发，避免噪声止损 —— ★V4.3 修复★；
        #    ★V4.5★ 均线由 5 日改 10 日，热点票 5 日线噪声过大）
        #    ★V4.7★ P0-1 核心修复★ 该分支改为**尾盘确认**：只在 EXIT_BREAK_TIME 之后判定。
        #      V4.5 中它接管了 60% 的出场（21/35 笔，其中 11 笔成交于 09:35 前）——
        #      等于用隔夜均线在开盘第一分钟砍仓，出场价落在当日最差的时间窗。
        # ★V4.9★ P0-3 赢家宽管：强势票沿 MA10 上行时经常被"贴着均线被震出"，改用更长的均线
        _ma_n = (WINNER_RETREAT_MA if (is_winner and WINNER_RETREAT_MA > 0) else RETREAT_MA)
        if sell is None and now >= EXIT_BREAK_TIME and len(closes) >= _ma_n:
            ma = _ma(closes, _ma_n)
            if ma and price_now < ma:
                held_days_break = g.hold_days.get(code, 99)
                if held_days_break >= MIN_HOLD_FOR_TIGHT_STOP:
                    sell, reason = amount, "破{}日线清仓(尾盘确认){}".format(
                        _ma_n, "，赢家宽管" if _ma_n != RETREAT_MA else "")
                elif _noise_once(code, "break_short_hold"):
                    log.info("[风控] {} 破{}日线但持仓仅{}日(<{}日)，暂不噪声止损".format(
                        code, _ma_n, held_days_break, MIN_HOLD_FOR_TIGHT_STOP))
        if sell and sell > 0:
            if reason.startswith(("止损", "破")):
                g.cool_down[code] = COOL_DOWN_DAYS
            tr = _tradeable_amount(px)
            if tr <= 0:
                g.stop_queue.append((code, amount, reason))
                log.info("[卖出排队] {} 可卖量0，次日首时段补卖: {}".format(code, reason))
                continue
            _do_sell(code, min(sell, tr), reason, price_now)


# ============================================================
# 十三、交易日守卫与日初处理
# ============================================================
def _is_trading_day_guard(context):
    """极简交易日/时段守卫：无法取到时间或落在非交易时段则跳过。"""
    now = _now_str(context)
    if not now:
        _degrade("guard", "无法获取当前时间，跳过本轮")
        return False
    return True


def before_trading_start(context, data):
    """日初：冷静期衰减、持仓天数+1、持仓日K缓存、★V4 盘前选股★。"""
    _HEALTH["degraded"] = []
    g.today = _today_str(context)
    g.now_str = _now_str(context) or ""
    # 冷静期衰减
    for c in list(g.cool_down.keys()):
        g.cool_down[c] = g.cool_down[c] - 1
        if g.cool_down[c] <= 0:
            del g.cool_down[c]
    # 持仓天数
    for c in list(g.hold_days.keys()):
        g.hold_days[c] = g.hold_days.get(c, 0) + 1
    # 清理已清仓标的的状态
    pm = positions_map()
    for c in list(g.hold_days.keys()):
        if c not in pm:
            g.hold_days.pop(c, None)
            g.peak.pop(c, None)
            g.code_sector.pop(c, None)
    # ★V4.5★ 同步清掉已清仓标的的出场辅助状态（防策略重启/记录残留导致误判）
    for c in list(g.entry_ref.keys()):
        if c not in pm:
            g.entry_ref.pop(c, None)
            g.entry_low.pop(c, None)
            g.partial_done.discard(c)
            g.stop_stage1.pop(c, None)      # ★V4.8★ P0-1 两段式标记同步清理
    for c in list(g.stop_stage1.keys()):
        if c not in pm:
            g.stop_stage1.pop(c, None)
    g.buy_today = set()
    g.intraday_px = {}                  # ★V4.5★ 当日日内价缓存每日重置
    g.noise_slot = {}                   # ★V4.7★ P2-1 噪声日志去重表每日重置
    g.risk_off = False                  # ★V4.8★ P1-3 避险档状态每日重置（由 buy_job 重新判定）
    # 持仓日K缓存（供盘中零取数风控）
    if pm:
        g.pos_hist = fetch(list(pm.keys()), POS_BARS)
        if not g.pos_hist:
            _degrade("poshist", "持仓日K缓存为空，ATR/均线风控将降级")
        # ★V4.5★ 用真实入场日最低价更新"破位线"（入场日 bar 在 T+1 盘前才可取到）
        for c in list(pm.keys()):
            hd = int(g.hold_days.get(c, 0))
            rows_p = g.pos_hist.get(c) or []
            if hd <= 0 or len(rows_p) < hd:
                continue
            lows = [r[3] for r in rows_p[-hd:] if r[3]]
            if not lows:
                continue
            low = min(lows)
            prev = g.entry_low.get(c)
            if prev is None or low < prev:
                g.entry_low[c] = low
    log.info("[日初] 持仓 {} 只 冷静期 {} 只 上一轮候选 {} 只".format(
        len(pm), len(g.cool_down), len(g.pending_buy)))
    # ★V4：盘前选股（用 T-1 完整收盘数据；此时当日 bar 尚未生成）★
    if SIGNAL_AT_PREMARKET:
        try:
            _run_signal_layer(context)
        except Exception as e:
            _degrade("signal", "盘前信号层异常: {}".format(repr(e)))
    _dump_health("[盘前]")


def _register_universe(cands, pm):
    """★V4.8★ P0-3 把"待买候选 + 当前持仓"注册进 universe。

    PTrade 回测里 handle_data(context, data) 的 data **只覆盖 universe**（set_universe
    设定的标的池），而建仓层要用的当日日内价只能来自 data → g.intraday_px。
    V4.5 引入该通道后实测仍是 42/42 笔退化为 assumed(+1.0%)，根因不是字段名对不上，
    而是**候选票根本不在 data 里**：本函数把它们注册进去，护栏才有机会真正生效。
    失败不影响主流程（退化为 assumed 路径，并计入降级表）。
    """
    try:
        codes = []
        seen = set()
        for x in list(cands or []):
            c = x.get("code") if isinstance(x, dict) else x
            if c and c not in seen:
                seen.add(c)
                codes.append(_suffix(c))
        for c in list(pm or {}):
            if c and c not in seen:
                seen.add(c)
                codes.append(_suffix(c))
        if not codes:
            return False
        for arg in (codes, list(codes), tuple(codes)):
            try:
                set_universe(arg)
                log.info("[口径-U] set_universe 注册 {} 只（候选 {} + 持仓 {}）"
                         "→ handle_data 的 data 将覆盖它们".format(
                             len(codes), len(cands or []), len(pm or {})))
                return True
            except Exception:
                continue
    except Exception as e:
        _degrade("universe", "set_universe 失败: {}".format(repr(e)))
    return False


def _capture_intraday(data):
    """★V4.5★ B-6 配套 + ★V4.8★ P0-3 修复：从 handle_data 的 data 参数捕获当日进行中价，
    供建仓层护栏使用（回测里 get_current_data 常不可用，data 是最后的日内价来源）。

    ★V4.8★ P0-3 两处修：
      ① 盘前 `_register_universe(候选+持仓)` —— 让 data 覆盖候选票（V4.7 42/42 走
         assumed 的真因：票不在 universe 里，本函数无从取值）；
      ② 本函数扩为多字段（close / price / last_price / now）× 多键探测，
         并在首日打印 [口径-探测]（data 键样本 + 命中数），供下一轮回测定位。

    只抓"待买候选"（≤MAX_CANDIDATES 只），不遍历全池 → 每分钟开销可忽略。
    """
    if data is None:
        return
    pb = getattr(g, "pending_buy", None)
    today = getattr(g, "today", None)
    if getattr(g, "probe_logged", None) != today:
        g.probe_logged = today
        try:
            ks = list(data.keys())[:8] if hasattr(data, "keys") else []
            nk = len(data) if hasattr(data, "__len__") else -1
            log.info("[口径-探测] data 键样本 {}（共 {} 个）| 待买候选 {} 只 | 已捕获日内价 {} 只".format(
                ks, nk, len(pb or []), len(g.intraday_px or {})))
        except Exception:
            pass
    if not pb:
        return
    try:
        if not hasattr(data, "get"):
            return
    except Exception:
        return
    hit = 0
    for f in pb:
        try:
            c = f["code"] if isinstance(f, dict) else str(f)
        except Exception:
            continue
        if g.intraday_px.get(c):
            continue
        for key in (c, _suffix(c), _canon(c)):
            try:
                obj = data.get(key)
            except Exception:
                obj = None
            if obj is None:
                continue
            px = 0.0
            for fld in ("close", "price", "last_price", "now"):
                try:
                    v = obj.get(fld) if isinstance(obj, dict) else getattr(obj, fld, None)
                except Exception:
                    v = None
                try:
                    px = float(v or 0)
                except Exception:
                    px = 0.0
                if px > 0:
                    break
            if px > 0:
                g.intraday_px[c] = px
                hit += 1
                break
    if hit and getattr(g, "probe_hit_logged", None) != today:
        g.probe_hit_logged = today
        log.info("[口径-探测] 本日首次捕获日内价 {} 只（示例 {}）".format(
            hit, sorted(g.intraday_px.items())[:3]))


def handle_data(context, data):
    """盘中主循环：捕获日内价 + 风控（建仓/早盘准备由 run_daily 负责；不可用时按窗口兜底）。

    ★V4.5★ 板块级清仓仅在 now >= RISK_FALLBACK_TIME（14:48）时开启，
    这样即使 run_daily 不可用，14:48 之后的第一次 handle_data 也会完成板块级清仓。
    """
    g.now_str = _now_str(context)
    now = g.now_str
    if not now:
        _degrade("clock", "无法获取当前时间，handle_data 空转")
        _dump_health("[时钟]")
        return
    # ★V4.5★ 日内价捕获（必须在建仓窗口判定之前）
    try:
        _capture_intraday(data)
    except Exception:
        pass
    if not getattr(g, "sched_ok", False):
        if _in_window(now, EARLY_TIME) and g.early_slot != _today_str(context):
            g.early_slot = _today_str(context)
            try:
                early_job(context)
            except Exception as e:
                _degrade("early", "早盘处理异常: {}".format(repr(e)))
            return
        if _in_window(now, BUY_TIME) and g.buy_slot != _today_str(context):
            g.buy_slot = _today_str(context)
            try:
                buy_job(context)
            except Exception as e:
                _degrade("buy", "建仓处理异常: {}".format(repr(e)))
            return
    if "09:30" <= now <= "15:00":
        try:
            monitor_risk(context, sector_clear=(now >= RISK_FALLBACK_TIME))
        except Exception as e:
            _degrade("risk", "风控异常: {}".format(repr(e)))


def _log_equity(context):
    """★V4.7★ P2-2 日终净值打印：供回测直接读净值，不必再从"目标金额 ÷ 仓位比例"反推。

    V4.5 复盘时因日志无净值，只能用 `目标金额 ÷ 阶段仓位比例` 反推 → 系统性低估约 2pp、
    无法与面板对账。此日志落盘后，区间收益 / 最大回撤 可直接从日志逐日算出。
    """
    total = _total_asset(context)
    if not total or total <= 0:
        return
    pm = positions_map()
    log.info("[净值] {} 总资产={:.0f} 持仓={} 只".format(
        _today_str(context), total, len(pm)))


def risk_fallback_job(context):
    g.now_str = _now_str(context) or RISK_FALLBACK_TIME
    try:
        # ★V4.5★ 板块级清仓的唯一正式时点（当日只判定一次，见 monitor_risk）
        monitor_risk(context, sector_clear=True)
    except Exception as e:
        _degrade("risk", "兜底风控异常: {}".format(repr(e)))
    # ★V4.7★ P2-2 日终净值打印
    try:
        _log_equity(context)
    except Exception as e:
        _degrade("equity", "净值打印失败: {}".format(repr(e)))
    _dump_health("[兜底风控]")


def on_order(context, orders):
    """订单回执（下单失败必须可知，不能静默）。字段名按本券商核对。"""
    try:
        for o in (orders or []):
            code = _pos_f(o, "security")
            st = _pos_f(o, "status")
            amt = _pos_f(o, "amount")
            filled = _pos_f(o, "filled") or _pos_f(o, "business_amount")
            log.info("[回报] {} 状态={} 委托={} 成交={}".format(code, st, amt, filled))
            err = _pos_f(o, "error_info") or _pos_f(o, "message")
            if err:
                _degrade("order", "{} 委托异常: {}".format(code, err))
            try:
                if amt and filled is not None and abs(float(filled)) < abs(float(amt)) * 0.5:
                    _degrade("order", "{} 成交 {} < 委托 {} 的一半（疑似缩量/部成）".format(
                        code, filled, amt))
            except Exception:
                pass
    except Exception as e:
        _degrade("order", "on_order 解析失败: {}".format(repr(e)))


# ============================================================
# 十四、PTrade 入口
# ============================================================
def initialize(context):
    # ---- 状态容器（全部入 g，避免模块级变量跨日/重启丢失）----
    g.hist = {}
    g.pos_hist = {}
    g.feat = {}
    g.sector_map = None
    g.sector_codes = {}
    g.code_sectors = {}
    g.sector_state = []
    g.prev_signal = {}
    g.pending_buy = []
    g.cool_down = {}
    g.hold_days = {}
    g.peak = {}
    g.buy_today = set()
    g.stop_queue = []
    g.trades = []
    g.code_sector = {}
    g.index_rows = []
    # ★V4.5★ 新增状态
    g.prev_rate = {}            # 板块封板率历史（_sector_killed 主判据）
    g.prev_sig_day = {}         # 每个板块最近一次 append 的日期（用于剔除"今日"值）
    g.entry_ref = {}            # 建仓时记录的静态破位线 = T-1 收盘 ×(1-SECTOR_CLEAR_DROP)
    g.entry_low = {}            # 入场日最低价（T+1 盘前用真实日K更新，取更小值）
    g.partial_done = set()      # 已完成分批止盈的标的（每标的一次）
    # ★V4.9★ P1-1 策略自有成本：出场判据一律用它；平台 cost_price 只用于对账。
    #   分批减仓后**不更新** —— 剩余仓位的成本基准不应被减仓行为改写（平台正是做错了这点）。
    g.entry_px = {}             # code -> 建仓时采用的入场价
    # ★V4.9★ P0-2 主线建仓流水 [(日期, 主线名)]：支撑滚动窗口内的主线次数约束
    g.mainline_entries = []
    g.intraday_px = {}          # handle_data 捕获的当日进行中价（供建仓护栏）
    g.noise_slot = {}           # ★V4.7★ P2-1 噪声日志去重（code -> {kind: 日期}）
    g.sector_clear_slot = None  # 板块级清仓"当日已判定"标记
    # ★V4.8★ 新增状态
    g.stop_stage1 = {}          # P0-1 两段式止损第一阶段标记（code -> 触发日期）
    g.risk_off = False          # P1-3 市场级避险档当日状态
    g.probe_logged = None       # P0-3 [口径-探测] 去重（已打印日期）
    g.probe_hit_logged = None   # P0-3 [口径-探测] 捕获成功去重（已打印日期）
    g.risk_slot = None
    g.hist_mode = None
    g.fq_ok = None
    g.fq_fail = 0
    g.st_name = {}
    g.unit_logged = False
    g.sched_ok = False
    g.early_slot = None
    g.buy_slot = None
    g.now_str = ""
    g.today = ""

    try:
        set_benchmark(INDEX_FOR_REGIME)
    except Exception:
        try:
            set_benchmark("000300")
        except Exception as e:
            _degrade("benchmark", "set_benchmark fail: {}".format(repr(e)))
    # 佣金 + 印花税
    for kw in (
        dict(commission_ratio=0.0003, min_commission=5.0, type="STOCK", tax=0.0005),
        dict(commission_ratio=0.0003, min_commission=5.0, type="STOCK"),
        dict(PerTrade=0.0003, Min=5),
    ):
        try:
            set_commission(**kw)
            break
        except Exception:
            continue
    try:
        set_slippage(slippage=0.002)
    except Exception:
        try:
            set_slippage(0.002)
        except Exception as e:
            _degrade("slippage", "滑点未设置: {}".format(repr(e)))
    # 调度：run_daily 优先，失败则 handle_data 容错窗口兜底
    try:
        run_daily(context, early_job, time=EARLY_TIME)
        run_daily(context, buy_job, time=BUY_TIME)
        run_daily(context, risk_fallback_job, time=RISK_FALLBACK_TIME)
        g.sched_ok = True
    except Exception as e:
        g.sched_ok = False
        _degrade("schedule", "run_daily 不可用，改用 handle_data 容错窗口: {}".format(repr(e)))
    log.info("[初始化] V4.9 启动 TRADE_ENABLED={} 调度={} 板块池={}".format(
        TRADE_ENABLED, "run_daily" if g.sched_ok else "handle_data兜底", SECTOR_MAP_FILE))
    # ★V4.9★ 参数指纹：上传平台后核对第一屏日志，一眼确认跑的是哪一版（防"传错文件白跑一轮"）
    log.info("[指纹] ★V4.9★ 止损={} clamp[{:.0%},{:.0%}] 闸门:{}~尾盘{} | 止盈:分批{:.0%} 移动武装{:.0%}/回撤{:.0%}"
             " | 仓位:板块{}只 总{}只 启动{:.0%}/扩散{:.0%} 日新{}笔 | 换手:{}日≤{}次"
             " | 簇:Jaccard{} 同簇≤{:.0%} | 赢家:浮盈≥{:.0%} 回撤×{:.1f} MA{} 最长{}日"
             " | 主线:≤{}笔/{}日".format(
                 STOP_MODE, ATR_STOP_MIN_PCT, ATR_STOP_MAX_PCT, STOP_TIME_FLOOR, EXIT_BREAK_TIME,
                 PARTIAL_TAKE_PCT, TRAIL_ARM_PCT, TRAIL_PCT,
                 MAX_PER_SECTOR, MAX_POSITIONS, POSITION_RATIO, DIFFUSE_POSITION_RATIO,
                 MAX_NEW_POSITIONS_PER_DAY, TURNOVER_WINDOW_DAYS, MAX_ANNUAL_TURNS,
                 CLUSTER_JACCARD, CLUSTER_MAX_WEIGHT,
                 WINNER_EXEMPT_PCT, WINNER_TRAIL_MULT, WINNER_RETREAT_MA, WINNER_MAX_HOLD,
                 MAINLINE_MAX_ENTRIES, MAINLINE_WINDOW_DAYS))
    log.info("[初始化] 口径: 选股=盘前(T-1完整收盘) | 建仓={} 快照限价 | 护栏基准=T-1收盘".format(
        BUY_TIME))
    log.info("[初始化] 每板块限 {} 只 | 总仓上限 {} 只 | 单票启动{:.0%}/扩散{:.0%} | 每日新建≤{} 笔 | 护栏 [T-1收盘×{:.1%}, ×{:.1%}]".format(
        MAX_PER_SECTOR, MAX_POSITIONS, POSITION_RATIO, DIFFUSE_POSITION_RATIO,
        MAX_NEW_POSITIONS_PER_DAY, 1 - BUY_FLOOR_PCT, 1 + BUY_PREMIUM_PCT))
    log.info("[初始化] 止损模式={} | 移动止盈 武装{:.0%}/回撤{:.0%} | 破{}日线 | 紧止损最短持有{}日".format(
        STOP_MODE, TRAIL_ARM_PCT, TRAIL_PCT, RETREAT_MA, MIN_HOLD_FOR_TIGHT_STOP))
    log.info("[初始化] 板块级清仓: 时点{} 最短持有{}日 破位线=T-1收盘-{:.0%} | 衰退判据=前5日均值×{:.0%}且连续2日".format(
        RISK_FALLBACK_TIME, SECTOR_CLEAR_MIN_HOLD, SECTOR_CLEAR_DROP, SECTOR_FADE_RATIO))
    log.info("[初始化] ★V4.7 统一出场时间闸门★ 破{}日线仅在 {} 后尾盘确认 | 硬止损最早 {} 执行"
             "（硬止损豁免最短持有期，仅受时间闸门约束）".format(
                 RETREAT_MA, EXIT_BREAK_TIME, STOP_TIME_FLOOR))
    # ★V4.9★ 止损形态（本版删除 V4.8 两段式，回归单段清仓）
    log.info("[初始化] ★V4.9 止损形态★ 模式={} | ATR 止损带 clamp(1.8×ATR/成本, {:.0%}, {:.0%}) | {}".format(
        "STAGED(两段式)" if STOP_STAGED else "ONE-SHOT(一次清仓)",
        ATR_STOP_MIN_PCT, ATR_STOP_MAX_PCT,
        "首次触发减半、收窄撤销、再跌破清仓" if STOP_STAGED else
        "触发即一次清仓 —— V4.8 两段式已验证无效（3/3 全废，两段间隔仅 1 分钟，实为平台 cost_price 摊薄假象）"))
    if ATR_STOP_MAX_PCT <= 0.05:
        log.info("!! [参数自检] ATR_STOP_MAX_PCT={:.1%} 过紧：热点票 ATR/价格常态 3~5%%，"
                 "1.8×ATR≈6.3%% 会被上限截断成'固定 {:.1%} 一刀切'（V4.7 的教训）".format(
                     ATR_STOP_MAX_PCT, ATR_STOP_MAX_PCT))
    log.info("[初始化] ★V4.8 市场避险档★ 指数<MA20（或 MA{}<MA20 且收盘<快线）→ 单票仓位×{:.2f}、"
             "每日新建上限 {} 笔（半仓减速，非全停）".format(
                 REGIME_RISK_OFF_MA_FAST, REGIME_RISK_OFF_SCALE, REGIME_RISK_OFF_MAX_NEW))
    log.info("[初始化] 换手预算: 近{}交易日 ≤{} 次双边 | 每月建仓≤{} 笔 | 产业链簇 Jaccard>{} 同簇≤{:.0%}".format(
        TURNOVER_WINDOW_DAYS, MAX_ANNUAL_TURNS, MAX_BUYS_PER_MONTH,
        CLUSTER_JACCARD, CLUSTER_MAX_WEIGHT))
    log.info("[初始化] 入场硬条件: 信号日涨幅∈[{:.0f}%, {:.0f}%] 量比≥{} 收在振幅上半≥{:.0%}".format(
        HOT_GAIN_MIN, SIGNAL_DAY_GAIN_MAX, SIGNAL_DAY_VR_MIN, SIGNAL_DAY_POS_MIN))
    # ★V4.5★ 自检：信号日涨幅带宽过窄时提示（窄带会把候选数打掉 60%+，属正常现象而非 bug）
    if HOT_GAIN_MIN >= SIGNAL_DAY_GAIN_MAX - 1.0:
        log.info("!! [参数自检] 信号日涨幅带宽 [{:.0f}%, {:.0f}%] 过窄（仅 {:.1f} 个百分点）"
                 "→ 候选数将大幅减少；若回测出现长时间空仓，先把 SIGNAL_DAY_GAIN_MAX 放宽到 6~8".format(
                     HOT_GAIN_MIN, SIGNAL_DAY_GAIN_MAX, SIGNAL_DAY_GAIN_MAX - HOT_GAIN_MIN))
    _dump_health("[初始化]")