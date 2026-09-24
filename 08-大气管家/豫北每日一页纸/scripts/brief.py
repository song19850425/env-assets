# -*- coding: utf-8 -*-
"""研判层 V2：把"播报数字"升级为"给出可追溯的判断"。

三条硬规则（本项目对外交付的红线）：
1. 实时口径 ≠ 日均口径。平台 AQI 字段是【当前小时浓度】算出的实时 AQI；
   达标判定必须用 24h 滑动均值/8h 均值对 GB 3095-2012 二级限值，二者不可混用。
2. 城市评价值按 HJ 663-2013 取【点位平均】（先平均浓度、再算 IAQI、取最大），
   不得用"最差点位 AQI"冒充城市 AQI。
3. 所有结论必须挂证据链；无依据不下结论，样本不足就写"待核"。
"""
from collections import defaultdict

# GB 3095-2012 二级限值（浓度判定，非 AQI 判定）
GB3095_2 = {
    "pm25_24h": 75, "pm10_24h": 150, "o3_8h": 160, "no2_24h": 80, "co_24h": 4, "so2_24h": 150,
}

# HJ 633-2012 IAQI 分段：(浓度下限, 浓度上限, IAQI下限, IAQI上限)
IAQI_BP = {
    "pm25": [(0, 35, 0, 50), (35, 75, 50, 100), (75, 115, 100, 150),
             (115, 150, 150, 200), (150, 250, 200, 300), (250, 350, 300, 400), (350, 500, 400, 500)],
    "pm10": [(0, 50, 0, 50), (50, 150, 50, 100), (150, 250, 100, 150),
             (250, 350, 150, 200), (350, 420, 200, 300), (420, 500, 300, 400), (500, 600, 400, 500)],
    "so2": [(0, 50, 0, 50), (50, 150, 50, 100), (150, 475, 100, 150),
            (475, 800, 150, 200), (800, 1600, 200, 300), (1600, 2100, 300, 400), (2100, 2620, 400, 500)],
    "no2": [(0, 40, 0, 50), (40, 80, 50, 100), (80, 180, 100, 150),
            (180, 280, 150, 200), (280, 565, 200, 300), (565, 750, 300, 400), (750, 940, 400, 500)],
    "co": [(0, 2, 0, 50), (2, 4, 50, 100), (4, 14, 100, 150),
           (14, 24, 150, 200), (24, 36, 200, 300), (36, 48, 300, 400), (48, 60, 400, 500)],
    "o3_8h": [(0, 100, 0, 50), (100, 160, 50, 100), (160, 215, 100, 150),
              (215, 265, 150, 200), (265, 800, 200, 300)],
}

# 局地 / 区域判别阈值（可调，写明依据便于复核）
DISPERSION_LOCAL = 1.5   # 同城 PM2.5 实时 max/min ≥ 1.5 → 局地源特征明显
DISPERSION_REGION = 1.25 # 四市 PM2.5 均值 max/min ≤ 1.25 → 区域同步（传输型）
PM_RATIO_DUST = 2.0      # PM10/PM2.5 ≥ 2.0 → 扬尘型特征

# IAQI 键 → 对外显示名
POLL_CN = {"pm25": "PM2.5", "pm10": "PM10", "o3_8h": "O₃-8h",
           "no2": "NO₂", "so2": "SO₂", "co": "CO"}


def iaqi(poll, c):
    """单项 IAQI。c 为浓度，poll 为 IAQI_BP 的键"""
    if c is None or c < 0:
        return None
    for clo, chi, ilo, ihi in IAQI_BP.get(poll, []):
        if c <= chi:
            return round(ilo + (ihi - ilo) * (c - clo) / (chi - clo), 1) if chi > clo else float(ilo)
    return 500.0


def _avg(vals):
    vs = [v for v in vals if v is not None]
    return round(sum(vs) / len(vs), 1) if vs else None


def city_aqi_hj663(rows, daily=False):
    """HJ 663-2013 点位平均法：各污染物取点位平均浓度 → 算 IAQI → 取最大。

    daily=True 时用 24h 滑动均值/8h 值，对应"日均口径"；否则用实时小时值。
    """
    if daily:
        # 只纳入语义明确的"24小时滑动均值"字段。
        # 平台 O3_8h_24h 字段口径待核（不知是"24h 内最大 8h 均值"还是"8h 均值的 24h 平均"），
        # 故本版不用于达标判定，仅作参照值展示。
        conc = {"pm25": _avg([r["pm25_24h"] for r in rows]),
                "pm10": _avg([r["pm10_24h"] for r in rows])}
    else:
        conc = {"pm25": _avg([r["pm25"] for r in rows]),
                "pm10": _avg([r["pm10"] for r in rows]),
                "o3_8h": _avg([r["o3_8h"] for r in rows]),
                "no2": _avg([r["no2"] for r in rows]),
                "so2": _avg([r["so2"] for r in rows]),
                "co": _avg([r["co"] for r in rows])}
    items = [(p, iaqi(p, c), c) for p, c in conc.items()]
    items = [i for i in items if i[1] is not None]
    if not items:
        return None, None, conc
    poll, val, c = max(items, key=lambda i: i[1])
    return val, poll, conc


def daily_exceed(rows):
    """按 GB 3095-2012 二级限值判定点位是否超标（严格口径，供对外引用）

    hits 每项 = (标签, 实测值, 限值, 是否仅筛查)
    ⚠️ O₃ 一项必须区别对待：GB 3095 的 O₃-8h 日均标准（160 μg/m³）评价对象是
    **日最大 8 小时滑动平均**，而平台只提供**当前小时推的 O₃-8h**。
    两者不是同一口径 —— 拿当前值比 160 只能算"筛查信号"，不能写成"该点位当日已超标"。
    因此标签写明"当前值"并置 screen_only=True，页面据此加口径说明。
    """
    out = []
    for r in rows:
        hits = []
        if r["pm25_24h"] is not None and r["pm25_24h"] > GB3095_2["pm25_24h"]:
            hits.append(("PM2.5·24h", r["pm25_24h"], GB3095_2["pm25_24h"], False))
        if r["pm10_24h"] is not None and r["pm10_24h"] > GB3095_2["pm10_24h"]:
            hits.append(("PM10·24h", r["pm10_24h"], GB3095_2["pm10_24h"], False))
        if r["o3_8h"] is not None and r["o3_8h"] > GB3095_2["o3_8h"]:
            hits.append(("O₃-8h（当前值）", r["o3_8h"], GB3095_2["o3_8h"], True))
        if hits:
            out.append({"city": r["city"], "station": r["station_name"], "hits": hits,
                        "screen_only": all(h[3] for h in hits)})
    return out


def city_brief(city, rows):
    """单市研判"""
    valid = [r for r in rows if r["aqi"] is not None]
    worst = max(valid, key=lambda r: r["aqi"]) if valid else None
    aqi_rt, poll_rt, conc_rt = city_aqi_hj663(rows, daily=False)
    aqi_dy, poll_dy, conc_dy = city_aqi_hj663(rows, daily=True)

    pm25 = [r["pm25"] for r in rows if r["pm25"] is not None]
    disp = round(max(pm25) / min(pm25), 2) if len(pm25) > 1 and min(pm25) > 0 else None
    pm_ratio = round(conc_rt["pm10"] / conc_rt["pm25"], 2) if conc_rt.get("pm25") and conc_rt.get("pm10") else None

    ex_rt = [r for r in valid if r["aqi"] > 100]
    ex_dy = [e for e in daily_exceed(rows)]

    return {
        "city": city, "n": len(rows), "worst": worst,
        "aqi_rt": aqi_rt, "poll_rt": poll_rt, "conc_rt": conc_rt,
        "aqi_dy": aqi_dy, "poll_dy": poll_dy, "conc_dy": conc_dy,
        "point_avg_aqi": _avg([r["aqi"] for r in valid]),
        "aqi_max": worst["aqi"] if worst else None,
        "pm25_mean": conc_rt.get("pm25"), "pm25_24h_mean": conc_dy.get("pm25"),
        "pm10_mean": conc_rt.get("pm10"), "pm10_24h_mean": conc_dy.get("pm10"),
        "o3_8h_mean": conc_rt.get("o3_8h"), "o3_8h_max": max((r["o3_8h"] for r in rows if r["o3_8h"] is not None), default=None),
        "no2_mean": conc_rt.get("no2"), "so2_mean": conc_rt.get("so2"), "co_mean": conc_rt.get("co"),
        "pm_ratio": pm_ratio, "dispersion": disp,
        "exceed_rt_cnt": len(ex_rt), "exceed_dy": ex_dy, "exceed_dy_cnt": len(ex_dy),
        "feature": "局地" if (disp or 0) >= DISPERSION_LOCAL else "区域",
        "stations": sorted(rows, key=lambda r: -(r["aqi"] or -1)),
    }


def region_brief(cities):
    """四市区域同步性：均值极差小 → 受同一天气系统影响。

    注意口径边界：区域同步 ≠ 城市间相互传输。同步只能说明四市被同一天气系统覆盖，
    是否构成"输入性传输"必须结合风向与上风向城市浓度另行判定（见 calc/wind.py）。
    """
    means = [(c["city"], c["pm25_mean"]) for c in cities if c["pm25_mean"]]
    if len(means) < 2:
        return {"sync": None, "text": "样本不足，待核"}
    hi = max(means, key=lambda m: m[1])
    lo = min(means, key=lambda m: m[1])
    ratio = round(hi[1] / lo[1], 2) if lo[1] else None
    sync = ratio is not None and ratio <= DISPERSION_REGION
    return {
        "sync": sync, "ratio": ratio, "hi": hi, "lo": lo,
        "text": ("四市 PM2.5 均值极差比 %.2f（≤%.2f），呈**区域同步**特征："
                 "四市受同一天气系统覆盖、同步抬升。需注意区域同步不能直接等同于城市间相互传输，"
                 "传输与否须结合风向与上风向城市浓度另行判定。" % (ratio, DISPERSION_REGION)) if sync else
                ("四市 PM2.5 均值极差比 %.2f（>%.2f），城市间差异明显，"
                 "需按城市分别排查局地源。" % (ratio, DISPERSION_REGION)),
    }


def cause_frame(cities, region):
    """成因研判框架：每条给可自动判别的指标，避免只有框架没有依据"""
    out = []
    for c in cities:
        reasons = []
        if (c["pm_ratio"] or 0) >= PM_RATIO_DUST:
            reasons.append("PM10/PM2.5 比值 %.2f（≥%.1f），颗粒物偏粗，**扬尘/道路与施工尘**特征"
                           % (c["pm_ratio"], PM_RATIO_DUST))
        if c["feature"] == "局地":
            reasons.append("同城 PM2.5 点位极差比 %.2f（≥%.1f），**局地源**特征明显，需查高值站点周边"
                           % (c["dispersion"], DISPERSION_LOCAL))
        else:
            reasons.append("同城 PM2.5 点位极差比 %.2f，点位间较均匀，**区域性**抬升" % (c["dispersion"] or 0))
        if (c["o3_8h_max"] or 0) >= 100:
            reasons.append("O₃-8h 峰值 %s μg/m³，存在**光化学**贡献" % c["o3_8h_max"])
        if (c["co_mean"] or 0) >= 1.0:
            reasons.append("CO 均值 %.2f mg/m³ 偏高，提示**燃烧源**（工业/民用）贡献" % c["co_mean"])
        if (c["no2_mean"] or 0) >= 40:
            reasons.append("NO₂ 均值 %.1f μg/m³ 偏高，提示**机动车/工业**排放" % c["no2_mean"])
        out.append({"city": c["city"], "reasons": reasons,
                    "verdict": ("以 %s 为主" % POLL_CN.get(c["poll_dy"], c["poll_dy"])) if c["poll_dy"] else "待核"})
    return out


def tasks(cities, region):
    """今日重点行动：只在有依据时给动作，并标明依据口径"""
    out = []
    for c in cities:
        acts = []
        if c["exceed_dy_cnt"]:
            names = "、".join(sorted({e["station"] for e in c["exceed_dy"]}))
            acts.append("核实 %s 点位 PM2.5 24h 滑动均值超二级标准（占比 %d/%d），"
                        "优先排查周边燃煤、工业与生物质燃烧源" % (names, c["exceed_dy_cnt"], c["n"]))
        if c["feature"] == "局地":
            acts.append("对同城最高值与最低值点位（极差比 %.2f）开展走航/巡查比对，锁定局地排放" % c["dispersion"])
        if (c["pm_ratio"] or 0) >= PM_RATIO_DUST:
            acts.append("PM10/PM2.5 比值偏高，建议市区加密道路洒水与施工工地覆盖检查")
        if not acts:
            if c["exceed_rt_cnt"] >= max(2, c["n"] // 2):
                acts.append("日均口径各项均达标，但实时 AQI&gt;100 的点位达 %d/%d，"
                            "属静稳累积下的<b>实时高值</b>（非超标），保持关注即可，暂不启动专项响应"
                            % (c["exceed_rt_cnt"], c["n"]))
            else:
                acts.append("实时与日均口径均未见异常，维持常规巡查")
        out.append({"city": c["city"], "acts": acts})
    return out
