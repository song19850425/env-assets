# -*- coding: utf-8 -*-
"""下载逐月国控数据（quotsoft 逐小时 CSV），按市聚合，用于看季节性。

数据源：https://quotsoft.net/air/data/china_sites_YYYYMMDD.csv
  · 免 key，列名 = 站点编码（与 CNEMC 的 StationCode 一致，可映射到城市）
  · 每天约 660 KB；本脚本每月取 3 天（1/11/21 日）做代表
用法：python fetch_aqi_monthly.py 2025-11 2026-10
"""
import collections
import csv
import io
import json
import os
import statistics
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
STA = os.path.join(MOD, "data", "stations")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
WANT = {"AQI", "PM2.5", "PM10", "SO2", "NO2"}


def month_days(ym):
    y, m = ym.split("-")
    return ["%s%s01" % (y, m), "%s%s11" % (y, m), "%s%s21" % (y, m)]


def main():
    code2city = {str(s["StationCode"]): str(s["Area"])
                 for s in json.load(open(os.path.join(STA, "cnemc-henan.json"), encoding="utf-8"))}
    months = sys.argv[1:] or ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04",
                              "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    out = {}
    for ym in months:
        acc = collections.defaultdict(lambda: collections.defaultdict(list))
        ok = 0
        for d in month_days(ym):
            try:
                r = requests.get("https://quotsoft.net/air/data/china_sites_%s.csv" % d,
                                 headers=H, timeout=90)
                if r.status_code != 200:
                    continue
                rd = csv.reader(io.StringIO(r.content.decode("utf-8", "ignore")))
                head = next(rd)
                idx = {i: code2city[c] for i, c in enumerate(head) if c in code2city}
                for row in rd:
                    if len(row) < 4 or row[2] not in WANT:
                        continue
                    for i, city in idx.items():
                        if i < len(row) and row[i] and row[i] != "NA":
                            try:
                                acc[city][row[2]].append(float(row[i]))
                            except ValueError:
                                pass
                ok += 1
            except Exception as e:
                print("  err", d, type(e).__name__)
        out[ym] = {c: {t: round(statistics.mean(v), 1) for t, v in tv.items() if v}
                   for c, tv in acc.items()}
        print("  %s: %d 天, %d 个市" % (ym, ok, len(acc)))
    p = os.path.join(STA, "aqi-monthly.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写出", p)


if __name__ == "__main__":
    main()
