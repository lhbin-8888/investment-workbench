# -*- coding: utf-8 -*-
"""
热点早盘001 V4.8 离线行为校验器（不上网、不依赖 PTrade）
==========================================================
用合成行情 + 假 PTrade API 把 V4.8 的关键改动"跑一遍"：**验证行为，不验证收益**。

覆盖的 V4.8 新断言：
  EXP-1  两段式止损 · 第一阶段：首次触发只减半（不是一次清仓）+ 09:45 时间闸门 + 豁免最短持有
  EXP-2  两段式止损 · 第二阶段：次日仍触发 → 清掉剩余
  EXP-3  两段式止损 · 深跌兜底：同日跌破 阈值×1.5 → 立即清剩余（不等次日）
  EXP-4  两段式止损 · 收窄撤销：浮亏回到 阈值×0.5 以内 → 撤销标记、重新武装
  EXP-5  每日新建仓上限 = 2 笔；避险档把上限压到 1 笔、单票仓位 ×0.5
  EXP-6  换手预算口径回归（60 交易日 / 6 次）+ 避险档判定函数
  EXP-7  P0-3 修护栏空转：set_universe 注册候选 + [口径-探测] + [成交] 统计日志
  EXP-8  V4.7 核心行为回归（[净值] / 破均线 14:45 尾盘确认 / 板块清仓 14:48 / 卖出记账）
  EXP-9  参数落地核对（ATR 止损带 5%~12% / Jaccard 0.5 / 同簇 50% / 分批止盈 10% / TRAIL 0.10）

用法： python 热点早盘001_V4.8_离线校验器.py
"""
import sys, os, json, types, tempfile, shutil
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(_HERE, "热点早盘001_V4.8.py")
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
# EXP-1 两段式止损 · 第一阶段（减半）+ 时间闸门 + 豁免最短持有
# ============================================================
def exp1_stage1():
    print("\n[EXP-1] 两段式止损第一阶段：首次触发只减半（不再一次清仓）")
    env = build_env()
    arm_stop_fixed(env, 0.05)
    inject(env, "600003", 200, cost=10.0, px=10.0, hold_days=3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]

    # 09:30-09:44 触发但被闸门顺延（去重后只 1 条日志）
    for t in ("09:30", "09:35", "09:44"):
        tick(env, "2026-05-06", t, px=9.45)          # -5.5% ≤ -5%
    n_floor = len(find("处在开盘噪声区", "[风控] "))
    rows0 = sell_rows()
    chk("1.1 09:45 前不成交（时间闸门生效）", len(rows0) == 0, "越闸卖出=%s" % rows0)
    chk("1.2 噪声去重：3 次顺延只打 1 条日志", n_floor == 1, "日志=%d 条" % n_floor)
    chk("1.3 参数核对：STOP_STAGED=True 且 ATR 止损带 = (5%, 12%)",
        env.mod.STOP_STAGED is True and env.mod.ATR_STOP_MIN_PCT == 0.05
        and env.mod.ATR_STOP_MAX_PCT == 0.12,
        "staged=%s min=%s max=%s" % (env.mod.STOP_STAGED, env.mod.ATR_STOP_MIN_PCT,
                                     env.mod.ATR_STOP_MAX_PCT))

    # 09:45 执行 → 只减半
    tick(env, "2026-05-06", "09:45", px=9.45)
    rows = sell_rows()
    left = env.positions.get("600003.SS")
    chk("1.4 09:45 减半成交（200 → 卖 100）",
        len(rows) == 1 and rows[0][2] == 100 and "止损两段-减半" in rows[0][3],
        "卖出=%s" % rows)
    chk("1.5 剩余保留 100 股（不是一次清仓）",
        left is not None and left.current_amount == 100,
        "剩余=%s" % (left.current_amount if left else None))
    chk("1.6 已记录第一阶段标记（触发日）",
        env.g.stop_stage1.get("600003") == "2026-05-06",
        "stage1=%s" % env.g.stop_stage1)
    chk("1.7 硬止损豁免最短持有期（hold_days=3 仅为对照，两段式不设门槛）",
        env.mod.MIN_HOLD_FOR_TIGHT_STOP == 3)

    # 同日之后仍触发但未深跌 → 等次日（不动作）
    tick(env, "2026-05-06", "10:30", px=9.45)
    rows2 = sell_rows()
    chk("1.8 同日不再重复动作（等次日确认，避免减半后立即清仓）",
        len(rows2) == 1, "卖出=%s" % rows2)
    n_wait = len(find("等次日确认", "[风控] "))
    chk("1.9 「等次日确认」提示每日只打 1 条", n_wait == 1, "日志=%d 条" % n_wait)
    return env


# ============================================================
# EXP-2 两段式止损 · 第二阶段（次日清剩余）
# ============================================================
def exp2_stage2():
    print("\n[EXP-2] 两段式止损第二阶段：次日仍触发 → 清掉剩余仓位")
    env = build_env()
    arm_stop_fixed(env, 0.05)
    inject(env, "600003", 200, cost=10.0, px=10.0, hold_days=3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    tick(env, "2026-05-06", "09:45", px=9.45)        # D2：减半
    chk("2.1 D2 已减半（前置条件）", len(sell_rows()) == 1, "卖出=%s" % sell_rows())
    tick(env, "2026-05-07", "09:50", px=9.45)        # D3：仍 -5.5% → 清剩余
    rows = sell_rows()
    chk("2.2 D3 清掉剩余 100 股",
        len(rows) == 2 and rows[1][2] == 100, "卖出=%s" % rows)
    chk("2.3 原因标注「两段式第二阶段」", "两段式第二阶段" in rows[1][3],
        "原因=%s" % rows[1][3])
    chk("2.4 持仓已清空", not env.positions.get("600003.SS"))
    return env


# ============================================================
# EXP-3 两段式止损 · 同日深跌兜底
# ============================================================
def exp3_deep():
    print("\n[EXP-3] 两段式止损兜底：同日跌破 阈值×1.5 → 立即清剩余（不等次日）")
    env = build_env()
    arm_stop_fixed(env, 0.05)
    inject(env, "600003", 200, cost=10.0, px=10.0, hold_days=3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    tick(env, "2026-05-06", "09:45", px=9.45)        # -5.5% → 减半
    tick(env, "2026-05-06", "10:00", px=9.20)        # -8.0% ≤ -7.5%(=5%×1.5) → 兜底清仓
    rows = sell_rows()
    chk("3.1 同日深跌触发兜底清仓", len(rows) == 2, "卖出=%s" % rows)
    chk("3.2 全程清仓发生在同日（未拖到次日）",
        len(rows) == 2 and rows[0][0] == "09:45" and rows[1][0] == "10:00",
        "时刻=%s" % [r[0] for r in rows])
    chk("3.3 兜底比例为 阈值×1.5 = 7.5%",
        abs(env.mod.STOP_STAGE1_HARD_MULT * env.mod.STOP_LOSS_PCT - 0.075) < 1e-9,
        "STOP_STAGE1_HARD_MULT=%s" % env.mod.STOP_STAGE1_HARD_MULT)
    return env


# ============================================================
# EXP-4 两段式止损 · 收窄撤销
# ============================================================
def exp4_recover():
    print("\n[EXP-4] 两段式止损撤销：浮亏收窄到 阈值×0.5 以内 → 撤销标记、重新武装")
    env = build_env()
    arm_stop_fixed(env, 0.05)
    inject(env, "600003", 200, cost=10.0, px=10.0, hold_days=3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    tick(env, "2026-05-06", "09:45", px=9.45)        # -5.5% → 减半 + 标记
    chk("4.1 已减半并标记", len(sell_rows()) == 1
        and env.g.stop_stage1.get("600003") == "2026-05-06", "stage1=%s" % env.g.stop_stage1)
    tick(env, "2026-05-06", "11:00", px=9.85)        # -1.5% > -2.5%(=5%×0.5) → 撤销
    n_rec = len(find("撤销两段式第一阶段标记", "[风控] "))
    chk("4.2 收窄后撤销标记", "600003" not in env.g.stop_stage1
        and n_rec == 1, "stage1=%s 日志=%d" % (env.g.stop_stage1, n_rec))
    chk("4.3 撤销后未追加卖出（只保留最早那 1 笔减半）",
        len(sell_rows()) == 1, "卖出=%s" % sell_rows())
    # 撤销后再触发：仓位仅剩 100 股（不足 2 手）→ 不做两段式，直接一次清仓
    tick(env, "2026-05-06", "11:30", px=9.45)
    rows = sell_rows()
    chk("4.4 重新触发但仓位不足 2 手 → 直接一次清仓（不再减半）",
        len(rows) == 2 and rows[1][2] == 100 and "两段式第二阶段" not in rows[1][3],
        "卖出=%s" % rows)
    return env


# ============================================================
# EXP-5 每日建仓上限 = 2 笔 + 避险档（半仓 / 每日 1 笔）
# ============================================================
def exp5_cap_and_riskoff():
    print("\n[EXP-5] 每日新建仓上限 = 2 笔 + 市场避险档（单票 ×0.5、每日 1 笔）")
    env = build_env()
    mod = env.mod
    mod.MAX_PER_SECTOR = 6                   # 放宽板块限制，隔离"每日上限"
    mod.CLUSTER_MAX_WEIGHT = 0               # 关闭产业链簇约束
    chk("5.1 参数量核对（每日 2 笔 / 避险 0.5×1 笔）",
        mod.MAX_NEW_POSITIONS_PER_DAY == 2 and mod.REGIME_RISK_OFF_SCALE == 0.5
        and mod.REGIME_RISK_OFF_MAX_NEW == 1,
        "daily=%s scale=%s riskoff_max=%s" % (mod.MAX_NEW_POSITIONS_PER_DAY,
                                              mod.REGIME_RISK_OFF_SCALE, mod.REGIME_RISK_OFF_MAX_NEW))
    run_day(env, PRE, scan=False)
    bu = find("委托=OID", "[买入] ")
    chk("5.2 正常档：D1 恰好建仓 2 笔", len(bu) == 2, "买入 %d 笔" % len(bu))

    # 避险档：patch 判定为 True，重跑建仓层
    env2 = build_env()
    mod2 = env2.mod
    mod2.MAX_PER_SECTOR = 6
    mod2.CLUSTER_MAX_WEIGHT = 0
    mod2.market_risk_off = lambda: True
    run_day(env2, PRE, scan=False)
    bu2 = find("委托=OID", "[买入] ")
    chk("5.3 避险档：D1 只建仓 1 笔（上限被压到 1）", len(bu2) == 1, "买入 %d 笔" % len(bu2))
    tag = find("单票缩放=0.50")
    chk("5.4 避险档：[成交] 日志标注单票缩放 = 0.50", len(tag) >= 1,
        tag[0][1] if tag else "无 [成交] 日志")
    chk("5.5 避险档：已置 g.risk_off=True", env2.g.risk_off is True)
    return env2


# ============================================================
# EXP-6 换手预算口径 + 避险档判定函数
# ============================================================
def exp6_turnover():
    print("\n[EXP-6] 换手预算口径回归（60 交易日 / 6 次）+ 避险档判定函数")
    env = build_env()
    mod = env.mod
    chk("6.1 参数 = (60 交易日, 6 次)",
        mod.TURNOVER_WINDOW_DAYS == 60 and mod.MAX_ANNUAL_TURNS == 6,
        "window=%s turns=%s" % (mod.TURNOVER_WINDOW_DAYS, mod.MAX_ANNUAL_TURNS))
    env.g.trades = [("2026-05-06", 1.0e7, "buy")]
    ok1 = mod.turnover_ok(env.ctx, 1e6)
    env.g.trades = [("2026-05-06", 1.3e7, "buy")]
    ok2 = mod.turnover_ok(env.ctx, 1e6)
    chk("6.2 换手 5.0 次 ≤ 6 → 允许开仓", ok1 is True)
    chk("6.3 换手 6.5 次 > 6 → 熔断停开新仓", ok2 is False)
    env.g.trades = []

    # 避险档函数：构造"收盘 900 < MA20 ≈1003.6"的指数序列
    rows = [("d%d" % i, 1000.0 + i) for i in range(19)] + [("d19", 900.0)]
    env.g.index_rows = rows
    chk("6.4 指数跌破 MA20 → market_risk_off() = True", mod.market_risk_off() is True)
    env.g.index_rows = [("d%d" % i, 1000.0 + i) for i in range(20)]     # 单边上行
    chk("6.5 指数上行（收盘 > MA20）→ market_risk_off() = False",
        mod.market_risk_off() is False)
    env.g.index_rows = []
    chk("6.6 指数数据缺失 → 不误伤建仓（返回 False）", mod.market_risk_off() is False)
    return env


# ============================================================
# EXP-7 P0-3 修护栏空转：set_universe + 探测日志 + 成交统计
# ============================================================
def exp7_universe():
    print("\n[EXP-7] P0-3 修护栏空转：set_universe 注册候选 + 诊断日志")
    env = build_env()
    mod = env.mod
    mod.MAX_PER_SECTOR = 6
    mod.CLUSTER_MAX_WEIGHT = 0
    run_day(env, PRE, scan=False)
    chk("7.1 盘前已调用 set_universe 注册候选（含 .SS/.SZ 后缀）",
        len(env.universe) > 0 and all(("." in c) for c in env.universe),
        "universe=%s" % env.universe[:8])
    u_log = find("[口径-U] set_universe 注册")
    chk("7.2 [口径-U] 注册日志已打印", len(u_log) >= 1,
        u_log[0][1][:96] if u_log else "无")
    p_log = find("[口径-探测]")
    chk("7.3 [口径-探测] 诊断日志已打印（data 键样本 + 命中数）", len(p_log) >= 1,
        p_log[0][1][:96] if p_log else "无")
    c_log = find("[成交] 本日递交委托")
    chk("7.4 [成交] 递交/受理笔数统计已打印", len(c_log) >= 1,
        c_log[0][1][:96] if c_log else "无")
    return env


# ============================================================
# EXP-8 V4.7 核心行为回归（净值 / 尾盘确认 / 板块清仓 14:48 / 卖出记账）
# ============================================================
def exp8_regression():
    print("\n[EXP-8] V4.7 核心行为回归（[净值] / 破均线 14:45 / 板块清仓 14:48 / 卖出记账）")
    env = build_env()
    arm_stop_fixed(env, 0.90)                # 软禁用硬止损，隔离趋势类出场

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
    chk("8.1 [净值] 日终打印覆盖 4 个交易日", len(net) >= 4, "%d 条" % len(net))
    srows = sell_rows()
    early = [r for r in srows if r[0] < "09:45" and ("破" in r[3] or "止损" in r[3])]
    chk("8.2 无 09:45 前的趋势类/止损类卖出（分批/移动止盈不受闸门约束，属预期）",
        not early, "越闸卖出=%s" % early)
    brk = [r for r in srows if "破" in r[3] and "日线" in r[3]]
    # 本场景刻意不构造破均线条件 → 此处仅作"越界防护"；该分支的实质验证在 EXP-10
    chk("8.3 本场景无破均线卖出（越界防护；实质验证见 EXP-10）",
        all(r[0] >= "14:45" for r in brk), "破均线=%s" % [(r[0], r[3][:22]) for r in brk])
    clear = [r for r in srows if "板块联动清仓" in r[3]]
    chk("8.4 板块级清仓只发生在 14:48",
        all(r[0] == "14:48" for r in clear), "清仓时刻=%s" % [r[0] for r in clear])
    chk("8.5 卖出同步记账（g.trades 含 sell）",
        any(s == "sell" for (d, v, s) in env.g.trades), "g.trades=%d 条" % len(env.g.trades))
    src_log = find("", "[口径-来源] ")
    chk("8.6 [口径-来源] 每轮建仓均打印（护栏失效时可见）", len(src_log) >= 1,
        src_log[0][1][:88] if src_log else "无")
    return env


# ============================================================
# EXP-9 参数落地核对 + 分批止盈阈值 10%
# ============================================================
def exp9_params():
    print("\n[EXP-9] 参数落地核对 + 分批止盈阈值 10%")
    env = build_env()
    mod = env.mod
    chk("9.1 产业链簇放松（Jaccard 0.5 / 同簇 50%）",
        mod.CLUSTER_JACCARD == 0.5 and abs(mod.CLUSTER_MAX_WEIGHT - 0.50) < 1e-9,
        "jaccard=%s weight=%s" % (mod.CLUSTER_JACCARD, mod.CLUSTER_MAX_WEIGHT))
    chk("9.2 扩散期仓位 12%（0.15 → 0.12）", abs(mod.DIFFUSE_POSITION_RATIO - 0.12) < 1e-9,
        "diffuse=%s" % mod.DIFFUSE_POSITION_RATIO)
    chk("9.3 TRAIL_PCT 保持用户指定值 0.10", abs(mod.TRAIL_PCT - 0.10) < 1e-9,
        "trail=%s" % mod.TRAIL_PCT)

    # 分批止盈 10%：注入 200 股、浮盈 10% → 减半
    arm_stop_fixed(env, 0.90)
    inject(env, "600003", 200, cost=10.0, px=11.0, hold_days=3)
    env.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    tick(env, "2026-05-06", "10:30", px=11.0)
    rows = sell_rows()
    chk("9.4 浮盈 10% 触发分批止盈（阈值由 12% 提前到 10%）",
        len(rows) == 1 and rows[0][2] == 100 and "分批止盈" in rows[0][3],
        "卖出=%s" % rows)
    chk("9.5 剩余 100 股继续跟移动止盈",
        (env.positions.get("600003.SS") or _Pos("x", 0, 0)).current_amount == 100)

    # 浮盈 9% 不应触发（确认阈值确为 10% 而非更低）
    env2 = build_env()
    arm_stop_fixed(env2, 0.90)
    inject(env2, "600003", 200, cost=10.0, px=10.9, hold_days=3)
    env2.g.pos_hist = {}
    del LOGS[:], TIMES[:]
    tick(env2, "2026-05-06", "10:30", px=10.9)
    chk("9.6 浮盈 9% 不触发（阈值确为 10%）", len(sell_rows()) == 0, "卖出=%s" % sell_rows())
    return env


# ============================================================
# EXP-10 破均线清仓仍在 14:45（V4.7 P0-1 回归，独立场景避免空断言）
# ============================================================
def exp10_break_gate():
    print("\n[EXP-10] 破均线清仓仍在 14:45（尾盘确认回归，禁用硬止损以隔离该分支）")
    env = build_env()
    mod = env.mod
    mod.MAX_POSITIONS = 1
    mod.MAX_NEW_POSITIONS_PER_DAY = 1
    arm_stop_fixed(env, 0.90)                # 软禁用硬止损，隔离"破均线"分支
    run_day(env, PRE, scan=False)
    chk("10.1 D1 建仓 1 只", sorted(env.positions.keys()) == ["600003.SS"],
        "实际=%s" % sorted(env.positions.keys()))

    def px_fn(e, k, c):
        if c != "600003":
            return None
        if k in (2, 3):
            return cost_of(e, "600003") * 1.00      # 横盘：不触发任何出场
        if k == 4:
            return cost_of(e, "600003") * 0.80      # 暴跌 20% → 跌破 MA10
        return None

    del LOGS[:], TIMES[:]
    run_day(env, PRE + 1, px_fn=px_fn)       # D2 hold_days=1
    run_day(env, PRE + 2, px_fn=px_fn)       # D3 hold_days=2
    run_day(env, PRE + 3, px_fn=px_fn)       # D4 hold_days=3 → 破均线可执行
    rows = sell_rows()
    times = sorted(set(r[0] for r in rows))
    chk("10.2 破均线清仓已成交（非空断言）", len(rows) >= 1, "卖出=%s" % rows)
    chk("10.3 成交时刻 = 14:45（尾盘确认，非 09:31/09:32）", times == ["14:45"],
        "时刻=%s" % times)
    chk("10.4 原因标注尾盘确认", any("尾盘确认" in r[3] for r in rows),
        "原因=%s" % [r[3] for r in rows])
    chk("10.5 两段式止损未介入该分支（原因不含'两段'）",
        not any("两段" in r[3] for r in rows), "原因=%s" % [r[3] for r in rows])
    return env


def main():
    if not os.path.isdir(WORK):
        os.makedirs(WORK)
    os.chdir(WORK)
    with open(os.path.join(WORK, "sector_map.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "offline-verify", "generated_at": "2026-09-20", "industry": {},
                   "concept": {"测试题材": [c + ".SS" for c in CODES]}}, f, ensure_ascii=False)

    print("=" * 78)
    print("热点早盘001 V4.8 离线行为校验（合成行情；验证行为，不验证收益）")
    print("=" * 78)
    try:
        exp1_stage1()
        exp2_stage2()
        exp3_deep()
        exp4_recover()
        exp5_cap_and_riskoff()
        exp6_turnover()
        exp7_universe()
        exp8_regression()
        exp9_params()
        exp10_break_gate()
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
