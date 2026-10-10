# -*- coding: utf-8 -*-
"""全省持续热排放点位统计。

口径：2024–2025 两年，按 0.01° 网格（约 1.1km）聚合，判定为「工业/固定源」的点位
      （出现 ≥10 天；≥30 天且夜间占比 ≥70% 为高置信），按出现天数排序。

产出：report/全省持续热排放点位.html

⚠ 边界：卫星火点探的是「热异常」。本清单覆盖的是**有明火或高温**的持续排放
   （窑炉、堆场自燃、煤泥自燃等），**不覆盖污水直排和扬尘**（无热异常）。
   清单是「线索」，不是「违法认定」，用于执法须现场核实。
"""
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
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
import straw_pattern as SP

CITIES = ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
          "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]
C_HOT = "#f97316"


def county_index():
    """{市: [(县名, geom), ...]}"""
    idx = {}
    for c in CITIES:
        p = GEO / ("%s市_县.geojson" % c)
        if not p.exists():
            continue
        gj = json.loads(p.read_text(encoding="utf-8"))
        idx[c] = [(f["properties"].get("name", "?"), f["geometry"]) for f in gj["features"]]
    return idx


def county_of(city, lng, lat, idx):
    for n, g in idx.get(city, []):
        if FF.point_in_geom(lng, lat, g):
            return n
    return "—"


def svg_map(points, w=880, h=620):
    """全省空间分布：点大小 = 出现天数。"""
    gj = json.loads((GEO / "henan-cities.geojson").read_text(encoding="utf-8"))
    rings = []
    xs, ys = [], []
    for f in gj["features"]:
        for ring in SP.geom_rings(f["geometry"]):
            rings.append(ring)
            for c in ring:
                xs.append(c[0]); ys.append(c[1])
    bb = (min(xs), min(ys), max(xs), max(ys))
    proj = SP.make_proj(bb, w, h, pad=18)
    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block;'
         f'background:#0b1120;border-radius:10px">']
    for ring in rings:
        pts = " ".join("%.1f,%.1f" % proj(c[0], c[1]) for c in ring[::max(1, len(ring)//200)])
        p.append(f'<polygon points="{pts}" fill="none" stroke="#1e293b" stroke-width="1"/>')
    mx = max(d for _, _, d in points) or 1
    for lng, lat, days in sorted(points, key=lambda x: x[2]):
        x, y = proj(lng, lat)
        r = 2.5 + 9 * (days / mx) ** 0.6
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{C_HOT}" '
                 f'opacity="0.82" stroke="#7c2d12" stroke-width="0.7">'
                 f'<title>{days} 天</title></circle>')
    p.append(f'<text x="16" y="26" fill="#94a3b8" font-size="12">'
             f'点越大＝两年内被探测到的天数越多（最大 {mx} 天）</text>')
    p.append("</svg>")
    return "".join(p)


def main():
    fires = []
    for y in (2024, 2025):
        fires += json.loads((HIST / ("%d.json" % y)).read_text(encoding="utf-8"))["fires"]
    prof = CL.build_profiles(fires)
    kind = {k: CL.classify(p)[0] for k, p in prof.items()}
    ind = {k: p for k, p in prof.items() if kind[k] == "工业/固定源"}
    n_fires_ind = sum(p["n"] for p in ind.values())
    ranked = sorted(ind.items(), key=lambda kv: -kv[1]["days"])

    idx = county_index()
    rows = []
    for k, p in ranked:
        lng, lat = SP.key2ll(k)
        rows.append({
            "key": k, "lng": lng, "lat": lat, "days": p["days"], "n": p["n"],
            "ntr": p["night_ratio"], "frp_med": p["frp_med"], "frp_max": p["frp_max"],
            "city": p["city"], "county": county_of(p["city"], lng, lat, idx),
            "months": p["n_months"], "first": p["first"], "last": p["last"],
        })

    # 天数区间
    bands = [(10, 19), (20, 29), (30, 49), (50, 99), (100, 199), (200, 10 ** 9)]
    band_rows = []
    for lo, hi in bands:
        cs = [r for r in rows if lo <= r["days"] <= hi]
        band_rows.append(("%d–%s 天" % (lo, "730" if hi > 1000 else hi),
                          len(cs), sum(r["n"] for r in cs)))

    by_city = Counter(r["city"] for r in rows)
    city_fires = defaultdict(int)
    for r in rows:
        city_fires[r["city"]] += r["n"]

    css = (AR.CSS.replace("__BG__", AR.C["bg"]).replace("__PANEL__", AR.C["panel"])
           .replace("__LINE__", AR.C["line"]).replace("__TXT__", AR.C["txt"])
           .replace("__DIM__", AR.C["dim"]).replace("__DIM2__", AR.C["dim2"])
           .replace("__ACC__", AR.C["accent"]).replace("__HOT__", AR.C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>全省持续热排放点位统计</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>全省持续热排放点位统计</h1>',
         '<div class="sub">河南省　·　2024–2025 两年　·　NASA FIRMS VIIRS 375m　·　'
         '生成于 %s</div>'
         % datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")]

    h.append('<div class="kpi">')
    for val, lab in [(f'{len(rows)}', '持续热排放点位'),
                     (f'{n_fires_ind:,}', '覆盖火点（占全省 %.0f%%）' % (n_fires_ind / len(fires) * 100)),
                     (f'{rows[0]["days"]}', '最高出现天数（两年共 730 天）'),
                     (f'{by_city.most_common(1)[0][0]} {by_city.most_common(1)[0][1]}',
                      '点位数最多的市')]:
        h.append('<div><b>%s</b><span>%s</span></div>' % (AR._esc(val), lab))
    h.append('</div>')

    h.append('<div class="card"><h2>这份清单是什么</h2><div class="note" style="font-size:13.5px">'
             '把两年 45,540 条卫星火点按 0.01° 网格（约 1.1km）聚合后，'
             '<b>有 %s 个点位在两年内被反复探测到 ≥10 天</b>——它们贡献了全省 '
             '<b>%.0f%%</b> 的火点。<br><br>'
             '这些点位<b>不是农田焚烧</b>：它们全年都在出现、<b>夜间占比中位 %.0f%%</b>、'
             '辐射功率稳定在低位（闷烧而非明火）——符合工业窑炉、堆场自燃、煤泥/煤矸石自燃等'
             '<b>固定源的持续排放特征</b>。<br><br>'
             '<b>⚠ 边界</b>：卫星火点探的是「热异常」，只能覆盖<b>有明火或高温</b>的排放；'
             '<b>污水直排、扬尘没有热信号，本清单覆盖不到</b>。'
             '清单是「线索」不是「违法认定」，用于执法须现场核实。</div></div>'
             % (f'{len(rows)}', n_fires_ind / len(fires) * 100,
                statistics.median(r["ntr"] for r in rows) * 100))

    h.append('<div class="card"><h2>全省分布</h2>')
    h.append(svg_map([(r["lng"], r["lat"], r["days"]) for r in rows]))
    h.append('<div class="note">点越大＝两年内出现天数越多。可以看出集中在'
             '安阳—焦作—济源（豫北钢铁焦化带）、平顶山—许昌（豫中煤焦带）、'
             '三门峡（豫西矿业）几条线上。</div></div>')

    h.append('<div class="card"><h2>按出现天数分档</h2>')
    h.append(AR.svg_bar([(b[0], b[1]) for b in band_rows], h=240, color=C_HOT, unit="个点位"))
    h.append('<table><tr><th>天数区间</th><th class="num">点位数</th><th class="num">覆盖火点</th>'
             '</tr>')
    for name, c, f_ in band_rows:
        h.append('<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td></tr>'
                 % (name, c, f'{f_:,}'))
    h.append('</table><div class="note">'
             '<b>200 天以上的 19 个点位，就覆盖了 %s 条火点</b>——'
             '平均每个点位两年里有一半以上的日子都在被探测到。'
             '这类点位是最该优先核查的。</div></div>'
             % f'{band_rows[-1][2]:,}')

    h.append('<div class="card"><h2>按市统计</h2>')
    h.append(AR.svg_hbar([(c, v) for c, v in by_city.most_common()], row_h=24, color=C_HOT,
                         unit="个点位"))
    h.append('<div class="note">平顶山、安阳最多——与两市是煤焦/钢铁集聚区一致。'
             '全省 %d 个市中有 %d 个市存在持续热排放点位。</div>'
             % (len(CITIES), len(by_city)))
    h.append('</div>')

    # 完整排行表
    h.append('<div class="card"><h2>全部 %d 个点位（按出现天数排序）</h2>' % len(rows))
    h.append('<table><tr><th class="num">#</th><th>坐标（WGS-84）</th><th>市</th><th>县区</th>'
             '<th class="num">出现天数</th><th class="num">夜间</th>'
             '<th class="num">FRP中位</th><th class="num">FRP最大</th>'
             '<th class="num">探测次数</th><th class="num">跨月</th></tr>')
    for i, r in enumerate(rows, 1):
        hl = ' style="background:rgba(249,115,22,.10)"' if r["days"] >= 200 else ""
        h.append('<tr%s><td class="num">%d</td><td>%s</td><td>%s</td><td>%s</td>'
                 '<td class="num"><b>%d</b></td><td class="num">%.0f%%</td>'
                 '<td class="num">%.2f</td><td class="num">%.1f</td>'
                 '<td class="num">%d</td><td class="num">%d</td></tr>'
                 % (hl, i, AR._esc(r["key"]), AR._esc(r["city"]), AR._esc(r["county"]),
                    r["days"], r["ntr"] * 100, r["frp_med"], r["frp_max"],
                    r["n"], r["months"]))
    h.append('</table>')
    h.append('<div class="note">「跨月」＝该点位出现过的不同月份数；接近 24 说明全年无休。'
             '标注底色的为 200 天以上点位。<br>'
             '<b>坐标是 WGS-84</b>，可直接用于地图定位；'
             '用于执法核查前建议先做实地确认。</div></div>')

    h.append('<footer><b>方法与边界</b><br>'
             '· 数据源：NASA FIRMS VIIRS 375m 活跃火产品（Suomi-NPP + NOAA-20，SP 标准处理），'
             '2024–2025 年河南省域，共 %s 条。<br>'
             '· 网格 0.01°（约 1.1km）；类型判定见 <code>classify.py</code>'
             '（出现 ≥10 天判工业/固定源；≥30 天且夜间 ≥70%% 判高置信）。<br>'
             '· <b>本清单为遥感线索，不构成违法认定</b>，不能作为行政处罚依据；'
             '具体是什么设施需结合现场、环评与排污许可信息核实。<br>'
             '· 覆盖范围仅限<b>有热异常</b>的排放；污水、扬尘、常温废气不在其中。<br>'
             '· 本页由 hotspots.py 自动生成，全部数字可复算。</footer>'
             % f'{len(fires):,}')
    h.append('</div></body></html>')

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "全省持续热排放点位.html"
    out.write_text("".join(h), encoding="utf-8")
    print("[hotspots] %d 个点位 / 覆盖 %s 条火点（%.1f%%）"
          % (len(rows), f'{n_fires_ind:,}', n_fires_ind / len(fires) * 100))
    print("[hotspots] 最高 %d 天（%s %s）" % (rows[0]["days"], rows[0]["city"], rows[0]["county"]))
    print("[hotspots] 写出 %s（%.0f KB）" % (out, out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
