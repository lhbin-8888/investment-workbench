# -*- coding: utf-8 -*-
# =============================================================================
# fusion_backtest.py — 热点融合 v1.8 成交模式回测引擎（本地版）
# -----------------------------------------------------------------------------
# 目的：把 hotspot_fusion_v1_ptrade.py 原文件【一字不改】加载进来，注入一套
#       事件驱动的 PTrade API 模拟实现，使其在本地就能跑"成交模式回测"，
#       产出与原三策略同格式的 [净值]/[买入]/[卖出] 日志 + 每日净资产序列 + 统计。
#
# 数据层可插拔：
#   - SyntheticProvider : 确定性合成行情（演示/接线用，明确标注 PROXY，非真实市场）
#   - CSVBundleProvider : 真实行情（把 PTrade/东方财富导出的日线 bundle 放进来即可重跑）
#
# 重要口径说明（务必读）：
#   1. 本引擎默认用 SyntheticProvider（PROXY）跑通，是为了验证"策略代码→回测引擎"
#      接线正确、输出格式可用；PROXY 数字【不代表真实收益】，仅作形状/流程演示。
#   2. 真实收益必须靠 CSVBundleProvider（导出真实日线）在本地重跑，或上传 .py 到
#      券商 PTrade 回测环境跑。融合策略文件本身 PTrade 兼容，可直接上传。
#   3. 日内价格模型：10:30 及之前用当日 open 作填充价（双护栏有意义），其后用 close；
#      日终净值按 close 计。属"日线级、收盘执行"近似，非分钟级。
#   4. 行业映射：引擎 get_industry 直接挂 lhb888/industry_map.json，还原 PTrade 上
#      行业过滤的真实行为（否则 _industry_of 退化为单行业）。
# =============================================================================
import importlib.util
import os
import sys
import math
import json
import random
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FUSION_PY = os.path.join(HERE, "hotspot_fusion_v1_ptrade.py")
IND_MAP = os.path.join(os.path.dirname(HERE),
                       "热点追踪lhb888", "industry_map.json")
# 平台侧行业表就是 sector_map.json（001 同款外挂文件）。本地引擎优先用它反查出
# {code6: 行业名}，与平台注入 g["ind_rev"] 的形态一致；缺失再退 industry_map.json。
SECTOR_MAP = os.path.join(r"D:\投研工作台", "quant", "hotspot", "sector_map.json")
START_CASH = 100000.0

# 真实平台 get_history 认可的字段名（来自 2026-09-22 实盘回测的平台报错原文）
# 注意：昨收是 preclose（无下划线）；pre_close 会被平台拒绝。
PLATFORM_FIELDS = {"open", "high", "low", "close", "price", "volume", "money",
                   "preclose", "high_limit", "low_limit", "unlimited", "is_open"}


# ----------------------------- 数据视图（模拟 data 对象）--------------------
class Bar(object):
    __slots__ = ("date", "open", "high", "low", "close", "volume", "money", "pre_close")

    def __init__(self, date, o, h, l, c, v, m, pc):
        self.date = date
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v
        self.money = m
        self.pre_close = pc

    def __getitem__(self, key):
        # 允许 bar["open"] / bar["close"] 按字段名取值（DataView 用）
        return getattr(self, key)


class FakeDF(object):
    """模拟 PTrade get_history 返回的 DataFrame（单只）。

    同时提供 .values（位置取数）与 .columns（列名取数）——真实平台的 DataFrame
    两者都有；策略已改为【优先按列名】对齐，故 columns 必须真实存在。
    """

    def __init__(self, rows, columns=None):
        self.values = rows  # list[list]，列顺序与 fields 一致
        self.columns = list(columns) if columns else None


class FakeStruct(object):
    """模拟 numpy 结构化数组 —— 平台 get_history(is_dict=True) 每值的【真实形态】。

    001 日志实测 `[诊断] 首值 type=ndarray repr=array([(20260114, 32.14, 32.15,
    33.74, 31.6, 4748482.), ...])`，即 dtype.names=('date','open','close','high',
    'low','volume')、列序固定且与请求顺序无关。引擎必须按这个形态返回，否则
    「按位置取列把 date 当 open」这类错位在本地跑不出来。
    """

    class _DT(object):
        def __init__(self, names):
            self.names = tuple(names)

    def __init__(self, names, recs):
        self.dtype = FakeStruct._DT(names)
        self._recs = list(recs)

    def __len__(self):
        return len(self._recs)

    def __iter__(self):
        return iter(self._recs)

    def __getitem__(self, i):
        return self._recs[i]


class FakeRec(object):
    """模拟 numpy 结构化标量：rec['close']（按名）与 rec[2]（按位）都支持。"""
    __slots__ = ("_names", "_vals")

    def __init__(self, names, vals):
        self._names = list(names)
        self._vals = list(vals)

    def __getitem__(self, k):
        if isinstance(k, str):
            return self._vals[self._names.index(k)]
        return self._vals[k]


_STRUCT_ORDER = ("open", "close", "high", "low", "volume", "money", "preclose")


class DataView(object):
    """传给 handle_data 的 data 快照。

    真实 PTrade 的 get_history('1d') 不含当日 bar，因此「当日价/开/高/低/量」
    只能由 data 提供。本视图按此建模：
      kind='open'  -> 10:30 及之前的盘中快照（价格取当日开盘，量按约 45% 累计），
                      **不含未来信息**；
      kind='close' -> 午后快照（价格取当日收盘，量为全天量）。
    """

    def __init__(self, market, day, kind):
        self._m = market
        self._day = day
        self._kind = kind  # 'open' | 'close'

    def get(self, code):
        bars = self._m.series.get(code)
        b = self._m.bar(self._day, code)
        if not bars or not b:
            return None
        prev = b.open
        for i, x in enumerate(bars):
            if x.date == self._day:
                prev = bars[i - 1].close if i > 0 else b.open
                break
        if self._kind == "open":
            px = b.open
            hi = max(b.open, b.open * 1.003)
            lo = min(b.open, b.open * 0.997)
            vol = b.volume * 0.45
        else:
            px = b.close
            hi, lo, vol = b.high, b.low, b.volume
        # 【v1.5+】返回 BarNS 而非 SimpleNS：数值=当日价，.price/.close=昨收。
        # 平台实证（1030 日志）：昨收=11.13 data价=11.34 price字段=11.13。
        # 引擎若不复刻这个陷阱，"只按字段名取价"的回归在本地永远跑不出来。
        return BarNS(px, prev, b.open, hi, lo, vol)

    def __getitem__(self, code):
        return self.get(code)


class BarNS(object):
    """模拟平台 handle_data 的 Bar：float(bar)=当日价，而 .price/.close=昨收。"""

    def __init__(self, today_px, prev_close, o, h, lo, v):
        self._today = float(today_px)
        self.price = float(prev_close)      # ← 陷阱：字段名给的是【昨收】
        self.close = float(prev_close)
        self.last_price = float(prev_close)
        self.open = float(o)
        self.high = float(h)
        self.low = float(lo)
        self.volume = float(v)

    def __float__(self):
        return self._today                  # ← 数值才是【当日价】


class SimpleNS(object):
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ----------------------------- 市场数据容器 ---------------------------------
class Market(object):
    def __init__(self):
        # code -> list[Bar]（按 days 顺序）
        self.series = {}
        self.days = []

    def add(self, code, bars):
        self.series[code] = bars

    def bar(self, day, code):
        bars = self.series.get(code)
        if not bars:
            return None
        for b in bars:
            if b.date == day:
                return b
        return None

    def history(self, code, count, day, include_today=True):
        """count 根日线。include_today=False 时不含当日 bar。

        【为什么要这个开关】10:30 时当日日线还没收完，若把当日 bar 的 close 喂给
        策略，就等于把全天收盘价泄漏到盘中（未来函数）。故 kind='open'（盘中快照）
        一律 exclude 当日；kind='close'（尾盘/收盘后）才含当日。
        """
        bars = self.series.get(code)
        if not bars:
            return []
        out = []
        for b in bars:
            if b.date < day or (include_today and b.date == day):
                out.append(b)
        return out[-count:]


# ----------------------------- 组合模拟 -------------------------------------
class Position(object):
    def __init__(self, code, shares, cost):
        self.sid = code
        self.stock_code = code
        self.code = code
        self.amount = shares
        self.current_amount = shares
        self.enable_amount = shares
        self.cost_basis = cost
        self.cost_price = cost
        self.avg_price = cost
        self.last_sale_price = 0.0


class Portfolio(object):
    def __init__(self, cash):
        self.cash = cash
        self.positions = {}  # code -> Position
        # PTrade 的 context.portfolio.portfolio_value；策略 _account() 读它
        self.portfolio_value = float(cash)

    def value(self, market, day, kind="close"):
        v = self.cash
        for code, p in self.positions.items():
            if p.amount > 0:
                b = market.bar(day, code)
                if b:
                    px = getattr(b, kind, b.close)
                    v += p.amount * px
        return v

    def sync(self, market, day, kind):
        """每个时点刷新 portfolio_value，供策略 _account() 读取"""
        self.portfolio_value = self.value(market, day, kind)


# ----------------------------- 回测引擎 -------------------------------------
class Engine(object):
    def __init__(self, market, ind_map):
        self.market = market
        self.ind_map = ind_map or {}
        self.today = ""
        self.portfolio = Portfolio(START_CASH)
        self.ctx = SimpleNS()
        self.ctx.portfolio = self.portfolio
        self.ctx.blotter = SimpleNS()
        self.ctx.blotter.current_dt = ""
        self.log_lines = []
        self.buy_log = []   # (day, code, value)
        self.sell_log = []  # (day, code, reason, pnl)
        self.errors = []    # 策略 log.error 行（静默失败告警）
        self.net_series = []  # (day, nv)
        self.costs = 0.0
        self.kind = "close"  # 当前快照类型：'open'(10:30及之前) / 'close'(午后)

    # ---- 日志 ----
    def log(self):
        return self

    def info(self, msg):
        self.log_lines.append("[%s] %s" % (self.today, msg))

    def warning(self, msg):
        self.log_lines.append("[%s] WARN %s" % (self.today, msg))

    def error(self, msg):
        # 【夹具纪律】策略新增了 log.error 级别的告警（空转看门狗/取数失败），
        # 夹具必须同步支持，否则真实代码一调用就 AttributeError（本轮踩过）。
        self.log_lines.append("[%s] ERROR %s" % (self.today, msg))
        self.errors.append("[%s] %s" % (self.today, msg))

    def warn(self, msg):
        self.warning(msg)

    # ---- 平台接口：行情 ----
    def get_history(self, count, freq, fields, codes, fq=None, is_dict=False):
        """严格模仿真实平台：字段名必须在白名单内，否则抛与平台一致的异常；
        且【必须显式 is_dict=True 才返回数据】。

        真实平台报错原文（2026-09-22 实盘回测）：
          function get_history: invalid field ['pre_close'], valid fields are
          {'open','volume','is_open','money','high','price','preclose',
           'high_limit','low','unlimited','close','low_limit'}
        严格校验的意义：`pre_close`（多一个下划线）这类写法在真实环境会让
        取数整段抛异常 -> 候选池恒空 -> 全天 0 成交。宽松 Mock 会放过它，
        让离线校验全绿却上线即哑火。

        is_dict 同理：本平台不传 is_dict 时返回空结果且【不抛异常】。v1.2 把它
        误当"没有数据"，白查两轮；这里必须忠实复刻，让"忘了传"本地就炸。
        """
        if isinstance(codes, str):
            codes = [codes]
        if isinstance(fields, str):
            fields = [fields]
        fields = list(fields)
        bad = [f for f in fields if f not in PLATFORM_FIELDS]
        if bad:
            raise Exception(
                "function get_history: invalid field %s, valid fields are "
                "{'open', 'volume', 'is_open', 'money', 'high', 'price', "
                "'preclose', 'high_limit', 'low', 'unlimited', 'close', "
                "'low_limit'}, got %s (type: <class 'list'>)" % (bad, fields))
        if not is_dict:
            return {}
        # 日期列真名是 datetime（平台 [诊断] 实测），不是 date —— 引擎也必须如此，
        # 否则策略里"查 date 列"的写法在本地上永远失败不了，回归就抓不出来。
        names = ["datetime"] + [f for f in _STRUCT_ORDER if f in fields]
        names += [f for f in fields if f not in _STRUCT_ORDER and f not in names]
        include_today = (getattr(self, "kind", "close") == "close")
        res = {}
        for code in codes:
            bars = self.market.history(code, count, self.today, include_today)
            recs = []
            for b in bars:
                vals = []
                for nm in names:
                    if nm == "datetime":
                        try:
                            vals.append(int(str(b.date).replace("-", "")))
                        except Exception:
                            vals.append(0)
                    elif nm == "preclose":
                        vals.append(b.pre_close)
                    elif nm == "price":
                        # 平台 price 字段 = 日线末根收盘（即昨收），不是当日价 ——
                        # 这正是 v1.3 误把它当"当日价"从而 pct 恒 0 的陷阱点。
                        vals.append(b.pre_close)
                    else:
                        vals.append(getattr(b, nm, 0.0))
                recs.append(FakeRec(names, vals))
            if recs:
                res[code] = FakeStruct(names, recs)
        return res

    def get_Ashares(self):
        out = []
        for code in self.market.series.keys():
            if code in ("000300.SS", "000852.SS"):
                continue
            out.append(code)
        return out

    def get_all_stocks(self):
        return self.get_Ashares()

    def get_industry(self, code6):
        return self.ind_map.get(code6, "")

    def get_snapshot(self, codes):
        if isinstance(codes, str):
            codes = [codes]
        res = {}
        for code in codes:
            b = self.market.bar(self.today, code)
            if not b:
                continue
            if getattr(self, "kind", "close") == "open":
                px, hi, lo, vol = b.open, max(b.open, b.open * 1.003), min(b.open, b.open * 0.997), b.volume * 0.45
            else:
                px, hi, lo, vol = b.close, b.high, b.low, b.volume
            res[code] = {"last_px": px, "last_price": px, "price": px,
                         "open": b.open, "high": hi, "low": lo, "volume": vol}
        return res

    # ---- 平台接口：交易 ----
    def _lot(self, code):
        return 200 if code.startswith("68") else 100

    def order_target_value(self, code, value, limit_price=None):
        b = self.market.bar(self.today, code)
        if not b:
            return
        price = limit_price if limit_price else b.close
        if price <= 0:
            return
        lot = self._lot(code)
        desired = int(value / price // lot) * lot
        cur = self.portfolio.positions.get(code)
        cur_shares = cur.amount if cur else 0
        delta = desired - cur_shares
        if delta > 0:
            self._buy(code, delta, price)
        elif delta < 0:
            self._sell(code, -delta, price)

    def order_target(self, code, target):
        cur = self.portfolio.positions.get(code)
        if not cur or cur.amount == 0:
            return
        b = self.market.bar(self.today, code)
        price = b.close if b else cur.cost_basis
        if target == 0:
            self._sell(code, cur.amount, price)

    def order(self, code, shares):
        # shares<0 表示卖出
        if shares >= 0:
            return
        b = self.market.bar(self.today, code)
        price = b.close if b else 0.0
        self._sell(code, -shares, price)

    def _buy(self, code, shares, price):
        slip = price * 1.001
        commission = max(slip * shares * 0.0003, 5.0)
        cost = slip * shares + commission
        if cost > self.portfolio.cash:
            # 现金不足，按可买手数缩减
            afford = self.portfolio.cash / (slip * self._lot(code) * 1.0003)
            shares = int(afford // 1) * self._lot(code)
            if shares <= 0:
                return
            cost = slip * shares + max(slip * shares * 0.0003, 5.0)
        self.portfolio.cash -= cost
        self.costs += commission
        cur = self.portfolio.positions.get(code)
        if cur and cur.amount > 0:
            new_amt = cur.amount + shares
            new_cost = (cur.cost_basis * cur.amount + slip * shares) / new_amt
            cur.amount = new_amt
            cur.current_amount = new_amt
            cur.enable_amount = new_amt
            cur.cost_basis = new_cost
            cur.cost_price = new_cost
            cur.avg_price = new_cost
            cur.last_sale_price = slip
        else:
            self.portfolio.positions[code] = Position(code, shares, slip)
            self.portfolio.positions[code].last_sale_price = slip
        self._on_buy(code, slip * shares)

    def _sell(self, code, shares, price):
        cur = self.portfolio.positions.get(code)
        if not cur or cur.amount <= 0:
            return
        shares = min(shares, cur.amount)
        slip = price * 0.999
        pnl = (slip - cur.cost_basis) / cur.cost_basis if cur.cost_basis > 0 else 0.0
        commission = max(slip * shares * 0.0003, 5.0)
        stamp = slip * shares * 0.001
        proceeds = slip * shares - commission - stamp
        self.portfolio.cash += proceeds
        self.costs += commission + stamp
        cur.amount -= shares
        cur.current_amount = cur.amount
        cur.enable_amount = cur.amount
        cur.last_sale_price = slip
        self._on_sell(code, "平仓", pnl)
        if cur.amount <= 0:
            del self.portfolio.positions[code]

    # ---- 钩子：记录日志（供分析与统计）----
    def _on_buy(self, code, value):
        self.buy_log.append((self.today, code, value))

    def _on_sell(self, code, reason, pnl):
        self.sell_log.append((self.today, code, reason, pnl))

    # ---- 主循环 ----
    def run(self, strat, run_days, emit=True):
        for day in run_days:
            self.today = day
            self.ctx.blotter.current_dt = day + " 09:30:00"
            strat.before_trading_start(self.ctx, DataView(self.market, day, "open"))
            for t in ["09:45", "10:30", "11:20", "13:10", "14:15", "14:45", "14:55"]:
                kind = "open" if t <= "10:30" else "close"
                self.kind = kind
                self.ctx.blotter.current_dt = day + " " + t + ":00"
                self.portfolio.sync(self.market, day, kind)
                strat.handle_data(self.ctx, DataView(self.market, day, kind))
            nv = self.portfolio.value(self.market, day)
            if emit:
                self.log_lines.append("[%s] [净值] %s 总资产=%d" %
                                      (day, day, int(round(nv))))
            self.net_series.append((day, nv))


# ----------------------------- 合成行情（PROXY）-----------------------------
INDUSTRIES = ["半导体", "电池", "消费电子", "汽车零部件", "计算机", "通信设备",
              "医药生物", "化学制药", "工程机械", "白酒", "证券", "电力", "军工", "面板"]

# 热点事件：日期 -> 行业（在合成市场里制造"板块集群"触发策略买入）
HOT_EVENTS = {
    "2026-05-08": "半导体",
    "2026-05-15": "电池",
    "2026-05-22": "消费电子",
    "2026-05-29": "汽车零部件",
    "2026-06-05": "计算机",
    "2026-06-12": "通信设备",
    "2026-06-19": "医药生物",   # 下跌段中的热点（测弱市行为）
    "2026-06-26": "军工",
}


def _weekdays(start, end):
    d = datetime.date(*start)
    e = datetime.date(*end)
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += datetime.timedelta(days=1)
    return out


def build_synthetic(seed=20260506):
    rnd = random.Random(seed)
    days = _weekdays((2026, 2, 2), (2026, 6, 30))  # 前置数据满足 MA60
    n = len(days)

    # 指数路径：5月初起温和上行至6/12见顶，随后回落（中证1000跌破MA20触发HALT）
    idx_ret = []
    for i, day in enumerate(days):
        dt = datetime.date(*map(int, day.split("-")))
        if day < "2026-05-06":
            idx_ret.append(rnd.gauss(0.0, 0.004))
        elif day <= "2026-06-12":
            # 上行段：均值+0.05%，叠加噪声
            idx_ret.append(0.0005 + rnd.gauss(0.0, 0.006))
        else:
            # 回落段：均值-0.5%
            idx_ret.append(-0.005 + rnd.gauss(0.0, 0.006))
    # 构造指数序列
    idx = {"000300.SS": [], "000852.SS": []}
    base = {"000300.SS": 3500.0, "000852.SS": 6500.0}
    for k in idx:
        v = base[k]
        for i, day in enumerate(days):
            # 中证1000波动更大
            r = idx_ret[i] * (1.3 if k == "000852.SS" else 1.0)
            v = v * (1 + r)
            idx[k].append((day, v))

    # 构造个股
    market = Market()
    market.days = days
    codes = []
    # 注意：用【不会撞真实代码】的编号（98xxxx.SS / 12xxxx.SZ），均属主板。
    # 这样 _industry_of 稳定返回 ""（无映射），行业过滤退化为单伪行业、靠数量共振，
    # 忠实还原"平台无行业映射"时的行为；避免撞 industry_map.json 真实代码导致
    # 个股被随机分入真实行业、共振过滤把候选砍光。
    plan = [("98SS", 70), ("12SZ", 70)]
    cid = 1
    for prefix, cnt in plan:
        for _ in range(cnt):
            if prefix == "98SS":
                code = "98%04d.SS" % (1000 + cid)
            else:
                code = "12%04d.SZ" % (1000 + cid)
            codes.append(code)
            cid += 1

    # 给每个股分配行业 + 个股 beta + 个股漂移
    stock_ind = {}
    stock_beta = {}
    stock_drift = {}
    for i, code in enumerate(codes):
        ind = INDUSTRIES[i % len(INDUSTRIES)]
        stock_ind[code] = ind
        stock_beta[code] = rnd.uniform(0.6, 1.4)
        stock_drift[code] = rnd.gauss(0.0003, 0.0006)  # 轻微个股趋势

    # 热点行业 -> 事件日
    hot_ind_day = {v: k for k, v in HOT_EVENTS.items()}

    # 把指数日收益按日对齐成 dict
    idx_ret_by_day = {day: idx_ret[i] for i, day in enumerate(days)}

    # 涨停梯队：真实 A 股每日涨停家数随大市波动（20~70 家区间）。
    # 不给涨停会让 MARKET_ZT_FLOOR(25) 永远判 ICE -> 情绪闸门永久半仓，代理结果失真。
    zt_by_day = {}
    for day in days:
        ir = idx_ret_by_day[day]
        n = int(round(28 + 400 * ir))
        n = max(3, min(70, n))
        # 当日热点事件股不进涨停梯队（涨停不可买，会吞掉候选）
        excl = set(c for c in codes if hot_ind_day.get(stock_ind[c]) == day)
        cand = [c for c in codes if c not in excl]
        zt_by_day[day] = set(rnd.sample(cand, min(n, len(cand))))

    # 生成每只股票日线
    for code in codes:
        ind = stock_ind[code]
        beta = stock_beta[code]
        drift = stock_drift[code]
        price = rnd.uniform(6.0, 70.0)
        bars = []
        prev_close = price
        ev_day = hot_ind_day.get(ind)  # 该股行业的热点事件日（可能无）
        for i, day in enumerate(days):
            ir = idx_ret_by_day[day]
            # 基础日收益
            ret = beta * ir + drift + rnd.gauss(0.0, 0.012)
            # 热点事件日前 5 日注入上升通道（保证 MA20>MA60、形态>=2）
            if ev_day:
                dd = (datetime.date(*map(int, ev_day.split("-"))) -
                      datetime.date(*map(int, day.split("-")))).days
                if 1 <= dd <= 5:
                    ret += 0.008
            # 热点事件日：该股所在行业获得 +[3.5%,6%](主板/创业) 或 +[6%,9%](科创) 跳升。
            # 【口径】平台日线不含当日，10:30 的当日价来自 data 快照（本引擎取当日开盘，
            #   无未来函数）。故事件涨幅必须体现在【开盘缺口】上——这也符合真实热点股
            #   "开盘即跳空高开"的形态；若只写在收盘价上，盘中扫描必然看不到达标涨幅。
            gap_ev = None
            if ev_day and day == ev_day:
                if code.startswith("68"):
                    gap_ev = rnd.uniform(0.060, 0.090)
                else:
                    gap_ev = rnd.uniform(0.035, 0.060)
                ret = gap_ev + rnd.uniform(0.0, 0.010)
            # 事件后 2 日轻微回落（制造后续止盈/止损信号，不平直持有）
            if ev_day:
                dd = (datetime.date(*map(int, day.split("-"))) -
                      datetime.date(*map(int, ev_day.split("-")))).days
                if 1 <= dd <= 2:
                    ret -= 0.010
            # 涨停梯队：直接封板（ALLOW_LIMIT_UP_BUY=False，故不参与买入，仅贡献情绪）
            if code in zt_by_day.get(day, ()):
                ret = 0.10
            close = max(1.0, price * (1 + ret))
            gap = rnd.gauss(0.0, 0.004)
            o = max(1.0, prev_close * (1 + gap))
            # 【修 bug】热点日的跳空必须落在【开盘价】上，否则 10:30 的当日价
            # （本引擎 kind='open' 取 b.open）看不到任何事件涨幅，pct≈0 → 全池被
            # 涨幅带宽滤掉 → 引擎永远 0 成交。上面注释早就写明"事件涨幅必须体现在
            # 开盘缺口上"，但代码只给了 o 一个高斯小缺口 —— 注释与实现对不上。
            if gap_ev is not None:
                o = prev_close * (1.0 + gap_ev)      # 开盘即跳空高开
            hi = max(o, close) * (1 + abs(rnd.gauss(0.0, 0.006)))
            lo = min(o, close) * (1 - abs(rnd.gauss(0.0, 0.006)))
            vol = rnd.uniform(5e7, 2e8)
            # 热点日放巨量。倍数取 4~6 倍（而非 2.5~3.5）是有意的：策略在 10:30
            # 用的是「当日累计量 / 前5日均量」，10:30 只累计了全天约 45%，
            # 故全天量必须达到均量的 4 倍以上，盘中量比才可能 >1.5 ——
            # 这正是「量比」在盘中的真实含义，也是本策略要求的最低门槛。
            if ev_day and day == ev_day:
                vol *= rnd.uniform(4.0, 6.0)
            money = vol * ((o + close) / 2.0)
            bars.append(Bar(day, o, hi, lo, close, vol, money, prev_close))
            prev_close = close
            price = close
        market.add(code, bars)

    # 指数也加入 market（供 get_history 直接取）
    for k in idx:
        bars = []
        for i, (day, v) in enumerate(idx[k]):
            pc = idx[k][i - 1][1] if i > 0 else v
            o = pc * (1 + rnd.gauss(0, 0.002))
            hi = max(o, v) * 1.002
            lo = min(o, v) * 0.998
            bars.append(Bar(day, o, hi, lo, v, 1e8, v * 1e8, pc))
        market.add(k, bars)

    return market


# ----------------------------- 真实数据 bundle（留接口）---------------------
class CSVBundleProvider(object):
    """把 PTrade/东方财富导出的日线 bundle 载入 Market。

    目录结构（每只股票一个 csv，指数同格式）：
        bundle/<code>.csv   列: date,open,high,low,close,volume,amount
        bundle/000300.SS.csv
        bundle/000852.SS.csv
    code 形如 600001.SS / 000001.SZ / 300001.SZ / 688001.SS
    """

    def __init__(self, bundle_dir):
        self.bundle_dir = bundle_dir

    def load(self):
        market = Market()
        d = self.bundle_dir
        files = [f for f in os.listdir(d) if f.endswith(".csv")]
        all_days = set()
        for f in files:
            code = f[:-4]
            rows = []
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                hdr = fh.readline()
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    p = line.split(",")
                    day = p[0]
                    o, h, l, c = float(p[1]), float(p[2]), float(p[3]), float(p[4])
                    v = float(p[5])
                    m = float(p[6]) if len(p) > 6 else v * c
                    pc = float(p[7]) if len(p) > 7 else (rows[-1].close if rows else c)
                    rows.append(Bar(day, o, h, l, c, v, m, pc))
                    all_days.add(day)
            market.add(code, rows)
        market.days = sorted(all_days)
        return market


# ----------------------------- 统计 -----------------------------------------
def parse_strategy_sells(log_lines):
    """从策略自身 [卖出] 日志解析 (原因, 盈亏%) —— 比引擎记账更贴近策略口径。"""
    import re
    # 兼容两种写法：
    #   [卖出] 600001.SS —— 止盈全清 浮盈31.2%
    #   [卖出] 600001.SS 数量100 减半 浮盈13.3%
    pat = re.compile(
        r"\[(\d{4}-\d{2}-\d{2})\].*\[卖出\]\s+(\S+)"
        r"(?:\s+数量\d+)?\s*(?:——)?\s*(\S+?)\s+浮(盈|亏)(-?[\d.]+)%")
    out = []
    for ln in log_lines:
        m = pat.search(ln)
        if not m:
            continue
        day, code, reason, sign, num = m.groups()
        pnl = float(num) / 100.0
        if sign == "亏":
            pnl = -abs(pnl)
        out.append((day, code, reason, pnl))
    return out


def compute_stats(net_series, sell_log):
    if not net_series:
        return {}
    days = [d for d, _ in net_series]
    vals = [v for _, v in net_series]
    start = vals[0]
    end = vals[-1]
    total_ret = end / start - 1.0
    n = len(vals)
    years = (datetime.date(*map(int, days[-1].split("-"))) -
             datetime.date(*map(int, days[0].split("-")))).days / 365.0
    ann = (end / start) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    # 最大回撤
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd
    # 日收益夏普
    rets = [(vals[i] / vals[i - 1] - 1.0) for i in range(1, n)]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var_r = sum((x - mean_r) ** 2 for x in rets) / len(rets) if rets else 0.0
    std_r = var_r ** 0.5
    sharpe = (mean_r / std_r) * (250 ** 0.5) if std_r > 0 else 0.0
    calmar = (ann / abs(mdd)) if mdd < 0 else 0.0
    # 交易统计
    wins = [s for s in sell_log if s[3] > 0]
    losses = [s for s in sell_log if s[3] <= 0]
    win_rate = len(wins) / len(sell_log) if sell_log else 0.0
    avg_win = sum(s[3] for s in wins) / len(wins) if wins else 0.0
    avg_loss = sum(s[3] for s in losses) / len(losses) if losses else 0.0
    pf = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
    return {
        "start": start, "end": end, "total_ret": total_ret, "ann": ann,
        "mdd": mdd, "sharpe": sharpe, "calmar": calmar,
        "trades": len(sell_log), "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss, "profit_factor": pf,
    }


# ----------------------------- 主程序 ---------------------------------------
def main():
    # 加载融合策略（原文件不变）
    spec = importlib.util.spec_from_file_location("fusion_strat", FUSION_PY)
    strat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strat)

    # 行业映射
    ind_map = {}
    if os.path.isfile(IND_MAP):
        ind_map = json.load(open(IND_MAP, encoding="utf-8"))
    # 优先用 sector_map.json 反查（与平台外挂文件的形态一致）
    if os.path.isfile(SECTOR_MAP):
        try:
            sm = json.load(open(SECTOR_MAP, encoding="utf-8"))
            rev = {}
            for name, codes in (sm.get("industry") or {}).items():
                for c in codes:
                    k = str(c)[:6]
                    if k not in rev:
                        rev[k] = name
            if rev:
                ind_map = rev
                print("[行业] 引擎采用 sector_map.json 反查表：覆盖 %d 只" % len(rev))
        except Exception as e:
            print("[行业] sector_map 读取失败，回落 industry_map: %r" % (e,))

    # 数据：默认合成（PROXY）
    use_bundle = os.environ.get("FUSION_BUNDLE")
    if use_bundle and os.path.isdir(use_bundle):
        market = CSVBundleProvider(use_bundle).load()
        tag = "REAL(%s)" % use_bundle
    else:
        market = build_synthetic()
        tag = "PROXY(合成)"

    engine = Engine(market, ind_map)
    # 注入平台接口到策略模块
    for name in ("get_history", "get_Ashares", "get_all_stocks", "get_industry",
                 "get_snapshot", "order_target_value", "order_target", "order"):
        setattr(strat, name, getattr(engine, name))
    strat.log = engine  # Engine 实例自带 .info/.warning

    run_days = [d for d in market.days if d >= "2026-05-06"]
    strat.initialize(engine.ctx)
    # 注入行业反查表（等价于平台上传 sector_map.json 后 _load_sector_index 的结果）。
    # 不注入的话策略会走"文件不存在 → log.error → 行业恒空"分支，行业层等于没测。
    strat.g["ind_rev"] = dict(ind_map)
    engine.run(strat, run_days, emit=True)

    # 出场明细：优先用策略自身 [卖出] 日志（含原因与盈亏）
    strat_sells = parse_strategy_sells(engine.log_lines)
    sell_for_stats = strat_sells if strat_sells else engine.sell_log
    stats = compute_stats(engine.net_series, sell_for_stats)
    stats["sell_reasons"] = {}
    for s in sell_for_stats:
        r = s[2]
        stats["sell_reasons"][r] = stats["sell_reasons"].get(r, 0) + 1

    # 写出日志
    log_path = os.path.join(HERE, "融合_v1_回测日志_%s.txt" % tag.split("(")[0])
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("[指纹] ★FUSION v1.8★ 本地成交模式回测 | 数据=%s | 初始=%d\n"
                 % (tag, int(START_CASH)))
        for ln in engine.log_lines:
            fh.write(ln + "\n")
    # 写出净资产序列
    nv_path = os.path.join(HERE, "融合_v1_每日净资产_%s.csv" % tag.split("(")[0])
    with open(nv_path, "w", encoding="utf-8") as fh:
        fh.write("date,net_value\n")
        for d, v in engine.net_series:
            fh.write("%s,%.2f\n" % (d, v))
    # 写出统计
    st_path = os.path.join(HERE, "融合_v1_统计_%s.json" % tag.split("(")[0])
    json.dump({"data_tag": tag, "stats": stats}, open(st_path, "w"),
              ensure_ascii=False, indent=2)

    print("=" * 70)
    print("热点融合 v1.8 成交模式回测（数据=%s）" % tag)
    print("=" * 70)
    print("交易日数 :", len(run_days))
    print("买入笔数 :", len(engine.buy_log))
    print("卖出笔数 :", stats["trades"], "(策略口径) /", len(engine.sell_log), "(引擎成交)")
    print("最终净值 : %.2f" % stats["end"])
    print("累计收益 : %.2f%%" % (stats["total_ret"] * 100))
    print("最大回撤 : %.2f%%" % (stats["mdd"] * 100))
    print("年化收益 : %.2f%%" % (stats["ann"] * 100))
    print("夏普     : %.2f" % stats["sharpe"])
    print("卡玛     : %.2f" % stats["calmar"])
    print("胜率     : %.2f%%" % (stats["win_rate"] * 100))
    print("盈亏比   : %.2f" % stats["profit_factor"])
    print("-" * 70)
    print("日志 :", log_path)
    print("净资产:", nv_path)
    print("统计 :", st_path)
    # 卖出原因分布
    if stats.get("sell_reasons"):
        print("卖出原因:", stats["sell_reasons"])


if __name__ == "__main__":
    main()
