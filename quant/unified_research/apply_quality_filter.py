# -*- coding: utf-8 -*-
"""
对已生成的 resonance-picks.json 执行"层4 业绩质量过滤"（纯本地、不联网）。
用途：东财接口临时限流时，用缓存的基本面字段离线重放过滤规则，
     与 resonance_picker.py 的层4 阈值保持一致（MIN_NP_YOY/MIN_REV_YOY/MAX_PE）。
产出：过滤后的 resonance-picks.json + 重写通达信「共振优选」GXYX.blk
"""
import os
import json
import shutil
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT_JSON = os.path.join(DATA, "resonance-picks.json")
BLOCK_DIR = os.path.join(r"D:\TDX", "T0002", "blocknew")
BLK = os.path.join(BLOCK_DIR, "GXYX.blk")

MIN_NP_YOY = -50.0
MIN_REV_YOY = -30.0
MAX_PE = 200.0


def fnum(v):
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def main():
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    rows = d["rows"]
    print(f"过滤前 {len(rows)} 只")
    kept, dropped = [], []
    for r in rows:
        reasons = []
        np_yoy = fnum(r.get("np_yoy"))
        rev_yoy = fnum(r.get("rev_yoy"))
        pe = fnum(r.get("pe"))
        if np_yoy is not None and np_yoy < MIN_NP_YOY:
            reasons.append(f"业绩暴雷(利润同比{np_yoy:.1f}%)")
        if rev_yoy is not None and rev_yoy < MIN_REV_YOY:
            reasons.append(f"主营萎缩(营收同比{rev_yoy:.1f}%)")
        if pe is not None and pe > MAX_PE:
            reasons.append(f"微利高估(PE{pe:.0f})")
        if reasons:
            dropped.append((r, reasons))
            print(f"  ✗ {r['name']}({r['code']}): {'; '.join(reasons)}")
        else:
            kept.append(r)
            print(f"  ✓ {r['name']}({r['code']}) 保留")

    d["rows"] = kept
    d["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if "strategy" in d:
        d["strategy"] = "共振优选(热点定方向+主力资金验真+多因子排雷+业绩质量过滤)"
    json.dump(d, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"过滤后 {len(kept)} 只 → {OUT_JSON}")

    # 重写通达信板块
    if os.path.exists(BLK):
        bdir = os.path.join(BASE, "blk_backup")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(BLK, os.path.join(bdir, f"GXYX_{ts}.blk"))
    content = "".join(("1" if r["market"] == "沪" else "0") + r["code"] + "\r\n" for r in kept)
    tmp = BLK + ".tmp"
    with open(tmp, "w", encoding="gbk", newline="") as f:
        f.write(content)
    os.replace(tmp, BLK)
    print(f"写入「共振优选」板块 {len(kept)} 只 → {BLK}")


if __name__ == "__main__":
    main()
