# -*- coding: utf-8 -*-
"""市级持续排放点位排查（通用版）。

在 anyi_check.py 的基础上参数化：任意城市都能跑，产出「全市 NO₂ + 点位 + 监测站」
「核心区放大」「点位清单」「监测站覆盖」四块。

与 anyi_check.py 的差别
-----------------------
  · anyi_check.py 是安阳专用（含安阳市控站点清单、内黄县对照等安阳特有内容）
  · 本脚本通用：县界文件按 `<市>市_县.geojson` 自动找；只有一个县级单元时
    （如济源这类省直辖县级市）自动跳过县区分析；国控点从 CNEMC 全省数据里筛。

用法：
  python city_check.py 济源
  python city_check.py 三门峡
"""
import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np

import annual_report as AR
import classify as CL
import synth_data as SD
from satellite_check import cmap, png_b64, _dp

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
SAT = os.path.join(MOD, "data", "satellite")
GEO = os.path.join(MOD, "geo")
STA = os.path.join(MOD, "data", "stations")
OUT = os.path.join(MOD, "report")
C = AR.C
MIN_DAYS = 10


# ---------------------------------------------------------------- 地理
def _rings(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in polys]


def in_ring(x, y, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                inside = not inside
    return inside


def in_poly(x, y, poly):
    if not in_ring(x, y, poly[0]):
        return False
    for hole in poly[1:]:
        if in_ring(x, y, hole):
            return False
    return True


def load_counties(city):
    p = os.path.join(GEO, "%s市_县.geojson" % city)
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding="utf-8"))
    return [(f["properties"]["name"], _rings(f["geometry"])) for f in d["features"]]


def county_of(lat, lon, counties):
    for nm, polys in counties:
        for poly in polys:
            if in_poly(lon, lat, poly):
                return nm
    return "—"


def county_centroid(polys):
    xs, ys = [], []
    for poly in polys:
        for x, y in poly[0]:
            xs.append(x); ys.append(y)
    return sum(ys) / len(ys), sum(xs) / len(xs)


def load_stations(city):
    """国控点来自 CNEMC 全省数据；市控点来自 data/stations/<拼音或中文>-monitors.json（可选）。"""
    out = []
    p = os.path.join(STA, "cnemc-henan.json")
    if os.path.exists(p):
        for s in json.load(open(p, encoding="utf-8")):
            if city in str(s.get("Area", "")):
                out.append(dict(kind="国控", name=s.get("PositionName"),
                                code=s.get("StationCode"), county="—",
                                lat=float(s["Latitude"]), lon=float(s["Longitude"]),
                                src="CNEMC"))
    for fn in os.listdir(STA):
        if fn.endswith("-monitors.json"):
            d = json.load(open(os.path.join(STA, fn), encoding="utf-8"))
            if d.get("city") == city:
                for s in d["stations"]:
                    s = dict(s); s.setdefault("src", "市控清单")
                    out.append(s)
    return out


# ---------------------------------------------------------------- 卫星
def grid_of(rec):
    g = np.array([[np.nan if v is None else v for v in row] for row in rec["grid"]],
                 dtype="float64")
    lat = rec["lat0"] + rec["dlat"] * np.arange(rec["ny"])
    lon = rec["lon0"] + rec["dlon"] * np.arange(rec["nx"])
    return lat, lon, g


def load_months():
    recs = {}
    for fn in sorted(os.listdir(SAT)):
        if fn.startswith("no2-"):
            r = json.load(open(os.path.join(SAT, fn), encoding="utf-8"))
            recs[r["ym"]] = r
    return recs


def mean_grid(recs):
    stack = np.stack([grid_of(recs[k])[2] for k in sorted(recs)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(stack, axis=0)


# ---------------------------------------------------------------- 地图
def svg_map(mg, lat, lon, counties, hot, bbox, stations, W=880, H=800, pad=12,
            label=True, cells=False, city=""):
    lat0, lat1, lon0, lon1 = bbox
    i0, i1 = np.searchsorted(lat, [lat0, lat1])
    j0, j1 = np.searchsorted(lon, [lon0, lon1])
    sub = mg[i0:i1, j0:j1]
    ny, nx = sub.shape
    lo, hi = np.nanpercentile(sub, [3, 97])
    iw, ih = W - 2 * pad, H - 2 * pad
    glat0, glat1 = float(lat[i0]), float(lat[i1 - 1])
    glon0, glon1 = float(lon[j0]), float(lon[j1 - 1])

    def xy(la, ln):
        return (pad + (ln - glon0) / (glon1 - glon0) * iw,
                pad + (glat1 - la) / (glat1 - glat0) * ih)

    if cells:
        cw, chh = iw / nx, ih / ny
        grid_svg = []
        for i in range(ny):
            for j in range(nx):
                v = sub[i, j]
                if not np.isfinite(v):
                    continue
                r, g_, b = cmap((v - lo) / (hi - lo) if hi > lo else 0.5)
                grid_svg.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" '
                                'fill="#%02x%02x%02x"/>'
                                % (pad + j * cw, pad + (ny - 1 - i) * chh,
                                   cw + 0.5, chh + 0.5, r, g_, b))
        img = None
    else:
        rgba = bytearray()
        for i in range(ny):
            for j in range(nx):
                v = sub[i, j]
                if not np.isfinite(v):
                    rgba.extend((0, 0, 0, 0))
                else:
                    r, g_, b = cmap((v - lo) / (hi - lo) if hi > lo else 0.5)
                    rgba.extend((r, g_, b, 255))
        img = png_b64(rgba, nx, ny)

    def path_of(polys):
        segs = []
        for poly in polys:
            for ring in poly:
                pts = _dp([xy(la, ln) for ln, la in ring], 0.7)
                if len(pts) > 2:
                    segs.append("M" + " ".join("%.0f %.0f" % q for q in pts) + "Z")
        return "".join(segs)

    cpath = "".join(path_of(polys) for _, polys in counties)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block;border-radius:12px">'
         % (W, H)]
    p.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, C["bg"]))
    if img is None:
        p.append("".join(grid_svg))
    else:
        p.append('<defs><image id="bg" x="%d" y="%d" width="%d" height="%d" '
                 'href="data:image/png;base64,%s" preserveAspectRatio="none"/>'
                 '<clipPath id="hnc"><path d="%s"/></clipPath></defs>'
                 % (pad, pad, iw, ih, img, cpath))
        p.append('<use href="#bg" opacity="0.22"/>')
        p.append('<use href="#bg" clip-path="url(#hnc)"/>')
    if cpath:
        p.append('<path d="%s" fill="none" stroke="#e2e8f0" stroke-width="1.1" '
                 'stroke-opacity="0.6" stroke-linejoin="round"/>' % cpath)

    for nm, polys in counties:
        la, ln = county_centroid(polys)
        x, y = xy(la, ln)
        p.append('<text x="%.1f" y="%.1f" fill="#94a3b8" font-size="12" text-anchor="middle" '
                 'style="paint-order:stroke;stroke:#020617;stroke-width:3px">%s</text>'
                 % (x, y, AR._esc(nm)))

    for st in stations:
        x, y = xy(st["lat"], st["lon"])
        if not (pad <= x <= W - pad and pad <= y <= H - pad):
            continue
        if st["kind"] == "国控":
            p.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f Z" fill="#a78bfa" '
                     'stroke="#fff" stroke-width="1.2" opacity="0.95">'
                     '<title>国控 · %s</title></path>'
                     % (x, y - 7.5, x + 7, y + 5, x - 7, y + 5, AR._esc(st["name"])))
        else:
            extra = "（近似位置）" if st.get("approx") else ""
            p.append('<circle cx="%.1f" cy="%.1f" r="4.8" fill="#34d399" stroke="#fff" '
                     'stroke-width="1.2" opacity="0.95"><title>市控 · %s%s</title></circle>'
                     % (x, y, AR._esc(st["name"]), extra))

    for k, it in enumerate(hot, 1):
        la, ln = [float(v) for v in it["key"].split(",")]
        x, y = xy(la, ln)
        r = 8.5 if it["days"] >= 100 else (7 if it["days"] >= 30 else 5.5)
        p.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#ef4444" stroke="#fff" '
                 'stroke-width="1.4" opacity="0.95"><title>%s　%d 天 · 夜间 %.0f%% · '
                 'FRP中位 %.2f MW</title></circle>'
                 % (x, y, r, it["key"], it["days"], it["night_ratio"] * 100, it["frp_med"]))
        if label:
            p.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="8.5" font-weight="600" '
                     'text-anchor="middle">%d</text>' % (x, y + 3.1, k))
    p.append("</svg>")
    return "".join(p), (lo, hi)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    CITY = sys.argv[1]

    allf = SD.load(2024) + SD.load(2025)
    prof = SD.profiles(allf)
    ps = [p for p in prof.values() if p["city"] == CITY]
    if not ps:
        raise SystemExit("没有 %s 的火点数据" % CITY)
    fire_n = sum(p["n"] for p in ps)
    for p in ps:
        p["kind"] = SD.kind_of(p)
    hot = sorted([p for p in ps if p["days"] >= MIN_DAYS], key=lambda p: -p["days"])
    n_ind = sum(1 for p in ps if p["kind"] == "工业/固定源")
    n_str = sum(1 for p in ps if p["kind"] == "秸秆焚烧疑似")
    str_n = sum(p["n"] for p in ps if p["kind"] == "秸秆焚烧疑似")
    ind_n = sum(p["n"] for p in ps if p["kind"] == "工业/固定源")

    counties = load_counties(CITY)
    multi = len(counties) > 1
    for p in hot:
        la, ln = [float(v) for v in p["key"].split(",")]
        p["county"] = county_of(la, ln, counties) if multi else "—"

    stations = load_stations(CITY)
    for st in stations:
        if st.get("county", "—") == "—" and multi:
            st["county"] = county_of(st["lat"], st["lon"], counties)

    recs = load_months()
    months = sorted(recs)
    lat, lon, _ = grid_of(recs[months[0]])
    mg = mean_grid(recs)

    if multi:
        xs, ys = [], []
        for _, polys in counties:
            for poly in polys:
                for x, y in poly[0]:
                    xs.append(x); ys.append(y)
        bbox = (min(ys) - 0.06, max(ys) + 0.06, min(xs) - 0.06, max(xs) + 0.06)
    else:
        hla = [float(p["key"].split(",")[0]) for p in hot]
        hln = [float(p["key"].split(",")[1]) for p in hot]
        bbox = (min(hla) - 0.16, max(hla) + 0.16, min(hln) - 0.16, max(hln) + 0.16)

    i0, i1 = np.searchsorted(lat, [bbox[0], bbox[1]])
    j0, j1 = np.searchsorted(lon, [bbox[2], bbox[3]])
    city_bg = float(np.nanmedian(mg[i0:i1, j0:j1]))
    prov_med = float(np.nanmedian(mg))

    for p in hot:
        la, ln = [float(v) for v in p["key"].split(",")]
        i = int(np.searchsorted(lat, la) - 1); j = int(np.searchsorted(lon, ln) - 1)
        p["no2"] = float(mg[i, j])
        p["pct_city"] = float((mg[i0:i1, j0:j1] < mg[i, j]).mean() * 100)
        nb = mg[max(0, i - 8):i + 9, max(0, j - 8):j + 9]
        p["nb"] = float(np.nanmedian(nb))
        p["ratio"] = p["no2"] / p["nb"] if p["nb"] else float("nan")

    covered, cov_guo, cov_shi = set(), set(), set()
    for st in stations:
        i = int(np.searchsorted(lat, st["lat"]) - 1)
        j = int(np.searchsorted(lon, st["lon"]) - 1)
        st["no2"] = float(mg[i, j])
        st["n3"] = 0
        for k, p in enumerate(hot):
            dla = float(p["key"].split(",")[0]) - st["lat"]
            dln = (float(p["key"].split(",")[1]) - st["lon"]) * 0.809
            if (dla ** 2 + dln ** 2) ** 0.5 * 111 <= 3:
                st["n3"] += 1
                covered.add(k)
                (cov_guo if st["kind"] == "国控" else cov_shi).add(k)

    mp, (lo, hi) = svg_map(mg, lat, lon, counties, hot, bbox, stations, label=False, city=CITY)
    hla = [float(p["key"].split(",")[0]) for p in hot]
    hln = [float(p["key"].split(",")[1]) for p in hot]
    core = (min(hla) - 0.10, max(hla) + 0.10, min(hln) - 0.10, max(hln) + 0.10)
    core_h = int(880 * ((core[1] - core[0]) / ((core[3] - core[2]) * 0.83)))
    mp2, (lo2, hi2) = svg_map(mg, lat, lon, counties, hot, core, stations,
                              W=880, H=core_h, pad=12, cells=True, city=CITY)

    med_hot = float(np.median([p["no2"] for p in hot]))
    top5 = sum(p["n"] for p in sorted(ps, key=lambda x: -x["n"])[:5]) / fire_n * 100
    top10 = sum(p["n"] for p in sorted(ps, key=lambda x: -x["n"])[:10]) / fire_n * 100
    lat_span = (max(hla) - min(hla)) * 111
    lon_span = (max(hln) - min(hln)) * 111 * 0.809

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>%s持续排放点位排查 · 卫星印证</title><style>%s</style></head><body>'
         % (CITY, css),
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>%s持续排放点位排查 · 卫星印证</h1>' % CITY,
         '<div class="sub">TROPOMI NO₂（%d 个月月均）+ FIRMS VIIRS 375m 两年火点'
         '　·　%s　·　生成于 %s</div>' % (len(months), CITY, dt)]

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>两年火点（条）</span></div>'
             '<div><b>%d</b><span>点位总数</span></div>'
             '<div><b>%d</b><span>持续排放点位（≥%d 天）</span></div>'
             '<div><b>%.1f%%</b><span>工业源火点占比</span></div>'
             '</div>' % (format(fire_n, ","), len(ps), len(hot), MIN_DAYS,
                         ind_n / fire_n * 100))

    h.append('<div class="card" style="border-color:#f97316"><h2>结论</h2><div class="big">'
             '%s两年 %s 条火点里，<span class="hl">%.1f%%</span>（%s 条）来自 '
             '<b>%d 个工业/固定源点位</b>；前 5 个点位就占了全市火点的 '
             '<span class="hl">%.0f%%</span>，前 10 个占 %.0f%%。'
             '</div>'
             '<div class="note">这些点位集中在约 <b>%.0f × %.0f km</b> 的范围内'
             '（见下图核心区），最高点位两年出现 <b>%d 天</b>、夜间占比 %.0f%%、'
             'FRP 中位 %.2f MW —— 典型的工业闷烧特征。'
             '而秸秆焚烧疑似只有 %d 条、分散在 %d 个点位，且几乎都只烧一次。</div></div>'
             % (CITY, format(fire_n, ","), ind_n / fire_n * 100, format(ind_n, ","),
                n_ind, top5, top10, lat_span, lon_span, hot[0]["days"],
                hot[0]["night_ratio"] * 100, hot[0]["frp_med"], str_n, n_str))

    h.append('<div class="card"><h2>%s NO₂ 月均（%d 个月）· 持续排放点位 · 空气监测站</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#38bdf8"></i>NO₂ 低 → 高（%.0f → %.0f μmol/m²）</span>'
             '<span><i style="background:#ef4444"></i>持续排放点位（编号同下表）</span>'
             '<span><i style="background:#a78bfa"></i>国控空气站</span>'
             '<span><i style="background:#34d399"></i>市控空气站</span>'
             '</div></div>' % (CITY, len(months), mp, lo, hi))

    h.append('<div class="card"><h2>核心区放大（按原始 0.022° 网格逐格绘制、不插值）</h2>'
             '%s'
             '<div class="note">每个方块约 2.4 km —— 看到的就是 TROPOMI 的真实空间分辨率。'
             '圆越大代表两年出现天数越多（≥100 天 / 30–99 天 / 10–29 天三档）。</div></div>'
             % mp2)

    h.append('<div class="card"><h2>持续排放点位清单（≥%d 天，共 %d 个）</h2>'
             '<div class="note">按两年出现天数降序。NO₂ 为 %s 共 %d 个月的月均；'
             '「/周边」= 点位 NO₂ ÷ 周边 20 km 中位；「市域分位」= 在全市格点中的百分位。</div>'
             '<table><tr><th>#</th><th>坐标</th><th class="num">天数</th>'
             '<th class="num">夜间</th><th class="num">FRP中位</th><th class="num">跨月</th>'
             '<th class="num">探测次数</th><th class="num">NO₂</th>'
             '<th class="num">市域分位</th><th class="num">/周边</th><th>判定</th></tr>'
             % (MIN_DAYS, len(hot), months[0][:4], len(months)))
    for k, p in enumerate(hot, 1):
        h.append('<tr><td>%d</td><td>%s</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f</td>'
                 '<td class="num">%d</td><td class="num">%d</td>'
                 '<td class="num">%.1f</td><td class="num">%.0f%%</td>'
                 '<td class="num">%.2f</td><td>%s</td></tr>'
                 % (k, p["key"], p["days"], p["night_ratio"] * 100, p["frp_med"],
                    p["n_months"], p["n"], p["no2"], p["pct_city"], p["ratio"],
                    AR._esc(p["kind"])))
    h.append('</table></div>')

    if stations:
        n_guo = sum(1 for s in stations if s["kind"] == "国控")
        h.append('<div class="card"><h2>监测站覆盖（国控 %d + 市控 %d）</h2>'
                 '<div class="big">%d 个持续排放点位里，有 <span class="hl">%d 个</span>'
                 '落在监测站 3 km 以内（其中国控覆盖 %d 个、市控覆盖 %d 个）。</div>'
                 '<table><tr><th>类型</th><th>站名</th><th>纬度</th><th>经度</th>'
                 '<th class="num">NO₂ 月均</th><th class="num">3 km 内持续点位</th></tr>'
                 % (n_guo, len(stations) - n_guo, len(hot), len(covered),
                    len(cov_guo), len(cov_shi)))
        for st in sorted(stations, key=lambda s: (s["kind"] != "国控", s["name"])):
            h.append('<tr><td>%s</td><td>%s</td><td>%.4f</td><td>%.4f</td>'
                     '<td class="num">%.1f</td><td class="num">%d</td></tr>'
                     % (AR._esc(st["kind"]),
                        AR._esc(st["name"]) + ("（近似）" if st.get("approx") else ""),
                        st["lat"], st["lon"], st["no2"], st["n3"]))
        h.append('</table>'
                 '<div class="note">国控点坐标来自中国环境监测总站实时发布平台（平台发布值）；'
                 '国控点面向城市建成区的区域空气质量，不面向工业点源，'
                 '因此「覆盖不到」是设计使然，不是失灵。</div></div>')

    h.append('<div class="card"><h2>边界与口径</h2>'
             '<table><tr><th>项</th><th>说明</th></tr>'
             '<tr><td>火点口径</td><td>NASA FIRMS VIIRS 375m，2024 + 2025 两年，'
             '归属%s的全部火点</td></tr>'
             '<tr><td>点位口径</td><td>0.01° 网格（约 1.1 km）聚合；「天数」= 该格点出现火点的'
             '<b>不重复日期数</b>（两年合计，上限 730）</td></tr>'
             '<tr><td>类型判定</td><td>出现 ≥10 天 → 工业/固定源；≤2 天且在收获季 → 秸秆疑似；'
             '其余按夜间占比与季节细分（规则见「火点类型判别模型 · 验证」）</td></tr>'
             '<tr><td>NO₂ 口径</td><td>TROPOMI L3 月产品 %d 个月平均；'
             '原始像元 3.5×5.5 km，网格 0.022°（约 2.4 km）</td></tr>'
             '<tr><td>⚠ 不能做的事</td><td>不能指认企业、不能给排放量、'
             '不能区分「这家厂」与「这个园区」</td></tr>'
             '</table></div>' % (CITY, len(months)))

    h.append(AR.qr_foot("../../../assets"))


    h.append('<footer>'
             '数据：NASA FIRMS VIIRS 375m · Sentinel-5P TROPOMI L3（S5P-PAL）· '
             '中国环境监测总站实时发布平台<br>'
             '方法：0.01° 点位聚合 → 两年复现天数/夜间占比/FRP 判定 → '
             'TROPOMI 月均取点位值并与市域背景比较 → 监测站 3 km 覆盖分析<br>'
             '<b>边界声明</b>：遥感与卫星柱浓度只能提供「疑似 + 依据」的线索，'
             '不能确证成因、不能指认主体。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "%s持续排放点位排查.html" % CITY)
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("%s 火点 %d / 点位 %d / 持续 %d / 工业源 %d 个 %d 条 (%.1f%%)"
          % (CITY, fire_n, len(ps), len(hot), n_ind, ind_n, ind_n / fire_n * 100))
    print("  前5点位占 %.0f%% / 前10占 %.0f%% / 工业带 %.0f×%.0f km"
          % (top5, top10, lat_span, lon_span))
    print("  市域背景 %.1f / 全省中位 %.1f / 点位NO2中位 %.1f" % (city_bg, prov_med, med_hot))
    print("  监测站 %d 个，覆盖 %d/%d 个持续点位" % (len(stations), len(covered), len(hot)))


if __name__ == "__main__":
    main()
