# -*- coding: utf-8 -*-
"""
工具-回测日志自检.py —— 回测跑完先跑这个，确认"平台跑的到底是哪一版"。

背景（2026-09-21 踩坑）：
    把 V4.9 传上平台，跑完 5.5 小时的回测，结果收益反而变差。
    排查发现平台加载的是 V4.5 —— 白跑一轮。
    目录里 V4.5/V4.6/V4.7/V4.8/V4.9 五个文件并列，极易选错。
    因此每版策略在初始化日志里新增了"[指纹]"行，本工具负责对照。

用法：
    python 工具-回测日志自检.py [日志路径] [策略路径]

    不带参数时，默认取同目录：
        日志 = 001优化方案回测.txt
        策略 = 热点早盘001_V4.11.py

输出：
    ① 判定日志实际来自哪一版（[指纹]行为权威判据，特征组合打分为辅）
    ② 逐项对照表（日志实际值 vs 目标策略源码值）
    ③ 结论 + 建议

★2026-09-21 修订（V4.10 误判事件）★
    旧版正则写的是 `V4\\.\\d`，只能匹配一位数版本号 —— 遇到 `[初始化] V4.10 启动`
    直接匹配失败，于是"打印版本"这一最重的判据（权重 3）恒为 0，工具把 **V4.10 的真日志
    误判成 V4.9**（匹配分 12 恰好落在 V4.9 上）。教训：版本号一旦进入两位数，
    所有"解析版本串"的正则都必须用 `V4\\.\\d+`。
    同时新增：把 `[指纹] ★V4.x★` 行升级为**权威判据**（权重 10）——
    因为 V4.10/V4.11 的参数完全相同，仅靠参数特征无法区分，只有指纹行能分辨。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LOG = os.path.join(HERE, "001优化方案回测.txt")
DEFAULT_SRC = os.path.join(HERE, "热点早盘001_V4.11.py")

# 各版本特征签名（用于反推日志来源）
#   print_v   : 初始化行打印的版本串
#   trail     : 移动止盈回撤百分比
#   maxsec    : 每板块限仓只数
#   diffuse   : 扩散期单票仓位百分比
#   jac       : 产业链簇 Jaccard 阈值
#   turnover  : 换手窗口描述
#   netval    : 是否有 [净值] 日终行（V4.7+ 才有）
VERSION_SIGN = {
    "V4.5": dict(print_v="V4.5", trail="10", maxsec="2", diffuse="10", jac="0.3", turnover="20/30", netval=False),
    "V4.6": dict(print_v="V4.5", trail="7",  maxsec="3", diffuse="15", jac="0.3", turnover="20/30", netval=False),
    "V4.7": dict(print_v="V4.7", trail="10", maxsec="3", diffuse="15", jac="0.3", turnover="60/6",  netval=True),
    "V4.8": dict(print_v="V4.8", trail="10", maxsec="3", diffuse="12", jac="0.5", turnover="60/6",  netval=True),
    "V4.9": dict(print_v="V4.9", trail="15", maxsec="3", diffuse="12", jac="0.5", turnover="60/6",  netval=True),
    # V4.10 / V4.11 参数完全相同，只能靠 [指纹] 行区分（见 guess_version 的指纹加权）
    "V4.10": dict(print_v="V4.10", trail="15", maxsec="3", diffuse="12", jac="0.5", turnover="60/6", netval=True),
    "V4.11": dict(print_v="V4.11", trail="15", maxsec="3", diffuse="12", jac="0.5", turnover="60/6", netval=True),
}


def read_text(path):
    with open(path, "rb") as f:
        b = f.read()
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", errors="replace")


def src_param(src, key):
    """从策略源码读顶层参数值（字符串形式）"""
    m = re.search(r"^%s\s*=\s*([^\n#]+)" % key, src, re.M)
    return m.group(1).strip() if m else None


def src_param_float(src, key):
    v = src_param(src, key)
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", v.split("#")[0]) or "nan")
    except Exception:
        return None


def log_features(txt):
    """从回测日志抽取可比对的特征"""
    f = {}
    # ★修订★ 版本号必须是 \d+（V4.10 起为两位数，旧 \d 漏匹配 → 误判根因）
    m = re.search(r"\[初始化\]\s*(V4\.\d+)\s*启动", txt)
    f["print_v"] = m.group(1) if m else ""

    m = re.search(r"移动止盈\s*武装(\d+)%/回撤(\d+)%", txt)
    f["trail"] = m.group(2) if m else ""
    f["trail_arm"] = m.group(1) if m else ""

    m = re.search(r"每板块限\s*(\d+)\s*只", txt)
    f["maxsec"] = m.group(1) if m else ""

    m = re.search(r"单票启动\d+%/扩散(\d+)%", txt)
    f["diffuse"] = m.group(1) if m else ""

    m = re.search(r"Jaccard>([\d.]+)", txt)
    f["jac"] = m.group(1) if m else ""

    m = re.search(r"近(\d+)交易日\s*≤(\d+)\s*次双边", txt)
    f["turnover"] = "{}/{}".format(m.group(1), m.group(2)) if m else ""

    m = re.search(r"ATR\s*止损带\s*clamp\([^,]+,\s*([\d.]+)%,\s*([\d.]+)%\)", txt)
    f["atr_min"] = m.group(1) if m else ""
    f["atr_max"] = m.group(2) if m else ""

    f["netval"] = txt.count("[净值]")
    f["probe"] = txt.count("[口径-探测]")
    f["winner"] = txt.count("进入赢家宽管")
    f["regime"] = txt.count("市场避险")
    f["staged_mark"] = ("★V4.9 止损形态★" in txt) or ("★V4.8 两段式止损★" in txt)
    f["fingerprint"] = "[指纹]" in txt
    # ★修订★ [指纹] 行是权威判据：可直接读出"本文件自报的版本"，无需靠参数反推
    f["fp_versions"] = sorted(set(re.findall(r"\[指纹\]\s*★(V4\.\d+)★", txt)))

    # 实盘分批止盈触发值（V4.5 的 12% 会全部贴 12.0~13.5）
    partials = [float(x) for x in re.findall(r"分批止盈:浮盈([\d.]+)%减", txt)]
    f["partial_seen"] = partials
    return f


def guess_version(f):
    """按特征组合给各版本打分，返回 (版本, 分数明细)

    ★修订★ [指纹] 命中给 +10 权重，使其成为**压倒性权威判据**：
    V4.10/V4.11 参数完全一致，仅特征打分无法区分，只能靠指纹。
    """
    score = {}
    for ver, sig in VERSION_SIGN.items():
        s, detail = 0, []
        if ver in (f.get("fp_versions") or []):
            s += 10
            detail.append("★指纹行命中★")
        if f.get("print_v") == sig["print_v"]:
            s += 3
            detail.append("打印版本")
        if f.get("trail") == sig["trail"]:
            s += 3
            detail.append("移动止盈回撤")
        if f.get("maxsec") == sig["maxsec"]:
            s += 2
            detail.append("每板块限仓")
        if f.get("diffuse") == sig["diffuse"]:
            s += 2
            detail.append("扩散仓")
        if f.get("jac") == sig["jac"]:
            s += 2
            detail.append("簇Jaccard")
        if f.get("turnover") == sig["turnover"]:
            s += 2
            detail.append("换手窗口")
        if bool(f.get("netval")) == sig["netval"]:
            s += 1
            detail.append("[净值]行")
        score[ver] = (s, detail)
    best = max(score.items(), key=lambda kv: kv[1][0])
    return best[0], score


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    src_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SRC

    if not os.path.isfile(log_path):
        print("[错误] 日志不存在:", log_path)
        return 2
    txt = read_text(log_path)
    src = read_text(src_path) if os.path.isfile(src_path) else ""
    tgt = os.path.splitext(os.path.basename(src_path))[0] if src else "?"

    f = log_features(txt)
    ver, score = guess_version(f)

    print("=" * 78)
    print("【回测日志自检】")
    print("  日志:", log_path)
    print("  目标:", src_path)
    print("=" * 78)
    print("  日志跨度:", end=" ")
    days = sorted(set(re.findall(r"^(2026-\d\d-\d\d) \d\d:\d\d:\d\d", txt, re.M)))
    real = [d for d in days if not d.startswith("2026-09")]
    if real:
        print("{} → {} （{} 个交易日）".format(real[0], real[-1], len(real)))
    else:
        print("未识别")
    print("  判定来源版本:", ver, "（匹配分 {}）".format(score[ver][0]))
    print("  命中项:", ", ".join(score[ver][1]) or "无")
    print("  日志[指纹]行:", ", ".join(f.get("fp_versions") or []) or "（无）")
    print()

    if not src:
        print("[提示] 未找到目标策略源码，跳过逐项对照。")
        return 1

    rows = []
    refs = []      # ★修订★ 参考项：打印但不计入"不符项"（属已知口径差异，与版本无关）

    def cmp_row(name, actual, expect, ok):
        rows.append((name, actual, expect, ok))

    def ref_row(name, actual, expect, note):
        refs.append((name, actual, expect, note))

    # 0 ★修订★ 指纹行版本（权威判据）：日志自报版本 vs 源码里出现的版本
    src_fp = sorted(set(re.findall(r"★(V4\.\d+)★", src)))
    log_fp = f.get("fp_versions") or []
    cmp_row("★[指纹]行版本（权威）", ",".join(log_fp) or "无",
            "含 " + (src_fp[-1] if src_fp else "-"),
            bool(log_fp) and bool(src_fp) and
            (log_fp[-1] == src_fp[-1] or log_fp[-1] in src_fp))
    # 1 打印版本
    # ★修订★ 同样改为 \d+ —— V4.10 起版本号两位数，旧 \d 使本行恒判 ✗（误判的另一半原因）
    sv = re.search(r'\[初始化\]\s*(V4\.\d+)\s*启动', src)
    cmp_row("初始化版本串", f.get("print_v") or "-", sv.group(1) if sv else "-",
            bool(sv) and f.get("print_v") == sv.group(1))
    # 2 指纹行
    cmp_row("[指纹]行（V4.9+ 新增）", "有" if f.get("fingerprint") else "无",
            "有" if "[指纹]" in src else "-", f.get("fingerprint") or not ("[指纹]" in src))
    # 3 移动止盈回撤
    tv = src_param_float(src, "TRAIL_PCT")
    cmp_row("移动止盈回撤", (f.get("trail") or "-") + "%",
            "{:.0%}".format(tv) if tv is not None else "-",
            tv is not None and f.get("trail") == str(int(round(tv * 100))))
    # 4 分批止盈
    pv = src_param_float(src, "PARTIAL_TAKE_PCT")
    seen = f.get("partial_seen") or []
    cmp_row("分批止盈阈值（实测）",
            ("{:.1f}%".format(sum(seen) / len(seen)) + " ×{}笔".format(len(seen))) if seen else "未触发",
            "{:.0%}".format(pv) if pv is not None else "-",
            pv is not None and bool(seen) and abs(sum(seen) / len(seen) - pv * 100) <= 2.0)
    # 5 ATR 止损带
    amin = src_param_float(src, "ATR_STOP_MIN_PCT")
    amax = src_param_float(src, "ATR_STOP_MAX_PCT")
    logged_atr = (f.get("atr_min") or "-") + "%~" + (f.get("atr_max") or "-") + "%"
    exp_atr = ("{:.0%}~{:.0%}".format(amin, amax) if (amin is not None and amax is not None) else "-")
    cmp_row("ATR 止损带 clamp", logged_atr, exp_atr,
            bool(f.get("atr_max")) and amax is not None and f.get("atr_max") == str(int(round(amax * 100))))
    # 6 每板块限仓
    ms = src_param_float(src, "MAX_PER_SECTOR")
    cmp_row("每板块限仓", (f.get("maxsec") or "-") + "只",
            "{:.0f}只".format(ms) if ms is not None else "-",
            ms is not None and f.get("maxsec") == str(int(ms)))
    # 7 扩散仓
    dv = src_param_float(src, "DIFFUSE_POSITION_RATIO")
    cmp_row("扩散期单票仓位", (f.get("diffuse") or "-") + "%",
            "{:.0%}".format(dv) if dv is not None else "-",
            dv is not None and f.get("diffuse") == str(int(round(dv * 100))))
    # 8 簇 Jaccard
    jv = src_param_float(src, "CLUSTER_JACCARD")
    cmp_row("产业链簇 Jaccard", f.get("jac") or "-",
            "{}".format(jv) if jv is not None else "-",
            jv is not None and f.get("jac") == ("%g" % jv))
    # 9 换手窗口
    tw = src_param_float(src, "TURNOVER_WINDOW_DAYS")
    tm = src_param_float(src, "MAX_ANNUAL_TURNS")
    exp_turn = "{:.0f}/{}".format(tw, int(tm)) if (tw is not None and tm is not None) else "-"
    cmp_row("换手 窗口/上限", f.get("turnover") or "-", exp_turn,
            bool(f.get("turnover")) and f.get("turnover") == exp_turn)
    # 10-12 功能开关类
    expect_netval = "V4.7" in src or bool(re.search(r"\[净值\]", src))
    cmp_row("[净值] 日终行", str(f.get("netval")), "应有" if expect_netval else "-",
            (f.get("netval") or 0) > 0 if expect_netval else True)
    expect_probe = "[口径-探测]" in src
    # ★修订★ 该项转为"参考项"：该行在**回测**环境下恒不输出（属已知口径差异，
    #   与"跑的是哪一版"无关），计入不符项会造成假警报，正是 V4.10 误判的干扰源之一。
    ref_row("[口径-探测] 覆盖率", str(f.get("probe")), "源码含此打印",
            "回测环境不出此行，属已知差异，不参与版本判定")
    expect_win = "WINNER_EXEMPT_PCT" in src
    cmp_row("赢家宽管（出场/进入）", str(f.get("winner")), "应有" if expect_win else "-",
            (f.get("winner") or 0) > 0 if expect_win else True)
    expect_regime = "REGIME_RISK_OFF_SCALE" in src
    cmp_row("市场避险档", str(f.get("regime")), "应有" if expect_regime else "-",
            (f.get("regime") or 0) > 0 if expect_regime else True)

    w = max(len(r[0]) for r in rows + refs + [("项目", "", "", True)]) + 2
    print("{:<{w}}{:<16}{:<16}{}".format("项目", "日志实际", "目标应为", "结果", w=w))
    print("-" * 78)
    bad = 0
    for name, act, exp, ok in rows:
        if not ok:
            bad += 1
        print("{:<{w}}{:<16}{:<16}{}".format(name, str(act), str(exp), "✓" if ok else "✗", w=w))
    print("-" * 78)
    print("不符项: {} / {}".format(bad, len(rows)))
    if refs:
        print()
        print("【参考项】（不计入不符项）")
        for name, act, exp, note in refs:
            print("  - {:<20} 日志={:<6} 目标={:<14} {}".format(name, str(act), str(exp), note))
    print()
    if bad == 0:
        print("【结论】日志确由 `{}` 产出，可以放心使用这份回测结果。".format(tgt))
        return 0
    print("【结论】⚠ 日志与 `{}` 不匹配（判定实际来自 {}）。".format(tgt, ver))
    print("        这份回测不能用于验证 {} 的效果，请重新上传正确的策略文件后再跑。".format(tgt))
    return 1


if __name__ == "__main__":
    sys.exit(main())
