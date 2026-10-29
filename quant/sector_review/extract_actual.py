# -*- coding: utf-8 -*-
"""
从 git 历史提取每期板块轮动日报的 SEED 数据（9/16 ~ 10/28 实际判定记录）
输出：actual_reports.json  {日期: [板块记录...]}
"""
import subprocess, json, re, os, sys

GIT = "C:/Program Files/Git/cmd/git.exe"
REPO = "D:/投研工作台"
PATH = "03-A股盘面信息/板块轮动/板块轮动与主线确定每日报告.html"
ROOT = os.path.dirname(os.path.abspath(__file__))


def git(*args):
    r = subprocess.run([GIT, "-C", REPO] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout


def main():
    # 全部涉及该文件的提交
    log = git("log", "--format=%h|%ad", "--date=short", "--", PATH)
    commits = []
    for line in log.strip().split("\n"):
        if not line.strip():
            continue
        h, d = line.split("|")
        commits.append((h, d))
    print(f"相关提交 {len(commits)} 个")

    out = {}
    for h, d in commits:
        html = git("show", f"{h}:{PATH}")
        if not html or "SEED" not in html:
            continue
        recs = extract_seed(html)
        if not recs:
            continue
        # 以提交日期为准（可能与报告日期不同，取报告内标注的日期优先）
        rep_date = find_report_date(html) or d
        # 同一天多次提交，保留信息量最大（板块数最多）的一版
        if rep_date not in out or len(recs) > len(out[rep_date]["records"]):
            out[rep_date] = {"commit": h, "commit_date": d, "records": recs}

    # 补齐：按提交日期回填（报告内日期可能因节假日/顺延与提交日不一致）
    for h, d in commits:
        if d in out:
            continue
        html = git("show", f"{h}:{PATH}")
        recs = extract_seed(html) if html and "SEED" in html else []
        if recs:
            out[d] = {"commit": h, "commit_date": d, "records": recs,
                      "note": "按提交日期回填"}

    # 补齐 9/16~9/28 早期版本：数据在 sector-rotation-data.json
    JPATH = "03-A股盘面信息/板块轮动/sector-rotation-data.json"
    jlog = git("log", "--format=%h|%ad", "--date=short", "--", JPATH)
    for line in jlog.strip().split("\n"):
        if not line.strip():
            continue
        h, d = line.split("|")
        if d in out:
            continue
        raw = git("show", f"{h}:{JPATH}")
        try:
            recs = json.loads(raw)
        except Exception:
            continue
        if isinstance(recs, list) and recs:
            out[d] = {"commit": h, "commit_date": d, "records": recs,
                      "note": "取自 sector-rotation-data.json"}

    json.dump(out, open(os.path.join(ROOT, "actual_reports.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for d in sorted(out):
        print(f"  {d}: {len(out[d]['records'])} 个板块  (commit {out[d]['commit']})")
    print(f"共 {len(out)} 期")


def extract_seed(html):
    """抽取 SEED 数组。兼容 const SEED = [...] / var SEED / SEED = [...]"""
    # 找 SEED 赋值起点
    m = re.search(r"(?:const|var|let)?\s*SEED\s*=\s*(\[|\{)", html)
    if not m:
        return []
    start = m.start(1)
    opener = html[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    end = None
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if not end:
        return []
    blob = html[start:end]
    try:
        data = json.loads(blob)
    except Exception:
        # 容错：去掉尾随逗号
        cleaned = re.sub(r",(\s*[}\]])", r"\1", blob)
        try:
            data = json.loads(cleaned)
        except Exception:
            return []
    if isinstance(data, dict):
        for k in ("data", "sectors", "boards", "items"):
            if k in data and isinstance(data[k], list):
                return data[k]
        return []
    return data if isinstance(data, list) else []


def find_report_date(html):
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", html)
    if m:
        return m.group(0)
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", html)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return None


if __name__ == "__main__":
    main()
