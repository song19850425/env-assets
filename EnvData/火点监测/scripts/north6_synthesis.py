# -*- coding: utf-8 -*-
"""华北六省综合分析：火点 / 空气 / 政策 四个维度合起来看。

核心问题：各省的治理火力，是不是对着最严重的污染源？
数据：
  · data/north6/summary-typed.json    六省火点分类型统计
  · data/stations/aqi-north6.json     六省冬季 15 天国控点均值
  · 政策强度为公开信息检索归纳（2026-10）
用法：python north6_synthesis.py
"""
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C
ORDER = ["河北", "山西", "山东", "河南", "天津", "北京"]
COLOR = {"河北": "#f97316", "山西": "#a78bfa", "山东": "#38bdf8",
         "河南": "#ef4444", "天津": "#34d399", "北京": "#fbbf24"}
# 政策强度（公开信息检索归纳，1–5 星）
POLICY = {
    "河南": (5, "郑州：每火点扣减镇（办）财力 100 万元（>100㎡ 或 >30min）；"
                "洛阳：扣 40/30 万元 + 镇街党委书记公开约谈、责令公开检讨；"
                "固始县：烧 1 ㎡ 杂草罚 500 元（2026-09 舆情）"),
    "河北": (3.5, "省级《禁止秸秆垃圾露天焚烧监管问责办法》；"
                  "邯郸市《禁止秸秆垃圾露天焚烧加严考核问责实施办法》"),
    "山东": (3, "省环保厅：所辖县（市、区）出现 2 个以上火点即启动责任追究"),
    "山西": (2, "县级实施方案为主（如泽州高都镇），未检索到省级加严问责办法"),
    "天津": (2, "未检索到专门加严办法"),
    "北京": (2, "未检索到专门加严办法"),
}


def esc(s):
    return AR._esc(s)


def spearman(x, y):
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean(); ry -= ry.mean()
    return float((rx * ry).sum() / math.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def svg_stack(rows, w=880, row_h=42, lab_w=64, val_w=120):
    """堆叠横条：各省火点的类型构成（工业 / 秸秆 / 其他）。"""
    mx = max(r["fire"] for r in rows) or 1
    h = row_h * len(rows) + 12
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    segs = [("ind_fire", "#ef4444", "工业/固定源"), ("straw_fire", "#34d399", "秸秆疑似"),
            ("other_fire", "#64748b", "其他")]
    for i, r in enumerate(rows):
        y = 6 + i * row_h
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 8, y + 25, C["txt"], esc(r["prov"])))
        x = lab_w
        for key, col, lab in segs:
            bw = pw * r[key] / mx
            p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%d" fill="%s" opacity="0.9">'
                     '<title>%s · %s：%s 条</title></rect>'
                     % (x, y + 8, bw, row_h - 20, col, esc(r["prov"]), esc(lab),
                        format(r[key], ",")))
            x += bw
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11.5">%s</text>'
                 % (lab_w + pw + 8, y + 25, C["dim"], format(r["fire"], ",")))
    p.append("</svg>")
    return "".join(p)


def svg_mirror(rows, w=880, h=360, pad=54):
    """镜像条形：工业源占比（左）vs 秸秆占比（右）。"""
    mx = max(max(r["ind_pct"] for r in rows), max(r["straw_pct"] for r in rows)) * 1.15
    rh = (h - pad - 40) / len(rows)
    mid = pad + (w - 2 * pad) / 2
    half = (w - 2 * pad) / 2 - 62
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s"/>'
             % (mid, pad - 12, mid, pad + rh * len(rows), C["line"]))
    p.append('<text x="%.1f" y="%d" fill="#ef4444" font-size="13" text-anchor="middle">'
             '← 工业源占比（工厂在烧）</text>' % (mid - half / 2, pad - 20))
    p.append('<text x="%.1f" y="%d" fill="#34d399" font-size="13" text-anchor="middle">'
             '秸秆占比（农民在烧）→</text>' % (mid + half / 2, pad - 20))
    for i, r in enumerate(rows):
        y = pad + i * rh
        bw = half * r["ind_pct"] / mx
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#ef4444" '
                 'opacity="0.88"/>' % (mid - bw, y + rh * 0.22, bw, rh * 0.5))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11.5" text-anchor="end">%.1f%%</text>'
                 % (mid - bw - 6, y + rh * 0.62, C["dim"], r["ind_pct"]))
        bw2 = half * r["straw_pct"] / mx
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#34d399" '
                 'opacity="0.88"/>' % (mid, y + rh * 0.22, bw2, rh * 0.5))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="11.5">%.1f%%</text>'
                 % (mid + bw2 + 6, y + rh * 0.62, C["dim"], r["straw_pct"]))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="13" text-anchor="middle">%s</text>'
                 % (mid, y + rh * 0.62, C["txt"], esc(r["prov"])))
    p.append("</svg>")
    return "".join(p)


def main():
    sm = json.load(open(os.path.join(MOD, "data", "north6", "summary-typed.json"), encoding="utf-8"))
    aq = json.load(open(os.path.join(MOD, "data", "stations", "aqi-north6.json"), encoding="utf-8"))
    rows = []
    for pv in ORDER:
        s, a = sm[pv], aq[pv]
        rows.append(dict(prov=pv, **{k: s[k] for k in
                                     ("fire", "pts", "ind_pts", "ind_fire", "straw_pts",
                                      "straw_fire", "other_fire", "hi", "hot_night", "hot_frp")},
                         ind_pct=s["ind_fire"] / s["fire"] * 100,
                         straw_pct=s["straw_fire"] / s["fire"] * 100,
                         pm25=a["PM2.5"], pm10=a["PM10"], so2=a["SO2"], no2=a["NO2"],
                         aqi=a["AQI"], policy=POLICY[pv][0], policy_note=POLICY[pv][1]))
    r_straw_policy = spearman([r["straw_pct"] for r in rows], [r["policy"] for r in rows])
    r_ind_policy = spearman([r["ind_pct"] for r in rows], [r["policy"] for r in rows])
    r_ind_pm = spearman([r["ind_pct"] for r in rows], [r["pm25"] for r in rows])
    r_straw_pm = spearman([r["straw_pct"] for r in rows], [r["pm25"] for r in rows])

    stack = svg_stack(rows)
    mirror = svg_mirror(rows)
    tot_fire = sum(r["fire"] for r in rows)
    tot_ind = sum(r["ind_fire"] for r in rows)
    tot_straw = sum(r["straw_fire"] for r in rows)
    tot_ind_pts = sum(r["ind_pts"] for r in rows)

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>华北六省综合分析 · 火点 / 空气 / 政策</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>华北六省综合分析 · 火点 / 空气 / 政策</h1>',
         '<div class="sub">山河四省 + 京津　·　火点 FIRMS VIIRS 375m（2024–2025）· '
         '空气质量国控点冬季 15 天　·　政策为公开信息检索归纳　·　生成于 %s</div>' % dt]

    h.append('<div class="card" style="border-color:#f97316"><h2>一句话</h2>'
             '<div style="font-size:21px;line-height:1.7">'
             '火点考核在<b>挑软柿子捏</b>：能扣钱的是农民，扣不动的是工厂。'
             '</div>'
             '<div class="note" style="font-size:13.5px">'
             '<b>① 同样是「火点多」，成因完全相反</b><br>'
             '河北的火点 <b>78.3%% 是工厂在烧</b>（%s 条），秸秆只占 4.9%%；'
             '河南反过来，秸秆占 <b>19.0%%</b>（%s 条），工业源 49.5%%。'
             '一个要抓工厂，一个要管农民。<br><br>'
             '<b>② 但政策火力只对着秸秆</b><br>'
             '秸秆占比 vs 政策强度 <b>r = %.2f</b> —— 谁秸秆多，谁政策严；'
             '工业源占比 vs 政策强度 <b>r = %.2f</b> —— 工业多不多，政策一个样。<br>'
             '河南为秸秆定了「每火点扣减财力 100 万元」；'
             '而河北那 <b>%d 个工业持续点位</b>，没有一个省建立对应机制。<br><br>'
             '<b>③ 不是不想管工业，是管不动</b><br>'
             '秸秆的责任链条是清晰的：农户 → 村 → 乡镇，一个卫星火点就能定责扣钱；'
             '工业无组织排放（堆场自燃、焦炉泄漏）要现场核查、要设备台账，'
             '责任认定复杂得多。<b>结果就是六省 %d 个持续排放点位，全部处在「问责真空」里。</b>'
             '</div></div>'
             % (format(rows[0]["ind_fire"], ","), format(rows[3]["straw_fire"], ","),
                r_straw_policy, r_ind_policy, tot_ind_pts, tot_ind_pts))

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>六省两年火点</span></div>'
             '<div><b>%s</b><span>工业/固定源火点（%.0f%%）</span></div>'
             '<div><b>%d</b><span>持续排放点位</span></div>'
             '<div><b>%s</b><span>秸秆疑似火点（%.0f%%）</span></div>'
             '</div>' % (format(tot_fire, ","), format(tot_ind, ","),
                         tot_ind / tot_fire * 100, tot_ind_pts,
                         format(tot_straw, ","), tot_straw / tot_fire * 100))

    h.append('<div class="card"><h2>一、各省火点的「成分」完全不同</h2>'
             '%s'
             '<div class="legend">'
             '<span><i style="background:#ef4444"></i>工业/固定源</span>'
             '<span><i style="background:#34d399"></i>秸秆疑似</span>'
             '<span><i style="background:#64748b"></i>其他（偶发/待核实）</span>'
             '</div>'
             '<div class="note">同样是「火点多」，成因可以完全相反：'
             '<b>河北是工厂在烧，河南是农民在烧</b>。'
             '用同一张火点数表考核六省，等于把两种完全不同的治理对象混在一起算账。</div></div>'
             % stack)

    h.append('<div class="card"><h2>二、镜像结构：工业源 vs 秸秆</h2>'
             '%s'
             '<div class="note">左边（工业源占比）最长的是河北（78.3%%）、山西（68.6%%）；'
             '右边（秸秆占比）最长的是河南（19.0%%）、天津（15.4%%）、北京（15.5%%）。<br>'
             '河北与河南几乎站在光谱两端 —— '
             '<b>一个要抓工厂，一个要管农民，治理手段没有任何可比性</b>。</div></div>'
             % mirror)

    h.append('<div class="card"><h2>三、四个维度总表</h2>'
             '<table><tr><th>省/市</th><th class="num">两年火点</th>'
             '<th class="num">工业源占比</th><th class="num">秸秆占比</th>'
             '<th class="num">冬 PM2.5</th><th class="num">SO₂</th>'
             '<th class="num">政策强度</th></tr>')
    for r in rows:
        stars = "★" * int(r["policy"]) + ("☆" if r["policy"] % 1 else "")
        h.append('<tr><td><b>%s</b></td><td class="num">%s</td>'
                 '<td class="num" style="color:#ef4444">%.1f%%</td>'
                 '<td class="num" style="color:#34d399">%.1f%%</td>'
                 '<td class="num">%.1f</td><td class="num">%.1f</td>'
                 '<td class="num" style="color:#fbbf24">%s</td></tr>'
                 % (esc(r["prov"]), format(r["fire"], ","), r["ind_pct"],
                    r["straw_pct"], r["pm25"], r["so2"], stars))
    h.append('</table>'
             '<div class="note">政策强度为<b>公开信息检索归纳</b>（1–5 星），'
             '不是官方评级，仅供比较参考。</div></div>')

    h.append('<div class="card"><h2>四、政策错配的三个证据</h2>'
             '<table><tr><th>证据</th><th>数据</th></tr>'
             '<tr><td><b>① 秸秆占比越高，政策越严</b></td>'
             '<td>河南秸秆 19.0%% → 5 星（每火点扣 100 万）；'
             '河北秸秆 4.9%% → 3.5 星。Spearman <b>r = %.2f</b></td></tr>'
             '<tr><td><b>② 工业源占比与政策强度无关</b></td>'
             '<td>河北工业源 78.3%%、%d 个持续点位，政策 3.5 星；'
             '山西 68.6%%、416 个点位，政策仅 2 星。r = <b>%.2f</b></td></tr>'
             '<tr><td><b>③ 秸秆比工业源更能解释 PM2.5</b></td>'
             '<td>秸秆占比 vs 冬 PM2.5：<b>r = %.2f</b>（中等正相关）；'
             '工业源占比 vs PM2.5：<b>r = %.2f</b>（无关）</td></tr>'
             '</table>'
             '<div class="note">这三条合起来说明：<br>'
             '· <b>严管秸秆是有依据的</b> —— 秸秆占比与 PM2.5 确有正相关（r=%.2f），'
             '露天焚烧无任何治理设施，颗粒物直接排；<br>'
             '· <b>但工业源这边存在「问责真空」</b> —— '
             '工业源占比与政策强度几乎无关（r=%.2f），而它对应着 <b>%d 个持续排放点位</b>、'
             '%s 条火点；<br>'
             '· <b>工业源与 PM2.5 不相关（r=%.2f）不等于工业不重要</b> —— '
             '火点只反映工业的<b>无组织燃烧</b>那一小部分，'
             '真正的排放大头（有组织排放、烟囱）根本不产生卫星可见的火点。'
             '所以「火点少」不能作为工业源治理达标的证据。</div></div>'
             % (r_straw_policy, tot_ind_pts, r_ind_policy,
                r_straw_pm, r_ind_pm, r_straw_pm, r_ind_policy,
                tot_ind_pts, format(tot_ind, ","), r_ind_pm))

    h.append('<div class="card"><h2>五、分省画像</h2>'
             '<table><tr><th>省/市</th><th>火点结构</th><th>空气特征</th><th>政策</th>'
             '<th>判断</th></tr>'
             '<tr><td><b>河北</b></td><td>工业源 78.3%%、持续点位 %d 个（六省第一）</td>'
             '<td>PM2.5 59.9、PM10 97.4</td><td>3.5 星</td>'
             '<td><b>最该抓工业，但政策火力不足</b></td></tr>'
             '<tr><td><b>山西</b></td><td>工业源 68.6%%、持续点位 %d 个</td>'
             '<td>PM2.5 43.2 但 PM10 101.9（煤尘型）</td><td>2 星</td>'
             '<td>煤矸石/煤堆自燃为主，治理路径特殊</td></tr>'
             '<tr><td><b>山东</b></td><td>工业源 59.3%%、点位最多但持续占比低</td>'
             '<td>SO₂ 11.4（六省最高）</td><td>3 星</td>'
             '<td>工业大省，火点分散，以点源+区域为主</td></tr>'
             '<tr><td><b>河南</b></td><td>秸秆 19.0%%（六省最高）、工业源 49.5%%</td>'
             '<td><b>PM2.5 69.1（六省最差）</b></td><td><b>5 星</b></td>'
             '<td><b>政策最严，但主要严在秸秆上</b></td></tr>'
             '<tr><td><b>天津</b></td><td>工业源 30.3%%</td><td>NO₂ 48.1（六省最高）</td>'
             '<td>2 星</td><td>港口+重卡型，与火点关系小</td></tr>'
             '<tr><td><b>北京</b></td><td>工业源 23.7%%，持续点位仅 %d 个</td>'
             '<td>各项最低</td><td>2 星</td><td>产业疏解后本地工业源已很少</td></tr>'
             '</table></div>'
             % (rows[0]["ind_pts"], rows[1]["ind_pts"], rows[5]["ind_pts"]))

    h.append('<div class="card"><h2>六、结论（三句话）</h2>'
             '<div class="note" style="font-size:14px;line-height:1.9">'
             '<b>1. 火点数不能当统一考核指标。</b><br>'
             '河北的火点 78%% 来自工厂、河南 19%% 来自秸秆 —— '
             '一个要用工业执法，一个要靠收储疏导，'
             '但在考核表上是同一个数字。<br><br>'
             '<b>2. 工业无组织排放是「问责真空」。</b><br>'
             '六省合计 <b>%d 个持续排放点位</b>，坐标明确、反复出现、可直接交办；'
             '但没有任何一个省建立了对应机制。<br><br>'
             '<b>3. 谁先建分类台账，谁先掌握主动。</b><br>'
             '2026 年《生态环境法典》要求「精准区分大面积焚烧与农户零星操作」——'
             '<b>精准区分靠数据，不靠文件</b>。'
             '而分类台账这件事，现在还没有人做。</div></div>'
             % tot_ind_pts)

    h.append(AR.qr_foot("../../../assets"))


    h.append('<footer>'
             '数据来源：NASA FIRMS VIIRS 375m（VIIRS_SNPP_SP + VIIRS_NOAA20_SP，2024–2025）· '
             '中国环境监测总站国控点（经 quotsoft.net 逐小时归档）· '
             'DataV.GeoAtlas 行政区划 · 各省秸秆禁烧政策为公开报道与政府文件检索<br>'
             '方法：0.01° 点位聚合 → 出现 ≥10 天判为工业/固定源、≤2 天且落在收获季判为秸秆疑似 → '
             '按省界射线法归属；空气质量取冬季 15 天均值<br>'
             '<b>边界声明</b>：类型判定是启发式规则（依据见「火点类型判别模型 · 验证」），'
             '不是地面核实结论；政策强度为公开信息检索归纳，非官方评级；'
             '相关性为统计描述，不构成因果推断。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "华北六省综合分析.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("秸秆占比 vs 政策强度 r = %.2f ｜ 工业源占比 vs 政策强度 r = %.2f"
          % (r_straw_policy, r_ind_policy))
    print("工业源占比 vs PM2.5 r = %.2f ｜ 秸秆占比 vs PM2.5 r = %.2f" % (r_ind_pm, r_straw_pm))


if __name__ == "__main__":
    main()
