# -*- coding: utf-8 -*-
"""生成「火点晨检卡」：读仓库里已归档的 FIRMS 数据 → 单页卡片 HTML → 截图成 PNG。

用法：
    python morning_card.py                  # 全部 18 市 + 河南省
    python morning_card.py 洛阳 南阳          # 只做指定的
    python morning_card.py --no-png          # 只出 HTML，不截图

可选环境变量：
    CARD_DATE=2026-10-10   卡片日期（默认今天，北京时间）
    CARD_OUT=<目录>        输出目录（默认 ../cards/<日期>/）
    CHROME=<exe>           Chrome 可执行文件（默认自动探测）

设计要点：
- **不抓 FIRMS**：数据一律来自 `data/fires-henan.json`（由 CI 每 6 小时更新）。
  只联网取两样东西：Open-Meteo 的实时气象、高德地图瓦片（截图用）。
- 底图只用**高德**（合规白名单）；卡片里的地图是**静态截图**，关掉了所有交互。
- 地图用的 Leaflet 与 WGS-84→GCJ-02 转换函数**从已生成的市页里原样提取**，
  保证与网页端完全一致的坐标对齐，不另写一份（避免两套算法漂移）。
- 截图后按「最后一行非背景色」自动裁掉多余空白，避免 PNG 下方留大片黑边。
"""
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent                      # EnvData/火点监测
DATA = MOD / "data"
GEO = MOD / "geo"
PAGE_FOR_EXTRACT = MOD / "洛阳市火点监测-暗色版.html"   # 提取 Leaflet + wgs2gcj 的样板页

_BJ = timezone(timedelta(hours=8))
CARD_W = 680                            # 卡片宽度（PNG 宽度）
MAP_W = CARD_W - 2 * 18 - 2 * 16 - 2    # 地图可用宽（去 body/section 内边距与边框）
MAP_H = 330 - 2                         # 地图高度（与 CSS 里 #map 一致）


def bj_now():
    return datetime.now(_BJ)


def target_list():
    cities = sorted(p.name.replace("市_县.geojson", "")
                    for p in GEO.glob("*市_县.geojson"))
    return cities + ["河南"]


def boundary_path(target):
    return GEO / ("henan-cities.geojson" if target == "河南" else f"{target}市_县.geojson")


# ---------------- 几何工具（复用 fetch_firms，避免两套实现）----------------
def _ff():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import fetch_firms
    return fetch_firms


def geom_bbox(geom):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for k in c:
                walk(k)

    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def bbox_center(geom):
    w, s, e, n = geom_bbox(geom)
    return (e + w) / 2.0, (n + s) / 2.0


def bbox_of_geoms(geoms):
    w = s = 1e18
    e = n = -1e18
    for g in geoms:
        a, b, c, d = geom_bbox(g)
        w, s, e, n = min(w, a), min(s, b), max(e, c), max(n, d)
    return w, s, e, n


def _merc_y(lat):
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    return 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def map_view(geoms_wgs, w_px, h_px, pad=16):
    """在 Python 里算好地图中心与缩放（比 Leaflet fitBounds 可靠：
    fitBounds 依赖容器已测量，截图场景下容器尺寸可能还没稳定）。

    返回 (lat, lng, zoom)——经纬度已转成 GCJ-02（与高德瓦片一致）。
    """
    w, s, e, n = bbox_of_geoms(geoms_wgs)
    x1, x2 = (w + 180) / 360.0, (e + 180) / 360.0
    y1, y2 = _merc_y(n), _merc_y(s)          # 纬度越大 y 越小
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    lng = cx * 360.0 - 180.0
    lat = math.degrees(2 * math.atan(math.exp((0.5 - cy) * 2 * math.pi)) - math.pi / 2)
    avail_w = max(80, w_px - 2 * pad)
    avail_h = max(80, h_px - 2 * pad)
    zx = math.log2(avail_w / (256.0 * max(1e-9, x2 - x1))) if x2 > x1 else 18
    zy = math.log2(avail_h / (256.0 * max(1e-9, y2 - y1))) if y2 > y1 else 18
    # 用**小数**缩放（地图已设 zoomSnap:0.01）：取整会让地图缩得太远、边界只占中间一小块。
    zoom = max(3.0, min(16.0, min(zx, zy) - 0.02))
    glng, glat = _wgs2gcj_py(lng, lat)
    return glat, glng, zoom


_A = 6378245.0
_EE = 0.00669342162296594323


def _wgs2gcj_py(lng, lat):
    """WGS-84 → GCJ-02（与页面里的 JS 同源算法；仅用于算地图中心，偏差 <2m 无影响）。"""
    if not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lng, lat

    def t_lat(x, y):
        r = -100 + 2 * x + 3 * y + .2 * y * y + .1 * x * y + .2 * math.sqrt(abs(x))
        r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        r += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
        r += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
        return r

    def t_lng(x, y):
        r = 300 + x + 2 * y + .1 * x * x + .1 * x * y + .1 * math.sqrt(abs(x))
        r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        r += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
        r += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 3 * math.pi)) * 2 / 3
        return r

    dla, dln = t_lat(lng - 105, lat - 35), t_lng(lng - 105, lat - 35)
    rad = lat / 180 * math.pi
    m = 1 - _EE * math.sin(rad) ** 2
    return (lng + dln * 180 / (_A / math.sqrt(m) * math.cos(rad) * math.pi),
            lat + dla * 180 / (_A * (1 - _EE) / (m * math.sqrt(m)) * math.pi))


# ---------------- 气象（Open-Meteo，免 key）----------------
WMO = {0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "有雾", 48: "雾凇",
       51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
       61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
       71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
       80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
       95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹"}
WMO_ICON = {0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️", 45: "🌫", 48: "🌫",
            51: "🌦", 53: "🌦", 55: "🌦", 56: "🌧", 57: "🌧",
            61: "🌧", 63: "🌧", 65: "🌧", 66: "🌧", 67: "🌧",
            71: "🌨", 73: "🌨", 75: "❄️", 77: "🌨",
            80: "🌦", 81: "🌧", 82: "⛈", 85: "🌨", 86: "🌨",
            95: "⛈", 96: "⛈", 99: "⛈"}
DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]


def wind_dir(deg):
    if deg is None:
        return ""
    return DIRS[int((deg % 360) / 45.0 + 0.5) % 8] + "风"


def fetch_weather(lng, lat):
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": round(lat, 4), "longitude": round(lng, 4),
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Shanghai", "forecast_days": 1,
    }))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "envlab-fire/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
        cur = d.get("current") or {}
        day = d.get("daily") or {}
        code = cur.get("weather_code")
        return {
            "ok": True,
            "text": WMO.get(code, "—"),
            "icon": WMO_ICON.get(code, "🌡"),
            "temp": cur.get("temperature_2m"),
            "hum": cur.get("relative_humidity_2m"),
            "wind": cur.get("wind_speed_10m"),
            "wdir": wind_dir(cur.get("wind_direction_10m")),
            "tmin": (day.get("temperature_2m_min") or [None])[0],
            "tmax": (day.get("temperature_2m_max") or [None])[0],
        }
    except Exception as e:  # noqa
        print("  [warn] 气象获取失败：%s" % e, file=sys.stderr)
        return {"ok": False, "text": "气象获取失败", "icon": "🌡"}


# ---------------- 位置推算 ----------------
def load_boundary(target):
    return json.loads(boundary_path(target).read_text(encoding="utf-8"))


def make_locator(target):
    """返回 locate(lng, lat) -> 「宜阳县附近」/「伊川县东约14km」这类大概位置。"""
    gj = load_boundary(target)
    items = []
    for i, f in enumerate(gj.get("features", [])):
        props = f.get("properties") or {}
        name = props.get("name") or props.get("NAME") or ("区域%d" % (i + 1))
        items.append((name, f["geometry"], bbox_center(f["geometry"])))
    if target == "河南":
        return None, items          # 省级卡片用「所属市」，不做县级定位
    ff = _ff()
    geoms = [(n, g) for n, g, _ in items]

    def locate(lng, lat):
        for name, geom in geoms:
            if ff.point_in_geom(lng, lat, geom):
                return name + "附近"
        best, bd = None, 1e18
        for name, _, (cx, cy) in items:
            d = (cx - lng) ** 2 + (cy - lat) ** 2
            if d < bd:
                bd, best = d, name
        if not best:
            return "—"
        cx, cy = next((c for n, _, c in items if n == best), (lng, lat))
        km = math.hypot((lng - cx) * 111 * math.cos(math.radians(lat)), (lat - cy) * 111)
        ang = math.degrees(math.atan2(lat - cy, (lng - cx) * math.cos(math.radians(lat))))
        d8 = DIRS[int((ang % 360) / 45.0 + 0.5) % 8]
        return "%s%s约%.0fkm" % (best, d8, km)

    return locate, items


# ---------------- 卡片 HTML ----------------
def extract_js(html):
    """从样板页提取内联 Leaflet 与 wgs2gcj（保证与网页端同一套算法）。"""
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    leaflet = next((b for b in blocks if "L.version" in b or "window.L=" in b), None)
    m = re.search(r"function wgs2gcj\([^)]*\)\{[\s\S]*?\n\}", html)
    if not leaflet or not m:
        raise RuntimeError("样板页里没找到内联 Leaflet 或 wgs2gcj")
    return leaflet, m.group(0)


def extract_leaflet_css(html):
    """提取样板页里 Leaflet 的 CSS 规则。

    ⚠ 必须有：只内联 Leaflet 的 JS 而没有它的 CSS 时，`.leaflet-pane{position:absolute}`
    这类定位规则缺失，瓦片会按普通文档流排布 —— 表现为「地图上只有稀疏几块瓦片」。
    """
    parts = []
    for style in re.findall(r"<style>(.*?)</style>", html, re.S):
        for chunk in style.split("}"):
            sel = chunk.split("{")[0]
            if ".leaflet" in sel and "@" not in sel:
                parts.append(chunk + "}")
    css = "".join(parts)
    flat = css.replace(" ", "")
    # 完整性兜底：Leaflet 的定位规则必须在内，否则瓦片会退化成普通文档流
    if len(css) < 4000 or ".leaflet-pane" not in css or "position:absolute" not in flat:
        raise RuntimeError("提取到的 Leaflet CSS 不完整（%d 字节），请检查样板页" % len(css))
    return css


CARD_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070b14;padding:18px;width:__W__px;
  font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#e2e8f0}
.card{display:flex;flex-direction:column;gap:12px}
.hd{display:flex;justify-content:space-between;align-items:center;padding:2px 4px 4px}
.hd .t{font-size:22px;font-weight:800;color:#fb923c;letter-spacing:1px}
.hd .d{font-size:13px;color:#94a3b8;font-family:ui-monospace,monospace}
.sec{background:#0e1626;border:1px solid #1e293b;border-radius:14px;padding:14px 16px}
.sec-h{font-size:13px;color:#7dd3fc;font-weight:700;letter-spacing:.5px;margin-bottom:10px}
.sec-h .sub{font-weight:400;color:#64748b;font-size:11px;margin-left:6px}
.big{display:flex;align-items:baseline;gap:8px;margin-bottom:10px}
.big b{font-size:38px;line-height:1;color:#fff;font-family:ui-monospace,monospace}
.big span{color:#94a3b8;font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.chip{font-size:12px;padding:5px 11px;border-radius:8px;background:#152036;
  border:1px solid #24334d;color:#cbd5e1;white-space:nowrap}
.chip b{color:#fff;margin-left:5px}
#map{height:330px;border-radius:10px;overflow:hidden;border:1px solid #1e293b;background:#dfe6ee}
.cap{font-size:11px;color:#64748b;margin-top:8px;line-height:1.7}
.wx{display:flex;align-items:center;gap:16px}
.wx .ic{font-size:40px;line-height:1}
.wx .main{font-size:20px;font-weight:700;color:#fff}
.wx .s2{font-size:12px;color:#94a3b8;margin-top:5px;line-height:1.7}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#64748b;font-weight:600;padding:7px 6px;
  border-bottom:1px solid #1e293b;font-size:11px;white-space:nowrap}
td{padding:7px 6px;border-bottom:1px solid #131c2e;color:#cbd5e1}
td.i{color:#64748b;font-family:ui-monospace,monospace;width:26px}
td.c{font-family:ui-monospace,monospace;font-size:11.5px;color:#94a3b8;white-space:nowrap}
td.f{text-align:right;font-family:ui-monospace,monospace;color:#fdba74;white-space:nowrap}
.tag{font-size:11px;padding:2px 7px;border-radius:6px;background:#1b2942;
  border:1px solid #2b3d5c;color:#93c5fd;white-space:nowrap}
.ft{font-size:10.5px;color:#475569;line-height:1.9;padding:2px 4px}
"""


def esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def kind_of(f):
    """类型标签：昼夜 + 成因推测。"""
    c = f.get("cause") or "待核实"
    return ("夜间 · " if f.get("dn") == "N" else "") + c


def build_card(target, fires, boundary, weather, leaflet_js, wgs2gcj_js,
               locate, date_str, view, leaflet_css="", snap_utc=""):
    n = len(fires)
    frp_sum = sum(float(f.get("frp") or 0) for f in fires)
    conf_h = sum(1 for f in fires if (f.get("conf") or "") == "h")
    conf_n = sum(1 for f in fires if (f.get("conf") or "") == "n")
    conf_l = sum(1 for f in fires if (f.get("conf") or "") == "l")
    conf_txt = " · ".join(t for t in [
        ("高置信 %d" % conf_h) if conf_h else "",
        ("中置信 %d" % conf_n) if conf_n else "",
        ("低置信 %d" % conf_l) if conf_l else ""] if t) or "无"

    # 类型 chips（按成因归类计数）
    buckets = {}
    for f in fires:
        k = f.get("cause") or "待核实"
        buckets[k] = buckets.get(k, 0) + 1
    chips = "".join('<div class="chip">%s<b>%d</b></div>' % (esc(k), v)
                    for k, v in sorted(buckets.items(), key=lambda kv: -kv[1]))
    if not chips:
        chips = '<div class="chip">近 2 天无火点</div>'

    # 明细表
    cap_note = ""
    if target == "河南":
        head = "<tr><th>#</th><th>市</th><th>火点数</th><th>FRP 合计</th><th>主要成因</th></tr>"
        by_city = {}
        for f in fires:
            c = (f.get("city") or "—")
            e = by_city.setdefault(c, {"n": 0, "frp": 0.0, "kind": {}})
            e["n"] += 1
            e["frp"] += float(f.get("frp") or 0)
            k = f.get("cause") or "待核实"
            e["kind"][k] = e["kind"].get(k, 0) + 1
        rows = []
        for i, (c, e) in enumerate(sorted(by_city.items(), key=lambda kv: -kv[1]["n"]), 1):
            top = max(e["kind"].items(), key=lambda kv: kv[1])[0] if e["kind"] else "—"
            rows.append('<tr><td class="i">%d</td><td>%s</td><td>%d</td>'
                        '<td class="f">%.1f MW</td><td><span class="tag">%s</span></td></tr>'
                        % (i, esc(c), e["n"], e["frp"], esc(top)))
        table = "<table>%s%s</table>" % (head, "".join(rows))
        sub = "按市汇总"
        map_cap = "底图：高德地图 · 范围：河南省 · 火点圆点越大火越强（按 FRP）"
    else:
        head = ("<tr><th>#</th><th>类型</th><th>坐标（纬度, 经度）</th>"
                "<th>大概位置</th><th>FRP</th></tr>")
        show = sorted(fires, key=lambda f: -(float(f.get("frp") or 0)))
        cap_note = ""
        if len(show) > 25:
            cap_note = '<div class="cap">共 %d 条，此处按 FRP 从大到小列出前 25 条。</div>' % len(show)
            show = show[:25]
        rows = []
        for i, f in enumerate(show, 1):
            pos = locate(f["lng"], f["lat"]) if locate else "—"
            rows.append('<tr><td class="i">%d</td><td><span class="tag">%s</span></td>'
                        '<td class="c">%.4f, %.4f</td><td>%s</td>'
                        '<td class="f">%.1f</td></tr>'
                        % (i, esc(kind_of(f)), f["lat"], f["lng"], esc(pos),
                           float(f.get("frp") or 0)))
        table = "<table>%s%s</table>" % (head, "".join(rows))
        sub = "坐标为卫星原始坐标 · 位置为推算的大概位置"
        map_cap = "底图：高德地图 · 范围：%s市 · 火点圆点越大火越强（按 FRP）" % target
        cap_note = cap_note if n else ""

    if weather.get("ok"):
        wx_html = (
            '<div class="wx"><div class="ic">%s</div><div>'
            '<div class="main">%s · 气温 %s°C（今日 %s ~ %s°C）</div>'
            '<div class="s2">湿度 %s%% · %s %s km/h</div></div></div>'
            % (weather["icon"], esc(weather["text"]),
               weather.get("temp"), weather.get("tmin"), weather.get("tmax"),
               weather.get("hum"), esc(weather.get("wdir") or ""), weather.get("wind")))
    else:
        wx_html = '<div class="wx"><div class="ic">🌡</div><div><div class="main">%s</div></div></div>' % esc(weather["text"])

    if target == "河南":
        title = "河南火点晨检卡"
        fname_note = "河南省火点监测"
    else:
        title = "%s火点晨检卡" % target
        fname_note = "%s火点监测" % target

    payload_boundary = json.dumps(boundary, ensure_ascii=False, separators=(",", ":"))
    payload_fires = json.dumps(
        [{"lng": f["lng"], "lat": f["lat"], "frp": float(f.get("frp") or 0)} for f in fires],
        ensure_ascii=False, separators=(",", ":"))
    try:
        _d = datetime.strptime(date_str, "%Y-%m-%d")
        date_cn = "%d年%d月%d日" % (_d.year, _d.month, _d.day)
    except Exception:
        date_cn = date_str

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>%s</title>
<style>%s</style>
<style>%s</style>
</head><body>
<div class="card">
  <div class="hd"><span class="t">🔥 %s</span><span class="d">%s</span></div>

  <div class="sec">
    <div class="sec-h">🛰 卫星火点<span class="sub">NASA FIRMS · 近 2 天%s</span></div>
    <div class="big"><b>%d</b><span>个火点</span><span>· %s</span>
      <span style="margin-left:auto;color:#64748b;font-size:11px">FRP 合计 %.1f MW</span></div>
    <div class="chips">%s</div>
    <div id="map"></div>
    <div class="cap">%s</div>
  </div>

  <div class="sec">
    <div class="sec-h">🌤 今日气象<span class="sub">Open-Meteo · 实时</span></div>
    %s
  </div>

  <div class="sec">
    <div class="sec-h">📍 %s<span class="sub">%s</span></div>
    %s
    %s
  </div>

  <div class="ft">数据口径：火点为 NASA FIRMS VIIRS 375m 近实时卫星数据（火情推测仅供参考，以现场核实为准）；
气象为 Open-Meteo 实时数据；成因列为基于「点位历史复现 + 遥感特征」的推测，非确证。<br>
%s · 数据快照 %s · 每 6 小时自动更新 · 卡片生成 %s</div>
</div>
<script>%s</script>
<script>%s</script>
<script>
(function(){
  var BOUNDARY = %s;
  var FIRES = %s;
  function tGj(g){
    if(g.type==='FeatureCollection'){ g.features.forEach(function(f){ tGj(f.geometry); }); return g; }
    var conv=function(ring){ ring.forEach(function(c){ var r=wgs2gcj(c[0],c[1]); c[0]=+r[0].toFixed(5); c[1]=+r[1].toFixed(5); }); };
    if(g.type==='MultiPolygon'){ g.coordinates.forEach(function(p){ p.forEach(conv); }); }
    else if(g.type==='Polygon'){ g.coordinates.forEach(conv); }
    return g;
  }
  var map = L.map('map', {zoomControl:false, attributionControl:false, dragging:false,
    scrollWheelZoom:false, doubleClickZoom:false, touchZoom:false, keyboard:false,
    zoomSnap:0.01, fadeAnimation:false});
  // 必须在添加任何图层之前设好视图：否则矢量图层渲染时拿不到 _bounds，
  // Leaflet 会抛 "Cannot read properties of undefined (reading 'min')" 并中断后面的代码。
  map.setView([%s], %s, {animate:false});
  L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    {subdomains:'1234', maxZoom:18}).addTo(map);
  var b = L.geoJSON(tGj(BOUNDARY), {style:{color:'#2563eb', weight:1.6, opacity:.8, fill:false}}).addTo(map);
  FIRES.forEach(function(f){
    var g = wgs2gcj(f.lng, f.lat);
    var r = Math.max(5, Math.min(15, 5 + Math.sqrt(f.frp||1) * 3.2));
    L.circleMarker([g[1], g[0]], {radius:r, color:'#b91c1c', weight:1.5,
      fillColor:'#f97316', fillOpacity:0.75}).addTo(map);
  });
  map.invalidateSize();
  window.__map = map;          // 调试钩子：便于核对容器尺寸/瓦片加载情况
})();
</script>
</body></html>
""" % (esc(title), CARD_CSS.replace("__W__", str(CARD_W)), leaflet_css,
       esc(title), esc(date_cn),
       ("市内" if target != "河南" else "省内"),
       n, conf_txt, frp_sum, chips, esc(map_cap), wx_html,
       ("%s市内火点明细" % target) if target != "河南" else "河南省内各市分布",
       sub, table, cap_note,
       fname_note, esc(date_str), bj_now().strftime("%Y-%m-%d %H:%M"),
       leaflet_js, wgs2gcj_js, payload_boundary, payload_fires,
       "%.5f, %.5f" % (view[0], view[1]), view[2])


# ---------------- 截图 + 裁剪 ----------------
def find_chrome():
    env = os.environ.get("CHROME")
    if env and Path(env).exists():
        return env
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if Path(p).exists():
            return p
    raise RuntimeError("没找到 Chrome/Edge，可用 CHROME=<exe> 指定")


def shoot(chrome, html_path, png_path, rows):
    # 给足高度，之后按内容裁剪；宁高勿低（低了会截断内容）。
    # virtual-time-budget 给大一些：地图瓦片要联网加载，预算太小会截到半张地图。
    h = min(3600, 980 + rows * 34)
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--hide-scrollbars", "--force-device-scale-factor=2",
           "--window-size=%d,%d" % (CARD_W, h),
           "--virtual-time-budget=40000",
           "--screenshot=" + str(png_path), html_path.as_uri()]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240)


def crop_png(png_path, bg=(7, 11, 20)):
    """裁掉底部多余背景（按「最后一行有内容」），顺带裁掉右侧空白。"""
    try:
        from PIL import Image
    except ImportError:
        print("  [warn] 没有 Pillow，跳过裁剪（PNG 底部会留空白）。"
              "请用带 Pillow 的解释器运行：~/.workbuddy-ai/binaries/python/envs/default/Scripts/python.exe",
              file=sys.stderr)
        return None
    im = Image.open(png_path).convert("RGB")
    w, h = im.size
    px = im.load()

    def row_has_content(y):
        for x in range(0, w, 3):
            r, g, b = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 24:
                return True
        return False

    def col_has_content(x):
        for y in range(0, h, 3):
            r, g, b = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 24:
                return True
        return False

    bottom = h - 1
    while bottom > 0 and not row_has_content(bottom):
        bottom -= 1
    # 只裁高度、保留整幅宽度（左右留白对称）；底部多留一点，与 body 的 18px 内边距一致
    box = (0, 0, w, min(h, bottom + 37))
    if box[3] < h:
        im.crop(box).save(png_path)
    return box


# ---------------- 主流程 ----------------
def main():
    args = [a for a in sys.argv[1:]]
    do_png = "--no-png" not in args
    args = [a for a in args if not a.startswith("--")]
    targets = args or target_list()

    date_str = os.environ.get("CARD_DATE") or bj_now().strftime("%Y-%m-%d")
    out_dir = Path(os.environ.get("CARD_OUT", str(MOD / "cards" / date_str)))
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads((DATA / "fires-henan.json").read_text(encoding="utf-8"))
    snap = payload.get("updated_utc", "")
    print("[card] 数据快照 %s（共 %d 条）" % (snap, payload.get("count", 0)))

    page_html = PAGE_FOR_EXTRACT.read_text(encoding="utf-8")
    leaflet_js, wgs2gcj_js = extract_js(page_html)
    leaflet_css = extract_leaflet_css(page_html)
    print("[card] 已提取内联 Leaflet（JS %d KB + CSS %d KB）+ wgs2gcj"
          % (len(leaflet_js) // 1024, len(leaflet_css) // 1024))

    chrome = find_chrome() if do_png else None
    made = []
    for t in targets:
        if t == "河南":
            fires = []
            for c, lst in (payload.get("cities") or {}).items():
                if c == "省外":
                    continue
                for f in lst:
                    fires.append(dict(f, city=c))
            locate, items = None, []
        else:
            fires = list((payload.get("cities") or {}).get(t, []))
            locate, items = make_locator(t)

        gj = load_boundary(t)
        geoms = [f["geometry"] for f in gj.get("features", [])]
        bw, bs, be, bn = bbox_of_geoms(geoms)
        wx = fetch_weather((bw + be) / 2.0, (bs + bn) / 2.0)     # 气象取整个市/省范围的中心
        view = map_view(geoms, MAP_W, MAP_H)

        html = build_card(t, fires, gj, wx, leaflet_js, wgs2gcj_js, locate, date_str, view,
                          leaflet_css=leaflet_css)
        name = ("河南省" if t == "河南" else t + "市") + "火点晨检卡"
        hp = out_dir / (name + ".html")
        hp.write_text(html, encoding="utf-8")
        rec = {"target": t, "fires": len(fires), "html": str(hp)}
        if do_png:
            pp = out_dir / (name + ".png")
            rows = len(fires) if t != "河南" else min(len(fires), 18)
            shoot(chrome, hp, pp, min(rows, 25))
            crop_png(pp)
            rec["png"] = str(pp)
            rec["kb"] = pp.stat().st_size // 1024 if pp.exists() else 0
        made.append(rec)
        print("[card] %-6s 火点 %-4d 气象 %-6s → %s%s"
              % (t, len(fires), wx.get("text", "-"), name,
                 ("（%d KB）" % rec.get("kb", 0)) if do_png else ""))
        time.sleep(0.2)

    print("[card] 完成 %d 张 → %s" % (len(made), out_dir))
    return made


if __name__ == "__main__":
    main()
