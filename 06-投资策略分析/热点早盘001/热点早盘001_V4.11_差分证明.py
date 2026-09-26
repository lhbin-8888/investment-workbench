# -*- coding: utf-8 -*-
"""热点早盘001 V4.11 —— 差分证明：同一回归逻辑跑在 V4.10 上必须失败

背景：V4.10 的头号卖点「赢家浮盈回撤锁利(③b)」因 g.winner_peak_pnl 缺省值取成"当前浮盈"
      而**永不落库** → 判据恒为 0 → 死代码（V4.10 回测 41 次进入赢家宽管、锁利 0 次）。
      V4.11 修复为显式缺省判定后，峰值真正持久化。

本脚本把 V4.11 校验器 Test 6 的同一段逻辑跑在 **V4.10** 上，应当观察到：
  ① 首次 +30% 后 g.winner_peak_pnl["WIN.SZ"] 仍为 None（峰值未落库）；
  ② 二次 +21% 后不触发"赢家锁利"。
若观察到相反结果，说明 V4.10 已自行修复（与既有结论矛盾），需重新核对基线文件。

用法：python 热点早盘001_V4.11_差分证明.py   → 退出码 0 = 证明成立（V4.10 确实为死代码）。
配套：热点早盘001_V4.11_离线校验器.py（Test 6，跑 V4.11 应全部通过）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASELINE = os.path.join(_HERE, "热点早盘001_V4.10.py")
if not os.path.exists(_BASELINE):
    print("[FATAL] 找不到基线文件: {}".format(_BASELINE))
    sys.exit(2)

# ---------------------------------------------------------------------------
# mock PTrade 平台环境（与离线校验器同构）
# ---------------------------------------------------------------------------
_log = []
def _mk_log():
    class _L(object):
        @staticmethod
        def info(*a, **k): _log.append(a[0] if a else "")
        @staticmethod
        def warn(*a, **k): _log.append("[W]" + str(a[0] if a else ""))
        @staticmethod
        def error(*a, **k): _log.append("[E]" + str(a[0] if a else ""))
        @staticmethod
        def debug(*a, **k): pass
    return _L()

class _G(object): pass
class _Ctx(object): pass
_dosell = []
ns = {
    "g": _G(), "log": _mk_log(), "context": _Ctx(),
    "data": None, "set_benchmark": lambda *a, **k: None,
    "run_daily": lambda *a, **k: None,
    "order_target_value": lambda *a, **k: None, "order": lambda *a, **k: None,
    "get_history": lambda *a, **k: [], "get_current_data": lambda *a, **k: {},
    "attribute_history": lambda *a, **k: [], "history": lambda *a, **k: [],
    "get_fundamentals": lambda *a, **k: {}, "schedule": lambda *a, **k: None,
    "record": lambda *a, **k: None,
}

with open(_BASELINE, "r", encoding="utf-8") as f:
    exec(compile(f.read(), _BASELINE, "exec"), ns)

print("=" * 72)
print("[差分证明] 基线文件 = {}".format(_BASELINE))

g = ns["g"]
ns["initialize"](ns["context"])
for _k in ("peak", "hold_days", "winner_set", "winner_peak_pnl", "partial_done",
           "cool_down", "stop_stage1", "code_sector", "pos_hist", "entry_px",
           "sector_stops", "sector_cooldown_days"):
    setattr(g, _k, {} if _k not in ("winner_set", "partial_done") else set())

_pm = {"WIN.SZ": {"current_amount": 1000, "enable_amount": 1000,
                  "last_price": 130.0, "cost_price": 100.0}}
ns["positions_map"] = lambda: _pm
ns["_do_sell"] = lambda code, amt, reason, px=None: _dosell.append((code, amt, reason))
ns["_now_str"] = lambda c: "14:50"
g.now_str = "14:50"; g.today = "2026-06-02"
g.entry_px = {"WIN.SZ": 100.0}; g.hold_days = {"WIN.SZ": 5}
g.winner_set = {"WIN.SZ"}; g.partial_done = {"WIN.SZ"}
g.code_sector = {}; g.pos_hist = {}; g.peak = {}

# 第一次：+30% —— V4.10 应不落库峰值
ns["monitor_risk"](ns["context"])
pk1 = g.winner_peak_pnl.get("WIN.SZ")
print("[1] V4.10 首次 +30% 后 winner_peak_pnl['WIN.SZ'] = {!r}（预期 None = 峰值未落库）".format(pk1))

# 第二次：+21% —— V4.10 应不触发锁利
_pm["WIN.SZ"]["last_price"] = 121.0
_dosell[:] = []
ns["monitor_risk"](ns["context"])
hit = [r for (_, _, r) in _dosell if "赢家锁利" in r]
print("[2] V4.10 二次 +21% 后 赢家锁利触发 = {}（预期 0）".format(len(hit)))

ok = (pk1 is None) and (len(hit) == 0)
print("=" * 72)
if ok:
    print("[结论] 证明成立 ✅  V4.10 的赢家锁利确为死代码 → V4.11 的 Test 6 是有效回归护栏。")
    sys.exit(0)
print("[结论] ⚠ 未复现 V4.10 死代码形态 —— 请核对基线文件是否为未修复的 V4.10。")
sys.exit(1)
