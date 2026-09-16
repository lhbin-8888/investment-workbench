#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投研工作台 · 一键发布到线上（GitHub Pages + Gitee Pages）

流程：
  1. git add -A            —— 仅纳入源码；.gitignore 已排除生成报告/PDF/缓存/.workbuddy
  2. git commit            —— 带时间戳，仅在有改动时提交
  3. 双通道推送 + 远程校验 —— 复用经实战验证的「SSH 优先 / HTTPS 回退 / 推送后比对 SHA」策略

用法：
  python tools/publish_workbench.py
依赖：仅 Python 标准库 + 本机 Git（已配置 gitee / github-ssh 的 SSH 密钥）
"""
import os
import sys
import subprocess
import shutil
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GIT_CANDIDATES = [
    r"C:\Program Files\Git\mingw64\bin\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
]

PAGES_URL = "https://lhbin-8888.github.io/investment-workbench/"


def resolve_git():
    for c in GIT_CANDIDATES:
        if os.path.isfile(c):
            return c
    found = shutil.which("git")
    if found:
        return found
    raise SystemExit("未找到 Git，请安装 Git for Windows 或检查安装路径。")


GIT = resolve_git()


def git(args, timeout=120, capture=True):
    """执行一次 git 命令。只关闭交互式口令提示（绝不设 ASKPASS，否则破坏 SSH 公钥认证）。"""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = [GIT] + list(args)
    try:
        return subprocess.run(cmd, cwd=REPO, env=env,
                              capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        class _R:
            returncode = -1
            stdout = ""
            stderr = "（超时）"
        return _R()


def step(title):
    print("\n" + "=" * 58)
    print("  " + title)
    print("=" * 58)


def short_head():
    return git(["rev-parse", "--short", "HEAD"]).stdout.strip()


def main():
    step("[1/3] 工作区状态预览")
    st = git(["status", "-s"])
    if st.stdout.strip():
        print(st.stdout.rstrip())
    else:
        print("（无改动）")
    print("\n本地 HEAD:", short_head())

    step("[2/3] 暂存并提交")
    git(["add", "-A"])
    diff = git(["diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("无新增暂存内容，跳过提交。")
    else:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = "投研工作台 更新 %s" % ts
        c = git(["commit", "-m", msg])
        if c.returncode == 0:
            tail = (c.stdout or "").strip().splitlines()[-1:] or [""]
            print("已提交：", msg)
            print("  ", tail[0])
        else:
            print("提交失败：")
            print(((c.stderr or c.stdout) or "").strip()[-500:])
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    head7 = head[:7]
    print("当前本地 HEAD:", head7)

    step("[3/3] 双通道推送 + 远程校验")
    results = {}

    # --- Gitee：main->main 与 main->master（两个分支都推，Gitee Pages 可能走 master）---
    for dst in ("main", "master"):
        r = git(["push", "gitee", "main:%s" % dst], timeout=90)
        ok = r.returncode == 0
        results["gitee main->%s" % dst] = ok
        print("  gitee main->%-6s %s" % (dst, "OK" if ok else "失败/超时（不阻断）"))

    # --- GitHub：SSH 优先，失败回退 HTTPS（origin，关闭系统代理）---
    r = git(["push", "github-ssh", "main:refs/heads/main"], timeout=180)
    if r.returncode == 0:
        results["github (SSH)"] = True
        print("  github-ssh        OK（SSH 通道）")
    else:
        print("  github-ssh        失败，回退 HTTPS ...")
        ok = False
        for i in range(3):
            r2 = git(["-c", "http.proxy=", "-c", "http.lowSpeedLimit=0",
                      "-c", "http.lowSpeedTime=999999",
                      "push", "origin", "main:refs/heads/main"], timeout=240)
            if r2.returncode == 0:
                ok = True
                break
            print("    HTTPS 重试 %d/3 ..." % (i + 1))
        results["github (HTTPS回退)"] = ok
        print("  github (HTTPS回退) %s" % ("OK" if ok else "失败"))

    # --- 远程校验：比对各远端 HEAD 与本地 SHA ---
    print("\n  远程校验（本地 %s）：" % head7)
    all_ok = True
    for remote, ref in (("gitee", "main"), ("github-ssh", "refs/heads/main")):
        rr = git(["ls-remote", remote, ref], timeout=40)
        parts = rr.stdout.strip().split()
        rsha = parts[0][:7] if parts else ""
        ok = (rsha == head7)
        all_ok = all_ok and ok
        print("    %-12s %s" % (remote, ("已同步 %s" % rsha) if ok else ("未同步（远程=%s）" % (rsha or "无响应"))))

    step("完成")
    if all_ok:
        print("✅ 已同步到线上。GitHub Pages 通常 1~2 分钟内刷新：")
        print("   " + PAGES_URL)
    else:
        print("⚠️ 部分远程未同步，请检查网络 / SSH 后重试（本脚本可重复运行）。")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
