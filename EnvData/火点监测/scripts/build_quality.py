# -*- coding: utf-8 -*-
"""构建「数据可信度」报告所需的数据：周节律 + 云校正 + 仪器分层摘要。

输出：data/quality-report.json
用法：python build_quality.py
"""
import collections
import datetime as dt
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_data as SD

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def weekly(fires, subset=None):
    c = collections.Counter()
    for f in fires:
        if subset is not None and "%.2f,%.2f" % (f["lat"], f["lng"]) not in subset:
            continue
        c[dt.date.fromisoformat(f["date"]).weekday()] += 1
    n = collections.Counter()
    for k in range(730):
        n[(dt.date(2024, 1, 1) + dt.timedelta(days=k)).weekday()] += 1
    base = [c[i] / n[i] for i in range(7)]
    we = (base[5] + base[6]) / 2
    wd_ = sum(base[:5]) / 5
    return dict(by_day=[round(b, 1) for b in base], ratio=round(we / wd_, 3) if wd_ else 0)


def main():
    fires = SD.load(2024) + SD.load(2025)
    prof = SD.profiles(fires)
    hot = set(k for k, p in prof.items() if p["days"] >= 10)
    straw = set(k for k, p in prof.items() if SD.kind_of(p) == "秸秆焚烧疑似")

    out = dict(weekday=dict(hot=weekly(fires, hot), straw=weekly(fires, straw),
                            all=weekly(fires)))
    # 六省周节律
    n6 = json.load(open(os.path.join(MOD, "data", "north6", "fires-north6.json"), encoding="utf-8"))
    byp = collections.defaultdict(list)
    for f in n6:
        byp[f["province"]].append(f)
    out["prov_weekday"] = {}
    for pv in ["河北", "山西", "山东", "河南", "天津", "北京"]:
        c = collections.Counter()
        for f in byp[pv]:
            c[dt.date.fromisoformat(f["date"]).weekday()] += 1
        n = collections.Counter()
        for k in range(730):
            n[(dt.date(2024, 1, 1) + dt.timedelta(days=k)).weekday()] += 1
        base = [c[i] / n[i] for i in range(7)]
        out["prov_weekday"][pv] = round(((base[5] + base[6]) / 2) / (sum(base[:5]) / 5), 3)

    cc = json.load(open(os.path.join(MOD, "data", "cloud-correction.json"), encoding="utf-8"))
    out["cloud"] = dict(n_low=cc["n_low"], n_days=cc["n_days"], pct=cc["pct"],
                        sync=cc["sync"], top=cc["top"][:8])
    ml = json.load(open(os.path.join(MOD, "data", "modis", "layer-analysis.json"), encoding="utf-8"))
    out["modis"] = ml
    json.dump(out, open(os.path.join(MOD, "data", "quality-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("周节律（周末/工作日）：持续点位 %.2f｜秸秆 %.2f｜全省 %.2f"
          % (out["weekday"]["hot"]["ratio"], out["weekday"]["straw"]["ratio"],
             out["weekday"]["all"]["ratio"]))
    print("六省：", out["prov_weekday"])
    print("云校正：%d/%d 天（%.1f%%）" % (cc["n_low"], cc["n_days"], cc["pct"]))
    print("已写出 data/quality-report.json")


if __name__ == "__main__":
    main()
