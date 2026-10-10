# -*- coding: utf-8 -*-
"""生成公众号文章（图文并茂 HTML）：《河南秋收季 87% 的火点，其实是工厂在烧》。

所有图表都是**内联 SVG**（脚本现场从原始数据算出来），所以产出的 HTML 是单文件、
不含任何外部图片——可以直接在浏览器看，也可以逐张截图贴进公众号编辑器。

用法：python make_article.py
产出：<工作区>/公众号文章/河南火点-秋收季真相.html
"""
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent                       # EnvData/火点监测
ROOT = MOD.parent.parent.parent         # 工作区根
GEO = MOD / "geo"
HIST = MOD / "data" / "history"
OUT = ROOT / "公众号文章" / "河南火点-秋收季真相.html"
sys.path.insert(0, str(HERE))

import annual_report as AR
import classify as CL
import fetch_firms as FF
import straw_pattern as SP

DARK = "#0f172a"          # 图表底色（深色，在浅色文章里更醒目）
GRID = "#1e293b"
TXTC = "#e2e8f0"
DIMC = "#94a3b8"
C_IND = "#f97316"
C_STRAW = "#34d399"
C_OTH = "#64748b"


# ----------------------------------------------------------------- 图

def _tw(s, size=12.5):
    """粗略估算文字宽度：中文按字号，ASCII 按 0.55 倍。"""
    return sum(size if ord(c) > 0x2E80 else size * 0.55 for c in s)


def fig_share(n_ind, n_straw, n_other, w=880, h=150):
    """秋收季火点构成：一条堆叠横条。"""
    tot = n_ind + n_straw + n_other or 1
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">',
             f'<rect x="0" y="0" width="{w}" height="{h}" fill="{DARK}" rx="10"/>']
    x, y, bh = 24, 62, 42
    bw = w - 48
    for val, col, lab in [(n_ind, C_IND, "工业/固定源"),
                          (n_straw, C_STRAW, "秸秆焚烧疑似"),
                          (n_other, C_OTH, "其他")]:
        seg = bw * val / tot
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{seg:.1f}" height="{bh}" fill="{col}">'
                     f'<title>{lab}：{val} 个（{val/tot*100:.1f}%）</title></rect>')
        if seg > 60:
            parts.append(f'<text x="{x+seg/2:.1f}" y="{y+bh/2+6}" fill="#0b1120" font-size="17" '
                         f'font-weight="700" text-anchor="middle">{val/tot*100:.1f}%</text>')
        x += seg
    # 顶部标题 + 底部图例
    parts.append(f'<text x="24" y="34" fill="{TXTC}" font-size="16" font-weight="600">'
                 f'秋收季（9–10 月）河南 {tot:,} 个火点，按类型拆开</text>')
    lx = 24
    for val, col, lab in [(n_ind, C_IND, f"工业/固定源 {val:,}"),
                          (n_straw, C_STRAW, f"秸秆焚烧疑似 {val:,}"),
                          (n_other, C_OTH, f"其他 {val:,}")]:
        parts.append(f'<circle cx="{lx+5}" cy="126" r="5" fill="{col}"/>')
        parts.append(f'<text x="{lx+16}" y="130" fill="{DIMC}" font-size="12.5">{lab}</text>')
        lx += 16 + _tw(lab, 12.5) + 28
    parts.append("</svg>")
    return "".join(parts)


def fig_top_points(pts, w=880, row=40):
    """高频点位横向条形（pts = [(label, days, sub)]）。"""
    h = row * len(pts) + 22
    mx = max(d for _, d, _ in pts) or 1
    labw, valw = 290, 82
    pw = w - labw - valw - 16
    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">',
         f'<rect x="0" y="0" width="{w}" height="{h}" fill="{DARK}" rx="10"/>']
    for i, (lab, days, sub) in enumerate(pts):
        y = 11 + i * row
        bw = max(3, pw * days / mx)
        p.append(f'<text x="{labw-10}" y="{y+18}" fill="{TXTC}" font-size="13" '
                 f'text-anchor="end">{AR._esc(lab)}</text>')
        p.append(f'<text x="{labw-10}" y="{y+31}" fill="#7dd3fc" font-size="11" '
                 f'text-anchor="end">{AR._esc(sub)}</text>')
        p.append(f'<rect x="{labw}" y="{y+6}" width="{bw:.1f}" height="{row-14}" rx="4" '
                 f'fill="{C_IND}" opacity="0.9"><title>{AR._esc(lab)}：{days} 天</title></rect>')
        p.append(f'<text x="{labw+bw+9:.1f}" y="{y+20}" fill="{TXTC}" font-size="13" '
                 f'font-weight="600">{days} 天</text>')
    p.append("</svg>")
    return "".join(p)


def fig_dist(dists, w=880, h=170):
    """安阳秸秆点位「到最近工业源距离」直方图。"""
    edges = [0, 5, 10, 15, 20, 25, 30, 40, 50, 1e9]
    labs = ["<5", "5–10", "10–15", "15–20", "20–25", "25–30", "30–40", "40–50", ">50"]
    bins = [0] * (len(edges) - 1)
    for d in dists:
        for i in range(len(edges) - 1):
            if edges[i] <= d < edges[i + 1]:
                bins[i] += 1
                break
    mx = max(bins) or 1
    pw = w - 120
    gap = pw / len(bins)
    bw = gap * 0.66
    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block">',
         f'<rect x="0" y="0" width="{w}" height="{h}" fill="{DARK}" rx="10"/>',
         f'<text x="24" y="30" fill="{TXTC}" font-size="15" font-weight="600">'
         f'安阳：{len(dists)} 个秸秆点位，到最近工业源的距离（km）</text>']
    for i, v in enumerate(bins):
        x = 60 + gap * i + (gap - bw) / 2
        bh = (h - 80) * v / mx
        y = h - 34 - bh
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(1,bh):.1f}" '
                 f'rx="3" fill="{C_STRAW}" opacity="0.85"><title>{labs[i]} km：{v} 个</title></rect>')
        p.append(f'<text x="{x+bw/2:.1f}" y="{h-16}" fill="{DIMC}" font-size="11" '
                 f'text-anchor="middle">{labs[i]}</text>')
        if v:
            p.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" fill="{TXTC}" font-size="10.5" '
                     f'text-anchor="middle">{v}</text>')
    p.append("</svg>")
    return "".join(p)


CSS = """
:root{--txt:#2b2b2b;--sub:#6b7280;--line:#e5e7eb;--accent:#0e7490;--mark:#fff3cd}
*{box-sizing:border-box}
body{margin:0;background:#f3f4f6;color:var(--txt);
  font:16px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.paper{max-width:700px;margin:0 auto;background:#fff;padding:36px 26px 60px;
  box-shadow:0 1px 3px rgba(0,0,0,.06)}
h1{font-size:23px;line-height:1.45;margin:0 0 18px;font-weight:700}
h2{font-size:18px;margin:40px 0 14px;padding-left:11px;border-left:4px solid var(--accent);
  line-height:1.4;font-weight:700}
h3{font-size:16px;margin:26px 0 8px;color:var(--accent);font-weight:700}
p{margin:0 0 16px}
strong{font-weight:700;color:#111}
em{font-style:normal;background:var(--mark);padding:1px 3px;border-radius:2px}
hr{border:0;border-top:1px solid var(--line);margin:32px 0}
blockquote{margin:0 0 18px;padding:14px 16px;background:#f6f8fa;
  border-left:3px solid #cbd5e1;color:#374151;font-size:15px;line-height:1.75}
blockquote p:last-child{margin-bottom:0}
table{width:100%;border-collapse:collapse;font-size:15px;margin:0 0 18px}
th,td{border:1px solid var(--line);padding:9px 11px;text-align:left}
th{background:#f9fafb;font-weight:600;color:#374151}
.lead{font-size:17px;color:#374151}
.kicker{color:var(--sub);font-size:14px;margin:0 0 22px;line-height:1.8}
figure{margin:22px 0 26px}
figure svg{border-radius:10px;display:block}
figcaption{color:var(--sub);font-size:13px;margin-top:8px;line-height:1.7}
.warn{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;
  padding:14px 16px;margin:24px 0;font-size:15px;line-height:1.75}
.warn b{color:#b45309}
.end{color:var(--sub);font-size:13.5px;line-height:1.8;margin-top:34px;
  padding-top:16px;border-top:1px solid var(--line)}
ul,ol{margin:0 0 16px;padding-left:22px}
li{margin-bottom:7px}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0 0 18px}
.cmp>div{border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.cmp h4{margin:0 0 10px;font-size:14.5px}
.cmp .a{border-top:3px solid #f97316}
.cmp .b{border-top:3px solid #34d399}
.cmp dl{margin:0;font-size:13.5px;line-height:1.9}
.cmp dt{color:var(--sub);font-size:12.5px}
.cmp dd{margin:0 0 6px;font-weight:600}
@media(max-width:600px){.cmp{grid-template-columns:1fr}}
"""


def main():
    # ---------- 算数据 ----------
    d25 = json.loads((HIST / "2025.json").read_text(encoding="utf-8"))
    fires25 = d25["fires"]
    prof25 = CL.build_profiles(fires25)
    kind25 = {k: CL.classify(p)[0] for k, p in prof25.items()}

    # 秋收季构成
    so = [f for f in fires25 if f["date"][5:7] in ("09", "10")]
    cnt = Counter(kind25[CL.cell_key(f)] for f in so)
    n_ind = cnt.get("工业/固定源", 0)
    n_straw = cnt.get("秸秆焚烧疑似", 0)
    n_other = sum(v for k, v in cnt.items() if k not in ("工业/固定源", "秸秆焚烧疑似"))
    tot_so = len(so)

    # 逐月昼夜
    bm_dn = {}
    for f in fires25:
        m = f["date"][5:7]
        bm_dn.setdefault(m, {"D": 0, "N": 0})[f["dn"]] += 1

    # 安阳：空间 + 距离 + 高频点位
    anyang = []
    for y in (2024, 2025):
        anyang += [f for f in json.loads((HIST / f"{y}.json").read_text(encoding="utf-8"))["fires"]
                   if f["city"] == "安阳"]
    pa = CL.build_profiles(anyang)
    ka = {k: CL.classify(p)[0] for k, p in pa.items()}
    sk = [k for k, v in ka.items() if v == "秸秆焚烧疑似"]
    ik = [k for k, v in ka.items() if v == "工业/固定源"]
    s_pts = [SP.key2ll(k) for k in sk]
    i_pts = [(*SP.key2ll(k), pa[k]["days"]) for k in ik]
    dists = sorted(min(SP.hav(p, q) for q in [(x, y) for x, y, _ in i_pts]) for p in s_pts)
    dist_med = statistics.median(dists)

    gj = json.loads((GEO / "安阳市_县.geojson").read_text(encoding="utf-8"))
    counties = [(f["properties"]["name"], f["geometry"]) for f in gj["features"]]

    def cty(lng, lat):
        for n, g in counties:
            if FF.point_in_geom(lng, lat, g):
                return n
        return "市外"
    top = sorted(pa.values(), key=lambda p: -p["days"])[:8]
    top_rows = [(p["key"], p["days"], cty(*SP.key2ll(p["key"]))) for p in top]

    # 秸秆特征
    sf = [f for f in anyang if CL.cell_key(f) in set(sk)]
    straw_frp = statistics.median(float(f["frp"]) for f in sf)
    once = sum(1 for k in sk if pa[k]["days"] == 1)
    straw_share = n_straw / tot_so * 100

    # ---------- 拼 HTML ----------
    figs = {
        "share": fig_share(n_ind, n_straw, n_other),
        "stack": AR.svg_stack([(AR.mon_label(f"2025-{m}"), bm_dn[m]["D"], bm_dn[m]["N"])
                               for m in sorted(bm_dn)], w=880, h=300),
        "scatter": SP.scatter_city("安阳", counties, s_pts, i_pts, w=880, h=520),
        "top": fig_top_points(top_rows),
        "dist": fig_dist(dists),
    }

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>河南秋收季 87% 的火点，其实是工厂在烧</title>
<style>{CSS}</style></head><body><div class="paper">

<h1>河南秋收季 87% 的火点，其实是工厂在烧</h1>
<p class="kicker">我们扒了河南两年 45,540 个卫星火点。发现一件挺憋屈的事。</p>

<p class="lead">每年秋收季，全省通报的火点里，<strong>绝大多数根本不是秸秆焚烧</strong>。</p>
<p class="lead">而是工厂。</p>

<hr>

<h2>一、先看数据</h2>
<p>用 NASA 的 VIIRS 卫星火点数据（375 米分辨率，能探到一亩地里的一堆火），
我们把河南 2024、2025 两年的火点全拉了一遍。</p>
<p>2025 年全省 <strong>22,626 个火点</strong>。拆到月看，秋收季（9–10 月）有
<strong>{tot_so:,} 个</strong>。这 {tot_so:,} 个里——</p>

<figure>{figs["share"]}
<figcaption>秋收季河南火点构成。{n_ind:,} 个（{n_ind/tot_so*100:.1f}%）是工业/固定源，
真正的秸秆焚烧疑似只有 {n_straw} 个（{straw_share:.1f}%）。</figcaption></figure>

<p><strong>86.7% 是工厂。</strong>怎么判出来的？后面说方法。先看这些"火点"长什么样。</p>

<h2>二、这些"火点"长什么样</h2>
<p>举两个最典型的。</p>
<p><strong>安阳，一个点位，两年 730 天里被卫星探测到 445 天。</strong>
坐标 36.21, 114.05，在安阳县。夜间占比 95%，辐射功率稳定在 1.5 兆瓦上下。</p>
<p><strong>平顶山，一个点位，两年出现 295 天。</strong>
坐标 34.00, 112.96，在宝丰县。夜间占比 96%。</p>
<p><em>没有农民会连着两年、每年两百多天，在同一块地里烧秸秆。</em></p>

<figure>{figs["top"]}
<figcaption>安阳出现最频繁的 8 个点位。全部集中在安阳县与殷都区——安钢集团所在地、
水冶/铜冶钢铁焦化集聚区。</figcaption></figure>

<p>这些火点的特征很清楚：<strong>夜间为主</strong>（95% 以上，窑炉和堆场自燃不会天黑就熄）、
<strong>辐射功率稳定偏低</strong>（1 兆瓦左右，是闷烧不是明火）、
<strong>全年都在烧</strong>（不分季节）。</p>

<h2>三、那真正的秸秆焚烧是什么样的</h2>
<p>反过来看，被判定为"秸秆焚烧疑似"的火点，特征完全相反。</p>

<h3>① 只在收获季出现</h3>
<p>2025 年全省的秸秆疑似火点：5 月 566 个、6 月 514 个、9 月 130 个、10 月 180 个——
<strong>其余八个月加起来只有 2 个</strong>。</p>
<p>同一张图上，9–10 月还有另一个特征——</p>

<figure>{figs["stack"]}
<figcaption>2025 年河南火点逐月昼夜结构。黄色是白天、紫色是夜间。
9–10 月的火点几乎全是紫色（夜间占比 92%/94%）——而农民烧秸秆是白天的事。</figcaption></figure>

<h3>② 基本只烧一次</h3>
<p>安阳 141 个秸秆点位里，<strong>{once} 个（{once/len(sk)*100:.0f}%）两年只出现 1 天</strong>；
平顶山 758 个里，614 个（81%）只出现 1 天。<strong>没有一个出现超过 2 天。</strong></p>

<h3>③ 辐射功率反而更高</h3>
<p>秸秆火点的 FRP 中位数是 <strong>{straw_frp:.2f} 兆瓦</strong>（安阳），
比工业源的 1.5 兆瓦<strong>还高</strong>——因为秸秆是成堆明火，火焰明显；工业源多是闷烧。</p>

<div class="cmp">
  <div class="a"><h4>工业/固定源</h4><dl>
    <dt>两年出现天数</dt><dd>最高 445 天</dd>
    <dt>夜间占比</dt><dd>95% 以上</dd>
    <dt>FRP 中位</dt><dd>约 1.5 MW</dd>
    <dt>位置</dt><dd>工业集聚区（安阳县、殷都区）</dd>
  </dl></div>
  <div class="b"><h4>秸秆焚烧疑似</h4><dl>
    <dt>两年出现天数</dt><dd>{once/len(sk)*100:.0f}% 只出现 1 天</dd>
    <dt>出现月份</dt><dd>只有 5/6/9/10 月</dd>
    <dt>FRP 中位</dt><dd>{straw_frp:.2f} MW</dd>
    <dt>位置</dt><dd>农业县（内黄、滑县、汤阴）</dd>
  </dl></div>
</div>

<h3>④ 远离工业区</h3>
<p>安阳的秸秆点位，到最近工业源点位的距离中位数是 <strong>{dist_med:.0f} 公里</strong>。
两者在空间上基本是<strong>两张网</strong>。</p>

<figure>{figs["dist"]}
<figcaption>安阳 {len(dists)} 个秸秆点位到最近工业源的距离分布。中位数 {dist_med:.0f} 公里——
秸秆焚烧和工厂，根本不在一个地方。</figcaption></figure>

<figure>{figs["scatter"]}
<figcaption>安阳：橙色大点是工业/固定源点位，绿色小点是秸秆焚烧疑似点位。
橙点全挤在中北部（安阳县、殷都区），绿点散在东部和南部（内黄、滑县、汤阴、林州）——
两张网几乎不重叠。</figcaption></figure>

<h2>四、这意味着什么</h2>
<p>如果上级按火点<strong>数量</strong>通报、基层按数量被问责——
那秋收季的绝大多数账，是<strong>替工厂背的</strong>。</p>
<p>这不是猜测。看几个公开的标准和通报：</p>
<ul>
<li><strong>郑州上街区</strong>的文件写明：每个秸秆焚烧火点，<strong>扣减所属镇（办）财力 100 万元</strong></li>
<li><strong>洛阳</strong> 2025 年 5 月的通报：洛龙区、汝阳县因秸秆焚烧分别被扣 40 万、30 万，
<strong>2 名街道/镇党委书记被公开约谈并责令公开检讨</strong></li>
</ul>
<p>一个县一个秋收季被推几十个火点，其中八成以上是工厂——<strong>这笔账怎么算？</strong></p>
<p>而且，<strong>纪检监察机关自己也发现了这个问题</strong>。2025 年 4 月，
中央纪委国家监委网站的文章披露：</p>
<blockquote><p>平顶山市纪委监委在对 2023 年 2 月某企业大气污染问题问责案件进行评查时发现，
某地以"属地管理"为由，对<strong>不在基层职责范围内</strong>的一般干部问责。
上级纪委督促纠正，明确提出——<strong>不能让一般干部替企业背锅</strong>。</p></blockquote>
<p>话说得很明白了。</p>

<h2>五、那该怎么办</h2>

<h3>第一，把两类火点分开</h3>
<p>工业源交<strong>生态环境执法</strong>（查环评、无组织排放、堆场苫盖、脱硫脱硝运行记录），
秸秆交<strong>禁烧办</strong>。安阳 {len(ik)} 个点位、平顶山 39 个点位——
<strong>这就是可以直接交办的清单</strong>，带着坐标和历史记录。</p>

<h3>第二，禁烧巡查只需要在 4 个月上强度</h3>
<p>5、6、9、10 月。其余八个月，全省秸秆火点加起来只有 2 个。
把全年的人力压到两个窗口，比全年平铺有效得多。</p>

<h3>第三，考核口径建议分开</h3>
<p>按火点数量考核时，工业源那部分应该单列——否则基层永远在替工厂背账。</p>

<h2>最后说一句方法</h2>
<p>我们没有用什么黑箱模型。判据就三条：<strong>这个点位以前出现过几次、
是不是主要在夜里、在不在收获季。</strong></p>
<ul>
<li>同一点位反复出现、夜里也烧 → <strong>固定源</strong></li>
<li>只出现一两次、落在收获季 → <strong>秸秆焚烧疑似</strong></li>
</ul>
<p>规则透明，你可以拿任何一条火点来复核。跨年验证的结果是：2024 年判定为"工业/固定源"的
145 个点位，2025 年有 <strong>86% 仍在持续出现，只有一个消失了</strong>——
工厂不会因为换年份就消失。</p>

<div class="warn">
<p><b>⚠ 最后必须说清楚：</b></p>
<p>卫星遥感<strong>无法确证</strong>某个火点就是秸秆焚烧、或就是某家工厂。
我们给出的是"<strong>疑似类型 + 依据</strong>"，不是认定，<strong>不能作为行政处罚依据</strong>。
用于执法，必须经过现场核实。</p>
<p style="margin-bottom:0"><strong>数据是拿来把事分清楚的，不是拿来追责的。</strong></p>
</div>

<div class="end">
数据来源：NASA FIRMS VIIRS 375m 活跃火产品（Suomi-NPP + NOAA-20），2024–2025 年，河南省域。
</div>

</div></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("[article] 秋收季 %d 个火点：工业源 %d（%.1f%%）/ 秸秆 %d（%.1f%%）"
          % (tot_so, n_ind, n_ind / tot_so * 100, n_straw, straw_share))
    print("[article] 安阳秸秆点位 %d 个，距工业源中位 %.1f km" % (len(dists), dist_med))
    print("[article] 写出 %s（%.0f KB）" % (OUT, OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
