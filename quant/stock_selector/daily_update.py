"""每日自动更新选股雷达并发布线上快照。

安全边界：
1. 先在临时目录重算，结果语义未变化时不修改工作区。
2. 不执行 git add -A，只提交选股雷达输出。
3. 发现已有其他暂存文件时中止，避免误提交用户工作。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOG_DIR = Path(__file__).resolve().parent / "logs"


def log(message: str, log_path: Path | None = None) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def run(
    command: list[str],
    log_path: Path,
    timeout: int = 240,
) -> subprocess.CompletedProcess[str]:
    log("执行：" + " ".join(command), log_path)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log("  " + line, log_path)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log("  [stderr] " + line, log_path)
    return result


def semantic_signature(payload: dict[str, Any]) -> str:
    copied = json.loads(json.dumps(payload, ensure_ascii=False))
    copied.pop("generated_at", None)
    return json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def output_files(date_text: str) -> list[Path]:
    return [
        OUTPUT_DIR / "latest.html",
        OUTPUT_DIR / "latest.json",
        OUTPUT_DIR / f"选股雷达_{date_text}.html",
        OUTPUT_DIR / f"选股雷达_{date_text}.json",
    ]


def git_command() -> str:
    found = shutil.which("git")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ):
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("未找到 git.exe")


def git(
    args: list[str],
    log_path: Path,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return run([git_command(), *args], log_path, timeout=timeout)


def push_with_retry(
    remote: str,
    refspec: str,
    log_path: Path,
    attempts: int = 2,
) -> bool:
    for index in range(1, attempts + 1):
        result = git(["push", remote, refspec], log_path, timeout=240)
        if result.returncode == 0:
            return True
        log(f"推送失败 {remote} {refspec}（{index}/{attempts}）", log_path)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="选股雷达每日自动更新与发布")
    parser.add_argument("--dry-run", action="store_true", help="只重算并比较，不写工作区、不提交")
    parser.add_argument("--no-push", action="store_true", help="允许本地提交，但不推送远端")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"daily_{dt.datetime.now():%Y%m%d}.log"
    baseline = load_json(OUTPUT_DIR / "latest.json")

    with tempfile.TemporaryDirectory(prefix="stock-selector-daily-") as temp:
        temp_dir = Path(temp)
        command = [
            sys.executable,
            "-m",
            "quant.stock_selector.run",
            "--offline",
            "--output-dir",
            str(temp_dir),
        ]
        result = run(command, log_path)
        if result.returncode != 0:
            log("选股雷达重算失败，终止更新", log_path)
            return result.returncode
        generated = load_json(temp_dir / "latest.json")
        if not generated:
            log("未生成有效 latest.json", log_path)
            return 2
        if baseline and semantic_signature(baseline) == semantic_signature(generated):
            log("输入数据未产生实质变化，跳过文件替换、提交和推送", log_path)
            return 0
        date_text = str(generated.get("data_date") or dt.date.today().isoformat())
        log(f"检测到选股雷达内容变化，数据日期 {date_text}", log_path)
        if args.dry_run:
            log("dry-run：将更新最新快照，但不修改工作区", log_path)
            return 0

        copied: list[Path] = []
        for filename in (
            "latest.html",
            "latest.json",
            f"选股雷达_{date_text}.html",
            f"选股雷达_{date_text}.json",
        ):
            source = temp_dir / filename
            if not source.exists():
                log(f"缺少输出文件：{filename}", log_path)
                return 3
            target = OUTPUT_DIR / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)

    staged = git(["diff", "--cached", "--name-only"], log_path)
    if staged.returncode != 0:
        log("无法检查暂存区，终止自动提交", log_path)
        return 4
    staged_files = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
    if staged_files:
        log("检测到已有其他暂存文件，为避免误提交已中止：", log_path)
        for path in staged_files:
            log("  " + path, log_path)
        return 5

    relative_files = [str(path.relative_to(ROOT)) for path in copied if path.exists()]
    added = git(["add", "--", *relative_files], log_path)
    if added.returncode != 0:
        log("暂存选股雷达输出失败", log_path)
        return 6
    diff = git(["diff", "--cached", "--quiet"], log_path)
    if diff.returncode == 0:
        log("没有可提交的变化", log_path)
        return 0
    commit = git(
        [
            "commit",
            "-m",
            f"data: 选股雷达每日更新 {dt.datetime.now():%Y-%m-%d %H:%M}",
            "--",
            *relative_files,
        ],
        log_path,
    )
    if commit.returncode != 0:
        log("自动提交失败", log_path)
        return 7
    head = git(["rev-parse", "--short", "HEAD"], log_path)
    log("已提交：" + head.stdout.strip(), log_path)
    if args.no_push:
        log("--no-push：已跳过远端推送", log_path)
        return 0

    pushes = [
        push_with_retry("gitee", "main:main", log_path),
        push_with_retry("gitee", "main:master", log_path),
        push_with_retry("github-ssh", "main:refs/heads/main", log_path),
    ]
    if not all(pushes):
        log("至少一个远端推送失败，请查看日志并重试", log_path)
        return 8
    log("Gitee main/master 与 GitHub main 均已推送", log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
