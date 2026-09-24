# hotspot_trader_v1 部署清单与调参说明

> 配套 `hotspot_trader_v1_ptrade.py`（自选股 · 热点短线突破策略骨架 v1.4）
> 本清单是**上线前必须逐项核对**的硬要求，不是建议。

## 一、平台口径核对（不同券商白标接口细节会变，先问平台/看文档）
- [ ] `get_history` 签名 `(count, frequency, field, security_list, fq, include, fill, is_dict)`；`is_dict=True` 返回 `OrderedDict({代码: 2D数组[(日期,开,高,低,收,量,额,最新价),...]})`，列序=所请字段(可能前置日期列)——策略 `_hist` 已转成 {字段:array}
- [ ] 盘前取数 `include=False`，末根=昨收（选股锚基于此，正确）；`volume` 单位=股
- [ ] `preclose` 不再依赖 get_history 字段（改为前一根收盘推算）；单股传字符串/多股传列表返回结构不同，已统一 is_dict
- [ ] 持仓 `get_positions()` 返回 `dict[str:Position]`，已做形态兼容
- [ ] 当日价：`handle_data` 用 `data[code].price`；**`run_daily` 回调只收 `context`(无 data)**，现价改由 `get_snapshot(交易,last_px)` / `get_history(include=True,回测)` 兜底（已写，实测可取）
- [ ] 账户读 `context.portfolio`，无 `get_account`（已写）
- [ ] `get_snapshot` 仅交易模块可用，**回测不可用**；其 `circulation_amount`=流通股本(股)、`turnover_ratio`=换手率(ratio,*100=%)、字段名以券商实盘为准
- [ ] `set_commission` 只在回测可用，交易接口勿调
- [ ] 国金 vs 山西：移植只改封装、业务逻辑零改动；移植后重跑成交模式验证持仓链路

## 二、必填数据（v1.1 硬性过滤的必需输入）
- [ ] `WATCHLIST`：你的真实自选股（6位纯数字）—— **策略只在此池内选股**，自动剔除 ST/次新
- [ ] `HOT_SECTORS`：热点板块追踪技能的输出（行业名须与 `INDUSTRY_MAP` 一致）
      → 若留空且 `MOMENTUM_FALLBACK=True`，自动用自选股内动量前 N 名当伪热点
- [ ] `INDUSTRY_MAP`：**同板块集中度上限的必需输入**，格式 `{ '600519':'白酒','300750':'电池' }`；不填则集中度检查失效（仅告警）
- [ ] `FLOAT_SHARES`：**换手率<20% 过滤的静态兜底**，格式 `{ '600519': 流通股本(股) }`（不填也可，运行时走 get_fundamentals）
      → 运行时（回测可用）`get_fundamentals([code], 'valuation', fields=[候选])` 多候选字段探测流通股本(股)：`a_floats/float_a_shares/circulation_amount/float_shares/...`
      → 换手率主用 `volume(股)/流通股本(股)*100`（单位自校），备用 `valuation` 直读（turnover 多为 ratio，自动×100）
      → **`a_floats`/`turnover_rate` 是 JOINQUANT 命名，PTrade 未必一致**；启动探针会打印 `valuation` 实际返回列名，以此为准核对
      → 启动自测 `_probe_float_source` 打印 `[probe]`：可取则换手率过滤生效；取不到=全部候选被保守剔除(零成交)

## 三、参数调参表（先用回测标定，别拍脑袋）
| 参数 | 默认 | 含义 | 建议区间 |
|---|---|---|---|
| STOP_LOSS_PCT | 0.05 | 初始硬止损 | 0.04~0.07 |
| TRAIL_K | 2.5 | ATR 移动止盈倍数 | 2.0~3.0 |
| TRAIL_MIN_PCT | 0.06 | ATR缺失时回撤兜底 | 0.05~0.08 |
| BE_TRIGGER_PCT | 0.05 | 上移保本的盈利阈值 | 0.04~0.06 |
| TP1_PCT / TP2_PCT | 0.08/0.15 | 两批减仓阈值 | 按个股波动定 |
| MAX_HOLD_DAYS | 8 | 时间止损天数 | 5~10 |
| RISK_PER_TRADE | 0.02 | 单票风险预算(占本金) | 0.01~0.02 |
| MAX_POSITION_PCT | 0.30 | 单票仓位上限 | 0.20~0.35 |
| VOL_UP_RATIO / VOL_MA5_RATIO | 1.2/1.3 | 量能放大倍数 | 1.1~1.5 |
| EXCLUDE_ST / EXCLUDE_NEW_STOCK | True/True | 剔除ST / 次新股 | 关闭改 False |
| NEW_STOCK_DAYS | 250 | 次新判定(上市不足N交易日) | 200~365 |
| TURNOVER_CAP | 20 | 换手率上限(百分比单位,防庄股) | 15~25 |
| SECTOR_CAP | 0.40 | 同板块集中度上限(占净值) | 0.30~0.50 |

## 四、回测要求（缺这项=没验证）
- [ ] 样本 ≥ 1~2 年，必须覆盖牛/熊/震荡三种市况
- [ ] 含费用：印花税单边千一(卖出) + 双边佣金 + 滑点(约0.1%)
- [ ] 看四指标：胜率、盈亏比、最大回撤、夏普；并留最近3个月做样本外
- [ ] 日线回测对"盘中触发止盈"存在低估（见技能 §四十九），关键出场用分钟级或成交模式复核

## 五、上线流程（纪律）
1. `TRADE_ENABLED = False` 先跑信号模式 3~5 日，核对 `[hist]/[acct]/[pos]` 告警应为 0
2. 模拟盘 1~2 周
3. 小资金实盘，确认成交/风控识别到真实持仓后，再放量与调参
4. 启动日志首屏认 `★HOTSPOT-V1★` 指纹，确认跑的是这个版本

## 六、已知局限（骨架待补强）
- **ST / 次新 / 换手率 的取数依赖 `get_security_info` 与 `get_fundamentals('valuation')`**：流通股本经 `valuation` 多候选字段探测(股)、换手率主用 `volume/流通股本`(单位自校)；`a_floats`/`turnover_rate` 为 JOINQUANT 命名，PTrade 字段名以探针打印的 `valuation` 实际列名为准；取不到时按"保守剔除"(ST/换手率)或"按非次新"降级并告警（R4），不会静默放行
- 热点板块为"动量兜底"或"手工填 HOT_SECTORS"，未自动调用热点追踪技能（托管机无外网，需盘前把技能输出写入 `HOT_SECTORS`）
- 换手率过滤对"当日放量"敏感：若某日非正常巨量（如大宗过户），可能误剔；如误剔频繁可放宽 `TURNOVER_CAP`
- 板块集中度按 `INDUSTRY_MAP` 的板块名聚合；若一只票跨多板块，本策略只取单一映射，可能低估真实关联风险
- **离线验证器** `hotspot_trader_v1_离线验证器.py`：用 mock 平台 API + 人造 K 线跑通选股/剔除/出场逻辑，无需券商即可自检（含涨停/换手率/ST/次新/均线五项剔除断言 + 启动探针 + 信号模式买盘）；上线前可常跑，已验证 ALL PASS

## 七、v1.2 回测实测修复记录（2026-09-23）
- **before_trading_start 签名**：PTrade 以 `(context, data)` 两参调用；原 `def before_trading_start(context):` 会 `TypeError` 直接崩回测。已改为 `(context, data=None)`（`_buy`/`_risk_control` 同步）。
- **get_fundamentals 口径**：原错误写成 `get_fundamentals([code], 'circulating_cap')`（字段当表名）且字段名不对；山西/PTrade 正确签名为 `get_fundamentals(security, table, fields=...)`，流通股本/换手率走 `table='valuation'`（`a_floats` 万股 / `turnover_rate` 带%字符串）。已修正。
- **换手率单位 bug（致命）**：`_turnover_rate` 返回百分比值（如 5.0=5%），原 `TURNOVER_CAP=0.20` 为分数 → `5.0 >= 0.20` 恒成立，会把**所有有换手率的票误剔**（实际零成交）。已将 `TURNOVER_CAP` 改为 20（百分比单位），与 `_turnover_rate` 一致。
- 离线验证器已同步：mock `get_fundamentals` 返回 `valuation` 形态 DataFrame；`before_trading_start` 以两参调用；实测 ALL PASS。
- 仍待实盘/回测首跑核对：① 山西证券 `get_fundamentals('valuation')` 在回测中是否如期返回对应字段（看 `[probe]` 日志打印的 `valuation 实际列`）；② `valuation` 直读换手率若为回测当日收盘后数据，存在轻微未来函数，正式交易前建议传 `date=上一交易日` 修正。

## 八、v1.3 山西证券官方API文档核对修复（2026-09-23）
> 依据彬哥哥提供的《山西证券的API文档.docx》逐条核对，修掉 3 个此前离线验证器未暴露、真实平台必崩/必失效的隐患：
- **BUG-1（必崩）`get_history(is_dict=True)` 返回结构**：原 `_hist` 把返回值当 `df['close']` 字典用，但官方口径是 `OrderedDict({代码: 2D数组[(日期,开,高,低,收,量,额,最新价),...]})`——真实平台直接 `TypeError`。已重写 `_hist` 把 2D 数组按字段顺序转成 `{字段:array}`，下游访问不变。
- **BUG-2（回测静默失效）`run_daily` 回调只收 `context`**：官方明确 `func` 须 `Callable[[Context], None]`（不传 `data`）。原 `_buy`/`_risk_control` 依赖 `data[code].price` 取现价 → `data=None` → 回测 `get_snapshot` 不可用 → 返回 0 → 风控全部 `continue`（止损止盈在回测形同虚设）。已改 `_cur_price`：handle_data 用 `data` → 交易用 `get_snapshot.last_px` → 回测用 `get_history(include=True)`，实测兜底取到价。
- **BUG-3（字段名/单位未证实）换手率过滤零成交**：`a_floats`/`turnover_rate` 是 JOINQUANT 命名，本文档未确认 PTrade `valuation` 表字段名；且快照 `circulation_amount`=股、`turnover_ratio`=ratio(0.0042=0.42%)，与原假设(万股/%字符串)不符。已改为：流通股本多候选字段探测(股,不乘1e4) + 换手率主用 `volume/流通股本`(单位自校) + 直读自动×100；启动探针**打印 `valuation` 实际列名**便于核对。
- 离线验证器已同步：mock 严格还原 is_dict 2D 数组 / `get_snapshot.last_px` / `valuation` 多列 DataFrame；实测 ALL PASS（含 run_daily 无 data 兜底取价）。
- 仍待你确认（唯一开放项）：回测首跑看 `[probe]` 日志的 `valuation 实际列`，把 PTrade 真实字段名告诉我；若与候选不符，我再据实钉死 `FLOAT_CANDIDATES` 顺序。


## 九、v1.4 回测致命崩溃修复（2026-09-23）
> 彬哥哥首跑回测在 09:31 报 `TypeError: 'str' object is not callable`，并伴随 `valuation 列探测失败` / `流通股本/换手率均取不到` 告警。逐条定位后修复三处真实平台问题：

- **致命崩溃根因：`run_daily` 注册签名写反**（本次崩溃的直接原因）
  - 官方签名：`run_daily(context, func, time='9:31')`（文档 line 916）。`context` 必须是第一参。
  - 原代码 `run_daily(_buy, '09:31')`（func-first）让平台把 `context=_buy`、`func='09:31'`(字符串)，到点调用 `'09:31'(context)` → TypeError。
  - 已改为 `run_daily(context, _buy, '09:31')` 等三处（before_trading_start / _buy / _risk_control）。
  - 注意：这与 v1.3「BUG-2 回调只收 context(无 data)」是两回事——前者是**注册参数顺序**（不修直接崩），后者是回调形参/取价兜底；两者均已处理。

- **`log` 不格式化，掩盖了真实异常**
  - 平台 `log` 只接受预格式化字符串、不执行 % 格式化；原 `log.info('...%s...', a, b)` 留下裸 `%s`，使真实异常被淹没。
  - 已新增 `_Log` 兼容层：先 `msg % args` 预格式化再转发真实 `log`；离线验证器同构。效果：`valuation 列探测失败` 的真实异常现在能正常打印，便于核对。

- **`valuation` 表字段名不确定（自动适配）**
  - `a_floats`/`turnover_rate` 系 JOINQUANT 命名，本文档未列 PTrade `valuation` 字段。
  - 已重写 `_probe_float_source`：用 `get_trading_day(-1)` 取上一交易日，调 `get_fundamentals([code], 'valuation', date=prev)` 拉**全部列名**；拉不到再逐候选字段探测；把真机可用列缓存到 `_DISC_FLOAT_COL` / `_DISC_TURN_COL`，`_float_shares` / `_turnover_rate` 优先消费。现已自动适配券商真实字段，**无需再手改 `FLOAT_CANDIDATES`**。

- 离线验证器升 v1.4：mock 严格还原 context-first `run_daily` / `log` 不格式化 / `get_trading_day` / `valuation` 全列返回；实测 **ALL PASS**。
  - 探针日志示例（mock）：`valuation 实际列=[a_floats, float_a_shares, circulation_amount, float_shares, circulating_shares, free_shares, free_float_shares, turnover_rate, turnover_ratio, turnover]`，`选用 流通列=a_floats 换手列=turnover_rate`，`换手率可取(≈5.00%) <20% 过滤生效`。

- **唯一开放项（已自解，无需您再反馈字段名）**：回测首跑看 `[probe]` 日志的 `valuation 实际列` 与 `选用 流通列/换手列`，确认不再报 `str' object is not callable`、探针能取到流通股本/换手率即可。若真实列名与候选不符，`_DISC_*` 自动适配，不再需要手改。

- **v1.4 补丁（平台禁用 `sys`）**：重跑回测报错误码3「sys被禁止使用」——v1.4 为让 `_Log` 在无 log 环境落盘加了 `import sys` + `sys.stdout.write`，托管机（Python 3.5 受限环境）禁止 `import sys`，初始化即失败。已移除 `import sys`、兜底改静默 `pass`、`getattr(rl, meth)` 加 `try/except` 防日志异常拖垮策略；`py_compile` OK、离线验证器续 ALL PASS。现已可正常初始化并跑回测。


## 十、真机字段实测结论（2026-09-23 盘前探针，20列全探明）
- 山西证券 `valuation` 真实列：`trading_day, total_value, float_value, naps, pcf, ps, ps_ttm, pe_ttm, a_shares, a_floats, pe_dynamic, pe_static, b_floats, b_shares, h_shares, total_shares, turnover_rate, dividend_ratio, pb, roe`
- **`turnover_rate` 已是百分比**（002747 原始值 4.2310 = 4.23%）；旧规则「≤5 当 ratio×100」会误读成 423%。已改直读不×100，>100 ÷100、<0.05 ×100 自愈。
- **`float_value` 是流通市值，不是流通股本**——当股本用会把换手率算到≈0（过滤形同虚设）。探针选列已跳过含 `value`/`cap` 的市值类列，现选 `a_floats`（流通A股股本）。
- 探针已从 initialize 迁至 `before_trading_start` 首跑（**初始化阶段禁 `get_fundamentals`**，实测 RuntimeError）。
- 次新判定在上市日期缺失时用日线根数兜底（`_bars_count`，<250根≈次新；长期停牌股可能误判，可接受）。
- 回测三跑已完整跑通：探针自动选列成功、信号模式正常产出买入信号；修完单位坑后换手率过滤才真正有效。

## 十一、v1.6 修复记录（2026-09-23 深夜，开真实交易后的首轮成交复盘）

首轮真实成交回测（22:25）暴露三处出场逻辑问题，一次修完：

1. **底仓永不清仓（最影响统计指标）**：分批减仓走完 stage2 后无最终离场，剩余底仓挂到回测结束
   -> 平台只统计完整平仓交易，胜率显示 0%（实际 301150 +35.5%、301536 浮盈 +36.6% 未落袋）。
   修复：时间止损扩展为「亏损仓到限即砍；止盈仓 stage>=2 到 MAX_HOLD_DAYS 也清仓（底仓闭环）」，
   移动止盈仍对底仓全程生效。
2. **零股 bug**：减仓卖 amount/3 经 round 到整手，剩 100 股时 100/3≈33 股不足一手，
   `_do_sell` 算出 0 股静默返回但 stage 照样推进（日志打了"减半2"却无订单）。
   修复：剩余 <=300 股（3 手）时跳过分批、直接一次性清仓（止盈清仓-余量小全清）。
3. **回测 get_snapshot 告警刷屏**：_cur_price 原顺序 snapshot 优先，回测每次 14:50 每持仓打
   「回测不支持get_snapshot函数」。修复：取价顺序改为 data -> get_history(include=True)（回测/实盘通用）
   -> get_snapshot（仅实盘兜底），回测不再触碰 snapshot。

同轮回测其他观察（非 bug）：
- 000060 止损设定 -5% 实收 -7%：14:50 检查频率 + 跳空所致。
  **v1.6b 已修（彬哥哥拍板）**：①当日低点提前判定——get_history(1,'1d','low',include=True) 取当日盘中低点，
  低点触及止损价即触发离场（不等尾盘现价，收盘前回收的也按纪律走）；②按止损价限价挂单——
  _do_sell 增加 limit_price 参数，限价=min(现价,止损价)（现价已在止损下方按现价走，触及后回收则按止损价挂，
  成交价不会差于止损价）；股票限价 2 位小数（官方 order 接口 limit_price 要求）。离场日志新增「限价/当日低」两列，
  下轮回测可直接核对滑点收敛效果。
- Alpha 0.42 / Beta 0.24 / 夏普 2.57 / 最大回撤 4.02%，低贝塔高超额，框架方向正确；但 2 个月仅 3 笔样本，
  统计意义不足，建议下一步把回测区间拉长到 1 年再评指标。
