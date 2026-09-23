# -*- coding: utf-8 -*-
"""
国金证券 PTrade 量化策略 —— 长线股「核心-卫星 + 波段 + 日内T」三层架构
=====================================================================
平台：PTrade（恒生系白标，Python 3.5 托管环境，无外网、无 os 模块）
约束（来自 ptrade-strategy-dev 技能，逐条已落实）：
  - 代码后缀 .SS / .SZ / .BJ；内部比较一律用 6 位纯数字（_canon）
  - T+1：卖出必须用 enable_amount（可卖量），current_amount 含当日新仓
  - 涨跌停用板区分：30/68->20%  8/4->30%  ST->5%  其余 10%
  - 成本含印花税（卖出单边）；换手预算按"交易日窗口"计
  - 回测当日价只能走 handle_data 的 data 参数或 1m 线；不可读 close[-1] 当已收盘
  - 两段式止损已证伪 -> 统一用"单段一次性清仓" + 策略自有成本价记录
  - 盈亏比：止损上限 <= 止盈上限的一半
  - 出场分级闸门：风险类(硬止损)只设下限 09:45；趋势类(破线/清仓)尾盘 14:45
  - 任何接口降级必须 log.warning，绝不静默换口径

默认 TRADE_ENABLED = False：先信号模式跑 3~5 日核对日志，再模拟盘，最后小资金实盘。
"""

# ============================== 全局状态 ==============================
# PTrade 模块级 g 字典（全局可变状态，跨回调共享）
g = {}

# ============================== 一、参数区 ==============================
# ---- 总开关 ----
TRADE_ENABLED = False          # [上线前必改] False=只出信号不下单；True=实盘下单
INTRADAY_T    = True           # 是否启用 L3 日内T（需 handle_data 拿到盘中 data；拿不到自动降级）

# ---- 三层资金架构（占组合净值比例，合计 < 1，余为缓冲）----
L1_RATIO = 0.58               # L1 长线底仓
L2_RATIO = 0.25               # L2 波段卫星
# L3 日内T 不占额外长期仓位，只在 L2/L3 现金里做"有去有回"的闭环

# ---- 再平衡 ----
L1_REBALANCE_DAYS = 60        # L1 季度再平衡间隔（交易日）
L1_MIN_HOLD_DAYS  = 5         # L1 单只最短持有（交易日），防过度换手

# ---- L2 波段信号 ----
L2_PULLBACK_PCT = 0.06        # 收盘价回落至 MA20 下方 6% 视为回调买点
L2_VOL_RATIO_MAX = 0.80       # 量比上限（地量）：当日量 < 近5日均量*0.8
L2_RSI_LO, L2_RSI_HI = 35, 55 # RSI(14) 共振区间
L2_TAKE_PCT   = 0.14          # 目标收益 +14%（止盈上限）
L2_TRAIL_PCT  = 0.08          # 移动止盈回撤 8%
L2_STOP_PCT   = 0.07          # 硬止损 -7%（满足 止损<=止盈/2）
L2_RSI_SELL   = 70            # 超买清仓线

# ---- L3 日内T ----
T_TRIGGER_PCT = 0.012         # VWAP 偏离 1.2% 触发
T_MAX_FRAC    = 0.20          # 单次动用可卖量上限 20%
T_MAX_ROUNDS  = 2             # 单票单日最多 2 回合
T_EDGE_MIN    = 0.004         # edge < 0.4% 不做（散户T净贡献常为负）
T_OPEN, T_CLOSE = "09:45", "14:45"   # T 仅在此窗口；14:50 强制平掉未回补
T_VWAP_WIN    = 60            # VWAP 计算用近 60 根 1m 线

# ---- 风控 ----
CB_STAGE1, CB_STAGE2, CB_STAGE3 = -0.08, -0.12, -0.18   # 组合断路器三级
MKT_MA_SHORT, MKT_MA_LONG = 60, 120                    # 沪深300 均线开关
MKT_RESET_CONFIRM_DAYS = 1    # 长均线档位复位需连续站上 120 日线的交易日数(默认1=立即复位；
                              # 调大如3~5可防指数在均线附近反复穿越导致反复减仓)
SINGLE_MAX = 0.10            # 单票上限 10%
SECTOR_MAX = 0.30           # 行业上限 30%（按表中细分行业，见 SECTOR_OF）

# ---- 成本 / 换手预算（R3 经济性先于策略）----
# 现行费率估算（A股 2024-2026）：印花税卖出单边 0.05%（2023-08-28 起减半）；
#   佣金双边 万2.5（最低5元/笔）；滑点为回测建模假设 0.05%。未含过户费（中登 万0.1 双向）。
STAMP_TAX   = 0.0005         # 印花税：卖出单边 0.05%（现行）
COMM_RATE   = 0.00025        # 佣金：双边 0.025%（万2.5，最低5元/笔）
SLIPPAGE    = 0.0005         # 滑点：回测建模假设 0.05%
COST_PER_TURN = STAMP_TAX + 2*COMM_RATE + 2*SLIPPAGE   # 单回合（买+卖）综合成本 ≈ 0.20%（未含过户费）
ANNUAL_COST_BUDGET = 0.015   # 年度成本预算 1.5%
MAX_ANNUAL_TURNS  = ANNUAL_COST_BUDGET / COST_PER_TURN  # ≈ 7.5 回合/年硬上限
TURNOVER_MIN_DAYS = 20        # 年化外推的最小样本(交易日)；不足则不做年化判定，
                              # 避免回测初期 1 个回合被外推成 250 回合/年、一天烧光整年预算

# ============================== 二、股票池 ==============================
# 来自「长线选股_20260920」精选 16 只，带正确后缀
STOCKS = [
    "600519.SS",  # 贵州茅台
    "603605.SS",  # 珀莱雅
    "002027.SZ",  # 分众传媒
    "000538.SZ",  # 云南白药
    "300760.SZ",  # 迈瑞医疗
    "603259.SS",  # 药明康德
    "688111.SS",  # 金山办公
    "603986.SS",  # 兆易创新
    "688012.SS",  # 中微公司
    "688072.SS",  # 拓荆科技
    "002414.SZ",  # 高德红外
    "601899.SS",  # 紫金矿业
    "000792.SZ",  # 盐湖股份
    "600938.SS",  # 中国海油
    "600900.SS",  # 长江电力
    "688008.SS",  # 澜起科技
]
# L1 质量权重（原始值，代码内归一化到 L1_RATIO）
L1_RAW = {
    "600519.SS": 10, "601899.SS": 9, "600938.SS": 8, "600900.SS": 8, "300760.SZ": 8,
    "603259.SS": 7, "002027.SZ": 7, "000538.SZ": 7, "603605.SS": 7, "000792.SZ": 7,
    "688111.SS": 6, "603986.SS": 6, "688012.SS": 5, "688072.SS": 5, "002414.SZ": 5,
    "688008.SS": 5,
}
# L2 波段卫星（流动性好的 10 只），L2_RATIO 在其间均分
L2_SET = [
    "600519.SS", "601899.SS", "600938.SS", "600900.SS", "300760.SZ",
    "002027.SZ", "603986.SS", "688012.SS", "688072.SS", "688111.SS",
]
# L3 日内T 标的（最流动的 7 只）
L3_SET = [
    "600519.SS", "601899.SS", "600938.SS", "600900.SS", "300760.SZ",
    "002027.SZ", "603986.SS",
]
# 行业划分：采用「长线选股_20260920」原表 细分行业 字段（自选股20260920.xls，492 只全样本筛选）
# 仅用于行业上限约束 SECTOR_MAX
SECTOR_OF = {
    "600519.SS": "白酒",          # 贵州茅台
    "603605.SS": "化妆品",        # 珀莱雅
    "000538.SZ": "中药",          # 云南白药
    "300760.SZ": "医疗设备",      # 迈瑞医疗
    "603259.SS": "医疗研发外包",  # 药明康德
    "688111.SS": "云软件服务",    # 金山办公
    "603986.SS": "集成电路设计",  # 兆易创新
    "688008.SS": "集成电路设计",  # 澜起科技
    "688012.SS": "半导体设备",    # 中微公司
    "688072.SS": "半导体设备",    # 拓荆科技
    "002414.SZ": "军工电子",      # 高德红外
    "601899.SS": "铜",            # 紫金矿业
    "000792.SZ": "钾肥",          # 盐湖股份
    "600938.SS": "油气开采",      # 中国海油
    "600900.SS": "水力发电",      # 长江电力
    "002027.SZ": "其他广告营销",  # 分众传媒
}
INDEX_CODE = "000300.SS"   # 沪深300 作为市场开关


# ============================== 三、工具函数 ==============================
def _canon(code):
    """返回 6 位纯数字，所有内部比较统一用。"""
    if "." in code:
        return code.split(".")[0]
    return code


def _suffix(digit):
    """6 位数字补后缀。指数（已带点）原样返回。"""
    if "." in digit:
        return digit
    if digit.startswith("6") or digit.startswith("9"):
        return digit + ".SS"
    if digit.startswith("8") or digit.startswith("4"):
        return digit + ".BJ"
    return digit + ".SZ"


def _plate_pct(code):
    """涨停/跌停幅度（小数）：创业板30*/科创板688* -> 0.20；北交所8/4 -> 0.30；ST -> 0.05；其余 0.10。"""
    d = _canon(code)
    up = (d[0:2] in ("30",) or d[0:3] in ("688",)) and 1 or 0
    if up:
        return 0.20
    if d[0] in ("8", "4"):
        return 0.30
    if "ST" in code.upper():
        return 0.05
    return 0.10


def _lot_min(code):
    """整手最小单位：科创板 200，其余 100。"""
    d = _canon(code)
    if d[0:3] == "688":
        return 200
    return 100


def _round_lot(shares, code):
    """向下取整到整手。"""
    lm = _lot_min(code)
    return int(shares // lm) * lm


def _hist_lists(code, count, period="1d"):
    """取历史行情，返回 (closes, opens, highs, lows, vols) 列表；失败返回 None（R4 显式告警）。"""
    try:
        # 真实签名: get_history(count, frequency, field, security_list, ...)
        # code 必须传字符串(单只)才返回 DataFrame(列=字段名)；无 df 参数
        bars = get_history(count, period, ["close", "open", "high", "low", "volume"], code)
    except Exception as e:
        log.warning("[hist] get_history 异常 %s: %s" % (code, e))
        return None
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        log.warning("[hist] %s 返回空（可能不支持 df/字段），L 层该票跳过" % code)
        return None
    try:
        closes = list(bars["close"])
        opens = list(bars["open"])
        highs = list(bars["high"])
        lows = list(bars["low"])
        vols = list(bars["volume"])
    except Exception as e:
        log.warning("[hist] %s 返回形态非预期: %s" % (code, e))
        return None
    return closes, opens, highs, lows, vols


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _index_below_ma(code, ma_days):
    """指数收盘价是否低于其 ma_days 均线（用已完成数据：before_trading_start 时末根是昨收）。

    返回 True / False；数据不足或取不到时返回 None（无法判定），由调用方做保守处理，
    避免把「无数据」当成「站上均线」而误复位市场开关档位。
    """
    h = _hist_lists(code, ma_days + 5, "1d")
    if h is None:
        return None
    closes = h[0]
    ma = _ma(closes, ma_days)
    if ma is None:
        return None
    return closes[-1] < ma


def _cur_price(code, data):
    """Intraday price: prefer handle_data data[code].price, fallback get_snapshot last_px. Returns (price, source)."""
    if data is not None:
        try:
            obj = data[code]
            px = getattr(obj, "price", None)
            if px is None and hasattr(obj, "get"):
                px = obj.get("price")
            if px is None and hasattr(obj, "get"):
                px = obj.get("close") or obj.get("last_px")
            if px and float(px) > 0:
                return float(px), "data"
        except Exception:
            pass
    try:
        snap = get_snapshot(code)
        if snap and isinstance(snap, dict):
            obj = snap.get(code, snap)
            if isinstance(obj, dict):
                px = obj.get("last_px") or obj.get("price") or obj.get("close") or obj.get("last_price")
                if px and float(px) > 0:
                    return float(px), "snapshot"
    except Exception:
        pass
    return None, "none"
def _pos_to_dict(p, code_hint=""):
    """Map a Position object (or a legacy dict) into the uniform shape.

    PTrade 口径（山西/国金文档一致）：get_positions() 与 context.portfolio.positions
    均为 dict[str:Position]，值为 Position 对象，字段 sid/enable_amount/amount/
    last_sale_price/cost_basis。code_hint 用于字典键与 Position 内代码不一致时兜底。
    """
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0
    if isinstance(p, dict):
        code = (p.get("stock_code") or p.get("security") or p.get("code")
                or p.get("sid") or code_hint or "")
        d = {
            "code": code,
            "current_amount": _f(p.get("current_amount", p.get("amount", 0))),
            "enable_amount": _f(p.get("enable_amount", 0)),
            "cost_price": _f(p.get("cost_price", p.get("keep_cost_price", 0))),
            "current_price": _f(p.get("last_price", p.get("last_sale_price", 0))),
        }
    else:
        code = (getattr(p, "sid", "") or getattr(p, "security", "")
                or getattr(p, "stock_code", "") or code_hint)
        d = {
            "code": code,
            "current_amount": _f(getattr(p, "amount", 0)),
            "enable_amount": _f(getattr(p, "enable_amount", 0)),
            "cost_price": _f(getattr(p, "cost_basis", getattr(p, "cost_price", 0))),
            "current_price": _f(getattr(p, "last_sale_price", getattr(p, "last_price", 0))),
        }
    cd = _canon(d["code"])
    d["code"] = _suffix(cd)
    return d


def _get_positions():
    """Return {canon: dict(current_amount, enable_amount, cost_price, current_price)}.

    【口径·重要】山西/国金文档一致：get_positions() 返回 **dict[str:Position]**
    （键=标的代码，值=Position 对象）；context.portfolio.positions 同为 dict[str:Position]。
    返回 list[dict] 的是 get_all_positions()，仅交易模块可用，本策略不用。
    因此必须按 .items() 取键值对：早前写成 `for p in poss`，遍历 dict 只会得到
    字符串键，被 _pos_to_dict 判为空代码而整仓丢弃 -> 策略误判"零持仓"，
    风控/日内T/行业上限全部静默失效（信号模式下无持仓，故冒烟测试掩盖了该缺陷）。
    兼容处理：dict -> items()；list -> 按下标取值。
    """
    out = {}
    items = []
    try:
        poss = get_positions()
    except Exception as e:
        poss = None
        log.warning("[pos] get_positions err: %s" % e)
    if isinstance(poss, dict):
        items = list(poss.items())
    elif poss:
        try:
            for i in range(len(poss)):
                items.append((None, poss[i]))
        except Exception:
            items = []
    for key, p in items:
        hint = str(key) if key is not None else ""
        d = _pos_to_dict(p, hint)
        cd = _canon(d["code"])
        if not cd:
            continue
        out[cd] = d
    if out:
        return out
    # 退化通道：直接读 context.portfolio.positions（同为 dict[str:Position]）
    ctx = g.get("ctx")
    if ctx is not None:
        pf = getattr(ctx, "portfolio", None)
        src = getattr(pf, "positions", None) if pf is not None else None
        if src:
            for key, p in src.items():
                d = _pos_to_dict(p, str(key))
                cd = _canon(d["code"])
                if not cd:
                    continue
                out[cd] = d
    return out
def _account():
    """PTrade has no get_account(); account info lives in context.portfolio."""
    ctx = g.get("ctx")
    if ctx is not None:
        pf = getattr(ctx, "portfolio", None)
        if pf is not None:
            total = getattr(pf, "portfolio_value", None)
            cash = getattr(pf, "cash", None)
            pv = getattr(pf, "positions_value", None)
            if total is None:
                try:
                    total = float(cash or 0) + float(pv or 0)
                except Exception:
                    total = None
            if total is not None:
                return {
                    "total_value": float(total),
                    "cash": float(cash or 0),
                    "positions_value": float(pv or 0),
                }
    log.warning("[acct] no context.portfolio, fallback get_account()")
    try:
        return get_account()
    except Exception as e:
        log.warning("[acct] get_account err: %s" % e)
        return None
def _noise_once(cd, kind):
    """同日同类提示只打一次（§八之二 坑2）。"""
    slot = g.setdefault("noise_slot", {})
    day = g.get("today", "")
    key = cd + "|" + kind
    if slot.get(key) == day:
        return False
    slot[key] = day
    return True


def _record_turn(reason, round_trip=False):
    """成交记账（两套口径，勿混）：
    - STATS：逐笔统计，每次委托都计，用于日志与归因；
    - ytd_turns：只计「已完成回合」(round_trip=True)，与 COST_PER_TURN(买+卖综合成本)同口径。
      L1 配置型建仓/再平衡属长线底仓，不计入投机换手预算，避免首次建仓就吃掉整年预算。
    """
    st = g.setdefault("STATS", {"n": 0, "by_reason": {}})
    st["n"] += 1
    st["by_reason"].setdefault(reason, [0, 0.0])
    st["by_reason"][reason][0] += 1
    if round_trip:
        g["ytd_turns"] = g.get("ytd_turns", 0) + 1


def _turnover_ok():
    """年化换手是否还在预算内（仅约束 L2/L3 投机换手；L1 配置型再平衡不受此限）。

    R1 修正：样本不足 TURNOVER_MIN_DAYS 个交易日时不做年化外推——否则回测第 1 天
    1 个回合即被外推为 250 回合/年，整年预算当天烧光，L2/L3 被长期误锁。
    R2 修正：告警走 _noise_once，同日只打一次（原实现同一秒重复打印 15 次）。
    """
    days = max(1, g.get("trade_days", 1))
    if days < TURNOVER_MIN_DAYS:
        return True
    turns = g.get("ytd_turns", 0)
    annual = turns * 250.0 / days
    if annual > MAX_ANNUAL_TURNS:
        if _noise_once("__turnover__", "budget"):
            log.warning("[换手预算] 年化 %.1f 回合 > 上限 %.1f，暂停新开 L2/L3" % (annual, MAX_ANNUAL_TURNS))
        return False
    return True


def _do_sell(code, shares, reason):
    """带 T+1 校验的卖出（仅用 enable_amount）。返回实际委托股数（整手）。"""
    cd = _canon(code)
    poss = _get_positions()
    pos = poss.get(cd)
    if not pos:
        return 0
    avail = pos["enable_amount"]
    if avail <= 0:
        if _noise_once(cd, "t1"):
            log.info("[卖出] %s 可卖为0(T+1未交收)，顺延次日" % code)
        return 0
    qty = _round_lot(min(shares, avail), code)
    if qty <= 0:
        return 0
    if TRADE_ENABLED:
        try:
            # 目标市值 = (现持股 - 卖出量) * 现价（市价单，price 仅用于换算股数差）
            order_target_value(code, (pos["current_amount"] - qty) * pos["current_price"])
        except Exception as e:
            log.warning("[卖出] order 失败 %s: %s" % (code, e))
            return 0
    else:
        log.info("[信号-卖] %s 数量%d 原因:%s" % (code, qty, reason))
    return qty


def _sector_of(code):
    """Return sector label for code per SECTOR_OF, or None if unmapped."""
    return SECTOR_OF.get(_suffix(_canon(code)))


def _sector_value(code):
    """Current total market value of all held positions sharing code's sector."""
    sec = _sector_of(code)
    if sec is None:
        return 0.0
    poss = _get_positions()
    s = 0.0
    for cd, d in poss.items():
        if SECTOR_OF.get(_suffix(cd)) == sec:
            s += d.get("current_amount", 0) * (d.get("current_price", 0) or 0)
    return s


def _apply_sector_cap(code, total, add_value):
    """Cap add_value so the sector's post-buy market value <= SECTOR_MAX*total.

    add_value is the intended market-value increment for this buy. Returns the
    allowed increment (0 if the sector is already at/over cap). Unmapped stocks
    skip the constraint but warn once.
    """
    sec = _sector_of(code)
    if sec is None:
        if code not in g.get("sector_warn", set()):
            g.setdefault("sector_warn", set()).add(code)
            log.warning("[sector-cap] %s 未在 SECTOR_OF 配置行业，跳过行业上限" % code)
        return add_value
    sec_cap = total * SECTOR_MAX
    sec_val = _sector_value(code)
    if sec_val >= sec_cap:
        pct = (sec_val / total * 100) if total else 0.0
        log.warning("[sector-cap] %s 行业%s已封顶(%.1f%%/上限%.0f%%)，拒单"
                    % (code, sec, pct, SECTOR_MAX * 100))
        return 0
    room = sec_cap - sec_val
    if add_value <= room:
        return add_value
    log.info("[sector-cap] %s 行业%s减额 %.0f->%.0f" % (code, sec, add_value, room))
    return room


def _do_buy_value(code, target_value):
    """Buy by target market value (L1/L2). Enforces SINGLE_MAX (single-name) and SECTOR_MAX (industry) caps; one fill per code per callback to avoid order_target_value double-submit on stale reads."""
    cd = _canon(code)
    if cd in g.get("buy_codes", set()):
        return 0
    # 断路器独立拦截所有方向性买入（L3 日内T回补不走此函数，不受影响）
    if g.get("circuit_halt"):
        return 0
    # 换手预算不在此处判定：本函数同时服务 L1 配置型季度再平衡（不受投机换手预算约束）。
    # L2 的换手预算在 _l2_daily 判定，L3 的在 _t_once 判定。
    acct = _account()
    if acct is None:
        return 0
    total = acct.get("total_value", 0) or 0
    if total <= 0:
        return 0
    poss = _get_positions()
    pos = poss.get(cd, {})
    cur_val = pos.get("current_amount", 0) * (pos.get("current_price", 0) or 0)
    cap = total * SINGLE_MAX
    if cur_val + target_value > cap:
        target_value = max(0, cap - cur_val)
    # 行业上限：该笔买入后所属细分行业总市值占比不得超过 SECTOR_MAX
    target_value = _apply_sector_cap(code, total, target_value)
    if target_value <= 0:
        return 0
    if TRADE_ENABLED:
        try:
            order_target_value(code, cur_val + target_value)
        except Exception as e:
            log.warning("[buy] order failed %s: %s" % (code, e))
            return 0
    else:
        log.info("[signal-buy] %s val %.0f" % (code, target_value))
    g.setdefault("buy_codes", set()).add(cd)
    g.setdefault("buy_day", {})[cd] = g.get("trade_days", 0)
    _record_turn("buy")
    return target_value
def initialize(context):
    # 注册标的：PTrade 框架要求 set_universe 后，handle_data 的 data 才会带这些股票的行情
    set_universe(STOCKS)
    set_benchmark(INDEX_CODE)
    # 归一化 L1 权重到 L1_RATIO
    raw_sum = sum(L1_RAW.values())
    g["L1_W"] = {}
    for c in STOCKS:
        g["L1_W"][c] = (L1_RAW.get(c, 1) / raw_sum) * L1_RATIO
    g["L2_W"] = {c: L2_RATIO / len(L2_SET) for c in L2_SET}
    g["trade_days"] = 0
    g["last_reb_day"] = -999
    g["ytd_turns"] = 0
    g["peak_total"] = 0.0
    g["circuit_halt"] = False
    g["cb_stage"] = 0          # 0/1/2/3 已触发到第几级
    g["mkt_stage"] = 0         # 0/1 市场开关已降级到第几级(1=已因跌破120日线砍过两成)
    g["mkt_above_days"] = 0    # 连续站上120日线的交易日数(用于档位复位确认)
    g["l2_enabled"] = True     # 波段开关(_market_switch 每日按60日线双向刷新)
    g["entry_px"] = {}         # 策略自有成本价（防平台摊薄口径，§十一）
    g["peak_px"] = {}          # L2 移动止盈峰值
    g["buy_day"] = {}          # 实际建仓日(trade_days)，用于 _held_days 真实持有期
    g["buy_codes"] = set()     # 每回调内买入去重(防 order_target_value 重复下单)
    g["ctx"] = None            # 当前 context（账户/持仓来源）
    g["_vwap_cache"] = {}      # VWAP 同分钟缓存
    g["t_rounds"] = {}         # 单票单日T回合数
    g["t_pending"] = {}        # 已卖待回补的股数
    g["noise_slot"] = {}
    g["STATS"] = {"n": 0, "by_reason": {}}
    g["intr_checked"] = False
    g["intr_ok"] = False
    log.info("[初始化] 国金PTrade三层策略 | 标的%d | L1=%.0f%% L2=%.0f%% | TRADE=%s" %
             (len(STOCKS), L1_RATIO * 100, L2_RATIO * 100, TRADE_ENABLED))


# ============================== 五、盘前：L1 再平衡 + L2 信号 + 风控 ==============================
def _dt_now(context):
    """Current datetime: prefer context.blotter.current_dt (doc'd), fallback context.current_dt."""
    blotter = getattr(context, "blotter", None)
    if blotter is not None and hasattr(blotter, "current_dt"):
        return blotter.current_dt
    if hasattr(context, "current_dt"):
        return context.current_dt
    return None

def before_trading_start(context, data):
    g["ctx"] = context
    g["trade_days"] += 1
    dt = _dt_now(context)
    g["today"] = dt.strftime("%Y-%m-%d") if dt else ""
    g["noise_slot"] = {}
    g["t_rounds"] = {}
    g["t_pending"] = {}
    g["buy_codes"] = set()       # reset buy dedup per trading day

    acct = _account()
    if acct is None:
        log.warning("[盘前] 取不到账户，跳过本日")
        return
    total = acct.get("total_value", 0) or 0
    if total <= 0:
        return

    # 峰值跟踪
    if total > g["peak_total"]:
        g["peak_total"] = total
    dd = (total - g["peak_total"]) / g["peak_total"] if g["peak_total"] > 0 else 0.0
    log.info("[盘前] 总资产%.0f 峰值%.0f 回撤%.2f%%" % (total, g["peak_total"], dd * 100))

    _circuit_breaker(total, dd)
    _market_switch()

    # L1 季度再平衡（用已完成数据）
    if g["trade_days"] - g["last_reb_day"] >= L1_REBALANCE_DAYS:
        _l1_rebalance(total)
        g["last_reb_day"] = g["trade_days"]

    # L2 波段：日级信号（已完成数据：昨收为末根）
    if not g["circuit_halt"]:
        _l2_daily(total)

    # L1/L2 日级风控扫描（硬止损、移动止盈，用昨收近似；盘中另有 intraday 补刀）
    _daily_risk_scan()


def _l1_rebalance(total):
    log.info("[L1] 季度再平衡启动")
    for code in STOCKS:
        target_val = total * g["L1_W"][code]
        poss = _get_positions()
        cd = _canon(code)
        pos = poss.get(cd)
        cur_val = pos["current_amount"] * pos["current_price"] if pos else 0
        delta = target_val - cur_val
        # 再平衡也受 T+1 限制：减仓需可卖量
        if delta > 0:
            # L1 最短持有保护：建仓不足 L1_MIN_HOLD_DAYS 交易日不追买，防过度换手
            if _held_days(cd) < L1_MIN_HOLD_DAYS:
                log.info("[L1] %s 持仓不足%d日，跳过再平衡追买" % (code, L1_MIN_HOLD_DAYS))
            else:
                _do_buy_value(code, delta)
        elif delta < -1e-6:
            sell_qty = _round_lot(-delta / (pos["current_price"] or 1), code) if pos else 0
            if sell_qty > 0:
                _do_sell(code, sell_qty, "L1再平衡减仓")
        g["entry_px"][cd] = pos["cost_price"] if pos else 0


def _l2_daily(total):
    if not g.get("l2_enabled", True):
        return
    for code in L2_SET:
        h = _hist_lists(code, 30, "1d")
        if h is None:
            continue
        closes, opens, highs, lows, vols = h
        if len(closes) < 21:
            continue
        ma20 = _ma(closes, 20)
        rsi = _rsi(closes, 14)
        if ma20 is None or rsi is None:
            continue
        price = closes[-1]            # 已完成（昨收）
        prev_ma5_vol = _ma(vols[-6:-1], 5) or 1
        vol_ratio = vols[-1] / prev_ma5_vol if prev_ma5_vol > 0 else 1
        poss = _get_positions()
        cd = _canon(code)
        held = poss.get(cd, {}).get("current_amount", 0)

        # 买入信号：回调 + 地量 + RSI 共振（仅空仓或低仓时建）
        if held == 0:
            pullback = price <= ma20 * (1 - L2_PULLBACK_PCT)
            quiet = vol_ratio < L2_VOL_RATIO_MAX
            rsi_ok = L2_RSI_LO <= rsi <= L2_RSI_HI
            if pullback and quiet and rsi_ok and _turnover_ok():
                log.info("[L2-买] %s 价%.2f MA20%.2f 量比%.2f RSI%.1f" % (code, price, ma20, vol_ratio, rsi))
                _do_buy_value(code, total * g["L2_W"][code])
                g["entry_px"][cd] = price
                g["peak_px"][cd] = price
        else:
            # 持仓处理下放 _daily_risk_scan / intraday
            pass


def _daily_risk_scan():
    """L2 卫星仓日级退出（用已完成数据，盘前执行）：目标收益 / 超买 / 移动止盈。
    L1 核心仓长持，不在此处理（由断路器/市场开关保护）。"""
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        if code not in L2_SET:
            continue
        cost = g["entry_px"].get(cd) or pos["cost_price"]
        if cost <= 0:
            continue
        if _held_days(cd) < 1:
            continue
        h = _hist_lists(code, 30, "1d")
        if h is None:
            continue
        closes = h[0]
        price = closes[-1]            # 已完成（昨收）
        rsi = _rsi(closes, 14)
        pnl = price / cost - 1
        if price > g["peak_px"].get(cd, 0):
            g["peak_px"][cd] = price
        peak_rt = g["peak_px"].get(cd, cost) / cost - 1
        reason = None
        if pnl >= L2_TAKE_PCT:
            reason = "L2目标止盈+%.0f%%" % (L2_TAKE_PCT * 100)
        elif rsi is not None and rsi >= L2_RSI_SELL:
            reason = "L2超买RSI%.0f" % rsi
        elif peak_rt >= 0.05 and price <= g["peak_px"].get(cd, price) * (1 - L2_TRAIL_PCT):
            reason = "L2移动止盈回撤%.0f%%" % (L2_TRAIL_PCT * 100)
        if reason:
            log.info("[L2-卖] %s %s 浮盈%.2f%%" % (code, reason, pnl * 100))
            _do_sell(code, pos["enable_amount"], reason)
            _record_turn("L2退出", True)


def _held_days(cd):
    """Real holding days: diff from build day (trade_days); no record => long-held (large)."""
    bd = g.get("buy_day", {}).get(cd)
    if bd is None:
        return 9999
    return g.get("trade_days", 0) - bd
def _circuit_breaker(total, dd):
    """三级断路器：自高点回撤 -8% 停所有交易；-12% 砍1/3；-18% 再减半。"""
    if dd <= CB_STAGE3 and g["cb_stage"] < 3:
        g["cb_stage"] = 3
        g["circuit_halt"] = True
        log.warning("[断路器-3级] 回撤%.2f%% 全组合减半(剩余)" % (dd * 100))
        _cut_all(0.5)
    elif dd <= CB_STAGE2 and g["cb_stage"] < 2:
        g["cb_stage"] = 2
        g["circuit_halt"] = True
        log.warning("[断路器-2级] 回撤%.2f%% 砍1/3高位仓" % (dd * 100))
        _cut_all(1.0 / 3.0)
    elif dd <= CB_STAGE1 and g["cb_stage"] < 1:
        g["cb_stage"] = 1
        g["circuit_halt"] = True
        log.warning("[断路器-1级] 回撤%.2f%% 暂停一切新开仓" % (dd * 100))
    # 回升后解除 halt（但不回退已砍仓位）
    if dd > CB_STAGE1 and g["cb_stage"] == 1:
        g["circuit_halt"] = False
        g["cb_stage"] = 0
        log.info("[断路器] 回撤收敛，解除交易暂停")


def _cut_all(frac):
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        qty = _round_lot(pos["enable_amount"] * frac, code)
        if qty > 0:
            _do_sell(code, qty, "断路器减仓")


def _market_switch():
    """沪深300 均线市场开关（双向，可复位）。

    - 短均线(MKT_MA_SHORT=60)下方 -> L2 暂停新开；回到上方 -> L2 恢复新开（每日双向判定）。
    - 长均线(MKT_MA_LONG=120)下方 -> L1 砍两成、档位置 1；
      回到上方连续 MKT_RESET_CONFIRM_DAYS 个交易日后档位复位为 0，再次跌破可再减仓一次。
      复位只复位「档位标记」，不回补已砍仓位（与断路器口径一致），补仓交给下一次 L1 季度再平衡。
    - 均线判定取不到数据(None)时维持当前档位，仅打一次降级提示，不误复位。
    """
    below_short = _index_below_ma(INDEX_CODE, MKT_MA_SHORT)
    below_long = _index_below_ma(INDEX_CODE, MKT_MA_LONG)

    # ---- 短均线：L2 开/关（双向）----
    if below_short is None:
        if _noise_once("__mkt__", "nomkt"):
            log.warning("[市场开关] 沪深300 均线数据不足，判定跳过，维持当前档位")
    elif below_short:
        g["l2_enabled"] = False
        if _noise_once("__mkt__", "short"):
            log.warning("[市场开关] 沪深300 在%d日线下方 -> L2 暂停新开" % MKT_MA_SHORT)
    else:
        if not g.get("l2_enabled", True):
            log.info("[市场开关] 沪深300 回到%d日线上方 -> L2 恢复新开" % MKT_MA_SHORT)
        g["l2_enabled"] = True

    # ---- 长均线：L1 减仓档位（跌破砍两成；回到上方连续确认后复位）----
    if below_long is None:
        return
    if below_long:
        g["mkt_above_days"] = 0
        if g["mkt_stage"] < 1:
            g["mkt_stage"] = 1
            log.warning("[市场开关] 沪深300 在%d日线下方 -> L1 砍两成" % MKT_MA_LONG)
            poss = _get_positions()
            for cd, pos in poss.items():
                qty = _round_lot(pos["enable_amount"] * 0.2, pos["code"])
                if qty > 0:
                    _do_sell(pos["code"], qty, "市场开关L1减仓")
    else:
        g["mkt_above_days"] = g.get("mkt_above_days", 0) + 1
        if g["mkt_stage"] >= 1 and g["mkt_above_days"] >= MKT_RESET_CONFIRM_DAYS:
            g["mkt_stage"] = 0
            log.info("[市场开关] 沪深300 回到%d日线上方(连续%d日) -> L1 档位复位，再次跌破可再减仓"
                     % (MKT_MA_LONG, g["mkt_above_days"]))


# ============================== 七、盘中：L3 日内T + intraday 风控 ==============================
def handle_data(context, data):
    # 首根盘后初始化 intr 标记
    g["ctx"] = context
    dt = _dt_now(context)
    now = dt.strftime("%H:%M") if dt else ""
    if not g.get("intr_checked"):
        g["intr_checked"] = True
        p, src = _cur_price(STOCKS[0], data)
        g["intr_ok"] = (src != "none")
        if not g["intr_ok"]:
            log.warning("[口径-降级] handle_data 拿不到盘中价(data=None/snapshot空) -> L3日内T 自动关闭，仅保留日级 L1/L2")
        else:
            log.info("[口径] 盘中价来源=%s，L3日内T 可用" % src)

    if not g["intr_ok"] or not INTRADAY_T:
        return  # 无盘中价：L3 关闭，日级逻辑已在盘前完成

    # ---- intraday 硬止损补刀（风险类，只设下限 09:45）----
    if now >= "09:45":
        _intraday_hard_stop(data)

    # ---- L3 日内T ----
    if "09:45" <= now <= T_CLOSE:
        for code in L3_SET:
            _t_once(code, data, now)
    # 14:50 强制回补未平 T
    if now >= "14:50":
        _t_force_close(data)


def _intraday_hard_stop(data):
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        if code not in L2_SET:
            continue  # L1 核心仓：长持，日内不硬砍（仅 L2 卫星仓参与日内硬止损）
        if _held_days(cd) < 1:
            continue  # T+1 当日新仓不卖（§八之二 坑... 风控循环跳过 held<1）
        cost = g["entry_px"].get(cd) or pos["cost_price"]
        if cost <= 0:
            continue
        p, src = _cur_price(code, data)
        if p is None:
            continue
        pnl = p / cost - 1
        if pnl <= -L2_STOP_PCT:
            if _noise_once(cd, "istop"):
                log.warning("[intraday止损] %s 浮亏%.2f%% 现价%.2f 来源%s" % (code, pnl * 100, p, src))
            _do_sell(code, pos["enable_amount"], "intraday硬止损")
            _record_turn("L2硬止损", True)


def _t_once(code, data, now):
    cd = _canon(code)
    poss = _get_positions()
    pos = poss.get(cd)
    if not pos:
        return
    enable = pos["enable_amount"]
    if enable <= 0:
        return
    if g["t_rounds"].get(cd, 0) >= T_MAX_ROUNDS:
        return
    p, src = _cur_price(code, data)
    if p is None:
        return
    # VWAP（1m 窗口）
    vwap = _vwap(code, g.get("today", "") + " " + now)
    if vwap is None or vwap <= 0:
        return
    dev = p / vwap - 1
    cur_val = pos["current_amount"] * pos["current_price"]
    # 有未回补仓位 -> 低位或尾盘买回归（不增隔夜仓）
    if g["t_pending"].get(cd, 0) > 0:
        if dev <= 0 or now >= "14:45":
            buy_qty = min(g["t_pending"][cd], _round_lot(enable, code))
            if buy_qty > 0:
                if TRADE_ENABLED:
                    try:
                        order_target_value(code, cur_val + buy_qty * p)
                        g.setdefault("buy_day", {})[cd] = g.get("trade_days", 0)
                    except Exception as e:
                        log.warning("[T-回补] order 失败 %s: %s" % (code, e))
                        return
                else:
                    log.info("[信号-T回补] %s 数量%d 价%.2f" % (code, buy_qty, p))
                    g.setdefault("buy_day", {})[cd] = g.get("trade_days", 0)
                g["t_pending"][cd] -= buy_qty
                _record_turn("T", True)
    else:
        # 开新 T：高位偏离、edge 够，且在换手预算内（与"暂停新开 L2/L3"文案一致）
        if dev >= T_TRIGGER_PCT and dev >= T_EDGE_MIN and _turnover_ok():
            sell_qty = _round_lot(enable * T_MAX_FRAC, code)
            if sell_qty > 0:
                if TRADE_ENABLED:
                    try:
                        order_target_value(code, cur_val - sell_qty * p)
                    except Exception as e:
                        log.warning("[T-卖] order 失败 %s: %s" % (code, e))
                        return
                else:
                    log.info("[信号-T卖] %s 数量%d 价%.2f 偏离%.2f%%" % (code, sell_qty, p, dev * 100))
                g["t_pending"][cd] = g["t_pending"].get(cd, 0) + sell_qty
                g["t_rounds"][cd] = g["t_rounds"].get(cd, 0) + 1
                _record_turn("T")


def _t_force_close(data):
    for cd, qty in list(g.get("t_pending", {}).items()):
        if qty > 0:
            code = _canon_to_code(cd)
            poss = _get_positions()
            pos = poss.get(cd)
            if not pos:
                g["t_pending"][cd] = 0
                continue
            p, _ = _cur_price(code, data)
            if p is None:
                p = pos["current_price"]
            buy_qty = min(qty, _round_lot(pos["enable_amount"], code))
            if TRADE_ENABLED and buy_qty > 0:
                try:
                    order_target_value(code, pos["current_amount"] * pos["current_price"] + buy_qty * p)
                except Exception as e:
                    log.warning("[T-强平] order 失败 %s: %s" % (code, e))
            else:
                log.info("[信号-T强平] %s 数量%d" % (code, buy_qty))
            g["t_pending"][cd] = 0
            _record_turn("T", True)


def _canon_to_code(cd):
    for c in STOCKS:
        if _canon(c) == cd:
            return c
    return _suffix(cd)


def _vwap(code, minute=""):
    """VWAP over last T_VWAP_WIN 1m bars; None if unavailable. Cached per minute."""
    key = code + "|" + minute
    cache = g.get("_vwap_cache", {})
    if key in cache:
        return cache[key]
    try:
        bars = get_history(T_VWAP_WIN, "1m", ["close", "volume"], code)
    except Exception:
        return None
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        return None
    try:
        c = list(bars["close"])
        v = list(bars["volume"])
    except Exception:
        return None
    pv = 0.0
    tot = 0.0
    for i in range(len(c)):
        pv += float(c[i]) * float(v[i])
        tot += float(v[i])
    if tot <= 0:
        return None
    res = pv / tot
    cache[key] = res
    g["_vwap_cache"] = cache
    return res
def after_trading_end(context, data):
    st = g.get("STATS", {"n": 0, "by_reason": {}})
    days = max(1, g.get("trade_days", 1))
    annual = g.get("ytd_turns", 0) * 250.0 / days
    log.info("[统计] 累计回合%d 年化%.1f/上限%.1f 成本率%.3f" %
             (g.get("ytd_turns", 0), annual, MAX_ANNUAL_TURNS, COST_PER_TURN))
    for reason, (n, _s) in sorted(st["by_reason"].items()):
        log.info("[统计] %s: %d 笔" % (reason, n))
    # 盈亏比自洽检查（§十二）
    log.info("[自检] 止损上限%.0f%% <= 止盈上限%.0f%%*0.5 ? %s" %
             (L2_STOP_PCT * 100, L2_TAKE_PCT * 100, (L2_STOP_PCT <= L2_TAKE_PCT * 0.5)))
