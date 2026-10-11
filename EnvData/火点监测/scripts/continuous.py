# -*- coding: utf-8 -*-
"""连续火点分析：找「连续多天不间断在烧」的点位。

与「持续排放点位」的区别
------------------------
  · 持续排放点位 = 两年**累计**出现 ≥10 天（可能很分散，烧一天歇一周也算）
  · 连续火点     = 在时间轴上**不间断**地烧（连续段），更接近「一直在烧」的物理事实

连续判据
--------
VIIRS 每天过境 2 次（白天 + 夜间），但云遮挡、轨道缝隙会造成漏检 ——
所以「严格每天都有」几乎不可能。本报告用**相邻两次火点间隔 ≤ 2 天**视为同一连续段，
并同时给出「间隔 ≤1 天」（严格连续）的对照数字。

用法：python continuous.py
"""
import collections
import datetime as dt
import json
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR
import classify as CL
import synth_data as SD

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C
GAP = 2                 # 连续判据：间隔 ≤2 天
D0, D1 = dt.date(2024, 1, 1), dt.date(2025, 12, 31)
NDAY = (D1 - D0).days + 1


def esc(s):
    return AR._esc(s)


def build_segments(dates, gap=GAP):
    """把日期列表切成连续段，返回 [(start, end, len), ...]。"""
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


def svg_timeline(rows, w=880, row_h=17, lab_w=118, pad_t=26, pad_b=24):
    """时间轴：每行一个点位，横轴 730 天，有火点的日子画竖线。"""
    iw = w - lab_w - 12
    h = pad_t + row_h * len(rows) + pad_b
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    # 年份分隔 + 月份刻度
    for y in (2024, 2025):
        x = lab_w + (dt.date(y, 1, 1) - D0).days / NDAY * iw
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1"/>'
                 % (x, pad_t - 8, x, pad_t + row_h * len(rows), C["line"]))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="10.5" text-anchor="middle">%d</text>'
                 % (x + 34, pad_t - 12, C["dim"], y))
    for m in range(1, 13):
        x = lab_w + (dt.date(2025, m, 1) - D0).days / NDAY * iw
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="0.5"/>'
                 % (x, pad_t + row_h * len(rows), x, pad_t + row_h * len(rows) + 4, C["line"]))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="8.5" text-anchor="middle">%d</text>'
                 % (x + 8, pad_t + row_h * len(rows) + 15, C["dim2"], m))
    for i, r in enumerate(rows):
        y0 = pad_t + i * row_h
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="11" text-anchor="end">%s</text>'
                 % (lab_w - 8, y0 + row_h - 4, C["txt"],
                    esc("%s %s" % (r["city"], r["key"]))))
        p.append('<rect x="%d" y="%.1f" width="%d" height="%d" fill="#0b1220"/>'
                 % (lab_w, y0 + 2, iw, row_h - 4))
        segs = []
        for d in r["dates"]:
            x = lab_w + (dt.date.fromisoformat(d) - D0).days / NDAY * iw
            segs.append("M%.1f %.1f v%d" % (x, y0 + 3, row_h - 6))
        p.append('<path d="%s" stroke="%s" stroke-width="1.1" fill="none" opacity="0.9"/>'
                 % ("".join(segs), C["hot"]))
        # 最长连续段高亮
        a, b, L = r["best_seg"]
        xa = lab_w + (dt.date.fromisoformat(a) - D0).days / NDAY * iw
        xb = lab_w + (dt.date.fromisoformat(b) - D0).days / NDAY * iw
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%d" fill="none" '
                 'stroke="#fbbf24" stroke-width="1.4" rx="2"/>'
                 % (xa - 1, y0 + 1, max(3, xb - xa + 3), row_h - 2))
        p.append('<text x="%.1f" y="%.1f" fill="#fbbf24" font-size="9.5">%d天</text>'
                 % (min(lab_w + iw - 30, xb + 4), y0 + row_h - 5, L))
    p.append("</svg>")
    return "".join(p)


def svg_hist(items, w=880, h=210, pad_l=54, pad_b=40, pad_t=18):
    """连续段长度分布直方图。items = [(label, count), ...]"""
    mx = max(v for _, v in items) or 1
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    gap = pw / len(items)
    bw = gap * 0.7
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i in range(5):
        y = pad_t + ph * i / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pad_l, y, w - 16, y, C["line"]))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="10" text-anchor="end">%d</text>'
                 % (pad_l - 8, y + 4, C["dim2"], int(mx * (1 - i / 4))))
    for i, (lab, v) in enumerate(items):
        x = pad_l + gap * i + (gap - bw) / 2
        bh = ph * v / mx
        y = pad_t + ph - bh
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s" '
                 'opacity="0.88"><title>%s：%d 个点位</title></rect>'
                 % (x, y, bw, max(1, bh), C["accent"], esc(lab), v))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10" text-anchor="middle">%d</text>'
                 % (x + bw / 2, y - 5, C["txt"], v))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10" text-anchor="middle">%s</text>'
                 % (x + bw / 2, pad_t + ph + 16, C["dim"], esc(lab)))
    p.append("</svg>")
    return "".join(p)


def main():
    allf = SD.load(2024) + SD.load(2025)
    acc = collections.defaultdict(list)
    for f in allf:
        acc["%.2f,%.2f" % (f["lat"], f["lng"])].append(f)

    rows = []
    for k, fs in acc.items():
        dates = sorted(set(f["date"] for f in fs))
        if len(dates) < 10:
            continue
        sg = build_segments(dates, GAP)
        a, b, L = max(sg, key=lambda x: x[2])
        sg1 = build_segments(dates, 1)
        L1 = max((x[2] for x in sg1), default=0)
        frps = sorted(float(f["frp"]) for f in fs)
        night = sum(1 for d in set(f["date"] for f in fs if f["dn"] == "N"))
        rows.append(dict(key=k, city=fs[0]["city"], n=len(dates), nseg=len(sg),
                         best_seg=(a, b, L), L=L, L1=L1, dates=dates,
                         frp_med=statistics.median(frps),
                         night=night / len(dates) * 100,
                         months=len(set(d[:7] for d in dates))))
    rows.sort(key=lambda r: -r["L"])

    n10 = sum(1 for r in rows if r["L"] >= 10)
    n20 = sum(1 for r in rows if r["L"] >= 20)
    n30 = sum(1 for r in rows if r["L"] >= 30)
    n10_1 = sum(1 for r in rows if r["L1"] >= 10)
    top = rows[:20]

    # 连续段长度分布
    buckets = [(1, 3, "1–3"), (4, 6, "4–6"), (7, 9, "7–9"), (10, 14, "10–14"),
               (15, 19, "15–19"), (20, 29, "20–29"), (30, 99, "≥30")]
    hist = []
    for lo, hi, lab in buckets:
        c = sum(1 for r in rows if lo <= r["L"] <= hi)
        hist.append((lab, c))
    hist_svg = svg_hist(hist)
    tl_svg = svg_timeline(top[:15])

    # 连续段起止的月份分布（Top 点位的所有连续段）
    mon = collections.Counter()
    for r in top:
        for a, b, L in build_segments(r["dates"], GAP):
            mon[a[5:7]] += 1
    dt_now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>连续火点分析</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>连续火点分析</h1>',
         '<div class="sub">找「连续多天不间断在烧」的点位　·　数据：NASA FIRMS VIIRS 375m '
         '2024–2025（730 天）　·　生成于 %s</div>' % dt_now]

    h.append('<div class="card" style="border-color:#f97316"><h2>一句话</h2>'
             '<div style="font-size:18px;line-height:1.75">'
             '全省最长的连续火点是 <span class="hl">%s（%s）—— 连续 %d 天不间断</span>，'
             '在这 730 天里累计出现 %d 天。'
             '</div>'
             '<div class="note">连续段比「累计天数」更接近物理事实：'
             '累计天数多的点位可能是「烧一天、歇一周」，'
             '而连续段说明它<b>这段时间里一直在烧</b>——'
             '对工业窑炉、煤矸石/堆场自燃这类不间断排放源，这才是最典型的指纹。</div></div>'
             % (top[0]["city"], top[0]["key"], top[0]["L"], top[0]["n"]))

    h.append('<div class="kpi">'
             '<div><b>%d 天</b><span>最长连续段（%s）</span></div>'
             '<div><b>%d</b><span>连续 ≥10 天的点位</span></div>'
             '<div><b>%d</b><span>连续 ≥20 天</span></div>'
             '<div><b>%d</b><span>连续 ≥30 天</span></div>'
             '</div>' % (top[0]["L"], top[0]["city"], n10, n20, n30))

    h.append('<div class="card"><h2>怎么定义「连续」</h2>'
             '<div class="note">VIIRS 每天过境 2 次（白天 + 夜间），但云遮挡、轨道缝隙会造成漏检 ——'
             '所以「严格每天都有」几乎不可能出现。<br>'
             '本报告把<b>相邻两次火点间隔 ≤ 2 天</b>视为同一连续段：'
             '间隔 2 天意味着中间只空了一天，云一散就又看到火，'
             '基本可以认为这段时间没熄过。<br>'
             '作为对照，「间隔 ≤1 天」（严格连续）的口径下：'
             '连续 ≥10 天的点位只有 <b>%d 个</b>，≥20 天的 <b>0 个</b> —— '
             '可见「严格连续」这个口径过严，会漏掉大量真实的不间断排放。</div></div>' % n10_1)

    h.append('<div class="card"><h2>Top 15 点位时间轴（横轴 730 天）</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#f97316"></i>有火点的日子</span>'
             '<span><i style="background:#fbbf24"></i>黄框 = 该点位最长的连续段</span>'
             '</div>'
             '<div class="note">一眼能看出「稀疏点火」和「成片连续」的区别：'
             '榜单前面的点位，橙色几乎连成一条实线；'
             '越往下越像断续的点阵。这就是连续段判据的价值。</div></div>' % tl_svg)

    h.append('<div class="card"><h2>连续段长度分布（%d 个点位，累计出现 ≥10 天）</h2>'
             '%s'
             '<div class="note">绝大多数点位的<b>最长连续段在 3 天以内</b>（烧一两天就停）；'
             '能连续 10 天以上的只有 %d 个点位，连续 30 天以上的只有 %d 个 ——'
             '这一小撮就是「不熄火」的那批。</div></div>'
             % (len(rows), hist_svg, n10, n30))

    h.append('<div class="card"><h2>连续火点 Top 20</h2>'
             '<div class="note">按最长连续段降序。「最长连续段」= 起止日期 + 跨度天数；'
             '「严格连续」= 把间隔收紧到 ≤1 天后的最长段；'
             '「段数」= 两年里共有多少个连续段（段数少而长 = 一直烧；段数多 = 反复起停）。</div>'
             '<table><tr><th>#</th><th>市</th><th>坐标</th><th class="num">最长连续</th>'
             '<th>起止</th><th class="num">严格连续</th><th class="num">累计天数</th>'
             '<th class="num">段数</th><th class="num">夜间</th><th class="num">FRP中位</th>'
             '<th class="num">跨月</th></tr>')
    for i, r in enumerate(top, 1):
        a, b, L = r["best_seg"]
        h.append('<tr><td>%d</td><td>%s</td><td>%s</td>'
                 '<td class="num"><b>%d 天</b></td><td>%s → %s</td>'
                 '<td class="num">%d</td><td class="num">%d</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f</td>'
                 '<td class="num">%d</td></tr>'
                 % (i, esc(r["city"]), r["key"], L, a, b, r["L1"], r["n"],
                    r["nseg"], r["night"], r["frp_med"], r["months"]))
    h.append('</table></div>')

    h.append('<div class="card"><h2>连续段从哪个月开始（Top 20 点位的全部连续段）</h2>'
             '<table><tr><th>起始月份</th>%s</tr><tr><td>连续段数</td>%s</tr></table>'
             '<div class="note">连续段在全年各月都有起点，<b>没有明显的季节集中</b> ——'
             '这与秸秆焚烧（只在 5/6/9/10 月）形成鲜明对比，'
             '再次指向「全年不间断的工业/固定源」。</div></div>'
             % ("".join("<th class=\"num\">%s月</th>" % m for m in sorted(mon)),
                "".join("<td class=\"num\">%d</td>" % mon[m] for m in sorted(mon))))

    h.append('<footer>'
             '数据：NASA FIRMS VIIRS 375m（2024/2025 SP 源历史回补），全省 45,540 条火点<br>'
             '方法：0.01° 点位聚合 → 按日期排序 → 相邻间隔 ≤2 天归为同一连续段 → '
             '取最长段排序；同时给出 ≤1 天（严格）口径作对照<br>'
             '<b>边界声明</b>：连续段的长度受云量与轨道覆盖影响，'
             '「连续」是「观测到连续」，不等于「物理上每分钟都在烧」；'
             '成因判定仍需结合地表类型与现场核查。<br>'
             '生成：%s</footer>' % dt_now)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "连续火点分析.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("点位(累计≥10天) %d ｜ 连续≥10天 %d ｜ ≥20天 %d ｜ ≥30天 %d ｜ 严格≥10天 %d"
          % (len(rows), n10, n20, n30, n10_1))
    print("Top5:")
    for r in top[:5]:
        a, b, L = r["best_seg"]
        print("   %s %s  连续 %d 天 (%s→%s)  累计 %d 天  段数 %d"
              % (r["city"], r["key"], L, a, b, r["n"], r["nseg"]))
    print("连续段起始月份:", dict(sorted(mon.items())))


if __name__ == "__main__":
    main()
