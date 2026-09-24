# -*- coding: utf-8 -*-
"""交付层：每日一页纸（浅色专业版，可直接打印/转发；样报模式带未审定水印）"""
from datetime import datetime
from calc.aqi_stats import aqi_level


def _chip(aqi):
    name, bg, fg = aqi_level(aqi)
    a = "—" if aqi is None else ("%d" % aqi)
    return "<span style='background:%s;color:%s;padding:2px 10px;border-radius:6px;font-weight:600'>%s %s</span>" % (bg, fg, a, name)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#F5F4F0;color:#2B2B28;font-size:14px;line-height:1.6}
.page{max-width:900px;margin:16px auto;background:#fff;border:1px solid #E2E0D8;border-radius:12px;padding:28px 32px}
.hd{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #1F5C45;padding-bottom:14px;margin-bottom:18px}
.hd h1{font-size:22px;color:#1F3B2C}
.hd .sub{font-size:13px;color:#888780;margin-top:4px}
.stamp{border:2px solid #A32D2D;color:#A32D2D;border-radius:8px;padding:6px 12px;font-size:13px;font-weight:600;text-align:center;transform:rotate(-4deg)}
.cards{display:flex;gap:12px;margin:14px 0 20px}
.card{flex:1;background:#FAF9F5;border:1px solid #E2E0D8;border-radius:10px;padding:14px 16px}
.card .k{font-size:13px;color:#888780}
.card .v{font-size:26px;font-weight:700;margin:2px 0}
.card .n{font-size:12px;color:#888780}
h2{font-size:15px;color:#1F3B2C;margin:18px 0 8px;border-left:4px solid #1F5C45;padding-left:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1F3B2C;color:#fff;padding:7px 8px;text-align:left;font-weight:500}
td{padding:6px 8px;border-bottom:1px solid #ECEAE2}
tr.warn td{background:#FFF6E8}
.ft{margin-top:18px;padding-top:10px;border-top:1px solid #E2E0D8;font-size:12px;color:#888780}
.tip{background:#FDF3E7;border:1px solid #E8C99F;border-radius:8px;padding:10px 14px;font-size:13px;margin:10px 0}
@media print{body{background:#fff}.page{border:none;margin:0}}
"""


def render(summaries, timepoint, cfg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sample = cfg.get("sample", True)
    stamp = "<div class='stamp'>AI 草稿<br>未经审定</div>" if sample else ""

    cards_html = ""
    for c in summaries:
        worst_name = c["worst"]["station_name"] if c["worst"] else "—"
        cards_html += """
<div class="card"><div class="k">%s · 综合（%d 个点位）</div>
<div class="v">%s</div>
<div class="n">首要污染物 %s ｜ 最差点位：%s ｜ 超标点位 %d 个</div></div>""" % (
            c["city"], c["n"], _chip(c["aqi_max"]), c["primary"] or "—", worst_name, c["exceed_cnt"])

    tips = ""
    for c in summaries:
        if c["exceed_cnt"]:
            tips += "<div class='tip'><b>【%s 高值提示】</b>%d 个点位 AQI&gt;100，最差 %s（AQI %d，%s）。建议关注 %s。</div>" % (
                c["city"], c["exceed_cnt"], c["worst"]["station_name"],
                c["worst"]["aqi"], c["worst"]["primary_pollutant"] or "—",
                "颗粒物" if (c["worst"]["pm25"] or 0) >= 75 else "O₃/NO₂ 传输与本地叠加")

    body_rows = ""
    for c in summaries:
        for s in c["stations"]:
            warn = " class='warn'" if (s["aqi"] or 0) > 100 else ""
            body_rows += ("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
                warn, c["city"], s["station_name"], s["quality"] or "—",
                _chip(s["aqi"]),
                fmt(s["pm25"]), fmt(s["pm25_24h"]), fmt(s["pm10"]), fmt(s["o3_8h"]))

    return """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>大气管家 · 每日一页纸</title><style>%s</style></head><body><div class="page">
<div class="hd"><div><h1>大气管家 · 每日一页纸%s</h1>
<div class="sub">服务对象：%s ｜ 数据时点：%s ｜ 生成：%s</div></div>%s</div>
%s
<h2>城市综合</h2><div class="cards">%s</div>
<h2>点位明细（按 AQI 降序，超标点位底色标出）</h2>
<table><tr><th>城市</th><th>点位</th><th>等级</th><th>AQI</th><th>PM2.5</th><th>PM2.5·24h</th><th>PM10</th><th>O₃-8h</th></tr>%s</table>
<div class="ft">数据来源：%s<br>
本页由自动化流水线生成%s，结论段须经专家审定后方可对外使用；不作为行政处罚或行政决策依据。<br>
大气管家 · 大气环境第三方服务 · %s</div>
</div></body></html>""" % (
        CSS, "（样报）" if sample else "", cfg.get("client_name", ""),
        timepoint, now, stamp, tips, cards_html, body_rows,
        cfg.get("source", ""), "（样报演示）" if sample else "",
        now[:10])


def fmt(v):
    return "—" if v is None else ("%g" % v)
