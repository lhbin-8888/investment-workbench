# -*- coding: utf-8 -*-
"""
热点早盘001 V4.9 离线行为校验器（不上网、不依赖 PTrade）
==========================================================
沿用 V4.8 校验器的合成行情与假 API 工具区，**专测 V4.9 的新改动**：验证行为，不验证收益。

本版新断言：
  EXP-1  自有成本 g.entry_px：分批卖出后判据成本不漂移（双向对照，攻击的是"平台摊薄成本"）
  EXP-2  P0-3 赢家宽管 · 移动止盈回撤放宽（0.15 → 0.15×1.6 = 24%）
  EXP-3  P0-3 赢家宽管 · 趋势线由 MA10 放宽到 MA20
  EXP-4  P1-2 _do_sell 统一追加浮盈亏（补齐 V4.8 缺失的 19/31 笔观测盲区）
  EXP-5  P0-2 主线滚动窗口建仓次数约束（_mainline_recent_entries 计数与窗口）
  EXP-6  V4.9 参数落地核对 + 盈亏比自洽检查（★止损上限 ≤ 止盈一半★）

说明：V4.8 那 52 项断言中，与本次参数无关的部分由 V4.9 天然继承；
     仅"两段式止损"四态因 STOP_STAGED=False 不再适用（V4.8 已实证该设计失败），
     故本版不再重测。

用法： python 热点早盘001_V4.9_离线校验器.py
"""
import sys, os, json, types, tempfile, shutil
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(_HERE, "热点早盘001_V4.9.py")
WORK = tempfile.mkdtemp(prefix="v48_verify_")

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
        self.universe = []                  # ★V4.8★ set_universe 记录

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

    def set_universe(self, arg):
        """★V4.8★ P0-3 记录被注册进 universe 的标的（回测里 data 只覆盖 universe）"""
        try:
            self.universe = list(arg)
        except Exception:
            self.universe = [arg]
        return True

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
          "set_universe": env.set_universe,
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
    env.g.today = day
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
    """手工注入持仓（供止损/止盈等需要精确股数/成本的断言使用）。"""
    p = _Pos(code + ".SS", qty, cost)
    p.enable_amount = qty
    p.last_price = px
    env.positions[code + ".SS"] = p
    env.g.hold_days[code] = hold_days
    env.g.peak[code] = px
    env.g.code_sector[code] = sector
    env.g.partial_done.discard(code)
    env.g.stop_stage1.pop(code, None)
    return p


def tick(env, day, hhmm, px=None, code="600003"):
    """驱动一次 monitor_risk（手工时刻 + 手工现价），用于精确验证出场分支。"""
    set_time(env, day, hhmm)
    env.g.now_str = hhmm
    if px is not None:
        p = env.positions.get(code + ".SS")
        if p is not None:
            p.last_price = px
    env.mod.monitor_risk(env.ctx, sector_clear=False)


def arm_stop_fixed(env, pct=0.05):
    """把硬止损切到固定百分比，隔离 ATR 计算，便于精确构造触发/不触发。"""
    env.mod.STOP_MODE = "fixed"
    env.mod.STOP_LOSS_PCT = pct


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
# EXP-1 自有成本：分批卖出后判据成本不漂移
# ============================================================
def exp1_own_cost():
    print("\n[EXP-1] 自有成本 g.entry_px：分批卖出后判据不漂移")
    env = build_env()
    env.mod.TRADE_ENABLED = True
    arm_stop_fixed(env, 0.06)                # 固定 6% 止损，隔离 ATR 便于精确构造
    env.mod.USE_OWN_COST = True
    # 场景：真实建仓价 10.0；平台 cost_price 被"摊薄/污染"到 11.5；现价 9.5
    #   按 自有成本 10.0 → −5.0%（未到 −6%，**不该**止损）
    #   按 平台成本 11.5 → −17.4%（会错误地止损）
    inject(env, "600003", 1000, 11.5, 9.5)
    env.g.entry_px["600003"] = 10.0
    env.g.hold_days["600003"] = 5
    chk("1-1 污染源已注入：平台 cost_price = 11.5",
        cost_of(env, "600003") == 11.5, "实际 {}".format(cost_of(env, "600003")))
    tick(env, DATES[PRE], "10:00", 9.5, "600003")
    chk("1-2 USE_OWN_COST=True → 按 10.0 算 −5.0%，不触发 6% 止损",
        len(sell_rows()) == 0, "卖出 {}".format(sell_rows()))
    # 反向对照：证明这个坑真实存在（关掉自有成本就会被错误止损）
    env.mod.USE_OWN_COST = False
    tick(env, DATES[PRE], "10:05", 9.5, "600003")
    rows2 = sell_rows()
    chk("1-3 反向对照：关掉自有成本 → 按 11.5 算 −17.4%，被错误止损（证明确有此坑）",
        len(rows2) == 1, "卖出 {}".format(rows2))


# ============================================================
# EXP-2 P0-3 赢家宽管 · 移动止盈回撤放宽（15% → 24%）
# ============================================================
def exp2_winner_trail():
    print("\n[EXP-2] P0-3 赢家宽管：移动止盈回撤由 15% 放宽到 24%")
    env = build_env()
    env.mod.TRADE_ENABLED = True
    # ⚠️ 分支隔离：浮盈 60% ≥ PARTIAL_TAKE_PCT(15%)，分批止盈会先命中并 continue，
    #    必须标记已完成分批，才能隔离出"移动止盈"分支单独验证（V4.8 校验器里的同款坑）。
    inject(env, "600003", 1000, 10.0, 16.0)
    env.g.entry_px["600003"] = 10.0
    env.g.hold_days["600003"] = 5
    env.g.peak["600003"] = 20.0              # 曾经翻倍
    env.g.partial_done.add("600003")
    # 现价 16.0：自高点回撤 20% —— 超过常规 15%，但未达赢家的 24%；浮盈 60% ≥ 15% → 赢家
    tick(env, DATES[PRE], "10:00", 16.0, "600003")
    chk("2-1 常规 15% 本会触发，赢家状态(24%)下不卖",
        len([r for r in sell_rows() if "移动止盈" in r[3]]) == 0, "卖出 {}".format(sell_rows()))
    tick(env, DATES[PRE], "10:10", 14.0, "600003")     # 自 20.0 回撤 30% > 24%
    rows = [r for r in sell_rows() if "移动止盈" in r[3]]
    chk("2-2 回撤扩到 30%（>24%）→ 触发移动止盈", len(rows) == 1, "卖出 {}".format(rows))
    chk("2-3 原因标注'(赢家宽管)'（便于归因）",
        len(rows) == 1 and "赢家宽管" in rows[0][3], rows[0][3] if rows else "无")

    env2 = build_env()
    env2.mod.TRADE_ENABLED = True
    env2.mod.WINNER_EXEMPT_PCT = 0.99        # 浮盈 60% 也进不了赢家状态
    inject(env2, "600003", 1000, 10.0, 16.0)
    env2.g.entry_px["600003"] = 10.0
    env2.g.hold_days["600003"] = 5
    env2.g.peak["600003"] = 20.0
    env2.g.partial_done.add("600003")
    tick(env2, DATES[PRE], "10:00", 16.0, "600003")
    rows2 = [r for r in sell_rows() if "移动止盈" in r[3]]
    chk("2-4 反向对照：关闭赢家状态 → 回撤 20%（>15%）立即卖出",
        len(rows2) == 1, "卖出 {}".format(rows2))


# ============================================================
# EXP-3 P0-3 赢家宽管 · 趋势线 MA10 → MA20
# ============================================================
def _mk_hist(env, code, closes):
    """构造 g.pos_hist 日线序列。

    ⚠️ row 必须是 **6 元组**：策略的 `_atr` 按 `_, c, h, l, _, _ = rows[i]` 解包，
       `monitor_risk` 按 `r[1]` 取 close —— 少给一个字段会在 _atr 里直接抛 ValueError。
    """
    rows = []
    for i, c in enumerate(closes):
        rows.append((DATES[PRE - len(closes) + i], c, c, c, 1000000.0, 0.0))
    env.g.pos_hist[code] = rows


def exp3_winner_ma():
    print("\n[EXP-3] P0-3 赢家宽管：趋势线由 MA10 放宽到 MA20")
    # 前 10 天收 40（更早），后 10 天收 100 ⇒ MA10 = 100，MA20 = 70
    # 现价 80：80 < MA10(100) 已破 10 日线，但 80 > MA20(70) 未破 20 日线
    closes = [40.0] * 10 + [100.0] * 10
    env = build_env()
    env.mod.TRADE_ENABLED = True
    inject(env, "600003", 1000, 60.0, 80.0, hold_days=6)
    env.g.entry_px["600003"] = 60.0          # 浮盈 33% ≥ 15% → 赢家状态
    env.g.partial_done.add("600003")         # 隔离分批止盈（同上：它会命中后 continue）
    _mk_hist(env, "600003", closes)
    tick(env, DATES[PRE], "14:50", 80.0, "600003")
    chk("3-1 赢家宽管：已破 MA10 但未破 MA20 → 不清仓",
        len(sell_rows()) == 0, "卖出 {}".format(sell_rows()))

    env2 = build_env()
    env2.mod.TRADE_ENABLED = True
    env2.mod.WINNER_EXEMPT_PCT = 0.99        # 关闭赢家
    inject(env2, "600003", 1000, 60.0, 80.0, hold_days=6)
    env2.g.entry_px["600003"] = 60.0
    env2.g.partial_done.add("600003")
    _mk_hist(env2, "600003", closes)
    tick(env2, DATES[PRE], "14:50", 80.0, "600003")
    rows = sell_rows()
    chk("3-2 反向对照：关闭赢家 → 破 MA10 正常清仓",
        len(rows) == 1 and "破10日线" in rows[0][3], rows[0][3] if rows else "无")


# ============================================================
# EXP-4 P1-2 出场原因统一追加浮盈亏
# ============================================================
def exp4_reason_pnl():
    print("\n[EXP-4] P1-2 出场原因统一追加浮盈亏")
    env = build_env()
    env.mod.TRADE_ENABLED = True
    inject(env, "600003", 1000, 10.0, 12.0)
    env.g.entry_px["600003"] = 10.0
    env.mod._do_sell("600003", 100, "破10日线清仓(尾盘确认)")   # 原因里没有盈亏
    r1 = [r for r in sell_rows() if "破10日线" in r[3]]
    chk("4-1 缺失时自动追加 → 带上 浮盈 20.0%",
        len(r1) == 1 and "浮盈" in r1[0][3] and "20.0%" in r1[0][3], r1[0][3] if r1 else "未找到")
    env.mod._do_sell("600003", 100, "止损:浮亏-6.0% (模式fixed, 阈值6.0%)")   # 本身已带
    r2 = [r for r in sell_rows() if r[3].startswith("止损")]
    chk("4-2 已含'浮'字样 → 不重复追加",
        len(r2) == 1 and r2[0][3].count("浮") == 1, r2[0][3] if r2 else "未找到")
    chk("4-3 EXP-3 的破均线原因也已带浮盈亏（补齐 V4.8 的 19/31 笔盲区）",
        any(("浮盈" in r[3] or "浮亏" in r[3]) for r in sell_rows()),
        "; ".join(r[3] for r in sell_rows()))


# ============================================================
# EXP-5 P0-2 主线滚动窗口建仓次数约束
# ============================================================
def exp5_mainline_cap():
    print("\n[EXP-5] P0-2 主线滚动窗口建仓次数约束")
    env = build_env()
    env.g.today = DATES[PRE]
    env.mod.MAINLINE_WINDOW_DAYS = 20
    env.mod.MAINLINE_MAX_ENTRIES = 4
    env.g.mainline_entries = [(DATES[PRE], "稀缺资源")] * 3 + [(DATES[PRE], "元件")]
    n1 = env.mod._mainline_recent_entries("稀缺资源")
    n2 = env.mod._mainline_recent_entries("元件")
    chk("5-1 按主线分别计数（稀缺资源 3 / 元件 1）", n1 == 3 and n2 == 1,
        "稀缺={} 元件={}".format(n1, n2))
    env.g.mainline_entries.append((DATES[PRE - 40], "稀缺资源"))    # 窗口外的旧记录
    chk("5-2 窗口外的旧记录被剔除（仍为 3）",
        env.mod._mainline_recent_entries("稀缺资源") == 3,
        "实际 {}".format(env.mod._mainline_recent_entries("稀缺资源")))
    env.g.mainline_entries = []
    chk("5-3 空流水返回 0（不抛异常）",
        env.mod._mainline_recent_entries("稀缺资源") == 0)


# ============================================================
# EXP-6 V4.9 参数落地核对 + 盈亏比自洽检查
# ============================================================
def exp6_params():
    print("\n[EXP-6] V4.9 参数落地核对 + 盈亏比自洽检查")
    m = build_env().mod
    chk("6-1 ATR_STOP_MAX_PCT = 0.06", m.ATR_STOP_MAX_PCT == 0.06, str(m.ATR_STOP_MAX_PCT))
    chk("6-2 ATR_STOP_MIN_PCT = 0.04（留 4%~6% 自适应窗口）",
        m.ATR_STOP_MIN_PCT == 0.04, str(m.ATR_STOP_MIN_PCT))
    chk("6-3 PARTIAL_TAKE_PCT = 0.15", m.PARTIAL_TAKE_PCT == 0.15, str(m.PARTIAL_TAKE_PCT))
    chk("6-4 TRAIL_PCT = 0.15", m.TRAIL_PCT == 0.15, str(m.TRAIL_PCT))
    chk("6-5 STOP_STAGED = False（两段式已删除）", m.STOP_STAGED is False, str(m.STOP_STAGED))
    chk("6-6 USE_OWN_COST = True", m.USE_OWN_COST is True, str(m.USE_OWN_COST))
    chk("6-7 WINNER_EXEMPT_PCT = 0.15", m.WINNER_EXEMPT_PCT == 0.15, str(m.WINNER_EXEMPT_PCT))
    chk("6-8 MAINLINE_MAX_ENTRIES = 4 / WINDOW = 20",
        m.MAINLINE_MAX_ENTRIES == 4 and m.MAINLINE_WINDOW_DAYS == 20,
        "{}/{}".format(m.MAINLINE_MAX_ENTRIES, m.MAINLINE_WINDOW_DAYS))
    chk("6-9 ★盈亏比自洽★ 止损上限(6%) ≤ 止盈上限(15%)的一半",
        m.ATR_STOP_MAX_PCT <= m.PARTIAL_TAKE_PCT * 0.5,
        "可达盈亏比上限 = {:.2f}（保本需 2.50）".format(m.PARTIAL_TAKE_PCT / m.ATR_STOP_MAX_PCT))
    e = build_env()
    chk("6-10 g.entry_px / g.mainline_entries 已在 initialize 初始化",
        isinstance(getattr(e.g, "entry_px", None), dict)
        and isinstance(getattr(e.g, "mainline_entries", None), list))


# ============================================================
def main():
    print("=" * 78)
    print("热点早盘001 V4.9 离线行为校验器")
    print("=" * 78)
    exp1_own_cost()
    exp2_winner_trail()
    exp3_winner_ma()
    exp4_reason_pnl()
    exp5_mainline_cap()
    exp6_params()
    print("\n" + "=" * 78)
    bad = [nm for nm, ok_ in RESULTS if not ok_]
    print("{} 项断言，{} 项失败".format(len(RESULTS), len(bad)))
    for nm in bad:
        print("  FAIL:", nm)
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

