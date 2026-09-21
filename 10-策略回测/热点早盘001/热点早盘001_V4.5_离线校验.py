# -*- coding: utf-8 -*-
"""
热点早盘001 V4.5 离线行为校验器（不上网、不依赖 PTrade）
==========================================================
用合成行情 + 假 PTrade API 把 V4.5 的关键改动"跑一遍"：验证行为，不验证收益。
覆盖点（对应诊断报告 A/B 组）：
  1. 每日建仓上限 2 笔生效
  2. 建仓价"显式假设"路径（不再静默退化为昨收）
  3. handle_data 捕获日内价作为护栏来源
  4. 分批止盈只减一次（B-8）
  5. D3 判衰退但持仓仅 2 日 → 最短持有保护，不强平（B-3）
  6. D4 判衰退 + 持仓满 3 日 + 跌破破位线 → 14:48 清仓；同板块未破位持仓不动（B-3/B-4）
  7. 卖出同步记账（B-5）
  8. 候选漏斗日志存在
"""
import sys, os, json, types
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(_HERE, "热点早盘001_V4.5.py")
WORK = r"D:\投研工作台\archive\temp_v45_verify"

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
# 涨跌幅(%)：index 99 = D1 的 T-1（即信号日），index 100.. = 各模拟日当天
# 候选票刻意做成"信号日前一段陡坡上行"：这样 MA10 明显低于现价，
# 才能把"跌破破位线→板块级清仓"分支与"破10日线"分支隔离开验证（否则前者永远被后者抢先）。
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
# 模拟日 1~4 的日内价（相对持仓成本倍数；1 表示用 D1 的 c_prev 规则）
INTRADAY = {
    "600003": {1: None, 2: 1.13, 3: 1.05, 4: 0.93},   # D2 触发分批止盈；D3 无事；D4 破位 → 清仓
    "600004": {1: None, 2: 0.99, 3: 0.99, 4: 0.985},  # 全程未破位 → 不清仓
}

LOGS, TIMES = [], []
NOW = [""]


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
        p.enable_amount = 0                      # T+1
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
    mod.MARKET_ZT_FLOOR = 0                # 合成池只有 2 家涨停，放宽广度地板
    mod.REGIME_USE_INDEX_MA20 = False
    return env


def set_time(env, day, hhmm):
    h, m = [int(x) for x in hhmm.split(":")]
    dt = datetime.strptime(day, "%Y-%m-%d").replace(hour=h, minute=m)
    env.ctx.blotter.current_dt = dt
    env.ctx.now = dt
    NOW[0] = hhmm


def refresh_prices(env, di):
    """按当日剧本刷新"当日日内价"。"""
    env.prices = {}
    k = di - PRE + 1                     # 模拟日序号 1..4
    for c in CODES:
        if k == 1:
            if c == "600003":            # 由 handle_data 的 data 提供（真实日内价路径）
                env.prices[c] = CLOSE[c][di - 1] * 1.005
        else:
            p = env.positions.get(c + ".SS")
            mult = INTRADAY.get(c, {}).get(k)
            if p and mult:
                env.prices[c] = p.cost_price * mult
    for p in env.positions.values():
        code = "".join(ch for ch in p.security if ch.isdigit())[:6]
        p.last_price = env.prices.get(code, p.last_price)


def run_day(env, di):
    day = DATES[di]
    env.day_idx = di
    mod, ctx = env.mod, env.ctx
    set_time(env, day, "08:30")
    mod.before_trading_start(ctx, {})
    for p in env.positions.values():
        p.enable_amount = p.current_amount          # T+1：今日可卖
    refresh_prices(env, di)
    for hhmm in ["09:30", "09:31"]:
        set_time(env, day, hhmm)
        if hhmm == "09:31":
            mod.early_job(ctx)
        mod.handle_data(ctx, dict([(c, {"close": px}) for c, px in env.prices.items()]))
    set_time(env, day, "09:32")
    mod.buy_job(ctx)
    mod.handle_data(ctx, {})
    for h in range(9, 16):
        for m in range(60):
            t = "%02d:%02d" % (h, m)
            if "09:33" <= t <= "15:00":
                set_time(env, day, t)
                if t == "14:48":
                    mod.risk_fallback_job(ctx)
                mod.handle_data(ctx, {})
    return day


def main():
    if not os.path.isdir(WORK):
        os.makedirs(WORK)
    for f in os.listdir(WORK):
        fp = os.path.join(WORK, f)
        if os.path.isfile(fp) and f.endswith((".json", ".log")):
            os.remove(fp)
    os.chdir(WORK)
    with open(os.path.join(WORK, "sector_map.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "offline-verify", "generated_at": "2026-09-20", "industry": {},
                   "concept": {"测试题材": [c + ".SS" for c in CODES]}}, f, ensure_ascii=False)

    del LOGS[:], TIMES[:]
    env = build_env()
    env.mod.initialize(env.ctx)
    for di in range(PRE, NDAY):
        run_day(env, di)
        print(">>>>> %s 结束 | 持仓 %s" % (DATES[di], sorted(env.positions.keys())))

    print("=" * 78)
    print("关键日志（带模拟时刻）")
    print("=" * 78)
    KEY = ("[买入] ", "[候选漏斗]", "[口径-假设]", "[口径-来源]", "[卖出] ", "[风控] ",
           "[初始化] ", "!!", "[候选] 主线", "[主线确定]")
    for i, m in enumerate(LOGS):
        if any(k in m for k in KEY):
            print("  %s  %s" % (TIMES[i] or "--:--", m))
    print("=" * 78)

    def find(kw, pre=None):
        return [(i, m) for i, m in enumerate(LOGS)
                if (pre is None or m.startswith(pre)) and kw in m]

    bu = find("委托=OID", "[买入] ")
    assumed = [m for i, m in bu if "假设价" in m]
    src_log = [m for i, m in find("", "[口径-来源]")]
    funnel = find("", "[候选漏斗]")
    sells = find("", "[卖出] ")
    clear = [(i, m) for i, m in sells if "板块联动清仓" in m]
    part = [(i, m) for i, m in sells if "分批止盈" in m]

    print("V4.5 行为校验")
    print("-" * 78)
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  | " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    chk("1 每日建仓上限=2 生效（4 只有效候选只买 2 只）", len(bu) == 2, "实际买入 %d 笔" % len(bu))
    chk("2 建仓价来源显式化：assumed 与 [口径-假设] 告警",
        len(assumed) == 1 and len(find("", "[口径-假设]")) == 1,
        "assumed=%d" % len(assumed))
    chk("3 handle_data 日内价路径生效（src=bar:handle_data）",
        any("bar:handle_data" in m for m in src_log),
        src_log[0] if src_log else "无")
    chk("4 分批止盈只减一次", len(part) == 1, "成交 %d 笔" % len(part))
    chk("5 卖出同步记账（g.trades 含 sell）",
        any(s == "sell" for (d, v, s) in env.g.trades), "g.trades=%d 条" % len(env.g.trades))
    chk("6 候选漏斗日志存在", len(funnel) > 0, "%d 行" % len(funnel))
    chk("7 板块级清仓成交时刻=14:48",
        len(clear) >= 1 and all(TIMES[i] == "14:48" for i, m in clear),
        "清仓 %d 笔，时刻=%s" % (len(clear), [TIMES[i] for i, m in clear]))
    chk("8 最短持有保护：D3 判衰退但持仓 2 日 → 不强平",
        len(find("但持仓仅2日(<3日) → 不在此强平", "[风控] ")) > 0)
    chk("9 破位过滤：浮亏但未跌破破位线 → 暂不强平",
        len(find("但未跌破破位线", "[风控] ")) > 0)
    kept = sorted(env.positions.keys())
    chk("10 清仓后仅剩未破位那只（600004）", kept == ["600004.SS"], "剩余=%s" % kept)
    chk("11 全天任何卖出都不发生在 09:31（旧版首因）",
        all(TIMES[i] != "09:31" for i, m in sells),
        "卖出时刻=%s" % sorted(set(TIMES[i] for i, m in sells)))
    chk("12 换手统计窗口按交易日口径（20 个交易日）",
        env.mod.TURNOVER_WINDOW_DAYS == 20 and env.mod.MAX_ANNUAL_TURNS == 30,
        "window=%s turns=%s" % (env.mod.TURNOVER_WINDOW_DAYS, env.mod.MAX_ANNUAL_TURNS))

    print("-" * 78)
    print("结果: %s（12 项断言，%d 项失败）" % ("全部通过" if not fails else "存在失败", len(fails)))
    for f in fails:
        print("   FAIL -> " + f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
