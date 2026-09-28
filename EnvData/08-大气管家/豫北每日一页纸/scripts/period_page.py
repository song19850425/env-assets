# -*- coding: utf-8 -*-
"""交付层：周报/月报页面（结构对标第三方周报样例：概况→逐日→环比→污染特征→结论建议）"""
from datetime import datetime
from calc.aqi_stats import aqi_level
from calc.period_stats import POLL, arrow


def _fmt(v, unit_pct=False):
    return "—" if v is None else ("%g" % v)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#F5F4F0;color:#2B2B28;font-size:14px;line-height:1.7}
.page{max-width:920px;margin:16px auto;background:#fff;border:1px solid #E2E0D8;border-radius:12px;padding:30px 36px}
.hd{border-bottom:3px solid #1F5C45;padding-bottom:12px;margin-bottom:16px;display:flex;justify-content:space-between}
.hd h1{font-size:21px;color:#1F3B2C}
.hd .sub{font-size:13px;color:#888780;margin-top:4px}
.stamp{border:2px solid #A32D2D;color:#A32D2D;border-radius:8px;padding:6px 12px;font-size:13px;font-weight:600;text-align:center;transform:rotate(-4deg);height:fit-content}
h2{font-size:15px;color:#1F3B2C;margin:20px 0 8px;border-left:4px solid #1F5C45;padding-left:8px}
h3{font-size:14px;color:#3A5C4C;margin:12px 0 6px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}
th{background:#1F3B2C;color:#fff;padding:6px 8px;text-align:left;font-weight:500}
td{padding:5px 8px;border-bottom:1px solid #ECEAE2}
p{margin:8px 0;font-size:13.5px}
.up{color:#A32D2D}.down{color:#2E6B0F}
.note{background:#FDF3E7;border:1px solid #E8C99F;border-radius:8px;padding:9px 13px;font-size:12.5px;margin:10px 0}
.ft{margin-top:20px;padding-top:10px;border-top:1px solid #E2E0D8;font-size:12px;color:#888780}
@media print{body{background:#fff}.page{border:none;margin:0}}
"""


def render_period(kind, title, period_desc, stats_list, cfg, window_note=""):
    """kind: weekly/monthly；stats_list: 各城市 city_period_stats 结果"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sample = cfg.get("sample", True)
    stamp = "<div class='stamp'>AI 草稿<br>未经审定</div>" if sample else ""
    cn = "周报" if kind == "weekly" else "月报"

    # 一、概况对比表
    overview = """<table><tr><th>城市</th><th>期均AQI</th><th>优良天数</th><th>优良率</th>
<th>轻度污染</th><th>中度及以上</th><th>PM2.5均值</th><th>首要污染物（频次前三）</th></tr>"""
    for s in stats_list:
        freq = "、".join("%s×%d" % (k.split("(")[0], v) for k, v in s["primary_freq"]) or "—"
        overview += "<tr><td><b>%s</b></td><td>%s</td><td>%d 天</td><td>%.0f%%</td><td>%d 天</td><td>%d 天</td><td>%s</td><td>%s</td></tr>" % (
            s["city"], _fmt(s["mean_aqi"]), s["good"], s["good_rate"], s["light"], s["mid_plus"],
            _fmt(s["means"]["pm25"]), freq)
    overview += "</table>"

    # 二、逐日明细（每城一张小表）
    daily = ""
    for s in stats_list:
        daily += "<h3>%s（%d 天）</h3><table><tr><th>日期</th><th>AQI</th><th>级别</th><th>首要污染物</th><th>PM2.5</th><th>PM10</th><th>O₃-8h</th></tr>" % (
            s["city"], s["n"])
        for r in s["rows"]:
            name, bg, fg = aqi_level(r["aqi"])
            a = "—" if r["aqi"] is None else "%d" % r["aqi"]
            chip = "<span style='background:%s;color:%s;padding:1px 8px;border-radius:5px'>%s</span>" % (bg, fg, a)
            daily += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                r["date"][5:], chip, name, r["primary"] or "—",
                _fmt(r["pm25"]), _fmt(r["pm10"]), _fmt(r["o3_8h"]))
        daily += "</table>"

    # 三、环比表（本期均值 / 上期均值 / 变化率）
    huanbi = """<table><tr><th>城市</th><th>污染物</th><th>本期均值</th><th>上期均值</th><th>环比变化</th></tr>"""
    for s in stats_list:
        first = True
        for k, label, unit in POLL:
            ch = s["changes"][k]
            cls = "up" if (ch is not None and ch > 0) else ("down" if (ch is not None and ch < 0) else "")
            huanbi += "<tr>%s<td>%s</td><td>%s</td><td>%s %s</td><td>%s %s</td><td class='%s'>%s</td></tr>" % (
                "" if first else "<td></td>", s["city"] if first else "", label,
                _fmt(s["means"][k]), unit, _fmt(s["means_prev"][k]), unit, cls, arrow(ch))
            first = False
    huanbi += "</table>"

    # 四、污染特征 + 颗粒物
    feat = "<p>"
    for s in stats_list:
        if s["primary_freq"]:
            top = s["primary_freq"][0]
            feat += "<b>%s</b>：首要污染物以 <b>%s</b> 为主（%d/%d 天）；" % (
                s["city"], top[0].split("(")[0], top[1], s["n"])
    feat += "</p><p><b>PM2.5/PM10 比值</b>（细颗粒物占比，均值）："
    feat += " ｜ ".join("<b>%s</b> %.1f%%" % (s["city"], s["ratio"]) for s in stats_list if s["ratio"] is not None)
    feat += "。比值偏高提示二次生成与扬尘占比结构变化，需结合组分数据进一步溯源。"
    feat += "</p>"
    if s_worst := [x for x in stats_list if x["worst"]]:
        w = max(s_worst, key=lambda x: x["worst"]["aqi"])
        feat += "<p>期内最差日：<b>%s %s</b>（AQI %d，%s，首要污染物 %s）。</p>" % (
            w["city"], w["worst"]["date"], w["worst"]["aqi"], w["worst"]["quality"], w["worst"]["primary"])

    # 五、结论与建议（月报段名按样例；全部由统计量推导）
    concl = "<p>"
    for s in stats_list:
        trend = "改善" if all((s["changes"][k] is None) or (s["changes"][k] <= 0) for k, _, _ in POLL) else \
                "承压" if all((s["changes"][k] is not None) and (s["changes"][k] >= 0) for k, _, _ in POLL) else "涨跌互现"
        concl += "<b>%s</b> 本期优良率 %.0f%%，较上期 %s；六项污染物环比以%s为主。" % (
            s["city"], s["good_rate"], trend,
            "上升" if sum(1 for k, _, _ in POLL if (s['changes'][k] or 0) > 0) >= 3 else "下降")
    concl += " 建议关注首要污染物对应的排放源管控（%s），并在下一期跟踪环比变化是否收敛。</p>" % (
        "、".join(sorted({x["primary_freq"][0][0].split("(")[0] for x in stats_list if x["primary_freq"]})))

    feat = "<h2>四、污染特征与颗粒物分析</h2>" + feat

    concl_html = "<h2>五、结论与建议</h2>" + concl if kind == "monthly" else \
                 "<h2>五、结论与建议（简）</h2>" + concl

    return """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>%s</title><style>%s</style></head><body><div class="page">
<div class="hd"><div><h1>%s</h1>
<div class="sub">%s ｜ 服务对象：%s ｜ 生成：%s</div></div>%s</div>
%s
<h2>一、空气质量概况</h2>%s
<h2>二、逐日明细</h2>%s
<h2>三、环比分析（本期均值 vs 上期均值）</h2>%s
%s
%s
<div class="ft">数据来源：%s%s<br>
%s 期数：第 %s 期 ｜ 本页由自动化流水线生成，结论段须经专家审定后方可对外使用，不作为行政决策或处罚依据。<br>
大气管家 · 大气环境第三方服务</div>
</div></body></html>""" % (
        title, CSS, title, period_desc, cfg.get("client_name", ""), now, stamp,
        window_note, overview, daily, huanbi, feat, concl_html,
        cfg.get("source", ""), ("（样报演示）" if sample else ""),
        cn, "%s" % datetime.now().strftime("%Y") + ("W%02d" % datetime.now().isocalendar()[1] if kind == "weekly" else datetime.now().strftime("%m")))
