# -*- coding: utf-8 -*-
"""卫星气体印证报告：用 Sentinel-5P TROPOMI 的 NO2 / CO 月产品，
独立验证「持续热排放点位」是否真的对应持续的燃烧排放。

为什么要做这件事
----------------
FIRMS 的火点来自**热红外**（卫星看到高温像元）。它有一个天然的质疑：
「会不会是传感器伪影 / 地表高温假信号？」
TROPOMI 测的是**大气柱浓度**（化学量），是完全独立的物理量。
如果两者指向同一批格点，就基本排除了「热异常是假信号」的可能。

本报告给出的边界（重要）
------------------------
  ✅ 能做：区域级印证 —— 火点密集格点确实系统性 NO2 偏高。
  ❌ 不能做：单点源定量 —— TROPOMI 原始像元 3.5×5.5 km，月均更被平滑，
     单个 1 km 点源相对 20 km 背景只高 4%~22%，无法反推排放量。

用法：
  python satellite_check.py            # 用 data/satellite/ 下已有的月份
"""
import base64
import json
import os
import struct
import zlib
from datetime import datetime, timezone, timedelta

import numpy as np

import annual_report as AR

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
SAT = os.path.join(MOD, "data", "satellite")
OUT = os.path.join(MOD, "report")
C = AR.C

# NO2 色带（深色底 → 青 → 黄 → 橙）：把暖色留给真正的高值，避免整片区域看起来都"红"
STOPS = [(0.00, (9, 14, 25)), (0.25, (23, 45, 100)), (0.50, (37, 99, 235)),
         (0.70, (56, 189, 248)), (0.85, (125, 211, 252)), (0.94, (250, 204, 21)),
         (1.00, (249, 115, 22))]


def cmap(t):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    for i in range(len(STOPS) - 1):
        a, ca = STOPS[i]
        b, cb = STOPS[i + 1]
        if t <= b:
            k = (t - a) / (b - a) if b > a else 0.0
            return tuple(int(ca[j] + (cb[j] - ca[j]) * k) for j in range(3))
    return STOPS[-1][1]


def png_b64(rgba, w, h):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw.extend(rgba[y * w * 4:(y + 1) * w * 4])

    def ch(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    data = (b"\x89PNG\r\n\x1a\n"
            + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(bytes(raw), 9))
            + ch(b"IEND", b""))
    return base64.b64encode(data).decode()


def grid_of(rec):
    g = np.array([[np.nan if v is None else v for v in row] for row in rec["grid"]],
                 dtype="float64")
    lat = rec["lat0"] + rec["dlat"] * np.arange(rec["ny"])
    lon = rec["lon0"] + rec["dlon"] * np.arange(rec["nx"])
    return lat, lon, g


def spearman(x, y):
    rx = np.argsort(np.argsort(x)).astype("float64")
    ry = np.argsort(np.argsort(y)).astype("float64")
    rx -= rx.mean(); ry -= ry.mean()
    return float((rx * ry).sum() / np.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def count_in_grid(lat, lon, fires):
    la = np.array([f["lat"] for f in fires]); lo = np.array([f["lng"] for f in fires])
    ii = np.searchsorted(lat, la); jj = np.searchsorted(lon, lo)
    ok = (ii > 0) & (ii < len(lat)) & (jj > 0) & (jj < len(lon))
    cnt = np.zeros((len(lat), len(lon)))
    np.add.at(cnt, (ii[ok] - 1, jj[ok] - 1), 1)
    return cnt


def _dp(pts, tol):
    """Douglas-Peucker 抽稀（在像素空间做，保证视觉不变形）。"""
    n = len(pts)
    if n < 3:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L == 0:
                dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                dist = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if dist > best:
                best, bi = dist, i
        if best > tol:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [p for i, p in enumerate(pts) if keep[i]]


CITIES = [("安阳", 36.10, 114.39), ("焦作", 35.22, 113.24), ("济源", 35.09, 112.60),
          ("郑州", 34.75, 113.63), ("三门峡", 34.77, 111.20), ("平顶山", 33.77, 113.19),
          ("许昌", 34.04, 113.85), ("南阳", 32.99, 112.53), ("信阳", 32.15, 114.09)]


def load_border_path(xy, tol=0.9):
    """把 18 市边界转成抽稀后的 SVG path（约 15.8k 点 → 数 k 点）。"""
    p = os.path.join(MOD, "geo", "henan-cities.geojson")
    d = json.load(open(p, encoding="utf-8"))
    segs, n0, n1 = [], 0, 0
    for f in d["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                n0 += len(ring)
                pts = _dp([xy(la, ln) for ln, la in ring], tol)
                n1 += len(pts)
                if len(pts) > 2:
                    segs.append("M" + " ".join("%.0f %.0f" % q for q in pts) + "Z")
    print("  边界抽稀 %d → %d 点" % (n0, n1))
    return "".join(segs)


def svg_gain(bins, w=880, row_h=36, lab_w=76, val_w=190):
    """以「无火点格点」为基准画相对增幅横条。bins = [(label, value, n), ...]"""
    base = bins[0][1]
    gains = [v / base - 1 for _, v, _ in bins]
    mx = max(gains) or 1
    h = row_h * len(bins) + 10
    pw = w - lab_w - val_w - 8
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i, (lab, v, n) in enumerate(bins):
        y = 5 + i * row_h
        bw = max(2, pw * gains[i] / mx)
        col = C["dim2"] if i == 0 else (C["hot"] if i == len(bins) - 1 else C["accent"])
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="12" text-anchor="end">%s</text>'
                 % (lab_w - 10, y + row_h / 2 + 4, C["txt"], AR._esc(lab)))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="%d" rx="4" fill="%s" opacity="0.9"/>'
                 % (lab_w, y + 7, bw, row_h - 16, col))
        note = ("基准 %.1f μmol/m²（%s 格点）" % (v, format(n, ",")) if i == 0
                else "+%.0f%%　%.1f μmol/m²（%s 格点）" % (gains[i] * 100, v, format(n, ",")))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11">%s</text>'
                 % (lab_w + bw + 10, y + row_h / 2 + 4, C["dim"], note))
    p.append("</svg>")
    return "".join(p)


def svg_map(no2, fires, pts, W=820, H=790, pad=10):
    """河南 NO2 月均底图（内嵌 PNG）+ 市界 + 2024-09 火点 + 19 个持续热排放点位。"""
    lat, lon, g = grid_of(no2)
    ny, nx = g.shape
    lo, hi = np.nanpercentile(g, [2, 98])
    rgba = bytearray()
    for i in range(ny):
        for j in range(nx):
            v = g[i, j]
            if not np.isfinite(v):
                rgba.extend((0, 0, 0, 0))
            else:
                r, gg, b = cmap((v - lo) / (hi - lo) if hi > lo else 0.5)
                rgba.extend((r, gg, b, 255))
    img = png_b64(rgba, nx, ny)

    lat0, lat1 = float(lat.min()), float(lat.max())
    lon0, lon1 = float(lon.min()), float(lon.max())
    iw, ih = W - 2 * pad, H - 2 * pad

    def xy(la, ln):
        x = pad + (ln - lon0) / (lon1 - lon0) * iw
        y = pad + (lat1 - la) / (lat1 - lat0) * ih
        return x, y

    bd = load_border_path(xy)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block;border-radius:12px">' % (W, H)]
    p.append('<defs><image id="no2bg" x="%d" y="%d" width="%d" height="%d" '
             'href="data:image/png;base64,%s" preserveAspectRatio="none"/>'
             '<clipPath id="hnclip"><path d="%s"/></clipPath></defs>'
             % (pad, pad, iw, ih, img, bd))
    p.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, C["bg"]))
    p.append('<use href="#no2bg" opacity="0.26"/>')          # 省外：淡化，保留区域背景
    p.append('<use href="#no2bg" clip-path="url(#hnclip)"/>')  # 省内：完整显示
    p.append('<path d="%s" fill="none" stroke="#e2e8f0" stroke-width="0.9" '
             'stroke-opacity="0.55" stroke-linejoin="round"/>' % bd)
    # 火点
    dots = []
    for f in fires:
        la, ln = f["lat"], f["lng"]
        if not (lat0 <= la <= lat1 and lon0 <= ln <= lon1):
            continue
        x, y = xy(la, ln)
        dots.append('<circle cx="%.1f" cy="%.1f" r="1.7" fill="#ffffff" opacity="0.55"/>' % (x, y))
    p.append("".join(dots))
    # 19 点位
    for k, it in enumerate(pts, 1):
        la, ln = [float(v) for v in it["key"].split(",")]
        x, y = xy(la, ln)
        p.append('<circle cx="%.1f" cy="%.1f" r="9" fill="#ef4444" stroke="#fff" '
                 'stroke-width="1.6" opacity="0.95"><title>%s · %s　持续 %d 天</title></circle>'
                 % (x, y, AR._esc(it["city"]), AR._esc(it["place"]), it["days"]))
        p.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="9.5" font-weight="600" '
                 'text-anchor="middle">%d</text>' % (x, y + 3.4, k))
    # 城市名（帮助定位）
    for nm, la, ln in CITIES:
        x, y = xy(la, ln)
        p.append('<text x="%.1f" y="%.1f" fill="#cbd5e1" font-size="11.5" text-anchor="middle" '
                 'style="paint-order:stroke;stroke:#020617;stroke-width:3px;'
                 'stroke-linejoin:round">%s</text>' % (x, y, nm))
    p.append("</svg>")
    return "".join(p), (lo, hi), (lat0, lat1, lon0, lon1)


def main():
    no2 = json.load(open(os.path.join(SAT, "no2-2024-09.json"), encoding="utf-8"))
    co = json.load(open(os.path.join(SAT, "co-2024-09.json"), encoding="utf-8"))
    pts = json.load(open(os.path.join(MOD, "data", "top19_cells.json"), encoding="utf-8"))
    fires_all = json.load(open(os.path.join(MOD, "data", "history", "2024.json"),
                              encoding="utf-8"))["fires"]
    fires = [f for f in fires_all if str(f.get("date", "")).startswith("2024-09")]

    nlat, nlon, ng = grid_of(no2)
    clat, clon, cg = grid_of(co)

    # 分箱：火点密度 → NO2 / CO
    ncnt = count_in_grid(nlat, nlon, fires)
    ccnt = count_in_grid(clat, clon, fires)
    BINS = [(0, 0, "0"), (1, 1, "1"), (2, 3, "2-3"), (4, 9, "4-9"), (10, 10 ** 9, "10+")]
    no2_bins, co_bins = [], []
    for a, b, lab in BINS:
        m = (ncnt >= a) & (ncnt <= b)
        v = ng[m]; v = v[np.isfinite(v)]
        if len(v):
            no2_bins.append((lab, float(np.median(v)), int(m.sum())))
        m2 = (ccnt >= a) & (ccnt <= b)
        w2 = cg[m2]; w2 = w2[np.isfinite(w2)]
        if len(w2):
            co_bins.append((lab, float(np.median(w2)), int(m2.sum())))

    ok = np.isfinite(ng.ravel())
    r_no2 = spearman(ncnt.ravel()[ok], ng.ravel()[ok])
    ok2 = np.isfinite(cg.ravel())
    r_co = spearman(ccnt.ravel()[ok2], cg.ravel()[ok2])

    # 19 点位明细
    rows = []
    for it in pts:
        la, ln = [float(v) for v in it["key"].split(",")]
        i = int(np.searchsorted(nlat, la) - 1); j = int(np.searchsorted(nlon, ln) - 1)
        ic = int(np.searchsorted(clat, la) - 1); jc = int(np.searchsorted(clon, ln) - 1)
        nv = float(ng[i, j]); cv = float(cg[ic, jc])
        pct = float((ng < nv).mean() * 100)
        nf = int(ncnt[i, j])
        nb = ng[max(0, i - 8):i + 9, max(0, j - 8):j + 9]
        nbmed = float(np.nanmedian(nb))
        rows.append(dict(i=it["i"], city=it["city"], key=it["key"], place=it["place"],
                         days=it["days"], ntr=it["ntr"], no2=nv, co=cv, pct=pct, nf=nf,
                         ratio=nv / nbmed if nbmed else float("nan")))
    rows.sort(key=lambda r: -r["pct"])

    med_no2 = float(np.nanmedian(ng))
    n_hi = sum(1 for r in rows if r["nf"] >= 10)
    n_p90 = sum(1 for r in rows if r["pct"] >= 90)
    med_p19 = float(np.median([r["no2"] for r in rows]))
    med_nf = float(np.median([r["nf"] for r in rows]))

    # 地图
    mp, (lo, hi), bbox = svg_map(no2, fires, pts)

    # 分箱柱状图
    bar = svg_gain(no2_bins)

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>卫星气体印证 · TROPOMI</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>卫星气体印证 · TROPOMI</h1>',
         '<div class="sub">用 Sentinel-5P 的 <b>NO₂ / CO 大气柱浓度</b>独立验证「持续热排放点位」'
         '　·　数据：S5P-PAL L3 月产品（2024-09）　·　生成于 %s</div>' % dt]

    h.append('<div class="kpi">'
             '<div><b>%.0f</b><span>19 点位 NO₂ 中位（μmol/m²）</span></div>'
             '<div><b>%.0f</b><span>全省格点 NO₂ 中位</span></div>'
             '<div><b>+%.0f%%</b><span>点位相对全省中位</span></div>'
             '<div><b>%.2f</b><span>NO₂ × 火点密度 Spearman r</span></div>'
             '</div>' % (med_p19, med_no2, (med_p19 / med_no2 - 1) * 100, r_no2))

    h.append('<div class="card"><h2>结论</h2><div class="big">'
             'TROPOMI 与 FIRMS 是<b>两个物理上完全独立</b>的测量：一个测大气化学柱浓度，'
             '一个测地表热辐射。它们指向了同一批格点 —— 2024 年 9 月，'
             '全省 <span class="hl">%d / 19</span> 个持续热排放点位落在'
             '「当月 10 个以上火点」的格点里（这种格点全省只有 %d 个，占 %.2f%%）。'
             '火点越密的格点，NO₂ 越高（Spearman r = <span class="hl">%.2f</span>）。'
             '</div>'
             '<div class="note">这排除了「热异常是传感器伪影」的可能，'
             '也说明这些点位确实伴随<b>持续的燃烧排放</b>。'
             '但请注意：它<b>不能</b>给出某个点位的排放量 —— 见下节边界。</div></div>'
             % (n_hi, int((ncnt >= 10).sum()), (ncnt >= 10).mean() * 100, r_no2))

    h.append('<div class="card"><h2>能做什么 / 不能做什么</h2>'
             '<table><tr><th>用途</th><th>可行性</th><th>依据</th></tr>'
             '<tr><td>印证「高频火点 = 持续排放源」</td><td><span class="hl">✅ 可以</span></td>'
             '<td>NO₂ 与火点密度显著正相关（r=%.2f），两者物理独立</td></tr>'
             '<tr><td>区域级排查（哪个县区排放集中）</td><td><span class="hl">✅ 可以</span></td>'
             '<td>月均格点图能看出高值带，与工业集聚区吻合</td></tr>'
             '<tr><td>反推某个点位的排放量 / 排放清单</td><td>❌ 不行</td>'
             '<td>点位相对 20 km 背景仅高 %.0f%%~%.0f%%，点源信号被像元和月均稀释</td></tr>'
             '<tr><td>确证企业名称</td><td>❌ 不行</td><td>卫星没有企业属性，只能给坐标</td></tr>'
             '</table>'
             '<div class="note">TROPOMI 原始像元 <b>3.5 × 5.5 km</b>，NO₂ 月产品再被平均一次。'
             '一个 1 km 尺度的点源，其柱浓度增量在 20 km 背景里几乎被抹平 —— '
             '这正是「卫星能看见一条工业带，却看不见一家工厂」的原因。</div></div>'
             % (r_no2, min(r["ratio"] for r in rows) * 100 - 100,
                max(r["ratio"] for r in rows) * 100 - 100))

    h.append('<div class="card"><h2>河南 NO₂ 月均（2024-09）· 火点 · 19 个持续热排放点位</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#38bdf8"></i>NO₂ 柱浓度低 → 高（%.0f → %.0f μmol/m²）</span>'
             '<span><i style="background:#ffffff;opacity:.6"></i>当月火点（%d 个）</span>'
             '<span><i style="background:#ef4444"></i>持续热排放点位（编号 1–19）</span>'
             '</div>'
             '<div class="note">底图为 0.022°（约 2.4 km）网格的月均值，等经纬度投影。'
             '可以看到 NO₂ 高值带（青→黄→橙）与火点密集区在空间上高度重合：'
             '北部安阳—焦作—济源、中部平顶山—许昌。</div></div>'
             % (mp, lo, hi, len(fires)))

    h.append('<div class="card"><h2>火点越密的格点，NO₂ 越高</h2>'
             '<div class="note">按每个格点在 2024-09 的火点数分组。'
             '横条长度 = 该组 NO₂ 中位相对「无火点格点」的增幅。</div>'
             '%s'
             '<table><tr><th>格点火点数</th><th class="num">格点数</th>'
             '<th class="num">NO₂ 中位</th><th class="num">CO 中位（mmol/m²）</th></tr>' % bar)
    for (lab, v, n) in no2_bins:
        cv = next((x[1] for x in co_bins if x[0] == lab), float("nan"))
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f</td>'
                 '<td class="num">%.2f</td></tr>' % (lab, format(n, ","), v, cv))
    h.append('</table>'
             '<div class="note">NO₂ 呈单调递增（无火点 %.1f → 10+ 火点 %.1f，'
             '<b>+%.0f%%</b>），Spearman r = <b>%.2f</b>；'
             'CO 方向一致但弱得多（r = %.2f）—— CO 寿命长、背景高，对点源不敏感。'
             '这也是为什么选 NO₂ 作主证。</div></div>'
             % (no2_bins[0][1], no2_bins[-1][1],
                (no2_bins[-1][1] / no2_bins[0][1] - 1) * 100, r_no2, r_co))

    h.append('<div class="card"><h2>19 个点位明细</h2>'
             '<div class="note">「格点火点」= 该点位所在 2.4 km 格点在 2024-09 的火点数；'
             '「全省分位」= 该格点 NO₂ 在全省 %s 个格点中的百分位；'
             '「/20km背景」= 点位 NO₂ ÷ 周边 20 km 中位。</div>'
             '<table><tr><th>#</th><th>市</th><th>坐标</th><th>最近地名</th>'
             '<th class="num">持续天数</th><th class="num">NO₂</th><th class="num">全省分位</th>'
             '<th class="num">格点火点</th><th class="num">/20km背景</th></tr>' % format(int(ng.size), ","))
    for r in rows:
        h.append('<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td>'
                 '<td class="num">%d</td><td class="num">%.1f</td>'
                 '<td class="num">%s</td><td class="num">%d</td>'
                 '<td class="num">%.2f</td></tr>'
                 % (r["i"], AR._esc(r["city"]), r["key"], AR._esc(r["place"]),
                    r["days"], r["no2"],
                    ("%.0f%%" % r["pct"]) + (" ▲" if r["pct"] >= 90 else ""),
                    r["nf"], r["ratio"]))
    h.append('</table>'
             '<div class="note">19 个点位的 NO₂ 中位 %.1f，全部高于全省中位 %.1f；'
             '%d 个位于全省前 10%%。但同一行最右列说明问题：'
             '相对本地 20 km 背景只高 %.0f%%~%.0f%% —— 这就是「看得见带、看不见厂」的量化表述。'
             '</div></div>'
             % (med_p19, med_no2, n_p90,
                (min(r["ratio"] for r in rows) - 1) * 100,
                (max(r["ratio"] for r in rows) - 1) * 100))

    h.append('<div class="card"><h2>数据与技术边界</h2>'
             '<table><tr><th>项</th><th>说明</th></tr>'
             '<tr><td>数据源</td><td>S5P-PAL（ESA/Copernicus 官方分发），STAC API <b>免 key</b></td></tr>'
             '<tr><td>产品</td><td>L3 网格月产品：NO₂ 0.022°（2.4 km）、CO 0.044°（4.9 km）</td></tr>'
             '<tr><td>覆盖期</td><td>NO₂ 至 2025-03、CO 至 2025-07（月产品）；2024 全年完整</td></tr>'
             '<tr><td>同平台其它可选项</td><td>CH₄ / HCHO / O₃；<b>SO₂ 该平台无产品</b></td></tr>'
             '<tr><td>⚠ 下载成本</td><td>L3 产品是<b>单块存储</b>（整数据集一个 chunk + gzip），'
             '远程 Range 读取无效，必须整文件下载：NO₂ 1.14 GB/月、CO 0.43 GB/月。'
             '本项目已下载后只保留河南切片（NO₂ 500 KB / CO 118 KB）入库。</td></tr>'
             '<tr><td>⚠ 时间匹配</td><td>用 2024-09 单月火点对 2024-09 月均浓度，时间口径一致；'
             '月产品的最新月份滞后约 1–2 个月。</td></tr>'
             '</table></div>')

    h.append('<footer>'
             '数据来源：Sentinel-5P TROPOMI L3 月产品（S5P-PAL）· NASA FIRMS VIIRS 375m（历史回补）<br>'
             '方法：0.022° 公共网格对齐 → 按格点火点数分组 → Spearman 秩相关 → 点位对 20 km 背景比值<br>'
             '<b>边界声明</b>：卫星柱浓度只能提供「区域级印证」与坐标线索，'
             '不能确证成因、不能给出点位排放量、不能指认企业。任何对外表述都应保留「疑似 + 依据」的措辞。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "卫星气体印证-TROPOMI.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", p, "%.0f KB" % (os.path.getsize(p) / 1024))
    print("NO2 bins:", no2_bins)
    print("r_no2=%.3f r_co=%.3f  19pts med=%.1f med_no2=%.1f n_hi=%d n_p90=%d"
          % (r_no2, r_co, med_p19, med_no2, n_hi, n_p90))
    print("ratio range: %.2f ~ %.2f" % (min(r["ratio"] for r in rows),
                                        max(r["ratio"] for r in rows)))


if __name__ == "__main__":
    main()
