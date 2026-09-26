# PTrade 热点追踪策略 · 验证与加固

体检报告：`D:\投研工作台\06-投资策略分析\PTrade热点追踪策略_体检报告_20260912.html`

## 目录

| 文件 | 说明 |
|---|---|
| `strategy_original.py` | 待检策略 v2.0 原文，未做任何修改 |
| `../策略回测/hotspot_trader_v3_hardened.py` | **加固版 v3.0**（体检修复落地，可直接替换；已移至「策略回测」目录） |
| `harness.py` | Mock PTrade API，验证 v2.0 的缺陷（跑 6 个场景） |
| `harness_v3.py` | Mock PTrade API，验证 v3.0 的修复（跑 8 个场景） |
| `cost_model.py` | 交易成本 / 保本胜率敏感度测算 |

## 快速验证

```bash
python harness.py        # v2.0 原版：复现 4 个 P0 缺陷
python harness_v3.py     # v3.0 加固版：验证修复是否生效
python cost_model.py     # 成本测算（结果写 cost_out.txt）
```

无第三方依赖，Python 3.5+ 可跑（内置极简 DataFrame 替身，不需要 pandas）。

## v3.0 相对 v2.0 的修复对照

| 编号 | v2.0 缺陷 | v3.0 修复 | 验证 |
|---|---|---|---|
| P0-1 | current_dt≠14:45 时全策略静默 | run_daily 定时 + 时间自检，无 run_daily 时按 `>=信号时间` 执行并幂等 | V-S4 ✓ |
| P0-2 | 接口不兼容静默降级、谎报信号模式 | 多签名容错 + 启动自检 + 候选为 0 打 ERROR | V-S2 ✓ |
| P0-3 | 成交额单位「手」全市场误杀 | 启动用蓝筹自动校准成交量单位，自动 x100 | V-S3 ✓ |
| P0-4 | T+1 卖出用错数量必废单 | 只用 enable_amount，优先 order_target(code,0) | V-S5/5b ✓ |
| P1-1 | 追涨停买不进（逆向选择） | 可买性硬约束：不追涨停/一字板，涨幅按本股涨停幅度比例封顶 | V-S1 ✓ |
| P1-2 | 回测口径不一致/偷价 | 启动检测是否含当日 bar，明确告警 | V-S8 ✓ |
| P1-3 | 100% 仓位不校验资金 | 按可用现金建仓 + 10% 现金缓冲 + 整百股 | V-S1 ✓ |
| P1-4 | 固定步长抽样永久漏票 | 默认全市场批量粗筛；抽样模式按日期轮换 | — |
| P1-5 | 逐票取数性能差 | 批量取数，调用量从数千次降到 5~14 次 | V-S1 ✓ |

## 上实盘前仍需在真实 PTrade 上确认的 4 项

1. `get_history` 是否包含当日 bar（决定 pct 口径，v3 启动自检会自动提示）
2. `volume` 字段单位是「股」还是「手」（v3 启动自检会自动校准并提示）
3. `get_stock_name` 是否存在（决定 ST/退市过滤是否生效）
4. `context.blotter.current_dt` / `run_daily` 是否可用（决定定时是否稳定）

这四项 v3 在启动日志里都有自检输出，跑一遍信号模式即可全部核对。

## 真实环境实测修复（2026-09-12 山西证券 PTrade 回测日志）

把 v3 贴进真实 PTrade 回测后，日志暴露了三个平台差异，已全部修复并回归验证：

| 真实环境现象 | 根因 | 修复 |
|---|---|---|
| 粗筛 16 个批次全部 `invalid field 'amount'`，候选恒 0 | 该平台成交额字段叫 `money`，不是 `amount` | 字段改 `money`，close/volume 与 money 分离取数，money 取不到自动回退 volume×close |
| `不支持在[程序初始化]阶段运行get_history` | PTrade 禁止在 initialize 里取数 | 成交量/口径自检延迟到首个交易日执行 |
| `run_daily() missing 'func'`，注册后 09:31 报 `'str' object is not callable` | 该平台 run_daily 参数顺序颠倒，位置参数把 `"14:45"` 字符串注册成了 func | **彻底弃用 run_daily**，统一 handle_data 触发（已实测稳定） |

修复后真实环境的关键点：用 `money` 直接取成交额，**绕开了 volume 单位问题**（成交额不受「手/股」干扰，P0-3 的自动校准只作为无 money 时的兜底）。

## 持仓读取兼容（「只有买入没有卖出」问题）

若回测出现「只买不卖、明明有仓位却显示无持仓」，根因是 `get_positions()` 返回的持仓对象字段名与代码假设不一致，导致持仓永远解析为空。

- `positions_map()` 已兼容多套字段名（含驼峰）：代码字段 `security/code/stock_code/symbol/instrument/...`，数量 `current_amount/total_amount/...`，可卖 `enable_amount/available_amount/...`，成本 `cost_price/cost_basis/avg_cost/...`。
- 多路兜底读取持仓：`get_positions()` → `context.portfolio.positions` / `long_positions` → `get_position()`。
- 加了诊断日志：① `get_positions()` 返回数据但解析不出代码 → 打印 `样本结构: ...`；② 完全读不到 → 打印 `context.portfolio 可用属性: [...]`。**把这两行任一行发来即可精确定位。**

## 股票名 dict 问题

部分平台 `get_stock_name()` 返回 `{'300542.SZ': '新晨科技'}` 这种 dict 而非字符串。已兼容：返回 dict 时自动取 value 作为名称，热点榜不再显示成 `{'300542.SZ': '新晨科技'}`。

## 当日涨幅口径 + 板块分档（选股 + 买入都在 14:45 尾盘）

回测里日线 `get_history('1d')` 不含当日未走完的 bar，原先只能用「昨日涨幅」。现已改为**当日涨幅**，并**按板块分档**：

- 选股与买入都在 **14:45** 由 `handle_data` 触发（`>= 14:45` + 日期幂等，每天只跑一次，尾盘买入）。
- 当日涨幅 = **当日 14:45 实时价（data 参数）/ 昨收（日线最后一根）− 1**。
- 当日价优先取 **handle_data 的 `data` 参数**（当前 bar），次选 `price` 字段，再次分钟线，都取不到回退「昨日涨幅」并告警。
- **已实测确认**：该平台 `data` 对象类型为 `BarDict`，`data[代码]` 能取到当日实时价（`get_history('1d'/'1m')` 和 `price` 字段在回测里都只返回昨收，不可用）。

## 持仓读取（已确认结构）

该平台持仓在 `context.portfolio.base_portfolio` 下的子账户里（`stock_account.positions`），`get_positions()` 与 `context.portfolio.positions` 在回测里为空。已按多路兜底覆盖：
`get_positions()` → `portfolio.positions/long_positions` → `base_portfolio.positions` → `base_portfolio.stock_account.positions` → `get_position()`。

⚠️ **信号模式（TRADE_ENABLED=False）不真正下单**，持仓为空属正常，不会触发止损止盈。要看到完整「买入→持仓→止损止盈」链路，需把 `TRADE_ENABLED` 设为 `True` 回测。
- 涨幅区间（`GAIN_RANGE` 可改）：主板 3%~8%；科创板 688 8%~14%；创业板 300/301 8%~14%（与科创板同属 20cm）；北交所默认排除（`ALLOW_BOARDS` 不含 `"BJ"` 且 `_gain_range` 对北交所返回 `None`）。
- 细评的涨停判定、MA20 站上判断都用当日价与昨收基准，均线序列已拼接当日价。
- 兜底：若平台取不到分钟线，自动回退「昨日涨幅」并 ERROR 告警（自检日志会明确提示 `当日涨幅口径已生效` 或 `回退昨日涨幅`）。

## 分批止盈（彬哥哥定制出场）

出场从「单一止盈」改为**分批止盈**，让利润奔跑、回撤有底线：

| 优先级 | 触发条件 | 动作 |
|---|---|---|
| 1 | 跌破 **5 日线**（TP_MA） | **清仓**（趋势破位先走） |
| 2 | 跌破 20 日线（RETREAT_MA） | **清仓**（更保守兜底，与 5 日线并存） |
| 3 | **已减半票**回落 ≤ **保本价**（BREAKEVEN_STOP，成本价×(1−BREAKEVEN_BUF)） | **清仓**（保本止损，锁定已落袋利润） |
| 4 | 浮亏 ≤ **−5%**（STOP_LOSS_PCT） | **清仓**（止损） |
| 5 | **买入次日（持有≥1天）仍在亏损**（T1_LOSS_EXIT，rt<0） | **清仓**（T+1 亏损清仓，当天买、次日亏就走） |
| 6 | **时间止损**：盈利票持有 ≥ **10** 天（MAX_HOLD_PROFIT_DAYS）/ 亏损票持有 ≥ **5** 天（MAX_HOLD_DAYS） | **清仓** |
| 7 | 浮盈 ≥ **+15%**（TP_FULL_PCT） | **清仓**（止盈兑现） |
| 8 | 浮盈 ≥ **+10%**（TP_HALF_PCT）且未减半过 | **减半仓**（卖可卖量的一半，仅一次） |

- **T+1 亏损清仓（新增）**：某票买入次日（持有 ≥1 天）若仍为负收益即清仓，避免扛住反转票；与固定 −5% 止损不冲突——−5% 以上小亏的次日亏损票由本条清掉，−5% 及以下由止损线清掉。
- **盈利票持仓上限（新增）**：时间止损改为「盈利 / 亏损」双档——盈利票最多持 `MAX_HOLD_PROFIT_DAYS=10` 天，亏损票最多持 `MAX_HOLD_DAYS=5` 天（让利润多跑、亏得快砍）。同日买入（持有 0 天）不触发任何时间类退出，避免刚买就卖。
- 减半用 `context.halved` 做幂等标记：同一票 +10% 只减半一次，之后要么等 +15% 清仓，要么等破 5 日线清仓，**不会每天重复卖一半**。
- **保本止损（新增）**：某票 `+10% 减半` 时，记录保本价 = 成本价 ×(1−BREAKEVEN_BUF)（默认 BREAKEVEN_BUF=0，即严格等于成本价）存入 `context.breakeven[code]`。此后该票若回落到保本价以下，立即清掉剩余半仓——整体锁定在「不亏」状态（已落袋的一半利润已安全）。未减半的票不触发保本止损，继续走固定 −5% 止损。
- 减半与清仓都只用**可卖量（enable_amount）**，规避 T+1 未交收废单（与 P0-4 同源约束）。
- 当日价优先用 `handle_data` 的 `data` 实时价，回退昨收；均线与当日价同源比较，破位判定在盘中即可生效。
- 重新建仓（execute_buy）会自动清除该票的 `halved` / `breakeven` 标记，分批止盈与保本基准重新计数。
- 参数全在文件顶部「仓位与风控」区，按需微调：`TP_HALF_PCT / TP_FULL_PCT / TP_MA / RETREAT_MA / STOP_LOSS_PCT / MAX_HOLD_DAYS / MAX_HOLD_PROFIT_DAYS / T1_LOSS_EXIT / BREAKEVEN_STOP / BREAKEVEN_BUF`。

> 创业板默认归入科创板档（8%~14%），如需单独设档或排除，改 `GAIN_RANGE` 里的 `cyb` 即可。

## 收益优化（提升收益的两道开关，均默认可关）

### 1) 仓位随热点强度分档（`STRENGTH_WEIGHT`）
- 开启后单票金额 `∝ 强度分^STRENGTH_EXP`，强信号给更高权重、集中度可控；单票上限 `MAX_SINGLE_RATIO`（默认 30% 总资产）。
- 迭代再分配：触顶（达上限）的票移出，剩余预算继续按权重分给未触顶的票，**尽量用满预算**（不浪费仓位）。
- 关闭（`STRENGTH_WEIGHT=False`）则回到等权，与原逻辑一致。
- 调参：`STRENGTH_EXP`（越大越集中于最强票，默认 1.6）、`MAX_SINGLE_RATIO`。

### 2) 14:45 分时回踩过滤（`BUY_PULLBACK_FILTER`）
- 只做「**回踩不破开盘价**」：14:45 价仍 `>= 当日开盘价` 才买，说明日内动量未转弱；跌破开盘价则过滤（动量转弱，不接飞刀）。
- 当日开盘价用**聚合当日分钟线**（`get_history('1m')` 多根聚合）取，可靠；取不到开盘价时退化为「不过滤」，保证不静默丢信号。
- 已**弃用**「买在日内绝对高点」判定：单根 1m bar 的 `high` 是最后一分钟最高价而非当日最高，会系统性误杀候选（实测曾把全部候选拒掉）。
- 开关：`BUY_PULLBACK_FILTER`、`PULLBACK_OPEN_BREAK`（默认均开）。

> 回归：V-S17 锁定强度分档分配（强票最多/弱票最少、单票不超 30%、预算用满、关闭后等权）与分时回踩过滤（破开盘价过滤、无价/无开盘价不退化为过滤）。

