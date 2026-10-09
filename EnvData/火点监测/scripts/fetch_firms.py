# -*- coding: utf-8 -*-
"""抓取 NASA FIRMS 近实时火点，按河南省各市归属，写出静态 JSON。

用法（本地 / GitHub Actions）：
    FIRMS_MAP_KEY=xxxxxxxx python fetch_firms.py
    （可选）FIRMS_DAYS=1  默认 1 天

输出：
    ../data/fires-henan.json

设计要点：
- 数据源：VIIRS 375m 近实时（Suomi-NPP + NOAA-20），坐标 WGS-84。
- 页面显示时再把 WGS-84 转 GCJ-02（页面已有 wgs2gcj），与高德底图对齐。
- 归属：点落多边形，使用 D:/文献/13-GIS数据/*市_县.geojson（11 市）
        与 河南省_县.geojson（全省县界，用于判断是否在省内）。
- 密钥只从环境变量 FIRMS_MAP_KEY 读，绝不写进代码/仓库。
"""
import csv
import io
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cause  # 同目录：火点成因推测

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE.parent / "data" / "fires-henan.json"

# 河南外扩 bbox（west,south,east,north），覆盖 18 市 + 邻省边缘
BBOX = (110.0, 31.0, 117.0, 36.6)
SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]
DAYS = int(os.environ.get("FIRMS_DAYS", "1"))

_REPO_GEO = HERE.parent / "geo"
GEO_DIR = Path(os.environ.get("HENAN_GEO_DIR",
                             str(_REPO_GEO if _REPO_GEO.exists() else Path(r"D:/文献/13-GIS数据"))))
PROVINCE_GEO = GEO_DIR / "河南省_县.geojson"

FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{bbox}/{days}"


# ---------- 几何：点落多边形（射线法，纯 Python，无依赖）----------
def point_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            xin = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xin:
                inside = not inside
        j = i
    return inside


def point_in_geom(x, y, geom):
    t = geom.get("type")
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return False
    for poly in polys:
        if not poly:
            continue
        if point_in_ring(x, y, poly[0]):
            if not any(point_in_ring(x, y, h) for h in poly[1:]):
                return True
    return False


def load_geojson(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_city_geoms():
    """返回 [(city_name, [geometry,...]), ...]"""
    out = []
    for p in sorted(GEO_DIR.glob("*市_县.geojson")):
        city = p.name.replace("市_县.geojson", "")
        gj = load_geojson(p)
        geoms = [f["geometry"] for f in gj.get("features", [])]
        out.append((city, geoms))
    return out


def load_province_geoms():
    gj = load_geojson(PROVINCE_GEO)
    return [f["geometry"] for f in gj.get("features", [])]


def assign_city(lng, lat, city_geoms, prov_geoms):
    for city, geoms in city_geoms:
        for g in geoms:
            if point_in_geom(lng, lat, g):
                return city
    for g in prov_geoms:
        if point_in_geom(lng, lat, g):
            return "河南·其他市"
    return "省外"


# ---------- 抓取 ----------
def fetch_source(key, src):
    url = FIRMS_AREA.format(key=key, src=src, bbox=",".join(str(v) for v in BBOX), days=DAYS)
    req = urllib.request.Request(url, headers={"User-Agent": "envlab-fire/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    if not text.startswith("latitude"):
        raise RuntimeError("FIRMS 返回异常：%s" % text[:200])
    rows = list(csv.DictReader(io.StringIO(text)))
    fires = []
    for r_ in rows:
        try:
            fires.append({
                "lat": round(float(r_["latitude"]), 5),
                "lng": round(float(r_["longitude"]), 5),
                "frp": round(float(r_["frp"]), 2),
                "conf": r_.get("confidence", ""),
                "sat": r_.get("satellite", ""),
                "date": r_.get("acq_date", ""),
                "time": r_.get("acq_time", ""),
                "dn": r_.get("daynight", ""),
            })
        except (KeyError, ValueError):
            continue
    return fires


def dedupe(fires):
    seen = set()
    out = []
    for f in fires:
        k = (f["lat"], f["lng"], f["date"], f["time"])
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


def main():
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        print("[firms] 缺少环境变量 FIRMS_MAP_KEY", file=sys.stderr)
        sys.exit(2)

    all_fires = []
    for src in SOURCES:
        try:
            got = fetch_source(key, src)
            print("[firms] %s -> %d 条" % (src, len(got)))
            all_fires.extend(got)
        except Exception as e:  # noqa
            print("[firms] %s 失败：%s" % (src, e), file=sys.stderr)

    all_fires = dedupe(all_fires)
    print("[firms] 去重后 %d 条" % len(all_fires))

    city_geoms = load_city_geoms()
    prov_geoms = load_province_geoms()
    print("[firms] 已加载 %d 个市界 + 全省县界" % len(city_geoms))

    # 读上一版（拿历史：各市计数 + 网格复现索引）
    prev = {}
    if OUT_JSON.exists():
        try:
            prev = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")   # 北京时间日期
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=30)).strftime("%Y-%m-%d")

    # 网格复现索引（~1km 取整）：用于成因推测的「固定源」判据
    cells = {k: list(v) for k, v in (prev.get("cells") or {}).items()}

    def cell_key(f):
        return f"{f['lat']:.2f},{f['lng']:.2f}"

    # 用「历史」（不含今日）算复现天数，给每个火点打「成因推测」标签
    for f in all_fires:
        cd = len(set(cells.get(cell_key(f), [])))
        cname, cconf, reasons = cause.classify(f, cd)
        f["cause"], f["cause_conf"], f["reasons"] = cname, cconf, reasons

    # 并入今日并裁剪到近 30 天
    for f in all_fires:
        k = cell_key(f)
        s = set(cells.get(k, [])); s.add(today); cells[k] = sorted(s)
    cells = {k: [d for d in v if d >= cutoff] for k, v in cells.items()}
    cells = {k: v for k, v in cells.items() if v}

    cities = {}
    for f in all_fires:
        c = assign_city(f["lng"], f["lat"], city_geoms, prov_geoms)
        cities.setdefault(c, []).append(f)

    # 各市每日计数历史（供页面日报趋势用），每市保留近 30 天
    history = prev.get("history") or {}
    for c, lst in cities.items():
        if c == "省外":
            continue
        h = [e for e in history.get(c, []) if e.get("date") != today]
        h.append({"date": today, "count": len(lst)})
        history[c] = sorted(h, key=lambda e: e["date"])[-30:]

    payload = {
        "source": "NASA FIRMS VIIRS 375m 近实时 (Suomi-NPP + NOAA-20)",
        "bbox": list(BBOX),
        "days": DAYS,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(all_fires),
        "counts": {k: len(v) for k, v in sorted(cities.items(), key=lambda kv: -len(kv[1]))},
        "cities": cities,
        "history": history,
        "cells": cells,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("[firms] 写出 %s" % OUT_JSON)
    print("[firms] 各市计数：")
    for k, v in payload["counts"].items():
        print("    %-12s %d" % (k, v))
    from collections import Counter
    cc = Counter(f.get("cause") for f in all_fires)
    print("[firms] 成因推测分布：")
    for k, v in cc.most_common():
        print("    %-22s %d" % (k, v))


if __name__ == "__main__":
    main()
