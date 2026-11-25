from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant.stock_selector.analytics import macd, sma, stock_features
from quant.stock_selector.data_access import latest_leader_report, load_config, parse_leader_report
from quant.stock_selector.backtest import _evaluate_trade
from quant.stock_selector.engine import (
    determine_market_regime,
    evaluate_lane,
    fundamental_quality,
)
from quant.stock_selector.models import Bar, Candidate, SectorState
from quant.stock_selector.report import write_reports


def make_bars(count: int, start: float = 10.0, step: float = 0.1) -> list[Bar]:
    bars = []
    for index in range(count):
        close = start + index * step
        bars.append(
            Bar(
                date=20250101 + index,
                open=close - 0.05,
                high=close + 0.12,
                low=close - 0.12,
                close=close,
                amount=200_000_000 + index * 1_000_000,
                volume=10_000_000 + index * 10_000,
            )
        )
    return bars


class AnalyticsTest(unittest.TestCase):
    def test_sma_and_macd(self) -> None:
        closes = [float(value) for value in range(1, 61)]
        self.assertAlmostEqual(sma(closes, 5), 58.0)
        values = macd(closes)
        self.assertIsNotNone(values["dif"])
        self.assertIsNotNone(values["dea"])
        self.assertIsNotNone(values["hist"])

    def test_features_have_no_exception_on_short_series(self) -> None:
        self.assertFalse(stock_features(make_bars(10))["enough_data"])
        features = stock_features(make_bars(130), make_bars(130, 3000, 5))
        self.assertTrue(features["enough_data"])
        self.assertTrue(features["ma20_rising"])
        self.assertIn("macd_daily_hist", features)


class SourceParsingTest(unittest.TestCase):
    def test_leader_report_parses_three_per_sector(self) -> None:
        report = latest_leader_report()
        self.assertIsNotNone(report)
        items = parse_leader_report(report)
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0].sector, "文娱用品")
        self.assertEqual(items[0].tier, 1)
        self.assertIsNotNone(items[0].main_net)
        self.assertIsNotNone(items[0].net_profit_yoy)

    def test_fundamental_quality(self) -> None:
        red = Candidate(
            code="000001",
            name="测试",
            sector="测试",
            fundamentals_available=True,
            net_profit_billion=-0.1,
        )
        green = Candidate(
            code="000002",
            name="测试",
            sector="测试",
            fundamentals_available=True,
            net_profit_billion=0.2,
            net_profit_yoy=20,
            revenue_yoy=10,
            pe=25,
        )
        self.assertEqual(fundamental_quality(red)[0], "red")
        self.assertEqual(fundamental_quality(green)[0], "green")


class MarketRegimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()

    def test_rising_market_is_offensive(self) -> None:
        result = determine_market_regime(
            make_bars(130, 3000, 5),
            make_bars(130, 5000, 8),
            {"up": 3500, "down": 1200, "limit_up": 90, "failed": 10, "cycle": "启动"},
            self.config,
        )
        self.assertEqual(result["regime"], "进攻")
        self.assertTrue(result["trade_allowed"])

    def test_weak_market_is_defensive(self) -> None:
        result = determine_market_regime(
            make_bars(130, 5000, -5),
            make_bars(130, 7000, -8),
            {"up": 1200, "down": 3500, "limit_up": 30, "failed": 60, "cycle": "退潮"},
            self.config,
        )
        self.assertEqual(result["regime"], "防守")
        self.assertFalse(result["trade_allowed"])


class EvaluationTest(unittest.TestCase):
    def test_qualified_swing_leader_can_enter_candidate_pool(self) -> None:
        config = load_config()
        bars = make_bars(130, 10.0, 0.08)
        features = stock_features(bars, make_bars(130, 3000, 3))
        candidate = Candidate(
            code="600001",
            name="测试龙头",
            sector="测试主线",
            pct=4.5,
            volume_ratio=1.8,
            main_net=80_000_000,
            float_cap=8_000_000_000,
            fundamentals_available=True,
            net_profit_billion=1.2,
            net_profit_yoy=30,
            revenue_yoy=20,
            pe=28,
        )
        sector = SectorState(
            name="测试主线",
            gate="pass",
            avg_score=4.2,
            days=3,
            ma20=True,
            ma10=True,
            swing_eligible=True,
            short_eligible=True,
        )
        market = {"trade_allowed": True}
        result = evaluate_lane(
            "swing", candidate, features, "波段龙头", sector, market, config
        )
        self.assertEqual(result.decision, "候选")
        self.assertIn(result.grade, {"A", "B"})
        self.assertFalse(result.hard_fail_reasons)

    def test_snapshot_trade_uses_next_day_open(self) -> None:
        bars = make_bars(20, 10.0, 0.1)
        signal = {"code": "600001", "name": "测试", "sector": "测试", "lane": "short", "role": "波段龙头", "grade": "A", "data_date": "2025-01-05"}
        trade = _evaluate_trade(signal, bars, 3, 15)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["entry_date"], "20250106")
        self.assertGreater(trade["raw_return_pct"], 0)


class ReportTest(unittest.TestCase):
    def test_write_reports(self) -> None:
        payload = {
            "version": "test",
            "generated_at": "2026-11-25 15:00:00",
            "data_date": "2026-11-24",
            "market": {"regime": "防守", "trade_allowed": False, "position_multiplier": 0, "reasons": []},
            "sectors": [],
            "swing": [],
            "short": [],
            "rejected": [],
            "summary": {},
            "source": {},
        }
        with tempfile.TemporaryDirectory() as temp:
            paths = write_reports(payload, Path(temp))
            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["markdown"].exists())
            self.assertTrue(paths["html"].exists())
            decoded = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertEqual(decoded["data_date"], "2026-11-24")
