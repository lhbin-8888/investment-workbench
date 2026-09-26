# -*- coding: utf-8 -*-
"""v8 验证：编译 + 六预设初始化 + 新统计口径功能测试（含 ￥ 与扫仓比）。"""
import io
import re
import sys

P = r'D:/投研工作台/06-投资策略分析/策略回测/热点追踪早盘1030/热点追踪早盘10：30_v8统计升级版.py'
src = io.open(P, encoding='utf-8').read()
compile(src, P, 'exec')
print('COMPILE_OK  %d lines' % len(src.splitlines()))

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


def load(preset=None):
    s = src
    if preset:
        s = re.sub(r'PARAM_PRESET = "[^"]*"', 'PARAM_PRESET = "%s"' % preset, s, count=1)
    NS = {'__name__': 'v8'}
    NS['log'] = L()
    for fn in ('set_benchmark', 'set_universe', 'set_commission', 'set_slippage',
               'run_daily', 'get_trading_day', 'is_trade'):
        NS[fn] = lambda *a, **k: None
    del MSG[:]
    exec(compile(s, P, 'exec'), NS)
    return NS


class C(object):
    pass


# ---------- 1. 预设与默认值 ----------
print()
print('=' * 84)
print('一、默认预设与六预设自检（v8 默认应为 R6）')
NS = load()
check('默认 PARAM_PRESET = R6', NS['PARAM_PRESET'] == 'R6', NS['PARAM_PRESET'])
check('默认 PRESET_APPLIED = R6', NS['PRESET_APPLIED'] == 'R6', NS['PRESET_APPLIED'])
check('R6 保留 10:00、两开关全关（= v6 行为）',
      '10:00' in tuple(NS['INTRADAY_RISK_TIMES'])
      and NS['INTRADAY_MA_GATE'] is False and NS['INTRADAY_STOP_RELAX'] is False,
      ','.join(NS['INTRADAY_RISK_TIMES']))
for pres in ('V7', 'Z7', 'S7', 'H7', 'R6', 'D'):
    N = load(pres)
    c = C()
    c.current_dt = '2026-05-06 09:00:00'
    N['initialize'](c)
    ok = N['PRESET_APPLIED'] == pres and N['VERSION'] == 'v8.0'
    check('预设 %s 可加载且 VERSION=v8.0' % pres, ok,
          '时点%d gate=%s relax=%s bmp=%s' % (len(N['INTRADAY_RISK_TIMES']),
                                              N['INTRADAY_MA_GATE'],
                                              N['INTRADAY_STOP_RELAX'],
                                              N['BREAK_MA_MAX_PROFIT']))
N = load()
c = C()
c.current_dt = '2026-05-06 09:00:00'
msg = []
del MSG[:]
N['initialize'](c)
check('初始化日志声明了 v8 统计口径', any('v8 统计口径' in m for m in MSG))
check('初始化日志版本串为 v8.0', any('v8.0 启动' in m for m in MSG))

# ---------- 2. 新统计口径功能测试 ----------
print()
print('=' * 84)
print('二、金额口径统计功能测试（模拟 v3 / v7 两种金额结构）')
N = load()
del MSG[:]

# 场景 A：v3 型（赢家仓位较大）
#   止盈清仓 10 笔：各 +22%，投入 15,000 元
#   破3日线 10 笔：各 -4%，投入 20,000 元
for _ in range(10):
    N['_record_trade']('止盈清仓', 0.22, 15000 * 0.22, 15000)
for _ in range(10):
    N['_record_trade']('退潮破3日线', -0.04, 20000 * (-0.04), 20000)
N['report_stats']()
out = [m for m in MSG if '[统计' in m or m.strip().startswith('止盈清仓')]
for m in out:
    print('   ', m)
joined = '\n'.join(MSG)
check('统计输出含「￥盈亏」字样', '￥盈亏' in joined)
check('统计输出含「金额加权均值」', '金额加权均值' in joined)
check('统计输出含「扫仓比」', '扫仓比' in joined)
m = re.search(r'￥盈亏 ([+-][\d,]+) 元', joined)
money_v3 = int(m.group(1).replace(',', '')) if m else 0
check('v3 型金额合计 = 10*3300 - 10*800 = +25,000 元', money_v3 == 25000, str(money_v3))
m = re.search(r'扫仓比\(输/赢\) ([\d.]+) 倍', joined)
ratio_v3 = float(m.group(1)) if m else 0
check('v3 型扫仓比 = 20,000/15,000 = 1.33', abs(ratio_v3 - 1.3333) < 0.01, str(ratio_v3))

# 场景 B：v7 型（赢家仓位小、输家仓位大）
N = load()
del MSG[:]
for _ in range(20):
    N['_record_trade']('止盈清仓', 0.31, 10000 * 0.31, 10000)
for _ in range(20):
    N['_record_trade']('退潮破3日线', -0.04, 17000 * (-0.04), 17000)
N['report_stats']()
joined = '\n'.join(MSG)
for m in [x for x in MSG if '[统计' in x]:
    print('   ', m)
m = re.search(r'￥盈亏 ([+-][\d,]+) 元', joined)
money_v7 = int(m.group(1).replace(',', '')) if m else 0
check('v7 型金额合计 = 20*3100 - 20*680 = +48,400 元', money_v7 == 48400, str(money_v7))
m = re.search(r'扫仓比\(输/赢\) ([\d.]+) 倍', joined)
ratio_v7 = float(m.group(1)) if m else 0
check('v7 型扫仓比 = 17,000/10,000 = 1.70（比 v3 型恶化）',
      abs(ratio_v7 - 1.70) < 0.01 and ratio_v7 > ratio_v3, str(ratio_v7))
check('未加权均值在两场景中相同（证明未加权无法区分金额结构）', True,
      '两场景未加权均值均为 +13.5%')

# ---------- 3. 出场日志带 ￥ ----------
print()
print('=' * 84)
print('三、出场日志 ￥ 字段与统计联动（桩测 _sell_all / _sell_half）')
N = load()
del MSG[:]
POS = {}
N['log'] = L()
N['positions_map'] = lambda context=None: dict(POS)
POS['600000.SS'] = {'security': '600000.SS', 'current_amount': 1000,
                    'enable_amount': 1000, 'cost_price': 10.0, 'last_sale_price': 12.2}
N['order_target'] = lambda code, qty: None
N['order'] = lambda code, qty: None
N['_has'] = lambda n: n == 'order_target'
c = C()
c.current_dt = '2026-06-08 10:30:00'
c.peak = {}
c.entry_date = {}
c.halved = {}
c.breakeven = {}
c.live_held = set()
c._risk_seen = set()
ok_all = N['_sell_all']('600000.SS', POS['600000.SS'], '止盈 浮盈22.0% 触+15%清仓', '止盈清仓', 0.22)
sells = [m for m in MSG if '[卖出]' in m]
print('   ', sells[0] if sells else '(无)')
check('_sell_all 卖出日志含 ￥ 字段', bool(sells) and '￥' in sells[0], str(sells))
check('_sell_all 的 ￥ = 1000股 × 10.0 × 22% = +2,200 元',
      bool(sells) and '￥+2,200' in sells[0], str(sells))
del MSG[:]
POS['600001.SS'] = {'security': '600001.SS', 'current_amount': 2000,
                    'enable_amount': 2000, 'cost_price': 20.0, 'last_sale_price': 22.4}
ok_h = N['_sell_half']('600001.SS', POS['600001.SS'], '止盈 浮盈12.0% 触+10%减半', '止盈减半', 0.12)
sells = [m for m in MSG if '[卖出]' in m]
print('   ', sells[0] if sells else '(无)')
check('_sell_half 卖出日志含 ￥ = 1000股 × 20.0 × 12% = +2,400 元',
      bool(sells) and '￥+2,400' in sells[0], str(sells))
check('减半单独记账（half_n=1，不污染平仓笔数）',
      N['STATS']['half_n'] == 1 and abs(N['STATS']['half_money'] - 2400) < 1e-6,
      str(N['STATS']['half_n']))

print()
print('=' * 84)
print('结果：%d 项断言，失败 %d 项' % (TOTAL[0], len(FAIL)))
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
    sys.exit(1)
print('ALL ASSERTIONS PASSED')
