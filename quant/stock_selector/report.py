"""生成 Markdown 与独立 HTML 选股雷达。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


GRADE_LABEL = {"A": "A级", "B": "B级", "C": "C级", "淘汰": "淘汰"}


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):+.2f}%"


def _number(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _money(value: Any) -> str:
    if value is None:
        return "—"
    number = float(value)
    if abs(number) >= 1e8:
        return f"{number / 1e8:+.2f}亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:+.1f}万"
    return f"{number:+.0f}"


def _cell(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value)
    return str(value)


def _rows(items: list[dict[str, Any]], lane: str) -> list[str]:
    if not items:
        return ["| — | — | — | — | — | — | — | — |"]
    rows = []
    for item in items:
        features = item.get("features") or {}
        candidate = item.get("candidate") or {}
        plan = item.get("trade_plan") or {}
        entry = plan.get("entry_zone")
        entry_text = f"{entry[0]}~{entry[1]}" if entry else "—"
        risk = "；".join(item.get("risk_tags") or []) or "无"
        rows.append(
            "| {name} | {sector} | {role} | {grade} | {score} | {pct} | {vr} | "
            "{main} | {entry} | {stop} | {risk} |".format(
                name=item.get("name") or item.get("code"),
                sector=item.get("sector") or "—",
                role=item.get("role") or "—",
                grade=GRADE_LABEL.get(item.get("grade"), item.get("grade") or "—"),
                score=_number(item.get("score")),
                pct=_pct(candidate.get("pct", features.get("pct"))),
                vr=_number(candidate.get("volume_ratio", features.get("volume_ratio"))),
                main=_money(candidate.get("main_net")),
                entry=entry_text,
                stop=plan.get("stop", "—"),
                risk=risk.replace("|", "/"),
            )
        )
    return rows


def build_markdown(payload: dict[str, Any]) -> str:
    market = payload.get("market") or {}
    summary = payload.get("summary") or {}
    sectors = payload.get("sectors") or []
    eligible = [
        sector
        for sector in sectors
        if sector.get("swing_eligible") or sector.get("short_eligible")
    ]
    lines = [
        f"# 主线与热点双通道选股雷达 · {payload.get('data_date')}",
        "",
        f"> 生成时间：{payload.get('generated_at')}",
        "> 本报告是规则化研究工具输出，不构成投资建议。",
        "",
        "## 一、市场总闸",
        "",
        f"- **市场状态**：{market.get('regime', '未知')}",
        f"- **允许新开仓**：{'是' if market.get('trade_allowed') else '否'}",
        f"- **建议仓位系数**：{market.get('position_multiplier', 0)}",
        f"- **判断依据**：{'；'.join(market.get('reasons') or [])}",
        "",
        "## 二、结果概览",
        "",
        f"- 板块总数：{summary.get('sector_count', 0)}",
        f"- 波段可用板块：{summary.get('swing_eligible_sectors', 0)}",
        f"- 短线可用板块：{summary.get('short_eligible_sectors', 0)}",
        f"- 波段观察/候选：{summary.get('swing_count', 0)}",
        f"- 短线观察/候选：{summary.get('short_count', 0)}",
        f"- 淘汰记录：{summary.get('rejected_count', 0)}",
        "",
        "## 三、有资格的板块",
        "",
        "| 板块 | 状态 | 均分 | 涨幅 | 主力净额 | 连续天数 | MA20 | 波段 | 短线 |",
        "|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    if eligible:
        for sector in eligible:
            lines.append(
                "| {name} | {gate} | {avg:.2f} | {pct:+.2f}% | {fund:+.2f}亿 | {days} | "
                "{ma20} | {swing} | {short} |".format(
                    name=sector.get("name"),
                    gate=sector.get("gate"),
                    avg=float(sector.get("avg_score") or 0),
                    pct=float(sector.get("pct") or 0),
                    fund=float(sector.get("main_net") or 0),
                    days=sector.get("days") or 0,
                    ma20="是" if sector.get("ma20") else "否",
                    swing="是" if sector.get("swing_eligible") else "否",
                    short="是" if sector.get("short_eligible") else "否",
                )
            )
    else:
        lines.append("| — | 当前无合格板块 | — | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## 四、波段强势龙头 / 中军",
            "",
            "| 名称 | 板块 | 角色 | 等级 | 得分 | 涨幅 | 量比 | 主力资金 | 入场区 | 止损 | 风险标签 |",
            "|---|---|---|---|---:|---:|---:|---:|---|---:|---|",
            *_rows(payload.get("swing") or [], "swing"),
            "",
            "> 波段通道只有在市场不是防守、板块通过硬门槛、个股为龙头或中军时才升级为交易候选。",
            "",
            "## 五、短线机会",
            "",
            "| 名称 | 板块 | 角色 | 等级 | 得分 | 涨幅 | 量比 | 主力资金 | 入场区 | 止损 | 风险标签 |",
            "|---|---|---|---|---:|---:|---:|---:|---|---:|---|",
            *_rows(payload.get("short") or [], "short"),
            "",
            "> C 级只进入观察名单。高开超过 2%、接近涨停、板块退潮或资金转负时，不执行计划。",
            "",
            "## 六、重点淘汰原因",
            "",
            "| 名称 | 板块 | 通道 | 角色 | 得分 | 淘汰原因 |",
            "|---|---|---|---|---:|---|",
        ]
    )
    rejected = payload.get("rejected") or []
    if rejected:
        for item in rejected[:30]:
            lines.append(
                "| {name} | {sector} | {lane} | {role} | {score} | {reason} |".format(
                    name=item.get("name") or item.get("code"),
                    sector=item.get("sector") or "—",
                    lane=item.get("lane") or "—",
                    role=item.get("role") or "—",
                    score=_number(item.get("score")),
                    reason="；".join(item.get("hard_fail_reasons") or []).replace("|", "/"),
                )
            )
    else:
        lines.append("| — | — | — | — | — | 无 |")
    lines.extend(
        [
            "",
            "## 七、数据口径",
            "",
            f"- 板块报告：`{(payload.get('source') or {}).get('sector_report', '')}`",
            f"- 龙头报告：`{(payload.get('source') or {}).get('leader_report', '')}`",
            f"- 在线快照增强：{'启用' if (payload.get('source') or {}).get('online_quotes') else '未启用'}",
            "- 本地通达信日线为不复权数据，实盘前必须结合除权除息处理；回测需使用历史时点板块成分，禁止使用当前成分回填。",
        ]
    )
    return "\n".join(lines) + "\n"


def _grade_class(grade: str) -> str:
    return {"A": "a", "B": "b", "C": "c", "淘汰": "x"}.get(grade, "c")


def _table(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">当前没有满足该通道硬门槛的标的。没有机会也是结论。</div>'
    rows = []
    for item in items:
        candidate = item.get("candidate") or {}
        features = item.get("features") or {}
        plan = item.get("trade_plan") or {}
        entry = plan.get("entry_zone")
        entry_text = f"{entry[0]} ~ {entry[1]}" if entry else "—"
        tags = "".join(
            f'<span class="tag">{html.escape(str(tag))}</span>'
            for tag in (item.get("risk_tags") or [])
        ) or '<span class="muted">无</span>'
        grade = str(item.get("grade") or "C")
        rows.append(
            "<tr>"
            f'<td><strong>{html.escape(str(item.get("name") or item.get("code")))}</strong>'
            f'<small>{html.escape(str(item.get("code")))}</small></td>'
            f"<td>{html.escape(str(item.get('sector') or '—'))}</td>"
            f"<td>{html.escape(str(item.get('role') or '—'))}</td>"
            f'<td><span class="grade {_grade_class(grade)}">{html.escape(GRADE_LABEL.get(grade, grade))}</span></td>'
            f"<td>{_number(item.get('score'))}</td>"
            f"<td>{_pct(candidate.get('pct', features.get('pct')))}</td>"
            f"<td>{_number(candidate.get('volume_ratio', features.get('volume_ratio')))}</td>"
            f"<td>{_money(candidate.get('main_net'))}</td>"
            f"<td>{html.escape(entry_text)}</td>"
            f"<td>{html.escape(str(plan.get('stop', '—')))}</td>"
            f"<td>{tags}</td>"
            "</tr>"
        )
    return (
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>名称</th><th>板块</th><th>角色</th><th>等级</th><th>得分</th>"
        "<th>涨幅</th><th>量比</th><th>主力资金</th><th>入场区</th><th>止损</th><th>风险标签</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def build_html(payload: dict[str, Any]) -> str:
    market = payload.get("market") or {}
    summary = payload.get("summary") or {}
    eligible = [
        sector
        for sector in (payload.get("sectors") or [])
        if sector.get("swing_eligible") or sector.get("short_eligible")
    ]
    sector_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(sector.get('name')))}</td>"
        f"<td>{html.escape(str(sector.get('gate')))}</td>"
        f"<td>{_number(sector.get('avg_score'))}</td>"
        f"<td>{_pct(sector.get('pct'))}</td>"
        f"<td>{_money(float(sector.get('main_net') or 0) * 1e8)}</td>"
        f"<td>{sector.get('days') or 0}</td>"
        f"<td>{'是' if sector.get('swing_eligible') else '否'}</td>"
        f"<td>{'是' if sector.get('short_eligible') else '否'}</td>"
        "</tr>"
        for sector in eligible
    ) or '<tr><td colspan="8" class="empty">当前无合格板块</td></tr>'
    rejected = payload.get("rejected") or []
    rejected_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('name') or item.get('code')))}</td>"
        f"<td>{html.escape(str(item.get('sector') or '—'))}</td>"
        f"<td>{html.escape(str(item.get('lane') or '—'))}</td>"
        f"<td>{html.escape('；'.join(item.get('hard_fail_reasons') or []))}</td>"
        "</tr>"
        for item in rejected[:60]
    )
    regime_class = {"进攻": "on", "中性": "mid", "防守": "off"}.get(
        str(market.get("regime")), "mid"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>主线与热点双通道选股雷达 {html.escape(str(payload.get("data_date")))}</title>
<style>
:root{{--bg:#0c1118;--panel:#141c27;--panel2:#182331;--line:#29394d;--text:#e7edf5;--muted:#8fa1b7;--a:#36d399;--b:#62a8ff;--c:#f5c542;--x:#8b98a8;--danger:#ff6b6b;--accent:#b794f6}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top right,#1c2738 0,var(--bg) 38%);color:var(--text);font:14px/1.55 "Microsoft YaHei","PingFang SC",sans-serif}}
main{{max-width:1480px;margin:0 auto;padding:32px 22px 60px}}h1{{font-size:28px;margin:0 0 6px}}h2{{font-size:19px;margin:30px 0 12px}}.sub{{color:var(--muted)}}
.notice{{margin:16px 0;padding:12px 14px;border:1px solid var(--line);background:#111a25;border-radius:10px;color:#b9c7d8}}.grid{{display:grid;grid-template-columns:1.2fr 2fr;gap:14px}}
.embedded main{{padding-top:18px}}.embedded .page-title,.embedded .page-meta,.embedded .page-notice{{display:none}}
.card{{background:linear-gradient(160deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 10px 30px #0004}}
.regime{{display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:20px}}.dot{{width:10px;height:10px;border-radius:50%}}.on .dot{{background:var(--a);box-shadow:0 0 14px var(--a)}}.mid .dot{{background:var(--c);box-shadow:0 0 14px var(--c)}}.off .dot{{background:var(--danger);box-shadow:0 0 14px var(--danger)}}
.stats{{display:grid;grid-template-columns:repeat(6,minmax(100px,1fr));gap:10px}}.stat{{background:#101824;border:1px solid var(--line);border-radius:10px;padding:12px}}.stat b{{display:block;font-size:23px;color:#fff}}.stat span{{color:var(--muted);font-size:12px}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse;min-width:980px}}th,td{{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#101824;color:#aebdd0;font-weight:600;position:sticky;top:0}}tr:hover td{{background:#ffffff05}}small{{display:block;color:var(--muted);margin-top:2px}}
.grade{{display:inline-block;min-width:42px;text-align:center;border-radius:999px;padding:2px 8px;font-weight:700}}.grade.a{{background:#133c2c;color:var(--a)}}.grade.b{{background:#152d4a;color:var(--b)}}.grade.c{{background:#403718;color:var(--c)}}.grade.x{{background:#252c35;color:var(--x)}}
.tag{{display:inline-block;margin:2px 4px 2px 0;background:#2a2235;color:#d7c6ff;border:1px solid #493765;border-radius:999px;padding:1px 7px;font-size:12px}}.muted{{color:var(--muted)}}.empty{{padding:26px;color:var(--muted);text-align:center}}
details{{margin-top:16px}}summary{{cursor:pointer;color:#b9c7d8}}code{{color:#c9d8ea}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(2,1fr)}}main{{padding:22px 12px}}}}
</style>
</head>
<body><main>
<h1 class="page-title">主线与热点双通道选股雷达</h1>
<div class="sub page-meta">数据日期 {html.escape(str(payload.get("data_date")))} · 生成于 {html.escape(str(payload.get("generated_at")))} · v{html.escape(str(payload.get("version")))}</div>
<div class="notice page-notice">规则化研究工具输出，不构成投资建议。所有“候选”仍需人工核验公告、流动性与除权数据。</div>
<section class="grid">
  <div class="card"><div class="regime {regime_class}"><span class="dot"></span>{html.escape(str(market.get("regime")))}</div>
  <p class="sub">新开仓：{'允许' if market.get("trade_allowed") else '暂停'} · 仓位系数 {market.get("position_multiplier")}</p>
  <p>{html.escape('；'.join(market.get("reasons") or []))}</p></div>
  <div class="stats">
    <div class="stat"><b>{summary.get("sector_count", 0)}</b><span>板块总数</span></div>
    <div class="stat"><b>{summary.get("swing_eligible_sectors", 0)}</b><span>波段可用板块</span></div>
    <div class="stat"><b>{summary.get("short_eligible_sectors", 0)}</b><span>短线可用板块</span></div>
    <div class="stat"><b>{summary.get("swing_count", 0)}</b><span>波段观察/候选</span></div>
    <div class="stat"><b>{summary.get("short_count", 0)}</b><span>短线观察/候选</span></div>
    <div class="stat"><b>{summary.get("rejected_count", 0)}</b><span>淘汰记录</span></div>
  </div>
</section>
<h2>有资格的板块</h2>
<div class="table-wrap"><table><thead><tr><th>板块</th><th>状态</th><th>均分</th><th>涨幅</th><th>主力净额</th><th>连续天数</th><th>波段</th><th>短线</th></tr></thead><tbody>{sector_rows}</tbody></table></div>
<h2>波段强势龙头 / 中军</h2>
{_table(payload.get("swing") or [])}
<h2>短线机会</h2>
{_table(payload.get("short") or [])}
<details><summary>展开重点淘汰原因（{len(rejected)} 条）</summary>
<div class="table-wrap"><table><thead><tr><th>名称</th><th>板块</th><th>通道</th><th>原因</th></tr></thead><tbody>{rejected_rows}</tbody></table></div>
</details>
<h2>数据口径</h2>
<p class="sub">板块报告：<code>{html.escape(str((payload.get("source") or {}).get("sector_report", "")))}</code></p>
<p class="sub">龙头报告：<code>{html.escape(str((payload.get("source") or {}).get("leader_report", "")))}</code></p>
<p class="sub">本地日线为不复权数据；历史回测必须使用当时可见的板块成分与财报，禁止未来数据回填。</p>
</main>
<script>
(function(){{
  try{{
    if(new URLSearchParams(location.search).get('embed')==='1'){{
      document.documentElement.classList.add('embedded');
    }}
  }}catch(e){{}}
}})();
</script>
</body></html>"""


def write_reports(payload: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_date = str(payload.get("data_date") or "latest")
    paths = {
        "json": output_dir / f"选股雷达_{data_date}.json",
        "markdown": output_dir / f"选股雷达_{data_date}.md",
        "html": output_dir / f"选股雷达_{data_date}.html",
    }
    paths["json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["markdown"].write_text(build_markdown(payload), encoding="utf-8")
    paths["html"].write_text(build_html(payload), encoding="utf-8")
    latest = {
        "json": output_dir / "latest.json",
        "markdown": output_dir / "latest.md",
        "html": output_dir / "latest.html",
    }
    for kind in list(paths):
        latest[kind].write_text(paths[kind].read_text(encoding="utf-8"), encoding="utf-8")
        paths[f"latest_{kind}"] = latest[kind]
    return paths
