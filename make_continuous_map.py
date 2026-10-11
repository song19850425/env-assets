# -*- coding: utf-8 -*-
"""生成「河南连续火点地图」独立页面。

为什么不用报告页里的地图：
  报告页的底图是 TROPOMI 网格 / Esri 影像（WGS-84），火点坐标直接用没问题；
  而这个交互地图用的是**高德 / 腾讯底图（GCJ-02）**，
  FIRMS 火点是 WGS-84，不纠偏会偏约 540 m（河南）。
  模板里已内置 wgs2gcj()，渲染时统一转换 —— 本脚本只需保证喂进去的是 WGS-84 原始坐标。

做法：复用 make_fire_city.py 的模板与 apply_page（边界/底图/暗色滤镜/弹窗全都现成），
      把「运行时 fetch 实时火点」换成「内联连续火点数据」，并禁掉自动刷新，
      避免页面加载 30 分钟后被实时数据覆盖。

用法：python make_continuous_map.py
"""
import collections
import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "EnvData" / "火点监测" / "scripts"))

import make_fire_city as MFC          # 复用模板与注入逻辑
import synth_data as SD               # 复用点位档案

MOD = HERE / "EnvData" / "火点监测"
OUT = MOD / "连续火点地图.html"
GAP = 2          # 连续判据：相邻火点间隔 ≤2 天


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


def build_points(min_days=10):
    allf = SD.load(2024) + SD.load(2025)
    acc = collections.defaultdict(list)
    for f in allf:
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
        pts.append({
            "lat": last["lat"], "lng": last["lng"],
            "date": last["date"], "time": last["time"],
            "frp": round(frps[len(frps) // 2], 2),
            "conf": last.get("conf", "n"), "sat": last.get("sat", "N"),
            "dn": "N" if ndays / len(dates) > 0.5 else "D",
            "city": last["city"],
            "cont": L, "days": len(dates), "n": len(fs),
            "seg": len(sg), "seg_a": a, "seg_b": b,
            "night": round(ndays / len(dates) * 100),
            "months": len(set(d[:7] for d in dates)),
        })
    pts.sort(key=lambda p: -p["cont"])
    return pts


def main():
    pts = build_points()
    print("连续火点（累计 ≥10 天）：%d 个点位" % len(pts))
    print("  最长连续段：%d 天（%s %s）" % (pts[0]["cont"], pts[0]["city"],
                                          "%.2f,%.2f" % (pts[0]["lat"], pts[0]["lng"])))

    tpl = MFC.TEMPLATE.read_text(encoding="utf-8")

    # 全省 cfg（照抄 make_fire_city.build_province）
    stations, xs, ys = [], [], []
    for c in MFC.CITY_NAMES:
        geo = json.loads((MFC.GEO_DIR / f"{c}市_县.geojson").read_text(encoding="utf-8"))
        b = MFC.city_bbox(geo)
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
        stations += MFC.derive_stations(c, geo)
    bbox = (min(xs), min(ys), max(xs), max(ys))
    cfg = {
        "name": "河南",
        "center": (round((bbox[1] + bbox[3]) / 2, 4), round((bbox[0] + bbox[2]) / 2, 4)),
        "zoom": 7,
        "bbox": bbox,
        "stations": stations,
        "range_text": "河南省界外扩50km",
        "boundary_expr": "'geo/henan-cities.geojson'",
        "fire_mode": "province",
    }
    html = MFC.apply_page(tpl, cfg)

    # 1) 内联连续火点数据（覆盖空的 FIRES）
    payload = json.dumps(pts, ensure_ascii=False, separators=(",", ":"))
    n = 0
    html, k = re.subn(r"const FIRES = \[\];", "const FIRES = %s;" % payload, html, count=1)
    n += k
    html, k = re.subn(r"let FIRES_UPDATED = '[^']*';",
                      "let FIRES_UPDATED = '连续火点分析（2024–2025 两年，间隔≤2天视为连续）';",
                      html, count=1)
    n += k
    html, k = re.subn(r"const FIRE_HISTORY = \[\];", "const FIRE_HISTORY = [];", html, count=1)

    # 2) 禁掉运行时自动刷新（否则 30 分钟后会被实时火点覆盖）
    html, k2 = re.subn(r"fetch\('data/fires-henan\.json\?t=' \+ Date\.now\(\)",
                       "fetch('data/__continuous_disabled__.json?t=' + Date.now()", html, count=1)
    n += k2
    html, k3 = re.subn(r"setInterval\(function\(\)\{ loadFires\(\); \}, 30\*60\*1000\);",
                       "/* 连续火点页：数据已内联，不再自动刷新 */", html, count=1)
    n += k3

    # 3) 标题与页头
    html = html.replace("<title>河南火点监测 · 空气站点</title>",
                        "<title>河南连续火点地图 · 不间断排放点位</title>")
    html = html.replace("<b>河南火点监测</b>", "<b>河南连续火点地图</b>")

    # 4) 页脚加一段口径说明
    note = ('<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(148,163,184,.2)">'
            '<b>本页口径：</b>只显示「两年累计出现 ≥10 天」的持续排放点位，'
            '共 <b>%d 个</b>；点的<b>大小</b>按累计天数分档。'
            '「连续段」= 相邻两次火点间隔 ≤2 天视为同一段（VIIRS 每天过境 2 次，'
            '云遮挡必然造成漏检，故不用「严格每天」口径）。'
            '坐标：FIRMS 为 <b>WGS-84</b>，页面已用 wgs2gcj() 转为 <b>GCJ-02</b> 与高德/腾讯底图对齐。'
            '</div>') % len(pts)
    html = re.sub(r"(<div class=\"contact\">)", note + r"\1", html, count=1)

    OUT.write_text(html, encoding="utf-8", newline="\n")
    print("替换动作：%d 处" % n)
    print("已生成", OUT, "%.0f KB" % (OUT.stat().st_size / 1024))
    print("残留 '洛阳' 次数：", html.count("洛阳"))
    print("残留 openstreetmap：", html.count("openstreetmap"))


if __name__ == "__main__":
    main()
