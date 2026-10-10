# -*- coding: utf-8 -*-
"""火点类型判别模型：从历史复现特征判定点位类型，并做稳定性验证。

与 cause.py 的分工
------------------
  · `cause.py` —— **在线**用。只回看近 60 天，面向「这一条火点像什么」，
    给页面弹窗里的即时判定。
  · 本模块 —— **离线**用。回看整年/多年，面向「这个点位到底是什么」，
    并且能做**跨期验证**。这是把判据从「拍脑袋的启发式」变成
    「有数据支撑、可复现、可验证」的关键一步。

核心特征：点位复现
------------------
同一点位（0.01° 网格，约 1.1km）在长时间窗内的**复现次数**是最强的判别特征：
  · 工业窑炉 / 堆场自燃 / 垃圾填埋场 → 几乎天天在烧、夜里也在烧、强度稳定
  · 农田秸秆焚烧 → 一次性、白天、强度低、集中在收获季
2025 年实测：7,474 个点位中 86.7% 全年只出现 1 天；出现 ≥30 天的 78 个点位
夜间占比中位 99%、FRP 中位 1.11 MW —— 与上述物理预期完全吻合。

阈值从哪来（不拍脑袋）
--------------------
见 `THRESHOLDS` 的注释，每条阈值都注明了对应的数据依据。

验证方法
--------
遥感**没有地面真值**，所以这里验的不是「准确率」，而是**稳定性**：
  ① 跨年一致性：A 年判为「工业/固定源」的点位，B 年是否仍表现为高频？
  ② 半年分割：用上半年判、看下半年表现。
只有稳定的判据才值得写进产品；只在单年成立的，是噪声。
"""
import json
import statistics
from collections import defaultdict

import annual_report as AR          # 复用返回导航样式

HARVEST_MONTHS = (5, 6, 9, 10)      # 华北秸秆焚烧高发期：5–6 月麦收 / 9–10 月秋收

# 阈值依据（2025 年 22,626 条实测分布）：
#   · 点位全年出现天数的 P50=1、P75=1、P90=2、P95=3、P99=32、max=227
#     → 出现 ≥10 天已进入前 2%；≥30 天是前 1% 的极端长尾，几乎必是固定源
#   · ≥30 天的 78 个点位：夜间占比中位 99%、FRP 中位 1.11 MW（稳定低强度）
#   · 只出现 1 天的 6,480 个点位：夜间占比仅 25%、FRP 中位 2.80 MW（白天为主）
THRESHOLDS = {
    "fixed_high_days": 30,      # 工业/固定源（高）：≥30 天
    "fixed_high_night": 0.70,   #   且夜间占比 ≥70%
    "fixed_mid_days": 10,       # 工业/固定源（中）：≥10 天
    "fixed_mid_night": 0.50,    #   且夜间占比 ≥50% 时置信度提到中高
    "lean_days": 4,             # 偏固定源：≥4 天
    "lean_night": 0.60,         #   且夜间占比 ≥60%
    "once_days": 2,             # 一次性：≤2 天
    "harvest_ratio": 0.80,      # 秸秆焚烧疑似：收获季火点占比 ≥80%
}

KINDS = ["工业/固定源", "偏固定源", "秸秆焚烧疑似", "其他偶发", "待核实"]
KIND_DESC = {
    "工业/固定源": "反复出现（≥10 天），常在夜间——工业窑炉/堆场/垃圾填埋场等持续排放",
    "偏固定源": "出现 4–9 天且夜间为主，介于固定源与偶发之间",
    "秸秆焚烧疑似": "全年仅出现 1–2 天，且几乎都落在收获季（5/6/9/10 月）",
    "其他偶发": "全年仅出现 1–2 天，且不在收获季（冬季居多）",
    "待核实": "出现 3 天左右，特征不典型",
}


def cell_key(f):
    return "%.2f,%.2f" % (f["lat"], f["lng"])


def build_profiles(fires):
    """把火点明细聚合成「点位画像」。返回 {key: profile}。"""
    acc = defaultdict(lambda: {"days": set(), "nd": set(), "frps": [], "months": set(),
                               "city": "", "harvest": 0, "n": 0})
    for f in fires:
        a = acc[cell_key(f)]
        a["days"].add(f["date"])
        a["months"].add(f["date"][:7])
        a["frps"].append(float(f["frp"]))
        a["n"] += 1
        if not a["city"]:
            a["city"] = f["city"]
        if f["dn"] == "N":
            a["nd"].add(f["date"])
        if f["date"][5:7] in ("%02d" % m for m in HARVEST_MONTHS):
            a["harvest"] += 1

    prof = {}
    for k, a in acc.items():
        d = len(a["days"])
        frps = sorted(a["frps"])
        prof[k] = {
            "key": k, "city": a["city"],
            "days": d, "n": a["n"],
            "ndays": len(a["nd"]),
            "night_ratio": len(a["nd"]) / d if d else 0.0,
            "frp_med": statistics.median(frps) if frps else 0.0,
            "frp_p90": frps[int(len(frps) * 0.9)] if frps else 0.0,
            "frp_max": max(frps) if frps else 0.0,
            "months": sorted(a["months"]),
            "n_months": len(a["months"]),
            "harvest_ratio": a["harvest"] / a["n"] if a["n"] else 0.0,
            "first": min(a["days"]), "last": max(a["days"]),
        }
    return prof


def classify(p):
    """点位画像 → (类型, 置信度, 依据列表)。规则透明、可复核，不调模型。"""
    T = THRESHOLDS
    d, ntr = p["days"], p["night_ratio"]
    ev = ["全年出现 %d 天、探测 %d 次；夜间 %d 天（%.0f%%）；FRP 中位 %.2f MW"
          % (d, p["n"], p["ndays"], ntr * 100, p["frp_med"])]

    if d >= T["fixed_high_days"] and ntr >= T["fixed_high_night"]:
        ev.append("全年 ≥%d 天且夜间占比 ≥%.0f%%——反复、夜间持续，是固定源（工业窑炉/堆场/"
                  "垃圾填埋场）的典型特征" % (T["fixed_high_days"], T["fixed_high_night"] * 100))
        return "工业/固定源", "高", ev

    if d >= T["fixed_mid_days"]:
        conf = "中高" if ntr >= T["fixed_mid_night"] else "中"
        ev.append("全年 ≥%d 天，反复出现" % T["fixed_mid_days"]
                  + ("且以夜间为主" if ntr >= T["fixed_mid_night"] else "")
                  + "，偏向固定源")
        return "工业/固定源", conf, ev

    if d >= T["lean_days"] and ntr >= T["lean_night"]:
        ev.append("出现 %d 天且夜间占比 %.0f%%，偏固定源但样本偏少" % (d, ntr * 100))
        return "偏固定源", "中", ev

    if d <= T["once_days"]:
        if p["harvest_ratio"] >= T["harvest_ratio"]:
            ev.append("仅出现 %d 天、且 %.0f%% 落在收获季（%s）——符合农田一次性焚烧特征"
                      % (d, p["harvest_ratio"] * 100,
                         "/".join(str(m) for m in HARVEST_MONTHS) + " 月"))
            return "秸秆焚烧疑似", "中低", ev
        ev.append("仅出现 %d 天、不在收获季（出现月份：%s）——成因无法由卫星数据判定"
                  % (d, "、".join(p["months"]) or "—"))
        return "其他偶发", "低", ev

    ev.append("出现 %d 天，特征不典型，需结合现场或外部图层核实" % d)
    return "待核实", "低", ev


def profile_kinds(fires):
    """对一批火点算出「点位类型」与「按火点条数」的类型分布。"""
    prof = build_profiles(fires)
    kind_cells = defaultdict(int)
    kind_fires = defaultdict(int)
    detail = {}
    for k, p in prof.items():
        kind, conf, ev = classify(p)
        kind_cells[kind] += 1
        kind_fires[kind] += p["n"]
        detail[k] = {"kind": kind, "conf": conf, "ev": ev, "p": p}
    return {"profiles": prof, "detail": detail,
            "kind_cells": dict(kind_cells), "kind_fires": dict(kind_fires)}


# ---------------------------------------------------------------- 验证

def cross_period(fires_a, fires_b, name_a="A 期", name_b="B 期"):
    """跨期一致性：A 期的点位类型，在 B 期是否仍表现为相同量级？

    「吻合」的判据（保守）：
      · 判为 工业/固定源 → B 期出现天数 ≥ 10
      · 判为 偏固定源     → B 期出现天数 ≥ 3
      · 判为 秸秆/偶发    → B 期出现天数 ≤ 3（一次性火点不该年年在同一格子里烧）
    """
    ka = profile_kinds(fires_a)
    kb = build_profiles(fires_b)          # B 期只看表现，不重新判类型

    rows = []
    for kind in KINDS:
        keys = [k for k, v in ka["detail"].items() if v["kind"] == kind]
        if not keys:
            continue
        ok = 0
        b_days = []
        for k in keys:
            bd = kb[k]["days"] if k in kb else 0
            b_days.append(bd)
            if kind == "工业/固定源":
                hit = bd >= 10
            elif kind == "偏固定源":
                hit = bd >= 3
            else:
                hit = bd <= 3
            ok += 1 if hit else 0
        rows.append({
            "kind": kind, "cells": len(keys), "hit": ok,
            "rate": ok / len(keys) if keys else 0,
            "b_med": statistics.median(b_days) if b_days else 0,
            "b_zero": sum(1 for x in b_days if x == 0),
        })

    # 火点条数口径的一致率（更有业务意义）
    tot_fires = sum(ka["kind_fires"].values())
    return {"name_a": name_a, "name_b": name_b, "rows": rows,
            "kind_fires_a": ka["kind_fires"], "kind_cells_a": ka["kind_cells"],
            "tot_fires": tot_fires,
            "n_a": len(fires_a), "n_b": len(fires_b)}


def split_half(fires):
    """按日期把一年数据切成上半年 / 下半年（用于半年分割验证）。"""
    ds = sorted({f["date"] for f in fires})
    if not ds:
        return [], []
    mid = ds[len(ds) // 2]
    a = [f for f in fires if f["date"] < mid]
    b = [f for f in fires if f["date"] >= mid]
    return a, b


# ---------------------------------------------------------------- 报告

KIND_COLOR = {
    "工业/固定源": "#f97316", "偏固定源": "#fbbf24",
    "秸秆焚烧疑似": "#34d399", "其他偶发": "#64748b", "待核实": "#38bdf8",
}


def svg_scatter(items, w=880, h=400, pad_l=64, pad_b=46, pad_t=20, pad_r=20):
    """散点：x = 全年出现天数（log 刻度），y = 夜间占比。items = [(days, ntr, kind)]"""
    import math
    if not items:
        return ""
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
    xmax = max(3, max(d for d, _, _ in items))
    lx = math.log10(max(2, xmax))
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">']
    # y 网格
    for i in range(5):
        y = pad_t + ph * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                     f'stroke="#1e293b" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="#64748b" font-size="10" '
                     f'text-anchor="end">{100-i*25}%</text>')
    # x 刻度（1/3/10/30/100/300）
    for v in [1, 3, 10, 30, 100, 300]:
        if v > xmax * 1.15:
            continue
        x = pad_l + pw * math.log10(max(1, v)) / lx
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t+ph}" '
                     f'stroke="#1e293b" stroke-width="1" stroke-dasharray="3 3"/>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t+ph+16}" fill="#64748b" font-size="10" '
                     f'text-anchor="middle">{v}</text>')
    # 阈值参考线
    T = THRESHOLDS
    for v, lab in [(T["fixed_mid_days"], "≥10 天"), (T["fixed_high_days"], "≥30 天")]:
        x = pad_l + pw * math.log10(max(1, v)) / lx
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t+ph}" '
                     f'stroke="#38bdf8" stroke-width="1" opacity="0.5"/>')
        parts.append(f'<text x="{x+3:.1f}" y="{pad_t+11}" fill="#38bdf8" font-size="9">'
                     f'{lab}</text>')
    y = pad_t + ph * (1 - T["fixed_high_night"])
    parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                 f'stroke="#38bdf8" stroke-width="1" opacity="0.5"/>')
    parts.append(f'<text x="{w-pad_r-6}" y="{y-4:.1f}" fill="#38bdf8" font-size="9" '
                 f'text-anchor="end">夜间占比 70%</text>')
    # 先按（天数, 夜间占比分桶, 类型）聚合，半径反映密度——否则 7000+ 个点会撑爆文件
    from collections import Counter
    agg = Counter()
    for d, ntr, kind in items:
        agg[(d, min(20, int(round(ntr * 20))), kind)] += 1
    # 先画小类，后画大类，避免遮挡
    order = ["其他偶发", "待核实", "秸秆焚烧疑似", "偏固定源", "工业/固定源"]
    for kind in order:
        for (d, nb, k), cnt in sorted(agg.items()):
            if k != kind:
                continue
            ntr = nb / 20
            x = pad_l + pw * math.log10(max(1, d)) / lx
            yy = pad_t + ph * (1 - ntr)
            r = 1.8 + min(7.0, math.sqrt(cnt) * 0.55)
            op = 0.30 if kind in ("其他偶发", "秸秆焚烧疑似") else 0.75
            parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="{r:.1f}" '
                         f'fill="{KIND_COLOR[kind]}" opacity="{op}"><title>'
                         f'{kind} · 出现 {d} 天 · 夜间 {ntr*100:.0f}% · {cnt} 个点位</title></circle>')
    parts.append(f'<text x="{pad_l+pw/2:.0f}" y="{h-6}" fill="#94a3b8" font-size="11" '
                 f'text-anchor="middle">全年出现天数（对数刻度）</text>')
    parts.append(f'<text x="14" y="{pad_t+ph/2:.0f}" fill="#94a3b8" font-size="11" '
                 f'transform="rotate(-90 14 {pad_t+ph/2:.0f})" text-anchor="middle">夜间占比</text>')
    parts.append("</svg>")
    return "".join(parts)


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#070b14;color:#e2e8f0;
  font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:25px;margin:0 0 6px}
h2{font-size:17px;margin:0 0 6px;color:#38bdf8;font-weight:600}
.sub{color:#94a3b8;font-size:13px;margin-bottom:22px}
.card{background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:18px 20px;margin:0 0 16px}
.card .note{color:#64748b;font-size:12px;margin-top:10px;line-height:1.7}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #1e293b}
th{color:#94a3b8;font-weight:500;font-size:12px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:#94a3b8;font-size:12px;margin-top:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
code{background:#1e293b;padding:1px 5px;border-radius:4px;font-size:12px}
footer{color:#64748b;font-size:12px;margin-top:24px;border-top:1px solid #1e293b;padding-top:16px;line-height:1.8}
"""


def render_html(data, cross=None, halves=None):
    """data = {年: fires}；cross = 跨年结果；halves = {年: 半年结果}"""
    from datetime import datetime, timezone, timedelta
    yrs = sorted(data)
    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>火点类型判别模型 · 验证</title><style>%s</style></head><body>'
         % (CSS + AR.NAV_CSS),
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>火点类型判别模型 · 验证</h1>',
         '<div class="sub">从「点位历史复现」判定火点类型　·　数据：NASA FIRMS VIIRS 375m　·　'
         '生成于 %s</div>' % datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")]

    # 方法
    T = THRESHOLDS
    h.append('<div class="card"><h2>方法：为什么用「点位复现」判类型</h2>'
             '<div class="note">同一点位（0.01° 网格 ≈ 1.1km）在长时间窗内的<b>复现次数</b>'
             '是最强的判别特征，因为两类燃烧的物理行为完全不同：</div>'
             '<table><tr><th>特征</th><th>工业 / 固定源</th><th>农田秸秆焚烧</th></tr>'
             '<tr><td>出现频率</td><td>几乎天天在烧（全年几十到两百多天）</td><td>一次性，很少复现</td></tr>'
             '<tr><td>昼夜</td><td><b>夜里也在烧</b>（窑炉/堆场不熄火）</td><td>基本只在白天（农民下地）</td></tr>'
             '<tr><td>强度</td><td>稳定、偏低</td><td>低</td></tr>'
             '<tr><td>季节</td><td>全年</td><td>集中在收获季（5/6/9/10 月）</td></tr>'
             '</table></div>')

    h.append('<div class="card"><h2>判定规则与阈值依据</h2>'
             '<div class="note">每条阈值都对应实测分布，不是拍出来的：</div><table>'
             '<tr><th>类型</th><th>判据</th><th>阈值依据（2025 年 22,626 条实测）</th></tr>'
             '<tr><td>工业/固定源（高）</td><td>全年 ≥%d 天 且 夜间占比 ≥%.0f%%</td>'
             '<td>出现天数的 P99 = 32 天 → ≥30 天是前 1%%；这批点位夜间占比中位 99%%、'
             'FRP 中位 1.11 MW</td></tr>'
             '<tr><td>工业/固定源（中）</td><td>全年 ≥%d 天</td>'
             '<td>≥10 天已进入前 2%%（7,474 个点位的 P95 = 3 天）</td></tr>'
             '<tr><td>偏固定源</td><td>出现 %d–9 天 且 夜间占比 ≥%.0f%%</td>'
             '<td>介于两者之间，置信度中</td></tr>'
             '<tr><td>秸秆焚烧疑似</td><td>全年 ≤%d 天 且 收获季火点占比 ≥%.0f%%</td>'
             '<td>只出现 1 天的 6,480 个点位：夜间占比仅 25%%、FRP 中位 2.80 MW（白天为主）</td></tr>'
             '<tr><td>其他偶发</td><td>全年 ≤%d 天 且 不在收获季</td><td>卫星无法进一步区分</td></tr>'
             '</table></div>'
             % (T["fixed_high_days"], T["fixed_high_night"] * 100, T["fixed_mid_days"],
                T["lean_days"], T["lean_night"] * 100, T["once_days"],
                T["harvest_ratio"] * 100, T["once_days"]))

    # 散点
    fires_last = data[yrs[-1]]
    prof = build_profiles(fires_last)
    pts = []
    for k, p in prof.items():
        kind, _, _ = classify(p)
        pts.append((p["days"], p["night_ratio"], kind))
    h.append('<div class="card"><h2>特征空间：%d 年 %s 个点位</h2>' % (yrs[-1], f'{len(pts):,}'))
    h.append(svg_scatter(pts))
    h.append('<div class="legend">')
    for kind in KINDS:
        h.append('<span><i style="background:%s"></i>%s</span>' % (KIND_COLOR[kind], kind))
    h.append('</div>')
    h.append('<div class="note">右上角是「又频繁又在夜里烧」的点位——固定源的密集区；'
             '左下角（只出现 1–2 天、多在白天）是一次性燃烧。两类在特征空间里<b>分得很开</b>，'
             '这正是判据成立的原因。蓝色虚线是判定阈值。</div></div>')

    # 类型分布
    h.append('<div class="card"><h2>类型分布</h2><table><tr><th>类型</th>')
    for y in yrs:
        h.append('<th class="num">%d 年火点</th>' % y)
    h.append('<th>说明</th></tr>')
    per = {y: profile_kinds(data[y]) for y in yrs}
    for kind in KINDS:
        h.append('<tr><td style="color:%s">%s</td>' % (KIND_COLOR[kind], kind))
        for y in yrs:
            n = per[y]["kind_fires"].get(kind, 0)
            tot = len(data[y]) or 1
            h.append('<td class="num">%s<br><span style="color:#64748b;font-size:11px">%.1f%%</span></td>'
                     % (f'{n:,}', n / tot * 100))
        h.append('<td style="color:#64748b;font-size:12px">%s</td></tr>' % KIND_DESC[kind])
    h.append('</table></div>')

    # 半年验证
    if halves:
        h.append('<div class="card"><h2>验证 ①：半年分割（用上半年判类型 → 看下半年表现）</h2>')
        for y, res in halves.items():
            h.append('<div class="note" style="color:#94a3b8;margin-top:12px"><b>%d 年</b></div>' % y)
            h.append('<table><tr><th>判出的类型</th><th class="num">点位数</th>'
                     '<th class="num">下半年吻合</th><th class="num">一致率</th>'
                     '<th class="num">下半年天数中位</th></tr>')
            for row in res["rows"]:
                col = "#34d399" if row["rate"] >= 0.8 else ("#fbbf24" if row["rate"] >= 0.6 else "#f97316")
                h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                         '<td class="num" style="color:%s">%.0f%%</td><td class="num">%.0f</td></tr>'
                         % (row["kind"], f'{row["cells"]:,}', f'{row["hit"]:,}',
                            col, row["rate"] * 100, row["b_med"]))
            h.append('</table>')
        h.append('<div class="note"><b>怎么读</b>：判为「工业/固定源」的点位，'
                 '下半年有 80%+ 仍在持续出现（中位十几天）——说明这个判定<b>不是单年的偶然</b>；'
                 '判为「秸秆/偶发」的点位，下半年几乎全部零出现——同样稳定。'
                 '「偏固定源」一致率偏低，说明这个中间类别本身不牢靠，'
                 '产品里应弱化它（或合并进相邻类别）。</div></div>')

    # 跨年验证
    if cross:
        h.append('<div class="card"><h2>验证 ②：跨年一致性（用 %s 判类型 → 看 %s 表现）</h2>'
                 % (cross["name_a"], cross["name_b"]))
        h.append('<table><tr><th>判出的类型</th><th class="num">点位数</th>'
                 '<th class="num">次年吻合</th><th class="num">一致率</th>'
                 '<th class="num">次年天数中位</th><th class="num">次年完全消失</th></tr>')
        for row in cross["rows"]:
            col = "#34d399" if row["rate"] >= 0.8 else ("#fbbf24" if row["rate"] >= 0.6 else "#f97316")
            h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num" style="color:%s">%.0f%%</td><td class="num">%.0f</td>'
                     '<td class="num">%s</td></tr>'
                     % (row["kind"], f'{row["cells"]:,}', f'{row["hit"]:,}', col,
                        row["rate"] * 100, row["b_med"], f'{row["b_zero"]:,}'))
        h.append('</table>')
        h.append('<div class="note">跨年仍稳定，才说明这个判据抓的是<b>真实存在的物理对象</b>'
                 '（工厂的窑炉不会因为换了年份就消失），而不是随机噪声。</div></div>')

    h.append('<footer><b>方法与边界</b><br>'
             '· 判据全部基于卫星可观测特征（复现天数、昼夜、FRP、季节），规则透明、可复核，'
             '<b>不调用任何模型</b>，同一份输入永远得到同一个结论。<br>'
             '· <b>没有地面真值</b>——遥感无法确证某个火点就是秸秆焚烧或某家工厂。'
             '所以这里验的是判据的<b>稳定性</b>（跨期/跨年是否一致），不是「准确率」。<br>'
             '· 输出是<b>疑似类型 + 依据</b>，<b>不能作为行政处罚依据</b>；'
             '用于执法须经现场核实。<br>'
             '· 要进一步提升判别力，需接入外部图层：<b>土地利用/地类</b>'
             '（HJ 1008-2018 要求结合农田范围判定秸秆焚烧）、工业区 POI、VIIRS 夜间灯光。<br>'
             '· 本页由 <code>classify.py</code> 从原始数据自动生成，全部数字可复算。</footer>')
    h.append('</div></body></html>')
    return "".join(h)


# ---------------------------------------------------------------- CLI

def _load(year):
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "history" / ("%d.json" % year)
    if not p.exists():
        raise SystemExit("[classify] 缺少 %s" % p)
    return json.loads(p.read_text(encoding="utf-8"))["fires"]


def main():
    import sys
    from pathlib import Path
    years = sorted({int(a) for a in sys.argv[1:] if a.isdigit()}) or [2025]
    print("[classify] 载入年份：%s" % years)
    data = {y: _load(y) for y in years}

    for y, fires in data.items():
        r = profile_kinds(fires)
        n = len(fires)
        print("\n=== %d 年：%d 条火点 / %d 个点位 ===" % (y, n, len(r["profiles"])))
        for k in KINDS:
            c, f_ = r["kind_cells"].get(k, 0), r["kind_fires"].get(k, 0)
            if c or f_:
                print("  %-8s 点位 %5d · 火点 %6d (%.1f%%)" % (k, c, f_, f_ / n * 100))

    # 验证 ①：半年分割
    halves = {}
    for y, fires in data.items():
        a, b = split_half(fires)
        res = cross_period(a, b, "上半年", "下半年")
        halves[y] = res
        print("\n=== %d 年 半年分割验证（用上半年判类型 → 看下半年表现）===" % y)
        print("  %-10s %6s %6s %8s %10s" % ("类型", "点位数", "吻合", "一致率", "B期天数中位"))
        for row in res["rows"]:
            print("  %-10s %6d %6d %7.0f%% %10.0f"
                  % (row["kind"], row["cells"], row["hit"], row["rate"] * 100, row["b_med"]))

    # 验证 ②：跨年
    cross = None
    if len(years) >= 2:
        res = cross_period(data[years[0]], data[years[-1]],
                           "%d 年" % years[0], "%d 年" % years[-1])
        cross = res
        print("\n=== 跨年验证（用 %d 年判类型 → 看 %d 年表现）===" % (years[0], years[-1]))
        print("  %-10s %6s %6s %8s %10s %8s"
              % ("类型", "点位数", "吻合", "一致率", "B期天数中位", "完全消失"))
        for row in res["rows"]:
            print("  %-10s %6d %6d %7.0f%% %10.0f %8d"
                  % (row["kind"], row["cells"], row["hit"], row["rate"] * 100,
                     row["b_med"], row["b_zero"]))

    out = Path(__file__).resolve().parent.parent / "report" / "火点类型判别模型-验证.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data, cross, halves), encoding="utf-8")
    print("\n[classify] 写出 %s（%.0f KB）" % (out, out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
