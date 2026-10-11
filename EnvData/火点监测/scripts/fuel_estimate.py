# -*- coding: utf-8 -*-
"""用 FRP 估算持续火点的燃料消耗与污染物排放（情景法）。

⚠ 这是一个**量级估算**，不是实测。链条每一环都有不确定性：
   FRP → 燃烧量 → 排放量，任何一环的假设变化都会带来数倍差异。
   本脚本的价值在于把假设**摊开**，给出区间而不是一个"精确数"。

方法：
   1. FRE(MJ) = FRP(MJ/s) × 每天燃烧秒数 × 出现天数
   2. 总热释放 = FRE ÷ 辐射效率 η
   3. 燃料量 = 总热释放 ÷ 燃料热值
   4. 污染物 = 燃料量 × 排放因子（未治理的原始排放）

关键假设与依据：
   · 每天燃烧时长：卫星每天过境 2 次，只能看到瞬间；这里按 4/8/16 h 三档情景
   · 辐射效率 η：明火约 0.2–0.3，闷烧更低；取 0.25 / 0.15 / 0.08 三档
   · 燃料：按煤计（22 MJ/kg）。若实为煤矸石（8–10 MJ/kg），燃料量要 ×2.5 左右
   · 排放因子（煤，未治理）：PM2.5 1.0 / PM10 1.8 / SO2 14 / NOx 5 / CO 25 g/kg

用法：python fuel_estimate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_data as SD

HV_COAL = 22.0          # MJ/kg
EF = [("PM2.5", 1.0), ("PM10", 1.8), ("SO2", 14.0), ("NOx", 5.0), ("CO", 25.0)]  # g/kg
SCEN = [("保守", 4, 0.25), ("中性", 8, 0.15), ("激进", 16, 0.08)]


def calc(pts, hours, eta, hv=HV_COAL):
    fre = sum(p["frp_med"] * hours * 3600 * p["days"] for p in pts)
    heat = fre / eta
    return fre, heat, heat / hv


def main():
    allf = SD.load(2024) + SD.load(2025)
    prof = SD.profiles(allf)
    hot = [p for p in prof.values() if p["days"] >= 10]
    top19 = [p for p in prof.values() if p["days"] >= 200]

    print("点位：≥10 天 %d 个（FRP中位合计 %.1f MW，天数合计 %d）"
          % (len(hot), sum(p["frp_med"] for p in hot), sum(p["days"] for p in hot)))
    print("      ≥200 天 %d 个（FRP中位合计 %.1f MW，天数合计 %d）"
          % (len(top19), sum(p["frp_med"] for p in top19), sum(p["days"] for p in top19)))
    print("\n假设燃料 = 煤（%.0f MJ/kg ≈ 7500 kcal/kg）" % HV_COAL)
    print("%-6s %6s %6s | %10s %12s %14s" % ("情景", "h/天", "η", "辐射能 TJ", "热释放 TJ", "折煤 万吨/年"))
    for nm, h, eta in SCEN:
        fre, heat, kg = calc(hot, h, eta)
        print("%-6s %6d %6.2f | %10.1f %12.1f %14.1f" % (nm, h, eta, fre / 1e6, heat / 1e6, kg / 1e7))

    _, heat, kg = calc(hot, 8, 0.15)
    print("\n=== 中性情景（每天 8 h、η=0.15）：203 个点位折煤 %.1f 万吨/年 ===" % (kg / 1e7))
    for nm, ef in EF:
        print("    %-6s 因子 %5.1f g/kg → %9.1f 吨/年" % (nm, ef, kg * ef / 1e6))

    print("\n=== 对比：同样燃料量，走「有治理」的锅炉会排多少 ===")
    print("    有组织排放（除尘 99%%、脱硫 95%%、脱硝 70%%）:")
    for nm, ef, rm in [("PM2.5", 1.0, 0.99), ("SO2", 14.0, 0.95), ("NOx", 5.0, 0.70)]:
        print("      %-6s %8.1f 吨/年（无治理 %.1f）→ 相差 %.0f 倍"
              % (nm, kg * ef / 1e6 * (1 - rm), kg * ef / 1e6, 1 / (1 - rm)))
    print("    → 同样烧这么多煤，无组织自燃的排放量是达标锅炉的 3–20 倍")

    _, _, kg2 = calc(top19, 8, 0.15)
    print("\n=== 仅 19 个「钉子户」：折煤 %.1f 万吨/年（占 203 点位的 %.0f%%）==="
          % (kg2 / 1e7, kg2 / kg * 100))
    for nm, ef in [("PM2.5", 1.0), ("SO2", 14.0), ("NOx", 5.0)]:
        print("    %-6s %8.1f 吨/年" % (nm, kg2 * ef / 1e6))

    print("\n=== 参照物 ===")
    print("  · 300 MW 燃煤机组年耗煤约 90 万吨 → 203 点位 ≈ %.2f 个机组" % (kg / 1e3 / 900000))
    print("  · 农村家庭冬季取暖年用煤 1.5 吨 → 相当于 %s 户" % format(int(kg / 1e3 / 1.5), ","))
    print("  · 折标准煤（29.3 MJ/kg）：%.1f 万吨标煤/年" % (heat / 29.3 / 1e7))


if __name__ == "__main__":
    main()
