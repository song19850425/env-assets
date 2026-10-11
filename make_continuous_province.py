# -*- coding: utf-8 -*-
"""生成多个省份的「连续火点地图」独立页面（河北 / 山西 / 山东 …）。

与 make_continuous_map.py（河南）的区别
--------------------------------------
  · 河南用 synth_data（本省逐条数据）；其他省用 north6 合并数据，按 province 字段过滤
  · north6 数据没有 city 字段 → 用射线法按市界把点位归到所属市，供弹窗显示
  · 每省需要一份市界 geojson 供页面运行时 fetch → 从 geo/north6/<省>.json 复制成 ASCII 名

用法：python make_continuous_province.py [省名 ...]
"""
import collections
import datetime as dt
import json
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "EnvData" / "火点监测" / "scripts"))

import make_fire_city as MFC          # 复用模板与注入逻辑

MOD = HERE / "EnvData" / "火点监测"
DATA = MOD / "data" / "north6" / "fires-north6.json"
GEO6 = MOD / "geo" / "north6"
GEO = MOD / "geo"
GAP = 2          # 连续判据：相邻火点间隔 ≤2 天
MIN_DAYS = 10    # 累计出现 ≥10 天才算「持续排放点位」

# 省名 → 输出用的 ASCII 边界文件名
PROVINCES = {
    "河北": "hebei",
    "山西": "shanxi",
    "山东": "shandong",
    "天津": "tianjin",
    "北京": "beijing",
}


# ---------------- 连续段 ----------------
def segs(dates, gap=GAP):
    ds = sorted(set(dates))
    if not ds:
        return []
    out, s, prev = [], ds[0], ds[0]
    for d in ds[1:]:
        if (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev)).days <= gap:
            prev = d
        else:
            out.append((s, prev))
            s = prev = d
    out.append((s, prev))
    return [(a, b, (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1)
            for a, b in out]


# ---------------- 点面归属（射线法） ----------------
def _ring_bbox(ring):
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _polys(geom):
    """统一取出多边形列表（每个多边形 = [外环, 内环...]）。"""
    t = geom.get("type")
    cs = geom.get("coordinates")
    if t == "Polygon":
        return [cs]
    if t == "MultiPolygon":
        return cs
    return []


def build_city_index(geo):
    """[(name, [poly,...], bbox), ...]"""
    idx = []
    for f in geo["features"]:
        nm = f["properties"].get("name", "")
        polys = _polys(f["geometry"])
        xs, ys = [], []
        for p in polys:
            for ring in p:
                for c in ring:
                    xs.append(c[0]); ys.append(c[1])
        if xs:
            idx.append((nm, polys, (min(xs), min(ys), max(xs), max(ys))))
    return idx


def assign_city(lat, lng, city_idx):
    for nm, polys, bb in city_idx:
        if not (bb[0] <= lng <= bb[2] and bb[1] <= lat <= bb[3]):
            continue
        for p in polys:
            if _in_ring(lng, lat, p[0]):
                # 落在内环（洞）里则不算
                if any(_in_ring(lng, lat, r) for r in p[1:]):
                    continue
                return nm
    return ""


# ---------------- 点位聚合 ----------------
def build_points(fires, city_idx, min_days=MIN_DAYS):
    acc = collections.defaultdict(list)
    for f in fires:
        acc["%.2f,%.2f" % (f["lat"], f["lng"])].append(f)
    pts = []
    for k, fs in acc.items():
        dates = sorted(set(f["date"] for f in fs))
        if len(dates) < min_days:
            continue
        sg = segs(dates)
        a, b, L = max(sg, key=lambda x: x[2])
        frps = sorted(float(f["frp"]) for f in fs)
        ndays = sum(1 for d in set(f["date"] for f in fs if f["dn"] == "N"))
        last = max(fs, key=lambda f: (f["date"], f["time"]))
        city = assign_city(last["lat"], last["lng"], city_idx)
        pts.append({
            "lat": last["lat"], "lng": last["lng"],
            "date": last["date"], "time": last["time"],
            "frp": round(frps[len(frps) // 2], 2),
            "conf": last.get("conf", "n"), "sat": last.get("sat", "N"),
            "dn": "N" if ndays / len(dates) > 0.5 else "D",
            "city": city,
            "cont": L, "days": len(dates), "n": len(fs),
            "seg": len(sg), "seg_a": a, "seg_b": b,
            "night": round(ndays / len(dates) * 100),
            "months": len(set(d[:7] for d in dates)),
        })
    pts.sort(key=lambda p: -p["cont"])
    return pts


def build_province(prov, ascii_name, all_fires, template):
    geo6 = json.loads((GEO6 / f"{prov}.json").read_text(encoding="utf-8"))
    city_idx = build_city_index(geo6)

    # 1) 边界文件复制成 ASCII 名（页面运行时 fetch，避免中文路径）
    dst = GEO / f"{ascii_name}-cities.geojson"
    shutil.copyfile(GEO6 / f"{prov}.json", dst)

    # 2) 该省火点
    fires = [f for f in all_fires if f.get("province") == prov]
    pts = build_points(fires, city_idx)
    print(f"[{prov}] 火点 {len(fires)} 条；连续火点（≥{MIN_DAYS} 天）{len(pts)} 个点位")
    if pts:
        print(f"        最长连续 {pts[0]['cont']} 天（{pts[0]['city']} "
              f"{pts[0]['lat']:.2f},{pts[0]['lng']:.2f}）")

    # 3) 站点 + bbox（用市界质心）
    stations, xs, ys = [], [], []
    for f in geo6["features"]:
        b = MFC.geom_bbox(f["geometry"])
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    for nm, polys, bb in city_idx:
        cx = round((bb[0] + bb[2]) / 2, 4)
        cy = round((bb[1] + bb[3]) / 2, 4)
        stations.append({"name": nm + "站", "level": "乡镇", "layer": "xz",
                         "lng": cx, "lat": cy,
                         "detail": f"{nm}（示例待核实）",
                         "vendor": "中国铁塔", "device": "六参数"})

    cfg = {
        "name": prov,
        "center": (round((bbox[1] + bbox[3]) / 2, 4), round((bbox[0] + bbox[2]) / 2, 4)),
        "zoom": 7,
        "bbox": bbox,
        "stations": stations,
        "range_text": f"{prov}省界外扩50km",
        "boundary_expr": "'geo/%s-cities.geojson'" % ascii_name,
        "fire_mode": "province",
    }
    html = MFC.apply_page(template, cfg)

    # 4) 内联连续火点数据
    payload = json.dumps(pts, ensure_ascii=False, separators=(",", ":"))
    n = 0
    html, k = re.subn(r"const FIRES = \[\];", "const FIRES = %s;" % payload, html, count=1)
    n += k
    html, k = re.subn(r"let FIRES_UPDATED = '[^']*';",
                      "let FIRES_UPDATED = '连续火点分析（2024–2025 两年，间隔≤2天视为连续）';",
                      html, count=1)
    n += k
    html, k = re.subn(r"const FIRE_HISTORY = \[\];", "const FIRE_HISTORY = [];", html, count=1)

    # 5) 禁掉运行时自动刷新
    html, k2 = re.subn(r"fetch\('data/fires-henan\.json\?t=' \+ Date\.now\(\)",
                       "fetch('data/__continuous_disabled__.json?t=' + Date.now()", html, count=1)
    n += k2
    html, k3 = re.subn(r"setInterval\(function\(\)\{ loadFires\(\); \}, 30\*60\*1000\);",
                       "/* 连续火点页：数据已内联，不再自动刷新 */", html, count=1)
    n += k3

    # 6) 标题与页头
    html = html.replace("<title>%s火点监测 · 空气站点</title>" % prov,
                        "<title>%s连续火点地图 · 不间断排放点位</title>" % prov)
    html = html.replace("<b>%s火点监测</b>" % prov,
                        "<b>%s连续火点地图</b>" % prov)

    # 7) 页脚口径说明
    note = ('<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(148,163,184,.2)">'
            '<b>本页口径：</b>只显示「两年累计出现 ≥%d 天」的持续排放点位，'
            '共 <b>%d 个</b>；点的<b>大小</b>按累计天数分档。'
            '「连续段」= 相邻两次火点间隔 ≤2 天视为同一段（VIIRS 每天过境 2 次，'
            '云遮挡必然造成漏检，故不用「严格每天」口径）。'
            '坐标：FIRMS 为 <b>WGS-84</b>，页面已用 wgs2gcj() 转为 <b>GCJ-02</b> 与高德/腾讯底图对齐。'
            '</div>') % (MIN_DAYS, len(pts))
    html = re.sub(r"(<div class=\"contact\">)", note + r"\1", html, count=1)

    out = MOD / f"连续火点地图-{prov}.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    print(f"        已生成 {out.name}  {out.stat().st_size / 1024:.0f} KB；"
          f"替换 {n} 处；残留洛阳 {html.count('洛阳')}；OSM {html.count('openstreetmap')}")
    return out


def main():
    args = sys.argv[1:] or ["河北", "山西", "山东"]
    template = MFC.TEMPLATE.read_text(encoding="utf-8")
    print(f"[prov] 模板 {MFC.TEMPLATE.name}；待生成 {args}")
    all_fires = json.loads(DATA.read_text(encoding="utf-8"))
    print(f"[prov] north6 火点合计 {len(all_fires)} 条")
    outs = []
    for prov in args:
        if prov not in PROVINCES:
            print(f"[prov] 跳过未知省 {prov}")
            continue
        outs.append(build_province(prov, PROVINCES[prov], all_fires, template))
    print("[prov] 完成：", ", ".join(o.name for o in outs))


if __name__ == "__main__":
    main()
