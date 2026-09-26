# -*- coding: utf-8 -*-
"""
热点追踪量化程序（山西证券 PTrade 版）v2.0 —— 全自动热点识别
=====================================================
模式说明：
  本版不再预设任何板块/个股清单。程序每日尾盘对全市场扫描，
  用多维强度评分自动识别「当前热点标的池」，并叠加退潮与止损风控。
逻辑来源（从 rd-hotspot-vetting / rd-hotspot-play 内化）：五维共振、
  启动/扩散/衰退三阶段、跌破20日线=退潮一票否决、单票-3%止损失/溢+10%止盈。
平台约束（山西证券 PTrade）：
  托管机房、内网无外网、普遍 Python 3.5、仅内置 API、证券尾缀 .SS/.SZ/.BJ。
运行模式：
  TRADE_ENABLED=False（默认）= 信号监控，只输出热点榜不下单；
  核对日志确认无误后改为 True 并在模拟盘验证，再考虑实盘。

⚠️ 实盘自动交易风险自负。全市场扫描是抽样近似（受券商行情接口性能限制），
   高热门票追高风险高，务必先跑信号模式观察数日。
"""

# ============================================================
# 一、参数配置区（按需修改）
# ============================================================
TRADE_ENABLED = True           # True=自动交易（下单）；False=信号模式（只输出不下单）
SCAN_STEP = 2                  # 全市场扫描抽样步长：1=全量约5000只(慢)，2≈2500只，5≈1000只
TOP_PICKS = 8                  # 输出来/可买入的当日热点候选数（等权买入前 MAX_POSITIONS 个）
MAX_POSITIONS = 5              # 同时在仓个股数上限
HOT_GAIN_MIN = 6.0             # 当日涨幅 >= 此值(%) 才进候选池
ZT_PCT = 9.5                   # 近似涨停判定线(%)，用于连板统计
STOP_LOSS_PCT = 0.03           # 单票浮亏超过 3% 无条件止损
TAKE_PROFIT_PCT = 0.10         # 单票浮盈达到 10% 无条件止盈
RETREAT_MA = 20                # 退潮一票否决均线（跌破=当日清仓）
LOOKBACK = 60                  # 日K回看天数（覆盖 MA20/MA60）
SIGNAL_TIME = "14:45"          # 每日信号评估/执行时间（尾盘）
POSITION_VALUE_RATIO = 0.2     # 单票目标市值占总资产比例（配合 MAX_POSITIONS 控制总仓位）

# ---- 标的过滤（标的池硬性剔除项） ----
REQUIRE_NO_ST = True           # 剔除 ST / *ST 股
MIN_HIST_BARS = 60             # 剔除次新/新股：上市历史K线不足此根直接剔除（也保证MA60可用）
MIN_AMOUNT = 3e8               # 剔除流动性不足：当日成交额下限 3亿(元)，用 量×收盘 近似
REQUIRE_MAIN_INFLOW = True     # 剔除主力资金净流出股（PTrade无真实资金流接口，用量价近似）
FLOW_LAG_VR = 2.0              # 主力净流出近似：量比 >= 此值 且 收在振幅下半 视为放量回落/流出

# ============================================================
# 二、工具函数
# ============================================================
def _suffix(code):
    """把 6 位代码 规范为 PTrade 代码格式（沪.SS / 深.SZ / 北交所.BJ）。"""
    code = str(code)
    if "." in code:
        return code
    if code.startswith(("68", "60")):
        return code + ".SS"
    if code.startswith(("00", "30")):
        return code + ".SZ"
    if code.startswith(("8", "4")):
        return code + ".BJ"
    return code


def _pure(code):
    """
    提取 6 位证券数字代码，统一不同后缀形态：'000710.SZ' / '000710.XSHE' /
    '000710'（IQEngine 内部用 XSHE/XSHG，策略统一用 .SZ/.SS，比较与取数前归一）。
    """
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


_st_name_cache = {}           # code -> bool（单只ST判定缓存）


def _is_st(code):
    """
    判断单只股票是否 ST/*ST。用恒生 PTrade 自带 get_stock_name()
    （研究/回测/交易均可用；新版不再有 get_all_securities/get_current_data）。
    只对通过量价/成交额筛选的少数候选调用，配缓存避免重复查询；
    若接口不可用（NameError 等）则视为非 ST 放行，并提示一次。
    """
    global _st_name_cache
    if code in _st_name_cache:
        return _st_name_cache[code]
    name = ""
    try:
        fn = globals().get("get_stock_name")
        if fn is not None:
            name = fn(code) or ""
    except Exception as e:
        log.info("[过滤] get_stock_name({}) 不可用: {}".format(code, repr(e)))
    is_st = "ST" in str(name).upper()
    _st_name_cache[code] = is_st
    return is_st


def _krows(df):
    """
    把 PTrade 返回的 DataFrame/其他格式归一为 [(date, close, high, low, vol), ...]
    升序（最新在后）。兼容 3.5 与 3.11 返回差异。
    """
    if df is None:
        return []
    try:  # DataFrame 形态
        idx = list(df.index)
        rows = []
        for i in range(len(df)):
            r = df.iloc[i]
            close = float(r["close"])
            high = float(r.get("high", close))
            low = float(r.get("low", close))
            try:
                vol = float(r.get("volume", 0) or 0)
            except Exception:
                vol = 0.0
            rows.append((idx[i], close, high, low, vol))
        return rows
    except Exception:
        pass
    try:  # list of dict
        if isinstance(df, list) and df and isinstance(df[0], dict):
            out = []
            for x in df:
                c = float(x.get("close", 0))
                out.append((x.get("date"), c, float(x.get("high", c)),
                            float(x.get("low", c)), float(x.get("volume", 0) or 0)))
            return out
        # list of [date, open, close, high, low, volume]
        if isinstance(df, list) and df:
            return [(x[0], float(x[2]), float(x[3]), float(x[4]),
                     float(x[5]) if len(x) > 5 else 0.0) for x in df]
    except Exception:
        pass
    return []


def get_hist(code, n):
    """获取 n 个交易日日K，优先 get_history，失败回退 get_price。返回统一 rows。"""
    code = _suffix(code)
    try:
        hist = get_history(n, "1d", ["close", "high", "low", "volume"], [code])
        if isinstance(hist, dict) and code in hist:
            rows = _krows(hist[code])
            if rows:
                return rows
    except Exception:
        pass
    try:
        df = get_price(code, None, None, "1d",
                       ["close", "high", "low", "volume"], fq="pre", count=n)
        rows = _krows(df)
        if rows:
            return rows
    except Exception:
        pass
    return []


def _ma(vals, n):
    if len(vals) < n or not all(vals[-n:]):
        return None
    return sum(vals[-n:]) / n


# ============================================================
# 三、个股强度评分（全市场自动热点识别）
# ============================================================
def assess_stock(code):
    """
    对单只个股计算当日热点强度分。返回 dict 或 None。
    评分维度（对『五维共振』做了个股级内化）：
      + 当日涨幅 pct
      + 连板数 lianban（近似：连续多日涨幅>=ZT_PCT）
      + 量能 vol_ratio（当日量/5日均量，资金介入特征）
      + 形态（站上 MA10/MA20/MA60，趋势确立）
    综合分 score = pct + lianban*10 + min(vol_ratio,3)*8 + 形态加分
    硬性过滤（任一命中即剔除，返回 None）：
      + ST / *ST 股（REQUIRE_NO_ST）
      + 次新/新股：历史K线不足 MIN_HIST_BARS 根（无论ST开关取值均生效）
      + 当日成交额 < MIN_AMOUNT（量×收盘近似）
      + 主力资金净流出近似：放量(量比>=FLOW_LAG_VR)但收在振幅下半 → 冲高回落/资金流出
    """
    rows = get_hist(code, LOOKBACK)
    # 过滤1：新股/次新（上市历史K线不足保护期，同时保证 MA60 有足够样本）
    if len(rows) < MIN_HIST_BARS:
        return None
    closes = [r[1] for r in rows]
    vols = [r[4] for r in rows]
    c0, c1 = closes[-2], closes[-1]
    if not c0:
        return None
    # 过滤3：当日成交额 < 3亿（PTrade无 amount 字段时用 量×收盘 近似估算）
    amt_est = vols[-1] * c1
    if amt_est < MIN_AMOUNT:
        return None
    pct = (c1 / c0 - 1) * 100.0
    if pct < 0:  # 当日下跌不进热点候选
        return None
    # 连板近似统计（最近连续 N 日单日涨幅>=ZT%）
    lb = 0
    for i in range(len(closes) - 1, 0, -1):
        chg = (closes[i] / closes[i - 1] - 1) * 100.0 if closes[i - 1] else 0
        if chg >= ZT_PCT:
            lb += 1
        else:
            break
    # 量能：当日量/近5日均量
    ma5v = sum(vols[-6:-1]) / 5.0 if len(vols) >= 6 and sum(vols[-6:-1]) > 0 else 0
    vol_ratio = (vols[-1] / ma5v) if ma5v else 0.0
    # 过滤4：主力资金净流出近似 —— 放量(量比>=FLOW_LAG_VR)却收在振幅下半 视为冲高回落/资金流出
    if REQUIRE_MAIN_INFLOW:
        hi, lo = rows[-1][2], rows[-1][3]
        if hi > lo and c1 < (hi + lo) * 0.5 and vol_ratio >= FLOW_LAG_VR:
            return None
    # 均线形态
    ma10, ma20, ma60 = _ma(closes, 10), _ma(closes, 20), _ma(closes, 60)
    above10 = bool(ma10 and c1 > ma10)
    above20 = bool(ma20 and c1 > ma20)
    above60 = bool(ma60 and c1 > ma60)
    shape_pts = (1 if above10 else 0) + (2 if above20 else 0) + (3 if above60 else 0)
    # 综合分
    score = pct + lb * 10.0 + min(vol_ratio, 3.0) * 8.0 + shape_pts * 1.5
    # 过滤2（延迟执行）：ST / *ST —— 只对已通过前述量价/成交额筛选的少数候选查名
    if REQUIRE_NO_ST and _is_st(code):
        return None
    return {
        "code": code, "pct": round(pct, 2), "lianban": lb,
        "vol_ratio": round(vol_ratio, 2), "above20": above20,
        "above60": above60, "score": round(score, 2),
    }


_pool_cache = None


def _get_market_pool():
    """
    获取全市场 A 股代码池（带回测/实盘可用性容错）。
    恒生 PTrade 标准接口：get_Ashares()（研究/回测/交易均可，返回带后缀代码列表）；
    部分券商定制版本用 get_all_stocks()。都失败则返回空。
    结果做模块级缓存，避免每个交易日重复拉全市场（回测性能关键）。
    """
    global _pool_cache
    if _pool_cache:
        return _pool_cache
    for fn_name in ("get_Ashares", "get_all_stocks"):
        try:
            fn = globals().get(fn_name)
            if fn is None:
                continue
            pool = fn()
            if isinstance(pool, dict):
                pool = list(pool.keys())
            if isinstance(pool, list) and pool and isinstance(pool[0], dict):
                pool = [x.get("code") or x.get("symbol") for x in pool]
            pool = [_suffix(str(x)) for x in pool if x]
            if pool:
                _pool_cache = pool
                log.info("[扫描] 用 {} 取全市场股票池 {} 只（已缓存）".format(
                    fn_name, len(pool)))
                return pool
        except Exception as e:
            log.info("[扫描] {} 不可用: {}".format(fn_name, repr(e)))
    log.info("[扫描] 无可用全市场股票池接口（get_Ashares / get_all_stocks 均失败）")
    return []


def scan_market():
    """
    全市场自动热点扫描：取全市场代码池（get_Ashares）-> 抽样 ->
    逐票评估 -> 按强度分排序输出 Top N。返回候选 list（dict）。
    """
    pool = _get_market_pool()
    if not pool:
        log.info("[扫描] 无全市场股票池，跳过本轮")
        return []
    codes = pool[::SCAN_STEP] if SCAN_STEP > 1 else pool
    log.info("[扫描] 开始全市场抽样 {} 只（总 {}，步长 {}）...".format(
        len(codes), len(pool), SCAN_STEP))

    cands = []
    cnt = 0
    for code in codes:
        try:
            a = assess_stock(code)
        except Exception:
            continue
        if a is None:
            continue
        if a["pct"] >= HOT_GAIN_MIN:
            cands.append(a)
        cnt += 1
        if cnt % 500 == 0:
            log.info("[扫描] 进度 {} / {}".format(cnt, len(codes)))
    cands.sort(key=lambda x: x["score"], reverse=True)
    log.info("[扫描] 完成，热点候选 {} 只".format(len(cands)))

    top = cands[:TOP_PICKS]
    log.info("=" * 60)
    log.info("[热点榜] 今日全市场最强 Top{}（强度分|涨幅|连板|量比|站上20日线）:".format(
        len(top)))
    for a in top:
        log.info("  {}  分{}  +{}%  连板{}  量比{}  20日线:{}".format(
            a["code"], a["score"], a["pct"], a["lianban"],
            a["vol_ratio"], "是" if a["above20"] else "否"))
    return top


# ============================================================
# 四、风控层：退潮一票否决 + 单票止损（来自 rd-hotspot-play）
# ============================================================
def _pos_f(p, name):
    """统一取持仓字段值：兼容 position 为 dict（p["name"]）或对象（p.name）两种形态。"""
    try:
        if isinstance(p, dict):
            return p.get(name)
        return getattr(p, name, None)
    except Exception:
        return None


def positions_map():
    """
    持仓快照：code -> position。多引擎/多版本容错：
      - get_positions() 返回 list[dict]（恒生标准）逐一按 security 取键；
      - get_positions() 返回 dict 时直接取键；
      - 元素也可能是持仓对象（属性 security）；
      - 以上全部失败回退 get_position() 单只读取。
    key 统一用 _suffix(_pure(..)) 规范化（IQEngine 内部返回 .XSHE/.XSHG 后缀，
    策略与热点榜统一用 .SZ/.SS，必须归一否则 build_orders 去重与取数全部失配）。
    返回空 dict 即表示当前无持仓（或读取失败，build_orders / monitor_risk 自动跳过）。
    """
    out = {}
    try:
        gp = get_positions()
        if isinstance(gp, dict):
            for k, p in gp.items():
                code = _pos_f(p, "security") or k
                if code:
                    out[_suffix(_pure(code))] = p
            if out:
                return out
        for p in gp or []:
            code = _pos_f(p, "security")
            if code:
                out[_suffix(_pure(code))] = p
        if out:
            return out
    except Exception as e:
        log.info("[持仓] get_positions 读取异常: {}".format(repr(e)))
    try:
        p = get_position()
        code = _pos_f(p, "security")
        if code:
            out[_suffix(_pure(code))] = p
    except Exception as e:
        log.info("[持仓] get_position 回退异常: {}".format(repr(e)))
    return out


def monitor_risk():
    """持仓风控：单票浮盈>=+10% 止盈 / 单票浮亏<=-3% 止损 / 跌破20日线=退潮清仓。
       任一条件触发即清仓离场。"""
    pm = positions_map()
    if not pm:
        log.info("[风控] 无持仓（positions_map 为空），本轮无可止盈/止损标的")
        return
    for code, px in pm.items():
        # 持仓量：标准字段 current_amount；IQEngine 实测仅有 enable_amount（可卖量），兜底兼容
        amount = _pos_f(px, "current_amount") or _pos_f(px, "enable_amount") or 0
        cost = _pos_f(px, "cost_price") or _pos_f(px, "avg_price") or 0
        log.info("[风控] 检查 {} 持仓{}股 成本{} 字段快照 {}".format(
            code, amount, cost,
            {k: _pos_f(px, k) for k in ("security", "current_amount",
                                        "enable_amount", "cost_price",
                                        "avg_price", "last_price")}))
        if amount <= 0:
            continue
        rows = get_hist(code, 25)
        if len(rows) < 20:
            log.info("[风控] {} 历史K线不足20根({})，跳过止损止盈判断".format(
                code, len(rows)))
            continue
        closes = [r[1] for r in rows]
        ok = True
        # 止盈 / 止损（需有持仓成本）
        # 关键：回测实测 get_hist 的最后一根K线滞后一个交易日（14:45触发时日K仅含
        # 昨日已收盘，当日未写入），用它算浮盈恒为「昨日收盘 vs 建仓成本」≈0，
        # 导致止损止盈永不触发。当日可成交参考价用持仓 last_price（无则退收盘）。
        price_now = _pos_f(px, "last_price") or _pos_f(px, "price") or closes[-1]
        if cost:
            profit_rt = price_now / cost - 1
            log.info("[风控] {} 最新价{} 成本{} 浮盈{:.2%}".format(
                code, price_now, cost, profit_rt))
            if profit_rt >= TAKE_PROFIT_PCT:
                ok = False
                log.info("[止盈] {} 浮盈{:.1%}>=+{:.0f}%，清仓".format(
                    code, profit_rt, TAKE_PROFIT_PCT * 100))
            elif profit_rt <= -STOP_LOSS_PCT:
                ok = False
                log.info("[止损] {} 浮亏{:.1%}<=-{:.0f}%，清仓".format(
                    code, profit_rt, STOP_LOSS_PCT * 100))
        else:
            log.info("[风控] {} 无持仓成本字段，跳过止盈止损".format(code))
        # 退潮一票否决（同样用当日参考价与均线比较，而非滞后的昨日收盘）
        if ok and price_now < _ma(closes, RETREAT_MA):
            ok = False
            log.info("[退潮] {} 跌破{}日线，清仓离场".format(code, RETREAT_MA))
        if not ok:
            if TRADE_ENABLED:
                order(code, -amount)
            else:
                log.info("[信号] 应清仓 {}".format(code))


def build_orders(top):
    """
    由热点榜生成买入清单：剔除已跌破20日线（退潮票），排除已在仓的，
    可买档位 = MAX_POSITIONS - 当前持仓数（MAX_POSITIONS 是最大同时持仓数，
    非每轮买入数）。已满仓则本轮不新增，避免资金不足导致平台自动缩量成碎股。
    """
    held = set(positions_map().keys())
    remaining = MAX_POSITIONS - len(held)
    if remaining <= 0:
        log.info("[买入] 持仓已满（{}只），本轮不再新增".format(len(held)))
        return []
    picks = []
    for a in top:
        if not a["above20"]:
            continue          # 站不上20日线=退潮/弱势，不追
        if a["code"] in held:
            continue
        picks.append(a)
        if len(picks) >= remaining:
            break
    return picks


# ============================================================
# 五、PTrade 入口
# ============================================================
def _safe_commission():
    """
    佣金设置多平台/多版本容错。
    恒生 PTrade（IQEngine 回测引擎 Python3.11）标准签名：
        set_commission(commission_ratio=0.0003, min_commission=5.0, type='STOCK')
    山西证券等定制版曾用：set_commission(PerTrade=0.0003, Min=5)
    逐个签名尝试，全部失败不阻断初始化，按平台默认佣金回测。
    """
    for name, kw in (
            ("ratio", dict(commission_ratio=0.0003, min_commission=5.0,
                           type="STOCK")),
            ("per_trade", dict(PerTrade=0.0003, Min=5)),
            ("per_amount", dict(PerAmount=0.0003, Min=5)),
    ):
        try:
            set_commission(**kw)
            log.info("[配置] set_commission 生效（{} 签名）".format(name))
            return
        except Exception as e:
            log.info("[配置] set_commission({}) 失败: {}".format(name, repr(e)))
    log.info("[配置] 佣金未显式设置（平台不支持已尝试签名），按平台默认成本")


def initialize(context):
    try:
        set_benchmark("000300.SS")
    except Exception as e:
        log.info("[配置] set_benchmark 失败: {}".format(repr(e)))
    _safe_commission()
    try:
        set_slippage(slippage=0.002)
    except Exception as e:
        log.info("[配置] set_slippage(slippage=0.002) 失败: {}".format(repr(e)))
        try:
            set_slippage(0.002)
        except Exception as e2:
            log.info("[配置] 滑点未显式设置: {}".format(repr(e2)))
    log.info("[初始化] 全自动热点识别策略 v2.0（山西证券）启动；TRADE_ENABLED={}".format(
        TRADE_ENABLED))


def before_trading_start(context, data):
    pass


def _now_str(context):
    try:
        return context.blotter.current_dt.strftime("%H:%M")
    except Exception:
        pass
    try:
        return context.now.strftime("%H:%M")
    except Exception:
        pass
    try:
        return get_datetime().strftime("%H:%M")
    except Exception:
        return ""


def _total_asset(context):
    """
    获取账户总资产，多引擎容错：恒生官方接口为 context.portfolio.portfolio_value
    （IQEngine 新引擎无 get_total_assets）；老版 PTrade 用 get_total_assets() 回退。
    全部失败返回 0（建仓将自动跳过）。
    """
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        pass
    try:
        return float(get_total_assets())
    except Exception as e:
        log.info("[资产] 无法获取总资产: {}".format(repr(e)))
    return 0.0


def handle_data(context, data):
    now = _now_str(context)
    if now != SIGNAL_TIME:
        return

    log.info("=" * 60)
    log.info("[{}] 每日全市场热点识别开始".format(now))
    try:
        top = scan_market()
    except Exception as e:
        log.info("[扫描] 全市场扫描异常: {}".format(repr(e)))
        top = []

    # 风控先行：处理已有持仓（退潮/止损）
    try:
        monitor_risk()
    except Exception as e:
        log.info("[风控] 持仓风控异常: {}".format(repr(e)))

    # 建仓
    if TRADE_ENABLED and top:
        picks = build_orders(top)
        if picks:
            total_asset = _total_asset(context)
            if total_asset <= 0:
                log.info("[买入] 无法获取总资产，本轮跳过建仓")
            else:
                target = total_asset * POSITION_VALUE_RATIO
                for a in picks:
                    log.info("[买入] {} 现价+{}% 分配{}".format(
                        a["code"], a["pct"], round(target, 2)))
                    order_value(a["code"], target)
        else:
            log.info("[信号] 无符合建仓条件的热点候选（等回踩/等退潮修复）")
    else:
        log.info("[信号模式] 本日仅输出热点榜，不下单；如需自动交易请置 TRADE_ENABLED=True")


def after_trading_end(context, data):
    log.info("[收盘] 当日策略运行结束")
