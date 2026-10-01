# -*- coding: utf-8 -*-
"""小时序列看板（纯渲染层，无 DB / 网络依赖）。

存在的理由：项目一直在"采小时"，但小时数据此前只有三个原始出口
  ① data/air.db 的 station_hourly（要看只能连库）
  ② data/raw/<日期>/*.json（原始报文）
  ③ 云端 data-hourly/YYYY-MM-DD.jsonl（GitHub 上点开是 JSON 文本）
→ 没有任何"能直接看"的入口，等于"采了看不见"。本模块补上这一个口子。

设计约束（与全项目口径红线一致）：
  - 城市值按 HJ 663-2013 取点位平均，不取最差点位；
  - O₃-8h 是平台按**当前小时**推算的滑动值，不等于日最大 8 小时均值 → 图注必须标「当前值口径」；
  - 平台数据为未审核实时值 → 页面必须声明，且保留「AI草稿·未经审定」水印；
  - 不依赖任何 CDN / 外部 JS（折线与地图一律自绘 SVG），离线与打印均可看。

地图为什么自绘、且不画行政边界
------------------------------
本页要在三种场景下同时成立：本机离线打开、打印成纸质件、公开站点（GitHub Pages）访问。
真底图只能靠在线瓦片服务，一旦断网/在公开站上就会白屏，等于把最直观的一屏丢掉。
而手工描画国界/省界存在画错的高风险，且坐标一旦描错无法自证。
因此这里的「区域态势图」是**按真实经纬度定位的相对位置示意图**：
只画城市点位、风矢、经纬网与比例尺，不画任何行政边界，
用来回答"谁在谁的哪个方位、上风向是谁、当前谁更脏"，
**不能用于任何边界认定**。若日后需要真实底图，应另行接入合规地图服务，
不要在本模块里手描边界。
"""
import math
from datetime import datetime, timedelta

CITY_COLOR = {
    "安阳市": "#c0392b",
    "濮阳市": "#2b6cb0",
    "鹤壁市": "#2f6b4f",
    "新乡市": "#b3541e",
}
_FALLBACK = ["#c0392b", "#2b6cb0", "#2f6b4f", "#b3541e", "#7a4fa3", "#0f7b7b"]

# AQI 等级（HJ 633-2012）：上限、名称、色。用于折线背景色带与矩阵格色。
AQI_GRADES = [
    (50, "优", "#1E9E5A"),
    (100, "良", "#C9A227"),
    (150, "轻度污染", "#E07B1A"),
    (200, "中度污染", "#C93A31"),
    (300, "重度污染", "#8446A0"),
    (10 ** 9, "严重污染", "#6B1B2E"),
]

# 首要污染物归并：平台给的是中文串（如「颗粒物(PM10),细颗粒物(PM2.5)」），先归并再统计。
# 「优（无首要）」与「缺字段」必须分开：前者是 AQI≤50 时平台**本就不给**首要污染物
# （合规行为，说明当天干净），后者是接口没返回（数据质量问题）——
# 合成一类会把"天干净"读成"数据烂"，是方向性误判。
PRI_BUCKETS = [
    ("PM2.5", "#C0392B"),
    ("PM2.5+PM10", "#7A4FA3"),
    ("PM10", "#B3541E"),
    ("O₃", "#2B6CB0"),
    ("其他", "#5F7A6E"),
    ("优（无首要）", "#AFC9B8"),
    ("缺字段", "#C3CCC6"),
]

METRICS = [
    ("aqi", "实时 AQI", "AQI", 0),
    ("pm25", "PM2.5", "μg/m³", 0),
    ("o3_8h", "O₃-8h（当前值口径）", "μg/m³", 0),
    ("wind_speed", "风速", "m/s", 1),
    ("blh", "边界层高度 BLH", "m", 0),
]

# 参与聚合的污染物键（多取几个不亏：日志/矩阵/构成图都要用）
AGG_KEYS = ("aqi", "pm25", "pm10", "o3_8h", "no2", "so2", "co")
WX_KEYS = ("wind_speed", "wind_dir", "blh", "temp", "rh")


def grade(v):
    """AQI →（等级名, 色）。None 返回灰。"""
    if v is None:
        return ("—", "#B9C4BE")
    for hi, name, col in AQI_GRADES:
        if v <= hi:
            return (name, col)
    return ("严重污染", "#6B1B2E")


def _pri_bucket(s):
    t = str(s or "").strip()
    if t in ("", "NA", "—", "－", "无", "None"):
        return "无/缺"
    has25 = ("PM2.5" in t) or ("PM25" in t)
    has10 = "PM10" in t
    if has25 and has10:
        return "PM2.5+PM10"
    if has25:
        return "PM2.5"
    if has10:
        return "PM10"
    if ("O3" in t) or ("臭氧" in t):
        return "O₃"
    return "其他"


def _c(i, name):
    if name in CITY_COLOR:
        return CITY_COLOR[name]
    return _FALLBACK[i % len(_FALLBACK)]


def _hh(tp):
    s = str(tp)
    return s[11:16] if len(s) >= 16 else s


def _dd(tp):
    s = str(tp)
    return s[5:10] if len(s) >= 10 else s


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _to_dt(tp):
    try:
        return datetime.strptime(str(tp), "%Y-%m-%dT%H:%M")
    except Exception:
        return None


def _num(v, dec=0):
    if v is None:
        return "—"
    try:
        return ("%%.%df" % dec) % float(v)
    except Exception:
        return "—"


# ── 区域自称（"豫北四市" / "豫西六市"）────────────────────────────────
# 同一份渲染器服务两套档案（豫北日报模块 + 豫西日报板块），页面自称一律现算，不写死。
# 为什么用模块级当前值而不是逐函数传参：这些字符串散布在 6 个绘图函数里，
# 逐个传参要改十几处调用点；本模块是"调一次渲染一张静态页"的纯函数集合，
# 单进程内不存在并发，模块级最省事也最不容易漏掉（2026-10-01 加豫西看板时改）。
_REGION = "本地各市"
_CN_NUM = {2: "两", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


def region_label():
    """当前页面的区域自称，例：豫北四市 / 豫西六市（由 render_hourly 入口按档案设定）"""
    return _REGION


def _set_region(cities, region_name=""):
    global _REGION
    n = len(cities or [])
    _REGION = "%s%s市" % (region_name or "", _CN_NUM.get(n, str(n)))
    return _REGION


def _city_short(city):
    """'三门峡市' → '三门峡'（页眉城市列用全称，避免 [:2] 写成"三门"）"""
    c = str(city or "")
    return c[:-1] if c.endswith("市") else c


# ================================================================ 折线
def line_chart(series, xs, y_unit, height=240, width=980, note="",
               bands=False, ref_lines=None, ymin=0.0):
    """series: [(name, color, {tp: value})]；xs: 已排序的时点列表。

    X 轴按**真实时间**比例定位（不是按序号等距）：
    平台没有小时级历史接口，漏采是常态；若按序号等距画，10 小时的缺口会被压缩成
    与 1 小时相同的间距，看上去像连续序列 —— 那正好掩盖了本页要暴露的问题。
    同时在间隔 > 2 小时处**断开折线**，只保留真实的连续段。

    bands=True 时铺 AQI 等级背景色带（把"是否超标"变成一眼可见）；
    ref_lines 为 [(值, 标签, 色)]，用于国标限值参考线（如 PM2.5 75、O₃-8h 160）。
    """
    pad_l, pad_r, pad_t, pad_b = 52, 14, 20, 46
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    vals = [v for _, _, d in series for tp, v in d.items() if v is not None and tp in xs]
    if not vals or not xs:
        return "<p class='sub2'>暂无数据。</p>"
    vmin = ymin
    vmax = max(vals)
    if ref_lines:
        vmax = max(vmax, max(r[0] for r in ref_lines))
    vmax = vmax * 1.12 if vmax > 0 else 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0

    t0 = _to_dt(xs[0])
    t1 = _to_dt(xs[-1])
    if t0 is None or t1 is None:
        return "<p class='sub2'>时点格式异常。</p>"
    span = max((t1 - t0).total_seconds() / 3600.0, 1.0)
    off = {tp: (_to_dt(tp) - t0).total_seconds() / 3600.0 for tp in xs if _to_dt(tp)}

    def X(tp):
        return pad_l + off[tp] / span * iw

    def Y(v):
        return pad_t + ih - (v - vmin) / (vmax - vmin) * ih

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]

    # AQI 等级色带（先铺底，再画网格与数据）
    if bands:
        prev = vmin
        for hi, gname, gcol in AQI_GRADES:
            top = min(float(hi), vmax)
            if top <= prev:
                if hi >= vmax:
                    break
                continue
            y_top, y_bot = Y(top), Y(prev)
            g.append("<rect x='%d' y='%.1f' width='%d' height='%.1f' fill='%s' fill-opacity='0.14'/>"
                     % (pad_l, y_top, iw, max(y_bot - y_top, 0), gcol))
            if (y_bot - y_top) >= 13:
                g.append("<text x='%d' y='%.1f' font-size='10' fill='#7c8a83' text-anchor='end'>%s</text>"
                         % (pad_l + iw - 4, y_bot - 4, _esc(gname)))
            prev = float(hi)
            if hi >= vmax:
                break

    # 日界竖线（让"漏了多久"有一眼可量的标尺）
    day = t0.replace(hour=0, minute=0)
    if day < t0:
        day = day + timedelta(days=1)
    while day <= t1:
        x = pad_l + (day - t0).total_seconds() / 3600.0 / span * iw
        g.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#f0e2c8' stroke-width='1'/>"
                 % (x, pad_t, x, pad_t + ih))
        g.append("<text x='%.1f' y='%d' font-size='9.5' fill='#b3541e' text-anchor='middle'>%s</text>"
                 % (x, pad_t + 10, day.strftime("%m-%d")))
        day = day + timedelta(days=1)

    # 水平网格 + Y 刻度
    for k in range(6):
        v = vmin + (vmax - vmin) * k / 5.0
        y = Y(v)
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e8ece9' stroke-width='1'/>"
                 % (pad_l, y, pad_l + iw, y))
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='#71807a' text-anchor='end'>%s</text>"
                 % (pad_l - 6, y + 3.5, ("%.1f" % v) if vmax < 10 else ("%.0f" % v)))

    # 国标限值参考线
    for val, label, col in (ref_lines or []):
        if val < vmin or val > vmax:
            continue
        y = Y(val)
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='%s' stroke-width='1.4'"
                 " stroke-dasharray='6 4' fill='none'/>" % (pad_l, y, pad_l + iw, y, col))
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='%s' font-weight='bold'>%s</text>"
                 % (pad_l + 5, y - 4, col, _esc(label)))

    g.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#c9d4cd' stroke-width='1'/>"
             % (pad_l, pad_t + ih, pad_l + iw, pad_t + ih))

    # 数据：点全画；线只在相邻间隔 ≤2h 时连（缺口断开，不假装连续）
    for name, color, d in series:
        pts = [(tp, d[tp]) for tp in xs if d.get(tp) is not None]
        if not pts:
            continue
        seg = []
        for i, (tp, v) in enumerate(pts):
            seg.append((X(tp), Y(v)))
            if i + 1 < len(pts) and (off[pts[i + 1][0]] - off[tp]) <= 2.0:
                continue
            if len(seg) >= 2:
                g.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='2'"
                         " stroke-linejoin='round'/>"
                         % (" ".join("%.1f,%.1f" % p for p in seg), color))
            seg = []
        for tp, v in pts:
            g.append("<circle cx='%.1f' cy='%.1f' r='3.2' fill='%s' stroke='#fff' stroke-width='1'/>"
                     % (X(tp), Y(v), color))

    g.append("<text x='%d' y='%d' font-size='10.5' fill='#71807a'>%s</text>"
             % (pad_l, pad_t - 6, _esc(y_unit)))
    g.append("</svg>")

    legend = " ".join(
        "<span style='display:inline-block;margin-right:12px;font-size:12.4px;color:#41504a'>"
        "<i style='display:inline-block;width:16px;height:3px;background:%s;vertical-align:3px;"
        "margin-right:5px;border-radius:2px'></i>%s</span>" % (c, _esc(nm))
        for nm, c, _ in series)
    out = "<div class='tscroll'>" + "".join(g) + "</div><div class='legend'>" + legend
    if note:
        out += " <span class='sub2'>" + note + "</span>"
    out += "</div>"
    return out


# ================================================================ 区域态势图（自绘地图）
def situation_map(points, width=980, height=470, note=""):
    """区域态势图：按真实经纬度定位的相对位置**示意图**（不画行政边界）。

    points: [dict(name, lat, lon, aqi, wd, ws, kind, tp)]
            kind='main' 本地城市（气泡大、带风矢）；kind='neighbor' 上风向邻居（气泡小、淡）。
    投影：等距圆柱 + 纬度余弦校正（保证东西向不被拉扁），按包围盒等比缩放并居中。
    """
    pts = [p for p in points if p.get("lat") is not None and p.get("lon") is not None]
    if len(pts) < 2:
        return "<p class='sub2'>坐标或数据不足，暂无法绘制区域态势图。</p>"

    lats = [p["lat"] for p in pts]
    lons = [p["lon"] for p in pts]
    lat0, lat1 = min(lats), max(lats)
    lon0, lon1 = min(lons), max(lons)
    latm = (lat0 + lat1) / 2.0
    kx = math.cos(math.radians(latm))          # 经度 → 公里的纬度余弦校正

    pad_l, pad_r, pad_t, pad_b = 52, 52, 34, 46
    boxw, boxh = width - pad_l - pad_r, height - pad_t - pad_b
    urange = max((lon1 - lon0) * kx, 1e-6)
    vrange = max(lat1 - lat0, 1e-6)
    scale = min(boxw / urange, boxh / vrange)
    offx = pad_l + (boxw - urange * scale) / 2.0
    offy = pad_t + (boxh - vrange * scale) / 2.0

    def P(lat, lon):
        return (offx + (lon - lon0) * kx * scale, offy + (lat1 - lat) * scale)

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]
    g.append("<rect x='%d' y='%d' width='%d' height='%d' rx='10' fill='#f8fbf7'"
             " stroke='#dfe7e1' stroke-width='1'/>" % (pad_l - 18, pad_t - 18,
                                                       boxw + 36, boxh + 36))

    # 经纬网（每 0.5°，仅作方位/距离参考，非行政边界）
    latln = math.ceil(lat0 * 2.0) / 2.0
    while latln <= lat1:
        _x, y = P(latln, lon0)
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e9efe9' stroke-width='1'/>"
                 % (pad_l - 8, y, pad_l + boxw + 8, y))
        g.append("<text x='%d' y='%.1f' font-size='9.5' fill='#a9b6ae' text-anchor='start'>%s°N</text>"
                 % (pad_l - 4, y - 3, ("%.1f" % latln)))
        latln += 0.5
    lonln = math.ceil(lon0 * 2.0) / 2.0
    while lonln <= lon1:
        x, _y = P(lat1, lonln)
        g.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#e9efe9' stroke-width='1'/>"
                 % (x, pad_t - 8, x, pad_t + boxh + 8))
        g.append("<text x='%.1f' y='%d' font-size='9.5' fill='#a9b6ae' text-anchor='middle'>%s°E</text>"
                 % (x, pad_t + boxh + 20, ("%.1f" % lonln)))
        lonln += 0.5

    # 风矢（先画，压在气泡下面）
    # 气象风向 wd 是"风从哪个方位吹来"（0/360=北，90=东），箭头画"吹向"（wd+180）。
    for p in pts:
        wd, ws = p.get("wd"), p.get("ws")
        if wd is None or ws is None:
            continue
        try:
            wd, ws = float(wd), float(ws)
        except Exception:
            continue
        x, y = P(p["lat"], p["lon"])
        aqi = p.get("aqi")
        r = 16 + min(aqi or 0, 300) / 300.0 * 8
        a = math.radians((wd + 180.0) % 360.0)
        dx, dy = math.sin(a), -math.cos(a)
        x0, y0 = x + dx * (r + 2), y + dy * (r + 2)
        L = 20 + min(ws, 10.0) * 6
        x1, y1 = x0 + dx * L, y0 + dy * L
        g.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='#41678a'"
                 " stroke-width='2.2' stroke-linecap='round'/>" % (x0, y0, x1, y1))
        px, py = -dy, dx
        g.append("<path d='M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f Z' fill='#41678a'/>"
                 % (x1 + dx * 7.5, y1 + dy * 7.5,
                    x1 + px * 4.6, y1 + py * 4.6,
                    x1 - px * 4.6, y1 - py * 4.6))

    # 气泡（数据点）
    for p in pts:
        x, y = P(p["lat"], p["lon"])
        main = p.get("kind") != "neighbor"
        aqi = p.get("aqi")
        _nm, col = grade(aqi)
        r = (16 + min(aqi or 0, 300) / 300.0 * 8) if main else 11.0
        if main:
            # 悬停给出"数字从哪来"：时点 + 等级 + 风（含采样高度说明见下方警示行）
            ttl = "%s ｜ %s ｜ AQI %s（%s）" % (p["name"], p.get("tp") or "—", _num(aqi), _nm)
            if p.get("wd") is not None and p.get("ws") is not None:
                ttl += " ｜ 风 %s（%s°）%s m/s" % (_wd_cn(p["wd"]), _num(p["wd"]),
                                                  _num(p["ws"], 1))
            g.append("<circle cx='%.1f' cy='%.1f' r='%.1f' fill='%s' stroke='#ffffff'"
                     " stroke-width='2.5'><title>%s</title></circle>"
                     % (x, y, r, col, _esc(ttl)))
            g.append("<text x='%.1f' y='%.1f' font-size='11.5' font-weight='bold' fill='#ffffff'"
                     " text-anchor='middle'>%s</text>" % (x, y + 4.1, _num(aqi)))
            g.append("<text x='%.1f' y='%.1f' font-size='12.6' font-weight='bold' fill='#1f2b26'"
                     " text-anchor='middle'>%s</text>" % (x, y - r - 7, _esc(p["name"])))
        else:
            ttl = "%s ｜ %s ｜ AQI %s（%s）· 未采气象" % (p["name"], p.get("tp") or "—",
                                                        _num(aqi), _nm)
            g.append("<circle cx='%.1f' cy='%.1f' r='%.1f' fill='%s' fill-opacity='0.52'"
                     " stroke='%s' stroke-width='1.4' stroke-dasharray='3 2'>"
                     "<title>%s</title></circle>" % (x, y, r, col, col, _esc(ttl)))
            g.append("<text x='%.1f' y='%.1f' font-size='9.6' fill='#33443c'"
                     " text-anchor='middle'>%s</text>" % (x, y + 3.4, _num(aqi)))
            g.append("<text x='%.1f' y='%.1f' font-size='11' fill='#71807a'"
                     " text-anchor='middle'>%s</text>" % (x, y + r + 13, _esc(p["name"])))

    # 指北针
    nx, ny = width - 34, 30
    g.append("<path d='M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f Z' fill='#41504a'/>"
             % (nx, ny, nx - 6, ny + 16, nx + 6, ny + 16))
    g.append("<text x='%.1f' y='%.1f' font-size='11' font-weight='bold' fill='#41504a'"
             " text-anchor='middle'>北</text>" % (nx, ny - 3))

    # 比例尺（50 km；1° 纬度 ≈ 110.574 km）
    bar = 50.0 / 110.574 * scale
    bx, by = pad_l + 6, height - 20
    g.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='#41504a' stroke-width='1.6'/>"
             % (bx, by, bx + bar, by))
    g.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='#41504a' stroke-width='1.6'/>"
             % (bx, by - 4, bx, by + 4))
    g.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='#41504a' stroke-width='1.6'/>"
             % (bx + bar, by - 4, bx + bar, by + 4))
    g.append("<text x='%.1f' y='%.1f' font-size='10.5' fill='#41504a'>50 km</text>"
             % (bx + bar + 7, by + 4))
    g.append("</svg>")

    lg = ["<div class='legend' style='margin-top:8px'>"
          "<b>实心大泡</b>＝%s（泡内数字＝该市最近时点实时 AQI，各市时点可能不同；"
          "深蓝箭头＝风矢，指向<b>下游</b>、长度随风速增大），"
          "箭头与该市 AQI 取<b>同一小时</b>，<b>悬停</b>可见时点、等级与风速风向；"
          "<b>虚线小泡</b>＝上风向邻居城市（若本窗口已采到；仅显示其当前 AQI，"
          "暂未采其气象，故无风矢）。</div>" % region_label()]
    lg.append("<div class='legend' style='margin-top:6px'>"
              "<b>AQI 等级</b>："
              + " ".join("<span style='display:inline-block;margin-right:10px;font-size:12.2px;color:#41504a'>"
                         "<i style='display:inline-block;width:12px;height:12px;background:%s;"
                         "border-radius:3px;vertical-align:-2px;margin-right:4px'></i>%s</span>"
                         % (col, _esc(nm)) for _hi, nm, col in AQI_GRADES)
              + "</div>")
    lg.append("<div class='warn' style='margin-top:8px'>本图为<b>按真实经纬度定位的相对位置示意图</b>，"
              "未绘制任何行政边界，<b>不可用于边界认定或行政管辖判据</b>；"
              "经纬网仅作方位与距离参考。邻居城市坐标取城区中心近似值（0.1° 量级）。</div>")
    if note:
        lg.append("<div class='sub2' style='margin-top:4px'>" + note + "</div>")
    return "<div class='tscroll'>" + "".join(g) + "</div>" + "".join(lg)


# ================================================================ 城市 × 小时 AQI 矩阵
def aqi_matrix(series_val, xs, cities):
    """行＝城市×日期，列＝0..23 时，格色＝AQI 等级、格内数字＝点位平均 AQI。

    与折线互补：折线看走势，矩阵看"哪天哪个时段高"，且能同时暴露漏采格。
    """
    days = sorted({tp[:10] for tp in xs})
    if not days or not cities:
        return "<p class='sub2'>暂无数据。</p>"
    hdr = "".join("<th style='text-align:center;padding:2px 0;font-size:9.5px'>%02d</th>" % h
                  for h in range(24))
    rows = []
    for i, c in enumerate(cities):
        d = series_val.get((c, "aqi")) or {}
        first = True
        for ds in days:
            cells = []
            for h in range(24):
                tp = "%sT%02d:00" % (ds, h)
                v = d.get(tp)
                if v is None:
                    cells.append("<td class='mx0' title='%s %02d:00 无数据（未采到）'>·</td>" % (ds, h))
                else:
                    nm, col = grade(v)
                    fg = "#ffffff" if (v > 100 or v <= 50) else "#20302a"
                    cells.append("<td class='mx' style='background:%s;color:%s'"
                                 " title='%s %02d:00 ｜ %s ｜ AQI %.0f（%s）'>%.0f</td>"
                                 % (col, fg, ds, h, _esc(c), v, nm, v))
            rows.append(
                "<tr><td class='mxlbl'>%s%s</td>%s</tr>"
                % (_esc(c) if first else "", "<br><span class='sub2'>%s</span>" % _dd(ds),
                   "".join(cells)))
            first = False
        if i < len(cities) - 1:
            rows.append("<tr class='mxsep'><td colspan='25'></td></tr>")
    return ("<div class='tscroll'><table class='mxt'><thead><tr>"
            "<th style='padding:2px 6px;font-size:10.5px'>城市 \\ 时</th>" + hdr +
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            "<div class='legend'>格色＝AQI 等级（同上方色阶），格内＝该时点%s<b>点位平均</b> AQI"
            "（HJ 663-2013）；<span style='color:#c98b8b'>淡红「·」＝该小时未采到</span>。"
            "鼠标悬停任一格可看完整信息。</div>" % region_label())


# ================================================================ 昼夜切换（小时廓线）
def hour_profile(series, note=""):
    """按"时钟小时"聚合的小时廓线：把窗口内所有天压成 24 个点。

    比逐时折线更能看清形态 —— 颗粒物夜间累积、臭氧午后光化学生成，
    两条线在同一坐标系（同为 μg/m³）里交叉，就是"昼夜切换"的直接证据。
    """
    if not series:
        return "<p class='sub2'>暂无数据。</p>"
    width, height = 980, 270
    pad_l, pad_r, pad_t, pad_b = 52, 16, 22, 44
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    vals = [v for _, _, d in series for v in d.values() if v is not None]
    if not vals:
        return "<p class='sub2'>暂无数据。</p>"
    vmax = max(vals) * 1.15
    vmin = 0.0

    def X(h):
        return pad_l + h / 23.0 * iw

    def Y(v):
        return pad_t + ih - (v - vmin) / (vmax - vmin) * ih

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]
    # 白天带（06–18 时）
    g.append("<rect x='%.1f' y='%d' width='%.1f' height='%d' fill='#fdf3dd'/>"
             % (X(6), pad_t, X(18) - X(6), ih))
    g.append("<text x='%.1f' y='%d' font-size='10' fill='#b8933f' text-anchor='middle'>白天 06–18 时</text>"
             % ((X(6) + X(18)) / 2.0, pad_t + 12))
    g.append("<text x='%.1f' y='%d' font-size='10' fill='#8a9bb0' text-anchor='middle'>夜间</text>"
             % ((X(0) + X(6)) / 2.0, pad_t + 12))
    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4.0
        y = Y(v)
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e8ece9' stroke-width='1'/>"
                 % (pad_l, y, pad_l + iw, y))
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='#71807a' text-anchor='end'>%.0f</text>"
                 % (pad_l - 6, y + 3.5, v))
    for h in range(0, 24, 2):
        g.append("<text x='%.1f' y='%d' font-size='10' fill='#71807a' text-anchor='middle'>%02d</text>"
                 % (X(h), pad_t + ih + 16, h))
    g.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#c9d4cd' stroke-width='1'/>"
             % (pad_l, pad_t + ih, pad_l + iw, pad_t + ih))

    for name, color, d in series:
        pts = [(X(h), Y(d[h])) for h in range(24) if d.get(h) is not None]
        if len(pts) >= 2:
            g.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='2.4'"
                     " stroke-linejoin='round'/>"
                     % (" ".join("%.1f,%.1f" % p for p in pts), color))
        for h in range(24):
            v = d.get(h)
            if v is not None:
                g.append("<circle cx='%.1f' cy='%.1f' r='3.1' fill='%s' stroke='#fff'"
                         " stroke-width='1'/>" % (X(h), Y(v), color))
    g.append("<text x='%d' y='%d' font-size='10.5' fill='#71807a'>μg/m³</text>" % (pad_l, pad_t - 6))
    g.append("</svg>")

    legend = " ".join(
        "<span style='display:inline-block;margin-right:14px;font-size:12.4px;color:#41504a'>"
        "<i style='display:inline-block;width:16px;height:3px;background:%s;vertical-align:3px;"
        "margin-right:5px;border-radius:2px'></i>%s</span>" % (c, _esc(nm))
        for nm, c, _ in series)
    return ("<div class='tscroll'>" + "".join(g) + "</div><div class='legend'>" + legend
            + " <span class='sub2'>横轴＝钟点（0–23 时），纵轴＝%s点位平均浓度；"
            "同一横坐标下两条线的交叉即「夜间颗粒物 / 午后臭氧」的昼夜切换。" % region_label()
            + note + "</span></div>")


# ================================================================ 区域分化度
def divergence_chart(series_val, xs, cities, height=210, width=980):
    """区域 AQI 极差比 = 该时点最高市 AQI / 最低市 AQI。

    项目内既有经验阈值：≤1.25 → 区域同步型（各市趋同，倾向区域传输/大范围过程）；
    ≥1.50 → 分化明显（倾向局地排放、单城特征）。只在该时点≥3 市有值时才计算。
    """
    pts = []
    for tp in xs:
        vs = [(series_val.get((c, "aqi")) or {}).get(tp) for c in cities]
        vs = [v for v in vs if v is not None]
        if len(vs) >= 3 and min(vs) > 0:
            pts.append((tp, max(vs) / min(vs)))
    if len(pts) < 2:
        return "<p class='sub2'>有效时点不足，暂无法研判区域分化度。</p>"

    pad_l, pad_r, pad_t, pad_b = 52, 16, 18, 44
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    vmax = max([v for _, v in pts] + [1.6]) * 1.08
    vmin = 1.0
    t0, t1 = _to_dt(pts[0][0]), _to_dt(pts[-1][0])
    span = max((t1 - t0).total_seconds() / 3600.0, 1.0)

    def X(tp):
        return pad_l + (_to_dt(tp) - t0).total_seconds() / 3600.0 / span * iw

    def Y(v):
        return pad_t + ih - (v - vmin) / (vmax - vmin) * ih

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]
    # 两条参考线在低比值区只差约 10px，标签必须错开（实测同位平铺会糊成一团）
    for v, lab, col, dy in ((1.25, "1.25 区域同步线", "#2f6b4f", 13.0),
                            (1.50, "1.50 分化线", "#c0392b", -4.0)):
        if vmin <= v <= vmax:
            y = Y(v)
            g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='%s' stroke-width='1.4'"
                     " stroke-dasharray='6 4'/>" % (pad_l, y, pad_l + iw, y, col))
            g.append("<text x='%d' y='%.1f' font-size='10.5' fill='%s' font-weight='bold'>%s</text>"
                     % (pad_l + 5, y + dy, col, lab))
    for k in range(4):
        v = vmin + (vmax - vmin) * k / 3.0
        y = Y(v)
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='#71807a' text-anchor='end'>%.2f</text>"
                 % (pad_l - 6, y + 3.5, v))
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e8ece9' stroke-width='1'/>"
                 % (pad_l, y, pad_l + iw, y))
    day = t0.replace(hour=0, minute=0)
    if day < t0:
        day = day + timedelta(days=1)
    while day <= t1:
        x = pad_l + (day - t0).total_seconds() / 3600.0 / span * iw
        g.append("<text x='%.1f' y='%d' font-size='9.5' fill='#b3541e' text-anchor='middle'>%s</text>"
                 % (x, pad_t + 10, day.strftime("%m-%d")))
        day = day + timedelta(days=1)
    seg = []
    for i, (tp, v) in enumerate(pts):
        seg.append((X(tp), Y(v)))
        if i + 1 < len(pts) and (_to_dt(pts[i + 1][0]) - _to_dt(tp)).total_seconds() / 3600.0 <= 2.0:
            continue
        if len(seg) >= 2:
            g.append("<polyline points='%s' fill='none' stroke='#b3541e' stroke-width='2'/>"
                     % " ".join("%.1f,%.1f" % p for p in seg))
        seg = []
    for tp, v in pts:
        g.append("<circle cx='%.1f' cy='%.1f' r='3' fill='#b3541e' stroke='#fff' stroke-width='1'/>"
                 % (X(tp), Y(v)))
    g.append("</svg>")
    sync_n = sum(1 for _, v in pts if v <= 1.25)
    div_n = sum(1 for _, v in pts if v >= 1.50)
    vals_sorted = sorted(v for _, v in pts)
    med = vals_sorted[len(vals_sorted) // 2]
    return ("<div class='tscroll'>" + "".join(g) + "</div>"
            "<div class='legend'>曲线＝该时点<b>最高市 AQI ÷ 最低市 AQI</b>（≥3 市有值才计）。"
            "比值越接近 1 说明%s越趋同。本窗口 %d 个有效时点："
            "<b>中位数 %.2f</b>，其中 <b>≤1.25（同步型）%d 个</b>、"
            "<b>≥1.50（分化型）%d 个</b>。"
            " <span class='sub2'>⚠️ 该比值是<b>相对指标</b>：%s AQI 都很低时，"
            "分母小会把比值放大（图上个别尖峰即此因），故应看<b>中位数与整体形态</b>，"
            "不可拿单点比值下结论。阈值为项目内经验值，非国标。</span></div>"
            % (region_label(), len(pts), med, sync_n, div_n, region_label()))


# ================================================================ 首要污染物构成
def stacked_primary(rows, cities, height=250, width=980):
    """首要污染物构成：按日统计"点位-小时"记录，画 100% 堆叠柱。"""
    per_day = {}
    for r in rows:
        c, tp = r.get("city"), r.get("timepoint")
        if c not in cities or not tp:
            continue
        b = _pri_bucket(r.get("primary_pollutant"))
        if b == "无/缺":
            a = r.get("aqi")
            try:
                clean = (a is not None and float(a) <= 50)
            except Exception:
                clean = False
            b = "优（无首要）" if clean else "缺字段"
        per_day.setdefault(tp[:10], {}).setdefault(b, 0)
        per_day[tp[:10]][b] += 1
    if not per_day:
        return "<p class='sub2'>暂无首要污染物字段，跳过。</p>"

    days = sorted(per_day)
    pad_l, pad_r, pad_t, pad_b = 52, 16, 22, 52
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    slot = iw / float(len(days))
    barw = min(54.0, slot * 0.6)

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]
    for k in range(5):
        y = pad_t + ih - ih * k / 4.0
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e8ece9' stroke-width='1'/>"
                 % (pad_l, y, pad_l + iw, y))
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='#71807a' text-anchor='end'>%d%%</text>"
                 % (pad_l - 6, y + 3.5, k * 25))
    for i, ds in enumerate(days):
        tot = sum(per_day[ds].values()) or 1
        cx = pad_l + slot * (i + 0.5)
        x = cx - barw / 2.0
        ycur = pad_t + ih
        for bname, col in PRI_BUCKETS:
            n = per_day[ds].get(bname, 0)
            if not n:
                continue
            hh = ih * n / float(tot)
            g.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'>"
                     "<title>%s ｜ %s：%d 条（%.0f%%）</title></rect>"
                     % (x, ycur - hh, barw, hh, col, ds, _esc(bname), n, 100.0 * n / tot))
            if hh >= 15:
                g.append("<text x='%.1f' y='%.1f' font-size='10' fill='#ffffff' text-anchor='middle'"
                         " font-weight='bold'>%.0f%%</text>"
                         % (cx, ycur - hh / 2.0 + 3.4, 100.0 * n / tot))
            ycur -= hh
        g.append("<text x='%.1f' y='%.1f' font-size='10' fill='#71807a' text-anchor='middle'>%s</text>"
                 % (cx, pad_t + ih + 16, _dd(ds)))
        g.append("<text x='%.1f' y='%.1f' font-size='9.5' fill='#a9b6ae' text-anchor='middle'>"
                 "n=%d</text>" % (cx, pad_t + ih + 29, tot))
    g.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#c9d4cd' stroke-width='1'/>"
             % (pad_l, pad_t + ih, pad_l + iw, pad_t + ih))
    g.append("</svg>")
    legend = " ".join(
        "<span style='display:inline-block;margin-right:12px;font-size:12.2px;color:#41504a'>"
        "<i style='display:inline-block;width:12px;height:12px;background:%s;border-radius:3px;"
        "vertical-align:-2px;margin-right:4px'></i>%s</span>" % (col, _esc(nm))
        for nm, col in PRI_BUCKETS)
    return ("<div class='tscroll'>" + "".join(g) + "</div><div class='legend'>" + legend
            + " <span class='sub2'>按「点位-小时」记录数统计（n＝当日记录条数），每日归一化到 100%。"
            "「优（无首要）」＝AQI≤50 时平台本就不给首要污染物（干净日的正常表现），"
            "与「缺字段」（接口没返回）分开计，二者不可混读。"
            "⚠️ 平台实时值的首要污染物与日评价口径不一致（早间帧易指错），"
            "此处只用于看<b>结构随日推移</b>，不作单时点定论；"
            "「O₃」类含平台的臭氧 1 小时/8 小时口径。</span></div>")


# ================================================================ 风场：16 方位风玫瑰
# 借鉴 urban-wind-lab（MIT Licence, Karam Al-Obaidi）的两点做法：
#   ① 把逐时风向/风速聚合成 16 方位风玫瑰，而不是只画风速折线；
#   ② 引用任何"风"的数字时，必须同时交代风向、地表粗糙度、采样高度与数据源。
# 本项目没有三维建筑体量、也不做 CFD 求解，街区级风场无从谈起；
# 能做的、且有决策价值的是「来向频率 × 本项目风速分级」——
# 它直接回答：把上风向通道打通的风，一年出现多少次、且是不是静稳的那一类。

WIND_CLASSES = [
    ("静稳 <2.0", 2.0, "#c0392b"),
    ("一般 2.0–3.5", 3.5, "#c9a227"),
    ("有利 >3.5", None, "#2f6b4f"),
]

_DIR16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
_DIR16_CN = ["北", "东北偏北", "东北", "东北偏东", "东", "东南偏东", "东南", "东南偏南",
             "南", "西南偏南", "西南", "西南偏西", "西", "西北偏西", "西北", "西北偏北"]


def _wd_cn(wd):
    """风向角 → 16 方位中文（用于悬停提示，避免只给数字要人自己换算）。"""
    try:
        i = int((float(wd) % 360.0 + 11.25) // 22.5) % 16
    except Exception:
        return "—"
    return _DIR16_CN[i]


def _bearing(lat1, lon1, lat2, lon2):
    """点 1 → 点 2 的方位角（自正北顺时针，0–360）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def wind_rose(samples, coords, neighbors, width=980, height=452):
    """samples: [(wd, ws)] 逐时风记录（本档案各市汇总）。

    玫瑰方位＝**风的来向**（wd 的定义就是"风从哪个方位吹来"）；
    径向长度＝该来向出现频率；分段色＝本项目风速分级（静稳/一般/有利）。
    环外蓝色弧段＝各上风向邻居相对本地城市的方位角范围（由真实经纬度算得），
    与玫瑰叠看，就能读出"空气从哪个上风向邻居来的频率有多高、且是不是静稳"。
    """
    SEC, HW = 16, 10.4
    cnt = [[0] * len(WIND_CLASSES) for _ in range(SEC)]
    for s in samples:
        try:
            wd, ws = float(s[0]) % 360.0, float(s[1])
        except Exception:
            continue
        i = int((wd + 11.25) // 22.5) % SEC
        k = len(WIND_CLASSES) - 1
        for ci, (_nm, hi, _c) in enumerate(WIND_CLASSES):
            if hi is None or ws < hi:
                k = ci
                break
        cnt[i][k] += 1
    tot = sum(sum(r) for r in cnt)
    if tot < 6:
        return "<p class='sub2'>有效风向风速样本不足（<6 条），暂不绘风玫瑰。</p>"
    freq = [sum(r) / float(tot) for r in cnt]
    vmax = max(max(freq) * 1.18, 0.08)

    cx, cy, R = 440.0, 214.0, 142.0

    def P(r, ang):
        a = math.radians(ang)
        return (cx + r * math.sin(a), cy - r * math.cos(a))

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>"
         % (width, height, width)]
    for f in (0.25, 0.5, 0.75, 1.0):
        rr = R * f
        g.append("<circle cx='%.1f' cy='%.1f' r='%.1f' fill='none' stroke='#e8ece9' stroke-width='1'/>"
                 % (cx, cy, rr))
        g.append("<text x='%.1f' y='%.1f' font-size='9.5' fill='#a9b6ae'>%.0f%%</text>"
                 % (cx + 3, cy - rr + 11, vmax * f * 100))
    for i in range(SEC):
        x1, y1 = P(0, i * 22.5)
        x2, y2 = P(R, i * 22.5)
        g.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='#eff3f0' stroke-width='1'/>"
                 % (x1, y1, x2, y2))

    for i in range(SEC):
        ang = i * 22.5
        r0 = 0.0
        for ci, (cname, _hi, col) in enumerate(WIND_CLASSES):
            c = cnt[i][ci]
            if not c:
                continue
            r1 = min(R * (sum(cnt[i][:ci + 1]) / float(tot)) / vmax, R)
            if r1 <= r0:
                continue
            a1, a2 = ang - HW, ang + HW
            x1, y1 = P(r0, a1)
            x2, y2 = P(r1, a1)
            x3, y3 = P(r1, a2)
            x4, y4 = P(r0, a2)
            large = 1 if (a2 - a1) > 180 else 0
            g.append("<path d='M%.1f,%.1f L%.1f,%.1f A%.1f,%.1f 0 %d 1 %.1f,%.1f L%.1f,%.1f Z'"
                     " fill='%s' fill-opacity='0.88' stroke='#ffffff' stroke-width='0.8'>"
                     "<title>%s（%s）｜ %s：%.1f%%（%d 条）</title></path>"
                     % (x1, y1, x2, y2, r1, r1, large, x3, y3, x4, y4, col,
                        _DIR16[i], _DIR16_CN[i], cname, 100.0 * c / tot, c))
            r0 = r1

    for i in range(0, SEC, 2):
        x, y = P(R + 17, i * 22.5)
        g.append("<text x='%.1f' y='%.1f' font-size='11' font-weight='bold' fill='#41504a'"
                 " text-anchor='middle'>%s</text>" % (x, y + 4, _DIR16[i]))

    # 上风向邻居方位角弧段（取最小覆盖弧，避免跨 0° 时画成整圈）
    # 标签分层：上风向邻居的方位角高度集中（北—东北一簇、西—西北一簇），
    # 同位半径平铺会直接叠字（实测"邢台""邯郸"糊成一团），故按角距贪心分层。
    hats = []
    for nm, ll in (neighbors or {}).items():
        bears = [_bearing(cll[0], cll[1], ll[0], ll[1])
                 for cll in (coords or {}).values()]
        if not bears:
            continue
        bs = sorted(bears)
        gaps = [(bs[(i + 1) % len(bs)] - bs[i]) % 360.0 for i in range(len(bs))]
        gi = gaps.index(max(gaps))
        lo = bs[(gi + 1) % len(bs)]
        span = (360.0 - max(gaps)) % 360.0
        if span <= 0:
            span = 6.0
        x1, y1 = P(R + 7, lo)
        x2, y2 = P(R + 7, lo + span)
        large = 1 if span > 180 else 0
        g.append("<path d='M%.1f,%.1f A%.1f,%.1f 0 %d 1 %.1f,%.1f' fill='none' stroke='#41678a'"
                 " stroke-width='4' stroke-linecap='round' stroke-opacity='0.5'>"
                 "<title>%s：相对%s的方位角 %.0f°–%.0f°</title></path>"
                 % (x1, y1, R + 7, R + 7, large, x2, y2, _esc(nm), region_label(), lo,
                    (lo + span) % 360))
        hats.append(((lo + span / 2.0) % 360.0, nm))
    hats.sort()
    levels = []
    for ang, nm in hats:
        lv = 0
        while lv < len(levels):
            d = abs(ang - levels[lv])
            if min(d, 360.0 - d) >= 26.0:
                break
            lv += 1
        if lv == len(levels):
            levels.append(ang)
        else:
            levels[lv] = ang
        mx, my = P(R + 30 + lv * 16, ang)
        g.append("<text x='%.1f' y='%.1f' font-size='10.6' fill='#41678a' text-anchor='middle'>%s</text>"
                 % (mx, my + 3.7, _esc(nm[:2])))
    g.append("</svg>")

    top = sorted(range(SEC), key=lambda i: -freq[i])[:3]
    top_txt = "、".join("%s %.0f%%" % (_DIR16_CN[i], 100 * freq[i]) for i in top)
    calm = sum(cnt[i][0] for i in range(SEC)) / float(tot)
    legend = " ".join(
        "<span style='display:inline-block;margin-right:12px;font-size:12.2px;color:#41504a'>"
        "<i style='display:inline-block;width:12px;height:12px;background:%s;border-radius:3px;"
        "vertical-align:-2px;margin-right:4px'></i>%s m/s</span>" % (col, _esc(nm))
        for nm, _hi, col in WIND_CLASSES)
    return ("<div class='tscroll'>" + "".join(g) + "</div><div class='legend'>" + legend
            + " <span class='sub2'>方位＝<b>风的来向</b>；径向＝出现频率（共 %d 条逐时记录）；"
            "蓝色弧段＝各上风向邻居相对%s的方位角范围。</span></div>"
            "<div class='legend'>本窗口主导来向：<b>%s</b>；"
            "其中<b>静稳（&lt;2.0 m/s）占 %.0f%%</b> —— 该比例越高，"
            "越说明本窗口的污染累积发生在不利于扩散的条件下。"
            "<br><span class='sub2'>⚠️ 风速风向来自 Open-Meteo <b>模式产品、城市尺度、10 m 高度</b>"
            "（非国控站实测、非点位尺度），模式存在系统偏差："
            "<b>只读频率与相对大小，不得引用绝对风速或作合规判据</b>。"
            "引用任何风数字都必须同时交代风向、地表粗糙度、采样高度与数据源。</span></div>"
            % (tot, region_label(), top_txt, 100 * calm))


# ================================================================ 覆盖网格
def coverage_grid(tp_counts, city_n):
    """tp_counts: {时点: {城市: 点位数}} → 日期 × 24h 网格，单元格显示该小时点位行数"""
    if not tp_counts:
        return "<p class='sub2'>暂无数据。</p>"
    tps = sorted(tp_counts)
    d0 = datetime.strptime(tps[0][:10], "%Y-%m-%d").date()
    d1 = datetime.strptime(tps[-1][:10], "%Y-%m-%d").date()
    have = {}
    for tp in tps:
        have[(tp[:10], int(tp[11:13]))] = tp_counts[tp]

    hdr = "".join("<th style='text-align:center;padding:3px 1px;font-size:10px'>%02d</th>"
                  for h in range(24))
    rows = []
    d = d0
    while d <= d1:
        ds = d.strftime("%Y-%m-%d")
        cells = []
        for h in range(24):
            rec = have.get((ds, h))
            if not rec:
                cells.append("<td style='background:#fde2e2;color:#c98b8b;text-align:center;"
                             "padding:3px 1px;border-bottom:1px solid #f6eaea;font-size:10px'"
                             " title='%s %02d:00 无数据'>·</td>" % (ds, h))
            else:
                tot = sum(rec.values())
                cells.append("<td style='background:#2f6b4f;color:#fff;text-align:center;"
                             "padding:3px 1px;font-size:10px;font-weight:600'"
                             " title='%s %02d:00 ｜ 共 %d 条点位记录'>%d</td>" % (ds, h, tot, tot))
        rows.append("<tr><td style='padding:3px 7px;font-size:11px;color:#41504a;white-space:nowrap'>%s</td>%s</tr>"
                    % (ds, "".join(cells)))
        d += timedelta(days=1)
    return ("<div class='tscroll'><table style='min-width:760px'><thead><tr>"
            "<th style='padding:3px 7px;font-size:11px'>日期 \\ 时</th>" + hdr +
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            "<div class='legend'>深绿格＝该小时已采，格内数字为该小时入库的<b>点位记录条数</b>"
            "（含%s国控点；采集到邻居城市时会更多）；<span style='color:#c98b8b'>淡红「·」＝该小时完全缺失</span>，"
            "平台无小时级历史接口，<b>缺失的小时永久无法回补</b>。</div>" % region_label())


# ================================================================ 当前实况（逐市快照）
def realtime_panel(series_val, wval, cities, pri_map=None, q_map=None):
    """当前实况：各市**各自最近一个有时点的值**聚成一张快照卡，摆在页首。

    为什么不是"取全区域同一个时点"：采集掉线是常态，各市最后有值的时点常常不同；
    硬取同一时点会把掉线城市整卡变成空白，反而看不出"它现在怎么样"。
    折中做法是每张卡**自己写明时点**，不假装全区域同一时刻 —— 读数的人一眼能看到
    「郑州 09:00 / 洛阳 08:00」这种差异本身就是重要信息。

    差值只在该市上一个时点相邻（≤2 小时）时才给，否则宁可不给（跨大缺口算差值＝编数）。
    """
    pri_map = pri_map or {}
    q_map = q_map or {}

    def av(store, city, key, tp):
        if not tp:
            return None
        return (store.get((city, key)) or {}).get(tp)

    items = []
    for c in cities:
        d = series_val.get((c, "aqi")) or {}
        tp = max(d) if d else None
        items.append((c, tp, (d.get(tp) if tp else None)))
    have = [it for it in items if it[2] is not None]
    if not have:
        return "<p class='sub2'>暂无 AQI 数据。</p>"

    hi_c, hi_tp, hi_v = max(have, key=lambda x: x[2])
    lo_c, _lo_tp, lo_v = min(have, key=lambda x: x[2])
    ratio = (hi_v / lo_v) if lo_v else None
    over = sorted([(c, v) for c, _tp, v in have if v > 100], key=lambda x: -x[1])

    def card_live(c, tp, v):
        if v is None:
            return ("<div class='lc'><div class='lb'><b>%s</b><span>本窗口无数据</span></div>"
                    "<div class='lw'>该市在本窗口未采到 AQI（平台掉线或尚未开始采集）。</div></div>"
                    % _esc(_city_short(c)))
        nm, col = grade(v)
        d = series_val.get((c, "aqi")) or {}
        prev = [k for k in sorted(d) if k < tp]
        delta = ""
        if prev:
            ptp = prev[-1]
            gap = (_to_dt(tp) - _to_dt(ptp)).total_seconds() / 3600.0
            if gap <= 2.0:
                dv = v - d[ptp]
                if abs(dv) < 0.5:
                    seg = "<span style='color:#71807a'>→ 持平</span>"
                else:
                    seg = ("<span style='color:%s;font-weight:600'>%s %.0f</span>"
                           % ("#c0392b" if dv > 0 else "#2f6b4f",
                              "↑" if dv > 0 else "↓", abs(dv)))
                delta = seg + "<i style='font-style:normal;color:#a9b6ae'> vs %s</i>" % _hh(ptp)
            else:
                delta = "<span style='color:#a9b6ae'>上一点 %s（间隔太大，不给差值）</span>" % _hh(ptp)
        ws = av(wval, c, "wind_speed", tp)
        wd = av(wval, c, "wind_dir", tp)
        if wd is not None and ws is not None:
            wind = "%s（%s°）%s m/s" % (_wd_cn(wd), _num(wd), _num(ws, 1))
        elif ws is not None:
            wind = "%s m/s" % _num(ws, 1)
        else:
            wind = "未采到"
        pri = str(pri_map.get((c, tp)) or "").strip()
        if not pri:
            # AQI≤50 时平台本就不返回首要污染物（干净日的正常表现），
            # 与「接口没返回」必须分开说，否则把"天干净"读成"数据烂"。
            pri = "无（AQI≤50 平台不给）" if v <= 50 else "缺字段（接口未返回）"
        kv = "".join(
            "<div class='kv'><i>%s</i><span>%s</span></div>" % (k, val) for k, val in (
                ("首要污染物", _esc(pri)),
                ("PM2.5 / PM10", "%s / %s" % (_num(av(series_val, c, "pm25", tp)),
                                              _num(av(series_val, c, "pm10", tp)))),
                ("O₃-8h（当前值口径）", _num(av(series_val, c, "o3_8h", tp))),
                ("风向风速", _esc(wind)),
            ))
        return ("<div class='lc'><div class='lb'><b>%s</b><span>%s</span></div>"
                "<div class='lv'><span class='na' style='color:%s'>%s</span>"
                "<span class='lg' style='background:%s'>%s</span>"
                "<span class='sub2' style='margin-left:auto'>%s</span></div>%s"
                "<div class='lw'>点位平均 AQI（HJ 663-2013）· 平台实时未审核值</div></div>"
                % (_esc(_city_short(c)),
                   ("%s %s" % (_dd(tp), _hh(tp))) if tp else "—",
                   col, _num(v), col, _esc(nm), delta, kv))

    head = ("<div class='note'><b>当前实况</b>：各市取<b>自己最近一个有值的时点</b>"
            "（每张卡右上角标出该市时点，各市可能不同）；区域最高 <b>"
            + _esc(_city_short(hi_c)) + " " + _num(hi_v) + "</b>（" + _esc(grade(hi_v)[0]) + "）、"
            "最低 <b>" + _esc(_city_short(lo_c)) + " " + _num(lo_v) + "</b>（"
            + _esc(grade(lo_v)[0]) + "），极差比 <b>"
            + (("%.2f" % ratio) if ratio else "—") + "</b>；AQI&gt;100（轻度污染及以上）<b>"
            + str(len(over)) + "</b> 市："
            + ("、".join("%s %s" % (_esc(_city_short(c)), _num(v)) for c, v in over) or "无")
            + "。<br><span class='sub2'>AQI 为<b>点位平均</b>的<b>实时小时值</b>（未经审核），"
            "与日报的日均口径不同，不可直接互换；差值＝该市与上一相邻（≤2 小时）时点之差，"
            "<span style='color:#c0392b'>红 ↑ 表示变差</span>、"
            "<span style='color:#2f6b4f'>绿 ↓ 表示变好</span>。"
            "⚠️ 极差比是<b>相对指标</b>：各市 AQI 都低时分母小会把比值放大"
            "（本页各市同处「优」时出现 2 以上属正常），只看相对格局、不可据此下结论。"
            "AQI≤50 时平台本就不给首要污染物，此处标为「无（AQI≤50 平台不给）」"
            "而非缺失，二者不可混读。</span></div>")
    return head + ("<div class='live'>"
                   + "".join(card_live(c, tp, v) for c, tp, v in items) + "</div>")


# ================================================================ 主渲染
def render_hourly(hourly_rows, weather_rows, cities, generated_at=None, sample=True,
                  back_link=None, coords=None, neighbors=None, region_name=None):
    """hourly_rows: station_hourly 字典行（**可含邻居城市**）；weather_rows: city_hourly_weather 行

    只有 cities（本档案本地城市）参与指标/图表/清单统计；其余城市仅用于区域态势图定位。
    coords: {城市: (纬度, 经度)}；neighbors: {城市: (纬度, 经度)} 上风向邻居（仅上图）。
    region_name: 区域短名（"豫北"/"豫西"），页面自称由它 + 城市数拼出（不写死）。

    generated_at 必须写成「生成：YYYY-MM-DD HH:MM」形式 —— 云端每小时重跑，
    这个字段会被 index_pages.STAMP_RE 抹掉后再比对，否则每个整点都会因时间戳变化
    产生一次无意义提交（页脚因此不再重复出现生成时刻）。
    back_link：云端在 模块/hourly/ 下，传 "../index.html"；本机独立产物传 None。
    """
    now = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    cities = [c for c in (cities or [])]
    coords = dict(coords or {})
    neighbors = dict(neighbors or {})
    REGION = _set_region(cities, region_name)        # 供下方各绘图函数取用（页面自称）
    CITY_LIST = " / ".join(_city_short(c) for c in cities)

    # 城市 × 时点 点位平均（HJ 663-2013）。聚合覆盖所有城市，统计只认 cities。
    agg = {}
    tp_counts = {}
    for r in hourly_rows:
        tp, c = r.get("timepoint"), r.get("city")
        if not tp or not c:
            continue
        if c in cities:
            tp_counts.setdefault(tp, {})
            tp_counts[tp][c] = tp_counts[tp].get(c, 0) + 1
        for k in AGG_KEYS:
            v = r.get(k)
            if v is None:
                continue
            agg.setdefault((c, k), {}).setdefault(tp, []).append(v)
    series_val = {}
    for (c, k), d in agg.items():
        series_val[(c, k)] = {tp: (sum(v) / len(v)) for tp, v in d.items()}

    wval = {}
    for r in (weather_rows or []):
        c, tp = r.get("city"), r.get("timepoint")
        if not c or not tp:
            continue
        for k in WX_KEYS:
            if r.get(k) is not None:
                wval.setdefault((c, k), {})[tp] = r[k]

    # 原始字段（不聚合）：首要污染物 / 平台等级名 —— 供「当前实况」逐市快照直接引用。
    # 用 setdefault 而非覆盖：同一时点有多个点位时，只保留第一条非空值，
    # 避免后面的 None 把前面已拿到的值冲掉。
    pri_map, q_map = {}, {}
    for r in hourly_rows:
        c, tp = r.get("city"), r.get("timepoint")
        if c not in cities or not tp:
            continue
        p = r.get("primary_pollutant")
        if p not in (None, "", "NA", "—", "－"):
            pri_map.setdefault((c, tp), p)
        if r.get("quality"):
            q_map.setdefault((c, tp), r.get("quality"))

    xs = sorted(tp_counts)

    def last_of(store, city, key):
        d = store.get((city, key)) or {}
        if not d:
            return None, None
        tp = max(d)
        return tp, d[tp]

    # 统计
    n_hours = len(xs)
    if xs:
        t0 = datetime.strptime(xs[0], "%Y-%m-%dT%H:%M")
        t1 = datetime.strptime(xs[-1], "%Y-%m-%dT%H:%M")
        span_h = int((t1 - t0).total_seconds() // 3600) + 1
    else:
        span_h = 0
    cov = (100.0 * n_hours / span_h) if span_h else 0.0
    n_rec = sum(sum(v.values()) for v in tp_counts.values())

    # 最新时点（各城各自最后一个有值时点）区域概览
    latest_vals = {}
    for c in cities:
        _tp, v = last_of(series_val, c, "aqi")
        if v is not None:
            latest_vals[c] = v
    if latest_vals:
        hi_c = max(latest_vals, key=lambda k: latest_vals[k])
        lo_c = min(latest_vals, key=lambda k: latest_vals[k])
        span_ratio = (latest_vals[hi_c] / latest_vals[lo_c]) if latest_vals[lo_c] else None
        hi_txt = "%s %.0f" % (_esc(_city_short(hi_c)), latest_vals[hi_c])
        ratio_txt = ("%.2f" % span_ratio) if span_ratio else "—"
    else:
        hi_txt, ratio_txt = "—", "—"

    def card(t, big, sub):
        return ("<div class='card'><div class='ct'><b>%s</b></div>"
                "<div class='big' style='font-size:24px;font-weight:700;color:#1f3b2c'>%s</div>"
                "<div class='sub2'>%s</div></div>" % (t, big, sub))

    win_txt = ("%s %s ~ %s %s" % (_dd(xs[0]), _hh(xs[0]), _dd(xs[-1]), _hh(xs[-1]))) if xs else "—"
    cards = ("<div class='cards'>"
             + card("库内时点数", "%d" % n_hours, "窗口 %s" % win_txt)
             + card("小时覆盖率", "%.0f%%" % cov, "窗口共 %d 小时" % span_h)
             + card("点位记录", "%d" % n_rec, "%s国控点位小时值" % REGION)
             + card("最新时点·区域最高", hi_txt, "%s点位平均 AQI（HJ 663）" % REGION)
             + card("最新时点·极差比", ratio_txt, "≤1.25 倾向区域同步")
             + card("覆盖城市", "%d" % len(set(c for v in tp_counts.values() for c in v)),
                    "按 HJ 663 点位平均")
             + "</div>")

    # ---------- 一、区域态势图
    # 风矢必须与气泡上的 AQI 取**同一小时**：气象表里含未来预报帧（最远到当日 23:00），
    # 若图省事取"最后一个时点"，箭头画的会是 +14 小时的预报风，与 09:00 的 AQI 拼在一张图上 ——
    # 时间错配的图比不画更糟（会被当成"当时就是这个风"）。
    def at(store, city, key, tp):
        if not tp:
            return None
        return (store.get((city, key)) or {}).get(tp)

    map_pts = []
    for name, ll in list(coords.items()) + list(neighbors.items()):
        main = name in coords
        tp_a, aqi = last_of(series_val, name, "aqi")
        if not main and aqi is None:
            continue                       # 该邻居本窗口无任何 AQI 数据，不占图
        map_pts.append({"name": name, "lat": ll[0], "lon": ll[1], "aqi": aqi,
                        "ws": at(wval, name, "wind_speed", tp_a),
                        "wd": at(wval, name, "wind_dir", tp_a),
                        "kind": "main" if main else "neighbor", "tp": tp_a})
    if len([p for p in map_pts if p["aqi"] is not None]) >= 2:
        map_html = situation_map(map_pts)
    else:
        map_html = "<p class='sub2'>坐标或 AQI 数据不足，暂无法绘制区域态势图。</p>"

    # ---------- 风场：本档案各市汇总的风玫瑰（只用落在观测窗口内的时点，排除纯预报帧）
    rose_samples = []
    for c in cities:
        ws_d = wval.get((c, "wind_speed")) or {}
        wd_d = wval.get((c, "wind_dir")) or {}
        for tp, ws in ws_d.items():
            wd = wd_d.get(tp)
            if wd is None or ws is None:
                continue
            if xs and tp > xs[-1]:
                continue
            rose_samples.append((wd, ws))
    rose_html = wind_rose(rose_samples, coords, neighbors)

    # ---------- 折线
    charts = []
    for key, label, unit, dec in METRICS:
        s = []
        for i, c in enumerate(cities):
            d = (wval if key in ("wind_speed", "blh") else series_val).get((c, key))
            if d:
                s.append((c, _c(i, c), d))
        if not s:
            continue
        note, refs, bands = "", None, False
        if key == "o3_8h":
            note = ("⚠️ 平台按当前小时推算，非「日最大 8 小时滑动平均」，<b>只能作筛查信号</b>；"
                    "虚线为 GB 3095-2012 二级限值 160 μg/m³（判定对象是日最大 8h 滑动平均，"
                    "与本图口径不同，不可直接比对超标）。")
            refs = [(160, "国标二级 160（日最大8h）", "#c0392b")]
        if key == "aqi":
            note = ("城市值＝该时点%s国控点位 AQI 平均（HJ 663-2013）；"
                    "背景色带＝AQI 等级（HJ 633-2012）。" % REGION)
            bands = True
        if key == "pm25":
            refs = [(75, "国标二级 75（24h均值）", "#c0392b")]
            note = ("虚线为 GB 3095-2012 二级 24 小时均值限值 75 μg/m³；"
                    "本图为<b>实时小时值</b>，口径不同，仅作距离提示。")
        charts.append("<h2>%s</h2>%s" % (_esc(label), line_chart(s, xs, unit, note=note,
                                                              bands=bands, ref_lines=refs)))

    # ---------- 昼夜切换（本档案各市平均，PM2.5 vs O₃-8h）
    prof = []
    for key, label, col in (("pm25", "PM2.5（%s平均）" % REGION, "#b3541e"),
                            ("o3_8h", "O₃-8h（%s平均·当前值口径）" % REGION, "#2b6cb0")):
        byhour = {}
        for tp in xs:
            vs = [(series_val.get((c, key)) or {}).get(tp) for c in cities]
            vs = [v for v in vs if v is not None]
            if not vs:
                continue
            byhour[int(tp[11:13])] = sum(vs) / len(vs)
        if byhour:
            # 各钟点取窗口内均值（同一天多日叠加）
            bucket = {}
            for hh_ in range(24):
                vals_h = []
                for tp in xs:
                    if int(tp[11:13]) != hh_:
                        continue
                    vs = [(series_val.get((c, key)) or {}).get(tp) for c in cities]
                    vs = [v for v in vs if v is not None]
                    if vs:
                        vals_h.append(sum(vs) / len(vs))
                if vals_h:
                    bucket[hh_] = sum(vals_h) / len(vals_h)
            if bucket:
                prof.append((label, col, bucket))
    profile_html = hour_profile(prof) if prof else "<p class='sub2'>暂无数据。</p>"

    # ---------- 透视表 + 矩阵
    th = "".join("<th>%s</th>" % _esc(c) for c in cities)
    trs = []
    for tp in reversed(xs):
        tds = []
        for c in cities:
            v = series_val.get((c, "aqi"), {}).get(tp)
            tds.append("<td>%s</td>" % ("—" if v is None else "%.0f" % v))
        trs.append("<tr><td>%s %s</td>%s</tr>" % (_dd(tp), _hh(tp), "".join(tds)))
    table = ("<div class='tscroll'><table><thead><tr><th>时点</th>" + th +
             "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>")

    # ---------- 当前实况（放在页首：打开本页第一眼要回答的就是"现在什么情况"）
    live_html = realtime_panel(series_val, wval, cities, pri_map, q_map)

    stamp = ""
    if sample:
        stamp = "<div class='stamp'>AI草稿<br>未经审定</div>"

    html = []
    html.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    html.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    html.append("<title>%s · 小时序列看板 · %s</title><style>%s</style></head><body><div class='page'>"
                % (REGION, _dd(xs[-1]) if xs else "", CSS))
    html.append("<div class='hd'><div><h1>%s大气 · 小时序列看板</h1>"
                "<div class='sub'>%s ｜ 国控点位小时值 ｜ 生成：%s</div></div>%s</div>"
                % (REGION, CITY_LIST, now, stamp))
    html.append("<div class='note'><b>口径与来源（必读）</b><br>"
                "① 数据来自生态环境部全国城市空气质量实时发布平台（air.cnemc.cn:18007）的<b>未审核实时数据</b>，"
                "正式结论应以总站／省级审核后数据为准；<br>"
                "② 城市评价值按 <b>HJ 663-2013 点位平均法</b>计算，非最差点位；<br>"
                "③ <b>O₃-8h 为平台按当前小时推算值</b>，与「日最大 8 小时滑动平均」不是同一口径，仅作筛查；<br>"
                "④ 平台不提供小时级历史接口 —— <b>未采集的小时永久丢失、无法回补</b>，故本页同时呈现「采到了哪些小时」；<br>"
                "⑤ 区域态势图（第 2 节）为<b>相对位置示意图</b>，未绘制行政边界，不可用于边界认定。</div>")
    html.append("<h2>一、当前实况（各市最近时点 · 一眼看现在）</h2>" + live_html)
    html.append("<h2>二、区域态势（谁在哪个方位·上风向是谁·当前谁更脏）</h2>" + map_html)
    html.append("<h2>三、风场（16 方位风玫瑰：来向频率 × 风速分级）</h2>" + rose_html)
    html.append("<h2>四、关键指标</h2>" + cards)
    html.append("<h2>五、逐时趋势（AQI / PM2.5 / O₃-8h / 气象）</h2>")
    for ch in charts:
        html.append(ch)
    html.append("<h2>六、城市 × 小时 AQI 矩阵</h2>" + aqi_matrix(series_val, xs, cities))
    html.append("<h2>七、颗粒物与臭氧的昼夜切换</h2>" + profile_html)
    html.append("<h2>八、区域分化度（%s同步还是单城局地）</h2>" % REGION
                + divergence_chart(series_val, xs, cities))
    html.append("<h2>九、首要污染物构成</h2>"
                + stacked_primary(hourly_rows, cities))
    html.append("<h2>十、采集覆盖（缺哪些小时一眼可见）</h2>" + coverage_grid(tp_counts, cities))
    html.append("<h2>十一、逐时城市 AQI 透视（点位平均）</h2>" + table)
    html.append("<div class='ft'>本页由自动化流水线按采集到的数据自动生成，未经人工审定，"
                "仅供技术交流参考，不作为行政决策或处罚依据。<br>"
                "数据区间 %s。折线 X 轴按<b>真实时间比例</b>定位、间隔超 2 小时即断开 —— "
                "漏采的小时在图上会留出空白，不会被伪装成连续序列；相应小时在覆盖网格与矩阵中标为淡红「·」。"
                "平台不提供小时级历史接口，<b>缺失的小时永久无法回补</b>。</div>" % win_txt)
    if back_link:
        html.append("<p style='margin-top:10px'><a href='%s' style='color:#1F5C45'>← 返回模块目录</a></p>"
                    % back_link)
    html.append("</div></body></html>")
    return "".join(html)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#eef2ef;color:#1f2b26;font-size:14px;line-height:1.7}
.page{max-width:1040px;margin:18px auto;background:#fff;border:1px solid #e3e8e4;border-radius:12px;padding:26px 30px}
.hd{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
 background:linear-gradient(135deg,#26523f,#3c7a5b);color:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.hd h1{font-size:21px;letter-spacing:.5px}
.hd .sub{font-size:12.5px;opacity:.9;margin-top:5px}
.stamp{flex:none;border:2px solid #ffd9d9;color:#ffd9d9;border-radius:8px;padding:5px 10px;
 font-size:12px;font-weight:600;text-align:center;line-height:1.35}
h2{font-size:15px;color:#1f3b2c;margin:22px 0 9px;border-left:4px solid #2f6b4f;padding-left:9px}
.note,.legend{background:#f6f8f4;border:1px solid #e2e8de;border-radius:9px;padding:11px 14px;font-size:12.8px;color:#41504a;margin:9px 0}
.note{background:#fdf7ea;border-color:#e8d6a8}
.warn{background:#fdf1ef;border:1px solid #f0d3cd;border-radius:9px;padding:9px 12px;font-size:12.2px;color:#8a4a3e}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.card{border:1px solid #e3e8e4;border-radius:11px;padding:14px 15px;background:#fbfcfa}
.card .ct b{font-size:15px;color:#1f3b2c}
.sub2{font-size:11.8px;color:#71807a}
table{width:100%;border-collapse:collapse;font-size:12.8px}
th{background:#1f3b2c;color:#fff;padding:6px 8px;text-align:left;font-weight:500;white-space:nowrap}
td{padding:5px 8px;border-bottom:1px solid #eef1ee;white-space:nowrap}
tr:hover td{background:#f8faf8}
table.mxt{border-collapse:separate;border-spacing:1px}
table.mxt th{background:#1f3b2c}
table.mxt td.mx{padding:0;height:22px;font-size:9.6px;text-align:center;white-space:nowrap;border-bottom:none}
table.mxt td.mx0{padding:0;height:22px;font-size:9.6px;text-align:center;background:#fde2e2;color:#c98b8b;border-bottom:none}
table.mxt td.mxlbl{padding:0 7px;font-size:11px;color:#41504a;background:#f7faf7;white-space:nowrap;border-bottom:none}
table.mxt tr.mxsep td{height:8px;background:transparent;border:none}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.live{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.live .lc{border:1px solid #e3e8e4;border-radius:11px;overflow:hidden;background:#fbfcfa}
.live .lb{display:flex;justify-content:space-between;align-items:baseline;gap:8px;
 background:#1f3b2c;color:#fff;padding:7px 12px}
.live .lb b{font-size:14px}
.live .lb span{font-size:11px;opacity:.85;white-space:nowrap}
.live .lv{display:flex;align-items:center;gap:9px;padding:9px 12px 4px;flex-wrap:wrap}
.live .lv .na{font-size:26px;font-weight:700;line-height:1.1}
.live .lv .lg{font-size:11.6px;padding:2px 8px;border-radius:20px;color:#fff;font-weight:600;white-space:nowrap}
.live .kv{display:flex;justify-content:space-between;gap:8px;padding:2px 12px;font-size:12px;color:#41504a}
.live .kv i{font-style:normal;color:#71807a;white-space:nowrap}
.live .lw{padding:6px 12px 10px;font-size:11.4px;color:#9aa8a0}
.ft{margin-top:18px;padding-top:11px;border-top:1px solid #e3e8e4;font-size:11.8px;color:#7c8a83}
@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.cards{grid-template-columns:1fr}.page{padding:18px 15px}}
@media print{
  body{background:#fff}
  .page{border:none;margin:0;max-width:none;padding:0}
  .hd{background:#26523f !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h2{page-break-after:avoid}
  .tscroll{overflow:visible}
  svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
@media(max-width:900px){.live{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.live{grid-template-columns:1fr}}
"""
