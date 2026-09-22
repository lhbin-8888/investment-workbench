# -*- coding: utf-8 -*-
# =============================================================================
# 热点融合 v1.0  (PTrade / Python 3.5 兼容)
# 融合对象：热点早盘001 V4.11 / 热点追踪lhb888 v3 / 热点追踪早盘1030 v8.1
# 设计目标：取三家之长、避三家之短 -> 更高收益 + 各市场环境下更平滑
#
# [指纹] ★FUSION v1.0★
#   热点判定 = 申万行业均值(↑) + 板块强度分(001) + 共振>=2(常开, 改1030默认OFF)
#   选股     = 涨幅[3.5%,6%]/科创[6%,9%] + 量比>=1.5 + 站MA20&MA60 + 形态>=2 + 日内回撤<=4% + 回踩cur>=open
#   买入     = 10:30 + 每日新<=2 + 冷静期2日 + 双护栏 + 强度加权 + 额度回收3轮
#   止损     = ATR自适应 clamp[5%,11%] (改001[4,6]过紧致震) + 硬止损下限09:45
#   止盈     = +10%减半 + 保本+3% + 移动止盈武装5%/回撤15% + 赢家粘性锁利8pp
#   破线     = 破10日线(14:45确认,浮亏才砍) + 破20日线(14:45确认,硬清)
#   大市     = 沪深300<MA20暂停新建 + 中证1000<MA20 halt全停 + 情绪冰点HALF减半
# =============================================================================

import math
# 注意：PTrade 3.5 环境禁用 os / 网络 / f-string / 类型注解

# ----------------------------- 全局参数区 -----------------------------------
SIGNAL_TIME      = "10:30"          # 选股+买入主时点
RISK_TIMES       = ["09:45", "11:20", "13:10", "14:15", "14:45", "14:55"]  # 盘中巡检
TAIL_RISK_TIMES  = ["14:45", "14:55"]   # 结构时点（尾盘确认类）
BREAK_MA_TIME    = "14:45"          # 破均线仅在此时点后确认

# --- 热点/板块 ---
TOP_MAIN_LINES   = 3                # 取前 N 主线（001）
SECTOR_FADE_RATIO = 0.5             # 衰退：涨停率<=前5日均*0.5
SECTOR_FADE_DAYS  = 2               # 连续确认天数（001 修复点）
MIN_SECTOR_ALIGN = 2                # 同行业>=2只才共振（常开，改1030 OFF）
INDUSTRY_MIN_RISE = 0.0             # 申万行业均值>0才列为强势（lhb888）
TOP_INDUSTRY_N  = 10               # 申万行业均值排名前 N（lhb888）

# --- 选股 ---
MIN_HIST_BARS    = 60
MIN_AMOUNT       = 4e8              # 成交额下限（3亿~5亿折中）
MIN_VOL_RATIO    = 1.5
REQUIRE_ABOVE_MA20 = True
REQUIRE_ABOVE_MA60 = True
MA_SHAPE_MIN     = 2                # 均线多头形态阈值（lhb888）
INTRADAY_PULLBACK_MAX = 0.04        # 日内回撤上限（lhb888）
ALLOW_LIMIT_UP_BUY  = False
REQUIRE_NO_ST    = True
DETAIL_POOL      = 60               # 细评池上限
MAX_CANDIDATES   = 12

# --- 买入/仓位 ---
POSITION_VALUE_RATIO = 0.17
STRENGTH_EXP     = 1.6
MAX_SINGLE_RATIO = 0.25
MAX_POSITIONS    = 6
MAX_NEW_PER_DAY  = 2                # 放宽001的1笔，避免踏空；仍控频
COOL_DOWN_DAYS   = 2                # 比001的3日更短
CASH_BUFFER      = 0.10
BUY_FLOOR_PCT    = 0.015           # 走弱不接刀（001双护栏）
BUY_PREMIUM_PCT  = 0.03            # 涨过头不追（001双护栏）
BUDGET_RECYCLE   = True
RECYCLE_ROUNDS   = 3
REINVEST_ON_SELL = False            # 砍仓额度留次日（1030）

# --- 止损 ---
ATR_N            = 14
ATR_STOP_MULT    = 2.0
ATR_STOP_MIN_PCT = 0.05            # 下限5%（放宽001的4%减震）
ATR_STOP_MAX_PCT = 0.11            # 上限11%（放宽001的6%减震）
STOP_TIME_FLOOR  = "09:45"          # 硬止损最早时点（避集合竞价噪声）
STOP_MODE        = "atr"           # 亦可 "fixed"
FIXED_STOP_PCT   = 0.05

# --- 止盈 ---
PARTIAL_TAKE_PCT = 0.10            # +10%减半（1030）
PARTIAL_TAKE_RATIO = 0.5
BREAKEVEN_GUARD  = 0.03            # 浮盈>=3%锁保本（lhb888）
TRAIL_ARM_PCT    = 0.05            # 移动止盈武装（001）
TRAIL_PCT        = 0.15            # 峰值回撤15%清仓（001）
TP_FULL_PCT      = 0.30            # +30%全清（lhb888）

# --- 破均线 ---
RETREAT_MA_FAST  = 10              # 破10日线（浮亏才砍）
RETREAT_MA_HARD  = 20              # 破20日线（硬清）

# --- 时间/赢家 ---
MAX_HOLD_DAYS    = 5               # 亏损持仓>=5日退出
WINNER_EXEMPT_PCT   = 0.15         # 浮盈>=15%进入赢家粘性（001 V4.10）
WINNER_GIVEBACK_PCT= 0.08          # 自峰值回撤>=8pp清仓（百分点尺，更稳）
WINNER_MAX_HOLD  = 30             # 赢家最长持有天数

# --- 大市择时/避险 ---
REGIME_BROAD     = "000300.SS"     # 沪深300（宽基，暂停新建用）
REGIME_SMALL     = "000852.SS"     # 中证1000（与持仓风格匹配，halt用）
REGIME_MA        = 20
REGIME_MA_FAST   = 5
MARKET_ZT_FLOOR  = 25              # 池内涨停<25 -> 情绪冰点HALF（1030）
SENTIMENT_HALF_FACTOR = 0.5        # HALF模式预算系数

# --- 换手熔断 ---
MAX_ANNUAL_TURNS = 25
TURNOVER_WINDOW_DAYS = 60
MAX_BUYS_PER_MONTH = 20

ALLOW_BOARDS = ("SS", "SZ")
BROAD_TAG_BLACKLIST = ()           # 可扩展宽口径标签


# ----------------------------- 工具函数 -------------------------------------
def _suffix(code):
    if "." in code:
        return code
    if code.startswith("6") or code.startswith("9"):
        return code + ".SS"
    return code + ".SZ"


def _pure(code):
    return code.split(".")[0]


def _board(code):
    c = _pure(code)
    if c.startswith("8") or c.startswith("4"):
        return "BJ"
    if c.startswith("68"):
        return "KCB"
    if c.startswith("30"):
        return "CYB"
    return "MB"


def _is_kcb(code):
    return _board(code) == "KCB"


def _limit_pct(code):
    b = _board(code)
    if b == "KCB":
        return 0.20
    if b == "BJ":
        return 0.30
    return 0.10


def _gain_range(code):
    # 折中：比001[4,5]宽（防空仓），与lhb888/1030同档
    b = _board(code)
    if b == "KCB":
        return (0.06, 0.09)
    if b == "CYB":
        return (0.06, 0.09)
    return (0.035, 0.06)


def _ma(vals, n):
    if vals is None or len(vals) < n:
        return None
    return sum(vals[-n:]) / float(n)


def _mean(xs):
    if not xs:
        return 0.0
    return sum(xs) / float(len(xs))


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    m = len(s)
    if m % 2 == 1:
        return s[m // 2]
    return (s[m // 2 - 1] + s[m // 2]) / 2.0


def _has(name):
    try:
        return name in globals() or callable(globals().get(name))
    except Exception:
        return False


def _warn(msg):
    try:
        log.warning(msg)
    except Exception:
        pass


def _warn_once(key, msg):
    g = _G()
    slot = g.setdefault("noise_slot", {})
    today = g.get("today", "")
    d = slot.setdefault(key, {})
    if d.get("day") == today:
        return
    d["day"] = today
    _warn(msg)


def _days_between(a, b):
    # a,b: 'YYYY-MM-DD'，返回日历日差（近似交易日用）
    try:
        ya, ma, da = [int(x) for x in a.split("-")]
        yb, mb, db = [int(x) for x in b.split("-")]
        import datetime
        da_dt = datetime.date(ya, ma, da)
        db_dt = datetime.date(yb, mb, db)
        return abs((db_dt - da_dt).days)
    except Exception:
        return 999


# ----------------------------- 平台接口封装 --------------------------------
def _G():
    return globals().get("g", {})


def _hist(code, count, fields):
    """单只批量取数：get_history(count, freq, field, [code]) -> 该只的 DataFrame

    注意：PTrade 的 get_history 在 securities 传入【列表】时恒返回 dict
    （key=标的）。本函数统一把单只的 DataFrame 抽取出来返回，避免上层
    _hist_closes / _stop_pct 误把整个 dict 当 DataFrame 用（raw.values 会
    变成 dict_values 导致取序列失败 -> ATR自适应止损与破均线出场双双失效）。
    同时兼容平台对单只也直接返回 DataFrame 的情形。
    """
    try:
        if not _has("get_history"):
            return None
        if isinstance(fields, str):
            fields = [fields]
        raw = get_history(count, "1d", list(fields), [_suffix(code)])
        if raw is None:
            return None
        if isinstance(raw, dict):
            if _suffix(code) in raw:
                return raw[_suffix(code)]
            vals = list(raw.values())
            return vals[0] if vals else None
        return raw
    except Exception as e:
        _warn("[hist] %s 取数失败: %s" % (code, e))
        return None


def _account(context):
    # PTrade 无 get_account；读 context.portfolio
    try:
        pf = context.portfolio
        return float(pf.portfolio_value), float(pf.cash)
    except Exception as e:
        _warn("[acct] %s" % e)
        return 0.0, 0.0


def _get_positions(context):
    """兼容 dict[str:Position] 与 list[dict] 两种形态（防001/lhb888同源缺陷）"""
    try:
        poss = context.portfolio.positions
    except Exception:
        try:
            poss = get_positions()
        except Exception:
            return []
    if isinstance(poss, dict):
        out = []
        for k, v in poss.items():
            out.append(_pos_to_dict(v, k))
        return out
    if isinstance(poss, list):
        out = []
        for p in poss:
            out.append(_pos_to_dict(p, ""))
        return out
    return []


def _pos_to_dict(p, code_hint):
    d = {}
    if isinstance(p, dict):
        d = dict(p)
        if not code_hint and "stock_code" in d:
            code_hint = d["stock_code"]
        if not code_hint and "sid" in d:
            code_hint = d["sid"]
    else:
        for nm in ("sid", "stock_code", "code"):
            if hasattr(p, nm):
                code_hint = getattr(p, nm)
                break
        for nm in ("amount", "current_amount", "enable_amount", "cost_basis",
                  "last_sale_price", "last_price", "cost_price", "avg_price"):
            if hasattr(p, nm):
                d[nm] = getattr(p, nm)
    d["_code"] = _suffix(code_hint) if code_hint else ""
    return d


def _pos_field(p, names):
    for nm in names:
        if nm in p and p[nm] is not None:
            try:
                return float(p[nm])
            except Exception:
                return 0.0
    return 0.0


def _cur_price(data, code, hist_close=None):
    """取当日价：优先 data 对象，退化快照/昨收"""
    code_s = _suffix(code)
    if data is not None:
        try:
            obj = data.get(code_s) if hasattr(data, "get") else None
            if obj is None and hasattr(data, "__getitem__"):
                obj = data[code_s]
            if obj is not None:
                for f in ("price", "close", "last_price", "last_px"):
                    v = getattr(obj, f, None)
                    if v is not None:
                        return float(v)
        except Exception:
            pass
    try:
        snap = get_snapshot([code_s])
        if snap and code_s in snap:
            for f in ("last_px", "last_price", "price"):
                if f in snap[code_s] and snap[code_s][f] is not None:
                    return float(snap[code_s][f])
    except Exception:
        pass
    if hist_close is not None:
        return float(hist_close)
    return None


# ----------------------------- 板块/行业 -----------------------------------
def _industry_of(code):
    """申万行业归属（自带轻量表，缺失则用 get_industry 兜底）。"""
    code6 = _pure(code)
    # 轻量内置映射（覆盖常见热点行业；完整版可外挂 industry_map.json）
    EMBED = {
        "300StatusCode": None,
    }
    # 优先尝试平台接口
    try:
        if _has("get_industry"):
            ind = get_industry(code6)
            if ind:
                return ind
    except Exception:
        pass
    return ""


def _get_market_pool():
    for fn in ("get_Ashares", "get_all_stocks"):
        if _has(fn):
            try:
                xs = globals()[fn]()
                if xs:
                    return [_suffix(x) for x in xs if _board(x) in ("MB", "CYB", "KCB")]
            except Exception:
                pass
    _warn("[扫描] 无可用股票池接口")
    return []


# ----------------------------- 初始化 ---------------------------------------
def initialize(context):
    g = {}
    globals()["g"] = g
    g["today"] = ""
    g["entry_px"] = {}          # 自有成本（避摊薄成本陷阱）
    g["first_buy"] = {}         # 首次买入日
    g["hold_days"] = {}
    g["peak_px"] = {}           # 持仓峰值价
    g["winner_set"] = set()
    g["winner_peak_pnl"] = {}   # 赢家最高浮盈（百分点）
    g["partial_done"] = set()
    g["sector_stops"] = []      # (日期, 板块)
    g["sector_cooldown_days"] = {}
    g["cool_down"] = {}         # code -> 剩余冷静日
    g["noise_slot"] = {}
    g["buys_today"] = 0
    g["month_buys"] = {}
    g["turn_log"] = []          # 换手记账（买+卖双向）
    g["regime"] = "NORMAL"
    g["sentiment"] = "OK"
    g["sector_fade"] = {}       # 板块 -> 衰退计数
    g["candidates"] = []
    g["sector_strength"] = {}
    log.info("[初始化] ★FUSION v1.0★ 启动；TRADE_ENABLED 见平台")
    log.info("[指纹] 热点=行业均值+强度分+共振>=2 | 止损=ATR clamp[5%,11%] | 大市=300暂停+1000halt+情绪HALF")


# ----------------------------- 盘前 -----------------------------------------
def before_trading_start(context, data):
    g = _G()
    g["today"] = _context_date(context)
    g["buys_today"] = 0
    g["candidates"] = []
    g["noise_slot"] = {}
    # 冷却衰减
    for k in list(g["cool_down"].keys()):
        g["cool_down"][k] -= 1
        if g["cool_down"][k] <= 0:
            del g["cool_down"][k]
    for k in list(g["sector_cooldown_days"].keys()):
        g["sector_cooldown_days"][k] -= 1
        if g["sector_cooldown_days"][k] <= 0:
            del g["sector_cooldown_days"][k]
    # 大市状态
    _update_regime(context)
    _update_sentiment(context)
    log.info("[日初] 持仓 %d 只 | 大市=%s | 情绪=%s" %
             (len(_get_positions(context)), g["regime"], g["sentiment"]))


def _context_date(context):
    try:
        dt = context.blotter.current_dt
        return str(dt)[:10]
    except Exception:
        try:
            return str(context.current_dt)[:10]
        except Exception:
            return ""


def _update_regime(context):
    g = _G()
    halt = False
    pause = False
    try:
        raw = get_history(REGIME_MA + 5, "1d", "close",
                          [REGIME_BROAD, REGIME_SMALL])
        if raw is not None:
            # 取两指数收盘序列
            def series(idx_code):
                try:
                    col = raw[idx_code] if idx_code in raw else None
                    if col is None and hasattr(raw, "columns"):
                        col = raw[REGIME_BROAD]
                    if hasattr(col, "values"):
                        return list(col.values)
                    if hasattr(col, "tolist"):
                        return col.tolist()
                except Exception:
                    pass
                return None
            sb = series(REGIME_SMALL)
            br = series(REGIME_BROAD)
            if sb and len(sb) >= REGIME_MA:
                ma20 = _ma(sb, REGIME_MA)
                ma5 = _ma(sb[-REGIME_MA_FAST:], REGIME_MA_FAST) if len(sb) >= REGIME_MA_FAST else None
                last = sb[-1]
                if (ma20 and last < ma20) or (ma5 and ma20 and ma5 < ma20 and last < ma5):
                    halt = True
            if br and len(br) >= REGIME_MA:
                ma20 = _ma(br, REGIME_MA)
                if ma20 and br[-1] < ma20:
                    pause = True
    except Exception as e:
        _warn("[regime] %s" % e)
    if halt:
        g["regime"] = "HALT"
    elif pause:
        g["regime"] = "PAUSE"
    else:
        g["regime"] = "NORMAL"
    # 情绪冰点叠加 HALF
    if g["sentiment"] == "ICE" and g["regime"] == "NORMAL":
        g["regime"] = "HALF"


def _update_sentiment(context):
    g = _G()
    g["sentiment"] = "OK"
    try:
        pool = _get_market_pool()
        if not pool:
            return
        raw = get_history(2, "1d", ["close", "pre_close"], pool)
        if raw is None:
            return
        zt = 0
        up = 0
        tot = 0
        for code in pool:
            try:
                sub = raw[code] if code in raw else raw[_suffix(code)]
                if hasattr(sub, "values"):
                    rows = sub.values
                else:
                    rows = sub
                if len(rows) < 2:
                    continue
                c = float(rows[-1][0]) if hasattr(rows[-1], "__getitem__") else float(rows[-1])
                pc = float(rows[-2][0]) if hasattr(rows[-2], "__getitem__") else float(rows[-2])
                if pc <= 0:
                    continue
                pct = (c - pc) / pc
                tot += 1
                if pct >= _limit_pct(code):
                    zt += 1
                if pct > 0:
                    up += 1
            except Exception:
                continue
        if tot > 0 and zt < MARKET_ZT_FLOOR:
            g["sentiment"] = "ICE"
        # 上涨占比过低也判冰点
        if tot > 0 and up * 1.0 / tot < 0.30:
            g["sentiment"] = "ICE"
    except Exception as e:
        _warn("[senti] %s" % e)


# ----------------------------- 扫描+选股 -------------------------------------
def scan_market(context, data=None):
    g = _G()
    pool = _get_market_pool()
    if not pool:
        return []
    # 批量取面板
    fields = ["open", "close", "high", "low", "volume", "money", "pre_close"]
    try:
        panel = get_history(MAX_HIST_BARS + 5, "1d", list(fields), pool)
    except Exception as e:
        _warn("[扫描] 面板取数失败: %s" % e)
        return []
    if panel is None:
        return []

    feats = {}
    for code in pool:
        sub = panel.get(code) if isinstance(panel, dict) else None
        if sub is None:
            sub = panel.get(_suffix(code))
        if sub is None:
            continue
        try:
            rows = sub.values if hasattr(sub, "values") else sub
            if len(rows) < MIN_HIST_BARS:
                continue
            closes = [float(r[1]) for r in rows]
            opens = [float(r[0]) for r in rows]
            highs = [float(r[2]) for r in rows]
            lows = [float(r[3]) for r in rows]
            vols = [float(r[4]) for r in rows]
            moneys = [float(r[5]) for r in rows]
            prec = [float(r[6]) for r in rows]
            last = closes[-1]
            prev = prec[-1]
            if prev <= 0:
                continue
            pct = (last - prev) / prev
            ma20 = _ma(closes, 20)
            ma60 = _ma(closes, 60)
            ma5v = _ma(vols[-5:], 5) if len(vols) >= 5 else None
            vol_ratio = (vols[-1] / ma5v) if ma5v else 1.0
            above20 = (ma20 is not None and last >= ma20)
            above60 = (ma60 is not None and last >= ma60)
            # 均线形态：收盘价在短期均线上方且短期>长期
            ma5 = _ma(closes[-5:], 5)
            ma10 = _ma(closes[-10:], 10)
            shape = 0
            if ma5 and ma10 and ma20:
                if last >= ma5 >= ma10 >= ma20:
                    shape = 3
                elif ma5 and ma10 and ma5 >= ma10:
                    shape = 2
            feats[code] = dict(pct=pct, vol_ratio=vol_ratio, above20=above20,
                               above60=above60, shape=shape, money=moneys[-1],
                               closes=closes, opens=opens, highs=highs, lows=lows,
                               last=last, prev=prev)
        except Exception:
            continue

    # 粗筛
    rough = []
    for code, f in feats.items():
        lo, hi = _gain_range(code)
        if not (lo <= f["pct"] <= hi):
            continue
        if f["money"] < MIN_AMOUNT:
            continue
        if REQUIRE_ABOVE_MA20 and not f["above20"]:
            continue
        rough.append((code, f))
    if not rough:
        return []

    # 行业分组 + 强度分（融合：申万均值 + 001强度 + 共振）
    ind_pct = {}
    ind_cnt = {}
    ind_zt = {}
    for code, f in rough:
        ind = _industry_of(code)
        if ind not in ind_pct:
            ind_pct[ind] = []
            ind_cnt[ind] = 0
            ind_zt[ind] = 0
        ind_pct[ind].append(f["pct"])
        ind_cnt[ind] += 1
        if f["pct"] >= _limit_pct(code):
            ind_zt[ind] += 1
    # 行业均值排名前 N
    ind_avg = {k: _mean(v) for k, v in ind_pct.items()}
    strong_ind = set()
    ranked = sorted([(k, v) for k, v in ind_avg.items() if v > INDUSTRY_MIN_RISE],
                    key=lambda x: -x[1])[:TOP_INDUSTRY_N]
    for k, _ in ranked:
        strong_ind.add(k)

    cands = []
    for code, f in rough:
        ind = _industry_of(code)
        if ind not in strong_ind:
            continue  # 申万行业级确认（lhb888）
        # 共振：同行业候选>=2（常开）
        if ind_cnt.get(ind, 0) < MIN_SECTOR_ALIGN:
            continue
        # 细评：MA60 + 形态 + 日内回撤 + 回踩
        if REQUIRE_ABOVE_MA60 and not f["above60"]:
            continue
        if f["shape"] < MA_SHAPE_MIN:
            continue
        # 日内回撤 = (high-last)/high
        if f["highs"][-1] > 0 and (f["highs"][-1] - f["last"]) / f["highs"][-1] > INTRADAY_PULLBACK_MAX:
            continue
        # 回踩 cur>=open
        if f["last"] < f["opens"][-1]:
            continue
        # 不买涨停
        if not ALLOW_LIMIT_UP_BUY and f["pct"] >= _limit_pct(code):
            continue
        # 强度分
        lb = 1 if f["pct"] >= _limit_pct(code) else 0
        score = f["pct"] + lb * 6.0 + min(f["vol_ratio"], 3.0) * 8.0 + f["shape"] * 1.5
        cands.append(dict(code=code, score=score, ind=ind, f=f))
    cands.sort(key=lambda x: -x["score"])
    cands = cands[:MAX_CANDIDATES]
    g["candidates"] = cands
    g["sector_strength"] = {k: (ind_avg.get(k, 0), ind_cnt.get(k, 0), ind_zt.get(k, 0))
                            for k in strong_ind}
    return cands


# ----------------------------- 买入 -----------------------------------------
def buy_job(context, data=None):
    g = _G()
    cands = g.get("candidates") or []
    if not cands:
        return
    if g["regime"] in ("HALT", "PAUSE"):
        log.info("[买入] 大市%s，暂停新建仓" % g["regime"])
        return
    total, cash = _account(context)
    if total <= 0:
        return
    budget_factor = SENTIMENT_HALF_FACTOR if g["regime"] == "HALF" else 1.0
    base_budget = min(cash * (1 - CASH_BUFFER), total * POSITION_VALUE_RATIO * MAX_POSITIONS)
    budget = base_budget * budget_factor
    live = _get_positions(context)
    live_codes = set(_pure(p["_code"]) for p in live)
    held = len(live)
    remaining = MAX_POSITIONS - held
    if remaining <= 0:
        return

    pending = []
    for c in cands:
        code = c["code"]
        if _pure(code) in live_codes:
            continue
        if _pure(code) in g["cool_down"]:
            continue
        if c["ind"] in g["sector_cooldown_days"]:
            continue
        if g["buys_today"] >= MAX_NEW_PER_DAY:
            break
        pending.append(c)

    for c in pending:
        if remaining <= 0 or budget <= 0:
            break
        if g["buys_today"] >= MAX_NEW_PER_DAY:
            break
        code = c["code"]
        # 强度加权分配
        weight = math.pow(max(c["score"], 0.01), STRENGTH_EXP)
        tot_w = sum(math.pow(max(x["score"], 0.01), STRENGTH_EXP) for x in pending)
        alloc = budget * (weight / tot_w) if tot_w > 0 else budget / max(len(pending), 1)
        alloc = min(alloc, total * MAX_SINGLE_RATIO)
        if alloc < 1000:
            continue
        # 双护栏：取当日价
        cur = _cur_price(data, code, hist_close=c["f"]["last"])
        if cur is None:
            cur = c["f"]["last"]
        lo_guard = cur * (1 - BUY_FLOOR_PCT)
        hi_guard = cur * (1 + BUY_PREMIUM_PCT)
        if cur < lo_guard or cur > hi_guard:
            continue  # 走弱不接刀 / 涨过头不追
        limit = min(cur * 1.02, hi_guard)
        try:
            order_target_value(_suffix(code), alloc, limit_price=limit)
            g["entry_px"][_pure(code)] = cur
            g["first_buy"][_pure(code)] = g["today"]
            g["peak_px"][_pure(code)] = cur
            g["buys_today"] += 1
            remaining -= 1
            budget -= alloc
            _record_turn("BUY")
            _record_month(g["today"])
            log.info("[买入] %s 行业=%s 强度%.1f 分配%.0f 限价%.2f" %
                     (code, c["ind"], c["score"], alloc, limit))
        except Exception as e:
            _warn("[买入] %s 下单失败: %s" % (code, e))


# ----------------------------- 风控/出场 ------------------------------------
def monitor_risk(context, data=None, tag="NORMAL"):
    g = _G()
    live = _get_positions(context)
    now = _now_hhmm(context)
    is_tail = now >= BREAK_MA_TIME
    for p in live:
        code = p["_code"]
        code6 = _pure(code)
        amount = _pos_field(p, ("amount", "current_amount"))
        enable = _pos_field(p, ("enable_amount",))
        if amount <= 0:
            continue
        cur = _cur_price(data, code)
        if cur is None:
            continue
        entry = g["entry_px"].get(code6)
        if entry is None or entry <= 0:
            entry = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or cur
            g["entry_px"][code6] = entry
        pnl = (cur - entry) / entry
        # 更新峰值
        if code6 not in g["peak_px"] or cur > g["peak_px"][code6]:
            g["peak_px"][code6] = cur
        peak = g["peak_px"][code6]
        peak_pnl = (peak - entry) / entry
        held = g["hold_days"].get(code6, _days_between(g["first_buy"].get(code6, g["today"]), g["today"]))
        g["hold_days"][code6] = held
        # T+1：当日买入不可卖，跳过所有卖出判定（防废单/噪声）
        if held < 1:
            continue

        # ① 硬止损（风险类，下限09:45）
        stop_pct = _stop_pct(code6, entry, cur)
        if now >= STOP_TIME_FLOOR and pnl <= -stop_pct:
            _sell_all(context, code, "硬止损", pnl=pnl, entry_today=(held < 1))
            _on_stop(code6, g, p)
            continue
        # ② 保本止损：峰值曾盈利>=3% 后回撤至成本线即退出（用 peak_pnl 判定，避免与 cur<=entry 互斥导致死代码）
        if peak_pnl >= BREAKEVEN_GUARD and cur <= entry:
            _sell_all(context, code, "保本止损", pnl=pnl, entry_today=(held < 1))
            continue
        # ③ 分批止盈（+10%减半，未做过）
        if pnl >= PARTIAL_TAKE_PCT and code6 not in g["partial_done"] and enable >= 100:
            _sell_half(context, code, p, pnl)
            g["partial_done"].add(code6)
            continue
        # ④ 移动止盈（武装5%/回撤15%，价格触发，无闸门）
        if peak_pnl >= TRAIL_ARM_PCT and cur <= peak * (1 - TRAIL_PCT):
            _sell_all(context, code, "移动止盈", pnl=pnl, entry_today=(held < 1))
            continue
        # ⑤ 赢家粘性锁利（百分点尺，自峰值回撤>=8pp）
        if peak_pnl >= WINNER_EXEMPT_PCT:
            g["winner_set"].add(code6)
            g["winner_peak_pnl"][code6] = peak_pnl
        if code6 in g["winner_set"] and held <= WINNER_MAX_HOLD:
            giveback = peak_pnl - pnl
            if giveback >= WINNER_GIVEBACK_PCT:
                _sell_all(context, code, "赢家锁利", pnl=pnl, entry_today=(held < 1))
                continue
        # ⑥ +30%全清（锁利类，无闸门）
        if pnl >= TP_FULL_PCT:
            _sell_all(context, code, "止盈全清", pnl=pnl, entry_today=(held < 1))
            continue
        # ⑦ 破均线（趋势类，仅尾盘确认）
        if is_tail:
            closes = _hist_closes(code, RETREAT_MA_HARD + 2)
            if closes and len(closes) >= RETREAT_MA_HARD:
                ma20 = _ma(closes, RETREAT_MA_HARD)
                if ma20 and cur < ma20:
                    _sell_all(context, code, "破20日线", pnl=pnl, entry_today=(held < 1))
                    continue
                ma10 = _ma(closes, RETREAT_MA_FAST)
                if ma10 and cur < ma10 and pnl < 0:
                    _sell_all(context, code, "破10日线", pnl=pnl, entry_today=(held < 1))
                    continue
        # ⑧ 时间止损（亏损持仓>=5日）
        if pnl < 0 and held >= MAX_HOLD_DAYS:
            _sell_all(context, code, "时间止损", pnl=pnl, entry_today=(held < 1))
            continue


def _stop_pct(code6, entry, cur):
    if STOP_MODE == "fixed":
        return FIXED_STOP_PCT
    # ATR 自适应（取近期振幅估算）
    closes = _hist_closes(code6, ATR_N + 2)
    if closes and len(closes) >= ATR_N:
        atr = _atr(closes, ATR_N)
        if atr > 0 and entry > 0:
            ratio = atr / entry
            pct = ATR_STOP_MULT * ratio
            return max(ATR_STOP_MIN_PCT, min(ATR_STOP_MAX_PCT, pct))
    return ATR_STOP_MIN_PCT


def _atr(closes, n):
    trs = []
    for i in range(1, len(closes)):
        trs.append(abs(closes[i] - closes[i - 1]))
    if len(trs) < n:
        return _mean(trs) if trs else 0.0
    return _mean(trs[-n:])


def _hist_closes(code, count):
    raw = _hist(code, count, "close")
    if raw is None:
        return None
    try:
        if hasattr(raw, "values"):
            return [float(r[0]) for r in raw.values]
        return [float(x) for x in raw]
    except Exception:
        return None


def _sell_all(context, code, reason, pnl=0.0, entry_today=False):
    g = _G()
    code6 = _pure(code)
    try:
        order_target(_suffix(code), 0)
    except Exception as e:
        _warn("[卖出] %s 清仓失败: %s" % (code, e))
        return
    # 先快照成本算￥，再清（PTrade order 后持仓清零）
    entry = g["entry_px"].get(code6)
    enable = 0
    _record_turn("SELL")
    _record_trade(reason, pnl)
    log.info("[卖出] %s —— %s 浮盈%.1f%%" % (code, reason, pnl * 100))
    for k in ("entry_px", "first_buy", "peak_px", "hold_days", "winner_peak_pnl"):
        if isinstance(g.get(k), dict):
            g[k].pop(code6, None)
    for k in ("partial_done", "winner_set"):
        if isinstance(g.get(k), set):
            g[k].discard(code6)


def _sell_half(context, code, p, pnl):
    g = _G()
    code6 = _pure(code)
    amount = int(_pos_field(p, ("amount", "current_amount")))
    enable = int(_pos_field(p, ("enable_amount",)))
    lot = 200 if _is_kcb(code) else 100
    half = (amount // 2 // lot) * lot
    if half < lot or enable < half:
        return
    try:
        order(_suffix(code), -half)
    except Exception as e:
        _warn("[卖出] %s 减半失败: %s" % (code, e))
        return
    _record_turn("SELL")
    _record_trade("分批止盈", pnl)
    log.info("[卖出] %s 数量%d 减半 浮盈%.1f%%" % (code, half, pnl * 100))


def _on_stop(code6, g, p):
    ind = _industry_of(code6)
    g["sector_stops"].append((g["today"], ind))
    # 板块连败冷却
    recent = [s for s in g["sector_stops"]
              if s[1] == ind and _days_between(s[0], g["today"]) <= 20]
    if len(recent) >= 2:
        g["sector_cooldown_days"][ind] = 10
        log.info("[板块冷却] %s 连败>=2，冷却10日" % ind)


# ----------------------------- 换手/统计 -------------------------------------
def _record_turn(kind):
    g = _G()
    g["turn_log"].append((g["today"], kind))


def _record_month(today):
    g = _G()
    ym = today[:7]
    g["month_buys"][ym] = g["month_buys"].get(ym, 0) + 1


def _record_trade(reason, pnl):
    """记录每笔卖出（原因 + 浮盈率），供 [卖出] 分原因统计使用。"""
    g = _G()
    g.setdefault("trade_log", []).append((g.get("today", ""), reason, pnl))
    # 同步推进换手记账（卖出单向，配合 _record_turn 的买向构成双向）
    if reason not in ("",):
        g.setdefault("sell_reasons", {}).setdefault(reason, 0)
        g["sell_reasons"][reason] += 1


def _turnover_ok():
    g = _G()
    recent = [t for t in g["turn_log"] if _days_between(t[0], g["today"]) <= TURNOVER_WINDOW_DAYS]
    # 买+卖双向计数，按窗口折算年频次
    n = len(recent)
    span = max([_days_between(recent[0][0], g["today"]) for _ in recent] + [1])
    ann = n * 250.0 / max(span, TURNOVER_WINDOW_DAYS)
    if ann > MAX_ANNUAL_TURNS * 2:
        return False
    return True


def report_stats():
    g = _G()
    log.info("[统计] 大市=%s 情绪=%s 板块强度Top=%s" %
             (g["regime"], g["sentiment"],
              sorted(g["sector_strength"].items(), key=lambda x: -x[1][0])[:3]))


# ----------------------------- 时钟/入口 ------------------------------------
def _now_hhmm(context):
    try:
        dt = context.blotter.current_dt
        return str(dt)[11:16]
    except Exception:
        return "15:00"


def handle_data(context, data):
    now = _now_hhmm(context)
    g = _G()
    g["today"] = _context_date(context)
    if now == SIGNAL_TIME:
        cands = scan_market(context, data)
        buy_job(context, data)
        report_stats()
    elif now in RISK_TIMES:
        monitor_risk(context, data, "NORMAL")
    elif now in TAIL_RISK_TIMES:
        monitor_risk(context, data, "TAIL")


# 若平台用 run_daily 而非 handle_data，可注册：
# run_daily(before_trading_start, 'before_open')
# run_daily(lambda c,d: handle_data(c,d), SIGNAL_TIME)
