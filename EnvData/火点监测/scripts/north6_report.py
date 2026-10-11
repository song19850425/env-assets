# -*- coding: utf-8 -*-
"""华北六省（山河四省 + 京津）火点与空气质量对比。

核心问题：火点多的省，是不是空气也最差？
数据：
  · data/north6/summary.json          六省两年火点统计（FIRMS VIIRS 375m）
  · data/stations/aqi-north6.json     六省冬季 15 天国控点均值
用法：python north6_report.py
"""
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C
ORDER = ["河北", "山西", "山东", "河南", "天津", "北京"]
COLOR = {"河北": "#f97316", "山西": "#a78bfa", "山东": "#38bdf8",
         "河南": "#ef4444", "天津": "#34d399", "北京": "#fbbf24"}


def esc(s):
    return AR._esc(s)


def spearman(x, y):
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean(); ry -= ry.mean()
    return float((rx * ry).sum() / math.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def svg_hbar(items, w=880, row_h=30, lab_w=76, val_w=150, unit="", fmt="{:,.0f}",
             colors=None):
    mx = max(v for _, v in items) or 1
    h = row_h * len(items) + 10
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i, (lab, v) in enumerate(items):
        y = 5 + i * row_h
        bw = max(2, pw * v / mx)
        col = (colors or {}).get(lab, C["accent"])
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 8, y + 19, C["txt"], esc(lab)))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="%d" rx="4" fill="%s" opacity="0.88"/>'
                 % (lab_w, y + 5, bw, row_h - 12, col))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12">%s%s</text>'
                 % (lab_w + bw + 8, y + 19, C["dim"], fmt.format(v), unit))
    p.append("</svg>")
    return "".join(p)


def svg_scatter(rows, w=880, h=440, pad=54):
    """火点数（x，对数）vs PM2.5（y）。"""
    xs = [r["fire"] for r in rows]
    ys = [r["pm25"] for r in rows]
    lx = [math.log10(v) for v in xs]
    x0, x1 = min(lx) - 0.15, max(lx) + 0.15
    y0, y1 = min(ys) - 6, max(ys) + 6
    pw, ph = w - pad - 110, h - pad - 54
    def X(v): return pad + pw * (math.log10(v) - x0) / (x1 - x0)
    def Y(v): return pad + ph - ph * (v - y0) / (y1 - y0)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#0b1220" rx="8"/>'
             % (pad, pad, pw, ph))
    for i in range(5):
        y = pad + ph * i / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pad, y, pad + pw, y, C["line"]))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="10" text-anchor="end">%.0f</text>'
                 % (pad - 6, y + 4, C["dim2"], y1 - (y1 - y0) * i / 4))
    for i in range(5):
        x = pad + pw * i / 4
        v = 10 ** (x0 + (x1 - x0) * i / 4)
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="10" text-anchor="middle">%s</text>'
                 % (x, pad + ph + 16, C["dim2"],
                    ("%.0f万" % (v / 10000)) if v >= 10000 else "%.0f" % v))
    p.append('<text x="%.1f" y="%d" fill="%s" font-size="12" text-anchor="middle">'
             '两年火点数（对数轴）</text>' % (pad + pw / 2, pad + ph + 36, C["dim"]))
    p.append('<text x="%d" y="%d" fill="%s" font-size="12" transform="rotate(-90 %d %d)">'
             '冬季 PM2.5 (μg/m³)</text>' % (pad - 38, pad + ph / 2, C["dim"], pad - 38, pad + ph / 2))
    for r in rows:
        x, y = X(r["fire"]), Y(r["pm25"])
        col = COLOR.get(r["prov"], C["accent"])
        p.append('<circle cx="%.1f" cy="%.1f" r="11" fill="%s" opacity="0.85" '
                 'stroke="#fff" stroke-width="1.5"/>' % (x, y, col))
        p.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="12" text-anchor="middle" '
                 'font-weight="600">%s</text>' % (x, y + 4, esc(r["prov"][0])))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11" text-anchor="middle">%s</text>'
                 % (x, y + 25, col, esc(r["prov"])))
    p.append("</svg>")
    return "".join(p)


def main():
    sm = json.load(open(os.path.join(MOD, "data", "north6", "summary.json"), encoding="utf-8"))
    aq = json.load(open(os.path.join(MOD, "data", "stations", "aqi-north6.json"), encoding="utf-8"))
    rows = []
    for pv in ORDER:
        s, a = sm[pv], aq[pv]
        rows.append(dict(prov=pv, fire=s["fire"], pts=s["pts"], hot=s["hot"], hotf=s["hotf"],
                         pct=s["pct"], hi=s["hi"], night=s["hotnight"], frp=s["hotfrp"],
                         aqi=a["AQI"], pm25=a["PM2.5"], pm10=a["PM10"], so2=a["SO2"],
                         no2=a["NO2"], ratio=a["PM2.5"] / a["PM10"]))

    r_fire = spearman([r["fire"] for r in rows], [r["pm25"] for r in rows])
    r_hot = spearman([r["hot"] for r in rows], [r["pm25"] for r in rows])
    r_so2 = spearman([r["fire"] for r in rows], [r["so2"] for r in rows])
    tot_fire = sum(r["fire"] for r in rows)
    tot_hot = sum(r["hot"] for r in rows)

    fire_bar = svg_hbar([(r["prov"], r["fire"]) for r in rows], colors=COLOR, unit=" 条")
    hot_bar = svg_hbar([(r["prov"], r["hot"]) for r in rows], colors=COLOR, unit=" 个")
    pm_bar = svg_hbar([(r["prov"], r["pm25"]) for r in rows], colors=COLOR,
                      unit=" μg/m³", fmt="{:.1f}")
    so2_bar = svg_hbar([(r["prov"], r["so2"]) for r in rows], colors=COLOR,
                       unit=" μg/m³", fmt="{:.1f}")
    scatter = svg_scatter(rows)

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>华北六省火点与空气质量对比</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>华北六省火点与空气质量对比</h1>',
         '<div class="sub">山河四省 + 京津　·　火点：FIRMS VIIRS 375m 2024–2025　·　'
         '空气质量：国控点冬季 15 天均值　·　生成于 %s</div>' % dt]

    h.append('<div class="card" style="border-color:#f97316"><h2>核心结论</h2>'
             '<div style="font-size:18px;line-height:1.8">'
             '<span class="hl">火点最多的省，不是空气最差的省。</span>'
             '</div>'
             '<div class="note">河北两年火点 <b>%s 条</b>（是河南的 %.1f 倍）、'
             '持续排放点位 <b>%d 个</b>（河南的 %.1f 倍）—— 六省第一。'
             '但它的冬季 PM2.5 是 <b>%.1f</b>，<b>低于河南的 %.1f</b>。<br>'
             '六省的火点数排名与 PM2.5 排名的 Spearman 相关系数 = <b>%.2f</b>'
             '（火点数 vs 持续点位数：<b>%.2f</b>；vs SO₂：<b>%.2f</b>）。'
             '也就是说：<b>在省级尺度上，火点数量解释不了空气质量差异</b>。</div></div>'
             % (format(rows[0]["fire"], ","), rows[0]["fire"] / rows[3]["fire"],
                rows[0]["hot"], rows[0]["hot"] / rows[3]["hot"],
                rows[0]["pm25"], rows[3]["pm25"], r_fire, r_hot, r_so2))

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>六省两年火点合计</span></div>'
             '<div><b>%d</b><span>持续排放点位（≥10 天）</span></div>'
             '<div><b>%s</b><span>河北火点（六省第一）</span></div>'
             '<div><b>%d</b><span>北京持续点位（最少）</span></div>'
             '</div>' % (format(tot_fire, ","), tot_hot,
                         format(rows[0]["fire"], ","), rows[5]["hot"]))

    h.append('<div class="card"><h2>一、火点维度</h2>'
             '%s'
             '<div class="note">河北 %s 条、山西 %s 条，两个省占了六省总量的 %.0f%%。'
             '北京只有 %s 条 —— 与河北差 <b>%.0f 倍</b>。</div></div>'
             % (fire_bar, format(rows[0]["fire"], ","), format(rows[1]["fire"], ","),
                (rows[0]["fire"] + rows[1]["fire"]) / tot_fire * 100,
                format(rows[5]["fire"], ","), rows[0]["fire"] / rows[5]["fire"]))

    h.append('<div class="card"><h2>二、持续排放点位（≥10 天）</h2>'
             '%s'
             '<table><tr><th>省/市</th><th class="num">持续点位</th>'
             '<th class="num">贡献火点</th><th class="num">占本省</th>'
             '<th class="num">最高天数</th><th class="num">夜间占比中位</th>'
             '<th class="num">FRP 中位</th></tr>' % hot_bar)
    for r in rows:
        h.append('<tr><td><b>%s</b></td><td class="num">%d</td><td class="num">%s</td>'
                 '<td class="num">%.1f%%</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f MW</td></tr>'
                 % (esc(r["prov"]), r["hot"], format(r["hotf"], ","), r["pct"],
                    r["hi"], r["night"], r["frp"]))
    h.append('</table>'
             '<div class="note"><b>两个值得注意的点</b>：<br>'
             '· <b>河北的「持续点占比」高达 %.1f%%</b>（河南 %.1f%%）—— '
             '河北的火点更集中、更持续，散点少；<br>'
             '· <b>六省的夜间占比中位都在 %.0f–%.0f%%、FRP 中位 %.2f–%.2f MW</b> —— '
             '特征高度一致，说明「工业闷烧」是整个华北平原的共性问题，不是某个省的特产。'
             '</div></div>'
             % (rows[0]["pct"], rows[3]["pct"],
                min(r["night"] for r in rows), max(r["night"] for r in rows),
                min(r["frp"] for r in rows), max(r["frp"] for r in rows)))

    h.append('<div class="card"><h2>三、空气质量维度（冬季 15 天国控点均值）</h2>'
             '%s'
             '<table><tr><th>省/市</th><th class="num">AQI</th><th class="num">PM2.5</th>'
             '<th class="num">PM10</th><th class="num">PM2.5/PM10</th>'
             '<th class="num">SO₂</th><th class="num">NO₂</th><th>特征</th></tr>' % pm_bar)
    for r in rows:
        if r["ratio"] >= 0.60:
            tag, col = "燃烧 / 二次型", "#ef4444"
        elif r["ratio"] <= 0.45:
            tag, col = "扬尘 / 煤尘型", "#fbbf24"
        else:
            tag, col = "混合", "#94a3b8"
        h.append('<tr><td><b>%s</b></td><td class="num">%.0f</td><td class="num">%.1f</td>'
                 '<td class="num">%.0f</td><td class="num">%.2f</td>'
                 '<td class="num">%.1f</td><td class="num">%.0f</td>'
                 '<td style="color:%s">%s</td></tr>'
                 % (esc(r["prov"]), r["aqi"], r["pm25"], r["pm10"], r["ratio"],
                    r["so2"], r["no2"], col, tag))
    h.append('</table>'
             '<div class="note"><b>PM2.5/PM10 比值</b>是区分污染类型的简易指标：'
             '接近或超过 0.6 说明细颗粒占主导（燃烧 + 二次生成）；'
             '低于 0.45 说明粗颗粒多（扬尘、煤尘）。<br>'
             '<b>山西是六省里唯一的「扬尘/煤尘型」</b>（%.2f）—— '
             'PM10 高达 %.0f（六省第二），但 PM2.5 只有 %.1f（六省第五）。'
             '结合它 416 个持续火点，很可能是<b>煤矸石/煤堆自燃</b>为主，'
             '而不是钢铁焦化那种高温燃烧。</div></div>'
             % (rows[1]["ratio"], rows[1]["pm10"], rows[1]["pm25"]))

    h.append('<div class="card"><h2>四、交叉看：火点 vs 空气质量的错位</h2>'
             '%s'
             '<div class="note">横轴是火点数（对数），纵轴是冬季 PM2.5。'
             '如果火点是空气差的主因，点应该从左下往右上排 —— '
             '但实际是<b>散乱的</b>：山西（火点第二、PM2.5 第五）、'
             '河南（火点第四、PM2.5 第一）、天津（火点第五、PM2.5 第四）。<br>'
             '<b>相关系数 %.2f</b>，几乎不相关。</div></div>' % (scatter, r_fire))

    h.append('<div class="card"><h2>五、分省画像</h2>'
             '<table><tr><th>省/市</th><th>火点特征</th><th>空气特征</th><th>判断</th></tr>'
             '<tr><td><b>河北</b></td><td>火点第一（%s），持续点位 %d 个，'
             '占比 %.1f%% 最高</td><td>PM2.5 %.1f、PM10 %.0f，AQI %.0f</td>'
             '<td>火点与污染<b>双高</b>，但火点不是唯一原因（传输、扬尘、'
             '钢铁有组织排放都在）</td></tr>'
             '<tr><td><b>山西</b></td><td>火点第二（%s），持续点位 %d 个</td>'
             '<td>PM2.5 仅 %.1f 但 PM10 %.0f（比值 %.2f）</td>'
             '<td><b>煤尘型</b>：火点很可能是煤矸石/煤堆自燃，'
             '治理路径与钢铁焦化不同</td></tr>'
             '<tr><td><b>山东</b></td><td>火点第三（%s），点位最多（%s）但持续占比低（%.1f%%）</td>'
             '<td>SO₂ 六省最高（%.1f）</td>'
             '<td>工业大省，火点<b>分散</b>，以点源+区域为主</td></tr>'
             '<tr><td><b>河南</b></td><td>火点第四（%s），持续点位 %d 个</td>'
             '<td><b>PM2.5 六省最高（%.1f）</b>，AQI 最高</td>'
             '<td>火点不是最多，但空气最差 —— '
             '<b>说明河南的污染主因在火点之外</b>（传输、盆地地形、有组织排放）</td></tr>'
             '<tr><td><b>天津</b></td><td>火点第五（%s）</td>'
             '<td>NO₂ 六省最高（%.1f）</td>'
             '<td>港口 + 重卡特征明显，与工业火点关系不大</td></tr>'
             '<tr><td><b>北京</b></td><td>火点最少（%s），持续点位仅 %d 个</td>'
             '<td>各项最低，SO₂ 仅 %.1f</td>'
             '<td>产业结构疏解后，本地工业源已很少</td></tr>'
             '</table></div>'
             % (format(rows[0]["fire"], ","), rows[0]["hot"], rows[0]["pct"],
                rows[0]["pm25"], rows[0]["pm10"], rows[0]["aqi"],
                format(rows[1]["fire"], ","), rows[1]["hot"],
                rows[1]["pm25"], rows[1]["pm10"], rows[1]["ratio"],
                format(rows[2]["fire"], ","), format(rows[2]["pts"], ","), rows[2]["pct"],
                rows[2]["so2"],
                format(rows[3]["fire"], ","), rows[3]["hot"], rows[3]["pm25"],
                format(rows[4]["fire"], ","), rows[4]["no2"],
                format(rows[5]["fire"], ","), rows[5]["hot"], rows[5]["so2"]))

    h.append('<div class="card"><h2>六、结论</h2>'
             '<div class="big">'
             '火点是「工业活动强度」的指示器，不是「空气质量」的解释变量。'
             '</div>'
             '<div class="note">'
             '① <b>火点与 PM2.5 在省级尺度上几乎不相关（r=%.2f）</b>。'
             '把火点数当作空气质量的替代表现，会得出错误结论。<br>'
             '② <b>但火点的价值不在解释浓度，而在指认排放行为</b>：'
             '六省合计 %d 个持续排放点位，每一个都是可交办的具体对象。<br>'
             '③ <b>区域差异比总量更重要</b>：山西的「煤尘型」、天津的「港口型」、'
             '河南的「复合型」，治理手段完全不同 —— '
             '用同一张表考核六省，是典型的一刀切。<br>'
             '④ <b>跨省联防有依据</b>：太行山前城市带（邢台—邯郸—安阳—鹤壁—新乡—焦作）'
             '横跨河北、河南两省，汾渭平原与山西、河南相连，'
             '单省减排会被传输抵消。</div></div>'
             % (r_fire, tot_hot))

    h.append('<footer>'
             '数据来源：NASA FIRMS VIIRS 375m（VIIRS_SNPP_SP + VIIRS_NOAA20_SP，'
             '2024–2025）· 中国环境监测总站国控点（经 quotsoft.net 逐小时归档）· '
             'DataV.GeoAtlas 省界<br>'
             '方法：火点按 0.01° 网格聚合 → 出现 ≥10 天判为持续排放点位 → '
             '按省界射线法归属；空气质量取冬季 15 天（2025-12-15~19 + 2026-01-05~14）均值<br>'
             '<b>边界声明</b>：省级均值掩盖了省内差异；火点归属依赖省界数据精度，'
             '边界附近点位可能误归；火点数量与浓度的相关性是<b>统计描述</b>，'
             '不构成因果推断。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "华北六省火点与空气质量对比.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("火点 vs PM2.5 r = %.2f ｜ 持续点位 vs PM2.5 r = %.2f ｜ 火点 vs SO2 r = %.2f"
          % (r_fire, r_hot, r_so2))


if __name__ == "__main__":
    main()
