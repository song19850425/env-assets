# -*- coding: utf-8 -*-
"""日评价回顾层：把"昨天的日评价"和"近 14 天基线"算出来，供日报的回顾章节使用。

为什么必须单独有这一层
----------------------
早间日报有一个方法学硬伤：**07:00 的瞬时帧没资格承担"今日研判"**。
理由（2026-09-24/25 实测）：07:00 臭氧尚未生成（O₃-8h 全缺测）、
PM2.5 处于夜间累积峰值、边界层仅 55 m（日出前最低）——用这一帧判
"首要污染物 / 成因类型 / 局地还是区域"，结论会系统性偏向 PM2.5 与"局地源"。
同一天 07:00 帧判四市"轻度污染、首要 PM2.5、20/21 点位超标"，
17:00 帧四市全部转"良"（55–92）—— 结论完全反转。

正确做法：早间日报应以**日评价口径**（城市日 AQI / 首要污染物 / 超标）作为回顾与判据，
再叠加预报看未来；瞬时帧只作"当前状态"陈述，不下结构结论。
本模块提供那个"日评价口径"的回顾数据。

数据源：`city_daily`（平台日历史接口，14 天滚动窗口，唯一留存处）。
本模块是**纯函数**：不碰数据库、不碰网络 —— 本机与云端都能复用。
"""
from .brief import POLL_CN

# 首要污染物判定用"包含"匹配：平台写法不统一
# （实测「臭氧8小时(O3_8h)」「细颗粒物(PM2.5)」「颗粒物(PM10)」等）
_O3_KEYS = ("臭氧", "O3", "O₃")
_PM25_KEYS = ("PM2.5", "PM2_5", "细颗粒物")
_PM10_KEYS = ("颗粒物(PM10)", "PM10")


def _mean(vals):
    vs = [v for v in vals if v is not None]
    return round(sum(vs) / len(vs), 1) if vs else None


def _bucket(primary):
    """把平台的首要污染物写法归到三大类，便于统计结构"""
    if not primary:
        return "none"
    p = str(primary)
    if any(k in p for k in _O3_KEYS):
        return "o3"
    if any(k in p for k in _PM25_KEYS):
        return "pm25"
    if any(k in p for k in _PM10_KEYS):
        return "pm10"
    return "other"


def build_review(daily, cities, window=14, ref_date=None):
    """逐市生成日评价回顾。

    daily: {city: [{date,aqi,quality,primary,pm25,pm10,so2,no2,co,o3_8h}, ...]}（日期升序）
    ref_date: 以"不晚于该日"的最后一个有数据的日为回顾对象；None = 用各市最新一日。
              平台的日评价数据天然晚一天，故通常 ref 就是"昨日"；若滞后更多，
              data_lag_days 会如实反映，页面据此声明。

    返回 {city: {...}}；数据结构见文件末的 __doc__ 示例（见 out 页面的"日评价回顾"表）。
    """
    out = {}
    for city in cities:
        rows = [r for r in (daily.get(city) or []) if r.get("date")]
        if not rows:
            continue
        rows.sort(key=lambda r: r["date"])
        if ref_date:
            rows = [r for r in rows if r["date"] <= ref_date] or rows

        ref = rows[-1]
        # 基线：参考日**之前**的 window 天，避免把被评价日本身算进均值（自我包含会系统性压低距平）
        prev = rows[:-1][-window:]
        # 结构窗口：含参考日的最近 window 天（用于统计首要污染物构成与超标天数）
        win = rows[-window:]

        aqi14 = _mean([r.get("aqi") for r in prev])
        aqi7 = _mean([r.get("aqi") for r in prev[-7:]])
        ref_aqi = ref.get("aqi")
        anom = None
        anom_pct = None
        if ref_aqi is not None and aqi14:
            anom = round(ref_aqi - aqi14, 1)
            anom_pct = round((ref_aqi - aqi14) / aqi14 * 100, 1)

        mix = {"o3": 0, "pm25": 0, "pm10": 0, "other": 0, "none": 0}
        for r in win:
            mix[_bucket(r.get("primary"))] += 1
        n_win = len(win)
        over100 = sum(1 for r in win if (r.get("aqi") or 0) > 100)

        out[city] = {
            "city": city,
            "ref": {
                "date": ref["date"], "aqi": ref_aqi,
                "quality": ref.get("quality"), "primary": ref.get("primary"),
                "pm25": ref.get("pm25"), "o3_8h": ref.get("o3_8h"),
                "pm10": ref.get("pm10"),
            },
            "baseline_days": len(prev),
            "aqi_mean7": aqi7, "aqi_mean14": aqi14,
            "pm25_mean14": _mean([r.get("pm25") for r in prev]),
            "o3_mean14": _mean([r.get("o3_8h") for r in prev]),
            "aqi_anom": anom, "aqi_anom_pct": anom_pct,
            "window_days": n_win, "mix": mix,
            "o3_share": (round(mix["o3"] / n_win * 100) if n_win else None),
            "over100_days": over100,
        }
    return out


def region_review(review, cities):
    """区域小结：把"这半个月的主线是什么"变成一句可复核的话。

    这一段存在的意义：管控路线必须与污染物结构匹配。
    实测 2026-09-10~09-23 四市 79% 的天数首要污染物是臭氧、O₃-8h 均值 146–154（贴近 160 限值），
    而日报的行动任务长期只写"扬尘/洒水" —— 那是控 PM 的路线，对臭氧基本无效
    （臭氧要控 VOCs / NOx 前体物）。本函数把这个错配显式暴露出来。
    """
    got = [review[c] for c in cities if c in review and review[c]["window_days"]]
    if not got:
        return None
    n_win = max(g["window_days"] for g in got)
    o3_days = max(g["mix"]["o3"] for g in got)
    pm25_days = max(g["mix"]["pm25"] for g in got)
    pm10_days = max(g["mix"]["pm10"] for g in got)
    o3_share = round(o3_days / n_win * 100) if n_win else None
    o3_means = [g["o3_mean14"] for g in got if g["o3_mean14"] is not None]
    o3_avg = round(sum(o3_means) / len(o3_means), 0) if o3_means else None
    over100 = max(g["over100_days"] for g in got)

    lead = "臭氧" if (o3_share or 0) >= 50 else ("颗粒物" if (pm25_days + pm10_days) > o3_days else "无单一主导")
    parts = [
        "近 %d 天四市中单市最高有 <b>%d 天</b>首要污染物为 <b>臭氧</b>（约占 %s%%），"
        "O₃-8h 均值约 <b>%s μg/m³</b>（GB 3095-2012 二级限值 160），AQI&gt;100 最多 %d 天。"
        % (n_win, o3_days, o3_share, o3_avg, over100)
    ]
    if lead == "臭氧":
        parts.append("→ 本阶段污染结构<b>以臭氧为主导</b>。臭氧管控的技术路线是"
                     "<b>VOCs 与 NOx 前体物</b>（涉 VOCs 企业、加油站、涂装/印刷/化工、机动车），"
                     "与颗粒物的<b>扬尘/除尘</b>路线不是一回事；行动任务须按此分配，"
                     "否则会出现「措施很忙、指标不动」。")
    elif lead == "颗粒物":
        parts.append("→ 本阶段污染结构<b>以颗粒物为主导</b>，扬尘/燃烧源管控路线适用。")
    else:
        parts.append("→ 本阶段<b>无单一主导污染物</b>，需按日评价结果分日选用管控路线。")
    return {"n_days": n_win, "o3_days": o3_days, "pm25_days": pm25_days, "pm10_days": pm10_days,
            "o3_share": o3_share, "o3_mean": o3_avg, "over100_days": over100,
            "lead": lead, "html": " ".join(parts)}


def primary_cn(p):
    return POLL_CN.get(p, p or "—")
