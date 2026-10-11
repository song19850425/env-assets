# -*- coding: utf-8 -*-
"""安阳市持续排放点位排查（卫星气体印证）。

思路：安阳是全省火点最多的市（两年 6,688 条 / 607 个点位），且 85% 是工业/固定源。
本报告把 TROPOMI NO2（7 个月月均）下钻到安阳市，回答三个问题：
  ① 这些高频点位在 NO2 上处于什么水平（相对安阳背景 / 相对全省）；
  ② 它们落在哪个县区，是否集中在已知的钢铁—焦化—煤化工集聚带；
  ③ 哪些点位值得优先去核。

边界（不越线）：卫星只能证明「这个格点上方有持续 NO2 增量」，
不能指认企业、不能给排放量。点位坐标是 0.01° 网格（约 1.1 km）。

用法：
  python anyi_check.py
"""
import json
import os
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np

import annual_report as AR
import classify as CL
from satellite_check import cmap, png_b64, _dp

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
SAT = os.path.join(MOD, "data", "satellite")
GEO = os.path.join(MOD, "geo")
OUT = os.path.join(MOD, "report")
C = AR.C
CITY = "安阳"
MIN_DAYS = 10          # 纳入「持续排放点位」的天数阈值（与全省报告同口径）


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


def load_counties():
    d = json.load(open(os.path.join(GEO, "安阳市_县.geojson"), encoding="utf-8"))
    return [(f["properties"]["name"], _rings(f["geometry"])) for f in d["features"]]


def county_of(lat, lon, counties):
    for nm, polys in counties:
        for poly in polys:
            if in_poly(lon, lat, poly):
                return nm
    return "边界外"


def county_centroid(polys):
    xs, ys = [], []
    for poly in polys:
        for x, y in poly[0]:
            xs.append(x); ys.append(y)
    return sum(ys) / len(ys), sum(xs) / len(xs)


def counties_with_bbox(counties):
    out = []
    for nm, polys in counties:
        xs, ys = [], []
        for poly in polys:
            for x, y in poly[0]:
                xs.append(x); ys.append(y)
        out.append((nm, polys, (min(ys), max(ys), min(xs), max(xs))))
    return out


def county_grid_median(mg, lat, lon, counties, bbox):
    """每个县区范围内的 NO2 格点中位（先 bbox 预筛再射线法，避免逐格全量判断）。"""
    cb = counties_with_bbox(counties)
    i0, i1 = np.searchsorted(lat, [bbox[0], bbox[1]])
    j0, j1 = np.searchsorted(lon, [bbox[2], bbox[3]])
    acc = {}
    for i in range(i0, i1):
        la = float(lat[i])
        for j in range(j0, j1):
            v = mg[i, j]
            if not np.isfinite(v):
                continue
            ln = float(lon[j])
            for nm, polys, (y0, y1, x0, x1) in cb:
                if not (y0 <= la <= y1 and x0 <= ln <= x1):
                    continue
                if any(in_poly(ln, la, poly) for poly in polys):
                    acc.setdefault(nm, []).append(v)
                    break
    return {k: (float(np.median(v)), len(v)) for k, v in acc.items()}


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
def svg_map(mg, lat, lon, counties, hot, bbox, W=880, H=800, pad=12,
            label=True, cells=False, stations=None):
    lat0, lat1, lon0, lon1 = bbox
    i0, i1 = np.searchsorted(lat, [lat0, lat1])
    j0, j1 = np.searchsorted(lon, [lon0, lon1])
    sub = mg[i0:i1, j0:j1]
    ny, nx = sub.shape
    lo, hi = np.nanpercentile(sub, [3, 97])
    iw, ih = W - 2 * pad, H - 2 * pad
    # 用格点实际范围做映射，保证底图与县界严丝合缝
    glat0, glat1 = float(lat[i0]), float(lat[i1 - 1])
    glon0, glon1 = float(lon[j0]), float(lon[j1 - 1])

    def xy(la, ln):
        return (pad + (ln - glon0) / (glon1 - glon0) * iw,
                pad + (glat1 - la) / (glat1 - glat0) * ih)

    if cells:
        # 放大到单格可见时改画矢量方块，避免位图放大成马赛克
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
    p.append('<path d="%s" fill="none" stroke="#e2e8f0" stroke-width="1.1" '
             'stroke-opacity="0.6" stroke-linejoin="round"/>' % cpath)

    # 县区名
    for nm, polys in counties:
        la, ln = county_centroid(polys)
        x, y = xy(la, ln)
        p.append('<text x="%.1f" y="%.1f" fill="#94a3b8" font-size="12" text-anchor="middle" '
                 'style="paint-order:stroke;stroke:#020617;stroke-width:3px">%s</text>'
                 % (x, y, AR._esc(nm)))

    # 环境空气监测站：国控=紫三角，市控=绿圆点（画在火点点位之下，避免遮挡编号）
    if stations:
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

    # 点位：半径按天数分档
    for k, it in enumerate(hot, 1):
        la, ln = [float(v) for v in it["key"].split(",")]
        x, y = xy(la, ln)
        r = 8.5 if it["days"] >= 100 else (7 if it["days"] >= 30 else 5.5)
        p.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#ef4444" stroke="#fff" '
                 'stroke-width="1.4" opacity="0.95"><title>%s · %s　%d 天 · 夜间 %.0f%% · '
                 'FRP中位 %.2f MW</title></circle>'
                 % (x, y, r, AR._esc(it["county"]), it["key"], it["days"],
                    it["night_ratio"] * 100, it["frp_med"]))
        if label:
            p.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="8.5" font-weight="600" '
                     'text-anchor="middle">%d</text>' % (x, y + 3.1, k))
    p.append("</svg>")
    return "".join(p), (lo, hi), int(sub.size)


def main():
    fires = []
    for y in (2024, 2025):
        d = json.load(open(os.path.join(MOD, "data", "history", "%d.json" % y),
                           encoding="utf-8"))
        fires += [f for f in d["fires"] if f.get("city") == CITY]
    prof = CL.build_profiles(fires)
    counties = load_counties()
    mon = json.load(open(os.path.join(MOD, "data", "stations", "anyi-monitors.json"),
                         encoding="utf-8"))
    stations = mon["stations"]
    for st in stations:
        if "county" not in st:
            st["county"] = county_of(st["lat"], st["lon"], counties)
    for p in prof.values():
        la, ln = [float(x) for x in p["key"].split(",")]
        p["county"] = county_of(la, ln, counties)
    hot = sorted([p for p in prof.values() if p["days"] >= MIN_DAYS], key=lambda p: -p["days"])

    kinds = {}
    for p in prof.values():
        k = CL.classify(p)[0]
        kinds[k] = kinds.get(k, 0) + 1
    n_ind = sum(1 for p in prof.values() if CL.classify(p)[0] == "工业/固定源")

    recs = load_months()
    months = sorted(recs)
    lat, lon, _ = grid_of(recs[months[0]])
    mg = mean_grid(recs)

    # 安阳市 bbox（从县界算，留一点余量）
    xs, ys = [], []
    for _, polys in counties:
        for poly in polys:
            for x, y in poly[0]:
                xs.append(x); ys.append(y)
    bbox = (min(ys) - 0.06, max(ys) + 0.06, min(xs) - 0.06, max(xs) + 0.06)

    # 安阳背景（市域内格点中位）与全省中位
    i0, i1 = np.searchsorted(lat, [bbox[0], bbox[1]])
    j0, j1 = np.searchsorted(lon, [bbox[2], bbox[3]])
    city_bg = float(np.nanmedian(mg[i0:i1, j0:j1]))
    prov_med = float(np.nanmedian(mg))

    for p in hot:
        la, ln = [float(x) for x in p["key"].split(",")]
        i = int(np.searchsorted(lat, la) - 1); j = int(np.searchsorted(lon, ln) - 1)
        p["no2"] = float(mg[i, j])
        p["pct_city"] = float((mg[i0:i1, j0:j1] < mg[i, j]).mean() * 100)
        nb = mg[max(0, i - 8):i + 9, max(0, j - 8):j + 9]
        p["nb"] = float(np.nanmedian(nb))
        p["ratio"] = p["no2"] / p["nb"] if p["nb"] else float("nan")

    # 监测站：取该点 NO2，并统计 3 km 内的持续排放点位（看监测网络覆盖不覆盖）
    covered = set()
    cov_guo, cov_shi = set(), set()
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

    mp, (lo, hi), npx = svg_map(mg, lat, lon, counties, hot, bbox, label=False,
                                stations=stations)
    # 核心区放大：34 个点位里有 30 个挤在安阳县—殷都区，全市图上分不开
    hla = [float(p["key"].split(",")[0]) for p in hot]
    hln = [float(p["key"].split(",")[1]) for p in hot]
    core = (min(hla) - 0.10, max(hla) + 0.10, min(hln) - 0.10, max(hln) + 0.10)
    core_h = int(880 * ((core[1] - core[0]) / ((core[3] - core[2]) * 0.83)))
    mp2, (lo2, hi2), _ = svg_map(mg, lat, lon, counties, hot, core,
                                 W=880, H=core_h, pad=12, cells=True, stations=stations)

    # 县区汇总
    ct = {}
    for p in prof.values():
        a = ct.setdefault(p["county"], {"n_fire": 0, "pts": 0, "hot": 0, "no2": []})
        a["n_fire"] += p["n"]; a["pts"] += 1
        if p["days"] >= MIN_DAYS:
            a["hot"] += 1
    for p in hot:
        if p["county"] in ct:
            ct[p["county"]]["no2"].append(p["no2"])
    crows = sorted(ct.items(), key=lambda kv: -kv[1]["hot"])
    cno2 = county_grid_median(mg, lat, lon, counties, bbox)

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    med_hot_no2 = float(np.median([p["no2"] for p in hot]))
    n_above = sum(1 for p in hot if p["no2"] > city_bg)
    top_ct = crows[0]

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>安阳持续排放点位排查 · 卫星印证</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>安阳持续排放点位排查 · 卫星印证</h1>',
         '<div class="sub">TROPOMI NO₂（%d 个月月均）+ FIRMS VIIRS 375m 两年火点'
         '　·　安阳市　·　生成于 %s</div>' % (len(months), dt)]

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>两年火点（条）</span></div>'
             '<div><b>%d</b><span>点位总数</span></div>'
             '<div><b>%d</b><span>持续排放点位（≥%d 天）</span></div>'
             '<div><b>%d</b><span>工业/固定源点位</span></div>'
             '</div>' % (format(len(fires), ","), len(prof), len(hot), MIN_DAYS, n_ind))

    h.append('<div class="card"><h2>结论</h2><div class="big">'
             '安阳的持续热排放点位<b>高度集中在%s</b>：全县区里 <span class="hl">%d</span> 个'
             '「≥%d 天」点位落在%s，两年贡献火点 %s 条（占全市 %.0f%%）。'
             '这些点位所在格点的 NO₂ 月均中位 <span class="hl">%.1f μmol/m²</span>，'
             '高于安阳市域背景 %.1f；其中 %d / %d 个点位高于市域中位。'
             '</div>'
             '<div class="note">空间上与安阳县—殷都区一线的钢铁/焦化/煤化工集聚带重合。'
             '但请注意：这只能说明「该 1.1 km 格点上方存在持续 NO₂ 增量」，'
             '<b>不能据此指认具体企业，也不能给出排放量</b>。</div></div>'
             % (top_ct[0], top_ct[1]["hot"], MIN_DAYS, top_ct[0],
                format(top_ct[1]["n_fire"], ","),
                top_ct[1]["n_fire"] / len(fires) * 100, med_hot_no2, city_bg, n_above, len(hot)))

    h.append('<div class="card"><h2>安阳 NO₂ 月均（%s 共 %d 个月）· 县界 · 持续排放点位</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#38bdf8"></i>NO₂ 低 → 高（%.0f → %.0f μmol/m²）</span>'
             '<span><i style="background:#ef4444"></i>持续排放点位（编号同下表）</span>'
             '<span><i style="background:#a78bfa"></i>国控空气站</span>'
             '<span><i style="background:#34d399"></i>市控空气站</span>'
             '</div>'
             '<div class="note">底图为 %d 个月平均（%s），已按安阳市域裁剪，市外淡化。'
             'NO₂ 高值带沿安阳县—殷都区一线展开，与火点点位密集区重合；'
             '林州、滑县等县点位稀疏，NO₂ 也是全市最低的一档。</div></div>'
             % (months[0][:4], len(months), mp, lo, hi, len(months),
                "、".join(m[5:] + "月" for m in months)))

    h.append('<div class="card"><h2>核心区放大 · 安阳县—殷都区—市区</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#38bdf8"></i>NO₂（%.0f → %.0f μmol/m²）</span>'
             '<span><i style="background:#ef4444"></i>持续排放点位（编号同下表）</span>'
             '<span><i style="background:#a78bfa"></i>国控空气站</span>'
             '<span><i style="background:#34d399"></i>市控空气站</span>'
             '</div>'
             '<div class="note">34 个点位里 30 个挤在安阳县—殷都区，全市图上分不开，'
             '这里单独放大。<b>底图按原始 0.022° 网格逐格绘制、不做插值</b> —— '
             '看到的就是 TROPOMI 的真实空间分辨率（每格约 2.4 km）。'
             '圆越大代表两年出现天数越多（≥100 天 / 30–99 天 / 10–29 天三档）。</div></div>'
             % (mp2, lo2, hi2))

    n_guo = sum(1 for s in stations if s["kind"] == "国控")
    n_shi = sum(1 for s in stations if s["kind"] == "市控")

    def _n3(nm):
        return next((s["n3"] for s in stations if s["name"] == nm), 0)

    h.append('<div class="card"><h2>环境空气监测站分布（国控 %d + 市控 %d）</h2>'
             '<div class="big">把 %d 个持续排放点位按「距离最近监测站 3 km 以内」算，'
             '只有 <span class="hl">%d / %d</span> 个落在现有监测站的有效覆盖圈内 —— '
             '而且全部靠市控乡镇站（铜冶镇 %d 个、水冶镇 %d 个、许家沟镇 %d 个…）；'
             '<b>%d 个国控点 3 km 内合计只有 %d 个</b>。'
             '</div>'
             '<div class="note">这不是国控点「失灵」—— 国控点的设计目标是反映城市建成区的'
             '区域空气质量、服务公众健康提示，本来就布在人口密集区，不是用来抓工业点源。'
             '但这恰好说明：<b>只看国控数据，发现不了这些持续燃烧排放源</b>；'
             '安阳县—殷都区的工业带正好落在国控网络的盲区里。'
             '要把它们纳入监管，要么靠乡镇站（市控），要么靠火点遥感这类独立手段。</div>'
             '<div class="note">国控点位来自中国环境监测总站实时发布平台（坐标为平台发布值，可直接使用）；'
             '市控名单来自《安阳市生态环境局安阳市市控环境质量自动监测站点运维服务项目招标文件》'
             '（安财招标采购-2026-19，包 1 共 17 个，含 1 辆移动监测车不绘图）。'
             '<b>⚠ 市控坐标为所在乡镇/单位位置的近似值（OpenStreetMap），不是站点实测坐标</b>，'
             '其中「武装部」未能定位到具体单位、用北关区中心近似，误差可能较大；'
             '对外使用前请以业主站点台账为准。</div>'
             '<table><tr><th>类型</th><th>站名</th><th>县区</th><th>纬度</th><th>经度</th>'
             '<th class="num">NO₂ 月均</th><th class="num">3 km 内持续点位</th></tr>'
             % (n_guo, n_shi, len(hot), len(covered), len(hot),
                _n3("铜冶镇"), _n3("水冶镇"), _n3("许家沟镇"),
                n_guo, len(cov_guo)))
    for st in sorted(stations, key=lambda s: (s["kind"] != "国控", s["name"])):
        h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%.4f</td><td>%.4f</td>'
                 '<td class="num">%.1f</td><td class="num">%d</td></tr>'
                 % (AR._esc(st["kind"]), AR._esc(st["name"]) + ("（近似）" if st.get("approx") else ""),
                    AR._esc(st.get("county", "—")), st["lat"], st["lon"], st["no2"], st["n3"]))
    h.append('</table></div>')

    h.append('<div class="card"><h2>按县区看</h2>'
             '<table><tr><th>县区</th><th class="num">火点（条）</th><th class="num">点位</th>'
             '<th class="num">持续排放点位（≥%d 天）</th><th class="num">县区 NO₂ 中位</th>'
             '<th class="num">持续点位 NO₂ 中位</th></tr>'
             % MIN_DAYS)
    for nm, a in crows:
        n2 = ("%.1f" % float(np.median(a["no2"]))) if a["no2"] else "—"
        c2 = ("%.1f" % cno2[nm][0]) if nm in cno2 else "—"
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%d</td>'
                 '<td class="num">%d</td><td class="num">%s</td><td class="num">%s</td></tr>'
                 % (AR._esc(nm), format(a["n_fire"], ","), a["pts"], a["hot"], c2, n2))
    h.append('</table>'
             '<div class="note">「县区 NO₂ 中位」是该县区范围内所有 0.022° 格点的中位（不做点位筛选）；'
             '「持续点位 NO₂ 中位」只统计该县区的 ≥%d 天点位，不足 1 个显示 —。'
             '县区归属用射线法对县界多边形判定（忽略极小飞地）。</div></div>'
             % MIN_DAYS)

    crows_d = dict(crows)
    urban = ["文峰区", "北关区", "龙安区"]
    urb_fire = sum(crows_d.get(u, {}).get("n_fire", 0) for u in urban)
    if all(u in cno2 for u in urban) and "安阳县" in cno2:
        h.append('<div class="card"><h2>一个反例：市区三区</h2><div class="big">'
                 '文峰、北关、龙安三区的 NO₂ 月均中位 %.0f / %.0f / %.0f μmol/m²，'
                 '<b>都不低于安阳县（%.0f）</b>；但三区两年火点合计只有 %s 条，'
                 '持续排放点位 <b>0 个</b>。'
                 '</div>'
                 '<div class="note">这说明 <b>NO₂ 高 ≠ 有燃烧排放</b> —— 市区的 NO₂ 主要来自'
                 '交通与生活源，不是工业窑炉。反过来说，本报告真正的证据不是「NO₂ 高」，'
                 '而是「<b>火点与 NO₂ 同时高</b>」的格点：殷都区（NO₂ 中位 %.0f、持续点位 %d 个）'
                 '与安阳县（%.0f、%d 个）。热红外与化学柱浓度是两个物理上独立的测量，'
                 '同时高才构成持续燃烧排放的旁证。</div></div>'
                 % (cno2["文峰区"][0], cno2["北关区"][0], cno2["龙安区"][0],
                    cno2["安阳县"][0], format(urb_fire, ","),
                    cno2["殷都区"][0], crows_d.get("殷都区", {}).get("hot", 0),
                    cno2["安阳县"][0], crows_d.get("安阳县", {}).get("hot", 0)))

    h.append('<div class="card"><h2>持续排放点位清单（≥%d 天，共 %d 个）</h2>'
             '<div class="note">按两年出现天数降序。NO₂ 为 %s 共 %d 个月的月均；'
             '「/周边」= 点位 NO₂ ÷ 周边 20 km 中位；「市域分位」= 在安阳市域格点中的百分位。</div>'
             '<table><tr><th>#</th><th>县区</th><th>坐标</th>'
             '<th class="num">天数</th><th class="num">夜间</th><th class="num">FRP中位</th>'
             '<th class="num">跨月</th><th class="num">NO₂</th><th class="num">市域分位</th>'
             '<th class="num">/周边</th><th>判定</th></tr>'
             % (MIN_DAYS, len(hot), months[0][:4], len(months)))
    for k, p in enumerate(hot, 1):
        kd = CL.classify(p)[0]
        h.append('<tr><td>%d</td><td>%s</td><td>%s</td>'
                 '<td class="num">%d</td><td class="num">%.0f%%</td>'
                 '<td class="num">%.2f</td><td class="num">%d</td>'
                 '<td class="num">%.1f</td><td class="num">%.0f%%</td>'
                 '<td class="num">%.2f</td><td>%s</td></tr>'
                 % (k, AR._esc(p["county"]), p["key"], p["days"], p["night_ratio"] * 100,
                    p["frp_med"], p["n_months"], p["no2"], p["pct_city"], p["ratio"],
                    AR._esc(kd)))
    h.append('</table></div>')

    h.append('<div class="card"><h2>边界与口径</h2>'
             '<table><tr><th>项</th><th>说明</th></tr>'
             '<tr><td>火点口径</td><td>NASA FIRMS VIIRS 375m，2024 + 2025 两年，归属安阳市的全部火点</td></tr>'
             '<tr><td>点位口径</td><td>0.01° 网格（约 1.1 km）聚合；「天数」= 该格点出现火点的<b>不重复日期数</b>'
             '（两年合计，上限 730）</td></tr>'
             '<tr><td>NO₂ 口径</td><td>TROPOMI L3 月产品 %d 个月（%s）平均；原始像元 3.5×5.5 km，'
             '网格 0.022°（约 2.4 km）</td></tr>'
             '<tr><td>⚠ 时间不匹配</td><td>NO₂ 月份与火点月份不同源同期（NO₂ 月产品最新到 2025-03），'
             '因此本报告用「多月平均」做<b>空间</b>对照，不解释逐月数量关系</td></tr>'
             '<tr><td>⚠ 不能做的事</td><td>不能指认企业、不能给排放量、不能区分「这家厂」与「这个园区」</td></tr>'
             '</table></div>'
             % (len(months), "、".join(m[5:] + "月" for m in months)))

    h.append(AR.qr_foot("../../../assets"))


    h.append('<footer>'
             '数据：Sentinel-5P TROPOMI L3 月产品（S5P-PAL，免 key）· NASA FIRMS VIIRS 375m<br>'
             '方法：0.01° 点位聚合 → 两年复现天数/夜间占比/FRP 判定 → 县区射线法归属 → '
             'TROPOMI 月均取点位值并与市域背景比较<br>'
             '<b>边界声明</b>：卫星与遥感都只能提供「疑似 + 依据」的线索，不能确证成因、不能指认主体。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "安阳持续排放点位排查.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("月份:", months)
    print("点位 %d / 持续 %d / 工业源 %d" % (len(prof), len(hot), n_ind))
    print("市域背景 %.1f 全省中位 %.1f 点位NO2中位 %.1f 高于背景 %d/%d"
          % (city_bg, prov_med, med_hot_no2, n_above, len(hot)))
    print("县区:", [(nm, a["n_fire"], a["hot"]) for nm, a in crows])
    print("县区NO2中位:", {k: round(v[0], 1) for k, v in cno2.items()})


if __name__ == "__main__":
    main()
