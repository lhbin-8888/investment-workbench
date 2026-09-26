# -*- coding: utf-8 -*-
"""v7 聚焦行为验证：逐预设断言「盘中/结构时点」的出场规则差异。

不模拟行情，只构造单一持仓 + 受控收盘序列，直接调用风控，检查实际发出的卖出决策。

夹具修正（v7 第二轮）：
  1) entry 默认 2026-06-05（距 ctx.current_dt=2026-06-08 共 3 个自然日 < MAX_HOLD_DAYS=5），
     否则「时间止损」会抢在破均线/止损之前把持仓打掉，掩盖真正要验证的分支。
  2) 10:30 场景必须显式 stage="NORMAL" 直调 monitor_risk：
     10:30 不在 INTRADAY_RISK_TIMES 中，真实主流程根本不经过 _risk_watch；
     若走 _risk_watch 会被误判为 INTRADAY，从而错误地禁掉均线出场。
"""
import io
import re
import sys

STRAT = r'D:/投研工作台/06-投资策略分析/策略回测/热点追踪早盘1030/热点追踪早盘10：30_v7修正版.py'

OUT = []
POS = {}
CLOSES = {}


class _Log(object):
    def info(self, m):
        OUT.append(('INFO', str(m)))

    def error(self, m):
        OUT.append(('ERROR', str(m)))

    def warning(self, m):
        OUT.append(('WARN', str(m)))

    warn = warning


def load(preset):
    src = io.open(STRAT, encoding='utf-8').read()
    src = re.sub(r'PARAM_PRESET = "[^"]*"', 'PARAM_PRESET = "%s"' % preset, src, count=1)
    NS = {'__name__': 'strategy_v7'}
    exec(compile(src, STRAT, 'exec'), NS)
    # ---- 打桩：把平台接口换成受控的假数据 ----
    NS['log'] = _Log()
    NS['positions_map'] = lambda context=None: dict(POS)
    NS['_fetch_panel'] = lambda codes, count, fields, log_tag="", quiet=False, freq="1d": {
        c: {'close': list(CLOSES.get(c, []))} for c in codes}
    NS['order_target'] = lambda code, qty: None
    NS['order'] = lambda code, qty: None
    return NS


class Ctx(object):
    pass


def run(preset, hhmm, cost, cur, closes, peak=None, entry="2026-06-05", stage=None):
    NS = load(preset)
    code = '600000.SS'
    POS.clear()
    CLOSES.clear()
    del OUT[:]
    POS[code] = {'security': code, 'current_amount': 1000,
                 'enable_amount': 1000, 'cost_price': cost}
    CLOSES[code] = closes
    ctx = Ctx()
    ctx.current_dt = '2026-06-08 10:30:00'
    ctx.peak = {code: peak} if peak else {}
    ctx.entry_date = {code: entry}
    ctx.halved = {}
    ctx.breakeven = {}
    ctx.live_held = set(POS.keys())
    ctx._risk_seen = set()
    data = {code: {'price': cur}}
    if stage is None:
        NS['_risk_watch'](ctx, data, hhmm)
    else:
        NS['monitor_risk'](ctx, data, tag='test', stage=stage)
    sells = [m for lv, m in OUT if lv == 'INFO' and ('[卖出]' in m or '[信号]' in m)]
    return sells, OUT


FAIL = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    print('  [{}] {}{}'.format('PASS' if ok else 'FAIL', name,
                               ('  | ' + detail) if detail else ''))
    if not ok:
        FAIL.append(name)


FLAT_9 = [9.0] * 25      # MA3 = 9.0
FLAT_11 = [11.0] * 25    # MA3 = 11.0

print('=' * 82)
print('场景 A｜破均线出场：现价 8.90（成本 9.18 → 浮亏 -3.1%，MA3=9.00 → 破3日线成立）')
s, _ = run('V7', '11:00', 9.18, 8.90, FLAT_9)
check('V7  @11:00 盘中时点 → 破均线被后移，不卖出', not s, str(s))
s, _ = run('V7', '14:45', 9.18, 8.90, FLAT_9)
check('V7  @14:45 结构时点 → 破3日线卖出', any('破3日线' in x for x in s), str(s))
s, _ = run('V7', '10:30', 9.18, 8.90, FLAT_9, stage="NORMAL")
check('V7  @10:30 主流程   → 破3日线卖出', any('破3日线' in x for x in s), str(s))
s, _ = run('R6', '11:00', 9.18, 8.90, FLAT_9)
check('R6  @11:00（复现v6）→ 破3日线卖出（两开关全关）', any('破3日线' in x for x in s), str(s))
s, _ = run('Z7', '11:00', 9.18, 8.90, FLAT_9)
check('Z7  @11:00（只删10:00）→ 破3日线卖出', any('破3日线' in x for x in s), str(s))
s, _ = run('S7', '11:00', 9.18, 8.90, FLAT_9)
check('S7  @11:00（只放宽止损）→ 破均线仍可用 → 卖出', any('破3日线' in x for x in s), str(s))

print()
print('=' * 82)
print('场景 B｜硬止损阈值：现价 9.35（成本 10.00 → 浮亏 -6.5%；MA3=9.00 低于现价，不触发破线）')
s, _ = run('V7', '11:00', 10.0, 9.35, FLAT_9)
check('V7  @11:00 盘中 -6.5% → 未到 -8% 线，不卖出', not s, str(s))
s, _ = run('V7', '11:00', 10.0, 9.10, FLAT_9)
check('V7  @11:00 盘中 -9.0% → 触发「止损(盘中放宽至8%)」', any('盘中放宽' in x for x in s), str(s))
s, _ = run('V7', '14:45', 10.0, 9.35, FLAT_9)
check('V7  @14:45 结构时点 -6.5% → 按 -5% 止损', any('止损' in x and '盘中放宽' not in x for x in s), str(s))
s, _ = run('R6', '11:00', 10.0, 9.35, FLAT_9)
check('R6  @11:00（复现v6）-6.5% → 按 -5% 止损（对照：v6 无放宽）',
      any('止损' in x and '盘中放宽' not in x for x in s), str(s))
s, _ = run('S7', '11:00', 10.0, 9.35, FLAT_9)
check('S7  @11:00（只放宽止损）-6.5% → 不卖出', not s, str(s))

print()
print('=' * 82)
print('场景 C｜浮盈仓位破均线（v7-4）：现价 10.70（成本 10.00 → 浮盈 +7%；MA3=11.00 → 破3日线成立）')
s, _ = run('H7', '11:00', 10.0, 10.70, FLAT_11)
check('H7  @11:00 浮盈 +7% → 破均线不动，不卖出', not s, str(s))
s, _ = run('H7', '14:45', 10.0, 10.70, FLAT_11)
check('H7  @14:45 结构时点浮盈 +7% → 同样不卖出（关键：不是靠时点，是靠浮盈上限）', not s, str(s))
s, _ = run('R6', '11:00', 10.0, 10.70, FLAT_11)
check('R6  @11:00 同场景（v6 行为）→ 破3日线卖出（证明 v7-4 是新增约束）',
      any('破3日线' in x for x in s), str(s))
s, _ = run('H7', '14:45', 10.0, 9.70, FLAT_11)
check('H7  @14:45 浮亏 -3% 破均线 → 仍卖出（限制只针对浮盈）', any('破3日线' in x for x in s), str(s))

print()
print('=' * 82)
print('场景 D｜止盈与峰值回撤在盘中时点不受影响')
s, _ = run('V7', '11:00', 10.0, 11.60, FLAT_11)
check('V7  @11:00 浮盈 +16% → 止盈清仓（不受 v7-2 影响）', any('止盈' in x and '清仓' in x for x in s), str(s))
s, _ = run('V7', '11:00', 10.0, 10.05, FLAT_9, peak=11.00)
check('V7  @11:00 峰值+10%回撤至+0.5% → 峰值回撤清仓（武装线已过）', any('峰值回撤' in x for x in s), str(s))
s, _ = run('V7', '11:00', 10.0, 9.60, FLAT_9, peak=10.20)
check('V7  @11:00 峰值仅 +2%（未达武装线）→ 峰值回撤不触发', not any('峰值回撤' in x for x in s), str(s))

print()
print('=' * 82)
print('预设参数自检')
want = {
    'V7': (False, True, True, 9.99),
    'Z7': (False, False, False, 9.99),
    'S7': (True, False, True, 9.99),
    'H7': (False, True, True, 0.01),
    'R6': (True, False, False, 9.99),
}
for p, (t10, gate, relax, bmp) in want.items():
    NS = load(p)
    times = tuple(NS['INTRADAY_RISK_TIMES'])
    ok = (('10:00' in times) == t10) and NS['INTRADAY_MA_GATE'] == gate \
        and NS['INTRADAY_STOP_RELAX'] == relax and abs(NS['BREAK_MA_MAX_PROFIT'] - bmp) < 1e-9
    check('预设 %s：10:00%s | 均线后移=%s | 止损放宽=%s | 浮盈上限=%s' % (
        p, '在列' if t10 else '已删', gate, relax, bmp), ok, ','.join(times))
ND = load('D')
check('预设 D：盘中巡检已关（v3 基线）', ND['INTRADAY_RISK_ENABLED'] is False)
NR6 = load('R6')
check('预设 R6 与 v6 对齐：MA_GATE/STOP_RELAX 全关、10:00 保留、每轮 8 时点',
      NR6['INTRADAY_MA_GATE'] is False and NR6['INTRADAY_STOP_RELAX'] is False
      and len(NR6['INTRADAY_RISK_TIMES']) == 8)

print()
print('=' * 82)
print('结果：%d 项断言，失败 %d 项' % (TOTAL[0], len(FAIL)))
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
    sys.exit(1)
print('ALL ASSERTIONS PASSED')
