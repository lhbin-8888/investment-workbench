"""时点快照回放回测。

只回放本工具每日实际生成的 A/B 级候选，避免拿今天的板块成分回填历史，
从而杜绝幸存者偏差和未来函数。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .data_access import load_stock_bars
from .models import Bar


def _date_int(value: str) -> int:
    return int(value.replace("-", ""))


def _apply_costs(raw_return: float, cost_bps: float) -> float:
    return raw_return - cost_bps / 10000.0


def _evaluate_trade(
    candidate: dict[str, Any],
    bars: list[Bar],
    horizon: int,
    cost_bps: float,
) -> dict[str, Any] | None:
    signal_date = _date_int(str(candidate["data_date"]))
    future = [bar for bar in bars if bar.date > signal_date]
    if len(future) < horizon:
        return None
    entry_bar = future[0]
    window = future[1 : horizon + 1]
    if len(window) < horizon or entry_bar.open <= 0:
        return None
    entry_price = entry_bar.open
    exit_price = window[-1].close
    raw_return = exit_price / entry_price - 1.0
    net_return = _apply_costs(raw_return, cost_bps)
    max_high = max(bar.high for bar in window)
    min_low = min(bar.low for bar in window)
    return {
        "code": candidate["code"],
        "name": candidate.get("name", ""),
        "sector": candidate.get("sector", ""),
        "lane": candidate["lane"],
        "role": candidate.get("role", ""),
        "grade": candidate.get("grade", ""),
        "signal_date": candidate["data_date"],
        "entry_date": str(entry_bar.date),
        "exit_date": str(window[-1].date),
        "horizon": horizon,
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "raw_return_pct": round(raw_return * 100.0, 4),
        "net_return_pct": round(net_return * 100.0, 4),
        "mfe_pct": round((max_high / entry_price - 1.0) * 100.0, 4),
        "mae_pct": round((min_low / entry_price - 1.0) * 100.0, 4),
    }


def _summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "avg_net_return_pct": None,
            "median_net_return_pct": None,
            "win_rate": None,
            "avg_mfe_pct": None,
            "avg_mae_pct": None,
        }
    returns = [float(item["net_return_pct"]) for item in trades]
    return {
        "trades": len(trades),
        "avg_net_return_pct": round(statistics.fmean(returns), 4),
        "median_net_return_pct": round(statistics.median(returns), 4),
        "win_rate": round(sum(value > 0 for value in returns) / len(returns), 4),
        "avg_mfe_pct": round(
            statistics.fmean(float(item["mfe_pct"]) for item in trades), 4
        ),
        "avg_mae_pct": round(
            statistics.fmean(float(item["mae_pct"]) for item in trades), 4
        ),
    }


def run_backtest(
    snapshot_dir: Path,
    cost_bps: float = 15.0,
) -> dict[str, Any]:
    snapshots = sorted(snapshot_dir.glob("选股雷达_*.json"))
    all_candidates: list[dict[str, Any]] = []
    for path in snapshots:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for lane in ("swing", "short"):
            for item in payload.get(lane, []):
                if item.get("decision") != "候选" or item.get("grade") not in {"A", "B"}:
                    continue
                all_candidates.append(
                    {
                        **item,
                        "data_date": payload.get("data_date"),
                        "lane": lane,
                    }
                )
    bars_cache: dict[str, list[Bar]] = {}
    trades: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for candidate in all_candidates:
        code = candidate["code"]
        if code not in bars_cache:
            bars_cache[code] = load_stock_bars(code)
        horizons = (5, 10, 20) if candidate["lane"] == "swing" else (1, 3, 5)
        produced = False
        for horizon in horizons:
            result = _evaluate_trade(candidate, bars_cache[code], horizon, cost_bps)
            if result is None:
                continue
            trades.append(result)
            produced = True
        if not produced:
            pending.append(
                {
                    "code": code,
                    "name": candidate.get("name", ""),
                    "lane": candidate["lane"],
                    "signal_date": candidate.get("data_date"),
                }
            )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[f"{trade['lane']}:{trade['grade']}:{trade['horizon']}"].append(trade)
        groups[f"{trade['lane']}:all:{trade['horizon']}"].append(trade)
    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_count": len(snapshots),
        "qualified_signal_count": len(all_candidates),
        "completed_trade_count": len(trades),
        "pending_count": len(pending),
        "cost_bps_round_trip": cost_bps,
        "groups": {name: _summary(items) for name, items in sorted(groups.items())},
        "trades": trades,
        "pending": pending,
        "warning": "这是时点快照前向回放，不会使用未来板块成分；样本不足时不得据此调参。",
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 选股雷达快照回放",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 快照数：{payload['snapshot_count']}",
        f"- A/B 信号数：{payload['qualified_signal_count']}",
        f"- 已完成交易窗口：{payload['completed_trade_count']}",
        f"- 待未来数据：{payload['pending_count']}",
        f"- 往返成本假设：{payload['cost_bps_round_trip']} bps",
        "",
        payload["warning"],
        "",
        "| 分组 | 样本 | 平均净收益 | 中位净收益 | 胜率 | 平均MFE | 平均MAE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    if not payload["groups"]:
        lines.append("| 暂无可回放信号 | 0 | — | — | — | — | — |")
    for name, group in payload["groups"].items():
        lines.append(
            "| {name} | {trades} | {avg}% | {median}% | {win:.1%} | {mfe}% | {mae}% |".format(
                name=name,
                trades=group["trades"],
                avg=group["avg_net_return_pct"],
                median=group["median_net_return_pct"],
                win=group["win_rate"],
                mfe=group["avg_mfe_pct"],
                mae=group["avg_mae_pct"],
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="选股雷达时点快照回放")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
    )
    parser.add_argument("--cost-bps", type=float, default=15.0)
    args = parser.parse_args()
    payload = run_backtest(args.snapshot_dir, args.cost_bps)
    output_dir = args.snapshot_dir / "backtest"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"snapshot_backtest_{stamp}.json"
    md_path = output_dir / f"snapshot_backtest_{stamp}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(_markdown(payload), encoding="utf-8")
    print(
        f"快照 {payload['snapshot_count']} 份，A/B 信号 {payload['qualified_signal_count']} 条，"
        f"完成窗口 {payload['completed_trade_count']} 条，待数据 {payload['pending_count']} 条"
    )
    print(f"JSON：{json_path}")
    print(f"Markdown：{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
