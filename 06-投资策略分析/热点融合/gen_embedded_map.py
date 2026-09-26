# -*- coding: utf-8 -*-
"""gen_embedded_map.py —— 把行业/概念归属表「内嵌」进 PTrade 策略文件。

动机
    外挂 sector_map.json 有两个麻烦：
      ① 每次上传策略都要多传一个 416KB 的文件，还得赌只读目录路径对不对；
      ② 路径不对时整层「行业均值 + 共振」静默失效（v1.4 踩过这个坑）。
    内嵌后 = 单文件上传，零 IO、零路径依赖、零上传遗漏。

压缩原理
    JSON 把板块名重复存了 N 遍（"000505": "农林牧渔" × 5218 条）；
    反向组织成「板块名:代码 代码 ...」后，板块名只存一次：
        东财 sector_map.json   416.2 KB -> industry 95 KB / concept 227 KB
        申万 industry_map.json 123.6 KB -> 36 KB
    实测 416KB 的 JSON 内嵌后只让策略文件从 89KB 涨到 185KB。

幂等性
    内嵌区用成对标记包住，本脚本可反复执行：
        # === EMB_IND_BEGIN ===  ... # === EMB_IND_END ===
    每次只重写目标常量，另一个常量原样保留。所以「更新表」= 重跑一条命令。

用法
    python gen_embedded_map.py                          # 默认：东财 sector_map 的 industry
    python gen_embedded_map.py --kind concept           # 内嵌东财 concept
    python gen_embedded_map.py --src <path> --kind flat # 内嵌扁平 {code:行业名} 表（如申万）
    python gen_embedded_map.py --gen sw                 # 快捷：内嵌申万 31 一级行业
    python gen_embedded_map.py --dry-run                # 只报体积，不写盘

注意
    本脚本只改「内嵌区」与版本号，不动任何交易逻辑。改完请跑：
        python fusion_validator.py
"""

import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.join(HERE, "hotspot_fusion_v1_ptrade.py")

# 数据源候选
SRC_EM = r"D:\投研工作台\quant\hotspot\sector_map.json"
SRC_SW = r"D:\投研工作台\06-投资策略分析\策略回测\热点追踪lhb888\industry_map.json"

# 内嵌区标记（成对，勿手改）
IND_BEGIN = "# === EMB_IND_BEGIN ==="
IND_END = "# === EMB_IND_END ==="
CON_BEGIN = "# === EMB_CON_BEGIN ==="
CON_END = "# === EMB_CON_END ==="

VAR_IND = "EMB_SECTOR_RAW"
VAR_CON = "EMB_CONCEPT_RAW"

# 插入锚点：常量区里唯一的一行
ANCHOR = "MINUTE_BARS_TODAY = 61"

WRAP = 92          # 每个字符串片段的目标字符数（中文按 1 字符计）
INDENT = "    "


# ---------------------------------------------------------------- 数据清洗

def _clean_name(name):
    n = str(name).strip()
    hit = [ch for ch in (":", "|", "\r", "\n", "\t") if ch in n]
    for ch in hit:
        n = n.replace(ch, "")
    return n.strip(), bool(hit)


def _clean_codes(codes):
    out = []
    for c in codes:
        s = str(c).strip().split(".")[0]
        if re.match(r"^\d{6}$", s):
            out.append(s)
    return sorted(set(out))


def _build_raw(board2codes):
    """{板块名: [代码]} -> '名称:代码 代码|名称:代码...'

    返回 (raw, n_board, n_code, fixed_names)
    """
    segs = []
    fixed = []
    n_code = 0
    for name, codes in board2codes.items():
        nm, was_fixed = _clean_name(name)
        cs = _clean_codes(codes)
        if not nm or not cs:
            continue
        if was_fixed:
            fixed.append(str(name))
        segs.append(nm + ":" + " ".join(cs))
        n_code += len(cs)
    return "|".join(segs), len(segs), n_code, fixed


def _wrap(raw):
    """切成多行字符串字面量（相邻字面量自动拼接，语义等价）。"""
    if not raw:
        return INDENT + '""'
    lines = []
    buf = ""
    for i, seg in enumerate(raw.split("|")):
        piece = seg if i == 0 else "|" + seg
        if buf and len(buf) + len(piece) > WRAP:
            lines.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        lines.append(buf)
    return "\n".join(INDENT + '"' + l + '"' for l in lines)


# ---------------------------------------------------------------- 块生成

def _make_block(var, raw, begin, end, meta):
    """生成完整的内嵌块文本。meta 为注释行列表。"""
    head = [begin]
    for m in meta:
        head.append("# " + m)
    body = "%s = (\n%s\n)" % (var, _wrap(raw))
    return "\n".join(head) + "\n" + body + "\n" + end


def _replace_block(text, begin, end, new):
    i = text.find(begin)
    j = text.find(end)
    if i >= 0 and j > i:
        return text[:i] + new + text[j + len(end):], True
    return text, False


def _insert_blocks(text, block_ind, block_con):
    """首次：把两块插到锚点之前。"""
    if ANCHOR not in text:
        return text, False
    payload = block_ind + "\n" + block_con + "\n"
    return text.replace(ANCHOR, payload + ANCHOR, 1), True


# ---------------------------------------------------------------- 源解析

def load_source(src, kind):
    """返回 (raw, meta) """
    if not os.path.isfile(src):
        raise IOError("源文件不存在: %s" % src)
    sz = os.path.getsize(src) / 1024.0

    if kind in ("industry", "concept"):
        d = json.load(io.open(src, encoding="utf-8"))
        board2codes = d.get(kind, {}) or {}
        if not board2codes:
            raise ValueError("%s 里没有 %s 段" % (src, kind))
        raw, nb, nc, fixed = _build_raw(board2codes)
        meta = [
            "source: %s" % (d.get("source", "?")),
            "generated_at: %s" % (d.get("generated_at", "?")),
            "原表: %.1f KB JSON | 内嵌: %.1f KB | %s 板块 %d / 标的 %d"
            % (sz, len(raw.encode("utf-8")) / 1024.0, kind, nb, nc),
            "格式: \"板块名:代码 代码 ...|板块名:...\"  代码为 6 位",
            "生成: python gen_embedded_map.py --kind %s" % kind,
        ]
        return raw, meta, fixed

    # flat: {code: 板块名}
    d = json.load(io.open(src, encoding="utf-8"))
    if not d:
        raise ValueError("%s 为空" % src)
    k0 = list(d.keys())[0]
    v0 = d[k0]
    if not isinstance(v0, str):
        raise ValueError("%s 不是扁平 {code:板块名} 表（样本 %r->%r）" % (src, k0, v0))
    rev = {}
    for c, n in d.items():
        rev.setdefault(n, []).append(c)
    raw, nb, nc, fixed = _build_raw(rev)
    meta = [
        "source: %s (flat)" % os.path.basename(src),
        "原表: %.1f KB JSON | 内嵌: %.1f KB | 板块 %d / 标的 %d"
        % (sz, len(raw.encode("utf-8")) / 1024.0, nb, nc),
        "格式: \"板块名:代码 代码 ...|板块名:...\"  代码为 6 位",
        "生成: python gen_embedded_map.py --src %s --kind flat" % src,
    ]
    return raw, meta, fixed


# ---------------------------------------------------------------- 主流程

def main(argv):
    kind = "industry"
    src = SRC_EM
    dry = False
    gen = None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kind" and i + 1 < len(argv):
            kind = argv[i + 1]
            i += 2
        elif a == "--src" and i + 1 < len(argv):
            src = argv[i + 1]
            i += 2
        elif a == "--gen" and i + 1 < len(argv):
            gen = argv[i + 1]
            i += 2
        elif a == "--dry-run":
            dry = True
            i += 1
        else:
            print("未知参数: %s" % a)
            print(__doc__)
            return 2

    if gen == "sw":
        src, kind = SRC_SW, "flat"

    print("=" * 72)
    print("内嵌生成器 | 源=%s | kind=%s | dry=%s" % (src, kind, dry))
    print("=" * 72)

    raw, meta, fixed = load_source(src, kind)
    for m in meta:
        print("  " + m)
    if fixed:
        print("  [警告] %d 个板块名含 : 或 | 等分隔符，已清理: %s"
              % (len(fixed), "; ".join(fixed[:5])))

    text = io.open(STRAT, encoding="utf-8").read()
    cur_kb = len(text.encode("utf-8")) / 1024.0

    if kind == "concept":
        block_new = _make_block(VAR_CON, raw, CON_BEGIN, CON_END, meta)
        text2, ok = _replace_block(text, CON_BEGIN, CON_END, block_new)
    else:
        block_new = _make_block(VAR_IND, raw, IND_BEGIN, IND_END, meta)
        text2, ok = _replace_block(text, IND_BEGIN, IND_END, block_new)

    if not ok:
        # 首次：一次写入两块（目标块有内容，另一块留空占位）
        if kind == "concept":
            blk_con = block_new
            blk_ind = _make_block(VAR_IND, "", IND_BEGIN, IND_END,
                                  ["行业层（尚未生成）",
                                   "生成: python gen_embedded_map.py --kind industry"])
        else:
            blk_ind = block_new
            blk_con = _make_block(VAR_CON, "", CON_BEGIN, CON_END,
                                  ["概念层（当前策略未使用，留空以省体积）",
                                   "需要时: python gen_embedded_map.py --kind concept"])
        text2, ok2 = _insert_blocks(text, blk_ind, blk_con)
        if not ok2:
            print("[失败] 策略文件里找不到锚点: %s" % ANCHOR)
            return 1
        print("  [插入] 首次写入内嵌区（锚点前）")
    else:
        print("  [替换] 已更新内嵌区")

    new_kb = len(text2.encode("utf-8")) / 1024.0
    print()
    print("策略文件: %.1f KB -> %.1f KB  (+%.1f KB)" % (cur_kb, new_kb, new_kb - cur_kb))
    print("内嵌串  : %.1f KB" % (len(raw.encode("utf-8")) / 1024.0))

    if dry:
        print("[dry-run] 未写盘")
        return 0

    # newline="\n" 必须显式指定：Windows 文本模式默认把 \n 写成 \r\n，
    # 会让 2719 行的策略文件整体变 CRLF（体积虚增 2.7KB、与仓库其他文件不一致）。
    io.open(STRAT, "w", encoding="utf-8", newline="\n").write(text2)
    print("[已写入] %s" % STRAT)
    print()
    print("下一步：python fusion_validator.py   （应保持全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
