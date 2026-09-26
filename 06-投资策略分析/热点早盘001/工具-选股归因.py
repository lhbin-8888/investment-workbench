# -*- coding: utf-8 -*-
"""
热点早盘系列 —— 选股质量归因工具（可复用）

解决的问题：
    回测收益不好时，到底是「选股选得差」还是「出场砍得早」？
    本工具把两者剥离：不按策略的买卖信号算，而是用真实行情重算
    「买入后如果什么都不做、持有 N 天」的收益，再与同期基准对照。

用法：
    1. 跑完回测，把日志存为纯文本（如 xxx回测.txt）
    2. 修改下方 CONFIG 的 LOG 和 Base 日期区间
    3. python 工具-选股归因.py

输出：
    ① 逐笔明细（买入日 / 持有期收益 / 实际路径收益）
    ② 策略 vs 基准 的超额（持有 3/5/10 日）
    ③ 主线分组、阶段分组
    ④ 入场后首日表现（验证入场价口径是否被高估）

依赖：仅标准库（urllib + json），无需 requests。
行情源：腾讯财经前复权日线，走 HTTPS 直连。
"""
import re, json, os, ssl, urllib.request, statistics as st

# ============ CONFIG ============
LOG = r"D:\投研工作台\10-策略回测\热点早盘001\001优化方案回测.txt"
OUT_DIR = r"D:\投研工作台\archive\temp_attrib"     # 明细落地目录（可改）
K_START = '2026-04-20'      # 行情起点（比首个买入日提前约 15 天）
K_END = '2026-08-01'        # 行情终点（比末个买入日延后 +10 个交易日，够算持有10日）
PERIOD_END = '2026-06-30'   # 回测区间末交易日
BENCH = {'沪深300': '000300', '中证1000': '000852', '创业板指': '399006'}
HOLD_DAYS = (3, 5, 10)
UA = {'User-Agent': 'Mozilla/5.0'}
# ================================

BUY_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - INFO - \[买入\] (\d{6}) \[([^\]]+)\] '
    r'假设价([\d.]+).*?目标(\d+)')
SELL_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - INFO - \[卖出\] (\d{6}) (\d+) 股 原因:(.*?)(?: 委托=|$)')


def parse_log(path):
    buys, sells = [], []
    for line in open(path, encoding='utf-8', errors='ignore'):
        line = line.rstrip('\n')
        m = BUY_RE.match(line)
        if m:
            buys.append({'date': m.group(1), 'code': m.group(2), 'tag': m.group(3),
                         'assumed': float(m.group(4)), 'target': float(m.group(5))})
            continue
        m = SELL_RE.match(line)
        if m:
            sells.append({'date': m.group(1), 'code': m.group(2),
                          'shares': int(m.group(3)), 'reason': m.group(4).strip()})
    return buys, sells


_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_cache = {}


def get_kline(code):
    """返回 [{'d','o','c'}]，失败返回 []"""
    if code in _cache:
        return _cache[code]
    tx = ('sh' if code.startswith(('6', '9')) else 'sz') + code
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={tx},day,{K_START},{K_END},320,qfq")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25, context=_ctx) as r:
            js = json.loads(r.read().decode('utf-8'))
        nd = js['data'][tx]
        kl = nd.get('qfqday') or nd.get('day') or []
        _cache[code] = [{'d': x[0], 'o': float(x[1]), 'c': float(x[2])} for x in kl]
    except Exception as e:
        print(f"  [行情失败] {code}: {e}")
        _cache[code] = []
    return _cache[code]


def idx_after(kl, date):
    """第一个 >= date 的下标"""
    return next((i for i, x in enumerate(kl) if x['d'] >= date), None)


def build_rows(buys, sells):
    rows = []
    for b in buys:
        kl = get_kline(b['code'])
        ib = idx_after(kl, b['date'])
        if ib is None:
            continue
        p0, op = b['assumed'], kl[ib]['o']
        rec = dict(b, entry_open=op, kl=kl)
        for n in HOLD_DAYS:
            rec[f'r{n}'] = (kl[ib + n]['c'] - p0) / p0 if ib + n < len(kl) else None
            rec[f'r{n}o'] = (kl[ib + n]['c'] - op) / op if ib + n < len(kl) else None
        rec['d1_r'] = (kl[ib]['c'] - p0) / p0
        rec['d1_gap_open'] = (op - p0) / p0
        my = sorted([s for s in sells if s['code'] == b['code'] and s['date'] > b['date']],
                    key=lambda s: s['date'])
        if my:
            sd, reason = my[0]['date'], my[0]['reason'][:22]
        else:
            sd, reason = PERIOD_END, '区间末仍持有'
        isl = idx_after(kl, sd)
        if isl is None or isl >= len(kl):
            isl = len(kl) - 1
        rec.update(exit_date=sd if my else f'{sd}(未平)', reason=reason,
                   held_days=isl - ib, exit_close=kl[isl]['c'],
                   r_actual=(kl[isl]['c'] - p0) / p0,
                   r_actual_o=(kl[isl]['c'] - op) / op)
        for name, code in BENCH.items():
            pass
        rows.append(rec)
    return rows


def bench_ret(rows, bench_code):
    kb = get_kline(bench_code)

    def ret(d0, d1):
        i0, i1 = idx_after(kb, d0), idx_after(kb, d1)
        return (kb[i1]['c'] - kb[i0]['c']) / kb[i0]['c'] if i0 is not None and i1 is not None else None

    for r in rows:
        kl, ib = r['kl'], None
        ib = idx_after(kl, r['date'])
        for n in HOLD_DAYS:
            j = min(ib + n, len(kl) - 1)
            r[f'b{n}_{bench_code}'] = ret(r['date'], kl[j]['d'])
        r[f'bact_{bench_code}'] = ret(r['date'], r['exit_date'].replace('(未平)', ''))
    return rows


def wavg(rows, key):
    vals = [(r[key], r['target']) for r in rows if r.get(key) is not None]
    if not vals:
        return None, 0
    tw = sum(w for _, w in vals)
    return sum(v * w for v, w in vals) / tw, len(vals)


def report(rows, title):
    print('\n' + '=' * 92)
    print(title)
    print('=' * 92)
    print(f"{'代码':<8}{'主线/阶段':<18}{'买入日':<12}{'退出日':<16}{'持有':>4}{'实际':>8}{'3日':>8}{'5日':>8}{'10日':>8}")
    print('-' * 92)
    for r in rows:
        print(f"{r['code']:<8}{r['tag'][:16]:<18}{r['date']:<12}{r['exit_date']:<16}"
              f"{r['held_days']:>4}{r['r_actual']*100:>7.1f}%"
              + ''.join(f"{(r.get(f'r{n}') or 0)*100:>7.1f}%" for n in HOLD_DAYS))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    buys, sells = parse_log(LOG)
    print(f"解析完成：买入 {len(buys)} 笔 / 卖出 {len(sells)} 单")

    rows = build_rows(buys, sells)
    for code in BENCH.values():
        get_kline(code)
    for code in BENCH.values():
        bench_ret(rows, code)

    report(rows, f"逐笔明细（n={len(rows)}）")

    print('\n' + '=' * 92)
    print('口径汇总（加权 = 按目标金额加权）')
    print('=' * 92)

    def line(key, label):
        v, n = wavg(rows, key)
        if v is None:
            return None
        a = [r[key] for r in rows if r.get(key) is not None]
        win = len([x for x in a if x > 0]) / len(a) * 100
        pl = [x for x in a if x > 0]
        ls = [x for x in a if x <= 0]
        plr = (sum(pl) / len(pl)) / abs(sum(ls) / len(ls)) if pl and ls else 0
        print(f"{label:<26} n={n:<3} 加权{v*100:>7.2f}%  等权{st.mean(a)*100:>7.2f}%  "
              f"中位{st.median(a)*100:>7.2f}%  胜率{win:>5.1f}%  盈亏比{plr:>5.2f}")
        return v

    act = line('r_actual', '策略实际路径')
    for n in HOLD_DAYS:
        line(f'r{n}', f'固定持有 {n} 日')

    bname, bcode = list(BENCH.items())[1]
    print()
    ba = line(f'bact_{bcode}', f'[基准]{bname} 同期')
    b3 = line(f'b3_{bcode}', f'[基准]{bname} 3日')
    b5 = line(f'b5_{bcode}', f'[基准]{bname} 5日')

    if None not in (act, ba, b3, b5):
        r3, _ = wavg(rows, 'r3')
        r5, _ = wavg(rows, 'r5')
        print('\n' + '=' * 92)
        print('超额收益（策略 − 基准）')
        print('=' * 92)
        print(f"  持有 3 日     {r3*100:>6.2f}% − {b3*100:>6.2f}% = {(r3-b3)*100:>6.2f} pp")
        print(f"  持有 5 日     {r5*100:>6.2f}% − {b5*100:>6.2f}% = {(r5-b5)*100:>6.2f} pp")
        print(f"  策略实际路径   {act*100:>6.2f}% − {ba*100:>6.2f}% = {(act-ba)*100:>6.2f} pp")
        print(f"\n  --> 出场规则影响 = {(act-max(r3, r5))*100:>6.2f} pp（相对较优的固定持有期）")

    o, _ = wavg(rows, 'r_actual_o')
    g = st.mean([r['d1_gap_open'] for r in rows])
    low = len([r for r in rows if r['d1_gap_open'] < 0]) / len(rows) * 100
    print('\n' + '=' * 92)
    print('入场价口径对照（假设价=昨收×1.01  vs  T日开盘价）')
    print('=' * 92)
    print(f"  策略实际路径：假设价{act*100:>6.2f}%  开盘价{o*100:>6.2f}%  差 {(o-act)*100:>5.2f} pp")
    print(f"  入场日开盘 vs 买入价：均值{g*100:>6.2f}%   低开占比 {low:>4.0f}%")

    def group(title, keyfn):
        print('\n' + '=' * 92)
        print(title)
        print('=' * 92)
        bk = {}
        for r in rows:
            bk.setdefault(keyfn(r), []).append(r)
        print(f"{'分组':<16}{'n':>3}{'均值':>9}{'中位':>9}{'胜率':>8}")
        stat = []
        for k, vs in bk.items():
            a = [v['r_actual'] for v in vs]
            stat.append((st.mean(a), k, len(vs), st.median(a),
                         len([x for x in a if x > 0]) / len(a) * 100))
        for m, k, n, med, w in sorted(stat, reverse=True):
            flag = '  <== 关注' if n >= 4 and m < 0.01 else ''
            print(f"{str(k):<16}{n:>3}{m*100:>8.1f}%{med*100:>8.1f}%{w:>7.0f}%{flag}")

    group('主线分组（n>=4 且均值<1% 需要重点审查）',
          lambda r: r['tag'].split('|')[0] if '|' in r['tag'] else '?')
    group('阶段分组', lambda r: r['tag'].split('|')[-1] if '|' in r['tag'] else '?')

    a = sorted([r['r_actual'] for r in rows], reverse=True)
    print('\n' + '=' * 92)
    print('收益集中度')
    print('=' * 92)
    print(f"  Top5: {[f'{x*100:.1f}%' for x in a[:5]]}")
    print(f"  Bot5: {[f'{x*100:.1f}%' for x in a[-5:]]}")
    print(f"  前 3 笔合计 {sum(a[:3])*100:>6.1f} pp，其余 {len(a)-3} 笔合计 {sum(a[3:])*100:>6.1f} pp")
    print(f"  剔除首尾各 3 笔后均值 {st.mean(a[3:-3])*100:>6.2f}%")

    out = os.path.join(OUT_DIR, 'attrib_detail.json')
    json.dump([{k: v for k, v in r.items() if k != 'kl'} for r in rows],
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(f"\n逐笔明细已保存 -> {out}")


if __name__ == '__main__':
    main()
