# -*- coding: utf-8 -*-
"""探针值守：每 120 秒轻量探测东财接口，一通立即触发全量生成+校验+回滚。

- 最多值守 4 小时（120 轮探针）
- 探针用 pz=5 单请求，2~15 秒内出结果，代价极小
- 触发生成后复用 _run_gen_with_retry 的校验/回滚逻辑
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HOT = r"D:\投研工作台\quant\hotspot"
PY = r"C:\Users\73873\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
OUT = os.path.join(HOT, "sector_map.json")
BACKUP = os.path.join(HOT, "_git_pool_0921.json")
GEN = os.path.join(HOT, "gen_sector_map_v3.py")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PROBE_URL = ("https://push2.eastmoney.com/api/qt/clist/get?"
             + urllib.parse.urlencode({
                 "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                 "fid": "f3", "fs": "m:90+t:3+f:!50", "fields": "f12,f13,f14"}))


def probe():
    try:
        req = urllib.request.Request(PROBE_URL, headers={
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/center/boardlist.html"})
        with urllib.request.urlopen(req, timeout=8, context=CTX) as r:
            body = r.read(100)
        return body.startswith(b"{")
    except Exception:
        return False


def validate(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return False, "读取失败: {}".format(e)
    con, ind = d.get("concept", {}), d.get("industry", {})
    con_ok = sum(1 for v in con.values() if v)
    ind_ok = sum(1 for v in ind.values() if v)
    ok = (len(con) >= 500 and con_ok == len(con)
          and len(ind) >= 150 and ind_ok == len(ind)
          and d.get("source") == "eastmoney+sw")
    return ok, "source={} 概念 {}/{} 含成分, 行业 {}/{} 含成分".format(
        d.get("source"), con_ok, len(con), ind_ok, len(ind))


shutil.copyfile(BACKUP, OUT)
print("[进场] {} 保底池就位，开始值守".format(time.strftime("%H:%M:%S")))

for rnd in range(1, 121):
    if probe():
        print("[{:}] 探针通过，触发生成...".format(time.strftime("%H:%M:%S")))
        try:
            p = subprocess.run([PY, GEN, "--out", OUT, "--delay", "0.12"],
                               cwd=HOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=2400)
        except subprocess.TimeoutExpired:
            print("  X 生成超 40 分钟被掐断，回到值守")
            shutil.copyfile(BACKUP, OUT)
            time.sleep(120)
            continue
        tail = (p.stdout or "").strip().splitlines()[-2:]
        for line in tail:
            print("  |", line)
        if p.returncode == 0:
            ok, detail = validate(OUT)
            print("  校验:", "PASS" if ok else "FAIL", "-", detail)
            if ok:
                print("[成功] 完整混合源池已生成，值守结束")
                sys.exit(0)
            shutil.copyfile(BACKUP, OUT)
            print("  已回滚保底池")
        else:
            err = (p.stderr or "").strip().splitlines()
            print("  X 生成失败 rc={} {}".format(
                p.returncode, err[-1][:100] if err else ""))
        # 生成刚失败说明窗口不稳，歇 3 分钟再探
        time.sleep(180)
    else:
        if rnd % 10 == 0:
            print("[{:}] 第 {} 轮探针未通，继续值守".format(
                time.strftime("%H:%M:%S"), rnd))
        time.sleep(120)

print("[结束] 4 小时值守无窗口；sector_map.json 保持保底池")
sys.exit(2)
