# -*- coding: utf-8 -*-
"""
抓取个股日线（新浪源），用于计算各板块的：
  - 涨停家数（近似：涨幅 ≥ 9.8% 视作涨停；创业板/科创板 ≥ 19.8%）
  - 广度：上涨家数占比、涨幅中位数
输入：ths_members.json（成分股清单）
输出：stock_kline.json {code: {date: {"c":..,"pct":..}}}
"""
import urllib.request, json, ssl, time, os
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Referer": "https://finance.sina.com.cn/", "Accept": "*/*"}
ROOT = os.path.dirname(os.path.abspath(__file__))


def _get(url, tries=3, timeout=20):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def mkt(code):
    """6位代码 -> sh/sz/bj 前缀"""
    if code.startswith(("60", "68", "51", "58", "11", "900")):
        return "sh" + code
    if code.startswith(("00", "30", "12", "15", "16", "18", "200")):
        return "sz" + code
    if code.startswith(("43", "83", "87", "88", "92")):
        return "bj" + code
    return "sh" + code


def fetch(code):
    sym = mkt(code)
    u = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
         f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=120")
    try:
        t = _get(u, tries=3, timeout=18)
    except Exception:
        return None
    if not t or not t.strip().startswith("["):
        return None
    try:
        arr = json.loads(t)
    except Exception:
        return None
    out = {}
    prev = None
    for it in arr:
        d = it.get("day")
        try:
            c = float(it["close"])
        except Exception:
            continue
        pct = None
        if prev:
            pct = round((c / prev - 1) * 100, 3)
        out[d] = {"c": c, "pct": pct}
        prev = c
    return out or None


def main():
    t0 = time.time()
    mem = json.load(open(os.path.join(ROOT, "ths_members.json"), encoding="utf-8"))
    stocks = sorted(set(s for v in mem.values() for s in v["stocks"]))
    print(f"待抓 {len(stocks)} 只个股日线…")
    out = {}
    cnt = [0]

    def work(code):
        r = fetch(code)
        cnt[0] += 1
        if r:
            out[code] = r
        if cnt[0] % 200 == 0:
            print(f"  {cnt[0]}/{len(stocks)} ok={len(out)} {time.time()-t0:.0f}s")

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(work, stocks))
    json.dump(out, open(os.path.join(ROOT, "stock_kline.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    need = ["2026-08-03", "2026-10-28"]
    ok = sum(1 for v in out.values() if all(d in v for d in need))
    print(f"完成 {len(out)}/{len(stocks)}，完整覆盖 {ok} 只，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
