# -*- coding: utf-8 -*-
"""用 MODIS（低灵敏度）与 VIIRS（高灵敏度）的差异做「明火 / 闷烧」分层。

原理：两个仪器的探测下限差约 10 倍 ——
  MODIS 1km 像元：白天受太阳反射压制，实测 P10 ≈ 5.3 MW，看不到 3 MW 以下的火
  VIIRS 375m  ：夜间 P10 ≈ 0.56 MW，能看到 1 MW 量级的闷烧
所以「被 MODIS 看到」≈ 明火；「只有 VIIRS 看到」≈ 闷烧。
本脚本检验这个分层能不能区分工业源与秸秆点位（若成立即为第 5 个独立判据）。

输出：data/modis/layer-analysis.json
用法：python modis_layer.py
"""
import collections
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_data as SD
import fetch_firms_north as FFN

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
MDIR = os.path.join(MOD, "data", "modis")
HARVEST = ("05", "06", "09", "10")
MATCH_DEG = 0.015          # 匹配半径约 1.6 km（MODIS 定位精度 ~1 km）


def key_of(la, ln):
    return "%.2f,%.2f" % (la, ln)


def main():
    # MODIS
    mod_raw = []
    for y in (2024, 2025):
        p = os.path.join(MDIR, "henan-%d.json" % y)
        if os.path.exists(p):
            mod_raw += json.load(open(p, encoding="utf-8"))
    print("MODIS 河南 bbox 两年：%d 条" % len(mod_raw))
    if not mod_raw:
        raise SystemExit("没有 MODIS 数据，先跑 fetch_firms_modis.py")
    # ⚠ bbox 跨省，必须按省界过滤，否则会混入山西/河北/陕西的火点
    provs = FFN.load_provs()
    mod = [m for m in mod_raw if FFN.province_of(m["lat"], m["lng"], provs) == "河南"]
    print("  其中归属河南：%d 条（剔除省外 %d 条）" % (len(mod), len(mod_raw) - len(mod)))

    frp = sorted(x["frp"] for x in mod if x["frp"] > 0)
    q = lambda a, p: a[min(len(a) - 1, int(len(a) * p))]
    print("  FRP P10 %.1f / 中位 %.1f / P90 %.1f MW｜<3MW 占 %.1f%%"
          % (q(frp, .1), q(frp, .5), q(frp, .9),
             sum(1 for v in frp if v < 3) / len(frp) * 100))
    print("  昼夜：", dict(collections.Counter(x["dn"] for x in mod)))
    print("  卫星：", dict(collections.Counter(x["sat"] for x in mod)))
    print("  时间窗：", dict(collections.Counter(int(str(x["time"]).zfill(4)) // 100
                                                for x in mod)))

    # VIIRS 点位档案
    fires = SD.load(2024) + SD.load(2025)
    acc = collections.defaultdict(lambda: {"dates": set(), "frps": [], "night": set()})
    for f in fires:
        a = acc[key_of(f["lat"], f["lng"])]
        a["dates"].add(f["date"])
        a["frps"].append(f["frp"])
        if f["dn"] == "N":
            a["night"].add(f["date"])

    # MODIS 命中的点位-日
    mod_hit = set()
    mod_keys = set()
    for m in mod:
        if m["frp"] < 3:          # 用 3 MW 门槛，排除边缘弱信号
            continue
        # 就近匹配 VIIRS 点位
        best, bd = None, 9e9
        la0, ln0 = round(m["lat"], 2), round(m["lng"], 2)
        for dla in (-0.02, -0.01, 0.0, 0.01, 0.02):
            for dln in (-0.02, -0.01, 0.0, 0.01, 0.02):
                k = key_of(la0 + dla, ln0 + dln)
                if k not in acc:
                    continue
                kla, kln = [float(v) for v in k.split(",")]
                dist = math.hypot((kla - m["lat"]) * 111, (kln - m["lng"]) * 111 * 0.809)
                if dist < bd:
                    best, bd = k, dist
        if best and bd <= MATCH_DEG * 111:
            mod_hit.add((best, m["date"]))
            mod_keys.add(best)

    # 按类型统计命中率（类型判定沿用既有口径 SD.kind_of）
    prof = SD.profiles(fires)
    grp = collections.defaultdict(lambda: {"pts": 0, "days": 0, "hit_days": 0,
                                           "pts_with_hit": 0, "frp": []})
    for k, a in acc.items():
        p = prof.get(k)
        if not p or p["days"] < 2:
            continue
        d = len(a["dates"])
        kd = SD.kind_of(p)
        g = grp[kd]
        g["pts"] += 1
        g["days"] += d
        hits = sum(1 for dt in a["dates"] if (k, dt) in mod_hit)
        g["hit_days"] += hits
        if hits:
            g["pts_with_hit"] += 1
        g["frp"].append(statistics.median(a["frps"]))

    print("\n=== MODIS 命中率（FRP≥3MW 的 MODIS 火点，匹配半径 1.6 km）===")
    print("%-14s %6s %9s %10s %12s %10s" % ("类型", "点位数", "VIIRS天", "MODIS命中", "命中率", "FRP中位"))
    order = ["工业/固定源", "偏固定源", "待核实", "其他偶发", "秸秆焚烧疑似"]
    out = {}
    for k in order:
        if k not in grp:
            continue
        g = grp[k]
        rate = g["hit_days"] / g["days"] * 100
        pts_rate = g["pts_with_hit"] / g["pts"] * 100
        print("%-14s %6d %9d %10d %11.2f%% %10.2f"
              % (k, g["pts"], g["days"], g["hit_days"], rate, statistics.median(g["frp"])))
        out[k] = dict(pts=g["pts"], days=g["days"], hits=g["hit_days"],
                      rate=round(rate, 3), pts_with_hit=g["pts_with_hit"],
                      pts_rate=round(pts_rate, 1),
                      frp_med=round(statistics.median(g["frp"]), 2))
    print("\n  至少被 MODIS 命中过一次的点位占比：")
    for k in order:
        if k in out:
            print("    %-14s %5.1f%%（%d / %d 个点位）"
                  % (k, out[k]["pts_rate"], out[k]["pts_with_hit"], out[k]["pts"]))

    # MODIS 独有的强火（附近没有 VIIRS 点位）
    lone = [m for m in mod if m["frp"] >= 3
            and key_of(round(m["lat"], 2), round(m["lng"], 2)) not in acc]
    print("\n  MODIS 有、附近无 VIIRS 点位的火点（FRP≥3MW）：%d 条" % len(lone))

    json.dump(dict(n_modis=len(mod), frp_med=round(q(frp, .5), 2),
                   frp_p10=round(q(frp, .1), 2), groups=out),
              open(os.path.join(MDIR, "layer-analysis.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写出 data/modis/layer-analysis.json")


if __name__ == "__main__":
    main()
