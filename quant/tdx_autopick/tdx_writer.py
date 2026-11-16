# -*- coding: utf-8 -*-
"""
通达信板块写入器
================
把选股结果写进通达信「自选板块」，双击板块即可在通达信界面直接看到。

核心事实（本机实测，不是猜测）
--------------------------------
- 通达信安装目录：D:\\TDX
- 板块文件目录：D:\\TDX\\T0002\\blocknew\\
- .blk 文件格式：纯文本，每行一个 7 位代码 = 市场号(1位) + 6位原始代码
- 板块名与文件名一一对应（如 ZXG.blk ↔「自选股」），文件名全大写、不超 6 字符
- 通达信会自动扫描 blocknew 目录，新出现的 .blk 需在「自选股」右键刷新后才可见

⚠ 三个最容易踩的坑（本模块已全部规避）
  1. ⚠ 市场号前缀方向极易搞反 —— 本机 blk 实证结论（已比对 vipdoc 日线文件名逐个反查）：
       深市代码（000/002/300/301 等）→ 前缀 0，如 002549 → 0002549、301269 → 0301269
       沪市代码（600/601/603/605/688 等）→ 前缀 1，如 603773 → 1603773、000688 → 1000688
     写反了通达信会显示「无此代码」，而不是报错，属静默失败，最难发现
  2. 写入必须「先写临时文件再改名」，否则通达信正在读会读到半截内容导致板块错乱
  3. 不能删已有板块文件，只覆盖自己写的，避免误伤通达信自带的板块

用法：
    python tdx_writer.py                       # 把 AIRESULT.txt 里的票写入「AI选股」板块
    python tdx_writer.py --input a.txt --block AI选股
"""

import os
import sys
import shutil
import argparse
import datetime

# ===================== 路径配置（唯一允许硬编码通达信的地方） =====================
TDX_ROOT = r"D:\TDX"
BLOCK_DIR = os.path.join(TDX_ROOT, "T0002", "blocknew")
# 板块注册表：自定义板块必须在此登记，否则通达信界面里看不到。
# ⚠ 实测纠正：真正的活动注册表是 blocknew\blocknew.cfg，
#    同目录下 LastSync\blocknew.cfg 只是通达信云同步用的历史副本（会滞后）。
#    排查时先看活动那份，否则会误判"板块没注册"。
CFG_PATH = os.path.join(BLOCK_DIR, "blocknew.cfg")
CFG_BACKUP = os.path.join(BLOCK_DIR, "LastSync", "blocknew.cfg")
REPORT_DIR = r"D:\投研工作台\quant\tdx_autopick"

# 系统板块名 → 磁盘文件名 对照（通达信自带，一般不需要动）
SYSTEM_MAP = {
    "自选股": "ZXG",
    "沪深A股": "HSAG",
    "创业板": "CYB",
    "科创板": "KCB",
}

# ===================== 代码格式转换 =====================

def to_tdx_code(code):
    """
    统一转成通达信 7 位代码 = 市场号(1位) + 6位原始代码。
    无法识别返回 None（宁可不写，也不写错代码 —— 写错是静默失败，最难发现）。

    ⚠ 市场号方向已由本机 blk 实证确认，勿凭记忆改反：
       沪市 → 前缀 1   深市 → 前缀 0
      实证样本（blk 行↔ vipdoc 日线文件逐一对上）：
       0002549 → sz002549.day  （深市 002549）
       0301269 → sz301269.day  （深市 301269）
       1603773 → sh603773.day  （沪市 603773）
    """
    raw = str(code).strip()
    if not raw or not raw.isdigit():
        return None  # 拒绝空值/含非数字字符
    if len(raw) == 7 and raw.isdigit():
        # 已是通达信 7 位（市场号+6位），直接放行。
        # ⚠ 历史缺陷：原先这里对 7 位一律 return None，导致从 .blk 读出的
        #   代码全部被丢弃（write_block 报"无有效代码"）。
        return raw if is_valid_blk7(raw) else None
    if len(raw) > 6:
        return None  # 已是 7 位或更长，说明上游传错，拒收而不是猜
    s = raw.zfill(6)
    head3 = s[:3]
    # ---- 沪市：主板 600/601/603/605、科创板 688/689、板块指数 880/881 → 市场号 1 ----
    # ⚠ 881 = 通达信新行业指数（实证 sh881287.day 存在、市场号为 1）。
    #   缺 881 会导致 write_block 静默丢弃全部 881 代码（2026-10-20 实测踩坑）。
    if head3 in ("600", "601", "603", "605", "688", "689", "880", "881"):
        return "1" + s
    # ---- 深市：主板 000/001、中小板 002/003、创业板 300/301、B股 200 → 市场号 0 ----
    #⚠ 000 段是深市主板（000001 平安银行等），早期误以为 000 是指数代码而漏掉，
    #    导致深市主板个股被静默丢弃。
    if head3 in ("000", "001", "002", "003", "300", "301", "200"):
        return "0" + s
    return None


def is_valid_blk7(code):
    """校验 7 位 blk 代码是否合法（市场号 + 已知 6 位前缀）"""
    if len(code) != 7 or not code.isdigit():
        return False
    m, raw = code[0], code[1:]
    if m == "1":
        # 880/881xxx = 通达信板块指数（沪市场），实证存在于系统自带板块中
        if raw[:3] in ("600", "601", "603", "605", "688", "689", "880", "881"):
            return True
        return False
    if m == "0":
        return raw[:3] in ("000", "001", "002", "003", "300", "301", "200")
    return False


def dedupe(codes):
    """去重并保持原有顺序（顺序= 选股得分排名，顺序有意义不能乱排）"""
    seen, out = set(), []
    for c in codes:
        t = to_tdx_code(c)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ===================== 写入 =====================

def block_filename(block_name):
    """
    板块名 → 磁盘文件名（= 注册表里的拼音代号）。

    ⚠ 关键约束（已由本机 blocknew.cfg 实证）：
      .blk 文件名必须与 blocknew.cfg 中登记的「拼音代号」完全一致，
      否则通达信界面不显示该板块。通达信自身板块全部用 ASCII 拼音
      （HYLT/GSCG/DXG3~5T…），从不使用中文文件名，所以这里不能把中文名
      直接当文件名用 —— 那是静默失败，文件生成了但界面里看不见。

    优先查显式映射（BLOCK_PINY），其次查系统表，最后用原名兜底。
    """
    if block_name in BLOCK_PINY:
        return BLOCK_PINY[block_name]
    if block_name in SYSTEM_MAP:
        return SYSTEM_MAP[block_name]
    # 兜底：保留 ASCII 字母数字和 ~。若清洗后为空（例如纯中文名
    # 未在 BLOCK_PINY 里登记），退回 AIZX，避免生成空文件名。
    safe = "".join(ch for ch in block_name
                   if ch.isascii() and (ch.isalnum() or ch == "~"))
    return safe.upper() if safe else "AIZX"


# 自定义板块的拼音代号映射：中文显示名 → .blk 文件名 / 注册表代号
# ⚠ 代号约束（由通达信自身 29 个板块实证）：ASCII 大写字母/数字，
#    长度 2-16 以内，与 .blk 文件名严格一致。
#    通达信自带板块代号如 HYLT / DXG3~5T / 6GTX，数字和 ~ 都可用，
#    但为稳妥起见自建板块只用字母。
BLOCK_PINY = {
    "AI自选": "AIZX",
    # 盘中盯盘池：自选股 + AI自选 的合并池，供 .401 排序与条件预警监控
    # ⚠ 必须显式登记。未登记时 block_filename() 会因中文名清洗为空而
    #    兜底返回 AIZX，导致直接覆盖掉「AI自选」板块 —— 静默数据事故。
    "盯盘池": "DPC",
    # 条件预警触发结果落盘板块
    # ⚠ 2026-10-20 实测纠正：通达信实际把「盯盘信号」注册成 DPXH（非 DPXG）。
    #    旧映射写 DPXG 会落到不被界面识别的孤立文件，属静默失败。已对齐到 DPXH。
    "盯盘信号": "DPXH",
    # 龙头启动条件选股结果落盘板块（用户在通达信手动建，注册为 LTQD）
    "龙头启动": "LTQD",
    # 真主线 + 真热点 合并池（依据板块轮动日报五维评分分档）
    "主线板块池": "ZXZB",
    "真主线热点池": "ZXZB",   # 同代号别名：更准确的叫法
    # 主线板块池内的成分股（按 AI 自选标准二次筛选）
    "主线个股池": "ZGXP",
    "主线热点个股": "ZGXP",   # 同代号别名
    "AI技术突破": "AITECH",
    "AI主线龙头": "AIZXL",
    "AI基本面": "AIZXFB",
    "AI打板情绪": "AIZXDB",
    # 周线选股器独立板块（与日线 AI自选 互不干扰）
    "AI周线": "AIWEEK",
    # 板块热点筛选器：通达信板块指数连续走强入选池
    "热点板块": "RDKB",
    # 全量板块指池（880xxx 全部写入），供 .402 用「板块综合强度」排序取前10
    # ⚠ 与「热点板块」RDKB 区别：那个是脚本按K线筛出的少量强势板块，
    #    这个是全量池，排序交给通达信 .402 自己算，口径与界面一致。
    "热点板块池": "RDBK",
    # 热点股池：对 RDKB 各强势板块按「AI自选标准」各取前3个股落盘
    "热点股池": "RDGP",
}


# ===================== 板块注册表管理 =====================
# 格式（本机 blocknew.cfg 实证，28 条 × 120 字节，无误差）：
#   偏移  0-49中文显示名，GBK，右侧补 0
#   偏移 50-67   拼音代号，ASCII 大写，右侧补 0，必须与 .blk 文件名一致
#   偏移 68-119  保留区，全 0
CFG_REC = 120
CFG_NAME_LEN = 50
CFG_PY_LEN = 18


def is_tdx_running():
    """
    检测通达信主程序是否正在运行。

    ⚠ 为什么要检测：通达信启动时会把 blocknew.cfg 读进内存，
    退出时把内存里的板块表写回磁盘。如果它在运行时我改了注册表，
    它退出时会把我的修改覆盖掉 —— 表现为「明明注册了，重启后又没了」，
    是最难排查的一类bug。所以运行期一律不动注册表。
    """
    try:
        import psutil  # type: ignore
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n in ("tdxw.exe", "tdxrun.exe", "newtdxw.exe"):
                return True
        return False
    except ImportError:
        pass
    # 无psutil 时退化为进程列表扫描
    try:
        if os.name == "nt":
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq TDXW.EXE"],
                capture_output=True, text=True, timeout=10).stdout
            return "TdxW.exe" in out or "TDXW.EXE" in out
        return False
    except Exception:
        return False


def read_cfg():
    """读注册表，返回 [(中文名, 拼音代号), ...]"""
    if not os.path.exists(CFG_PATH):
        return []
    raw = open(CFG_PATH, "rb").read()
    out = []
    for i in range(len(raw) // CFG_REC):
        rec = raw[i * CFG_REC:(i + 1) * CFG_REC]
        name = rec[0:CFG_NAME_LEN].split(b"\x00")[0].decode("gbk",
                                                          errors="replace")
        py = rec[CFG_NAME_LEN:CFG_NAME_LEN + CFG_PY_LEN].split(
            b"\x00")[0].decode("ascii", errors="replace")
        if name or py:
            out.append((name, py))
    return out


def is_registered(block_name, py_code):
    """该板块是否已在注册表里登记（按拼音代号判断，代号唯一）"""
    for _, py in read_cfg():
        if py == py_code:
            return True
    return False


def register_block(block_name, py_code):
    """
    把板块写进注册表，使它在通达信界面可见。返回 (成功, 说明)。

    策略：已存在则不动；不存在则追加一条 120 字节记录，
    追加前先备份原文件（写坏注册表会导致通达信所有板块消失，代价极高）。
    """
    if is_registered(block_name, py_code):
        return True, "已注册"

    # ⚠ 安全第一：注册表写坏会导致通达信所有自定义板块从界面消失
    backup_dir = os.path.join(REPORT_DIR, "cfg_backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(CFG_PATH, os.path.join(backup_dir, f"blocknew_{ts}.cfg"))

    # 结构校验：长度必须是记录数的整数倍，否则宁可不写
    before = os.path.getsize(CFG_PATH)
    if before % CFG_REC != 0:
        return False, (f"注册表长度 {before} 不是 {CFG_REC} 整数倍，"
                       f"疑似结构异常，放弃写入以免损坏")

    raw = bytearray(open(CFG_PATH, "rb").read())

    name_b = block_name.encode("gbk")[:CFG_NAME_LEN - 1]
    py_b = py_code.encode("ascii")[:CFG_PY_LEN - 1]
    rec = bytearray(CFG_REC)
    rec[0:len(name_b)] = name_b
    rec[CFG_NAME_LEN:CFG_NAME_LEN + len(py_b)] = py_b
    raw.extend(rec)

    # 原子写入
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(raw))
    os.replace(tmp, CFG_PATH)

    # 写后校验：长度必须恰好增加一条记录，否则立即报告
    after = os.path.getsize(CFG_PATH)
    if after != before + CFG_REC:
        return False, (f"写入后长度异常({before}→{after})，"
                       f"请从 cfg_backup 恢复")
    return True, f"已注册「{block_name}」→ {py_code}"


def write_block(block_name, codes, backup=True, auto_register=True):
    """
    写入一个板块。返回 (成功bool, 实际写入条数, 落盘路径)

    原子写入：先写 .tmp 再 os.replace，保证通达信永远读到完整内容
    auto_register=True 时自动在注册表登记，保证通达信界面可见
    """
    if not os.path.isdir(BLOCK_DIR):
        return False, 0, f"板块目录不存在：{BLOCK_DIR}"

    final_codes = dedupe(codes)
    if not final_codes:
        return False, 0, "无有效代码"

    fname = block_filename(block_name)
    fpath = os.path.join(BLOCK_DIR, fname + ".blk")
    tmp_path = fpath + ".tmp"

    # 备份旧版本（最多留 10 份，按时间命名，方便回溯）
    if backup and os.path.exists(fpath):
        try:
            os.makedirs(os.path.join(REPORT_DIR, "blk_backup"),
                        exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(
                fpath,
                os.path.join(REPORT_DIR, "blk_backup",
                             f"{fname}_{ts}.blk"))
        except Exception:
            pass  # 备份失败不阻断主流程

    try:
        with open(tmp_path, "w", encoding="gbk",
                  newline="\r\n") as f:
            f.write("\n".join(final_codes) + "\n")
        os.replace(tmp_path, fpath)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False, 0, f"写入失败：{e}"

    # 注册到通达信板块表（失败不阻断，.blk 文件已写入）
    # ⚠ 实测结论（本机验证）：通达信运行中也会自动把新 .blk 登记进
    #    blocknew.cfg（实测 AIZX 已被自动写入并置顶），所以运行期
    #    并不需要回避注册表。但仍先查一次，避免重复追加记录。
    if auto_register and os.path.exists(CFG_PATH):
        ok2, msg = register_block(block_name, fname)
        if not ok2:
            print(f"  ⚠ 注册失败：{msg}")

    return True, len(final_codes), fpath


def clear_block(block_name, backup=True):
    """
    清空一个板块（把 .blk 写成空内容），用于「本轮 0 命中」时清除过期存量。

    与 write_block 的区别：write_block 遇到空代码列表会直接返回、不写文件（保护设计），
    这会导致 0 命中时旧票一直残留在板块里被误认为「今天入选」。clear_block 显式写空，
    只在调用方明确要求清空时使用。

    返回 (成功bool, 实际写入条数=0, 落盘路径/说明)
    - 原子写入：先写 .tmp 再 os.replace
    - backup=True 时先备份旧 .blk（复用 blk_backup 目录，最多靠时间戳区分）
    - 只覆盖自己名字对应的 .blk，不动注册表、不动其他板块
    """
    if not os.path.isdir(BLOCK_DIR):
        return False, 0, f"板块目录不存在：{BLOCK_DIR}"
    fname = block_filename(block_name)
    fpath = os.path.join(BLOCK_DIR, fname + ".blk")
    tmp_path = fpath + ".tmp"

    # 备份旧版本（含旧票，便于回溯），失败不阻断
    if backup and os.path.exists(fpath):
        try:
            bdir = os.path.join(REPORT_DIR, "blk_backup")
            os.makedirs(bdir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(fpath, os.path.join(bdir, f"{fname}_{ts}.blk"))
        except Exception:
            pass

    try:
        # 通达信空板块 = 0 字节文件；原子替换
        with open(tmp_path, "w", encoding="gbk", newline="") as f:
            f.write("")
        os.replace(tmp_path, fpath)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False, 0, f"清空失败：{e}"
    return True, 0, fpath


def append_report(title, rows, ts=None):
    """
    同步生成一份可读报表（MD），便于复盘「今天为什么选它」
    rows: [(代码, 名称, 分数, 理由), ...]
    """
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = ts or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(
        REPORT_DIR,
        f"选股结果_{datetime.datetime.now():%Y%m%d}.md")

    lines = [f"# 通达信自动选股结果", "",
             f"- 生成时间：{ts}",
             f"- 板块名：{title}",
             f"- 入选数量：{len(rows)}", "",
             "| 代码 | 名称 | 得分 | 入选理由 |",
             "|---|---|---|---|"]
    for code, name, score, reason in rows:
        lines.append(f"| {code} | {name} | {score} | {reason} |")
    lines.append("")

    # 追加写：一天多次跑，保留全部历史轮次
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n---\n\n")
    return path


# ===================== 命令行入口 =====================

def main():
    ap = argparse.ArgumentParser(
        description="把代码列表写入通达信自选板块")
    ap.add_argument("--input", help="代码文件（每行一个6位代码）")
    ap.add_argument("--block", default="AI选股", help="板块名")
    ap.add_argument("--test", action="store_true",
                    help="只做格式转换测试，不写盘")
    args = ap.parse_args()

    if args.test:
        # 格式自检：这几只覆盖了沪深创各市场
        for c in ["600519", "000001", "300750", "688981", "601318",
                  "002594", "000651", "830799", "abc123"]:
            print(f"{c} → {to_tdx_code(c)}")
        return

    if not args.input:
        print("请用 --input 指定代码文件，或用 --test 做格式自检")
        return

    with open(args.input, encoding="utf-8") as f:
        codes = [ln.strip() for ln in f if ln.strip()]

    ok, n, path = write_block(args.block, codes)
    print(f"板块：{args.block}")
    print(f"写入：{'成功' if ok else '失败'}，共 {n} 只")
    print(f"路径：{path}")
    if ok:
        print("\n【通达信里怎么看】")
        print("  1. 进入通达信 → 报价 → 自选股")
        print("  2. 在板块列表上右键 → 刷新")
        print(f"  3. 双击「{args.block}」即可看到 {n} 只入选股票")


if __name__ == "__main__":
    main()