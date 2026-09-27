# -*- coding: utf-8 -*-
# =============================================================================
# 热点融合 v1.5  (PTrade / Python 3.5 兼容)
# 融合对象：热点早盘001 V4.11 / 热点追踪lhb888 v3 / 热点追踪早盘1030 v8.1
# 设计目标：取三家之长、避三家之短 -> 更高收益 + 各市场环境下更平滑
#
# [指纹] ★FUSION v1.5★
#   版本演进 = v1.0(首次真机跑，字段名踩坑全天0成交) -> v1.1(字段白名单+当日价兜底)
#              -> v1.1.1(补逐日[净值]快照 + 空转看门狗 + 取数失败升格error)
#              -> v1.2(分批取数 + 当日价三层兜底 + 001假设定价兜底)
#              -> v1.3(照抄001已验证的取数形态 is_dict=True + fq降级；结构化数组按
#                      dtype.names 解析；日线是否含当日改用 date 列运行时判定)
#              -> v1.4(当日价改为「数值优先 + 每层拒绝==昨收」的四层兜底；date 列
#                      别名补 datetime；接入外挂 sector_map.json 修行业恒空；
#                      量比退化到昨日口径；新增 [粗筛] 漏斗 + [口径] 样本自证行)
#              -> v1.5(净值自算持仓市值修 HALT日计价bug；止损ATR倍1.8/下限6%；赢家
#                      粘性门槛12%+回撤10pp锁利，激活时豁免移动止盈/破均线让利润多跑)
#   热点判定 = 申万行业均值(↑) + 板块强度分(001) + 共振>=2(常开, 改1030默认OFF)
#   选股     = 涨幅[3.5%,6%]/科创[6%,9%] + 量比>=1.5 + 站MA20&MA60 + 形态>=2 + 日内回撤<=4% + 回踩cur>=open
#   买入     = 10:30 + 每日新<=2 + 冷静期2日 + 双护栏 + 强度加权 + 额度回收3轮
#   止损     = ATR自适应 clamp[6%,11%](倍1.8) + 硬止损下限09:45
#   止盈     = +10%减半 + 保本+3% + 移动止盈武装5%/回撤15%(赢家豁免) + 赢家粘性锁利12%+10pp
#   破线     = 破10日线(14:45确认,浮亏才砍) + 破20日线(14:45确认,硬清)
#   大市     = 沪深300<MA20暂停新建 + 中证1000<MA20 halt全停 + 情绪冰点HALF减半
# =============================================================================

import json
import math
# 注意：PTrade 3.5 环境禁用 os / 网络 / f-string / 类型注解

# ----------------------------- 平台字段名容错层 ------------------------------
# 【2026-09-22 实盘回测踩坑】平台 get_history 只认下面这 12 个字段名：
#   open high low close price volume money preclose high_limit low_limit
#   unlimited is_open
# 昨收的字段名是 preclose（无下划线）；写成 pre_close 会被平台直接拒绝并抛
# invalid field 异常。该异常若被上层 try/except 吞掉，表现为「候选池恒为空、
# 全天 0 成交、净值一条直线」——最隐蔽也最致命的一类故障。
PLATFORM_FIELDS = ("open", "high", "low", "close", "price", "volume", "money",
                   "preclose", "high_limit", "low_limit", "unlimited", "is_open")
FIELD_ALIAS = {
    "pre_close": "preclose", "preClose": "preclose", "prev_close": "preclose",
    "last_price": "price", "current_price": "price", "avg_price": "price",
    "vol": "volume", "amount": "money", "turnover": "money",
}


def _norm_fields(fields):
    """逻辑字段名 -> 平台合法字段名。未识别的一律剔除（宁缺毋滥，绝不触发 invalid field）。"""
    if isinstance(fields, str):
        fields = [fields]
    out = []
    for f in fields:
        k = FIELD_ALIAS.get(f, f)
        if k in PLATFORM_FIELDS and k not in out:
            out.append(k)
    return out


def _sub_rows(sub, fields):
    """单只返回值 -> (rows, idxmap)。rows=[[...],...] 每行一个交易日；idxmap={字段名: 列下标}。

    一律【优先按列名】对齐（平台 DataFrame 的列名即请求字段名），取不到列名时才
    退回按请求顺序的位置映射。理由：依赖位置取数会在「字段被平台剔除/顺序变化」时
    静默错列——不报错，但会一直选出错的票。
    """
    if sub is None:
        return None, None
    cols = None
    try:
        c = getattr(sub, "columns", None)
        if c is None and isinstance(sub, dict):
            c = list(sub.keys())
        if c is not None:
            cols = [str(x) for x in list(c)]
    except Exception:
        cols = None

    rows = None
    # ① {字段: [序列]} 形态（部分版本逐字段返回）
    if isinstance(sub, dict) and cols:
        n = 0
        for k in cols:
            v = sub.get(k)
            if isinstance(v, (list, tuple)):
                n = max(n, len(v))
        if n > 0:
            rows = []
            for i in range(n):
                row = []
                for k in cols:
                    v = sub.get(k)
                    if isinstance(v, (list, tuple)) and i < len(v):
                        row.append(v[i])
                    else:
                        row.append(None)
                rows.append(row)
    # ② numpy 结构化数组 —— 本平台 get_history(is_dict=True) 每值的【真实形态】
    #    实测 dtype.names = ('date','open','close','high','low','volume')：
    #      · 含 date 列，且列顺序不保证等于请求顺序 ⇒ 只能【按字段名】取列；
    #      · 旧实现会落进下面的 list(r) 分支：结构化标量不可迭代 → 每行退化成
    #        [记录对象] → 所有列都取不到 → 有效票恒 0，而且不报任何错。
    if rows is None and getattr(sub, "dtype", None) is not None:
        names = getattr(sub.dtype, "names", None)
        if names:
            try:
                rows = []
                for rec in sub:
                    rows.append([rec[k] for k in names])
                cols = [str(k).lower() for k in names]
            except Exception:
                rows = None
        else:
            # 无字段名的普通 2D 数组：按 001 实测口径 (date, open, close, high, low, volume)
            try:
                rows = [list(r) for r in sub]
                cols = ["date", "open", "close", "high", "low", "volume"][:len(rows[0])] if rows else None
            except Exception:
                rows = None
    # ③ DataFrame / list[list] 形态
    if rows is None:
        if isinstance(sub, dict):
            return None, None
        src = getattr(sub, "values", None)
        if src is None:
            src = sub
        try:
            rows = []
            for r in src:
                try:
                    rows.append(list(r))
                except Exception:
                    rows.append([r])
        except Exception:
            return None, None
    idx = {}
    if cols:
        for i, c in enumerate(cols):
            if c not in idx:
                idx[c] = i
        if len(cols) == len(fields):
            for i, f in enumerate(fields):
                idx.setdefault(f, i)
    else:
        for i, f in enumerate(fields):
            idx[f] = i
    return rows, idx


def _col(rows, idxmap, name):
    """按列名取整列 -> list[float]；整列有任一值不可转则返回 None（宁可弃票，不可错位）。"""
    if not rows or not idxmap or name not in idxmap:
        return None
    j = idxmap[name]
    out = []
    for r in rows:
        try:
            out.append(float(r[j]))
        except Exception:
            return None
    return out


def _last_val(rows, idxmap, name):
    """取该列最后一个有效值（昨收等只需末值的场景，容忍前段缺失）。"""
    if not rows or not idxmap or name not in idxmap:
        return None
    j = idxmap[name]
    v = None
    for r in rows:
        try:
            v = float(r[j])
        except Exception:
            continue
    return v


def _col_last(rows, idxmap, name):
    """末值取数（语义同 _last_val，命名对齐 _col 便于阅读）。"""
    return _last_val(rows, idxmap, name)


def _col_first(rows, idxmap, names):
    """按【别名列表】取第一个存在的整列 —— 平台同一语义的列名不唯一。

    【v1.4 修正】本平台结构化数组里日期列叫 `datetime`，不叫 `date`（见 [诊断]
    的"解析列=[...'datetime'...]"）。旧代码硬查 "date" 恒取空 → has_today 恒 False
    → 口径判定失效（并且日志照样写"不含当日"，属假判定，把排查带偏）。
    """
    if not rows or not idxmap:
        return None
    for nm in names:
        if nm in idxmap:
            return _col(rows, idxmap, nm)
    return None


# ===================== 平台取数协议层（v1.3 根因修复） ========================
# 【2026-09-22 第三轮真机回测：分批=27 批，合并后键数仍=0】
#   上一轮把「整池一次请求」改成分批 200 只，仍然全空 —— 说明问题不在批大小。
#   决定性证据来自 001 策略（同一平台、同一接口、真能取到 5183/5645 只）的日志：
#       [数据层] get_history 多证券返回形态 = dict （批量可用，全池一次取）
#       [诊断] get_history 返回 type=OrderedDict mode=dict
#       [诊断] dict 共 200 键     <-- 一批正好 FETCH_CHUNK 只
#       [诊断] 首值 type=ndarray len=70 repr=array([(20260114, 32.14, ...)])
#   结论：本券商必须显式 [is_dict=True] 才返回 {代码: 结构化数组}；不传时返回的
#   形态策略侧不认识，而被旧 _fetch_panel 静默丢弃 —— 于是日志表现为「面板为空
#   dict」，把一个"形态不匹配"误报成"没有数据"，白查了两轮。
#   001 在 2026-09-14 踩过同一族的坑（见其源码 V4.1 数据层补丁：fq='pre' 返回空而
#   不抛异常）。这里照抄其已被 38 个交易日、5183/5645 只验证过的做法：
#     ① 显式传 is_dict=True；② 空结果一律当失败；③ 逐级降级且必须显式告警。
_DS = {"style": None, "style_name": "未探测", "diag": False}

# 候选调用形态，按「001 实测有效」程度排序；探测命中即缓存复用，不再反复试错。
_HIST_STYLES = (
    ("dict+fq", {"fq": "pre", "is_dict": True}),
    ("dict",    {"is_dict": True}),
    ("fq",      {"fq": "pre"}),
    ("plain",   {}),
)


def _has_data(r):
    """返回结果里是否真的含 K 线 —— 空结果（含空 dict）一律视为【失败】。

    ★这是 001 V4.1 的核心修正★：本券商 get_history 在参数不被支持时
    「返回空结果而不抛异常」。若把"无异常"当成"成功"，就会永久锁死在空通道上：
    每批皆空、零成交，且日志一声不吭。
    """
    if r is None:
        return False
    if isinstance(r, dict):
        for v in r.values():
            try:
                rows, _idx = _sub_rows(v, ("close",))
                if rows:
                    return True
            except Exception:
                continue
        return False
    try:
        if getattr(r, "empty", None) is not None:
            return not bool(r.empty)
        return len(r) > 0
    except Exception:
        return bool(r)


def _hist_style(codes):
    """探测并缓存「本平台认」的取数参数形态；只在首次用到时探一次。"""
    if _DS["style"] is not None:
        return _DS["style"]
    probe = list(codes[:2]) if codes else []
    if not probe:
        probe = ["000001.SZ", "600000.SS"]
    for name, kw in _HIST_STYLES:
        try:
            r = get_history(3, "1d", ["close"], probe, **kw)
        except Exception as e:
            log.error("[降级] 取数形态 %s 参数不被支持（%s）→ 试下一档"
                      % (name, repr(e)[:90]))
            continue
        if _has_data(r):
            _DS["style"] = kw
            _DS["style_name"] = name
            log.info("[取数] 形态探测命中 = %s（本次回测所有取数复用此形态）" % name)
            return kw
        log.error("[降级] 取数形态 %s 返回空结果（无异常）→ 视为不可用，试下一档" % name)
    log.error("[取数] 四档形态全部取不到数据 → 平台接口/代码后缀/字段名三者之一有问题，"
              "已退回 plain 形态继续跑（后续报错落在真实业务路径上）")
    _DS["style"] = {}
    _DS["style_name"] = "plain(兜底)"
    return {}


def _hist_call(n, freq, fields, codes):
    """统一取数入口：形态探测 + 空结果判定 + 逐级降级。全策略只此一处直调平台。"""
    if not _has("get_history"):
        return None
    kw = _hist_style(codes)
    try:
        return get_history(n, freq, list(fields), list(codes), **kw)
    except Exception as e:
        _DS["style"] = None      # 缓存形态偶发失效 → 清缓存，下轮重新探测
        log.error("[取数] %s 形态调用失败，已清缓存待重探: %s"
                  % (_DS.get("style_name"), repr(e)[:110]))
        return None


# ----------------------------- 全局参数区 -----------------------------------
SIGNAL_TIME      = "10:30"          # 选股+买入主时点
RISK_TIMES       = ["09:45", "11:20", "13:10", "14:15", "14:45", "14:55"]  # 盘中巡检
TAIL_RISK_TIMES  = ["14:45", "14:55"]   # 结构时点（尾盘确认类）
BREAK_MA_TIME    = "14:45"          # 破均线仅在此时点后确认
NET_VALUE_TIME   = "14:55"          # 逐日净值快照时点（缺此行→回测后拿不到同口径净值曲线）
IDLE_WARN_DAYS   = 5                # 连续空仓 N 日触发 [空转告警]（防"静默不交易"整段回测作废）

# --- 热点/板块 ---
TOP_MAIN_LINES   = 3                # 取前 N 主线（001）
SECTOR_FADE_RATIO = 0.5             # 衰退：涨停率<=前5日均*0.5
SECTOR_FADE_DAYS  = 2               # 连续确认天数（001 修复点）
MIN_SECTOR_ALIGN = 2                # 同行业>=2只才共振（常开，改1030 OFF）
INDUSTRY_MIN_RISE = 0.0             # 申万行业均值>0才列为强势（lhb888）
TOP_INDUSTRY_N  = 10               # 申万行业均值排名前 N（lhb888）

# --- 选股 ---
MIN_HIST_BARS    = 60
MAX_HIST_BARS    = 60               # 面板取数根数（与 MIN_HIST_BARS 同源，勿改名）
# 单次 get_history 的证券数上限。001 日志 [诊断] 明写「dict 共 200 键」（请求 5645
# 只）→ 平台会静默截断批量请求，必须自己分块取数再合并。
FETCH_BATCH      = 200
# ★v1.4 面板字段集★ 在 v1.3 的 5 字段上补回 price / money —— 两者都在平台白名单内，
# 且 1030 策略在同平台的回测里【长期稳定请求它们】(close,price,volume + money 分批)：
#   · price 字段 = 日线末根的「收盘价」快照，是当日价三层兜底的第 2 档输入；
#   · money 字段 = 成交额，直接用平台值比自算（volume×close）少一个未知变量。
PANEL_FIELDS     = ["open", "close", "high", "low", "volume", "price", "money"]
# 日期列别名：本平台实测列名是 datetime（不是 date）。列名一变，口径判定就静默失效。
DATE_COL_ALIASES = ("date", "datetime", "time", "trade_date", "dt")
# 行业归属表（001 同款外挂文件 + 同款候选路径）。缺失则"行业均值+共振"整层失效，
# 表现为 [统计] 里板块强度 Top 全是空字符串 ''。
SECTOR_MAP_FILE  = "sector_map.json"
SECTOR_MAP_PATHS = (
    "sector_map.json",
    "只读/sector_map.json",
    "../只读/sector_map.json",
    "readonly/sector_map.json",
    "user/19264938/files/sector_map.json",
    "/user/19264938/files/sector_map.json",
)
MINUTE_BARS_TODAY = 61              # 10:30 时当日 1 分钟线根数（09:30~10:30）；改扫描时点须同步改
ASSUME_ENTRY_PREMIUM = 0.010        # 当日价取不到时的保守假设加成（001 口径：昨收×1.010）
DIAG_ONCE        = True             # 首个交易日输出一次 [诊断]，之后不再刷屏
MIN_AMOUNT       = 4e8              # 成交额下限（3亿~5亿折中）
MIN_VOL_RATIO    = 1.5
REQUIRE_ABOVE_MA20 = True
REQUIRE_ABOVE_MA60 = True
MA_SHAPE_MIN     = 2                # 均线多头形态阈值（lhb888）
INTRADAY_PULLBACK_MAX = 0.04        # 日内回撤上限（lhb888）
ALLOW_LIMIT_UP_BUY  = False
REQUIRE_NO_ST    = True
DETAIL_POOL      = 60               # 细评池上限
MAX_CANDIDATES   = 12

# --- 买入/仓位 ---
POSITION_VALUE_RATIO = 0.17
STRENGTH_EXP     = 1.6
MAX_SINGLE_RATIO = 0.20            # ★V1.6 25%→20%：回测 30/72 笔超 25%，最差日 -3.70% 由集中度引发
MAX_POSITIONS    = 6
MAX_NEW_PER_DAY  = 2                # 放宽001的1笔，避免踏空；仍控频
COOL_DOWN_DAYS   = 2                # 比001的3日更短
CASH_BUFFER      = 0.10

# --- ★V1.6 新增：闸门上限 / 复位回补 / 科创板 / 残仓对账 ★---
HALT_MAX_WEIGHT     = 0.30          # HALT 期持仓市值/总资产 上限（v1.5 为清零式禁建，改为不清零）
PAUSE_MAX_WEIGHT    = 0.60          # PAUSE 期持仓上限
GATE_MIN_BUY_VALUE  = 5000          # 上限余量低于此值不再开新仓（防碎单）
RESET_RECOVER_DAYS  = 5             # 复位(HALT/PAUSE→NORMAL)后分批回补窗口（交易日）
RESET_MAX_NEW_PER_DAY = 3           # 回补期内每日新开仓上限（常态 MAX_NEW_PER_DAY=2）
KCB_SIZE_FACTOR     = 0.5           # 688 建仓金额 ×0.5（敞口折半：止损穿透与残仓事故均集中 688）
ATR_STOP_MAX_PCT_KCB = 0.09         # 688 硬止损 ATR clamp 上限（常规 11%，688 收紧至 9%）
BUY_FLOOR_PCT    = 0.015           # 走弱不接刀（001双护栏）
BUY_PREMIUM_PCT  = 0.03            # 涨过头不追（001双护栏）
BUDGET_RECYCLE   = True
RECYCLE_ROUNDS   = 3
REINVEST_ON_SELL = False            # 砍仓额度留次日（1030）

# --- 止损 ---
ATR_N            = 14
ATR_STOP_MULT    = 1.8            # 调优：略降倍数贴近真实波动，减少窄幅震荡被止损
ATR_STOP_MIN_PCT = 0.06            # 下限6%（v1.4=5%，略放宽避免微幅下挫即砍）
ATR_STOP_MAX_PCT = 0.11            # 上限11%（放宽001的6%减震）
STOP_TIME_FLOOR  = "09:45"          # 硬止损最早时点（避集合竞价噪声）
STOP_MODE        = "atr"           # 亦可 "fixed"
FIXED_STOP_PCT   = 0.05

# --- 止盈 ---
PARTIAL_TAKE_PCT = 0.10            # +10%减半（1030）
PARTIAL_TAKE_RATIO = 0.5
BREAKEVEN_GUARD  = 0.03            # 浮盈>=3%锁保本（lhb888）
TRAIL_ARM_PCT    = 0.05            # 移动止盈武装（001）
TRAIL_PCT        = 0.15            # 峰值回撤15%清仓（001）
TP_FULL_PCT      = 0.30            # +30%全清（lhb888）

# --- 破均线 ---
RETREAT_MA_FAST  = 10              # 破10日线（浮亏才砍）
RETREAT_MA_HARD  = 20              # 破20日线（硬清）

# --- 时间/赢家 ---
MAX_HOLD_DAYS    = 5               # 亏损持仓>=5日退出
WINNER_EXEMPT_PCT   = 0.12         # 浮盈>=15%进入赢家粘性（001 V4.10）
WINNER_GIVEBACK_PCT= 0.10          # 自峰值回撤>=8pp清仓（百分点尺，更稳）
WINNER_MAX_HOLD  = 30             # 赢家最长持有天数

# --- 大市择时/避险 ---
REGIME_BROAD     = "000300.SS"     # 沪深300（宽基，暂停新建用）
REGIME_SMALL     = "000852.SS"     # 中证1000（与持仓风格匹配，halt用）
REGIME_MA        = 20
REGIME_MA_FAST   = 5
MARKET_ZT_FLOOR  = 25              # 池内涨停<25 -> 情绪冰点HALF（1030）
SENTIMENT_HALF_FACTOR = 0.5        # HALF模式预算系数

# --- 换手熔断 ---
MAX_ANNUAL_TURNS = 25
TURNOVER_WINDOW_DAYS = 60
MAX_BUYS_PER_MONTH = 20

ALLOW_BOARDS = ("SS", "SZ")
BROAD_TAG_BLACKLIST = ()           # 可扩展宽口径标签


# ----------------------------- 工具函数 -------------------------------------
def _suffix(code):
    if "." in code:
        return code
    if code.startswith("6") or code.startswith("9"):
        return code + ".SS"
    return code + ".SZ"


def _pure(code):
    return code.split(".")[0]


def _board(code):
    c = _pure(code)
    if c.startswith("8") or c.startswith("4"):
        return "BJ"
    if c.startswith("68"):
        return "KCB"
    if c.startswith("30"):
        return "CYB"
    return "MB"


def _is_kcb(code):
    return _board(code) == "KCB"


def _limit_pct(code):
    b = _board(code)
    if b == "KCB":
        return 0.20
    if b == "BJ":
        return 0.30
    return 0.10


def _gain_range(code):
    # 折中：比001[4,5]宽（防空仓），与lhb888/1030同档
    b = _board(code)
    if b == "KCB":
        return (0.06, 0.09)
    if b == "CYB":
        return (0.06, 0.09)
    return (0.035, 0.06)


def _flatten(vals):
    """把 get_history 的 .values 展平成一维浮点序列。

    多码+单字段时 PTrade 常返回 [[v],[v],...]（每行一列），直接 sum() 会
    触发 'int + list' 异常。这里统一兼容 标量 / 单元素行 / 多列行。
    """
    out = []
    if vals is None:
        return out
    for v in vals:
        try:
            if isinstance(v, (list, tuple)):
                out.append(float(v[0]))
            else:
                out.append(float(v))
        except Exception:
            continue
    return out


def _ma(vals, n):
    if vals is None or len(vals) < n:
        return None
    seq = _flatten(vals[-n:])
    if len(seq) < n:
        return None
    return sum(seq) / float(n)


def _mean(xs):
    if not xs:
        return 0.0
    return sum(xs) / float(len(xs))


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    m = len(s)
    if m % 2 == 1:
        return s[m // 2]
    return (s[m // 2 - 1] + s[m // 2]) / 2.0


def _has(name):
    try:
        return name in globals() or callable(globals().get(name))
    except Exception:
        return False


def _warn(msg):
    try:
        log.warning(msg)
    except Exception:
        pass


def _warn_once(key, msg):
    g = _G()
    slot = g.setdefault("noise_slot", {})
    today = g.get("today", "")
    d = slot.setdefault(key, {})
    if d.get("day") == today:
        return
    d["day"] = today
    _warn(msg)


def _days_between(a, b):
    # a,b: 'YYYY-MM-DD'，返回日历日差（近似交易日用）
    try:
        ya, ma, da = [int(x) for x in a.split("-")]
        yb, mb, db = [int(x) for x in b.split("-")]
        import datetime
        da_dt = datetime.date(ya, ma, da)
        db_dt = datetime.date(yb, mb, db)
        return abs((db_dt - da_dt).days)
    except Exception:
        return 999


# ----------------------------- 平台接口封装 --------------------------------
def _G():
    return globals().get("g", {})


def _hist(code, count, fields):
    """单只批量取数：get_history(count, freq, field, [code]) -> 该只的 DataFrame

    注意：PTrade 的 get_history 在 securities 传入【列表】时恒返回 dict
    （key=标的）。本函数统一把单只的 DataFrame 抽取出来返回，避免上层
    _hist_closes / _stop_pct 误把整个 dict 当 DataFrame 用（raw.values 会
    变成 dict_values 导致取序列失败 -> ATR自适应止损与破均线出场双双失效）。
    同时兼容平台对单只也直接返回 DataFrame 的情形。
    """
    try:
        if not _has("get_history"):
            return None
        fields = _norm_fields(fields)
        if not fields:
            return None
        raw = _hist_call(count, "1d", fields, [_suffix(code)])
        if raw is None:
            return None
        if isinstance(raw, dict):
            if _suffix(code) in raw:
                return raw[_suffix(code)]
            if _pure(code) in raw:
                return raw[_pure(code)]
            vals = list(raw.values())
            return vals[0] if vals else None
        return raw
    except Exception as e:
        _warn("[hist] %s 取数失败: %s" % (code, e))
        return None


def _account(context):
    # PTrade 无 get_account；读 context.portfolio
    try:
        pf = context.portfolio
        return float(pf.portfolio_value), float(pf.cash)
    except Exception as e:
        _warn("[acct] %s" % e)
        return 0.0, 0.0


def _get_positions(context):
    """兼容 dict[str:Position] 与 list[dict] 两种形态（防001/lhb888同源缺陷）"""
    try:
        poss = context.portfolio.positions
    except Exception:
        try:
            poss = get_positions()
        except Exception:
            return []
    if isinstance(poss, dict):
        out = []
        for k, v in poss.items():
            out.append(_pos_to_dict(v, k))
        return out
    if isinstance(poss, list):
        out = []
        for p in poss:
            out.append(_pos_to_dict(p, ""))
        return out
    return []


def _pos_to_dict(p, code_hint):
    d = {}
    if isinstance(p, dict):
        d = dict(p)
        if not code_hint and "stock_code" in d:
            code_hint = d["stock_code"]
        if not code_hint and "sid" in d:
            code_hint = d["sid"]
    else:
        for nm in ("sid", "stock_code", "code"):
            if hasattr(p, nm):
                code_hint = getattr(p, nm)
                break
        for nm in ("amount", "current_amount", "enable_amount", "cost_basis",
                  "last_sale_price", "last_price", "cost_price", "avg_price"):
            if hasattr(p, nm):
                d[nm] = getattr(p, nm)
    d["_code"] = _suffix(code_hint) if code_hint else ""
    return d


def _pos_field(p, names):
    for nm in names:
        if nm in p and p[nm] is not None:
            try:
                return float(p[nm])
            except Exception:
                return 0.0
    return 0.0


def _pick(obj, names):
    """从对象或 dict 中取第一个存在字段并转 float；取不到返回 None。"""
    if obj is None:
        return None
    for k in names:
        v = None
        try:
            if isinstance(obj, dict):
                v = obj.get(k)
            else:
                v = getattr(obj, k, None)
        except Exception:
            v = None
        if v is not None:
            try:
                return float(v)
            except Exception:
                continue
    return None


# ============ 当日价读取（v1.4 根因修复：数值优先，绝不只认字段名）============
def _num(v):
    """转正 float；非数或 <=0 一律 None。"""
    try:
        f = float(v)
    except Exception:
        return None
    return f if f > 0 else None


def _bar_price(obj, prev_close=None):
    """从一个 Bar 对象取「当日价」——按候选顺序挑【不等于昨收】的第一个值。

    【为什么数值优先、且要过滤昨收】2026-09-22 实测（1030 日志第 15 行原文）：
        样本 000001.SZ 昨收=11.13 data价=11.34 price字段=11.13 分钟close=11.13
    即：同一只票，data 对象【数值本身】= 当日价 11.34，而按 `price` 字段名读到的是
    昨收 11.13。v1.3 的 _cur_bar 只按字段名读（price/last_px/close）→ 当日价恒=昨收
    → pct 恒 0 → 涨幅区间 [3.5%,6%] 全灭 → 粗筛恒空 → 全天 0 成交。
    这里不仅要求"先试数值"，还要逐候选与昨收比对：只有明显不等于昨收的值才算
    "当日价"，否则继续往下找（找不到就交给上层走假设定价）。
    """
    if obj is None:
        return None
    eps = 1e-9
    cands = []
    v = _num(obj)                      # ① Bar 可转 float → 数值就是当日价（1030 实证）
    if v:
        cands.append(v)
    for f in ("close", "price", "last_price", "lastPrice", "last_px", "new_price"):
        try:
            v = _num(obj.get(f)) if isinstance(obj, dict) else _num(getattr(obj, f, None))
        except Exception:
            v = None
        if v:
            cands.append(v)
    fn = getattr(obj, "values", None)
    if callable(fn):
        try:
            for x in list(fn()):
                v = _num(x)
                if v:
                    cands.append(v)
        except Exception:
            pass
    for v in cands:
        if prev_close and prev_close > 0:
            if abs(v - prev_close) > eps:
                return v
        else:
            return v
    return None


def _data_price(data, code, prev_close=None):
    """handle_data 的 data 对象 -> 当日价；取不到返回 None。

    入口组合照抄 1030（同平台、同回测配置，实测 5098/5201 只拿得到当日价）：
      数值(data.get(code)) -> 数值(data[code]) -> data.current(code, field)
      -> data.get_price(...)
    每一档都用 prev_close 过滤掉"其实是昨收"的值 —— 因为本平台【按字段名】取到的
    很可能是昨收，而数值才是当日价。
    """
    if data is None:
        return None
    keys = (_suffix(code), _pure(code))
    # ① 数值优先：data.get(code) / data[code]
    for k in keys:
        obj = None
        try:
            if hasattr(data, "get"):
                obj = data.get(k)
        except Exception:
            obj = None
        if obj is None:
            try:
                obj = data[k]
            except Exception:
                obj = None
        v = _bar_price(obj, prev_close)
        if v:
            return v
    # ② 方法式入口
    for m in ("current", "get_price"):
        fn = getattr(data, m, None)
        if not callable(fn):
            continue
        for k in keys:
            for f in ("price", "close", "last_price", "lastPrice"):
                try:
                    v = _num(fn(k, f))
                except Exception:
                    v = None
                if v and (not prev_close or abs(v - prev_close) > 1e-9):
                    return v
    return None


def _today_price(data, code, prev_close, daily_price, minute_price):
    """当日价四层兜底 -> (价格, 来源标签)。

    【v1.4 铁律】每一层都要做「与昨收相等就作废」的 guard（1030 源码 1186/1188 行
    的已验证写法）。没有这道闸，本平台会把「昨收」当「当日价」交给你，而 pct 恒 0
    不会报任何错 —— v1.3 全天 0 成交就是栽在这里。
    四层：data 对象 -> 日线 price 字段 -> 分钟线 -> 保守假设定价。
    最后一层【不弃票】（001 口径），保证回测不至全池为空。
    """
    eps = 1e-9
    if prev_close and prev_close > 0:
        for v, tag in ((_data_price(data, code, prev_close), "data"),
                       (_num(daily_price), "price字段"),
                       (_num(minute_price), "分钟线")):
            if v and abs(v - prev_close) > eps:
                return v, tag
        return prev_close * (1.0 + ASSUME_ENTRY_PREMIUM), "假设定价"
    return None, "无昨收"


def _cur_bar(data, code, snap=None):
    """取【当日】快照：价/开/高/低/量。

    口径说明（v1.3 已改为运行时判定，不再假设）：本平台日线【是否含当日 bar】
    与策略时点相关 —— 001 日志实测含当日（故其有 _strip_today），1030 源码注释
    写不含当日。两者矛盾，所以 scan_market 改为读 date 列自行判定：
      · 含当日 → 当日价直接用末根，根本不会走到这个函数；
      · 不含当日 → 末根=昨收，当日价/开/高/量必须另找来源，优先级：
        handle_data 的 data 对象 -> 批量 get_snapshot -> 调用方再兜分钟线。
    取不到时由调用方走「保守假设定价」，绝不用昨收冒充当日价（否则涨幅恒为 0，
    静默选出全错的一批票）。
    """
    code_s = _suffix(code)
    out = {"price": None, "open": None, "high": None, "low": None, "volume": None}
    obj = None
    if data is not None:
        try:
            obj = data.get(code_s) if hasattr(data, "get") else None
            if obj is None and hasattr(data, "__getitem__"):
                obj = data[code_s]
        except Exception:
            obj = None
    for src in (obj, snap):
        if src is None:
            continue
        if out["price"] is None:
            out["price"] = _pick(src, ("price", "last_px", "last_price", "close"))
        if out["open"] is None:
            out["open"] = _pick(src, ("open", "open_price", "today_open"))
        if out["high"] is None:
            out["high"] = _pick(src, ("high", "high_price", "today_high"))
        if out["low"] is None:
            out["low"] = _pick(src, ("low", "low_price", "today_low"))
        if out["volume"] is None:
            out["volume"] = _pick(src, ("volume", "vol", "business_amount"))
    return out


def _snap_map(pool):
    """批量实时快照 -> {code: {..}}，失败或不可用返回 {}。

    注意：PTrade **回测**环境不支持 get_snapshot（平台会直接打
    「回测不支持get_snapshot函数」），所以回测里本函数恒为空，
    当日价只能靠 data 快照或批量分钟线 —— 别把快照当唯一来源。
    """
    out = {}
    if not _has("get_snapshot"):
        return out
    try:
        snap = get_snapshot(list(pool))
    except Exception:
        return out
    if not snap:
        return out
    try:
        for code, v in snap.items():
            out[str(code)] = v
            out[_pure(code)] = v
    except Exception:
        pass
    return out


def _split_frame(part, chunk):
    """MultiIndex 列 DataFrame -> {6位code: 该只的子DataFrame}；不适用返回 {}。

    本平台传 is_dict=True 时返回 dict，走不到这里；但若某版本忽略 is_dict 而退回
    多证券 DataFrame，这一步是唯一能救回来的地方——否则整批被当作"无法识别"作废。
    """
    cols = getattr(part, "columns", None)
    if cols is None:
        return {}
    out = {}
    try:
        cl = list(cols)
        if getattr(cols, "nlevels", 1) < 2 or not cl:
            return {}
        codeset = set(_pure(c) for c in chunk)
        hit = {}
        for lev in (0, 1):
            s = set()
            for c in cl:
                try:
                    s.add(_pure(c[lev]))
                except Exception:
                    pass
            hit[lev] = len(s & codeset)
        lv = 0 if hit[0] >= hit[1] else 1
        for c in cl:
            key = _pure(c[lv])
            if not key:
                continue
            out.setdefault(key, []).append(c)
        res = {}
        for key, clist in out.items():
            try:
                res[key] = part[clist]
            except Exception:
                pass
        return res
    except Exception:
        return {}


def _fetch_panel(fields, codes, count=None, diag=False):
    """分批 get_history（'1d'）并合并 -> (dict{code: sub}, 批次数)。

    v1.3 两条硬纪律：
      ① 走 _hist_call（带形态探测 + is_dict=True + fq 降级），不再裸调 get_history；
      ② 无论返回什么形态，【要么被识别、要么显式报错】—— 旧版把"形态不匹配"
         静默当成"没有数据"，把排查方向带偏了两整轮，这是不可再犯的错。
    分批保留（FETCH_BATCH=200）：单批过大平台会静默截断，且单批失败不波及其它批。
    """
    out = {}
    nbatch = 0
    total = len(codes)
    n = MAX_HIST_BARS + 5 if count is None else count
    i = 0
    while i < total:
        chunk = list(codes[i:i + FETCH_BATCH])
        i += FETCH_BATCH
        part = _hist_call(n, "1d", fields, chunk)
        nbatch += 1
        if part is None:
            if nbatch <= 2:
                log.error("[取数] 第 %d 批（%d 只）返回 None（形态=%s）"
                          % (nbatch, len(chunk), _DS.get("style_name")))
            continue
        # 形态 1：{code: sub}（本平台 is_dict=True 的正常形态，001 已实测）
        if isinstance(part, dict):
            for k in list(part.keys()):
                out[k] = part[k]
                kk = _pure(k)
                if kk:
                    out[kk] = part[k]
            continue
        # 形态 2：MultiIndex 列 DataFrame -> 按代码拆
        sp = _split_frame(part, chunk)
        if sp:
            for k, v in sp.items():
                out[k] = v
            continue
        # 形态 3：按请求顺序返回的序列
        if isinstance(part, (list, tuple)):
            for j, v in enumerate(part):
                if j < len(chunk):
                    out[chunk[j]] = v
            continue
        # 形态 4：认不出来 —— 必须吼出来（旧版就是在这里静默丢光的）
        if nbatch <= 2:
            log.error("[取数] 第 %d 批返回了无法识别的形态 type=%s repr=%s → 本批作废"
                      % (nbatch, type(part).__name__, repr(part)[:160]))
            log.error("[取数] 把这行发我，需要为这个形态补一个适配分支（别改批大小，没用）")
    if diag and total and not _DS["diag"]:
        _DS["diag"] = True
        _diag_panel(out, codes, fields, nbatch)
    return out, nbatch


def _minute_map(fields, codes, bars=MINUTE_BARS_TODAY):
    """批量分钟线 -> {code: {price/open/high/low/volume}}，聚合成「当日至今」一根 bar。

    回测不支持 get_snapshot，但**分钟线可得**（001 源码注释：日线不含当日 bar，
    分钟线可得）。因此这是回测里唯一能拿到「当日价」的批量通道。逐只调用太慢
    （5000+ 次），必须分批。

    聚合口径（重要）：
      price  = 最后一根分钟 close（当日最新价）
      open   = 第一根分钟 open（当日开盘）
      high/low = 窗口内 max/min
      volume = 窗口内 sum ⇒ 即「当日累计成交量」，可直接与 5 日均量比量比
    取 bars 根（默认 61：10:30 时当日恰好 61 根 1 分钟线，不多不少不漏到昨日）。
    若扫描时点不是 10:30，bars 需同步调整，否则窗口会混入昨日尾盘。
    """
    out = {}
    if not _has("get_history"):
        return out
    i = 0
    total = len(codes)
    while i < total:
        chunk = list(codes[i:i + FETCH_BATCH])
        i += FETCH_BATCH
        raw = _hist_call(bars, "1m", fields, chunk)
        if not raw or not isinstance(raw, dict):
            continue
        for code, sub in raw.items():
            rows, idx = _sub_rows(sub, fields)
            if not rows:
                continue
            bar = {}
            price = _last_val(rows, idx, "close")
            if price is None:
                price = _last_val(rows, idx, "price")
            op = _last_val(rows, idx, "open")
            hi = _max_val(rows, idx, "high")
            lo = _min_val(rows, idx, "low")
            if price is not None:
                bar["price"] = price
            if op is not None:
                bar["open"] = op
            if hi is not None:
                bar["high"] = hi
            if lo is not None:
                bar["low"] = lo
            vsum = _sum_val(rows, idx, "volume")
            if vsum is not None:
                bar["volume"] = vsum
            if bar:
                out[str(code)] = bar
                out[_pure(code)] = bar
    return out


def _max_val(rows, idxmap, name):
    if not rows or not idxmap or name not in idxmap:
        return None
    j = idxmap[name]
    v = None
    for r in rows:
        try:
            x = float(r[j])
        except Exception:
            continue
        v = x if v is None else (x if x > v else v)
    return v


def _min_val(rows, idxmap, name):
    if not rows or not idxmap or name not in idxmap:
        return None
    j = idxmap[name]
    v = None
    for r in rows:
        try:
            x = float(r[j])
        except Exception:
            continue
        v = x if v is None else (x if x < v else v)
    return v


def _sum_val(rows, idxmap, name):
    if not rows or not idxmap or name not in idxmap:
        return None
    j = idxmap[name]
    s = 0.0
    got = False
    for r in rows:
        try:
            s += float(r[j])
            got = True
        except Exception:
            continue
    return s if got else None


def _diag_panel(panel, pool, fields, nbatch):
    """一次性 [诊断]：把「取数形态 + 为什么有效票是 0」一次查清，不靠猜。

    模仿 001 已被验证有效的做法（`[诊断] get_history 返回 type=...` /
    `[诊断] dict 共 N 键` / `[诊断] 首值 type=... repr=...`），并额外打印
    「解析出的列名」与「解出行数」—— 这两项是区分"没取到"与"取到了但解不出"的关键。
    """
    try:
        log.info("[诊断] 池=%d 分批=%d 批 形态=%s 合并后键数=%d(去重后代码数=%d) | 请求字段=%s"
                 % (len(pool), nbatch, _DS.get("style_name"),
                    len(panel) if hasattr(panel, "__len__") else -1,
                    len(set(_pure(k) for k in panel.keys())) if isinstance(panel, dict) else -1,
                    list(fields)))
        ks = list(panel.keys()) if isinstance(panel, dict) else []
        log.info("[诊断] 面板 keys 示例=%s" % (ks[:5] if ks else "空"))
        if ks:
            sub = panel[ks[0]]
            rows, idx = _sub_rows(sub, fields)
            try:
                ln = len(sub)
            except Exception:
                ln = -1
            log.info("[诊断] 首值 type=%s len=%s 解析列=%s 解出行数=%s"
                     % (type(sub).__name__, ln,
                        sorted(idx.keys()) if idx else None,
                        len(rows) if rows else 0))
            try:
                rep = repr(sub)[:240]
            except Exception:
                rep = "<repr失败>"
            log.info("[诊断] 首值 repr=%s" % rep)
        else:
            log.info("[诊断] 合并后面板为空 —— 形态=%s 四档已用尽；"
                     "下一步查 codes 元素是否带 .SS/.SZ 后缀" % _DS.get("style_name"))
    except Exception as e:
        log.error("[诊断] 诊断输出本身失败: %s" % e)



def _minute_last(code):
    """分钟线兜底：取当日最后一根分钟收盘价（日线不含当日时的最后手段）。"""
    try:
        if not _has("get_history"):
            return None
        raw = _hist_call(1, "1m", ["close"], [_suffix(code)])
        if raw is None:
            return None
        if isinstance(raw, dict):
            sub = raw[_suffix(code)] if _suffix(code) in raw else None
            if sub is None:
                sub = raw.get(_pure(code))
            if sub is None:
                vals = list(raw.values())
                sub = vals[0] if vals else None
        else:
            sub = raw
        rows, idx = _sub_rows(sub, ["close"])
        c = _col(rows, idx, "close")
        return c[-1] if c else None
    except Exception:
        return None


def _cur_price(data, code, hist_close=None):
    """取当日价：优先 data 对象，退化快照/昨收（hist_close 仅供风控巡检兜底）"""
    code_s = _suffix(code)
    bar = _cur_bar(data, code)
    if bar["price"] is not None:
        return bar["price"]
    try:
        snap = get_snapshot([code_s])
        if snap and code_s in snap:
            for f in ("last_px", "last_price", "price"):
                if f in snap[code_s] and snap[code_s][f] is not None:
                    return float(snap[code_s][f])
    except Exception:
        pass
    if hist_close is not None:
        return float(hist_close)
    return None


# ----------------------------- 板块/行业 -----------------------------------
def _load_sector_index():
    """载入 sector_map.json -> {6位code: 行业名}，缓存到 g。

    【v1.4 根因修复】v1.3 的 _industry_of 只试 get_industry()，本平台没有这个接口
    → 恒返回 "" → 所有票归入同一个空行业 → 「行业均值排名 + 同行业共振>=2」整层
    失效（表现为 [统计] 里 板块强度Top=[('', (...,1,0))]，行业名是空字符串）。
    001 用的是外挂 sector_map.json（496 行业 + 504 概念 / 5645 标的），本函数照抄
    同款多路径 + 同款失败必告警纪律，不再静默返回空串。
    返回 {code6: 行业名} 反查表；失败返回 None（调用方据此打 error）。
    """
    g = _G()
    if g.get("ind_rev") is not None:
        return g["ind_rev"]
    paths = list(SECTOR_MAP_PATHS)
    try:
        root = str(get_research_path()).rstrip("/")
        if root:
            paths = [root + "/只读/" + SECTOR_MAP_FILE,
                     root + "只读/" + SECTOR_MAP_FILE,
                     root + "/" + SECTOR_MAP_FILE] + paths
    except Exception:
        pass
    tried = []
    for path in paths:
        tried.append(path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        ind = data.get("industry", {}) or {}
        if not ind:
            continue
        rev = {}
        for name, codes in ind.items():
            for c in codes:
                k = _pure(c)
                if k and k not in rev:
                    rev[k] = name
        if not rev:
            continue
        g["ind_rev"] = rev
        log.info("[行业] 加载成功 行业数=%d 覆盖标的=%d | source=%s 生成=%s 路径=%s"
                 % (len(ind), len(rev), data.get("source"),
                    data.get("generated_at"), path))
        return rev
    g["ind_rev"] = {}
    log.error("[行业] sector_map.json 载入失败（尝试 %d 个路径）→ 「行业均值+共振」"
              "整层将失效，候选会全部归入同一空行业" % len(tried))
    log.error("[行业] 已尝试路径: %s" % "; ".join(tried))
    log.error("[行业] 修复：把 sector_map.json 上传到 PTrade 只读目录，"
              "或把可用绝对路径加进 SECTOR_MAP_PATHS 后重跑")
    return g["ind_rev"]


def _industry_of(code):
    """行业归属：外挂 sector_map 反查 -> 平台接口兜底 -> ""（并计数，便于观测）。"""
    g = _G()
    rev = g.get("ind_rev")
    if rev is None:
        rev = _load_sector_index()
    name = rev.get(_pure(code)) if rev else None
    if name:
        return name
    try:
        if _has("get_industry"):
            ind = get_industry(_pure(code))
            if ind:
                return ind
    except Exception:
        pass
    g["ind_miss"] = g.get("ind_miss", 0) + 1
    return ""


def _get_market_pool():
    for fn in ("get_Ashares", "get_all_stocks"):
        if _has(fn):
            try:
                xs = globals()[fn]()
                if xs:
                    return [_suffix(x) for x in xs if _board(x) in ("MB", "CYB", "KCB")]
            except Exception:
                pass
    _warn("[扫描] 无可用股票池接口")
    return []


# ----------------------------- 初始化 ---------------------------------------
def initialize(context):
    g = {}
    globals()["g"] = g
    g["today"] = ""
    g["ind_rev"] = None         # code6 -> 行业名（懒加载 sector_map，None=未加载）
    g["ind_miss"] = 0           # 查不到行业归属的累计次数（应远小于池子规模）
    g["entry_px"] = {}          # 自有成本（避摊薄成本陷阱）
    g["first_buy"] = {}         # 首次买入日
    g["hold_days"] = {}
    g["peak_px"] = {}           # 持仓峰值价
    g["winner_set"] = set()
    g["winner_peak_pnl"] = {}   # 赢家最高浮盈（百分点）
    g["partial_done"] = set()
    g["sector_stops"] = []      # (日期, 板块)
    g["sector_cooldown_days"] = {}
    g["cool_down"] = {}         # code -> 剩余冷静日
    g["noise_slot"] = {}
    g["buys_today"] = 0
    g["month_buys"] = {}
    g["turn_log"] = []          # 换手记账（买+卖双向）
    g["regime"] = "NORMAL"
    g["sentiment"] = "OK"
    g["sector_fade"] = {}       # 板块 -> 衰退计数
    g["candidates"] = []
    g["sector_strength"] = {}
    g["flat_days"] = 0          # 连续空仓交易日（空转看门狗）
    g["last_scan_ok"] = -9      # 上一轮扫描有效票数：-9 未跑 / -1 取数失败 / >=0 实际有效数
    g["prev_regime"] = "NORMAL"  # ★V1.6 上一日大市档位（复位检测用）
    g["recovery_left"] = 0       # ★V1.6 复位回补窗口剩余天数
    g["delever_date"] = ""       # ★V1.6 降档执行日（每日最多一次）
    g["exit_check"] = {}         # ★V1.6 已下清仓单待对账: code6 -> 下单日
    log.info("[初始化] ★FUSION v1.6★ 启动；TRADE_ENABLED 见平台")
    log.info("[指纹] 热点=行业均值+强度分+共振>=2 | 止损=ATR clamp[6%,11%] | 大市=300暂停+1000halt+情绪HALF")
    log.info("[指纹] v1.6 取数形态探测(is_dict=True/fq降级) + 结构化数组按dtype.names解析 + 字段=%s | 分批=%d"
             % (list(PANEL_FIELDS), FETCH_BATCH))
    log.info("[指纹] v1.6 当日价四层(data数值优先/日线price/分钟线/假设定价) 每层拒绝==昨收 | "
             "date列别名=%s | 行业=外挂%s" % (list(DATE_COL_ALIASES), SECTOR_MAP_FILE))
    log.info("[指纹] v1.6 日线含当日与否由 date 列运行时判定（today=%s）；不含当日时按"
             "四层兜底，假设定价=昨收×%.3f" % (_context_date(context), 1.0 + ASSUME_ENTRY_PREMIUM))
    log.info("[指纹] v1.6 闸门=仓位上限(HALT%.0f%%/PAUSE%.0f%%)+降档先亏后盈+复位%d日回补 | "
             "单票%.0f%% | 688金额×%.1f 止损clamp%.0f%% | 残仓对账逐日核销"
             % (HALT_MAX_WEIGHT * 100, PAUSE_MAX_WEIGHT * 100, RESET_RECOVER_DAYS,
                MAX_SINGLE_RATIO * 100, KCB_SIZE_FACTOR, ATR_STOP_MAX_PCT_KCB * 100))


# ----------------------------- 盘前 -----------------------------------------
def before_trading_start(context, data):
    g = _G()
    g["today"] = _context_date(context)
    g["buys_today"] = 0
    g["candidates"] = []
    g["noise_slot"] = {}
    # 冷却衰减
    for k in list(g["cool_down"].keys()):
        g["cool_down"][k] -= 1
        if g["cool_down"][k] <= 0:
            del g["cool_down"][k]
    for k in list(g["sector_cooldown_days"].keys()):
        g["sector_cooldown_days"][k] -= 1
        if g["sector_cooldown_days"][k] <= 0:
            del g["sector_cooldown_days"][k]
    # 大市状态
    _prev_regime = g.get("prev_regime")
    _update_regime(context)
    _update_sentiment(context)
    # ★V1.6 闸门复位检测：HALT/PAUSE → NORMAL 启动分批回补窗口
    if g["regime"] == "NORMAL" and _prev_regime in ("HALT", "PAUSE"):
        g["recovery_left"] = RESET_RECOVER_DAYS
        log.info("[闸门回补] 大市 %s→NORMAL 复位，启动 %d 日分批回补"
                 % (_prev_regime, RESET_RECOVER_DAYS))
    elif g.get("recovery_left", 0) > 0 and g["regime"] == "NORMAL":
        g["recovery_left"] -= 1
        if g["recovery_left"] <= 0:
            g["recovery_left"] = 0
            log.info("[闸门回补] 回补窗口结束")
    g["prev_regime"] = g["regime"]
    npos = len(_get_positions(context))
    log.info("[日初] 持仓 %d 只 | 大市=%s | 情绪=%s" %
             (npos, g["regime"], g["sentiment"]))
    # 空转看门狗：整段回测"0 成交"是 v1.0 踩过的坑（静默失败最难发现）
    if npos == 0:
        g["flat_days"] = g["flat_days"] + 1
    else:
        g["flat_days"] = 0
    if g["flat_days"] >= IDLE_WARN_DAYS and g["flat_days"] % IDLE_WARN_DAYS == 0:
        log.error("[空转告警] 连续 %d 个交易日 0 持仓 | 上一轮扫描有效票数=%s —— "
                  "若行情不至于此，先看 [扫描] 体检行与取数报错；"
                  "典型根因=字段名/取数口径与平台不符 → 候选池恒空 → 全天不开仓"
                  % (g["flat_days"], g["last_scan_ok"]))


def _context_date(context):
    try:
        dt = context.blotter.current_dt
        return str(dt)[:10]
    except Exception:
        try:
            return str(context.current_dt)[:10]
        except Exception:
            return ""


def _update_regime(context):
    g = _G()
    halt = False
    pause = False
    try:
        # v1.3：指数取数也走统一入口（旧版裸调 get_history 且 field 传字符串，
        # 在同一形态坑里同样会静默拿空 → 大市档位永远停在 NORMAL 假象）
        f_close = _norm_fields(["close"])
        raw, _nb = _fetch_panel(f_close, [REGIME_BROAD, REGIME_SMALL],
                                count=REGIME_MA + 5)
        if raw:
            def series(idx_code):
                sub = raw.get(idx_code)
                if sub is None:
                    sub = raw.get(_pure(idx_code))
                rows, idx = _sub_rows(sub, f_close)
                c = _col(rows, idx, "close")
                return c if c else None
            sb = series(REGIME_SMALL)
            br = series(REGIME_BROAD)
            if sb and len(sb) >= REGIME_MA:
                ma20 = _ma(sb, REGIME_MA)
                ma5 = _ma(sb[-REGIME_MA_FAST:], REGIME_MA_FAST) if len(sb) >= REGIME_MA_FAST else None
                last = sb[-1]
                if (ma20 and last < ma20) or (ma5 and ma20 and ma5 < ma20 and last < ma5):
                    halt = True
            if br and len(br) >= REGIME_MA:
                ma20 = _ma(br, REGIME_MA)
                if ma20 and br[-1] < ma20:
                    pause = True
    except Exception as e:
        _warn("[regime] %s" % e)
    if halt:
        g["regime"] = "HALT"
    elif pause:
        g["regime"] = "PAUSE"
    else:
        g["regime"] = "NORMAL"
    # 情绪冰点叠加 HALF
    if g["sentiment"] == "ICE" and g["regime"] == "NORMAL":
        g["regime"] = "HALF"


def _update_sentiment(context):
    g = _G()
    g["sentiment"] = "OK"
    try:
        pool = _get_market_pool()
        if not pool:
            return
        # 口径：日线【不含当日】，末根=昨收，倒数第二根=前日收
        # => pct = 昨收/前日收-1 即「昨日涨跌幅」，与 1030/001 的情绪口径同源。
        # 只用 close 一个字段，规避 pre_close 这类非法字段名把整段取数打挂。
        fields = _norm_fields(["close"])
        raw, _nb = _fetch_panel(fields, pool, count=3)
        if not raw:
            # 【重要】取数失败时不能默默返回 OK —— 那会让情绪闸门假装"正常"，
            # 掩盖取数故障。这里显式标 FAIL，让 [日初] 行一眼看出情绪层没工作。
            g["sentiment"] = "FAIL"
            log.error("[senti] 分批取数返回空（%d 只）→ 情绪闸门失效，标记 FAIL" % len(pool))
            return
        zt = 0
        up = 0
        tot = 0
        for code in pool:
            try:
                sub = raw.get(code)
                if sub is None:
                    sub = raw.get(_suffix(code))
                if sub is None:
                    sub = raw.get(_pure(code))
                rows, idx = _sub_rows(sub, fields)
                closes = _col(rows, idx, "close")
                if not closes or len(closes) < 2:
                    continue
                pc = closes[-1]      # 昨收
                pc2 = closes[-2]     # 前日收
                if pc2 <= 0:
                    continue
                pct = (pc - pc2) / pc2
                tot += 1
                if pct >= _limit_pct(code):
                    zt += 1
                if pct > 0:
                    up += 1
            except Exception:
                continue
        if tot <= 0:
            g["sentiment"] = "FAIL"
            log.error("[senti] 面板有数据但一只都算不出涨跌幅 → 列名/口径对不上")
            return
        # 情绪口径自证：把样本量打出来，避免"样本 3 只也算出冰点"这类假信号
        g["senti_breadth"] = (zt, up, tot)
        log.info("[senti] 样本 %d 只 | 涨停 %d | 上涨占比 %.1f%%"
                 % (tot, zt, up * 100.0 / tot))
        if zt < MARKET_ZT_FLOOR:
            g["sentiment"] = "ICE"
        # 上涨占比过低也判冰点
        if up * 1.0 / tot < 0.30:
            g["sentiment"] = "ICE"
    except Exception as e:
        g["sentiment"] = "FAIL"
        _warn("[senti] %s" % e)


# ----------------------------- 扫描+选股 -------------------------------------
def scan_market(context, data=None):
    g = _G()
    pool = _get_market_pool()
    if not pool:
        return []
    # 批量取面板
    # 【v1.4】字段集 = PANEL_FIELDS（7 个，全部在平台白名单内）。除 001 实测的 5 个
    # OHLCV 外，补回 price（当日价第 2 档来源）与 money（成交额，免自算）。
    # 1030 策略在同平台长期稳定请求 price/money，故不增加取数风险。
    fields = _norm_fields(PANEL_FIELDS)
    panel, nbatch = _fetch_panel(fields, pool, diag=True)
    if not panel:
        g["last_scan_ok"] = -1        # -1 = 取数整体失败（区别于"取到但筛空"的 0）
        log.error("[扫描] 分批取数后面板为空（%d 批全部无数据，形态=%s）→ 全天不会开仓"
                  % (nbatch, _DS.get("style_name")))
        log.error("[扫描] 排查顺序: ①[取数]形态探测行是否命中（未命中说明四档全空）；"
                  "②codes 元素是否带 .SS/.SZ 后缀；"
                  "③[取数] 是否报了「无法识别的形态」（那就把该行发我补适配）")
        return []

    feats = {}
    miss_px = 0        # 当日价四层全空（不会被走到：最后一层是假设定价）
    fb_vol = 0         # 当日量不可信、退化用昨日量比的票数
    min_px = 0         # 靠分钟线兜底取到当日价的票数
    rows_short = 0     # 拿到数据但行数不足 MIN_HIST_BARS 的票数（诊断用）
    no_key = 0         # 面板里根本没有这只票的票数（诊断用）
    assumed_cnt = 0    # 用「保守假设定价」的票数（当日价前两层全空时）
    bar_today = 0      # 日线末根就是当日进行中 bar 的票数（口径自适应命中数）
    px_data = 0        # 当日价来源=data 对象（首选通道）
    px_field = 0       # 当日价来源=日线 price 字段
    px_minute = 0      # 当日价来源=分钟线
    date_ok = 0        # 成功取到 date 列（能真正判定当日口径）的票数
    # 当日 8 位整数日期（yyyyMMdd），与平台 K 线 date 列同口径 —— 用来运行时判定
    # 「末根是不是当日 bar」，避免继续用假设去赌平台口径。
    _ts = _context_date(context).replace("-", "")
    try:
        today_int = int(_ts) if _ts else 0
    except Exception:
        today_int = 0
    # 分钟线通道：本平台【回测里给的是昨日最后一根】（1030 日志第 15 行实证：
    # 「分钟close=11.13」== 昨收 11.13）。因此它只能当"最后兜底"，绝不能当
    # "当日价"用 —— v1.3 正是把当日价来源主要落在它身上，导致 pct 恒 0。
    snap_is_minute = False
    snap = _snap_map(pool)
    if not snap:
        snap = _minute_map(_norm_fields(["open", "high", "low", "close", "volume"]), pool)
        snap_is_minute = bool(snap)
    for code in pool:
        sub = panel.get(code) if isinstance(panel, dict) else None
        if sub is None:
            sub = panel.get(_suffix(code))
        if sub is None:
            sub = panel.get(_pure(code))
        if sub is None:
            no_key += 1
            continue
        try:
            rows, idx = _sub_rows(sub, fields)
            if not rows or len(rows) < MIN_HIST_BARS:
                rows_short += 1
                continue
            closes = _col(rows, idx, "close")
            opens = _col(rows, idx, "open")
            highs = _col(rows, idx, "high")
            lows = _col(rows, idx, "low")
            vols = _col(rows, idx, "volume")
            if not closes or not opens or not highs or not lows or not vols:
                continue
            # 【口径自适应】用返回的日期列判定末根是不是「当日进行中 bar」，
            # 不再靠猜（001 实测=含当日；1030 源码注释=不含当日，两者互相矛盾）：
            #   含当日 → 当日价/昨收/量比全部就地从末根拿，完全不依赖快照或分钟线；
            #   不含当日 → 末根=昨收，走 data/日线price/分钟线/假设定价四层兜底。
            # 【v1.4 date 列别名】平台结构化数组里这一列实际叫 datetime（不叫 date），
            # 旧写法查 "date" 恒取空 → has_today 恒 False（且日志照样写"不含当日"，
            # 属于假判定）。这里按别名表取，并把"取到列"与"判定结果"分开计数。
            dates = _col_first(rows, idx, DATE_COL_ALIASES)
            has_today = False
            if dates:
                date_ok += 1
                if today_int:
                    try:
                        dv = str(int(float(dates[-1])))
                    except Exception:
                        dv = str(dates[-1]).replace("-", "").split(".")[0]
                    try:
                        has_today = int(dv) == today_int
                    except Exception:
                        has_today = False
            if has_today:
                bar_today += 1
            prev_close = closes[-2] if (has_today and len(closes) >= 2) else closes[-1]
            if prev_close <= 0:
                continue
            assumed = False
            px_src_one = "日线末根"
            if has_today:
                cur = closes[-1]
                if cur <= 0:
                    continue
                cur_bar = {"price": cur, "open": opens[-1], "high": highs[-1],
                           "low": lows[-1], "volume": vols[-1]}
            else:
                # 【v1.4 根因修复】四层兜底 + 每层"与昨收相等即作废"的 guard：
                #   data 对象 -> 日线 price 字段 -> 分钟线 -> 保守假设定价。
                # 旧版只按字段名从 data 里读 price(拿到的是昨收)、且没有 guard，
                # 于是当日价恒=昨收 → pct 恒 0 → 涨幅区间全灭 → 全天 0 成交。
                dprice = _col_last(rows, idx, "price")
                mvals = snap.get(code) or snap.get(_pure(code)) or {}
                cur, px_src_one = _today_price(data, code, prev_close, dprice,
                                               mvals.get("price"))
                if px_src_one == "data":
                    px_data += 1
                elif px_src_one == "price字段":
                    px_field += 1
                elif px_src_one == "分钟线":
                    px_minute += 1
                    min_px += 1
                else:
                    assumed = True
                    assumed_cnt += 1
                cur_bar = _cur_bar(data, code, mvals)
                cur_bar["price"] = cur
                # 量比/日内形态只信「当日 bar」；当日 bar 不可得时全部退化到昨日口径
                if px_src_one != "data" or has_today:
                    cur_bar["open"] = closes[-1]
                    cur_bar["high"] = max(highs[-1], cur)
                    cur_bar["volume"] = None
                if cur is None or cur <= 0:
                    cur = prev_close * (1.0 + ASSUME_ENTRY_PREMIUM)
                    assumed = True
                    assumed_cnt += 1
                    px_src_one = "假设定价"
            pct = (cur - prev_close) / prev_close
            # 均线：日线含当日时末根本身就是进行中价，整体取均线即可；
            # 不含当日时，用「已收盘序列 + 当前价」补出含当日的短均线。
            if has_today:
                ma5 = _ma(closes, 5)
                ma10 = _ma(closes, 10)
            else:
                ma5 = _ma(closes[-4:] + [cur], 5) if len(closes) >= 4 else None
                ma10 = _ma(closes[-9:] + [cur], 10) if len(closes) >= 9 else None
            ma20 = _ma(closes, 20)
            ma60 = _ma(closes, 60)
            # 量比：只认「日线含当日」时的当日量；否则一律用【昨日量比】。
            # 【v1.4 口径修正】旧版把分钟线量当"当日累计量"，但本平台回测的分钟线
            # 给的是昨日（见 1030 日志），其窗口内求和 ≈ 昨日尾盘量 → 量比恒约 0.25，
            # 是所有票一起被系统性低估。既然不可信，就明确退化到昨日量比并计数。
            base5 = _ma(vols[-6:-1], 5) if has_today else _ma(vols[-5:], 5)
            if has_today and vols[-1] and base5:
                vol_ratio = vols[-1] / base5
            else:
                fb_vol += 1
                vol_ratio = (vols[-1] / base5) if (base5 and vols[-1]) else 1.0
            # 成交额：平台 money 字段优先（1030 同款做法），取不到再自算量×价
            money_today = _col_last(rows, idx, "money")
            if not money_today:
                money_today = (vols[-1] * cur) if (vols[-1] and cur > 0) else 0.0

            above20 = (ma20 is not None and cur >= ma20)
            above60 = (ma60 is not None and cur >= ma60)
            shape = 0
            if ma5 and ma10 and ma20:
                if cur >= ma5 >= ma10 >= ma20:
                    shape = 3
                elif ma5 >= ma10:
                    shape = 2
            feats[code] = dict(pct=pct, vol_ratio=vol_ratio, above20=above20,
                               above60=above60, shape=shape, money=money_today,
                               day_open=cur_bar["open"], day_high=cur_bar["high"],
                               closes=closes, opens=opens, highs=highs, lows=lows,
                               last=cur, prev=prev_close, px_src=px_src_one)
        except Exception:
            continue
    if miss_px:
        g["diag_miss_px"] = g.get("diag_miss_px", 0) + miss_px
    if fb_vol:
        g["diag_fb_vol"] = g.get("diag_fb_vol", 0) + fb_vol
    # 取数体检：池子有效数 / 当日价来源分布 / 各档失败计数
    if snap_is_minute:
        px_src = "批量分钟线(回测=昨日,仅兜底)"
    elif snap:
        px_src = "批量快照"
    else:
        px_src = "无(仅data)"
    log.info("[扫描] 池%d 有效%d | 当日价: data%d 日线price%d 分钟线%d 假设%d | "
             "当日bar%d 量比退化%d | 无键%d 行数不足%d | 分钟通道=%s"
             % (len(pool), len(feats), px_data, px_field, px_minute, assumed_cnt,
                bar_today, fb_vol, no_key, rows_short, px_src))
    # ===== v1.4 关键自证行（照抄 1030 第 15 行的口径自检）=====
    # 这一行是本次三轮空转的"照妖镜"：它同时打出【昨收/当日价/口径来源】。
    # 若「data当日价」为空或等于昨收，说明 data 通道没取到 → 必定全天 0 成交。
    if not g.get("px_diag_done"):
        g["px_diag_done"] = True
        sample = None
        for c, ff in list(feats.items())[:1]:
            sample = (c, ff)
        if sample:
            log.info("[口径] 样本 %s 昨收=%.3f 现价=%.3f 涨幅=%.2f%% 成交额=%.2e "
                     "量比=%.2f 站MA20=%s | 当日价来源=%s | data通道命中%d/%d"
                     % (sample[0], sample[1]["prev"], sample[1]["last"],
                        sample[1]["pct"] * 100.0, sample[1]["money"],
                        sample[1]["vol_ratio"], sample[1]["above20"],
                        sample[1].get("px_src"), px_data, len(feats)))
    log.info("[口径] 形态=%s | 日线%s当日bar（date列命中%d/%d，today=%s）| 字段=%s"
             % (_DS.get("style_name"),
                "含" if bar_today else "不含", date_ok, len(feats), today_int,
                list(fields)))
    if date_ok == 0 and len(feats) > 0:
        log.error("[口径] date 列一只都没取到（别名表=%s）→ 无法判定日线是否含当日，"
                  "口径判定与量比/形态全部退化。请把 [诊断] 的「解析列」发我补别名"
                  % (list(DATE_COL_ALIASES),))
    if px_data == 0 and len(feats) > 0:
        log.error("[口径] data 通道一只当日价都没取到 → 涨幅将以日线末根口径退化，"
                  "若同时 date列命中0 则全部票的 pct 会退化为 0，导致粗筛必然全空。"
                  "排查：①handle_data 的 data 是否覆盖股票池（必要时 set_universe）；"
                  "②data 对象取值方式见 [口径] 样本行的「data通道命中」")
    if assumed_cnt:
        # 001 纪律：口径必须写进日志与结论，否则收益绝对值不可与真实快照口径相比
        log.info("[口径-假设] %d/%d 只按保守假设定价（成交价=昨收×%.3f）；"
                 "该假设下收益绝对值偏保守，不可与真实快照口径直接比较"
                 % (assumed_cnt, len(feats), 1.0 + ASSUME_ENTRY_PREMIUM))
    g["diag_bar_today"] = bar_today
    g["last_scan_ok"] = len(feats)
    if len(feats) == 0:
        log.error("[扫描] 有效票数为 0 —— 取数返回了但一只都用不了 | 无键%d 行数不足%d"
                  % (no_key, rows_short))
        log.error("[扫描] 判读: 无键大=合并后的键与池代码对不上（看 [诊断] 解析列）；"
                  "行数不足大=返回行数少于 MIN_HIST_BARS(%d)（调小或加大 count）"
                  % MIN_HIST_BARS)

    # 粗筛（v1.4：每一道闸都计数，粗筛为空时必须能一眼看出是哪道闸杀的）
    rough = []
    n_gain = 0
    n_amt = 0
    n_ma = 0
    samples = []
    for code, f in feats.items():
        lo, hi = _gain_range(code)
        if not (lo <= f["pct"] <= hi):
            n_gain += 1
            if len(samples) < 5:
                samples.append("%s pct=%.2f%%(需%.1f~%.1f%%)" % (_pure(code),
                               f["pct"] * 100.0, lo * 100.0, hi * 100.0))
            continue
        if f["money"] < MIN_AMOUNT:
            n_amt += 1
            if len(samples) < 5:
                samples.append("%s 额=%.2e(需%.1e)" % (_pure(code), f["money"], MIN_AMOUNT))
            continue
        if REQUIRE_ABOVE_MA20 and not f["above20"]:
            n_ma += 1
            if len(samples) < 5:
                samples.append("%s 未站MA20" % _pure(code))
            continue
        rough.append((code, f))
    log.info("[粗筛] 池%d → 涨幅区间淘汰%d → 成交额淘汰%d → MA20淘汰%d → 过关%d "
             "| 门槛: 额>=%.1e MA20=%s"
             % (len(feats), n_gain, n_amt, n_ma, len(rough), MIN_AMOUNT,
                REQUIRE_ABOVE_MA20))
    if not rough and samples:
        log.info("[粗筛] 淘汰样本: %s" % " | ".join(samples))
    if not rough:
        if n_gain >= len(feats) * 0.9:
            log.error("[粗筛] 九成以上票死在涨幅区间 → 当日价口径仍然不对"
                      "（pct 被压到 0 附近）。看上一行 [口径] 样本的「当日价来源」。")
        elif n_amt >= len(feats) * 0.9:
            log.error("[粗筛] 九成以上票死在成交额 → money 字段单位/口径不对"
                      "（看 [粗筛] 淘汰样本里的 额= 数量级）")
        return []

    # 行业分组 + 强度分（融合：申万均值 + 001强度 + 共振）
    ind_pct = {}
    ind_cnt = {}
    ind_zt = {}
    for code, f in rough:
        ind = _industry_of(code)
        if ind not in ind_pct:
            ind_pct[ind] = []
            ind_cnt[ind] = 0
            ind_zt[ind] = 0
        ind_pct[ind].append(f["pct"])
        ind_cnt[ind] += 1
        if f["pct"] >= _limit_pct(code):
            ind_zt[ind] += 1
    # 行业均值排名前 N
    ind_avg = {k: _mean(v) for k, v in ind_pct.items()}
    strong_ind = set()
    ranked = sorted([(k, v) for k, v in ind_avg.items() if v > INDUSTRY_MIN_RISE],
                    key=lambda x: -x[1])[:TOP_INDUSTRY_N]
    for k, _ in ranked:
        strong_ind.add(k)

    cands = []
    for code, f in rough:
        ind = _industry_of(code)
        if ind not in strong_ind:
            continue  # 申万行业级确认（lhb888）
        # 共振：同行业候选>=2（常开）
        if ind_cnt.get(ind, 0) < MIN_SECTOR_ALIGN:
            continue
        # 细评：MA60 + 形态 + 日内回撤 + 回踩
        if REQUIRE_ABOVE_MA60 and not f["above60"]:
            continue
        if f["shape"] < MA_SHAPE_MIN:
            continue
        # 日内回撤 = (当日最高-当日价)/当日最高；当日最高不可得则跳过这道（宁可少过滤，不可用错数据误杀）
        dh = f["day_high"]
        if dh and dh > 0 and (dh - f["last"]) / dh > INTRADAY_PULLBACK_MAX:
            continue
        # 回踩：当日价 >= 当日开盘；开盘不可得则近似为「当日不破昨收」
        ref_open = f["day_open"] if f["day_open"] else f["prev"]
        if f["last"] < ref_open:
            continue
        # 不买涨停
        if not ALLOW_LIMIT_UP_BUY and f["pct"] >= _limit_pct(code):
            continue
        # 强度分
        lb = 1 if f["pct"] >= _limit_pct(code) else 0
        score = f["pct"] + lb * 6.0 + min(f["vol_ratio"], 3.0) * 8.0 + f["shape"] * 1.5
        cands.append(dict(code=code, score=score, ind=ind, f=f))
    cands.sort(key=lambda x: -x["score"])
    cands = cands[:MAX_CANDIDATES]
    g["candidates"] = cands
    g["sector_strength"] = {k: (ind_avg.get(k, 0), ind_cnt.get(k, 0), ind_zt.get(k, 0))
                            for k in strong_ind}
    return cands


# ----------------------------- 买入 -----------------------------------------
def buy_job(context, data=None):
    g = _G()
    cands = g.get("candidates") or []
    if not cands:
        return
    total, cash = _account(context)
    if total <= 0:
        return
    # ★V1.6 闸门改造：HALT/PAUSE 由"清零式禁建"改为"仓位上限"，上限内继续开仓
    cap_value = None
    if g["regime"] in ("HALT", "PAUSE"):
        cap = HALT_MAX_WEIGHT if g["regime"] == "HALT" else PAUSE_MAX_WEIGHT
        cap_value = total * cap
        pos_value = total - cash
        if pos_value >= cap_value - GATE_MIN_BUY_VALUE:
            log.info("[买入] 大市%s 仓位%.1f%% ≥ 上限%.0f%% → 停开新仓"
                     % (g["regime"], pos_value * 100.0 / total, cap * 100))
            return
        log.info("[买入] 大市%s 仓位%.1f%% < 上限%.0f%% → 限额内继续开仓"
                 % (g["regime"], pos_value * 100.0 / total, cap * 100))
    budget_factor = SENTIMENT_HALF_FACTOR if g["regime"] == "HALF" else 1.0
    base_budget = min(cash * (1 - CASH_BUFFER), total * POSITION_VALUE_RATIO * MAX_POSITIONS)
    budget = base_budget * budget_factor
    if cap_value is not None:
        budget = min(budget, max(cap_value - (total - cash), 0.0))
    live = _get_positions(context)
    live_codes = set(_pure(p["_code"]) for p in live)
    held = len(live)
    remaining = MAX_POSITIONS - held
    if remaining <= 0:
        return
    # ★V1.6 回补期：复位后 5 日内每日新开仓上限 2→3，加速回到目标仓位
    max_new = RESET_MAX_NEW_PER_DAY if g.get("recovery_left", 0) > 0 else MAX_NEW_PER_DAY

    pending = []
    for c in cands:
        code = c["code"]
        if _pure(code) in live_codes:
            continue
        if _pure(code) in g["cool_down"]:
            continue
        if c["ind"] in g["sector_cooldown_days"]:
            continue
        if g["buys_today"] >= max_new:
            break
        pending.append(c)

    for c in pending:
        if remaining <= 0 or budget <= 0:
            break
        if g["buys_today"] >= max_new:
            break
        code = c["code"]
        # 强度加权分配
        weight = math.pow(max(c["score"], 0.01), STRENGTH_EXP)
        tot_w = sum(math.pow(max(x["score"], 0.01), STRENGTH_EXP) for x in pending)
        alloc = budget * (weight / tot_w) if tot_w > 0 else budget / max(len(pending), 1)
        alloc = min(alloc, total * MAX_SINGLE_RATIO)
        # ★V1.6 科创板敞口折半：688 建仓金额 ×0.5
        if _is_kcb(code):
            alloc *= KCB_SIZE_FACTOR
        if alloc < 1000:
            continue
        # 双护栏：取当日价
        cur = _cur_price(data, code, hist_close=c["f"]["last"])
        if cur is None:
            cur = c["f"]["last"]
        if cur <= 0:
            continue
        # 最小 1 手闸门：分配额买不满 1 手会静默废单并白占预算
        lot = 200 if _pure(code).startswith("688") else 100
        if alloc < cur * lot * 1.02:
            continue
        lo_guard = cur * (1 - BUY_FLOOR_PCT)
        hi_guard = cur * (1 + BUY_PREMIUM_PCT)
        if cur < lo_guard or cur > hi_guard:
            continue  # 走弱不接刀 / 涨过头不追
        limit = min(cur * 1.02, hi_guard)
        try:
            order_target_value(_suffix(code), alloc, limit_price=limit)
            g["entry_px"][_pure(code)] = cur
            g["first_buy"][_pure(code)] = g["today"]
            g["peak_px"][_pure(code)] = cur
            g["buys_today"] += 1
            remaining -= 1
            budget -= alloc
            _record_turn("BUY")
            _record_month(g["today"])
            log.info("[买入] %s 行业=%s 强度%.1f 分配%.0f 限价%.2f%s" %
                     (code, c["ind"], c["score"], alloc, limit,
                      " 科创折半" if _is_kcb(code) else ""))
        except Exception as e:
            _warn("[买入] %s 下单失败: %s" % (code, e))


# ----------------------------- 风控/出场 ------------------------------------
def _gate_delever(context, data=None):
    """★V1.6 闸门降档：进入 HALT/PAUSE 当日把仓位降到闸门上限。

    顺序=先砍亏损最深的（浮盈>0 的排在全部亏损砍完之后再动），
    每日最多执行一次。v1.5 进入 HALT 后持仓无人降档（只禁新开），
    7 月连续 21 日 HALT 期间亏损敞口全程裸奔，是回撤放大的主因之一。
    """
    g = _G()
    if g["regime"] not in ("HALT", "PAUSE"):
        return
    if g.get("delever_date") == g["today"]:
        return
    total, cash = _account(context)
    if total <= 0:
        return
    cap = HALT_MAX_WEIGHT if g["regime"] == "HALT" else PAUSE_MAX_WEIGHT
    rows = []
    pos_value = 0.0
    for p in _get_positions(context):
        code = p["_code"]
        amount = _pos_field(p, ("amount", "current_amount")) or 0
        if amount <= 0:
            continue
        cur = _cur_price(data, code)
        if cur is None or cur <= 0:
            cur = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or 0.0
        mv = amount * cur
        pos_value += mv
        code6 = _pure(code)
        entry = g["entry_px"].get(code6)
        if not entry or entry <= 0:
            entry = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or cur
        pnl = (cur - entry) / entry if entry else 0.0
        rows.append((pnl, code, p, mv))
    if not rows:
        g["delever_date"] = g["today"]
        return
    weight = pos_value / total
    if weight <= cap:
        g["delever_date"] = g["today"]
        return
    log.info("[闸门降档] %s 仓位%.1f%% > 上限%.0f%% → 先砍亏损最深者"
             % (g["regime"], weight * 100, cap * 100))
    rows.sort(key=lambda x: x[0])   # pnl 升序：最亏先砍
    for pnl, code, p, mv in rows:
        if weight <= cap:
            break
        _sell_all(context, code, "闸门降档", pnl=pnl)
        weight -= mv / total
    g["delever_date"] = g["today"]


def monitor_risk(context, data=None, tag="NORMAL"):
    g = _G()
    live = _get_positions(context)
    now = _now_hhmm(context)
    is_tail = now >= BREAK_MA_TIME
    # ★V1.6 残仓对账：逐日核对已下清仓单的票
    for code6 in list(g.get("exit_check", {}).keys()):
        p_still = None
        for p in live:
            if _pure(p["_code"]) == code6:
                p_still = p
                break
        if p_still is None:
            # 平台已无此仓 → 清仓成交完毕，正式销台账
            for k in ("entry_px", "first_buy", "peak_px", "hold_days", "winner_peak_pnl"):
                if isinstance(g.get(k), dict):
                    g[k].pop(code6, None)
            for k in ("partial_done", "winner_set"):
                if isinstance(g.get(k), set):
                    g[k].discard(code6)
            g["exit_check"].pop(code6, None)
        elif _days_between(g["exit_check"][code6], g["today"]) >= 1:
            # 残量仍在 → 次日起重卖（部分成交残留纳入统一退出管理）
            log.info("[对账] %s 清仓单未全部成交，残量重卖" % code6)
            try:
                order_target(_suffix(code6), 0)
                _record_turn("SELL")
            except Exception as e:
                _warn("[对账] %s 残量重卖失败: %s" % (code6, e))
    for p in live:
        code = p["_code"]
        code6 = _pure(code)
        amount = _pos_field(p, ("amount", "current_amount"))
        enable = _pos_field(p, ("enable_amount",))
        if amount <= 0:
            continue
        cur = _cur_price(data, code)
        if cur is None:
            continue
        entry = g["entry_px"].get(code6)
        if entry is None or entry <= 0:
            entry = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or cur
            g["entry_px"][code6] = entry
        pnl = (cur - entry) / entry
        # 更新峰值
        if code6 not in g["peak_px"] or cur > g["peak_px"][code6]:
            g["peak_px"][code6] = cur
        peak = g["peak_px"][code6]
        peak_pnl = (peak - entry) / entry
        # 赢家粘性是否激活（浮盈>=门槛）：激活时豁免 ④移动止盈 / ⑦破均线
        winner_active = peak_pnl >= WINNER_EXEMPT_PCT
        # 必须每次重算：缓存会把建仓日的 0 固化，导致 held<1 恒成立、
        # T+1 判断永远跳过卖出分支（只买不卖）
        held = _days_between(g["first_buy"].get(code6, g["today"]), g["today"])
        g["hold_days"][code6] = held
        # T+1：当日买入不可卖，跳过所有卖出判定（防废单/噪声）
        if held < 1:
            continue

        # ① 硬止损（风险类，下限09:45）
        stop_pct = _stop_pct(code6, entry, cur)
        if now >= STOP_TIME_FLOOR and pnl <= -stop_pct:
            _sell_all(context, code, "硬止损", pnl=pnl, entry_today=(held < 1))
            _on_stop(code6, g, p)
            continue
        # ② 保本止损：峰值曾盈利>=3% 后回撤至成本线即退出（用 peak_pnl 判定，避免与 cur<=entry 互斥导致死代码）
        if peak_pnl >= BREAKEVEN_GUARD and cur <= entry:
            _sell_all(context, code, "保本止损", pnl=pnl, entry_today=(held < 1))
            continue
        # ③ 分批止盈（+10%减半，未做过）
        if pnl >= PARTIAL_TAKE_PCT and code6 not in g["partial_done"] and enable >= 100:
            _sell_half(context, code, p, pnl)
            g["partial_done"].add(code6)
            continue
        # ④ 移动止盈（武装5%/回撤15%，价格触发，无闸门）
        if (not winner_active) and peak_pnl >= TRAIL_ARM_PCT and cur <= peak * (1 - TRAIL_PCT):
            _sell_all(context, code, "移动止盈", pnl=pnl, entry_today=(held < 1))
            continue
        # ⑤ 赢家粘性锁利（百分点尺，自峰值回撤>=10pp；winner_active 已在循环头判定）
        if peak_pnl >= WINNER_EXEMPT_PCT:
            g["winner_set"].add(code6)
            g["winner_peak_pnl"][code6] = peak_pnl
        if code6 in g["winner_set"] and held <= WINNER_MAX_HOLD:
            giveback = peak_pnl - pnl
            if giveback >= WINNER_GIVEBACK_PCT:
                _sell_all(context, code, "赢家锁利", pnl=pnl, entry_today=(held < 1))
                continue
        # ⑥ +30%全清（锁利类，无闸门）
        if pnl >= TP_FULL_PCT:
            _sell_all(context, code, "止盈全清", pnl=pnl, entry_today=(held < 1))
            continue
        # ⑦ 破均线（趋势类，仅尾盘确认；赢家粘性激活时豁免）
        if (not winner_active) and is_tail:
            closes = _hist_closes(code, RETREAT_MA_HARD + 2)
            if closes and len(closes) >= RETREAT_MA_HARD:
                ma20 = _ma(closes, RETREAT_MA_HARD)
                if ma20 and cur < ma20:
                    _sell_all(context, code, "破20日线", pnl=pnl, entry_today=(held < 1))
                    continue
                ma10 = _ma(closes, RETREAT_MA_FAST)
                if ma10 and cur < ma10 and pnl < 0:
                    _sell_all(context, code, "破10日线", pnl=pnl, entry_today=(held < 1))
                    continue
        # ⑧ 时间止损（亏损持仓>=5日）
        if pnl < 0 and held >= MAX_HOLD_DAYS:
            _sell_all(context, code, "时间止损", pnl=pnl, entry_today=(held < 1))
            continue


def _stop_pct(code6, entry, cur):
    if STOP_MODE == "fixed":
        return FIXED_STOP_PCT
    # ATR 自适应（取近期振幅估算）
    closes = _hist_closes(code6, ATR_N + 2)
    if closes and len(closes) >= ATR_N:
        atr = _atr(closes, ATR_N)
        if atr > 0 and entry > 0:
            ratio = atr / entry
            pct = ATR_STOP_MULT * ratio
            # ★V1.6：688 clamp 上限收紧（跳空/跌停穿透幅度大，回测 20 笔均 -7.64%、最差 -12.3%）
            cap_pct = ATR_STOP_MAX_PCT_KCB if _is_kcb(code6) else ATR_STOP_MAX_PCT
            return max(ATR_STOP_MIN_PCT, min(cap_pct, pct))
    return ATR_STOP_MIN_PCT


def _atr(closes, n):
    trs = []
    for i in range(1, len(closes)):
        trs.append(abs(closes[i] - closes[i - 1]))
    if len(trs) < n:
        return _mean(trs) if trs else 0.0
    return _mean(trs[-n:])


def _hist_closes(code, count):
    raw = _hist(code, count, "close")
    if raw is None:
        return None
    rows, idx = _sub_rows(raw, ["close"])
    return _col(rows, idx, "close")


def _sell_all(context, code, reason, pnl=0.0, entry_today=False):
    g = _G()
    code6 = _pure(code)
    try:
        order_target(_suffix(code), 0)
    except Exception as e:
        _warn("[卖出] %s 清仓失败: %s" % (code, e))
        return
    # 先快照成本算￥，再清（PTrade order 后持仓清零）
    entry = g["entry_px"].get(code6)
    enable = 0
    _record_turn("SELL")
    _record_trade(reason, pnl)
    log.info("[卖出] %s —— %s 浮盈%.1f%%" % (code, reason, pnl * 100))
    # ★V1.6 残仓对账：下单后【不立即销台账】。旧版立刻 pop entry/first_buy，
    # 部分成交留残量时残仓既无成本也无买入日 → T+1 判定 held<1 恒成立 →
    # 永久跳过卖出分支（5/21 688112 残 700 股脱管 3 个月的根因）。
    # 改为挂 exit_check，由 monitor_risk 逐日核对：清干净才销账，没清干净次日重卖。
    g.setdefault("exit_check", {})[code6] = g["today"]


def _sell_half(context, code, p, pnl):
    g = _G()
    code6 = _pure(code)
    amount = int(_pos_field(p, ("amount", "current_amount")))
    enable = int(_pos_field(p, ("enable_amount",)))
    lot = 200 if _is_kcb(code) else 100
    half = (amount // 2 // lot) * lot
    if half < lot or enable < half:
        return
    try:
        order(_suffix(code), -half)
    except Exception as e:
        _warn("[卖出] %s 减半失败: %s" % (code, e))
        return
    _record_turn("SELL")
    _record_trade("分批止盈", pnl)
    log.info("[卖出] %s 数量%d 减半 浮盈%.1f%%" % (code, half, pnl * 100))


def _on_stop(code6, g, p):
    ind = _industry_of(code6)
    g["sector_stops"].append((g["today"], ind))
    # 板块连败冷却
    recent = [s for s in g["sector_stops"]
              if s[1] == ind and _days_between(s[0], g["today"]) <= 20]
    if len(recent) >= 2:
        g["sector_cooldown_days"][ind] = 10
        log.info("[板块冷却] %s 连败>=2，冷却10日" % ind)


# ----------------------------- 换手/统计 -------------------------------------
def _record_turn(kind):
    g = _G()
    g["turn_log"].append((g["today"], kind))


def _record_month(today):
    g = _G()
    ym = today[:7]
    g["month_buys"][ym] = g["month_buys"].get(ym, 0) + 1


def _record_trade(reason, pnl):
    """记录每笔卖出（原因 + 浮盈率），供 [卖出] 分原因统计使用。"""
    g = _G()
    g.setdefault("trade_log", []).append((g.get("today", ""), reason, pnl))
    # 同步推进换手记账（卖出单向，配合 _record_turn 的买向构成双向）
    if reason not in ("",):
        g.setdefault("sell_reasons", {}).setdefault(reason, 0)
        g["sell_reasons"][reason] += 1


def _turnover_ok():
    g = _G()
    recent = [t for t in g["turn_log"] if _days_between(t[0], g["today"]) <= TURNOVER_WINDOW_DAYS]
    # 买+卖双向计数，按窗口折算年频次
    n = len(recent)
    span = max([_days_between(recent[0][0], g["today"]) for _ in recent] + [1])
    ann = n * 250.0 / max(span, TURNOVER_WINDOW_DAYS)
    if ann > MAX_ANNUAL_TURNS * 2:
        return False
    return True


def report_stats():
    g = _G()
    log.info("[统计] 大市=%s 情绪=%s 板块强度Top=%s 行业未命中=%d"
             % (g["regime"], g["sentiment"],
                sorted(g["sector_strength"].items(), key=lambda x: -x[1][0])[:3],
                g.get("ind_miss", 0)))
    if g.get("sector_strength") and "" in g["sector_strength"]:
        log.error("[统计] 板块强度里出现空行业名 → sector_map 未生效，"
                  "「行业均值+共振」等于没做（全池归成一个行业）。见上方 [行业] 行")


def log_net_value(context, data=None):
    """逐日净值快照（v1.5 自算持仓市值，修复 HALT/PAUSE 日平台不给持仓定价→市值记0）。

    口径与 热点早盘001 `[净值] 日期 总资产=N 持仓=M 只` 对齐，使 compare_all.py
    可直接入库做同口径横向比较。compare_all.py 抓的是 `总资产=` 字段，故本函数让
    `总资产=` 输出【自算修正权益】(现金 + 持仓市值)，HALT 日才准；原平台
    portfolio_value 另存 `平台账=` 供对照。持仓市值用 v1.4 已验证的 _cur_price
    （数值优先当日价）自算，取不到时退化用成本价，避免市值恒0的假象。
    本函数只读账户、不下单。
    """
    g = _G()
    total, cash = _account(context)
    pos_value = 0.0
    npos = 0
    try:
        live = _get_positions(context)
        for p in live:
            code = p["_code"]
            amount = _pos_field(p, ("amount", "current_amount"))
            if amount is None or amount <= 0:
                continue
            npos += 1
            cur = _cur_price(data, code) if data is not None else None
            if cur is None or cur <= 0:
                # HALT 日 data 可能也无当日价 -> 退化用成本价估值，至少不是 0
                cur = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or 0.0
            pos_value += amount * cur
    except Exception as e:
        _warn("[净值] 持仓估值异常: %s" % e)
    equity = cash + pos_value
    flag = " (HALT日成本补齐)" if (npos > 0 and pos_value <= 0) else ""
    log.info("[净值] %s 总资产=%.0f 现金=%.0f 持仓=%d 只 持仓市值=%.0f 平台账=%.0f%s"
             % (g["today"], equity, cash, npos, pos_value, total, flag))
    # ★V1.6 台账↔平台对账：平台有仓但台账无底 → 当场纳管（成本取平台，次日起纳入退出规则）
    try:
        live_all = _get_positions(context)
        plat = set(_pure(p["_code"]) for p in live_all)
        led = set(g.get("entry_px", {}).keys())
        ghosts = sorted(plat - led - set(g.get("exit_check", {}).keys()))
        if ghosts:
            log.error("[对账] 台账外持仓: %s → 纳管（成本取平台，次日起纳入退出规则）" % ghosts)
            for p in live_all:
                c6 = _pure(p["_code"])
                if c6 not in ghosts:
                    continue
                cost = _pos_field(p, ("cost_basis", "cost_price", "avg_price")) or 0.0
                g["entry_px"][c6] = cost
                g["first_buy"].setdefault(c6, g["today"])
                cur0 = _cur_price(data, c6) if data is not None else None
                g["peak_px"][c6] = cur0 or cost or 0.0
    except Exception as e:
        _warn("[对账] %s" % e)


# ----------------------------- 时钟/入口 ------------------------------------
def _now_hhmm(context):
    try:
        dt = context.blotter.current_dt
        return str(dt)[11:16]
    except Exception:
        return "15:00"


def handle_data(context, data):
    now = _now_hhmm(context)
    g = _G()
    g["today"] = _context_date(context)
    if now == SIGNAL_TIME:
        cands = scan_market(context, data)
        buy_job(context, data)
        report_stats()
    elif now in RISK_TIMES:
        _gate_delever(context, data)
        monitor_risk(context, data, "NORMAL")
    elif now in TAIL_RISK_TIMES:
        monitor_risk(context, data, "TAIL")
    # 逐日收盘净值快照（放在最后，任何分支都执行；仅记录，不影响交易）
    if now == NET_VALUE_TIME:
        log_net_value(context, data)


# 若平台用 run_daily 而非 handle_data，可注册：
# run_daily(before_trading_start, 'before_open')
# run_daily(lambda c,d: handle_data(c,d), SIGNAL_TIME)