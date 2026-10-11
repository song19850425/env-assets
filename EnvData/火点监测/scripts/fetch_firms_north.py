# -*- coding: utf-8 -*-
"""拉取山河四省 + 京津的 FIRMS 火点（2024–2025 两年），按省归属。

数据源：NASA FIRMS Area API
  https://firms.modaps.eosdis.nasa.gov/api/area/csv/<KEY>/<SOURCE>/<BBOX>/<DAYS>/<START>
  · DAYS 上限 5 → 两年需 146 次请求/源
  · 用 SP（标准产品）源覆盖历史：VIIRS_SNPP_SP + VIIRS_NOAA20_SP
  · 事务限制 5000 次/10 分钟，本脚本远低于上限

密钥只从环境变量 FIRMS_MAP_KEY 读，绝不写进代码或仓库。

用法：
  FIRMS_MAP_KEY=xxx python fetch_firms_north.py
  FIRMS_MAP_KEY=xxx python fetch_firms_north.py 2024-01-01 2025-12-31
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
GEO = os.path.join(MOD, "geo", "north6")
OUT = os.path.join(MOD, "data", "north6")
BBOX = "110.2,31.4,122.7,42.6"
SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"]
PROVS = ["山东", "山西", "河北", "北京", "天津", "河南"]
WIN = 5
API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/%s/%s/%s/%d/%s"


def rings(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in polys]


def in_ring(x, y, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                inside = not inside
    return inside


def load_provs():
    out = []
    for pv in PROVS:
        d = json.load(open(os.path.join(GEO, "%s.json" % pv), encoding="utf-8"))
        polys, xs, ys = [], [], []
        for f in d["features"]:
            for poly in rings(f["geometry"]):
                polys.append(poly)
                for ring in poly:
                    for x, y in ring:
                        xs.append(x); ys.append(y)
        out.append((pv, polys, (min(ys), max(ys), min(xs), max(xs))))
    return out


def province_of(lat, lon, provs):
    for pv, polys, (y0, y1, x0, x1) in provs:
        if not (y0 <= lat <= y1 and x0 <= lon <= x1):
            continue
        for poly in polys:
            if in_ring(lon, lat, poly[0]):
                hole = False
                for h in poly[1:]:
                    if in_ring(lon, lat, h):
                        hole = True; break
                if not hole:
                    return pv
    return None


def fetch_one(key, src, d0):
    u = API % (key, src, BBOX, WIN, d0.strftime("%Y-%m-%d"))
    for attempt in range(3):
        try:
            r = requests.get(u, timeout=120,
                             headers={"User-Agent": "Mozilla/5.0 (firms-north6)"})
            if r.status_code == 200 and r.text.startswith("latitude"):
                rd = csv.DictReader(io.StringIO(r.text))
                return list(rd)
            if r.status_code in (400, 404):
                return []
        except Exception:
            pass
        time.sleep(2 + attempt * 3)
    return []


def main():
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        raise SystemExit("缺少环境变量 FIRMS_MAP_KEY")
    args = sys.argv[1:]
    start = dt.date.fromisoformat(args[0]) if args else dt.date(2024, 1, 1)
    end = dt.date.fromisoformat(args[1]) if len(args) > 1 else dt.date(2025, 12, 31)

    windows = []
    d = start
    while d <= end:
        windows.append(d)
        d += dt.timedelta(days=WIN)
    print("窗口数 %d × 源 %d = %d 次请求（%s ~ %s）"
          % (len(windows), len(SOURCES), len(windows) * len(SOURCES), start, end))

    rows = []
    for src in SOURCES:
        got = 0
        with ThreadPoolExecutor(4) as ex:
            for i, res in enumerate(ex.map(lambda w: fetch_one(key, src, w), windows)):
                rows += res
                got += len(res)
                if (i + 1) % 20 == 0:
                    print("  %s %d/%d 窗口，累计 %d 条" % (src, i + 1, len(windows), got), flush=True)
        print("  %s 完成：%d 条" % (src, got), flush=True)

    # 去重（同日期/时间/坐标）
    seen = set()
    uniq = []
    for r in rows:
        k = (r.get("acq_date"), r.get("acq_time"), r.get("latitude"), r.get("longitude"))
        if k in seen:
            continue
        seen.add(k); uniq.append(r)
    print("去重后 %d 条（原始 %d）" % (len(uniq), len(rows)))

    provs = load_provs()
    out = []
    skipped = 0
    for r in uniq:
        try:
            lat = float(r["latitude"]); lon = float(r["longitude"])
        except Exception:
            skipped += 1; continue
        pv = province_of(lat, lon, provs)
        if not pv:
            skipped += 1; continue
        out.append(dict(date=r["acq_date"], time=r["acq_time"], lat=lat, lng=lon,
                        frp=float(r.get("frp") or 0), conf=(r.get("confidence") or "").lower()[:1],
                        sat=("N" if "NPP" in (r.get("satellite") or "") or r.get("satellite") == "N" else "N20"),
                        dn=(r.get("daynight") or "D"), province=pv))
    print("归属成功 %d 条，剔除 %d 条（省界外）" % (len(out), skipped))

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "fires-north6.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    print("已写出", p, "%.1f MB" % (os.path.getsize(p) / 1e6))

    import collections
    byp = collections.Counter(f["province"] for f in out)
    bypy = collections.Counter((f["province"], f["date"][:4]) for f in out)
    print("\n%-6s %8s %8s %8s" % ("省/市", "合计", "2024", "2025"))
    for pv in PROVS:
        print("%-6s %8d %8d %8d" % (pv, byp[pv], bypy[(pv, "2024")], bypy[(pv, "2025")]))


if __name__ == "__main__":
    main()
