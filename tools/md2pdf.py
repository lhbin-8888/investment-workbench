#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
md2pdf.py —— 投研报告 Markdown 转 PDF（白底简洁版）

设计约束（2026-09-08 用户确认）：
  1. 白底，不用深色底色；仅表头用极浅灰 #f4f5f7
  2. 简洁：细线分隔、无渐变、无阴影、无装饰色块
  3. 排版不乱：表格按列数自动适配字号/列宽，禁止单元格内数字串行

用法：
  python md2pdf.py input.md [-o output.pdf] [--title "报告标题"] [--subtitle "副标题"]

依赖：markdown（含 tables 扩展）；PDF 渲染使用本机 Microsoft Edge 无头模式。
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

import markdown

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

CSS = """
@page { size: A4; margin: 16mm 13mm 15mm 13mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
    margin: 0;
    background: #ffffff;
    color: #1a1a1a;
    font-family: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 10pt;
    line-height: 1.75;
}

/* ---------- 报头 ---------- */
.doc-head { border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-bottom: 4px; }
.doc-title { font-size: 19pt; font-weight: 700; letter-spacing: .5px; margin: 0; }
.doc-sub { font-size: 9.5pt; color: #666; margin-top: 5px; }
.doc-meta { font-size: 8.5pt; color: #888; margin-top: 3px; }

/* ---------- 标题 ---------- */
h1 { font-size: 16pt; font-weight: 700; margin: 22px 0 10px; padding-bottom: 6px;
     border-bottom: 1px solid #d8d8d8; break-after: avoid; }
h2 { font-size: 12.5pt; font-weight: 700; margin: 18px 0 8px; padding-left: 8px;
     border-left: 3px solid #333; break-after: avoid; }
h3 { font-size: 11pt; font-weight: 700; margin: 14px 0 6px; break-after: avoid; }
h4 { font-size: 10pt; font-weight: 700; margin: 10px 0 4px; break-after: avoid; }

/* ---------- 正文 ---------- */
p { margin: 6px 0; text-align: justify; }
strong { font-weight: 700; }
em { color: #666; font-style: normal; }
ul, ol { margin: 6px 0 6px 0; padding-left: 20px; }
li { margin: 3px 0; }
blockquote {
    margin: 8px 0; padding: 6px 12px; color: #555;
    background: #fafafa; border-left: 2px solid #bbb;
}
hr { border: 0; border-top: 1px solid #e2e2e2; margin: 14px 0; }
code { background: #f4f4f4; padding: 1px 4px; font-size: 9pt; }

/* ---------- 表格 ---------- */
table {
    width: 100%; border-collapse: collapse; margin: 8px 0 12px;
    table-layout: fixed; word-break: keep-all;
    font-size: 8.5pt; line-height: 1.45;
}
thead { display: table-header-group; }
tfoot { display: table-footer-group; }
tr { break-inside: avoid; }
th {
    background: #f4f5f7; font-weight: 700; color: #222; text-align: center;
    padding: 5px 4px; border-top: 1px solid #d0d0d0; border-bottom: 1px solid #d0d0d0;
}
td {
    padding: 4px 4px; border-bottom: 1px solid #ececec; text-align: center;
}
tbody tr:nth-child(even) { background: #fcfcfc; }
/* 首列（板块/名称）左对齐，其余居中 */
td:first-child { text-align: left; }
th:first-child { text-align: left; }

/* 涨红跌绿（A股口径） */
.up   { color: #c0392b; font-weight: 600; }
.down { color: #1e8449; font-weight: 600; }
.flat { color: #666; }

/* 表格下方注释 */
.tnote { font-size: 8pt; color: #777; margin: -4px 0 14px; }

/* ---------- 分页控制 ---------- */
h1, h2, h3 { break-inside: avoid; break-after: avoid; }
table { break-inside: auto; }
.no-break { break-inside: avoid; }
.new-page { break-before: page; }

/* ---------- 页脚 ---------- */
.doc-foot {
    margin-top: 18px; padding-top: 8px; border-top: 1px solid #d8d8d8;
    font-size: 8pt; color: #888; text-align: center;
}
"""

# 匹配单元格内的纯数值：涨跌幅 / 净流入 / 带正负号的金额与百分比
_NUM_RE = re.compile(r"^\s*([+-]?\d[\d,]*\.?\d*)\s*(%|亿|元|倍)?\s*$")


def colorize_numbers(html: str) -> str:
    """给表格单元格中的正负数值上色：正=红（涨），负=绿（跌）。"""
    def repl(m):
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        plain = re.sub(r"<[^>]+>", "", content).strip()
        if not plain or plain in {"亏损", "未涨停", "—", "-"}:
            return m.group(0)
        mm = _NUM_RE.match(plain)
        if not mm:
            return m.group(0)
        num = mm.group(1)
        if num.startswith("-"):
            cls = "down"
        elif num.startswith("+"):
            cls = "up"
        else:
            return m.group(0)
        return f'{open_tag}<span class="{cls}">{plain}</span>{close_tag}'

    return re.sub(r"(<td[^>]*>)(.*?)(</td>)", repl, html, flags=re.S)


def build_html(md_text: str, title: str = "", subtitle: str = "", meta: str = "") -> str:
    body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"]
    )
    body = colorize_numbers(body)

    head = ""
    if title or subtitle or meta:
        parts = []
        if title:
            parts.append(f'<div class="doc-title">{title}</div>')
        if subtitle:
            parts.append(f'<div class="doc-sub">{subtitle}</div>')
        if meta:
            parts.append(f'<div class="doc-meta">{meta}</div>')
        head = f'<div class="doc-head">{"".join(parts)}</div>'

    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{title or 'report'}</title><style>{CSS}</style></head>"
        f'<body>{head}{body}</body></html>'
    )


def render_pdf(html_path: pathlib.Path, pdf_path: pathlib.Path) -> None:
    cmd = [
        EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf_path.resolve().as_posix()}",
        html_path.resolve().as_uri(),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if not pdf_path.exists() or pdf_path.stat().st_size < 1024:
        raise RuntimeError(
            f"PDF 渲染失败: {r.stdout.decode('utf-8', 'ignore')[-500:]}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="markdown 文件路径")
    ap.add_argument("-o", "--output", help="输出 PDF 路径（默认与 md 同名）")
    ap.add_argument("--title", default="", help="报告主标题")
    ap.add_argument("--subtitle", default="", help="副标题（日期/口径）")
    ap.add_argument("--meta", default="", help="报头补充说明")
    ap.add_argument("--keep-html", action="store_true", help="保留中间 HTML")
    a = ap.parse_args()

    src = pathlib.Path(a.input)
    if not src.exists():
        sys.exit(f"找不到文件: {src}")
    out = pathlib.Path(a.output) if a.output else src.with_suffix(".pdf")

    md_text = src.read_text(encoding="utf-8")

    # 去掉正文里重复的一级标题（报头已渲染一次）
    if a.title:
        md_text = re.sub(r"^#\s+.*$", "", md_text, count=1, flags=re.M)

    html = build_html(md_text, a.title, a.subtitle, a.meta)

    # 中间 HTML 一律落在仓库内临时目录（archive/temp_md2pdf，已被 .gitignore 排除），
    # 不写系统 temp，避免产物散落到 C 盘；渲染完成后自动清理。
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    tmp_dir = repo_root / "archive" / "temp_md2pdf"
    if a.keep_html:
        html_path = out.with_suffix(".html")
    else:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        html_path = tmp_dir / f"_md2pdf_{src.stem}.html"

    html_path.write_text(html, encoding="utf-8")
    try:
        render_pdf(html_path, out)
        print(f"[OK] PDF -> {out}  ({out.stat().st_size/1024:.0f} KB)")
        if a.keep_html:
            print(f"[OK] HTML -> {html_path}")
    finally:
        if not a.keep_html:
            try:
                html_path.unlink()
            except OSError:
                pass
            try:
                if tmp_dir.exists() and not any(tmp_dir.iterdir()):
                    tmp_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    main()
