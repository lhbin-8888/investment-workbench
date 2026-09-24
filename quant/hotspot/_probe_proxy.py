# -*- coding: utf-8 -*-
"""诊断：系统代理状态 + 东财/申万 直连 vs 走代理 对比探测"""
import json
import ssl
import urllib.request
import urllib.parse

# 1) 读 Windows 系统代理
try:
    import winreg
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
    def _v(name):
        try:
            v, _ = winreg.QueryValueEx(k, name)
            return v
        except OSError:
            return None
    print("[注册表代理] ProxyEnable =", _v("ProxyEnable"),
          "| ProxyServer =", _v("ProxyServer"),
          "| AutoConfigURL =", _v("AutoConfigURL"))
except Exception as e:
    print("[注册表代理] 读取失败:", e)

# 2) urllib 实际会用到的代理
print("[urllib所见] getproxies() =", urllib.request.getproxies())

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

def probe(name, url, referer, no_proxy):
    if no_proxy:
        # 绕过一切代理（环境变量 + 注册表）
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=CTX))
    else:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=CTX))  # 默认：走系统/环境代理
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer})
    try:
        with opener.open(req, timeout=12) as r:
            body = r.read(200)
        print("[{}] OK -> {}".format(name, body[:120]))
    except Exception as e:
        print("[{}] FAIL -> {}: {}".format(name, type(e).__name__, e))

EM_URL = ("https://push2.eastmoney.com/api/qt/clist/get?"
          + urllib.parse.urlencode({
              "pn": 1, "pz": 5, "po": 1, "np": 1,
              "fltt": 2, "invt": 2, "fid": "f3",
              "fs": "m:90+t:3", "fields": "f12,f13,f14"}))
SW_URL = ("https://www.swsresearch.com/institute-sw/api/index_publish/current/?"
          + urllib.parse.urlencode({"indextype": "一级行业", "page": 1, "page_size": 5}))

for no_proxy in (False, True):
    tag = "直连(绕代理)" if no_proxy else "默认(走系统代理)"
    print("---- {} ----".format(tag))
    probe("东财-push2", EM_URL, "https://quote.eastmoney.com/center/boardlist.html", no_proxy)
    probe("申万-list", SW_URL, "https://www.swsresearch.com/", no_proxy)
