# -*- coding: utf-8 -*-
"""
新浪板块全量：板块清单 + 板块指数日线
清单：https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class
      （var S_Finance_bankuai_class，字段: code,name,家数,均价,涨跌额,涨跌幅,成交量,成交额,领涨股代码,领涨股涨跌幅,领涨股价格,领涨股涨跌额,领涨股名）
日线：https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=<code>&scale=240&ma=no&datalen=N
输出：sina_boards.json {code: {"name":..,"n":..,"bars":{date:{c,...}}}}
"""
import urllib.request, json, re, ssl, time, os
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Referer": "https://finance.sina.com.cn/"}
ROOT = os.path.dirname(os.path.abspath(__file__))


def _get(url, tries=4, timeout=25, enc="utf-8"):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode(enc, "ignore")
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def fetch_list():
    h = _get("https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class", enc="gbk")
    m = re.search(r"S_Finance_bankuai_class\s*=\s*(\{.*)", h, re.S)
    if not m:
        raise RuntimeError("未找到 S_Finance_bankuai_class")
    raw = m.group(1)
    # 找到 JSON 对象的结束（右花括号后不是引号/字母）
    depth = 0
    end = None
    in_str = False
    esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end:
        raw = raw[:end]
    out = {}
    # 每条记录形如 "code":"code,name,..." ，用正则逐条抽
    for mm in re.finditer(r'"([^"]+)":"([^"]*)"', raw):
        code, payload = mm.group(1), mm.group(2)
        p = payload.split(",")
        if len(p) < 2:
            continue
        name = p[1]
        try:
            nstock = int(p[2]) if len(p) > 2 and p[2] else 0
        except Exception:
            nstock = 0
        out[code] = {"name": name, "nstock": nstock}
    return out


def fetch_kline(code, datalen=200):
    u = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
         "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d" % (code, datalen))
    try:
        t = _get(u, tries=4, timeout=20)
    except Exception:
        return None
    if not t or not t.strip().startswith("["):
        return None
    try:
        arr = json.loads(t)
    except Exception:
        return None
    bars = {}
    for it in arr:
        try:
            bars[it["day"]] = {"o": float(it["open"]), "h": float(it["high"]),
                               "l": float(it["low"]), "c": float(it["close"]),
                               "v": float(it.get("volume") or 0)}
        except Exception:
            continue
    return bars or None


def main():
    t0 = time.time()
    boards = fetch_list()
    print(f"新浪板块清单 {len(boards)} 个")
    codes = list(boards.keys())
    out = {}
    cnt = [0]

    def work(c):
        bars = fetch_kline(c)
        cnt[0] += 1
        if bars:
            out[c] = {"name": boards[c]["name"], "nstock": boards[c]["nstock"], "bars": bars}
        if cnt[0] % 100 == 0:
            print(f"  {cnt[0]}/{len(codes)} ok={len(out)} {time.time()-t0:.0f}s")

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, codes))
    json.dump(out, open(os.path.join(ROOT, "sina_boards.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    need = ["2026-08-03", "2026-10-28"]
    ok = sum(1 for v in out.values() if all(d in v["bars"] for d in need))
    print(f"完成 {len(out)}/{len(codes)}，完整覆盖8/3~10/28 的 {ok} 个，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
