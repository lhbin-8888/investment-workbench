

def _days_between(d1, d2):
    try:
        import datetime as _dt
        a = _dt.date(*[int(x) for x in str(d1)[:10].split("-")])
        b = _dt.date(*[int(x) for x in str(d2)[:10].split("-")])
        return abs((b - a).days)
    except Exception:
        return 0


# ============================================================
# 十、建仓（按可用现金 + 【v4-5】预算回收）
# ============================================================
def build_orders(context, top):
    """挑出本轮建仓候选：受 MAX_POSITIONS 与自维护 live_held 约束。"""
    held = set(getattr(context, "live_held", set()))
    remaining = MAX_POSITIONS - len(held)
    if remaining <= 0:
        log.info("[买入] 持仓已满 {} 只，本轮不新增".format(len(held)))
        return []
    picks = []
    for a in top:
        if a["code"] in held:
            continue
        if REQUIRE_ABOVE_MA20 and not a["above20"]:
            continue
        picks.append(a)
        if len(picks) >= remaining:
            break
    return picks


def _cash(context):
    for attr in ("cash", "available_cash", "total_cash"):
        try:
            return float(getattr(context.portfolio, attr))
        except Exception:
            continue
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        return 0.0


def _total_asset(context):
    try:
        return float(context.portfolio.portfolio_value)
    except Exception:
        pass
    if _has("get_total_assets"):
        try:
            return float(get_total_assets())
        except Exception:
            pass
    return 0.0


def _alloc_by_strength(picks, budget, total):
    """按热点强度分档分配预算（纯函数）。返回与 picks 等长的金额列表。"""
    if not picks:
        return []
    if not STRENGTH_WEIGHT:
        per = min(total * POSITION_VALUE_RATIO, budget / len(picks))
        return [per] * len(picks)
    scores = [max(float(a.get("score", 0.1)), 0.1) for a in picks]
    exp = STRENGTH_EXP
    weights = [s ** exp for s in scores]
    cap = total * MAX_SINGLE_RATIO
    n = len(picks)
    allocs = [0.0] * n
    remaining = budget
    active = set(range(n))
    for _ in range(20):
        if not active or remaining <= 1.0:
            break
        fw = sum(weights[i] for i in active) or 1.0
        moved = 0.0
        capped = []
        for i in active:
            add = remaining * (weights[i] / fw)
            if allocs[i] + add >= cap - 1e-6:
                moved += cap - allocs[i]
                allocs[i] = cap
                capped.append(i)
            else:
                allocs[i] += add
                moved += add
        for i in capped:
            active.discard(i)
        remaining -= moved
    return allocs


def execute_buy(context, picks, budget_factor=1.0, tag=""):
    """建仓。v4 相对 v3 的两处改动：

      【v4-5】预算回收：某票因「不足最小手数」或触及单票上限而用不满额度时，
              把剩余额度顺延给后续候选；全部候选走完后若仍有结余，再按 RECYCLE_ROUNDS
              轮对已成交标的追加（order_target_value 加仓），直到用满或全员触顶。
      【v4-5】单票上限 MAX_SINGLE_RATIO 在分配阶段与下单阶段双重校验，防过度集中。
    """
    total = _total_asset(context)
    cash = _cash(context)
    if total <= 0:
        log.error("[买入] 无法获取总资产，跳过建仓")
        return
    base_budget = min(cash * (1 - CASH_BUFFER), total * POSITION_VALUE_RATIO * MAX_POSITIONS)
    budget = base_budget * max(0.0, float(budget_factor))
    if budget <= 0 or cash <= 0:
        log.error("[买入] 本轮预算为 0（情绪闸门/现金不足），跳过建仓")
        return
    allocs = _alloc_by_strength(picks, budget, total)
    log.info("[买入]{} 总资产{:.0f} 可用现金{:.0f} 基准预算{:.0f} 实际预算{:.0f}（系数{:.2f}；"
             "强度分档 {} 只；回收={}）".format(
                 (" " + tag) if tag else "", total, cash, base_budget, budget,
                 budget_factor, len(picks), "开" if BUDGET_RECYCLE else "关"))

    entry = getattr(context, "entry_date", None)
    if entry is None:
        entry = {}
        context.entry_date = entry
    halved = getattr(context, "halved", None)
    if halved is None:
        halved = {}
        context.halved = halved
    breakeven = getattr(context, "breakeven", None)
    if breakeven is None:
        breakeven = {}
        context.breakeven = breakeven
    live_held = getattr(context, "live_held", set())
    context.live_held = live_held

    cap_value = total * MAX_SINGLE_RATIO
    leftover = 0.0
    booked = []          # [{a, code, price, lot, used}]

    for a, per in zip(picks, allocs):
        code = a["code"]
        price = a.get("price")
        if not price or price <= 0:
            log.error("[买入] {} 无可用现价，跳过".format(code))
            if BUDGET_RECYCLE:
                leftover += per
            continue
        lot = 200 if _is_kcb(code) else 100
        avail = per + (leftover if BUDGET_RECYCLE else 0.0)
        # 单票上限
        budgeted_room = cap_value
        avail = min(avail, budgeted_room)
        shares = int(avail // (price * lot)) * lot
        if shares < lot:
            log.info("[买入] {} 可用额度{:.0f}元 @现价{:.2f} 不足最小{}股，跳过（额度顺延）".format(
                code, avail, price, lot))
            if BUDGET_RECYCLE:
                leftover += per
                log.info("[回收] {} 的额度 {:.0f} 元顺延至后续候选（累计结余 {:.0f}）".format(
                    code, per, leftover))
            continue
        used = shares * price
        if per < 1000 and not BUDGET_RECYCLE:
            log.error("[买入] {} 分配金额过小({:.0f})，跳过".format(code, per))
            continue
        halved.pop(code, None)
        breakeven.pop(code, None)
        if TRADE_ENABLED:
            log.info("[买入] {} {} 现价+{}% 强度{} 分配{:.0f}元 目标{}股 ≈{:.0f}元{}".format(
                code, a["name"], a["pct"], a["score"], avail, shares, used,
                "（板块[{}x{}]）".format(a.get("industry") or "-", a.get("sector_cnt", 0))
                if a.get("sector_cnt") else ""))
            try:
                if _has("order_target_value"):
                    order_target_value(code, used)
                else:
                    order_value(code, used)
                entry[code] = _context_date(context)
                live_held.add(code)
                booked.append({"a": a, "code": code, "price": price, "lot": lot, "used": used})
            except Exception as e:
                log.error("[买入异常] {} : {}".format(code, repr(e)))
        else:
            log.info("[信号] 拟买入 {} {} 现价+{}% 强度{} 目标{}股（未下单）".format(
                code, a["name"], a["pct"], a["score"], shares))
            entry[code] = _context_date(context)
            live_held.add(code)
            booked.append({"a": a, "code": code, "price": price, "lot": lot, "used": used})
        if BUDGET_RECYCLE:
            leftover = max(0.0, avail - used)

    # ---- 【v4-5】结余回填：对已成交标的按强度顺序追加 ----
    if BUDGET_RECYCLE and leftover > 0 and booked:
        for r in range(RECYCLE_ROUNDS):
            if leftover < 1000:
                break
            progressed = False
            for b in booked:
                code, price, lot = b["code"], b["price"], b["lot"]
                room = cap_value - b["used"]
                if room <= 0:
                    continue
                add_avail = min(leftover, room)
                add_shares = int(add_avail // (price * lot)) * lot
                if add_shares < lot:
                    continue
                add_val = add_shares * price
                if not TRADE_ENABLED:
                    log.info("[信号] 拟追加 {} {} 股（用结余额度 {:.0f} 元）".format(
                        code, add_shares, add_val))
                else:
                    try:
                        if _has("order_target_value"):
                            order_target_value(code, b["used"] + add_val)
                        else:
                            order_value(code, add_val)
                        log.info("[回收] 第{}轮追加 {} {}股 用额{:.0f}元（结余剩 {:.0f}）".format(
                            r + 1, code, add_shares, add_val, leftover - add_val))
                    except Exception as e:
                        log.error("[回收异常] {} : {}".format(code, repr(e)))
                        continue
                b["used"] += add_val
                leftover -= add_val
                progressed = True
            if not progressed:
                break
        if leftover > 1000:
            log.info("[回收] 结余额度 {:.0f} 元未能用出（不足最小手数或全员触及单票上限"
                     "{}%）".format(leftover, int(MAX_SINGLE_RATIO * 100)))
        else:
            log.info("[回收] 预算基本用满（结余 {:.0f} 元）".format(leftover))


# ============================================================
# 十一、入口
# ============================================================
_LAST_DATE = [""]
_DIAG_DONE = [False]
_DAILY_FALLBACK_WARNED = [False]


def initialize(context):
    try:
        set_benchmark("000300.SS")
    except Exception as e:
        log.info("[配置] set_benchmark 失败: {}".format(repr(e)))
    try:
        set_slippage(slippage=SLIPPAGE)
    except Exception:
        try:
            set_slippage(SLIPPAGE)
        except Exception as e2:
            log.info("[配置] 滑点未设置: {}".format(repr(e2)))
    try:
        set_commission(commission_ratio=0.0003, min_commission=5.0, type="STOCK")
    except Exception:
        try:
            set_commission(PerTrade=0.0003, Min=5)
        except Exception as e2:
            log.info("[配置] 佣金未设置: {}".format(repr(e2)))

    log.info("=" * 60)
    log.info("[初始化] 热点追踪 {} 启动；预设={}；TRADE_ENABLED={}".format(
        VERSION, PRESET_APPLIED, TRADE_ENABLED))
    log.info("[初始化] 六项改造开关：[v4-1]盘中巡检={}（{}个时点） [v4-2]情绪闸门={}({}) "
             "[v4-3]板块共振={}(>= {}只) [v4-4]量比{} 额{:.0f}亿 高开上限{} [v4-5]预算回收={} "
             "持仓上限{}只 [v4-6]弱离场={} EXIT_MA={} TRAIL={:.0%} 时间止损={}日".format(
                 "开" if INTRADAY_RISK_ENABLED else "关", len(INTRADAY_RISK_TIMES),
                 "开" if SENTIMENT_GATE_ENABLED else "关", SENTIMENT_MODE,
                 SECTOR_MODE, MIN_SECTOR_ALIGN,
                 MIN_VOL_RATIO, MIN_AMOUNT / 1e8, "不限" if MAX_OPEN_PCT <= 0 else MAX_OPEN_PCT,
                 "开" if BUDGET_RECYCLE else "关", MAX_POSITIONS,
                 "开" if WEAK_EXIT_ENABLED else "关", EXIT_MA, TRAIL_PCT, MAX_HOLD_DAYS))
    _diag_api()
    log.info("[初始化] 行情/成交量/口径自检将延迟到首个交易日执行（PTrade 初始化阶段禁止取数）")
    log.info("=" * 60)

    context.halved = {}
    context.breakeven = {}
    context.peak = {}
    context.live_held = set()
    context._risk_seen = set()
    context._tail_done = set()


def _retreat_scan(context, data, reason_tag):
    """卖出后的额度立即参与建仓：重扫一次（【v4-1】配套，保证当日释放额度当日可用）。"""
    top = scan_market(context, data)
    if not top:
        return
    picks = build_orders(context, top)
    if not picks:
        log.info("[补仓] 无符合建仓条件的候选")
        return
    execute_buy(context, picks, tag=reason_tag)


def _daily_routine(context, data=None):
    # 延迟自检：PTrade 初始化阶段禁止取数，改为首个交易日执行一次
    if not _DIAG_DONE[0]:
        _DIAG_DONE[0] = True
        try:
            _diag_vol_scale()
            _diag_cutoff(context)
            _diag_data(data)
        except Exception as e:
            log.error("[自检] 延迟自检异常: {}".format(repr(e)))
    today = _context_date(context)
    if today and _LAST_DATE[0] == today:
        return
    _LAST_DATE[0] = today
    log.info("=" * 60)
    log.info("[{}] 每日热点识别开始（预设 {}）".format(today, PRESET_APPLIED))
    try:
        top = scan_market(context, data)
    except Exception as e:
        log.error("[扫描] 异常: {}".format(repr(e)))
        top = []

    # ---- 【v4-2】情绪闸门判定 ----
    senti = SCAN_META.get("sentiment") or {}
    verdict, factor, why = _sentiment_verdict(senti)
    SCAN_META["verdict"] = verdict
    SCAN_META["verdict_msg"] = why
    if verdict == "OK":
        log.info("[闸门] 放行（{}）".format(why))
    else:
        _warn("[闸门] {} —— {}".format(verdict, why))

    try:
        monitor_risk(context, data)
    except Exception as e:
        log.error("[风控] 异常: {}".format(repr(e)))

    # 风控卖出后当日释放的额度：立即补建仓（REINVEST_ON_SELL）
    if REINVEST_ON_SELL and _LAST_SELL_FLAG[0]:
        _LAST_SELL_FLAG[0] = False
        log.info("[补仓] 本轮风控有平仓动作，重新扫描并补足仓位")
        try:
            _retreat_scan(context, data, "补仓")
        except Exception as e:
            log.error("[补仓] 异常: {}".format(repr(e)))
        return

    if not top:
        if TRADE_ENABLED:
            log.error("[警告] 本轮热点榜为空，未建仓。若连续多日为空，"
                      "请检查取数接口、成交额单位与入场门槛（量比/成交额/高开上限）")
        else:
            log.info("[信号模式] 本轮热点榜为空，不下单")
        return

    if verdict == "STOP":
        _warn("[闸门] 情绪冰点，今日只做风控不建仓（这是有意为之，非故障）")
        return
    picks = build_orders(context, top)
    if not picks:
        log.info("[信号] 无符合建仓条件的候选")
        return
    if verdict == "HALF":
        keep = max(1, (len(picks) + 1) // 2)
        log.info("[闸门] 情绪冰点减半仓：候选 {} -> {} 只，预算系数 {:.2f}".format(
            len(picks), keep, factor))
        picks = picks[:keep]
    execute_buy(context, picks, budget_factor=factor)


def _risk_watch(context, data, hhmm):
    """【v4-1】盘中风控巡检：(日期, 时点) 幂等，只跑风控不下单。"""
    today = _context_date(context)
    key = "{} {}".format(today, hhmm)
    seen = getattr(context, "_risk_seen", None)
    if seen is None:
        seen = set()
        context._risk_seen = seen
    if key in seen:
        return
    seen.add(key)
    try:
        monitor_risk(context, data, tag="巡检{}".format(hhmm))
    except Exception as e:
        log.error("[巡检] {} 异常: {}".format(hhmm, repr(e)))


def _tail_routine(context, data):
    """【v4-5 延伸】尾盘补仓：仅当仍有空位且仍有可投现金时执行，每日一次。"""
    today = _context_date(context)
    done = getattr(context, "_tail_done", None)
    if done is None:
        done = set()
        context._tail_done = done
    if today in done:
        return
    done.add(today)
    held = set(getattr(context, "live_held", set()))
    if len(held) >= MAX_POSITIONS:
        return
    cash = _cash(context)
    total = _total_asset(context)
    if cash <= total * CASH_BUFFER:
        return
    log.info("[尾盘] 空位 {} 个、可用现金 {:.0f}，执行 14:45 补仓扫描".format(
        MAX_POSITIONS - len(held), cash))
    try:
        top = scan_market(context, data)
        if not top:
            log.info("[尾盘] 无候选，放弃补仓")
            return
        picks = build_orders(context, top)
        if picks:
            execute_buy(context, picks, tag="尾盘")
    except Exception as e:
        log.error("[尾盘] 异常: {}".format(repr(e)))


def handle_data(context, data):
    hhmm = _now_hhmm(context)
    if not hhmm:
        # 日频回测：拿不到 HH:MM，按日执行（幂等），盘中巡检与尾盘补仓自动失效
        if not _DAILY_FALLBACK_WARNED[0]:
            _DAILY_FALLBACK_WARNED[0] = True
            _warn("[时间] 无法读取 HH:MM（日频回测或平台限制）→ 主流程按日执行；"
                  "【v4-1】盘中巡检 / 尾盘补仓 在日频下不生效，请在分钟级回测验证")
        _daily_routine(context, data)
        return
    if hhmm >= SIGNAL_TIME:
        _daily_routine(context, data)
    if INTRADAY_RISK_ENABLED and hhmm in INTRADAY_RISK_TIMES:
        _risk_watch(context, data, hhmm)
    if TAIL_SCAN_ENABLED and hhmm >= TAIL_TIME:
        _tail_routine(context, data)


def before_trading_start(context, data):
    _LAST_SELL_FLAG[0] = False


def after_trading_end(context, data):
    try:
        report_stats()
    except Exception as e:
        log.error("[统计] 异常: {}".format(repr(e)))
