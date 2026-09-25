# -*- coding: utf-8 -*-
# 生成 sector_map.json —— 山西证券 PTrade 热点策略 V4 用的板块静态池
# 数据源：东方财富 push2delay（行业板块 t:2 + 概念板块 t:3），逐板块取成分股
# 输出 schema（与 hotspot_trader_v4_ptrade.py::load_sector_map 严格一致）：
#   {"industry": {板块名: [6位code,...]}, "concept": {...}, "source":..., "generated_at":...}
import urllib.request, json, ssl, time, os, sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HOST = "push2delay.eastmoney.com"
CTX = ssl.create_default_context(); CTX.set_ciphers("DEFAULT@SECLEVEL=1")
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Accept": "*/*", "Referer": "https://quote.eastmoney.com/"}

def _get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(0.4 * (i + 1))
    raise last

def fetch_board_list(t):
    """返回 {板块代码: 板块名}，分页拉全。
    注意：东方财富板块列表接口单页最多返回 100 条，与 pz 无关，必须逐页翻。"""
    out = {}
    pn = 1
    while True:
        u = ("https://%s/api/qt/clist/get?pn=%d&pz=100&po=1&np=1&fltt=2&invt=2"
             "&fid=f3&fs=m:90+t:%s&fields=f12,f14" % (HOST, pn, t))
        d = json.loads(_get(u))
        diff = (d.get("data") or {}).get("diff") or []
        for x in diff:
            out[x["f12"]] = x["f14"]
        total = (d.get("data") or {}).get("total") or 0
        if not diff or len(out) >= total:
            break
        pn += 1
        time.sleep(0.03)
    return out

def fetch_constituents(board_code):
    """返回该板块成分股 6 位代码列表（去重，分页拉全）。"""
    out, pn = [], 1
    while True:
        u = ("https://%s/api/qt/clist/get?pn=%d&pz=1000&po=1&np=1&fltt=2&invt=2"
             "&fid=f3&fs=b:%s&fields=f12,f14" % (HOST, pn, board_code))
        d = json.loads(_get(u))
        diff = (d.get("data") or {}).get("diff") or []
        for x in diff:
            c = x.get("f12", "")
            if c.isdigit():
                out.append(c)
        if len(diff) < 1000:
            break
        pn += 1
        time.sleep(0.03)
    # 去重保序
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq

def main():
    t0 = time.time()
    print("[1/3] 拉取板块列表 ...")
    ind_boards = fetch_board_list("2")   # 行业板块
    con_boards = fetch_board_list("3")   # 概念板块
    print("      行业板块 %d 个，概念板块 %d 个" % (len(ind_boards), len(con_boards)))

    def build(group, boards, label):
        res = {}
        total = len(boards); done = 0
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(fetch_constituents, bc): nm for bc, nm in boards.items()}
            for f in as_completed(futs):
                nm = futs[f]; done += 1
                try:
                    codes = f.result()
                except Exception as e:
                    codes = []
                    sys.stderr.write("  ! %s 成分失败: %s\n" % (nm, repr(e)[:60]))
                if codes:
                    res[nm] = codes
                if done % 50 == 0:
                    print("      [%s] %d/%d 完成" % (label, done, total))
        return res

    print("[2/3] 并行拉取行业板块成分 ...")
    industry = build("industry", ind_boards, "行业")
    print("[2/3] 并行拉取概念板块成分 ...")
    concept = build("concept", con_boards, "概念")

    # 统计唯一标的数
    allc = set()
    for g in (industry, concept):
        for cs in g.values():
            allc.update(cs)

    payload = {
        "source": "eastmoney-push2delay",
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "行业板块(t:2)+概念板块(t:3)，逐板块取成分股；代码为6位，与策略 _canon 同口径",
        "industry": industry,
        "concept": concept,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_map.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print("[3/3] 写出 %s" % out_path)
    print("      行业板块 %d / 概念板块 %d / 唯一标的 %d / 用时 %.1fs"
          % (len(industry), len(concept), len(allc), time.time() - t0))

if __name__ == "__main__":
    main()
