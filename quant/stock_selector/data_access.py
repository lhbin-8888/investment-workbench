"""复用投研工作台现有报告、通达信日线和可选实时快照。"""

from __future__ import annotations

import json
import re
import struct
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .models import Bar, Candidate, SectorState


ROOT = Path(__file__).resolve().parents[2]
TDX_ROOT = Path(r"D:\TDX")
DAY_DIRS = {
    "sh": TDX_ROOT / "vipdoc" / "sh" / "lday",
    "sz": TDX_ROOT / "vipdoc" / "sz" / "lday",
}
NAME_FILE = TDX_ROOT / "T0002" / "hq_cache" / "infoharbor_ex.code"
BLOCK_DIR = TDX_ROOT / "T0002" / "blocknew"
SECTOR_JSON = ROOT / "03-A股盘面信息" / "板块轮动" / "sector-rotation-data.json"
RDGP_CANDIDATES = ROOT / "quant" / "tdx_intraday_watch" / "热点股池_candidates.json"
RESONANCE_JSON = ROOT / "quant" / "unified_research" / "data" / "resonance-picks.json"
LEADER_REPORT_DIR = ROOT / "01-投研信息收集" / "行业板块龙头股分析"
SENTIMENT_JSON = ROOT / "data" / "market-sentiment.json"

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (Path(__file__).resolve().parent / "config.json")
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def parse_day_file(path: Path) -> list[Bar]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    count = len(raw) // 32
    if count <= 0:
        return []
    values = struct.unpack("<" + ("iiiiifii" * count), raw[: count * 32])
    bars: list[Bar] = []
    for index in range(count):
        offset = index * 8
        date = values[offset]
        close = values[offset + 4] / 100.0
        if date < 19900101 or close <= 0:
            continue
        bars.append(
            Bar(
                date=date,
                open=values[offset + 1] / 100.0,
                high=values[offset + 2] / 100.0,
                low=values[offset + 3] / 100.0,
                close=close,
                amount=float(values[offset + 5]),
                volume=int(values[offset + 6]),
            )
        )
    return bars


def market_of(code: str) -> str | None:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "sh"
    if code.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return "sz"
    return None


def stock_day_path(code: str) -> Path | None:
    market = market_of(code)
    if not market:
        return None
    return DAY_DIRS[market] / f"{market}{code}.day"


def load_stock_bars(code: str) -> list[Bar]:
    path = stock_day_path(code)
    return parse_day_file(path) if path else []


def load_index_bars(code: str) -> list[Bar]:
    prefix = "sh" if code.startswith("000") else "sz"
    return parse_day_file(DAY_DIRS[prefix] / f"{prefix}{code}.day")


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if not NAME_FILE.exists():
        return names
    try:
        lines = NAME_FILE.read_text(encoding="gbk", errors="ignore").splitlines()
    except OSError:
        return names
    for line in lines:
        parts = line.split("|")
        if len(parts) >= 2 and parts[0].isdigit():
            names[parts[0]] = parts[1].strip()
    return names


def is_risk_name(name: str) -> bool:
    normalized = (name or "").upper().replace(" ", "")
    return normalized.startswith(("ST", "*ST")) or "退" in normalized


def load_sectors() -> list[SectorState]:
    rows = load_json(SECTOR_JSON, [])
    sectors: list[SectorState] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        scores = row.get("s") or []
        avg = row.get("avgRaw", row.get("avg", 0.0)) or 0.0
        sectors.append(
            SectorState(
                name=str(row.get("n") or ""),
                pct=float(row.get("z") or 0.0),
                main_net=float(row.get("f") or 0.0),
                limit_up=int(row.get("zt") or 0),
                max_streak=int(row.get("lb") or 0),
                avg_score=float(avg),
                gate=str(row.get("gate") or "unknown"),
                days=int(row.get("days") or 0),
                ma20=row.get("ma20") if isinstance(row.get("ma20"), bool) else None,
                ma10=row.get("ma10") if isinstance(row.get("ma10"), bool) else None,
                up_ratio=float(row["upRatio"]) if row.get("upRatio") is not None else None,
                median_pct=float(row["medPct"]) if row.get("medPct") is not None else None,
                stage=str(row.get("pos") or ""),
                catalyst=str(row.get("cat") or ""),
                reasons=[f"六维分:{scores}", f"硬门槛:{row.get('gateMsg') or ''}"]
                if scores
                else [f"硬门槛:{row.get('gateMsg') or ''}"],
            )
        )
    return sectors


def latest_leader_report() -> Path | None:
    reports = sorted(LEADER_REPORT_DIR.glob("*-行业板块龙头股分析报告.md"))
    return reports[-1] if reports else None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    compact = value.replace(",", "").strip()
    match = _NUM_RE.search(compact)
    return float(match.group(0)) if match else None


def _money_billion_to_yuan(value: str | None) -> float | None:
    number = _to_float(value)
    return number * 1e8 if number is not None else None


def _parse_revenue_cell(value: str) -> tuple[float | None, float | None]:
    parts = [part.strip() for part in value.split("/")]
    revenue_billion = _to_float(parts[0]) if parts else None
    yoy = _to_float(parts[1]) if len(parts) > 1 else None
    return revenue_billion, yoy


def parse_leader_report(path: Path) -> list[Candidate]:
    """解析每日龙头报告的三只龙头明细表。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    candidates: list[Candidate] = []
    current_sector = ""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        heading = re.match(r"^###\s+\d+\.\d+\s+(.+?)（[+-]?\d", line)
        if heading:
            current_sector = heading.group(1).strip()
        if not line.startswith("| 地位 | 代码 | 名称 |"):
            index += 1
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        index += 1
        if index < len(lines) and set(lines[index].replace("|", "").strip()) <= {"-", ":", " "}:
            index += 1
        while index < len(lines) and lines[index].strip().startswith("|"):
            row_line = lines[index].strip()
            cells = [cell.strip() for cell in row_line.strip("|").split("|")]
            if len(cells) != len(headers):
                index += 1
                continue
            row = dict(zip(headers, cells))
            code = row.get("代码", "").strip()
            name = row.get("名称", "").strip()
            if not re.fullmatch(r"\d{6}", code):
                index += 1
                continue
            status = row.get("地位", "")
            tier = {"龙一": 1, "龙二": 2, "龙三": 3}.get(status, 99)
            revenue_billion, revenue_yoy = _parse_revenue_cell(
                row.get("三季报营收/同比", "")
            )
            net_profit_billion, net_profit_yoy = _parse_revenue_cell(
                row.get("三季报归母/同比", "")
            )
            candidates.append(
                Candidate(
                    code=code,
                    name=name,
                    sector=current_sector,
                    source=f"leader_report:{path.name}",
                    tier=tier,
                    pct=_to_float(row.get("涨跌幅")),
                    close=_to_float(row.get("收盘价")),
                    float_cap=_money_billion_to_yuan(row.get("流通市值（亿元）")),
                    amount=_money_billion_to_yuan(row.get("成交额（亿元）")),
                    turnover=_to_float(row.get("换手率")),
                    volume_ratio=_to_float(row.get("量比")),
                    main_net=_money_billion_to_yuan(row.get("主力净流入")),
                    pe=_to_float(row.get("PE(TTM)")),
                    pb=_to_float(row.get("PB")),
                    roe=_to_float(row.get("ROE")),
                    revenue_billion=revenue_billion,
                    revenue_yoy=revenue_yoy,
                    net_profit_billion=net_profit_billion,
                    net_profit_yoy=net_profit_yoy,
                    status=row.get("题材/状态", ""),
                    fundamentals_available=True,
                )
            )
            index += 1
        continue
    return candidates


def load_rdgp_candidates() -> list[Candidate]:
    payload = load_json(RDGP_CANDIDATES, {})
    candidates: list[Candidate] = []
    for sector in payload.get("sectors", []):
        sector_name = str(sector.get("name") or "")
        sector_code = str(sector.get("code") or "")
        for row in sector.get("chosen", []):
            code = str(row.get("code") or "")
            if not re.fullmatch(r"\d{6}", code):
                continue
            candidates.append(
                Candidate(
                    code=code,
                    name=str(row.get("name") or ""),
                    sector=sector_name,
                    sector_code=sector_code,
                    source="RDGP",
                    tier=int(row.get("tier") or 99),
                    pct=row.get("pct"),
                    close=row.get("c"),
                    volume_ratio=row.get("vr"),
                )
            )
    return candidates


def load_resonance_candidates() -> list[Candidate]:
    payload = load_json(RESONANCE_JSON, {})
    candidates: list[Candidate] = []
    for row in payload.get("rows", []):
        code = str(row.get("code") or "")
        if not re.fullmatch(r"\d{6}", code):
            continue
        candidates.append(
            Candidate(
                code=code,
                name=str(row.get("name") or ""),
                sector=str(row.get("sector") or ""),
                source="resonance",
                tier=4,
                pct=row.get("pct"),
                turnover=row.get("turnover"),
                main_net=row.get("main_net"),
                pe=row.get("pe"),
                pb=row.get("pb"),
                revenue_yoy=row.get("rev_yoy"),
                net_profit_yoy=row.get("np_yoy"),
                fundamentals_available=bool(row.get("report_date")),
                status=";".join(row.get("risk_tags") or []),
            )
        )
    return candidates


def merge_candidates(*groups: Iterable[Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for group in groups:
        for item in group:
            existing = merged.get(item.code)
            if existing is None:
                merged[item.code] = item
                continue
            for field_name in (
                "sector",
                "sector_code",
                "source",
                "tier",
                "pct",
                "close",
                "float_cap",
                "amount",
                "turnover",
                "volume_ratio",
                "main_net",
                "pe",
                "pb",
                "roe",
                "revenue_billion",
                "revenue_yoy",
                "net_profit_billion",
                "net_profit_yoy",
                "status",
            ):
                new_value = getattr(item, field_name)
                old_value = getattr(existing, field_name)
                if new_value not in (None, "", 0, 0.0, 99) or old_value in (None, "", 0, 0.0, 99):
                    setattr(existing, field_name, new_value)
            existing.fundamentals_available = (
                existing.fundamentals_available or item.fundamentals_available
            )
            existing.extra.update(item.extra)
            if item.source and item.source not in existing.source:
                existing.source = f"{existing.source}+{item.source}"
    return list(merged.values())


def load_all_candidates() -> tuple[list[Candidate], Path | None]:
    report = latest_leader_report()
    report_candidates = parse_leader_report(report) if report else []
    candidates = merge_candidates(
        load_rdgp_candidates(),
        report_candidates,
        load_resonance_candidates(),
    )
    return candidates, report


def fetch_live_quotes(codes: list[str], timeout: int = 8) -> dict[str, dict[str, Any]]:
    """批量获取少量候选股快照；失败时返回空字典，由上层降级。"""
    if not codes:
        return {}
    secids = ",".join(
        ("1." if code.startswith(("6", "9")) else "0.") + code for code in codes
    )
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get?secids="
        + urllib.parse.quote(secids, safe=",.")
        + "&fields=f2,f3,f8,f9,f10,f12,f14,f20,f21,f23,f62,f184"
        + "&fltt=2&invt=2&ut=fa5fd1943c7b386f172d6893dbfba10b"
    )
    request = urllib.request.Request(url, headers=_UA)
    payload = None
    for attempt in range(2):
        try:
            raw = urllib.request.urlopen(request, timeout=timeout).read()
            payload = json.loads(raw.decode("utf-8", "ignore"))
            break
        except Exception:
            if attempt == 0:
                time.sleep(0.4)
    if not payload:
        return {}
    result: dict[str, dict[str, Any]] = {}
    diff = (payload.get("data") or {}).get("diff", []) or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    for item in diff:
        code = str(item.get("f12") or "")
        if not code:
            continue
        result[code] = {
            "price": _safe_live_number(item.get("f2")),
            "pct": _safe_live_number(item.get("f3")),
            "turnover": _safe_live_number(item.get("f8")),
            "pe": _safe_live_number(item.get("f9")),
            "volume_ratio": _safe_live_number(item.get("f10")),
            "total_cap": _safe_live_number(item.get("f20")),
            "float_cap": _safe_live_number(item.get("f21")),
            "pb": _safe_live_number(item.get("f23")),
            "main_net": _safe_live_number(item.get("f62")),
            "main_pct": _safe_live_number(item.get("f184")),
        }
    return result


def _safe_live_number(value: Any) -> float | None:
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enrich_candidates(candidates: list[Candidate]) -> tuple[list[Candidate], bool]:
    quotes = fetch_live_quotes([candidate.code for candidate in candidates])
    for candidate in candidates:
        quote = quotes.get(candidate.code)
        if not quote:
            continue
        candidate.close = candidate.close or quote.get("price")
        candidate.pct = quote.get("pct") if quote.get("pct") is not None else candidate.pct
        candidate.float_cap = quote.get("float_cap") or candidate.float_cap
        candidate.turnover = quote.get("turnover") if quote.get("turnover") is not None else candidate.turnover
        candidate.volume_ratio = (
            quote.get("volume_ratio")
            if quote.get("volume_ratio") is not None
            else candidate.volume_ratio
        )
        candidate.main_net = quote.get("main_net") if quote.get("main_net") is not None else candidate.main_net
        candidate.pe = quote.get("pe") if quote.get("pe") is not None else candidate.pe
        candidate.pb = quote.get("pb") if quote.get("pb") is not None else candidate.pb
        candidate.extra["main_pct"] = quote.get("main_pct")
    return candidates, bool(quotes)


def load_sentiment() -> dict[str, Any]:
    payload = load_json(SENTIMENT_JSON, {})
    rows = payload.get("rows") or []
    return rows[-1] if rows else {}
