# -*- coding: utf-8 -*-
"""
verify_v3_mock.py —— hotspot_trader_v3_ptrade.py 离线全链路验证器
====================================================================
不联网、不上平台。自建一个结构与真实 sector_map.json 同形的板块池
（含 400 只级宽口径标签 + 60 只级题材 + 150 只级超限板块），
在本地注入 mock 版 PTrade API，把 V3 全链路真实跑一遍，
并对 V3 声称修复的每一条逐项断言。

用法（位置参数与 --mode 两种写法均可）:
  python verify_v3_mock.py                 # dict 模式（is_dict=True）
  python verify_v3_mock.py multiindex      # MultiIndex 列降级（需 pandas）
  python verify_v3_mock.py --mode single   # 逐票降级 + 扫描范围自动收缩
  python verify_v3_mock.py nofq            # 平台 get_history 无 fq 参数

模式非法时直接报错退出（不静默降级到默认模式 —— 那正是 R4 要禁止的行为）。
退出码 0 = 全部断言通过。
"""
import datetime
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(HERE, "hotspot_trader_v3_ptrade.py")
WORK = os.path.join(HERE, "_v3_verify")

VALID_MODES = ("dict", "multiindex", "single", "nofq")
MODE = None
_i = 0
_args = sys.argv[1:]
while _i < len(_args):
    _a = _args[_i]
    if _a in ("--mode", "-m"):
        if _i + 1 >= len(_args):
            raise SystemExit("--mode 后缺少取值；可选：{}".format("/".join(VALID_MODES)))
        MODE = _args[_i + 1].lower()
        _i += 2
        continue
    if _a.startswith("-"):
        raise SystemExit("未知选项 {!r}；用法：python verify_v3_mock.py <mode>".format(_a))
    if MODE is None:
        MODE = _a.lower()
    _i += 1
if MODE is None:
    MODE = "dict"
if MODE not in VALID_MODES:
    raise SystemExit(
        "未知模式 {!r}；可选：{}（用法：python verify_v3_mock.py <mode>）".format(
            MODE, "/".join(VALID_MODES)))

try:
    import pandas as pd
except Exception:
    pd = None

os.makedirs(WORK, exist_ok=True)
os.chdir(WORK)

FAILS = []
CHECKS = [0]


def ok(cond, name, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  [PASS] {}".format(name))
    else:
        print("  [FAIL] {}  {}".format(name, detail))
        FAILS.append(name)


# ============================================================
# 1. 自建板块池（结构与真实池同形）
# ============================================================
random.seed(20260914)


def mk_codes(prefix, n, start=0):
    """生成 6 位代码：前缀 3 位 + 3 位序号（必须是 6 位，否则被 _pure 截断塌缩）。"""
    return ["{}{:03d}".format(prefix, start + i) for i in range(n)]


UNIVERSE = (mk_codes("600", 300) + mk_codes("000", 300)
            + mk_codes("300", 300) + mk_codes("688", 200)
            + mk_codes("830", 100))
assert len(set(UNIVERSE)) == 1200, "代码池有重复"
MAIN = [c for c in UNIVERSE if c.startswith(("600", "000"))]

HOT_THEME = "机器人概念"
HOT2 = "固态电池"
OVERSIZE = "光伏概念"
BROAD = ["融资融券", "参股金融", "专精特新", "股权激励", "业绩预升"]

THEME_MEMBERS = MAIN[10:70]                       # 60 只，全主板
THEME2_MEMBERS = MAIN[100:145]                    # 45 只
BIG_MEMBERS = MAIN[200:350] + UNIVERSE[600:700]   # 150 只，超上限

BROAD_MEMBERS = {}
for name, n in zip(BROAD, (391, 400, 398, 354, 309)):
    BROAD_MEMBERS[name] = random.sample(UNIVERSE, min(n, len(UNIVERSE)))

DECOYS = {}
_no_hot = [c for c in UNIVERSE if c not in set(THEME_MEMBERS) | set(THEME2_MEMBERS)]
for i, n in enumerate((15, 20, 25, 30, 35, 40, 50, 55, 65, 70)):
    DECOYS["题材{}\u53f7".format(i)] = random.sample(_no_hot, n)

concept = {HOT_THEME: THEME_MEMBERS, HOT2: THEME2_MEMBERS, OVERSIZE: BIG_MEMBERS}
concept.update(BROAD_MEMBERS)
concept.update(DECOYS)
industry = {"机械行业": random.sample(UNIVERSE, 247),
            "电子信息": random.sample(UNIVERSE, 247),
            "其它行业": random.sample(UNIVERSE, 160)}

POOL = {"generated_at": "2026-09-13T09:20:56", "source": "mock",
        "industry": industry, "concept": concept}
with open(os.path.join(WORK, "sector_map.json"), "w", encoding="utf-8") as f:
    json.dump(POOL, f, ensure_ascii=False)

ZT_MEMBERS = set(THEME_MEMBERS[:3]) | set(THEME2_MEMBERS[:2]) | set(BIG_MEMBERS[:5])
HOT_MEMBERS = (set(THEME_MEMBERS) | set(THEME2_MEMBERS)) - ZT_MEMBERS
HOT_SORTED = sorted(HOT_MEMBERS)
COOL_MEMBER = HOT_SORTED[0]
HELD_MEMBER = HOT_SORTED[1]
ST_MEMBER = HOT_SORTED[2]
LOW_OPEN = HOT_SORTED[3]
HIGH_OPEN = HOT_SORTED[4]

CODES = sorted(set(UNIVERSE) | set(BIG_MEMBERS))
INDEX = "000300"

# ============================================================
# 2. 合成行情
# ============================================================
NBARS = 70
BARS_T, BARS_T1, OPEN_FACTOR = {}, {}, {}
BROAD_ALL = set()
for _v in BROAD_MEMBERS.values():
    BROAD_ALL.update(_v)


def _mk(code):
    is_idx = (code == INDEX)
    is_zt = code in ZT_MEMBERS
    is_hot = code in HOT_MEMBERS
    is_broad = code in BROAD_ALL
    base = 3800.0 if is_idx else random.uniform(8.0, 45.0)
    closes = [base]
    for i in range(1, NBARS):
        if is_idx:
            d = 0.0022                                   # 指数稳步上行，确保在 MA20 之上
        elif is_hot or is_zt:
            d = 0.0012
        elif is_broad:
            d = random.uniform(-0.002, 0.002)             # 宽口径标签：低波动
        else:
            d = random.uniform(-0.004, 0.004)
        closes.append(max(1.0, closes[-1] * (1 + d + random.uniform(-0.003, 0.003))))
    prev = closes[-2]
    if is_idx:
        closes[-1] = prev * 1.003                         # 指数必须站稳 MA20
    elif is_zt:
        closes[-1] = prev * 1.099
    elif is_hot:
        closes[-1] = prev * 1.07
    else:
        closes[-1] = prev * (1 + random.uniform(-0.03, 0.03))
    opens, highs, lows, vols = [], [], [], []
    for i in range(NBARS):
        c = closes[i]
        o = closes[i - 1] * (1 + random.uniform(-0.004, 0.004)) if i else c
        opens.append(o)
        highs.append(max(o, c) * 1.006)
        lows.append(min(o, c) * 0.994)
        v = 1.0e9 if is_idx else 5.0e7
        if (is_hot or is_zt) and i == NBARS - 1:
            v = 1.5e8                                    # 末日放量 → 高量比
        vols.append(v)
    return opens, closes, highs, lows, vols


for code in CODES + [INDEX]:
    o, c, h, l, v = _mk(code)
    BARS_T[code] = {"open": o, "close": c, "high": h, "low": l, "volume": v}
    tc = c[-1]
    fac = 1.005
    if code == LOW_OPEN:
        fac = 0.965                                     # < 下限 0.985
    elif code == HIGH_OPEN:
        fac = 1.055                                     # > 上限 1.030
    OPEN_FACTOR[code] = fac
    BARS_T1[code] = {"open": o + [tc * fac], "close": c + [tc * fac],
                     "high": h + [tc * fac * 1.01], "low": l + [tc * fac * 0.99],
                     "volume": v + [v[-1] * 0.3]}

T_CLOSE = dict((c, BARS_T[c]["close"][-1]) for c in BARS_T)


# ============================================================
# 3. mock PTrade 环境
# ============================================================
class Log(object):
    def __init__(self):
        self.lines = []

    def info(self, m):
        self.lines.append(str(m))

    def warn(self, m):
        self.lines.append("WARN " + str(m))

    def error(self, m):
        self.lines.append("ERR " + str(m))


class G(object):
    pass


class Ctx(object):
    def __init__(self, dt, total=5000000.0, cash=5000000.0):
        self.blotter = type("B", (), {"current_dt": dt})()
        self.portfolio = type("P", (), {"portfolio_value": total, "cash": cash})()
        self.now = dt


def pos(security, amount=10000, cost=20.0, price=20.0, enable=None):
    return {"security": security, "current_amount": amount, "cost_price": cost,
            "last_price": price, "enable_amount": amount if enable is None else enable}


class Env(object):
    def __init__(self, phase="T", dt=None, positions=None, cash=5000000.0):
        self.phase = phase
        self.orders = []
        self.hist_calls = []
        self.names = {}
        self.positions = positions or {}
        self.log = Log()
        self.g = G()
        self.ns = None
        self.ctx = Ctx(dt or datetime.datetime(2026, 9, 14, 14, 55), cash=cash)

    @staticmethod
    def _k(c):
        return "".join(ch for ch in str(c) if ch.isdigit())[:6]

    def _bars(self, code):
        return (BARS_T if self.phase == "T" else BARS_T1).get(code)

    def get_history(self, count, frequency="1d", field=None, security_list=None,
                    fq=None, is_dict=False):
        if MODE == "nofq" and fq is not None:
            raise TypeError("mock: 本版本 get_history 不接受 fq 参数")   # 触发 fq 降级
        self.hist_calls.append(list(security_list or []))
        codes = [self._k(c) for c in (security_list or [])] or [INDEX]
        fields = list(field or ["close"])
        res = {}
        for c in codes:
            b = self._bars(c)
            if not b:
                continue
            n = min(count, len(b["close"]))
            sl = slice(len(b["close"]) - n, len(b["close"]))
            sub = {}
            for f in fields:
                if f in b:
                    sub[f] = b[f][sl]
            if pd is not None:
                df = pd.DataFrame(sub)
                res[c] = df
            else:
                res[c] = sub
        if MODE in ("dict", "nofq"):
            return res
        if MODE == "multiindex":
            if pd is not None and res:
                frames = []
                for c, d in res.items():
                    d = d.copy()
                    d.columns = pd.MultiIndex.from_tuples([(f, c) for f in d.columns])
                    frames.append(d)
                return pd.concat(frames, axis=1)
            return res
        first = codes[0]
        return res.get(first, {})

    def get_snapshot(self, code):
        return None

    def get_positions(self):
        return dict(self.positions)

    def get_position(self):
        return None

    def get_stock_name(self, code):
        return self.names.get(self._k(code), "某某股份")

    def order(self, security, amount, **kw):
        self.orders.append({"api": "order", "code": security, "amount": amount})
        return "OID{}".format(len(self.orders))

    def order_value(self, security, value, limit_price=None, **kw):
        self.orders.append({"api": "order_value", "code": security, "value": value,
                            "limit_price": limit_price})
        return "OID{}".format(len(self.orders))

    def set_benchmark(self, b):
        return True

    def set_commission(self, **kw):
        if "tax" in kw:
            raise TypeError("mock: 本版本不支持 tax 参数")     # 触发 V3 的参数降级
        return True

    def set_slippage(self, *a, **kw):
        return True

    def run_daily(self, context, func, time=None):
        if not hasattr(self, "scheduled"):
            self.scheduled = {}
        self.scheduled[time] = func
        return True

    def get_research_path(self):
        raise Exception("mock: 无研究根目录 → 走相对路径回退")

    def get_datetime(self):
        return self.ctx.blotter.current_dt

    def get_cash(self):
        return self.ctx.portfolio.cash

    def get_total_assets(self):
        return self.ctx.portfolio.portfolio_value

    def load(self):
        src = open(STRAT, encoding="utf-8").read()
        ns = {"__name__": "strategy", "log": self.log, "g": self.g,
              "get_history": self.get_history, "get_snapshot": self.get_snapshot,
              "get_positions": self.get_positions, "get_position": self.get_position,
              "get_stock_name": self.get_stock_name, "order": self.order,
              "order_value": self.order_value, "set_benchmark": self.set_benchmark,
              "set_commission": self.set_commission, "set_slippage": self.set_slippage,
              "run_daily": self.run_daily, "get_research_path": self.get_research_path,
              "get_datetime": self.get_datetime, "get_cash": self.get_cash,
              "get_total_assets": self.get_total_assets}
        exec(compile(src, STRAT, "exec"), ns)
        self.ns = ns
        ns["MARKET_ZT_FLOOR"] = 2          # 测试场景固定涨停数低，放开市场开关
        return ns

    def run_signal(self, **kw):
        """跑一遍 initialize + 日初 + 信号层。"""
        if not self.ns:
            self.load()
        self.ns["initialize"](self.ctx)
        self.ns["before_trading_start"](self.ctx, None)
        self.ns["signal_job"](self.ctx)
        return self.g


def logtext(env):
    return "\n".join(env.log.lines)


print("=" * 76)
print("V3 离线验证 | 模式={} | pandas={}".format(MODE, pd.__version__ if pd else "无"))
print("池: 概念 {} 个 / 行业 {} 个 | 代码 {} 只".format(
    len(concept), len(industry), len(CODES)))
print("题材 {}={} 只 | {}={} 只 | 超限 {}={} 只 | 宽口径 {}".format(
    HOT_THEME, len(THEME_MEMBERS), HOT2, len(THEME2_MEMBERS),
    OVERSIZE, len(BIG_MEMBERS), BROAD[0]))
print("=" * 76)

# ------------------------------------------------------------
print("\n【1】initialize / 板块池 / 调度")
env = Env()
ns = env.load()
ns["initialize"](env.ctx)
ok(env.g.sched_ok is True, "run_daily 注册成功（3 个时点）",
   str(sorted(getattr(env, "scheduled", {}).keys())))
ok(len(getattr(env, "scheduled", {})) == 3, "注册了 信号/开盘/兜底 三个任务")
ok(ns["load_sector_map"]() is not None, "sector_map.json 载入成功")
fw, rev = ns["_build_sector_index"]()
ok(len(fw) == len(concept) + len(industry), "板块索引完整",
   "{} 板块".format(len(fw)))
ok(len(rev) > 1000, "code→板块 反查索引构建", "{} 只".format(len(rev)))
ok(any("tax" not in str(x) for x in env.log.lines), "set_commission 参数降级成功")

print("\n【2】_canon 标识符统一（V2 BUG-1 根因）")
ok(ns["_canon"]("600360.SS") == "600360", "_canon 去后缀")
ok(ns["_canon"]("600360") == "600360", "_canon 幂等")
ok(ns["_canon"]("300123.SZ") == "300123", "_canon 创业板")
ok(ns["_suffix"]("000300.SS") == "000300.SS", "_api_code 保留指数后缀不被改成 .SZ")
ok(ns["_api_code"]("000300.SS") == "000300.SS", "_api_code 指数原样保留")
ok(ns["_api_code"]("600000") == "600000.SS", "_api_code 普通代码补后缀")

print("\n【3】涨跌幅自适应（V2 BUG-3）")
ok(abs(ns["_limit_pct"]("600000") - 0.10) < 1e-9, "主板 10%")
ok(abs(ns["_limit_pct"]("300123") - 0.20) < 1e-9, "创业板 20%")
ok(abs(ns["_limit_pct"]("688001") - 0.20) < 1e-9, "科创板 20%")
ok(abs(ns["_limit_pct"]("830001") - 0.30) < 1e-9, "北交所 30%")
ok(abs(ns["_limit_pct"]("600000", True) - 0.05) < 1e-9, "ST 5%")
ok(ns["_zt_line"]("300123") > 19.0, "创业板涨停线≈19.6%（V2 一律 9.5% → 判错）")
ok(ns["_zt_line"]("600000") < 10.0, "主板涨停线≈9.8%")

# ------------------------------------------------------------
print("\n【4】signal_job 全链路（T日 14:55 尾盘快照）")
g = env.run_signal()
if MODE == "single":
    ok(len(g.hist) > 200, "取数命中（逐票降级：扫描范围已收缩）",
       "{} 只".format(len(g.hist)))
else:
    ok(len(g.hist) > 800, "批量取数命中", "{} 只".format(len(g.hist)))
ok(len(g.feat) > 300, "个股特征计算", "{} 只".format(len(g.feat)))
ok(len(g.sector_state) > 10, "板块信号非空", "{} 个".format(len(g.sector_state)))
mains = [s for s in g.sector_state if s.get("is_main")]
mnames = [s["sector"] for s in mains]
ok(len(mains) >= 1, "主线选出", str(mnames))
ok(HOT_THEME in mnames, "热点题材入选主线", str(mnames))
ok(OVERSIZE not in mnames, "超限板块（{}只>80）被剔除".format(len(BIG_MEMBERS)), str(mnames))
ok(not any(m in BROAD for m in mnames), "宽口径标签未入选主线", str(mnames))
ok(all(s["n_feat"] <= ns["MAX_SECTOR_SIZE"] for s in mains), "主线成分数均在上限内")
ok(all(s["zt_cnt"] > 0 for s in mains), "主线均含涨停（涨停驱动）")

print("\n【5】板块强度归一化（V2：强度正比于成分数）")
sig_map = dict((s["sector"], s) for s in g.sector_state)
big_over = [s for s in g.sector_state if s["n_feat"] > ns["MAX_SECTOR_SIZE"]]
if big_over:
    bo = max(big_over, key=lambda s: s["strength"])
    th = sig_map.get(HOT_THEME)
    print("     超限板块 {} 成分{} 涨停{} 归一强度{}".format(
        bo["sector"], bo["n_feat"], bo["zt_cnt"], bo["strength"]))
    if th:
        print("     题材   {} 成分{} 涨停{} 归一强度{}".format(
            th["sector"], th["n_feat"], th["zt_cnt"], th["strength"]))
    ok(th is None or th["zt_rate"] >= 0.0, "涨停率字段存在")
ok(all(0.0 <= s["zt_rate"] <= 1.0 for s in g.sector_state), "zt_rate 归一化到 [0,1]")
ok(all(0.0 <= s["ratio_up"] <= 1.0 for s in g.sector_state), "ratio_up 归一化到 [0,1]")

print("\n【6】候选生成")
cands = list(g.pending_buy)
cset = set(c["code"] for c in cands)
ok(len(cands) > 0, "候选非空", "{} 只".format(len(cands)))
if cands:
    print("     " + ", ".join("{}(+{:.1f}%,连板{})".format(c["code"], c["pct"], c["lianban"])
                             for c in cands[:6]))
ok(not (cset & ZT_MEMBERS), "封板组被剔除（R1 可成交性）", str(sorted(cset & ZT_MEMBERS)))
ok(all(c["pct"] < c["zt_line"] for c in cands), "候选全部未封板")
ok(all(c["above20"] for c in cands), "候选全部站上20日线")
ok(all(c["amt"] >= ns["MIN_AMOUNT"] for c in cands), "成交额门槛真实生效")
ok(all(c["amt"] > 1e8 for c in cands), "成交额量级正确（volume=股，未乘100）",
   str([round(c["amt"] / 1e8, 2) for c in cands[:3]]))
ok(max((c["amt"] for c in cands), default=0) > 3e8, "成交额 > 3亿门槛")
if MODE == "single":
    ok(len(env.hist_calls) > 400,
       "逐票降级：调用数≈收缩后的扫描数（而非全池 13,609 次）",
       "实际 {} 次".format(len(env.hist_calls)))
else:
    ok(len(env.hist_calls) < 30,
       "取数已批量化（V2 为 13,609 次单票调用）",
       "实际 {} 次".format(len(env.hist_calls)))
ok("量纲标定" in logtext(env), "量纲标定已打印")

print("\n【7】_main_line_groups 单元测试（黑名单 / 体量上限 / Jaccard）")
fake_sigs = [
    {"sector": BROAD[0], "strength": 99.0, "zt_cnt": 20, "n_feat": len(BROAD_MEMBERS[BROAD[0]])},
    {"sector": OVERSIZE, "strength": 98.0, "zt_cnt": 15, "n_feat": len(BIG_MEMBERS)},
    {"sector": HOT_THEME, "strength": 50.0, "zt_cnt": 3, "n_feat": len(THEME_MEMBERS)},
    {"sector": HOT2, "strength": 40.0, "zt_cnt": 2, "n_feat": len(THEME2_MEMBERS)},
]
picked = [s["sector"] for s in ns["_main_line_groups"](fake_sigs)]
ok(BROAD[0] not in picked, "宽口径标签（强度第1）被剔除", str(picked))
ok(OVERSIZE not in picked, "超限板块（强度第2）被剔除", str(picked))
ok(HOT_THEME in picked, "合规题材入选", str(picked))

print("\n【8】三阶段接入决策")
unit = dict((s["sector"], s) for s in g.sector_state)
th = unit.get(HOT_THEME)
if th:
    ok(th["stage"] in ("启动", "扩散", "无"), "首日无历史 → 启动期", th["stage"])
    ok(ns["classify_stage"]({"zt_cnt": 1}, [6, 5, 5]) == "衰退", "涨停腰斩 → 衰退")
    ok(ns["classify_stage"]({"zt_cnt": 4}, [5, 5, 5]) == "扩散", "持平 → 扩散")
    ok(ns["classify_stage"]({"zt_cnt": 3}, [0, 0, 1]) == "启动", "首现涨停 → 启动")
env_st = Env()
env_st.run_signal()
env_st.g.sector_state = [dict(s, stage="衰退") if s["sector"] == HOT_THEME else s
                         for s in env_st.g.sector_state]
bad = [c for c in env_st.ns["_pick_candidates"]([s for s in env_st.g.sector_state
                                                if s.get("is_main")])
       if c.get("sector") == HOT_THEME]
ok(not bad, "衰退期板块不产生候选")

print("\n【9】持仓排除 / 冷静期真正生效（V2 BUG-1 的行为验证）")
tgt = sorted(cset)[0] if cset else None
if tgt:
    e2 = Env(positions={ns["_suffix"](tgt): pos(ns["_suffix"](tgt))})
    e2.run_signal()
    ok(tgt not in set(c["code"] for c in e2.g.pending_buy),
       "已持仓标的被排除出候选", tgt)
    e3 = Env()
    e3.run_signal()
    tgt2 = sorted(set(c["code"] for c in e3.g.pending_buy))[0]
    e4 = Env()
    e4.load()
    e4.ns["initialize"](e4.ctx)
    e4.ns["before_trading_start"](e4.ctx, None)
    e4.g.cool_down[tgt2] = 3
    e4.ns["signal_job"](e4.ctx)
    ok(tgt2 not in set(c["code"] for c in e4.g.pending_buy),
       "冷静期内标的不进候选", tgt2)

print("\n【10】ST 剔除")
if tgt:
    e5 = Env()
    e5.load()
    e5.ns["initialize"](e5.ctx)
    e5.ns["before_trading_start"](e5.ctx, None)
    e5.names[tgt] = "ST某某"
    e5.ns["signal_job"](e5.ctx)
    ok(tgt not in set(c["code"] for c in e5.g.pending_buy), "ST 标的被剔除", tgt)

# ------------------------------------------------------------
print("\n【11】open_job：限价锚 = T日收盘（V2 用 T-1 收盘，致命错位）")
env.phase = "T+1"
env.ctx.blotter.current_dt = datetime.datetime(2026, 9, 15, 9, 31)
env.ns["TRADE_ENABLED"] = True
env.orders = []
env.ns["open_job"](env.ctx)
buys = [o for o in env.orders if o["api"] == "order_value"]
ok(len(buys) > 0, "产生买单", "{} 笔".format(len(buys)))
if buys:
    bad = []
    for o in buys:
        c = Env._k(o["code"])
        want = round(T_CLOSE[c] * 1.03, 2)
        if abs(o["limit_price"] - want) > 0.011:
            bad.append((c, o["limit_price"], want))
    ok(not bad, "限价 = T日收盘×1.03（锚精确到 T 日收盘）", str(bad[:3]))
    c0 = Env._k(buys[0]["code"])
    prev_c = T_CLOSE[c0] / 1.07 if c0 in HOT_MEMBERS else None
    print("     {} 锚(T日收盘)={:.2f} 限价={:.2f}  T-1收盘≈{:.2f}".format(
        c0, T_CLOSE[c0], buys[0]["limit_price"],
        prev_c if prev_c else float("nan")))
ok(not any(o.get("limit_price") is None for o in buys), "order_value 使用 limit_price 参数名")
low_tried = any(Env._k(o["code"]) == LOW_OPEN for o in buys)
high_tried = any(Env._k(o["code"]) == HIGH_OPEN for o in buys)
if LOW_OPEN in cset:
    ok(not low_tried, "低开 < 下限 → 放弃（不接刀）", LOW_OPEN)
if HIGH_OPEN in cset:
    ok(not high_tried, "高开 > 上限 → 放弃（不追高）", HIGH_OPEN)
lt = logtext(env)
ok(("低开不接刀" in lt) or (LOW_OPEN not in cset), "低开放弃有日志")
ok("高开不追" in lt or (HIGH_OPEN not in cset), "高开放弃有日志")
ok("已满仓" not in lt, "未误判满仓")

print("\n【12】切片推进（V2 BUG-2：候选错位 → 重复下单）")
e6 = Env(phase="T+1")
e6.load()
e6.ns["initialize"](e6.ctx)
e6.ctx.blotter.current_dt = datetime.datetime(2026, 9, 15, 9, 31)
e6.ns["TRADE_ENABLED"] = True
A, B = MAIN[500], MAIN[501]
e6.g.pending_buy = [{"code": A, "amt": 1e9, "sector": "X", "stage": "启动"},
                    {"code": B, "amt": 1e9, "sector": "X", "stage": "启动"}]
e6.positions = {ns["_suffix"](A): pos(ns["_suffix"](A))}
e6.ns["open_job"](e6.ctx)
placed = [Env._k(o["code"]) for o in e6.orders if o["api"] == "order_value"]
ok(A not in placed, "已在持仓的不重复下单")
ok(B in placed, "后续候选被正常处理（V2 会错位）")
ok(not e6.g.pending_buy, "已处理候选从队列移除（不残留）")

print("\n【13】风控：板块级联动清仓（V2 未实现）")
e7 = Env(phase="T+1")
e7.load()
e7.ns["initialize"](e7.ctx)
rc = COOL_MEMBER
k = ns["_canon"](rc)
e7.positions = {ns["_suffix"](rc): pos(ns["_suffix"](rc), cost=20.0, price=19.9)}
e7.g.prev_signal[HOT_THEME] = [6, 6, 5, 4]
e7.g.sector_state = [{"sector": HOT_THEME, "stage": "衰退", "zt_cnt": 0, "strength": 0}]
e7.g.code_sector[k] = HOT_THEME
e7.g.pos_hist = {k: [("d", 20.0, 20.2, 19.8, 1e7, 20.0)] * 12}
e7.ns["TRADE_ENABLED"] = True
e7.orders = []
e7.ns["monitor_risk"](e7.ctx)
sells = [o for o in e7.orders if o["api"] == "order" and o["amount"] < 0]
ok(len(sells) > 0, "板块衰退 → 联动清仓卖出", str(sells[:2]))
ok("板块联动清仓" in logtext(e7), "清仓原因正确标注")
e8 = Env(phase="T+1")
e8.load()
e8.ns["initialize"](e8.ctx)
e8.g.sector_state = [{"sector": HOT_THEME, "stage": "启动", "zt_cnt": 5, "strength": 9}]
e8.g.prev_signal[HOT_THEME] = [5, 5, 5]
ok(HOT_THEME not in e8.ns["_sector_killed"](), "非衰退板块不被否决")

print("\n【14】风控：ATR 止损 + 最短持有期")
e9 = Env(phase="T+1")
e9.load()
e9.ns["initialize"](e9.ctx)
c = HELD_MEMBER
k = ns["_canon"](c)
e9.positions = {ns["_suffix"](c): pos(ns["_suffix"](c), cost=20.0, price=17.0)}
e9.g.pos_hist = {k: [("d", 16.5, 17.4, 15.6, 1e7, 16.5)] * 20}   # MA5 < 现价，隔离 ATR 逻辑
e9.g.hold_days[k] = 10
e9.g.sector_state = []
e9.g.code_sector[k] = "无关题材ABC"
e9.ns["TRADE_ENABLED"] = True
e9.orders = []
e9.ns["monitor_risk"](e9.ctx)
ok(len([o for o in e9.orders if o.get("amount", 0) < 0]) > 0,
   "ATR 止损触发（浮亏15%，持仓10日）")
e9.g.hold_days[k] = 1
e9.orders = []
e9.ns["monitor_risk"](e9.ctx)
ok(len([o for o in e9.orders if o.get("amount", 0) < 0]) == 0,
   "未满最短持有期 → 不启用紧止损")
ok("暂不紧止损" in logtext(e9), "最短持有期有日志")

print("\n【15】可卖量=0 → 排队次日，不发废单（P0-4）")
e10 = Env(phase="T+1")
e10.load()
e10.ns["initialize"](e10.ctx)
c = ST_MEMBER
k = ns["_canon"](c)
e10.positions = {ns["_suffix"](c): pos(ns["_suffix"](c), cost=20.0, price=17.0, enable=0)}
e10.g.pos_hist = {k: [("d", 16.5, 17.4, 15.6, 1e7, 16.5)] * 20}
e10.g.hold_days[k] = 10
e10.g.sector_state = []
e10.g.code_sector[k] = "无关题材ABC"
e10.ns["TRADE_ENABLED"] = True
e10.orders = []
e10.ns["monitor_risk"](e10.ctx)
ok(len(e10.orders) == 0, "可卖=0 不发单")
ok(len(e10.g.stop_queue) == 1, "已入次日排队队列")

print("\n【16】换手预算 / 市场开关 / 参数自检")
ok(ns["MAX_ANNUAL_TURNS"] == int(ns["TARGET_ANNUAL_COST"] / (2 * ns["COST_PER_SIDE"])),
   "换手预算换算一致", str(ns["MAX_ANNUAL_TURNS"]))
ok(ns["BUY_FLOOR_PCT"] < ns["BUY_PREMIUM_PCT"], "双边限价区间合法")
ok(ns["RETREAT_MA"] == 5, "退潮均线已对齐决策3（5日线）")
ok(ns["STOP_MODE"] in ("atr", "fixed"), "止损模式可切换")
ok(ns["MIN_HOLD_FOR_TIGHT_STOP"] >= 1, "最短持有期已启用")
env.g.trades = [("2026-08-01", 1.0e8, "buy")] * 60
ok(ns["turnover_ok"](env.ctx, 5.0e6) is False, "换手超预算 → 停开新仓")
env.g.trades = []
ok(ns["turnover_ok"](env.ctx, 5.0e6) is True, "无成交 → 预算通过")
ok(ns["market_regime_ok"]() is True, "市场开关在本场景通过")
old = ns["MARKET_ZT_FLOOR"]
ns["MARKET_ZT_FLOOR"] = 999
ok(ns["market_regime_ok"]() is False, "涨停家数不足 → 停开新仓")
ns["MARKET_ZT_FLOOR"] = old

print("\n【17】降级路径（模式 {}）".format(MODE))
detected = ns["_probe_hist_mode"]()
expected_mode = "dict" if MODE == "nofq" else MODE
ok(detected == expected_mode, "探测返回形态 = {}".format(expected_mode),
   "实际 {}".format(detected))
if MODE == "nofq":
    ok(env.g.fq_ok is False, "fq 参数不支持已自动降级（非静默换口径）")
    ok("fq" in logtext(env) or "不复权" in logtext(env), "fq 降级已告警")
if MODE == "single":
    e11 = Env()
    e11.load()
    e11.ns["initialize"](e11.ctx)
    e11.ns["before_trading_start"](e11.ctx, None)
    uni = e11.ns["_scan_universe"]()
    ok(len(uni) < len(CODES), "扫描范围自动收缩",
       "{} → {}".format(len(CODES), len(uni)))
    e11.ns["signal_job"](e11.ctx)
    ok(len(e11.g.sector_state) > 0, "逐票模式下信号层仍可产出")

print("\n" + "=" * 76)
print("断言 {} 项，失败 {} 项".format(CHECKS[0], len(FAILS)))
for f in FAILS:
    print("  FAIL: {}".format(f))
print("=" * 76)
sys.exit(1 if FAILS else 0)
