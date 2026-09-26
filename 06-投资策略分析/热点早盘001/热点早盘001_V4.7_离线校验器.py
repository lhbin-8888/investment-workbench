# -*- coding: utf-8 -*-
"""
热点早盘001 V4.7 离线行为校验器（不上网、不依赖 PTrade）
==========================================================
用合成行情 + 假 PTrade API 把 V4.7 的关键改动"跑一遍"：**验证行为，不验证收益**。

覆盖的 V4.7 新断言：
  EXP-1  硬止损时间闸门：09:30-09:44 触发止损 → 顺延不成交；>=09:45 才执行
         同时验证 P0-3（豁免最短持有期：持仓仅 1 日也执行硬止损）
         同时验证 P2-1（同一标的同类噪声每日只打一条日志）
  EXP-2  破均线清仓尾盘确认：D4 跌破 MA10，但只在 14:45 成交（旧版会在 09:31 就砍）
  EXP-3  分批止盈修复：200 股 → 减 100 留 100；100 股 → 不减、标记完成且不刷屏
  EXP-4  每日新建仓上限 = 3 笔
  EXP-5  换手预算口径：窗口 60 交易日 / 阈值 6 次，且回合超限时 turnover_ok 返回 False
  EXP-6  保留 V4.5 核心行为 + 新增 [净值] 日志
  EXP-7  板块级清仓仍在 14:48（V4.5 B-1~B-4 回归，禁用硬止损以隔离该分支）

用法： python 热点早盘001_V4.7_离线校验器.py
"""
import sys, os, json, types, tempfile, shutil
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(_HERE, "热点早盘001_V4.7.py")
WORK = tempfile.mkdtemp(prefix="v47_verify_")

PRE = 100
SIM = ["2026-05-06", "2026-05-07", "2026-05-08", "2026-05-11"]


def _trading_days(end, n):
    out, d = [], datetime.strptime(end, "%Y-%m-%d")
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return list(reversed(out))


DATES = _trading_days("2026-05-05", PRE) + SIM
NDAY = len(DATES)
CODES = ["600001", "600002", "600003", "600004", "600005", "600006"]

# 候选票刻意做成"信号日前一段陡坡上行"：MA10 明显低于现价，
# 才能把"破均线"与"硬止损"两个出场分支隔离开验证。
RAMP_DAYS, RAMP = 11, 5.0


def _series(sig, sim):
    return [0.0] * (PRE - 1 - RAMP_DAYS) + [RAMP] * RAMP_DAYS + [sig] + [sim] * len(SIM)


_SPEC = {
    "600001": ([0.0] * (PRE - 1) + [9.9, 1.0, 1.0, 1.0, 1.0], 2.5),   # 封板龙头：仅信号日涨停
    "600002": ([0.0] * (PRE - 1) + [9.9, 1.0, 1.0, 1.0, 1.0], 2.5),
    "600003": (_series(4.9, 0.0), 3.0),
    "600004": (_series(4.5, 0.0), 2.0),
    "600005": (_series(4.15, 0.0), 2.2),
    "600006": (_series(4.05, 0.0), 1.3),
}
PCT, CLOSE, VR = {}, {}, {}
for c, (arr, vr) in _SPEC.items():
    PCT[c] = arr
    VR[c] = vr
    v, cl = 10.0, []
    for p in arr:
        v = v * (1 + p / 100.0)
        cl.append(round(v, 3))
    CLOSE[c] = cl
BASEVOL = 2e7

LOGS, TIMES, NOW = [], [], [""]


class _Log(object):
    def info(self, m):
        LOGS.append(str(m)); TIMES.append(NOW[0])

    def warning(self, m):
        self.info("WARN " + str(m))

    def error(self, m):
        self.info("ERR " + str(m))


def day_bars(code, upto_idx, n=80):
    out = []
    for i in range(max(0, upto_idx - n), upto_idx):
        cl, p = CLOSE[code][i], PCT[code][i]
        zt = p >= 9.5
        vol = BASEVOL * VR[code] if i == upto_idx - 1 else BASEVOL
        out.append((DATES[i], cl, cl if zt else cl * 1.01, cl if zt else cl * 0.98, vol, cl))
    return out


class _Pos(object):
    def __init__(self, code, qty, cost):
        self.security, self.current_amount, self.enable_amount = code, qty, qty
        self.cost_price = self.last_price = cost


class _Portfolio(object):
    def __init__(self):
        self.cash = 1e6
        self.portfolio_value = 1e6


class _Ctx(object):
    def __init__(self):
        self.blotter = types.SimpleNamespace(current_dt=datetime(2026, 1, 1, 8, 30))
        self.now = self.blotter.current_dt
        self.portfolio = _Portfolio()


class Env(object):
    def __init__(self):
        self.g, self.ctx = types.SimpleNamespace(), _Ctx()
        self.positions, self.prices = {}, {}
        self.day_idx, self.seq = 0, 0

    def get_history(self, n=None, freq="1d", fields=None, part=None, fq=None, is_dict=None):
        out = {}
        for pc in (part or []):
            code = "".join(ch for ch in str(pc) if ch.isdigit())[:6]
            src = code if code in CLOSE else "600003"
            rows = day_bars(src, self.day_idx, 60)
            if code in CLOSE:
                out[pc] = {"date": [r[0] for r in rows], "open": [r[5] for r in rows],
                           "close": [r[1] for r in rows], "high": [r[2] for r in rows],
                           "low": [r[3] for r in rows], "volume": [r[4] for r in rows]}
            else:
                out[pc] = {"date": [r[0] for r in rows], "open": [3000.0] * len(rows),
                           "close": [3000.0] * len(rows), "high": [3010.0] * len(rows),
                           "low": [2990.0] * len(rows), "volume": [1e9] * len(rows)}
        return out

    def get_current_data(self):
        return None

    def get_positions(self):
        return dict(self.positions)

    def get_position(self):
        return None

    def get_total_assets(self):
        return self.ctx.portfolio.portfolio_value

    def get_cash(self):
        return self.ctx.portfolio.cash

    def get_stock_name(self, code):
        return "测试股"

    def get_research_path(self):
        return WORK

    def order_value(self, api_code, value, limit_price=None):
        px = float(limit_price or 0)
        if px <= 0:
            return None
        qty = int(int(value) / px / 100) * 100
        if qty <= 0:
            return None
        self.seq += 1
        p = _Pos(api_code, qty, px)
        p.enable_amount = 0
        self.positions[api_code] = p
        self.ctx.portfolio.cash -= qty * px
        return "OID%d" % self.seq

    def order(self, api_code, amount):
        p = self.positions.get(api_code)
        if p is None:
            return None
        qty = min(abs(int(amount)), p.enable_amount)
        if qty <= 0:
            return None
        self.seq += 1
        p.current_amount -= qty
        p.enable_amount -= qty
        self.ctx.portfolio.cash += qty * p.last_price
        if p.current_amount <= 0:
            self.positions.pop(api_code, None)
        return "OID%d" % self.seq

    def run_daily(self, ctx, fn, time=None):
        return True

    def set_benchmark(self, c):
        return True

    def set_commission(self, **kw):
        return True

    def set_slippage(self, **kw):
        return True


def build_env():
    del LOGS[:], TIMES[:]
    env = Env()
    gl = {"log": _Log(), "g": env.g, "get_history": env.get_history,
          "get_current_data": env.get_current_data, "get_positions": env.get_positions,
          "get_position": env.get_position, "get_total_assets": env.get_total_assets,
          "get_cash": env.get_cash, "get_stock_name": env.get_stock_name,
          "get_research_path": env.get_research_path, "order_value": env.order_value,
          "order": env.order, "run_daily": env.run_daily, "set_benchmark": env.set_benchmark,
          "set_commission": env.set_commission, "set_slippage": env.set_slippage,
          "get_datetime": lambda: env.ctx.blotter.current_dt}
    mod = types.ModuleType("strat")
    mod.__dict__.update(gl)
    exec(compile(open(STRAT, encoding="utf-8").read(), STRAT, "exec"), mod.__dict__)
    env.mod = mod
    mod.MARKET_ZT_FLOOR = 0
    mod.REGIME_USE_INDEX_MA20 = False
    env.mod.initialize(env.ctx)
    return env


def set_time(env, day, hhmm):
    h, m = [int(x) for x in hhmm.split(":")]
    dt = datetime.strptime(day, "%Y-%m-%d").replace(hour=h, minute=m)
    env.ctx.blotter.current_dt = dt
    env.ctx.now = dt
    NOW[0] = hhmm


def refresh_prices(env, di, px_fn=None):
    """按剧本刷新"当日日内价"。px_fn(env, k, code) -> float|None；k = 模拟日序号 1..4。"""
    env.prices = {}
    k = di - PRE + 1
    for c in CODES:
        v = px_fn(env, k, c) if px_fn else None
        if v:
            env.prices[c] = v
    for p in env.positions.values():
        code = "".join(ch for ch in p.security if ch.isdigit())[:6]
        p.last_price = env.prices.get(code, p.last_price)


def run_day(env, di, px_fn=None, scan=True):
    day = DATES[di]
    env.day_idx = di
    mod, ctx = env.mod, env.ctx
    set_time(env, day, "08:30")
    mod.before_trading_start(ctx, {})
    for p in env.positions.values():
        p.enable_amount = p.current_amount          # T+1：今日可卖
    refresh_prices(env, di, px_fn)
    for hhmm in ["09:30", "09:31"]:
        set_time(env, day, hhmm)
        if hhmm == "09:31":
            mod.early_job(ctx)
        mod.handle_data(ctx, dict([(c, {"close": px}) for c, px in env.prices.items()]))
    set_time(env, day, "09:32")
    mod.buy_job(ctx)
    mod.handle_data(ctx, {})
    if not scan:
        return day
    for h in range(9, 16):
        for m in range(60):
            t = "%02d:%02d" % (h, m)
            if "09:33" <= t <= "15:00":
                set_time(env, day, t)
                if t == "14:48":
                    mod.risk_fallback_job(ctx)
                mod.handle_data(ctx, {})
    return day


def find(kw, pre=None):
    return [(i, m) for i, m in enumerate(LOGS)
            if (pre is None or m.startswith(pre)) and kw in m]


def cost_of(env, code):
    p = env.positions.get(code + ".SS")
    return p.cost_price if p else 0.0


def inject(env, code, qty, cost, px, sector="测试题材", hold_days=2):
    """手工注入持仓（供分批止盈等需要精确股数/成本的断言使用）。"""
    p = _Pos(code + ".SS", qty, cost)
    p.enable_amount = qty
    p.last_price = px
    env.positions[code + ".SS"] = p
    env.g.hold_days[code] = hold_days
    env.g.peak[code] = px
    env.g.code_sector[code] = sector
    env.g.partial_done.discard(code)
    return p


# ============================================================
# 断言工具
# ============================================================
RESULTS = []


def chk(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  | " + detail) if detail else ""))
    RESULTS.append((name, bool(cond)))


def sells():
    return find("", "[卖出] ")


def sell_rows():
    """解析 [卖出] 行 → (时刻, code, 股数, 原因)"""
    out = []
    for i, m in sells():
        try:
            body = m.split("[卖出] ", 1)[1]
            parts = body.split()
            code, qty = parts[0], int(parts[1])
            reason = body.split("原因:", 1)[1].split(" 委托=", 1)[0]
            out.append((TIMES[i], code, qty, reason))
        except Exception:
            out.append((TIMES[i], "?", 0, m))
    return out


# ============================================================
# EXP-1 硬止损时间闸门 + 豁免最短持有 + 噪声去重
# ============================================================
def exp1_stop_gate():
    print("\n[EXP-1] 硬止损时间闸门（09:45 起）+ 豁免最短持有期 + 噪声去重")
    env = build_env()
    mod = env.mod
    mod.MAX_POSITIONS = 1                    # 只允许持 1 只 → D2 不会加新仓
    mod.MAX_NEW_POSITIONS_PER_DAY = 1
    run_day(env, PRE, scan=False)            # D1：建仓
    bought = sorted(env.positions.keys())
    chk("1.1 D1 建仓 1 只（600003）", bought == ["600003.SS"], "实际=%s" % bought)

    def px_fn(e, k, c):
        if k >= 2 and c == "600003":
            return cost_of(e, "600003") * 0.945      # -5.5% > ATR 上限 5%
        return None

    del LOGS[:], TIMES[:]
    run_day(env, PRE + 1, px_fn=px_fn)       # D2：全天扫描
    hold_during = env.g.hold_days.get("600003")   # D2 盘前自增后的持仓天数
    rows = sell_rows()
    times = [r[0] for r in rows]
    chk("1.2 硬止损已成交（1 笔）", len(rows) == 1 and "止损" in rows[0][3],
        "卖出=%s" % rows)
    chk("1.3 止损成交时刻 = 09:45（不在开盘噪声区）", times == ["09:45"], "时刻=%s" % times)
    chk("1.4 P0-3 豁免最短持有期（hold_days=1 < 门槛 3 仍执行硬止损）",
        hold_during == 1 and env.mod.MIN_HOLD_FOR_TIGHT_STOP == 3,
        "D2 持仓天数=%s, 门槛=%s" % (hold_during, env.mod.MIN_HOLD_FOR_TIGHT_STOP))
    n_floor = len(find("触发硬止损", "[风控] "))
    chk("1.5 P2-1 噪声去重：09:30-09:44 共 15 次顺延只打 1 条日志",
        n_floor == 1, "日志条数=%d" % n_floor)
    return env


# ============================================================
# EXP-2 破均线清仓尾盘确认（14:45）
# ============================================================
def exp2_break_gate():
    print("\n[EXP-2] 破均线清仓改为尾盘确认（只在 14:45 之后成交）")
    env = build_env()
    mod = env.mod
    mod.MAX_POSITIONS = 1
    mod.MAX_NEW_POSITIONS_PER_DAY = 1
    mod.STOP_MODE = "fixed"
    mod.STOP_LOSS_PCT = 0.90                 # 软禁用硬止损，隔离"破均线"分支
    run_day(env, PRE, scan=False)
    chk("2.1 D1 建仓 1 只", sorted(env.positions.keys()) == ["600003.SS"],
        "实际=%s" % sorted(env.positions.keys()))

    def px_fn(e, k, c):
        if c != "600003":
            return None
        if k in (2, 3):
            return cost_of(e, "600003") * 1.00    # 横盘：不触发任何出场
        if k == 4:
            return cost_of(e, "600003") * 0.80    # 暴跌 20% → 跌破 MA10
        return None

    del LOGS[:], TIMES[:]
    run_day(env, PRE + 1, px_fn=px_fn)       # D2 hold_days=1
    run_day(env, PRE + 2, px_fn=px_fn)       # D3 hold_days=2
    run_day(env, PRE + 3, px_fn=px_fn)       # D4 hold_days=3 → 破均线可执行
    rows = sell_rows()
    times = sorted(set(r[0] for r in rows))
    chk("2.2 D4 破均线清仓已成交", len(rows) >= 1, "卖出=%s" % rows)
    chk("2.3 成交时刻 = 14:45（尾盘确认，非 09:31/09:32）", times == ["14:45"], "时刻=%s" % times)
    chk("2.4 原因标注尾盘确认", any("尾盘确认" in r[3] for r in rows),
        "原因=%s" % [r[3] for r in rows])
    chk("2.5 全天无 09:35 前卖出（旧版首因已消除）",
        all(r[0] >= "14:45" for r in rows), "时刻=%s" % [r[0] for r in rows])
    return env


# ============================================================
# EXP-3 分批止盈修复
# ============================================================
def exp3_partial():
    print("\n[EXP-3] 分批止盈：减仓后至少留 1 手（修 `0 < half < amount` 失效 bug）")
    # 3a: 200 股 → 减 100 留 100
    env = build_env()
    inject(env, "600003", 200, cost=10.0, px=11.3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    set_time(env, "2026-05-06", "10:30")
    env.g.now_str = "10:30"
    env.mod.monitor_risk(env.ctx, sector_clear=False)
    rows = sell_rows()
    left = env.positions.get("600003.SS")
    chk("3.1 200 股 → 减 100 股", len(rows) == 1 and rows[0][2] == 100 and "分批止盈" in rows[0][3],
        "卖出=%s" % rows)
    chk("3.2 剩余保留 100 股（不是全清）", left is not None and left.current_amount == 100,
        "剩余=%s" % (left.current_amount if left else None))

    # 3b: 100 股 → 不减、标记完成、日志只 1 条
    env2 = build_env()
    inject(env2, "600003", 100, cost=10.0, px=11.3)
    env2.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    for t in ("10:30", "10:31", "10:32"):     # 连打 3 次，验证去重
        set_time(env2, "2026-05-06", t)
        env2.g.now_str = t
        env2.mod.monitor_risk(env2.ctx, sector_clear=False)
    rows2 = sell_rows()
    chk("3.3 100 股 → 不减仓（_round_lot(50,100)=100 的边界不再误判）", len(rows2) == 0,
        "卖出=%s" % rows2)
    chk("3.4 已标记 partial_done（避免每轮重算）", "600003" in env2.g.partial_done)
    n_small = len(find("不足 2 手无法分批", "[风控] "))
    chk("3.5 连打 3 次只打 1 条日志（噪声去重）", n_small == 1, "日志条数=%d" % n_small)
    return env


# ============================================================
# EXP-4 每日建仓上限 = 3
# ============================================================
def exp4_daily_cap():
    print("\n[EXP-4] 每日新建仓上限 = 3 笔（V4.5 为 2）")
    env = build_env()
    mod = env.mod
    mod.MAX_PER_SECTOR = 6                   # 放宽板块限制，隔离"每日上限"
    mod.CLUSTER_MAX_WEIGHT = 0               # 关闭产业链簇约束
    mod.MAX_NEW_POSITIONS_PER_DAY = 3
    run_day(env, PRE, scan=False)
    bu = find("委托=OID", "[买入] ")
    codes = []
    for i, m in bu:
        try:
            codes.append(m.split("[买入] ", 1)[1].split()[0])
        except Exception:
            pass
    chk("4.1 D1 恰好建仓 3 笔", len(bu) == 3, "买入 %d 笔: %s" % (len(bu), codes))
    chk("4.2 参数确为 3", mod.MAX_NEW_POSITIONS_PER_DAY == 3)
    return env


# ============================================================
# EXP-5 换手预算口径
# ============================================================
def exp5_turnover():
    print("\n[EXP-5] 换手预算：窗口 60 交易日 / 阈值 6 次（折年 ≈25 次）")
    env = build_env()
    mod = env.mod
    chk("5.1 参数 = (60 交易日, 6 次)",
        mod.TURNOVER_WINDOW_DAYS == 60 and mod.MAX_ANNUAL_TURNS == 6,
        "window=%s turns=%s" % (mod.TURNOVER_WINDOW_DAYS, mod.MAX_ANNUAL_TURNS))
    # 未超预算 → True
    env.g.trades = [("2026-05-06", 1.0e7, "buy")]
    ok1 = mod.turnover_ok(env.ctx, 1e6)
    # 超预算（traded/(2×1e6) = 6.5 > 6）→ False
    env.g.trades = [("2026-05-06", 1.3e7, "buy")]
    ok2 = mod.turnover_ok(env.ctx, 1e6)
    chk("5.2 换手 5.0 次 ≤ 6 → 允许开仓", ok1 is True)
    chk("5.3 换手 6.5 次 > 6 → 熔断停开新仓", ok2 is False)
    env.g.trades = []
    return env


# ============================================================
# EXP-6 V4.5 核心行为回归 + [净值] 日志
# ============================================================
def exp6_regression():
    print("\n[EXP-6] V4.5 核心行为回归 + [净值] 日志（P2-2）")
    env = build_env()

    def px_fn(e, k, c):
        if k == 1:
            if c == "600003":
                return CLOSE[c][PRE - 1] * 1.005     # handle_data 日内价路径
            return None
        p = e.positions.get(c + ".SS")
        if not p:
            return None
        MULT = {"600003": {2: 1.13, 3: 1.05, 4: 0.93},
                "600004": {2: 0.99, 3: 0.99, 4: 0.985}}
        mult = MULT.get(c, {}).get(k)
        return p.cost_price * mult if mult else None

    for di in range(PRE, NDAY):
        run_day(env, di, px_fn=px_fn)

    net = find("", "[净值] ")
    chk("6.1 新增 [净值] 日终打印（覆盖 4 个交易日）", len(net) >= 4, "%d 条" % len(net))
    src_log = find("", "[口径-来源] ")
    chk("6.2 handle_data 日内价路径生效（src=bar:handle_data）",
        any("bar:handle_data" in m for i, m in src_log), src_log[0][1] if src_log else "无")
    srows = sell_rows()
    # ★注意★ 分批止盈 / 移动止盈属"锁利"动作，不受出场时间闸门约束（设计如此）；
    #   受闸门约束的是"趋势类"（破均线，>=14:45）与"风险类"（硬止损，>=09:45）。
    early = [r for r in srows if r[0] < "09:45" and ("破" in r[3] or "止损" in r[3])]
    chk("6.3 无 09:45 前的趋势类/止损类卖出（分批止盈不受闸门约束，属预期）",
        not early, "越闸卖出=%s" % early)
    clear = [r for r in srows if "板块联动清仓" in r[3]]
    chk("6.4 板块级清仓只发生在 14:48",
        all(r[0] == "14:48" for r in clear), "清仓=%s" % [r[0] for r in clear])
    partn = [r for r in srows if "分批止盈" in r[3]]
    chk("6.5 分批止盈仍只减一次（V4.5 B-8 回归）", len(partn) <= 1, "减仓 %d 次" % len(partn))
    chk("6.6 卖出同步记账（g.trades 含 sell）",
        any(s == "sell" for (d, v, s) in env.g.trades), "g.trades=%d 条" % len(env.g.trades))
    return env


def exp7_sector_clear():
    print("\n[EXP-7] 板块级清仓仍在 14:48（V4.5 B-1~B-4 回归；本场景禁用硬止损以隔离该分支）")
    env = build_env()
    mod = env.mod
    mod.STOP_MODE = "fixed"
    mod.STOP_LOSS_PCT = 0.90                 # 软禁用硬止损，让板块清仓成为唯一出口

    def px_fn(e, k, c):
        if k == 1:
            if c == "600003":
                return CLOSE[c][PRE - 1] * 1.005
            return None
        p = e.positions.get(c + ".SS")
        if not p:
            return None
        # D3 回到成本（浮盈 0% → 不武装移动止盈，避免它抢在板块清仓之前出手）
        MULT = {"600003": {2: 1.13, 3: 1.00, 4: 0.93},
                "600004": {2: 0.99, 3: 0.99, 4: 0.985}}
        mult = MULT.get(c, {}).get(k)
        return p.cost_price * mult if mult else None

    for di in range(PRE, NDAY):
        run_day(env, di, px_fn=px_fn)

    rows = sell_rows()
    clear = [r for r in rows if "板块联动清仓" in r[3]]
    chk("7.1 板块级清仓已成交", len(clear) >= 1, "全部卖出=%s" % rows)
    chk("7.2 成交时刻 = 14:48（唯一判定时点，非开盘）",
        bool(clear) and all(r[0] == "14:48" for r in clear),
        "时刻=%s" % [r[0] for r in clear])
    n_hold = len(find("不在此强平", "[风控] "))
    chk("7.3 最短持有保护生效：D2/D3 判退潮但持仓不足 3 日 → 不强平",
        n_hold >= 2, "%d 条保护日志" % n_hold)
    return env


def main():
    if not os.path.isdir(WORK):
        os.makedirs(WORK)
    os.chdir(WORK)
    with open(os.path.join(WORK, "sector_map.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "offline-verify", "generated_at": "2026-09-20", "industry": {},
                   "concept": {"测试题材": [c + ".SS" for c in CODES]}}, f, ensure_ascii=False)

    print("=" * 78)
    print("热点早盘001 V4.7 离线行为校验（合成行情；验证行为，不验证收益）")
    print("=" * 78)
    try:
        exp1_stop_gate()
        exp2_break_gate()
        exp3_partial()
        exp4_daily_cap()
        exp5_turnover()
        exp6_regression()
        exp7_sector_clear()
    finally:
        os.chdir(_HERE)
        shutil.rmtree(WORK, ignore_errors=True)

    fails = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 78)
    print("结果: %s（共 %d 项断言，%d 项失败）" % (
        "全部通过" if not fails else "存在失败", len(RESULTS), len(fails)))
    for f in fails:
        print("   FAIL -> " + f)
    print("=" * 78)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
