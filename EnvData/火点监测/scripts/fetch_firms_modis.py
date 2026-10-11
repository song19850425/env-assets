# -*- coding: utf-8 -*-
"""拉取河南 MODIS 火点（2024–2025），用于与 VIIRS 做「明火 / 闷烧」分层。

为什么单独拉 MODIS：
  · MODIS 1km 像元 + 太阳反射 → 探测下限约 5 MW（实测 2024-09 P10 = 5.3 MW）
  · VIIRS 375m → 探测下限约 0.5 MW（夜间 P10 = 0.56 MW）
  · 两者相差约 10 倍，构成天然的「强度分层筛」：
      被 MODIS 看到 → 明火（FRP > 5 MW）
      只有 VIIRS 看到 → 闷烧（FRP < 5 MW）
  · 同时 Terra 的 10:30 / 22:30 过境是 VIIRS 没有的时段

⚠ 注意：MODIS 不能用来「补 VIIRS 的观测盲区」——它看不到 1 MW 量级的火。
   补盲要靠云掩膜校正，不是靠加低灵敏度仪器。

输出：data/modis/henan-<年>.json
用法：FIRMS_MAP_KEY=xxx python fetch_firms_modis.py [2024 2025]
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
OUT = os.path.join(MOD, "data", "modis")
BBOX = "110.0,31.0,117.0,36.6"
SOURCE = "MODIS_SP"
WIN = 5
API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/%s/%s/%s/%d/%s"


def windows(start, end):
    d = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    out = []
    while d <= e:
        out.append(d.isoformat())
        d += dt.timedelta(days=WIN)
    return out


def fetch_one(args):
    key, d0 = args
    url = API % (key, SOURCE, BBOX, WIN, d0)
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (firms-modis)"}, timeout=120)
            if r.status_code != 200:
                time.sleep(2)
                continue
            return list(csv.DictReader(io.StringIO(r.text)))
        except Exception:
            time.sleep(2)
    return []


def main():
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        raise SystemExit("缺少环境变量 FIRMS_MAP_KEY")
    years = [int(x) for x in sys.argv[1:]] or [2024, 2025]
    os.makedirs(OUT, exist_ok=True)
    for y in years:
        wins = windows("%d-01-01" % y, "%d-12-31" % y)
        print("%d: %d 个窗口" % (y, len(wins)), flush=True)
        t = time.time()
        rows = []
        with ThreadPoolExecutor(4) as ex:
            for i, batch in enumerate(ex.map(fetch_one, [(key, d) for d in wins]), 1):
                rows += batch
                if i % 20 == 0:
                    print("  %d/%d  %.0fs" % (i, len(wins), time.time() - t), flush=True)
        seen, out = set(), []
        for r in rows:
            if not str(r.get("acq_date", "")).startswith(str(y)):
                continue
            k = (r.get("acq_date"), r.get("acq_time"), r.get("latitude"), r.get("longitude"))
            if k in seen:
                continue
            seen.add(k)
            try:
                out.append(dict(date=r["acq_date"], time=r["acq_time"],
                                lat=float(r["latitude"]), lng=float(r["longitude"]),
                                frp=float(r.get("frp") or 0),
                                conf=int(float(r.get("confidence") or 0)),
                                sat=r.get("satellite", ""),
                                dn=(r.get("daynight") or "D")))
            except (ValueError, KeyError):
                pass
        p = os.path.join(OUT, "henan-%d.json" % y)
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        print("  -> %d 条（去重后） %.0fs  写出 %s" % (len(out), time.time() - t, os.path.basename(p)))


if __name__ == "__main__":
    main()
