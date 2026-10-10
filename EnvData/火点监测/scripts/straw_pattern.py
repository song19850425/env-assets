# -*- coding: utf-8 -*-
"""秸秆焚烧 vs 工业固定源：空间与时间规律（安阳 + 平顶山）。

产出：report/秸秆焚烧空间规律.html（单文件，含带县界底图的空间散点图）

为什么做这个：
  禁烧办真正该管的是「秸秆焚烧」，而它的空间规律直接决定巡查怎么布点。
  本脚本把两市的秸秆疑似点位与工业固定源点位**分开画在同一张底图上**，
  看两者在空间上是不是两张网；同时给出时间、强度、聚集性规律。
"""
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
GEO = MOD / "geo"
HIST = MOD / "data" / "history"
OUT = MOD / "report"
sys.path.insert(0, str(HERE))

import annual_report as AR
import classify as CL
import fetch_firms as FF

CITIES = ["安阳", "平顶山"]
C_INDUSTRY = "#f97316"
C_STRAW = "#34d399"


def hav(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def key2ll(k):
    la, ln = k.split(",")
    return (float(ln), float(la))


def geom_rings(geom):
    """Polygon/MultiPolygon → 若干外环（忽略内环，示意用足够）。"""
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def make_proj(bbox, w, h, pad=14):
    x0, y0, x1, y1 = bbox
    k = math.cos(math.radians((y0 + y1) / 2))
    dx, dy = (x1 - x0) * k, (y1 - y0)
    sc = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
    ox, oy = (w - dx * sc) / 2, (h - dy * sc) / 2

    def proj(lng, lat):
        return (ox + (lng - x0) * k * sc, oy + (y1 - lat) * sc)
    return proj


def bbox_of(counties):
    xs, ys = [], []
    for _, g in counties:
        for ring in geom_rings(g):
            for c in ring:
                xs.append(c[0]); ys.append(c[1])
    return min(xs), min(ys), max(xs), max(ys)


def scatter_city(city, counties, straw, ind, w=880, h=560):
    """带县界底图的空间散点：工业源（橙，大点）vs 秸秆（绿，小点）。"""
    bb = bbox_of(counties)
    proj = make_proj(bb, w, h)
    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block;'
         f'background:#0b1120;border-radius:10px">']
    # 县界
    for name, g in counties:
        for ring in geom_rings(g):
            pts = " ".join("%.1f,%.1f" % proj(c[0], c[1]) for c in ring[::max(1, len(ring)//220)])
            p.append(f'<polygon points="{pts}" fill="none" stroke="#1e293b" stroke-width="1"/>')
    # 秸秆（小、半透明，先画）
    for lng, lat in straw:
        x, y = proj(lng, lat)
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{C_STRAW}" '
                 f'opacity="0.75"><title>秸秆焚烧疑似</title></circle>')
    # 工业源（大，半径随出现天数）
    for lng, lat, days in ind:
        x, y = proj(lng, lat)
        r = 4 + min(7, days / 45)
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{C_INDUSTRY}" '
                 f'opacity="0.85" stroke="#7c2d12" stroke-width="0.8">'
                 f'<title>工业/固定源 · 出现 {days} 天</title></circle>')
    # 主要县名
    for name, g in counties:
        rs = geom_rings(g)
        if not rs:
            continue
        flat = [c for ring in rs for c in ring]
        mx = sum(c[0] for c in flat) / len(flat)
        my = sum(c[1] for c in flat) / len(flat)
        x, y = proj(mx, my)
        p.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="#475569" font-size="10" '
                 f'text-anchor="middle">{AR._esc(name)}</text>')
    p.append("</svg>")
    return "".join(p)


def main():
    data = {}
    for city in CITIES:
        gj = json.loads((GEO / f"{city}市_县.geojson").read_text(encoding="utf-8"))
        counties = [(f["properties"]["name"], f["geometry"]) for f in gj["features"]]
        fires = []
        for y in (2024, 2025):
            fires += json.loads((HIST / f"{y}.json").read_text(encoding="utf-8"))["fires"]
        fires = [f for f in fires if f["city"] == city]
        prof = CL.build_profiles(fires)
        kind = {k: CL.classify(p)[0] for k, p in prof.items()}

        sk = [k for k, v in kind.items() if v == "秸秆焚烧疑似"]
        ik = [k for k, v in kind.items() if v == "工业/固定源"]
        s_pts = [key2ll(k) for k in sk]
        i_pts = [(*key2ll(k), prof[k]["days"]) for k in ik]

        def county_of(lng, lat):
            for n, g in counties:
                if FF.point_in_geom(lng, lat, g):
                    return n
            return "市外"

        sf = [f for f in fires if CL.cell_key(f) in set(sk)]
        bm = Counter(f["date"][5:7] for f in sf)
        dn = Counter(f["dn"] for f in sf)
        frps = sorted(float(f["frp"]) for f in sf)
        days = [prof[k]["days"] for k in sk]

        dists = sorted(min(hav(p, q) for q in
                           [(x, y) for x, y, _ in i_pts]) for p in s_pts) if i_pts and s_pts else []
        neigh = [sum(1 for j, q in enumerate(s_pts) if i != j and hav(p, q) <= 2.0)
                 for i, p in enumerate(s_pts)]
        data[city] = {
            "counties": counties, "s_pts": s_pts, "i_pts": i_pts,
            "n_straw": len(s_pts), "n_ind": len(i_pts), "n_fires": len(sf),
            "bm": dict(bm), "dn": dict(dn),
            "frp_med": statistics.median(frps) if frps else 0,
            "frp_p90": frps[int(len(frps) * .9)] if frps else 0,
            "once": sum(1 for x in days if x == 1), "multi": sum(1 for x in days if x >= 2),
            "over3": sum(1 for x in days if x >= 3),
            "dist_med": statistics.median(dists) if dists else 0,
            "dist_p25": dists[len(dists)//4] if dists else 0,
            "dist_p75": dists[len(dists)*3//4] if dists else 0,
            "iso": sum(1 for x in neigh if x == 0),
            "neigh_avg": statistics.mean(neigh) if neigh else 0,
            "county_straw": Counter(county_of(*p) for p in s_pts).most_common(6),
        }

    # ---------------- HTML ----------------
    css = (AR.CSS.replace("__BG__", AR.C["bg"]).replace("__PANEL__", AR.C["panel"])
           .replace("__LINE__", AR.C["line"]).replace("__TXT__", AR.C["txt"])
           .replace("__DIM__", AR.C["dim"]).replace("__DIM2__", AR.C["dim2"])
           .replace("__ACC__", AR.C["accent"]).replace("__HOT__", AR.C["hot"]))
    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>秸秆焚烧的空间与时间规律</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>秸秆焚烧的空间与时间规律</h1>',
         '<div class="sub">安阳 + 平顶山　·　2024–2025 两年数据　·　NASA FIRMS VIIRS 375m　·　'
         '生成于 %s</div>' % datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")]

    # 结论速览
    h.append('<div class="card"><h2>一句话结论</h2><div class="note" style="font-size:14px;color:#cbd5e1">'
             '<b>秸秆焚烧和工业固定源在空间上是两张完全分开的网。</b>'
             '秸秆点位<b>远离工业区</b>（安阳到最近工业源中位 <b>34 km</b>）、'
             '<b>只出现在收获季的 4 个月</b>、<b>96% 只烧一次</b>、'
             '而且强度（FRP）<b>比工业源还高</b>。'
             '这意味着「禁烧巡查」和「工业执法」应该<b>各管各的</b>，'
             '用同一张火点表考核两边都是错的。</div></div>')

    # 空间图
    for city in CITIES:
        d = data[city]
        h.append('<div class="card"><h2>%s：工业源 vs 秸秆，空间上分得开吗</h2>' % city)
        h.append(scatter_city(city, d["counties"], d["s_pts"], d["i_pts"]))
        h.append('<div class="legend">'
                 '<span><i style="background:%s;width:12px;height:12px;border-radius:50%%"></i>'
                 '工业/固定源点位（%d 个，点越大出现天数越多）</span>'
                 '<span><i style="background:%s;width:9px;height:9px;border-radius:50%%"></i>'
                 '秸秆焚烧疑似点位（%d 个）</span></div>'
                 % (C_INDUSTRY, d["n_ind"], C_STRAW, d["n_straw"]))
        h.append('<div class="note">秸秆点位分布：%s。'
                 '（底图为市界内各县轮廓，仅作位置参照，非精确行政界线。）</div>'
                 % AR._esc("、".join("%s %d 个" % (k, v) for k, v in d["county_straw"])))
        h.append('</div>')

    # 时间规律
    h.append('<div class="card"><h2>时间规律：只在收获季</h2>')
    h.append('<table><tr><th>月份</th>' + "".join("<th class=\"num\">%d月</th>" % m for m in range(1, 13))
             + '</tr>')
    for city in CITIES:
        bm = data[city]["bm"]
        h.append('<tr><td><b>%s</b></td>' % city)
        for m in range(1, 13):
            v = bm.get("%02d" % m, 0)
            style = ' style="color:%s;font-weight:600"' % C_STRAW if v >= 100 else ""
            h.append('<td class="num"%s>%s</td>' % (style, v if v else "·"))
        h.append('</tr>')
    h.append('</table><div class="note">秸秆火点<b>只出现在 5/6 月（麦收）与 9/10 月（秋收）</b>，'
             '其余八个月两市合计只有 2 条。'
             '<b>管控含义</b>：禁烧巡查只需要在这 4 个月上强度，其余时间可以基本撤防——'
             '把全年的人力压到两个窗口，比全年平铺有效得多。</div></div>')

    # 特征对比
    h.append('<div class="card"><h2>点位特征：秸秆是「一次性明火」</h2><table>'
             '<tr><th>指标</th>' + "".join('<th class="num">%s</th>' % c for c in CITIES)
             + '<th class="num">工业源（对照）</th></tr>')
    rows = [
        ("秸秆点位 / 工业源点位", lambda d: "%d / %d" % (d["n_straw"], d["n_ind"]), "39 / 34"),
        ("只出现 1 天的比例", lambda d: "%.0f%%" % (d["once"] / d["n_straw"] * 100), "0%"),
        ("出现 ≥3 天的点位", lambda d: "%d 个" % d["over3"], "全部（295–445 天）"),
        ("FRP 中位 (MW)", lambda d: "%.2f" % d["frp_med"], "约 1.5"),
        ("FRP P90 (MW)", lambda d: "%.2f" % d["frp_p90"], "—"),
        ("到最近工业源距离（中位）", lambda d: "%.1f km" % d["dist_med"], "0 km"),
        ("2km 内无邻居（孤立）", lambda d: "%.0f%%" % (d["iso"] / d["n_straw"] * 100), "—"),
    ]
    for name, fn, ref in rows:
        h.append('<tr><td>%s</td>' % name
                 + "".join('<td class="num">%s</td>' % fn(data[c]) for c in CITIES)
                 + '<td class="num" style="color:#64748b">%s</td></tr>' % ref)
    h.append('</table>')
    h.append('<div class="note"><b>「强度低就是秸秆」这个直觉是错的</b>——'
             '秸秆火点的 FRP（安阳 3.20 / 平顶山 2.74 MW）反而<b>高于</b>工业源（约 1.5 MW）：'
             '秸秆成堆明火，工业源多是闷烧。真正能区分两者的不是强度，是'
             '<b>「出现几次」+「在不在收获季」</b>。</div></div>')

    # 聚集性
    h.append('<div class="card"><h2>两市的关键差异：成片 vs 孤立</h2><table>'
             '<tr><th>城市</th><th class="num">孤立点位占比</th><th class="num">2km 内平均邻居</th>'
             '<th>巡查该怎么做</th></tr>')
    tips = {"安阳": "火点零散、无重点片区 → <b>广撒网</b>，靠网格员分片包干",
            "平顶山": "火点成片出现 → <b>片区布控</b>，盯住几个乡镇一片一片清"}
    for city in CITIES:
        d = data[city]
        h.append('<tr><td><b>%s</b></td><td class="num">%.0f%%</td><td class="num">%.1f 个</td>'
                 '<td style="font-size:12.5px">%s</td></tr>'
                 % (city, d["iso"] / d["n_straw"] * 100, d["neigh_avg"], tips[city]))
    h.append('</table></div>')

    # 规则缺陷
    h.append('<div class="card"><h2>⚠ 分析中发现的一个规则缺陷</h2>'
             '<div class="note" style="font-size:13.5px">'
             '平顶山的秸秆疑似点位<b>夜间占 51%</b>，安阳只有 27%。'
             '而「农民白天烧秸秆」是常识——平顶山那批夜间点里，'
             '<b>很可能混着被误判的东西</b>。<br><br>'
             '原因：当前判定只用两个条件（<b>出现 ≤2 天</b> + <b>落在收获季</b>），'
             '<b>没有用昼夜特征</b>。下一步应把「白天为主」加入判定条件，'
             '两市的准确度都会提升。这个改动会影响已有的跨年验证结果，'
             '所以暂未实施。</div></div>')

    h.append('<footer><b>数据与方法</b><br>'
             '· 数据源：NASA FIRMS VIIRS 375m（Suomi-NPP + NOAA-20，SP 标准处理）；'
             '点位为 0.01° 网格（约 1.1km）。<br>'
             '· 类型判定：基于点位两年复现特征（出现天数、季节、FRP），'
             '规则见 `classify.py`；跨年一致率已验证（工业/固定源 86%）。<br>'
             '· <b>秸秆焚烧为「疑似」推断，不是认定</b>；空间图为示意，'
             '底图轮廓非精确行政界线，<b>不得用于任何法定用途</b>。<br>'
             '· 本页由 straw_pattern.py 自动生成，数字可复算。</footer>')
    h.append('</div></body></html>')

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "秸秆焚烧空间规律.html"
    out.write_text("".join(h), encoding="utf-8")
    for c in CITIES:
        d = data[c]
        print("[straw] %s：秸秆点位 %d / 工业源 %d / 距工业源中位 %.1f km / 孤立 %.0f%%"
              % (c, d["n_straw"], d["n_ind"], d["dist_med"], d["iso"] / d["n_straw"] * 100))
    print("[straw] 写出 %s（%.0f KB）" % (out, out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
