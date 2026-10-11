# -*- coding: utf-8 -*-
"""生成六省分类型统计（工业源 / 秸秆 / 其他），供综合分析报告使用。

用法：python build_north6_summary.py
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
HARVEST = ("05", "06", "09", "10")
PROVS = ["河北", "山西", "山东", "河南", "天津", "北京"]


def kind(a):
    d = len(a["days"])
    ntr = len(a["nd"]) / d if d else 0
    if d >= 10:
        return "工业/固定源"
    if d >= 4 and ntr >= 0.6:
        return "偏固定源"
    hr = sum(1 for dt in a["days"] if dt[5:7] in HARVEST) / d if d else 0
    if d <= 2 and hr >= 0.8:
        return "秸秆焚烧疑似"
    if d <= 2:
        return "其他偶发"
    return "待核实"


def main():
    fires = json.load(open(os.path.join(OUT, "fires-north6.json"), encoding="utf-8"))
    out = {}
    for pv in PROVS:
        fs = [f for f in fires if f["province"] == pv]
        acc = collections.defaultdict(lambda: {"days": set(), "n": 0, "nd": set(), "frps": []})
        for f in fs:
            a = acc["%.2f,%.2f" % (f["lat"], f["lng"])]
            a["days"].add(f["date"]); a["n"] += 1; a["frps"].append(f["frp"])
            if f["dn"] == "N":
                a["nd"].add(f["date"])
        kd = {k: kind(a) for k, a in acc.items()}
        byk = collections.Counter()
        for k, v in kd.items():
            byk[v] += acc[k]["n"]
        st_keys = [k for k, v in kd.items() if v == "秸秆焚烧疑似"]
        ind_keys = [k for k, v in kd.items() if v == "工业/固定源"]
        hot = [acc[k] for k in ind_keys]
        mon = collections.Counter()
        for f in fs:
            if "%.2f,%.2f" % (f["lat"], f["lng"]) in set(st_keys):
                mon[f["date"][5:7]] += 1
        out[pv] = dict(
            fire=len(fs), pts=len(acc),
            ind_pts=len(ind_keys), ind_fire=byk["工业/固定源"],
            straw_pts=len(st_keys), straw_fire=byk["秸秆焚烧疑似"],
            other_fire=byk["其他偶发"] + byk["待核实"] + byk["偏固定源"],
            straw_months=dict(sorted(mon.items())),
            hot_night=round(statistics.median([len(a["nd"]) / len(a["days"]) for a in hot]) * 100, 1) if hot else 0,
            hot_frp=round(statistics.median([statistics.median(a["frps"]) for a in hot]), 2) if hot else 0,
            hi=max((len(a["days"]) for a in acc.values()), default=0),
        )
        print("%-4s 火点 %6d｜工业 %6d（%4.1f%%）｜秸秆 %5d（%4.1f%%）｜其他 %6d"
              % (pv, out[pv]["fire"], out[pv]["ind_fire"],
                 out[pv]["ind_fire"] / out[pv]["fire"] * 100,
                 out[pv]["straw_fire"], out[pv]["straw_fire"] / out[pv]["fire"] * 100,
                 out[pv]["other_fire"]))
    json.dump(out, open(os.path.join(OUT, "summary-typed.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写出", os.path.join(OUT, "summary-typed.json"))


if __name__ == "__main__":
    main()
