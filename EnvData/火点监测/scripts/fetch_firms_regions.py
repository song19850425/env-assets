# -*- coding: utf-8 -*-
"""拉取全国 FIRMS 火点（2024–2025 两年），按省/市归属，输出「持续排放点位」。

为什么单独一个脚本：
  fetch_firms_north.py 的 bbox 只覆盖山河四省+京津（6 省）。
  本脚本用全国 bbox，覆盖全部 31 个省级行政区，供「多省 + 全国」连续火点地图使用。

输出（都很小，可直接入库）：
  data/regions/china-continuous.json   全国持续点位（两年累计出现 ≥10 天）
  data/regions/summary.json            分省/分市统计

用法：
  FIRMS_MAP_KEY=xxx python fetch_firms_regions.py
  FIRMS_MAP_KEY=xxx python fetch_firms_regions.py 2024-01-01 2025-12-31
"""
import collections
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
GEO = os.path.join(MOD, "geo", "regions")
OUT = os.path.join(MOD, "data", "regions")

BBOX = "73.0,17.0,135.5,54.0"          # 全国（含少量邻国，后面按省界过滤）
SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"]
WIN = 5                                 # FIRMS 单次窗口上限 5 天
MIN_DAYS = 10                           # 持续排放点位判据：两年累计出现 ≥10 天
GAP = 2                                 # 连续判据：相邻火点间隔 ≤2 天
# 只认这些省级单元（geo/regions/ 下的文件名）
PROV_NAMES = {
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
}
API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/%s/%s/%s/%d/%s"


# ---------------- 几何 ----------------
def polys_of(geom):
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return c
    return []


def in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def load_index():
    """返回 (cells, units)：cells[(ilat,ilon)] = [unit_idx,...]，unit = (省, 市, polys, bbox)。"""
    units = []
    for fn in sorted(os.listdir(GEO)):
        if not fn.endswith(".json"):
            continue
        prov = fn[:-5]
        if prov not in PROV_NAMES:      # 防呆：目录里若混入省级/全国级文件，不当成「省」
            print(f"[geo] 跳过非省级文件 {fn}")
            continue
        gj = json.load(open(os.path.join(GEO, fn), encoding="utf-8"))
        for f in gj["features"]:
            city = f["properties"].get("name", "")
            ps = polys_of(f["geometry"])
            xs, ys = [], []
            for p in ps:
                for ring in p:
                    for c in ring:
                        xs.append(c[0]); ys.append(c[1])
            if not xs:
                continue
            units.append((prov, city, ps, (min(xs), min(ys), max(xs), max(ys))))
    # 1°×1° 网格索引，避免对每个点扫全部 340+ 个市
    cells = collections.defaultdict(list)
    for i, (_, _, _, (x0, y0, x1, y1)) in enumerate(units):
        for a in range(int(y0), int(y1) + 1):
            for b in range(int(x0), int(x1) + 1):
                cells[(a, b)].append(i)
    print(f"[geo] 省级单元 {len(units)} 个，网格 {len(cells)} 格")
    return cells, units


def locate(lat, lon, cells, units):
    for i in cells.get((int(lat), int(lon)), ()):
        prov, city, ps, (x0, y0, x1, y1) = units[i]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        for p in ps:
            if in_ring(lon, lat, p[0]):
                if any(in_ring(lon, lat, r) for r in p[1:]):
                    continue
                return prov, city
    return None, None


# ---------------- 抓取 ----------------
def fetch_one(key, src, d0):
    u = API % (key, src, BBOX, WIN, d0.strftime("%Y-%m-%d"))
    for attempt in range(3):
        try:
            r = requests.get(u, timeout=180,
                             headers={"User-Agent": "Mozilla/5.0 (firms-regions)"})
            if r.status_code == 200 and r.text.startswith("latitude"):
                return list(csv.DictReader(io.StringIO(r.text)))
            if r.status_code in (400, 404):
                return []
        except Exception:
            pass
        time.sleep(2 + attempt * 3)
    return []


def segs(dates, gap=GAP):
    ds = sorted(set(dates))
    if not ds:
        return []
    out, s, prev = [], ds[0], ds[0]
    for d in ds[1:]:
        if (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev)).days <= gap:
            prev = d
        else:
            out.append((s, prev))
            s = prev = d
    out.append((s, prev))
    return [(a, b, (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1)
            for a, b in out]


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
    print(f"[firms] 窗口 {len(windows)} × 源 {len(SOURCES)} = "
          f"{len(windows) * len(SOURCES)} 次请求（{start} ~ {end}）", flush=True)

    cells, units = load_index()

    # acc[key] = [mask, night, n, frps, seen, last]
    acc = {}
    got_total = 0
    for src in SOURCES:
        got = 0
        with ThreadPoolExecutor(4) as ex:
            for i, rows in enumerate(ex.map(lambda w: fetch_one(key, src, w), windows)):
                got += len(rows)
                for r in rows:
                    try:
                        lat = float(r["latitude"]); lon = float(r["longitude"])
                    except Exception:
                        continue
                    prov, city = locate(lat, lon, cells, units)
                    if not prov:
                        continue
                    k = "%.2f,%.2f" % (lat, lon)
                    day = r.get("acq_date") or ""
                    if not day:
                        continue
                    try:
                        di = (dt.date.fromisoformat(day) - start).days
                    except Exception:
                        continue
                    if di < 0 or di > 900:
                        continue
                    tm = (r.get("acq_time") or "").zfill(4)
                    e = acc.get(k)
                    if e is None:
                        e = acc[k] = [0, 0, 0, [], set(), (lat, lon, "", "", 0.0, "", "", "", "", prov, city)]
                    if (day, tm) in e[4]:
                        continue
                    e[4].add((day, tm))
                    e[0] |= (1 << di)
                    if (r.get("daynight") or "D").upper().startswith("N"):
                        e[1] += 1
                    e[2] += 1
                    try:
                        e[3].append(float(r.get("frp") or 0))
                    except Exception:
                        e[3].append(0.0)
                    e[5] = (lat, lon, day, tm, float(r.get("frp") or 0),
                            (r.get("confidence") or "").lower()[:1],
                            ("N" if "NPP" in (r.get("satellite") or "") else "N20"),
                            (r.get("daynight") or "D"), prov, city)
                if (i + 1) % 20 == 0:
                    print(f"  {src} {i + 1}/{len(windows)} 窗口，本省归属累计 "
                          f"{len(acc)} 个格点", flush=True)
        got_total += got
        print(f"  {src} 完成：{got} 条", flush=True)

    print(f"[firms] 原始 {got_total} 条；中国境内格点 {len(acc)} 个", flush=True)

    # ---- 聚合出「持续排放点位」 ----
    pts = []
    for k, e in acc.items():
        days = e[0].bit_count()
        if days < MIN_DAYS:
            continue
        dates = []
        m = e[0]
        while m:
            b = (m & -m).bit_length() - 1
            dates.append((start + dt.timedelta(days=b)).isoformat())
            m &= m - 1
        sg = segs(dates)
        a, b, L = max(sg, key=lambda x: x[2])
        frps = sorted(e[3])
        lat, lon, day, tm, frp, conf, sat, dn, prov, city = e[5]
        pts.append({
            "lat": lat, "lng": lon, "date": day, "time": tm,
            "frp": round(frps[len(frps) // 2], 2),
            "conf": conf, "sat": sat,
            "dn": "N" if e[1] / max(e[2], 1) > 0.5 else "D",
            "province": prov, "city": city,
            "cont": L, "days": days, "n": e[2],
            "seg": len(sg), "seg_a": a, "seg_b": b,
            "night": round(e[1] / max(e[2], 1) * 100),
            "months": len(set(x[:7] for x in dates)),
        })
    pts.sort(key=lambda p: (-p["cont"], -p["days"]))
    print(f"[firms] 持续点位（≥{MIN_DAYS} 天）：{len(pts)} 个", flush=True)

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "china-continuous.json")
    json.dump(pts, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"[firms] 已写出 {p}  {os.path.getsize(p) / 1e6:.2f} MB", flush=True)

    # ---- 分省/分市统计 ----
    byp = collections.Counter(x["province"] for x in pts)
    byc = collections.Counter((x["province"], x["city"]) for x in pts)
    summ = {"total": len(pts), "by_province": dict(byp),
            "by_city": {f"{a}|{b}": v for (a, b), v in byc.items()},
            "generated": dt.datetime.now().isoformat(timespec="seconds")}
    json.dump(summ, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n%-8s %6s" % ("省/区", "点位数"))
    for k, v in byp.most_common():
        print("%-8s %6d" % (k, v))


if __name__ == "__main__":
    main()
