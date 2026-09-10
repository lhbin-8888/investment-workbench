# -*- coding: utf-8 -*-
"""
投研工作台 · 临时产物清理脚本
------------------------------
统一清理仓库内的临时/中间产物，保持工作区干净。

清理范围（仅限 D 盘主仓内部，绝不触碰仓库之外的目录）：
  - archive/temp_*        临时目录（脚本中间产物）
  - *.bak*                备份文件
  - __pycache__/ *.pyc    Python 缓存
  - node_modules/         Node 依赖（仅清理主仓根与 tools 下）
  - *.tmp *.part          未完成的下载/写入
  - .DS_Store Thumbs.db   系统垃圾

用法：
  python tools/cleanup-temp.py          # 预览（只列出，不删除）
  python tools/cleanup-temp.py --apply  # 实际删除
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要递归删除的目录名
DIR_NAMES = {"__pycache__", ".pytest_cache", "node_modules", ".ipynb_checkpoints"}
# 需要删除的目录名前缀（位于任意位置）
DIR_PREFIXES = ("temp_",)
# 需要删除的文件后缀 / 文件名
FILE_SUFFIXES = (".pyc", ".pyo", ".tmp", ".part", ".download")
FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def is_temp_dir(name, parent):
    if name in DIR_NAMES:
        return True
    # archive/temp_* 才清，避免误伤正常目录
    if name.startswith(DIR_PREFIXES) and os.path.basename(parent) == "archive":
        return True
    return False


def scan():
    dirs, files = [], []
    for cur, subdirs, filenames in os.walk(ROOT):
        # 跳过版本库与项目数据
        subdirs[:] = [d for d in subdirs if d not in (".git", ".workbuddy")]
        for d in list(subdirs):
            full = os.path.join(cur, d)
            if is_temp_dir(d, cur):
                dirs.append(full)
                subdirs.remove(d)  # 不再进入
        for f in filenames:
            if f in FILE_NAMES or f.endswith(FILE_SUFFIXES) or ".bak" in f.lower():
                files.append(os.path.join(cur, f))
    return dirs, files


def human(path):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    return rel


def main():
    apply = "--apply" in sys.argv
    dirs, files = scan()

    if not dirs and not files:
        print("[OK] 工作区干净，无临时产物")
        return

    print("发现临时产物：" if not apply else "正在清理：")
    for d in dirs:
        size = sum(
            os.path.getsize(os.path.join(r, f))
            for r, _, fs in os.walk(d) for f in fs
        ) if os.path.isdir(d) else 0
        print(f"  [目录] {human(d)}  ({size/1024:.1f} KB)")
    for f in files:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"  [文件] {human(f)}  ({size/1024:.1f} KB)")

    total = len(dirs) + len(files)
    if not apply:
        print(f"\n共 {total} 项。以上为预览，未删除。加 --apply 执行清理。")
        return

    ok = 0
    for d in dirs:
        try:
            shutil.rmtree(d)
            ok += 1
        except OSError as e:
            print(f"  ! 删除失败 {human(d)}: {e}")
    for f in files:
        try:
            os.remove(f)
            ok += 1
        except OSError as e:
            print(f"  ! 删除失败 {human(f)}: {e}")
    print(f"\n[OK] 已清理 {ok}/{total} 项")


if __name__ == "__main__":
    main()
