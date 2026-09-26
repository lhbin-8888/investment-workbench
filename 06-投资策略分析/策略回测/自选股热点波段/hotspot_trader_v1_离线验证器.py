# -*- coding: utf-8 -*-
"""
hotspot_trader_v1_离线验证器.py
=====================================================================
离线自检：在本地用"假 PTrade 平台"跑 hotspot_trader_v1_ptrade.py，
验证选股/剔除/出场逻辑是否正确，不依赖券商、不联网。

v1.3 起 mock 严格贴合《山西证券API文档》实测口径：
  - get_history(is_dict=True) 返回 {代码: 2D数组[(开,高,低,收,量,...),...]}（列序=所请字段）
  - get_fundamentals(security, table, fields) 返回多列 DataFrame（columns + 单列 .iloc）
    valuation 表：流通字段=股；turnover=ratio(0.05=5%)
  - get_snapshot 返回 last_px / circulation_amount(股) / turnover_ratio(ratio)
  - run_daily 回调只收 context（无 data）；_cur_price 走 get_history(include=True) 兜底

运行：python hotspot_trader_v1_离线验证器.py
"""
import importlib.util
import types
import datetime

NOW = datetime.datetime(2026, 9, 23)
OLD_DATE = datetime.datetime(2010, 1, 1)
NEW_DATE = NOW - datetime.timedelta(days=10)

GOOD = '600519'   # 贵州茅台
LIMIT = '000725'  # 京东方A（测涨停）
TURN = '000063'   # 中兴通讯（测高换手）
ST = '000333'     # 美的集团（名称打 ST）
NEW = '000338'    # 潍柴动力（测次新）
FLAT = '601398'   # 工商银行（测均线不达标）
IDX = '000300'    # 沪深300（市场关口）

VOL_BASE = 1_000_000

PROFILES = {
    GOOD:  dict(base=100.0, drift=0.010, float=1_000_000_000, name='贵州茅台', list_date=OLD_DATE, bars=60, turnover_ratio=0.05),
    LIMIT: dict(base=100.0, drift=0.010, float=1_000_000_000, name='京东方A', list_date=OLD_DATE, bars=60,
                limit_last=True, limit_pct=0.10, turnover_ratio=0.05),
    TURN:  dict(base=100.0, drift=0.010, float=VOL_BASE * 5, name='中兴通讯', list_date=OLD_DATE, bars=60, turnover_ratio=0.35),
    ST:    dict(base=100.0, drift=0.010, float=1_000_000_000, name='ST美的测试', list_date=OLD_DATE, bars=60, turnover_ratio=0.05),
    NEW:   dict(base=100.0, drift=0.010, float=1_000_000_000, name='潍柴动力', list_date=NEW_DATE, bars=60, turnover_ratio=0.05),
    FLAT:  dict(base=100.0, drift=0.000, float=1_000_000_000, name='工商银行', list_date=OLD_DATE, bars=60, turnover_ratio=0.05),
    IDX:   dict(base=3000.0, drift=0.003, float=1_000_000_000, name='沪深300', list_date=OLD_DATE, bars=60, turnover_ratio=0.05),
}


def gen_series(prof):
    n = prof.get('bars', 60)
    base = prof['base']
    drift = prof['drift']
    closes, opens, highs, lows, vols, precs = [], [], [], [], [], []
    px = base
    for i in range(n):
        px = px * (1 + drift)
        closes.append(px)
        opens.append(px * (1 - 0.003))
        highs.append(px * (1 + 0.012))
        lows.append(px * (1 - 0.012))
        precs.append(closes[i - 1] if i > 0 else px)
    for _ in range(n):
        vols.append(VOL_BASE)
    vols[-2] = int(VOL_BASE * 1.3)
    vols[-1] = int(VOL_BASE * 1.3 * 1.3)
    if prof.get('limit_last'):
        lim = prof.get('limit_pct', 0.10)
        closes[-1] = closes[-2] * (1 + lim)
        highs[-1] = closes[-1]
        precs[-1] = closes[-2]
    return {'open': opens, 'high': highs, 'low': lows,
            'close': closes, 'volume': vols, 'preclose': precs}


class _Col(object):
    def __init__(self, val):
        self._val = val

    @property
    def iloc(self):
        return _Iloc(self._val)


class _Iloc(object):
    def __init__(self, val):
        self._val = val

    def __getitem__(self, i):
        return self._val


class FakeValDF(object):
    """模拟 get_fundamentals 多列 DataFrame：columns + 单列 .iloc。"""
    def __init__(self, cols, vals):
        self.columns = list(cols)
        self._vals = vals
        self.iloc = None  # 仅用于 hasattr 命中 DataFrame 分支

    def __getitem__(self, k):
        return _Col(self._vals[k])


CACHE = {}


def _series(code6):
    if code6 not in CACHE:
        CACHE[code6] = gen_series(PROFILES[code6])
    return CACHE[code6]


# ----------------------- mock 平台 API -----------------------
def mock_get_history(count, freq, fields, secs, **kw):
    """is_dict=True 形态：{代码: 2D数组[(开,高,低,收,量,...),...]}，列序=所请字段。"""
    if isinstance(fields, str):
        fields = [fields]
    out = {}
    for s in secs:
        code6 = s.split('.')[0]
        if code6 not in PROFILES:
            continue
        full = _series(code6)
        rows = []
        for i in range(max(0, len(full['close']) - count), len(full['close'])):
            rows.append([full[f][i] for f in fields])
        out[s] = rows
    return out


def mock_get_positions(*a, **k):
    return []


def mock_get_snapshot(secs, *a, **k):
    out = {}
    for s in secs:
        code6 = s.split('.')[0]
        if code6 not in PROFILES:
            continue
        full = _series(code6)
        out[s] = {'last_px': full['close'][-1],
                  'circulation_amount': PROFILES[code6]['float'],
                  'turnover_ratio': PROFILES[code6].get('turnover_ratio', 0.05)}
    return out


VAL_FIELDS = {
    'a_floats': lambda p: p['float'],
    'float_a_shares': lambda p: p['float'],
    'circulation_amount': lambda p: p['float'],
    'float_shares': lambda p: p['float'],
    'circulating_shares': lambda p: p['float'],
    'free_shares': lambda p: p['float'],
    'free_float_shares': lambda p: p['float'],
    # 实测真机 turnover_rate 已是百分比(4.2310=4.23%)，mock 同步按百分比口径
    'turnover_rate': lambda p: p['turnover_ratio'] * 100,
    'turnover_ratio': lambda p: p['turnover_ratio'] * 100,
    'turnover': lambda p: p['turnover_ratio'] * 100,
}


def mock_get_fundamentals(sec_list, table, fields=None, *a, **k):
    s = sec_list[0]
    code6 = s.split('.')[0]
    p = PROFILES.get(code6)
    if not p:
        return None
    if fields is None:
        req = list(VAL_FIELDS.keys())
    elif isinstance(fields, (list, tuple)) and fields:
        req = list(fields)
    elif isinstance(fields, str):
        req = [fields]
    else:
        req = ['a_floats']
    cols = {}
    for f in req:
        fn = VAL_FIELDS.get(f)
        if fn:
            cols[f] = fn(p)
    if not cols:
        return None
    return FakeValDF(list(cols.keys()), cols)


def mock_get_trading_day(n=1, *a, **k):
    d = NOW + datetime.timedelta(days=n)
    return d.strftime('%Y%m%d')


class _SecInfo(object):
    def __init__(self, name, list_date):
        self.name = name
        self.list_date = list_date


def mock_get_security_info(suffix, *a, **k):
    code6 = suffix.split('.')[0]
    p = PROFILES.get(code6)
    if not p:
        return None
    return _SecInfo(p.get('name', '正常'), p.get('list_date', OLD_DATE))


ORDERS = []


def mock_order(code, sh, *a, **k):
    ORDERS.append(('sell', code, sh))


def mock_order_target_value(suffix, value, *a, **k):
    ORDERS.append(('buy', suffix, value))


DAILY = {}


def mock_run_daily(ctx, fn, t='9:31', *a, **k):
    DAILY[t] = fn


class _Log(object):
    """记录【预格式化后】的日志（策略的 _Log 兼容层已替平台做 % 格式化）。"""
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(('INFO', msg))

    def warning(self, msg, *a, **k):
        self.lines.append(('WARN', msg))

    def error(self, msg, *a, **k):
        self.lines.append(('ERR', msg))

    def debug(self, msg, *a, **k):
        self.lines.append(('DEBUG', msg))

    def critical(self, msg, *a, **k):
        self.lines.append(('CRIT', msg))


# ----------------------- 加载策略并注入 -----------------------
SPEC = importlib.util.spec_from_file_location(
    'hotspot_trader_v1_ptrade', 'D:/投研工作台/06-投资策略分析/策略回测/hotspot_trader_v1_ptrade.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

mod.get_history = mock_get_history
mod.get_positions = mock_get_positions
mod.get_snapshot = mock_get_snapshot
mod.get_fundamentals = mock_get_fundamentals
mod.get_security_info = mock_get_security_info
mod.order = mock_order
mod.order_target_value = mock_order_target_value
mod.run_daily = mock_run_daily
mod.get_trading_day = mock_get_trading_day
mod.__ptrade_log__ = _Log()

mod.WATCHLIST = [GOOD, LIMIT, TURN, ST, NEW, FLAT]
mod.INDUSTRY_MAP = {c: '测试' for c in mod.WATCHLIST}
mod.MOMENTUM_FALLBACK = False
mod.HOT_SECTORS = []
mod.TRADE_ENABLED = False  # 信号模式

# ----------------------- 运行 -----------------------
ctx = types.SimpleNamespace()
ctx.portfolio = types.SimpleNamespace(portfolio_value=1_000_000, cash=1_000_000, positions_value=0)
ctx.blotter = types.SimpleNamespace(current_dt=NOW)
ctx.day_sector_buy = {}
ctx.hold_state = {}
ctx.candidates = []
ctx.buys_today = 0

mod.initialize(ctx)
mod.before_trading_start(ctx, {})  # run_daily 只传 context；此处显式传 {} 兼容

cands = set(ctx.candidates)

# ----------------------- 断言 -----------------------
checks = []
checks.append(('达标股进入候选', GOOD in cands))
checks.append(('涨停股被剔除', LIMIT not in cands))
checks.append(('高换手股被剔除', TURN not in cands))
checks.append(('ST股被剔除', ST not in cands))
checks.append(('次新股被剔除', NEW not in cands))
checks.append(('均线不达标被剔除', FLAT not in cands))

probe_ok = any('probe' in m and '可取' in m for _, m in mod.__ptrade_log__.lines)
cols_ok = any('valuation 实际列' in m for _, m in mod.__ptrade_log__.lines)

mod._buy(ctx, {})
buy_signal = any('应买入' in m and GOOD + '.SS' in m for _, m in mod.__ptrade_log__.lines)

# 回测现价兜底（run_daily 无 data）：_cur_price 经 get_history(include=True) 取到价
price = mod._cur_price(GOOD + '.SS', None)
price_ok = price > 0

print('=' * 60)
print('候选名单: %s' % sorted(cands))
print('-' * 60)
for name, ok in checks:
    print('  [%s] %s' % ('PASS' if ok else 'FAIL', name))
print('-' * 60)
print('  [%s] 启动探针流通股本可取' % ('PASS' if probe_ok else 'FAIL'))
print('  [%s] 探针打印 valuation 实际列名' % ('PASS' if cols_ok else 'FAIL'))
print('  [%s] 信号模式产出买入信号' % ('PASS' if buy_signal else 'FAIL'))
print('  [%s] run_daily无data时 _cur_price 兜底取价(=%.2f)' % ('PASS' if price_ok else 'FAIL', price))
print('-' * 60)
print('探针/列名日志:')
for lv, m in mod.__ptrade_log__.lines:
    if 'probe' in m or 'valuation 实际列' in m:
        print('    %s %s' % (lv, m))
print('剔除原因日志:')
for lv, m in mod.__ptrade_log__.lines:
    if lv in ('WARN', 'ERR') and ('[turn]' in m or '[st]' in m or '[new]' in m or '[limit]' in m or '[acct]' in m or '[pos]' in m):
        print('    %s %s' % (lv, m))
all_ok = all(ok for _, ok in checks) and probe_ok and cols_ok and buy_signal and price_ok
print('=' * 60)
print('总判定: %s' % ('ALL PASS' if all_ok else 'HAS FAIL'))
