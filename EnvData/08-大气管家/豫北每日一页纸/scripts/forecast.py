# -*- coding: utf-8 -*-
"""预报层：把 CAMS 模式预报值算成"未来 24–72 小时逐时 AQI 与峰值时段"。

为什么必须有这一层
------------------
此前的日报 100% 是"此刻快照"，没有任何未来信息 —— 而城市大气管控的决策依据
恰恰是预报：明天要不要启动管控、几点启动、控什么污染物。没有预报，
"今日重点行动任务"只能写成泛化的"加强巡查"。

算法（全部可复算，见页面证据链）
  · 逐时 O₃ → 8 小时滑动平均（窗口不足 8 项或含缺测记 None，不补零、不缩短窗口）
  · 逐项算 IAQI（HJ 633-2012 分段，与实况口径共用 calc.brief.IAQI_BP）
  · 该小时 AQI = 各项 IAQI 取最大；首要污染物 = 取到最大 IAQI 的那一项
  · 未来 24h = 严格晚于数据时点的 24 个整点

⚠️ 口径边界（页面必须原样声明，不得省略）
  预报值来自 **CAMS 全球模式**（ECMWF 哥白尼大气监测服务），约 40 km 网格、
  城市尺度代表性，**不是**国控点位本地实测。静稳天气下模式对 PM2.5 峰值通常低估、
  对 O₃ 日变化的位相也可能偏移。因此：
    · 只用于**趋势与时段判断**（今天午后会不会起来、峰值大概在几点）
    · **不得**作为达标判据、考核依据或对外正式结论
    · 与实测冲突时，以实测为准
"""
from collections import Counter

from .aqi_stats import aqi_level
from .brief import IAQI_BP, POLL_CN, iaqi


def o3_8h_series(rows):
    """逐时 O₃ → 8 小时滑动平均序列（与 GB 3095 的 O₃-8h 定义一致）。

    窗口不足 8 项、或窗口内任一小时缺测 → 记 None。**不补零、不缩短窗口**：
    用不足 8 小时的均值去比 160 限值，是典型的"看起来成立、其实口径错"。
    """
    vals = [r.get("o3") for r in rows]
    out = []
    for i in range(len(rows)):
        if i < 7:
            out.append(None)
            continue
        w = vals[i - 7:i + 1]
        out.append(round(sum(w) / 8.0, 1) if all(v is not None for v in w) else None)
    return out


def hourly_aqi(rows):
    """逐时 AQI + 首要污染物。rows: [{timepoint,pm25,pm10,o3,no2,so2,co}]（升序，co 单位 mg/m³）"""
    o3 = o3_8h_series(rows)
    out = []
    for i, r in enumerate(rows):
        cand = [("pm25", r.get("pm25")), ("pm10", r.get("pm10")), ("o3_8h", o3[i]),
                ("no2", r.get("no2")), ("so2", r.get("so2")), ("co", r.get("co"))]
        items = [(p, iaqi(p, c), c) for p, c in cand if c is not None]
        items = [x for x in items if x[1] is not None]
        if not items:
            out.append({"timepoint": r["timepoint"], "aqi": None, "primary": None,
                        "pm25": r.get("pm25"), "pm10": r.get("pm10"), "o3_8h": o3[i]})
            continue
        p, val, _c = max(items, key=lambda x: x[1])
        out.append({"timepoint": r["timepoint"], "aqi": round(val, 1), "primary": p,
                    "pm25": r.get("pm25"), "pm10": r.get("pm10"), "o3_8h": o3[i]})
    return out


def forecast_summary(series, start_tp, hours=24, first_day=None):
    """未来 N 小时摘要。series 为 hourly_aqi 的输出，start_tp 为实况数据时点。

    返回 None 表示该城市无有效预报（调用方应整段跳过，不写"待核"占位）。
    """
    nxt = [s for s in series if s["timepoint"] > start_tp][:hours]
    if not nxt:
        return None
    valid = [s for s in nxt if s["aqi"] is not None]
    if not valid:
        return None

    peak = max(valid, key=lambda s: s["aqi"])
    lv = Counter(aqi_level(s["aqi"])[0] for s in valid)
    mix = Counter(s["primary"] for s in valid if s["primary"])
    over = [s for s in valid if s["aqi"] > 100]

    # 管控窗口：优先给"可能达到轻度污染及以上"的时段（这才是要出措施的时间）；
    # 若全程优良，则给未来 24h 的 AQI 相对高值前 3 小时，供安排巡查节奏。
    # 返回**完整时点**而非 'HH:MM'：跨日信息（+1日）由渲染层负责，算法层不做展示裁剪。
    if over:
        window_tps = [s["timepoint"] for s in over]
        window_note = "可能达轻度污染及以上的时段"
    else:
        top = sorted(valid, key=lambda s: -s["aqi"])[:3]
        window_tps = [s["timepoint"] for s in top]
        window_note = "全程无轻度污染，以下为 AQI 相对高值时段"
    window_tps.sort()      # 展示按时间先后，不按 AQI 高低 —— 读者是按时间安排巡查的

    # 当日（预报覆盖的首个自然日）O₃-8h 最大，用于对照 160 限值
    if first_day:
        day_o3 = [s["o3_8h"] for s in series
                  if s["timepoint"][:10] == first_day and s["o3_8h"] is not None]
    else:
        day_o3 = [s["o3_8h"] for s in nxt if s["o3_8h"] is not None]

    return {
        "hours": nxt, "n": len(nxt),
        "peak_aqi": peak["aqi"], "peak_tp": peak["timepoint"], "peak_lv": aqi_level(peak["aqi"])[0],
        "peak_primary": POLL_CN.get(peak["primary"], peak["primary"] or "—"),
        "levels": lv, "mix": mix,
        "primary_main": (POLL_CN.get(mix.most_common(1)[0][0], "—") if mix else "—"),
        "primary_main_n": (mix.most_common(1)[0][1] if mix else 0),
        "over100_hours": len(over),
        "window_tps": window_tps, "window_note": window_note,
        "o3_8h_day_max": max(day_o3) if day_o3 else None,
        "aqi_max_of_day": max((s["aqi"] for s in valid), default=None),
    }
