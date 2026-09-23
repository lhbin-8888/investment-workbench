# -*- coding: utf-8 -*-
"""
山西证券 PTrade 量化策略 —— 长线股「核心-卫星 + 波段 + 日内T」三层架构
=====================================================================
平台：山西证券 PTrade（恒生系白标，Python 3.5 托管环境，无外网、无 os 模块）
约束（来自 ptrade-strategy-dev 技能，逐条已落实）：
  - 代码后缀 .SS / .SZ / .BJ；内部比较一律用 6 位纯数字（_canon）
  - T+1：卖出必须用 enable_amount（可卖量），current_amount 含当日新仓
  - 涨跌停用板区分：30/68->20%  8/4->30%  ST->5%  其余 10%
  - 成本含印花税（卖出单边）；换手预算按"交易日窗口"计
  - 回测当日价只能走 handle_data 的 data 参数或 1m 线；不可读 close[-1] 当已收盘
  - 两段式止损已证伪 -> 统一用"单段一次性清仓" + 策略自有成本价记录
  - 盈亏比：止损上限 <= 止盈上限的一半
  - 出场分级闸门：风险类(硬止损)只设下限 09:45；趋势类(破线/清仓)尾盘 14:45
  - 任何接口降级必须 log.warning，绝不静默换口径

默认 TRADE_ENABLED = False：先信号模式跑 3~5 日核对日志，再模拟盘，最后小资金实盘。

山西证券实测口径（ptrade-strategy-dev 技能；与国金版接口层一致）：
  - get_history 含当日 bar：本策略 3 处日线取数均在 before_trading_start（盘前），
    此时当日 bar 尚未生成，末根仍为昨收 -> 不受该差异影响（已核查全部调用点）
  - volume 单位为股；order_value 限价参数名为 limit_price（本策略只用 order_target_value 市价单，不涉及）
  - 若该引擎不向 handle_data 传 data（技能实测有此行为），L3 自动退化：
    data -> get_snapshot(last_px) -> 皆无则关闭 L3（预期降级，日志有 [口径] 标注，不影响 L1/L2）

版本：★山西PTrade V1.4★（与国金PTrade_三层量化策略.py 同逻辑，仅券商适配）

★V1.3 修复（对应《回测复盘_山西PTrade_20260922.md》D9~D13，首跑真下单模式实测）：
  D9  下单时点：原五条下单路径全挂在 before_trading_start(08:30) -> 平台一律返回
      "订单不在交易时间段内，下单失败"（17 笔）。现改为「盘前算信号 -> 09:31 盘中执行」，
      统一委托出口 _submit_order() 入队 + _flush_pending() 出队。
  D10 整手可行性预检：原单票预算买不起 1 手仍发出 0 股委托（37 笔"股票委托数量为0"）。
      现预检 1 手成本，不足则打 [买不起] 明确告警并跳过。
  D11 拒单状态污染：平台拒单不抛异常，原实现无条件写 buy_day -> 留下"幽灵建仓日"，
      导致 L1 季度再平衡误判"持仓不足5日"而少建一只仓。现仅受理后才写状态。
  D12 统计拆「委托 / 被拒 / 有效」三行（原 "buy: N 笔" 是委托意图数，不是成交数）。
  D13 委托连续被拒熔断 + 在途委托去重（官方文档警告 order_target_value 易重复下单）。
  新增 资金再分配：买不起 1 手的预算顺延给买得起的标的（原名义 58% 实际只能落实 23.2%）。
  新增 资本适配自检：启动即暴露"结构性买不起"与组合最大可落实仓位。
  新增 可用现金预检（留 2% 缓冲）。

★V1.3 修复（对应《回测复盘_山西PTrade_V1.3_20260922.md》D16~D21，30万本金真下单模式实测）：
  D16 持仓层级归属：原 _daily_risk_scan/_intraday_hard_stop 用「code in L2_SET」判定，
      因 L2 池⊆L1 池，把 L1 核心仓误判为 L2 卫星仓反复清掉（07-07 建4只次日清3只）。
      现加 owner_layer 标记，出场规则按持仓归属层级过滤（D18 的 T 路径不登记层级）。
  D17 换手预算滚动化：原 ytd_turns 只增不减，L3 日内T 几十笔回合 30 日内烧穿年度预算，
      致 L2 此后 46% 交易日被锁、[L2-买] 全期 0 笔。现 L2/L3 分账 + 250 日滚动窗口，预算可恢复。
  D18 L3 日内T 接入统一出口：原 _t_once/_t_force_close 直连 order_target_value，绕过 _submit_order，
      24 笔 T 委托未入统计、拒单不熔断、幽灵状态在 T 路径复活。现全部经 _submit_order。
  D19 统计口径修正：原「已提交N」是 STATS 记账次数而非真实委托数。现改记 order_submitted/rejected。
  D20 去除 get_snapshot 回测噪音（平台在回测模式刷"回测不支持get_snapshot"，data 已是权威盘中价）。
  D21 同标的同日多笔委托合并：避免「先砍两成再清仓」类矛盾委托（_flush_pending 末笔覆盖）。
"""

# ============================== 全局状态 ==============================
# PTrade 模块级 g 字典（全局可变状态，跨回调共享）
g = {}

# ============================== 一、参数区 ==============================
# ---- 总开关 ----
TRADE_ENABLED = False          # [上线前必改] False=只出信号不下单；True=实盘下单
INTRADAY_T    = False          # ★V1.4 已移除 L3 日内T（V1.3 实测 57 回合、净贡献≈0，仅贡献交易摩擦）

# ---- 三层资金架构（占组合净值比例，合计 < 1，余为缓冲）----
L1_RATIO = 0.58               # L1 长线底仓
L2_RATIO = 0.25               # L2 波段卫星
# L3 日内T 不占额外长期仓位，只在 L2/L3 现金里做"有去有回"的闭环

# ---- 再平衡 ----
L1_REBALANCE_DAYS = 60        # L1 季度再平衡间隔（交易日）
L1_MIN_HOLD_DAYS  = 5         # L1 单只最短持有（交易日），防过度换手

# ---- L1 止盈/再平衡（V1.3：把 V1.1 误触发的止盈做成正式纪律）----
L1_TRIM_GAIN       = 0.15   # 单票浮盈>=15%% 触发减仓至目标权重（波动率收割/落袋，复刻 V1.1 误触发行为）
L1_DRIFT_CTRL_DAYS = 10     # L1 漂移控制检查间隔（交易日）：不止等季度，及时落袋

# ---- ★V1.4 L1 回补对称化（修 V1.3「只减不加」的单向失血）----
# V1.3 实测：市场开关「跌破120日线砍两成」执行 6 次，而「档位复位」5 次只清标记、
# 不回补仓位 -> 持仓占比 53.5% 一路砸到 32.0%，现金趴到 67%。本条规则是 V1.4 的核心修复。
L1_REFILL_DAYS     = 5      # 定期回补检查间隔（交易日）：兜底，不必等 60 天季度
L1_REFILL_MIN_GAP  = 0.15   # 缺口 >= 目标权重的 15% 才回补（防碎单）
L1_REFILL_COOLDOWN = 20     # 同一标的回补后 N 个交易日内不再回补（防高频小额）

# ---- L2 波段信号 ----
L2_PULLBACK_PCT = 0.05        # ★V1.4 放宽 6%->5%（原「回调6%+量比0.8+RSI35-55」三重叠加，全期仅5次信号）
L2_VOL_RATIO_MAX = 0.90       # ★V1.4 放宽 0.8->0.9：温和缩量即算地量
L2_RSI_LO, L2_RSI_HI = 35, 58 # ★V1.4 上限 55->58
L2_TAKE_PCT   = 0.14          # 目标收益 +14%（止盈上限）
L2_TRAIL_PCT  = 0.08          # 移动止盈回撤 8%
L2_STOP_PCT   = 0.07          # 硬止损 -7%（满足 止损<=止盈/2）
L2_RSI_SELL   = 70            # 超买清仓线

# ---- L3 日内T ----
T_TRIGGER_PCT = 0.012         # VWAP 偏离 1.2% 触发
T_MAX_FRAC    = 0.20          # 单次动用可卖量上限 20%
T_MAX_ROUNDS  = 2             # 单票单日最多 2 回合
T_EDGE_MIN    = 0.004         # edge < 0.4% 不做（散户T净贡献常为负）
T_OPEN, T_CLOSE = "09:45", "14:45"   # T 仅在此窗口；14:50 强制平掉未回补
T_VWAP_WIN    = 60            # VWAP 计算用近 60 根 1m 线

# ---- 风控 ----
CB_STAGE1, CB_STAGE2, CB_STAGE3 = -0.08, -0.12, -0.18   # 组合断路器三级
MKT_MA_SHORT, MKT_MA_LONG = 60, 120                    # 沪深300 均线开关
MKT_RESET_CONFIRM_DAYS = 1    # 长均线档位复位需连续站上 120 日线的交易日数(默认1=立即复位；
                              # 调大如3~5可防指数在均线附近反复穿越导致反复减仓)
SINGLE_MAX = 0.10            # 单票上限 10%
SECTOR_MAX = 0.30           # 行业上限 30%（按表中细分行业，见 SECTOR_OF）

# ---- 成本 / 换手预算（R3 经济性先于策略）----
# 现行费率估算（A股 2024-2026）：印花税卖出单边 0.05%（2023-08-28 起减半）；
#   佣金双边 万2.5（最低5元/笔）；滑点为回测建模假设 0.05%。未含过户费（中登 万0.1 双向）。
STAMP_TAX   = 0.0005         # 印花税：卖出单边 0.05%（现行）
COMM_RATE   = 0.00025        # 佣金：双边 0.025%（万2.5，最低5元/笔）
SLIPPAGE    = 0.0005         # 滑点：回测建模假设 0.05%
COST_PER_TURN = STAMP_TAX + 2*COMM_RATE + 2*SLIPPAGE   # 单回合（买+卖）综合成本 ≈ 0.20%（未含过户费）
ANNUAL_COST_BUDGET = 0.015   # 年度成本预算 1.5%
MAX_ANNUAL_TURNS  = ANNUAL_COST_BUDGET / COST_PER_TURN  # ≈ 7.5 回合/年硬上限
TURNOVER_MIN_DAYS = 20        # 年化外推的最小样本(交易日)；不足则不做年化判定，
                              # 避免回测初期 1 个回合被外推成 250 回合/年、一天烧光整年预算

# ============================== 二、股票池 ==============================
# 来自「长线选股_20260920」精选 16 只，带正确后缀
STOCKS = [
    "600519.SS",  # 贵州茅台
    "603605.SS",  # 珀莱雅
    "002027.SZ",  # 分众传媒
    "000538.SZ",  # 云南白药
    "300760.SZ",  # 迈瑞医疗
    "603259.SS",  # 药明康德
    "688111.SS",  # 金山办公
    "603986.SS",  # 兆易创新
    "688012.SS",  # 中微公司
    "688072.SS",  # 拓荆科技
    "002414.SZ",  # 高德红外
    "601899.SS",  # 紫金矿业
    "000792.SZ",  # 盐湖股份
    "600938.SS",  # 中国海油
    "600900.SS",  # 长江电力
    "688008.SS",  # 澜起科技
]
# L1 质量权重（原始值，代码内归一化到 L1_RATIO）
L1_RAW = {
    "600519.SS": 10, "601899.SS": 9, "600938.SS": 8, "600900.SS": 8, "300760.SZ": 8,
    "603259.SS": 7, "002027.SZ": 7, "000538.SZ": 7, "603605.SS": 7, "000792.SZ": 7,
    "688111.SS": 6, "603986.SS": 6, "688012.SS": 5, "688072.SS": 5, "002414.SZ": 5,
    "688008.SS": 5,
}
# L2 波段卫星（流动性好的 10 只），L2_RATIO 在其间均分
L2_SET = [
    # ★V1.4 换池：剔除 3 只科创板高价股（688012 中微 1手5.5万 / 688072 拓荆 6.6万 /
    # 688111 金山 4.6万 —— V1.3 实测 L2 的 5 次信号全落在这 3 只上，100% 买不起），
    # 换成 1 手成本 1.2千~9千 的中低价标的。8 只全部在 30 万本金的单票预算内。
    "601899.SS", "600938.SS", "600900.SS", "002027.SZ",
    "000538.SZ", "603605.SS", "000792.SZ", "002414.SZ",
]
# L3 日内T 标的（最流动的 7 只）
L3_SET = [
    "600519.SS", "601899.SS", "600938.SS", "600900.SS", "300760.SZ",
    "002027.SZ", "603986.SS",
]
# 行业划分：采用「长线选股_20260920」原表 细分行业 字段（自选股20260920.xls，492 只全样本筛选）
# 仅用于行业上限约束 SECTOR_MAX
SECTOR_OF = {
    "600519.SS": "白酒",          # 贵州茅台
    "603605.SS": "化妆品",        # 珀莱雅
    "000538.SZ": "中药",          # 云南白药
    "300760.SZ": "医疗设备",      # 迈瑞医疗
    "603259.SS": "医疗研发外包",  # 药明康德
    "688111.SS": "云软件服务",    # 金山办公
    "603986.SS": "集成电路设计",  # 兆易创新
    "688008.SS": "集成电路设计",  # 澜起科技
    "688012.SS": "半导体设备",    # 中微公司
    "688072.SS": "半导体设备",    # 拓荆科技
    "002414.SZ": "军工电子",      # 高德红外
    "601899.SS": "铜",            # 紫金矿业
    "000792.SZ": "钾肥",          # 盐湖股份
    "600938.SS": "油气开采",      # 中国海油
    "600900.SS": "水力发电",      # 长江电力
    "002027.SZ": "其他广告营销",  # 分众传媒
}
INDEX_CODE = "000300.SS"   # 沪深300 作为市场开关


# ============================== 三、工具函数 ==============================
def _canon(code):
    """返回 6 位纯数字，所有内部比较统一用。"""
    if "." in code:
        return code.split(".")[0]
    return code


def _suffix(digit):
    """6 位数字补后缀。指数（已带点）原样返回。"""
    if "." in digit:
        return digit
    if digit.startswith("6") or digit.startswith("9"):
        return digit + ".SS"
    if digit.startswith("8") or digit.startswith("4"):
        return digit + ".BJ"
    return digit + ".SZ"


def _plate_pct(code):
    """涨停/跌停幅度（小数）：创业板30*/科创板688* -> 0.20；北交所8/4 -> 0.30；ST -> 0.05；其余 0.10。"""
    d = _canon(code)
    up = (d[0:2] in ("30",) or d[0:3] in ("688",)) and 1 or 0
    if up:
        return 0.20
    if d[0] in ("8", "4"):
        return 0.30
    if "ST" in code.upper():
        return 0.05
    return 0.10


def _lot_min(code):
    """整手最小单位：科创板 200，其余 100。"""
    d = _canon(code)
    if d[0:3] == "688":
        return 200
    return 100


def _round_lot(shares, code):
    """向下取整到整手。"""
    lm = _lot_min(code)
    return int(shares // lm) * lm


def _hist_lists(code, count, period="1d"):
    """取历史行情，返回 (closes, opens, highs, lows, vols) 列表；失败返回 None（R4 显式告警）。"""
    try:
        # 真实签名: get_history(count, frequency, field, security_list, ...)
        # code 必须传字符串(单只)才返回 DataFrame(列=字段名)；无 df 参数
        bars = get_history(count, period, ["close", "open", "high", "low", "volume"], code)
    except Exception as e:
        log.warning("[hist] get_history 异常 %s: %s" % (code, e))
        return None
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        log.warning("[hist] %s 返回空（可能不支持 df/字段），L 层该票跳过" % code)
        return None
    try:
        closes = list(bars["close"])
        opens = list(bars["open"])
        highs = list(bars["high"])
        lows = list(bars["low"])
        vols = list(bars["volume"])
    except Exception as e:
        log.warning("[hist] %s 返回形态非预期: %s" % (code, e))
        return None
    return closes, opens, highs, lows, vols


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _index_below_ma(code, ma_days):
    """指数收盘价是否低于其 ma_days 均线（用已完成数据：before_trading_start 时末根是昨收）。

    返回 True / False；数据不足或取不到时返回 None（无法判定），由调用方做保守处理，
    避免把「无数据」当成「站上均线」而误复位市场开关档位。
    """
    h = _hist_lists(code, ma_days + 5, "1d")
    if h is None:
        return None
    closes = h[0]
    ma = _ma(closes, ma_days)
    if ma is None:
        return None
    return closes[-1] < ma


def _cur_price(code, data):
    """Intraday price: prefer handle_data data[code].price, fallback get_snapshot last_px. Returns (price, source)."""
    if data is not None:
        try:
            obj = data[code]
            px = getattr(obj, "price", None)
            if px is None and hasattr(obj, "get"):
                px = obj.get("price")
            if px is None and hasattr(obj, "get"):
                px = obj.get("close") or obj.get("last_px")
            if px and float(px) > 0:
                return float(px), "data"
        except Exception:
            pass
    # ★V1.3 D20：移除 get_snapshot 回测噪音（平台在回测模式下调用 get_snapshot 会刷
    # "回测不支持get_snapshot" 告警，且 handle_data 的 data 已是权威盘中价来源，无需回退）。
    return None, "none"
def _pos_to_dict(p, code_hint=""):
    """Map a Position object (or a legacy dict) into the uniform shape.

    PTrade 口径（山西/国金文档一致）：get_positions() 与 context.portfolio.positions
    均为 dict[str:Position]，值为 Position 对象，字段 sid/enable_amount/amount/
    last_sale_price/cost_basis。code_hint 用于字典键与 Position 内代码不一致时兜底。
    """
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0
    if isinstance(p, dict):
        code = (p.get("stock_code") or p.get("security") or p.get("code")
                or p.get("sid") or code_hint or "")
        d = {
            "code": code,
            "current_amount": _f(p.get("current_amount", p.get("amount", 0))),
            "enable_amount": _f(p.get("enable_amount", 0)),
            "cost_price": _f(p.get("cost_price", p.get("keep_cost_price", 0))),
            "current_price": _f(p.get("last_price", p.get("last_sale_price", 0))),
        }
    else:
        code = (getattr(p, "sid", "") or getattr(p, "security", "")
                or getattr(p, "stock_code", "") or code_hint)
        d = {
            "code": code,
            "current_amount": _f(getattr(p, "amount", 0)),
            "enable_amount": _f(getattr(p, "enable_amount", 0)),
            "cost_price": _f(getattr(p, "cost_basis", getattr(p, "cost_price", 0))),
            "current_price": _f(getattr(p, "last_sale_price", getattr(p, "last_price", 0))),
        }
    cd = _canon(d["code"])
    d["code"] = _suffix(cd)
    return d


def _get_positions():
    """Return {canon: dict(current_amount, enable_amount, cost_price, current_price)}.

    【口径·重要】山西/国金文档一致：get_positions() 返回 **dict[str:Position]**
    （键=标的代码，值=Position 对象）；context.portfolio.positions 同为 dict[str:Position]。
    返回 list[dict] 的是 get_all_positions()，仅交易模块可用，本策略不用。
    因此必须按 .items() 取键值对：早前写成 `for p in poss`，遍历 dict 只会得到
    字符串键，被 _pos_to_dict 判为空代码而整仓丢弃 -> 策略误判"零持仓"，
    风控/日内T/行业上限全部静默失效（信号模式下无持仓，故冒烟测试掩盖了该缺陷）。
    兼容处理：dict -> items()；list -> 按下标取值。
    """
    out = {}
    items = []
    try:
        poss = get_positions()
    except Exception as e:
        poss = None
        log.warning("[pos] get_positions err: %s" % e)
    if isinstance(poss, dict):
        items = list(poss.items())
    elif poss:
        try:
            for i in range(len(poss)):
                items.append((None, poss[i]))
        except Exception:
            items = []
    for key, p in items:
        hint = str(key) if key is not None else ""
        d = _pos_to_dict(p, hint)
        cd = _canon(d["code"])
        if not cd:
            continue
        out[cd] = d
    if out:
        return out
    # 退化通道：直接读 context.portfolio.positions（同为 dict[str:Position]）
    ctx = g.get("ctx")
    if ctx is not None:
        pf = getattr(ctx, "portfolio", None)
        src = getattr(pf, "positions", None) if pf is not None else None
        if src:
            for key, p in src.items():
                d = _pos_to_dict(p, str(key))
                cd = _canon(d["code"])
                if not cd:
                    continue
                out[cd] = d
    return out
def _account():
    """PTrade has no get_account(); account info lives in context.portfolio."""
    ctx = g.get("ctx")
    if ctx is not None:
        pf = getattr(ctx, "portfolio", None)
        if pf is not None:
            total = getattr(pf, "portfolio_value", None)
            cash = getattr(pf, "cash", None)
            pv = getattr(pf, "positions_value", None)
            if total is None:
                try:
                    total = float(cash or 0) + float(pv or 0)
                except Exception:
                    total = None
            if total is not None:
                return {
                    "total_value": float(total),
                    "cash": float(cash or 0),
                    "positions_value": float(pv or 0),
                }
    log.warning("[acct] no context.portfolio, fallback get_account()")
    try:
        return get_account()
    except Exception as e:
        log.warning("[acct] get_account err: %s" % e)
        return None
def _noise_once(cd, kind):
    """同日同类提示只打一次（§八之二 坑2）。"""
    slot = g.setdefault("noise_slot", {})
    day = g.get("today", "")
    key = cd + "|" + kind
    if slot.get(key) == day:
        return False
    slot[key] = day
    return True


def _record_turn(reason, round_trip=False):
    """成交记账（两套口径，勿混）：
    - STATS：逐笔统计，每次委托都计，用于日志与归因；
    - ytd_turns：只计「已完成回合」(round_trip=True)，与 COST_PER_TURN(买+卖综合成本)同口径。
      L1 配置型建仓/再平衡属长线底仓，不计入投机换手预算，避免首次建仓就吃掉整年预算。
    """
    st = g.setdefault("STATS", {"n": 0, "by_reason": {}})
    st["n"] += 1
    st["by_reason"].setdefault(reason, [0, 0.0])
    st["by_reason"][reason][0] += 1
    if round_trip:
        # ★V1.3 D17：L3 日内T 单独记账，不再污染 L2 年度换手预算；用「发生日」入日志，
        # _turnover_ok 按 250 日滚动窗口裁剪，预算可随市场降温自然恢复。
        if "T" in reason:
            g.setdefault("turn_log_l3", []).append(g.get("trade_days", 0))
        else:
            g.setdefault("turn_log_l2", []).append(g.get("trade_days", 0))


def _turnover_ok():
    """L2 波段换手是否还在预算内（★V1.3 D17 改为滚动 250 日窗口）。

    仅约束 L2 波段（L1 配置型再平衡、L3 日内T 均不在此限）。
    历史缺陷：原实现 ytd_turns 只增不减 + 年化外推，导致 L3 日内T 的几十笔回合
    在回测前 30 日就把年度预算烧穿，L2 此后 46% 交易日被长期误锁、[L2-买] 全期 0 笔。
    现改为「L2 回合发生日」入 turn_log_l2，按最近 250 交易日滚动裁剪，
    窗口外的旧回合自动脱落 -> 预算可随市场降温自然恢复，不再一次性锁死。
    样本不足 TURNOVER_MIN_DAYS 时直接放行（不做年化外推）。
    """
    days = max(1, g.get("trade_days", 1))
    if days < TURNOVER_MIN_DAYS:
        return True
    log_l2 = g.get("turn_log_l2", [])
    cutoff = g.get("trade_days", 0) - 250
    log_l2 = [d for d in log_l2 if d > cutoff]   # 滚动窗口裁剪
    g["turn_log_l2"] = log_l2
    annual = len(log_l2)                          # 窗口≈1年，窗口内回合即年化速率
    if annual > MAX_ANNUAL_TURNS:
        if _noise_once("__turnover__", "budget"):
            log.warning("[换手预算] L2 滚动年化 %d 回合 > 上限 %.1f，暂停新开 L2" % (annual, MAX_ANNUAL_TURNS))
        return False
    return True


def _do_sell(code, shares, reason):
    """带 T+1 校验的卖出（仅用 enable_amount）。

    返回实际**已受理**的委托股数（整手）：0 表示被拦下或被平台拒单。
    ★V1.3：改走统一委托出口（盘前入队、盘中执行）；被拒返回 0，调用方据此跳过记账。
    """
    cd = _canon(code)
    poss = _get_positions()
    pos = poss.get(cd)
    if not pos:
        return 0
    avail = pos["enable_amount"]
    if avail <= 0:
        if _noise_once(cd, "t1"):
            log.info("[卖出] %s 可卖为0(T+1未交收)，顺延次日" % code)
        return 0
    qty = _round_lot(min(shares, avail), code)
    if qty <= 0:
        return 0
    if _has_open_order(code):
        if _noise_once(cd, "sell_inflight"):
            log.info("[卖出] %s 已有在途委托，跳过（防重复下单）" % code)
        return 0
    # 目标市值 = (现持股 - 卖出量) * 现价（市价单，value 仅用于换算股数差）
    target_value = (pos["current_amount"] - qty) * (pos["current_price"] or 0)
    oid = _submit_order(code, target_value, reason, side="sell")
    if oid is None:
        log.warning("[卖出被拒] %s 数量%d 原因:%s" % (code, qty, reason))
        _note_reject(code)
        return 0
    return qty


def _sector_of(code):
    """Return sector label for code per SECTOR_OF, or None if unmapped."""
    return SECTOR_OF.get(_suffix(_canon(code)))


def _sector_value(code):
    """Current total market value of all held positions sharing code's sector."""
    sec = _sector_of(code)
    if sec is None:
        return 0.0
    poss = _get_positions()
    s = 0.0
    for cd, d in poss.items():
        if SECTOR_OF.get(_suffix(cd)) == sec:
            s += d.get("current_amount", 0) * (d.get("current_price", 0) or 0)
    return s


def _apply_sector_cap(code, total, add_value):
    """Cap add_value so the sector's post-buy market value <= SECTOR_MAX*total.

    add_value is the intended market-value increment for this buy. Returns the
    allowed increment (0 if the sector is already at/over cap). Unmapped stocks
    skip the constraint but warn once.
    """
    sec = _sector_of(code)
    if sec is None:
        if code not in g.get("sector_warn", set()):
            g.setdefault("sector_warn", set()).add(code)
            log.warning("[sector-cap] %s 未在 SECTOR_OF 配置行业，跳过行业上限" % code)
        return add_value
    sec_cap = total * SECTOR_MAX
    sec_val = _sector_value(code)
    if sec_val >= sec_cap:
        pct = (sec_val / total * 100) if total else 0.0
        log.warning("[sector-cap] %s 行业%s已封顶(%.1f%%/上限%.0f%%)，拒单"
                    % (code, sec, pct, SECTOR_MAX * 100))
        return 0
    room = sec_cap - sec_val
    if add_value <= room:
        return add_value
    log.info("[sector-cap] %s 行业%s减额 %.0f->%.0f" % (code, sec, add_value, room))
    return room


def _do_buy_value(code, target_value, reason="buy"):
    """按目标市值买入（L1 建仓 / L2 波段建仓）。

    五道约束：断路器 / 在途委托 / 单票上限 / 行业上限 / （★V1.3）整手可行性 + 可用现金。
    返回规划并成功提交（或入队）的市值；0 表示被拦下。
    ★V1.3：任何一项预检不通过都返回 0 并说明原因，**绝不把 0 股委托丢给平台**。
    """
    cd = _canon(code)
    if cd in g.get("buy_codes", set()):
        return 0
    if cd in g.get("buy_block", set()):
        return 0
    # 断路器独立拦截所有方向性买入（L3 日内T回补不走此函数，不受影响）
    if g.get("circuit_halt"):
        return 0
    # 换手预算不在此处判定：本函数同时服务 L1 配置型季度再平衡（不受投机换手预算约束）。
    # L2 的换手预算在 _l2_daily 判定，L3 的在 _t_once 判定。
    if _has_open_order(code):
        if _noise_once(cd, "inflight"):
            log.info("[买入] %s 已有在途委托，跳过（防重复下单）" % code)
        return 0
    acct = _account()
    if acct is None:
        return 0
    total = acct.get("total_value", 0) or 0
    if total <= 0:
        return 0
    poss = _get_positions()
    pos = poss.get(cd, {})
    cur_val = pos.get("current_amount", 0) * (pos.get("current_price", 0) or 0)
    cap = total * SINGLE_MAX
    if cur_val + target_value > cap:
        target_value = max(0, cap - cur_val)
    # 行业上限：该笔买入后所属细分行业总市值占比不得超过 SECTOR_MAX
    target_value = _apply_sector_cap(code, total, target_value)
    if target_value <= 0:
        return 0
    # ---- 整手可行性预检（★V1.3 D10）----
    lot_cost = _lot_cost(code)
    if lot_cost <= 0:
        if _noise_once(cd, "nopx"):
            log.warning("[买入] %s 取不到参考价，跳过" % code)
        return 0
    if target_value < lot_cost:
        g.setdefault("unaffordable", set()).add(cd)
        if _noise_once(cd, "unafford"):
            log.warning("[买不起] %s 预算%.0f < 1手成本%.0f（现价%.2f x %d股），跳过"
                        % (code, target_value, lot_cost, _ref_price(code), _lot_min(code)))
        return 0
    # ---- 可用现金预检（★V1.3）：留 2% 缓冲 ----
    cash = acct.get("cash", 0) or 0
    if target_value > cash * 0.98:
        target_value = cash * 0.98
        if target_value < lot_cost:
            if _noise_once(cd, "nocash"):
                log.warning("[现金不足] %s 可用%.0f 不足1手成本%.0f，跳过"
                            % (code, cash, lot_cost))
            return 0
    # ---- 提交委托（统一出口）----
    oid = _submit_order(code, cur_val + target_value, reason, side="buy")
    if oid is None:
        n = _note_reject(code)
        log.warning("[委托被拒] %s 目标%.0f 原因:%s（该标的连续第%d次）"
                    % (code, target_value, reason, n))
        return 0
    if oid == "QUEUED":
        return target_value   # 状态更新延后到 _flush_pending 受理成功后
    _mark_bought(code, reason)
    return target_value
# ============================== 三之二、交易执行与委托管理（★V1.3 新增） ==============================
# 背景：山西/国金首跑"真下单模式"回测中 54 笔委托 100% 被拒，两个根因：
#   ① 17 笔「订单不在交易时间段内，下单失败」—— 交易动作全挂在 before_trading_start(08:30)；
#   ② 37 笔「股票委托数量为0，委托取消」—— 单票预算买不起 1 手。
# 且平台拒单只打 WARNING、不抛异常，导致 try/except 全走成功分支，
#   策略写下"幽灵建仓日"，引发后续 L1 季度再平衡误判"持仓不足5日"而少建一只仓。
def _in_trade_window(now):
    """当前是否处于可下单窗口。

    官方文档：股票回测分钟级策略 handle_data 执行时间为 9:31--15:00；
    日线级策略为 15:00（已到收盘边界，不可下单）。
    这里保守取 [09:31, 14:57)，避开开盘瞬时与收盘集合竞价边界。
    """
    return bool(now) and "09:31" <= now < "14:57"


def _ref_price(code):
    """参考价（整手折算用）：优先盘中价，其次昨收。取不到返回 0。"""
    p, _src = _cur_price(code, g.get("cur_data"))
    if p is not None and p > 0:
        return p
    h = _hist_lists(code, 5, "1d")
    if h is None:
        return 0.0
    closes = h[0]
    return float(closes[-1]) if closes else 0.0


def _lot_cost(code):
    """买入 1 手所需资金（含滑点缓冲）。取不到价返回 0。"""
    px = _ref_price(code)
    if px <= 0:
        return 0.0
    return px * _lot_min(code) * (1.0 + SLIPPAGE)


def _has_open_order(code):
    """是否已有在途委托。

    官方文档明确警告：order_target_value 在交易场景下会因柜台持仓同步时滞（约 6 秒）
    或未成交委托未撤单而**重复下单**，需自行做订单同步管理。
    """
    try:
        oo = get_open_orders(code)
    except Exception:
        return False
    try:
        return bool(oo) and len(oo) > 0
    except Exception:
        return False


def _submit_order(code, target_value, reason="trade", side="buy"):
    """统一委托出口（★V1.3 唯一出口，禁止在回调里直接调 order_target_value）。

    返回：
      'SIGNAL' —— 信号模式（未开启真实交易），视为"模拟成交"
      'QUEUED' —— 盘前（非交易时段），已入队，等 handle_data 09:31 后执行
      order_id —— 交易时段内委托已受理
      None     —— 平台拒单

    ★关键依据（山西证券官方 API 文档）：
      order_target_value(security, value, limit_price=None)
      返回 "Order对象中的id或者None。如果创建订单成功，则返回Order对象的id(str)，
           失败则返回None(NoneType)。"
    """
    if not TRADE_ENABLED:
        log.info("[信号-委托] %s 目标市值%.0f 原因:%s" % (code, target_value, reason))
        return "SIGNAL"
    if not g.get("trade_window_ok"):
        g.setdefault("pending_orders", []).append((code, target_value, reason, side))
        log.info("[排队] %s 目标%.0f 原因:%s（非交易时段，等开盘执行）"
                 % (code, target_value, reason))
        return "QUEUED"
    try:
        oid = order_target_value(code, target_value)
    except Exception as e:
        log.warning("[委托异常] %s 目标%.0f: %s" % (code, target_value, e))
        return None
    if oid is None:
        g["order_rejected"] = g.get("order_rejected", 0) + 1   # ★V1.3 D19 真实拒单数
        return None
    g["order_submitted"] = g.get("order_submitted", 0) + 1     # ★V1.3 D19 真实下单成功数
    return oid


def _note_reject(code):
    """记录一次平台拒单，连续 >=3 次则熔断该标的（★D13）。"""
    g["reject_n"] = g.get("reject_n", 0) + 1
    cd = _canon(code)
    rc = g.setdefault("reject_by_code", {})
    rc[cd] = rc.get(cd, 0) + 1
    if rc[cd] >= 3:
        g.setdefault("buy_block", set()).add(cd)
        log.error("[熔断] %s 连续%d次委托被拒，本轮暂停该标的买入" % (code, rc[cd]))
    return rc[cd]


def _mark_bought(code, reason):
    """仅在委托**确认受理**后才写入"已建仓"状态（★D11 防幽灵持仓）。

    原实现把这几行放在 order_target_value 之后无条件执行，平台拒单时会写下
    不存在的建仓日 buy_day，导致 _held_days 误判，L1 再平衡跳过追买。

    ★V1.4 分层记账：L1 与 L2 可以在**同一标的**上同时持有（L1 底仓 + L2 波段仓），
    因此建仓日与归属标记必须分层写：
      L1 -> owner_layer[cd]="L1" + buy_day[cd]（供 _held_days 用）
      L2 -> l2_buy_day[cd]（供 _l2_held_days 用）；仅当该标的**尚无 L1 底仓**时，
            才把 owner_layer 置为 "L2"（owner_layer 只表达"是否 L1 底仓"）。
    T 回补不在此登记（T 不改变隔夜持仓层级）。
    """
    cd = _canon(code)
    g.setdefault("buy_codes", set()).add(cd)
    g.setdefault("reject_by_code", {})[cd] = 0
    if "T" in reason:
        _record_turn(reason)
        return
    if "L2" in reason:
        g.setdefault("l2_buy_day", {})[cd] = g.get("trade_days", 0)
        if g.setdefault("owner_layer", {}).get(cd) != "L1":
            g["owner_layer"][cd] = "L2"
    else:
        g.setdefault("owner_layer", {})[cd] = "L1"
        g.setdefault("buy_day", {})[cd] = g.get("trade_days", 0)
    _record_turn(reason)


def _flush_pending():
    """★V1.3 交易执行：出队执行盘前算好的委托（每交易日首个可交易 tick 执行一次）。"""
    pend_raw = g.get("pending_orders", [])
    g["pending_orders"] = []
    if not pend_raw:
        return
    # ★V1.3 D21：同标的同日多笔委托合并（取末笔绝对目标市值）。order_target_value 以绝对
    # 市值下单，末笔覆盖前笔；避免「先砍两成再清仓」之类的同 tick 矛盾委托。
    merged = {}
    for code, target_value, reason, side in pend_raw:
        merged[code] = (code, target_value, reason, side)
    pend = list(merged.values())
    log.info("[交易执行] 出队盘前委托 %d 笔(合并后%d) | 可用资金%.0f"
             % (len(pend_raw), len(pend), (_account() or {}).get("cash", 0)))
    ok, rej, skip = 0, 0, 0
    for code, target_value, reason, side in pend:
        if _has_open_order(code):
            skip += 1
            log.info("[交易执行] %s 已有在途委托，跳过（防重复下单）" % code)
            continue
        oid = _submit_order(code, target_value, reason, side)
        if oid is None:
            rej += 1
            n = _note_reject(code)
            log.warning("[委托被拒] %s 目标%.0f 原因:%s（该标的连续第%d次）"
                        % (code, target_value, reason, n))
        else:
            ok += 1
            if side == "buy":
                _mark_bought(code, reason)
            log.info("[成交受理] %s 目标%.0f 原因:%s" % (code, target_value, reason))
    log.info("[交易执行] 完成：受理%d 被拒%d 跳过%d" % (ok, rej, skip))
    if _account() is not None:
        a = _account()
        log.info("[交易执行] 执行后：总资产%.0f 持仓市值%.0f 可用资金%.0f"
                 % (a.get("total_value", 0), a.get("positions_value", 0), a.get("cash", 0)))


def _layer_room(total, ratio, codes, layer="L2"):
    """某层可用额度 = 层目标市值 - 该层**自身**持仓市值。

    ★V1.4 D22：原实现按「标的是否在 codes 池里」统计，把 L1 核心仓的市值也算成
    L2 已用额度 —— 而 L2 池与 L1 池高度重叠，等于 L2 名义 25% 被 L1 抽干。
    实测（2026-03-13）：L2 出信号时日志显示"可用额度 21951"，而 21951 = 75000 - 53049，
    其中 53049 元全是 L1 建的仓。L2 就这样被自己的"池子"锁死，全期 0 回合。
    现改为按层级份额统计：L2 只认 l2_qty 份额，L1 认总持仓减 L2 份额。
    """
    tgt = total * ratio
    poss = _get_positions()
    used = 0.0
    for code in codes:
        cd = _canon(code)
        pos = poss.get(cd)
        if not pos:
            continue
        px = pos.get("current_price", 0) or 0
        l2q = g.get("l2_qty", {}).get(cd, 0)
        if layer == "L2":
            used += l2q * px
        else:
            used += pos["current_amount"] * px - l2q * px
    return max(0.0, tgt - used)


def _redistribute(plan, total, layer="L1", single_cap=None):
    """★V1.3 资金再分配：把「预算买不起 1 手」的标的预算顺延给买得起的标的。

    ★V1.4 新增 single_cap：单票上限（占净值比例）。默认 SINGLE_MAX(10%)，
    L1 调用时传入 _l1_single_cap()（= L1_RATIO / L1 可买标的数），
    以免 L1 把可买标的吃满 10%、把同池的 L2 卫星层挤到没有空间。

    为什么必须做：本金受限（10 万 / 16 只标的）时，被高价股占住的预算若直接作废，
    名义仓位与实际可落实仓位会严重脱节 —— 首跑实测名义 L1 58% 实际只有 23.2%。
    分配受 SINGLE_MAX / SECTOR_MAX 双重约束，迭代 3 轮收敛。

    plan: [(code, value), ...]  ->  返回 [(code, value), ...]（已剔除买不起的标的）
    """
    cap_ratio = SINGLE_MAX if single_cap is None else min(SINGLE_MAX, max(0.0, single_cap))
    keep, pool = [], 0.0
    for code, val in plan:
        lc = _lot_cost(code)
        if lc > 0 and val >= lc:
            keep.append([code, val])
        else:
            pool += val
            log.info("[资金再分配-%s] %s 预算%.0f < 1手成本%.0f，转入公共池"
                     % (layer, code, val, lc))
    if not keep:
        log.warning("[资金再分配-%s] 全部标的均买不起1手（本金不足），本层本轮无法建仓" % layer)
        return []
    if pool <= 1.0:
        return [(c, v) for c, v in keep]
    poss = _get_positions()
    for _round in range(3):
        if pool <= 1.0:
            break
        rooms = []
        for code, val in keep:
            cd = _canon(code)
            pos = poss.get(cd, {})
            cur = pos.get("current_amount", 0) * (pos.get("current_price", 0) or 0)
            r_single = total * cap_ratio - cur - val
            r_sec = total * SECTOR_MAX - _sector_value(code)
            rooms.append(max(0.0, min(r_single, r_sec)))
        tr = sum(rooms)
        if tr <= 1.0:
            log.info("[资金再分配-%s] 剩余单票/行业额度不足，%.0f 元未能分配" % (layer, pool))
            break
        given = 0.0
        for i in range(len(keep)):
            add = pool * rooms[i] / tr
            keep[i][1] += add
            given += add
        pool -= given
        if given <= 1.0:
            break
    log.info("[资金再分配-%s] 保留%d只 合计%.0f 元（公共池剩余%.0f）"
             % (layer, len(keep), sum(v for _c, v in keep), max(0.0, pool)))
    return [(c, v) for c, v in keep]


def _capital_fit_report(total):
    """★V1.3 资本适配自检：启动即暴露「结构性买不起」与「组合最大可落实仓位」。

    这是首跑回测最容易漏掉的结构性问题：名义目标仓位 83%，
    但受「标的单价 x 整手门槛 x 本金规模」三重不匹配限制，实际只能落实 25% 左右，
    而日志上完全看不出异常（只是安静地打了一堆"委托数量为0"）。
    """
    if g.get("fit_reported"):
        return
    g["fit_reported"] = True
    l1_ok, l1_nominal, l1_pool, cheap = 0, 0.0, 0.0, []
    for code in STOCKS:
        val = total * g["L1_W"][code]
        lc = _lot_cost(code)
        l1_nominal += val
        if lc > 0 and val >= lc:
            l1_ok += 1
        else:
            l1_pool += val
            cheap.append("  %s 预算%.0f < 1手成本%.0f（现价%.2f x %d股）"
                         % (code, val, lc, _ref_price(code), _lot_min(code)))
    l1_cap = min(l1_nominal, l1_ok * total * SINGLE_MAX)
    log.info("[资本适配] 本金%.0f | L1 单票预算均值%.0f 元 | 可建仓 %d/%d 只 | 名义%.1f%% 实际可落实%.1f%%"
             % (total, l1_nominal / len(STOCKS), l1_ok, len(STOCKS),
                l1_nominal / total * 100, l1_cap / total * 100))
    l2_per = total * L2_RATIO / len(L2_SET)
    l2_single = total * SINGLE_MAX
    l2_ok, l2_ok2 = 0, 0
    for code in L2_SET:
        lc = _lot_cost(code)
        if lc > 0 and l2_per >= lc:
            l2_ok += 1
        if lc > 0 and l2_single >= lc:
            l2_ok2 += 1
    log.info("[资本适配] L2 等权单票预算%.0f 元 -> 可建仓 %d/%d 只；"
             "按单只上限%.0f 元动态分摊 -> 可覆盖 %d/%d 只 | 名义%.1f%%"
             % (l2_per, l2_ok, len(L2_SET), l2_single, l2_ok2, len(L2_SET), L2_RATIO * 100))
    if cheap:
        log.warning("[资本适配] L1 买不起清单 %d 只，合计预算 %.0f 元（将经资金再分配转给买得起的标的）："
                    % (len(cheap), l1_pool))
        for r in cheap:
            log.warning(r)
    buyable = set()
    for code in STOCKS:
        need = max(total * g["L1_W"][code], l2_per)
        lc = _lot_cost(code)
        if lc > 0 and need >= lc:
            buyable.add(_canon(code))
    # L1 经资金再分配后会集中在可买标的上，同一标的的单票额度被 L1 吃掉后 L2 还剩多少
    if l1_ok > 0:
        # ★V1.4：L1 单票上限主动收敛为「L1_RATIO / 可买标的数」，为 L2 让出单票空间。
        # V1.3 实测 L1 会把可买标的吃到 6.44%（再分配后），L2 仅余 3.56%/只 x 4 只 = 14.2%。
        l1_cap_r = _l1_single_cap(total)
        l1_per = total * l1_cap_r
        ov_n = 0
        for code in L2_SET:
            if _canon(code) in buyable:
                ov_n += 1
        l2_free = max(0.0, l2_single - l1_per) * ov_n
        log.info("[资本适配] ★V1.4 L1 单票上限收敛为%.2f%%（= L1_RATIO/可买%d只），"
                 "为其上重叠的%d只 L2 标的留出单票空间合计%.1f%%（L2 名义目标%.1f%%）"
                 % (l1_cap_r * 100, l1_ok, ov_n, l2_free / total * 100, L2_RATIO * 100))
        if l2_free < total * L2_RATIO * 0.6:
            log.warning("[资本适配] ⚠ L2 单票空间偏紧（%.1f%% < 名义%.1f%% 的 60%%）："
                        "可再下调 L1_RATIO 或提高 SINGLE_MAX。"
                        % (l2_free / total * 100, L2_RATIO * 100))
    nominal = (L1_RATIO + L2_RATIO) * total
    max_pos = min(nominal, len(buyable) * total * SINGLE_MAX)
    utilization = (max_pos / nominal * 100) if nominal > 0 else 0.0
    msg = ("[资本适配-关键] 组合名义目标%.1f%%，可买标的仅%d只 x 单票上限%.0f%% = 最大仓位%.1f%%"
           "，资金利用率仅%.0f%%" % ((L1_RATIO + L2_RATIO) * 100, len(buyable),
                                    SINGLE_MAX * 100, max_pos / total * 100, utilization))
    if utilization < 80:
        log.error(msg)
        log.error("[资本适配-建议] 三条出路：① 放大本金  ② 压缩标的池（剔除高价股）"
                  "  ③ 调高 SINGLE_MAX（当前%.0f%%）以让资金再分配有空间" % (SINGLE_MAX * 100))
    else:
        log.info(msg)


def initialize(context):
    # 注册标的：PTrade 框架要求 set_universe 后，handle_data 的 data 才会带这些股票的行情
    set_universe(STOCKS)
    set_benchmark(INDEX_CODE)
    # 归一化 L1 权重到 L1_RATIO
    raw_sum = sum(L1_RAW.values())
    g["L1_W"] = {}
    for c in STOCKS:
        g["L1_W"][c] = (L1_RAW.get(c, 1) / raw_sum) * L1_RATIO
    g["L2_W"] = {c: L2_RATIO / len(L2_SET) for c in L2_SET}
    g["trade_days"] = 0
    g["last_reb_day"] = -999
    # g["ytd_turns"] 已弃用(V1.3)：改用 turn_log_l2 / turn_log_l3 滚动窗口统计
    g["peak_total"] = 0.0
    g["circuit_halt"] = False
    g["cb_stage"] = 0          # 0/1/2/3 已触发到第几级
    g["mkt_stage"] = 0         # 0/1 市场开关已降级到第几级(1=已因跌破120日线砍过两成)
    g["mkt_above_days"] = 0    # 连续站上120日线的交易日数(用于档位复位确认)
    g["l2_enabled"] = True     # 波段开关(_market_switch 每日按60日线双向刷新)
    g["entry_px"] = {}         # 策略自有成本价（防平台摊薄口径，§十一）
    g["peak_px"] = {}          # L2 移动止盈峰值
    g["buy_day"] = {}          # 实际建仓日(trade_days)，用于 _held_days 真实持有期
    g["buy_codes"] = set()     # 每回调内买入去重(防 order_target_value 重复下单)
    g["ctx"] = None            # 当前 context（账户/持仓来源）
    g["_vwap_cache"] = {}      # VWAP 同分钟缓存
    g["t_rounds"] = {}         # 单票单日T回合数
    g["t_pending"] = {}        # 已卖待回补的股数
    g["noise_slot"] = {}
    g["STATS"] = {"n": 0, "by_reason": {}}
    g["intr_checked"] = False
    g["intr_ok"] = False
    # ---- ★V1.3 新增：交易执行与委托管理状态 ----
    g["pending_orders"] = []      # 盘前算出的委托，等 09:31 后出队执行
    g["day_exec_done"] = False    # 当日交易执行是否已完成
    g["trade_window_ok"] = False  # 当前是否处于可下单窗口
    g["cur_data"] = None          # handle_data 的最新 data（供 _ref_price 取盘中价）
    g["reject_n"] = 0             # 累计被平台拒绝的委托数
    g["reject_by_code"] = {}      # cd -> 连续被拒次数（用于熔断）
    g["buy_block"] = set()        # 因连续被拒而暂停买入的标的
    g["unaffordable"] = set()     # 预算 < 1手成本 的标的
    g["fit_reported"] = False     # 资本适配自检是否已打印
    g["mode_warned"] = False      # 非分钟级周期告警是否已打印
    g["owner_layer"] = {}         # ★V1.3 cd -> "L1"/"L2"：持仓归属层级（D16 防 L2 规则误清 L1 底仓）
    g["last_drift_day"] = -999     # ★V1.3 L1 漂移控制上次执行日
    # ---- ★V1.4 新增：L1/L2 分层份额记账 + 回补链路 ----
    g["l2_qty"] = {}              # ★V1.4 cd -> L2 卫星层持有的股数（与 L1 底仓分层记账）
    g["l2_entry_px"] = {}         # ★V1.4 cd -> L2 份额成本价（L2 自己的止盈/止损基准）
    g["l2_buy_day"] = {}          # ★V1.4 cd -> L2 份额建仓日（不能复用 L1 的 buy_day）
    g["last_refill_day"] = {}     # ★V1.4 cd -> 上次 L1 回补的 trade_days（冷却用）
    g["last_refill_check_day"] = -999   # ★V1.4 上次定期回补检查日
    g["refill_n"] = 0             # ★V1.4 累计回补笔数（自检用）
    g["market_off_days"] = 0      # ★V1.4 L2 被市场开关暂停的交易日数（自检用）
    g["l2_near_signal"] = 0       # ★V1.4 L2 候选"接近信号"累计计数（诊断信号是否过严）
    g["turn_log_l2"] = []        # ★V1.3 L2 回合发生日(trade_days)，_turnover_ok 按 250 日滚动窗口裁剪（D17）
    g["turn_log_l3"] = []        # ★V1.3 L3 日内T 回合发生日，独立计数（D17 不与 L2 共享年度预算）
    g["order_submitted"] = 0     # ★V1.3 实际下发平台的委托数（D19 修正统计口径）
    g["order_rejected"] = 0      # ★V1.3 平台返回 None 的拒单数（D19）
    log.info("[初始化] ★山西PTrade V1.4★ 三层策略 | 标的%d | L1=%.0f%% L2=%.0f%% | TRADE=%s" %
             (len(STOCKS), L1_RATIO * 100, L2_RATIO * 100, TRADE_ENABLED))
    log.info("[初始化] ★V1.4 变更★ ①L1回补对称化(市场开关复位/止盈后/每%d日) ②L2换池%d只中低价股 "
             "③层额度按份额统计 ④L1单票上限=L1_RATIO/可买数 ⑤L3日内T=%s"
             % (L1_REFILL_DAYS, len(L2_SET), "移除" if not INTRADAY_T else "启用"))


# ============================== 五、盘前：L1 再平衡 + L2 信号 + 风控 ==============================
def _dt_now(context):
    """Current datetime: prefer context.blotter.current_dt (doc'd), fallback context.current_dt."""
    blotter = getattr(context, "blotter", None)
    if blotter is not None and hasattr(blotter, "current_dt"):
        return blotter.current_dt
    if hasattr(context, "current_dt"):
        return context.current_dt
    return None

def before_trading_start(context, data):
    g["ctx"] = context
    g["trade_days"] += 1
    dt = _dt_now(context)
    g["today"] = dt.strftime("%Y-%m-%d") if dt else ""
    g["noise_slot"] = {}
    g["t_rounds"] = {}
    g["t_pending"] = {}
    g["buy_codes"] = set()       # reset buy dedup per trading day
    # ---- ★V1.3：盘前只算信号、不下单；委托入队等 09:31 执行 ----
    g["day_exec_done"] = False
    g["trade_window_ok"] = False
    g["pending_orders"] = []
    g["unaffordable"] = set()

    acct = _account()
    if acct is None:
        log.warning("[盘前] 取不到账户，跳过本日")
        return
    total = acct.get("total_value", 0) or 0
    if total <= 0:
        return
    _capital_fit_report(total)   # ★V1.3 启动自检（只打一次）

    # 峰值跟踪
    if total > g["peak_total"]:
        g["peak_total"] = total
    dd = (total - g["peak_total"]) / g["peak_total"] if g["peak_total"] > 0 else 0.0
    log.info("[盘前] 总资产%.0f 峰值%.0f 回撤%.2f%%" % (total, g["peak_total"], dd * 100))

    _circuit_breaker(total, dd)
    _market_switch()

    # L1 季度再平衡（用已完成数据）
    if g["trade_days"] - g["last_reb_day"] >= L1_REBALANCE_DAYS:
        _l1_rebalance(total)
        g["last_reb_day"] = g["trade_days"]

    # ★V1.3 L1 漂移控制：浮盈达标的标的减仓至目标权重（落袋）
    if g["trade_days"] - g["last_drift_day"] >= L1_DRIFT_CTRL_DAYS:
        _l1_drift_control(total)
        g["last_drift_day"] = g["trade_days"]

    # ★V1.4 L1 回补兜底（回补机制的第 3 个触发点）：每 L1_REFILL_DAYS 个交易日检查一次。
    # 另两个触发点：_market_switch 档位复位、_l1_drift_control 止盈减仓后。
    # V1.3 只有「季度再平衡」一个回补机会，60 天窗口一旦错过（07-07 整轮失败）就彻底断档。
    if g["trade_days"] - g.get("last_refill_check_day", -999) >= L1_REFILL_DAYS:
        g["last_refill_check_day"] = g["trade_days"]
        _l1_refill(total, "L1定期回补")

    # L2 波段：日级信号（已完成数据：昨收为末根）
    if not g["circuit_halt"]:
        _l2_daily(total)

    # L1/L2 日级风控扫描（硬止损、移动止盈，用昨收近似；盘中另有 intraday 补刀）
    _daily_risk_scan()


def _l1_rebalance(total):
    log.info("[L1] 季度再平衡启动")
    g["buy_block"] = set()          # 新一轮再平衡，解除上一轮的拒单熔断
    poss = _get_positions()
    plan = []
    for code in STOCKS:
        if g.get("L1_W", {}).get(code, 0) <= 0:
            continue
        cd = _canon(code)
        pos = poss.get(cd)
        # ★V1.4：L1 只对**自己的份额**（总持仓 - L2 卫星份额）做再平衡。
        # 否则会把同一标的上的 L2 波段仓也算进 L1 目标里，L1 减仓时连带清掉 L2。
        l2q = g.get("l2_qty", {}).get(cd, 0)
        px = (pos["current_price"] or 0) if pos else 0
        l1_amt = max(0, pos["current_amount"] - l2q) if pos else 0
        target_val = total * g["L1_W"][code]
        cur_val = l1_amt * px
        delta = target_val - cur_val
        # 再平衡也受 T+1 限制：减仓需可卖量
        if delta > 0:
            # L1 最短持有保护：建仓不足 L1_MIN_HOLD_DAYS 交易日不追买，防过度换手
            if _held_days(cd) < L1_MIN_HOLD_DAYS:
                log.info("[L1] %s 持仓不足%d日，跳过再平衡追买" % (code, L1_MIN_HOLD_DAYS))
            else:
                plan.append((code, delta))
        elif delta < -1e-6:
            sell_qty = _round_lot(-delta / (px or 1), code)
            sell_qty = min(sell_qty, l1_amt)     # ★V1.4 只卖 L1 份额，不碰 L2
            if sell_qty > 0:
                _do_sell(code, sell_qty, "L1再平衡减仓")
        g["entry_px"][cd] = pos["cost_price"] if pos else 0
    # ★V1.3 资金再分配：买不起 1 手的标的预算顺延给买得起的标的，避免名义仓位虚高
    # ★V1.4：单票上限收敛为 L1_RATIO/可买标的数（_l1_single_cap），给 L2 卫星层让出单票空间
    plan = _redistribute(plan, total, "L1", single_cap=_l1_single_cap(total))
    for code, val in plan:
        if _do_buy_value(code, val, "L1建仓") > 0:
            g.setdefault("last_refill_day", {})[_canon(code)] = g.get("trade_days", 0)


def _l1_drift_control(total):
    """★V1.3 L1 漂移控制：把 V1.1 误触发的「止盈」做成正式纪律。

    V1.1 因 D16 缺陷，L2 的 +14%% 止盈规则被错用到 L1 持仓上，等于"涨 14%% 就落袋"，
    恰好吃到 1-4 月上涨、躲过后半段下跌，把 +3.49%% 的好看收益撑了起来。
    V1.3 修掉缺陷后 L1 纯长持，收益回落到 -0.04%%。

    本函数把这种"卖强"行为变成有纪律的规则：单票浮盈>=L1_TRIM_GAIN 时，
    把超过目标权重的部分减仓至目标（保留长线底仓、不空仓），释放现金；
    现金由季度 _l1_rebalance 自动回补到欠配的 L1 标的（买弱），
    形成"卖强买弱"的波动率收割闭环。不做清仓、不破最短持有。
    """
    poss = _get_positions()
    trimmed = 0
    for code in STOCKS:
        cd = _canon(code)
        pos = poss.get(cd)
        if not pos:
            continue
        if g.get("owner_layer", {}).get(cd) != "L1":
            continue
        if _held_days(cd) < L1_MIN_HOLD_DAYS:
            continue
        cost = g["entry_px"].get(cd) or pos["cost_price"]
        if cost <= 0:
            continue
        # ★V1.4：只对 L1 份额做止盈（总持仓 - L2 卫星份额），不误卖 L2 波段仓
        l2q = g.get("l2_qty", {}).get(cd, 0)
        l1_amt = max(0, pos["current_amount"] - l2q)
        if l1_amt <= 0:
            continue
        cur_val = l1_amt * pos["current_price"]
        tgt = total * g["L1_W"][code]
        pnl = pos["current_price"] / cost - 1
        # 显著超配（浮盈达标且市值>目标）才减仓至目标权重，落袋超额收益
        if pnl >= L1_TRIM_GAIN and cur_val > tgt * 1.02:
            sell_val = cur_val - tgt
            qty = _round_lot(sell_val / (pos["current_price"] or 1), code)
            qty = min(qty, l1_amt)               # ★V1.4 不碰 L2 份额
            if qty > 0:
                _do_sell(code, qty, "L1止盈减仓")
                trimmed += 1
                log.info("[L1-止盈] %s 浮盈%.1f%% 减仓至目标权重(现%.0f->目标%.0f)"
                         % (code, pnl * 100, cur_val, tgt))
    if trimmed:
        # ★V1.4：止盈释放的现金**立即**回补欠配标的，不再干等季度再平衡。
        # V1.3 实测：全期止盈 5 次释放现金，但只能等季度（07-07 那次季度回补又整轮失败），
        # 现金就此长期趴在账上 —— 这是「卖强」与「买弱」不对称的第二个来源。
        log.info("[L1-止盈] 本轮回减%d只，立即回补欠配标的（★V1.4 不再等季度）" % trimmed)
        _l1_refill(total, "L1止盈后回补")


def _l2_held_days(cd):
    """★V1.4 L2 卫星份额的持有交易日数（独立于 L1 底仓的 buy_day，防互相污染）。"""
    bd = g.get("l2_buy_day", {}).get(cd)
    if bd is None:
        return 9999
    return g.get("trade_days", 0) - bd


def _l1_single_cap(total):
    """★V1.4 L1 单票上限：按「L1 可买标的数」分摊 L1_RATIO，为 L2 卫星层预留单票空间。

    为什么必须收紧：SINGLE_MAX(10%) 是 L1/L2 共享的硬上限。若 L1 把可买标的吃满 10%，
    与 L1 重叠的 L2 标的就再无空间 —— V1.2/V1.3 资本适配自检已实测
    「L2 仅余单票空间合计 14.2%（L2 名义目标 25.0%）」。改为 L1_RATIO / 可买标的数
    （30 万 x 9 只 = 6.44%）后，每只标的自然留出约 3.56% 给 L2，两层合计仍 <= SINGLE_MAX。
    """
    n = 0
    for code in STOCKS:
        if g.get("L1_W", {}).get(code, 0) <= 0:
            continue
        lc = _lot_cost(code)
        if lc > 0 and total * g["L1_W"][code] >= lc:
            n += 1
    if n <= 0:
        return SINGLE_MAX
    return max(0.02, min(SINGLE_MAX, L1_RATIO / float(n)))


def _l1_refill(total, reason="L1回补"):
    """★V1.4 L1 回补对称化：把欠配的 L1 底仓补足到目标权重（只买不卖）。

    为什么必须有它（V1.3 实测病根）：
      「市场开关跌破 120 日线砍两成」在 V1.3 是**单向**的 —— 全期砍 6 次
      （03-05 / 03-10 / 03-20 / 07-14 / 07-17 / 08-19），而「档位复位」5 次全部
      只清标记、不回补仓位，持仓占比被从 53.5% 一路砸到 32.0%（末日），现金趴到 67%。
      同期 07-07 那次季度再平衡又因「要补的标的恰好买不起 1 手」整轮失败
      （日志原话：[资金再分配-L1] 全部标的均买不起1手），回补窗口直接错过 60 天。
      结果就是「跌了砍、涨了不接」：5-6 月避开下跌确实有效，但 7-8 月指数回升时
      仓位还停在 32%，反弹只吃掉三分之一 —— 这是 V1.3 收益仅 +2.01% 的头号原因。

    触发点（三处）：
      1) _market_switch 档位复位（沪深300 站回 120 日线上方）；
      2) _l1_drift_control 止盈减仓后立刻回补（不再等 60 天季度）；
      3) before_trading_start 每 L1_REFILL_DAYS 个交易日兜底一次。

    约束：只买不卖 / 尊重 L1 最短持有 / 缺口门槛 / 同标的回补冷却 / 单票+行业+现金上限。
    """
    poss = _get_positions()
    today = g.get("trade_days", 0)
    plan = []
    for code in STOCKS:
        cd = _canon(code)
        if g.get("L1_W", {}).get(code, 0) <= 0:
            continue
        own = g.get("owner_layer", {}).get(cd)
        if own is not None and own != "L1":
            continue                      # 只回补归属 L1 的标的
        if _held_days(cd) < L1_MIN_HOLD_DAYS:
            continue                      # 尊重最短持有，防过度换手
        if today - g.get("last_refill_day", {}).get(cd, -9999) < L1_REFILL_COOLDOWN:
            continue                      # 同标的冷却，防每 5 日打碎单
        tgt = total * g["L1_W"][code]
        pos = poss.get(cd)
        l2v = 0.0
        if pos:
            l2v = g.get("l2_qty", {}).get(cd, 0) * (pos.get("current_price", 0) or 0)
        cur = ((pos["current_amount"] * (pos.get("current_price", 0) or 0)) - l2v) if pos else 0.0
        gap = tgt - cur
        if gap < max(_lot_cost(code), tgt * L1_REFILL_MIN_GAP):
            continue
        plan.append((code, gap))
    if not plan:
        return 0
    plan = _redistribute(plan, total, "L1回补", single_cap=_l1_single_cap(total))
    n, amt = 0, 0.0
    for code, val in plan:
        got = _do_buy_value(code, val, reason)
        if got > 0:
            g.setdefault("last_refill_day", {})[_canon(code)] = today
            n += 1
            amt += got
    if n:
        g["refill_n"] = g.get("refill_n", 0) + n
        log.info("[L1-回补] %s：回补 %d 只 合计%.0f 元（本金%.0f）" % (reason, n, amt, total))
    return n


def _l2_daily(total):
    """L2 波段日级信号扫描 + 建仓。

    ★V1.3 改造（原实现 7 条信号 100% 废单）：
      原逻辑每只固定分配 L2_RATIO/len(L2_SET) = 2.5% -> 10 万本金下仅 2500 元，
      除以科创板 200 股门槛或主板 100 股门槛后必然是 0 股。
      现改为"先扫信号、再按当日实际信号数分摊 L2 可用额度"，再经资金再分配兜底。
    """
    if not g.get("l2_enabled", True):
        return
    if not _turnover_ok():
        return
    poss = _get_positions()
    signals = []
    near = 0
    for code in L2_SET:
        h = _hist_lists(code, 30, "1d")
        if h is None:
            continue
        closes, opens, highs, lows, vols = h
        if len(closes) < 21:
            continue
        ma20 = _ma(closes, 20)
        rsi = _rsi(closes, 14)
        if ma20 is None or rsi is None:
            continue
        price = closes[-1]            # 已完成（昨收）
        prev_ma5_vol = _ma(vols[-6:-1], 5) or 1
        vol_ratio = vols[-1] / prev_ma5_vol if prev_ma5_vol > 0 else 1
        cd = _canon(code)
        # ★V1.4：建仓判定基准改为「该标的有没有 **L2 卫星份额**」，而不是「有没有持仓」。
        # 否则 L1 底仓会把同标的的 L2 建仓机会永久堵死（L2 池 8 只全部与 L1 可买标的重叠）。
        l2_held = g.get("l2_qty", {}).get(cd, 0)
        pullback = price <= ma20 * (1 - L2_PULLBACK_PCT)
        quiet = vol_ratio < L2_VOL_RATIO_MAX
        rsi_ok = L2_RSI_LO <= rsi <= L2_RSI_HI
        if l2_held == 0:
            if pullback and quiet and rsi_ok:
                log.info("[L2-买] %s 价%.2f MA20%.2f 量比%.2f RSI%.1f（L1底仓%d股，L2独立建仓）"
                         % (code, price, ma20, vol_ratio, rsi,
                            poss.get(cd, {}).get("current_amount", 0)))
                signals.append((code, price))
            elif pullback and rsi_ok:
                near += 1        # 只差"地量"一项：用于诊断信号阈值卡在哪一条
        # 持仓处理下放 _daily_risk_scan / intraday
    if near:
        g["l2_near_signal"] = g.get("l2_near_signal", 0) + near
    if not signals:
        return
    # ★V1.4：L2 可用额度按**层份额**统计（D22 修复），不再被 L1 底仓抽干
    avail = _layer_room(total, L2_RATIO, L2_SET, "L2")
    per = avail / len(signals)
    log.info("[L2] 当日%d只出信号，L2可用额度%.0f -> 单只%.0f" % (len(signals), avail, per))
    plan = _redistribute([(c, per) for c, _p in signals], total, "L2")
    for code, val in plan:
        got = _do_buy_value(code, val, "L2建仓")
        if got > 0:
            cd = _canon(code)
            ref = 0.0
            for c2, p2 in signals:
                if c2 == code:
                    ref = p2
            px_ref = ref if ref > 0 else (_ref_price(code) or 0)
            add_qty = _round_lot(got / px_ref, code) if px_ref > 0 else 0
            # ★V1.4 分层记账：L2 份额与 L1 底仓分开记，出场时只卖自己那份
            g.setdefault("l2_qty", {})[cd] = g.get("l2_qty", {}).get(cd, 0) + max(0, add_qty)
            g.setdefault("l2_entry_px", {})[cd] = px_ref
            g["entry_px"][cd] = px_ref
            g["peak_px"][cd] = px_ref
            log.info("[L2-建仓] %s L2份额+%d股 成本%.2f（与L1底仓分层记账）"
                     % (code, add_qty, px_ref))


def _daily_risk_scan():
    """L2 卫星仓日级退出（用已完成数据，盘前执行）：目标收益 / 超买 / 移动止盈。

    ★V1.4：改为按 **L2 份额**（l2_qty）出场，不再用整个持仓的 enable_amount。
    V1.3 的 D16 只解决了「池重叠」（L1 持仓不再被 L2 规则误清），但没解决
    「同一标的 L1/L2 双层共存」—— 若 L1 底仓与 L2 波段仓落在同一只股票上，
    按 enable_amount 全卖会把 L1 底仓一起清掉。现在只卖 L2 自己那份。
    """
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        l2q = min(g.get("l2_qty", {}).get(cd, 0), pos["current_amount"])
        if l2q <= 0:
            continue
        cost = g.get("l2_entry_px", {}).get(cd) or g["entry_px"].get(cd) or pos["cost_price"]
        if cost <= 0:
            continue
        if _l2_held_days(cd) < 1:
            continue
        h = _hist_lists(code, 30, "1d")
        if h is None:
            continue
        closes = h[0]
        price = closes[-1]            # 已完成（昨收）
        rsi = _rsi(closes, 14)
        pnl = price / cost - 1
        if price > g["peak_px"].get(cd, 0):
            g["peak_px"][cd] = price
        peak_rt = g["peak_px"].get(cd, cost) / cost - 1
        reason = None
        if pnl >= L2_TAKE_PCT:
            reason = "L2目标止盈+%.0f%%" % (L2_TAKE_PCT * 100)
        elif rsi is not None and rsi >= L2_RSI_SELL:
            reason = "L2超买RSI%.0f" % rsi
        elif peak_rt >= 0.05 and price <= g["peak_px"].get(cd, price) * (1 - L2_TRAIL_PCT):
            reason = "L2移动止盈回撤%.0f%%" % (L2_TRAIL_PCT * 100)
        if reason:
            log.info("[L2-卖] %s %s 浮盈%.2f%%（L2份额%d股，L1底仓保留）"
                     % (code, reason, pnl * 100, l2q))
            q = _do_sell(code, min(l2q, pos["enable_amount"]), reason)
            if q > 0:
                g["l2_qty"][cd] = max(0, l2q - q)
                _record_turn("L2退出", True)


def _held_days(cd):
    """Real holding days: diff from build day (trade_days); no record => long-held (large)."""
    bd = g.get("buy_day", {}).get(cd)
    if bd is None:
        return 9999
    return g.get("trade_days", 0) - bd
def _circuit_breaker(total, dd):
    """三级断路器：自高点回撤 -8% 停所有交易；-12% 砍1/3；-18% 再减半。"""
    if dd <= CB_STAGE3 and g["cb_stage"] < 3:
        g["cb_stage"] = 3
        g["circuit_halt"] = True
        log.warning("[断路器-3级] 回撤%.2f%% 全组合减半(剩余)" % (dd * 100))
        _cut_all(0.5)
    elif dd <= CB_STAGE2 and g["cb_stage"] < 2:
        g["cb_stage"] = 2
        g["circuit_halt"] = True
        log.warning("[断路器-2级] 回撤%.2f%% 砍1/3高位仓" % (dd * 100))
        _cut_all(1.0 / 3.0)
    elif dd <= CB_STAGE1 and g["cb_stage"] < 1:
        g["cb_stage"] = 1
        g["circuit_halt"] = True
        log.warning("[断路器-1级] 回撤%.2f%% 暂停一切新开仓" % (dd * 100))
    # 回升后解除 halt（但不回退已砍仓位）
    if dd > CB_STAGE1 and g["cb_stage"] == 1:
        g["circuit_halt"] = False
        g["cb_stage"] = 0
        log.info("[断路器] 回撤收敛，解除交易暂停")


def _cut_all(frac):
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        qty = _round_lot(pos["enable_amount"] * frac, code)
        if qty > 0:
            _do_sell(code, qty, "断路器减仓")


def _market_switch():
    """沪深300 均线市场开关（双向，可复位）。

    - 短均线(MKT_MA_SHORT=60)下方 -> L2 暂停新开；回到上方 -> L2 恢复新开（每日双向判定）。
    - 长均线(MKT_MA_LONG=120)下方 -> L1 砍两成、档位置 1；
      回到上方连续 MKT_RESET_CONFIRM_DAYS 个交易日后档位复位为 0，再次跌破可再减仓一次。
      ★V1.4 关键修复：复位时**同时执行 _l1_refill 把砍掉的仓位补回来**。
      V1.3 复位只清「档位标记」、不回补仓位，实测全期砍 6 次（03-05/03-10/03-20/07-14/
      07-17/08-19）而只回补 1 次（且靠季度），持仓占比被单向砸到 32.0% —— 这是收益上不去的头号病根。
    - 均线判定取不到数据(None)时维持当前档位，仅打一次降级提示，不误复位。
    """
    below_short = _index_below_ma(INDEX_CODE, MKT_MA_SHORT)
    below_long = _index_below_ma(INDEX_CODE, MKT_MA_LONG)

    # ---- 短均线：L2 开/关（双向）----
    if below_short is None:
        if _noise_once("__mkt__", "nomkt"):
            log.warning("[市场开关] 沪深300 均线数据不足，判定跳过，维持当前档位")
    elif below_short:
        g["l2_enabled"] = False
        g["market_off_days"] = g.get("market_off_days", 0) + 1   # ★V1.4 自检统计
        if _noise_once("__mkt__", "short"):
            log.warning("[市场开关] 沪深300 在%d日线下方 -> L2 暂停新开" % MKT_MA_SHORT)
    else:
        if not g.get("l2_enabled", True):
            log.info("[市场开关] 沪深300 回到%d日线上方 -> L2 恢复新开" % MKT_MA_SHORT)
        g["l2_enabled"] = True

    # ---- 长均线：L1 减仓档位（跌破砍两成；回到上方连续确认后复位）----
    if below_long is None:
        return
    if below_long:
        g["mkt_above_days"] = 0
        if g["mkt_stage"] < 1:
            g["mkt_stage"] = 1
            log.warning("[市场开关] 沪深300 在%d日线下方 -> L1 砍两成" % MKT_MA_LONG)
            poss = _get_positions()
            for cd, pos in poss.items():
                qty = _round_lot(pos["enable_amount"] * 0.2, pos["code"])
                if qty > 0:
                    _do_sell(pos["code"], qty, "市场开关L1减仓")
    else:
        g["mkt_above_days"] = g.get("mkt_above_days", 0) + 1
        if g["mkt_stage"] >= 1 and g["mkt_above_days"] >= MKT_RESET_CONFIRM_DAYS:
            g["mkt_stage"] = 0
            # ★V1.4 核心修复：复位不再只是"清标记"，而是真的把仓位补回来。
            log.info("[市场开关] 沪深300 回到%d日线上方(连续%d日) -> L1 档位复位，执行回补"
                     % (MKT_MA_LONG, g["mkt_above_days"]))
            _acct_m = _account()
            if _acct_m is not None:
                _l1_refill(_acct_m.get("total_value", 0) or 0, "市场开关L1回补")


# ============================== 七、盘中：L3 日内T + intraday 风控 ==============================
def handle_data(context, data):
    # 首根盘后初始化 intr 标记
    g["ctx"] = context
    dt = _dt_now(context)
    now = dt.strftime("%H:%M") if dt else ""
    if not g.get("intr_checked"):
        g["intr_checked"] = True
        p, src = _cur_price(STOCKS[0], data)
        g["intr_ok"] = (src != "none")
        if not g["intr_ok"]:
            log.warning("[口径-降级] handle_data 拿不到盘中价(data=None/snapshot空) -> L3日内T 自动关闭，仅保留日级 L1/L2")
        else:
            log.info("[口径] 盘中价来源=%s，L3日内T 可用" % src)

    g["cur_data"] = data          # ★V1.3：供 _ref_price 取盘中价

    # ---- ★V1.3 交易执行：每日首个可交易 tick 出队执行盘前算好的委托 ----
    # 原实现在 before_trading_start(08:30) 直接下单 -> 平台一律返回
    # "订单不在交易时间段内，下单失败"，54 笔委托 100% 废单。
    if not g.get("day_exec_done"):
        if _in_trade_window(now):
            g["day_exec_done"] = True
            g["trade_window_ok"] = True
            _flush_pending()
        elif now and now >= "14:57" and not g.get("mode_warned"):
            g["mode_warned"] = True
            log.error("[周期告警] handle_data 首根 bar 时点为 %s，不在交易窗口 [09:31,14:57) 内。"
                      "本策略要求**分钟级周期**（回测 9:31-15:00）；当前配置下所有委托都无法执行！"
                      % now)

    if not g["intr_ok"]:
        return  # 无盘中价：日级逻辑已在盘前完成

    # ---- intraday 硬止损补刀（风险类，只设下限 09:45）----
    # ★V1.4：与 L3 开关**解耦** —— L3 日内T 已移除，但 L2 卫星仓的日内硬止损必须保留。
    if now >= "09:45":
        _intraday_hard_stop(data)

    if not INTRADAY_T:
        return  # ★V1.4 L3 日内T 已移除（实测净贡献≈0，仅贡献摩擦）

    # ---- L3 日内T ----
    if "09:45" <= now <= T_CLOSE:
        for code in L3_SET:
            _t_once(code, data, now)
    # 14:50 强制回补未平 T
    if now >= "14:50":
        _t_force_close(data)


def _intraday_hard_stop(data):
    """★V1.4：只对 L2 份额生效（L1 底仓长持、不受日内波动干扰），且只卖 L2 那一份。"""
    poss = _get_positions()
    for cd, pos in poss.items():
        code = pos["code"]
        l2q = min(g.get("l2_qty", {}).get(cd, 0), pos["current_amount"])
        if l2q <= 0:
            continue
        if _l2_held_days(cd) < 1:
            continue  # T+1 当日新仓不卖（§八之二 坑... 风控循环跳过 held<1）
        cost = g.get("l2_entry_px", {}).get(cd) or g["entry_px"].get(cd) or pos["cost_price"]
        if cost <= 0:
            continue
        p, src = _cur_price(code, data)
        if p is None:
            continue
        pnl = p / cost - 1
        if pnl <= -L2_STOP_PCT:
            if _noise_once(cd, "istop"):
                log.warning("[intraday止损] %s 浮亏%.2f%% 现价%.2f 来源%s（L2份额%d股）"
                            % (code, pnl * 100, p, src, l2q))
            q = _do_sell(code, min(l2q, pos["enable_amount"]), "intraday硬止损")
            if q > 0:
                g["l2_qty"][cd] = max(0, l2q - q)
                _record_turn("L2硬止损", True)


def _t_once(code, data, now):
    """L3 日内T 单次触发（★V1.3 D18：统一走 _submit_order 出口，享拒单/熔断/统计一致处理）。

    ★V1.3 D17：开新 T 不再受 L2 年度换手预算(_turnover_ok)约束——L3 日内T 为高频闭环，
    其换手由「单票单日 T_MAX_ROUNDS 回合上限」独立封顶，混入 L2 年度预算只会把 L2 锁死。
    """
    cd = _canon(code)
    poss = _get_positions()
    pos = poss.get(cd)
    if not pos:
        return
    enable = pos["enable_amount"]
    if enable <= 0:
        return
    if g["t_rounds"].get(cd, 0) >= T_MAX_ROUNDS:
        return
    p, src = _cur_price(code, data)
    if p is None:
        return
    vwap = _vwap(code, g.get("today", "") + " " + now)
    if vwap is None or vwap <= 0:
        return
    dev = p / vwap - 1
    cur_val = pos["current_amount"] * pos["current_price"]
    # 有未回补仓位 -> 低位或尾盘买回归（不增隔夜仓；断路器期间也必须回补，避免隔夜裸卖）
    if g["t_pending"].get(cd, 0) > 0:
        if dev <= 0 or now >= "14:45":
            buy_qty = min(g["t_pending"][cd], _round_lot(enable, code))
            if buy_qty > 0:
                oid = _submit_order(code, cur_val + buy_qty * p, "T回补", side="buy")
                if oid is None:
                    _note_reject(code)
                    return
                g["t_pending"][cd] -= buy_qty
                g["t_rounds"][cd] = g["t_rounds"].get(cd, 0) + 1
                _record_turn("T", True)
    else:
        # 开新 T：高位偏离 + edge 够；断路器触发时不开新仓（已有未回补的仍须回补）
        if dev >= T_TRIGGER_PCT and dev >= T_EDGE_MIN and not g.get("circuit_halt"):
            sell_qty = _round_lot(enable * T_MAX_FRAC, code)
            if sell_qty > 0:
                oid = _submit_order(code, cur_val - sell_qty * p, "T开仓", side="sell")
                if oid is None:
                    _note_reject(code)
                    return
                g["t_pending"][cd] = g["t_pending"].get(cd, 0) + sell_qty
                g["t_rounds"][cd] = g["t_rounds"].get(cd, 0) + 1
                _record_turn("T")


def _t_force_close(data):
    """14:50 强制回补未平 T（★V1.3 D18：统一走 _submit_order 出口）。"""
    for cd, qty in list(g.get("t_pending", {}).items()):
        if qty > 0:
            code = _canon_to_code(cd)
            poss = _get_positions()
            pos = poss.get(cd)
            if not pos:
                g["t_pending"][cd] = 0
                continue
            p, _ = _cur_price(code, data)
            if p is None:
                p = pos["current_price"]
            buy_qty = min(qty, _round_lot(pos["enable_amount"], code))
            if buy_qty > 0:
                oid = _submit_order(code, pos["current_amount"] * pos["current_price"] + buy_qty * p,
                                    "T强平", side="buy")
                if oid is None:
                    _note_reject(code)
                    continue
                g["t_pending"][cd] = 0
                _record_turn("T", True)


def _canon_to_code(cd):
    for c in STOCKS:
        if _canon(c) == cd:
            return c
    return _suffix(cd)


def _vwap(code, minute=""):
    """VWAP over last T_VWAP_WIN 1m bars; None if unavailable. Cached per minute."""
    key = code + "|" + minute
    cache = g.get("_vwap_cache", {})
    if key in cache:
        return cache[key]
    try:
        bars = get_history(T_VWAP_WIN, "1m", ["close", "volume"], code)
    except Exception:
        return None
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        return None
    try:
        c = list(bars["close"])
        v = list(bars["volume"])
    except Exception:
        return None
    pv = 0.0
    tot = 0.0
    for i in range(len(c)):
        pv += float(c[i]) * float(v[i])
        tot += float(v[i])
    if tot <= 0:
        return None
    res = pv / tot
    cache[key] = res
    g["_vwap_cache"] = cache
    return res
def after_trading_end(context, data):
    st = g.get("STATS", {"n": 0, "by_reason": {}})
    days = max(1, g.get("trade_days", 1))
    # ★V1.3 D17：回合按层级分别滚动统计
    cutoff = g.get("trade_days", 0) - 250
    l2_log = [d for d in g.get("turn_log_l2", []) if d > cutoff]
    l3_log = [d for d in g.get("turn_log_l3", []) if d > cutoff]
    log.info("[统计] L2回合%d(滚动年化窗口%d) L3回合%d | 综合成本率%.3f" %
             (len(g.get("turn_log_l2", [])), len(l2_log), len(l3_log), COST_PER_TURN))
    for reason, (n, _s) in sorted(st["by_reason"].items()):
        log.info("[统计] %s: %d 笔" % (reason, n))
    # ★V1.3 D19：委托口径改为「实际下发平台 / 被拒 / 有效」，不再用 STATS 记账次数冒充
    sub = g.get("order_submitted", 0)
    rej = g.get("order_rejected", 0)
    log.info("[统计] 委托口径：实际下单%d 被平台拒%d 有效%d%s"
             % (sub, rej, max(0, sub - rej),
                ("  (首日未开盘属正常，若整段回测被拒率>0 需查时点/整手)" if rej else "")))
    # ★V1.4 回补链路自检：把「减仓 vs 回补」的对称性直接摆进日志
    #（V1.3 就是死在这里：砍 6 次只补 1 次，且日志上完全看不出异常）
    log.info("[统计] ★V1.4 回补链路：累计回补%d只 | L2被市场开关暂停%d日 | L2候选接近信号%d次 | L3=%s"
             % (g.get("refill_n", 0), g.get("market_off_days", 0),
                g.get("l2_near_signal", 0), "ON" if INTRADAY_T else "已移除"))
    if g.get("unaffordable"):
        log.warning("[统计] 本日因「预算<1手成本」跳过的标的 %d 只：%s"
                    % (len(g["unaffordable"]), ",".join(sorted(g["unaffordable"]))))
    # 盈亏比自洽检查（§十二）
    log.info("[自检] 止损上限%.0f%% <= 止盈上限%.0f%%*0.5 ? %s" %
             (L2_STOP_PCT * 100, L2_TAKE_PCT * 100, (L2_STOP_PCT <= L2_TAKE_PCT * 0.5)))
