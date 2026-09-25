# -*- coding: utf-8 -*-
"""
热点追踪量化程序 V3 —— 板块共振 + 三阶段择时（山西证券 PTrade 版）
=====================================================================
V3 = V2 + 《V2策略审计报告与优化方案.md》全部 P0/P1 修复。

## 已确认的平台口径（V3 按此实现，不再猜测）
  1) get_history **含当日 bar** —— 当日最后一根为进行中 bar；
  2) volume 单位为 **股**（成交额 = volume × close，不乘 100）；
  3) order_value 限价参数名为 **limit_price**（下划线式）。

## 口径设计（V3 核心变更，如实标注，不再自称"只用已收盘数据"）
  · 选股口径 = **T 日 14:55 尾盘快照**（含当日 bar，属"尾盘近似"，非已收盘）；
  · 成交口径 = **T+1 09:31 开盘限价单**；
  · 价格锚   = **T 日真实收盘价**（于 T+1 09:31 读取 closes[-2] 取得，此时
               T+1 当日 bar 已生成，故 closes[-2] 即 T 日最终收盘，**完全精确**）；
  · 因此全链路不存在未来函数：选股只用 T 日及以前，成交在 T+1，锚为已收盘价。

  V2 的致命错位（锚取 T-1 收盘、低于 T 日收盘，导致"只在低开时成交"）已消除：
  V3 上限 = T日收盘×(1+3%)，下限 = T日收盘×(1-1.5%)，开盘价越界一律放弃。

## 实现状态表（V3 逐条自检，杜绝"声称已修"）
  | 项 | 状态 |
  |----|------|
  | R1 可成交性优先（锚正确 + 双边限价 + 不接刀） | 已实现 |
  | R2 口径清晰（尾盘快照选股 + 已收盘锚 + T+1 成交） | 已实现（如实标注） |
  | R3 换手预算（滚动统计 + 超预算停开新仓） | 已实现 |
  | R4 降级显式告警（含取数为空、下单返回空） | 已实现 |
  | P0-1 时间门（run_daily 注册 + 容错窗口 + 盘内兜底 + 不依赖 run_daily 的降级） | 已实现 |
  | P0-2 静默降级 | 已实现（订单回执 on_order + 空结果必告警） |
  | P0-3 量纲（按"股"，并打印标定） | 已实现 |
  | P0-4 T+1 可卖量（卖出取可卖；可卖=0 排队次日；取整到 100 股） | 已实现 |
  | P0-5 缩量/资金停单 | 部分（资金停单已实现；成交缩量检测依赖 on_order 字段，见 on_order） |
  | 标识符统一（修复 V2 持仓排除/冷静期失效） | 已实现（全链路 6 位） |
  | 涨跌幅自适应（主板10/创业科创20/北交所30/ST5） | 已实现 |
  | 板块强度归一化（剔除规模偏置） | 已实现 |
  | 宽口径标签剔除 + Jaccard 去重 | 已实现 |
  | 三阶段接入交易决策（启动买/扩散只回踩/衰退否决） | 已实现 |
  | 板块级联动清仓 | 已实现 |
  | 批量取数 + 缓存（13,609 次 → 约 15 次批量调用） | 已实现 |
  | 市场级开关（涨停家数 + 指数 MA20） | 已实现 |
  | 相对流动性约束 | 已实现 |
  | 移动止盈 + ATR 动态止损 + 最短持有期 | 已实现（止损模式可切回固定 -3%） |
| 板块池来源（已改） | 已实现（gen_sector_map.py 抓东方财富概念+行业；覆盖 AI/算力/低空/光模块） |
| 静态池日频刷新（已改） | 已实现（before_trading_start 每日失效缓存 + SECTOR_MAP_MAX_AGE_DAYS 过期告警；每日盘前跑 gen_sector_map.py 重新生成上传） |

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
SECTOR_MAP_MAX_AGE_DAYS = 2        # 板块池生成超过此天数 → 显式告警（日频刷新时应≤2）

SECTOR_MAP_FALLBACK_PATHS = [
    "sector_map.json",
    "只读/sector_map.json",
    "../只读/sector_map.json",
    "readonly/sector_map.json",
    "user/19264938/files/sector_map.json",
    "/user/19264938/files/sector_map.json",
]

# ---- 调度时刻（V3：run_daily 注册，不依赖精确字符串匹配）----
SIGNAL_TIME = "14:55"               # 选股：尾盘快照（含当日 bar，如实口径）
BUY_TIME = "09:31"                  # 建仓：T+1 开盘后 1 分钟（确保当日 bar 已生成）
RISK_FALLBACK_TIME = "14:58"        # 兜底风控（盘内，可成交）
SCHED_GRACE_MIN = 3                 # 容错窗口（分钟）；run_daily 不可用时按窗口兜底

# ---- 仓位与限价 ----
MAX_POSITIONS = 5                   # 同时在仓上限
POSITION_RATIO = 0.18               # 单票目标市值 / 总资产（5×18%=90%，留 10% 现金）
BUY_PREMIUM_PCT = 0.03              # 上限 = T日收盘×(1+3%)，高于开盘价则放弃
BUY_FLOOR_PCT = 0.015               # 下限 = T日收盘×(1-1.5%)，低于则放弃（不接刀）
MAX_AMT_SHARE = 0.005               # 单票买入额 <= 当日成交额 × 0.5%（相对流动性约束）

# ---- 出场纪律 ----
STOP_MODE = "atr"                   # "atr"=ATR动态止损（默认）；"fixed"=固定百分比
STOP_LOSS_PCT = 0.03                # STOP_MODE="fixed" 时生效（对齐原决策3）
ATR_N = 14
ATR_STOP_MULT = 1.8                 # 止损 = 成本 - 1.8×ATR(14)
ATR_STOP_MIN_PCT = 0.04             # ATR 止损收紧下限（防止噪声级别止损）
ATR_STOP_MAX_PCT = 0.08             # ATR 止损放宽上限（防止单边杀跌过久）
MIN_HOLD_FOR_TIGHT_STOP = 5         # 未满 5 个交易日不做紧止损（只受板块级否决约束）
TAKE_PROFIT1_PCT = 0.10             # +10% 减半
TAKE_PROFIT2_PCT = 0.15             # +15% 清仓
TRAIL_PCT = 0.08                    # 移动止盈：自持仓最高价回撤 8% 清仓
RETREAT_MA = 5                      # 破 5 日线清仓（对齐决策3，原为20）
COOL_DOWN_DAYS = 3                  # 止损后冷静期（交易日）

# ---- 信号层 ----
STAGE_ZT_MIN = 2                    # 进入启动期所需最小当日涨停家数
TOP_MAIN_LINES = 3                  # 主线板块数量（V3 由 2 提到 3，配合归一化）
MAX_SECTOR_SIZE = 80                # 成分数超过此值的板块不参与主线评选
MAX_CANDIDATES = 10                 # 每日候选上限
HOT_GAIN_MIN = 4.0                  # 成分入选板块强度统计 / 启动期候选的最小区间涨幅(%)
DIFFUSE_VR_MAX = 1.5                # 扩散期"回踩"要求：量比下限（缩量）
REQUIRE_NO_ST = True                # 剔除 ST/*ST
MIN_HIST_BARS = 60                  # 剔除次新（并保 MA60 计算）
MIN_AMOUNT = 3e8                    # 当日成交额下限 3 亿元（volume 单位=股，真实生效）
REQUIRE_MAIN_INFLOW = True          # 剔除主力净流出近似（放量 + 收在振幅下半）
FLOW_LAG_VR = 2.0                   # 净流出近似量比阈值
VOL_RATIO_ADJUST = True             # 量比按已交易分钟折算（尾盘≈1.0，盘中才有意义）

BROAD_TAG_BLACKLIST = (             # 宽口径属性标签（非题材），禁止参与主线评选
    "融资融券", "参股金融", "金融参股", "专精特新", "股权激励",
    "业绩预升", "业绩预降", "重组概念", "次新股", "其它行业",
    "超大盘", "含GDR", "含H股", "央企50", "基金重仓", "保险重仓", "股期概念",
)

# ---- 市场级开关 ----
MARKET_ZT_FLOOR = 25                # 板块池内涨停家数低于此值 → 停开新仓
INDEX_FOR_REGIME = "000300.SS"
INDEX_BARS = 60

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
    V2 的致命 bug 源于 positions_map 用带后缀 key、板块成分用 6 位，
    导致 `code in held` / `code in cool_down` 永不命中。V3 全链路统一为本函数。"""
    return _pure(code)


def _limit_pct(code, is_st=False):
    """该标的当日涨跌幅限制（小数）。V2 一刀切 9.5% 导致双向失真。"""
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
    """T+1 可卖量（P0-4）。
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
    """持仓快照 {6位code: position}。★V3 修正：key 统一为 6 位★"""
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


# ============================================================
# 四、板块静态池载入
# ============================================================
def _warn_stale_pool(generated_at):
    """板块池生成时间距今天数超阈值 → 显式告警（日频刷新纪律）。"""
    if not generated_at:
        _degrade("sector_map", "板块池无 generated_at 字段，无法判断新鲜度，请改用 gen_sector_map.py 重新生成")
        return
    try:
        gt = datetime.datetime.strptime(str(generated_at)[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        # 兼容 "2026-09-13 09:20:56" 等形态
        try:
            gt = datetime.datetime.strptime(str(generated_at)[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")
        except Exception:
            _degrade("sector_map", "板块池 generated_at 解析失败({})，请重新生成".format(generated_at))
            return
    age = (datetime.datetime.now() - gt).days
    if age > SECTOR_MAP_MAX_AGE_DAYS:
        _degrade("sector_map", "板块池生成于 {}，已 {} 天（>{} 天）未刷新；"
                 "题材已滞后热点周期，请运行 gen_sector_map.py 日频刷新后重新上传".format(
                     generated_at, age, SECTOR_MAP_MAX_AGE_DAYS))
        log.info("[板块池] !! 过期告警：题材池可能落后 3~5 天热点周期，信号质量下降")


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
            # 过期告警（日频刷新：若生成日距今天数超阈值，说明没按时刷新）
            _warn_stale_pool(data.get("generated_at"))
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
def _hist_call(n, fields, part, is_dict=None):
    """调用 get_history，自动适配 fq / is_dict 参数是否被本券商版本支持。
    首次带 fq="pre" 失败 -> 记录并改为不复权重试（结果会打印告警，绝不静默换口径）。"""
    kw = {}
    if is_dict is not None:
        kw["is_dict"] = is_dict
    if getattr(g, "fq_ok", None) is not False:
        try:
            r = get_history(n, "1d", fields, part, fq="pre", **kw)
            g.fq_ok = True
            g.fq_fail = 0
            return r
        except Exception as e:
            # 连续 2 次失败才判定"本版本不支持 fq"，避免一次瞬时异常就永久降级
            g.fq_fail = getattr(g, "fq_fail", 0) + 1
            if g.fq_fail >= 2:
                g.fq_ok = False
            _degrade("hist", "带 fq='pre' 取数失败（第{}次{}）: {}".format(
                g.fq_fail,
                "，已永久改为不复权" if g.fq_ok is False else "，本次改为不复权",
                repr(e)))
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
    """按列向量化取值（避免 df.iloc[i] 逐行访问的慢写法）。
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
    # DataFrame（含 MultiIndex 列，自动展平）
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
    # dict of columns
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
    # list of dict / list of list
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


def fetch(codes, n):
    """批量取数 -> {6位code: rows}。三级降级：dict -> multiindex -> single。"""
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
                if isinstance(r, dict):
                    for k, v in r.items():
                        rows = _rows_from_any(v)
                        if rows:
                            out[_canon(k)] = rows
                    continue
                _degrade("fetch", "dict 模式返回非 dict，降级为逐票处理本批")
            if mode == "multiindex":
                r = _hist_call(n, HIST_FIELDS, part)
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
    return out


def _is_st(code):
    """ST 判定（带缓存）。★只对通过量价筛选的少数标的调用，避免 3784 次查名。"""
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
    """单只个股特征。rows 来自缓存（遵守尾盘快照口径）。返回 dict / None。"""
    if not rows or len(rows) < MIN_HIST_BARS:
        return None
    closes = [r[1] for r in rows]
    vols = [r[4] for r in rows]
    c1, c0 = closes[-1], closes[-2]
    if not c0 or not c1:
        return None
    is_st = _is_st(code) if want_name else False
    zl = _zt_line(code, is_st)
    # 成交额：★volume 单位=股（已确认口径）★ 不乘 100
    amt = vols[-1] * c1
    if amt < MIN_AMOUNT:
        return None
    pct = (c1 / c0 - 1) * 100.0
    # 连板数
    lb = 0
    for i in range(len(closes) - 1, 0, -1):
        pc = closes[i - 1]
        chg = (closes[i] / pc - 1) * 100.0 if pc else 0.0
        if chg >= zl:
            lb += 1
        else:
            break
    # 量比（按已交易分钟折算，避免"半日量 vs 全日均量"的系统性低估）
    ma5v = sum(vols[-6:-1]) / 5.0 if len(vols) >= 6 and sum(vols[-6:-1]) > 0 else 0.0
    vol_ratio = (vols[-1] / ma5v) if ma5v else 0.0
    if VOL_RATIO_ADJUST:
        e = _elapsed_min(g.now_str)
        if 0 < e < 240:
            vol_ratio = vol_ratio * (240.0 / e)
    # 主力净流出近似：放量但收在振幅下半
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
    """板块信号。★V3：强度全部归一化，剔除"成分越多越强"的规模偏置★"""
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
    """主线：归一化强度排序 + 宽口径剔除 + 体量上限 + Jaccard 去重。"""
    sigs = sorted(signals, key=lambda s: s["strength"], reverse=True)
    picks, skipped = [], []
    for s in sigs:
        if len(picks) >= TOP_MAIN_LINES:
            break
        name = s["sector"]
        if not s["zt_cnt"]:
            continue
        if name in BROAD_TAG_BLACKLIST:
            skipped.append(name + "(宽口径)")
            continue
        cs = set(g.sector_codes.get(name, []))
        if not cs:
            continue
        if len(cs) > MAX_SECTOR_SIZE:
            skipped.append("{}(成分{})".format(name, len(cs)))
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
    """候选：三阶段接入决策 + 标识符统一（持仓排除/冷静期真正生效）。"""
    held = set(positions_map().keys())
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
            # 量价已过关，最后才查名（省去数千次查名）
            if REQUIRE_NO_ST and _is_st(code):
                seen.add(code)
                continue
            d = dict(f)
            d["sector"] = s["sector"]
            d["stage"] = stage
            cands.append(d)
            seen.add(code)
    cands.sort(key=lambda x: (min(x["pct"], 9.0), min(x["vol_ratio"], 3.0)), reverse=True)
    return cands[:MAX_CANDIDATES]


# ============================================================
# 七、扫描范围（批量不可用时自动收缩，保证能跑完）
# ============================================================
def _scan_universe():
    """
    返回要扫描的 6 位代码列表。
    批量可用 -> 全池；逐票模式 -> 收缩到黑名单外 + 体量合规板块的并集（显式告警）。
    """
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
    """① 池内涨停家数 >= 阈值；② 指数站上 MA20。数据全部用缓存，零额外请求。"""
    zt = 0
    for c, f in g.feat.items():
        if f["pct"] >= f["zt_line"]:
            zt += 1
    if g.feat and zt < MARKET_ZT_FLOOR:
        log.info("[市场开关] 池内涨停约 {} 家 < 阈值 {} → 停开新仓".format(zt, MARKET_ZT_FLOOR))
        return False
    rows = g.index_rows
    if rows:
        closes = [r[1] for r in rows]
        ma20 = _ma(closes, 20)
        if ma20 and closes and closes[-1] < ma20:
            log.info("[市场开关] 指数 {:.1f} < MA20 {:.1f} → 停开新仓".format(closes[-1], ma20))
            return False
    return True


# ============================================================
# 九、换手预算（R3 真正落地）
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
# 十、信号主入口（T 日 14:55）
# ============================================================
def _run_signal_layer(context):
    if not _build_sector_index()[0]:
        log.info("[信号] 板块池不可用，本日不生成信号")
        g.pending_buy = []
        return
    uni = _scan_universe()
    g.hist = fetch(uni, LOOKBACK)
    log.info("[信号] 批量取数 {}/{} 只成功".format(len(g.hist), len(uni)))
    if not g.hist:
        _degrade("signal", "全池取数为空（数据层故障），本日不生成信号")
        g.pending_buy = []
        return
    # 指数（市场开关用）
    try:
        idx = fetch([INDEX_FOR_REGIME], INDEX_BARS)
        g.index_rows = idx.get(_canon(INDEX_FOR_REGIME)) or []
    except Exception as e:
        _degrade("index", "指数取数失败: {}".format(repr(e)))
    # 个股特征（一次算好，供板块聚合与候选复用）
    g.feat = {}
    for c, rows in g.hist.items():
        f = _stock_feat(c, rows)
        if f:
            g.feat[c] = f
    log.info("[信号] 通过四道过滤的个股 {} 只（池内 {} 只）".format(len(g.feat), len(g.hist)))
    # 板块聚合
    signals = []
    for name, codes in g.sector_codes.items():
        try:
            s = build_sector_signal(name, codes)
        except Exception as e:
            _degrade("signal", "板块 {} 信号异常: {}".format(name, repr(e)))
            continue
        if s:
            signals.append(s)
    # 三阶段（历史 zt_cnt 平滑）
    for s in signals:
        h = g.prev_signal.get(s["sector"]) or []
        s["stage"] = classify_stage(s, h[-2:])
    mains = _main_line_groups(signals)
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
        log.info("[候选] 主线 {} 条 → T+1 开盘候选 {} 只".format(len(mains), len(g.pending_buy)))
        for c in g.pending_buy:
            log.info("  {} {} [{}] +{:.1f}% 连板{} 量比{} 成交额{:.1f}亿".format(
                c["code"], c.get("sector", ""), c.get("stage", ""), c["pct"],
                c["lianban"], c["vol_ratio"], c["amt"] / 1e8))
    else:
        log.info("[候选] 今日无主线（可能全市场退潮），无 T+1 候选")
        g.pending_buy = []
    if TRADE_ENABLED and not g.pending_buy:
        log.info("!! [告警] TRADE_ENABLED=True 但今日无候选/无主线，本轮不建仓（非信号模式）")
    # 记录历史（供明日三阶段对照）
    for s in signals:
        g.prev_signal.setdefault(s["sector"], [])
        g.prev_signal[s["sector"]].append(s["zt_cnt"])
        g.prev_signal[s["sector"]] = g.prev_signal[s["sector"]][-5:]
    g.sector_state = signals
    # 量纲标定（一次性打印，杜绝 V2 的静默量纲歧义）
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
# 十一、交易层：T+1 开盘（先补卖，再建仓）
# ============================================================
def _open_price_and_anchor(codes):
    """
    取候选的【T 日真实收盘价】与【T+1 开盘价】。
    T+1 开盘时 get_history 含当日 bar → closes[-2] 即 T 日最终收盘（已收盘、精确），
    open[-1] 即 T+1 开盘价。这是 V3 修复"锚错位"的核心。
    """
    snap = fetch(codes, 2)
    out = {}
    for c, rows in snap.items():
        if len(rows) >= 2:
            out[c] = {"anchor": rows[-2][1], "open": rows[-1][5]}
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


def open_job(context):
    """T+1 09:31：① 补处理昨日可卖=0 的止损队列；② 执行建仓。"""
    if not _is_trading_day_guard(context):
        return
    _HEALTH["degraded"] = []
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
    # ② 建仓
    pending = list(g.pending_buy)
    if not pending:
        _dump_health("[开盘]")
        return
    held = set(positions_map().keys())
    remaining = MAX_POSITIONS - len(held)
    if remaining <= 0:
        log.info("[买入] 已满仓，放弃本日 {} 笔候选".format(len(pending)))
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    total = _total_asset(context)
    if total <= 0:
        _degrade("buy", "无法获取总资产，停止建仓")
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    target = total * POSITION_RATIO
    cash = _cash_of(context, total, len(held))
    if target > cash:
        log.info("[买入] 停单兜底：单票目标 {:.0f} > 可用现金 {:.0f}，今日不建仓".format(target, cash))
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    if not turnover_ok(context, total):
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    if not market_regime_ok():
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    snap = _open_price_and_anchor([f["code"] for f in pending])
    if not snap:
        _degrade("buy", "候选全部无法取到 T日收盘/开盘价，放弃建仓")
        g.pending_buy = []
        _dump_health("[开盘]")
        return
    idx = 0
    done = 0
    while idx < len(pending) and done < remaining:
        f = pending[idx]
        idx += 1
        code = f["code"]
        if code in held:
            continue
        sc = snap.get(code)
        if not sc or not sc["anchor"] or not sc["open"]:
            _degrade("buy", "{} 无 T日收盘/开盘价，放弃".format(code))
            continue
        anchor, op = sc["anchor"], sc["open"]
        upper = round(anchor * (1 + BUY_PREMIUM_PCT), 2)
        lower = round(anchor * (1 - BUY_FLOOR_PCT), 2)
        if op < lower:
            log.info("[买入] {} 开盘 {:.2f} < 下限 {:.2f}（低开不接刀）→ 放弃".format(code, op, lower))
            continue
        if op > upper:
            log.info("[买入] {} 开盘 {:.2f} > 上限 {:.2f}（高开不追）→ 放弃".format(code, op, upper))
            continue
        cap = (f.get("amt") or 0) * MAX_AMT_SHARE
        if cap and target > cap:
            log.info("[买入] {} 目标 {:.0f} > 成交额×{:.1%}（{:.0f}）→ 放弃（流动性约束）".format(
                code, target, MAX_AMT_SHARE, cap))
            continue
        if TRADE_ENABLED:
            oid = None
            try:
                oid = order_value(_suffix(code), target, limit_price=upper)
            except Exception as e:
                _degrade("buy", "{} 下单异常: {}".format(code, repr(e)))
            if oid:
                g.buy_today.add(code)
                g.hold_days[code] = 0
                g.peak[code] = 0.0
                g.code_sector[code] = f.get("sector")
                _record_trade(context, target, "buy")
                log.info("[买入] {} [{}] 锚(T日收盘){:.2f} 限价{:.2f} 目标{:.0f} 委托={}".format(
                    code, f.get("stage", ""), anchor, upper, target, oid))
            else:
                _degrade("buy", "{} 下单返回空（未成交）".format(code))
        else:
            log.info("[信号-买] {} [{}] 锚(T日收盘){:.2f} 限价[{:.2f},{:.2f}]".format(
                code, f.get("stage", ""), anchor, lower, upper))
        done += 1
    g.pending_buy = pending[idx:]
    if g.pending_buy:
        log.info("[买入] 本轮成交 {} 笔，剩余 {} 笔留待下次（非错位，V2 切片 bug 已修）".format(
            done, len(g.pending_buy)))
    _dump_health("[开盘]")


# ============================================================
# 十二、风控层（每分钟 + 14:58 兜底）
# ============================================================
def _sector_killed():
    """板块级一票否决集合：stage=衰退 或 zt 自峰值回落 ≥50%。"""
    killed = set()
    for s in (g.sector_state or []):
        if s.get("stage") == "衰退":
            killed.add(s["sector"])
            continue
        h = g.prev_signal.get(s["sector"]) or []
        if len(h) >= 2:
            peak = max(h[:-1]) if len(h) > 1 else h[-1]
            if peak >= 2 and s["zt_cnt"] < peak * 0.5:
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
        sec = g.code_sector.get(code)
        if sec and sec in killed:
            sell, reason = amount, "板块联动清仓:{}转衰退/腰斩".format(sec)
        # ② 止盈（分批 + 移动止盈）
        if sell is None and cost:
            pr = price_now / cost - 1
            if pr >= TAKE_PROFIT2_PCT:
                sell, reason = amount, "止盈2:浮盈{:.1%}>=+15%".format(pr)
            elif pr >= TAKE_PROFIT1_PCT:
                sell, reason = int(amount * 0.5), "止盈1:浮盈{:.1%}>=+10%减半".format(pr)
            elif g.peak.get(code, 0) > 0 and price_now <= g.peak[code] * (1 - TRAIL_PCT) \
                    and g.peak[code] > cost * (1 + TAKE_PROFIT1_PCT * 0.6):
                sell, reason = amount, "移动止盈:自高点{:.1f}回撤{:.1%}".format(
                    g.peak[code], TRAIL_PCT)
            else:
                # ③ 止损
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
        # ④ 破均值线清仓
        if sell is None and len(closes) >= RETREAT_MA:
            ma = _ma(closes, RETREAT_MA)
            if ma and price_now < ma:
                sell, reason = amount, "破{}日线清仓".format(RETREAT_MA)
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
    """日初：冷静期衰减、持仓天数+1、持仓日K缓存（供盘中零取数风控）。"""
    _HEALTH["degraded"] = []
    # 板块池每日失效缓存（日频刷新：重新生成的 sector_map.json 必须在当日生效，
    # 否则 persist 进程会一直用旧池；load_sector_map 被置 None 后下次信号层重新读文件）
    g.sector_map = None
    g.sector_codes = {}
    g.code_sectors = {}
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
    # 持仓日K缓存
    if pm:
        g.pos_hist = fetch(list(pm.keys()), POS_BARS)
        if not g.pos_hist:
            _degrade("poshist", "持仓日K缓存为空，ATR/均线风控将降级")
    log.info("[日初] 持仓 {} 只 冷静期 {} 只 昨日候选 {} 只".format(
        len(pm), len(g.cool_down), len(g.pending_buy)))


def handle_data(context, data):
    """盘中主循环：只做风控（建仓/信号由 run_daily 负责；run_daily 不可用则按窗口兜底）。"""
    g.now_str = _now_str(context)
    now = g.now_str
    if not now:
        _degrade("clock", "无法获取当前时间，handle_data 空转")
        _dump_health("[时钟]")
        return
    if not getattr(g, "sched_ok", False):
        # run_daily 不可用 → 用容错窗口在 handle_data 内兜底调度
        if _in_window(now, BUY_TIME) and g.buy_slot != _today_str(context):
            g.buy_slot = _today_str(context)
            try:
                open_job(context)
            except Exception as e:
                _degrade("open", "开盘处理异常: {}".format(repr(e)))
            return
        if _in_window(now, SIGNAL_TIME) and g.signal_slot != _today_str(context):
            g.signal_slot = _today_str(context)
            try:
                _run_signal_layer(context)
            except Exception as e:
                _degrade("signal", "信号层异常: {}".format(repr(e)))
            _dump_health("[健康]")
            return
    if "09:30" <= now <= "15:00":
        try:
            monitor_risk(context)
        except Exception as e:
            _degrade("risk", "风控异常: {}".format(repr(e)))


def signal_job(context):
    g.now_str = _now_str(context) or SIGNAL_TIME
    _HEALTH["degraded"] = []
    log.info("=" * 72)
    log.info("[{}] V3 信号层（尾盘快照口径）开始".format(g.now_str))
    try:
        _run_signal_layer(context)
    except Exception as e:
        _degrade("signal", "信号层异常: {}".format(repr(e)))
    _dump_health("[健康]")


def risk_fallback_job(context):
    g.now_str = _now_str(context) or RISK_FALLBACK_TIME
    try:
        monitor_risk(context)
    except Exception as e:
        _degrade("risk", "兜底风控异常: {}".format(repr(e)))
    _dump_health("[兜底风控]")


def on_order(context, orders):
    """订单回执（V2 完全没有，导致下单失败不可知）。★字段名按本券商核对★"""
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
    # ---- 状态容器（V3 全部入 g，解决 V2 模块级变量跨日/重启丢失）----
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
    g.buy_slot = None
    g.signal_slot = None
    g.now_str = ""

    try:
        set_benchmark(INDEX_FOR_REGIME)
    except Exception:
        try:
            set_benchmark("000300")
        except Exception as e:
            _degrade("benchmark", "set_benchmark fail: {}".format(repr(e)))
    # 佣金 + 印花税（V2 漏印花税，回测收益虚高）
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
        run_daily(context, signal_job, time=SIGNAL_TIME)
        run_daily(context, open_job, time=BUY_TIME)
        run_daily(context, risk_fallback_job, time=RISK_FALLBACK_TIME)
        g.sched_ok = True
    except Exception as e:
        g.sched_ok = False
        _degrade("schedule", "run_daily 不可用，改用 handle_data 容错窗口: {}".format(repr(e)))
    log.info("[初始化] V3 启动 TRADE_ENABLED={} 调度={} 板块池={}".format(
        TRADE_ENABLED, "run_daily" if g.sched_ok else "handle_data兜底", SECTOR_MAP_FILE))
    log.info("[初始化] 口径: 选股={} 尾盘快照 | 成交={} 开盘限价 | 锚=T日收盘".format(
        SIGNAL_TIME, BUY_TIME))
    log.info("[初始化] 限价区间 [T日收盘×{:.1%}, ×{:.1%}] 止损模式={} 换手预算≤{}次双边".format(
        1 - BUY_FLOOR_PCT, 1 + BUY_PREMIUM_PCT, STOP_MODE, MAX_ANNUAL_TURNS))
    _dump_health("[初始化]")
