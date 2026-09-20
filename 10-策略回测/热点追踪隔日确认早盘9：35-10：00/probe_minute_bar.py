# -*- coding: utf-8 -*-
"""
探针策略 v7：修正 v6 的两处致命问题
  1) v6 的「判读」结论是硬编码字符串(永远"分钟含当日")，与真实数据无关 -> 本版改为按真实提取到的分钟末行日期做判定。
  2) v6 给分钟传了不含 datetime 的字段列表(且含不支持的 preclose)，导致返回结构里取不到日期 -> 本版分钟改用 fields=None(取默认全字段，含 datetime)，并打印字段名/原始值便于定位。
只测不下单，安全。
注意：PTrade托管为 Python3.5，日志必须先用 % 预格式化再传给 log.info（引擎不替换 %s）。
"""
import re
import traceback

PROBE_TIMES = ["09:31", "14:55", "15:05"]
SAMPLES = ["600000.SS", "000001.SZ"]


def _norm_date(v):
    if v is None:
        return None
    s = str(v)
    m = re.sub(r'[^0-9]', '', s)
    return m[:8] if len(m) >= 8 else m


def _engine_date(context):
    try:
        dt = context.current_dt
    except Exception:
        dt = None
    s = str(dt)
    m = re.sub(r'[^0-9]', '', s)
    return m[:8] if len(m) >= 8 else m


def _last_dt_debug(r, code):
    """返回 (norm_date, raw_value, field_names) 便于调试"""
    if not isinstance(r, dict):
        return None, None, None
    sub = r.get(code)
    if sub is None:
        return None, None, None
    try:
        n = len(sub)
        if n == 0:
            return None, None, None
        row = sub[n - 1]
    except Exception:
        return None, None, None
    names = getattr(getattr(sub, 'dtype', None), 'names', None)
    if names and ('datetime' in names):
        try:
            return _norm_date(row['datetime']), row['datetime'], names
        except Exception:
            pass
    if names and ('date' in names):
        try:
            return _norm_date(row['date']), row['date'], names
        except Exception:
            pass
    return None, None, names


def probe(context):
    try:
        ed = _engine_date(context)
        log.info("===== 时点(引擎日期 %s) =====" % ed)

        # 日K 对照（fields=None 取默认全字段，已验证可用）
        try:
            r = get_history(5, "1d", None, SAMPLES, fq="pre", is_dict=True)
            nd, raw, names = _last_dt_debug(r, SAMPLES[0])
            log.info("[探针] 日K[1d] 末行日期=%s (原始=%s 字段=%s)" % (nd, raw, names))
        except Exception as e:
            log.info("[探针] 日K[1d] 异常: %s" % e)

        # 分钟：fields=None 取默认全字段(含 datetime)，分频率打印并收集真实日期
        min_dates = []
        for freq in ["1m", "1min"]:
            try:
                r = get_history(240, freq, None, SAMPLES, fq="pre", is_dict=True)
                nd, raw, names = _last_dt_debug(r, SAMPLES[0])
                same = (nd == ed)
                log.info("[探针] 分钟[%s] 末行日期=%s (原始=%s 字段=%s) %s" % (
                    freq, nd, raw, names, "★含当日" if same else "○非当日"))
                if nd is not None:
                    min_dates.append(nd)
            except Exception as e:
                log.info("[探针] 分钟[%s] 异常: %s" % (freq, e))

        # 判读：基于真实数据，不再硬编码
        if min_dates and ed in min_dates:
            verdict = "★★ 分钟含当日(%s) -> 路径B可用分钟近似改造 ★★" % ed
        else:
            verdict = "XX 分钟不含当日(末行=%s, 引擎=%s) -> 路径B无法用分钟近似, 转模拟盘" % (min_dates, ed)
        log.info("[探针] 判读: " + verdict)
    except Exception:
        log.info("[探针] 顶层异常:\n" + traceback.format_exc())


def initialize(context):
    log.info("探针v7启动 监测时点 %s 样本 %s" % (",".join(PROBE_TIMES), SAMPLES))
    for t in PROBE_TIMES:
        # 本引擎 run_daily 签名 = run_daily(context, func, time=...)
        run_daily(context, probe, time=t)
