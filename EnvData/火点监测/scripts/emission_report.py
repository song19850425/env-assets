# -*- coding: utf-8 -*-
"""《持续火点排放量估算 · 从假设到观测》报告生成器。

回答的问题：这些持续火点的辐射值，相当于烧掉多少燃料、排放多少污染物？

本报告的核心贡献：把估算链里最大的假设（每天燃烧多久）从「拍脑袋」
钉到 VIIRS 多窗口观测上，并用蒙特卡洛给出区间而非单点值。

数据：
  · data/north6/frp-evidence.json   燃烧时长的观测证据
  · data/north6/fuel-mc.json        蒙特卡洛抽样（20000 次）
  · data/satellite/no2co-ratio.json TROPOMI NO2/CO 比值（独立验证）
用法：python emission_report.py
"""
import json
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR
import synth_data as SD

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C
TXT, DIM, LINE, PANEL, BG = C["txt"], C["dim"], C["line"], C["panel"], C["bg"]


def esc(s):
    return AR._esc(s)


# ─────────────────────────── SVG ───────────────────────────

def svg_frp_floor(day, night, w=880, h=300, pad_l=54, pad_b=46, pad_t=22):
    """白天 / 夜间 FRP 分布对比，显示白天的探测下限。"""
    edges = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 1e9)]
    labs = ["<1", "1-2", "2-3", "3-5", "5-10", "10-20", "20+"]

    def hist(arr):
        n = len(arr) or 1
        return [sum(1 for v in arr if a <= v < b) / n * 100 for a, b in edges]

    hd, hn = hist(day), hist(night)
    mx = max(max(hd), max(hn)) or 1
    pw, ph = w - pad_l - 20, h - pad_b - pad_t
    bw = pw / len(edges)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    # 网格
    for k in range(5):
        y = pad_t + ph - ph * k / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                 % (pad_l, y, w - 20, y, LINE))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="11" text-anchor="end">%.0f%%</text>'
                 % (pad_l - 8, y + 4, DIM, mx * k / 4))
    for i, (lab, a, b) in enumerate(zip(labs, hd, hn)):
        x0 = pad_l + i * bw
        for j, (v, col) in enumerate(((a, "#fbbf24"), (b, "#6366f1"))):
            bh = ph * v / mx
            bx = x0 + bw * 0.16 + j * bw * 0.34
            p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2" '
                     'fill-opacity="0.9"/>' % (bx, pad_t + ph - bh, bw * 0.30, max(bh, 0.6), col))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="12" text-anchor="middle">%s</text>'
                 % (x0 + bw / 2, h - pad_b + 20, DIM, lab))
    p.append('<text x="%d" y="%d" fill="%s" font-size="12" text-anchor="middle">'
             '火点辐射功率 FRP（MW）</text>' % (w // 2, h - 10, DIM))
    # 探测下限标注（分类轴：第 3 个箱 = 2-3 MW）
    xf = pad_l + pw * (2.5 / 7)
    p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#ef4444" '
             'stroke-width="1.6" stroke-dasharray="5 4"/>' % (xf, pad_t + 6, xf, pad_t + ph))
    p.append('<text x="%.1f" y="%d" fill="#ef4444" font-size="12" font-weight="600">'
             '白天探测下限 ≈2-3 MW</text>' % (xf + 8, pad_t + 20))
    p.append('</svg>')
    return "".join(p)


def svg_mc_hist(hd, qs, w=880, h=280, pad_l=54, pad_b=46, pad_t=22):
    """折煤量蒙特卡洛分布 + P10/P50/P90。hd={lo,hi,counts}，qs=[P10..P90]。"""
    lo, hi, bins = hd["lo"], hd["hi"], hd["counts"]
    nb = len(bins)
    mx = max(bins) or 1
    pw, ph = w - pad_l - 20, h - pad_b - pad_t
    bw = pw / nb
    step = (hi - lo) / nb or 1
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for i, c in enumerate(bins):
        bh = ph * c / mx
        x = pad_l + i * bw
        v0 = lo + i * step
        col = "#f97316" if qs[0] <= v0 <= qs[4] else "#475569"
        p.append('<rect x="%.1f" y="%.1f" width="%.2f" height="%.1f" fill="%s"/>'
                 % (x, pad_t + ph - bh, bw * 0.92, max(bh, 0.6), col))
    for x, lab, col in ((qs[0], "P10", "#94a3b8"), (qs[2], "P50", "#fbbf24"),
                        (qs[4], "P90", "#94a3b8")):
        xf = pad_l + (x - lo) / (hi - lo or 1) * pw
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.8" '
                 'stroke-dasharray="4 3"/>' % (xf, pad_t, xf, pad_t + ph, col))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12" font-weight="600" '
                 'text-anchor="middle">%s %.0f</text>' % (xf, pad_t + 14, col, lab, x))
    p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.4"/>'
             % (pad_l, pad_t + ph, w - 20, pad_t + ph, LINE))
    p.append('<text x="%d" y="%d" fill="%s" font-size="12" text-anchor="middle">'
             '折合燃煤量（万吨 / 两年）</text>' % (w // 2, h - 10, DIM))
    p.append('</svg>')
    return "".join(p)


def svg_tornado(rows, w=880, row_h=46, lab_w=140, pad_r=96):
    """单参数敏感性：每个参数的取值区间对应结果区间。"""
    mx = max(max(r["va"], r["vb"]) for r in rows) or 1
    h = row_h * len(rows) + 16
    pw = w - lab_w - pad_r
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for i, r in enumerate(rows):
        y = 8 + i * row_h
        x0 = lab_w + pw * min(r["va"], r["vb"]) / mx
        x1 = lab_w + pw * max(r["va"], r["vb"]) / mx
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 12, y + 24, TXT, esc(r["name"])))
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="20" fill="%s" rx="4" '
                 'fill-opacity="0.85"/>' % (x0, y + 8, max(x1 - x0, 3), r["col"]))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12">%.0f</text>'
                 % (x0 - 6, y + 23, DIM, min(r["va"], r["vb"])))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12">%.0f 万吨</text>'
                 % (x1 + 8, y + 23, DIM, max(r["va"], r["vb"])))
    p.append('</svg>')
    return "".join(p)


def svg_ratio(rows, w=880, row_h=38, lab_w=140, val_w=110):
    """TROPOMI NO2/CO 比值横条。"""
    mx = max(r["ratio"] for r in rows) or 1
    h = row_h * len(rows) + 14
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for i, r in enumerate(rows):
        y = 7 + i * row_h
        bl = pw * r["ratio"] / mx
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 12, y + 22, TXT, esc(r["name"])))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="20" fill="%s" rx="4"/>'
                 % (lab_w, y + 6, bl, r["col"]))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="13" font-weight="600">'
                 '%.2f</text>' % (lab_w + bl + 8, y + 22, TXT, r["ratio"]))
    p.append('</svg>')
    return "".join(p)


def svg_prov_bars(rows, w=880, row_h=44, lab_w=76, val_w=200):
    """六省持续火点折煤量横条（含 P10–P90 误差线）。"""
    mx = max(r["coal90"] for r in rows) or 1
    h = row_h * len(rows) + 16
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for i, r in enumerate(rows):
        y = 8 + i * row_h
        bl = pw * r["coal50"] / mx
        x10 = lab_w + pw * r["coal10"] / mx
        x90 = lab_w + pw * r["coal90"] / mx
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 12, y + 26, TXT, esc(r["name"])))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="22" fill="%s" rx="4" '
                 'fill-opacity="0.9"/>' % (lab_w, y + 8, max(bl, 3), r["col"]))
        # P10–P90 误差线
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#e2e8f0" '
                 'stroke-width="1.4" stroke-opacity="0.55"/>' % (x10, y + 19, x90, y + 19))
        for xv in (x10, x90):
            p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#e2e8f0" '
                     'stroke-width="1.4" stroke-opacity="0.55"/>' % (xv, y + 14, xv, y + 24))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="13" font-weight="600">'
                 '%.0f 万吨（%d 个点位）</text>'
                 % (x90 + 8, y + 26, TXT, r["coal50"], r["hot"]))
    p.append('</svg>')
    return "".join(p)


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    ev = json.load(open(os.path.join(MOD, "data", "north6", "frp-evidence.json"), encoding="utf-8"))
    mc = json.load(open(os.path.join(MOD, "data", "north6", "fuel-mc.json"), encoding="utf-8"))
    ratio = json.load(open(os.path.join(MOD, "data", "satellite", "no2co-ratio.json"), encoding="utf-8"))
    prov = json.load(open(os.path.join(MOD, "data", "north6", "emission-by-prov.json"), encoding="utf-8"))

    # 原始 FRP 分布（画图用）
    fires = SD.load(2024) + SD.load(2025)

    def hr(t):
        t = str(t).zfill(4)
        return int(t[:2]) + int(t[2:]) / 60

    day = [f["frp"] for f in fires if hr(f["time"]) < 10]
    night = [f["frp"] for f in fires if hr(f["time"]) >= 10]

    IDX = {0.10: 0, 0.25: 1, 0.50: 2, 0.75: 3, 0.90: 4}

    def stat(key, arr, pct):
        return arr["q"][key][IDX[pct]]

    prof = SD.profiles(fires)
    hot = [p for p in prof.values() if p["days"] >= 10]
    top19 = [p for p in prof.values() if p["days"] >= 200]

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    css = (AR.CSS.replace("__BG__", BG).replace("__PANEL__", PANEL)
           .replace("__TXT__", TXT).replace("__DIM__", DIM)
           .replace("__LINE__", LINE).replace("__ACC__", C["accent"]))

    h = []
    h.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>持续火点排放量估算 · 从假设到观测</title><style>%s</style></head><body>' % css)
    h.append(AR.nav_back_html())
    h.append('<div class="wrap">')
    h.append('<h1>持续火点排放量估算</h1>')
    h.append('<div class="sub">河南 203 个持续排放点位 ｜ 用 FRP 反推燃料消耗与污染物排放 ｜ '
             '2024–2025 两年 ｜ 生成于 %s</div>' % now)

    # 结论
    h.append('<div class="card" style="border-color:#f97316"><h2>一句话结论</h2>'
             '<div style="font-size:18px;line-height:1.8">'
             '这 203 个点位两年烧掉约 <span class="hl">29–74 万吨煤</span>（中位 45 万吨），'
             '量级相当于 <b>0.25 个 300 MW 燃煤机组</b> —— <b>燃料量不大</b>。'
             '但它们<b>零治理</b>：同样一堆煤，PM2.5 排放量是达标锅炉的 <b>100 倍</b>。'
             '</div>'
             '<div class="note">'
             '所以管控依据是<b>排放方式</b>，不是排放总量。'
             '本报告相比初版的最大改进：把估算链里最大的假设「每天烧多久」'
             '从拍脑袋的 4/8/16 小时，<b>钉到了卫星观测上</b>。'
             '</div></div>')

    # 一、方法链
    h.append('<div class="card"><h2>一、估算链条</h2>'
             '<table><tr><th>步骤</th><th>公式</th><th>参数来源</th></tr>'
             '<tr><td>① 辐射能</td><td>FRE = FRP × 每天燃烧秒数 × 出现天数</td>'
             '<td>FRP 来自 VIIRS 实测；<b>燃烧时长本次用观测约束</b>；天数来自点位档案</td></tr>'
             '<tr><td>② 总热释放</td><td>热释放 = FRE ÷ 辐射效率 η</td>'
             '<td><b>η 无法从数据约束</b>，取文献区间 0.08–0.30</td></tr>'
             '<tr><td>③ 燃料量</td><td>燃料 = 热释放 ÷ 热值 HV</td>'
             '<td>煤 22 / 煤矸石 9 MJ/kg，取 9–25 区间</td></tr>'
             '<tr><td>④ 污染物</td><td>污染物 = 燃料 × 排放因子 EF</td>'
             '<td>煤燃烧未治理因子，逐个给区间</td></tr>'
             '</table>'
             '<div class="note">四步里 ①③④ 都能给区间，只有 ② 的 η 是硬缺口 —— '
             '它是「烧出来的总热量」和「卫星看到的那部分辐射」之间的比例，'
             '取决于燃烧状态（明火/闷烧），<b>只能靠实验测定</b>。</div></div>')

    # 二、燃烧时长
    h.append('<div class="card" style="border-color:#38bdf8">'
             '<h2>二、关键改进：燃烧时长从假设 → 观测</h2>'
             '<div class="big">初版里「每天烧多久」是拍脑袋的三档（4/8/16 h）。'
             '这次用 VIIRS 的<b>多窗口观测</b>把它钉住了。</div>')

    h.append('<h3 style="color:%s;font-size:15px;margin:16px 0 6px">'
             '证据 1：每天其实只有 2 个有效观测窗口</h3>' % C["accent"])
    h.append('<div class="note">SNPP 与 NOAA-20 两颗卫星在河南的过境时刻<b>几乎完全重合</b>'
             '（白天都在 UTC 5.4，夜间都在 UTC 18.2），相隔 <b>%.1f 小时</b>。'
             '所以「每天 4 次过境」实际只能提供 2 次有效观测。</div>' % ev["gap_hours"])

    h.append('<h3 style="color:%s;font-size:15px;margin:16px 0 6px">'
             '证据 2：白天存在约 2–3 MW 的探测下限</h3>' % C["accent"])
    h.append(svg_frp_floor(day, night))
    h.append('<table style="margin-top:12px">'
             '<tr><th>窗口</th><th class="num">样本</th><th class="num">P10</th>'
             '<th class="num">中位</th><th class="num">P90</th>'
             '<th class="num">FRP&lt;3MW 占比</th></tr>'
             '<tr><td>白天</td><td class="num">%s</td><td class="num">%.2f</td>'
             '<td class="num">%.2f</td><td class="num">%.2f</td>'
             '<td class="num">%.1f%%</td></tr>'
             '<tr><td>夜间</td><td class="num">%s</td><td class="num">%.2f</td>'
             '<td class="num">%.2f</td><td class="num">%.2f</td>'
             '<td class="num">%.1f%%</td></tr></table>'
             % (format(ev["day_all"]["n"], ","), ev["day_all"]["p10"], ev["day_all"]["med"],
                ev["day_all"]["p90"], ev["day_all"]["lt3"],
                format(ev["night_all"]["n"], ","), ev["night_all"]["p10"],
                ev["night_all"]["med"], ev["night_all"]["p90"], ev["night_all"]["lt3"]))
    h.append('<div class="note">白天 FRP 的 P10 是 <b>%.2f MW</b>，夜间只有 <b>%.2f MW</b>；'
             '白天几乎看不到 3 MW 以下的火（只有 %.1f%% 低于 3 MW），夜间却有 %.1f%%。'
             '这是太阳反射抬高背景噪声造成的<b>探测能力差异</b>，不是火的行为差异。'
             '而持续点位的 FRP 中位只有 <b>%.2f MW</b>（19 个钉子户 %.2f MW）——'
             '<b>根本够不到白天的门槛</b>。</div>'
             % (ev["day_all"]["p10"], ev["night_all"]["p10"], ev["day_all"]["lt3"],
                ev["night_all"]["lt3"], ev["hot_frp_med"], ev["top19_frp_med"]))

    h.append('<h3 style="color:%s;font-size:15px;margin:16px 0 6px">'
             '证据 3：但有 %s 个「点-日」昼夜都被看到 —— 白天确实在烧</h3>'
             % (C["accent"], format(ev["n_pairs"], ",")))
    h.append('<div class="big">这些点-日里，火在间隔 <span class="hl">%.1f 小时</span>'
             '的两个窗口都被探测到，<b>说明这段时间内火没有熄</b>。'
             '白天 FRP 中位 %.2f MW、夜间 %.2f MW。</div>'
             % (ev["gap_hours"], ev["pair_frp_day"], ev["pair_frp_night"]))
    h.append('<div class="note">如果火真的只在夜里烧，那白天窗口不该抓到它 —— '
             '但抓到了 %s 次。所以「夜间占比 94%%」不是「只在夜里烧」，'
             '而是<b>「白天看不见」</b>。工业窑炉和堆场自燃也不会白天停工。</div>'
             % format(ev["n_pairs"], ","))
    h.append('<div class="note" style="border-left-color:#f97316">'
             '<b>结论：这些点位是全天候燃烧，「每天燃烧时长」应按接近 24 小时估算。</b>'
             '初版的「中性 8 小时」低估约 3 倍。保守起见，本次取 <b>12–24 小时</b>的三角分布'
             '（众数 24）。</div></div>')

    # 三、结果
    h.append('<div class="card"><h2>三、估算结果（蒙特卡洛 20,000 次抽样）</h2>')
    h.append(svg_mc_hist(mc["all"]["coal_hist"], mc["all"]["q"]["coal"]))
    h.append('<div class="note">参数按三角分布抽样：燃烧时长 12–24 h、辐射效率 0.08–0.30、'
             '热值 9–25 MJ/kg、排放因子逐个给区间。橙色为 P10–P90 区间。</div>')
    h.append('<table style="margin-top:14px"><tr><th>指标（两年累计）</th>'
             '<th class="num">P10</th><th class="num">P50</th><th class="num">P90</th>'
             '<th class="num">年均（P50）</th></tr>')
    rows = [("折合燃煤（万吨）", "coal", 1), ("PM2.5（吨）", "PM2.5", 0),
            ("PM10（吨）", "PM10", 0), ("SO₂（吨）", "SO2", 0),
            ("NOx（吨）", "NOx", 0), ("CO（吨）", "CO", 0)]
    for lab, key, dec in rows:
        v10, v50, v90 = stat(key, mc["all"], .1), stat(key, mc["all"], .5), stat(key, mc["all"], .9)
        h.append('<tr><td>%s</td><td class="num">%.*f</td><td class="num"><b>%.*f</b></td>'
                 '<td class="num">%.*f</td><td class="num">%.*f</td></tr>'
                 % (lab, dec, v10, dec, v50, dec, v90, dec, v50 / 2))
    h.append('</table>')
    h.append('<div class="note">其中 <b>19 个「钉子户」（占点位数的 9%%）贡献了约 43%%</b>：'
             '折煤 %.1f 万吨（P50）、PM2.5 %.0f 吨、SO₂ %.0f 吨。</div>'
             % (stat("coal", mc["top19"], .5), stat("PM2.5", mc["top19"], .5),
                stat("SO2", mc["top19"], .5)))

    # 直观参照
    _c50 = stat("coal", mc["all"], .5)
    _days = sum(p["days"] for p in hot)
    _per_day = _c50 * 10000 / _days
    _t19 = stat("coal", mc["top19"], .5)
    _d19 = sum(p["days"] for p in top19)
    h.append('<table style="margin-top:14px"><tr><th>换个说法</th><th>数值</th></tr>'
             '<tr><td>单点位「在燃烧的那一天」平均烧掉</td>'
             '<td><b>%.0f 吨煤</b>（≈ 一辆重型自卸车满载的量）</td></tr>'
             '<tr><td>一个「钉子户」两年累计烧掉</td>'
             '<td><b>%.0f 吨煤</b>（年均 %.0f 吨）</td></tr>'
             '<tr><td>203 个点位两年总燃料量</td>'
             '<td>相当于 <b>%.1f 万吨标煤</b>（按 20 MJ/kg 折算）</td></tr>'
             '<tr><td>若换成天然气口径</td>'
             '<td>⚠ <b>不适用</b> —— 天然气不会无组织自燃，这类点位物理上只可能是固体燃料</td></tr>'
             '</table>'
             % (_per_day, _t19 * 10000 / 19, _t19 * 10000 / 19 / 2, _c50 * 20 / 29.3))

    h.append('<h3 style="color:%s;font-size:15px;margin:20px 0 6px">'
             '为什么「量不大」却仍要管：排放方式</h3>' % C["accent"])
    h.append('<table><tr><th>污染物</th><th class="num">无组织自燃</th>'
             '<th class="num">达标锅炉</th><th class="num">倍数</th></tr>')
    for lab, key, rm in (("PM2.5", "PM2.5", 0.99), ("SO₂", "SO2", 0.95), ("NOx", "NOx", 0.70)):
        v = stat(key, mc["all"], .5)
        h.append('<tr><td>%s</td><td class="num">%.0f 吨</td><td class="num">%.1f 吨</td>'
                 '<td class="num" style="color:#f97316;font-weight:600">%.0f 倍</td></tr>'
                 % (lab, v, v * (1 - rm), 1 / (1 - rm)))
    h.append('</table>'
             '<div class="note">同样烧掉这些煤，如果是在达标锅炉里烧（除尘 99%、脱硫 95%、'
             '脱硝 70%），PM2.5 只排 5 吨、SO₂ 只排 316 吨。'
             '无组织自燃<b>没有任何治理设施</b>，直接排 —— '
             '<b>它们不是「排放总量的大户」，是「排放强度的大户」</b>。</div></div>')

    # 四、敏感性
    h.append('<div class="card"><h2>四、哪个假设最要命</h2>')
    # 确定性基准：h=20、η=0.15、hv=20
    mwd = sum(p["frp_med"] * p["days"] for p in hot)
    base = mwd * 20 * 3600 / 0.15 / 20 / 1e7          # 万吨（两年）
    sens = [
        dict(name="辐射效率 η", va=base * 0.15 / 0.30, vb=base * 0.15 / 0.08, col="#ef4444"),
        dict(name="燃料热值", va=base * 20 / 25, vb=base * 20 / 9, col="#a78bfa"),
        dict(name="每天燃烧时长", va=base * 12 / 20, vb=base * 24 / 20, col="#38bdf8"),
    ]
    h.append(svg_tornado(sens))
    h.append('<table style="margin-top:12px"><tr><th>参数</th><th>取值区间</th>'
             '<th class="num">单独变化时结果极差</th><th>能否用卫星数据约束</th></tr>'
             '<tr><td>辐射效率 η</td><td>0.08 – 0.30</td>'
             '<td class="num" style="color:#ef4444;font-weight:600">3.8 倍</td>'
             '<td>❌ 只能实验测定</td></tr>'
             '<tr><td>燃料热值</td><td>9 – 25 MJ/kg</td><td class="num">2.8 倍</td>'
             '<td>△ 可配合地表/行业推断</td></tr>'
             '<tr><td>每天燃烧时长</td><td>12 – 24 h</td><td class="num">2.0 倍</td>'
             '<td>✅ <b>本次已用多窗口观测约束</b>（原为 4–16 h，8 倍）</td></tr>'
             '</table>'
             '<div class="note">三个参数组合的极差是 <b>21 倍</b>。'
             '本次把「燃烧时长」的区间从 8 倍压到 2 倍，剩下的最大缺口是 η —— '
             '它决定了「卫星看到的那一点辐射」背后到底烧了多少东西。'
             '<b>要提高绝对精度，唯一的办法是实测 η</b>（比如对一个已知堆场做热像仪 + 称重标定）。'
             '在此之前，这份估算只能用于<b>排序和量级判断</b>，不能用于总量考核。</div></div>')

    # 五、独立验证
    h.append('<div class="card"><h2>五、独立验证：TROPOMI 大气化学</h2>'
             '<div class="big">FRP 测的是地表热辐射，TROPOMI 测的是大气柱浓度 —— '
             '两个物理上完全独立的量。如果它们指向同一结论，可信度就高得多。</div>')
    order = ["工业/固定源", "偏固定源", "其他", "偶发（含秸秆）", "全省平均"]
    cols = {"工业/固定源": "#ef4444", "偏固定源": "#f97316", "其他": "#38bdf8",
            "偶发（含秸秆）": "#34d399", "全省平均": "#64748b"}
    rrows = [dict(name=k, ratio=ratio[k]["ratio"], col=cols[k]) for k in order if k in ratio]
    h.append('<div style="margin-top:12px">%s</div>' % svg_ratio(rrows))
    h.append('<table style="margin-top:12px"><tr><th>点位类型</th><th class="num">点位数</th>'
             '<th class="num">NO₂ 中位</th><th class="num">CO 中位</th>'
             '<th class="num">NO₂/CO</th></tr>')
    for k in order:
        if k not in ratio:
            continue
        v = ratio[k]
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f</td>'
                 '<td class="num">%.2f</td><td class="num"><b>%.2f</b></td></tr>'
                 % (esc(k), format(v["n"], ","), v["no2"], v["co"], v["ratio"]))
    h.append('</table>'
             '<div class="note">NO₂/CO 比值按点位类型<b>单调递减</b>：工业源 %.2f &gt; '
             '偏固定源 %.2f &gt; 其他 %.2f &gt; 偶发（含秸秆）%.2f &gt; 全省 %.2f。'
             '高温燃烧（窑炉）NOx 生成多，生物质明火 CO 多 —— '
             '<b>方向与「两类燃烧不是一回事」的推断一致</b>。</div>'
             '<div class="note">⚠ 但要如实说明：这只是<b>方向性旁证</b>，不是定量证据。'
             '原因有三 —— ①NO₂ 和 CO 的卫星像元分辨率不同（2.4 km vs 4.9 km）；'
             '②柱浓度比值不等于排放比值（NO₂ 寿命仅数小时、CO 数周，化学过程会改变比值）；'
             '③工业点位本身就在工业区，NO₂ 高也可能是周边有组织排放贡献的。'
             '<b>它能说明「两类点位不一样」，不能说明「排放量是多少」。</b></div></div>'
             % (ratio.get("工业/固定源", {}).get("ratio", 0),
                ratio.get("偏固定源", {}).get("ratio", 0),
                ratio.get("其他", {}).get("ratio", 0),
                ratio.get("偶发（含秸秆）", {}).get("ratio", 0),
                ratio.get("全省平均", {}).get("ratio", 0)))

    # 六、放到六省看
    ORDER_P = ["河北", "山西", "山东", "河南", "天津", "北京"]
    PCOL = {"河北": "#f97316", "山西": "#a78bfa", "山东": "#38bdf8",
            "河南": "#ef4444", "天津": "#34d399", "北京": "#fbbf24"}
    prows = [dict(name=k, coal50=prov[k]["coal50"], coal10=prov[k]["coal10"],
                  coal90=prov[k]["coal90"], hot=prov[k]["hot"], col=PCOL[k])
             for k in ORDER_P if k in prov]
    tot_hot = sum(prov[k]["hot"] for k in prov)
    tot50 = sum(prov[k]["coal50"] for k in prov)
    h.append('<div class="card" style="border-color:#a78bfa"><h2>六、放到六省看</h2>'
             '<div class="big">用同一套方法和参数，把山河四省 + 京津的 '
             '<span class="hl">%s 个</span>持续排放点位都算一遍。'
             '</div>' % format(tot_hot, ","))
    h.append('<div style="margin-top:14px">%s</div>' % svg_prov_bars(prows))
    h.append('<div class="note">横条为 P50，白线为 P10–P90 区间。'
             '<b>河北 %.0f 万吨是河南 %.0f 万吨的 %.1f 倍</b>，与火点数排名一致。'
             '六省合计折煤 <b>约 %.0f 万吨/两年（年均 %.0f 万吨）</b>，'
             '量级相当于 <b>%.1f 个 300 MW 燃煤机组</b>。'
             '</div>'
             '<div class="note" style="border-left-color:#f97316">'
             '这个总量放在能源盘子里<b>不大</b>（一个省的燃煤消费以千万吨计），'
             '但 %s 个点位每一个都是<b>坐标明确、反复出现、零治理</b>的具体对象。'
             '燃料量小 ≠ 问题小 —— 决定影响的是<b>排放方式</b>，不是燃料总量。</div></div>'
             % (prov["河北"]["coal50"], prov["河南"]["coal50"],
                prov["河北"]["coal50"] / prov["河南"]["coal50"],
                tot50, tot50 / 2, tot50 / 2 / 90, format(tot_hot, ",")))

    # 七、行动含义
    h.append('<div class="card" style="border-color:#34d399"><h2>七、行动含义</h2>'
             '<table><tr><th>做法</th><th>覆盖点位</th><th>覆盖排放量</th><th>投入产出</th></tr>'
             '<tr><td>只查 19 个「钉子户」（≥200 天）</td><td class="num">19 个（9%）</td>'
             '<td class="num"><b>约 43%</b></td><td class="num">最高</td></tr>'
             '<tr><td>查 203 个持续排放点位（≥10 天）</td><td class="num">203 个</td>'
             '<td class="num">约 100%</td><td class="num">高</td></tr>'
             '<tr><td>按火点总数排名考核</td><td class="num">13,736 个</td>'
             '<td class="num">被稀释</td><td class="num">低</td></tr>'
             '</table>'
             '<div class="note"><b>9% 的点位对应 43% 的排放量</b> —— '
             '这是整份报告里最直接的一个行动结论：'
             '先啃 19 个，就能拿到近一半的减排量，而且坐标是现成的、跑不掉。</div></div>')

    # 七、边界
    h.append('<div class="card" style="border-color:#64748b"><h2>八、边界与使用建议</h2>'
             '<table><tr><th>能说</th><th>不能说</th></tr>'
             '<tr><td>✅ 量级是「十几万吨到几十万吨煤」</td>'
             '<td>❌ 「精确到 45.4 万吨」——区间跨 2.5 倍</td></tr>'
             '<tr><td>✅ 无组织自燃的 PM2.5 排放强度是达标锅炉的约 100 倍</td>'
             '<td>❌ 「这些火点导致当地 PM2.5 上升了 X%」——链条上缺扩散模型</td></tr>'
             '<tr><td>✅ 用于点位排序、优先核查、明确责任主体</td>'
             '<td>❌ 用于排污收费、总量核算、浓度贡献分摊</td></tr>'
             '</table>'
             '<div class="note">三个必须标注的假设：'
             '① 燃烧时长按 12–24 h 估（有观测支持，但仍是区间）；'
             '② 辐射效率取文献区间 0.08–0.30，<b>未实测</b>；'
             '③ 燃料按煤计，若实为煤矸石（热值约 9 MJ/kg）则燃料量要再乘 2 倍多。'
             '另：FRP 只反映<b>卫星过境瞬间</b>的辐射，点位在两次过境之间的实际状态无从得知。</div>'
             '<div class="note">数据与方法均可复现：'
             '<code>build_frp_evidence.py</code>（观测证据）→ '
             '<code>fuel_estimate.py</code>（蒙特卡洛）→ '
             '<code>emission_north6.py</code>（六省总量）→ '
             '<code>emission_report.py</code>（本报告）。</div></div>')

    h.append('<div class="sub" style="margin-top:26px;text-align:center">'
             '河南火点监测 · 排放量估算 ｜ 数据源：NASA FIRMS (VIIRS SNPP/NOAA-20)、'
             'ESA S5P-PAL (TROPOMI) ｜ 生成于 %s</div>' % now)
    h.append('</div></body></html>')

    p = os.path.join(OUT, "持续火点排放量估算.html")
    open(p, "w", encoding="utf-8").write("".join(h))
    print("已写出", p, "%.0f KB" % (os.path.getsize(p) / 1024))
    print("203 点位折煤 P10/P50/P90 = %.1f / %.1f / %.1f 万吨（两年）"
          % (stat("coal", mc["all"], .10), stat("coal", mc["all"], .50),
             stat("coal", mc["all"], .90)))


if __name__ == "__main__":
    main()
