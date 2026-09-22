# 山西证券 PTrade 三层策略 —— 上线前核对清单

> 本策略文件：`山西PTrade_三层量化策略.py`
> 平台：山西证券 PTrade（恒生系白标）
> 默认 `TRADE_ENABLED = False`：先信号模式跑 3~5 个交易日核对日志，再模拟盘，最后小资金实盘。
> **本版来源**：由 `长线股三层量化策略_国金PTrade/国金PTrade_三层量化策略.py` 券商适配而来，交易逻辑一致。
>
> ✅ **API 口径已定稿（2026-09-21）**：已对照官方《山西证券的API文档.docx》（提取文本 `山西证券_API文档_提取.txt`，173,835 字符）逐条核对，**原 9 项待核 ☐ 全部闭环**。
> 核对过程中发现并修复 **1 处 P0 级静默缺陷**（`get_positions()` 返回形态误判 → 持仓读取全丢），并同步修复国金版。详见 §六。

---

## 〇、山西版 vs 国金版：差异一览

| 维度 | 国金版 | 山西版（本文件） |
|---|---|---|
| 文件 / 日志标识 | `国金PTrade_三层量化策略.py` | `山西PTrade_三层量化策略.py`，初始化日志加 `★山西PTrade V1.0★` 指纹（防"跑错版本"） |
| 交易逻辑 | 三层架构 + 风控闸门 + 参数 | **完全一致** |
| 接口口径 | 对照《国金PTrade的API文档》定稿 | **对照《山西证券的API文档》逐条核对，结论与国金一致** |
| `get_history` 含当日 bar | 国金文档未特别说明 | 山西文档 `include` 默认 `False`（不含当前周期）→ 盘前取数更无影响 |
| `handle_data` 的 `data` | 回测可取盘中 data | 山西文档明确 `data[security]` 返回 **BarData**，可取 `.price/.close` → L3 具备运行条件；实盘仍以 `[口径]` 日志确认 |

---

## 一、山西证券官方文档口径（逐条对照《山西证券的API文档.docx》）

| # | 项 | 文档原文口径（含行号） | 对本策略的影响 |
|---|---|---|---|
| 1 | `get_history` 签名 | `get_history(count, frequency='1d', field='close', security_list=None, fq=None, include=False, fill='nan', is_dict=False)`（文档 L1124） | **与国金完全一致**；`_hist_lists` / `_vwap` 无需改动 |
| 2 | `get_history` 返回形态 | 单只**字符串**入参 → `pandas.DataFrame`（行=datetime，列=字段名，L1162）；传 list 时 3.5 与 3.11 形态不同（L1170/L1188） | 本策略**一律传单只字符串** → 两版本下同为 DataFrame，跨版本行为一致 |
| 3 | `include` 参数 | 是否包含当前周期，**默认 `False`**（L1152） | 盘前取数末根=昨收，L1/L2 指标口径正确 |
| 4 | 分钟线频率 | 明确支持 `1m/5m/15m/30m/60m/120m/1d/1w/mo/1q/1y`（L1136） | L3 的 `_vwap` 可用；回测若不供 1m 则 VWAP=None、L3 自动关闭 |
| 5 | `get_snapshot(security)` | 参数可为单只 str 或 list；返回 **`dict[str:dict]`**（键=代码），`last_px`=最新成交价（L1676-1695） | `_cur_price` 用 `snap.get(code, snap)` 取值 → **已兼容**；仅**交易**模块可用 |
| 6 | `get_positions(security)` | 返回 **`dict[str:Position]`**（键=代码，值=Position 对象；L2404/L2419） | ⚠️ **本项即 P0 缺陷来源**，已修复（见 §六） |
| 7 | Position 对象字段 | `sid` / `enable_amount`(可用) / `amount`(总持仓) / `last_sale_price`(最新价) / `cost_basis`(成本)（L4909-4913） | `_pos_to_dict` 对象分支字段**完全匹配** |
| 8 | `get_all_positions()` | 返回 **`list[dict]`**：`stock_code`(6 位无后缀)/`current_amount`/`enable_amount`/`last_price`/`cost_price`（**仅交易**，L2429） | 本策略未使用；`_pos_to_dict` 的 dict 分支正为此保留 |
| 9 | `context.portfolio` | `cash` / `positions`(dict[str:Position]) / `portfolio_value` / `positions_value` / `capital_used`（L4875-4879） | `_account()` 读取的三个字段**均存在** |
| 10 | 时钟 | `context.blotter.current_dt`（L983/L1073 等多处） | `_dt_now` 主路径正确 |
| 11 | `data[code]` | 返回 **BarData** 对象，可取 `.price`(最新价)/`.close`/`.low`/`.high`/`.symbol`/`.datetime`（L4844-4846）；亦支持 `data[code]['close']`（L2834） | `_cur_price` 的 `data[code].price` 路径正确 |
| 12 | `order_target_value` | `order_target_value(security, value, limit_price=None)`；`value`=目标市值（L2838） | 两参调用合法（不传 limit_price 时以快照最新价报单，快照失败会记入日志） |
| 13 | Python 版本 | 文档明确「**python3.5、python3.11 版本均支持**」（L1161/L1170） | 策略为 3.5 兼容写法，两版本均可运行 |
| 14 | 复权 | `fq`：`pre`/`post`/`dypre`/`None`（默认 **None 不复权**，L1151） | 需按平台实际默认口径核对（见 §五） |
| 15 | 并发限制 | `get_history` / `get_price` **不支持多线程同时调用**，勿在 `run_daily`/`run_interval` 与 `handle_data` 同一时刻调用（L1133） | 本策略仅于 `before_trading_start` 与 `handle_data` 内调用，不并发 ✅ |
| 16 | `set_commission` | 仅**回测**可用（L231） | 策略未调用（正确） |

> 文档中**未出现 `get_account()`** —— 与国金一致，PTrade 无此接口，账户信息只在 `context.portfolio`。

---

## 二、接口口径核对表（山西文档已核，9 项全部闭环）

| # | 项 | 本策略写法 | 山西文档核对结果 |
|---|---|---|---|
| 1 | 股票代码后缀 | `.SS/.SZ/.BJ`（`_suffix` 自动补，指数原样） | 【已确认】文档示例 `'600570.SS'` / `'000001.SZ'` |
| 2 | 历史行情 `get_history` | `(count, frequency, field, security_list)`，无 `df` 参数，单只字符串返回 DataFrame | 【已确认】L1124 签名与返回形态一致，**无需改动** |
| 3 | 持仓 | `get_positions()` → **dict[str:Position]**，经 `_pos_to_dict` 统一映射 | 【已确认·已订正】原按 list[dict] 处理**有误**，已修复（§六） |
| 4 | 账户信息 | 无 `get_account()`；用 `context.portfolio.portfolio_value`/`cash`/`positions_value` | 【已确认】文档 Portfolio 对象列出同名字段 |
| 5 | 下单 | `order_target_value(code, value)`，value=目标市值 | 【已确认】L2838 签名兼容 |
| 6 | 盘中现价 | `data[code].price` → `obj['close']` → `get_snapshot(code)['last_px']` | 【已确认】BarData `.price` + 快照 `last_px` 均正确 |
| 7 | 分钟线 | `get_history(T_VWAP_WIN, '1m', ['close','volume'], code)`，同分钟缓存 | 【已确认】文档支持 1m 频率 |
| 8 | 回调名 / 时钟 | `initialize`/`before_trading_start`/`handle_data`/`after_trading_end`；`context.blotter.current_dt` | 【已确认】四回调与时钟属性均见文档 |
| 9 | 指数代码 | `000300.SS`（沪深300） | 【已确认】文档统一用 `.SS` 后缀，`get_history` 支持指数取数 |

> **最快的口径自检**：信号模式首跑后 grep 日志，`[hist]` / `[acct]` / `[pos]` 告警**应为 0 条**。
> 另：`set_commission` 只在**回测**可用，交易接口不存在，策略里未调用（正确）。

---

## 三、本策略已落实的硬规则

- [x] Python 3.5 / 3.11 双兼容：无 f-string、无类型注解、无 `os` 模块、无外网请求
- [x] `initialize` 内 `set_universe(STOCKS)`：注册标的后 `handle_data` 的 `data` 才带个股行情（缺则 L3 整段失效）
- [x] T+1：所有卖出走 `enable_amount`，`enable_amount == 0` 不回退到 `current_amount`（不发废单）
- [x] 涨跌停按板区分：30/68→20%、8/4→30%、ST→5%、其余 10%
- [x] 成本含印花税：卖出单边 0.05%（2023-08-28 起减半）；佣金双边 0.025%（万2.5）；滑点 0.05%（回测建模假设）
- [x] 回测当日价口径：L1/L2 信号在 `before_trading_start` 用**已完成数据**（末根=昨收）；L3 盘中价显式标注来源 `[口径]`
- [x] 盈亏比自洽：`L2_STOP_PCT(7%) <= L2_TAKE_PCT(14%) * 0.5` → 自检 PASS
- [x] 两段式止损已**弃用**：统一单段一次性清仓 + 策略自有成本价 `entry_px`（防平台摊薄口径改写）
- [x] 下单前先快照持仓（`poss = _get_positions()` 在前，`order_target_value` 在后），规避"下单后持仓被引擎清零"
- [x] 组合级风控：三级断路器（-8%/-12%/-18%）+ 沪深300 均线市场开关；断路器在 `_do_buy_value` 中**独立拦截所有方向性买入**（L1 季度再平衡补仓也受控；L3 日内T回补不走此函数）
- [x] 市场开关**双向可复位**：短均线(60)回归即恢复 L2；长均线(120)回归且连续 `MKT_RESET_CONFIRM_DAYS` 日（默认 1）后档位归零，再次跌破可再减仓；均线数据缺失时维持当前档位（`_index_below_ma` 三态返回）
- [x] 行业上限约束（`SECTOR_MAX=30%`）：`_do_buy_value` 下单前按 `SECTOR_OF` 聚合细分行业市值占比，超阈拒单/减额；L3 日内T 豁免；未配置行业标的一次告警
- [x] 单票上限（`SINGLE_MAX=10%`）+ L1 最短持有（`L1_MIN_HOLD_DAYS=5`）均已生效
- [x] 换手预算：`MAX_ANNUAL_TURNS` = 年度成本预算 ÷ 单回合成本（≈7.5 回合/年）；`TURNOVER_MIN_DAYS=20` 防早期外推；换手判定只在 L2/L3 入场处
- [x] **持仓读取口径（2026-09-21 新增）**：`_get_positions()` 按 `dict.items()` 取键值对（`get_positions()` 返回 `dict[str:Position]`）；`_pos_to_dict(p, code_hint)` 支持用字典键兜底代码；兼容 list 形态与 Position 对象
- [x] 任何接口降级都 `log.warning`，绝不静默换口径（`_hist_lists` / `_cur_price` / `_get_positions` / `_account` 全有告警）
- [x] L3 日内T 闭环：只卖可卖量、当日必回补（`14:50` 强制平），**不增隔夜仓、不碰 L1 核心**

---

## 四、上线前手动核对动作

1. **信号模式跑 3~5 日**：`TRADE_ENABLED=False`，看日志是否出现预期 `[signal-buy]`/`[信号-卖]`，以及 `[口径]`（若 L3 关说明无盘中价，正常）。
2. **口径自检**：grep 日志统计 `[hist]`/`[acct]`/`[pos]` 告警条数，**应全为 0**；若不为 0，说明某接口与文档口径有出入，需按告警定位。
3. **核对 T+1 拦截**：制造"当日买入"场景，确认打印 `可卖为0(T+1未交收)...顺延次日`，无废单。
4. **核对成本预算告警**：制造高频触发，确认 `[换手预算]` 告警并产生暂停。
5. **核对断路器**：模拟组合回撤 >8%/12%/18%，确认分级减仓日志与动作；确认断路器触发后 L1 季度再平衡不再补仓。
6. **L1 季度再平衡**只在第 60 个交易日触发一次，确认不会每天调仓。
7. **核对行业上限**：制造某细分行业（如"集成电路设计"=兆易+澜起）接近 30% 场景，确认 `[sector-cap]` 减额/拒单；L3 不受影响。
8. **核对 L1 最短持有**：对已持仓 <5 日的票制造"低配"场景，确认打印 `[L1] ... 持仓不足5日，跳过再平衡追买`。
9. **核对市场开关复位**：指数回到 120 日线上方连续 `MKT_RESET_CONFIRM_DAYS` 日后打印档位复位；此后**再次跌破**应能再砍两成。
10. **核对 L3 退化**：确认 `[口径] 盘中价来源=` 是 `data` 还是 `snapshot`；若 L3 被关闭，L1/L2 是否正常（应正常）。
11. **核对持仓读取（本次 P0 修复项，务必验）**：`TRADE_ENABLED=True` 后，确认 `_daily_risk_scan` / `_t_once` 能识别到真实持仓（日志出现持仓相关动作，而非恒空）；对照 `get_positions()` 原始返回，确认标的代码与数量一致。
12. **小资金实盘**：`TRADE_ENABLED=True`，单票极小仓，盯 1~2 周无异常再放大。

---

## 五、仍需平台侧 / 实盘确认（文档无法回答）

- **复权口径**：文档 `fq` 默认 `None`（不复权）。L2 阈值（MA20 下方 6%、量比 0.8、RSI 35–55）对复权方式敏感，需确认山西平台默认复权与选股时口径一致。
- **费率**：印花税 0.05% / 佣金 万2.5 / 滑点 0.05% 为现行估算，请按山西证券实际费率校正 `STAMP_TAX/COMM_RATE/SLIPPAGE`。
- **1m 数据可得性**：文档声明支持 1m，但回测档位是否实际提供需实跑验证；缺则 L3 自动关闭（已做降级）。
- **`handle_data` 的 `data` 实况**：文档声明提供 BarData，实盘以 `[口径] 盘中价来源=` 日志确认为准。
- **行业表可动态化**：文档提供 `get_industry_stocks`（研究/回测/交易）与 `get_Ashares`，可替换手工 `SECTOR_OF`；替换时需双写 key（纯数字 + 带后缀）。
- **持仓数据同步周期**：`Position` 对象在**交易**场景默认每 **6 秒**与柜台同步（`update_time` 记录），`order_target_value` 存在柜台时滞——策略已用 `buy_codes` 去重缓解，实盘需观察。

> ⚠️ 本报告基于量化 + 定性研究，**非买卖建议**。自动化策略仍需人工兜底开关：极端行情、停牌、平台故障、接口字段变更都需人工介入。

---

## 六、P0 缺陷修复记录（2026-09-21）

### 缺陷：`get_positions()` 返回形态误判 → 持仓读取全丢

**现象（静默、无报错）**：`_get_positions()` 原实现为：

```python
poss = get_positions()
if poss:
    for p in poss:          # ← 若 poss 是 dict，这里遍历到的是"字符串键"
        d = _pos_to_dict(p)
        ...
    return out
```

文档明确 `get_positions()` 返回 **`dict[str:Position]`**。对 dict 做 `for p in poss` 只会得到**代码字符串**（如 `'600570.SS'`）；`_pos_to_dict('600570.SS')` 走对象分支、`getattr(str, 'sid', '')` 取空 → `code=''` → `_canon('')` 为空 → `continue` → **out 恒为 `{}`**。
且因 `poss` 非空为真，`return out`（空字典）直接返回，**退化通道 `context.portfolio.positions` 永不可达**。

**连锁后果（全部静默，无一条告警）**：
- `_daily_risk_scan` 遍历空持仓 → 止盈 / 超买 / 移动止盈**永不触发**；
- `_intraday_hard_stop` 同上 → 日内硬止损**永不触发**；
- `_t_once` 找不到持仓 → **L3 日内T 全程空转**；
- `_apply_sector_cap` 聚合行业市值恒为 0 → **行业上限 30% 永不生效**；
- `_l1_rebalance` 见 `cur_val=0` → 季度再平衡重复按目标市值补仓，仓位与单票上限判断失真。

**为何此前未被发现**：国金首跑为**信号模式**（`TRADE_ENABLED=False`）零成交、无持仓，该缺陷被完全掩盖；`[pos]` 告警只在 `get_positions()` **抛异常**时打印，形态错误不抛异常。

**修复**（山西版与国金版同步）：
1. `_get_positions()` 改为 `isinstance(poss, dict) → list(poss.items())`，list 形态按下标取值；`out` 非空时才提前返回，否则保留 `context.portfolio.positions` 退化通道；
2. `_pos_to_dict(p, code_hint="")` 新增 `code_hint`，在 Position 内代码缺失时用字典键兜底（文档说明键可能是 `'600570.XSHG'`，`_canon` 已能处理四位后缀）。

**影响评估**：这是**双端（山西 + 国金）共同存在**的 P0 级缺陷——在实盘会**完全废掉风控与日内T**。修复后 `py_compile` 通过，两版均已落盘。

**残留验证动作**：见 §四 第 11 项（必须以 `TRADE_ENABLED=True` 的成交模式确认持仓可被读到）。

---

## 附：本版未包含的内容

- **回测日志与复盘**：国金目录下的 `2026-09-21 224654 ... 长线波段.txt` 与 `首跑回测复盘_20260921.md` 是**国金平台**的运行结果，未复制到本目录。山西版需在山西平台自行回测，并把日志规范命名归档（`回测_<预设>_<YYYYMMDD>.txt`，防被下次回测静默覆盖）。
- 首跑务必设 `TRADE_ENABLED = True`（否则零成交，收益与风控都验证不到——信号模式只能验接口与信号）。
