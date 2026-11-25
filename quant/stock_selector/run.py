"""命令行入口。

用法（在 D:\\投研工作台 根目录）：
    py -3 -m quant.stock_selector.run --offline
    py -3 -m quant.stock_selector.run --online
    py -3 -m quant.stock_selector.run --offline --write-blocks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .data_access import load_config
from .engine import analyze
from .report import write_reports


def _block_code(code: str) -> str:
    return ("1" if code.startswith(("6", "9")) else "0") + code


def _write_tdx_blocks(payload: dict) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tdx_autopick"))
    import tdx_writer as writer  # type: ignore

    swing_codes = [
        _block_code(item["code"])
        for item in payload.get("swing", [])
        if item.get("decision") == "候选" and item.get("grade") in {"A", "B"}
    ]
    short_codes = [
        _block_code(item["code"])
        for item in payload.get("short", [])
        if item.get("decision") == "候选" and item.get("grade") in {"A", "B"}
    ]
    if swing_codes:
        ok, count, path = writer.write_block(
            "波段强势", swing_codes, backup=True, auto_register=True
        )
        print(f"[板块] 波段强势 {'成功' if ok else '失败'} {count} 只 -> {path}")
    else:
        print("[板块] 波段强势无 A/B 候选，跳过写入，避免覆盖原板块")
    if short_codes:
        ok, count, path = writer.write_block(
            "短线机会", short_codes, backup=True, auto_register=True
        )
        print(f"[板块] 短线机会 {'成功' if ok else '失败'} {count} 只 -> {path}")
    else:
        print("[板块] 短线机会无 A/B 候选，跳过写入，避免覆盖原板块")


def main() -> int:
    parser = argparse.ArgumentParser(description="主线与热点双通道选股雷达")
    parser.add_argument("--online", action="store_true", help="使用东财实时快照补充候选字段")
    parser.add_argument("--offline", action="store_true", help="仅使用本地报告和日线（默认）")
    parser.add_argument("--write-blocks", action="store_true", help="把 A/B 级候选写入通达信板块")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="输出目录",
    )
    args = parser.parse_args()
    if args.online and args.offline:
        parser.error("--online 与 --offline 不能同时使用")
    config = load_config()
    payload = analyze(config, offline=not args.online)
    paths = write_reports(payload, args.output_dir)
    market = payload["market"]
    summary = payload["summary"]
    print(f"市场状态：{market['regime']}；新开仓：{'允许' if market['trade_allowed'] else '暂停'}")
    print(
        f"板块 {summary['sector_count']} 个；候选股 {summary['candidate_count']} 只；"
        f"波段记录 {summary['swing_count']} 条；短线记录 {summary['short_count']} 条；"
        f"淘汰 {summary['rejected_count']} 条"
    )
    print(f"JSON：{paths['json']}（最新：{paths['latest_json']}）")
    print(f"Markdown：{paths['markdown']}（最新：{paths['latest_markdown']}）")
    print(f"HTML：{paths['html']}（最新：{paths['latest_html']}）")
    if args.write_blocks:
        _write_tdx_blocks(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
