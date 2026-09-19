# -*- coding: utf-8 -*-
"""
热点追踪量化策略 v3.0（加固版 · 山西证券 PTrade）
=====================================================
相对 v2.0 的修复（对应体检报告编号）：

  P0-1  改用 run_daily 定时（不依赖 current_dt 字符串匹配），并打印实际时间自检
  P0-2  行情接口多签名容错 + 启动自检；候选为 0 时打 ERROR 并输出样本诊断，不再谎报「信号模式」
  P0-3  成交量单位启动自动校准（用大盘蓝筹做基准），不再靠 volume×close 盲估
  P0-4  卖出只用可卖数量 enable_amount，优先 order_target(code, 0)

  P1-1  加可买性硬约束：不追涨停/不追一字板（ALLOW_LIMIT_UP_BUY 可开）
  P1-2  数据 cutoff 启动自检：识别 get_history 是否含当日 bar，并明确告警
  P1-3  建仓按可用现金计算，留现金缓冲，保证整百股
  P1-4  默认全市场批量粗筛（不再固定步长抽样），抽样模式改为按日期轮换
  P1-5  批量取数：接口调用量从数千次降到 ~10 次量级

  P2    北交所 920 段识别、科创板/退市过滤、LOOKBACK 与 MIN_HIST 解耦、
        日志分级、当日幂等、时间止损、滑点可调

取向说明（重要）：
  每日 10:30 上午选股并买入，当日涨幅按板块分档（见 GAIN_RANGE）：
    主板 3%~4%（收窄降追高）；科创板/创业板（20cm）6%~8%；北交所默认排除。
  区间上限都低于对应涨停幅度，天然不追涨停、不追一字板。
  若你要打板，把 ALLOW_LIMIT_UP_BUY 置 True 并放宽 GAIN_RANGE 上限，
  但请先在模拟盘验证成交率。

⚠️ 实盘自动交易风险自负。TRADE_ENABLED 默认 False，请先跑信号模式观察。
"""

# ============================================================
# 一、参数配置区
# ============================================================
TRADE_ENABLED = False          # True=自动下单；False=信号模式（只输出热点榜）
SIGNAL_TIME = "10:30"          # 每日选股/买入执行时间（handle_data 触发，上午买入）

# ---- 扫描方式 ----
SCAN_MODE = "FULL"             # FULL=全市场批量粗筛（推荐）；SAMPLE=抽样（慢环境兜底）
SAMPLE_RATIO = 0.5             # SAMPLE 模式下的抽样比例
SAMPLE_ROTATE = True           # 抽样是否按日期轮换（避免同一批票永远扫不到）
LOOKBACK_DETAIL = 90           # 细评回看天数（> MIN_HIST_BARS，留出停牌余量）
DETAIL_POOL = 40               # 粗筛后进入细评的候选数
BATCH_SIZE = 300               # 每批批量取数的标的数量

# ---- 标的过滤 ----
MIN_HIST_BARS = 60             # 上市历史最少 K 线数
MIN_AMOUNT = 3e8               # 当日成交额下限（元）
REQUIRE_NO_ST = True           # 剔除 ST / *ST / 退市整理
EXCLUDE_KCB = False            # 不剔除科创板（本版科创板有专属涨幅档，需开通权限）
ALLOW_BOARDS = ("SS", "SZ")    # 允许交易的交易所后缀；北交所("BJ")默认排除（见 _gain_range 返回 None + 此过滤）

# ---- 选股（按板块分档的当日涨幅区间）----
# 当日涨幅区间（收窄上限=降追高）：主板 3%~4%；科创板/创业板（20cm）6%~8%。北交所默认排除。
GAIN_RANGE = {
    "main": (3.0, 4.0),        # 主板（沪 60 / 深 00）：收窄至 3%~4%，降低追高被埋
    "kcb":  (6.0, 8.0),        # 科创板 688：6%~8%
    "cyb":  (6.0, 8.0),        # 创业板 300/301（与科创板同属 20cm，对齐 6%~8%）
}
ALLOW_LIMIT_UP_BUY = False     # True=允许买入已封涨停的票（高风险，成交率低）
LIMIT_UP_BUFFER = 0.005        # 涨停判定缓冲：现价 >= 涨停价*(1-缓冲) 视为封板
MIN_VOL_RATIO = 1.5            # 量比下限（放量确认；v3.1 由 1.2 收紧到 1.5，过滤弱放量假突破）
REQUIRE_ABOVE_MA20 = True      # 必须站上 20 日线

# ---- 入场收紧（提胜率：宁可少做也不做错；v3.1 新增，针对回测 17.86% 低胜率）----
REQUIRE_ABOVE_MA60 = True     # 必须站上 60 日线（中期趋势确认，过滤弱势反弹/一日游）
MA_SHAPE_MIN = 2              # 均线多头形态门槛：shape>=2 即站上 MA10+MA20（设 3=全多头更严）
INTRADAY_PULLBACK_MAX = 0.04  # 日内回撤上限：当前价距日内最高回撤 >4% 视为冲高回落，剔除（避免追尖顶）

# ---- 仓位与风控 ----
MAX_POSITIONS = 5              # 最大同时持仓数
POSITION_VALUE_RATIO = 0.18    # 单票目标市值 / 总资产
CASH_BUFFER = 0.10             # 保留现金比例（1 - 此为可投上限）
# ---- 亏损侧硬止损（入场价锚定，封顶单票最大亏损，治「买高被埋」）----
HARD_STOP_PCT = {"main": 0.04, "kcb": 0.07, "cyb": 0.07}  # 硬止损（分板，入场价锚定）：主板浮亏<=-4% 清仓；科创板/创业板<=-7%（20cm 波动大，放宽到 7% 抗噪声）
STOP_LOSS_PCT = HARD_STOP_PCT # 兼容别名（旧引用保留，实际生效为 HARD_STOP_PCT，现为分板 dict）

# ---- 分批止盈（分板块：盈利减半 + 峰值回撤减半，单票最多减到 1/4）----
# 盈利减半阈值（分板块）：主板 +8% / 科创板 +12% / 创业板 +12%（20cm 大票让多跑）
TP_HALF_PCT = {"main": 0.08, "kcb": 0.12, "cyb": 0.12}
# 峰值回撤减半阈值（分板块）：从持仓峰值价回落超此比例即减半。
#   主板取 5%（主板日内常波动 2~4%，5% 抗噪声且不会过早下车）；
#   科创板/创业板取 8%（20cm 波动大，5% 易被正常抖动误减半，放宽到 8% 抗噪声）。
HALF_DRAWDOWN = {"main": 0.05, "kcb": 0.08, "cyb": 0.08}
TP_FULL_PCT = 0.15             # 浮盈达到 +15%：清仓（盈利减半后的终点兜底）
TP_MA = 5                      # 兼容保留
EXIT_MA = 3                    # 已弃用：亏损侧不再用破线出场，改 HARD_STOP_PCT 入场价锚定硬止损（封顶-4%）。保留供日后按需恢复 MA 出场。
RETREAT_MA = 20                # 跌破 20 日线 = 退潮清仓（更保守兜底）
TRAIL_PCT = {"main": 0.08, "kcb": 0.12, "cyb": 0.12}  # 峰值回撤清仓（分板，与 HALF_DRAWDOWN 形成阶梯：主板 5%→8%，科创/创业 8%→12%）
TRAIL_GUARD = {"main": 0.03, "kcb": 0.05, "cyb": 0.05}  # 护栏（分板）：浮盈达到该比例后才启动「峰值回撤」跟踪（减半/清仓）；20cm 板放宽到 +5%，避免 10:30 买入即高位被噪声误触发
MAX_HOLD_DAYS = 5              # 时间止损（亏损票）：持有超过 N 个交易日无条件退出

# ---- 大盘择时总闸（纯多头动量必须有"总闸"，弱市/空头不追涨）----
MARKET_TIMING = True           # True=开启大盘择时：沪深300 跌破 MA20 则暂停建仓
MKT_INDEX = "000300.SS"        # 择时参考指数（沪深300；看成长风格可换 399006.SZ 创业板指）
MKT_MA = 20                    # 择时均线周期
MKT_EXIT_WHEN_BEAR = False     # True=大盘破 MA20 时清空全部持仓（系统性撤退；默认关，避免盘中均线抖动误清）

# ---- 保本止损（减半后启用：把止损线上移到成本价，锁定已落袋利润）----
# 触发逻辑：某票「+10% 减半」后，剩余半仓若回落到保本价（≈ 成本价）以下即清仓，
# 把整体锁定在「不亏」状态（已落袋的一半利润已安全）。未减半的票不触发保本止损，
# 继续走固定 -5% 止损。
BREAKEVEN_STOP = True         # True=减半后启用保本止损；False=不启用（仍走 -5% 止损）
BREAKEVEN_BUF = 0.0           # 保本价相对成本价的缓冲（0=严格等于成本价；>0 允许略低于成本，抗毛刺）


# ---- 收益优化（提升收益的两道开关，均默认可关）----
# 1) 仓位随热点强度分档：强信号给更高权重，集中度可控（单票上限 MAX_SINGLE_RATIO）
STRENGTH_WEIGHT = True        # True=按强度分档分配；False=等权（原逻辑）
STRENGTH_EXP = 1.6            # 强度权重指数（越大越集中于最强票）
MAX_SINGLE_RATIO = 0.30       # 单票上限（占总资产比例），防过度集中
# 2) 10:30 分时回踩过滤：只做「回踩不破开盘价」（cur >= 当日开盘价才买，动量未转弱）
BUY_PULLBACK_FILTER = True    # True=开启分时回踩过滤
PULLBACK_OPEN_BREAK = True    # True=要求 cur>=open（回踩不破开盘价）；False=关闭该条件


# ---- 成本假设（回测用）----
SLIPPAGE = 0.003               # 滑点（v2.0 用 0.002，追高品种偏乐观，这里加压）

# ---- 成交量单位校准基准（大盘蓝筹，日成交额通常在 10 亿量级）----
CALIB_CODES = ("600519.SS", "601318.SS", "600036.SS", "000001.SZ")


# ============================================================
# 二、通用工具
# ============================================================
def _suffix(code):
    """6 位代码 -> PTrade 代码。补齐北交所 43/83/87/88/92 段（v2.0 漏了 920）。"""
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
        return "SS"          # 科创板，单独用 EXCLUDE_KCB 控制
    if c.startswith(("60", "51", "58", "11")):
        return "SS"
    return "SZ"


def _is_kcb(code):
    return _pure(code).startswith("688")


def _board_key(code):
    """返回持仓减半阈值字典的索引键：科创板 kcb / 创业板 cyb / 其余 main。"""
    c = _pure(code)
    if c.startswith("688"):
        return "kcb"
    if c.startswith(("300", "301")):
        return "cyb"
    return "main"


def _limit_pct(code, name):
    """涨跌停幅度：ST 5% / 主板 10% / 创业板科创板 20% / 北交所 30%"""
    if "ST" in str(name).upper() or "退" in str(name):
        return 0.05
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


def _has(name):
    return globals().get(name) is not None


# ============================================================
# 三、行情取数层（多签名容错 + 批量）
# ============================================================
def _to_panel(raw, fields):
    """
    把各种返回形态归一为 {code: {field: [values...], 'date': [...]}}
    支持：dict[code]=DataFrame / dict[code]=dict[field]=list / DataFrame(单票) / dict[field]=list
    """
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
    # dict[code] = ...
    if isinstance(raw, dict):
        # 先判断是不是「单票的 dict[field]=list」
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
    # 单票 DataFrame / list
    if isinstance(raw, (list, tuple)):
        return out
    _from_df("__single__", raw)
    return out


def _fetch_panel(codes, count, fields, log_tag="", quiet=False, freq="1d"):
    """
    批量取数，多签名容错。返回 {code: panel}。
    freq 为频率（'1d' 日线 / '1m' 分钟线）。
    quiet=True 时不打印取数失败（用于可选字段的静默尝试）。
    尝试顺序：
      1) get_history(count, freq, field_list, security_list)
      2) get_history(count, freq, 'close', security_list) 逐字段
      3) get_price(codes, count=count, frequency=freq, fields=[...])
      4) get_price(code, None, None, freq, fields, count=count) 逐票
    """
    codes = list(codes)
    if not codes or count <= 0:
        return {}
    err = []

    # 1) list field
    if _has("get_history"):
        try:
            raw = get_history(count, freq, list(fields), codes)
            p = _to_panel(raw, fields)
            p.pop("__single__", None)
            if p:
                return p
        except Exception as e:
            err.append("sig1:" + repr(e))
        # 2) 逐字段 str
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

    # 3) get_price 批量
    if _has("get_price"):
        try:
            raw = get_price(codes, None, None, freq, list(fields), count=count)
            p = _to_panel(raw, fields)
            p.pop("__single__", None)
            if p:
                return p
        except Exception as e:
            err.append("sig3:" + repr(e))
        # 4) get_price 逐票（最慢但绝不漏票的兜底）
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
    """
    从 handle_data 的 data 对象取某只股票「当日实时价」。
    get_history 系列在回测里只能拿到昨收，当日价必须走 data 参数（当前 bar）。
    多签名尝试，取不到返回 None。
    """
    if data is None:
        return None
    # 1) data.current(code, field) / data.get(code, field)
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
    # 2) data[code] -> .price/.close（对象或 dict）
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
    """诊断 handle_data 的 data 对象有哪些可用接口（仅首日打印一次）。"""
    if data is None:
        log.info("[口径] handle_data 的 data 参数为 None（该平台可能不支持 data 取当日价）")
        return
    try:
        attrs = [a for a in dir(data) if not a.startswith("_")][:30]
        log.info("[口径] data 对象类型={} 可用方法={}".format(type(data).__name__, attrs))
    except Exception as e:
        log.info("[口径] data 对象诊断失败: {}".format(repr(e)))


# ============================================================
# 四、启动自检（这是 v3.0 防「静默空转」的核心）
# ============================================================
DIAG = {
    "vol_scale": 1.0,      # 成交量 -> 股 的换算系数
    "has_today_bar": None, # get_history 是否包含当日 bar
    "api": {},
}


def _diag_api():
    names = ("get_history", "get_price", "get_Ashares", "get_all_stocks",
             "get_positions", "get_position", "order", "order_value",
             "order_target", "order_target_value", "run_daily",
             "get_stock_name", "get_total_assets", "get_datetime")
    for n in names:
        DIAG["api"][n] = _has(n)
    missing = [n for n in ("get_Ashares", "get_history", "order") if not DIAG["api"].get(n)]
    if missing:
        log.error("[自检] 关键接口缺失: {} —— 策略无法工作，请核对 PTrade 版本".format(missing))
    else:
        log.info("[自检] 关键接口齐全")


def _diag_vol_scale():
    """用大盘蓝筹校准成交量单位。优先用真实成交额 money，取不到再用 volume*close。"""
    panel = _fetch_panel(list(CALIB_CODES), 1, ["close", "volume"], "成交量校准")
    mp = _fetch_panel(list(CALIB_CODES), 1, ["money"], "成交量校准", quiet=True)
    est = []
    for c, p in panel.items():
        try:
            mv = (mp.get(c) or {}).get("money") or []
            if mv and mv[-1]:
                est.append(float(mv[-1]))          # 真实成交额
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
    """检测日线是否含当日 bar，以及分钟线是否可得（决定「当日涨幅」口径是否生效）。"""
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

    if has_today:
        log.info("[自检] 日线已含当日 bar：涨幅按「当日涨幅」计算")
    elif has_minute:
        log.info("[自检] 日线不含当日 bar，但分钟线可得 → 涨幅按「当日实时价/昨收」计算（当日涨幅口径已生效）")
    else:
        log.error("[自检] 日线不含当日 bar 且分钟线不可得 → 涨幅实际是「昨日涨幅」，"
                  "与你要的「当日涨幅」不符；请确认平台是否支持 1m 分钟数据")


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


# ============================================================
# 五、股票池
# ============================================================
_POOL_CACHE = None

# 板块共振所需的行业映射与当日板块强度（首个交易日构建一次，之后每日复用 snap 聚合）
INDUSTRY_OF = {}               # {code: 申万一级行业名}（个股→行业映射，缓存）
SECTOR_STRENGTH = {}          # {行业名: 当日平均涨幅(%)}
SECTOR_STRONG = set()         # 强势行业集合（排名前 SECTOR_TOP_N 且涨幅达门槛）
SECTOR_READY = False          # 行业映射是否构建成功（失败则板块共振降级关闭）
_INDUSTRY_BUILT = False       # 行业映射仅构建一次的标志


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
# 五·五、板块共振（行业强度过滤）
# ============================================================
def _parse_industry(r):
    """兼容多平台 get_industry 返回值，提取申万一级行业名。"""
    if not r:
        return None
    if isinstance(r, str):
        return r.strip() or None
    if isinstance(r, dict):
        # 嵌套形态：{'sw_l1': {'industry_name': '电子', 'industry_code': '801080'}}
        for key in ("sw_l1", "sw_l2", "sw_l3", "industry", "jq_l1"):
            v = r.get(key)
            if isinstance(v, dict):
                name = v.get("industry_name") or v.get("name")
                if name:
                    return str(name)
        # 平铺形态：{'industry_name': '电子', 'industry_code': '801080'}
        name = r.get("industry_name") or r.get("name") or r.get("hy")
        if name:
            return str(name)
    return None


def _build_industry_map(context):
    """首个交易日构建个股→申万一级行业映射并缓存；平台无 get_industry 时降级关闭。"""
    global INDUSTRY_OF, SECTOR_READY, _INDUSTRY_BUILT
    if _INDUSTRY_BUILT:
        return
    _INDUSTRY_BUILT = True
    if not SECTOR_CONFIRM:
        return
    if not _has("get_industry"):
        log.error("[板块] 平台无 get_industry，板块共振已降级关闭（不影响其它逻辑）")
        SECTOR_READY = False
        return
    pool = _get_market_pool()
    if not pool:
        log.error("[板块] 股票池为空，行业映射跳过，板块共振降级关闭")
        SECTOR_READY = False
        return
    ok = 0
    miss = 0
    for c in pool:
        ind = None
        for arg in (c, _pure(c)):
            try:
                r = get_industry(arg, type="sw_l1")
            except Exception:
                r = None
            ind = _parse_industry(r)
            if ind:
                break
        if ind:
            INDUSTRY_OF[c] = ind
            ok += 1
        else:
            miss += 1
    SECTOR_READY = (ok > 0)
    log.info("[板块] 行业映射完成：成功 {} 只 / 缺失 {} 只；板块共振{}".format(
        ok, miss, "启用" if SECTOR_READY else "降级关闭"))


def _compute_sector_strength(snap):
    """用全市场当日涨幅(snap)按行业聚合，算出强势板块集合。"""
    global SECTOR_STRENGTH, SECTOR_STRONG
    SECTOR_STRENGTH = {}
    SECTOR_STRONG = set()
    if not SECTOR_CONFIRM or not SECTOR_READY:
        return
    buckets = {}
    for c, s in snap.items():
        ind = INDUSTRY_OF.get(c)
        if not ind:
            continue
        pct = s.get("pct")
        if pct is None:
            continue
        buckets.setdefault(ind, []).append(pct)
    for ind, ps in buckets.items():
        if len(ps) < SECTOR_MIN_STOCKS:
            continue
        SECTOR_STRENGTH[ind] = sum(ps) / len(ps)
    if not SECTOR_STRENGTH:
        log.info("[板块] 当日无足够样本计算行业强度，板块共振本次不生效")
        return
    ranked = sorted(SECTOR_STRENGTH.items(), key=lambda kv: -kv[1])
    for i, (ind, avg) in enumerate(ranked):
        if i < SECTOR_TOP_N and avg > SECTOR_MIN_RISE:
            SECTOR_STRONG.add(ind)
    log.info("[板块] 行业强度排名（前{}）: {}".format(
        SECTOR_TOP_N,
        "；".join("{} {:.2f}%".format(ind, avg) for ind, avg in ranked[:SECTOR_TOP_N])))


# ============================================================
# 六、名称 / ST 过滤
# ============================================================
_NAME_CACHE = {}
_ST_WARNED = False


def _stock_name(code):
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
                    # 部分平台返回 {code: name} 形态，取 value
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
        global _ST_WARNED
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
# 七、主流程：粗筛 -> 细评 -> 排序
# ============================================================
def scan_market(context, data=None):
    pool = _get_market_pool()
    if not pool:
        log.error("[扫描] 股票池为空，本轮放弃（请查看上方接口自检）")
        return []

    # 抽样：按日期轮换 offset，避免固定批次（v2.0 的 P1-4）
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

    # ---- Stage 1：批量粗筛（当日涨幅 + 成交额）----
    # 当日涨幅 = 当日 10:30 实时价（data 参数）/ 昨收 - 1。
    # 当日价优先用「price 现价」字段，次选分钟线 close，都取不到回退「昨日涨幅」。
    snap = {}
    n_batch = 0
    n_cur_ok = 0
    n_cur_miss = 0
    _sample_done = False
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        tag = "粗筛批次{}".format(i // BATCH_SIZE + 1)
        p = _fetch_panel(batch, 2, ["close", "price", "volume"], tag, freq="1d")
        mp = _fetch_panel(batch, 2, ["money"], tag, quiet=True, freq="1d")
        m1 = _fetch_panel(batch, 1, ["close"], tag, quiet=True, freq="1m")
        n_batch += 1
        for c, v in p.items():
            cl = v.get("close") or []
            pl = v.get("price") or []
            if len(cl) < 2 or not cl[-2]:
                continue
            prev_close = cl[-1]      # 日线不含当日，最后一根 = 昨收
            prev2_close = cl[-2]     # 前日收盘
            vol = (v.get("volume") or [0, 0])[-1] or 0
            mv = (mp.get(c) or {}).get("money") or []
            amt = float(mv[-1]) if mv and mv[-1] else 0.0
            if not amt:
                amt = float(vol) * DIAG["vol_scale"] * prev_close
            # 当日价：优先 data 参数（当前 bar），次选 price 字段，再次分钟线
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
            m1c = (m1.get(c) or {})
            mcl = m1c.get("close") or []
            snap[c] = {"pct": pct, "amt": amt, "cur": cur,
                       "prev_close": prev_close, "prev2_close": prev2_close}
    log.info("[扫描] 粗筛完成：{} 只，批量请求 {} 次（当日价{}只 / 回退昨日{}只）".format(
        len(snap), n_batch, n_cur_ok, n_cur_miss))
    if n_cur_miss and not n_cur_ok:
        log.error("[扫描] 当日价取不到（price 字段与分钟线均=昨收），已回退「昨日涨幅」；"
                  "请查看上方 [口径] 样本日志确认字段语义")

    if not snap:
        log.error("[扫描] 粗筛结果为空！通常是取数接口不兼容或成交额单位错误，"
                  "请向上翻查看自检日志")
        return []

    # 板块共振：用全市场当日涨幅(snap)计算行业强度，确定强势板块集合（供 _assess 过滤）
    _compute_sector_strength(snap)

    # 粗筛条件：按板块涨幅区间 + 成交额
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
    log.info("[扫描] 进入细评 {} 只".format(len(detail_codes)))

    # ---- Stage 2：细评（逐票取长周期 K 线 + 当日分时区间）----
    cands = []
    for i in range(0, len(detail_codes), 20):
        batch = detail_codes[i:i + 20]
        p = _fetch_panel(batch, LOOKBACK_DETAIL,
                         ["close", "high", "low", "volume"], "细评批次")
        intraday = _intraday_ranges(batch)   # 当日开盘/最高/最低（回踩过滤用）
        for c in batch:
            v = p.get(c)
            if not v:
                continue
            a = _assess(c, v, snap.get(c, {}), intraday.get(c))
            if a:
                cands.append(a)

    cands.sort(key=lambda x: x["score"], reverse=True)
    top = cands[:MAX_POSITIONS * 2]
    log.info("=" * 60)
    log.info("[热点榜] 今日候选 Top{}（强度分|涨幅|连板|量比|站上20日线）:".format(len(top)))
    for a in top:
        log.info("  {} {} 分{} +{}% 连板{} 量比{} MA20:{}".format(
            a["code"], a["name"], a["score"], a["pct"], a["lianban"],
            a["vol_ratio"], "是" if a["above20"] else "否"))
    if not top:
        log.error("[扫描] 细评后无候选（全部被可买性/形态过滤），今日不建仓")
    return top


def _pass_pullback(cur, o, h, lo):
    """10:30 分时回踩过滤（纯函数，便于回归）。返回 True=可买。

    只保留「回踩不破开盘价」：10:30 价仍 >= 当日开盘价，说明日内动量未转弱。
    （「买在日内绝对高点」判定已弃用——单根 1m bar 的 high 是最后一分钟最高价，
     而非当日最高，会系统性误杀；当日开盘价用聚合分钟线取，可靠。）
    无当日价/无开盘价数据时退化为「不过滤」，保证不静默丢信号。
    """
    if not BUY_PULLBACK_FILTER:
        return True
    if not cur:
        return True
    if PULLBACK_OPEN_BREAK and o is not None and cur < o:
        return False
    return True


def _intraday_ranges(codes):
    """聚合当日分钟线，返回 {code: (open, high, low)} 的当日值。

    回测里 1m 可得当日数据（已实测），取多根聚合出「当日开盘/最高/最低」。
    取不到（接口不支持/无分钟线）返回空 dict，调用方退化为「不过滤」。
    """
    out = {}
    if not codes:
        return out
    try:
        m = _fetch_panel(list(codes), 330, ["open", "high", "low", "close"],
                         "分时区间", quiet=True, freq="1m")
        for c in codes:
            d = m.get(c) or {}
            o = d.get("open") or []
            h = d.get("high") or []
            l = d.get("low") or []
            if not h:
                continue
            out[c] = (float(o[0]) if o else None,
                      float(max(h)), float(min(l)) if l else None)
    except Exception:
        pass
    return out


def _assess(code, v, snap, intraday=None):
    closes = [x for x in (v.get("close") or []) if x]   # 日线收盘（不含当日）
    vols = v.get("volume") or []
    if len(closes) < MIN_HIST_BARS:
        return None

    rng = _gain_range(code)
    if rng is None:
        return None
    lo, hi = rng

    cur = snap.get("cur")                 # 当日 10:30 实时价（data 参数/分钟线）
    prev_close = snap.get("prev_close") or (closes[-1] if closes else None)
    if not prev_close:
        return None
    if not cur:
        cur = closes[-1]                  # 分钟价缺失时退回昨收（退化为昨日口径）
    if not cur:
        return None

    name = _stock_name(code)
    if _is_bad_name(code):
        return None

    pct = (cur / prev_close - 1) * 100.0   # 当日涨幅
    if pct < lo or pct < 0 or pct > hi:
        return None

    # ---- 分时回踩过滤：回踩不破开盘价才买 ----
    o = (intraday or (None, None, None))[0]
    if not _pass_pullback(cur, o, None, None):
        _of = "{:.2f}".format(o) if o is not None else "NA"
        log.info("[回踩] {} 跳过（cur={:.2f} open={}：跌破开盘价，动量转弱）".format(
            code, cur, _of))
        return None

    # ---- 可买性：涨停判定用昨收基准 + 当日价（保险，区间上限已低于涨停）----
    lim = _limit_pct(code, name)
    limit_up = round(prev_close * (1 + lim), 2)
    sealed = cur >= limit_up * (1 - LIMIT_UP_BUFFER)
    if sealed and not ALLOW_LIMIT_UP_BUY:
        return None

    # 量能（日线 volume 不含当日，此处为近似：最近一日量/5日均量）
    vs = [x for x in vols if x]
    ma5v = sum(vs[-6:-1]) / 5.0 if len(vs) >= 6 and sum(vs[-6:-1]) > 0 else 0.0
    vol_ratio = (vs[-1] / ma5v) if ma5v else 0.0
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

    # 均线：日线收盘 + 当日价拼接，让 MA 含当日
    full = closes + [cur]
    ma10, ma20, ma60 = _ma(full, 10), _ma(full, 20), _ma(full, 60)
    above20 = bool(ma20 and cur > ma20)
    above60 = bool(ma60 and cur > ma60)
    if REQUIRE_ABOVE_MA20 and not above20:
        return None
    shape = (1 if (ma10 and cur > ma10) else 0) + (2 if above20 else 0) + (3 if above60 else 0)

    # ---- 入场收紧①：中期趋势确认（站上 60 日线）----
    if REQUIRE_ABOVE_MA60 and not above60:
        log.info("[趋势] {} 跳过（未站上60日线，中期趋势弱）".format(code))
        return None
    # ---- 入场收紧②：均线多头形态门槛 ----
    if shape < MA_SHAPE_MIN:
        log.info("[形态] {} 跳过（均线多头 shape={} < {}）".format(code, shape, MA_SHAPE_MIN))
        return None
    # ---- 入场收紧③：日内回撤过滤（避免追尖顶/冲高回落）----
    # intraday = (open, high, low)；当前价距日内最高回撤超阈值即视为冲高回落、动量已衰
    hi_today = (intraday or (None, None, None))[1] if intraday else None
    if hi_today and cur and INTRADAY_PULLBACK_MAX > 0:
        if cur < hi_today * (1 - INTRADAY_PULLBACK_MAX):
            log.info("[回撤] {} 跳过（cur={:.2f} 日内最高={:.2f} 回撤{:.1%}，冲高回落）".format(
                code, cur, hi_today, 1 - cur / hi_today))
            return None

    # ---- 板块共振：个股所属申万一级行业当日须为强势板块（行业集体走强才视为板块性机会）----
    # 守卫 SECTOR_STRONG 非空：若当日未算出任何强板块（样本不足等），不强制剔除，降级为不共振过滤
    if SECTOR_CONFIRM and SECTOR_READY and SECTOR_STRONG:
        ind = INDUSTRY_OF.get(code)
        if not ind:
            log.info("[板块] {} 跳过（未取到行业映射，无法共振）".format(code))
            return None
        if ind not in SECTOR_STRONG:
            log.info("[板块] {} 跳过（行业『{}』非强势板块，不共振）".format(code, ind))
            return None

    score = pct + lb * 6.0 + min(vol_ratio, 3.0) * 8.0 + shape * 1.5
    return {"code": code, "name": name, "pct": round(pct, 2), "lianban": lb,
            "vol_ratio": round(vol_ratio, 2), "above20": above20,
            "above60": above60, "score": round(score, 2), "price": cur}


# ============================================================
# 八、持仓与风控
# ============================================================
# 持仓对象字段名候选（不同券商/引擎版本命名不一，含驼峰命名）
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
    """从持仓对象取字段，按优先级依次尝试多个字段名。"""
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
    """打印持仓对象结构，用于诊断字段名不匹配。"""
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
    """从 get_positions / portfolio.positions 的返回值解析 {规范代码: 持仓对象}。"""
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
    """
    读取持仓快照，返回 {规范代码: 持仓对象}。
    多路兜底：get_positions() -> portfolio.positions/long_positions
             -> base_portfolio.positions -> base_portfolio.stock_account.positions
             -> get_position()。
    """
    out = {}

    # 1) get_positions()
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

    # 2) portfolio.positions / long_positions
    for attr in ("positions", "long_positions"):
        pp = getattr(pf, attr, None)
        if pp:
            out = _parse_positions(pp)
            if out:
                log.info("[持仓] portfolio.{} 读到 {} 只".format(attr, len(out)))
                return out

    # 3) base_portfolio 及其子账户
    bp = getattr(pf, "base_portfolio", None)
    if bp is not None:
        for attr in ("positions", "long_positions"):
            pp = getattr(bp, attr, None)
            if pp:
                out = _parse_positions(pp)
                if out:
                    log.info("[持仓] base_portfolio.{} 读到 {} 只".format(attr, len(out)))
                    return out
        # 子账户（stock_account / accounts）
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

    # 4) get_position() 单只
    if _has("get_position"):
        try:
            p = get_position()
            code = _pos_field(p, _CODE_FIELDS) if not isinstance(p, (str, int, float)) else None
            if code:
                out[_suffix(_pure(str(code)))] = p
        except Exception as e:
            log.error("[持仓] get_position 回退异常: {}".format(repr(e)))

    if not out:
        log.info("[持仓] 持仓为空。注意：TRADE_ENABLED=False 信号模式不真正下单，"
                 "持仓为空属正常；开 True 买入后才能读到持仓并触发止损止盈。")
    return out


def _sell_all(code, px, reason):
    """清仓：只用可卖数量，优先 order_target（P0-4 修复）"""
    enable = _to_int(_pos_field(px, _ENABLE_FIELDS))
    if enable <= 0:
        log.error("[卖出失败] {} 可卖数量为 {}（T+1 未交收或已挂单），本次{}指令无法执行，"
                  "风险敞口顺延至下一交易日".format(code, enable, reason))
        return False
    if not TRADE_ENABLED:
        log.info("[信号] 应清仓 {} —— {}".format(code, reason))
        return True
    try:
        if _has("order_target"):
            order_target(code, 0)
        else:
            order(code, -enable)
        log.info("[卖出] {} 数量{} —— {}".format(code, enable, reason))
        return True
    except Exception as e:
        log.error("[卖出异常] {} : {}".format(code, repr(e)))
        return False


def _sell_half(code, px, reason):
    """减半：卖出可卖量（enable_amount）的一半，只触发一次（halved 标记在 monitor_risk 里维护）。

    - 用 enable_amount 而非 total amount，规避 T+1 未交收导致废单（P0-4 同源约束）。
    - 优先 order(code, -qty)；平台无 order 时回退 order_target(剩余股数)。
    """
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
        return True
    try:
        if _has("order"):
            order(code, -qty)
        elif _has("order_target"):
            cur = _to_int(_pos_field(px, _AMOUNT_FIELDS))
            order_target(code, max(0, cur - qty))
        log.info("[卖出] {} 减半卖{}股 —— {}".format(code, qty, reason))
        return True
    except Exception as e:
        log.error("[卖出异常] {} : {}".format(code, repr(e)))
        return False


def monitor_risk(context, data=None):
    """逐票风控：分批止盈 + 硬止损(-4%封顶) + 峰值回撤/破20日线兜底 + 时间止损。

    同一根 bar 内按以下优先级判定（命中即处理下一票）：
      1) 硬止损（入场价锚定，分板）：浮亏 <= -HARD_STOP_PCT[board]（主板-4%/科创·创业-7%）→ 清仓（封顶单票最大亏损，
         替代原「破3日线」/宽松-5%止损，治「买高被埋」大亏）
      2) 持仓峰值回落 > TRAIL_PCT[board]（主板8%/科创·创业12%）→ 清仓（峰值回撤跟踪止盈，让利润奔跑+保护）
      3) 破 20 日线（RETREAT_MA）      → 清仓（更保守兜底，趋势彻底走坏）
      4) 保本止损（仅已减半票）：cur <= 保本价 → 清仓（锁定已落袋利润）
      5) 时间止损（亏损票）：持有 >= MAX_HOLD_DAYS 天 → 清仓
      6) 浮盈 >= +15%（TP_FULL_PCT）   → 清仓（盈利减半后的终点兜底）
      7) 峰值回撤减半（分板块 HALF_DRAWDOWN）：从峰值回落超阈值 → 减半（最多到 1/4，
         首减半写入 context.breakeven[code] 保本基准）
      8) 盈利减半（分板块 TP_HALF_PCT）：主板 +8% / 科创板·创业板 +12% 且未减半过 → 减半
         （首减半写入 context.breakeven[code] 保本基准）
      注：减半最多两次（全仓→半仓→1/4），用 context.halved / context.quartered 双重标记防重复；
          1/4 之后只走 6) +15% 全清 / 2) 8% 回撤全清 / 4) 保本止损。
    """
    pm = positions_map(context)
    # 用上一交易日已交收的真实持仓初始化当日 live_held，再随本周期内卖出递减
    live_held = set(pm.keys())
    context.live_held = live_held
    peak = getattr(context, "peak", {})
    context.peak = peak
    if not pm:
        log.info("[风控] 当前无持仓")
        return
    entry = getattr(context, "entry_date", {})
    halved = getattr(context, "halved", {})
    context.halved = halved
    quartered = getattr(context, "quartered", {})
    context.quartered = quartered
    breakeven = getattr(context, "breakeven", {})
    context.breakeven = breakeven
    today = _context_date(context)
    need_bars = max(EXIT_MA, RETREAT_MA) + 5

    def _clear(code):
        live_held.discard(code)
        peak.pop(code, None)
        entry.pop(code, None)
        halved.pop(code, None)
        quartered.pop(code, None)
        breakeven.pop(code, None)

    for code, px in pm.items():
        amount = _to_int(_pos_field(px, _AMOUNT_FIELDS))
        cost = _pos_field(px, _COST_FIELDS) or 0
        if amount <= 0:
            continue
        rows_p = _fetch_panel([code], need_bars, ["close"], "风控取数")
        closes = (rows_p.get(code) or {}).get("close") or []
        closes = [x for x in closes if x]
        if not closes:
            log.info("[风控] {} 无有效K线，跳过".format(code))
            continue

        # 当日价：优先 data 实时价，回退昨收（get_history 不含当日 bar）
        cur = _current_price(data, code)
        if cur is None:
            cur = closes[-1]
        rt = (cur / float(cost) - 1) if cost else 0.0
        ma20 = _ma(closes, RETREAT_MA) if len(closes) >= RETREAT_MA else None
        d0 = entry.get(code)
        held_days = _days_between(d0, today) if (d0 and today) else 0
        board = _board_key(code)        # 分板块减半阈值索引：main / kcb / cyb

        # 更新持仓峰值（用于峰值回撤跟踪止盈）
        if cur:
            peak[code] = max(peak.get(code, cur), cur)

        # 1) 硬止损（入场价锚定，分板）：浮亏封顶 -HARD_STOP_PCT[board]，治「买高被埋」大亏
        hard = HARD_STOP_PCT.get(board, 0.04) if isinstance(HARD_STOP_PCT, dict) else HARD_STOP_PCT
        if hard > 0 and rt <= -hard:
            if _sell_all(code, px, "硬止损 浮亏{:.1%} 封顶-{}%".format(rt, int(hard * 100))):
                _clear(code)
            continue
        # 1b) 峰值回撤跟踪止盈：从高点回落超 TRAIL_PCT[board] → 清仓（浮盈需先达 TRAIL_GUARD[board] 才启动）
        trail = TRAIL_PCT.get(board, 0.08) if isinstance(TRAIL_PCT, dict) else TRAIL_PCT
        guard = TRAIL_GUARD.get(board, 0.03) if isinstance(TRAIL_GUARD, dict) else TRAIL_GUARD
        if trail > 0 and peak.get(code) and rt >= guard and cur <= peak[code] * (1 - trail):
            if _sell_all(code, px, "峰值回撤{:.0%} 浮盈{:.1%}".format(trail, rt)):
                _clear(code)
            continue
        # 2) 破 20 日线 → 清仓（更保守兜底）
        if ma20 and cur < ma20:
            if _sell_all(code, px, "退潮 破{}日线 浮盈{:.1%}".format(RETREAT_MA, rt)):
                _clear(code)
            continue
        # 3) 保本止损（仅已减半的票）：回落到保本价以下 → 清仓，锁定已落袋利润
        if BREAKEVEN_STOP and halved.get(code) and code in breakeven and cur <= breakeven[code]:
            if _sell_all(code, px, "保本止损 破保本价{:.2f} 浮盈{:.1%}".format(breakeven[code], rt)):
                _clear(code)
            continue
        # 4) 止损已由 1) 硬止损(-HARD_STOP_PCT)统一处理，此处不再单独判定
        # 5) 时间止损（亏损票）：持有 >= MAX_HOLD_DAYS 天 → 清仓
        if held_days >= 1 and rt <= 0 and MAX_HOLD_DAYS > 0 and held_days >= MAX_HOLD_DAYS:
            if _sell_all(code, px, "时间止损 亏损持仓{}天".format(MAX_HOLD_DAYS)):
                _clear(code)
            continue
        # 6) +15% 清仓（盈利减半后的终点兜底）
        if rt >= TP_FULL_PCT:
            if _sell_all(code, px, "止盈 浮盈{:.1%} 触+{}%清仓".format(rt, int(TP_FULL_PCT * 100))):
                _clear(code)
            continue
        # 7) 峰值回撤减半（分板块）：从持仓峰值回落超 HALF_DRAWDOWN[board] → 减半（最多到 1/4）
        #    需浮盈先达 TRAIL_GUARD 才启动，避免买入即高位、peak≈成本被噪声误减半
        dd = HALF_DRAWDOWN.get(board, 0) if isinstance(HALF_DRAWDOWN, dict) else HALF_DRAWDOWN
        guard = TRAIL_GUARD.get(board, 0.03) if isinstance(TRAIL_GUARD, dict) else TRAIL_GUARD
        if dd > 0 and peak.get(code) and rt >= guard and cur <= peak[code] * (1 - dd) and not quartered.get(code):
            if _sell_half(code, px, "回撤减半 峰值回落{:.0%} 浮盈{:.1%}".format(dd, rt)):
                if not halved.get(code):
                    halved[code] = True
                    if cost:
                        breakeven[code] = float(cost) * (1 - BREAKEVEN_BUF)
                        log.info("[保本] {} 已减半，保本价设为 {:.2f}（成本价{:.2f}*(1-{:.1%})）".format(
                            code, breakeven[code], float(cost), BREAKEVEN_BUF))
                else:
                    quartered[code] = True
                continue
        # 8) 盈利减半（分板块）：rt >= TP_HALF_PCT[board] 且未减半过 → 减半（首减半写保本价）
        tp = TP_HALF_PCT.get(board, 0) if isinstance(TP_HALF_PCT, dict) else TP_HALF_PCT
        if tp > 0 and rt >= tp and not halved.get(code):
            if _sell_half(code, px, "盈利减半 浮盈{:.1%} 触+{}%".format(rt, int(tp * 100))):
                halved[code] = True
                if cost:
                    breakeven[code] = float(cost) * (1 - BREAKEVEN_BUF)
                    log.info("[保本] {} 已减半，保本价设为 {:.2f}（成本价{:.2f}*(1-{:.1%})）".format(
                        code, breakeven[code], float(cost), BREAKEVEN_BUF))
                continue
    # 清理已无持仓的减半 / 回撤减半 / 保本 / 峰值标记
    for c in list(halved.keys()):
        if c not in pm:
            halved.pop(c, None); quartered.pop(c, None); breakeven.pop(c, None); peak.pop(c, None)


def _days_between(d1, d2):
    try:
        import datetime as _dt
        a = _dt.date(*[int(x) for x in str(d1)[:10].split("-")])
        b = _dt.date(*[int(x) for x in str(d2)[:10].split("-")])
        return abs((b - a).days)
    except Exception:
        return 0


# ============================================================
# 九、建仓（按可用现金）
# ============================================================
def build_orders(context, top):
    # 用策略自维护的 live_held（买入即加、卖出即减）做额度计数，
    # 避免「当日平仓不释放额度」的幽灵满仓（修复 09-08/09-10 回测现象）
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
    """按热点强度分档分配预算（纯函数，便于回归）。返回与 picks 等长的金额列表。

    - 关闭强度分档：等权，与原逻辑一致。
    - 开启：权重 ∝ score^STRENGTH_EXP；单票不超过 total*MAX_SINGLE_RATIO。
      迭代再分配：触顶的票移出，剩余预算继续按权重分给未触顶的票，尽量用满预算。
    """
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
    for _ in range(20):                      # 迭代再分配，直到用满预算或全员触顶
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


def execute_buy(context, picks):
    total = _total_asset(context)
    cash = _cash(context)
    if total <= 0:
        log.error("[买入] 无法获取总资产，跳过建仓")
        return
    budget = min(cash * (1 - CASH_BUFFER), total * POSITION_VALUE_RATIO * MAX_POSITIONS)
    if budget <= 0 or cash <= 0:
        log.error("[买入] 可用资金为 0，跳过建仓")
        return
    allocs = _alloc_by_strength(picks, budget, total)
    if STRENGTH_WEIGHT:
        log.info("[买入] 总资产{:.0f} 可用现金{:.0f} 本轮预算{:.0f}（强度分档：{} 只）".format(
            total, cash, budget, len(picks)))
    else:
        per = min(total * POSITION_VALUE_RATIO, budget / max(1, len(picks)))
        log.info("[买入] 总资产{:.0f} 可用现金{:.0f} 本轮预算{:.0f} 单票{:.0f}".format(
            total, cash, budget, per))
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
    for a, per in zip(picks, allocs):
        code = a["code"]
        if per < 1000:
            log.error("[买入] {} 分配金额过小({:.0f})，跳过".format(code, per))
            continue
        # 最小申报单位校验：科创板(688) 200 股、其余 100 股；金额不足最小手数则跳过，空出仓位
        price = a.get("price")
        if not price or price <= 0:
            log.error("[买入] {} 无可用现价，跳过".format(code))
            continue
        lot = 200 if _is_kcb(code) else 100
        max_shares = int(per // (price * lot)) * lot
        if max_shares < lot:
            log.info("[买入] {} 分配{:.0f}元 @现价{:.2f} 不足最小{}股，跳过（空出仓位）".format(
                code, per, price, lot))
            continue
        target_value = max_shares * price
        halved.pop(code, None)   # 重新建仓：清掉旧的减半标记，重新开始分批止盈
        breakeven.pop(code, None)  # 同时清掉旧保本价基准
        if TRADE_ENABLED:
            log.info("[买入] {} {} 现价+{}% 强度{} 分{} 目标{}股".format(
                code, a["name"], a["pct"], a["score"], round(per), max_shares))
            try:
                if _has("order"):
                    order(code, max_shares)       # 下精确股数（已是最小申报单位整数倍），避免科创板被取整拒单
                elif _has("order_target_value"):
                    order_target_value(code, target_value)
                else:
                    order_value(code, target_value)
                entry[code] = _context_date(context)
                live_held.add(code)
            except Exception as e:
                log.error("[买入异常] {} : {}".format(code, repr(e)))
        else:
            log.info("[信号] 拟买入 {} {} 现价+{}% 强度{} 分{} 目标{}股（未下单）".format(
                code, a["name"], a["pct"], a["score"], round(per), max_shares))
            entry[code] = _context_date(context)
            live_held.add(code)


# ============================================================
# 十、入口
# ============================================================
_LAST_DATE = [""]
_DIAG_DONE = [False]


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
    log.info("[初始化] 热点追踪 v3.0 加固版启动；TRADE_ENABLED={}".format(TRADE_ENABLED))
    _diag_api()
    log.info("[初始化] 行情/成交量/口径自检将延迟到首个交易日执行（PTrade 初始化阶段禁止取数）")
    log.info("=" * 60)

    # 定时：统一用 handle_data 按时间触发。不用 run_daily —— 不同券商版本 run_daily
    # 签名不一（实测出现过参数顺序颠倒，导致字符串被当成 func，报 'str' object is
    # not callable）。handle_data 已实测稳定：分钟级在 10:30 触发，配合日期幂等每天只跑一次。
    log.info("[初始化] 定时方式：handle_data（>= {} 触发，日期幂等）".format(SIGNAL_TIME))

    # 分批止盈状态：记录哪些票已经「减半」过（首次减半标记，halved 同时驱动保本止损）
    context.halved = {}
    # 二次减半状态：记录哪些票已从半仓再减半到 1/4（quartered 后不再减半，只走全清）
    context.quartered = {}
    # 保本止损状态：记录已减半票的保本价（成本价基准），减半时写入
    context.breakeven = {}
    # 峰值回撤跟踪止盈：记录每只持仓的峰值价（历史/日内最高），回落超 TRAIL_PCT 清仓
    context.peak = {}
    # 自维护持仓集合：买入即加、卖出即减，用于建仓额度计数（修复当日平仓不释放额度）
    context.live_held = set()
    # 大盘破位防御标记：由多转空清仓只触发一次（MKT_EXIT_WHEN_BEAR=True 时生效）
    context.mkt_bear = False


def _market_timing_ok(context, data):
    """大盘择时总闸：指数站上 MA(MKT_MA) 才允许建仓；弱市/空头不追涨。"""
    if not MARKET_TIMING:
        return True
    try:
        rows = _fetch_panel([MKT_INDEX], MKT_MA + 5, ["close"], "择时")
        closes = (rows.get(MKT_INDEX) or {}).get("close") or []
        closes = [x for x in closes if x]
        if len(closes) < MKT_MA:
            return True
        cur = _current_price(data, MKT_INDEX)
        if cur is None:
            cur = closes[-1]
        ma = _ma(closes, MKT_MA)
        ok = cur >= ma
        log.info("[择时] {} 现价{:.2f} MA{}={:.2f} 状态={}".format(
            MKT_INDEX, cur, MKT_MA, ma, "多头·可建仓" if ok else "空头·暂停建仓"))
        return ok
    except Exception as e:
        log.error("[择时] 异常 {}，默认放行".format(repr(e)))
        return True


def _market_defense(context, data):
    """大盘系统性防御（可选，MKT_EXIT_WHEN_BEAR=True 时生效）：指数由多转空破 MA 时清空全部持仓一次。"""
    if not MKT_EXIT_WHEN_BEAR:
        return
    try:
        rows = _fetch_panel([MKT_INDEX], MKT_MA + 5, ["close"], "防御")
        closes = (rows.get(MKT_INDEX) or {}).get("close") or []
        closes = [x for x in closes if x]
        if len(closes) < MKT_MA:
            return
        cur = _current_price(data, MKT_INDEX)
        if cur is None:
            cur = closes[-1]
        ma = _ma(closes, MKT_MA)
        bear = cur < ma
        if bear and not getattr(context, "mkt_bear", False):
            context.mkt_bear = True
            log.error("[择时] 大盘({}) 破 MA{}，触发系统性清仓".format(MKT_INDEX, MKT_MA))
            pm = positions_map(context)
            for code in list(pm.keys()):
                _sell_all(code, pm[code], "大盘破MA{} 系统性清仓".format(MKT_MA))
        elif not bear:
            context.mkt_bear = False
    except Exception as e:
        log.error("[择时] 防御异常: {}".format(repr(e)))


def _daily_routine(context, data=None):
    # 延迟自检：PTrade 初始化阶段禁止取数，改为首个交易日执行一次
    if not _DIAG_DONE[0]:
        _DIAG_DONE[0] = True
        try:
            _diag_vol_scale()
            _diag_cutoff(context)
            _diag_data(data)
            _build_industry_map(context)   # 首个交易日构建个股→行业映射（板块共振用，仅一次）
        except Exception as e:
            log.error("[自检] 延迟自检异常: {}".format(repr(e)))
    today = _context_date(context)
    if today and _LAST_DATE[0] == today:
        return                      # 幂等：同一天只跑一次
    _LAST_DATE[0] = today
    log.info("=" * 60)
    log.info("[{}] 每日热点识别开始".format(today))
    try:
        top = scan_market(context, data)
    except Exception as e:
        log.error("[扫描] 异常: {}".format(repr(e)))
        top = []
    # 大盘择时总闸：空头市况（指数跌破 MA）暂停建仓；持仓由 handle_data 每根 bar 的盘中实时风控处理
    if not _market_timing_ok(context, data):
        log.error("[择时] 大盘({}) 跌破 MA{}，暂停建仓；现有持仓继续走盘中实时风控".format(MKT_INDEX, MKT_MA))
    elif top:
        picks = build_orders(context, top)
        if picks:
            execute_buy(context, picks)
        else:
            log.info("[信号] 无符合建仓条件的候选")
    else:
        if TRADE_ENABLED:
            log.error("[警告] 本轮热点榜为空，未建仓。若连续多日为空，"
                  "请检查取数接口与成交额单位（见初始化自检日志）")
        else:
            log.info("[信号模式] 本轮热点榜为空，不下单")


def handle_data(context, data):
    now = ""
    for path in ("blotter.current_dt", "current_dt", "now"):
        try:
            obj = context
            for a in path.split("."):
                obj = getattr(obj, a)
            now = str(obj)
            break
        except Exception:
            continue
    hhmm = now[11:16] if len(now) >= 16 else ""
    if not hhmm:
        # 拿不到时间（日频回测常见，now 可能是纯日期或空串）：每根 bar 仍跑盘中实时风控，靠幂等防重复
        log.info("[时间] 无法从 context 读取 HH:MM（now={}），按日频执行；"
                 "建议改用支持 run_daily 的平台版本".format(now))
    # —— 盘中实时风控：每根 bar（分钟频）都跑，让硬止损/跟踪止盈真正盘中生效 ——
    # 旧版只在 10:30 跑一次，隔夜跳空与盘中急跌的盲区导致止损失真（实测打到 -16% 才卖）
    try:
        monitor_risk(context, data)
    except Exception as e:
        log.error("[风控] 异常: {}".format(repr(e)))
    # 大盘系统性防御（可选，默认关）：破位清仓
    try:
        _market_defense(context, data)
    except Exception as e:
        log.error("[择时] 防御异常: {}".format(repr(e)))
    if hhmm and hhmm < SIGNAL_TIME:
        return                       # 未到信号时间，仅做风控
    # hhmm >= SIGNAL_TIME 才执行选股+建仓；_daily_routine 内按日期幂等，分钟级不会重复跑
    _daily_routine(context, data)


def before_trading_start(context, data):
    pass


def after_trading_end(context, data):
    pass
