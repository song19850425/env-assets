# -*- coding: utf-8 -*-
"""单城市「一页纸」渲染器（轻量版，对应「每个城市单独一页纸」需求）。

复用：
  - calc.brief.city_brief  单市研判（实时/日均双口径、点位平均、超标判定、特征）
  - report.page_v2.chip/fmt/short  展示工具
数据全部来自 station_hourly / city_daily（已采集）+ data/forecast_*.json（CAMS 模式），
不新增采集。保留项目红线：实时≠日均、点位平均、证据链、AI草稿标识、模式偏差声明。
"""
import json
import sqlite3
from calc.brief import city_brief, POLL_CN
from report.page_v2 import chip, fmt, short


def _rows_at(con, city, tp):
    cols = ["city", "station_code", "station_name", "aqi", "primary_pollutant",
            "pm25", "pm25_24h", "pm10", "pm10_24h", "o3_8h", "no2", "so2", "co", "timepoint"]
    rs = con.execute(
        "SELECT %s FROM station_hourly WHERE city=? AND timepoint=?" % ",".join(cols),
        (city, tp)).fetchall()
    return [dict(zip(cols, r)) for r in rs]


def latest_tp(con, city):
    return con.execute("SELECT MAX(timepoint) FROM station_hourly WHERE city=?", (city,)).fetchone()[0]


def trend_24h(con, city, tp):
    rs = con.execute(
        "SELECT substr(timepoint,1,13) hh, AVG(aqi) a FROM station_hourly "
        "WHERE city=? AND timepoint<=? GROUP BY hh ORDER BY hh DESC LIMIT 24",
        (city, tp)).fetchall()
    rs.reverse()
    return [(hh[11:], a) for hh, a in rs if a is not None]


def day_series(con, city, date, n=14):
    rs = con.execute(
        "SELECT date, aqi, primary_pollutant, pm25, pm10, o3_8h FROM city_daily "
        "WHERE city=? AND date<=? ORDER BY date DESC LIMIT ?", (city, date, n)).fetchall()
    return rs


def fcst_summary(fraw, tp):
    """CAMS 原始 hourly → 未来 24h 相对高值时段（只给高低，不给绝对值预测）。"""
    if not fraw:
        return None
    times = fraw.get("time", [])
    pm = fraw.get("pm2_5", [])
    o3 = fraw.get("ozone", [])
    fut = [(t, p, o) for t, p, o in zip(times, pm, o3) if t >= tp][:24]
    if not fut:
        return None
    pmv = [(t, p) for t, p, _ in fut if p is not None]
    ov = [(t, o) for t, _, o in fut if o is not None]
    pm_peak = max(pmv, key=lambda x: x[1])[0][11:16] if pmv else None
    o3_peak = max(ov, key=lambda x: x[1])[0][11:16] if ov else None
    return {"pm_peak": pm_peak, "o3_peak": o3_peak, "n": len(fut)}


CSS = """
:root{--bg:#0b1020;--card:#121a30;--ink:#e8eefc;--dim:#8aa0c8;--cy:#22d3ee;--mg:#f472b6;--am:#fbbf24;--gr:#34d399;--bd:#23304f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;line-height:1.6;padding:26px}
.wrap{max-width:860px;margin:0 auto;position:relative}
h1{font-size:22px;margin:0 0 2px}
.sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.stamp{position:absolute;top:0;right:0;border:1px solid var(--mg);color:var(--mg);border-radius:8px;padding:4px 10px;font-size:12px;text-align:center;line-height:1.3;opacity:.9}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;min-width:120px;flex:1}
.card .k{color:var(--dim);font-size:12px}
.card .v{font-size:21px;font-weight:700;margin-top:3px}
.tag{display:inline-block;border-radius:6px;padding:1px 7px;font-size:12px;font-weight:700}
section{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px;margin:14px 0}
h2{font-size:15px;margin:0 0 10px;color:var(--cy)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid var(--bd)}
th{color:var(--dim);font-weight:600;font-size:11.5px}
td.num{font-variant-numeric:tabular-nums;color:#cfe0ff}
.bad{color:#ff6b6b;font-weight:700}.ok{color:var(--gr)}
.note,.legend{font-size:12px;color:var(--dim);margin:8px 0 0}
.bars{display:flex;align-items:flex-end;gap:3px;height:64px;margin-top:6px}
.bar{flex:1;background:linear-gradient(180deg,#22d3ee,#1b6ca8);border-radius:3px 3px 0 0;min-height:2px;position:relative}
.bar i{position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);font-size:9px;color:var(--dim);font-style:normal}
"""


def render_city_page(cfg, city, con, forecast_file, now=None):
    from datetime import datetime
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M")
    full = city
    cname = short(city)
    tp = latest_tp(con, city)
    if not tp:
        return "<p>暂无 %s 数据</p>" % cname
    rows = _rows_at(con, city, tp)
    b = city_brief(city, rows)
    day = tp[:10]
    tr = trend_24h(con, city, tp)
    days = day_series(con, city, day)
    region = cfg.get("region_name", "")
    # CAMS
    fcst = None
    if forecast_file:
        try:
            fj = json.load(open(forecast_file, encoding="utf-8"))
            fcst = fcst_summary(fj.get(cname, {}).get("aq", {}).get("hourly"), tp)
        except Exception:
            fcst = None

    # ── 点位清单 ──
    st_rows = ""
    for s in b["stations"]:
        st_rows += ("<tr><td>%s</td><td class='num'>%s</td><td>%s</td>"
                    "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>") % (
            s["station_name"], fmt(s["aqi"]), (s["primary_pollutant"] or "优（无首要）"),
            fmt(s["pm25"]), fmt(s["pm10"]), fmt(s["o3_8h"]))

    # ── 24h 趋势条 ──
    bars = ""
    if tr:
        peak = max(v for _, v in tr) or 1
        for hh, v in tr:
            h = max(3, int(v / peak * 56))
            bars += "<div class='bar' style='height:%dpx' title='%s %s'><i>%s</i></div>" % (h, hh, fmt(v, 0), hh[3:])

    # ── 日评价近14天 ──
    day_rows = ""
    for d, aqi, pp, pm25, pm10, o3 in days:
        day_rows += ("<tr><td>%s</td><td class='num'>%s</td><td>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td></tr>") % (
            d[5:], chip(aqi), (pp or "—"), fmt(pm25, 0), fmt(pm10, 0), fmt(o3, 0))

    # ── 预报文字 ──
    if fcst:
        ftxt = ("未来 %d 小时（模式）：PM2.5 相对高值约 <b>%s</b>，O₃ 相对高值约 <b>%s</b>。"
                % (fcst["n"], fcst["pm_peak"] or "—", fcst["o3_peak"] or "—"))
    else:
        ftxt = "未来预报未取到位（CAMS 文件缺失或该城市未覆盖）。"

    primary = POLL_CN.get(b["poll_rt"], b["poll_rt"]) if b["poll_rt"] else "优（无首要）"
    feat = "局地源特征" if b["feature"] == "局地" else "区域同步抬升"

    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s大气一页纸</title>
<style>%s</style></head><body><div class="wrap">
<div class="stamp">AI 草稿<br>未经审定</div>
<h1>%s · 大气一页纸</h1>
<div class="sub">数据时点 %s（实时小时值）｜ 所属档案 %s ｜ 生成 %s</div>

<div class="cards">
<div class="card"><div class="k">实时城市 AQI（点位平均）</div><div class="v">%s</div></div>
<div class="card"><div class="k">首要污染物（IAQI最大）</div><div class="v" style="font-size:17px">%s</div></div>
<div class="card"><div class="k">点位均值 / 最差</div><div class="v" style="font-size:17px">%s / %s</div></div>
<div class="card"><div class="k">点位数 / 特征</div><div class="v" style="font-size:17px">%d / %s</div></div>
</div>

<section><h2>一、核心污染物（实时 / 24h滑动）</h2>
<div class="tscroll"><table>
<tr><th>指标</th><th>实时浓度</th><th>24h滑动均值</th><th>口径</th></tr>
<tr><td>PM2.5</td><td class='num'>%s μg/m³</td><td class='num'>%s μg/m³</td><td>点位平均</td></tr>
<tr><td>PM10</td><td class='num'>%s μg/m³</td><td class='num'>%s μg/m³</td><td>点位平均</td></tr>
<tr><td>O₃-8h</td><td class='num'>%s μg/m³</td><td class='num'>—</td><td>实时8h值（筛查口径）</td></tr>
<tr><td>NO₂</td><td class='num'>%s μg/m³</td><td class='num'>—</td><td>点位平均</td></tr>
<tr><td>SO₂</td><td class='num'>%s μg/m³</td><td class='num'>—</td><td>点位平均</td></tr>
<tr><td>CO</td><td class='num'>%s mg/m³</td><td class='num'>—</td><td>点位平均</td></tr>
</table></div>
<p class="legend">O₃-8h 用<b>当前8小时值</b>比对日均限值 160 仅作<b>筛查信号</b>，GB 3095-2012 评价对象为<b>日最大8小时滑动平均</b>，二者不可混用；当日是否超标须待数据完整复核。</p>
</section>

<section><h2>二、点位清单（全部 %d 个，AQI 降序）</h2>
<div class="tscroll"><table>
<tr><th>点位</th><th>AQI</th><th>首要污染物</th><th>PM2.5</th><th>PM10</th><th>O₃-8h</th></tr>
%s</table></div></section>

<section><h2>三、近 24 小时 AQI 趋势（点位均值）</h2>
<div class="bars">%s</div>
<p class="legend">每根代表该小时全市点位平均 AQI；峰值出现在 %s。</p></section>

<section><h2>四、日评价回顾（近 14 天，平台日评价口径）</h2>
<div class="tscroll"><table>
<tr><th>日期</th><th>日 AQI</th><th>首要</th><th>PM2.5</th><th>PM10</th><th>O₃-8h</th></tr>
%s</table></div></section>

<section><h2>五、未来模式趋势（CAMS，未订正）</h2>
<p>%s</p>
<p class="legend">CAMS 为城市尺度模式产品（≈40km 网格），<b>不作合规判据</b>；已知对本市 PM2.5 偏高、臭氧明显低估。
本节<b>只给相对高值时段</b>，<b>不报绝对 AQI</b>，亦不得用"模式未超160"推断"不会臭氧超标"。</p></section>

<p class="note">红线：①平台 AQI 为实时小时值，非日均/未审核，对外结论以总站/省级审核数据为准；
②城市评价值按 HJ 663-2013 取点位平均；③本页为 AI 草稿，未经审定。</p>
</div></body></html>""" % (
        cname, CSS, cname, tp, region or "—", now,
        chip(b["aqi_rt"]), primary, fmt(b["point_avg_aqi"], 0), fmt(b["aqi_max"], 0),
        b["n"], feat,
        fmt(b["pm25_mean"], 0), fmt(b["pm25_24h_mean"], 0),
        fmt(b["pm10_mean"], 0), fmt(b["pm10_24h_mean"], 0),
        fmt(b["o3_8h_mean"], 0),
        fmt(b["no2_mean"], 0), fmt(b["so2_mean"], 0), fmt(b["co_mean"], 2),
        b["n"], st_rows, bars,
        (max(tr, key=lambda x: x[1])[0] if tr else "—"), day_rows, ftxt,
    )
