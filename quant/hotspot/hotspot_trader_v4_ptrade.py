# -*- coding: utf-8 -*-
"""
热点追踪量化程序 V4 —— 盘前选股 + 早盘 10:00 建仓（山西证券 PTrade 版）
=====================================================================
V4 = V3 + 三项改动（其余风控/数据/信号逻辑与 V3 一致）：

  ① 选股数据基准前移到 **T-1 完整收盘**（盘前 before_trading_start 计算）。
     V3 用 "T 日 14:55 尾盘快照"，自己承认那是"尾盘近似"而非已收盘；
     V4 在盘前取数时当日 bar 尚未生成，天然拿到的就是 T-1 完整日K，
     再叠加 drop_today 双保险 —— 全链路只用已收盘数据，口径瑕疵彻底消除。
  ② 建仓时点固定 **T 日 10:00**（由 09:31 后移，用户指定）。
     10:00 取【当日进行中 bar 的 close】作成交基准（唯一的实时价），
     取【T-1 真实收盘】作追高/接刀护栏基准 —— 两个口径显式拆开，不混用。
  ③ 新增 **每个热点板块最多买 2 只**（MAX_PER_SECTOR）：
     候选层按板块截断，下单层再对"已有持仓 + 本轮已买入"二次计数，双重约束。

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

## 已确认的平台口径（V4 按此实现，不再猜测）
  1) get_history **含当日 bar** —— 盘前无当日 bar，10:00 时最后一根为进行中 bar；
  2) volume 单位为 **股**（成交额 = volume × close，不乘 100）；
  3) order_value 限价参数名为 **limit_price**（下划线式）；
  4) 代码后缀 .SS/.SZ/.BJ；持仓可卖字段 enable_amount；Python3.5（无 f-string/无 os）。

## V4 时间线
```
T 日 盘前   before_trading_start
              ① 冷静期衰减 / 持仓天数+1 / 持仓日K缓存（供盘中零取数风控）
              ② ★信号层★ 全池批量取数（drop_today=True）→ 板块强度
                 → 三阶段 → 主线(3条) → 候选(每板块只取前2只)
       ↓ 候选只存代码与特征，不存成交价
T 日 09:35  early_job
              ① 补卖昨日"可卖=0"的排队单
              ② 若盘前信号层失败（g.sector_state 为空）则重试一次
T 日 10:00  buy_job
              ① 取当日进行中 bar close = 快照价 p_now（成交基准）
                 取 rows[-2] close     = T-1 收盘 c_prev（护栏基准）
              ② 双护栏：p_now < c_prev×(1-1.5%) 走弱不接刀；
                        p_now > c_prev×(1+3%)   涨过头不追
              ③ 每板块限 2 只（含已有持仓）→ order_value(..., limit_price=)
T 日 盘中    handle_data        每分钟风控（零额外取数：日K在日初已缓存）
T 日 14:58  risk_fallback_job  盘内兜底风控
```

## 实现状态表（V4 逐条自检，杜绝"声称已修"）
  | 项 | 状态 |
  |----|------|
  | R1 可成交性优先（快照价成交 + 双护栏 + 不接刀 + 可交易性过滤） | 已实现 |
  | R2 口径清晰（T-1 完整收盘选股 + 10:00 快照成交 + 护栏基准已收盘） | 已实现（全链路无未来函数） |
  | R3 换手预算（滚动统计 + 超预算停开新仓） | 已实现 |
  | R4 降级显式告警（含取数为空、下单返回空、护栏基准退化） | 已实现 |
  | ★每板块最多 2 只（候选层截断 + 持仓层二次计数） | 已实现（V4 新增） |
  | ★建仓时点 10:00 固定（run_daily 注册 + 容错窗口 + 盘内兜底） | 已实现（V4 新增） |
  | P0-4 T+1 可卖量（卖出取可卖；可卖=0 排队次日；取整到 100 股） | 已实现 |
  | 静默降级（订单回执 on_order + 空结果必告警） | 已实现 |
  | 量纲（按"股"，并打印标定） | 已实现 |
  | 标识符统一（全链路 6 位，修复持仓排除/冷静期失效） | 已实现 |
  | 涨跌幅自适应（主板10/创业科创20/北交所30/ST5） | 已实现 |
  | 板块强度归一化（剔除规模偏置）+ 宽口径剔除 + Jaccard 去重 | 已实现 |
  | 三阶段接入交易决策（启动买/扩散只回踩/衰退否决） | 已实现 |
  | 板块级联动清仓 | 已实现 |
  | 移动止盈 + ATR 动态止损 + 最短持有期 | 已实现（止损模式可切回固定 -3%） |
  | 市场级开关（涨停家数 + 指数 MA20） | 已实现 |
  | 相对流动性约束 | 已实现 |
  | 批量取数 + 缓存（全池约 20 次调用；盘中零取数） | 已实现 |
  | 板块池题材陈旧（source=sina） | 已解决：已用东方财富 push2delay 重生成真实板块池（496 行业 + 504 概念 / 5645 标的），见 output/sector_map.json |
  | 已知未解决：静态池滞后（建议日频刷新） | 需本地流程，见变更说明 |
  | 已知未解决：10:00 建仓当日被 T+1 锁定至次日 | 制度约束，见变更说明第七节 |

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
TRADE_ENABLED = False               # True=自动交易；False=信号模式
SECTOR_MAP_FILE = "sector_map.json"

SECTOR_MAP_FALLBACK_PATHS = [
    "sector_map.json",
    "只读/sector_map.json",
    "../只读/sector_map.json",
    "readonly/sector_map.json",
    "user/19264938/files/sector_map.json",
    "/user/19264938/files/sector_map.json",
]

# ---- 调度时刻（V4：盘前选股 + 09:35 早盘准备 + 10:00 建仓）----
SIGNAL_AT_PREMARKET = True          # ★V4★ 选股在 before_trading_start（T-1 完整数据）
EARLY_TIME = "09:35"                # ★V4★ 早盘准备：补卖队列 + 盘前信号失败时重试
BUY_TIME = "10:00"                  # ★V4★ 建仓时点（用户指定，固定 10:00）
RISK_FALLBACK_TIME = "14:58"        # 兜底风控（盘内，可成交）
SCHED_GRACE_MIN = 3                 # 容错窗口（分钟）；run_daily 不可用时按窗口兜底

# ---- 仓位与限价 ----
MAX_POSITIONS = 5                   # 同时在仓上限
MAX_PER_SECTOR = 2                  # ★V4★ 每个热点板块最多买入只数
POSITION_RATIO = 0.18               # 单票目标市值 / 总资产（5×18%=90%，留 10% 现金）
BUY_PREMIUM_PCT = 0.03              # 护栏上限 = T-1 收盘×(1+3%)，快照价高于此放弃（涨过头不追）
BUY_FLOOR_PCT = 0.015               # 护栏下限 = T-1 收盘×(1-1.5%)，快照价低于此放弃（走弱不接刀）
BUY_LIMIT_SLIP = 0.005              # ★V4★ 限价 = 快照价×(1+0.5%)，保证成交又不追高
MAX_AMT_SHARE = 0.005               # 单票买入额 <= T-1 成交额 × 0.5%（相对流动性约束）

# ---- 出场纪律 ----
STOP_MODE = "atr"                   # "atr"=ATR动态止损（默认）；"fixed"=固定百分比
STOP_LOSS_PCT = 0.03                # STOP_MODE="fixed" 时生效
ATR_N = 14
ATR_STOP_MULT = 1.8                 # 止损 = 成本 - 1.8×ATR(14)
ATR_STOP_MIN_PCT = 0.04             # ATR 止损收紧下限（防止噪声级别止损）
ATR_STOP_MAX_PCT = 0.08             # ATR 止损放宽上限（防止单边杀跌过久）
MIN_HOLD_FOR_TIGHT_STOP = 5         # 未满 5 个交易日不做紧止损（只受板块级否决约束）
# ★V4.4★ 出场改为纯移动止盈（自持仓最高价回撤 TRAIL_PCT 清仓），不再设 +10%/+15% 硬顶。
TRAIL_PCT = 0.08                    # 移动止盈回撤比例（自持仓最高价）
TRAIL_ARM_PCT = 0.03                # 移动止盈武装阈值：浮盈≥3% 后才挂上移动止盈（避免微利即砍）
RETREAT_MA = 5                      # 破 5 日线清仓（需持仓≥MIN_HOLD_FOR_TIGHT_STOP）
COOL_DOWN_DAYS = 3                  # 止损后冷静期（交易日）

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
# ★V4.4★ 滞后题材板：只作确认过滤（确认候选动量），禁止成为主线驱动选股。
#         回测中"昨日高换手"约 10/12 天是主线，本质是买"昨天已涨的"，入场即滞后。
MAINLINE_BLOCKLIST = ("昨日高换手",)
# ★V4.4★ 剔除信号日已涨 >8% 的候选：次日高开买在阶段高点，易均值回归（入场滞后问题）。
SIGNAL_DAY_GAIN_MAX = 8.0           # 单位与 f["pct"] 一致（百分点），非小数比例
MAX_CANDIDATES = 10                 # 每日候选上限（3 主线 × 2 只 = 6，此值留余量）
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

# ---- 经济性预算 ----
COST_PER_SIDE = 0.0035              # 单边成本（佣金0.03%+滑点0.2%+冲击0.1%+印花税均摊）
TARGET_ANNUAL_COST = 0.15           # 目标年化成本 ≤15%
MAX_ANNUAL_TURNS = int(TARGET_ANNUAL_COST / (2 * COST_PER_SIDE))   # ≈21 次双边
TURNOVER_WINDOW_DAYS = 365          # 滚动换手统计窗口（自然日）
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
    ma20 = _ma(closes, 20)
    return {
        "code": _canon(code), "pct": round(pct, 2), "lianban": lb,
        "vol_ratio": round(vol_ratio, 2), "above20": bool(ma20 and c1 > ma20),
        "amt": amt, "close": c1, "zt_line": zl, "is_st": is_st,
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
    """三阶段（用历史 zt_cnt 平滑，避免日间抖动导致 衰退/扩散 反复跳变）。"""
    z = sig["zt_cnt"]
    if not hist:
        return "启动" if z >= STAGE_ZT_MIN else "无"
    pz = hist[-1]
    avg = (sum(hist) + z) / float(len(hist) + 1)
    if z < max(1.0, pz * 0.5):
        return "衰退"
    if pz < STAGE_ZT_MIN and z >= STAGE_ZT_MIN:
        return "启动"
    if z >= pz or avg >= STAGE_ZT_MIN:
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
    for s in mains:
        stage = s.get("stage", "无")
        if stage == "衰退":
            log.info("[候选] 板块 {} 处衰退期 → 一票否决".format(s["sector"]))
            continue
        for code in g.sector_codes.get(s["sector"], []):
            if code in seen or code in held:
                continue
            f = g.feat.get(code)
            if not f:
                continue
            # 已封板/准封板不可成交 → 剔除（阈值按标的自适应）
            if f["pct"] >= f["zt_line"]:
                continue
            if not f["above20"]:
                continue
            if code in g.cool_down:
                continue
            if stage == "扩散":
                # 扩散期只做回踩：温和涨幅 + 缩量，禁止高位追涨
                if not (0.0 <= f["pct"] < HOT_GAIN_MIN):
                    continue
                if f["vol_ratio"] >= DIFFUSE_VR_MAX:
                    continue
            else:
                if f["pct"] < HOT_GAIN_MIN:
                    continue
            # ★V4.4★ 剔除信号日已涨 >8% 的候选（入场滞后：次日买高点易均值回归）
            if f["pct"] > SIGNAL_DAY_GAIN_MAX:
                continue
            # 量价已过关，最后才查名（省去数千次查名）
            if REQUIRE_NO_ST and _is_st(code):
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

    ⚠ 口径说明：判定用的是**最近一个已收盘交易日**的数据（T-1），不是 10:00 的
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


# ============================================================
# 九、换手预算
# ============================================================
def _record_trade(context, value, side):
    try:
        g.trades.append((_today_str(context), float(abs(value)), side))
        if len(g.trades) > 8000:
            g.trades = g.trades[-4000:]
    except Exception:
        pass


def turnover_ok(context, total_asset):
    """滚动窗口双边换手 = 累计成交额 / (2×总资产)，超预算则停开新仓。"""
    if not g.trades or total_asset <= 0:
        return True
    dt = _now_dt(context)
    try:
        cutoff = (dt - datetime.timedelta(days=TURNOVER_WINDOW_DAYS)).strftime("%Y-%m-%d")
    except Exception:
        return True
    traded = sum(v for (d, v, _) in g.trades if d >= cutoff)
    turns = traded / (2.0 * total_asset)
    if turns > MAX_ANNUAL_TURNS:
        log.info("[换手预算] 滚动双边换手 {:.1f} 次 > 预算 {} 次 → 停开新仓"
                 "（应放宽买入条件/延长持有，而非加止盈）".format(turns, MAX_ANNUAL_TURNS))
        return False
    return True


# ============================================================
# 十、信号主入口（V4：T 日盘前，用 T-1 完整收盘数据）
# ============================================================
def _run_signal_layer(context):
    """★V4 核心改动★ 在盘前调用，全部数据为 T-1 及以前的完整已收盘日K。"""
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
        s["stage"] = classify_stage(s, h[-2:])
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
        log.info("[候选] 主线 {} 条 × 每板块限 {} 只 → 今日 10:00 候选 {} 只".format(
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
        g.prev_signal[s["sector"]] = g.prev_signal[s["sector"]][-5:]
    g.sector_state = signals
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
# 十一、交易层：T 日 09:35 补卖 + T 日 10:00 建仓
# ============================================================
def _live_price_and_ref(context, codes):
    """★V4.1 修正回测口径★ 取候选的【T 日 10:00 快照价 p_now】与【护栏基准 c_prev】。

    数据源优先级（同时满足"实盘含当日 bar"与"回测也能取日内价"两种环境）：
      1) get_current_data() 的 last_price / pre_close —— 日内进行中价；实盘与回测引擎在
         10:00 都能给出当日真实快照价与昨收（昨收即涨停基准，与护栏一致）；
      2) 日 K（get_history，fetch）兜底 —— 仅当 get_current_data 不可用或该票缺字段时回退。
         回测在 10:00 不暴露当日 bar（日 K 只到 T-1）时，p_now/c_prev 退化为 T-1 收盘并显式告警。

    为什么要改（回测死穴）：旧实现在 10:00 只用日 K，而回测数据在 10:00 不返回当日 bar，
    导致 p_now 与 c_prev 都等于 T-1 收盘 —— "10:00 快照限价"与"开盘越界放弃"护栏在回测里
    完全失效，测的只是"按 T-1 收盘 +0.5% 滑点建仓"的近似。改用日内源后回测才忠实。
    """
    cur = None
    try:
        cur = get_current_data()
    except Exception:
        cur = None
    snap = fetch(codes, 2)
    today = _today_str(context)
    out = {}
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
        # p_now：优先日内快照价，否则日 K 当日 close，否则日 K 最近 close
        if g_lp and g_lp > 0:
            p_now = g_lp
        elif rows:
            p_now = rows[-1][1]
        else:
            p_now = 0.0
        # c_prev：优先日内昨收（即涨停基准），否则日 K T-1 close，否则日 K 最近 close
        if g_pc and g_pc > 0:
            c_prev = g_pc
        elif len(rows) >= 2 and _is_today_row(rows[-1], today):
            c_prev = rows[-2][1]
        elif rows:
            c_prev = rows[-1][1]
        else:
            c_prev = 0.0
        if not p_now or not c_prev:
            continue
        intraday_ok = bool(g_lp > 0 and g_pc > 0)
        # 仅当既无日内源、又无当日日 K 时才告警（回测 10:00 不暴露当日 bar 的典型情形）
        if not intraday_ok and not (rows and len(rows) >= 2 and _is_today_row(rows[-1], today)):
            _degrade("anchor", "{} 10:00 未见当日 bar（get_current_data 不可用），护栏基准退化为最近收盘".format(c))
        out[c] = {
            "p_now": p_now,
            "c_prev": c_prev,
            "has_today": intraday_ok or (bool(rows) and len(rows) >= 2 and _is_today_row(rows[-1], today)),
        }
    return out


def _do_sell(code, amount, reason):
    held_px = positions_map().get(code)
    held = (_pos_f(held_px, "current_amount") or _pos_f(held_px, "enable_amount") or 0) if held_px else amount
    amt = _round_lot(amount, held if held else amount)
    if amt <= 0:
        return
    if TRADE_ENABLED:
        try:
            o = order(_suffix(code), -amt)
            log.info("[卖出] {} {} 股 原因:{} 委托={}".format(code, amt, reason, o))
        except Exception as e:
            _degrade("sell", "{} 下单异常: {}".format(code, repr(e)))
    else:
        log.info("[信号-卖] {} 应卖 {} 股 原因:{}".format(code, amt, reason))


def early_job(context):
    """T 日 09:35：① 补处理昨日可卖=0 的止损队列；② 盘前信号失败时重试一次。"""
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
    """★V4 核心改动★ T 日 10:00：取快照价 → 双护栏校验 → 每板块限 2 只 → 限价建仓。"""
    if not _is_trading_day_guard(context):
        return
    _HEALTH["degraded"] = []
    g.now_str = _now_str(context) or BUY_TIME
    log.info("=" * 72)
    log.info("[{}] V4 建仓层（T-1 定热点 → 10:00 买入，每板块限 {} 只）开始".format(
        g.now_str, MAX_PER_SECTOR))
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
    target = total * POSITION_RATIO
    cash = _cash_of(context, total, len(held))
    if target > cash:
        log.info("[买入] 停单兜底：单票目标 {:.0f} > 可用现金 {:.0f}，今日不建仓".format(target, cash))
        g.pending_buy = []
        _dump_health("[建仓]")
        return
    if not turnover_ok(context, total):
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
    while idx < len(pending) and done < remaining:
        f = pending[idx]
        idx += 1
        code = f["code"]
        if code in held:
            continue
        sec = f.get("sector")
        # ★V4：每个热点板块最多 MAX_PER_SECTOR 只（含已有持仓与本轮已买入）★
        if sec and _held_sector_count(held, sec) >= MAX_PER_SECTOR:
            log.info("[买入] {} 板块「{}」持仓已达 {} 只上限 → 跳过".format(
                code, sec, MAX_PER_SECTOR))
            continue
        sc = snap.get(code)
        if not sc:
            _degrade("buy", "{} 无快照价/T-1收盘价，放弃".format(code))
            continue
        p_now, c_prev = sc["p_now"], sc["c_prev"]
        upper_ref = round(c_prev * (1 + BUY_PREMIUM_PCT), 2)
        lower_ref = round(c_prev * (1 - BUY_FLOOR_PCT), 2)
        if p_now < lower_ref:
            log.info("[买入] {} 快照 {:.2f} < 下线 {:.2f}（早盘走弱不接刀）→ 放弃".format(
                code, p_now, lower_ref))
            continue
        if p_now > upper_ref:
            log.info("[买入] {} 快照 {:.2f} > 上线 {:.2f}（早盘涨过头不追）→ 放弃".format(
                code, p_now, upper_ref))
            continue
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
                if sec:
                    sec_now[sec] = sec_now.get(sec, 0) + 1
                _record_trade(context, target, "buy")
                log.info("[买入] {} [{}|{}] 快照{:.2f} 护栏[{:.2f},{:.2f}] 限价{:.2f} 目标{:.0f} 委托={}".format(
                    code, sec, f.get("stage", ""), p_now, lower_ref, upper_ref, limit, target, oid))
            else:
                _degrade("buy", "{} 下单返回空（未成交）".format(code))
        else:
            log.info("[信号-买] {} [{}|{}] 快照{:.2f} 护栏[{:.2f},{:.2f}] 限价{:.2f}".format(
                code, sec, f.get("stage", ""), p_now, lower_ref, upper_ref, limit))
        done += 1
    g.pending_buy = pending[idx:]
    if g.pending_buy:
        log.info("[买入] 本轮处理 {} 笔，剩余 {} 笔留待下次（切片用独立下标，不会错位）".format(
            done, len(g.pending_buy)))
    _dump_health("[建仓]")


# ============================================================
# 十二、风控层（每分钟 + 14:58 兜底）
# ============================================================
def _sector_killed():
    """板块级一票否决集合：仅当板块发生"真实退潮"才清仓，避免每日涨停家数自然波动造成 whipaw。

    ★V4.2 修复★ 旧逻辑：历史≥2点 + 前峰值≥2 + 今日 zt_cnt<峰值×0.5 即砍。热点板块涨停家数
    日间本就波动（2→1 是常态），导致"建仓次日 09:31 即砍"（回测 17/22 笔平仓属此类），且不论盈亏
    一刀切，把刚建仓的赢仓也砍在起涨点。新逻辑只认"真实退潮"：
      ① stage=="衰退"（三阶段模型已确认退潮）；或
      ② 广度真实塌陷：历史≥3个观测点 + 前2日峰值≥4家涨停 + 今日涨停家数≤1
         （从≥4掉到≤1 属结构性退潮；2→1 的正常波动不再触发）。
    盈利持仓不在此层强平，交由止盈/移动止盈处理，避免"刚建仓次日即砍赢仓"。
    """
    killed = set()
    for s in (g.sector_state or []):
        if s.get("stage") == "衰退":
            killed.add(s["sector"])
            continue
        h = g.prev_signal.get(s["sector"]) or []
        if len(h) >= 3:
            peak = max(h[-3:-1]) if len(h) >= 3 else max(h[:-1])
            if peak >= 4 and s["zt_cnt"] <= 1:
                killed.add(s["sector"])
    return killed


def monitor_risk(context):
    pm = positions_map()
    if not pm:
        return
    killed = _sector_killed()
    for code, px in pm.items():
        amount = _pos_f(px, "current_amount") or _pos_f(px, "enable_amount") or 0
        if amount <= 0:
            continue
        cost = _pos_f(px, "cost_price") or _pos_f(px, "avg_price") or 0
        price_now = _pos_f(px, "last_price") or _pos_f(px, "price") or 0
        rows = g.pos_hist.get(code) or []
        closes = [r[1] for r in rows]
        if not price_now and closes:
            price_now = closes[-1]
        if not price_now:
            continue
        g.peak[code] = max(g.peak.get(code, 0.0), price_now)
        sell, reason = None, ""
        # ① 板块级联动清仓（早于单票止损）
        # ★V4.3 修复★ 仅对【亏损】持仓强平；盈利持仓交由止盈/移动止盈处理，
        #   避免"起涨点砍赢仓"。旧逻辑不论盈亏一刀切（与 _sector_killed docstring 承诺矛盾），
        #   回测中大量次日即砍的赢仓被误杀，是负收益首因之一。
        sec = g.code_sector.get(code)
        if sec and sec in killed:
            pr_sec = (price_now / cost - 1.0) if cost else 0.0
            if pr_sec <= 0:
                sell, reason = amount, "板块联动清仓:{}转衰退/腰斩(亏损)".format(sec)
            else:
                log.info("[风控] {} 板块{}转衰退但盈利{:.1%}，不在此强平（交止盈处理）".format(
                    code, sec, pr_sec))
        # ② 纯移动止盈（★V4.4★ 去掉 +10%/+15% 硬顶，全程只跟持仓最高价回撤 TRAIL_PCT 清仓）
        #    武装阈值 TRAIL_ARM_PCT：浮盈≥3% 后才挂上移动止盈，避免微利即砍；
        #    赢仓可一路多跑，直到自最高点回撤 8% 才离场。
        if sell is None and cost:
            pr = price_now / cost - 1
            peak = g.peak.get(code, 0.0)
            if peak > 0 and pr >= TRAIL_ARM_PCT and price_now <= peak * (1 - TRAIL_PCT):
                sell, reason = amount, "移动止盈:自高点{:.1f}回撤{:.1%}".format(peak, TRAIL_PCT)
        # ③ 止损（移动止盈未触发时）
        if sell is None and cost:
            pr = price_now / cost - 1
            held_days = g.hold_days.get(code, 99)
            stop_pct = 0.0
            if STOP_MODE == "fixed":
                stop_pct = STOP_LOSS_PCT
            elif rows:
                a = _atr(rows)
                if a and cost:
                    stop_pct = a * ATR_STOP_MULT / cost
                    stop_pct = max(ATR_STOP_MIN_PCT, min(ATR_STOP_MAX_PCT, stop_pct))
            if stop_pct and pr <= -stop_pct:
                if held_days >= MIN_HOLD_FOR_TIGHT_STOP:
                    sell, reason = amount, "止损:浮亏{:.1%} (模式{}, 阈值{:.1%})".format(
                        pr, STOP_MODE, stop_pct)
                else:
                    log.info("[风控] {} 浮亏{:.1%} 但持仓仅{}日(<{}日)，暂不紧止损".format(
                        code, pr, held_days, MIN_HOLD_FOR_TIGHT_STOP))
        # ④ 破均值线清仓（短持仓不触发，避免噪声止损 —— ★V4.3 修复★）
        if sell is None and len(closes) >= RETREAT_MA:
            ma = _ma(closes, RETREAT_MA)
            if ma and price_now < ma:
                held_days_break = g.hold_days.get(code, 99)
                if held_days_break >= MIN_HOLD_FOR_TIGHT_STOP:
                    sell, reason = amount, "破{}日线清仓".format(RETREAT_MA)
                else:
                    log.info("[风控] {} 破{}日线但持仓仅{}日(<{}日)，暂不噪声止损".format(
                        code, RETREAT_MA, held_days_break, MIN_HOLD_FOR_TIGHT_STOP))
        if sell and sell > 0:
            if reason.startswith(("止损", "破")):
                g.cool_down[code] = COOL_DOWN_DAYS
            tr = _tradeable_amount(px)
            if tr <= 0:
                g.stop_queue.append((code, amount, reason))
                log.info("[卖出排队] {} 可卖量0，次日首时段补卖: {}".format(code, reason))
                continue
            _do_sell(code, min(sell, tr), reason)


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
    g.buy_today = set()
    # 持仓日K缓存（供盘中零取数风控）
    if pm:
        g.pos_hist = fetch(list(pm.keys()), POS_BARS)
        if not g.pos_hist:
            _degrade("poshist", "持仓日K缓存为空，ATR/均线风控将降级")
    log.info("[日初] 持仓 {} 只 冷静期 {} 只 上一轮候选 {} 只".format(
        len(pm), len(g.cool_down), len(g.pending_buy)))
    # ★V4：盘前选股（用 T-1 完整收盘数据；此时当日 bar 尚未生成）★
    if SIGNAL_AT_PREMARKET:
        try:
            _run_signal_layer(context)
        except Exception as e:
            _degrade("signal", "盘前信号层异常: {}".format(repr(e)))
    _dump_health("[盘前]")


def handle_data(context, data):
    """盘中主循环：只做风控（建仓/早盘准备由 run_daily 负责；不可用时按窗口兜底）。"""
    g.now_str = _now_str(context)
    now = g.now_str
    if not now:
        _degrade("clock", "无法获取当前时间，handle_data 空转")
        _dump_health("[时钟]")
        return
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
            monitor_risk(context)
        except Exception as e:
            _degrade("risk", "风控异常: {}".format(repr(e)))


def risk_fallback_job(context):
    g.now_str = _now_str(context) or RISK_FALLBACK_TIME
    try:
        monitor_risk(context)
    except Exception as e:
        _degrade("risk", "兜底风控异常: {}".format(repr(e)))
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
    log.info("[初始化] V4 启动 TRADE_ENABLED={} 调度={} 板块池={}".format(
        TRADE_ENABLED, "run_daily" if g.sched_ok else "handle_data兜底", SECTOR_MAP_FILE))
    log.info("[初始化] 口径: 选股=盘前(T-1完整收盘) | 建仓={} 快照限价 | 护栏基准=T-1收盘".format(
        BUY_TIME))
    log.info("[初始化] 每板块限 {} 只 | 总仓上限 {} 只 × {:.0%} | 护栏 [T-1收盘×{:.1%}, ×{:.1%}]".format(
        MAX_PER_SECTOR, MAX_POSITIONS, POSITION_RATIO,
        1 - BUY_FLOOR_PCT, 1 + BUY_PREMIUM_PCT))
    log.info("[初始化] 止损模式={} 换手预算≤{} 次双边".format(STOP_MODE, MAX_ANNUAL_TURNS))
    _dump_health("[初始化]")
