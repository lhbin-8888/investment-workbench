# -*- coding: utf-8 -*-
# =============================================================================
# 热点融合 v1.1 —— 离线行为校验器
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
import re
import sys
import datetime

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
    """2D 矩阵（个股用）。真实平台 DataFrame 同时有 .values 与 .columns，
    故 Mock 必须一并提供，否则「按列名取数」的策略逻辑在离线测试里跑不到。"""
    def __init__(self, rows, columns=None):
        self.values = [list(r) for r in rows]
        self.columns = list(columns) if columns else None


class Rec(object):
    """模拟 numpy 结构化标量：支持 rec['close']（按名）与 rec[2]（按位）。"""
    def __init__(self, names, vals):
        self._names = list(names)
        self._vals = list(vals)

    def __getitem__(self, k):
        if isinstance(k, str):
            return self._vals[self._names.index(k)]
        return self._vals[k]

    def __len__(self):
        return len(self._vals)


class StructArr(object):
    """模拟 numpy 结构化数组 —— 本平台 get_history(is_dict=True) 每值的【真实形态】。

    【为什么必须用它做 Mock，而不是继续用 Mat】
      001 日志实测：`[诊断] 首值 type=ndarray len=70 repr=array([(20260114, 32.14,
      32.15, 33.74, 31.6, 4748482.), ...])`，即 dtype.names=('date','open','close',
      'high','low','volume')。用 Mat（.values 是 list[list]）做 Mock 会把
      「结构化标量不可迭代」这条真实路径整个绕过 —— 结果就是离线全绿、上线 0 票。
      为了让校验器真的在测生产路径，Mock 必须复刻 dtype.names 与列顺序。
    """
    class _DT(object):
        def __init__(self, names):
            self.names = tuple(names)

    def __init__(self, names, recs):
        self.dtype = StructArr._DT(names)
        self._recs = list(recs)

    def __len__(self):
        return len(self._recs)

    def __iter__(self):
        return iter(self._recs)

    def __getitem__(self, i):
        return self._recs[i]


# Mock 的"今天"与"日线末根日期"。默认末根=昨天 => 不含当日（走三层兜底路径）；
# 需要验证"含当日"路径的用例把 _MOCK["end_date"] 改成 _MOCK["today"]。
MOCK_TODAY_INT = 20260506
MOCK_END_INT = 20260505
_MOCK = {"today": MOCK_TODAY_INT, "end_date": MOCK_END_INT}


def _dates_back(n, end_int=None):
    """生成 n 个连续交易日（跳过周末）的 8 位整数日期，升序，末位=end_int。"""
    e = _MOCK["end_date"] if end_int is None else end_int
    d = datetime.date(e // 10000, (e // 100) % 100, e % 100)
    out = [int(d.strftime("%Y%m%d"))]
    while len(out) < n:
        d = d - datetime.timedelta(days=1)
        if d.weekday() < 5:
            out.append(int(d.strftime("%Y%m%d")))
    out.reverse()
    return out


class Price(object):
    def __init__(self, price):
        self.price = float(price)


class Bar(object):
    """模拟本平台 handle_data 的 Bar —— 本轮最致命陷阱的复刻。

    真实行为（1030 日志第 15 行实证）：
        样本 000001.SZ 昨收=11.13 data价=11.34 price字段=11.13 分钟close=11.13
    即：`float(bar)` = 当日价，而 `bar.price` = 昨收。策略若只按字段名读，就会把
    昨收当当日价，pct 恒 0，然后一声不响地全天 0 成交。
    """
    def __init__(self, today_px, prev_close, o=None, h=None, lo=None, v=None):
        self.price = float(prev_close)       # ← 陷阱：字段名给的是【昨收】
        self.close = float(prev_close)
        self.open = float(o if o is not None else prev_close)
        self.high = float(h if h is not None else prev_close)
        self.low = float(lo if lo is not None else prev_close)
        self.volume = float(v if v is not None else 0.0)
        self._today = float(today_px)

    def __float__(self):
        return self._today                   # ← 数值才是【当日价】


class BarData(object):
    """模拟 handle_data 的 data 容器（BarDict）：{code: Bar}。"""
    def __init__(self, bars):
        self._bars = dict(bars)

    def get(self, key, default=None):
        return self._bars.get(str(key), default)

    def __getitem__(self, key):
        return self._bars[str(key)]

    def keys(self):
        return list(self._bars.keys())

    def __contains__(self, key):
        return str(key) in self._bars


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
# 真实平台 get_history 认可的字段名（来自 2026-09-22 实盘回测的平台报错原文）。
# 昨收是 preclose（无下划线）；写成 pre_close 平台会直接拒绝。
PLATFORM_FIELDS = {"open", "high", "low", "close", "price", "volume", "money",
                   "preclose", "high_limit", "low_limit", "unlimited", "is_open"}
_FIELD_SRC = {"open": "open", "high": "high", "low": "low", "close": "close",
              "volume": "volume", "money": "money", "preclose": "pre_close"}
# 平台结构化数组的【固定列顺序】（001 日志实测），与请求顺序无关 ——
# 正是这一点要求策略必须"按字段名取列"，按位置取必然错列。
_STRUCT_ORDER = ("open", "close", "high", "low", "volume", "money", "preclose")


def _build_obj(code, fields):
    """构造单只返回对象：本平台 is_dict=True 时的真实形态 = 结构化数组。

    dtype.names = ('datetime',) + 平台固定顺序里被请求到的字段。

    【v1.4 关键】日期列在真实平台叫 **datetime**（不是 date）——证据是本轮 [诊断]
    打出的 `解析列=['close','datetime','high','low','open','volume']`。Mock 若继续
    用 'date'，策略里"查 date 列"的写法就永远不会失败，本轮那个 bug 也抓不出来。
    """
    fl = [fields] if isinstance(fields, str) else list(fields)
    fl = [f for f in fl if f not in ("date", "datetime")]
    names = ["datetime"] + [f for f in _STRUCT_ORDER if f in fl]
    names += [f for f in fl if f not in _STRUCT_ORDER and f not in names]
    if code in MARKET.index:
        cl = list(MARKET.index[code])
        n = len(cl)
        src = {"close": cl, "open": cl, "high": cl, "low": cl}
    elif code in MARKET.stocks:
        src = MARKET.stocks[code]
        n = len(src.get("close") or [])
    else:
        return None
    if n <= 0:
        return None
    dates = _dates_back(n)
    base_close = list(src.get("close") or [0.0] * n)
    cols = {}
    for nm in names:
        if nm == "datetime":
            cols[nm] = dates
            continue
        key = _FIELD_SRC.get(nm)
        series = src.get(key) if key else None
        if isinstance(series, (list, tuple)) and len(series) >= n:
            cols[nm] = list(series)
        elif nm in ("open", "high", "low"):
            cols[nm] = base_close          # 缺省用收盘价顶替（与平台 fill 行为同向）
        elif nm == "price":
            # 本平台 price 字段 = 日线末根收盘（即昨收），不是当日价 —— 这是陷阱点，
            # Mock 必须复刻：否则"按 price 字段取当日价"这条错路在离线永远是绿的。
            cols[nm] = base_close
        else:
            cols[nm] = [0.0] * n
    recs = []
    for i in range(n):
        recs.append(Rec(names, [cols[nm][i] for nm in names]))
    return StructArr(names, recs)


def get_history(count, freq, fields, codes, fq=None, is_dict=False):
    """严格模仿真实平台的三条行为，缺一条都会让离线校验失去意义：

      ① 非法字段名直接抛异常（宽松 Mock 会放过 pre_close 这类拼写错误）；
      ② 【is_dict=True 才返回 {代码: 结构化数组}】。本平台不传 is_dict 时返回
         空结果且不抛异常 —— 这正是 v1.2「分批 27 批、键数 0、日志无报错」的成因，
         必须由 Mock 复刻，否则"忘了传 is_dict"这个 bug 永远抓不出来；
      ③ 单只也走列表路径 → 恒返回 dict（与平台一致），由策略的 _hist() 自己解包。
    """
    if isinstance(codes, str):
        codes = [codes]
    codes = [str(c) for c in codes]
    fl = [fields] if isinstance(fields, str) else list(fields)
    bad = [f for f in fl if f not in PLATFORM_FIELDS]
    if bad:
        raise Exception(
            "function get_history: invalid field %s, valid fields are "
            "{'open', 'volume', 'is_open', 'money', 'high', 'price', "
            "'preclose', 'high_limit', 'low', 'unlimited', 'close', "
            "'low_limit'}, got %s (type: <class 'list'>)" % (bad, fl))
    if not is_dict:
        return {}
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
    """批量快照：把序列末元素当作「当日」提供给 scan_market 兜底取价。"""
    out = {}
    for c in codes:
        s = MARKET.stocks.get(str(c))
        if not s:
            continue
        px = s["close"][-1]
        out[str(c)] = {"last_px": px, "last_price": px, "price": px,
                       "open": s["open"][-1], "high": s["high"][-1],
                       "low": s["low"][-1], "volume": s["volume"][-1]}
    return out


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

        def error(self, msg):
            LOG_LINES.append("ERROR:" + str(msg))
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
    # 策略改为「每次按 first_buy 重算持有天数」（修复 held 被缓存固化成 0 的缺陷），
    # 因此夹具必须把 first_buy 设成 today 前 hold 个日历日，否则算出 held=0
    # 会被 T+1 判断跳过所有卖出分支。
    try:
        _d = datetime.date(*[int(x) for x in g["today"].split("-")])
        g["first_buy"][code6] = (_d - datetime.timedelta(days=int(hold))).strftime("%Y-%m-%d")
    except Exception:
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
    """赢家豁免移动止盈：peak>=12% 赢家回撤15% 应走赢家锁利而非移动止盈"""
    g = fresh_state(strat, ctx)
    code = "600001.SS"
    make_bull_stock(code, industry="半导体")
    # entry=100, peak=120(+20%赢家), cur=102(回撤15%) -> 赢家豁免④改走赢家锁利
    set_position(ctx, g, code, 1000, entry=100.0, peak=120.0, cur=102.0, hold=3)
    ctx.blotter.current_dt = "2026-05-06 10:00:00"
    BUY_REC[:] = []; SELL_REC[:] = []; LOG_LINES[:] = []
    strat.monitor_risk(ctx, DATA, "NORMAL")
    t.check("L1.赢家豁免移动止盈(改走赢家锁利)",
            any("赢家锁利" in ln for ln in LOG_LINES)
            and not any("移动止盈" in ln for ln in LOG_LINES),
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
    set_position(ctx, g, code, 1000, entry=58.0, peak=62.0, cur=60.0, hold=10)
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
    t.check("L1.ATR止损下限clamp=6%(v1.5)",
            0.059 < lo < 0.061, "lo=%.4f" % lo)
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
    t.check("L2.大市(v1.6 双弱:两指数同破MA20)->HALT",
            g["regime"] == "HALT", "regime=%s" % g["regime"])


def test_regime_pause(strat, ctx, t):
    # v1.6 分层：单弱不再「全停」→ 降为 HALF（半仓，降级但不缺席）。
    # v1.5 及以前此处断言 PAUSE，而 PAUSE 与 HALT 在买入闸门里行为完全一样
    # → 等价「任一指数破MA20就全停」，实测 16/39 天(41%)被误冻结。
    g = fresh_state(strat, ctx)
    set_market(index={"000852.SS": make_index(25, trend=0.004),      # 小盘强
                      "000300.SS": make_index(25, start=1200.0, trend=-0.01)})  # 宽基弱
    strat._update_regime(ctx)
    t.check("L2.大市(v1.6 单弱:沪深300<MA20,中证1000强)->HALF",
            g["regime"] == "HALF", "regime=%s" % g["regime"])

    g = fresh_state(strat, ctx)
    set_market(index={"000852.SS": make_index(25, start=1200.0, trend=-0.01),  # 小盘弱
                      "000300.SS": make_index(25, trend=0.004)})               # 宽基强
    strat._update_regime(ctx)
    t.check("L2.大市(v1.6 单弱:中证1000<MA20,沪深300强)->HALF",
            g["regime"] == "HALF", "regime=%s" % g["regime"])


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
# L0 平台契约（字段名白名单 / Mock 严格性）
# ===========================================================================
def test_static_field_whitelist(strat, ctx, t):
    """静态检查：策略源码里所有 get_history 的字段字面量必须在平台白名单内。

    针对 2026-09-22 实盘故障（pre_close -> invalid field -> 全天 0 成交）的
    永久防回归项。运行时测试只覆盖被调用到的分支，静态检查覆盖全部代码路径。
    """
    src = open(os.path.join(HERE, "hotspot_fusion_v1_ptrade.py"),
               encoding="utf-8", errors="replace").read()
    bad = []
    for call in re.findall(r"get_history\([^)]*\)", src):
        for lit in re.findall(r'"([a-z_]{2,})"', call):
            if lit in ("1d", "1m"):
                continue
            if lit not in PLATFORM_FIELDS:
                bad.append(lit)
    t.check("L0.静态: get_history 字段全部合法", not bad, "违规字段=%s" % bad)


def test_static_observability(strat, ctx, t):
    """静态检查：策略必须自带「可观测性三件套」。

    背景：v1.0 在真实 PTrade 上整段回测（39 个交易日）0 成交且**毫无提示**，
    事后只能靠肉眼翻日志才发现。三件套专门堵住这一类静默失败：
      ① 逐日 [净值] 快照 —— 否则回测跑完拿不到同口径净值曲线，无法与基准比；
      ② 空转看门狗 ---- 连续空仓 N 日主动报错，而不是安静躺着；
      ③ 取数失败升格为 error 并给排查顺序，而不是 _warn 后 return []。
    """
    src = open(os.path.join(HERE, "hotspot_fusion_v1_ptrade.py"),
               encoding="utf-8", errors="replace").read()
    has_net = "[净值]" in src
    t.check("L0.静态: 存在逐日 [净值] 快照输出", has_net,
            "缺失则回测后无法计算净值曲线" if not has_net else "")
    has_idle = "[空转告警]" in src
    t.check("L0.静态: 存在空转看门狗([空转告警])", has_idle,
            "缺失则整段 0 成交会被静默吞掉" if not has_idle else "")
    # 取数失败必须 log.error（预警级别不够，会被日志淹没）
    fail_block = re.findall(r"\[扫描\][^\n]*(?:取数失败|面板为空|有效票数为 0)[\s\S]{0,500}", src)
    loud = bool(fail_block) and "log.error" in fail_block[0]
    t.check("L0.静态: 扫描取数失败升格 log.error", loud,
            "" if loud else "仍为 _warn，失败会被日志淹没")


def test_static_version_fingerprint(strat, ctx, t):
    """静态检查：版本指纹唯一。

    实盘踩坑：修复后的 v1.1 代码没传上平台，跑的仍是 v1.0 —— 单看"
    跑完了没报错"是看不出来的，必须拿日志指纹对版本。
    """
    src = open(os.path.join(HERE, "hotspot_fusion_v1_ptrade.py"),
               encoding="utf-8", errors="replace").read()
    vers = re.findall(r"★FUSION (v[0-9.]+)★", src)
    # 不变量：① 至少一处指纹；② 所有指纹互相一致（避免头部注释残留旧版本号误导上传）；
    #         ③ 版本不低于 MIN_V（v1.0~v1.3 每一版各踩过一类"平台契约"坑：
    #            v1.0 字段名非法 / v1.1 日线不含当日bar / v1.2 is_dict / v1.3 data取值语义）
    vers_all = _ver_found(src)
    t.check("L0.静态: 版本指纹一致且已就位", _ver_ok(src),
            "指纹=%s（出现 %d 处，应完全一致且>=%s）"
            % (vers_all, len(re.findall(r"★FUSION (v[0-9.]+)★", src)), MIN_V))


MIN_V = "v1.8"


def _ver_found(src):
    """源码里出现的全部版本指纹（去重排序）。"""
    return sorted(set(re.findall(r"★FUSION (v[0-9.]+)★", src)),
                  key=lambda x: tuple(int(y) for y in x.lstrip("v").split(".")))


def _ver_ok(src):
    """版本指纹合法：唯一且 >= MIN_V。

    旧写法是每个版本手改 OR 链（'★FUSION v1.7★' in src，...），
    升一次版本要改 3 处，实测 v1.7/v1.8 连续两轮漏改导致假 FAIL。
    现在只留一个判据：找到的指纹唯一且 >= MIN_V。
    """
    vs = re.findall(r"★FUSION (v[0-9.]+)★", src)
    if not vs or len(set(vs)) != 1:
        return False
    key = tuple(int(y) for y in vs[0].lstrip("v").split("."))
    minv = tuple(int(y) for y in MIN_V.lstrip("v").split("."))
    return key >= minv


def test_mock_rejects_bad_field(strat, ctx, t):
    """运行时：Mock 必须像真实平台一样拒绝非法字段名 —— 否则回归测试形同虚设。"""
    ok = False
    try:
        get_history(2, "1d", ["close", "pre_close"], ["600001.SS"])
    except Exception as e:
        ok = "invalid field" in str(e)
    t.check("L0.平台契约: 非法字段名被拒绝", ok, "")


def test_no_prev_close_as_today(strat, ctx, t):
    """语义：日线末根是【昨收】，当日价三层全空时**必须假设定价兜底，不得弃票**。

    v1.2 行为修订（2026-09-22 真机实测）：
      旧行为=当日价取不到就 continue 弃票 → 回测无快照 → 全池弃票 → 有效 0、0 成交。
      新行为=退化为 001 已验证的保守假设定价（成交价=昨收×(1+ASSUME_ENTRY_PREMIUM)），
      量比/形态同步退化到昨日口径，并打 [口径-假设] 声明口径。

    构造"当日价三层全空"：把模拟平台的 get_snapshot 摘掉（回测确实不支持），
    并把批量分钟线通道打成空 —— 这正是真机第二轮跑出来的局面。
    守的不变量：不得崩，且**不得全池弃票**（有效票必须 > 0）。
    """
    g = fresh_state(strat, ctx)
    code = "600777.SS"
    make_bull_stock(code, industry="半导体")
    set_market(stocks={code: MARKET.stocks[code]}, pool=[code], industry={code: "半导体"})

    saved_snap = strat.__dict__.pop("get_snapshot", None)   # 模拟回测：不支持 get_snapshot
    saved_min = strat._minute_map
    saved_last = strat._minute_last
    strat._minute_map = lambda fields, codes, bars=0: {}     # 批量分钟线通道打空
    strat._minute_last = lambda code: None                   # 单只分钟线兜底也打空
    try:
        cands = strat.scan_market(ctx, None)
    except Exception as e:
        t.check("L1.当日价三层全空时不崩且不弃票", False, "EXC=%s" % e)
        return
    finally:
        strat._minute_map = saved_min
        strat._minute_last = saved_last
        if saved_snap is not None:
            strat.get_snapshot = saved_snap

    ok_cnt = g.get("last_scan_ok") or 0
    t.check("L1.当日价三层全空时不崩且不弃票", ok_cnt > 0,
            "last_scan_ok=%s（>0 说明走了假设定价兜底；=0 说明又退回「缺价就弃票」）"
            % g.get("last_scan_ok"))
    has_line = any("[口径-假设]" in x for x in LOG_LINES)
    t.check("L1.假设定价时打出口径声明行", has_line,
            "" if has_line else "日志中未见 [口径-假设]，口径未声明")


def test_mock_requires_is_dict(strat, ctx, t):
    """平台契约：不传 is_dict=True 时返回空、且【不抛异常】。

    这条必须由 Mock 复刻 —— 否则"忘了传 is_dict"这个 bug（v1.2 全天 0 成交、
    分批 27 批键数 0、日志无一行报错）在离线校验里永远是绿的。
    """
    make_bull_stock("600899.SS")
    r = get_history(3, "1d", ["close"], ["600899.SS"])
    t.check("L0.平台契约: 不传 is_dict 静默返回空", not r, "返回=%r" % (r,))
    r2 = get_history(3, "1d", ["close"], ["600899.SS"], fq="pre", is_dict=True)
    names = None
    if r2:
        names = getattr(getattr(list(r2.values())[0], "dtype", None), "names", None)
    t.check("L0.平台契约: is_dict=True 才返回结构化数组",
            bool(r2) and names and "datetime" in names,
            "键=%s dtype.names=%s（日期列真名=datetime）"
            % (list(r2.keys()) if r2 else [], names))


def test_structured_by_name(strat, ctx, t):
    """解析层：结构化数组必须【按 dtype.names 取列】，绝不能按位置。

    平台固定列序是 (date, open, close, high, low, volume)，与请求顺序无关；
    按位置取会把 date 当 open —— 不报错，但整批票全错（最隐蔽的一类）。
    """
    names = ("date", "low", "high", "open", "volume", "close")
    recs = [Rec(names, (20260505, 10.0, 30.0, 20.0, 500.0, 25.0)),
            Rec(names, (20260506, 11.0, 31.0, 21.0, 700.0, 26.0))]
    rows, idx = strat._sub_rows(StructArr(names, recs),
                                ["open", "close", "high", "low", "volume"])
    cl = strat._col(rows, idx, "close")
    lo = strat._col(rows, idx, "low")
    dt = strat._col(rows, idx, "date")
    ok = (cl == [25.0, 26.0] and lo == [10.0, 11.0] and dt == [20260505.0, 20260506.0])
    t.check("L1.结构化数组按字段名解析(乱序列)", ok,
            "close=%s low=%s date=%s（若 close=[20,21] 说明退化成按位置取列）"
            % (cl, lo, dt))


def test_hist_style_probe(strat, ctx, t):
    """取数协议层：应探测命中 dict+fq 形态并缓存复用，而不是每批重试四档。"""
    strat._DS["style"] = None
    strat._DS["style_name"] = "未探测"
    make_bull_stock("600801.SS", industry="半导体")
    set_market(index={"000300.SS": make_index(), "000852.SS": make_index()},
               stocks={"600801.SS": MARKET.stocks["600801.SS"]},
               industry={"600801.SS": "半导体"}, pool=["600801"])
    fresh_state(strat, ctx)
    strat.scan_market(ctx, None)
    name = strat._DS.get("style_name")
    t.check("L1.取数形态探测命中 dict+fq", name == "dict+fq",
            "style_name=%s（若是 plain(兜底) 说明四档全空 → 面板必空）" % name)


def test_bar_today_intraday(strat, ctx, t):
    """口径自适应：日线末根=当日进行中 bar 时，当日价直接用末根、昨收取倒数第二根，
    bar_today 命中，且完全不依赖快照 —— 这是 001 实测的平台口径。"""
    old_dt = ctx.blotter.current_dt
    old_end = _MOCK["end_date"]
    try:
        ctx.blotter.current_dt = "2026-05-06 10:30:00"
        _MOCK["end_date"] = MOCK_TODAY_INT          # 末根=当天
        stocks = {}
        ind = {}
        # 同行业 2 只（共振闸门 MIN_SECTOR_ALIGN=2），末根放量使量比达标
        for cd in ("600802.SS", "600803.SS"):
            # v1.8：主板区间 3%~4%，mock 用 +3.5%
            make_bull_stock(cd, final_pct=0.035, industry="半导体")
            s = MARKET.stocks[cd]
            n = len(s["volume"])
            s["volume"] = [1e6] * (n - 1) + [1e7]
            stocks[cd] = s
            ind[cd] = "半导体"
        set_market(index={"000300.SS": make_index(), "000852.SS": make_index()},
                   stocks=stocks, industry=ind, pool=["600802", "600803"])
        g = fresh_state(strat, ctx)
        # v1.7：策略改为「内嵌表优先」，会抢在 mock 之前命中；本用例测的是涨幅
        # 算法 + 共振闸门，故显式注入 mock 行业表覆盖内嵌表（同文件其它用例同款）。
        g["ind_rev"] = {"600802": "半导体", "600803": "半导体"}
        cands = strat.scan_market(ctx, None)
        bt = g.get("diag_bar_today") or 0
        t.check("L1.日线含当日时 bar_today 命中", bt >= 2, "bar_today=%s" % bt)
        hit = [c for c in (cands or []) if c["code"] == "600802.SS"]
        got = hit[0]["f"]["pct"] if hit else None
        t.check("L1.含当日时涨幅=(末根/倒数第二根-1)", got is not None and abs(got - 0.035) < 0.01,
                "pct=%s（应为 0.05）" % (None if got is None else round(got, 4)))
        t.check("L1.含当日时日志声明口径",
                any("日线含当日bar" in x for x in LOG_LINES), "")
    finally:
        ctx.blotter.current_dt = old_dt
        _MOCK["end_date"] = old_end


def test_date_col_alias_datetime(strat, ctx, t):
    """v1.4 修复：日期列在真实平台叫 `datetime`，别名表必须能取到。

    证据：本轮 [诊断] 打印 `解析列=['close','datetime','high','low','open','volume']`。
    旧代码硬查 "date" → 恒取空 → has_today 恒 False → 口径判定与量比/形态全部退化，
    且日志照样写"日线不含当日bar"（假判定），把排查带偏了一整轮。
    """
    names = ("datetime", "close", "open")
    recs = [Rec(names, (20260505, 25.0, 20.0)), Rec(names, (20260506, 26.0, 21.0))]
    rows, idx = strat._sub_rows(StructArr(names, recs), ["open", "close"])
    dt = strat._col_first(rows, idx, strat.DATE_COL_ALIASES)
    t.check("L0.日期列别名命中(datetime)", dt == [20260505.0, 20260506.0],
            "取到=%s（若为 None 说明别名表没覆盖平台真实列名）" % dt)
    has = "datetime" in tuple(strat.DATE_COL_ALIASES)
    t.check("L0.别名表含 datetime", has, "别名=%s" % (list(strat.DATE_COL_ALIASES),))


def test_data_object_value_is_today_price(strat, ctx, t):
    """★本轮根因回归★ data 对象【数值】=当日价，而 `.price` 字段=昨收。

    平台实证（1030 日志第 15 行原文）：
        样本 000001.SZ 昨收=11.13 data价=11.34 price字段=11.13 分钟close=11.13
    v1.3 的取价只按字段名读（price/last_px/close）→ 当日价恒=昨收 → pct 恒 0
    → 涨幅区间 [3.5%,6%] 全灭 → 粗筛恒空 → 全天 0 成交（且一行报错都没有）。

    本用例构造"字段名=昨收、数值=当日价"的 Bar，断言策略必须选中【数值】这条正确
    通道；夹具本身也自证陷阱已复现，避免出现"假绿"。
    """
    ctx.blotter.current_dt = "2026-05-06 10:30:00"
    stocks, ind, bars = {}, {}, {}
    for cd in ("600801.SS", "600802.SS"):
        make_bull_stock(cd, n=65, start=50.0, final_pct=0.0, money=5e9,
                        industry="半导体")
        s = MARKET.stocks[cd]
        prev = s["close"][-1]                  # 日线末根 = 昨收（日线不含当日）
        # v1.8：主板涨幅区间已对齐 lhb888 收窄为 3%~4%，mock 用 +3.5%
        #（本用例测的是「data 数值=当日价」这条取值通道，不是涨幅闸门）
        today = prev * 1.035
        s["money"] = [5e9] * len(s["close"])
        stocks[cd] = s
        ind[cd] = "半导体"
        bars[cd] = Bar(today, prev, o=prev * 1.01, h=today * 1.002, lo=prev, v=3e6)
        bars[strat._pure(cd)] = bars[cd]
    set_market(index={"000300.SS": make_index(), "000852.SS": make_index()},
               stocks=stocks, industry=ind, pool=["600801", "600802"])
    g = fresh_state(strat, ctx)
    g["ind_rev"] = {"600801": "半导体", "600802": "半导体"}   # 离线注入行业表
    LOG_LINES[:] = []
    one = bars["600801.SS"]
    t.check("L1.夹具自证: Bar.price==昨收(陷阱已复现)",
            abs(one.price - one._today) > 1e-6,
            "字段price=%s 数值=%s" % (one.price, one._today))
    try:
        cands = strat.scan_market(ctx, BarData(bars))
    except Exception as e:
        t.check("L1.data数值优先取到当日价", False, "EXC=%s" % e)
        return
    hit = [c for c in (cands or []) if c["code"] == "600801.SS"]
    got = hit[0]["f"]["pct"] if hit else None
    t.check("L1.data数值优先取到当日价(pct=+3.5%)",
            got is not None and abs(got - 0.035) < 0.005,
            "pct=%s（若为 0.0 说明又只按字段名读→拿到昨收）"
            % (None if got is None else round(got, 4)))
    srcs = [c["f"].get("px_src") for c in (cands or [])]
    t.check("L1.当日价来源标为 data", "data" in srcs, "来源=%s" % srcs)
    t.check("L1.口径自证行存在", any("当日价来源=" in x for x in LOG_LINES),
            "缺失则下次再出问题仍无法一眼定位")


def test_static_v14_contract(strat, ctx, t):
    """静态检查：v1.4 四条修复必须固化在源码里，且不许回退。"""
    src = open(os.path.join(HERE, "hotspot_fusion_v1_ptrade.py"),
               encoding="utf-8", errors="replace").read()
    # ① 当日价必须带"与昨收相等即作废"的 guard（1030 源码 1186/1188 行同款）
    guard = bool(re.search(r"abs\(v\s*-\s*prev_close\)\s*>\s*eps", src))
    t.check("L0.静态: 当日价每层拒绝「==昨收」的 guard", guard,
            "" if guard else "缺 guard → 会把昨收当当日价，pct 恒 0 且不报错")
    # ② 数值优先：_bar_price 必须先试 float(obj)
    val_first = "def _bar_price(" in src and bool(
        re.search(r"v = _num\(obj\)", src))
    t.check("L0.静态: data 取值「数值优先」", val_first,
            "" if val_first else "又变成只按字段名读 price → 拿到昨收")
    # ③ 行业表：外挂 sector_map + 失败必 error
    has_map = "SECTOR_MAP_PATHS" in src and "sector_map.json" in src
    t.check("L0.静态: 行业归属走外挂 sector_map", has_map,
            "" if has_map else "行业恒为空 → 行业均值+共振整层失效")
    loud = bool(re.search(r'\[行业\][\s\S]{0,200}log\.error', src))
    t.check("L0.静态: 行业表载入失败升格 log.error", loud,
            "" if loud else "载入失败静默 → 候选全归空行业且无人知晓")
    # ④ 粗筛漏斗：粗筛为空时必须能看出死在哪道闸
    funnel = "[粗筛]" in src and "涨幅区间淘汰" in src
    t.check("L0.静态: 存在 [粗筛] 漏斗日志", funnel,
            "" if funnel else "粗筛为空时无法定位是哪道闸杀的")
    # ⑤ 版本指纹（4 行：启动 + 3 行 [指纹]）
    n_fp = src.count("[指纹]")
    t.check("L0.静态: 指纹行数>=3", n_fp >= 3, "[指纹] 出现 %d 次" % n_fp)




def test_static_v15_contract(strat, ctx, t):
    src = open(os.path.join(HERE, 'hotspot_fusion_v1_ptrade.py'),
               encoding='utf-8', errors='replace').read()
    self_calc = 'equity = cash + pos_value' in src and '持仓市值' in src
    t.check('L0.静态: 净值自算持仓市值(修HALT计价bug)', self_calc,
            '' if self_calc else '仍只读 portfolio_value 导致 HALT 日持仓市值记0')
    passed = 'log_net_value(context, data)' in src
    t.check('L0.静态: log_net_value 传入 data 自算当日价', passed,
            '' if passed else '没传 data 则 _cur_price 取不到当日价')
    t.check('L0.静态: ATR止损下限=6%(v1.4=5%)', 'ATR_STOP_MIN_PCT = 0.06' in src,
            '回退到5%会频繁窄幅被砍')
    t.check('L0.静态: ATR止损倍数=1.8(贴近波动)', 'ATR_STOP_MULT    = 1.8' in src,
            '倍数过大导致止损带过宽')
    t.check('L0.静态: 赢家粘性门槛=12%(v1.4=15%)', 'WINNER_EXEMPT_PCT   = 0.12' in src,
            '门槛过高让赢家过早被其它规则清掉')
    t.check('L0.静态: 赢家锁利回撤=10pp(v1.4=8pp)', 'WINNER_GIVEBACK_PCT= 0.10' in src,
            '回撤过小利润跑不出来')
    t.check('L0.静态: 赢家激活豁免移动止盈',
            '(not winner_active) and peak_pnl >= TRAIL_ARM_PCT' in src, '')
    t.check('L0.静态: 赢家激活豁免破均线',
            '(not winner_active) and is_tail' in src, '')
    t.check('L0.静态: 版本指纹不低于 %s' % MIN_V, _ver_ok(src),
            '当前=%s 下限=%s' % (_ver_found(src), MIN_V))


def test_embedded_sector_map(strat, ctx, t):
    """v1.7 运行时契约：内嵌行业表必须可用、覆盖达标、且优先于外挂文件。"""
    g = fresh_state(strat, ctx)
    raw = getattr(strat, "EMB_SECTOR_RAW", "")
    t.check("L1.内嵌行业表非空", bool(raw),
            "EMB_SECTOR_RAW 长度=%d（0 说明内嵌块没生成，跑 gen_embedded_map.py）"
            % len(raw or ""))
    g["emb_rev"] = None                     # 清缓存，强制重解析
    rev, nb = strat._parse_emb_sector()
    t.check("L1.内嵌表覆盖标的达标", len(rev) >= 5000,
            "覆盖 %d 只 / %d 板块（应 >=5000 只）" % (len(rev), nb))
    # v1.8：行业表由东财 496 细分板块 切换为 申万一级 31 行业（归属唯一、与 lhb888 同口径）
    t.check("L1.内嵌表行业数达标(申万一级=31)", 20 <= nb <= 40,
            "行业数=%d（20~40 为申万一级；若=496 说明还是东财细分表）" % nb)
    # 内嵌优先：清掉两层缓存后，_load_sector_index 应走内嵌、完全不碰磁盘
    g["ind_rev"] = None
    g["emb_rev"] = None
    g["ind_src"] = None
    got = strat._load_sector_index()
    t.check("L1.行业表加载走内嵌优先", len(got) >= 5000 and g.get("ind_src") == "内嵌",
            "来源=%s 覆盖=%d（应为 内嵌 / >=5000）" % (g.get("ind_src"), len(got)))


def test_static_v17_contract(strat, ctx, t):
    """静态契约 v1.7：行业表内嵌（内嵌优先 + 外挂兜底 + 生成器就位）。"""
    src = open(os.path.join(HERE, 'hotspot_fusion_v1_ptrade.py'),
               encoding='utf-8', errors='replace').read()
    t.check('L0.静态: 内嵌块成对标记存在',
            '# === EMB_IND_BEGIN ===' in src and '# === EMB_IND_END ===' in src, '')
    t.check('L0.静态: 解析函数 _parse_emb_sector 存在',
            'def _parse_emb_sector():' in src, '')
    t.check('L0.静态: 行业表加载「内嵌优先」',
            'emb, emb_nb = _parse_emb_sector()' in src, '')
    t.check('L0.静态: 外挂多路径保留作兜底',
            'SECTOR_MAP_PATHS = (' in src and '回落外挂' in src, '')
    t.check('L0.静态: 行业来源写入状态位',
            'g["ind_src"] = "内嵌"' in src, '')
    t.check('L0.静态: 启动即加载行业表',
            '_load_sector_index()\n' in src, '')
    t.check('L0.静态: 版本指纹不低于 %s' % MIN_V, _ver_ok(src),
            '当前=%s 下限=%s' % (_ver_found(src), MIN_V))
    t.check('L0.静态: 内嵌生成器 gen_embedded_map.py 就位',
            os.path.isfile(os.path.join(HERE, 'gen_embedded_map.py')), '')


def test_static_v18_contract(strat, ctx, t):
    """静态契约 v1.8：行业层口径根因修复 + 入场口径对齐 lhb888。

    第七轮(v1.7 真机)实测：行业榜淘汰占全部淘汰 87.2%、候选中位数仅 2 只、
    5 天候选为 0、26 笔已平仓全亏。根因=行业均值只遍历候选池(已被涨幅区间截断)。
    """
    src = open(os.path.join(HERE, 'hotspot_fusion_v1_ptrade.py'),
               encoding='utf-8', errors='replace').read()
    t.check('L0.静态: SECTOR_MIN_STOCKS=5 (lhb888 同款小样本门槛)',
            'SECTOR_MIN_STOCKS = 5' in src, '')
    t.check('L0.静态: SECTOR_CONFIRM_FALLBACK 降级开关存在',
            'SECTOR_CONFIRM_FALLBACK = True' in src, '')
    # 核心不变式：行业均值样本必须来自【全市场 feats】，且该循环在候选池循环之前
    i0 = src.find('ind_pct = {}')
    i1 = src.find('ind_avg = {}', i0)
    seg = src[i0:i1] if (i0 >= 0 and i1 > i0) else ''
    order_ok = (seg.find('for code, f in feats.items():') >= 0 and
                seg.find('for code, f in feats.items():') <
                max(0, seg.find('for code, f in rough:')))
    t.check('L0.静态: 行业均值样本=全市场 feats(非候选池)', order_ok,
            '' if order_ok else '仍是候选池口径 -> 均值全挤同一区间、排序接近随机')
    t.check('L0.静态: 行业样本门槛已应用',
            'if len(v) >= SECTOR_MIN_STOCKS:' in src, '')
    t.check('L0.静态: 行业层失效时降级为不过滤',
            'if ind_filter_on and ind not in strong_ind:' in src,
            '' if 'ind_filter_on and ind not in strong_ind' in src
            else '降级缺失 -> 行业表一失效就清空候选(误杀)')
    raw = getattr(strat, 'EMB_SECTOR_RAW', '') or ''
    nb = sum(1 for x in raw.split('|') if x.find(':') > 0)
    t.check('L0.静态: 内嵌表已切申万一级(行业数<=40)', 20 <= nb <= 40,
            '行业数=%d（申万一级=31；若=496 说明还是东财细分表）' % nb)
    t.check('L0.静态: MA20 入场缓冲=2%',
            'MA20_ENTRY_BUFFER = 0.02' in src and
            'cur >= ma20 * (1.0 + MA20_ENTRY_BUFFER)' in src, '')
    gr = src[src.find('def _gain_range'):src.find('def _flatten')]
    t.check('L0.静态: 涨幅区间对齐 lhb888(主板 3~4%)',
            'return (0.03, 0.04)' in gr, '')
    t.check('L0.静态: [精选] 打印行业榜参评数与 Top3',
            'len(strong_ind), len(ind_avg), SECTOR_MIN_STOCKS' in src, '')
    t.check('L0.静态: 行业榜日志带降级标记',
            '"降级OFF"' in src, '')


def test_static_v16_contract(strat, ctx, t):
    """静态契约 v1.6：大市闸门分层 + [大市] 自证行 + 行业误报修复。"""
    src = open(os.path.join(HERE, 'hotspot_fusion_v1_ptrade.py'),
               encoding='utf-8', errors='replace').read()
    t.check('L0.静态: 大市分层常量 REGIME_LAYERED 存在',
            'REGIME_LAYERED' in src, '')
    layered = ('if small_below and broad_below:' in src
               and 'elif small_below or broad_below:' in src)
    t.check('L0.静态: 双弱->HALT / 单弱->HALF 分层已落地', layered,
            '' if layered else '仍是「任一破MA20即全停」的旧口径(实测41%天被冻结)')
    t.check('L0.静态: [大市] 自证行(两指数close/MA20/偏离)',
            '[大市] 中证1000 close=' in src, '')
    t.check('L0.静态: 指数取数不全必须 log.error',
            '[大市] 指数取数不全' in src, '')
    fixed = ('share >= 0.30' in src and '空行业名占' in src
             and '空行业名 %d 只' in src)
    t.check('L0.静态: 空行业名改为按占比判定(修误报)', fixed,
            '' if fixed else '仍一出现就 error，会把个别缺行业误判成整层失效')
    t.check('L0.静态: 版本指纹不低于 %s' % MIN_V, _ver_ok(src),
            '当前=%s 下限=%s' % (_ver_found(src), MIN_V))
    # v1.6.1：精选漏斗观测 + buy_job 静默 return 出声（纯观测，不改交易行为）
    t.check('L0.静态: [精选] 六道闸漏斗行存在',
            '[精选] 粗筛%d → 行业榜淘汰%d' in src, '')
    t.check('L0.静态: buy_job 候选为0 必须出声',
            '[买入] 当日候选为0' in src, '')
    t.check('L0.静态: buy_job 持仓已满 必须出声',
            '[买入] 持仓已满' in src, '')
    t.check('L0.静态: buy_job 账户异常必须 log.error',
            '[买入] 账户总资产<=0' in src, '')


def test_static_batch_and_assume(strat, ctx, t):
    """静态检查：三条防"整段 0 成交"的根因已固化在源码里。

    根因一（批量上限）：平台单次 get_history 的证券数有静默上限，所以面板取数必须
      走 `_fetch_panel` 分批，源码里不允许再出现"整池一次传"的面板取数。
    根因二（缺价弃票）：回测不支持 get_snapshot，当日价三层全空时必须假设定价兜底。
    根因三（v1.3 取数形态）：本平台必须显式 is_dict=True 才返回数据，不传时返回空
      且不抛异常。因此【所有取数必须经过协议层 _hist_call】，源码里除协议层外
      不允许再出现裸调 get_history —— 漏一处就会静默拿空。
    """
    src = open(os.path.join(HERE, "hotspot_fusion_v1_ptrade.py"),
               encoding="utf-8", errors="replace").read()
    has_fetch = "def _fetch_panel(" in src and bool(re.search(r"_fetch_panel\(fields,\s*pool", src))
    t.check("L0.静态: 面板取数走分批(_fetch_panel)", has_fetch,
            "" if has_fetch else "仍在整池一次传 get_history，会撞平台批量上限")
    m = re.search(r"FETCH_BATCH\s*=\s*(\d+)", src)
    ok_batch = bool(m) and int(m.group(1)) <= 500
    t.check("L0.静态: FETCH_BATCH 不超过平台单次上限", ok_batch,
            "FETCH_BATCH=%s" % (m.group(1) if m else "未定义"))
    has_assume = "ASSUME_ENTRY_PREMIUM" in src and "assumed = True" in src
    t.check("L0.静态: 缺当日价时走假设定价而非弃票", has_assume,
            "" if has_assume else "缺价仍直接 continue，回测会全池弃票→0 成交")
    # 裸调 get_history 只允许出现在协议层（_hist_style 探测 / _hist_call 落点）
    head, sep, tail = src.partition("# ===================== 平台取数协议层")
    if not sep:
        t.check("L0.静态: 取数统一收口到协议层", False, "未找到协议层分隔注释")
        return
    proto, sep2, rest = tail.partition("# ----------------------------- 全局参数区")
    stray = []
    in_doc = False
    for l in rest.splitlines():
        s = l.strip()
        q = s.count('"""')
        if in_doc:
            if q:
                in_doc = False
            continue
        if q:
            if q % 2 == 1:
                in_doc = True
            continue
        if s.startswith("#"):
            continue
        if re.search(r"(?<!_hist_)\bget_history\(", s):
            stray.append(s[:70])
    t.check("L0.静态: 协议层外无裸调 get_history", not stray,
            "裸调=%s（漏一处就静默拿空）" % stray if stray else "")
    has_is_dict = "is_dict" in proto and "is_dict" in src
    t.check("L0.静态: 取数形态含 is_dict=True", has_is_dict,
            "" if has_is_dict else "本平台不传 is_dict 会静默返回空 → 全天 0 成交")


def main():
    global strat, ctx
    strat = load_strategy()
    ctx = Ctx()
    inject_platform(strat, ctx)
    t = Tester()
    t.section("L0 平台契约")
    for fn in [test_static_field_whitelist, test_static_observability,
               test_static_version_fingerprint, test_static_batch_and_assume,
               test_static_v14_contract, test_static_v15_contract,
               test_static_v16_contract,
               test_embedded_sector_map,
               test_static_v17_contract,
               test_static_v18_contract,
               test_mock_rejects_bad_field, test_mock_requires_is_dict,
               test_no_prev_close_as_today, test_structured_by_name,
               test_date_col_alias_datetime,
               test_data_object_value_is_today_price,
               test_hist_style_probe, test_bar_today_intraday]:
        fn(strat, ctx, t)
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
        f.write("热点融合 v1.8 离线行为校验报告\n")
        f.write("通过 %d / %d\n\n" % (passed, total))
        for n, ok, d in t.results:
            f.write("[%s] %s  %s\n" % ("PASS" if ok else "FAIL", n, d))
    print("报告已写：%s" % report)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
