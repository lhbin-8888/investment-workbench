"""工具内部数据结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Bar:
    date: int
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int


@dataclass(slots=True)
class SectorState:
    name: str
    code: str = ""
    pct: float = 0.0
    main_net: float = 0.0
    limit_up: int = 0
    max_streak: int = 0
    avg_score: float = 0.0
    gate: str = "unknown"
    days: int = 0
    ma20: bool | None = None
    ma10: bool | None = None
    up_ratio: float | None = None
    median_pct: float | None = None
    stage: str = ""
    catalyst: str = ""
    swing_eligible: bool = False
    short_eligible: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Candidate:
    code: str
    name: str
    sector: str
    sector_code: str = ""
    source: str = ""
    tier: int = 99
    pct: float | None = None
    close: float | None = None
    float_cap: float | None = None
    amount: float | None = None
    turnover: float | None = None
    volume_ratio: float | None = None
    main_net: float | None = None
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    revenue_billion: float | None = None
    revenue_yoy: float | None = None
    net_profit_billion: float | None = None
    net_profit_yoy: float | None = None
    status: str = ""
    fundamentals_available: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Evaluation:
    code: str
    name: str
    sector: str
    lane: str
    role: str
    grade: str
    decision: str
    score: float
    score_parts: dict[str, float]
    features: dict[str, Any]
    hard_fail_reasons: list[str]
    risk_tags: list[str]
    trade_plan: dict[str, Any]
    candidate: dict[str, Any]
    sector_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
