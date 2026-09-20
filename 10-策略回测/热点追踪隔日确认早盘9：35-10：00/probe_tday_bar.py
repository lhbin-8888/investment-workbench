# -*- coding: utf-8 -*-
"""
探针策略 v4：彻底查清回测引擎 get_history(\"1d\") 在 09:31/14:55/15:30 三时点的返回结构，
并判定「当日K线 / 盘中实时更新」是否可用——决定路径B能否做日K近似实时价改造。

★PTrade 托管坑（已踩过，固化）★
  1) log.info 不吃额外参数的 % 替换 -> 全部用 % 运算符预格式化。
  2) get_history 合法字段不含 date/datetime/time（日期不在 field 列表）-> 用 fields=None 取全量，再看 dtype.names。
  3) is_dict=True 返回 OrderedDict，值是 numpy 结构化 ndarray（有 dtype.names，无 .index）。

★本版新加的「冻结 vs 实时」判定★
  把每个时点的末行字段签名存进 g，下一时点点对点比较：
    末行有变化 -> 盘中实时更新 -> 可用日K近似实时价；
    末行无变化 -> 冻结 -> 不可用。

跑 3~5 个交易日即可，把日志发回。
"""

FIELDS = ["open", "high", "low", "close", "volume", "preclose", "high_limit", "low_limit"]
PROBE_CODES = ["600000.SS", "000001.SZ"]
import re

PROBE_TIMES = ["09:31", "14:55", "15:05"]

_DATE_CAND = ("date", "datetime", "time", "day", "trading_day", "trading_date")
_CLOSE_CAND = ("close", "price")
_SIG_FIELDS = ("open", "high", "low", "close", "volume", "preclose", "high_limit", "low_limit")


def _now_dt(context):
    for getter in (lambda: context.blotter.current_dt,
                   lambda: context.now,
                   lambda: get_datetime()):
        try:
            return getter()
        except Exception:
            continue
    return None


def _safe(v):
    try:
        return str(v)
    except Exception:
        return "?"


def _norm(x):
    try:
        return re.sub(r"\D", "", str(x))
    except Exception:
        return ""


def _sig(sub):
    """从结构化 ndarray 取末行关键字段签名；无 dtype.names 则返回 None。"""
    if sub is None:
        return None
    dt = getattr(sub, "dtype", None)
    names = getattr(dt, "names", None) if dt is not None else None
    if not names:
        return None
    out = {}
    for f in _SIG_FIELDS:
        if f in names:
            try:
                out[f] = sub[f][-1]
            except Exception:
                pass
    for f in _DATE_CAND:
        if f in names:
            try:
                out["__date__"] = sub[f][-1]
            except Exception:
                pass
    return out


def _sig_str(sig):
    if not sig:
        return "?"
    parts = []
    for k in ("__date__", "open", "high", "low", "close", "volume", "preclose"):
        if k in sig:
            v = sig[k]
            parts.append("%s=%s" % (k, _safe(v)[:14]))
    return " ".join(parts)


def _probe_job(context):
    dt = _now_dt(context)
    today = dt.strftime("%Y-%m-%d") if dt else "?"
    hm = dt.strftime("%H:%M") if dt else "?"
    today_norm = _norm(today)
    log.info("[探针] ===== 时点 %s（引擎日期 %s）=====" % (hm, today))

    result = None
    attempts = [("fields=None", None), ("fields=''", ""), ("fields=OHLCV", FIELDS)]
    for name, farg in attempts:
        try:
            r = get_history(5, "1d", farg, PROBE_CODES, fq="pre", is_dict=True)
        except Exception as e:
            log.info("[探针] 调用风格[%s] 异常: %s" % (name, _safe(e)))
            continue
        if r is None:
            log.info("[探针] 调用风格[%s] 返回 None" % name)
            continue
        result = (name, r)
        log.info("[探针] 调用风格[%s] 成功，返回类型 %s" % (name, type(r).__name__))
        break

    if result is None:
        log.info("[探针] ★结论★ 三种调用风格全部失败，本时点无数据")
        return

    name, r = result
    try:
        top_keys = list(r.keys()) if isinstance(r, dict) else ("<非dict:%s>" % type(r).__name__)
        log.info("[探针] 顶层keys: %s" % _safe(top_keys)[:200])
    except Exception as e:
        log.info("[探针] 取顶层keys异常: %s" % _safe(e))

    if not isinstance(r, dict):
        return
    first_code = PROBE_CODES[0]
    obj = r.get(first_code)
    if obj is not None:
        dt = getattr(obj, "dtype", None)
        names = getattr(dt, "names", None) if dt is not None else None
        if names:
            log.info("[探针] %s dtype.names: %s" % (first_code, _safe(names)))
        else:
            log.info("[探针] %s 类型=%s (无 dtype.names，非结构化)" % (first_code, type(obj).__name__))

    for code in PROBE_CODES:
        sub = r.get(code)
        cur = _sig(sub)
        # 日期字段（若有）与引擎日期比对
        if cur and "__date__" in cur:
            d = cur["__date__"]
            if _norm(d) == today_norm:
                df = " ★含当日K线★"
            else:
                df = " （末项=%s）" % _safe(d)
        else:
            df = " （ndarray无date字段）"
        log.info("[探针] %s 末行: %s%s" % (code, _sig_str(cur), df))

        # 跨时点冻结/实时比对
        prev = g._probe_store.get(code)
        if prev is None:
            log.info("[探针]   └ 首测该代码，已记录基线")
        else:
            changed = (prev != cur)
            if changed:
                log.info("[探针]   └ ★末行有变化=盘中实时更新★（可用日K近似实时价）")
                diffs = []
                for k in set(list(prev.keys()) + list(cur.keys())):
                    if k == "__date__":
                        continue
                    pv, cv = prev.get(k), cur.get(k)
                    if pv != cv:
                        diffs.append("%s:%s→%s" % (k, _safe(pv)[:12], _safe(cv)[:12]))
                if diffs:
                    log.info("[探针]     变化: %s" % "; ".join(diffs)[:400])
            else:
                log.info("[探针]   └ ○末行无变化=冻结（不可用）")
        g._probe_store[code] = cur

    log.info("[探针] 判读: 15:30 末行含当日+跨时点有变化 -> 引擎给当日且实时更新，可做日K近似改造；否则转模拟盘")


def initialize(context):
    g._probe_store = {}
    log.info("[探针] initialize: 探针启动，监测时点 %s，样本 %s"
             % (",".join(PROBE_TIMES), _safe(PROBE_CODES)))
    for t in PROBE_TIMES:
        try:
            run_daily(context, _probe_job, time=t)
        except Exception as e:
            log.info("[探针] run_daily(%s) 失败: %s" % (t, _safe(e)))
