# -*- coding: utf-8 -*-
"""综合结论报告的数据核算：把各份报告的关键数字集中算一遍，供 HTML 生成使用。"""
import collections
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify as CL

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
HIST = os.path.join(MOD, "data", "history")


def load(year):
    return json.load(open(os.path.join(HIST, "%d.json" % year), encoding="utf-8"))["fires"]


def profiles(fires_all):
    """跨年点位档案。"""
    acc = collections.defaultdict(lambda: {"days": set(), "nd": set(), "frps": [], "months": set(),
                                           "city": "", "n": 0, "harvest": 0})
    for f in fires_all:
        k = "%.2f,%.2f" % (f["lat"], f["lng"])
        a = acc[k]
        a["days"].add(f["date"]); a["months"].add(f["date"][:7])
        a["frps"].append(float(f["frp"])); a["n"] += 1
        if not a["city"]:
            a["city"] = f["city"]
        if f["dn"] == "N":
            a["nd"].add(f["date"])
        if f["date"][5:7] in ("05", "06", "09", "10"):
            a["harvest"] += 1
    out = {}
    for k, a in acc.items():
        d = len(a["days"]); frps = sorted(a["frps"])
        out[k] = dict(key=k, city=a["city"], days=d, n=a["n"], ndays=len(a["nd"]),
                      night_ratio=len(a["nd"]) / d if d else 0,
                      frp_med=statistics.median(frps), frp_max=max(frps),
                      n_months=len(a["months"]),
                      harvest_ratio=a["harvest"] / a["n"] if a["n"] else 0)
    return out


def kind_of(p):
    """跨年版本的类型判定（沿用 classify 阈值）。"""
    T = CL.THRESHOLDS
    d, ntr = p["days"], p["night_ratio"]
    if d >= T["fixed_high_days"] and ntr >= T["fixed_high_night"]:
        return "工业/固定源"
    if d >= T["fixed_mid_days"]:
        return "工业/固定源"
    if d >= T["lean_days"] and ntr >= T["lean_night"]:
        return "偏固定源"
    if d <= T["once_days"] and p["harvest_ratio"] >= T["harvest_ratio"]:
        return "秸秆焚烧疑似"
    if d <= T["once_days"]:
        return "其他偶发"
    return "待核实"


def dist_km(a, b):
    la = (a[0] - b[0]) * 111.0
    ln = (a[1] - b[1]) * 111.0 * 0.809
    return math.hypot(la, ln)


def main():
    f24, f25 = load(2024), load(2025)
    allf = f24 + f25
    tot = len(allf)
    prof = profiles(allf)
    print("两年火点 %s ｜ 点位 %s" % (format(tot, ","), format(len(prof), ",")))

    print("\n== 按出现天数分层 ==")
    tiers = []
    for th in (10, 30, 100, 200):
        s = [p for p in prof.values() if p["days"] >= th]
        c = sum(p["n"] for p in s)
        tiers.append((th, len(s), c, c / tot * 100))
        print("  ≥%3d 天：%4d 个点位，%6s 条（%.1f%%）" % (th, len(s), format(c, ","), c / tot * 100))

    top19 = sorted([p for p in prof.values() if p["days"] >= 200], key=lambda p: -p["days"])
    print("\n== 19 个「钉子户」（≥200 天）==")
    print("  夜间占比中位 %.0f%%｜FRP 中位 %.2f MW｜FRP 最大中位 %.2f MW｜跨月中位 %.0f"
          % (statistics.median([p["night_ratio"] for p in top19]) * 100,
             statistics.median([p["frp_med"] for p in top19]),
             statistics.median([p["frp_max"] for p in top19]),
             statistics.median([p["n_months"] for p in top19])))
    print("  全部跨月数 ≥ 20 的：%d / 19" % sum(1 for p in top19 if p["n_months"] >= 20))

    kinds = collections.Counter(kind_of(p) for p in prof.values())
    kind_n = collections.Counter()
    for p in prof.values():
        kind_n[kind_of(p)] += p["n"]
    print("\n== 类型构成（跨两年）==")
    for k, v in kinds.most_common():
        print("  %-8s %5d 个点位（%.1f%%）｜%6s 条（%.1f%%）"
              % (k, v, v / len(prof) * 100, format(kind_n[k], ","), kind_n[k] / tot * 100))

    # 秸秆 vs 工业 的空间分离（以安阳为例）
    print("\n== 空间分离（安阳）==")
    ay = [p for p in prof.values() if p["city"] == "安阳"]
    ind = [p for p in ay if kind_of(p) == "工业/固定源"]
    strw = [p for p in ay if kind_of(p) == "秸秆焚烧疑似"]
    print("  安阳：火点 %s 条｜点位 %d｜工业/固定源 %d 个｜秸秆疑似 %d 个"
          % (format(sum(p["n"] for p in ay), ","), len(ay), len(ind), len(strw)))
    if ind and strw:
        ds = []
        for s in strw:
            sl = [float(v) for v in s["key"].split(",")]
            ds.append(min(dist_km(sl, [float(v) for v in i["key"].split(",")]) for i in ind))
        ds.sort()
        print("  秸秆点位→最近工业源距离：中位 %.0f km（p10 %.0f / p90 %.0f）"
              % (statistics.median(ds), ds[int(len(ds) * .1)], ds[int(len(ds) * .9)]))
    print("  工业源：夜间占比中位 %.0f%%｜FRP 中位 %.2f MW"
          % (statistics.median([p["night_ratio"] for p in ind]) * 100,
             statistics.median([p["frp_med"] for p in ind])))
    print("  秸秆：夜间占比中位 %.0f%%｜FRP 中位 %.2f MW｜只出现 1 天的 %.0f%%"
          % (statistics.median([p["night_ratio"] for p in strw]) * 100,
             statistics.median([p["frp_med"] for p in strw]),
             sum(1 for p in strw if p["days"] == 1) / len(strw) * 100))

    # 收获季集中度
    mons = collections.Counter()
    for f in allf:
        if f["city"] == "安阳" and kind_of(prof["%.2f,%.2f" % (f["lat"], f["lng"])]) == "秸秆焚烧疑似":
            mons[f["date"][:7]] += 1
    print("  秸秆火点月份分布：", dict(sorted(mons.items())))

    print("\n== 平顶山 ==")
    pds = [p for p in prof.values() if p["city"] == "平顶山"]
    pind = [p for p in pds if kind_of(p) == "工业/固定源"]
    pstr = [p for p in pds if kind_of(p) == "秸秆焚烧疑似"]
    print("  火点 %s 条｜点位 %d｜工业源 %d 个（%s 条，%.0f%%）｜秸秆 %d 个（%s 条，%.0f%%）"
          % (format(sum(p["n"] for p in pds), ","), len(pds), len(pind),
             format(sum(p["n"] for p in pind), ","),
             sum(p["n"] for p in pind) / sum(p["n"] for p in pds) * 100,
             len(pstr), format(sum(p["n"] for p in pstr), ","),
             sum(p["n"] for p in pstr) / sum(p["n"] for p in pds) * 100))

    print("\n== 内黄县（安阳）==")
    nx = [p for p in prof.values() if p["city"] == "安阳" and 35.95 <= float(p["key"].split(",")[0]) <= 36.10
          and 114.75 <= float(p["key"].split(",")[1]) <= 115.00]
    print("  粗筛（bbox）点位 %d 个，火点 %s 条" % (len(nx), format(sum(p["n"] for p in nx), ",")))
    print("  类型：", collections.Counter(kind_of(p) for p in nx))


if __name__ == "__main__":
    main()
