# -*- coding: utf-8 -*-
# =============================================================================
# 热点融合 v1.0 —— 离线行为校验器
# 目的：在「不接实盘/不跑完整回测」的前提下，对策略的逐条退出分支与大市闸门
#       做确定性断言，捕捉逻辑死代码与参数错配。
# 分层：
#   L1 分支单测    —— 直接驱动 monitor_risk，对每条退出理由做断言
#   L2 大市检测    —— _update_regime / _update_sentiment 对指数/情绪数据的判定
#   L3 买入闸门    —— buy_job 在不同 regime 下是否建仓 / 减半
#   L4 端到端冒烟  —— 3 日 bull 剧本跑通整条 handle_data 链路不崩
# 运行：python fusion_validator.py  （本地 3.x 即可，非 PTrade 环境）
# =============================================================================

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STRAT_PATH = os.path.join(HERE, "hotspot_fusion_v1_ptrade.py")


# ----------------------------- 载入策略模块 --------------------------------
def load_strategy():
    spec = importlib.util.spec_from_file_location("fusion_strat", STRAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------- Mock 数据结构 -------------------------------
class Col(object):
    """1D 序列（指数用），支持 .values"""
    def __init__(self, vals):
        self.values = list(vals)


class Mat(object):
    """2D 矩阵（个股用），支持 .values = 行列表"""
    def __init__(self, rows):
        self.values = [list(r) for r in rows]


class Price(object):
    def __init__(self, price):
        self.price = float(price)


class Ctx(object):
    """模拟 PTrade context"""
    def __init__(self):
        self.blotter = type("B", (), {"current_dt": ""})()
        self.portfolio = type("P", (), {"portfolio_value": 0.0,
                                        "cash": 0.0, "positions": {}})()


# ----------------------------- 全局 Mock 市场 ------------------------------
class Market(object):
    def __init__(self):
        self.index = {}        # code -> close list
        self.stocks = {}       # code -> dict(open/close/high/low/volume/money/pre_close)
        self.industry = {}     # code -> 行业名
        self.pool = []         # get_Ashares 返回（无后缀）


MARKET = Market()


def set_market(index=None, stocks=None, industry=None, pool=None):
    MARKET.index = index or {}
    MARKET.stocks = stocks or {}
    MARKET.industry = industry or {}
    MARKET.pool = pool or []


# ----------------------------- Mock 平台接口 -------------------------------
def _build_obj(code, fields):
    """构造单只代码返回对象：指数->Col；个股->Mat（含 .values）。"""
    if code in MARKET.index:
        return Col(MARKET.index[code])
    if code not in MARKET.stocks:
        return None
    s = MARKET.stocks[code]
    if set(fields) == {"close", "pre_close"}:
        cl, pc = s["close"], s["pre_close"]
        # 时间升序：rows[-1]=今日, rows[-2]=昨日（与策略 _update_sentiment 约定一致）
        return Mat([[cl[-2], pc[-2]], [cl[-1], pc[-1]]])
    if fields == "close" or (isinstance(fields, list) and fields == ["close"]):
        return Mat([[x] for x in s["close"]])
    # 全量面板（scan_market 用）：open,close,high,low,volume,money,pre_close
    rows = []
    for i in range(len(s["close"])):
        rows.append([s["open"][i], s["close"][i], s["high"][i], s["low"][i],
                     s["volume"][i], s["money"][i], s["pre_close"][i]])
    return Mat(rows)


def get_history(count, freq, fields, codes):
    if isinstance(codes, str):
        codes = [codes]
    codes = [str(c) for c in codes]
    # 单只代码：PTrade 返回该只的 DataFrame（非 dict），供 _hist_closes 直接取
    if len(codes) == 1:
        return _build_obj(codes[0], fields)
    # 多只（指数对 / 个股面板 / 情绪池）：返回 dict{code: Mat/Col}
    res = {}
    for c in codes:
        v = _build_obj(c, fields)
        if v is not None:
            res[c] = v
    return res


def get_Ashares():
    return list(MARKET.pool)


def get_all_stocks():
    return list(MARKET.pool)


def get_industry(code):
    return MARKET.industry.get(str(code), "")


def get_snapshot(codes):
    return {}


# ----------------------------- 日志与下单捕获 ------------------------------
LOG_LINES = []
BUY_REC = []
SELL_REC = []


def mock_log():
    class L(object):
        def info(self, msg):
            LOG_LINES.append(str(msg))

        def warning(self, msg):
            LOG_LINES.append("WARN:" + str(msg))
    return L()


def order_target_value(code, value, limit_price=None):
    BUY_REC.append((str(code), float(value)))


def order_target(code, qty):
    SELL_REC.append((str(code), int(qty)))


def order(code, qty):
    SELL_REC.append((str(code), int(qty)))


def inject_platform(strat, ctx):
    strat.get_history = get_history
    strat.get_Ashares = get_Ashares
    strat.get_all_stocks = get_all_stocks
    strat.get_industry = get_industry
    strat.get_snapshot = get_snapshot
    strat.log = mock_log()
    strat.order_target_value = order_target_value
    strat.order_target = order_target
    strat.order = order
    return strat


# ----------------------------- 行情构造器 ----------------------------------
def make_bull_stock(code, n=65, start=50.0, final_pct=0.05, money=5e8,
                    industry=""):
    """生成一条满足所有粗筛/细评过滤的上升序列。"""
    closes, opens, highs, lows, vols, moneys, prec = [], [], [], [], [], [], []
    prev = start
    # 用恒定小幅上行，使末日 pct≈final_pct
    daily = (pow(1.0 + final_pct, 1.0 / (n - 1)) - 1.0) * 0.6
    for i in range(n):
        c = prev * (1.0 + daily)
        o = prev * (1.0 - 0.004)          # 开略低于昨收
        h = c * 1.02
        l = c * 0.98
        v = 1e6
        closes.append(c)
        opens.append(o)
        highs.append(h)
        lows.append(l)
        vols.append(v)
        moneys.append(money)
        prec.append(prev)
        prev = c
    # 把末日 pct 精确调整
    closes[-1] = prec[-1] * (1.0 + final_pct)
    highs[-1] = max(highs[-1], closes[-1] * 1.02)
    MARKET.stocks[code] = dict(open=opens, close=closes, high=highs,
                               low=lows, volume=vols, money=moneys,
                               pre_close=prec)
    if industry:
        MARKET.industry[code] = industry
    return code


def make_index(n=25, start=1000.0, trend=0.004):
    return [start * pow(1.0 + trend, i) for i in range(n)]


# ----------------------------- 测试框架 ------------------------------------
class Tester(object):
    def __init__(self):
        self.results = []

    def check(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        tag = "PASS" if cond else "FAIL"
        print("[%s] %s  %s" % (tag, name, ("-> " + detail) if detail else ""))

    def section(self, title):
        print("\n========== %s ==========" % title)


def fresh_state(strat, ctx, today="2026-05-06"):
    strat.initialize(ctx)
    g = strat.g
    g["today"] = today
    g["regime"] = "NORMAL"
    g["sentiment"] = "OK"
    g["entry_px"] = {}
    g["peak_px"] = {}
    g["hold_days"] = {}
    g["first_buy"] = {}
    g["winner_set"] = set()
    g["winner_peak_pnl"] = {}
    g["partial_done"] = set()
    g["sector_stops"] = []
    g["sector_cooldown_days"] = {}
    g["cool_down"] = {}
    g["buys_today"] = 0
    g["turn_log"] = []
    g["month_buys"] = {}
    return g


def set_position(ctx, g, code, amount, entry, peak, cur, hold):
    code6 = strat._pure(code)
    ctx.portfolio.positions = {code: {"amount": amount,
                                      "enable_amount": amount,
                                      "cost_basis": entry}}
    g["entry_px"][code6] = entry
    g["peak_px"][code6] = peak
    g["first_buy"][code6] = g["today"]
    g["hold_days"][code6] = hold
    DATA[code] = Price(cur)


DATA = {}


# ===========================================================================
# L1 分支单测
# ===========================================================================
def test_branch_stop_hard(strat, ctx, t):
    """硬止损：pnl<=-stop_pct(上限11%)，且 now>=09:45 -> 触发"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    set_position(ctx, g, code, 1000, entry=100.0, peak=100.0, cur=88.0, hold=3)
    ctx.blotter.current_dt = "2026-05-06 09:45:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.硬止损(下行>11%@09:45)",
            any("硬止损" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_stop_hard_gate(strat, ctx, t):
    """硬止损时间闸门：now=09:40 不应触发硬止损"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    set_position(ctx, g, code, 1000, entry=100.0, peak=100.0, cur=88.0, hold=3)
    ctx.blotter.current_dt = "2026-05-06 09:40:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.硬止损时间闸门(09:40不触发)",
            not any("硬止损" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_breakeven(strat, ctx, t):
    """保本止损：峰值曾>=3% 且 回撤至成本线 -> 应触发（修正前为死代码）"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    # entry=100, peak=110(+10%), cur 回落到 100(回到成本)
    set_position(ctx, g, code, 1000, entry=100.0, peak=110.0, cur=100.0, hold=4)
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.保本止损(峰值+10%回落至成本)",
            any("保本止损" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_partial(strat, ctx, t):
    """分批止盈：pnl>=+10% 且 未减半过 -> 减半"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    set_position(ctx, g, code, 1000, entry=100.0, peak=112.0, cur=110.0, hold=2)
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.分批止盈(+10%减半)",
            any("减半" in ln for ln in LOG_LINES),
            "sells=%s" % SELL_REC)


def test_branch_trailing(strat, ctx, t):
    """移动止盈：峰值>=+5% 武装，回撤>=15% -> 清仓"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    # entry=100, peak=120(+20%), cur=120*0.85=102(回撤15%)
    set_position(ctx, g, code, 1000, entry=100.0, peak=120.0, cur=102.0, hold=3)
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.移动止盈(峰值+20%回撤15%)",
            any("移动止盈" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_winner(strat, ctx, t):
    """赢家锁利：峰值>=+15% 且 自峰值回撤>=8pp -> 清仓（先模拟已减半）"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    # entry=100, peak=130(+30%), cur=115(峰值回撤10.4pp)；partial_done 模拟此前+10%已减半
    set_position(ctx, g, code, 500, entry=100.0, peak=130.0, cur=115.0, hold=3)
    g["partial_done"] = {strat._pure(code)}
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.赢家锁利(峰值+30%回撤10.4pp)",
            any("赢家锁利" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_takefull(strat, ctx, t):
    """止盈全清：pnl>=+30% -> 清仓（先模拟已减半）"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    set_position(ctx, g, code, 500, entry=100.0, peak=131.0, cur=131.0, hold=2)
    g["partial_done"] = {strat._pure(code)}
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.止盈全清(+31%)",
            any("止盈全清" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_break20(strat, ctx, t):
    """破20日线：尾盘确认，cur<ma20 且 pnl>=0(避破10) -> 清仓"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    # 构造一条先涨后跌破 ma20 但仍在成本上方的序列
    n = 65
    closes = [50.0 * (1.0 + 0.01 * i) for i in range(n - 5)]  # 上升
    for _ in range(5):
        closes.append(closes[-1] * 0.99)                       # 末5日小跌
    closes[-1] = 60.0                                          # 末日价=60（>=entry）
    MARKET.stocks[code] = dict(
        open=[c * 0.999 for c in closes], close=closes,
        high=[c * 1.01 for c in closes], low=[c * 0.99 for c in closes],
        volume=[1e6] * n, money=[5e8] * n, pre_close=[50.0] + closes[:-1])
    set_position(ctx, g, code, 1000, entry=58.0, peak=65.0, cur=60.0, hold=10)
    ctx.blotter.current_dt = "2026-05-06 14:45:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.破20日线(尾盘确认)",
            any("破20日线" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_timestop(strat, ctx, t):
    """时间止损：亏损持仓且 hold>=5 日 -> 清仓"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    set_position(ctx, g, code, 1000, entry=100.0, peak=100.0, cur=98.0, hold=5)
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.时间止损(亏损持仓>=5日)",
            any("时间止损" in ln for ln in LOG_LINES),
            "logs=%s" % [l for l in LOG_LINES if "卖出" in l])


def test_branch_sector_cool(strat, ctx, t):
    """板块冷却：同行业 20 日内连败>=2 -> 冷却10日"""
    g = fresh_state(strat, ctx)
    strat._industry_of = lambda c: "半导体"   # 固定行业便于断言
    g["today"] = "2026-05-06"
    strat._on_stop("600001.SS", g, {})
    g["today"] = "2026-05-10"
    strat._on_stop("600002.SS", g, {})
    t.check("L1.板块冷却(连败>=2->冷却10日)",
            g["sector_cooldown_days"].get("半导体") == 10,
            "cooldown=%s" % g["sector_cooldown_days"])


def test_branch_turnover(strat, ctx, t):
    """换手熔断：窗口内笔数过多 -> _turnover_ok 返回 False"""
    g = fresh_state(strat, ctx)
    g["today"] = "2026-05-20"
    g["turn_log"] = [("2026-05-06", "BUY")] * 60   # 60 笔密集
    t.check("L1.换手熔断(密集交易触发)",
            strat._turnover_ok() is False,
            "annualized 超限")
    g2 = fresh_state(strat, ctx)
    g2["today"] = "2026-05-20"
    g2["turn_log"] = [("2026-05-06", "BUY"), ("2026-05-08", "SELL")]
    t.check("L1.换手熔断(低频不触发)",
            strat._turnover_ok() is True,
            "annualized 正常")


def test_atr_clamp(strat, ctx, t):
    """ATR 止损自适应 clamp[5%,11%]"""
    g = fresh_state(strat, ctx)
    # 低波动序列 -> 应被夹到下限 5%
    code = "600001.SS"
    MARKET.stocks[code] = dict(
        open=[100.0] * 20, close=[100.0 + i * 0.05 for i in range(20)],
        high=[101.0] * 20, low=[99.0] * 20, volume=[1e6] * 20,
        money=[5e8] * 20, pre_close=[100.0] * 20)
    lo = strat._stop_pct("600001", 100.0, 95.0)
    # 高波动序列 -> 应被夹到上限 11%
    MARKET.stocks[code] = dict(
        open=[100.0] * 20,
        close=[100.0 * (1.2 if i % 2 else 0.8) for i in range(20)],
        high=[120.0] * 20, low=[80.0] * 20, volume=[1e6] * 20,
        money=[5e8] * 20, pre_close=[100.0] * 20)
    hi = strat._stop_pct("600001", 100.0, 95.0)
    t.check("L1.ATR止损下限clamp=5%",
            0.049 < lo < 0.051, "lo=%.4f" % lo)
    t.check("L1.ATR止损上限clamp=11%",
            0.109 < hi < 0.111, "hi=%.4f" % hi)


# ===========================================================================
# L2 大市状态检测
# ===========================================================================
def test_regime_up(strat, ctx, t):
    g = fresh_state(strat, ctx)
    set_market(index={"000852.SS": make_index(25, trend=0.005),
                      "000300.SS": make_index(25, trend=0.004)})
    strat._update_regime(ctx)
    t.check("L2.大市上升市->NORMAL",
            g["regime"] == "NORMAL", "regime=%s" % g["regime"])


def test_regime_halt(strat, ctx, t):
    g = fresh_state(strat, ctx)
    set_market(index={"000852.SS": make_index(25, start=1200.0, trend=-0.01),
                      "000300.SS": make_index(25, start=1200.0, trend=-0.006)})
    strat._update_regime(ctx)
    t.check("L2.大市下跌市(中证1000<MA20)->HALT",
            g["regime"] == "HALT", "regime=%s" % g["regime"])


def test_regime_pause(strat, ctx, t):
    g = fresh_state(strat, ctx)
    set_market(index={"000852.SS": make_index(25, trend=0.004),      # 小盘强
                      "000300.SS": make_index(25, start=1200.0, trend=-0.01)})  # 宽基弱
    strat._update_regime(ctx)
    t.check("L2.大市(沪深300<MA20,中证1000强)->PAUSE",
            g["regime"] == "PAUSE", "regime=%s" % g["regime"])


def _sent_stock(code, zt):
    pc = 100.0
    cl = pc * 1.10 if zt else pc * 1.01
    # 提供 2 行（昨/今），rows[-1]=今日, rows[-2]=昨日
    return dict(open=[pc, cl], close=[pc, cl], high=[cl, cl],
                low=[pc, pc], volume=[1e6, 1e6], money=[5e8, 5e8],
                pre_close=[pc, pc])


def test_sentiment_ok(strat, ctx, t):
    g = fresh_state(strat, ctx)
    # 30 只票，26 只涨停 -> zt>=25 -> 非冰点
    stocks = {}
    pool = []
    for i in range(30):
        code = "600%03d.SS" % (100 + i)
        stocks[code] = _sent_stock(code, zt=(i < 26))
        pool.append(code)
    set_market(stocks=stocks, pool=pool)
    strat._update_sentiment(ctx)
    t.check("L2.情绪(涨停>=25)->OK",
            g["sentiment"] == "OK", "sentiment=%s" % g["sentiment"])


def test_sentiment_ice(strat, ctx, t):
    g = fresh_state(strat, ctx)
    # 8 只票，仅 1 只涨停 -> zt<25 -> 冰点
    stocks = {}
    pool = []
    for i in range(8):
        code = "600%03d.SS" % (200 + i)
        stocks[code] = _sent_stock(code, zt=(i == 0))
        pool.append(code)
    set_market(stocks=stocks, pool=pool)
    strat._update_sentiment(ctx)
    t.check("L2.情绪(涨停<25)->ICE",
            g["sentiment"] == "ICE", "sentiment=%s" % g["sentiment"])


# ===========================================================================
# L3 买入闸门
# ===========================================================================
def build_candidates(strat, codes, industry="半导体"):
    cands = []
    for code in codes:
        make_bull_stock(code, industry=industry, final_pct=0.05)
        cands.append({"code": code, "score": 10.0, "ind": industry,
                      "f": {"last": 100.0, "highs": [100.0],
                            "opens": [99.0]}})
    return cands


def test_buy_normal(strat, ctx, t):
    g = fresh_state(strat, ctx)
    g["regime"] = "NORMAL"
    ctx.portfolio.cash = 1_000_000.0
    ctx.portfolio.portfolio_value = 1_000_000.0
    g["candidates"] = build_candidates(strat, ["600301.SS", "600302.SS"])
    DATA.clear()
    for c in ["600301.SS", "600302.SS"]:
        DATA[c] = Price(100.0)
    ctx.blotter.current_dt = "2026-05-06 10:30:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.buy_job(ctx, DATA)
    t.check("L3.买入闸门(NORMAL建仓)",
            len(BUY_REC) >= 1 and g["buys_today"] <= strat.MAX_NEW_PER_DAY,
            "buys=%d today=%d" % (len(BUY_REC), g["buys_today"]))


def test_buy_halt(strat, ctx, t):
    g = fresh_state(strat, ctx)
    g["regime"] = "HALT"
    ctx.portfolio.cash = 1_000_000.0
    ctx.portfolio.portfolio_value = 1_000_000.0
    g["candidates"] = build_candidates(strat, ["600303.SS", "600304.SS"])
    DATA.clear()
    for c in ["600303.SS", "600304.SS"]:
        DATA[c] = Price(100.0)
    ctx.blotter.current_dt = "2026-05-06 10:30:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.buy_job(ctx, DATA)
    t.check("L3.买入闸门(HALT不建仓)",
            len(BUY_REC) == 0 and any("暂停新建仓" in ln for ln in LOG_LINES),
            "buys=%d logs=%s" % (len(BUY_REC),
                                 [l for l in LOG_LINES if "买入" in l]))


def test_buy_pause(strat, ctx, t):
    g = fresh_state(strat, ctx)
    g["regime"] = "PAUSE"
    ctx.portfolio.cash = 1_000_000.0
    ctx.portfolio.portfolio_value = 1_000_000.0
    g["candidates"] = build_candidates(strat, ["600305.SS", "600306.SS"])
    DATA.clear()
    for c in ["600305.SS", "600306.SS"]:
        DATA[c] = Price(100.0)
    ctx.blotter.current_dt = "2026-05-06 10:30:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.buy_job(ctx, DATA)
    t.check("L3.买入闸门(PAUSE不建仓)",
            len(BUY_REC) == 0, "buys=%d" % len(BUY_REC))


def test_buy_half(strat, ctx, t):
    g = fresh_state(strat, ctx)
    g["regime"] = "HALF"
    ctx.portfolio.cash = 1_000_000.0
    ctx.portfolio.portfolio_value = 1_000_000.0
    g["candidates"] = build_candidates(strat, ["600307.SS"])
    DATA.clear()
    DATA["600307.SS"] = Price(100.0)
    ctx.blotter.current_dt = "2026-05-06 10:30:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.buy_job(ctx, DATA)
    # HALF 模式预算系数 0.5，单票上限 25%
    base = min(1_000_000.0 * 0.90, 1_000_000.0 * 0.17 * 6) * 0.5
    cap = 1_000_000.0 * 0.25
    expect = min(base, cap)
    t.check("L3.买入闸门(HALF预算减半)",
            len(BUY_REC) == 1 and BUY_REC[0][1] <= expect + 1.0,
            "alloc=%.0f expect<=%.0f" % (BUY_REC[0][1] if BUY_REC else 0, expect))


# ===========================================================================
# L4 端到端冒烟
# ===========================================================================
def test_smoke_e2e(strat, ctx, t):
    """3 日 bull 剧本：建仓 -> 次日触发止盈/止损链路不崩"""
    g = fresh_state(strat, ctx, today="2026-05-06")
    set_market(index={"000852.SS": make_index(25, trend=0.005),
                      "000300.SS": make_index(25, trend=0.004)})
    build_candidates(strat, ["600401.SS", "600402.SS"], industry="半导体")
    ctx.portfolio.cash = 1_000_000.0
    ctx.portfolio.portfolio_value = 1_000_000.0
    DATA.clear()
    for c in ["600401.SS", "600402.SS"]:
        DATA[c] = Price(100.0)
    try:
        # Day1 10:30 建仓
        ctx.blotter.current_dt = "2026-05-06 10:30:00"
        strat.before_trading_start(ctx, DATA)
        strat.handle_data(ctx, DATA)
        day1_buys = len(BUY_REC)
        # Day2 盘中巡检（价格假设回落到成本，触发保本/时间等分支）
        g["today"] = "2026-05-07"
        for c in ["600401.SS", "600402.SS"]:
            if strat._pure(c) in g["entry_px"]:
                DATA[c] = Price(g["entry_px"][strat._pure(c)])  # 回到成本
        ctx.blotter.current_dt = "2026-05-07 14:45:00"
        strat.handle_data(ctx, DATA)
        t.check("L4.端到端冒烟(建仓+巡检无异常)",
                True, "day1_buys=%d" % day1_buys)
    except Exception as e:
        t.check("L4.端到端冒烟(建仓+巡检无异常)", False, "EXC=%s" % e)


# ===========================================================================
def main():
    global strat, ctx
    strat = load_strategy()
    ctx = Ctx()
    inject_platform(strat, ctx)
    t = Tester()
    t.section("L1 退出分支单测")
    for fn in [test_branch_stop_hard, test_branch_stop_hard_gate,
               test_branch_breakeven, test_branch_partial,
               test_branch_trailing, test_branch_winner, test_branch_takefull,
               test_branch_break20, test_branch_timestop,
               test_branch_sector_cool, test_branch_turnover, test_atr_clamp]:
        fn(strat, ctx, t)
    t.section("L2 大市状态检测")
    for fn in [test_regime_up, test_regime_halt, test_regime_pause,
               test_sentiment_ok, test_sentiment_ice]:
        fn(strat, ctx, t)
    t.section("L3 买入闸门")
    for fn in [test_buy_normal, test_buy_halt, test_buy_pause, test_buy_half]:
        fn(strat, ctx, t)
    t.section("L4 端到端冒烟")
    test_smoke_e2e(strat, ctx, t)

    passed = sum(1 for _, ok, _ in t.results if ok)
    total = len(t.results)
    print("\n================ 汇总 ================")
    print("通过 %d / %d" % (passed, total))
    fails = [n for n, ok, _ in t.results if not ok]
    if fails:
        print("失败项：")
        for n in fails:
            print("  - " + n)
    # 落盘报告
    report = os.path.join(HERE, "fusion_validator_report.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write("热点融合 v1.0 离线行为校验报告\n")
        f.write("通过 %d / %d\n\n" % (passed, total))
        for n, ok, d in t.results:
            f.write("[%s] %s  %s\n" % ("PASS" if ok else "FAIL", n, d))
    print("报告已写：%s" % report)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
