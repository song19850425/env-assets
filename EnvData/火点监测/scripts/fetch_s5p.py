# -*- coding: utf-8 -*-
"""抓取 Sentinel-5P TROPOMI L3 网格月产品（S5P-PAL，免 key），切出河南范围存小文件。

为什么要切：S5P-PAL 的 L3 产品是**单块存储**（chunk = 整个数据集，且 gzip），
远程 Range 读取无效，必须整文件下载。NO2 全球月产品 1.1 GB、CO 0.4 GB，
不能直接入库 —— 所以下载后只保留河南切片（几十 KB）。

数据源：https://data-portal.s5p-pal.com/api/s5p-l3/collections/<coll>/items
  · no2  0.022° 网格（约 2.4 km），覆盖到 2025-03
  · co   0.044° 网格（约 4.9 km），覆盖到 2025-07
  · 另可用：ch4 / hcho / o3（so2 该平台无产品）

用法：
  python fetch_s5p.py no2 2024-09
  python fetch_s5p.py co 2024-09 2024-10
"""
import json
import os
import sys
import time
import urllib.request

import numpy as np
import h5py
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
WIN = os.path.join(MOD, "_win")
OUT = os.path.join(MOD, "data", "satellite")
BBOX = (31.0, 36.6, 110.0, 117.0)       # 河南及邻域 lat0,lat1,lon0,lon1
VAR = {"no2": "NO2_column_number_density", "co": "CO_column_number_density",
       "ch4": "CH4_column_volume_mixing_ratio_dry_air",
       "hcho": "HCHO_column_number_density", "o3": "O3_column_number_density"}


def find_item(coll, ym):
    y, m = ym.split("-")
    nxt = "%d-%02d" % (int(y) + 1, 1) if int(m) == 12 else "%s-%02d" % (y, int(m) + 1)
    u = ("https://data-portal.s5p-pal.com/api/s5p-l3/collections/%s/items"
         "?datetime=%s-%s-01T00:00:00Z/%s-01T00:00:00Z&limit=30" % (coll, y, m, nxt))
    d = json.loads(urllib.request.urlopen(u, timeout=60).read())
    fs = [x for x in d.get("features", []) if "-month-" in x["id"]]
    if not fs:
        raise SystemExit("该月无 %s 月产品：%s" % (coll, ym))
    a = fs[0]["assets"]["product"]
    return fs[0]["id"], a["href"], int(a.get("file:size", 0))


def download(url, path, size):
    if os.path.exists(path) and os.path.getsize(path) == size:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = time.time()
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(path, "wb") as fh:
            for c in r.iter_content(1024 * 512):
                fh.write(c)
    print("  下载 %.0f MB / %.0fs" % (os.path.getsize(path) / 1e6, time.time() - t))


def extract(nc, var):
    h = h5py.File(nc, "r")
    lat = h["latitude"][:]; lon = h["longitude"][:]
    a, b = np.searchsorted(lat, [BBOX[0], BBOX[1]])
    c, d = np.searchsorted(lon, [BBOX[2], BBOX[3]])
    g = np.array(h[var][0, a:b, c:d], dtype="float64")
    units = str(h[var].attrs.get("units", ""))
    fv = h[var].attrs.get("_FillValue", None)
    h.close()
    if fv is not None:
        g[g == fv] = np.nan
    g[~np.isfinite(g)] = np.nan
    return dict(lat0=float(lat[a]), lon0=float(lon[c]),
                dlat=float(lat[1] - lat[0]), dlon=float(lon[1] - lon[0]),
                ny=int(b - a), nx=int(d - c), units=units,
                grid=[[None if not np.isfinite(v) else round(float(v), 2) for v in row]
                      for row in g])


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    coll = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    for ym in sys.argv[2:]:
        iid, url, size = find_item(coll, ym)
        print("%s %s -> %s (%.0f MB)" % (coll, ym, iid, size / 1e6))
        nc = os.path.join(WIN, "%s-%s.nc" % (coll, ym))
        download(url, nc, size)
        rec = extract(nc, VAR[coll])
        rec.update(coll=coll, ym=ym, item=iid)
        p = os.path.join(OUT, "%s-%s.json" % (coll, ym))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        print("  切出 %dx%d -> %s (%.0f KB)" % (rec["ny"], rec["nx"], os.path.basename(p),
                                                os.path.getsize(p) / 1024))


if __name__ == "__main__":
    main()
