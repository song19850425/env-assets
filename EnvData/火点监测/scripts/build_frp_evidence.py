# -*- coding: utf-8 -*-
"""从原始火点数据里提取「燃烧时长」的观测证据，供排放估算使用。

背景：排放估算最大的假设是「每天烧多久」。原估算拍 4/8/16 h 三档，
本文用 VIIRS 的多窗口观测把这个假设钉到数据上。

数据事实（河南 2024-2025，45,540 条）：
  · SNPP 与 NOAA-20 在河南的过境时刻几乎重合（白天 UTC 5.4 / 夜间 UTC 18.2），
    所以「每天 4 次过境」实际只有 2 个有效观测窗口
  · 白天窗口 FRP 存在约 2-3 MW 的探测下限（太阳反射抬高背景噪声）：
    白天 FRP P10 = 1.88 MW，夜间 P10 = 0.56 MW
  · 持续点位 FRP 中位仅 1.1-1.5 MW → 白天基本探测不到
  · 但有 567 个「点-日」昼夜两个窗口都被探测到 → 火在白天确实在烧

推论：这些点位是**全天候燃烧**，「每天燃烧时长」应取接近 24 h，
      原「中性 8 h」低估约 3 倍。

用法：python build_frp_evidence.py
"""
import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_data as SD

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "data", "north6")
DAY_MAX_HOUR = 10          # UTC 小时 < 10 视为白天窗口


def hour(t):
    t = str(t).zfill(4)
    return int(t[:2]) + int(t[2:]) / 60


def main():
    fires = SD.load(2024) + SD.load(2025)
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in fires:
        acc["%.2f,%.2f" % (f["lat"], f["lng"])][f["date"]].append(f)
    prof = SD.profiles(fires)
    hot = [p for p in prof.values() if p["days"] >= 10]

    # 1) 双窗口点-日（铁证：白天也在烧）
    pairs = []
    for p in hot:
        for d, fs in acc[p["key"]].items():
            day = [f for f in fs if hour(f["time"]) < DAY_MAX_HOUR]
            night = [f for f in fs if hour(f["time"]) >= DAY_MAX_HOUR]
            if day and night:
                pairs.append(dict(key=p["key"], date=d,
                                  frp_day=max(f["frp"] for f in day),
                                  frp_night=max(f["frp"] for f in night),
                                  gap=24 - (statistics.mean(hour(f["time"]) for f in night)
                                            - statistics.mean(hour(f["time"]) for f in day))))

    # 2) 探测下限（白天 vs 夜间 FRP 分布）
    def pct(arr, x):
        a = sorted(arr)
        return a[min(len(a) - 1, int(len(a) * x))]

    day_all = [f["frp"] for f in fires if hour(f["time"]) < DAY_MAX_HOUR]
    night_all = [f["frp"] for f in fires if hour(f["time"]) >= DAY_MAX_HOUR]

    # 3) 昼夜看到率（按点位）
    rows = []
    for p in sorted(hot, key=lambda x: -x["days"]):
        k = p["key"]
        D = B = C = 0
        for d, fs in acc[k].items():
            dy = any(hour(f["time"]) < DAY_MAX_HOUR for f in fs)
            nt = any(hour(f["time"]) >= DAY_MAX_HOUR for f in fs)
            if dy and nt:
                C += 1
            elif dy:
                D += 1
            else:
                B += 1
        T = D + B + C
        rows.append(dict(key=k, days=p["days"], day_only=D, night_only=B, both=C,
                         day_rate=round((D + C) / T * 100, 1),
                         night_rate=round((B + C) / T * 100, 1),
                         frp_med=round(p["frp_med"], 2)))

    rec = dict(
        n_fires=len(fires),
        n_hot=len(hot),
        n_top19=sum(1 for p in hot if p["days"] >= 200),
        gap_hours=round(statistics.median([x["gap"] for x in pairs]), 1) if pairs else 0,
        n_pairs=len(pairs),
        pair_frp_day=round(statistics.median([x["frp_day"] for x in pairs]), 2) if pairs else 0,
        pair_frp_night=round(statistics.median([x["frp_night"] for x in pairs]), 2) if pairs else 0,
        detect_floor_day=pct(day_all, 0.10),
        detect_floor_night=pct(night_all, 0.10),
        day_all=dict(n=len(day_all), med=round(statistics.median(day_all), 2),
                     p10=round(pct(day_all, .1), 2), p90=round(pct(day_all, .9), 2),
                     lt3=round(sum(1 for v in day_all if v < 3) / len(day_all) * 100, 1)),
        night_all=dict(n=len(night_all), med=round(statistics.median(night_all), 2),
                       p10=round(pct(night_all, .1), 2), p90=round(pct(night_all, .9), 2),
                       lt3=round(sum(1 for v in night_all if v < 3) / len(night_all) * 100, 1)),
        day_rate=round(sum(r["day_rate"] for r in rows) / len(rows), 1),
        night_rate=round(sum(r["night_rate"] for r in rows) / len(rows), 1),
        hot_frp_med=round(statistics.median([p["frp_med"] for p in hot]), 2),
        top19_frp_med=round(statistics.median([p["frp_med"] for p in hot if p["days"] >= 200]), 2),
    )
    json.dump(rec, open(os.path.join(OUT, "frp-evidence.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for k, v in rec.items():
        print("%-20s %s" % (k, v))
    print("\n已写出", os.path.join(OUT, "frp-evidence.json"))


if __name__ == "__main__":
    main()
