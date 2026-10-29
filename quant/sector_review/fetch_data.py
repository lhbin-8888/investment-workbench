# -*- coding: utf-8 -*-
"""
板块轮动复盘数据底座抓取器
输出：
  raw_flow_ind.json  行业板块每日涨跌幅+资金流（2026-07-01 ~ 2026-11-10）
  raw_flow_con.json  概念板块同上
  raw_kline.json     全部板块指数日线（push2his，BK代码）
数据源：datacenter-web.eastmoney.com + push2his.eastmoney.com
"""
import urllib.request, urllib.parse, json, ssl, time, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Accept": "*/*", "Referer": "https://data.eastmoney.com/"}
ROOT = os.path.dirname(os.path.abspath(__file__))
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _get(url, tries=5, timeout=30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    raise last


def fetch_flow(report, page_size=500):
    """按日期区间翻页拉全部记录。"""
    cols = ("BOARD_CODE,TRADE_DATE,BOARD_NAME,CHANGE_RATE,NET_INFLOW,"
            "SUPERDEAL_NET,BIGDEAL_NET,MIDDEAL_NET,MAX_NETINFLOW_SEC")
    filt = urllib.parse.quote("(TRADE_DATE>='2026-07-01')(TRADE_DATE<='2026-11-10')")
    rows, pn = [], 1
    while True:
        u = (f"{DC}?reportName={report}&columns={cols}&pageNumber={pn}"
             f"&pageSize={page_size}&sortColumns=TRADE_DATE&sortTypes=-1"
             f"&source=WEB&client=WEB&filter={filt}")
        d = json.loads(_get(u))
        res = d.get("result") or {}
        data = res.get("data") or []
        if not data:
            break
        rows.extend(data)
        if pn >= (res.get("pages") or 1):
            break
        pn += 1
        time.sleep(0.05)
    # 去重（同一 BOARD_CODE+TRADE_DATE）
    seen, out = set(), []
    for x in rows:
        k = (x.get("BOARD_CODE"), x.get("TRADE_DATE"))
        if k in seen:
            continue
        seen.add(k); out.append(x)
    return out


def fetch_kline(bk_code, beg="20260601", end="20261110"):
    """板块指数日线。返回 {date: (open,close,high,low,vol,amount,ampl)}"""
    u = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=90.{bk_code}"
         f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
         f"&klt=101&fqt=1&beg={beg}&end={end}")
    try:
        d = json.loads(_get(u, tries=4, timeout=25))
    except Exception:
        return None
    data = (d.get("data") or {})
    ks = data.get("klines") or []
    if not ks:
        return None
    out = {}
    for line in ks:
        p = line.split(",")
        try:
            out[p[0]] = (float(p[1]), float(p[2]), float(p[3]), float(p[4]),
                         float(p[5]), float(p[6]), float(p[7]))
        except Exception:
            continue
    return out


def main():
    t0 = time.time()
    print("[1/3] 拉行业板块每日资金流...")
    ind = fetch_flow("RPT_INDUSTRY_FUNDFLOW")
    json.dump(ind, open(os.path.join(ROOT, "raw_flow_ind.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"      行业 {len(ind)} 行, {len(set(x['BOARD_CODE'] for x in ind))} 个板块, {time.time()-t0:.1f}s")

    print("[2/3] 拉概念板块每日资金流...")
    t1 = time.time()
    con = fetch_flow("RPT_CONCEPT_FUNDFLOW")
    json.dump(con, open(os.path.join(ROOT, "raw_flow_con.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"      概念 {len(con)} 行, {len(set(x['BOARD_CODE'] for x in con))} 个板块, {time.time()-t1:.1f}s")

    # 板块清单 + 日线
    boards = {}
    for x in ind:
        boards[x["BOARD_CODE"]] = {"name": x["BOARD_NAME"], "type": "industry"}
    for x in con:
        boards.setdefault(x["BOARD_CODE"], {"name": x["BOARD_NAME"], "type": "concept"})
    print(f"[3/3] 拉 {len(boards)} 个板块指数日线...")

    codes = list(boards.keys())
    kl = {}
    done = [0]

    def work(c):
        k = fetch_kline(c)
        if k:
            kl[c] = k
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"      {done[0]}/{len(codes)} (ok={len(kl)}) {time.time()-t0:.0f}s")

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(work, c) for c in codes]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception:
                pass
    json.dump({"boards": boards, "kline": kl},
              open(os.path.join(ROOT, "raw_kline.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"完成：日线 {len(kl)}/{len(codes)} 板块, 总耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
