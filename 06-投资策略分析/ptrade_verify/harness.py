# -*- coding: utf-8 -*-
"""
hotspot_trader_ptrade 策略体检 harness
=====================================
用 mock 的 PTrade API 把策略原地跑起来验证边界行为。
"""
import random, datetime, io, os

# ---------------- 极简 DataFrame 替身（对齐 pandas 的 iloc / index 用法） ----------------
class Row(object):
    def __init__(self, d): self._d = d
    def __getitem__(self, k): return self._d[k]
    def get(self, k, default=None): return self._d.get(k, default)

class _Iloc(object):
    def __init__(self, df): self._df = df
    def __getitem__(self, i):
        return Row({k: v[i] for k, v in self._df._cols.items()})

class FakeDF(object):
    def __init__(self, index, cols):
        self.index = list(index); self._cols = cols
    def __len__(self): return len(self.index)
    @property
    def iloc(self): return _Iloc(self)


# ---------------- 虚拟市场 ----------------
N_STOCK = 600
DAYS = 150
HOT_DAY = 103          # 人造热点日
ST_IDX = (10, 56)      # 偶数下标 -> 一定落在 [::2] 抽样视野内

def gen_market(seed=7):
    rnd = random.Random(seed)
    codes = []
    for i in range(N_STOCK):
        if i < 300:   codes.append("{:06d}".format(600000 + i * 3))
        elif i < 598: codes.append("{:06d}".format(100 + (i - 300) * 7))
        else:         codes.append("{:06d}".format(920000 + i))
    dates = [(datetime.date(2025, 1, 1) + datetime.timedelta(days=k)).isoformat()
             for k in range(DAYS)]
    mkt = {}
    hot_cluster = set(codes[120:136])
    st_codes = set(codes[i] for i in ST_IDX)
    for c in codes:
        px = 8.0 + rnd.random() * 20
        rows = []
        for d in range(DAYS):
            is_hot = (c in hot_cluster or c in st_codes) and 100 <= d <= HOT_DAY + 2
            drift = (rnd.random() - 0.49) * 0.03
            if is_hot:
                drift = 0.075 + rnd.random() * 0.03
            op = px
            px = max(1.0, px * (1 + drift))
            cl = px
            hi = max(op, cl) * (1 + rnd.random() * 0.012)
            lo = min(op, cl) * (1 - rnd.random() * 0.012)
            vol = (2e7 + rnd.random() * 6e7) * (1.6 if is_hot else 1.0)
            rows.append(dict(date=dates[d], open=op, close=cl, high=hi, low=lo, volume=vol))
        mkt[c] = rows
    names = {c: c for c in codes}
    names[codes[ST_IDX[0]]] = "ST 华测试"
    names[codes[ST_IDX[1]]] = "*ST 退市测"
    return codes, mkt, names


CODES, MKT, NAMES = gen_market()


# ---------------- mock PTrade 运行时 ----------------
class Mock(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.logs = []
        self.orders = []
        self.order_values = []
        self.hist_calls = 0
        self.positions = []
        self.day = cfg.get("day", HOT_DAY)
        self.portfolio_value = cfg.get("portfolio_value", 1000000.0)

    def log_info(self, msg, *a):
        try: self.logs.append(msg % a if a else msg)
        except Exception: self.logs.append(str(msg))

    def get_history(self, count, period="1d", field=None, security_list=None, **kw):
        if self.cfg.get("strict_field_str") and isinstance(field, (list, tuple)):
            raise TypeError("field must be str in this build")
        self.hist_calls += 1
        out = {}
        end = self.day if self.cfg.get("include_today", True) else self.day - 1
        end = max(end, 0)
        for code in (security_list or []):
            pure = "".join(ch for ch in str(code) if ch.isdigit())[:6]
            rows = MKT.get(pure)
            if not rows: continue
            seg = rows[max(0, end - count + 1): end + 1]
            if not seg: continue
            sc = 1.0 / 100.0 if self.cfg.get("vol_in_lots") else 1.0
            cols = dict(date=[r["date"] for r in seg],
                        close=[r["close"] for r in seg],
                        high=[r["high"] for r in seg],
                        low=[r["low"] for r in seg],
                        volume=[r["volume"] * sc for r in seg])
            out[code] = FakeDF(cols["date"], cols)
        return out

    def get_price(self, security, start_date=None, end_date=None, frequency="1d",
                  fields=None, fq=None, count=None, **kw):
        if self.cfg.get("no_get_price"):
            raise AttributeError("get_price not available")
        return self.get_history(count or 1, frequency, fields, [security])

    def get_Ashares(self): return list(CODES)
    def get_stock_name(self, code):
        if self.cfg.get("no_get_stock_name"): raise NameError("undefined")
        return NAMES.get("".join(ch for ch in str(code) if ch.isdigit())[:6], "")
    def get_positions(self): return list(self.positions)
    def get_position(self): raise AttributeError("no get_position")
    def order(self, security, amount): self.orders.append((security, amount))
    def order_value(self, security, value): self.order_values.append((security, value))
    def set_commission(self, **kw): raise TypeError("bad signature")
    def set_slippage(self, *a, **kw): raise TypeError("bad signature")
    def set_benchmark(self, *a, **kw): pass
    def get_datetime(self): raise AttributeError("nope")
    def get_total_assets(self): return self.portfolio_value


class _Log(object):
    def __init__(self, m): self.m = m
    def info(self, s, *a): self.m.log_info(s, *a)
    def error(self, s, *a): self.m.log_info(s, *a)
    def warning(self, s, *a): self.m.log_info(s, *a)

class _Blotter(object):
    def __init__(self, hhmm):
        h, mi = hhmm.split(":")
        self.current_dt = datetime.datetime(2025, 6, 1, int(h), int(mi))

class _Portfolio(object):
    def __init__(self, v): self.portfolio_value = v

class _Ctx(object):
    def __init__(self, hhmm, v):
        self.blotter = _Blotter(hhmm)
        self.portfolio = _Portfolio(v)
        self.now = self.blotter.current_dt


SRC = {}

def load_strategy():
    if "code" not in SRC:
        base = os.path.dirname(os.path.abspath(__file__))
        for fn in ("strategy.py", "strategy_original.py"):
            p = os.path.join(base, fn)
            if os.path.exists(p):
                with io.open(p, encoding="utf-8") as f:
                    SRC["code"] = f.read()
                break
    return SRC["code"]


def run(cfg, positions=None, label=""):
    m = Mock(cfg)
    ns = {
        "log": _Log(m),
        "get_history": m.get_history, "get_price": m.get_price,
        "get_Ashares": m.get_Ashares, "get_stock_name": m.get_stock_name,
        "get_positions": m.get_positions, "get_position": m.get_position,
        "order": m.order, "order_value": m.order_value,
        "set_commission": m.set_commission, "set_slippage": m.set_slippage,
        "set_benchmark": m.set_benchmark, "get_datetime": m.get_datetime,
        "get_total_assets": m.get_total_assets,
        "__name__": "strategy",
    }
    exec(compile(load_strategy(), "strategy.py", "exec"), ns)
    m.positions = positions or []
    ctx = _Ctx(cfg.get("now", "14:45"), m.portfolio_value)
    ns["initialize"](ctx)
    ns["handle_data"](ctx, None)
    print("")
    print("=" * 74)
    print("SCENE:", label)
    print("-" * 74)
    for l in m.logs:
        if l.startswith("[配置]"):
            continue
        print("  |", l)
    tot = sum(v for _, v in m.order_values)
    print("  >> get_history 调用次数 :", m.hist_calls)
    print("  >> 买入 order_value     :", len(m.order_values), "合计 {:,}".format(int(tot)),
          "= 总资产 {}%".format(round(100.0 * tot / m.portfolio_value, 1)) if tot else "")
    print("  >> 卖出 order           :", len(m.orders), m.orders[:5])
    return m, ns


BASE = dict(day=HOT_DAY, now="14:45", include_today=True)

if __name__ == "__main__":
    m1, _ = run(dict(BASE), label="S1 基线：人造热点日 T=103，行情正常")

    st_set = set(CODES[i] for i in ST_IDX)
    picked = ["".join(ch for ch in c if ch.isdigit())[:6] for c, _ in m1.order_values]
    hit = [c for c in picked if c in st_set]
    print("  >> ST 股是否漏进买入清单:", hit if hit else "未漏入（ST 过滤生效）")

    _ = run(dict(BASE, strict_field_str=True, no_get_price=True),
            label="S2 get_history 不支持 field=list 且无 get_price 回退（静默失效）")

    _ = run(dict(BASE, vol_in_lots=True),
            label="S3 get_history 的 volume 单位是「手」而不是「股」")

    _ = run(dict(BASE, now="15:00"),
            label="S4 日线回测 current_dt=15:00（不等于 14:45）")

    _ = run(dict(BASE, include_today=False),
            label="S8 get_history 返回不含当日 bar 的口径（回测常见）")

    _c = CODES[120]
    _suf = _c + ".SS" if _c.startswith("60") else (_c + ".SZ" if _c[0] in "03" else _c + ".BJ")
    _last = MKT[_c][HOT_DAY]["close"]
    pos = [dict(security=_suf, current_amount=10000, enable_amount=0,
                cost_price=_last / 0.90, avg_price=_last / 0.90, last_price=_last)]
    _ = run(dict(BASE), positions=pos,
            label="S5 T+1：当日买入票浮亏 -10%，current_amount=10000 / 可卖 enable_amount=0")

    print("")
    print("=" * 74)
    print("S6-A 基线热点榜当日涨幅分布 -> 判断尾盘能否真的买到")
    print("-" * 74)
    pcts = []
    for l in m1.logs:
        s = l.strip()
        if s[:6].isdigit() and "分" in s and "+" in s:
            print("   |", s)
            try: pcts.append(float(s.split("+")[1].split("%")[0]))
            except Exception: pass
    if pcts:
        zt = len([p for p in pcts if p >= 9.5])
        print("   >> 榜单 {} 只，涨幅 >=9.5%（封涨停、尾盘买不进）{} 只，占比 {}%".format(
            len(pcts), zt, round(100.0 * zt / len(pcts), 1)))

    print("")
    print("=" * 74)
    print("S6-B SCAN_STEP=2 固定步长抽样的视野覆盖率")
    print("-" * 74)
    hot_idx = list(range(120, 136))
    seen = [i for i in hot_idx if i % 2 == 0]
    print("   | 人造热点簇 {} 只，落在抽样视野内 {} 只（{}%）".format(
        len(hot_idx), len(seen), round(100.0 * len(seen) / len(hot_idx), 1)))
    print("   | 抽样下标固定、不随日期轮换 -> 视野外的票永远扫不到")

    print("")
    print("=" * 74)
    print("S7 仓位：MAX_POSITIONS x POSITION_VALUE_RATIO")
    print("-" * 74)
    print("   | 5 x 20% = 100% 总资产，无现金缓冲；")
    print("   | 且 order_value 未判断可用资金，资金不足时平台会静默缩量成碎股。")
