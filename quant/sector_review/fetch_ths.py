# -*- coding: utf-8 -*-
"""
板块指数日线抓取器（同花顺源）
数据源：d.10jqka.com.cn/v6/line/48_<code>/01/last.js
  data 字段格式：日期,开,高,低,收,量,额,?,?,?,?;  以 ; 分隔每日
输出：ths_kline.json  {code: {"name":..., "bars": {date: {o,h,l,c,v,amt}}}}
"""
import urllib.request, json, re, ssl, time, os, sys
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Referer": "https://q.10jqka.com.cn/", "Accept": "*/*"}
ROOT = os.path.dirname(os.path.abspath(__file__))

IND_CODES = list(range(881101, 881201)) + list(range(881263, 881285))
CON_CODES = list(range(885900, 886120))
# 同花顺细分类型/其他段也常见，补充地区、风格段
EXTRA_CODES = list(range(881200, 881280))


def _get(url, tries=4, timeout=20):
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


def fetch(code):
    """返回 (code, name, bars) 或 None"""
    u = "https://d.10jqka.com.cn/v6/line/48_%d/01/last.js" % code
    try:
        t = _get(u)
    except Exception:
        return None
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None
    name = d.get("name")
    raw = d.get("data")
    if not name or not raw:
        return None
    bars = {}
    for line in raw.split(";"):
        p = line.split(",")
        if len(p) < 7:
            continue
        try:
            bars[p[0]] = {"o": float(p[1]), "h": float(p[2]), "l": float(p[3]),
                          "c": float(p[4]), "v": float(p[5]), "amt": float(p[6])}
        except Exception:
            continue
    if not bars:
        return None
    return code, name, bars


def main():
    t0 = time.time()
    allcodes = [(c, "industry") for c in IND_CODES] + [(c, "concept") for c in CON_CODES]
    print(f"待抓 {len(allcodes)} 个板块…")
    out = {}
    cnt = [0]

    def work(item):
        code, typ = item
        r = fetch(code)
        cnt[0] += 1
        if r:
            c, n, bars = r
            out[str(c)] = {"name": n, "type": typ, "bars": bars}
        if cnt[0] % 40 == 0:
            print(f"  {cnt[0]}/{len(allcodes)} ok={len(out)} {time.time()-t0:.0f}s")

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, allcodes))

    json.dump(out, open(os.path.join(ROOT, "ths_kline.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    ind = sum(1 for v in out.values() if v["type"] == "industry")
    con = sum(1 for v in out.values() if v["type"] == "concept")
    # 检查覆盖
    need = ["2026-08-03", "2026-10-28"]
    ok = sum(1 for v in out.values() if all(d in v["bars"] for d in need))
    print(f"完成：{len(out)} 个板块（行业 {ind} / 概念 {con}），"
          f"覆盖 {need[0]}~{need[1]} 的有 {ok} 个，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
