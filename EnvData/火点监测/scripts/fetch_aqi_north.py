# -*- coding: utf-8 -*-
"""拉取山河四省 + 京津的国控点数据（quotsoft 逐小时归档），按省聚合。

用法：python fetch_aqi_north.py            # 默认冬季 15 天
      python fetch_aqi_north.py 2026-07-01 2026-07-15
"""
import collections, csv, io, json, os, statistics, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
STA = os.path.join(MOD, "data", "stations")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
WANT = {"AQI", "PM2.5", "PM10", "SO2", "NO2", "CO", "O3"}
PROV = {"37": "山东", "14": "山西", "13": "河北", "11": "北京", "12": "天津", "41": "河南"}


def main():
    days = sys.argv[1:] or ["20251215", "20251216", "20251217", "20251218", "20251219",
                            "20260105", "20260106", "20260107", "20260108", "20260109",
                            "20260110", "20260111", "20260112", "20260113", "20260114"]
    nat = json.load(open(os.path.join(STA, "cnemc-national.json"), encoding="utf-8"))
    code2prov = {}
    for s in nat:
        cc = str(s.get("CityCode", ""))
        if len(cc) >= 2 and cc[:2] in PROV:
            code2prov[str(s["StationCode"])] = PROV[cc[:2]]
    print("六省市站点数:", collections.Counter(code2prov.values()))
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    bycity = collections.defaultdict(lambda: collections.defaultdict(list))
    n = 0
    for d in days:
        try:
            r = requests.get("https://quotsoft.net/air/data/china_sites_%s.csv" % d, headers=H, timeout=90)
            if r.status_code != 200:
                print(" miss", d); continue
            rd = csv.reader(io.StringIO(r.content.decode("utf-8", "ignore")))
            head = next(rd)
            idx = {i: code2prov[c] for i, c in enumerate(head) if c in code2prov}
            for row in rd:
                if len(row) < 4 or row[2] not in WANT:
                    continue
                for i, pv in idx.items():
                    if i < len(row) and row[i] and row[i] != "NA":
                        try:
                            acc[pv][row[2]].append(float(row[i]))
                        except ValueError:
                            pass
            n += 1
        except Exception as e:
            print(" err", d, type(e).__name__)
    print("成功", n, "天")
    out = {p: {t: round(statistics.mean(v), 1) for t, v in tv.items() if v} for p, tv in acc.items()}
    p = os.path.join(STA, "aqi-north6.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%-6s %6s %7s %7s %7s %7s %7s" % ("省/市", "AQI", "PM2.5", "PM10", "SO2", "NO2", "O3"))
    for pv in ["北京", "天津", "河北", "山西", "山东", "河南"]:
        v = out.get(pv, {})
        print("%-6s %6.0f %7.0f %7.0f %7.1f %7.0f %7.0f" % (pv, v.get("AQI", 0), v.get("PM2.5", 0),
              v.get("PM10", 0), v.get("SO2", 0), v.get("NO2", 0), v.get("O3", 0)))
    print("已写出", p)


if __name__ == "__main__":
    main()
