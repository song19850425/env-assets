# -*- coding: utf-8 -*-
"""日报构建（V2 研判版）：把"播报数字"变成"给出可追溯的判断"。

为什么单独一层
--------------
这份版式要在**两个地方**产出：本机（run_daily.py / run_v2.py，数据来自本地库）
和云端（cloud/report_cloud.py，数据来自 data-hourly/*.jsonl）。
如果两边各写一份编排逻辑，迟早会出现"网页上的口径与本机的不一样"——
这正是本项目最不能出的错（对外材料的口径必须唯一）。

故：本模块只做**编排**（取研判 → 拼证据链 → 渲染），
    不碰数据库、不碰网络 → 本地与云端都能直接复用同一份代码。
    数据来源差异（库 / JSONL / 气象缓存）由各自的入口负责，见：
      run_daily.py            本机：采集入库 → 从库读最新时点 → 出报
      run_v2.py               本机：不采集，只按库里最新时点重出报
      cloud/report_cloud.py   云端：读当天 JSONL → 出报

三条硬规则（沿用 calc/brief.py）：实时口径 ≠ 日均口径；城市值取点位平均；
无依据不下结论。
"""
from datetime import datetime

from calc.brief import (POLL_CN, DISPERSION_LOCAL, DISPERSION_REGION, GB3095_2,
                        PM_RATIO_DUST, city_brief, region_brief, cause_frame, tasks)
from calc.forecast import forecast_summary
from calc.review import region_review
from calc.wind import WIND_CALM, compass, stability, transport
from report.page_v2 import render_v2

BASE_URL = "https://air.cnemc.cn:18007/CityData/GetAQIDataPublishLive"


def make_briefs(cfg, rows):
    """逐市研判，按实时 AQI 降序（排序即"先看谁"，不改变任何数值口径）"""
    cities = cfg["cities"]
    briefs = [city_brief(c, [r for r in rows if r["city"] == c]) for c in cities]
    briefs.sort(key=lambda x: -(x["aqi_rt"] or 0))
    return briefs


def build_wind(briefs, weather, cfg, extra_air=None):
    """逐市气象研判 + 区域传输判断。

    weather: {city: {wind_speed, wind_dir, wind_gust, blh, temp, rh, pressure, precip}}
    （本机来自 city_hourly_weather 表，云端来自 JSONL 的 k=w 记录，字段名一致）
    extra_air: 省外上风向城市的城市级浓度 {city: {"pm25_mean":..}}，用于补上传输盲区。

    为什么把 neighbors 合进 coords：上风向判定是"目标城市→其它城市"的方位角比较，
    备选集合必须包含邻居城市才可能命中（此前 neighbors 为空，安阳/濮阳经常输出
    "无同组上风向城市"）。未提供 extra_air 时自动退回"仅本地四市"的旧行为 ——
    云端若未采邻居城市，页面会如实降级，不会假装判过。
    """
    coords = dict(cfg.get("coords") or {})
    coords.update(cfg.get("neighbor_coords") or {})
    air = {c["city"]: {"pm25_mean": c.get("pm25_mean"), "aqi_rt": c.get("aqi_rt")} for c in briefs}
    for k, v in (extra_air or {}).items():
        air[k] = {"pm25_mean": (v or {}).get("pm25_mean"), "aqi_rt": (v or {}).get("aqi_rt")}
    out = {}
    for c in briefs:
        w = weather.get(c["city"]) or {}
        ws, blh, wd = w.get("wind_speed"), w.get("blh"), w.get("wind_dir")
        level, desc = stability(ws, blh)
        tp = transport(c["city"], wd, coords, air)
        out[c["city"]] = {
            "wind_speed": ws, "wind_dir": wd, "wind_dir_cn": compass(wd),
            "wind_gust": w.get("wind_gust"), "blh": blh, "temp": w.get("temp"),
            "rh": w.get("rh"), "pressure": w.get("pressure"), "precip": w.get("precip"),
            "level": level, "desc": desc, "transport": tp,
            "rh_flag": (w.get("rh") is not None and w["rh"] >= 80 and (ws or 99) < WIND_CALM),
        }
    return out


def bias_check(rows, forecast_series, timepoint, cities):
    """同小时「实测 vs 模式」偏差自检。

    存在的理由：CAMS 是约 40 km 的全球模式，对本市存在**系统性偏差**。
    2026-09-25 实测：模式 PM2.5 比同期实测高 11%~328%（鹤壁、新乡最明显），
    臭氧预报值低约一半。把这种未订正的绝对值当"本地预报"发布，会直接误导管控决策
    （把模式高估读成"明天要污染"，或把臭氧低估读成"不会超标"）。
    故把偏差量级**当场算出来给读者看**，而不是藏在免责声明里。
    """
    out = []
    for c in cities:
        obs = [r.get("pm25") for r in rows
               if r.get("city") == c and r.get("pm25") is not None]
        obs_m = round(sum(obs) / len(obs), 1) if obs else None
        mod = None
        for r in (forecast_series.get(c) or []):
            if str(r.get("timepoint"))[:16] == str(timepoint)[:16]:
                mod = r.get("pm25")
                break
        out.append({"city": c, "obs": obs_m, "mod": mod})
    return {"rows": out, "tp": timepoint}


def _extra_evidence(timepoint, review, region_rev, fcst, bias, neighbor_air, cfg):
    """回顾段与预报段的证据链 —— 新增章节必须同等地可复核，不能只写结论。"""
    ev = []
    if review:
        ev.append("日评价回顾来源：平台城市日历史接口（<code>HourChangesPublish/"
                  "GetCityDayAqiHistoryByCondition</code>，按城市代码查询），落库表 "
                  "<code>city_daily</code>；距平基准为评价日<b>之前</b>近 14 天均值"
                  "（被评价日不计入，避免自我包含）。")
    if region_rev:
        ev.append("污染结构判据：近 %d 天各市首要污染物按日评价结果统计 —— 臭氧 %d 天、"
                  "PM2.5 %d 天、PM10 %d 天；结论「以%s为主导」即由此判定。"
                  % (region_rev["n_days"], region_rev["o3_days"], region_rev["pm25_days"],
                     region_rev["pm10_days"], region_rev["lead"]))
    if fcst:
        ev.append("预报接口：<code>air-quality-api.open-meteo.com/v1/air-quality</code>"
                  "（CAMS 全球模式，免密钥）；要素 <code>pm2_5 / pm10 / ozone / no2 / so2 / co</code>，"
                  "逐时、过去 1 天 + 未来 3 天。"
                  "<b>CO 已由 μg/m³ 折算为 mg/m³</b>，与平台口径及 HJ 633 IAQI 分段一致。")
        ev.append("预报算法：逐时 O₃ 取 8 小时滑动平均（窗口不足 8 项记缺测，不补零）；"
                  "各项按 HJ 633-2012 分段算 IAQI，该小时 AQI = 各 IAQI 取最大，"
                  "首要污染物 = 对应项；未来 24h = 严格晚于数据时点的 24 个整点。")
    if bias:
        got = [b for b in bias["rows"] if b["obs"] and b["mod"]]
        if got:
            ev.append("⚠️ <b>模式偏差自检（同日同时刻，实测城市均值 vs 模式值）</b>：%s。"
                      "模式在本市存在系统性偏差，故预报节的绝对值<b>只能用于比较时段高低</b>，"
                      "未做 MOS（模式输出统计）订正前不得作为预测值引用。"
                      % "；".join("%s %.1f→%.1f" % (b["city"][:2], b["obs"], b["mod"]) for b in got))
    if cfg.get("neighbors"):
        if neighbor_air:
            ev.append("传输研判城市池：本地 %d 市 + 省外上风向 %d 市（%s），共 %d 市。"
                      "邻居城市浓度取自实时接口同小时城市均值，与本地口径一致。"
                      % (len(cfg["cities"]), len(neighbor_air),
                         "、".join(c[:2] for c in sorted(neighbor_air)),
                         len(cfg["cities"]) + len(neighbor_air)))
        else:
            ev.append("⚠️ 传输研判城市池：本次<b>未取得省外上风向城市数据</b>"
                      "（配置已列 %s），上风向判定仅在本地 %d 市内成立，"
                      "结论可能因盲区而偏保守（「判不出」不等于「没有传输」）。"
                      % ("、".join(c[:2] for c in cfg["neighbors"]), len(cfg["cities"])))
    return ev


def evidence_chain(rows, cities, timepoint, cfg, weather=None, werr=None, raw_note=None):
    """证据链：让读者能自己复核结论怎么来的（这是本版式存在的理由）"""
    n_by_city = {c: sum(1 for r in rows if r["city"] == c) for c in cities}
    na = {}
    for r in rows:
        for k in ("pm25", "pm25_24h", "pm10", "pm10_24h", "o3_8h", "aqi"):
            if r.get(k) is None:
                na[k] = na.get(k, 0) + 1
    ev = [
        "接口：<code>%s?cityName=&lt;URL编码城市名&gt;</code>（逐城市调用）" % BASE_URL,
        "抓取时点（平台 TimePoint）：<b>%s</b>；本页生成时刻：<b>%s</b>"
        % (timepoint, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "样本数：<b>%d</b> 个点位（%s）"
        % (len(rows), "、".join("%s %d" % (c[:2], n_by_city[c]) for c in cities)),
        "缺测（返回 NA）统计：%s" % ("、".join("%s %d 个" % (k, v) for k, v in na.items()) if na else "<b>无缺测</b>"),
        "达标判定依据：GB 3095-2012 二级限值 PM2.5 24h %d、PM10 24h %d、O₃-8h %d μg/m³；"
        "城市 AQI 依据 HJ 663-2013 点位平均法。" % (GB3095_2["pm25_24h"], GB3095_2["pm10_24h"], GB3095_2["o3_8h"]),
        "口径风险提示：平台 <code>AQI</code> 字段由<b>当前小时浓度</b>算出（实时口径），"
        "与官方日报的日均 AQI 不等价；本页已分列两套口径，勿混用。",
        "字段待核：平台 <code>O3_8h_24h</code> 语义未确认，本版<b>未用于</b>达标判定。",
        "数据性质：总站实时发布平台<b>未经审核</b>数据，与年度审核数据可能存在差异；"
        "正式对外结论应使用省级/总站审核后数据。",
        "原始报文留存：%s" % (raw_note or
                              "本页<b>未留存</b>原始 JSON 响应，无法对单点数值回溯上游返回值"),
    ]
    if weather:
        got = [c for c in cities if c in weather]
        ev.insert(2, "气象接口：<code>api.open-meteo.com/v1/forecast</code>（免密钥，ECMWF/ICON 模式再分析+预报，"
                     "取 <code>wind_speed_10m / wind_direction_10m / boundary_layer_height / relative_humidity_2m</code> 等）")
        ev.insert(3, "气象命中：<b>%d</b> 个城市（%s），时点对齐 <b>%s</b>；单位：风速 m/s、风向 °（气象风向＝风的来向）、"
                     "边界层高度 m。" % (len(got), "、".join(c[:2] for c in got), timepoint))
        ev.append("气象数据性质：模式产品、<b>城市尺度</b>代表性，非国控点位本地实测气象，"
                  "与点位微环境存在差异；用于研判趋势与传输方向，不作为合规判据。")
        ev.append("传输研判盲区：上风向判定仅在<span>已纳入的 %d 个城市</span>内成立，"
                  "省外上风向城市（邯郸、邢台、聊城、菏泽、焦作、长治、晋城等）未纳入，可能存在传输盲区。"
                  % len(cities))
        ev.append("阈值属性：静稳/边界层/高湿静稳等阈值均为<b>经验阈值</b>，非国家标准限值，仅用于辅助研判。")
    else:
        ev.append("气象数据缺失：本版<b>未取得</b>风向风速与边界层数据，成因研判已相应降级为"
                  "&#34;仅基于空气质量数据&#34;，未作传输归因。")
    if werr:
        ev.append("气象采集失败项：%s" % "；".join(werr))
    return ev


def build(cfg, rows, timepoint, weather=None, werr=None, raw_note=None,
          review=None, forecast_series=None, neighbor_air=None):
    """构建日报。rows 为点位行（键名与 ingest/fetch_air、core.db.load_hour 一致）。

    三个新增入参**全部可选**，缺省即优雅降级（云端拿不到时该节自动隐藏，不写占位）：
      review          calc.review.build_review 的输出 —— 日评价回顾（依赖 city_daily）
      forecast_series {city: calc.forecast.hourly_aqi 的输出} —— 未来 24h 模式趋势
      neighbor_air    {city: {"pm25_mean":..}} —— 省外上风向城市浓度，用于补传输盲区

    返回 dict(html, briefs, region, causes, actions, winds, evidence, ...)，
    调用方自行决定落盘位置（本机 out/ 与云端 daily/ 的路径并不相同）。
    """
    cities = cfg["cities"]
    if not rows:
        raise ValueError("无点位数据（时点 %s）" % timepoint)

    briefs = make_briefs(cfg, rows)
    region = region_brief(briefs)
    causes = cause_frame(briefs, region)
    region_rev = region_review(review, cities) if review else None
    action_list = tasks(briefs, region, region_rev)

    weather = weather or {}
    winds = build_wind(briefs, weather, cfg, extra_air=neighbor_air) if weather else {}

    fcst, bias = {}, None
    if forecast_series:
        for city, ser in forecast_series.items():
            s = forecast_summary(ser, timepoint, 24, first_day=str(timepoint)[:10])
            if s:
                fcst[city] = s
        if fcst:
            bias = bias_check(rows, forecast_series, timepoint, cities)

    evidence = evidence_chain(rows, cities, timepoint, cfg, weather, werr, raw_note)
    evidence.extend(_extra_evidence(timepoint, review, region_rev, fcst, bias, neighbor_air, cfg))

    html = render_v2(briefs, region, causes, action_list, timepoint, cfg, evidence, winds,
                     review=review, region_rev=region_rev, forecast=fcst, bias=bias)
    return {"html": html, "briefs": briefs, "region": region,
            "causes": causes, "actions": action_list,
            "winds": winds, "evidence": evidence,
            "review": review, "region_rev": region_rev, "forecast": fcst, "bias": bias}


def print_summary(result, timepoint, n_rows):
    """把研判结果在控制台复述一遍 —— 出报后立刻能看出结论对不对"""
    print("[时点] %s | 点位 %d 个" % (timepoint, n_rows))
    print("%-4s %8s %8s %8s | %6s %6s | %6s %6s" % (
        "城市", "实时AQI", "日均AQI", "点位均", "PM2.5", "24h", "高值点", "超标点"))
    for c in result["briefs"]:
        print("%-4s %8s %8s %8s | %6s %6s | %6d %6d" % (
            c["city"][:2], c["aqi_rt"], c["aqi_dy"], c["point_avg_aqi"],
            c["pm25_mean"], c["pm25_24h_mean"], c["exceed_rt_cnt"], c["exceed_dy_cnt"]))
    print("[区域] %s" % result["region"]["text"].replace("**", ""))
    for c in result["briefs"]:
        w = result["winds"].get(c["city"]) or {}
        if w:
            print("[气象] %-4s %s（%s）风速 %s m/s ｜ 扩散 %s ｜ 传输：%s" % (
                c["city"][:2], w.get("wind_dir_cn"), w.get("wind_dir"),
                "—" if w.get("wind_speed") is None else "%.1f" % w["wind_speed"],
                w.get("level"), (w.get("transport") or {}).get("verdict", "—")))
    print("[成因] " + "；".join(
        "%s %s" % (c["city"][:2], (c["reasons"][0] if c["reasons"] else "待核"))
        for c in result["causes"]))
    print("[行动] " + "；".join(
        "%s %s" % (a["city"][:2], a["acts"][0]) for a in result["actions"]))


def primary_cn(poll):
    return POLL_CN.get(poll, poll or "—")
