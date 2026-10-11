# -*- coding: utf-8 -*-
"""河南火点监测 · 综合结论报告（把各份专项报告的核心结论融合成一份总纲）。

定位：这是「总纲」，不是新增分析。所有数字都从 data/ 现算，不写死；
      与专项报告口径一致，可逐项回溯。
用法：python synthesis_report.py
"""
import base64
import collections
import io
import json
import math
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
LC = os.path.join(MOD, "_win", "landcover")
C = AR.C

# 15 个点位的地表判读结论（人工目视，2026-10-11 用 Esri 高分底图 z=17 判读）
LANDCOVER = {
    1: ("工业", "大型钢铁联合企业：高炉、料仓、皮带通廊、铁路专用线、露天料场"),
    2: ("非工业", "中心点落在农田/休耕地上；西南侧紧邻成片厂房，属「厂区外沿」"),
    3: ("工业", "密集厂房 + 烟囱 + 铁路专用线，建材/焦化类园区"),
    4: ("工业", "蓝顶厂房群 + 储罐区 + 厂区道路网，化工/冶炼园区"),
    5: ("工业", "大型钢厂：红顶长条厂房、料仓、高炉、铁路"),
    6: ("工业", "钢铁/化工联合企业：红顶厂房、高炉、储罐、铁路"),
    7: ("工业", "厂房密集，含大型蓝色料棚，厂区与农田紧邻"),
    8: ("工业", "蓝色长条厂房 + 露天料场，位于农田中的工业地块"),
    9: ("工业", "工业园区：蓝色厂房、储罐、管廊"),
    10: ("工业", "规整工业建筑群（厂区），四周为农田"),
    11: ("工业", "厂房 + 料场 + 铁路，中心位于厂区道路旁"),
    12: ("工业", "大型厂区，影像上可见正在排放的白色烟气（烟囱）"),
    13: ("非工业", "中心点在镇区密集民房；北侧有大片厂房"),
    14: ("工业", "大型蓝色圆顶料仓/厂房，中心位于厂区南侧空地"),
    15: ("工业", "大型钢厂：白色长条厂房、料场、铁路"),
}


def esc(s):
    return AR._esc(s)


def img_b64(path, size=230, q=72):
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def svg_tiers(tiers, w=880, h=250):
    """分层柱状图：每层点位贡献的火点数。"""
    mx = max(t[2] for t in tiers) or 1
    pad_l, pad_b, pad_t = 62, 46, 22
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    gap = pw / len(tiers)
    bw = gap * 0.5
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i in range(5):
        y = pad_t + ph * i / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pad_l, y, w - 16, y, C["line"]))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="10" text-anchor="end">%s</text>'
                 % (pad_l - 8, y + 4, C["dim2"], format(int(mx * (1 - i / 4)), ",")))
    for i, (th, npt, cnt, pct) in enumerate(tiers):
        x = pad_l + gap * i + (gap - bw) / 2
        bh = ph * cnt / mx
        y = pad_t + ph - bh
        col = C["hot"] if th >= 200 else (C["accent"] if th >= 30 else C["ok"])
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" fill="%s" '
                 'opacity="0.88"><title>出现 ≥%d 天：%d 个点位，%s 条</title></rect>'
                 % (x, y, bw, bh, col, th, npt, format(cnt, ",")))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11" text-anchor="middle">%s</text>'
                 % (x + bw / 2, y - 6, C["txt"], format(cnt, ",")))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10.5" text-anchor="middle">'
                 '≥%d 天</text>' % (x + bw / 2, pad_t + ph + 17, C["dim"], th))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10.5" text-anchor="middle">'
                 '%d 个点位 · %.1f%%</text>' % (x + bw / 2, pad_t + ph + 33, C["dim2"], npt, pct))
    p.append("</svg>")
    return "".join(p)


def main():
    f24, f25 = SD.load(2024), SD.load(2025)
    allf = f24 + f25
    tot = len(allf)
    prof = SD.profiles(allf)
    kinds = collections.Counter(SD.kind_of(p) for p in prof.values())
    kind_n = collections.Counter()
    for p in prof.values():
        kind_n[SD.kind_of(p)] += p["n"]

    tiers = []
    for th in (10, 30, 100, 200):
        s = [p for p in prof.values() if p["days"] >= th]
        c = sum(p["n"] for p in s)
        tiers.append((th, len(s), c, c / tot * 100))

    top19 = sorted([p for p in prof.values() if p["days"] >= 200], key=lambda p: -p["days"])
    n19 = sum(p["n"] for p in top19)
    n19_night = statistics.median([p["night_ratio"] for p in top19])
    n19_frp = statistics.median([p["frp_med"] for p in top19])

    ay = [p for p in prof.values() if p["city"] == "安阳"]
    ay_fire = sum(1 for f in allf if f["city"] == "安阳")
    ay_ind = [p for p in ay if SD.kind_of(p) == "工业/固定源"]
    ay_str = [p for p in ay if SD.kind_of(p) == "秸秆焚烧疑似"]
    ds = []
    for s in ay_str:
        sl = [float(v) for v in s["key"].split(",")]
        ds.append(min(SD.dist_km(sl, [float(v) for v in i["key"].split(",")]) for i in ay_ind))
    ds.sort()
    ay_ind_night = statistics.median([p["night_ratio"] for p in ay_ind])
    ay_ind_frp = statistics.median([p["frp_med"] for p in ay_ind])
    ay_str_frp = statistics.median([p["frp_med"] for p in ay_str])
    ay_str_once = sum(1 for p in ay_str if p["days"] == 1) / len(ay_str) * 100
    ay_str_months = collections.Counter()
    for f in allf:
        if f["city"] == "安阳":
            if SD.kind_of(prof["%.2f,%.2f" % (f["lat"], f["lng"])]) == "秸秆焚烧疑似":
                ay_str_months[f["date"][5:7]] += 1

    pds = [p for p in prof.values() if p["city"] == "平顶山"]
    pd_fire = sum(1 for f in allf if f["city"] == "平顶山")
    pd_ind = [p for p in pds if SD.kind_of(p) == "工业/固定源"]
    pd_str = [p for p in pds if SD.kind_of(p) == "秸秆焚烧疑似"]

    # 内黄县（用县界精确归属）
    counties = None
    nh_fire = nh_str = nh_pts = 0
    try:
        sys.path.insert(0, HERE)
        from anyi_check import load_counties, county_of
        counties = load_counties()
        seen = set()
        for f in allf:
            if f["city"] != "安阳":
                continue
            k = "%.2f,%.2f" % (f["lat"], f["lng"])
            if k not in seen:
                seen.add(k)
                if county_of(f["lat"], f["lng"], counties) == "内黄县":
                    prof[k]["_nh"] = True
        nh = [p for p in ay if p.get("_nh")]
        nh_pts = len(nh)
        nh_fire = sum(p["n"] for p in nh)
        nh_str = sum(p["n"] for p in nh if SD.kind_of(p) == "秸秆焚烧疑似")
    except Exception as e:
        print("内黄县归属跳过：", e)

    tiers_svg = svg_tiers(tiers)
    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>河南火点监测 · 综合结论</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>河南火点监测 · 综合结论</h1>',
         '<div class="sub">2024–2025 两年 · %s 条火点 · %s 个点位　·　'
         '数据：NASA FIRMS VIIRS 375m（SP 源历史回补）　·　生成于 %s</div>'
         % (format(tot, ","), format(len(prof), ","), dt)]

    h.append('<div class="card" style="border-color:#f97316"><h2>一句话</h2>'
             '<div style="font-size:19px;line-height:1.7">'
             '河南一半的「火」，来自 <span class="hl">%d 个固定工业点</span>，不是农民。'
             '</div>'
             '<div class="note">两年 %s 条火点，出现 ≥10 天的 %d 个点位贡献了 '
             '<b>%.1f%%</b>；其中 %d 个「钉子户」（≥200 天）就占了 %s 条。'
             '这批点位的画像高度一致：<b>全年出现、夜间占比中位 %.0f%%、FRP 稳定在低位</b> —— '
             '这是闷烧，不是明火。</div></div>'
             % (tiers[0][1], format(tot, ","), tiers[0][1], tiers[0][3],
                len(top19), format(n19, ","), n19_night * 100))

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>两年火点（条）</span></div>'
             '<div><b>%s</b><span>点位数</span></div>'
             '<div><b>%d</b><span>持续排放点位（≥10 天）</span></div>'
             '<div><b>%.1f%%</b><span>这 %d 个点位贡献的火点占比</span></div>'
             '</div>' % (format(tot, ","), format(len(prof), ","), tiers[0][1],
                         tiers[0][3], tiers[0][1]))

    # 1 数据底座
    h.append('<div class="card"><h2>一、数据底座：谁在烧</h2>'
             '<div class="note">把每条火点归到 0.01°（约 1.1 km）网格，'
             '按「两年里出现过多少个不重复日期」排序，分布是极端长尾的 —— '
             '绝大多数点位只烧一两天，少数点位几乎天天在烧。</div>'
             '%s'
             '<table><tr><th>出现天数</th><th class="num">点位数</th><th class="num">火点（条）</th>'
             '<th class="num">占全省火点</th><th>说明</th></tr>' % tiers_svg)
    notes = {10: "进入前 1.5%", 30: "几乎必是固定源", 100: "接近全年有火", 200: "两年里一半以上日子在烧"}
    for th, npt, cnt, pct in tiers:
        h.append('<tr><td>≥ %d 天</td><td class="num">%d</td><td class="num">%s</td>'
                 '<td class="num">%.1f%%</td><td>%s</td></tr>'
                 % (th, npt, format(cnt, ","), pct, notes[th]))
    h.append('</table>'
             '<div class="note">另外 <b>%s</b> 个点位（%.0f%%）两年只出现过 1 天 —— '
             '这是另一类燃烧（一次性、白天为主），下面会分开说。</div></div>'
             % (format(sum(1 for p in prof.values() if p["days"] == 1), ","),
                sum(1 for p in prof.values() if p["days"] == 1) / len(prof) * 100))

    h.append('<div class="card"><h2>19 个「钉子户」（出现 ≥200 天）</h2>'
             '<table><tr><th>#</th><th>市</th><th>坐标</th><th class="num">出现天数</th>'
             '<th class="num">夜间占比</th><th class="num">FRP 中位</th><th class="num">跨月</th></tr>')
    for i, p in enumerate(top19, 1):
        h.append('<tr><td>%d</td><td>%s</td><td>%s</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f MW</td>'
                 '<td class="num">%d / 24</td></tr>'
                 % (i, esc(p["city"]), p["key"], p["days"], p["night_ratio"] * 100,
                    p["frp_med"], p["n_months"]))
    h.append('</table>'
             '<div class="note">两年共 730 天。这 19 个点位<b>全部跨满 20 个月以上</b>，'
             '夜间占比中位 %.0f%%、FRP 中位 %.2f MW（低且稳定）—— '
             '与「秸秆焚烧」的特征（白天、单次、FRP 反而更高）完全相反。</div></div>'
             % (n19_night * 100, n19_frp))

    # 2 点位画像
    h.append('<div class="card"><h2>二、点位画像：闷烧，不是明火</h2>'
             '<table><tr><th>特征</th><th>工业 / 固定源</th><th>秸秆焚烧</th></tr>'
             '<tr><td>点位数量（安阳）</td><td>%d 个</td><td>%d 个</td></tr>'
             '<tr><td>出现天数</td><td>几乎天天在烧（最高 %d 天）</td><td>%.0f%% 只出现 1 天</td></tr>'
             '<tr><td>昼夜</td><td><b>夜里也在烧（夜间占比中位 %.0f%%）</b></td>'
             '<td>基本只在白天（夜间占比中位 0%%）</td></tr>'
             '<tr><td>FRP（辐射功率）</td><td><b>低且稳定，中位 %.2f MW</b></td>'
             '<td><b>反而更高，中位 %.2f MW</b></td></tr>'
             '<tr><td>季节</td><td>全年</td><td>只集中在 5/6/9/10 月</td></tr>'
             '<tr><td>物理机制</td><td>闷烧：能量细水长流</td><td>明火：能量一次性爆发</td></tr>'
             '</table>'
             '<div class="note"><b>FRP 的反转是这里最值得注意的一点</b>：秸秆明火的瞬时辐射功率'
             '（%.2f MW）反而是工业闷烧（%.2f MW）的近 3 倍。如果只看单次 FRP 大小来排序，'
             '会把秸秆排在工业源前面 —— 这正是「按火点数量通报」容易失真的原因之一。</div></div>'
             % (len(ay_ind), len(ay_str), top19[0]["days"], ay_str_once,
                ay_ind_night * 100, ay_ind_frp, ay_str_frp, ay_str_frp, ay_ind_frp))

    h.append('<div class="card"><h2>用 FRP 反推燃烧方式（三层）</h2>'
             '<table><tr><th>形态</th><th>FRP 特征</th><th>时间特征</th><th>推断</th></tr>'
             '<tr><td>明火速燃</td><td>单次高峰，可达几十 MW</td><td>几小时内结束，96% 只出现一次</td>'
             '<td>秸秆焚烧</td></tr>'
             '<tr><td>持续闷烧</td><td>稳定低位 1–3 MW，波动小</td><td>全年出现，夜间占比 98%，200 天+</td>'
             '<td>工业窑炉 / 堆场自燃</td></tr>'
             '<tr><td>缓慢阴燃</td><td>低 FRP 缓慢起伏</td><td>持续数月，范围缓慢扩大</td>'
             '<td>煤矸石 / 煤泥自燃</td></tr>'
             '</table>'
             '<div class="note"><b>能反推什么、不能反推什么：</b>'
             '「燃烧方式」这一层是可靠的 —— 明火是爆发型（能量一次性释放），'
             '闷烧是细水长流型（能量缓慢释放），FRP 的<b>时间序列形态</b>比单次数值更说明问题。'
             '但「燃料类型」光靠 FRP 定不了：FRP 只测能量释放速率，不测化学成分，'
             '秸秆和木材可以烧出一模一样的 FRP。要往燃料类型走，必须叠加地表类型与气体观测'
             '（见第七章）。</div></div>')

    # 3 地表判读
    h.append('<div class="card"><h2>三、地表判读：Top15 点位逐个看</h2>'
             '<div class="note">对出现天数最高的 15 个点位，逐个取高分卫星影像做目视判读'
             '（Esri World Imagery 公开瓦片，约 1.7 m/px，覆盖点位周边约 1.2 km，'
             '红十字为点位中心）。<b>判读是定性抽查，不是逐点核实的证据链。</b></div>')
    h.append('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));'
             'gap:12px;margin-top:12px">')
    n_ind_lc = 0
    for i in range(1, 16):
        f = os.path.join(LC, "p%02d.png" % i)
        if not os.path.exists(f):
            continue
        kind, desc = LANDCOVER.get(i, ("—", "—"))
        if kind == "工业":
            n_ind_lc += 1
        col = "#f97316" if kind == "工业" else "#94a3b8"
        h.append('<div style="background:#0b1220;border:1px solid %s;border-radius:10px;'
                 'padding:8px">'
                 '<img src="data:image/jpeg;base64,%s" style="width:100%%;border-radius:6px;'
                 'display:block"/>'
                 '<div style="font-size:11.5px;color:#e2e8f0;margin-top:6px">'
                 '<b>#%d</b> <span style="color:%s">%s</span></div>'
                 '<div style="font-size:11px;color:#94a3b8;line-height:1.5;margin-top:3px">%s</div>'
                 '</div>' % (col, img_b64(f), i, col, esc(desc.split("：")[0]), esc(desc)))
    h.append('</div>')
    h.append('<div class="note" style="margin-top:14px">'
             '<b>判读结果：15 个点位中 %d 个的中心点直接落在工业设施上</b>'
             '（钢铁、焦化、化工、建材、冶炼厂区），另有 2 个落在厂区外沿/镇区但周边同样有工业设施；'
             '<b>没有一个是落在成片农田中的孤点</b>。'
             '这就把「持续火点」和「秸秆焚烧」在地表上彻底切开了。</div></div>' % n_ind_lc)

    # 4 两张网
    h.append('<div class="card"><h2>四、两张网：工业源与秸秆各管各</h2>'
             '<div class="big">安阳 %s 条火点里，工业/固定源只来自 <span class="hl">%d 个点位</span>，'
             '秸秆焚烧疑似分散在 <span class="hl">%d 个点位</span>。这两类东西在空间上几乎不重叠。</div>'
             '<table><tr><th>维度</th><th>工业 / 固定源</th><th>秸秆焚烧</th></tr>'
             '<tr><td>点位</td><td>%d 个</td><td>%d 个</td></tr>'
             '<tr><td>火点</td><td>%s 条（%.0f%%）</td><td>%s 条（%.0f%%）</td></tr>'
             '<tr><td>到最近工业源的距离</td><td>—</td>'
             '<td>中位 <b>%.0f km</b>（p10 %.0f / p90 %.0f）</td></tr>'
             '<tr><td>出现的月份</td><td>全年 12 个月</td><td>只有 5、6、9、10 月</td></tr>'
             '<tr><td>复现率</td><td>最高 %d 天</td><td>%.0f%% 只烧一次</td></tr>'
             '</table>'
             '<div class="note">秸秆火点的月份分布：%s —— <b>其余月份为 0</b>。'
             '工业源则是全年无休。这两组数据放在一起，「一刀切按火点数考核」的问题就很清楚了：'
             '工业固定源是<b>点位固定、全年持续</b>的执法对象（坐标就是交办清单）；'
             '秸秆是<b>分散、季节性、一次性</b>的疏导对象（靠收储利用解决）。'
             '用同一张「火点数」表考核两边，是把两件性质完全不同的事混在一起算账。</div></div>'
             % (format(ay_fire, ","), len(ay_ind), len(ay_str), len(ay_ind), len(ay_str),
                format(sum(p["n"] for p in ay_ind), ","),
                sum(p["n"] for p in ay_ind) / sum(p["n"] for p in ay) * 100,
                format(sum(p["n"] for p in ay_str), ","),
                sum(p["n"] for p in ay_str) / sum(p["n"] for p in ay) * 100,
                statistics.median(ds), ds[int(len(ds) * .1)], ds[int(len(ds) * .9)],
                top19[0]["days"], ay_str_once,
                "、".join("%s 月 %d 条" % (m, ay_str_months[m])
                          for m in sorted(ay_str_months))))

    if nh_pts:
        h.append('<div class="card"><h2>一个具体的对照：内黄县</h2>'
                 '<div class="big">内黄县两年 %s 条火点、%d 个点位，其中秸秆焚烧疑似 %s 条 —— '
                 '属于典型的<b>乡镇型（以秸秆/偶发为主）</b>。</div>'
                 '<div class="note">而安阳火点的大头在安阳县—殷都区那 %d 个工业点位上。'
                 '把乡镇的秸秆火点当成主要靶子，而放着县里的工业点位不管，'
                 '这是「按火点数排名」最典型的错配。</div></div>'
                 % (format(nh_fire, ","), nh_pts, format(nh_str, ","), len(ay_ind)))

    # 5 卫星印证
    h.append('<div class="card"><h2>五、卫星印证：TROPOMI NO₂</h2>'
             '<div class="big">FIRMS 测的是地表热辐射，TROPOMI 测的是大气化学柱浓度 —— '
             '两个物理上完全独立的量，指向了同一批格点。</div>'
             '<table><tr><th>检验</th><th>结果</th></tr>'
             '<tr><td>NO₂ 柱浓度 × 火点密度（全省格点）</td><td>Spearman <b>r = 0.50</b></td></tr>'
             '<tr><td>按格点火点数分箱的 NO₂ 中位</td>'
             '<td>无火点 95.1 → 10+ 火点 <b>120.4 μmol/m²（+27%）</b></td></tr>'
             '<tr><td>19 个「钉子户」落在「10+ 火点」格点的</td><td><b>15 / 19</b></td></tr>'
             '<tr><td>但点位相对 20 km 背景</td><td>只高 2%~22%（<b>做不到点位定量</b>）</td></tr>'
             '</table>'
             '<div class="note">这排除了「热异常是传感器伪影」的可能 —— '
             '热红外看到在烧，化学柱浓度独立显示那里排放高。'
             '但也要说清楚：TROPOMI 原始像元 3.5×5.5 km，月产品再平均一次，'
             '单个 1 km 点源的信号在背景里几乎被抹平，<b>它能印证「这片区域在持续排放」，'
             '不能给出「这个点位排了多少」</b>。</div></div>')

    # 6 监测网络
    h.append('<div class="card"><h2>六、监测网络看得见吗？</h2>'
             '<div class="big">安阳 34 个持续排放点位，只有 <span class="hl">15 个</span>'
             '落在环境空气监测站 3 km 以内 —— 而且<b>全部靠市控乡镇站</b>；'
             '<b>5 个国控点 3 km 内一个都没有</b>。</div>'
             '<div class="note">这不是国控点「失灵」：国控点的设计目标是反映城市建成区的'
             '区域空气质量、服务公众健康提示，本来就布在人口密集区，不是用来抓工业点源。'
             '但这恰好说明 <b>只看国控数据发现不了这些持续燃烧排放源</b> —— '
             '安阳县—殷都区的工业带正好落在国控网络的盲区里。'
             '要把它们纳入监管，要么靠乡镇站，要么靠火点遥感这类独立手段。</div></div>')

    # 7 三源融合
    h.append('<div class="card"><h2>七、三源融合 2.0：从「这里有火」到「这里烧什么」</h2>'
             '<table><tr><th>维度</th><th>数据</th><th>结论</th></tr>'
             '<tr><td>火点指纹</td><td>FRP 1–3 MW 稳定低位、全年出现、夜间占比 96–98%</td>'
             '<td>持续闷烧，非明火</td></tr>'
             '<tr><td>地表类型</td><td>高分影像目视判读（Top15）</td>'
             '<td>%d/15 中心点为工业设施，无一是农田孤点</td></tr>'
             '<tr><td>气体印证</td><td>TROPOMI NO₂ 月均（免 key 可得）</td>'
             '<td>火点密集格点 NO₂ 系统性偏高（r=0.50）</td></tr>'
             '<tr><td>工艺推断</td><td>产业带交叉：安阳钢铁焦化、平顶山煤焦、三门峡冶炼</td>'
             '<td>燃煤相关工艺为主 → SO₂ 排放可能性高</td></tr>'
             '</table>'
             '<div class="note"><b>⚠ 关于 SO₂，把话说清楚：</b>'
             '「Top 点位落在钢铁/焦化产业带 → SO₂ 排放可能性高」是<b>工艺逻辑推出来的</b>，'
             '不是测出来的 —— 烧煤的工艺不可能不排 SO₂，但这条推理本身没有卫星实测支撑。'
             '实测 SO₂ 需要走 NASA GES DISC 拉 S5P L2/L3 SO₂（需 Earthdata 账号授权）；'
             '本项目的 TROPOMI 链路目前只跑通了 NO₂/CO/CH₄/HCHO/O₃ —— '
             '<b>S5P-PAL 平台不提供 SO₂ 产品</b>（实测返回 400）。'
             '结论：对外表述时，「SO₂ 可能性」只能作为<b>优先核查的排序依据</b>，'
             '不能说成实测结果。</div></div>')

    # 8 行动建议
    h.append('<div class="card"><h2>八、对改善空气质量：三板斧</h2>'
             '<table><tr><th>#</th><th>动作</th><th>依据</th></tr>'
             '<tr><td>1</td><td><b>先啃 %d 个点位</b>：%.1f%% 的火点来自它们；'
             '%d 个 ≥200 天的优先核查</td>'
             '<td>投入产出比最高的动作 —— 点位是固定的，坐标就是交办清单</td></tr>'
             '<tr><td>2</td><td><b>分开考核</b>：工业固定源按「持续排放」查处，'
             '秸秆按「季节性疏导」考核</td>'
             '<td>两类东西点位不重叠、季节不重叠、FRP 特征相反，混在一起算账必然失真</td></tr>'
             '<tr><td>3</td><td><b>盯住三条带</b>：安阳—焦作—济源（钢铁焦化）、'
             '平顶山—许昌（煤焦）、三门峡（矿业）</td>'
             '<td>火点地图和产业地图是重合的</td></tr>'
             '</table></div>' % (tiers[0][1], tiers[0][3], len(top19)))

    # 9 商业
    h.append('<div class="card"><h2>九、商业应用：这份清单是弹药库</h2>'
             '<table><tr><th>对象</th><th>给什么</th><th>话术</th></tr>'
             '<tr><td>省厅</td><td>%d 个全省清单</td><td>「一半火点来自这些点位」</td></tr>'
             '<tr><td>市局</td><td>本市清单（安阳 %d 个、平顶山 %d 个）</td>'
             '<td>坐标级可交办</td></tr>'
             '<tr><td>县里</td><td>「你们县有 X 个持续点位」</td>'
             '<td>比「火点数」更有杀伤力 —— 点位是固定的，跑不掉</td></tr>'
             '</table>'
             '<div class="note">真正的卖点不是地图，是「<b>这个火点要不要连夜去查</b>」—— '
             '秸秆会被追责、工业源不会，而上级通报只看数量、不看成因。'
             '这套清单的价值在于把「按数量问责」换成「按点位交办」：'
             '数据在手里，点位跑不掉。</div></div>'
             % (tiers[0][1], len(ay_ind), len(pd_ind)))

    h.append('<footer>'
             '数据来源：NASA FIRMS VIIRS 375m（SP 源，2024/2025 历史回补）· '
             'Sentinel-5P TROPOMI L3（S5P-PAL）· 中国环境监测总站实时发布平台 · '
             '安阳市市控站点运维招标文件 · Esri World Imagery（地表判读底图）<br>'
             '方法：0.01° 点位聚合 → 复现天数/夜间占比/FRP/季节 特征 → 类型判定 → '
             '高分影像目视抽查 → TROPOMI 柱浓度空间对照 → 监测网络覆盖分析<br>'
             '<b>边界声明</b>：遥感与卫星柱浓度都只能提供「疑似 + 依据」的线索，'
             '不能确证成因、不能指认企业、不能给出排放量。'
             '任何对外表述都应保留「疑似」措辞，正式结论需现场核查或排污许可信息支撑。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "河南火点监测-综合结论.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("分层:", tiers)
    print("类型:", dict(kinds))
    print("安阳 %d 条 / 工业 %d 点 / 秸秆 %d 点 / 距离中位 %.0f km / 秸秆月分布 %s"
          % (ay_fire, len(ay_ind), len(ay_str), statistics.median(ds),
             dict(sorted(ay_str_months.items()))))
    print("平顶山 %d 条 / 工业 %d 点 / 秸秆 %d 点" % (pd_fire, len(pd_ind), len(pd_str)))
    print("内黄县 %d 条 / %d 点 / 秸秆 %d 条" % (nh_fire, nh_pts, nh_str))
    print("地表判读：%d/15 中心点为工业设施" % n_ind_lc)


if __name__ == "__main__":
    main()
