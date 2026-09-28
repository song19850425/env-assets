# -*- coding: utf-8 -*-
"""计算层：城市聚合、等级判定、高值标注。"""
from collections import defaultdict

LEVELS = [  # (上限, 名称, 颜色-浅底, 文字色)
    (50, "优", "#E8F5E0", "#2E6B0F"),
    (100, "良", "#FFF9DC", "#8A6D00"),
    (150, "轻度污染", "#FFEEDC", "#A85A00"),
    (200, "中度污染", "#FDE2E2", "#A32D2D"),
    (300, "重度污染", "#F3D9EE", "#7A2A68"),
    (9999, "严重污染", "#F2DBD9", "#6E1F1B"),
]


def aqi_level(aqi):
    if aqi is None:
        return ("—", "#F1EFE8", "#5F5E5A")
    for cap, name, bg, fg in LEVELS:
        if aqi <= cap:
            return (name, bg, fg)
    return (LEVELS[-1][1], LEVELS[-1][2], LEVELS[-1][3])


def city_summary(rows):
    """按城市聚合：点位数、最差点位、均值PM2.5、最大O3-8h、超标点位数"""
    by_city = defaultdict(list)
    for r in rows:
        by_city[r["city"]].append(r)
    out = []
    for city, rs in by_city.items():
        valid = [r for r in rs if r["aqi"] is not None]
        worst = max(valid, key=lambda r: r["aqi"]) if valid else None
        pm25s = [r["pm25"] for r in rs if r["pm25"] is not None]
        o3s = [r["o3_8h"] for r in rs if r["o3_8h"] is not None]
        exceed = [r for r in valid if r["aqi"] > 100]
        out.append({
            "city": city, "n": len(rs),
            "aqi_max": worst["aqi"] if worst else None,
            "worst": worst,
            "pm25_mean": round(sum(pm25s) / len(pm25s), 1) if pm25s else None,
            "o3_8h_max": max(o3s) if o3s else None,
            "exceed_cnt": len(exceed),
            "quality": worst["quality"] if worst else "—",
            "primary": worst["primary_pollutant"] if worst else "—",
            "stations": sorted(rs, key=lambda r: -(r["aqi"] if r["aqi"] is not None else -1)),
        })
    return sorted(out, key=lambda c: -(c["aqi_max"] if c["aqi_max"] is not None else -1))
