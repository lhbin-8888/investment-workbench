# -*- coding: utf-8 -*-
"""
用东财 em_kline（板块指数）+ 东财行业资金流，补全概念板块的资金流历史
方法：概念板块在东财有 BK 码与资金流（raw_flow_con.json 仅当日），
      改为按「单日全量概念」逐日拉取 datacenter 接口。
输出：flow_con_full.json {date: {BK: {name, netin, super, big, mid, chg, maxsec}}}
"""
import urllib.request, json, ssl, time, os, urllib.parse
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Referer": "https://data.eastmoney.com/", "Accept": "*/*"}
ROOT = os.path.dirname(os.path.abspath(__file__))
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    raise last


def fetch_day(date):
    """单日全量概念资金流（多页）"""
    cols = ("BOARD_CODE,TRADE_DATE,BOARD_NAME,CHANGE_RATE,NET_INFLOW,"
            "SUPERDEAL_NET,BIGDEAL_NET,MIDDEAL_NET,MAX_NETINFLOW_SEC")
    f = urllib.parse.quote("(TRADE_DATE='%s')" % date)
    rows, pn = [], 1
    while pn <= 12:
        u = (f"{DC}?reportName=RPT_CONCEPT_FUNDFLOW&columns={cols}"
             f"&pageNumber={pn}&pageSize=500&sortColumns=CHANGE_RATE&sortTypes=-1"
             f"&source=WEB&client=WEB&filter={f}")
        try:
            d = _get(u)
        except Exception:
            break
        res = d.get("result") or {}
        data = res.get("data") or []
        if not data:
            break
        rows.extend(data)
        if pn >= (res.get("pages") or 1):
            break
        pn += 1
    return date, rows


def main():
    daily = json.load(open(os.path.join(ROOT, "rebuild_daily.json"), encoding="utf-8"))
    dates = sorted(set(r["date"] for r in daily))
    # YYYYMMDD -> YYYY-MM-DD
    iso = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in dates]
    print(f"待拉 {len(iso)} 个交易日的概念板块资金流…")
    out = {}
    cnt = [0]

    def work(d):
        try:
            dd, rows = fetch_day(d)
        except Exception:
            return
        cnt[0] += 1
        if rows:
            out[dd] = {x["BOARD_CODE"]: {
                "name": x["BOARD_NAME"],
                "chg": x.get("CHANGE_RATE"),
                "netin": (x.get("NET_INFLOW") or 0) / 1e8,
                "super": (x.get("SUPERDEAL_NET") or 0) / 1e8,
                "big": (x.get("BIGDEAL_NET") or 0) / 1e8,
                "mid": (x.get("MIDDEAL_NET") or 0) / 1e8,
                "maxsec": x.get("MAX_NETINFLOW_SEC"),
            } for x in rows}
        if cnt[0] % 10 == 0:
            print(f"  {cnt[0]}/{len(iso)} ok={len(out)}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, iso))
    json.dump(out, open(os.path.join(ROOT, "flow_con_full.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    tot = sum(len(v) for v in out.values())
    print(f"完成 {len(out)}/{len(iso)} 日，概念记录 {tot} 条")


if __name__ == "__main__":
    main()
