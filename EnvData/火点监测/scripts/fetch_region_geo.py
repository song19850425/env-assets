# -*- coding: utf-8 -*-
"""下载 DataV GeoAtlas 的全国省级 + 各省级市级边界，存到 geo/regions/。

用途：火点按「省 → 市」归属，以及地图页运行时 fetch 边界画线。
坐标系已核对：与既有 geo/north6/*.json 同源（WGS-84 系，Δ=0m），
页面 wgs2gcj() 逻辑可直接复用。

用法：python fetch_region_geo.py
"""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)

# 省名 -> adcode（DataV 行政区划代码）
PROVS = {
    "北京": "110000", "天津": "120000", "河北": "130000", "山西": "140000",
    "内蒙古": "150000", "辽宁": "210000", "吉林": "220000", "黑龙江": "230000",
    "上海": "310000", "江苏": "320000", "浙江": "330000", "安徽": "340000",
    "福建": "350000", "江西": "360000", "山东": "370000", "河南": "410000",
    "湖北": "420000", "湖南": "430000", "广东": "440000", "广西": "450000",
    "海南": "460000", "重庆": "500000", "四川": "510000", "贵州": "520000",
    "云南": "530000", "西藏": "540000", "陕西": "610000", "甘肃": "620000",
    "青海": "630000", "宁夏": "640000", "新疆": "650000",
}
URL = "https://geo.datav.aliyun.com/areas_v3/bound/%s_full.json"


def dl(adcode):
    req = urllib.request.Request(URL % adcode, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))


def main():
    outdir = os.path.join(MOD, "geo", "regions")
    os.makedirs(outdir, exist_ok=True)
    for name, code in PROVS.items():
        p = os.path.join(outdir, "%s.json" % name)
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            print(f"[skip] {name}")
            continue
        try:
            gj = dl(code)
            json.dump(gj, open(p, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"[ok] {name}({code}) -> {len(gj['features'])} features")
        except Exception as e:
            print(f"[ERR] {name}({code}): {e}")
    # 全国省级边界（画全国图的省界）
    p = os.path.join(MOD, "geo", "china-provinces.json")
    if not (os.path.exists(p) and os.path.getsize(p) > 1000):
        gj = dl("100000")
        json.dump(gj, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[ok] 全国省级 -> {len(gj['features'])} features")


if __name__ == "__main__":
    main()
