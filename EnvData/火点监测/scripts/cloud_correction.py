# -*- coding: utf-8 -*-
"""云遮挡校正：量化「未探测日」里有多少是天气造成的观测盲区。

问题：VIIRS 光学遥感在有云时看不到地面火点。一个点位「当天没被探测到」，
我们一直当成「没在烧」——但它可能只是被云挡住了。这会让：
  · 「出现天数」被低估
  · 「连续段」被假中断截短
  · 类型判定（偶发 vs 持续）出错

方法：用「全省日探测数」作天气代理。云是大尺度的，若某天全省火点数
骤降到滚动中位的 30% 以下，判定为「低探测日」（观测盲区）。
并用六省数据交叉验证：天气是区域性的（六省同步），管控是省内的。

输出：data/low_detect_days.json + 控制台报告
用法：python cloud_correction.py
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
THRESH = 0.30          # 当日探测数 < 滚动中位 × 0.30 → 低探测日
WIN = 15               # 滚动窗口 ±15 天


def main():
    fires = SD.load(2024) + SD.load(2025)
    day = collections.Counter(f["date"] for f in fires)
    ds = sorted(day)

    def rollmed(i):
        a, b = max(0, i - WIN), min(len(ds), i + WIN + 1)
        return statistics.median([day[ds[j]] for j in range(a, b)])

    low = []
    for i, d in enumerate(ds):
        m = rollmed(i)
        if m > 0 and day[d] < m * THRESH:
            low.append(dict(date=d, n=day[d], med=round(m, 1), ratio=round(day[d] / m, 3)))

    # 六省同步性验证
    n6 = json.load(open(os.path.join(MOD, "data", "north6", "fires-north6.json"), encoding="utf-8"))
    d6 = collections.defaultdict(collections.Counter)
    for f in n6:
        d6[f["date"]][f["province"]] += 1
    PROV = ["河南", "河北", "山西", "山东"]
    sync = 0
    for r in low:
        c = d6[r["date"]]
        # 其他三省是否也低于各自基线（用全期均值做粗判）
        base = {p: statistics.median([d6[d][p] for d in ds if d in d6]) or 1 for p in PROV}
        if sum(1 for p in PROV[1:] if c[p] < base[p] * THRESH) >= 2:
            sync += 1
    print("低探测日 %d 天 / 共 %d 天 = %.1f%%" % (len(low), len(ds), len(low) / len(ds) * 100))
    print("其中「至少另两省同步偏低」的：%d 天（%.0f%%）→ 支持天气成因"
          % (sync, sync / max(len(low), 1) * 100))
    print("\n最极端的 12 天（河南 + 河北 + 山西 + 山东）：")
    print("%-12s %6s %8s %6s | %6s %6s %6s" % ("日期", "河南", "滚动中位", "比值", "河北", "山西", "山东"))
    for r in sorted(low, key=lambda x: x["ratio"])[:12]:
        c = d6[r["date"]]
        print("%-12s %6d %8.1f %6.2f | %6d %6d %6d"
              % (r["date"], r["n"], r["med"], r["ratio"], c["河北"], c["山西"], c["山东"]))

    # 校正：每个点位的「有效观测天数」
    lows = set(r["date"] for r in low)
    acc = collections.defaultdict(lambda: {"days": set(), "frps": []})
    for f in fires:
        a = acc["%.2f,%.2f" % (f["lat"], f["lng"])]
        a["days"].add(f["date"]); a["frps"].append(f["frp"])

    rows = []
    for k, a in acc.items():
        obs = len(a["days"])
        if obs < 10:
            continue
        d0, d1 = min(a["days"]), max(a["days"])
        span = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days + 1
        blind = sum(1 for d in lows if d0 <= d <= d1)
        eff = span - blind
        rate = obs / eff if eff > 0 else 0
        rows.append(dict(key=k, obs=obs, span=span, blind=blind, eff=eff,
                         rate=round(rate * 100, 1),
                         proj=round(rate * 730)))
    rows.sort(key=lambda r: -r["obs"])
    print("\n=== 校正后：持续点位的「出现率」（前 12）===")
    print("%-14s %6s %8s %6s %8s %8s" % ("点位", "观测天", "活跃期", "盲区天", "有效天", "出现率"))
    for r in rows[:12]:
        print("%-14s %6d %8d %6d %8d %7.1f%%" % (r["key"], r["obs"], r["span"], r["blind"],
                                                  r["eff"], r["rate"]))
    hi = [r for r in rows if r["obs"] >= 200]
    print("\n19 个「钉子户」校正后：出现率中位 %.1f%%（原口径：观测天数/730 = %.1f%%）"
          % (statistics.median([r["rate"] for r in hi]),
             statistics.median([r["obs"] / 730 * 100 for r in hi])))

    out = dict(n_low=len(low), n_days=len(ds), pct=round(len(low) / len(ds) * 100, 1),
               sync=sync, days=[r["date"] for r in low], top=[r for r in rows[:30]])
    json.dump(out, open(os.path.join(MOD, "data", "cloud-correction.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写出 data/cloud-correction.json")


if __name__ == "__main__":
    main()
