# -*- coding: utf-8 -*-
"""
东财板块日线（低并发 + 退避重试，避免频控）
secid = 90.BKxxxx（行业/概念通用）
同时抓：
  - 日线 kline（板块指数）
  - 成分股 clist（push2delay，单页100，逐页翻）
输出：em_kline.json {BK: {"name":..,"bars":{date:{o,h,l,c,v,amt,amp}}}}
"""
import urllib.request, json, ssl, time, os, random
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Referer": "https://quote.eastmoney.com/", "Accept": "*/*"}
ROOT = os.path.dirname(os.path.abspath(__file__))
BEG, END = "20260601", "20261110"


def _get(url, tries=6, timeout=25):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1) + random.random() * 0.8)
    raise last


def fetch_kline(bk, beg=BEG, end=END):
    u = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=90.{bk}"
         f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
         f"&klt=101&fqt=1&beg={beg}&end={end}")
    try:
        d = json.loads(_get(u, tries=6))
    except Exception:
        return None
    data = (d.get("data") or {})
    ks = data.get("klines") or []
    if not ks:
        return None
    bars = {}
    for line in ks:
        p = line.split(",")
        try:
            bars[p[0]] = {"o": float(p[1]), "h": float(p[2]), "l": float(p[3]),
                          "c": float(p[4]), "v": float(p[5]), "amt": float(p[6]),
                          "amp": float(p[7])}
        except Exception:
            continue
    return {"name": data.get("name"), "bars": bars} if bars else None


def main():
    t0 = time.time()
    flow = json.load(open(os.path.join(ROOT, "raw_flow_ind.json"), encoding="utf-8"))
    boards = {}
    for x in flow:
        boards[x["BOARD_CODE"]] = x["BOARD_NAME"]
    # 概念板块 BK 码（从 raw_flow_con.json 取）
    try:
        con = json.load(open(os.path.join(ROOT, "raw_flow_con.json"), encoding="utf-8"))
        for x in con:
            boards.setdefault(x["BOARD_CODE"], x["BOARD_NAME"])
    except Exception:
        pass
    codes = list(boards.keys())
    print(f"待抓 {len(codes)} 个东财板块日线（低并发 2）…")
    out = {}
    cnt = [0]

    def work(bk):
        r = fetch_kline(bk)
        cnt[0] += 1
        if r:
            out[bk] = {"name": r["name"] or boards[bk], "bars": r["bars"]}
        if cnt[0] % 20 == 0:
            print(f"  {cnt[0]}/{len(codes)} ok={len(out)} {time.time()-t0:.0f}s")
        time.sleep(0.35)

    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(work, codes))
    json.dump(out, open(os.path.join(ROOT, "em_kline.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    need = ["2026-08-03", "2026-10-28"]
    ok = sum(1 for v in out.values() if all(d in v["bars"] for d in need))
    print(f"完成 {len(out)}/{len(codes)}，完整覆盖 {ok} 个，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
