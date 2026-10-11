# -*- coding: utf-8 -*-
"""用 FRP 估算持续火点的燃料消耗与污染物排放（蒙特卡洛 + 观测约束）。

━━ 方法 ━━
   1. FRE(MJ) = FRP(MJ/s) × 每天燃烧秒数 × 出现天数
   2. 总热释放 = FRE ÷ 辐射效率 η
   3. 燃料量 = 总热释放 ÷ 燃料热值 HV
   4. 污染物 = 燃料量 × 排放因子 EF（未治理的原始排放）

━━ 关键改进（v2）：把「每天烧多久」从假设钉到观测 ━━
   v1 里这个参数是拍脑袋的 4/8/16 h。现在用 VIIRS 多窗口观测约束：
   · SNPP 与 NOAA-20 在河南过境时刻几乎重合 → 每天只有 2 个有效观测窗口
     （白天 UTC 5.4 / 夜间 UTC 18.2，相隔 11.4 h）
   · 白天窗口 FRP 有约 2-3 MW 的探测下限（太阳反射抬高背景）：
     白天 P10 = 1.88 MW，夜间 P10 = 0.56 MW
   · 持续点位 FRP 中位仅 1.08 MW（19 钉子户 1.51 MW）→ 白天基本够不到门槛
   · 但 567 个「点-日」昼夜两窗口都被看到 → 火在白天确实在烧
   ⇒ 这些点位是**全天候燃烧**，「每天燃烧时长」应取接近 24 h
     v1 的「中性 8 h」低估约 3 倍。

━━ 仍无法从数据约束的（只能给文献区间）━━
   · 辐射效率 η：明火 0.2-0.3、闷烧更低；取三角分布 0.08-0.30（众数 0.15）
   · 燃料热值：煤 22、煤矸石 9 MJ/kg；取三角分布 9-25（众数 20）
   · 排放因子：不同煤种/燃烧方式差 2-3 倍，逐个给区间

用法：python fuel_estimate.py            # 默认 20000 次抽样
      python fuel_estimate.py 5000
"""
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_data as SD

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "data", "north6")

# ── 参数分布（三角分布：下界, 上界, 众数）──
P_HOURS = (12.0, 24.0, 24.0)      # 每天燃烧时长 h —— 观测支持全天，保守下限 12
P_ETA = (0.08, 0.30, 0.15)        # 辐射效率
P_HV = (9.0, 25.0, 20.0)          # 燃料热值 MJ/kg
# 排放因子 g/kg（煤燃烧，未治理）
EF = {
    "PM2.5": (0.5, 2.0, 1.0),
    "PM10": (1.0, 3.5, 1.8),
    "SO2": (8.0, 20.0, 14.0),
    "NOx": (3.0, 8.0, 5.0),
    "CO": (15.0, 40.0, 25.0),
}
# 达标锅炉的去除率（用于「有治理 vs 无治理」对比）
REMOVAL = {"PM2.5": 0.99, "SO2": 0.95, "NOx": 0.70}


def tri(rng, p):
    return rng.triangular(p[0], p[1], p[2])


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    fires = SD.load(2024) + SD.load(2025)
    prof = SD.profiles(fires)
    hot = [p for p in prof.values() if p["days"] >= 10]
    top19 = [p for p in prof.values() if p["days"] >= 200]

    # 每个点位的「FRP 中位 × 出现天数」之和（单位 MW·天）
    mw_days = sum(p["frp_med"] * p["days"] for p in hot)
    mw_days19 = sum(p["frp_med"] * p["days"] for p in top19)

    rng = random.Random(20261011)
    res = {"all": [], "top19": []}
    for _ in range(n):
        h = tri(rng, P_HOURS)
        eta = tri(rng, P_ETA)
        hv = tri(rng, P_HV)
        for key, mwd in (("all", mw_days), ("top19", mw_days19)):
            # MW·天 × 3600 s/h × h → MJ
            fre = mwd * h * 3600
            heat = fre / eta
            kg = heat / hv
            row = {"coal": kg / 1e7, "heat_tj": heat / 1e6}   # kg → 万吨
            for nm, p in EF.items():
                row[nm] = kg * tri(rng, p) / 1e6      # 吨
            res[key].append(row)

    def q(arr, x):
        a = sorted(arr)
        return a[min(len(a) - 1, int(len(a) * x))]

    print("═" * 78)
    print("点位：≥10 天 %d 个（FRP中位合计 %.1f MW，天数合计 %d）"
          % (len(hot), sum(p["frp_med"] for p in hot), sum(p["days"] for p in hot)))
    print("      ≥200 天 %d 个（FRP中位合计 %.1f MW，天数合计 %d）"
          % (len(top19), sum(p["frp_med"] for p in top19), sum(p["days"] for p in top19)))
    print("抽样 %d 次｜参数：燃烧时长 %.0f-%.0f h、辐射效率 %.2f-%.2f、热值 %.0f-%.0f MJ/kg"
          % (n, P_HOURS[0], P_HOURS[1], P_ETA[0], P_ETA[1], P_HV[0], P_HV[1]))
    print("═" * 78)

    for key, lab in (("all", "203 个持续排放点位"), ("top19", "19 个「钉子户」")):
        print("\n【%s】两年累计" % lab)
        print("%-10s %12s %12s %12s" % ("指标", "P10", "P50（中位）", "P90"))
        coal = [r["coal"] for r in res[key]]
        print("%-10s %12.1f %12.1f %12.1f" % ("折煤 万吨", q(coal, .1), q(coal, .5), q(coal, .9)))
        for nm in EF:
            v = [r[nm] for r in res[key]]
            print("%-10s %12.0f %12.0f %12.0f" % (nm + " 吨", q(v, .1), q(v, .5), q(v, .9)))
        # 无治理 vs 达标锅炉
        print("  ── 同样燃料量走达标锅炉（除尘99%%/脱硫95%%/脱硝70%%）──")
        for nm in ("PM2.5", "SO2", "NOx"):
            v = [r[nm] for r in res[key]]
            med = q(v, .5)
            print("     %-6s 无治理 %8.0f 吨 → 达标 %8.1f 吨（相差 %.0f 倍）"
                  % (nm, med, med * (1 - REMOVAL[nm]), 1 / (1 - REMOVAL[nm])))

    # 参照物（注意：上面所有数字都是「两年累计」，下面同时给年均）
    coal50 = q([r["coal"] for r in res["all"]], .5)
    print("\n【参照物】203 个点位两年折煤 P50 %.1f 万吨（年均 %.1f 万吨）"
          % (coal50, coal50 / 2))
    print("  · 300 MW 燃煤机组年耗煤约 90 万吨 → 相当于 %.2f 个机组·年"
          % (coal50 / 2 / 90))
    print("  · 农村家庭冬季取暖年用煤 1.5 吨 → 相当于 %s 户·年"
          % format(int(coal50 * 10000 / 1.5), ","))

    json.dump({k: _slim(v) for k, v in res.items()},
              open(os.path.join(OUT, "fuel-mc.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写出", os.path.join(OUT, "fuel-mc.json"))


METRICS = ("coal", "heat_tj", "PM2.5", "PM10", "SO2", "NOx", "CO")
QS = (0.10, 0.25, 0.50, 0.75, 0.90)


def _slim(rows):
    """只保留结论：分位数 + 折煤量直方图（原始样本不落盘，可重跑重建）。"""
    def qs(arr):
        a = sorted(arr)
        return [round(a[min(len(a) - 1, int(len(a) * x))], 3) for x in QS]

    coal = sorted(r["coal"] for r in rows)
    lo, hi = coal[0], coal[-1]
    nb = 50
    step = (hi - lo) / nb or 1
    cnt = [0] * nb
    for v in coal:
        cnt[min(nb - 1, int((v - lo) / step))] += 1
    return {"q": {k: qs([r[k] for r in rows]) for k in METRICS},
            "coal_hist": {"lo": round(lo, 2), "hi": round(hi, 2), "counts": cnt}}


if __name__ == "__main__":
    main()
