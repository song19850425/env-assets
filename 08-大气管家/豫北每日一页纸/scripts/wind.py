# -*- coding: utf-8 -*-
"""气象研判层：把风向风速变成"污染从哪来、能不能散"的判断。

重要约定：
  - 气象风向 = 风的【来向】。风向 160° 表示风从南偏东吹来，上风向即 160° 方位。
  - 上风向判定用「同组城市方位角 vs 风向夹角 ≤ HALF_WIDTH」，
    因此结论仅在已纳入的城市池内成立；未纳入的省外城市会造成盲区，页面须声明。
  - 阈值均为【经验阈值】，非国家标准限值，页面须标注，不得当作合规判据。
"""
import math

# 经验阈值（非标准限值）
WIND_CALM = 2.0        # m/s 以下判静稳
WIND_GOOD = 3.5        # m/s 以上判扩散有利
BLH_LOW = 300.0        # m 以下垂直扩散严重受限
BLH_FAIR = 800.0       # m 以下受限
RH_HIGH = 80.0         # % 以上配合低风速判高湿静稳
HALF_WIDTH = 45.0      # 上风向扇形半角（度）
TRANSPORT_GAP = 1.15   # 上风向城市 PM2.5 高出目标城市 15% 以上才提示可能输入

COMPASS = ["北", "北东北", "东北", "东东北", "东", "东东南", "东南", "南东南",
           "南", "南西南", "西南", "西西南", "西", "西西北", "西北", "北西北"]


def compass(deg):
    """方位角 → 中文方位（16 方位）"""
    if deg is None:
        return "—"
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def bearing(lat1, lon1, lat2, lon2):
    """从点1指向点2的方位角（0=正北，顺时针）"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff(a, b):
    """两方位角最小夹角（0–180）"""
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def upwind_cities(target, wind_dir, coords, half_width=HALF_WIDTH):
    """目标城市的【上风向】其他城市（按与风向夹角升序）"""
    if wind_dir is None or target not in coords:
        return []
    la1, lo1 = coords[target]
    out = []
    for city, (la2, lo2) in coords.items():
        if city == target:
            continue
        b = bearing(la1, lo1, la2, lo2)
        d = angle_diff(b, wind_dir)
        if d <= half_width:
            out.append({"city": city, "bearing": round(b, 1),
                        "compass": compass(b), "diff": round(d, 1)})
    return sorted(out, key=lambda x: x["diff"])


def stability(wind_speed, blh):
    """扩散条件分级：返回 (等级, 说明)"""
    if wind_speed is None and blh is None:
        return ("待核", "气象数据缺失")
    parts = []
    bad = 0
    if wind_speed is not None:
        if wind_speed < WIND_CALM:
            parts.append("地面风速 %.1f m/s，低于 %.1f m/s，水平输送弱" % (wind_speed, WIND_CALM))
            bad += 2
        elif wind_speed < WIND_GOOD:
            parts.append("地面风速 %.1f m/s，水平输送一般" % wind_speed)
            bad += 1
        else:
            parts.append("地面风速 %.1f m/s，水平输送较有利" % wind_speed)
    if blh is not None:
        if blh < BLH_LOW:
            parts.append("边界层高度仅 %.0f m，垂直扩散严重受限" % blh)
            bad += 2
        elif blh < BLH_FAIR:
            parts.append("边界层高度 %.0f m，垂直扩散受限" % blh)
            bad += 1
        else:
            parts.append("边界层高度 %.0f m，垂直扩散空间较充足" % blh)
    level = ("不利" if bad >= 3 else "较不利" if bad == 2 else "一般" if bad == 1 else "有利")
    return (level, "；".join(parts))


def transport(target, wind_dir, coords, air_by_city):
    """区域传输研判。air_by_city: {city: {"pm25_mean":..., "aqi_rt":...}}"""
    ups = upwind_cities(target, wind_dir, coords)
    tgt = air_by_city.get(target, {})
    t_pm = tgt.get("pm25_mean")
    lines, verdict = [], "待核"
    if not ups:
        if wind_dir is None:
            return {"ups": [], "verdict": "待核（无风向）", "lines": ["缺少风向数据，无法判定上风向。"]}
        return {"ups": [], "verdict": "无同组上风向城市",
                "lines": ["风向 %s，上风向扇形（±%.0f°）内无已纳入的城市，"
                          "存在省外传输盲区，需扩充周边城市后方可判定。"
                          % (compass(wind_dir), HALF_WIDTH)]}
    names = "、".join("%s（%s，方位 %s，夹角 %.0f°）" % (u["city"], u["compass"], u["bearing"], u["diff"])
                     for u in ups)
    lines.append("主导风向为 %s（%.0f°），上风向已纳入城市：%s。" % (compass(wind_dir), wind_dir, names))
    if t_pm is None:
        return {"ups": ups, "verdict": "待核", "lines": lines + ["目标城市 PM2.5 缺失。"]}
    stronger = [(u, air_by_city.get(u["city"], {}).get("pm25_mean")) for u in ups]
    hi = [(u, v) for u, v in stronger if v and v > t_pm * TRANSPORT_GAP]
    lo = [(u, v) for u, v in stronger if v is not None]
    if hi:
        u, v = max(hi, key=lambda x: x[1])
        verdict = "存在输入性传输迹象"
        lines.append("上风向 %s PM2.5 均值 %.1f μg/m³ 高于本地 %.1f μg/m³（超 %.0f%%），"
                     "提示存在**输入性传输**贡献，需结合轨迹模型或省外上风向城市进一步确认。"
                     % (u["city"], v, t_pm, (v / t_pm - 1) * 100))
    else:
        verdict = "输入性传输证据不足"
        detail = "；".join("%s %.1f" % (u["city"], v) for u, v in lo if v is not None)
        lines.append("上风向城市 PM2.5（%s）均不高于本地 %.1f μg/m³，"
                     "**不支持**输入性传输为主导，更符合静稳条件下的本地累积与二次转化。"
                     % (detail, t_pm))
    return {"ups": ups, "verdict": verdict, "lines": lines}
