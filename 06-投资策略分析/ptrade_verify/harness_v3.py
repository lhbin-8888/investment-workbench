# -*- coding: utf-8 -*-
"""
hotspot_trader_v3_hardened 验证 harness
=======================================
在 mock 的 PTrade 环境里跑 v3 加固版，逐一验证 v2.0 的 P0/P1 是否已修复。
与 harness.py（跑 v2 原版）互为对照。
"""
import random, datetime, io, os

STRATEGY_FILE = "../策略回测/hotspot_trader_v3_hardened.py"


# ---------------- 极简 DataFrame 替身 ----------------
class Row(object):
    def __init__(self, d): self._d = d
    def __getitem__(self, k): return self._d[k]
    def get(self, k, default=None): return self._d.get(k, default)

class _Iloc(object):
    def __init__(self, df): self._df = df
    def __getitem__(self, i):
        return Row({k: v[i] for k, v in self._df._cols.items()})

class FakeDF(object):
    def __init__(self, index, cols):
        self.index = list(index)
        self._cols = cols
        self.columns = list(cols.keys())
    def __len__(self): return len(self.index)
    def __getitem__(self, k): return list(self._cols[k])
    @property
    def iloc(self): return _Iloc(self)


# ---------------- 虚拟市场 ----------------
N_STOCK = 600
DAYS = 150
HOT_DAY = 103
ST_IDX = (10, 56)

def gen_market(seed=7):
    rnd = random.Random(seed)
    codes = []
    for i in range(300): codes.append("{:06d}".format(600000 + i * 3))       # 主板沪 60
    for i in range(200): codes.append("{:06d}".format(100 + i * 7))          # 主板深 00
    for i in range(80):  codes.append("{:06d}".format(300000 + i * 5))       # 创业板 30
    for i in range(20):  codes.append("{:06d}".format(688000 + i * 3))       # 科创板 688
    dates = [(datetime.date(2025, 1, 1) + datetime.timedelta(days=k)).isoformat()
             for k in range(DAYS)]
    mkt = {}
    hot_main = set(codes[120:136])     # 主板热点（应 3%~6%）
    hot_20cm = set(codes[500:510]) | set(codes[585:595])   # 创业板+科创板热点（应 6%~12%）
    st = set(codes[i] for i in ST_IDX)
    for c in codes:
        px = 8.0 + rnd.random() * 20
        rows = []
        for d in range(DAYS):
            in_window = 100 <= d <= HOT_DAY + 2
            drift = (rnd.random() - 0.49) * 0.03
            if c in hot_main and in_window:
                drift = 0.03 + rnd.random() * 0.03     # 主板 3%~6%
            elif c in hot_20cm and in_window:
                drift = 0.06 + rnd.random() * 0.06     # 创业板/科创板 6%~12%
            elif c in st and in_window:
                drift = 0.03 + rnd.random() * 0.03
            op = px
            px = max(1.0, px * (1 + drift))
            cl = px
            hi = max(op, cl) * (1 + rnd.random() * 0.012)
            lo = min(op, cl) * (1 - rnd.random() * 0.012)
            vol = (2e7 + rnd.random() * 6e7) * (1.6 if (c in hot_main or c in hot_20cm or c in st) and in_window else 1.0)
            rows.append(dict(date=dates[d], open=op, close=cl, high=hi, low=lo, volume=vol))
        mkt[c] = rows
    names = {c: c for c in codes}
    names[codes[ST_IDX[0]]] = "ST 华测试"
    names[codes[ST_IDX[1]]] = "*ST 退市测"
    return codes, dates, mkt, names


CODES, DATES, MKT, NAMES = gen_market()
TODAY = DATES[HOT_DAY]


# ---------------- mock PTrade ----------------
class Mock(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.logs = []
        self.orders = []          # order(code, amount)
        self.targets = []         # order_target(code, 0)
        self.order_values = []
        self.target_values = []
        self.hist_calls = 0
        self.positions = []
        self.day = cfg.get("day", HOT_DAY)
        self.portfolio_value = cfg.get("portfolio_value", 1000000.0)
        self.cash = cfg.get("cash", 1000000.0)
        self.scheduled = []       # run_daily 注册的 (func, time)
        self.in_init = False      # 模拟「初始化阶段禁止取数」

    def log_info(self, m, *a): self.logs.append(("INFO", m % a if a else str(m)))
    def log_error(self, m, *a): self.logs.append(("ERROR", m % a if a else str(m)))

    def get_history(self, count, period="1d", field=None, security_list=None, **kw):
        if self.cfg.get("init_block_fetch") and self.in_init:
            raise RuntimeError("不支持在[程序初始化]阶段运行get_history")
        if self.cfg.get("strict_field_str") and isinstance(field, (list, tuple)):
            raise TypeError("field must be str")
        if self.cfg.get("no_batch") and security_list and len(security_list) > 1:
            raise TypeError("security_list must be single code")
        self.hist_calls += 1
        freq = period if isinstance(period, str) else "1d"
        out = {}
        for code in (security_list or []):
            pure = "".join(ch for ch in str(code) if ch.isdigit())[:6]
            rows = MKT.get(pure)
            if not rows: continue
            if freq == "1m":
                # 分钟线：返回当日实时价（用当日收盘近似）
                if self.cfg.get("no_minute"):
                    continue
                r = rows[self.day]
                cols = {"date": [r["date"]], "open": [r["open"]], "close": [r["close"]],
                        "high": [r["high"]], "low": [r["low"]],
                        "volume": [r["volume"]]}
                if not self.cfg.get("no_money"):
                    cols["money"] = [r["volume"] * r["close"]]
                out[code] = FakeDF(cols["date"], cols)
            else:
                # 日线：恒不含当日，最后一根 = 昨收；price 字段返回当日实时价
                end = self.day - 1
                seg = rows[max(0, end - count + 1): end + 1]
                if not seg: continue
                sc = 1.0 / 100.0 if self.cfg.get("vol_in_lots") else 1.0
                cols = {"date": [r["date"] for r in seg],
                        "close": [r["close"] for r in seg],
                        "high": [r["high"] for r in seg],
                        "low": [r["low"] for r in seg],
                        "volume": [r["volume"] * sc for r in seg]}
                if not self.cfg.get("no_price"):
                    cur_row = rows[self.day]
                    cols["price"] = [r["close"] for r in seg[:-1]] + [cur_row["close"]]
                if not self.cfg.get("no_money"):
                    cols["money"] = [r["volume"] * r["close"] for r in seg]
                out[code] = FakeDF(cols["date"], cols)
        return out

    def get_price(self, security, start_date=None, end_date=None, frequency="1d",
                  fields=None, fq=None, count=None, **kw):
        if self.cfg.get("no_get_price"):
            raise AttributeError("get_price not available")
        lst = security if isinstance(security, (list, tuple)) else [security]
        return self.get_history(count or 1, frequency, fields, lst)

    def get_Ashares(self): return list(CODES)
    def get_stock_name(self, code):
        if self.cfg.get("no_name"): raise NameError("undefined")
        return NAMES.get("".join(ch for ch in str(code) if ch.isdigit())[:6], "")
    def get_positions(self):
        if self.cfg.get("empty_positions"):
            return []
        return list(self.positions)
    def get_position(self): raise AttributeError("nope")
    def order(self, s, a): self.orders.append((s, a))
    def order_value(self, s, v): self.order_values.append((s, v))
    def order_target(self, s, a): self.targets.append((s, a))
    def order_target_value(self, s, v): self.target_values.append((s, v))
    def run_daily(self, func=None, time="09:30", **kw):
        if self.cfg.get("bad_run_daily"):
            raise TypeError("run_daily() missing 1 required positional argument: 'func'")
        self.scheduled.append((func, time))
    def set_commission(self, **kw): raise TypeError("bad sig")
    def set_slippage(self, *a, **kw): raise TypeError("bad sig")
    def set_benchmark(self, *a, **kw): pass
    def get_datetime(self): raise AttributeError("nope")
    def get_total_assets(self): return self.portfolio_value


class _Log(object):
    def __init__(self, m): self.m = m
    def info(self, s, *a): self.m.log_info(s, *a)
    def error(self, s, *a): self.m.log_error(s, *a)
    def warning(self, s, *a): self.m.log_error(s, *a)

class _Blotter(object):
    def __init__(self, dt): self.current_dt = dt

class _Portfolio(object):
    def __init__(self, v, c, positions=None):
        self.portfolio_value = v
        self.cash = c
        self.positions = positions
        self.long_positions = positions

class _Ctx(object):
    def __init__(self, day, hhmm, v, c, positions=None):
        h, mi = (hhmm.split(":") + ["0", "0"])[:2]
        self.blotter = _Blotter(datetime.datetime.strptime(
            DATES[day] + " " + h + ":" + mi, "%Y-%m-%d %H:%M"))
        self.current_dt = self.blotter.current_dt
        self.portfolio = _Portfolio(v, c, positions)


class _Data(object):
    """mock handle_data 的 data 对象：current(code, field) 返回当日实时价。"""
    def __init__(self, day):
        self.day = day
    def current(self, code, field):
        pure = "".join(ch for ch in str(code) if ch.isdigit())[:6]
        rows = MKT.get(pure)
        if not rows:
            return None
        r = rows[self.day]
        if field in ("price", "close", "last_price", "lastPrice"):
            return r.get("close")
        if field in ("volume",):
            return r.get("volume")
        return None


_SRC = {}
def load_src():
    if "c" not in _SRC:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), STRATEGY_FILE)
        with io.open(p, encoding="utf-8") as f:
            _SRC["c"] = f.read()
    return _SRC["c"]


def run(cfg, positions=None, label="", trade=None,
        prefill=None, risk_only=False, hist_override=None):
    m = Mock(cfg)
    ns = {"log": _Log(m), "__name__": "strategy"}
    if hist_override is not None:
        m.get_history = hist_override
    for n in ("get_history", "get_price", "get_Ashares", "get_stock_name",
              "get_positions", "get_position", "order", "order_value",
              "order_target", "order_target_value", "run_daily",
              "set_commission", "set_slippage", "set_benchmark",
              "get_datetime", "get_total_assets"):
        if cfg.get("no_" + n):
            continue
        ns[n] = getattr(m, n)
    exec(compile(load_src(), STRATEGY_FILE, "exec"), ns)
    if trade:
        ns["TRADE_ENABLED"] = trade
    m.positions = positions or []
    ctx = _Ctx(cfg.get("day", HOT_DAY), cfg.get("now", "14:45"),
               m.portfolio_value, m.cash, cfg.get("portfolio_positions"))
    m.in_init = True
    ns["initialize"](ctx)
    m.in_init = False
    if prefill:                       # 预先设置分批止盈 / 保本价状态
        for k, v in prefill.items():
            setattr(ctx, k, v)
    data = _Data(cfg.get("day", HOT_DAY)) if cfg.get("with_data") else None
    if risk_only:
        ns["monitor_risk"](ctx, data)   # 只跑风控（用于精确验证退出分支）
    elif m.scheduled:
        for fn, t in m.scheduled:
            fn(ctx, data)
    else:
        ns["handle_data"](ctx, data)

    print("")
    print("=" * 76)
    print("SCENE:", label)
    print("-" * 76)
    for lv, l in m.logs:
        if l.startswith("[配置]"):
            continue
        mark = "ERROR" if lv == "ERROR" else "     "
        print("  {} | {}".format(mark, l))
    tb = sum(v for _, v in m.target_values) + sum(v for _, v in m.order_values)
    print("  >> get_history 调用 :", m.hist_calls)
    print("  >> 买入            :", len(m.target_values) + len(m.order_values),
          "合计 {:,} / 可用现金 {:,}".format(int(tb), int(m.cash)))
    print("  >> 卖出            : order_target={} order={}".format(m.targets, m.orders))
    return m, ns


BASE = dict(day=HOT_DAY, now="14:45", include_today=True)

if __name__ == "__main__":
    print("v3 加固版验证    市场 600 只 / 热点日 T={} ({})".format(HOT_DAY, TODAY))

    _ = run(dict(BASE), trade=True,
            label="V-S1 基线：应选出「强势未封板」标的并按可用现金建仓")

    _ = run(dict(BASE, vol_in_lots=True), trade=True,
            label="V-S3 volume 单位为「手」：自检应自动 x100，不再全市场误杀")

    _ = run(dict(BASE, strict_field_str=True, no_get_price=True), trade=True,
            label="V-S2 get_history 只接受 field=str 且无 get_price：多签名容错应生效")

    _ = run(dict(BASE, now="15:00", no_run_daily=True), trade=True,
            label="V-S4 无 run_daily + current_dt=15:00：应照常执行（v2 在此静默）")

    _ = run(dict(BASE, now="09:31", no_run_daily=True), trade=True,
            label="V-S4b 无 run_daily + 09:31（早于信号时间）：应跳过")

    _ = run(dict(BASE, no_minute=True), trade=True,
            label="V-S8 分钟线不可得：应回退「昨日涨幅」口径并明确告警")

    _c = CODES[120]
    _suf = _c + ".SS" if _c.startswith("60") else _c + ".SZ"
    _last = MKT[_c][HOT_DAY]["close"]
    pos = [dict(security=_suf, current_amount=10000, enable_amount=0,
                cost_price=_last / 0.90, avg_price=_last / 0.90, last_price=_last)]
    _ = run(dict(BASE), positions=pos, trade=True,
            label="V-S5 T+1：可卖量=0 时不应发出废单，必须 ERROR 告警")

    pos2 = [dict(security=_suf, current_amount=10000, enable_amount=10000,
                 cost_price=_last / 1.20, avg_price=_last / 1.20, last_price=_last)]
    _ = run(dict(BASE, with_data=True), positions=pos2, trade=True,
            label="V-S5b 浮盈≥+15% 可卖量充足：应 order_target 清仓")

    # ---- 真实环境综合（对照彬哥哥发来的回测日志）----
    _ = run(dict(BASE, bad_run_daily=True, init_block_fetch=True), trade=True,
            label="V-S9 真实环境：money字段 + 初始化禁取数 + run_daily签名不匹配")

    _ = run(dict(BASE, no_money=True), trade=True,
            label="V-S9b 老平台无 money 字段：回退 volume×close 估算成交额")

    # ---- 持仓字段名兼容（对照「只有买入没有卖出」的问题）----
    _c2 = CODES[122]
    _suf2 = _c2 + ".SS" if _c2.startswith("60") else _c2 + ".SZ"
    _last2 = MKT[_c2][HOT_DAY]["close"]
    pos3 = [dict(code=_suf2, total_amount=10000, available_amount=10000,
                 cost_basis=_last2 / 0.90)]
    _ = run(dict(BASE), positions=pos3, trade=True,
            label="V-S11 非常规持仓字段名(code/total_amount/available_amount/cost_basis)：应正确识别并止损")

    _ = run(dict(BASE, empty_positions=True,
                 portfolio_positions=[dict(security=_suf2, current_amount=10000,
                                           enable_amount=10000, cost_price=_last2 / 0.90)]),
            trade=True,
            label="V-S12 get_positions 返回空时回退 context.portfolio.positions")

    _ = run(dict(BASE, with_data=True), trade=True,
            label="V-S13 用 handle_data 的 data 参数取当日价（get_history 拿不到当日价的平台）")

    # ---- 分批止盈回归（彬哥哥定制：+10% 减半，+15% 或破5日线清仓）----
    pos_half = [dict(security=_suf, current_amount=10000, enable_amount=10000,
                     cost_price=_last / 1.11, avg_price=_last / 1.11, last_price=_last)]
    _ = run(dict(BASE, with_data=True), positions=pos_half, trade=True,
            label="V-S14 浮盈≥+10%：应减半（卖一半可卖量，仅一次）")

    # 破 5 日线清仓：临时构造某票最近 5 日陡峭下行，使当日收盘 < MA5，结束后还原
    _c3 = CODES[130]
    _suf3 = _c3 + ".SS" if _c3.startswith("60") else _c3 + ".SZ"
    _back3 = MKT[_c3]
    _rows3 = [dict(r) for r in _back3]
    _base3 = _rows3[HOT_DAY - 1]["close"]
    for _off, _mult in [(5, 1.10), (4, 1.05), (3, 1.00), (2, 0.95), (1, 0.90)]:
        _rows3[HOT_DAY - _off]["close"] = _base3 * _mult
    MKT[_c3] = _rows3
    _last3 = MKT[_c3][HOT_DAY - 1]["close"]
    pos_ma5 = [dict(security=_suf3, current_amount=10000, enable_amount=10000,
                    cost_price=_last3 / 1.05, avg_price=_last3 / 1.05, last_price=_last3)]
    _ = run(dict(BASE), positions=pos_ma5, trade=True,
            label="V-S15 破5日线：应直接清仓（不分批）")
    MKT[_c3] = _back3

    # ---- 本次定制回归：14:45 买入 + 新涨幅区间 + 北交所排除 ----
    # 直接对策略模块做单元级断言，锁定彬哥哥的三项参数调整
    def _assert(cond, msg):
        if cond:
            print("  PASS | " + msg)
        else:
            print("  FAIL | " + msg)
            _assert.failed = True
    _assert.failed = False

    ns16 = {"log": _Log(Mock({})), "__name__": "strategy"}
    exec(compile(load_src(), STRATEGY_FILE, "exec"), ns16)

    print("")
    print("=" * 76)
    print("SCENE: V-S16 14:45 买入 + 新涨幅区间(主3-8 / 20cm8-14) + 北交所排除")
    print("-" * 76)
    gr = ns16["GAIN_RANGE"]
    _assert(ns16["SIGNAL_TIME"] == "14:45",
            "SIGNAL_TIME == '14:45'（尾盘买入）")
    _assert(gr["main"] == (3.0, 8.0), "主板涨幅区间 = 3%~8%（实得 {}）".format(gr["main"]))
    _assert(gr["kcb"] == (8.0, 14.0), "科创板涨幅区间 = 8%~14%（实得 {}）".format(gr["kcb"]))
    _assert(gr["cyb"] == (8.0, 14.0), "创业板涨幅区间 = 8%~14%（实得 {}）".format(gr["cyb"]))
    # 北交所：_gain_range 返回 None，且 ALLOW_BOARDS 不含 BJ
    _assert(ns16["_gain_range"]("920001.BJ") is None,
            "北交所 _gain_range 返回 None（不参与选股）")
    _assert("BJ" not in ns16["ALLOW_BOARDS"],
            "ALLOW_BOARDS 不含 'BJ'（股票池过滤排除北交所）")
    _assert(ns16["_suffix"]("920001") == "920001.BJ",
            "_suffix 北交所代码正确补 .BJ")
    if _assert.failed:
        print("  >> V-S16 断言失败")
    else:
        print("  >> V-S16 全部断言通过")


    # ---- 收益优化回归：强度分档分配 + 分时回踩(不破开盘价)过滤 ----
    ns17 = {"log": _Log(Mock({})), "__name__": "strategy"}
    exec(compile(load_src(), STRATEGY_FILE, "exec"), ns17)

    print("")
    print("=" * 76)
    print("SCENE: V-S17 收益优化：强度分档仓位 + 分时回踩(不破开盘价)过滤")
    print("-" * 76)
    _assert.failed = False
    # 1) 强度分档：强票分得多、弱票分得少，且单票不超 MAX_SINGLE_RATIO
    picks = [{"code": "A.SS", "score": 40.0}, {"code": "B.SZ", "score": 30.0},
             {"code": "C.SZ", "score": 20.0}, {"code": "D.SS", "score": 10.0}]
    budget, total = 900000.0, 1000000.0
    alloc = ns17["_alloc_by_strength"](picks, budget, total)
    _assert(len(alloc) == 4, "返回 4 个分配额")
    _assert(alloc[0] > alloc[-1], "强度最高(A)分得最多、最低(D)最少")
    _assert(all(a <= total * ns17["MAX_SINGLE_RATIO"] + 1e-6 for a in alloc),
            "单票不超 MAX_SINGLE_RATIO(30%)")
    _assert(abs(sum(alloc) - budget) < 1.0,
            "预算基本用满(sum={:.0f}≈{:.0f})".format(sum(alloc), budget))
    # 2) 关闭强度分档 -> 等权
    ns17["STRENGTH_WEIGHT"] = False
    alloc_eq = ns17["_alloc_by_strength"](picks, budget, total)
    _assert(abs(alloc_eq[0] - alloc_eq[-1]) < 1e-6, "关闭后等权")
    ns17["STRENGTH_WEIGHT"] = True
    # 3) 分时回踩(不破开盘价)过滤
    pb = ns17["_pass_pullback"]
    ns17["BUY_PULLBACK_FILTER"] = True
    ns17["PULLBACK_OPEN_BREAK"] = True
    _assert(pb(10.5, 10.0, None, None) is True,  "cur>open -> 可买")
    _assert(pb(9.8, 10.0, None, None) is False,  "cur<open(破开盘价) -> 过滤")
    _assert(pb(None, 10.0, None, None) is True,  "无当日价 -> 不退化为过滤")
    _assert(pb(9.8, None, None, None) is True,   "无开盘价 -> 不过滤(防静默丢信号)")
    ns17["PULLBACK_OPEN_BREAK"] = False
    _assert(pb(9.8, 10.0, None, None) is True,   "关闭 OPEN_BREAK -> 不过滤")
    ns17["BUY_PULLBACK_FILTER"] = False
    _assert(pb(9.8, 10.0, None, None) is True,   "关闭 BUY_PULLBACK_FILTER -> 不过滤")
    if _assert.failed:
        print("  >> V-S17 断言失败")
    else:
        print("  >> V-S17 全部断言通过")


    # ---- 保本止损回归：已减半票回落到成本以下 -> 保本清仓（不破5日线、不触-5%）----
    _be_code = CODES[0]
    _be_suf = _be_code + ".SS" if _be_code.startswith("60") else _be_code + ".SZ"
    _be_orig = MKT[_be_code][HOT_DAY]["close"]
    MKT[_be_code][HOT_DAY]["close"] = 10.0   # 当日价 cur = 10.0

    def _hist_breakeven(count, period="1d", field=None,
                        security_list=None, **kw):
        out = {}
        for c in (security_list or []):
            if _be_suf in str(c):
                # 25 根 close，末 5 根均值≈8.58 < 10.0 → 不破 5 日线
                closes = [8.0, 8.3, 8.6, 8.9, 9.1] * 5
                dates = ["2026-08-%02d" % (i + 1) for i in range(len(closes))]
                out[c] = FakeDF(dates, {"close": closes, "date": dates})
            else:
                out[c] = FakeDF([], {"close": [], "date": []})
        return out

    _be_pos = [dict(security=_be_suf, current_amount=10000, enable_amount=10000,
                    cost_price=10.3, avg_price=10.3, last_price=10.0)]
    m18, _ = run(dict(BASE, with_data=True), positions=_be_pos, trade=True,
                 prefill={"halved": {_be_suf: True}, "breakeven": {_be_suf: 10.3}},
                 risk_only=True, hist_override=_hist_breakeven,
                 label="V-S18 保本止损：已减半票 cur=10<保本价10.3 -> 保本清仓")
    _assert.failed = False
    _log18 = "\n".join(l for _, l in m18.logs)
    _assert("保本止损" in _log18, "日志命中「保本止损」分支（已减半票回落到成本以下）")
    _assert(any(_be_suf in str(t) for t in m18.targets) or
            any(_be_suf in str(o) for o in m18.orders),
            "已减半票触发清仓卖出（保本止损生效）")
    MKT[_be_code][HOT_DAY]["close"] = _be_orig   # 恢复，避免污染其他场景
    if _assert.failed:
        print("  >> V-S18 断言失败")
    else:
        print("  >> V-S18 全部断言通过")


    # ---- T+1 亏损清仓回归：买入次日（持有>=1天）仍亏损 -> 清仓（区别于 -5% 止损）----
    _t1_code = CODES[0]
    _t1_suf = _t1_code + ".SS" if _t1_code.startswith("60") else _t1_code + ".SZ"

    def _hist_t1(count, period="1d", field=None, security_list=None, **kw):
        out = {}
        for c in (security_list or []):
            if _t1_suf in str(c):
                # cur=9.7, cost=10.0 -> rt=-3%（介于 -5% 与 0 之间，专测 T+1 而非止损）
                closes = [9.6] * 24 + [9.7]
                dates = ["2026-08-%02d" % (i + 1) for i in range(len(closes))]
                out[c] = FakeDF(dates, {"close": closes, "date": dates})
            else:
                out[c] = FakeDF([], {"close": [], "date": []})
        return out

    _t1_pos = [dict(security=_t1_suf, current_amount=10000, enable_amount=10000,
                    cost_price=10.0, avg_price=10.0, last_price=9.7)]
    m19, _ = run(dict(BASE), positions=_t1_pos, trade=True,
                 prefill={"entry_date": {_t1_suf: DATES[HOT_DAY - 1]}},
                 risk_only=True, hist_override=_hist_t1,
                 label="V-S19 T+1亏损清仓：持有1天 rt=-3% -> 清仓")
    _assert.failed = False
    _log19 = "\n".join(l for _, l in m19.logs)
    _assert("T+1亏损清仓" in _log19, "日志命中「T+1亏损清仓」分支（次日亏损票清仓）")
    _assert(any(_t1_suf in str(t) for t in m19.targets) or
            any(_t1_suf in str(o) for o in m19.orders),
            "次日亏损票触发清仓卖出（T+1亏损清仓生效）")
    if _assert.failed:
        print("  >> V-S19 断言失败")
    else:
        print("  >> V-S19 全部断言通过")


    # ---- 盈利票持仓上限回归：持有>=10天 -> 清仓；持有5天 -> 保留 ----
    _p_code = CODES[1]
    _p_suf = _p_code + ".SS" if _p_code.startswith("60") else _p_code + ".SZ"

    def _hist_profit(count, period="1d", field=None, security_list=None, **kw):
        out = {}
        for c in (security_list or []):
            if _p_suf in str(c):
                # cur=10.8, cost=10.0 -> rt=+8%（未触 +10% 减半，专测时间止损）
                closes = [10.7] * 24 + [10.8]
                dates = ["2026-08-%02d" % (i + 1) for i in range(len(closes))]
                out[c] = FakeDF(dates, {"close": closes, "date": dates})
            else:
                out[c] = FakeDF([], {"close": [], "date": []})
        return out

    _p_pos = [dict(security=_p_suf, current_amount=10000, enable_amount=10000,
                   cost_price=10.0, avg_price=10.0, last_price=10.8)]
    # (a) 持有 10 天 -> 应触发「盈利持仓10天」清仓
    m20a, _ = run(dict(BASE), positions=_p_pos, trade=True,
                  prefill={"entry_date": {_p_suf: DATES[HOT_DAY - 10]}},
                  risk_only=True, hist_override=_hist_profit,
                  label="V-S20a 盈利票持有10天 -> 清仓")
    _assert.failed = False
    _log20a = "\n".join(l for _, l in m20a.logs)
    _assert("盈利持仓10天" in _log20a, "日志命中「时间止损 盈利持仓10天」")
    _assert(any(_p_suf in str(t) for t in m20a.targets) or
            any(_p_suf in str(o) for o in m20a.orders),
            "盈利票持有10天触发清仓")
    # (b) 持有 5 天 -> 不应触发时间止损（盈利票上限为 10 天）
    m20b, _ = run(dict(BASE), positions=_p_pos, trade=True,
                  prefill={"entry_date": {_p_suf: DATES[HOT_DAY - 5]}},
                  risk_only=True, hist_override=_hist_profit,
                  label="V-S20b 盈利票持有5天 -> 保留")
    _log20b = "\n".join(l for _, l in m20b.logs)
    _assert("时间止损" not in _log20b, "盈利票持有5天不触发时间止损（上限10天）")
    _assert(not any(_p_suf in str(t) for t in m20b.targets) and
            not any(_p_suf in str(o) for o in m20b.orders),
            "盈利票持有5天不被卖出（保留）")
    if _assert.failed:
        print("  >> V-S20 断言失败")
    else:
        print("  >> V-S20 全部断言通过")


