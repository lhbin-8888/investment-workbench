# -*- coding: utf-8 -*-
"""v8.1 验证：① 金额口径 bug 的「复现 + 修复」双向铁证
              ② E6 / P6 / EP6 新预设参数自检
              ③ 端到端金额加权 / 扫仓比

关键：本脚本的 mock **必须复现引擎真实副作用** ——
      PTrade 回测中 order_target(code, 0) 返回时持仓即被清零。
      v8 的 verify 把 order_target 写成了空函数，因此「假绿」通过，
      真机上金额字段全为 0。本脚本用 order_clears=True/False 双向对照。
"""
import io
import re
import sys

D = r'D:/投研工作台/06-投资策略分析/策略回测/热点追踪早盘1030/'
P80 = D + '热点追踪早盘10：30_v8统计升级版.py'
P81 = D + '热点追踪早盘10：30_v8.1统计升级版.py'

SRC = {}
for tag, path in (('v8.0', P80), ('v8.1', P81)):
    SRC[tag] = io.open(path, encoding='utf-8').read()
    compile(SRC[tag], path, 'exec')
    print('COMPILE_OK  %-5s  %d lines' % (tag, len(SRC[tag].splitlines())))

FAIL = []
TOTAL = [0]


def check(name, ok, detail=''):
    TOTAL[0] += 1
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  | ' + detail) if detail else ''))
    if not ok:
        FAIL.append(name)


MSG = []


class L(object):
    def info(self, m):
        MSG.append(str(m))

    def error(self, m):
        MSG.append('ERR ' + str(m))

    def warning(self, m):
        MSG.append(str(m))

    warn = warning


class C(object):
    pass


def load(tag, preset=None):
    s = SRC[tag]
    if preset:
        s = re.sub(r'PARAM_PRESET = "[^"]*"', 'PARAM_PRESET = "%s"' % preset, s, count=1)
    NS = {'__name__': 'x'}
    NS['log'] = L()
    for fn in ('set_benchmark', 'set_universe', 'set_commission', 'set_slippage',
               'run_daily', 'get_trading_day', 'is_trade'):
        NS[fn] = lambda *a, **k: None
    del MSG[:]
    exec(compile(s, '<%s>' % tag, 'exec'), NS)
    return NS


def run_sell_all(tag, cost, enable, rt, order_clears):
    """跑一笔 _sell_all，返回 (日志行, ￥值, notional)。

    order_clears=True 复现真机：order_target 返回后持仓被清零（cost→0、enable→0）。
    """
    NS = load(tag)
    del MSG[:]
    code = '600000.SS'
    POS = {code: {'security': code, 'current_amount': enable,
                  'enable_amount': enable, 'cost_price': cost,
                  'last_sale_price': cost * (1 + rt)}}

    def _ot(c, q):
        if order_clears and q == 0:
            POS[c]['cost_price'] = 0.0
            POS[c]['enable_amount'] = 0
            POS[c]['current_amount'] = 0
        return None

    NS['order_target'] = _ot
    NS['order'] = lambda c, q: None
    NS['_has'] = lambda n: n == 'order_target'
    NS['_sell_all'](code, POS[code], '测试原因', '止盈清仓', rt)
    lines = [m for m in MSG if '[卖出]' in m]
    line = lines[0] if lines else ''
    m = re.search(r'￥([+-][\d,]+)', line)
    money = int(m.group(1).replace(',', '')) if m else None
    return line, money, enable * cost


# ══════════════════════════════════════════════════════════
print()
print('=' * 88)
print('一、金额口径 bug：复现 + 修复（双向对照）')
print('=' * 88)
print()
print('  mock 语义：')
print('    order_clears=True  → 复现 PTrade 真机（order_target 返回即清零持仓）')
print('    order_clears=False → v8 旧测试用的空函数（不清零）')
print()

CASES = [
    # (tag,    cost, enable, rt,    clears, 期望￥,  说明)
    ('v8.0', 10.0, 1000, 0.22, True, 0, 'v8.0 真机语义 → 应复现 bug（￥=0）'),
    ('v8.1', 10.0, 1000, 0.22, True, 2200, 'v8.1 真机语义 → 应修复（￥=+2,200）'),
    ('v8.0', 10.0, 1000, 0.22, False, 2200, 'v8.0 空函数语义 → 当日测试为何假绿'),
    ('v8.1', 10.0, 1000, 0.22, False, 2200, 'v8.1 空函数语义 → 仍正确'),
    ('v8.1', 20.0, 2000, -0.04, True, -1600, 'v8.1 亏损单 → ￥=-1,600（=2000×20×-4%）'),
]
for tag, cost, enable, rt, clears, want, desc in CASES:
    line, money, nt = run_sell_all(tag, cost, enable, rt, clears)
    print('    %-5s clears=%-5s → %s' % (tag, clears, line if line else '(无日志)'))
    check(desc, money == want, '￥=%s 期望 %s' % (money, want))
print()
line0, money0, _ = run_sell_all('v8.0', 10.0, 1000, 0.22, True)
line1, money1, _ = run_sell_all('v8.1', 10.0, 1000, 0.22, True)
check('铁证：同一 mock 下 v8.0 归零、v8.1 正确 ⇒ bug 在位、修复有效',
      money0 == 0 and money1 == 2200, 'v8.0=%s  v8.1=%s' % (money0, money1))

# ══════════════════════════════════════════════════════════
print()
print('=' * 88)
print('二、E6 / P6 / EP6 预设自检（v8.1 新增）')
print('=' * 88)
NSr = load('v8.1', 'R6')
NSe = load('v8.1', 'E6')
NSp = load('v8.1', 'P6')
NSe2 = load('v8.1', 'EP6')

check('默认预设仍为 R6（标定样本）', load('v8.1')['PARAM_PRESET'] == 'R6')
check('v8.1 版本号', load('v8.1')['VERSION'] == 'v8.1', load('v8.1')['VERSION'])

check('E6 入场入口 = v3（量比1.2 / 额3e8 / 池40）',
      NSe['MIN_VOL_RATIO'] == 1.2 and NSe['MIN_AMOUNT'] == 3e8 and NSe['DETAIL_POOL'] == 40,
      '量比%s 额%s 池%s' % (NSe['MIN_VOL_RATIO'], NSe['MIN_AMOUNT'], NSe['DETAIL_POOL']))
check('P6 仓位组 = v3（上限5 / 0.18 / 0.30）',
      NSp['MAX_POSITIONS'] == 5 and NSp['POSITION_VALUE_RATIO'] == 0.18
      and NSp['MAX_SINGLE_RATIO'] == 0.30,
      '上限%s %s %s' % (NSp['MAX_POSITIONS'], NSp['POSITION_VALUE_RATIO'], NSp['MAX_SINGLE_RATIO']))
check('EP6 = E6 + P6 两组同时回退',
      NSe2['MIN_VOL_RATIO'] == 1.2 and NSe2['MIN_AMOUNT'] == 3e8 and NSe2['DETAIL_POOL'] == 40
      and NSe2['MAX_POSITIONS'] == 5 and NSe2['POSITION_VALUE_RATIO'] == 0.18
      and NSe2['MAX_SINGLE_RATIO'] == 0.30)

# 与 R6 逐键对比：只允许目标键不同
KEYS_E = ('MIN_VOL_RATIO', 'MIN_AMOUNT', 'DETAIL_POOL')
KEYS_P = ('MAX_POSITIONS', 'POSITION_VALUE_RATIO', 'MAX_SINGLE_RATIO')


def diff_keys(a, b, keys_all):
    return sorted(k for k in keys_all if a[k] != b[k])


ALL_KEYS = sorted(set(NSr['_PRESETS']['R6'].keys()))
check('E6 与 R6 仅 3 个入场键不同',
      diff_keys(NSr, NSe, ALL_KEYS) == sorted(KEYS_E),
      str(diff_keys(NSr, NSe, ALL_KEYS)))
check('P6 与 R6 仅 3 个仓位键不同',
      diff_keys(NSr, NSp, ALL_KEYS) == sorted(KEYS_P),
      str(diff_keys(NSr, NSp, ALL_KEYS)))
check('EP6 与 R6 仅上述 6 键不同',
      diff_keys(NSr, NSe2, ALL_KEYS) == sorted(KEYS_E + KEYS_P),
      str(diff_keys(NSr, NSe2, ALL_KEYS)))

# 出场行为必须与 R6 完全一致（本次不改出场）
check('E6 出场行为与 R6 一致（10:00 保留、两开关全关）',
      tuple(NSe['INTRADAY_RISK_TIMES']) == tuple(NSr['INTRADAY_RISK_TIMES'])
      and NSe['INTRADAY_MA_GATE'] is False and NSe['INTRADAY_STOP_RELAX'] is False)
check('EP6 出场行为与 R6 一致', NSe2['INTRADAY_MA_GATE'] is False
      and NSe2['INTRADAY_STOP_RELAX'] is False
      and '10:00' in tuple(NSe2['INTRADAY_RISK_TIMES']))

# 九预设均可 initialize
print()
for pres in ('V7', 'Z7', 'S7', 'H7', 'R6', 'D', 'E6', 'P6', 'EP6'):
    N = load('v8.1', pres)
    c = C()
    c.current_dt = '2026-05-06 09:00:00'
    del MSG[:]
    N['initialize'](c)
    check('预设 %s initialize 通过' % pres, N['PRESET_APPLIED'] == pres,
          '上限%s 量比%s 额%s 池%s' % (N['MAX_POSITIONS'], N['MIN_VOL_RATIO'],
                                      N['MIN_AMOUNT'], N['DETAIL_POOL']))

N = load('v8.1', 'EP6')
c = C()
c.current_dt = '2026-05-06 09:00:00'
del MSG[:]
N['initialize'](c)
check('EP6 初始化日志打印「回退项」',
      any('本预设相对 R6 的回退项' in m for m in MSG),
      [m for m in MSG if '回退项' in m][0] if any('回退项' in m for m in MSG) else '')
check('初始化日志声明 v8.1 口径', any('v8.1 统计口径' in m for m in MSG))

# ══════════════════════════════════════════════════════════
print()
print('=' * 88)
print('三、端到端：真机语义下金额加权 / 扫仓比')
print('=' * 88)
NS = load('v8.1')
del MSG[:]
codes = ['600001.SS', '600002.SS', '600003.SS',
         '600004.SS', '600005.SS', '600006.SS']
POS = {}
for i, cd in enumerate(codes):
    if i < 3:      # 三笔止盈：notional 15,000，收益 +22%
        POS[cd] = {'security': cd, 'current_amount': 1000, 'enable_amount': 1000,
                   'cost_price': 15.0}
        rt = 0.22
    else:          # 三笔破3日线：notional 20,000，收益 -4%
        POS[cd] = {'security': cd, 'current_amount': 1000, 'enable_amount': 1000,
                   'cost_price': 20.0}
        rt = -0.04
    POS[cd]['_rt'] = rt


def _ot(c, q):
    if q == 0:
        POS[c]['cost_price'] = 0.0
        POS[c]['enable_amount'] = 0
        POS[c]['current_amount'] = 0
    return None


NS['order_target'] = _ot
NS['order'] = lambda c, q: None
NS['_has'] = lambda n: n == 'order_target'
for cd in codes:
    rk = '止盈清仓' if POS[cd]['_rt'] > 0 else '退潮破3日线'
    NS['_sell_all'](cd, POS[cd], '端到端', rk, POS[cd]['_rt'])

NS['report_stats']()
for m in MSG:
    if '[统计' in m or m.strip().startswith(('止盈清仓', '退潮破3日线')):
        print('   ', m)
joined = '\n'.join(MSG)
m = re.search(r'￥盈亏 ([+-][\d,]+) 元', joined)
money = int(m.group(1).replace(',', '')) if m else None
check('真机语义下端到端 ￥ = 3×3,300 - 3×800 = +7,500 元', money == 7500, str(money))
m = re.search(r'累计投入 ([\d,]+) 元', joined)
ntot = int(m.group(1).replace(',', '')) if m else None
check('累计投入 = 3×15,000 + 3×20,000 = 105,000 元', ntot == 105000, str(ntot))
m = re.search(r'扫仓比\(输/赢\) ([\d.]+) 倍', joined)
ratio = float(m.group(1)) if m else None
check('扫仓比 = 20,000/15,000 = 1.33 倍', ratio is not None and abs(ratio - 1.3333) < 0.01, str(ratio))
m = re.search(r'金额加权均值 ([+-][\d.]+)%', joined)
wavg = float(m.group(1)) if m else None
check('金额加权均值 = 7,500/105,000 = +7.14%',
      wavg is not None and abs(wavg - 7.14) < 0.05, str(wavg))

print()
print('=' * 88)
print('结果：%d 项断言，失败 %d 项' % (TOTAL[0], len(FAIL)))
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
    sys.exit(1)
print('ALL ASSERTIONS PASSED')
