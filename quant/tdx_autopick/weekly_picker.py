# -*- coding: utf-8 -*-
"""
周线选股器（路线 A：本地日线 → 周线聚合，零网络依赖）
====================================================
依据「周线 MA3/MA5/MA10 多头 + 3周刚上穿5周 + 3周已上穿20周 + 一阳穿三线 + 近5日累计涨幅>5%」早期突破信号制作。

  核心判据（全部满足才入选）：
    1) 多头排列：MA3 > MA5 > MA10（3/5/10 周三线短期多头）
    2) 3周均线刚上穿5周均线：本周 MA3 上穿 MA5（金叉刚发生）
    3) 3周均线已上穿20周均线：MA3 曾从下方上穿 MA20（中期趋势已转多）
    4) 最近一根周K线「一阳穿三线」：
         · 当周收阳（收盘 > 开盘）
         · 收盘价站上 MA3、MA5、MA10 三线
         · 当周最低价低于三线中最低者（MA10），即从下方穿刺上来
    5) 量能：本周量能相对前 10 周均量放大（加分，非硬门槛）
    6) 动量确认：最近 5 个交易日（日线）累计涨幅 > 5%（无近期上攻动能则不入选）

  剔除规则（命中即不入选）：
    · 日线：最近 3 个交易日连续下跌；或最近 10 个交易日连续下跌累计幅度 >8%，
            或较近期高点回撤 >12%
    · 周线：截至最新一周往前 13 周（≈3 个月）累计涨幅 >30%
    · 名称以 ST / *ST 开头、北交所股、净利润<0 的亏损股、880/881 板块指数

数据来源：本地 D:\\TDX\\vipdoc\\{sh,sz}\\lday\\*.day —— 把日线按"周五"聚合为周线。
  这样即便本机从未下载过 .week 文件也能跑，且永远是本机最新日线口径。

写入板块：独立「AI周线」板块（AIWEEK.blk），与日线「AI自选」互不影响。

触发：默认每日盘后 15:00 后自动执行（计划任务每日 15:30 调用）；--force 可随时手动跑。
"""

import os
import sys
import struct
import datetime
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdx_writer as tw

# ===================== 路径配置 =====================
TDX_ROOT = r"D:\TDX"
DAY_DIRS = {
    "sh": os.path.join(TDX_ROOT, "vipdoc", "sh", "lday"),
    "sz": os.path.join(TDX_ROOT, "vipdoc", "sz", "lday"),
}
REPORT_DIR = os.path.dirname(os.path.abspath(__file__))

# ===================== 日志（与 run_picker 一致：同时写控制台 + 当日日志文件）=====================
# 2026-10-30 修正：原周线任务经 .vbs 静默运行，stdout 全部丢失，跑没跑/成没成功无迹可查。
# 改为脚本自带文件日志，无论被计划任务调用还是手动运行，都落盘到 weekly_YYYYMMDD.log。
LOG_DIR = REPORT_DIR


def log_line(msg):
    """同时写控制台和日志文件（与 run_picker.log_line 同款）"""
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(
                LOG_DIR,
                f"weekly_{datetime.datetime.now():%Y%m%d}.log"),
                "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ===================== 选股参数 =====================
# 最少需要的周线根数（MA20 + 13周涨幅窗口 + 安全余量）
MIN_WEEKLY_BARS = 60
# 日线弱势过滤窗口（交易日）：取最近 N 个交易日的日线做"连续下跌/回撤"检测
DAILY_CHECK_WINDOW = 10            # 最近 10 个交易日
DAILY_DECLINE_AMP_LIMIT = 0.08    # 日线连续下跌累计幅度上限 8%（>8% 即视为转弱）
DAILY_DRAWNDOWN_LIMIT = 0.12      # 日线较近期高点回撤上限 12%
# 日线连续下跌天数剔除：截至最新交易日，最近 N 个交易日连续下跌即剔除
CONSEC_DOWN_DAYS = 3
# 周线涨幅剔除：截至最新一周，往前 N 周（≈3个月）累计涨幅超过阈值即剔除
RECENT_GAIN_WINDOW = 13   # 13 周 ≈ 3 个月
RECENT_GAIN_LIMIT = 0.30  # 30%
# 一阳穿三线：当周最低价需低于三线中最低者(MA10)的比例容差（1.01 = 允许 1% 误差）
PIERCE_TOL = 1.01
# 3周已上穿20周：在最近 N 周内曾出现 MA3 从下方上穿 MA20（确认中期转多）
CROSS_LOOKBACK = 60
# 量能对比窗口（周）与放量倍数（用于评分与"放量"标签）
VOL_MA_WINDOW = 10
BREAKOUT_VOL_RATIO = 1.5   # 本周量 ≥ 前 10 周均量 ×1.5 视为放量
# 动量确认：最近 5 个交易日累计涨幅下限（小数，0.05=5%）；不足则不入选
RECENT5_GAIN_LIMIT = 0.05
DEFAULT_MAX = 80           # 默认最多入选（保护板块不至于过大）

REC = struct.Struct("<iiiiifii")  # 32 字节一条日线记录


# ===================== 数据层：日线 → 周线 =====================
def parse_day_file(path):
    """读一个 .day 文件，返回按时间升序的日线列表 [(date_int, o,h,l,c, vol, amt), ...]"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return None
    n = len(data) // 32
    if n == 0:
        return None
    # 一次性整体解包，比逐条 unpack 快一个数量级
    fmt = "<" + ("iiiiifii" * n)
    vals = struct.unpack(fmt, data[:32 * n])
    bars = []
    for i in range(n):
        b = i * 8
        d = vals[b]
        o = vals[b + 1] / 100.0
        h = vals[b + 2] / 100.0
        l = vals[b + 3] / 100.0
        c = vals[b + 4] / 100.0
        amt = vals[b + 5]
        vol = vals[b + 6]
        bars.append((d, o, h, l, c, vol, amt))
    return bars


def to_weekly(bars):
    """
    日线聚合为周线。按"周五"分桶：每个自然周的交易日合并为一根周线，
    周线日期取该周周五（与通达信周线口径一致）。
    返回 [(date_int(Friday), o,h,l,c, vol, amt), ...] 升序；不足则返回 []
    """
    if not bars:
        return []
    # date_int -> 桶(friday date_int)
    buckets = {}
    for (d, o, h, l, c, vol, amt) in bars:
        dt = datetime.date(d // 10000, (d % 10000) // 100, d % 100)
        fri = dt + datetime.timedelta(days=(4 - dt.weekday()))  # Mon=0..Fri=4
        fid = fri.year * 10000 + fri.month * 100 + fri.day
        if fid not in buckets:
            buckets[fid] = {"o": o, "h": h, "l": l, "c": c, "vol": vol, "amt": amt}
        else:
            bk = buckets[fid]
            bk["h"] = max(bk["h"], h)
            bk["l"] = min(bk["l"], l)
            bk["c"] = c
            bk["vol"] += vol
            bk["amt"] += amt
    out = [(fid, b["o"], b["h"], b["l"], b["c"], b["vol"], b["amt"])
           for fid, b in buckets.items()]
    out.sort(key=lambda x: x[0])
    return out


def sma(vals, n):
    """简单移动平均，返回 list（前 n-1 个为 None）"""
    if len(vals) < n:
        return [None] * len(vals)
    out = [None] * (n - 1)
    s = sum(vals[:n])
    out.append(s / n)
    for i in range(n, len(vals)):
        s += vals[i] - vals[i - n]
        out.append(s / n)
    return out


def consec_daily_down_days(closes, n=CONSEC_DOWN_DAYS):
    """
    最近 n 个交易日是否连续下跌（每根收盘 < 上一根收盘）。
    closes 为日线收盘价升序列表；不足 n 根返回 False（视为无信号）。
    """
    if not closes or len(closes) < n:
        return False
    for i in range(len(closes) - 1, len(closes) - n, -1):
        if closes[i] >= closes[i - 1]:
            return False
    return True


def crossed_up(ma_a, ma_b, i, lookback=CROSS_LOOKBACK):
    """
    截至下标 i，序列 ma_a 是否在最近 lookback 周内曾从下方上穿 ma_b
    （存在某 j∈[i-lookback, i] 使 ma_a[j-1] <= ma_b[j-1] 且 ma_a[j] > ma_b[j]），
    且当前 ma_a[i] > ma_b[i]。
    用于"3周均线已上穿20周均线"等中期趋势确认。None 不参与比较。
    """
    if ma_a[i] is None or ma_b[i] is None or ma_a[i] <= ma_b[i]:
        return False
    start = max(1, i - lookback)
    for j in range(start, i + 1):
        a0, b0, a1, b1 = ma_a[j - 1], ma_b[j - 1], ma_a[j], ma_b[j]
        if None in (a0, b0, a1, b1):
            continue
        if a0 <= b0 and a1 > b1:
            return True
    return False


def daily_weakness(bars, window=DAILY_CHECK_WINDOW):
    """
    用日线 bars 计算两项"已转弱"指标，返回 (连跌累计幅度, 峰值回撤)，均为小数（0.12=12%）。
      · 连跌累计幅度：从最新交易日往前，连续下跌日的累计跌幅（遇非下跌日停止）。
      · 峰值回撤：最新收盘较窗口内最高收盘的跌幅。
    bars 不足 2 根时返回 (0.0, 0.0)（视为无信号）。
    """
    if not bars:
        return 0.0, 0.0
    closes = [b[4] for b in bars][-window:]
    n = len(closes)
    if n < 2:
        return 0.0, 0.0
    drop = 0.0
    for i in range(n - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            drop += (closes[i - 1] - closes[i]) / closes[i - 1]
        else:
            break
    peak = max(closes)
    dd = (peak / closes[-1] - 1) if closes[-1] else 0.0  # 正数幅度（低于峰值多少）
    return drop, dd


# ===================== 选股逻辑 =====================
def evaluate(weekly, gain_limit=RECENT_GAIN_LIMIT, gain_window=RECENT_GAIN_WINDOW,
             daily_bars=None,
             d_decline_amp_limit=DAILY_DECLINE_AMP_LIMIT,
             d_drawdown_limit=DAILY_DRAWNDOWN_LIMIT,
             daily_window=DAILY_CHECK_WINDOW,
             consec_down_days=CONSEC_DOWN_DAYS,
             pierce_tol=PIERCE_TOL,
             cross_lookback=CROSS_LOOKBACK,
             recent5_gain_limit=RECENT5_GAIN_LIMIT):
    """
    对一只股票的周线施加「MA3/MA5/MA10 多头 + 3周刚上穿5周 + 3周已上穿20周 + 一阳穿三线」信号。
    返回 None（不入选）或 (score, reasons, info)。
    weekly: [(date, o,h,l,c, vol, amt), ...]
    gain_limit / gain_window: 近 gain_window 周累计涨幅超过 gain_limit 即剔除
    """
    if len(weekly) < MIN_WEEKLY_BARS:
        return None
    closes = [w[4] for w in weekly]
    vols = [w[5] for w in weekly]
    L = len(closes)
    i = L - 1  # 最新一周下标

    # —— 日线剔除（先于周线判据，过滤已转弱票）——
    if daily_bars is not None and len(daily_bars) >= 2:
        d_closes = [b[4] for b in daily_bars]
        # 剔除：最近 consec_down_days 个交易日连续下跌
        if consec_daily_down_days(d_closes, consec_down_days):
            return None
        # 剔除：最近 daily_window 交易日，日线连跌累计幅度>限 或 较近期高点回撤>限
        d_amp, d_dd = daily_weakness(daily_bars, daily_window)
        if d_amp > d_decline_amp_limit or d_dd > d_drawdown_limit:
            return None
        # 动量确认：最近 5 个交易日累计涨幅需 > 阈值（不足 5 日则跳过该检查，保守保留）
        if len(d_closes) >= 5:
            gain5 = d_closes[-1] / d_closes[-5] - 1
            if gain5 <= recent5_gain_limit:
                return None

    # —— 剔除：截至最新一周往前 gain_window 周累计涨幅 > gain_limit（高位过度拉升）——
    if L > gain_window:
        gain_recent = closes[-1] / closes[-1 - gain_window] - 1
        if gain_recent > gain_limit:
            return None

    # —— 均线计算 ——
    ma3 = sma(closes, 3)
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    if None in (ma3[i], ma5[i], ma10[i], ma20[i]):
        return None
    m3, m5, m10, m20 = ma3[i], ma5[i], ma10[i], ma20[i]
    m3_prev, m5_prev = ma3[i - 1], ma5[i - 1]
    c = closes[i]
    c_prev = closes[i - 1]
    o_i = weekly[i][1]
    low_i = weekly[i][3]

    # —— 核心信号（全部满足才入选）——
    # 1) 多头排列：MA3 > MA5 > MA10
    if not (m3 > m5 > m10):
        return None
    # 2) 3周均线刚上穿5周均线（本周金叉）
    if not (m3 > m5 and m3_prev <= m5_prev):
        return None
    # 3) 3周均线已上穿20周均线（中期趋势已转多）
    if not crossed_up(ma3, ma20, i, cross_lookback):
        return None
    # 4) 最近一根周K线一阳穿三线：收阳 + 收盘站上三线 + 最低价低于三线最低者(MA10)
    if not (c > o_i):
        return None
    if not (c > m3 and c > m5 and c > m10):
        return None
    if not (low_i <= m10 * pierce_tol):
        return None

    # —— 量能对比（用于评分与"放量"标签）——
    if i >= VOL_MA_WINDOW:
        vol_base = sum(vols[i - VOL_MA_WINDOW:i]) / VOL_MA_WINDOW
    else:
        vol_base = sum(vols[:i]) / max(1, i)
    vol_ratio = (vols[i] / vol_base) if vol_base else 0
    wk_gain = c / c_prev - 1 if c_prev else 0

    # —— 计分（越强越高，便于排序）——
    score = 100.0
    score += wk_gain * 100                       # 周涨幅贡献
    score += (vol_ratio - 1) * 20                # 放量贡献
    score += min(max(c / m3 - 1, 0), 0.2) * 50   # 站上3周线幅度
    score += min(max(c / m20 - 1, 0), 0.3) * 30  # 站上20周线幅度

    reasons = ["3周上穿5周+已上穿20周+一阳穿三线"]
    if vol_ratio >= BREAKOUT_VOL_RATIO:
        reasons.append(f"放量{vol_ratio:.1f}倍")
    reasons.append(f"周涨幅{wk_gain*100:.1f}%")

    return score, reasons, (m3, m5, m10, m20, c, wk_gain, vol_ratio)


def scan_all(max_n=DEFAULT_MAX, verbose=False,
             gain_limit=RECENT_GAIN_LIMIT, gain_window=RECENT_GAIN_WINDOW,
             exclude_loss=True,
             d_decline_amp_limit=DAILY_DECLINE_AMP_LIMIT,
             d_drawdown_limit=DAILY_DRAWNDOWN_LIMIT, daily_window=DAILY_CHECK_WINDOW,
             recent5_gain_limit=RECENT5_GAIN_LIMIT):
    """扫描全部本地日线文件，返回 [(score, code, reasons, info), ...] 按分降序"""
    global _ST_SKIPPED, _LOSS_SKIPPED, _BSE_SKIPPED
    results = []
    total = 0
    _ST_SKIPPED = 0
    _LOSS_SKIPPED = 0
    _BSE_SKIPPED = 0
    for market, ddir in DAY_DIRS.items():
        if not os.path.isdir(ddir):
            continue
        for fn in os.listdir(ddir):
            if not fn.endswith(".day"):
                continue
            # 文件名形如 sh600519.day / sz000001.day
            stem = fn[:-4]  # 去 .day → sh600519
            if len(stem) != 8 or stem[:2] not in ("sh", "sz") or not stem[2:].isdigit():
                continue
            code = stem[2:]            # 6 位代码
            # 剔除板块指数（880/881 开头）：周线选股只针对个股，
            # 指数不应进入「AI周线」个股池（2026-10-30 验证发现漏选）。
            if code[:3] in ("880", "881"):
                continue
            # 剔除北交所股（83/87/88/43/92 开头；to_tdx_code 白名单也会兜底排除）
            if is_bse_stock(code):
                _BSE_SKIPPED += 1
                continue
            # 复用 tdx_writer 的前缀白名单，只保留个股，剔除指数/基金
            if tw.to_tdx_code(code) is None:
                continue
            # 剔除 ST / *ST 股（按本地名称清单判断）
            if is_st_stock(code):
                _ST_SKIPPED += 1
                continue
            # 剔除亏损股（净利润 JLY < 0；无财务数据则保留，保守处理）
            if exclude_loss and is_loss_stock(code):
                _LOSS_SKIPPED += 1
                continue
            total += 1
            bars = parse_day_file(os.path.join(ddir, fn))
            weekly = to_weekly(bars)
            ev = evaluate(weekly, gain_limit, gain_window, bars,
                          d_decline_amp_limit, d_drawdown_limit, daily_window,
                          recent5_gain_limit=recent5_gain_limit)
            if ev is None:
                continue
            score, reasons, info = ev
            results.append((score, code, reasons, info))
            if verbose and len(results) % 50 == 0:
                print(f"  已扫描 {total} 只，命中 {len(results)} 只 ...")
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:max_n], total


# ===================== 股票名称（用于剔除 ST） =====================
# 通达信本地代码→名称清单（管道分隔：代码|名称|拼音...），用于识别 ST / *ST 股。
NAME_FILE = os.path.join(TDX_ROOT, "T0002", "hq_cache", "infoharbor_ex.code")
_NAME_MAP = None
_ST_SKIPPED = 0
_LOSS_SKIPPED = 0
_BSE_SKIPPED = 0


def load_name_map():
    """读取本地代码→名称映射并缓存到模块级，返回 {6位代码: 名称}。"""
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    m = {}
    try:
        with open(NAME_FILE, encoding="gbk", errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("|")
                if len(parts) >= 2 and parts[0].isdigit():
                    m[parts[0]] = parts[1]
    except Exception:
        pass
    _NAME_MAP = m
    return m


def is_st_stock(code):
    """按名称判断是否为 ST / *ST 股（需剔除）。非 ST 或名称缺失返回 False。"""
    name = load_name_map().get(code, "")
    if not name:
        return False
    # 名称形如 "ST某某" / "*ST某某"；去掉前导 '*' 后判断是否以 ST 开头
    return name.lstrip("*").upper().startswith("ST")


def is_bse_stock(code):
    """北交所股（代码以 83/87/88/43/92 开头）需剔除。

    注：to_tdx_code 的白名单本就不含北交所前缀，会兜底排除；
    此处显式判定是为了计入跳过计数并在说明书里明确口径。
    （880/881 板块指数已在 scan_all 中被更前的分支跳过，不会误杀到这里）
    """
    return code[:2] in ("83", "87", "88", "43", "92")


# ===================== 财务数据（用于剔除亏损股） =====================
# 通达信本地财务基本面库（dBase III 格式）：含净利润(JLY)等字段。
FINANCE_FILE = os.path.join(TDX_ROOT, "T0002", "hq_cache", "base.dbf")
_FIN_MAP = None


def load_finance_map():
    """解析 base.dbf，返回 {6位代码: 净利润(JLY, float)}（无法解析为 None）。"""
    global _FIN_MAP
    if _FIN_MAP is not None:
        return _FIN_MAP
    m = {}
    try:
        data = open(FINANCE_FILE, "rb").read()
        if len(data) < 32:
            _FIN_MAP = m
            return m
        hlen = struct.unpack("<H", data[8:10])[0]
        rlen = struct.unpack("<H", data[10:12])[0]
        # 解析字段描述符（32字节/个，遇 0x0D 结束）
        fields = []
        pos = 1  # 记录首字节为删除标志，字段从偏移1开始
        off = 32
        while data[off] != 0x0D:
            fname = data[off:off + 11].split(b"\x00")[0].decode("ascii", "replace").strip()
            flen = data[off + 16]
            fields.append((fname, pos, flen))
            pos += flen
            off += 32
        gpd = next((f for f in fields if f[0].upper() == "GPDM"), None)
        jly = next((f for f in fields if f[0].upper() == "JLY"), None)
        if gpd is None or jly is None:
            _FIN_MAP = m
            return m
        _, gpos, glen = gpd
        _, jpos, jlen = jly
        rpos = hlen
        for _ in range(struct.unpack("<I", data[4:8])[0]):
            rec = data[rpos:rpos + rlen]
            rpos += rlen
            if len(rec) < rlen:
                break
            code = rec[gpos:gpos + glen].decode("ascii", "ignore").strip()
            if not code.isdigit():
                continue
            raw = rec[jpos:jpos + jlen].strip()
            val = None
            if raw and raw != b"*":
                try:
                    val = float(raw)
                except ValueError:
                    val = None
            m[code] = val
    except Exception:
        pass
    _FIN_MAP = m
    return m


def is_loss_stock(code):
    """净利润(JLY) < 0 视为亏损股，需剔除；无财务数据则保留（保守）。"""
    jly = load_finance_map().get(code)
    if jly is None:
        return False
    return jly < 0


# ===================== 周五收盘触发 =====================
def should_run_now():
    """默认每日盘后 15:00 之后触发（计划任务每日 15:30 调用）；返回 (bool, 说明)"""
    now = datetime.datetime.now()
    if now.hour < 15:
        return False, f"尚未收盘（15:00 后才触发），当前 {now.hour}:{now.minute:02d}，跳过"
    return True, "盘后触发窗口，开始周线选股"


# ===================== 报表 =====================
def write_report(block_name, rows, total_scanned, ts=None):
    ts = ts or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(REPORT_DIR, f"周线选股结果_{datetime.datetime.now():%Y%m%d}.md")
    lines = [
        "# 周线选股结果（MA3/MA5/MA10 多头 + 一阳穿三线）",
        "",
        f"- 生成时间：{ts}",
        f"- 数据口径：本地 D:\\TDX\\vipdoc\\{{sh,sz}}\\lday（日线聚合为周线）",
        f"- 扫描个股：{total_scanned} 只",
        f"- 入选板块：{block_name}",
        f"- 入选数量：{len(rows)}",
        "",
        "| 排名 | 代码 | 周收盘 | 周涨幅 | MA3 | MA5 | MA10 | MA20 | 信号 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, (score, code, reasons, info) in enumerate(rows, 1):
        m3, m5, m10, m20, c, wk_gain, vol_ratio = info
        lines.append(
            f"| {rank} | {code} | {c:.2f} | {wk_gain*100:.1f}% | "
            f"{m3:.2f} | {m5:.2f} | {m10:.2f} | {m20:.2f} | "
            f"{'、'.join(reasons) if reasons else '-'} |")
    lines.append("")
    lines.append("> 判据：MA3>MA5>MA10 多头排列 + 本周 MA3 刚上穿 MA5 + MA3 已上穿 MA20（中期转多）"
                 " + 最近周K收阳且收盘站上三线、最低价穿刺三线（一阳穿三线）"
                 " + 最近5个交易日累计涨幅>5%（动量确认）。")
    lines.append("> 附加剔除：最近3日连跌、最近10日日线连跌累计>8%或较近期高点回撤>12%、"
                 "近13周涨幅>30%、ST/*ST 股、北交所股、亏损股（净利润<0）。")
    lines.append("")
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n---\n\n")
    return path


# ===================== 主流程 =====================
def main():
    ap = argparse.ArgumentParser(
        description="周线选股器（MA3/MA5/MA10 多头 + 3周上穿5周 + 已上穿20周 + 一阳穿三线）")
    ap.add_argument("--force", action="store_true",
                    help="忽略盘后时间校验，随时跑（手动用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只输出结果，不写通达信板块")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX,
                    help=f"最多入选数量，默认 {DEFAULT_MAX}")
    ap.add_argument("--consec-down", type=int, default=CONSEC_DOWN_DAYS,
                    help=f"日线连续下跌剔除天数，默认 {CONSEC_DOWN_DAYS}（最近 N 日连跌即剔）")
    ap.add_argument("--daily-decline-amp", type=float, default=DAILY_DECLINE_AMP_LIMIT * 100,
                    help=f"日线连续下跌累计幅度剔除阈值（%），超过即剔除，默认 {DAILY_DECLINE_AMP_LIMIT*100:.0f}")
    ap.add_argument("--daily-dd", type=float, default=DAILY_DRAWNDOWN_LIMIT * 100,
                    help=f"日线较近期高点回撤剔除阈值（%），超过即剔除，默认 {DAILY_DRAWNDOWN_LIMIT*100:.0f}")
    ap.add_argument("--daily-window", type=int, default=DAILY_CHECK_WINDOW,
                    help=f"日线弱势检测窗口（交易日），默认 {DAILY_CHECK_WINDOW}")
    ap.add_argument("--gain", type=float, default=RECENT_GAIN_LIMIT * 100,
                    help=f"近三个月涨幅剔除阈值（%），超过即剔除，默认 {RECENT_GAIN_LIMIT*100:.0f}")
    ap.add_argument("--gain-weeks", type=int, default=RECENT_GAIN_WINDOW,
                    help=f"近三个月涨幅统计窗口（周），默认 {RECENT_GAIN_WINDOW}")
    ap.add_argument("--recent5", type=float, default=RECENT5_GAIN_LIMIT * 100,
                    help=f"近5个交易日累计涨幅下限（%），低于即不入选，默认 {RECENT5_GAIN_LIMIT*100:.0f}")
    ap.add_argument("--verbose", action="store_true", help="打印扫描进度")
    ap.add_argument("--no-loss", action="store_true",
                    help="不排除亏损股（默认剔除净利润<0的股票）")
    args = ap.parse_args()

    if not args.force:
        ok, msg = should_run_now()
        log_line(f"[触发] {msg}")
        if not ok:
            return

    gain_limit = args.gain / 100.0
    log_line(f"[扫描] 开始扫描本地日线数据 ...（max={args.max}，"
          f"剔除：最近{args.consec_down}日连跌 / 最近{args.daily_window}日日线连跌>"
          f"{args.daily_decline_amp:.0f}%或回撤>{args.daily_dd:.0f}% / "
          f"近{args.gain_weeks}周涨幅>{args.gain:.0f}% / ST/*ST / 北交所 / "
          f"{'不剔除' if args.no_loss else '剔除'}亏损股；"
          f"信号：MA3>MA5>MA10 多头 + 3周刚上穿5周 + 3周已上穿20周 + 一阳穿三线"
          f" + 近5日累计涨幅>{args.recent5:.0f}%）")
    t0 = datetime.datetime.now()
    rows, total = scan_all(max_n=args.max, verbose=args.verbose,
                           gain_limit=gain_limit, gain_window=args.gain_weeks,
                           exclude_loss=not args.no_loss,
                           d_decline_amp_limit=args.daily_decline_amp / 100.0,
                           d_drawdown_limit=args.daily_dd / 100.0,
                           daily_window=args.daily_window,
                           recent5_gain_limit=args.recent5 / 100.0)
    dt = (datetime.datetime.now() - t0).total_seconds()
    log_line(f"[扫描] 完成：扫描 {total} 只个股，命中 {len(rows)} 只，用时 {dt:.1f}s")
    if _ST_SKIPPED:
        log_line(f"[筛选] 剔除 ST/*ST 股 {_ST_SKIPPED} 只")
    if _BSE_SKIPPED:
        log_line(f"[筛选] 剔除北交所股 {_BSE_SKIPPED} 只")
    if _LOSS_SKIPPED:
        log_line(f"[筛选] 剔除亏损股（净利润<0）{_LOSS_SKIPPED} 只")

    if not rows:
        log_line("[结果] 本轮无符合「MA3/MA5/MA10 多头 + 一阳穿三线 + 近5日涨幅>5%」信号的个股")
        return

    # 打印 Top 结果
    print(f"\n{'排名':<5}{'代码':<9}{'周收盘':<10}{'周涨幅':<9}信号")
    for rank, (score, code, reasons, info) in enumerate(rows[:20], 1):
        m3, m5, m10, m20, c, wk_gain, vol_ratio = info
        sig = "、".join(reasons) if reasons else "-"
        print(f"{rank:<5}{code:<9}{c:<10.2f}{wk_gain*100:<8.1f}% {sig}")
    if len(rows) > 20:
        print(f"  ... 其余 {len(rows)-20} 只见板块/报表")

    codes = [code for _, code, _, _ in rows]
    report_path = write_report("AI周线", rows, total)
    log_line(f"[报表] {report_path}")

    if not args.dry_run:
        ok, n, fpath = tw.write_block("AI周线", codes)
        if ok:
            log_line(f"[写入] 板块「AI周线」写入 {n} 只  ✓  ({fpath})")
            log_line("       在通达信 → 报价 → 自选股 → 右键刷新 → 双击「AI周线」即可查看")
        else:
            log_line(f"[写入] 失败：{fpath}")
    else:
        log_line("[dry-run] 未写入板块")


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        try:
            log_line(f"[致命异常] 周线选股中断：{_e}")
        except Exception:
            pass
        raise
