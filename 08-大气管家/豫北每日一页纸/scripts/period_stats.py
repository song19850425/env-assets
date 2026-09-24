# -*- coding: utf-8 -*-
"""周期统计：周报/月报的指标计算（全部由历史日值推导，不引入外部数）"""
from collections import Counter

POLL = [("pm25", "PM2.5", "µg/m³"), ("pm10", "PM10", "µg/m³"),
        ("so2", "SO₂", "µg/m³"), ("no2", "NO₂", "µg/m³"),
        ("co", "CO", "mg/m³"), ("o3_8h", "O₃-8h", "µg/m³")]


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _rate(cur, prev):
    """变化率%，prev 为 0/None 返回 None"""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def city_period_stats(rows_cur, rows_prev):
    """rows_cur/rows_prev：该城市本期/上期日值列表"""
    n = len(rows_cur)
    good = sum(1 for r in rows_cur if r["aqi"] is not None and r["aqi"] <= 100)
    light = sum(1 for r in rows_cur if r["aqi"] is not None and 100 < r["aqi"] <= 150)
    mid_plus = sum(1 for r in rows_cur if r["aqi"] is not None and r["aqi"] > 150)
    means = {k: _mean([r[k] for r in rows_cur]) for k, _, _ in POLL}
    means_prev = {k: _mean([r[k] for r in rows_prev]) for k, _, _ in POLL}
    changes = {k: _rate(means[k], means_prev[k]) for k, _, _ in POLL}
    ratio = _mean([r["pm25"] / r["pm10"] * 100 for r in rows_cur
                   if r["pm25"] and r["pm10"]])
    prim = Counter(r["primary"] for r in rows_cur if r["primary"] and r["primary"] != "—")
    valid = [r for r in rows_cur if r["aqi"] is not None]
    worst = max(valid, key=lambda r: r["aqi"]) if valid else None
    best = min(valid, key=lambda r: r["aqi"]) if valid else None
    mean_aqi = _mean([r["aqi"] for r in rows_cur])
    return {
        "city": rows_cur[0]["city"] if rows_cur else "—",
        "n": n, "good": good,
        "good_rate": round(good / n * 100, 0) if n else 0,
        "light": light, "mid_plus": mid_plus,
        "means": means, "means_prev": means_prev, "changes": changes,
        "ratio": ratio, "primary_freq": prim.most_common(3),
        "worst": worst, "best": best, "mean_aqi": mean_aqi,
        "rows": rows_cur,
    }


def arrow(rate):
    if rate is None:
        return "—"
    return ("↑%+.1f%%" % rate) if rate >= 0 else ("↓%.1f%%" % rate)
