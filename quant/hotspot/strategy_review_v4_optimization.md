# 热点追踪量化策略 V4.5 → V4.8 优化复盘与改动文档

> 文件：`hotspot_trader_v4_ptrade.py`（山西证券 PTrade 托管版）
> 整理日期：2026-09-18
> 适用环境：PTrade 托管机（Python 3.5、无外网、无 os、无高级库）

---

## 0. 版本脉络一览

| 版本 | 主题 | 动机 | 是否改动主逻辑 |
|---|---|---|---|
| **V4.5** | 入口改造 + 内置盈亏台账 | 回测诊断：13 笔平仓仅 2 笔盈利，亏损首因=入场追滞后热点 | 改（收敛为"仅扩散可买"） |
| **V4.6** | 收益差情形 + 缺点专项优化 | 针对"收益差情形"与"策略缺点"逐条缓解 | 否（全增量开关） |
| **V4.7** | 混合架构 + 窗口化建仓 | "信号源前移"讨论落地：压滞后动量、破单点快照 | 否（全增量开关） |
| **V4.8** | 动态板块发现 | 补齐"静态板块池盲区"：捕捉新题材 | 否（注入 `_build_sector_index`） |

**设计铁律**：V4.6/V4.7/V4.8 全部以"新增开关 + 逻辑分支"方式挂载，**关闭对应开关即完整回到上一版行为**，可一键回退。

---

## 1. 策略定位（不变的部分）

- **哲学**：买已确认扩散、不追启动一日游；盘前定热点、早盘跟涨。
- **无未来函数**：全链路只用已收盘数据（`drop_today=True`），实时价仅用于 09:30 后建仓护栏。
- **信号层（盘前 `before_trading_start`）**：用 T-1 完整收盘数据批量取数，跑个股四道过滤 → 板块聚合 → 三阶段判定（启动/扩散/衰退）→ 候选生成。
- **个股四过滤**：上市≥60日、成交额≥3亿、封板判定自适应（主10%/双创20%/北交所30%±2%）、放量滞涨剔除、站上 MA20、剔 ST。
- **三阶段**：`classify_stage` 用历史 `zt_cnt` 平滑判：启动（z≥2 且前日<2）/ 扩散（持续≥2日）/ 衰退（今<峰值×0.5）。
- **仓位纪律**：每板块≤2 只（`MAX_PER_SECTOR`）、总仓≤5 只（`MAX_POSITIONS`）×单票 18%（`POSITION_RATIO`，留 10% 现金）、换手预算≈21 次/年（`MAX_ANNUAL_TURNS`）。

---

## 2. V4.5 基线改造（2026-09-17 回测诊断后）

**根因**：回测显示 13 笔平仓仅 2 笔盈利，亏损首因是"入场追滞后热点"——策略入场点天然落在题材已拉升之后。

**改动 ① 方向 A①（`REQUIRE_DIFFUSE_ENTRY=True`，L199）**
- 候选层 `_pick_candidates` 仅放行"扩散"阶段主线；「启动」一日游一律不买。
- 直接砍掉启动期的高风险接盘，把入场收敛到"已扩散、有梯队"的窗口。

**改动 ② 方向 A②（开盘追高放弃，`OPEN_CHASE_PCT=0.02`，L200）**
- T 日开盘价较 T-1 收盘高开 >2% → 放弃建仓，不接高开尖峰。

**改动 ③ 内置逐笔盈亏台账（V4.5 新增，L201 起、L1457 `_close_pnl`）**
- 解决 PTrade 回测日志无 P&L 汇总面板之痛；回测期末打印策略级盈亏台账（平仓笔数/胜率/未平仓浮亏/最大回撤）。

**基线护栏（沿用）**
- 双护栏：快照价 `< 昨收×(1-1.5%)`（走弱不接刀，`BUY_FLOOR_PCT`）或 `> 昨收×(1+3%)`（涨过头不追）均放弃。
- 市场开关：昨日池内涨停 ≥25 家（`MARKET_ZT_FLOOR`）才开新仓。

---

## 3. V4.6 增量优化（收益差情形 + 缺点）

> 配置区 L217–235，全部可一键回退。对应"收益差情形"与"策略缺点"逐条缓解。

### 3.1 针对"收益差情形"

**(1) 扩散期中后段上行空间有限 → 偏好早期、剔除末段**
- `PREFER_EARLY_DIFFUSE=True`（L226）：扩散≤3 日且涨停家数未拐头的板块标记为 `fresh`，排序优先。
- 新增 `_diffuse_profile(s)`（L1283）：用 `g.prev_signal`（截至昨日涨停家数序列）+ 今日 `zt_cnt` 算"连续扩散天数"与是否加速。
- `SKIP_LATE_DIFFUSE=True`（L227）+ `MAX_DIFFUSE_DAYS=5`（L228）：扩散持续 ≥5 日的**末段板块直接不买**。

**(2) 板块广度自然波动误杀 → 退潮需连续确认**
- `RETREAT_CONFIRM_DAYS=2`（L229）：板块真实塌陷由"单日 ≤1 家"改为"连续 2 日全部 ≤1 家 + 前 3 日峰值≥4 家"（`_sector_killed`，L2121）。
- 效果：2→1 的正常日间波动不再触发联动清仓，仅结构性退潮（如 4→1→1）才砍仓。

**(3) 震荡横盘被破线/ATR 磨成本 → 横盘时间止损 + 破线加缓冲**
- 风控新增 ⑤（L2205）：持仓 ≥ `STALE_EXIT_DAYS=8`（L231）且收益落在成本 ±`STALE_BAND_PCT=1.5%`（L232）窄带（不死不活）→ 主动退出释放资金。
- 破 5 日线清仓加 `MA5_BREAK_MARGIN=1.5%`（L233）缓冲：须低于 MA5×(1−1.5%) 才触发，防微破即砍（L2198）。

**(4) 小幅高开冲高回落买在局部高点 → 日内须仍走强**
- `BUY_ONLY_IF_ABOVE_OPEN=True`（L230）：10:00 快照价须 ≥ 开盘价（日内仍在上行）才建仓，与高开护栏形成双保险（L1825/L1985）。

### 3.2 针对"缺点"的结构缓解

- **滞后动量根因**：早期扩散偏好把"买在拉升之后"的痛苦后移，容错更高，但 T-1定热点/T日10:00买/T+1锁仓三重约束无法根除。
- **锁利增强**：`DYNAMIC_TRAIL=True`（L234）+ `DYNAMIC_TRAIL_MIN=0.04`（L235）：移动止盈回撤带宽随浮盈收窄（浮盈越大锁得越紧，下限 4%），赢仓保留更多利润（L2170）。

---

## 4. V4.7 混合架构 + 窗口化建仓

> 配置区 L238–271，函数层 L1887 起。落实"信号源前移"讨论结论：**不纯前移（换噪声），做混合（T-1 选板块 + 开盘确认择时）**。

### 4.1 混合信号 `OPEN_CONFIRM`（解决滞后动量根因之一）
- `OPEN_CONFIRM=True`（L267）+ `OPEN_SCAN_TIME="09:30"`（L268）：新增 `open_scan_job`，T 日 09:30 用实时快照确认盘前 T-1 选出的扩散主线"开盘是否真在动"。
- 确认口径：板块平均涨幅 ≥ `OPEN_CONFIRM_MIN_RISE=1.5%`（L269）**或**开盘涨停/逼近家数 ≥ `OPEN_CONFIRM_MIN_ZT=1`（L270）→ 判"确认"。
- `OPEN_CONFIRM_USE_CAND=True`（L271）：拿不到板块全成分实时价时，退而用候选股自身开盘动量确认。
- 未确认板块当日**不开仓**；`g.open_confirm` 缺失（实时数据不可用）时安全降级为"全部通过"，不阻塞建仓（回到 V4.6 行为）。
- 设计实质：**T-1 收盘定"板块"（慢变量、噪声最低），T 日开盘定"择时"（快变量、压滞后）**——专业热点策略标准打法。

### 4.2 窗口化建仓 `WINDOWED_BUY`（解决固定 10:00 单点）
- `WINDOWED_BUY=True`（L248）+ `BUY_WINDOW_START="09:35"`（L249）+ `BUY_WINDOW_END="10:00"`（L250）：取消固定 10:00 单点，改为 09:35–10:00 滚动扫描（每分钟去重一次）。
- 核心 `_try_buy_one`（L1962）：返回 `bought / drop / keep` 三态——**价格类护栏临时不达标者"保留候选"（keep）留待下次扫描（非破坏性）**，捕捉 9:35–10:00 的回踩买点；已买/板块满/流动性不符者剔除（drop）。
- `buy_window_scan`（L2028）：每窗重算快照，回踩到位即买，错过 9:30 尖峰、等来二次回踩。

### 4.3 调度与降级
- `run_daily` 新增 `open_scan_job@09:30`；建仓任务改为 `_buy_dispatcher@窗口起点`（L2475，关 `WINDOWED_BUY` 则回到 `BUY_TIME=10:00` 单点）。
- `handle_data` 在窗口内滚动扫描；`run_daily` 不可用的兜底模式下，开盘确认 + 窗口建仓均自动补触发（L2288 起）。

---

## 5. V4.8 动态板块发现

> 配置区 L253–265，注入点 `_build_sector_index()`（L607 起）+ `_discover_dynamic_sectors()`（L648 起）。补齐"静态板块池盲区"——突发政策/事件催化的新题材不在 `sector_map.json` 里 → 完全捕捉不到。

### 5.1 流程（四步，全程可降级）
1. **枚举**：用 `get_concepts()` / `get_concept_stocks()` 枚举全市场概念板（纯元数据，廉价）。
2. **强度门控**（L742）：一次批量取数，概念内 `涨停家数≥DYNAMIC_MIN_ZT_CNT=1`（L262）**或** `平均涨幅≥DYNAMIC_MIN_AVG_PCT=4.0%`（L263）才纳入——既把下游取数限制在少数真热概念、又压制新概念噪声。
3. **自然衔接**：新概念 day-1 普遍被 V4.5「仅扩散可买」判为「启动」挡在门外，**不追一日游**（无需额外代码）。
4. **降级**：任何环节（接口不可用/取数为空/超成员或概念上限）→ 退回纯静态池，行为等同 V4.7。

### 5.2 注入点选型（最内聚）
- 仅动 `_build_sector_index()`：把通过门控的新概念并入 `g.sector_codes`，下游信号层、`_pick_candidates`、`_sector_killed` 全部自动消费，无需逐个改。
- 信号层取数段（L1520）剔除已预取的动态成员，避免重复拉取。

### 5.3 防爆参数
- `DYNAMIC_MAX_MEMBERS=4000`（L264）：动态成员去重上限，超出则跳过动态发现。
- `DYNAMIC_MAX_CONCEPTS=400`（L265）：枚举概念数上限（A股约 380 个），超出截断。

---

## 6. 完整参数开关速查表

| 开关 | 默认值 | 版本 | 关闭后行为 |
|---|---|---|---|
| `REQUIRE_DIFFUSE_ENTRY` | True | V4.5 | 启动期也参与候选 |
| `OPEN_CHASE_PCT` | 0.02 | V4.5 | —（高开追高阈值） |
| `PREFER_EARLY_DIFFUSE` | True | V4.6 | 取消早期/末段排序偏好 |
| `SKIP_LATE_DIFFUSE` | True | V4.6 | 末段板块也可买 |
| `MAX_DIFFUSE_DAYS` | 5 | V4.6 | 扩散持续上限判定值 |
| `RETREAT_CONFIRM_DAYS` | 2 | V4.6 | =1 回到原单日退潮判定 |
| `BUY_ONLY_IF_ABOVE_OPEN` | True | V4.6 | 不再要求 ≥ 开盘价 |
| `STALE_EXIT_DAYS` | 8 | V4.6 | 横盘时间止损失效 |
| `STALE_BAND_PCT` | 0.015 | V4.6 | 横盘带宽判定 |
| `MA5_BREAK_MARGIN` | 0.015 | V4.6 | 破5日线无缓冲 |
| `DYNAMIC_TRAIL` | True | V4.6 | 移动止盈固定 TRAIL_PCT=8% |
| `DYNAMIC_TRAIL_MIN` | 0.04 | V4.6 | 动态带宽下限 |
| `WINDOWED_BUY` | True | V4.7 | 回到固定 10:00 单点建仓 |
| `BUY_WINDOW_START` / `BUY_WINDOW_END` | 09:35 / 10:00 | V4.7 | 滚动扫描窗口 |
| `OPEN_CONFIRM` | True | V4.7 | 关闭开盘确认（纯 T-1 信号） |
| `OPEN_SCAN_TIME` | 09:30 | V4.7 | 开盘确认扫描时刻 |
| `OPEN_CONFIRM_MIN_RISE` | 0.015 | V4.7 | 板块开盘确认涨幅阈值 |
| `OPEN_CONFIRM_MIN_ZT` | 1 | V4.7 | 板块开盘确认涨停家数阈值 |
| `OPEN_CONFIRM_USE_CAND` | True | V4.7 | 用候选股自身动量兜底确认 |
| `DYNAMIC_SECTOR_DISCOVERY` | True | V4.8 | 完全回到 V4.7 静态池 |
| `DYNAMIC_MIN_ZT_CNT` | 1 | V4.8 | 概念内涨停门槛 |
| `DYNAMIC_MIN_AVG_PCT` | 4.0 | V4.8 | 概念平均涨幅门槛(%) |
| `DYNAMIC_MAX_MEMBERS` | 4000 | V4.8 | 动态成员去重上限 |
| `DYNAMIC_MAX_CONCEPTS` | 400 | V4.8 | 枚举概念数上限 |

**基线常量（贯穿各版，供参考）**：`MAX_POSITIONS=5`、`MAX_PER_SECTOR=2`、`POSITION_RATIO=0.18`、`MIN_HIST_BARS=60`、`MIN_AMOUNT=3e8`、`MARKET_ZT_FLOOR=25`、`TRAIL_PCT=0.08`、`TRAIL_ARM_PCT=0.03`、`ATR_STOP_MULT=1.8`、`ATR_STOP_MIN_PCT=0.04`、`ATR_STOP_MAX_PCT=0.08`、`RETREAT_MA=5`、`MIN_HOLD_FOR_TIGHT_STOP=5`、`HOT_GAIN_MIN=4.0`、`BUY_FLOOR_PCT=0.015`、`MAX_ANNUAL_TURNS≈21`。

---

## 7. 信号 → 候选 → 买入 → 风控 数据流（标注各版改动点）

```
before_trading_start
  └─ _run_signal_layer（T-1 收盘，全量）
       ├─ _build_sector_index()          ★V4.8 并入动态发现板块
       ├─ _scan_universe() + fetch()     ★V4.8 剔除已预取动态成员
       ├─ 个股四过滤 (_stock_feat)
       ├─ 板块聚合 + 主线评选（广度优先 TOP3）
       ├─ classify_stage（启动/扩散/衰退）
       └─ _pick_candidates()             ★V4.5 仅扩散可买
                                          ★V4.6 偏好早期/剔除末段/标记 fresh
   ↓ g.candidates（盘前定型）

T 日 09:30  open_scan_job()              ★V4.7 开盘实时确认 → g.open_confirm
T 日 09:35–10:00 窗口
   └─ _buy_dispatcher → buy_window_scan  ★V4.7 滚动扫描
        └─ _try_buy_one()                ★V4.7 三态（bought/drop/keep）
             ├─ 开盘确认否决             ★V4.7 OPEN_CONFIRM
             ├─ 高开追高放弃             ★V4.5 OPEN_CHASE_PCT
             ├─ 须≥开盘价               ★V4.6 BUY_ONLY_IF_ABOVE_OPEN
             ├─ 双护栏（接刀/追高）      ★基线 BUY_FLOOR_PCT / +3%
             └─ 限价=min(快照×1.005, 护栏上限)
   ↓ 成交（order_value，T+1 锁定）

盘中每分钟 + 14:58 兜底  monitor_risk()
   ├─ ①板块联动清仓（衰退且亏损）
   ├─ ②纯移动止盈（回撤 TRAIL_PCT）    ★V4.6 DYNAMIC_TRAIL 动态带宽
   ├─ ③ATR 动态止损（成本-1.8×ATR）
   ├─ ④破5日线（加 MA5_BREAK_MARGIN 缓冲）★V4.6
   └─ ⑤横盘时间止损（STALE_EXIT_DAYS） ★V4.6
```

---

## 8. 验证建议（重要）

⚠️ **以上 V4.6/V4.7/V4.8 改动仅完成 `py_compile` 语法校验，未在 PTrade 托管环境实盘/回测验证。** 建议对照回测：

1. **V4.5 基线 → V4.6 全开**：重点看"亏损仓联动清仓"笔数是否下降、"横盘时间止损"是否减少被磨。若好票被 `STALE_EXIT_DAYS=8` / `MA5_BREAK_MARGIN` 误伤，优先调大这两个值。
2. **V4.6 → V4.7 全开**：看"10:00 涨过头被挡、9:50 回踩却买不进"的笔数是否下降（窗口化收益），"开盘即转弱板块"是否被 `OPEN_CONFIRM` 拦掉（混合信号收益）。`OPEN_CONFIRM_MIN_RISE=1.5%` 过严会误杀，可上提 2%~2.5%。
3. **V4.7 → V4.8 全开**：看新题材主线是否被捕获、候选数是否增多、且未被 V4.5 挡在门外导致 0 成交（强度门控阈值需调）。
4. **枚举成本观察**：V4.8 约 380 次概念取成员 API + 一次全量取数，均在盘前完成，需实盘观察是否超时/被限频；嫌慢可下调 `DYNAMIC_MAX_CONCEPTS` 或直接关总开关。

---

## 9. 仍未解决（需独立改造项）

| 约束 | 说明 | 本次是否触及 |
|---|---|---|
| **T+1 锁仓 + 定点** | 平台与既定约束，入场精度误差要扛一整夜 | 未改时点逻辑 |
| **静态池盲区（已治标）** | V4.8 覆盖 PTrade 已登记概念板；连概念板都没有的极新题材仍进不来（属数据源层改造） | V4.8 缓解，未根除 |
| **接口依赖风险** | `get_concepts` 等依赖本券商 PTrade 版本，若不存在自动降级为静态池（不报错） | 已做降级 |
| **参数过拟合** | 多阈值（ATR倍数/TRAIL/各硬阈值）依赖"扩散多日主线"才盈利，鲁棒性待实盘验证 | 已集中可回退 |

---

## 10. V5 路径B：尾盘选股 + 次日早盘买（独立新文件）

> 文件：`D:\投研工作台\10-策略回测\热点追踪早盘\hotspot_trader_v5_tailsel_morningbuy.py`
> 基于 V4.8 完整复制后增量改造，全部以 `TAIL_SELECT_MODE` 可回退开关挂载；关则完全回到 V4.8 行为。

**动机**：讨论结论——尾盘(14:30)选股确定性显著高于早盘（全天信息充分），但纯后移建仓会吃掉"日内回踩弹性"。故采用路径B：**T-1 选板块 → T 日 14:30 尾盘确认选强 → 跨日 `g.tail_pool` → T+1 早盘回踩买**，既用足尾盘确定性，又保留次日早盘回踩的弹性。

**改动（相对 V4.8，全部增量 + 可回退）**
1. 配置区新增 `TAIL_SELECT_MODE=True` / `TAIL_SELECT_TIME="14:30"` / `TAIL_POOL_MAX=6`（L279–281）。
2. 信号层 `_run_signal_layer` 新增 `g.day_candidates`（与 `g.pending_buy` 同源，T 日 14:30 尾盘选股数据源，不被建仓消费）。
3. 新增三函数：
   - `_confirm_sectors_now()`（L2125）：通用"实时快照判定板块是否在动"。
   - `tail_select_job()`（L2159，@14:30）：确认 `g.day_candidates` 中"今日仍在动"的扩散主线，选强入 `g.tail_pool`（跨日留存，`before_trading_start` 不清除）。
   - `open_confirm_tail()`（L2201，@T+1 09:30）：对尾盘池板块做次日开盘确认 → `g.open_confirm`。
   - `buy_window_scan_tail()`（L2221，@T+1 09:35–10:00）：从 `g.tail_pool` 回踩买，复用 `_try_buy_one` 全部护栏 + 次日开盘确认；窗口终点清空尾盘池（隔夜 stale 丢弃）。
4. `_buy_dispatcher` 分流：TAIL_SELECT_MODE → `buy_window_scan_tail`；否则沿用 V4.8 路由。
5. `initialize` 新增 `g.day_candidates / g.tail_pool / g.tail_slot`。
6. 调度 + `handle_data`（sched_ok 两条分支）均按 `TAIL_SELECT_MODE` 切换路径B/V4.8。

**回退**：`TAIL_SELECT_MODE=False` → 不注册尾盘选股/次日确认任务，建仓完全回到 V4.8（开盘确认 + 当日早盘买）。

**关键不变量**：`before_trading_start` 不重置 `g.tail_pool`，故 T 日 14:30 选出的池可跨日至 T+1 早盘消费；T+1 09:30 `open_confirm_tail` 会对隔夜板块重新确认，死板块被 `_try_buy_one` 剔除，天然防 stale。

**验证建议**：V4.8 基线 vs V5 路径B 对照回测，重点看①尾盘选出的板块次日是否仍有回踩买点（若"今日强、次日直接高开无回踩"占比高，路径B会踏空，需配"竞价直接买"兜底）；②隔夜跳空风险是否被 `open_confirm_tail` 有效控制；③`TAIL_POOL_MAX=8` 与 `MAX_POSITIONS=5` 不冲突（尾盘池上限 ≥ 单日可买上限）；④首笔建仓天然延迟 1 日（部署后 T+1 才首次买入），属路径B固有特性。

### 10.1 路径B调参建议值（V5 已落盘，2026-09-18）

核心思路：**14:30 尾盘有全天信息 → 选股门槛应比 9:30 更严格；两个 9:30（开盘确认 / T+1 次日开盘确认）是"是否还活着"的宽松检查**。因此不整体调高 `OPEN_CONFIRM_MIN_RISE`，而是新增独立的 `TAIL_CONFIRM_MIN_RISE` 专门给尾盘。

| 参数 | V4.8 原值 | V5 路径B 建议值 | 调整理由 |
|---|---|---|---|
| `TAIL_CONFIRM_MIN_RISE` | （无） | **0.025** | 新增。14:30 尾盘选股用全天信息，板块平均涨幅≥2.5% 才视为"全天真强"，过滤日内冲高回落假强 |
| `TAIL_CONFIRM_MIN_ZT` | （无） | **1** | 新增。收盘仍有≥1家涨停/逼近亦确认在动 |
| `OPEN_CONFIRM_MIN_RISE` | 0.015 | **0.015（保持）** | 9:30 开盘确认 + T+1 次日开盘确认 `open_confirm_tail` 共用，刻意宽松防误杀真活板块 |
| `HOT_GAIN_MIN` | 4.0 | **3.0** | 基础热度门槛放宽，严格筛选后移到尾盘收盘确认；避免 T-1 预判过严把盘中日间走强板块提前滤掉 |
| `TAIL_POOL_MAX` | 6 | **8** | 尾盘池跨夜到 T+1 早盘回踩买，多留候选提高回踩命中率（不直接占资金） |
| `BUY_WINDOW_END` | 10:00 | **10:30** | 次日早盘回踩是黄金买点，窗口拉长捕捉更多回踩（V4.7 单窗口路径同步受益） |
| `MAX_DIFFUSE_DAYS` | 5 | **4** | 尾盘选股在 T 日、实际买入在 T+1，板块又老一天，提前防末段 |
| `TRAIL_ARM_PCT` | 0.03 | **0.04** | 隔夜持有，武装阈值略抬，避免隔夜小幅低开即触发移动止盈 |
| `ATR_STOP_MIN_PCT` | 0.04 | **0.05** | 隔夜跳空可能瞬时刺穿，下限抬到 5% 给隔夜低开一点缓冲（仍受 `ATR_STOP_MAX_PCT` 上限约束） |
| `OPEN_CHASE_PCT` | 0.02 | 保持 | 次日高开>2% 仍不追 |
| `BUY_ONLY_IF_ABOVE_OPEN` | True | 保持 | T+1 早盘快照价≥T+1 开盘价才买，防冲高回落接盘 |
| `STALE_EXIT_DAYS` / `MA5_BREAK_MARGIN` / `MARKET_ZT_FLOOR` | 8 / 0.015 / 25 | 保持 | 横盘止损、破线缓冲、市场开关与路径B无关，沿用 |

> 实现细节：`_confirm_sectors_now(context, sector_codes, min_rise, min_zt)` 增加两个可选参数（默认 `OPEN_CONFIRM_*`），仅 `tail_select_job`（14:30）传入 `TAIL_CONFIRM_*`，`open_scan_job` 与 `open_confirm_tail` 仍走默认宽松值。全部阈值集中在 V5 配置区，便于回测调参与回退。

---

## 11. 改动落地清单（行号索引，便于审计）

| 版本 | 关键位置 | 内容 |
|---|---|---|
| V4.5 | L30–56、L189–200、L1457、L1805(later)、L2332 | 入口改造 + 盈亏台账 + 文档头 |
| V4.6 | L217–235（配置）、L1283（`_diffuse_profile`）、L1326（末段不买）、L1364（fresh 标记）、L2121（`_sector_killed` 连续确认）、L1825/L1985（≥开盘价）、L2169–2173（动态移动止盈）、L2198（破线缓冲）、L2205（横盘止损） | 收益差/缺点专项 |
| V4.7 | L238–271（配置）、L1887–2070（函数层）、L1806/L1974（开盘确认否决）、L2288（兜底补触发）、L2475（调度挂载） | 混合架构 + 窗口化 |
| V4.8 | L48–56、L253–265（配置）、L607–745（`_build_sector_index` + `_discover_dynamic_sectors`）、L1520（剔除重复取数）、L2412（状态容器） | 动态板块发现 |
| V5(路径B) | L279–281（配置）、L1593/L1603（day_candidates）、L2125–2288（三函数 `_confirm_sectors_now`/`tail_select_job`/`open_confirm_tail`/`buy_window_scan_tail`）、`_buy_dispatcher` 分流、L2490/L2495（调度）、`initialize` 状态容器 | 尾盘选股+次日早盘买（独立新文件 `hotspot_trader_v5_tailsel_morningbuy.py`） |

---

*文档由策略复盘对话整理生成，所有开关默认开启；任一开关置 False 即回到对应上一版行为。实盘/回测验证前请勿直接用于生产。*
