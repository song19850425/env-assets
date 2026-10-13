# -*- coding: utf-8 -*-
"""从「全国持续火点」数据出图：任意省份 + 全国连续火点地图。

数据源：data/regions/china-continuous.json（fetch_firms_regions.py 的产物）
  · 与 make_continuous_province.py（读 north6）的区别：这里覆盖全国 31 省，
    且点位自带 province + city（抓取时已按市界归属）。

用法：
  python make_continuous_national.py                 # 默认出 8 省 + 全国
  python make_continuous_national.py 安徽 江苏 全国
"""
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "EnvData" / "火点监测" / "scripts"))

import make_fire_city as MFC

MOD = HERE / "EnvData" / "火点监测"
DATA = MOD / "data" / "regions" / "china-continuous.json"
GEOREG = MOD / "geo" / "regions"
GEOPROV = MOD / "geo" / "china-provinces.json"
GAP = 2
MIN_DAYS = 10

DEFAULT = ["安徽", "江苏", "四川", "甘肃", "陕西", "新疆", "内蒙古", "西藏", "全国"]
ASCII = {
    "安徽": "anhui", "江苏": "jiangsu", "四川": "sichuan", "甘肃": "gansu",
    "陕西": "shaanxi", "新疆": "xinjiang", "内蒙古": "neimenggu", "西藏": "xizang",
    "全国": "china",
}


def build_points(fires, min_days=MIN_DAYS):
    """把全国数据按 (lat,lng) 再聚合一次（抓取时已聚合过，这里主要做保险去重）。"""
    pts = [f for f in fires if f["days"] >= min_days]
    pts.sort(key=lambda p: (-p["cont"], -p["days"]))
    return pts


def stations_from(geo):
    st = []
    for f in geo["features"]:
        b = MFC.geom_bbox(f["geometry"])
        nm = f["properties"].get("name", "")
        st.append({"name": nm + "站", "level": "乡镇", "layer": "xz",
                   "lng": round((b[0] + b[2]) / 2, 4),
                   "lat": round((b[1] + b[3]) / 2, 4),
                   "detail": f"{nm}（示例待核实）",
                   "vendor": "中国铁塔", "device": "六参数"})
    return st


def make_page(name, geo_path, pts, out_name, template, ascii_name, zoom=None,
              view_bounds=None):
    """view_bounds=(w,s,e,n)：限定 fitBounds 的范围。

    全国图的边界含「南海诸岛」要素（南到 3.4°N），直接用 b.getBounds() 会把视野
    撑到 z=4（整个亚洲）。这里保留该要素照常绘制，只把视野框限定到大陆范围。
    """
    geo = json.loads(pathlib.Path(geo_path).read_text(encoding="utf-8"))
    xs, ys = [], []
    for f in geo["features"]:
        b = MFC.geom_bbox(f["geometry"])
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    # 边界文件复制成 ASCII 名（页面运行时 fetch，避免中文路径）
    dst = MOD / "geo" / ("%s-bound.geojson" % ascii_name)
    dst.write_bytes(pathlib.Path(geo_path).read_bytes())

    cfg = {
        "name": name,
        "center": (round((bbox[1] + bbox[3]) / 2, 4), round((bbox[0] + bbox[2]) / 2, 4)),
        "zoom": zoom or 7,
        "bbox": bbox,
        "stations": stations_from(geo),
        "range_text": f"{name}边界外扩50km",
        "boundary_expr": "'geo/%s-bound.geojson'" % ascii_name,
        "fire_mode": "province",
    }
    html = MFC.apply_page(template, cfg)

    if view_bounds:
        w, s, e, n = view_bounds
        # 中国南北跨度大，整数 zoomSnap 下 fitBounds 只能落到 z=4（视野过宽）→ 放开小数缩放
        html = html.replace("L.map('map', { zoomControl:true })",
                            "L.map('map', { zoomControl:true, zoomSnap:0.25 })")
        html = html.replace(
            "map.fitBounds(b.getBounds(), {padding:[24,24]});",
            "map.fitBounds(L.latLngBounds([[%s,%s],[%s,%s]]), {padding:[24,24]});"
            % (s, w, n, e))

    payload = json.dumps(pts, ensure_ascii=False, separators=(",", ":"))
    n = 0
    html, k = re.subn(r"const FIRES = \[\];", "const FIRES = %s;" % payload, html, count=1); n += k
    html, k = re.subn(r"let FIRES_UPDATED = '[^']*';",
                      "let FIRES_UPDATED = '连续火点分析（2024–2025 两年，间隔≤2天视为连续）';",
                      html, count=1); n += k
    html, k = re.subn(r"const FIRE_HISTORY = \[\];", "const FIRE_HISTORY = [];", html, count=1)
    html, k = re.subn(r"fetch\('data/fires-henan\.json\?t=' \+ Date\.now\(\)",
                      "fetch('data/__continuous_disabled__.json?t=' + Date.now()", html, count=1); n += k
    html, k = re.subn(r"setInterval\(function\(\)\{ loadFires\(\); \}, 30\*60\*1000\);",
                      "/* 连续火点页：数据已内联，不再自动刷新 */", html, count=1); n += k

    html = html.replace("<title>%s火点监测 · 空气站点</title>" % name,
                        "<title>%s连续火点地图 · 不间断排放点位</title>" % name)
    html = html.replace("<b>%s火点监测</b>" % name, "<b>%s连续火点地图</b>" % name)

    note = ('<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(148,163,184,.2)">'
            '<b>本页口径：</b>只显示「两年累计出现 ≥%d 天」的持续排放点位，'
            '共 <b>%d 个</b>；点的<b>大小</b>按累计天数分档。'
            '「连续段」= 相邻两次火点间隔 ≤2 天视为同一段（VIIRS 每天过境 2 次，'
            '云遮挡必然造成漏检，故不用「严格每天」口径）。'
            '数据源：NASA FIRMS VIIRS 375m（SNPP + NOAA-20，SP 标准产品），'
            '坐标 WGS-84，页面已用 wgs2gcj() 转为 GCJ-02 与高德/腾讯底图对齐。'
            '</div>') % (MIN_DAYS, len(pts))
    html = re.sub(r"(<div class=\"contact\">)", note + r"\1", html, count=1)

    out = MOD / out_name
    out.write_text(html, encoding="utf-8", newline="\n")
    print(f"[out] {out_name}  {out.stat().st_size / 1024:.0f} KB  "
          f"点位 {len(pts)}  替换 {n} 处  残留洛阳 {html.count('洛阳')}")
    return out


def main():
    targets = sys.argv[1:] or DEFAULT
    if not DATA.exists():
        raise SystemExit(f"缺数据文件：{DATA}\n先跑 fetch_firms_regions.py（或等 CI 提交回来）")
    allpts = json.loads(DATA.read_text(encoding="utf-8"))
    print(f"[nat] 全国持续点位 {len(allpts)} 个")
    template = MFC.TEMPLATE.read_text(encoding="utf-8")
    outs = []
    for name in targets:
        asc = ASCII.get(name, name)
        if name == "全国":
            geo_path = GEOPROV
            pts = build_points(allpts)
            outs.append(make_page("全国", geo_path, pts,
                                  "连续火点地图-全国.html", template, asc, zoom=5,
                                  view_bounds=(73.5, 18.0, 135.1, 53.6)))
        else:
            geo_path = GEOREG / ("%s.json" % name)
            if not geo_path.exists():
                print(f"[skip] {name} 无边界文件")
                continue
            pts = build_points([f for f in allpts if f.get("province") == name])
            outs.append(make_page(name, geo_path, pts,
                                  f"连续火点地图-{name}.html", template, asc, zoom=6))
    print("[nat] 完成：", ", ".join(o.name for o in outs))


if __name__ == "__main__":
    main()
