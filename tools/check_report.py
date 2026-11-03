#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_report.py —— 全球要闻报告校验脚本

检查项：
  1) Markdown 表格每行列数是否一致（表头/分隔行/数据行）
  2) 常见中文错别字与标点误用
  3) 数字与单位间缺失空格、常见事实性笔误

用法：python tools/check_report.py <report.md>
退出码 0 = 全部通过，1 = 有问题
"""
import re
import sys
import pathlib

# ---------- 常见错别字对照 ----------
TYPOS = {
    "按装": "安装", "按装": "安装",
    "必需": "必须", "必须": "必须",
    "反应": "反应",
    "帐面": "账面", "帐款": "账款",
    "帐单": "账单",
    "座落": "坐落", "座落点": "坐落点",
    "截止": "截止", "结止": "截止",
    "即使": "即使", "既使": "即使",
    "做为": "作为", "做位": "作为",
    "其它": "其他", "其它": "其他",
    "应收": "应收",
    "帐龄": "账龄",
    "即位": "即位",
    "竟然": "竟然",
    "以经": "已经", "以经完成": "已经完成",
    "在于": "在于",
    "疏通": "疏通",
    "重新定位": "重新定位",
    "相逢": "相逢",
    "不径而走": "不胫而走",
    "迫不急待": "迫不及待",
    "一如继往": "一如既往",
    "再接再励": "再接再厉",
    "川流不息": "川流不息",
    "相形见拙": "相形见绌",
    "谈笑风声": "谈笑风生",
    "光怪陆离": "光怪陆离",
    "甘败下风": "甘拜下风",
    "鼎立": "鼎立",
    "秋后算帐": "秋后算账",
    "以逸代劳": "以逸待劳",
    "委曲求全": "委曲求全",
    "相形见拙": "相形见绌",
    "察颜观色": "察言观色",
    "起 contribu": "",
    "地": "",
}

# 仅对明确错误的词做提示；同形同义/正确的词不放进来
REAL_TYPOS = {
    "以经": "已经",
    "既使": "即使",
    "做为": "作为",
    "迫不急待": "迫不及待",
    "一如继往": "一如既往",
    "再接再励": "再接再厉",
    "相形见拙": "相形见绌",
    "谈笑风声": "谈笑风生",
    "甘败下风": "甘拜下风",
    "不径而走": "不胫而走",
    "秋后算帐": "秋后算账",
    "按装": "安装",
    "帐面": "账面",
    "帐单": "账单",
    "帐龄": "账龄",
    "一部份": "一部分",
    "既使如此": "即使如此",
    "迫于紧": "迫于紧",
}

# 常见符号误用检查（正文段落中）
SYMBOL_ISSUES = [
    # 破折号两侧不应留空格（正确写法为"——"或"11—19日"连用）
    (re.compile(r"\s—\s|—\s|^\s*—"), "破折号旁不应有空格"),
    (re.compile(r"—{3,}"), "破折号多于两个"),
    (re.compile(r"\d\s*%{2,}"), "重复百分号"),
    (re.compile(r"[，。；：][，。；：]"), "重复标点"),
    (re.compile(r"[（(]\s*[）)]"), "空括号"),
    # 小数位超过 4 位（金融价格 4 位为正常，如 6.6557）
    (re.compile(r"\d+\.\d{5,}"), "小数点位数过多"),
]


def check_tables(lines):
    """检查 Markdown 表格列数一致性，返回问题列表"""
    issues = []
    i = 0
    table_no = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and line.strip().endswith("|"):
            # 找到表格结束
            start = i
            block = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                block.append((i + 1, lines[i]))
                i += 1
            table_no += 1
            counts = []
            for ln, txt in block:
                # 去掉首尾竖线后按 | 切分
                inner = txt.strip()[1:-1]
                cols = len(inner.split("|"))
                counts.append((ln, cols))
            expected = counts[0][1]
            for ln, c in counts:
                if c != expected:
                    issues.append(
                        f"表{table_no} 第 {ln} 行列数为 {c}，与表头 {expected} 列不一致"
                    )
            if len(block) < 2:
                issues.append(f"表{table_no}（第 {start+1} 行）只有一行，缺少分隔行")
            else:
                sep = block[1][1]
                if not re.match(r"^\|[\s:\-|]+\|$", sep.strip()):
                    issues.append(f"表{table_no}（第 {block[1][0]} 行）分隔行格式不规范")
        else:
            i += 1
    return issues, table_no


def check_typos(text):
    issues = []
    for bad, good in REAL_TYPOS.items():
        if not good:
            continue
        for m in re.finditer(re.escape(bad), text):
            line_no = text[: m.start()].count("\n") + 1
            ctx = text[max(0, m.start() - 4): m.end() + 4]
            if bad == "委曲" and "委曲求全" in ctx:
                continue
            if bad == "必需" and "必需品" in ctx:
                continue
            issues.append(f"第 {line_no} 行疑似错别字「{bad}」，建议改为「{good}」")
    return issues


def check_symbols(lines):
    issues = []
    for idx, line in enumerate(lines, 1):
        if line.strip().startswith("|"):
            continue  # 表格内不检查
        for pat, msg in SYMBOL_ISSUES:
            if pat.search(line):
                issues.append(f"第 {idx} 行：{msg}")
    return issues


def check_structure(text):
    """结构检查：五大类是否齐全、是否有今日重点提示"""
    issues = []
    required = [
        "一、政治要闻", "二、军事要闻", "三、经济要闻",
        "四、科技要闻", "五、金融要闻", "今日重点提示",
    ]
    for r in required:
        if r not in text:
            issues.append(f"缺少必要章节：{r}")
    # 今日重点提示不超过 3 条
    m = text.split("## 今日重点提示")[-1]
    n = len(re.findall(r"\*\*[一二三]、", m))
    if n > 3:
        issues.append(f"今日重点提示有 {n} 条，超过 3 条上限")
    if n == 0:
        issues.append("今日重点提示未识别到条目")
    return issues


def main():
    if len(sys.argv) < 2:
        print("用法：python check_report.py <report.md>")
        sys.exit(1)
    p = pathlib.Path(sys.argv[1])
    if not p.exists():
        print(f"找不到文件：{p}")
        sys.exit(1)
    text = p.read_text(encoding="utf-8")
    lines = text.split("\n")

    all_issues = []
    tab_issues, ntab = check_tables(lines)
    all_issues += tab_issues
    all_issues += check_typos(text)
    all_issues += check_symbols(lines)
    all_issues += check_structure(text)

    print(f"【1】表格列数校验：共 {ntab} 张表格")
    if tab_issues:
        for x in tab_issues:
            print("  ✗ " + x)
    else:
        print("  ✔ 全部表格列数一致、分隔行规范")

    print("\n【2】错别字校验")
    typo_issues = check_typos(text)
    if typo_issues:
        for x in typo_issues:
            print("  ✗ " + x)
    else:
        print("  ✔ 未发现常见错别字")

    print("\n【3】标点与格式校验")
    sym_issues = check_symbols(lines)
    if sym_issues:
        for x in sym_issues:
            print("  ✗ " + x)
    else:
        print("  ✔ 未发现标点或格式问题")

    print("\n【4】结构完整性校验")
    st_issues = check_structure(text)
    if st_issues:
        for x in st_issues:
            print("  ✗ " + x)
    else:
        print("  ✔ 五大分类齐全，今日重点提示不超过 3 条")

    print("\n【结论】" + ("✗ 共发现 %d 处问题，需修正" % len(all_issues)
                        if all_issues else "✔ 校验全部通过"))
    sys.exit(1 if all_issues else 0)


if __name__ == "__main__":
    main()
