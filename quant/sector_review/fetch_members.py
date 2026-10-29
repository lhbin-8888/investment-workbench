# -*- coding: utf-8 -*-
"""
抓取同花顺各板块成分股清单（全量，多排序字段 × 多页 组合去重）
URL: https://q.10jqka.com.cn/{thshy|gn}/detail/field/{fld}/order/{order}/page/{pg}/ajax/1/code/{code}/
输出：ths_members.json
"""
import urllib.request, json, re, ssl, time, os
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context(); CTX.set_ciphers('DEFAULT@SECLEVEL=1')
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
       "Referer": "https://q.10jqka.com.cn/", "Accept": "*/*"}
ROOT = os.path.dirname(os.path.abspath(__file__))

# 同花顺常用排序字段（涨跌幅/换手/量比/市值/市盈率等），组合可覆盖全部成分
FIELDS = [(199112, "desc"), (199112, "asc"), (264648, "desc"), (264648, "asc"),
          (1968584, "desc"), (1968584, "asc"), (1771976, "desc"), (1771976, "asc"),
          (2034120, "desc"), (2034120, "asc")]


def _get(url, tries=2, timeout=15):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("gbk", "ignore")
        except Exception as e:
            last = e
            time.sleep(0.4 * (i + 1))
    raise last


def fetch_members(code, kind):
    base = "thshy" if kind == "industry" else "gn"
    stocks = []
    seen = set()
    for fld, order in FIELDS:
        for pg in range(1, 8):
            u = (f"https://q.10jqka.com.cn/{base}/detail/field/{fld}/order/{order}/"
                 f"page/{pg}/ajax/1/code/{code}/")
            try:
                html = _get(u)
            except Exception:
                break
            rows = re.findall(r"stockpage\.10jqka\.com\.cn/(\d{6})", html)
            uniq = []
            for c in rows:
                if c not in seen and c not in uniq:
                    uniq.append(c)
            if not uniq:
                break
            for c in uniq:
                seen.add(c); stocks.append(c)
            if len(uniq) < 20:
                break
            time.sleep(0.08)
    return code, stocks


def main():
    kl = json.load(open(os.path.join(ROOT, "ths_kline.json"), encoding="utf-8"))
    items = [(int(c), v["type"]) for c, v in kl.items()]
    print(f"待抓 {len(items)} 个板块成分股…")
    out = {}
    cnt = [0]

    def work(it):
        code, typ = it
        c, stocks = fetch_members(code, typ)
        cnt[0] += 1
        if stocks:
            out[str(code)] = {"name": kl[str(code)]["name"], "type": typ, "stocks": stocks}
        if cnt[0] % 30 == 0:
            print(f"  {cnt[0]}/{len(items)} ok={len(out)}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, items))
    json.dump(out, open(os.path.join(ROOT, "ths_members.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    tot = sum(len(v["stocks"]) for v in out.values())
    uniq = len(set(s for v in out.values() for s in v["stocks"]))
    sizes = sorted((len(v["stocks"]), v["name"]) for v in out.values())
    print(f"完成：{len(out)} 个板块，成分股记录 {tot} 条（去重 {uniq} 只）")
    print("最小5:", sizes[:5])
    print("最大5:", sizes[-5:])


if __name__ == "__main__":
    main()
