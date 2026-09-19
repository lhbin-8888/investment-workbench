# -*- coding: utf-8 -*-
"""
探针策略：验证回测引擎在不同时点 get_history("1d") 能否返回「当日」K线。
目的：决定路径B（尾盘确认+次日回踩买）能否用日K近似实时价做回测改造。

★判读方法★（跑 3~5 个交易日即可，把日志发回）：
  [探针] 行会打印 当前引擎日期 vs 最后一根日K的日期：
    · 15:05 时 最后一根日K日期 == 当天   → 引擎在收盘后给当日K线，
      可以做「日K近似实时价」改造，路径B回测三缺陷可一次性解决。
    · 15:05 时 只到 T-1                  → 引擎不给当日K，
      路径B在本框架不可回测，转模拟盘验证。
    · 14:55 时若已含当日（部分K）         → 连 14:50 尾盘确认也能近似回测。
  09:31 那次是对照组：正常应只到 T-1（若已含当日说明引擎连盘中都给，更好）。

本探针完全自包含、只读不下单，不影响任何现有策略文件。
"""

PROBE_CODES = ["600000.SS", "000001.SZ"]
FIELDS = ["open", "high", "low", "close", "volume"]
PROBE_TIMES = ["09:31", "14:55", "15:05"]


def _now_dt(context):
    for getter in (lambda: context.blotter.current_dt,
                   lambda: context.now,
                   lambda: get_datetime()):
        try:
            return getter()
        except Exception:
            continue
    return None


def _probe_job(context):
    dt = _now_dt(context)
    today = dt.strftime("%Y-%m-%d") if dt else "?"
    hm = dt.strftime("%H:%M") if dt else "?"
    log.info("[探针] ===== 时点 %s（引擎日期 %s）=====", hm, today)

    result = None
    # 尝试三种调用风格，取第一个成功的
    attempts = [
        ("fq+is_dict", dict(fq="pre", is_dict=True)),
        ("is_dict", dict(is_dict=True)),
        ("裸调", dict()),
    ]
    for name, kw in attempts:
        try:
            r = get_history(5, "1d", FIELDS, PROBE_CODES, **kw)
        except Exception as e:
            log.info("[探针] 调用风格[%s] 异常: %s", name, repr(e))
            continue
        if r is None:
            log.info("[探针] 调用风格[%s] 返回 None", name)
            continue
        result = (name, r)
        log.info("[探针] 调用风格[%s] 成功，返回类型 %s", name, type(r).__name__)
        break

    if result is None:
        log.info("[探针] ★结论★ 三种调用风格全部失败，本时点无数据")
        return

    name, r = result
    # 逐代码解析最后一根K线的日期与收盘
    items = []
    if isinstance(r, dict):
        items = list(r.items())
    else:
        # 单表 / MultiIndex：把两个代码各试一次
        for code in PROBE_CODES:
            try:
                sub = r.loc[code]
            except Exception:
                try:
                    sub = r[code]
                except Exception:
                    continue
            items.append((code, sub))

    for code, sub in items:
        last_date, last_close, n_rows = "?", "?", 0
        try:
            try:
                n_rows = len(sub)
            except Exception:
                pass
            # DataFrame：取 index 最后一行
            idx = getattr(sub, "index", None)
            if idx is not None and len(idx):
                last_date = str(idx[-1])[:10]
                row = sub.iloc[-1] if hasattr(sub, "iloc") else None
                if row is not None:
                    try:
                        last_close = float(row["close"])
                    except Exception:
                        last_close = "?"
            else:
                # list[dict] / dict 形态
                if isinstance(sub, dict):
                    last_date = str(sub.get("date", "?"))[:10]
                    last_close = sub.get("close", "?")
                elif isinstance(sub, (list, tuple)) and sub:
                    last = sub[-1]
                    if isinstance(last, dict):
                        last_date = str(last.get("date", "?"))[:10]
                        last_close = last.get("close", "?")
        except Exception as e:
            log.info("[探针] 解析 %s 异常: %s", code, repr(e))
        flag = ""
        if last_date == today:
            flag = "  ★含当日K线★"
        elif last_date not in ("?",):
            flag = "  （仅到该日，无当日）"
        log.info("[探针] %s 最后一根日K: 日期=%s close=%s 行数=%s%s",
                 code, last_date, last_close, n_rows, flag)

    log.info("[探针] 判读: 若上方出现 ★含当日K线★ → 引擎该时点给当日数据；"
             "三时点分别对应 开盘对照/尾盘14:55/收盘15:05")


def initialize(context):
    log.info("[探针] initialize: 探针启动，监测时点 %s，样本 %s",
             ",".join(PROBE_TIMES), PROBE_CODES)
    for t in PROBE_TIMES:
        try:
            run_daily(context, _probe_job, time=t)
        except Exception as e:
            log.info("[探针] run_daily(%s) 失败: %s", t, repr(e))
