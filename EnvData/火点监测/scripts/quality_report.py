# -*- coding: utf-8 -*-
"""《火点数据的可信度边界》报告生成器。

把这一轮挖出的三个方法学问题固化下来：
  1. 观测盲区：19.7% 的日子全省探测数骤降（云遮挡），「没探测到」≠「没在烧」
  2. 仪器差异：MODIS(1km, 下限 5.6MW) 与 VIIRS(375m, 下限 0.6MW) 看到两种火
  3. 新判别器：周节律（工业 0.90 vs 秸秆 0.49）

数据：data/quality-report.json、data/modis/*.json、data/history/*.json
用法：python quality_report.py
"""
import collections
import datetime as dt
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
WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def esc(s):
    return AR._esc(s)


def svg_daily(day, lows, w=880, h=260, pad_l=48, pad_b=40, pad_t=18):
    """每日探测数序列，低探测日标红。"""
    ds = sorted(day)
    vals = [day[d] for d in ds]
    mx = max(vals) or 1
    pw, ph = w - pad_l - 16, h - pad_b - pad_t
    bw = pw / len(ds)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for i, d in enumerate(ds):
        bh = ph * vals[i] / mx
        col = "#ef4444" if d in lows else "#38bdf8"
        p.append('<rect x="%.2f" y="%.1f" width="%.2f" height="%.1f" fill="%s" '
                 'fill-opacity="0.9"/>' % (pad_l + i * bw, pad_t + ph - bh,
                                           max(bw * 0.9, 0.5), max(bh, 0.4), col))
    p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.2"/>'
             % (pad_l, pad_t + ph, w - 16, pad_t + ph, LINE))
    for frac, lab in ((0, "0"), (0.5, str(round(mx / 2))), (1, str(mx))):
        y = pad_t + ph - ph * frac
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="11" text-anchor="end">%s</text>'
                 % (pad_l - 6, y + 4, DIM, lab))
    for yr in ("2024", "2025"):
        idx = next((i for i, d in enumerate(ds) if d.startswith(yr + "-01")), None)
        if idx is None:
            continue
        x = pad_l + idx * bw
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                 'stroke-width="1" stroke-dasharray="3 3"/>' % (x, pad_t, x, pad_t + ph, LINE))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="11">%s</text>'
                 % (x + 4, pad_t + 12, DIM, yr))
    p.append('<text x="%d" y="%d" fill="#ef4444" font-size="12" text-anchor="end">'
             '红色 = 低探测日（观测盲区）</text>' % (w - 20, h - 12))
    p.append('</svg>')
    return "".join(p)


def svg_frp2(modis_frp, viirs_frp, w=880, h=270, pad_l=54, pad_b=44, pad_t=20):
    """MODIS 与 VIIRS 的 FRP 分布对比（对数分箱）。"""
    edges = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 1e9)]
    labs = ["<1", "1-2", "2-3", "3-5", "5-10", "10-20", "20+"]

    def hist(a):
        n = len(a) or 1
        return [sum(1 for v in a if lo <= v < hi) / n * 100 for lo, hi in edges]

    a, b = hist(modis_frp), hist(viirs_frp)
    mx = max(max(a), max(b)) or 1
    pw, ph = w - pad_l - 20, h - pad_b - pad_t
    bw = pw / len(edges)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for k in range(5):
        y = pad_t + ph - ph * k / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                 % (pad_l, y, w - 20, y, LINE))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="11" text-anchor="end">%.0f%%</text>'
                 % (pad_l - 8, y + 4, DIM, mx * k / 4))
    for i, (lab, va, vb) in enumerate(zip(labs, a, b)):
        x0 = pad_l + i * bw
        for j, (v, col) in enumerate(((va, "#f97316"), (vb, "#38bdf8"))):
            bh = ph * v / mx
            p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2"/>'
                     % (x0 + bw * 0.16 + j * bw * 0.34, pad_t + ph - bh, bw * 0.30,
                        max(bh, 0.6), col))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="12" text-anchor="middle">%s</text>'
                 % (x0 + bw / 2, h - pad_b + 20, DIM, lab))
    p.append('<text x="%d" y="%d" fill="%s" font-size="12" text-anchor="middle">'
             'FRP（MW）</text>' % (w // 2, h - 10, DIM))
    p.append('</svg>')
    return "".join(p)


def svg_week(rows, w=880, h=250, pad_l=54, pad_b=40, pad_t=18):
    """周节律：三组 × 7 天。"""
    mx = max(max(r["vals"]) for r in rows) or 1
    pw, ph = w - pad_l - 20, h - pad_b - pad_t
    gw = pw / 7
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<rect width="%d" height="%d" fill="%s" rx="10"/>' % (w, h, PANEL))
    for k in range(4):
        y = pad_t + ph - ph * k / 3
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                 % (pad_l, y, w - 20, y, LINE))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="11" text-anchor="end">%.0f</text>'
                 % (pad_l - 8, y + 4, DIM, mx * k / 3))
    for i, wd in enumerate(WD):
        x0 = pad_l + i * gw
        for j, r in enumerate(rows):
            bh = ph * r["vals"][i] / mx
            p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2"/>'
                     % (x0 + gw * 0.18 + j * gw * 0.25, pad_t + ph - bh, gw * 0.22,
                        max(bh, 0.6), r["col"]))
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="12" text-anchor="middle">%s</text>'
                 % (x0 + gw / 2, h - pad_b + 20, DIM, wd))
    p.append('</svg>')
    return "".join(p)


def main():
    q = json.load(open(os.path.join(MOD, "data", "quality-report.json"), encoding="utf-8"))
    fires = SD.load(2024) + SD.load(2025)
    day = collections.Counter(f["date"] for f in fires)
    lows = set(q["cloud"]["days"] if "days" in q["cloud"] else [])
    if not lows:
        cc = json.load(open(os.path.join(MOD, "data", "cloud-correction.json"), encoding="utf-8"))
        lows = set(cc["days"])

    mod = []
    for y in (2024, 2025):
        p = os.path.join(MOD, "data", "modis", "henan-%d.json" % y)
        if os.path.exists(p):
            mod += json.load(open(p, encoding="utf-8"))
    modis_frp = [m["frp"] for m in mod if m["frp"] > 0]
    viirs_frp = [f["frp"] for f in fires if f["frp"] > 0]

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    css = (AR.CSS.replace("__BG__", BG).replace("__PANEL__", PANEL).replace("__TXT__", TXT)
           .replace("__DIM__", DIM).replace("__LINE__", LINE).replace("__ACC__", C["accent"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>火点数据的可信度边界</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(), '<div class="wrap">',
         '<h1>火点数据的可信度边界</h1>',
         '<div class="sub">观测盲区 · 仪器差异 · 新判别器 ｜ 河南 2024–2025（45,540 条火点）'
         ' ｜ 生成于 %s</div>' % now]

    h.append('<div class="card" style="border-color:#f97316"><h2>一句话结论</h2>'
             '<div style="font-size:18px;line-height:1.8">'
             '这套数据的结论都建立在「卫星看到什么」之上，而它有三条边界：'
             '<span class="hl">19.7% 的日子是观测盲区</span>、'
             '<span class="hl">1 km 分辨率的仪器看不到 1 MW 的火</span>、'
             '但<b>周节律意外给出了一个免费的判别器</b>。'
             '</div>'
             '<div class="note">下面把三条边界逐个量化，并列出它们分别影响哪些既有结论。'
             '写这份报告的动机是：<b>先说清数据能撑到什么程度，再谈结论</b>。</div></div>')

    # 一、观测盲区
    n_low, n_days, pct = q["cloud"]["n_low"], q["cloud"]["n_days"], q["cloud"]["pct"]
    h.append('<div class="card" style="border-color:#ef4444"><h2>一、观测盲区：%d 天里 %d 天卫星是「瞎」的</h2>'
             '<div class="big">最初想用「春节工厂放假」验证这些火点能不能停，结果发现：'
             '2025-01-30/31、02-01 全省只有 <span class="hl">5 / 3 / 1</span> 条火点。'
             '</div>' % (n_days, n_low))
    h.append('<div class="note">用六省数据一验就清楚了 —— <b>同期河北 9/3/8、山西 7/18/11、'
             '山东 26/0/7、天津 0/0/0</b>。天气是区域性的，管控是省内的，'
             '<b>六省一起归零只能是天气</b>（大范围云遮挡）。2024-02-20 更是六省全部 0 条。'
             '所以「春节效应」是假象，也说明<b>「当天没探测到」不等于「没在烧」</b>。</div>')
    h.append('<div style="margin-top:14px">%s</div>' % svg_daily(day, lows))
    h.append('<div class="note">把「当日探测数 &lt; 滚动中位 × 30%%」定义为<b>低探测日</b>，'
             '两年共 <b>%d 天（%.1f%%）</b>，全年均匀分布（每月 2–9 天）—— '
             '这不是偶发事件，是常态。</div>' % (n_low, pct))

    h.append('<h3 style="color:%s;font-size:15px;margin:18px 0 6px">'
             '校正后的「出现率」</h3>' % C["accent"])
    h.append('<table><tr><th>点位</th><th class="num">观测天数</th><th class="num">活跃期</th>'
             '<th class="num">盲区天</th><th class="num">有效观测天</th>'
             '<th class="num">出现率</th></tr>')
    for r in q["cloud"]["top"][:6]:
        h.append('<tr><td>%s</td><td class="num">%d</td><td class="num">%d</td>'
                 '<td class="num">%d</td><td class="num">%d</td>'
                 '<td class="num"><b>%.1f%%</b></td></tr>'
                 % (r["key"], r["obs"], r["span"], r["blind"], r["eff"], r["rate"]))
    h.append('</table>'
             '<div class="note">原口径（观测天数 ÷ 730）算出来是 37.7%%，'
             '剔除观测盲区后是 <b>46.5%%</b>，最高点位达 <b>74.7%%</b> —— '
             '也就是说，<b>在能看清的日子里，它四分之三的时间都在烧</b>。</div>'
             '<div class="note">⚠ 但这个代理不纯：只有 <b>%d/%d（%.0f%%）</b>的低探测日'
             '能做到「另两省同步偏低」。极端反例 2024-10-26：河南仅 1 条、河北却有 76 条 ——'
             '河南单独低，可能是本地管控或生产变化，不是天气。'
             '<b>正解是接真实云产品（MODIS MOD35 / ERA5 云量）。</b></div></div>'
             % (q["cloud"]["sync"], n_low, q["cloud"]["sync"] / max(n_low, 1) * 100))

    # 二、仪器差异
    ml = q["modis"]
    h.append('<div class="card" style="border-color:#a78bfa">'
             '<h2>二、仪器差异：两个仪器看到两种火</h2>'
             '<div class="big">原以为可以「多源补盲」—— 加一颗卫星补上 VIIRS 的观测盲区。'
             '<span class="hl">结论是不行</span>，但失败得很值。</div>')
    h.append('<div class="note">MODIS 是 1 km 像元，白天受太阳反射压制，'
             '实测探测下限 <b>%.1f MW</b>（P10），而持续点位的 FRP 中位只有 <b>1.08 MW</b>。'
             '<b>它根本看不见这些火。</b>两年河南 MODIS 只有 4,812 条，是 VIIRS 的 1/9.5。</div>'
             % ml["frp_p10"])
    h.append('<div style="margin-top:14px">%s</div>' % svg_frp2(modis_frp, viirs_frp))
    h.append('<div class="legend"><span><i style="background:#f97316"></i>MODIS（1 km）</span>'
             '<span><i style="background:#38bdf8"></i>VIIRS（375 m）</span></div>')
    h.append('<table style="margin-top:14px"><tr><th>点位类型</th><th class="num">点位数</th>'
             '<th class="num">VIIRS 出现天数</th><th class="num">MODIS 命中</th>'
             '<th class="num">命中率</th><th class="num">FRP 中位</th></tr>')
    order = ["工业/固定源", "偏固定源", "待核实", "其他偶发", "秸秆焚烧疑似"]
    for k in order:
        g = ml["groups"].get(k)
        if not g:
            continue
        h.append('<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td>'
                 '<td class="num">%d</td><td class="num"><b>%.2f%%</b></td>'
                 '<td class="num">%.2f</td></tr>'
                 % (esc(k), g["pts"], format(g["days"], ","), g["hits"], g["rate"], g["frp_med"]))
    h.append('</table>'
             '<div class="note">工业点位的 MODIS 命中率 <b>0.47%</b>，'
             '而其他类型是 2–4% —— <b>低 5–8 倍</b>。'
             '一个灵敏度低 10 倍的仪器几乎看不到它们，'
             '这是「这些火又小又弱」的<b>物理层面佐证</b>，'
             '也再次确认它们不是明火。</div>'
             '<div class="note">两者的「画像」正好互为镜像：'
             '<b>MODIS 看到的</b>是 FRP 中位 <b>10.2 MW</b>、白天占 <b>96%</b> 的强火；'
             '<b>只有 VIIRS 看到的</b>是 FRP 中位 <b>1.08 MW</b>、夜间占 <b>98%</b> 的闷烧。'
             '同一个天空下，两种完全不同的火。</div></div>')

    # 三、周节律
    wk = q["weekday"]
    rows = [dict(vals=wk["hot"]["by_day"], col="#ef4444", lab="持续排放点位"),
            dict(vals=wk["straw"]["by_day"], col="#34d399", lab="秸秆疑似点位"),
            dict(vals=wk["all"]["by_day"], col="#64748b", lab="全省全部")]
    h.append('<div class="card" style="border-color:#34d399"><h2>三、意外收获：周节律是个免费判别器</h2>'
             '<div class="big">工业连续生产不该有周末效应；农户的农事活动会有。'
             '结果差距非常干净。</div>')
    h.append('<div style="margin-top:14px">%s</div>' % svg_week(rows))
    h.append('<div class="legend"><span><i style="background:#ef4444"></i>持续排放点位（%s）</span>'
             '<span><i style="background:#34d399"></i>秸秆疑似点位（%s）</span>'
             '<span><i style="background:#64748b"></i>全省全部（%s）</span></div>'
             % ("周末/工作日 = %.2f" % wk["hot"]["ratio"],
                "%.2f" % wk["straw"]["ratio"], "%.2f" % wk["all"]["ratio"]))
    h.append('<table style="margin-top:14px"><tr><th>对象</th><th class="num">周末 / 工作日</th>'
             '<th>解读</th></tr>'
             '<tr><td>持续排放点位（≥10 天）</td><td class="num"><b>%.2f</b></td>'
             '<td>几乎无差别 → 连续生产</td></tr>'
             '<tr><td>秸秆疑似点位</td><td class="num"><b>%.2f</b></td>'
             '<td>周末减半 → 人为农事节律</td></tr>'
             '<tr><td>河南全省（含 19%% 秸秆）</td><td class="num">%.2f</td>'
             '<td>被秸秆拉低</td></tr>'
             '</table>' % (wk["hot"]["ratio"], wk["straw"]["ratio"], wk["all"]["ratio"]))
    pw = q["prov_weekday"]
    h.append('<div class="note">跨省验证更能说明问题：'
             + "、".join("%s <b>%.2f</b>" % (esc(k), pw[k])
                        for k in ["河北", "山西", "山东"] if k in pw)
             + ' —— <b>精确到 1.00</b>，完全无周末效应。'
             '这三个省的持续点位占比是六省最高的（59–78%），'
             '行为学上再次印证「连续生产的工业源」。</div>'
             '<div class="note">这条可以加进类型判定做<b>第 5 个独立判据</b>'
             '（前四个：FRP、出现天数、夜间占比、季节集中度）。'
             '但改动会影响所有既有报告，需先确认。</div></div>')

    # 四、影响
    h.append('<div class="card"><h2>四、这些边界分别影响哪些既有结论</h2>'
             '<table><tr><th>既有结论</th><th>偏差来源</th><th>修正方向</th></tr>'
             '<tr><td>203 个持续排放点位（≥10 天）</td><td>盲区低估天数</td>'
             '<td>实际可能更多（部分点位被压在阈值以下）</td></tr>'
             '<tr><td>最长连续 59 天</td><td>盲区造成<b>假中断</b></td>'
             '<td>校正后「连续 ≥30 天」从 <b>2 个增至 5 个</b>；'
             '33.80,113.45 由 21 天增至 <b>38 天（+81%）</b></td></tr>'
             '<tr><td>夜间占比 96–98%</td><td>白天探测下限 2–3 MW</td>'
             '<td>实际<b>全天燃烧</b>（排放量已按 24 h 修正）</td></tr>'
             '<tr><td>秸秆占火点 19%</td><td>VIIRS 漏检上午焚烧'
             '（MODIS 上午 10:00 时段有 759 条 VIIRS 无对应）</td>'
             '<td>秸秆量<b>可能被低估</b></td></tr>'
             '<tr><td>排放量 28.9–74.4 万吨</td><td>天数 + 燃烧时长</td>'
             '<td>燃烧时长已修正；<b>天数仍是下界</b></td></tr>'
             '</table>'
             '<div class="note"><b>不受影响的部分</b>：点位坐标、空间分布、'
             '产业带重合、类型之间的相对关系（盲区对所有点位大致一视同仁）。'
             '所以「火点集中在钢铁焦化区」这类<b>相对结论依然成立</b>，'
             '受影响的是<b>绝对量</b>。</div></div>')

    # 五、建议
    h.append('<div class="card" style="border-color:#64748b"><h2>五、使用建议</h2>'
             '<table><tr><th>场景</th><th>能不能用</th></tr>'
             '<tr><td>点位排序、优先核查、责任主体认定</td><td>✅ 可以直接用</td></tr>'
             '<tr><td>空间分布与产业带重合</td><td>✅ 可以直接用</td></tr>'
             '<tr><td>「某点位在某个具体日期在烧」</td>'
             '<td>✅ 可用（观测到就是观测到）</td></tr>'
             '<tr><td>「某点位在某个具体日期<b>没</b>在烧」</td>'
             '<td>❌ 不可用 —— 可能是观测盲区</td></tr>'
             '<tr><td>绝对排放量、总量考核</td>'
             '<td>⚠ 只能给区间（且受辐射效率 η 主导，见《排放量估算》）</td></tr>'
             '<tr><td>跨年比较火点数量</td>'
             '<td>⚠ 需先扣除盲区日，否则年份间不可比</td></tr>'
             '</table>'
             '<div class="note">三条改进路径（按性价比排序）：'
             '① <b>接真实云产品</b>（MODIS MOD35 或 ERA5 云量）替掉「全省探测数」这个粗代理；'
             '② <b>把周节律加进类型判定</b>做交叉验证；'
             '③ 邻域一致性判据（用周边点位的探测情况推断该点位是否被云挡）。</div>'
             '<div class="note">数据与方法均可复现：'
             '<code>cloud_correction.py</code>（盲区）→ '
             '<code>fetch_firms_modis.py</code> + <code>modis_layer.py</code>（仪器分层）→ '
             '<code>build_quality.py</code> → <code>quality_report.py</code>（本报告）。</div></div>')

    h.append('<div class="sub" style="margin-top:26px;text-align:center">'
             '河南火点监测 · 数据可信度边界 ｜ 数据源：NASA FIRMS（VIIRS SNPP/NOAA-20、MODIS）'
             ' ｜ 生成于 %s</div>' % now)
    h.append('</div></body></html>')

    p = os.path.join(OUT, "火点数据可信度边界.html")
    open(p, "w", encoding="utf-8").write("".join(h))
    print("已写出", p, "%.0f KB" % (os.path.getsize(p) / 1024))


if __name__ == "__main__":
    main()
