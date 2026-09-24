# -*- coding: utf-8 -*-
"""有限重试跑 gen_sector_map_v3.py：等出口连通窗口，成功且池子完整才停。

规则：
- 最多 8 次尝试，每次间隔 60 秒
- 每次成功写盘后校验：概念 >= 500 且全部含成分；行业 >= 150 且全部含成分
- 校验不过视为本次失败（旧池不会被破坏，因为校验读的是生成结果文件）
- 注意：脚本成功写盘即覆盖 sector_map.json；若校验不过，用 git 恢复池还原
"""
import json
import os
import subprocess
import sys
import time

HOT = r"D:\投研工作台\quant\hotspot"
PY = r"C:\Users\73873\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
OUT = os.path.join(HOT, "sector_map.json")
BACKUP = os.path.join(HOT, "_git_pool_0921.json")  # git 恢复的 09-21 完整池（保底）

def validate(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return False, "读取/解析失败: {}".format(e)
    con = d.get("concept", {})
    ind = d.get("industry", {})
    con_ok = sum(1 for v in con.values() if v)
    ind_ok = sum(1 for v in ind.values() if v)
    ok = (len(con) >= 500 and con_ok == len(con)
          and len(ind) >= 150 and ind_ok == len(ind)
          and d.get("source") == "eastmoney+sw")
    detail = ("source={} 概念 {}/{} 含成分, 行业 {}/{} 含成分".format(
        d.get("source"), con_ok, len(con), ind_ok, len(ind)))
    return ok, detail

# 进场前确保磁盘上是保底池
shutil_ok = True
import shutil
shutil.copyfile(BACKUP, OUT)
print("[进场] 已用 git 恢复的 09-21 完整池作为起点")

for attempt in range(1, 13):
    print("==== 第 {} 次尝试 {}".format(attempt, time.strftime("%H:%M:%S")))
    try:
        p = subprocess.run([PY, os.path.join(HOT, "gen_sector_map_v3.py"),
                            "--out", OUT, "--delay", "0.12"],
                           cwd=HOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        print("  X 本次超 30 分钟被掐断（脚本只在末尾写盘，磁盘未受影响），继续下一轮")
        if attempt < 12:
            time.sleep(30)
        continue
    tail = (p.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("  |", line)
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        print("  X rc={} 最后错误: {}".format(p.returncode, err[-1][:120] if err else "?"))
    else:
        ok, detail = validate(OUT)
        print("  校验:", "PASS" if ok else "FAIL", "-", detail)
        if ok:
            print("[成功] 完整混合源池已生成")
            sys.exit(0)
        # 残缺池落盘了，回滚保底池
        shutil.copyfile(BACKUP, OUT)
        print("  已回滚保底池")
    if attempt < 12:
        print("  等待 300 秒后重试...")
        time.sleep(300)
print("[失败] 12 次尝试均未产出完整池；sector_map.json 保持 09-21 完整旧池")
sys.exit(2)
