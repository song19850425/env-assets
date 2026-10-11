# -*- coding: utf-8 -*-
"""地表判读抽查：对持续排放点位取高分卫星影像，判断落在工业设施还是农田。

为什么用高分影像而不是 Sentinel-2
--------------------------------
S2 是 10 m 分辨率，在「厂区 vs 农田」这种判读上要靠纹理和光谱猜；
而判读结论要拿去支撑「这些点位是工业源」的定性，容错空间很小。
所以这里改用 0.5–2 m 级的高分底图（Esri World Imagery，公开瓦片服务）做**目视抽查**，
S2 只作为补充（若后续需要可加）。

⚠ 边界：目视判读是**定性抽查**，不是逐点位核实的证据链；
正式对外时应配合现场核查或排污许可信息。

用法：
  python landcover_check.py            # 输出 Top15 拼图到 _win/landcover/
"""
import json
import math
import os
import time

import requests
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
WIN = os.path.join(MOD, "_win", "landcover")
CACHE = os.path.join(MOD, "_win", "tiles")
ESRI = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "Chrome/120.0 Safari/537.36"}
Z = 16          # 约 1.9 m/px @36°N
N = 3           # 3x3 瓦片 ≈ 1.48 km 见方


def deg2tile(z, lat, lon):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(math.radians(lat)) +
                            1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def tile_img(z, x, y):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%d_%d_%d.jpg" % (z, x, y))
    if not os.path.exists(p):
        r = requests.get(ESRI.format(z=z, x=x, y=y), headers=H, timeout=40)
        r.raise_for_status()
        with open(p, "wb") as f:
            f.write(r.content)
        time.sleep(0.05)
    return Image.open(p).convert("RGB")


def patch(lat, lon, z=Z, n=N, size=700, mark=True):
    """取以 (lat,lon) 为中心、n×n 瓦片的影像，缩放到 size，中心画十字。"""
    cx, cy = deg2tile(z, lat, lon)
    half = n // 2
    canvas = Image.new("RGB", (n * 256, n * 256))
    for i in range(n):
        for j in range(n):
            canvas.paste(tile_img(z, cx - half + i, cy - half + j), (i * 256, j * 256))
    if mark:
        d = ImageDraw.Draw(canvas)
        c = n * 128
        d.line([(c - 22, c), (c - 6, c)], fill="#ff2d2d", width=3)
        d.line([(c + 6, c), (c + 22, c)], fill="#ff2d2d", width=3)
        d.line([(c, c - 22), (c, c - 6)], fill="#ff2d2d", width=3)
        d.line([(c, c + 6), (c, c + 22)], fill="#ff2d2d", width=3)
    return canvas.resize((size, size), Image.LANCZOS)


def top_hot(n=15, min_days=10):
    """两年火点聚合出的点位，按出现天数降序取前 n。"""
    import collections
    acc = collections.defaultdict(lambda: {"days": set(), "n": 0, "city": "", "frps": []})
    for y in (2024, 2025):
        for f in json.load(open(os.path.join(MOD, "data", "history", "%d.json" % y),
                                encoding="utf-8"))["fires"]:
            k = "%.2f,%.2f" % (f["lat"], f["lng"])
            a = acc[k]
            a["days"].add(f["date"]); a["n"] += 1; a["frps"].append(float(f["frp"]))
            if not a["city"]:
                a["city"] = f["city"]
    rows = []
    for k, a in acc.items():
        if len(a["days"]) < min_days:
            continue
        la, ln = [float(v) for v in k.split(",")]
        frps = sorted(a["frps"])
        rows.append(dict(key=k, lat=la, lon=ln, city=a["city"], days=len(a["days"]),
                         n=a["n"], frp_med=frps[len(frps) // 2]))
    rows.sort(key=lambda r: -r["days"])
    return rows[:n]


def main():
    os.makedirs(WIN, exist_ok=True)
    pts = top_hot(15)
    print("Top%d 点位：" % len(pts))
    CELL = 700
    LABEL = 44
    # 每张 2x2 = 4 个点位
    for gi in range(0, len(pts), 4):
        grp = pts[gi:gi + 4]
        cols = 2
        rows = (len(grp) + cols - 1) // cols
        W = cols * CELL
        Hh = rows * (CELL + LABEL)
        sheet = Image.new("RGB", (W, Hh), (10, 15, 26))
        d = ImageDraw.Draw(sheet)
        for i, p in enumerate(grp):
            r, c = divmod(i, cols)
            img = patch(p["lat"], p["lon"], size=CELL)
            x0 = c * CELL
            y0 = r * (CELL + LABEL)
            sheet.paste(img, (x0, y0))
            txt = "#%d  %s  %s   %d天  FRP中位%.2fMW" % (
                gi + i + 1, p["city"], p["key"], p["days"], p["frp_med"])
            d.rectangle([x0, y0 + CELL, x0 + CELL, y0 + CELL + LABEL], fill=(10, 15, 26))
            d.text((x0 + 8, y0 + CELL + 14), txt, fill=(226, 232, 240))
        out = os.path.join(WIN, "top15_%d.png" % (gi // 4 + 1))
        sheet.save(out)
        print("  写出", os.path.basename(out), sheet.size)
        for i, p in enumerate(grp):
            print("    #%d %s %s %d天" % (gi + i + 1, p["city"], p["key"], p["days"]))


if __name__ == "__main__":
    main()
