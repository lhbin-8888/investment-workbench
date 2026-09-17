# -*- coding: utf-8 -*-
"""运行 V4.4 聚焦验证并把结果写 UTF-8 文件（绕过 shell 输出捕获故障）。"""
import io
import sys
import traceback

sys.path.insert(0, r"D:\投研工作台\quant\hotspot")
import test_v4_mainline as T

buf = io.StringIO()
old = sys.stdout
sys.stdout = buf
rc = 0
try:
    T.main()
    T.test_live_price()
    T.test_date_and_sector_kill()
    T.test_monitor_risk()
    T.test_v44_mainline_filters()
    T.test_v44_trailing()
    if T.fails:
        rc = 1
except Exception:
    traceback.print_exc()
    rc = 2
sys.stdout = old

out = buf.getvalue()
with open(r"D:\投研工作台\quant\hotspot\_v44_result.txt", "w", encoding="utf-8") as f:
    f.write(out)
    f.write("\nFINAL_RC=%d\n" % rc)
    if T.fails:
        f.write("FAILS=%s\n" % T.fails)
    else:
        f.write("ALL_PASS\n")
