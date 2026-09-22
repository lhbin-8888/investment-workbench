# -*- coding: utf-8 -*-
"""
热点早盘001 V4.11 —— 离线校验器（不依赖 PTrade 平台）

目的：在把策略文件上传券商托管机房前，先在本地用 mock 平台环境把代码跑一遍，
阻断"传错文件白跑一轮 / 新分支 NameError 崩溃"这类低级问题。

覆盖范围：
  1) 文件可 exec、initialize 可跑、本版新增的 5 个 g 状态字段全部就位；
  2) 纯函数 _days_between 日历日差计算正确；
  3) ★核心★ monitor_risk 赢家"浮盈回撤锁利"(③b) 分支（手动 seed 峰值）：赢家自 +30%
     回撤到 +22%(≥8pp) 必须触发锁利清仓；
  4) ★核心★ monitor_risk 板块连败冷却记录：板块内止损事件写入 g.sector_stops，
     达阈值后 g.sector_cooldown_days 置位；
  5) ★核心★ buy_job 连败冷却跳过：处于冷却期的板块候选必须被跳过、不下单。
  6) ★V4.11 回归★ 赢家峰值由代码**真实落库**并跨调用保持、不 seed 直接跑 monitor_risk：
     赢家 +30%→+21% 必须触发锁利（V4.10 此分支为死代码：峰值永不落库导致 0 触发）。

运行：python 热点早盘001_V4.10_离线校验器.py
退出码：0=全部通过；非 0=存在失败（详见输出）。
"""

import os
import sys
import types

# ---------------------------------------------------------------------------
# 0) 定位策略文件
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
# 候选路径：① 与校验器同目录；② 标准策略目录（档案构建时校验器在 archive\temp_v410 下）
_CANDIDATES = [
    os.path.join(_HERE, "热点早盘001_V4.11.py"),
    os.path.normpath(os.path.join(
        _HERE, "..", "..", "06-投资策略分析", "策略回测",
        "热点早盘001", "热点早盘001_V4.11.py")),
    r"D:\投研工作台\06-投资策略分析\策略回测\热点早盘001\热点早盘001_V4.11.py",
]
_STRATEGY = next((p for p in _CANDIDATES if os.path.exists(p)), None)
if not _STRATEGY:
    print("[FATAL] 找不到策略文件，已尝试: {}".format("; ".join(_CANDIDATES)))
    sys.exit(2)

print("=" * 72)
print("[校验器] 策略文件 = {}".format(_STRATEGY))

# ---------------------------------------------------------------------------
# 1) 构建 mock 平台环境
# ---------------------------------------------------------------------------
class _G(object):
    """模拟 PTrade 的全局 g 对象（属性容器）。"""
    pass


_log_lines = []           # 捕获 log 输出，便于后续断言
_ordered = []             # 捕获 order_target_value 下单
_dosell = []              # 捕获 _do_sell 调用


def _mk_log():
    class _L(object):
        @staticmethod
        def info(*a, **k):
            s = a[0] if a else ""
            _log_lines.append(s)
        @staticmethod
        def warn(*a, **k):
            s = a[0] if a else ""
            _log_lines.append("[WARN]" + str(s))
        @staticmethod
        def error(*a, **k):
            s = a[0] if a else ""
            _log_lines.append("[ERR]" + str(s))
        @staticmethod
        def debug(*a, **k):
            pass
    return _L()


class _Ctx(object):
    """极简 context：只满足被调用函数对它的取属性需求。"""
    pass


# 注入到模块命名空间的平台全局
ns = {
    "g": _G(),
    "log": _mk_log(),
    "context": _Ctx(),
    "data": None,
    "set_benchmark": lambda *a, **k: None,
    "run_daily": lambda *a, **k: None,
    "order_target_value": lambda *a, **k: _ordered.append(a),
    "order": lambda *a, **k: None,
    "get_history": lambda *a, **k: [],
    "get_current_data": lambda *a, **k: {},
    "attribute_history": lambda *a, **k: [],
    "history": lambda *a, **k: [],
    "get_fundamentals": lambda *a, **k: {},
    "schedule": lambda *a, **k: None,
    "record": lambda *a, **k: None,
}

# ---------------------------------------------------------------------------
# 2) 执行策略文件（等价 import），捕获语法/顶层错误
# ---------------------------------------------------------------------------
with open(_STRATEGY, "r", encoding="utf-8") as f:
    _src = f.read()

try:
    exec(compile(_src, _STRATEGY, "exec"), ns)
except Exception as e:
    import traceback
    print("[FATAL] 策略文件 exec 失败: {}".format(repr(e)))
    traceback.print_exc()
    sys.exit(2)

print("[校验器] exec 通过（无语法/顶层错误）")

# 把若干需要在测试中替换的"内部函数"统一引用，便于后面 monkeypatch
def _patch(name, fn):
    ns[name] = fn

# ---------------------------------------------------------------------------
# 3) 测试清单
# ---------------------------------------------------------------------------
_FAIL = []
_OK = []

def check(cond, msg):
    if cond:
        _OK.append(msg)
        print("  [PASS] " + msg)
    else:
        _FAIL.append(msg)
        print("  [FAIL] " + msg)


# ---- 3.1 initialize 冒烟 + 本版新增 g 字段 ----
print("-" * 72)
print("[测试 1] initialize 冒烟 & V4.11 新增状态字段")
try:
    ns["initialize"](ns["context"])
    g = ns["g"]
    _new_fields = ["regime_rows", "winner_set", "winner_peak_pnl",
                   "sector_stops", "sector_cooldown_days"]
    _missing = [f for f in _new_fields if not hasattr(g, f)]
    check(len(_missing) == 0,
          "initialize 跑通，新增字段齐全" + ("" if not _missing else "，缺失:{}".format(_missing)))
    # 类型 sanity
    check(isinstance(g.winner_set, set), "g.winner_set 是 set")
    check(isinstance(g.winner_peak_pnl, dict), "g.winner_peak_pnl 是 dict")
    check(isinstance(g.sector_stops, list), "g.sector_stops 是 list")
    check(isinstance(g.sector_cooldown_days, dict), "g.sector_cooldown_days 是 dict")
    check(isinstance(g.regime_rows, list), "g.regime_rows 是 list")
except Exception as e:
    import traceback
    check(False, "initialize 抛异常: {}".format(repr(e)))
    traceback.print_exc()

# ---- 3.2 纯函数 _days_between ----
print("-" * 72)
print("[测试 2] _days_between 日历日差")
_d = ns["_days_between"]
check(_d("2026-06-01", "2026-06-11") == 10, "_days_between(06-01,06-11)=10")
check(_d("2026-06-11", "2026-06-01") == -10, "_days_between 反向为负")
check(_d("2026-01-01", "2026-12-31") == 364, "_days_between 跨月")

# ---------------------------------------------------------------------------
# 公共：准备 monitor_risk 运行所需的 mock
# ---------------------------------------------------------------------------
def _prep_monitor(pm_dict, now="14:50", today="2026-06-01"):
    g = ns["g"]
    g.now_str = now
    g.today = today
    for _k in ("peak", "hold_days", "winner_set", "winner_peak_pnl",
              "partial_done", "cool_down", "stop_stage1", "code_sector",
              "pos_hist", "entry_px", "sector_stops", "sector_cooldown_days"):
        if not hasattr(g, _k):
            setattr(g, _k, {} if _k not in ("winner_set", "partial_done") else set())
    g.pos_hist.setdefault("__x", None)
    g.pos_hist.pop("__x", None)
    _patch("positions_map", lambda: pm_dict)
    _dosell[:] = []
    _patch("_do_sell", lambda code, amt, reason, px=None: _dosell.append((code, amt, reason)))
    _patch("_now_str", lambda c: now)

# ---- 3.3 赢家"浮盈回撤锁利"（③b） ----
print("-" * 72)
print("[测试 3] 赢家锁利分支：+30% 峰值回撤至 +22%（≥8pp）→ 清仓")
_prep_monitor({
    "WIN.SZ": {"current_amount": 1000, "enable_amount": 1000,
               "last_price": 122.0, "cost_price": 100.0}
})
g = ns["g"]
g.winner_set = {"WIN.SZ"}
g.winner_peak_pnl = {"WIN.SZ": 0.30}
g.entry_px = {"WIN.SZ": 100.0}
g.hold_days = {"WIN.SZ": 5}
g.partial_done = {"WIN.SZ"}          # 跳过分批止盈，直达 ③b
g.pos_hist = {}                       # 无均线，规避破线分支干扰
g.peak = {}
try:
    ns["monitor_risk"](ns["context"])   # sector_clear 默认 False
    _hit = [r for (_, _, r) in _dosell if "赢家锁利" in r]
    check(len(_hit) == 1, "赢家锁利清仓已触发，理由含'赢家锁利' -> {}".format(
        _hit[0] if _hit else "无"))
except Exception as e:
    import traceback
    check(False, "monitor_risk(赢家) 抛异常: {}".format(repr(e)))
    traceback.print_exc()

# ---- 3.4 板块连败冷却：记录 + 置位 ----
print("-" * 72)
print("[测试 4] 板块连败冷却记录：板块内止损 → g.sector_stops 写入、达阈值置位")
_prep_monitor({
    "LOS.SZ": {"current_amount": 1000, "enable_amount": 1000,
               "last_price": 93.0, "cost_price": 100.0}
})
g = ns["g"]
g.entry_px = {"LOS.SZ": 100.0}
g.hold_days = {"LOS.SZ": 3}
g.partial_done = set()
g.code_sector = {"LOS.SZ": "稀缺资源"}
g.pos_hist = {}
g.peak = {}
g.winner_set = set()
g.winner_peak_pnl = {}
g.sector_stops = []
g.sector_cooldown_days = {}
# 临时把阈值降到 1，使单次止损即触发冷却（验证记录→置位链路）
_orig_n = ns["SECTOR_STOP_COOLDOWN_N"]
ns["SECTOR_STOP_COOLDOWN_N"] = 1
# 强制 fixed 止损（默认 atr 模式需要 K 线，本测试不构造 K 线）
_orig_mode = ns.get("STOP_MODE")
_orig_fixed = ns.get("STOP_LOSS_PCT")
ns["STOP_MODE"] = "fixed"
ns["STOP_LOSS_PCT"] = 0.05
try:
    ns["monitor_risk"](ns["context"])
    _stop_hit = [r for (_, _, r) in _dosell if r.startswith("止损")]
    check(len(_stop_hit) == 1, "硬止损已触发 -> {}".format(_stop_hit[0] if _stop_hit else "无"))
    check(("2026-06-01", "稀缺资源") in g.sector_stops,
          "g.sector_stops 已记录 (日期,板块)")
    check(g.sector_cooldown_days.get("稀缺资源", 0) > 0,
          "g.sector_cooldown_days['稀缺资源'] 已置位 = {}".format(
              g.sector_cooldown_days.get("稀缺资源")))
finally:
    ns["SECTOR_STOP_COOLDOWN_N"] = _orig_n   # 复原
    ns["STOP_MODE"] = _orig_mode
    ns["STOP_LOSS_PCT"] = _orig_fixed

# ---- 3.5 buy_job 连败冷却跳过 ----
print("-" * 72)
print("[测试 5] buy_job 冷却跳过：冷却期板块候选必须被跳过、不下单")
g = ns["g"]
g.pending_buy = [{"code": "000001.SZ", "sector": "稀缺资源", "stage": "启动"}]
g.mainline_entries = []
g.today = "2026-06-05"
g.now_str = ""
g.sector_cooldown_days = {"稀缺资源": 5}     # 手工置位（模拟测试4的产出）
_ordered[:] = []
_log_lines[:] = []
_patch("positions_map", lambda: {})
_patch("_now_str", lambda c: "09:32")
_patch("market_risk_off", lambda: False)
_patch("turnover_ok", lambda c, t: True)
_patch("_buys_this_month_ok", lambda c: True)
_patch("market_regime_ok", lambda: True)
_patch("_total_asset", lambda c: 1_000_000)
_patch("_cash_of", lambda c, t, n: 1_000_000)
_patch("_live_price_and_ref", lambda c, codes: {cd: {"last": 10.0, "ref": 10.0} for cd in codes})
try:
    ns["buy_job"](ns["context"])
    _skipped = any("连败冷却" in s for s in _log_lines)
    check(_skipped, "日志中出现'连败冷却'跳过提示")
    check(len(_ordered) == 0, "冷却期板块未下单（order_target_value 调用 0 次）")
except Exception as e:
    import traceback
    check(False, "buy_job(冷却跳过) 抛异常: {}".format(repr(e)))
    traceback.print_exc()

# ---- 3.6 ★V4.11 回归★ 赢家峰值"真实代码路径"持久化 + 锁利触发 ----
print("-" * 72)
print("[测试 6] ★V4.11 回归★ 峰值由代码落库并跨调用保持；回撤≥8pp 触发锁利")
g = ns["g"]
# 复位相关状态（沿用 _prep_monitor 的同款字段集，但本测试全程不 seed winner_peak_pnl）
for _k in ("peak", "hold_days", "winner_set", "winner_peak_pnl", "partial_done",
           "cool_down", "stop_stage1", "code_sector", "pos_hist", "entry_px",
           "sector_stops", "sector_cooldown_days"):
    setattr(g, _k, {} if _k not in ("winner_set", "partial_done") else set())
g.now_str = "14:50"
g.today = "2026-06-02"
_pm = {"WIN.SZ": {"current_amount": 1000, "enable_amount": 1000,
                  "last_price": 130.0, "cost_price": 100.0}}
_patch("positions_map", lambda: _pm)
_dosell[:] = []
_patch("_do_sell", lambda code, amt, reason, px=None: _dosell.append((code, amt, reason)))
_patch("_now_str", lambda c: "14:50")
g.entry_px = {"WIN.SZ": 100.0}      # USE_OWN_COST=True → cost=100
g.hold_days = {"WIN.SZ": 5}          # <= WINNER_MAX_HOLD(30)
g.winner_set = {"WIN.SZ"}            # 直接赋予赢家身份，聚焦峰值追踪逻辑
g.partial_done = {"WIN.SZ"}          # 跳过分批止盈，直达 ③b
g.code_sector = {}                   # 无板块联动
g.pos_hist = {}                      # 无均线，规避破线分支
g.peak = {}
try:
    # 第一次：价格 130（+30%）→ 代码应把峰值 0.30 落库，不触发锁利
    ns["monitor_risk"](ns["context"])
    _pk1 = g.winner_peak_pnl.get("WIN.SZ")
    check(_pk1 is not None and abs(_pk1 - 0.30) < 1e-3,
          "① 首次进入后峰值已落库（实测 {!r}，应≈0.30）".format(_pk1))
    check(len(_dosell) == 0,
          "② 首次 +30% 未触发任何卖出（dosell={}）".format(_dosell))

    # 第二次：价格回落到 121（+21%），峰值应保持 0.30（不被当前浮盈覆盖），
    #         且 0.30−0.21=0.09 ≥ WINNER_GIVEBACK_PCT(0.08) → 赢家锁利触发
    _pm["WIN.SZ"]["last_price"] = 121.0
    _dosell[:] = []
    ns["monitor_risk"](ns["context"])
    _pk2 = g.winner_peak_pnl.get("WIN.SZ")
    check(_pk2 is not None and abs(_pk2 - 0.30) < 1e-3,
          "③ 二次调用后峰值仍保持 0.30（实测 {!r}，未被 0.21 覆盖）".format(_pk2))
    _hit = [r for (_, _, r) in _dosell if "赢家锁利" in r]
    check(len(_hit) == 1,
          "④ 回撤≥8pp 触发赢家锁利清仓 -> {}".format(_hit[0] if _hit else "无"))
except Exception as e:
    import traceback
    check(False, "monitor_risk(峰值持久化回归) 抛异常: {}".format(repr(e)))
    traceback.print_exc()

# ---------------------------------------------------------------------------
# 4) 汇总
# ---------------------------------------------------------------------------
print("=" * 72)
print("[汇总] 通过 {} 项，失败 {} 项".format(len(_OK), len(_FAIL)))
if _FAIL:
    print("[FAIL 清单]")
    for m in _FAIL:
        print("   - " + m)
    sys.exit(1)
print("[结论] 全部通过 ✅  可上传券商托管机房做正式回测。")
sys.exit(0)
