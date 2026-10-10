# -*- coding: utf-8 -*-
"""河南火点年报生成器。

读 data/history/<年>.json（由 backfill_firms.py 回补），产出单文件 HTML 年报：
  · 单年：report/河南火点年报-<年>.html
  · 多年：report/河南火点年报-<起>-<止>.html（含两年对比章节）

设计要点：
  · 纯静态、无外部依赖（图表是 Python 直接生成的 SVG，不引任何 JS 库）
  · 所有数字都从数据算出来，不写死
  · 成因/类型判定用「点位全年复现」规则，阈值由数据分布确定（见 classify_cell）
  · ⚠ 遥感无法确证成因，报告里一律用「疑似 + 依据」的措辞

用法：
  python annual_report.py 2025
  python annual_report.py 2024 2025
"""
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent                       # EnvData/火点监测
HIST = MOD / "data" / "history"
OUT = MOD / "report"

CITY_ORDER = ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
              "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]
HARVEST_MONTHS = (5, 6, 9, 10)          # 华北秸秆焚烧高发期（麦收 5–6 月 / 秋收 9–10 月）
C = {
    "bg": "#070b14", "panel": "#0f172a", "line": "#1e293b", "txt": "#e2e8f0",
    "dim": "#94a3b8", "dim2": "#64748b", "accent": "#38bdf8",
    "day": "#fbbf24", "night": "#6366f1", "hot": "#f97316", "ok": "#34d399",
}


# ---------------------------------------------------------------- 数据

def load_year(year):
    p = HIST / ("%d.json" % year)
    if not p.exists():
        raise SystemExit("[report] 缺少 %s（先跑 backfill_firms.py %d）" % (p, year))
    return json.loads(p.read_text(encoding="utf-8"))


def build_cells(fires):
    """0.01° 网格（约 1.1km）聚合，与 fetch_firms.cell_key 同口径。"""
    cells = defaultdict(lambda: {"days": set(), "nd": set(), "frps": [], "city": "",
                                 "months": set()})
    for f in fires:
        c = cells["%.2f,%.2f" % (f["lat"], f["lng"])]
        c["days"].add(f["date"])
        c["months"].add(f["date"][:7])
        c["frps"].append(float(f["frp"]))
        if not c["city"]:
            c["city"] = f["city"]
        if f["dn"] == "N":
            c["nd"].add(f["date"])
    return cells


def classify_cell(days, night_ratio, frp_med, frp_max, months):
    """点位类型判定。阈值由 2025 年数据分布确定：
       全年 7474 个点位中 86.7% 只出现 1 天；≥30 天的 78 个点位夜间占比中位 99%、
       FRP 中位 1.11 MW —— 是典型的工业固定源特征（反复、夜间、强度稳定）。
       返回 (类型, 置信度)。
    """
    if days >= 30 and night_ratio >= 0.7:
        return "工业/固定源", "高"
    if days >= 10:
        return "工业/固定源", "中"
    if days >= 3 and night_ratio >= 0.6:
        return "偏固定源", "中低"
    # 出现 ≤2 天：一次性火点。是否落在收获季决定像不像秸秆焚烧
    if any(m[5:7] in ("%02d" % x for x in HARVEST_MONTHS) for m in months):
        return "秸秆焚烧疑似", "中低"
    return "其他偶发", "低"


def summarize(fires, year):
    """算一年的全部统计量。"""
    n = len(fires)
    days = {f["date"] for f in fires}
    cells = build_cells(fires)

    # 逐月
    by_month = defaultdict(int)
    by_month_dn = defaultdict(lambda: {"D": 0, "N": 0})
    for f in fires:
        m = f["date"][:7]
        by_month[m] += 1
        by_month_dn[m][f["dn"]] += 1

    # 各市
    by_city = defaultdict(int)
    by_city_dn = defaultdict(lambda: {"D": 0, "N": 0})
    for f in fires:
        by_city[f["city"]] += 1
        by_city_dn[f["city"]][f["dn"]] += 1

    # 昼夜 / 置信度 / 卫星
    dn = {"D": 0, "N": 0}
    conf_cnt = defaultdict(int)
    sat_cnt = defaultdict(int)
    for f in fires:
        dn[f["dn"]] += 1
        conf_cnt[f["conf"]] += 1
        sat_cnt[f["sat"]] += 1

    # FRP
    frps = sorted(float(f["frp"]) for f in fires)

    # 小时（acq_time 是 UTC，转北京 +8）
    by_hour = [0] * 24
    for f in fires:
        try:
            hh = (int(f["time"][:2]) if len(f["time"]) == 4 else int(f["time"][:1])) + 8
        except (ValueError, IndexError):
            continue
        by_hour[hh % 24] += 1

    # 点位类型
    kind_fires = defaultdict(int)
    kind_cells = defaultdict(int)
    kind_conf = defaultdict(int)
    top_cells = []
    for k, c in cells.items():
        dd, nd = len(c["days"]), len(c["nd"])
        ntr = nd / dd if dd else 0
        fm = max(c["frps"]); fmed = statistics.median(c["frps"])
        kind, conf = classify_cell(dd, ntr, fmed, fm, c["months"])
        kind_cells[kind] += 1
        kind_fires[kind] += len(c["frps"])
        kind_conf[kind + "|" + conf] += 1
        top_cells.append({"key": k, "days": dd, "nd": nd, "ntr": ntr,
                          "fmed": fmed, "fmax": fm, "n": len(c["frps"]), "city": c["city"]})
    top_cells.sort(key=lambda x: -x["days"])

    # 复现天数分布
    dc = defaultdict(int)
    for c in cells.values():
        dc[len(c["days"])] += 1

    return {
        "year": year, "n": n, "days": len(days), "ncells": len(cells),
        "by_month": dict(by_month), "by_month_dn": {k: dict(v) for k, v in by_month_dn.items()},
        "by_city": dict(by_city), "by_city_dn": {k: dict(v) for k, v in by_city_dn.items()},
        "dn": dn, "frps": frps, "by_hour": by_hour,
        "conf": dict(conf_cnt), "sat": dict(sat_cnt),
        "kind_fires": dict(kind_fires), "kind_cells": dict(kind_cells),
        "kind_conf": dict(kind_conf), "top_cells": top_cells,
        "day_hist": dict(dc),
        "frp_sum": sum(frps),
    }


# ---------------------------------------------------------------- SVG

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def mon_label(m):
    """'2025-05' -> '5月'（去掉前导零）。"""
    try:
        return "%d月" % int(m[5:7])
    except (ValueError, IndexError):
        return m


def svg_bar(data, w=880, h=260, color=C["accent"], unit="条", pad_l=54, pad_b=42, pad_t=18):
    """竖向柱状图。data = [(label, value), ...]"""
    if not data:
        return ""
    n = len(data)
    mx = max(v for _, v in data) or 1
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    bw = pw / n * 0.62
    gap = pw / n
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    # y 轴网格
    for i in range(5):
        y = pad_t + ph * i / 4
        val = mx * (1 - i / 4)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-16}" y2="{y:.1f}" '
                     f'stroke="{C["line"]}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="{C["dim2"]}" font-size="10" '
                     f'text-anchor="end">{val:,.0f}</text>')
    for i, (lab, v) in enumerate(data):
        x = pad_l + gap * i + (gap - bw) / 2
        bh = ph * v / mx
        y = pad_t + ph - bh
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                     f'rx="3" fill="{color}" opacity="0.88"><title>{_esc(lab)}：{v:,} {unit}</title></rect>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{pad_t+ph+15}" fill="{C["dim"]}" font-size="10" '
                     f'text-anchor="middle">{_esc(lab)}</text>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" fill="{C["txt"]}" font-size="10" '
                     f'text-anchor="middle">{v:,}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_stack(data, w=880, h=280, pad_l=54, pad_b=42, pad_t=18):
    """堆叠柱（白天/夜间）。data = [(label, day, night), ...]"""
    if not data:
        return ""
    n = len(data)
    mx = max(d + nt for _, d, nt in data) or 1
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    gap = pw / n
    bw = gap * 0.62
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for i in range(5):
        y = pad_t + ph * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-16}" y2="{y:.1f}" '
                     f'stroke="{C["line"]}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="{C["dim2"]}" font-size="10" '
                     f'text-anchor="end">{mx*(1-i/4):,.0f}</text>')
    for i, (lab, d, nt) in enumerate(data):
        x = pad_l + gap * i + (gap - bw) / 2
        hd = ph * d / mx
        hn = ph * nt / mx
        y0 = pad_t + ph
        parts.append(f'<rect x="{x:.1f}" y="{y0-hd:.1f}" width="{bw:.1f}" height="{hd:.1f}" '
                     f'fill="{C["day"]}" opacity="0.85"><title>{_esc(lab)} 白天：{d:,} 条</title></rect>')
        parts.append(f'<rect x="{x:.1f}" y="{y0-hd-hn:.1f}" width="{bw:.1f}" height="{hn:.1f}" '
                     f'fill="{C["night"]}" opacity="0.9"><title>{_esc(lab)} 夜间：{nt:,} 条'
                     f'（{nt/(d+nt)*100:.0f}%）</title></rect>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{pad_t+ph+15}" fill="{C["dim"]}" font-size="10" '
                     f'text-anchor="middle">{_esc(lab)}</text>')
        if d + nt:
            parts.append(f'<text x="{x+bw/2:.1f}" y="{y0-hd-hn-5:.1f}" fill="{C["txt"]}" '
                         f'font-size="10" text-anchor="middle">{d+nt:,}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_hbar(data, w=880, row_h=26, color=C["hot"], unit="条"):
    """横向条形。data = [(label, value), ...]（已排序）"""
    if not data:
        return ""
    mx = max(v for _, v in data) or 1
    h = row_h * len(data) + 12
    lab_w, val_w = 78, 64
    pw = w - lab_w - val_w - 8
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for i, (lab, v) in enumerate(data):
        y = 6 + i * row_h
        bw = max(2, pw * v / mx)
        parts.append(f'<text x="{lab_w-8}" y="{y+14}" fill="{C["txt"]}" font-size="12" '
                     f'text-anchor="end">{_esc(lab)}</text>')
        parts.append(f'<rect x="{lab_w}" y="{y+3}" width="{bw:.1f}" height="{row_h-10}" rx="4" '
                     f'fill="{color}" opacity="0.85"><title>{_esc(lab)}：{v:,} {unit}</title></rect>')
        parts.append(f'<text x="{lab_w+bw+8:.1f}" y="{y+14}" fill="{C["dim"]}" font-size="11">'
                     f'{v:,}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_grouped_bar(data, names, colors, w=880, h=290, pad_l=58, pad_b=44, pad_t=18):
    """分组柱（多年对比）。data = [(label, [v1, v2, ...]), ...]"""
    if not data:
        return ""
    n, k = len(data), len(names)
    mx = max(max(vs) for _, vs in data) or 1
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    gap = pw / n
    grp = gap * 0.74
    bw = grp / k
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for i in range(5):
        y = pad_t + ph * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-16}" y2="{y:.1f}" '
                     f'stroke="{C["line"]}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="{C["dim2"]}" font-size="10" '
                     f'text-anchor="end">{mx*(1-i/4):,.0f}</text>')
    for i, (lab, vs) in enumerate(data):
        x0 = pad_l + gap * i + (gap - grp) / 2
        for j, v in enumerate(vs):
            x = x0 + bw * j
            bh = ph * v / mx
            y = pad_t + ph - bh
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(1,bw-1.5):.1f}" '
                         f'height="{max(1,bh):.1f}" rx="2" fill="{colors[j]}" opacity="0.88">'
                         f'<title>{_esc(lab)} · {_esc(names[j])}：{v:,} 条</title></rect>')
        parts.append(f'<text x="{x0+grp/2:.1f}" y="{pad_t+ph+15}" fill="{C["dim"]}" font-size="10" '
                     f'text-anchor="middle">{_esc(lab)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_grouped_hbar(data, names, colors, w=880, row_h=30, lab_w=78, val_w=110):
    """分组横条（多年对比）。data = [(label, [v1, v2]), ...]"""
    if not data:
        return ""
    mx = max(max(vs) for _, vs in data) or 1
    h = row_h * len(data) + 10
    pw = w - lab_w - val_w - 8
    bh = (row_h - 12) / len(names)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for i, (lab, vs) in enumerate(data):
        y0 = 5 + i * row_h
        parts.append(f'<text x="{lab_w-8}" y="{y0+row_h/2+4:.1f}" fill="{C["txt"]}" font-size="12" '
                     f'text-anchor="end">{_esc(lab)}</text>')
        for j, v in enumerate(vs):
            bw = max(1.5, pw * v / mx)
            y = y0 + j * bh + 1
            parts.append(f'<rect x="{lab_w}" y="{y:.1f}" width="{bw:.1f}" height="{bh-1.5:.1f}" '
                         f'rx="2" fill="{colors[j]}" opacity="0.88"><title>{_esc(lab)} · '
                         f'{_esc(names[j])}：{v:,} 条</title></rect>')
        parts.append(f'<text x="{lab_w+pw+8:.1f}" y="{y0+row_h/2+4:.1f}" fill="{C["dim"]}" '
                     f'font-size="11">{" / ".join(f"{v:,}" for v in vs)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_hist(bins, w=880, h=240, pad_l=54, pad_b=42, pad_t=18, color=C["ok"]):
    """直方图。bins = [(label, count), ...]"""
    if not bins:
        return ""
    n = len(bins)
    mx = max(v for _, v in bins) or 1
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    gap = pw / n
    bw = gap * 0.72
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    for i in range(5):
        y = pad_t + ph * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-16}" y2="{y:.1f}" '
                     f'stroke="{C["line"]}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="{C["dim2"]}" font-size="10" '
                     f'text-anchor="end">{mx*(1-i/4):,.0f}</text>')
    for i, (lab, v) in enumerate(bins):
        x = pad_l + gap * i + (gap - bw) / 2
        bh = ph * v / mx
        y = pad_t + ph - bh
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(1,bh):.1f}" '
                     f'rx="2" fill="{color}" opacity="0.85"><title>{_esc(lab)}：{v:,} 条</title></rect>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{pad_t+ph+15}" fill="{C["dim2"]}" font-size="9.5" '
                     f'text-anchor="middle">{_esc(lab)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- HTML

CSS = """
*{box-sizing:border-box}
body{margin:0;background:__BG__;color:__TXT__;
  font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.5px}
h2{font-size:17px;margin:0 0 4px;color:__ACC__;font-weight:600}
.sub{color:__DIM__;font-size:13px;margin-bottom:22px}
.card{background:__PANEL__;border:1px solid __LINE__;border-radius:14px;
  padding:18px 20px;margin:0 0 16px}
.card .note{color:__DIM2__;font-size:12px;margin-top:10px;line-height:1.6}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.kpi div{background:__PANEL__;border:1px solid __LINE__;border-radius:14px;padding:14px 16px}
.kpi b{display:block;font-size:24px;color:__TXT__;letter-spacing:.5px}
.kpi span{color:__DIM__;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid __LINE__}
th{color:__DIM__;font-weight:500;font-size:12px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:__DIM__;font-size:12px;margin-top:8px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;
  vertical-align:-1px}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;
  border:1px solid __LINE__;color:__DIM__}
.hl{color:__HOT__;font-weight:600}
.big{font-size:15px;line-height:1.8}
footer{color:__DIM2__;font-size:12px;margin-top:26px;line-height:1.8;
  border-top:1px solid __LINE__;padding-top:16px}
@media(max-width:600px){.wrap{padding:18px 12px 40px}h1{font-size:21px}}
"""

# 返回导航样式（单独抽出，供其他报告脚本拼接使用）
NAV_CSS = """
.wrap{padding-top:72px}          /* 给固定在左上角的返回按钮让出空间，避免遮住标题 */
#nav-back{position:fixed;top:14px;left:14px;z-index:9999}
#nav-back a{display:inline-flex;align-items:center;gap:5px;padding:7px 13px;
  border-radius:10px;background:rgba(15,23,42,.92);border:1px solid #1e293b;
  color:#cbd5e1;font-size:13px;text-decoration:none;white-space:nowrap;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
#nav-back a:hover{border-color:#38bdf8;color:#7dd3fc}
@media(max-width:600px){#nav-back{top:10px;left:10px}#nav-back a{padding:6px 10px;font-size:12px}}
"""
CSS = CSS + NAV_CSS


def nav_back_html(href="index.html", label="← 报告中心"):
    """统一的返回入口（所有报告页共用，避免页面孤立、回不去）。"""
    return '<div id="nav-back"><a href="%s">%s</a></div>\n' % (href, label)


def render(reports):
    """reports = [summary, ...]（按年份升序）。"""
    latest = reports[-1]
    yrs = [r["year"] for r in reports]
    multi = len(reports) > 1
    title = ("河南火点年报 · %d" % yrs[0]) if not multi else \
            ("河南火点年报 · %d–%d" % (yrs[0], yrs[-1]))

    css = (CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
              .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
              .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
              .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = []
    h.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    h.append('<title>%s</title><style>%s</style></head><body>' % (_esc(title), css))
    h.append(nav_back_html())
    h.append('<div class="wrap">')

    # ---- 头部
    h.append('<h1>%s</h1>' % _esc(title))
    h.append('<div class="sub">数据源 NASA FIRMS · VIIRS 375m（Suomi-NPP + NOAA-20，SP 标准处理）'
             '　·　河南省域　·　生成于 %s</div>'
             % (datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")))

    # ---- KPI
    r = latest
    f0 = reports[0]

    def _np(x):
        return x["dn"]["N"] / x["n"] * 100 if x["n"] else 0

    h.append('<div class="kpi">')
    if multi:
        y0, y1 = f0["year"], r["year"]
        items = [
            (f'{r["n"]:,}', '火点总数（条）<br>%d 年 %s → %d 年 %s'
             % (y0, f'{f0["n"]:,}', y1, f'{r["n"]:,}')),
            (f'{r["days"]}', '有火点的天数<br>%d → %d' % (f0["days"], r["days"])),
            (f'{r["ncells"]:,}', '火点点位（约 1km 网格）<br>%s → %s'
             % (f'{f0["ncells"]:,}', f'{r["ncells"]:,}')),
            (f'{_np(r):.0f}%', '夜间火点占比<br>%.0f%% → %.0f%%' % (_np(f0), _np(r))),
        ]
    else:
        items = [(f'{r["n"]:,}', '%d 年火点总数（条）' % r["year"]),
                 (f'{r["days"]}', '有火点的天数'),
                 (f'{r["ncells"]:,}', '火点点位（约 1km 网格）'),
                 (f'{_np(r):.0f}%', '夜间火点占比')]
    for val, lab in items:
        h.append('<div><b>%s</b><span>%s</span></div>' % (_esc(val), lab))
    h.append('</div>')

    # ---- 核心发现
    cells_sorted = sorted(r["day_hist"].items(), key=lambda kv: int(kv[0]))
    once = r["day_hist"].get(1, 0)
    once_pct = once / r["ncells"] * 100 if r["ncells"] else 0
    # 高频点位（≥30 天）覆盖的火点条数
    hi_fires = sum(c["n"] for c in r["top_cells"] if c["days"] >= 30)
    hi_cells = sum(1 for c in r["top_cells"] if c["days"] >= 30)
    hi_pct = hi_fires / r["n"] * 100 if r["n"] else 0

    h.append('<div class="card"><h2>核心发现</h2>')
    h.append('<div class="big">')
    h.append('· 全省 %s 个火点点位中，<span class="hl">%.0f%%（%s 个）全年只出现过 1 天</span>'
             '——是一次性燃烧。<br>' % (f'{r["ncells"]:,}', once_pct, f'{once:,}'))
    h.append('· 但 <span class="hl">%d 个点位（%.1f%%）就贡献了 %s 条火点（%.1f%%）</span>，'
             '最高一个点位全年被探测到 <b>%d 天</b>。' %
             (hi_cells, hi_cells / r["ncells"] * 100 if r["ncells"] else 0,
              f'{hi_fires:,}', hi_pct, r["top_cells"][0]["days"] if r["top_cells"] else 0))
    h.append('</div>')
    h.append('<div class="note">这意味着：<b>「火点数量」这个指标被少数长期存在的固定源主导</b>。'
             '按数量给基层排名次，会把常年冒烟的工业源算成「焚烧火点」。'
             '区分「反复出现的固定源」与「一次性焚烧」，才是这份数据真正的价值。</div>')
    h.append('</div>')

    # ---- 逐月趋势
    months = sorted(set().union(*[set(x["by_month"]) for x in reports]))
    h.append('<div class="card"><h2>逐月火点趋势%s</h2>'
             % ("（%d vs %d）" % (f0["year"], r["year"]) if multi else ""))
    if multi:
        h.append(svg_grouped_bar([(mon_label(m), [x["by_month"].get(m, 0) for x in reports])
                                  for m in months],
                                 ["%d 年" % x["year"] for x in reports],
                                 [C["dim2"], C["accent"]]))
        h.append('<div class="legend">%s</div>' % "".join(
            '<span><i style="background:%s"></i>%d 年</span>' % (c, x["year"])
            for c, x in zip([C["dim2"], C["accent"]], reports)))
    else:
        h.append(svg_bar([(mon_label(m), r["by_month"][m]) for m in months]))
    # 注意：month_note 内含 <b> 标签，不能转义（内容全由本脚本生成，无外部输入）
    h.append('<div class="note">%s</div>' % month_note(r))
    h.append('</div>')

    # ---- 昼夜结构
    h.append('<div class="card"><h2>逐月昼夜结构（%d 年）</h2>' % r["year"])
    h.append(svg_stack([(mon_label(m), r["by_month_dn"][m]["D"], r["by_month_dn"][m]["N"])
                        for m in sorted(r["by_month_dn"])]))
    h.append('<div class="legend"><span><i style="background:%s"></i>白天（daynight=D）</span>'
             '<span><i style="background:%s"></i>夜间（daynight=N）</span></div>' % (C["day"], C["night"]))
    h.append('<div class="note">%s</div>' % night_note(r))
    h.append('<div class="note">「白天/夜间」是 FIRMS 的 daynight 标志，'
             '按<b>卫星过境时的太阳天顶角</b>判定，不是本地时钟——它反映的是'
             '「这团火在夜里也在烧」。<b>夜里持续燃烧</b>是工业窑炉、堆场自燃、'
             '垃圾填埋场等固定源的典型特征；农田秸秆焚烧基本只发生在白天。</div>')
    h.append('</div>')

    # ---- 各市
    city_tot = defaultdict(int)
    for x in reports:
        for c, v in x["by_city"].items():
            city_tot[c] += v
    city_order = sorted(city_tot, key=lambda c: -city_tot[c])
    h.append('<div class="card"><h2>各市火点分布%s</h2>'
             % ("（%d vs %d）" % (f0["year"], r["year"]) if multi else "（%d 年）" % r["year"]))
    if multi:
        h.append(svg_grouped_hbar([(c, [x["by_city"].get(c, 0) for x in reports])
                                   for c in city_order],
                                  ["%d 年" % x["year"] for x in reports],
                                  [C["dim2"], C["accent"]]))
        h.append('<div class="legend">%s</div>' % "".join(
            '<span><i style="background:%s"></i>%d 年</span>' % (c, x["year"])
            for c, x in zip([C["dim2"], C["accent"]], reports)))
    else:
        h.append(svg_hbar([(c, r["by_city"][c]) for c in city_order], row_h=25))
    h.append('<div class="note">全省 %d 市中 %d 市有火点记录。'
             '%d 年前 5 市占全省 %.0f%%。</div>'
             % (len(CITY_ORDER), len(city_order), r["year"],
                sum(v for _, v in sorted(r["by_city"].items(), key=lambda kv: -kv[1])[:5])
                / r["n"] * 100 if r["n"] else 0))
    h.append('</div>')

    # ---- 点位类型
    h.append('<div class="card"><h2>火点类型判定（按点位全年复现特征）</h2>')
    h.append('<table><tr><th>类型</th><th class="num">火点条数</th><th class="num">占比</th>'
             '<th class="num">点位数</th><th>判定依据</th></tr>')
    rules = {
        "工业/固定源": "全年出现 ≥10 天（≥30 天且夜间占比 ≥70% 判高置信）",
        "偏固定源": "出现 3–9 天且夜间占比 ≥60%",
        "秸秆焚烧疑似": "全年出现 ≤2 天，且落在收获季（5/6/9/10 月）",
        "其他偶发": "全年出现 ≤2 天，且不在收获季",
    }
    for kind in ["工业/固定源", "偏固定源", "秸秆焚烧疑似", "其他偶发"]:
        nf = r["kind_fires"].get(kind, 0)
        nc = r["kind_cells"].get(kind, 0)
        if not nf and not nc:
            continue
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="num">%s</td><td style="color:%s;font-size:12px">%s</td></tr>'
                 % (_esc(kind), f'{nf:,}', nf / r["n"] * 100 if r["n"] else 0, f'{nc:,}',
                    C["dim2"], _esc(rules.get(kind, ""))))
    h.append('</table>')
    if r["kind_fires"].get("其他偶发"):
        h.append('<div class="note">「其他偶发」= 全年只出现 1–2 天、且不在收获季的火点'
                 '（冬季月份居多）。这类火点<b>仅凭卫星数据无法进一步区分</b>——'
                 '可能是取暖、垃圾/杂物焚烧、烧荒，也可能是偶发的工业间歇。'
                 '要拆开它们，必须引入地面信息（火点举报、巡查记录、土地分类）。</div>')
    if r["conf"]:
        c = r["conf"]
        tot = sum(c.values()) or 1
        h.append('<div class="note">卫星置信度分布：'
                 'nominal（常规）%.0f%% · low（低）%.0f%% · high（高）%.0f%%。'
                 '大部分火点为常规置信度，是 375m 产品在华北平原的正常水平。</div>'
                 % (c.get("n", 0) / tot * 100, c.get("l", 0) / tot * 100, c.get("h", 0) / tot * 100))
    h.append('<div class="note"><b>⚠ 诚实边界</b>：卫星遥感<b>无法确证</b>火点成因，'
             '这里给的是「疑似类型 + 判定依据」，不是认定，<b>不能作为处罚依据</b>。'
             '判定的核心特征是<b>点位复现</b>——固定源会反复、常在夜间出现；'
             '农田秸秆焚烧多为一次性、白天。<br>'
             '<b>提升空间</b>：要显著提高判别力，需补<b>土地利用/地类</b>（HJ 1008-2018 要求结合'
             '农田范围判定秸秆焚烧）、工业区 POI、VIIRS 夜间灯光图层——当前未接入。</div>')
    h.append('</div>')

    # ---- 高频点位表
    h.append('<div class="card"><h2>反复出现的点位 Top 15</h2>')
    h.append('<table><tr><th class="num">#</th><th>坐标（WGS-84）</th><th>所在市</th>'
             '<th class="num">出现天数</th><th class="num">夜间占比</th>'
             '<th class="num">FRP 中位</th><th class="num">探测次数</th></tr>')
    for i, c in enumerate(r["top_cells"][:15], 1):
        h.append('<tr><td class="num">%d</td><td>%s</td><td>%s</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f</td><td class="num">%d</td></tr>'
                 % (i, _esc(c["key"]), _esc(c["city"]), c["days"], c["ntr"] * 100,
                    c["fmed"], c["n"]))
    h.append('</table><div class="note">这些点位全年反复被探测、绝大多数在夜间、'
             '辐射功率稳定在低位——符合工业窑炉/堆场/垃圾填埋场等固定源的持续排放特征。'
             '具体是什么设施，需结合现场或工业 POI 数据核实。</div></div>')

    # ---- FRP 分布
    edges = [0, 1, 2, 3, 5, 8, 12, 20, 40, 1e9]
    labs = ["<1", "1–2", "2–3", "3–5", "5–8", "8–12", "12–20", "20–40", ">40"]
    bins = [0] * (len(edges) - 1)
    for v in r["frps"]:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                bins[i] += 1
                break
    h.append('<div class="card"><h2>辐射功率（FRP）分布</h2>')
    h.append(svg_hist(list(zip(labs, bins))))
    h.append('<div class="note">FRP 中位 <b>%.2f MW</b>、P90 %.2f MW、最大 %.2f MW。'
             '绝大多数火点辐射功率很低，属小型燃烧（工业热源/农田小面积焚烧），'
             '不是大规模野火。</div>'
             % (statistics.median(r["frps"]) if r["frps"] else 0,
                r["frps"][int(len(r["frps"]) * .9)] if r["frps"] else 0,
                max(r["frps"]) if r["frps"] else 0))
    h.append('</div>')

    # ---- 小时分布
    h.append('<div class="card"><h2>探测时刻分布（北京时间）</h2>')
    h.append(svg_bar([("%02d时" % i, r["by_hour"][i]) for i in range(24)],
                     h=230, color=C["night"]))
    h.append('<div class="note">峰值集中在卫星过境时刻（VIIRS 每天约 2 次过境，'
             '河南上空大致在午后与凌晨），所以「时刻分布」主要反映<b>过境窗口</b>，'
             '不能直接读成人为活动规律——但白天/夜间的相对比例是可比的。</div>')
    h.append('</div>')

    # ---- 多年对比
    if multi:
        h.append('<div class="card"><h2>%d vs %d 对比</h2>' % (yrs[0], yrs[-1]))
        h.append('<table><tr><th>指标</th>')
        for x in reports:
            h.append('<th class="num">%d 年</th>' % x["year"])
        h.append('<th class="num">变化</th></tr>')
        a, b = reports[0], reports[-1]
        rows = [("火点总数", a["n"], b["n"], "{:,}"),
                ("有火点天数", a["days"], b["days"], "{:,}"),
                ("火点点位数", a["ncells"], b["ncells"], "{:,}"),
                ("夜间占比", a["dn"]["N"] / a["n"] * 100 if a["n"] else 0,
                 b["dn"]["N"] / b["n"] * 100 if b["n"] else 0, "{:.1f}%"),
                ("FRP 中位 (MW)", statistics.median(a["frps"]) if a["frps"] else 0,
                 statistics.median(b["frps"]) if b["frps"] else 0, "{:.2f}")]
        for name, va, vb, fmt in rows:
            chg = (vb - va) / va * 100 if va else 0
            arrow = "↑" if chg > 0 else ("↓" if chg < 0 else "→")
            col = C["hot"] if chg > 0 else C["ok"]
            h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num" style="color:%s">%s %.1f%%</td></tr>'
                     % (_esc(name), fmt.format(va), fmt.format(vb), col, arrow, abs(chg)))
        h.append('</table>')
        h.append('<div class="note"><b>⚠ 口径提醒</b>：两个年份都用 SP 源（同一套产品与算法），'
                 '所以<b>可以横向比较</b>。但若与线上实时页（NRT 源）比较则<b>无效</b>——'
                 'NRT 与 SP 覆盖期不重叠、检出条数量级可能不同。<br>'
                 '<b>⚠ 归因要克制</b>：年际差异还可能受<b>云覆盖</b>（云多则检出少）、'
                 '卫星在轨状态等因素影响，<b>不能全部归因于燃烧活动变化</b>。'
                 '要坐实某市火点增减的原因，需要结合气象与农业活动数据。</div>')
        # 各市两年对比
        h.append('<table style="margin-top:14px"><tr><th>市</th>')
        for x in reports:
            h.append('<th class="num">%d</th>' % x["year"])
        h.append('<th class="num">变化</th></tr>')
        for c in CITY_ORDER:
            va = a["by_city"].get(c, 0); vb = b["by_city"].get(c, 0)
            if not va and not vb:
                continue
            chg = (vb - va) / va * 100 if va else (100 if vb else 0)
            arrow = "↑" if chg > 0 else ("↓" if chg < 0 else "→")
            col = C["hot"] if chg > 0 else C["ok"]
            h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num" style="color:%s">%s %.0f%%</td></tr>'
                     % (_esc(c), f'{va:,}', f'{vb:,}', col, arrow, abs(chg)))
        h.append('</table></div>')

    # ---- 页脚
    h.append('<footer>')
    h.append('<b>数据与方法</b><br>')
    h.append('· 数据源：NASA FIRMS，VIIRS 375m 活跃火产品（Suomi-NPP + NOAA-20，SP 标准处理），'
             '坐标 WGS-84。<br>')
    h.append('· 统计口径：河南省域 bbox（110.0,31.0,117.0,36.6）内、按市界多边形归属到市的火点；'
             '同一位置同日同过境时刻的记录已去重。<br>')
    h.append('· 点位：0.01° 网格（约 1.1km），与线上火点页同一口径。<br>')
    h.append('· <b>成因与类型为「疑似 + 依据」的推断，不是认定</b>；遥感无地面真值，'
             '不能作为处罚依据。用于行政处罚须经现场核实。<br>')
    h.append('· 方法依据可参照 HJ 1008-2018《卫星遥感秸秆焚烧监测技术规范》'
             '（该标准附录 A 所列数据源含 MODIS/AVHRR 等，未限定国产卫星；'
             '4.2 要求的波段 VIIRS 均满足）。<br>')
    h.append('· 本报告由 annual_report.py 从原始数据自动生成，全部数字可复算。')
    h.append('</footer>')

    h.append('</div></body></html>')
    return "".join(h)


def month_note(r):
    bm = r["by_month"]
    if not bm:
        return ""
    top = sorted(bm.items(), key=lambda kv: -kv[1])[:3]
    lo = sorted(bm.items(), key=lambda kv: kv[1])[:2]
    s = ("火点最多的月份：%s；最少的月份：%s。"
         % ("、".join("%s（%s 条）" % (mon_label(m), f'{v:,}') for m, v in top),
            "、".join("%s（%s 条）" % (mon_label(m), f'{v:,}') for m, v in lo)))
    # 一个值得点出的反直觉结论：秋收季（9–10 月）火点总数反而全年最低
    sep_oct = sum(bm.get("%d-%02d" % (r["year"], m), 0) for m in (9, 10))
    if r["n"] and sep_oct:
        avg = r["n"] / 12
        if sep_oct / 2 < avg * 0.6:
            s += ("　<b>值得注意</b>：9–10 月本是秋收季、理论上秸秆焚烧高发，"
                  "但这两个月的火点总数（%s 条）反而是全年最低——"
                  "说明该时段的露天焚烧管控很可能是有效的，"
                  "而全年火点主要由全年不间断的工业固定源贡献。"
                  % f'{sep_oct:,}')
    s += "　注意：收获季（5–6 月麦收、9–10 月秋收）并不必然是火点最多的月份——" \
         "全省火点里工业固定源占比很高，它们全年都在烧。"
    return s


def night_note(r):
    bmd = r["by_month_dn"]
    rows = []
    for m in sorted(bmd):
        d, nt = bmd[m]["D"], bmd[m]["N"]
        t = d + nt
        if t:
            rows.append((m, nt / t * 100))
    if not rows:
        return ""
    mx = max(rows, key=lambda x: x[1])
    mn = min(rows, key=lambda x: x[1])
    overall = r["dn"]["N"] / r["n"] * 100 if r["n"] else 0
    return ("全年夜间火点占 %.0f%%。夜间占比最高的月份是 %s（%.0f%%），最低是 %s（%.0f%%）。"
            "华北平原夜间火点主要与工业或固定源相关——夜间占比越高，"
            "该月火点里「工业/固定源」的成分越重。"
            % (overall, mon_label(mx[0]), mx[1], mon_label(mn[0]), mn[1]))


# ---------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    years = [int(a) for a in args] or [2025]
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for y in sorted(years):
        d = load_year(y)
        print("[report] %d 年：%d 条火点 / %d 天 / %d 点位"
              % (y, len(d["fires"]), d["days"], 0))
        s = summarize(d["fires"], y)
        reports.append(s)
        print("         算得：%d 点位 · 夜间 %.0f%% · 工业/固定源 %s 条"
              % (s["ncells"], s["dn"]["N"] / s["n"] * 100,
                 f'{s["kind_fires"].get("工业/固定源", 0):,}'))
    html = render(reports)
    if len(years) == 1:
        name = "河南火点年报-%d.html" % years[0]
    else:
        name = "河南火点年报-%d-%d.html" % (min(years), max(years))
    out = OUT / name
    out.write_text(html, encoding="utf-8")
    print("[report] 写出 %s（%.0f KB）" % (out, len(html.encode("utf-8")) / 1024))


if __name__ == "__main__":
    main()
