# -*- coding: utf-8 -*-
"""把「豫北—豫西空气质量成因分析」改写成公众号文章。

风格对齐已有的《河南火点-秋收季真相》：白底 700px 排版、口语化、有观点、
内联 SVG 配图（公众号可截图后上传）。
输出：公众号文章/豫北豫西-空气成因.html 与同名 .md

用法：python make_article_air.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)                    # env-assets/EnvData/火点监测
ASSETS = os.path.dirname(os.path.dirname(MOD))  # env-assets
WORKSPACE = os.path.dirname(ASSETS)            # 工作区根
ART = os.path.join(WORKSPACE, "公众号文章")

DARK = "#0f172a"
C_HOT, C_ACC, C_OK, C_PUR, C_WARN = "#f97316", "#38bdf8", "#34d399", "#a78bfa", "#fbbf24"


def svg_hbar(items, w=680, row_h=30, lab_w=76, val_w=112, unit="", color=C_ACC, hi=None):
    mx = max(v for _, v in items) or 1
    h = row_h * len(items) + 10
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i, (lab, v) in enumerate(items):
        y = 5 + i * row_h
        bw = max(2, pw * v / mx)
        col = hi(lab, v) if hi else color
        p.append('<text x="%d" y="%.1f" fill="#334155" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 8, y + 19, lab))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="%d" rx="4" fill="%s" opacity="0.9"/>'
                 % (lab_w, y + 5, bw, row_h - 12, col))
        p.append('<text x="%.1f" y="%.1f" fill="#475569" font-size="12">%s%s</text>'
                 % (lab_w + bw + 7, y + 19, ("%.1f" % v) if isinstance(v, float) else str(v), unit))
    p.append("</svg>")
    return "".join(p)


def svg_lines(labels, series, w=680, h=260, pad_l=44, pad_b=34, pad_t=16):
    allv = [v for _, _, vs in series for v in vs if v is not None]
    mx = max(allv) * 1.1
    pw, ph = w - pad_l - 78, h - pad_t - pad_b
    n = len(labels)
    def X(i): return pad_l + pw * i / max(1, n - 1)
    def Y(v): return pad_t + ph - ph * v / mx
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i in range(4):
        y = pad_t + ph * i / 3
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e2e8f0"/>'
                 % (pad_l, y, pad_l + pw, y))
        p.append('<text x="%d" y="%.1f" fill="#94a3b8" font-size="10" text-anchor="end">%.0f</text>'
                 % (pad_l - 6, y + 4, mx * (1 - i / 3)))
    for i, m in enumerate(labels):
        if i % 2 == 0:
            p.append('<text x="%.1f" y="%d" fill="#94a3b8" font-size="9.5" text-anchor="middle">%s</text>'
                     % (X(i), pad_t + ph + 15, m))
    for j, (lab, col, vs) in enumerate(series):
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(vs) if v is not None)
        p.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.4"/>' % (pts, col))
        p.append('<text x="%d" y="%d" fill="%s" font-size="11.5">%s</text>'
                 % (pad_l + pw + 8, pad_t + 12 + j * 17, col, lab))
    p.append("</svg>")
    return "".join(p)


def svg_profile(topo, w=680, h=200, pad_l=44, pad_b=30, pad_t=14):
    lons = [t["longitude"] for t in topo]
    els = [t["elevation"] for t in topo]
    x0, x1 = min(lons), max(lons)
    mx = max(els) * 1.12
    pw, ph = w - pad_l - 16, h - pad_t - pad_b
    def X(ln): return pad_l + pw * (ln - x0) / (x1 - x0)
    def Y(e): return pad_t + ph - ph * e / mx
    pts = " ".join("%.1f,%.1f" % (X(l), Y(e)) for l, e in zip(lons, els))
    area = "%s %.1f,%.1f %.1f,%.1f" % (pts, X(x1), Y(0), X(x0), Y(0))
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    p.append('<polygon points="%s" fill="#34d399" opacity="0.22"/>' % area)
    p.append('<polyline points="%s" fill="none" stroke="#059669" stroke-width="2.2"/>' % pts)
    peak = max(topo, key=lambda t: t["elevation"])
    p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#dc2626" stroke-width="1.3" '
             'stroke-dasharray="4 3"/>' % (X(peak["longitude"]), pad_t, X(peak["longitude"]), Y(peak["elevation"])))
    p.append('<text x="%.1f" y="%.1f" fill="#dc2626" font-size="11.5" text-anchor="middle">'
             '太行山主脊 %.0f m</text>' % (X(peak["longitude"]), Y(peak["elevation"]) - 6, peak["elevation"]))
    for ln, lab in [(114.05, "安阳"), (114.29, "鹤壁"), (113.24, "焦作")]:
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#f97316" stroke-width="1.3"/>'
                 % (X(ln), Y(0), X(ln), Y(0) - 10))
        p.append('<text x="%.1f" y="%.1f" fill="#c2410c" font-size="11" text-anchor="middle">%s</text>'
                 % (X(ln), Y(0) - 13, lab))
    p.append('<text x="%.1f" y="%.1f" fill="#64748b" font-size="11" text-anchor="middle">豫北平原</text>'
             % (X(114.6), Y(0) + 14))
    p.append('<text x="%.1f" y="%.1f" fill="#64748b" font-size="11" text-anchor="middle">山西高原</text>'
             % (X(112.4), pad_t + 12))
    p.append("</svg>")
    return "".join(p)


def main():
    mon = json.load(open(os.path.join(MOD, "data", "stations", "aqi-monthly.json"), encoding="utf-8"))
    winter = json.load(open(os.path.join(MOD, "data", "stations", "aqi-winter.json"), encoding="utf-8"))
    no2 = json.load(open(os.path.join(MOD, "data", "satellite", "city-no2.json"), encoding="utf-8"))
    topo = json.load(open(os.path.join(MOD, "data", "topo-profile.json"), encoding="utf-8"))
    months = sorted(mon)
    mlab = ["%s月" % m[5:7] for m in months]

    def wv(c, k):
        return winter.get(c, {}).get(k, 0)

    def ratio(c, k="SO2"):
        a = [mon[m].get(c, {}).get(k, 0) for m in ["2025-11", "2025-12", "2026-01", "2026-02"]]
        b = [mon[m].get(c, {}).get(k, 0) for m in ["2026-06", "2026-07", "2026-08"]]
        return (sum(a) / 4) / (sum(b) / 3) if sum(b) else 0

    pm_items = [(c.replace("市", ""), wv(c, "PM2.5")) for c in
                ["商丘市", "许昌市", "漯河市", "安阳市", "开封市", "濮阳市", "新乡市", "鹤壁市",
                 "驻马店市", "南阳市", "信阳市", "郑州市", "焦作市", "洛阳市", "平顶山市", "三门峡市"]]
    so2_items = [(c.replace("市", ""), wv(c, "SO2")) for c in
                 ["三门峡市", "洛阳市", "新乡市", "焦作市", "平顶山市", "濮阳市", "鹤壁市",
                  "许昌市", "漯河市", "南阳市", "信阳市", "安阳市", "开封市", "郑州市", "商丘市"]]
    rat_items = [(c.replace("市", ""), round(ratio(c), 2)) for c in
                 ["洛阳市", "焦作市", "鹤壁市", "漯河市", "新乡市", "商丘市", "驻马店市",
                  "三门峡市", "郑州市", "许昌市", "安阳市", "周口市", "濮阳市"]]
    no2_items = [(c, round(v["med"])) for c, v in sorted(no2.items(), key=lambda x: -x[1]["med"])[:8]]

    pm_svg = svg_hbar(pm_items, unit="", color=C_HOT)
    so2_svg = svg_hbar(so2_items, unit="", color=C_PUR,
                       hi=lambda lab, v: "#7c3aed" if lab in ("三门峡", "洛阳", "新乡") else C_PUR)
    rat_svg = svg_hbar(rat_items, unit="",
                       hi=lambda lab, v: "#dc2626" if v >= 1.4 else ("#059669" if v < 1.15 else C_WARN),
                       color=C_WARN)
    no2_svg = svg_hbar(no2_items, unit="", color=C_ACC)
    so2_lines = svg_lines(mlab, [
        ("洛阳", "#7c3aed", [mon[m].get("洛阳市", {}).get("SO2") for m in months]),
        ("三门峡", "#0ea5e9", [mon[m].get("三门峡市", {}).get("SO2") for m in months]),
        ("安阳", "#dc2626", [mon[m].get("安阳市", {}).get("SO2") for m in months]),
        ("濮阳", "#f97316", [mon[m].get("濮阳市", {}).get("SO2") for m in months]),
    ])
    prof_svg = svg_profile(topo)
    peak = max(t["elevation"] for t in topo)

    TITLE = "PM2.5 全省最低，SO₂ 全省最高：这一带的空气问题被误读了"
    body = []
    A = body.append

    A('<p class="kicker">我们把河南 18 个市的国控数据、卫星柱浓度和地形剖面摆在一起，'
      '发现一个被排名掩盖的事实。</p>')
    A('<p class="lead">如果只看 PM2.5 排名，你会得出一个结论：<strong>豫西空气挺好</strong>。</p>')
    A('<p class="lead">但把 SO₂ 拉出来一看，画风完全变了。</p>')
    A('<hr>')

    A('<h2>一、先看"哪里脏"：PM2.5 的答案很直白</h2>')
    A('<p>取冬季 15 天（2025 年 12 月中旬 + 2026 年 1 月上旬）的国控点均值：</p>')
    A('<figure>%s<figcaption>冬季 PM2.5 均值（μg/m³），国控点平均</figcaption></figure>' % pm_svg)
    A('<p>商丘 <strong>84</strong>、许昌 82、漯河 81、安阳 78、濮阳 74 —— '
      '高值集中在<strong>豫北和豫中</strong>。</p>')
    A('<p>而<strong>三门峡只有 56，洛阳 60</strong>。这两个数字，比信阳（64）还低。</p>')
    A('<p>如果到这里就收工，你会说：豫西没问题，该盯的是豫北和豫中。</p>')
    A('<p>但先别急。</p>')

    A('<h2>二、再看"谁在持续排"：SO₂ 给了相反的答案</h2>')
    A('<p>把 SO₂ 按同样的口径排一遍：</p>')
    A('<figure>%s<figcaption>冬季 SO₂ 均值（μg/m³）</figcaption></figure>' % so2_svg)
    A('<p><strong>三门峡 12.2、洛阳 11.2 —— 全省最高</strong>。'
      '比以煤化工著称的新乡（10.7）、焦作（9.7）还高，'
      '比安阳（6.6）、濮阳（8.0）高出一大截。</p>')
    A('<p>也就是说：<strong>PM2.5 最低的地方，SO₂ 反而最高。</strong></p>')
    A('<p>这不是矛盾，是两个不同的信号。</p>')

    A('<h2>三、一个比值，把两类源分开</h2>')
    A('<p>关键在于：<strong>SO₂ 有没有季节性</strong>。</p>')
    A('<p>冬季取暖会额外烧煤，所以纯取暖型的 SO₂ 一定"冬天高、夏天低"。'
      '而工业窑炉、冶炼炉是全年都在开的，它们的 SO₂ 应该<strong>一年到头都差不多</strong>。</p>')
    A('<p>于是我们算了一个很简单的比值：<strong>冬夏比 = 11–2 月均值 ÷ 6–8 月均值</strong>。</p>')
    A('<figure>%s<figcaption>SO₂ 冬夏比：越接近 1，越说明是全年性工业源；'
      '越大于 1，越说明季节性取暖占比大</figcaption></figure>' % rat_svg)
    A('<p>结果一目了然：</p>')
    A('<ul>'
      '<li><strong>洛阳 1.00、焦作 1.01、鹤壁 1.04</strong> —— 冬夏几乎一样多。'
      '这不是取暖烧出来的，是<strong>全年连续排放</strong>。</li>'
      '<li><strong>濮阳 2.06、安阳 1.45、许昌 1.44</strong> —— 冬季明显更高，'
      '季节性（取暖）的成分大得多。</li>'
      '</ul>')
    A('<p>把逐月曲线画出来，对比更直观：</p>')
    A('<figure>%s<figcaption>SO₂ 逐月均值（2025-11 ~ 2026-10，每月取 3 天）</figcaption></figure>' % so2_lines)
    A('<p>紫色（洛阳）和蓝色（三门峡）的线<strong>几乎是平的</strong>，'
      '而红色（安阳）、橙色（濮阳）<strong>冬季明显隆起</strong>。</p>')

    A('<h2>四、但别急着做"豫北 vs 豫西"的二分</h2>')
    A('<p>看到这里，很容易得出一个漂亮结论：<em>豫北是烧出来的，豫西是炼出来的</em>。</p>')
    A('<p>可惜数据不支持这么干净的分法。</p>')
    A('<p><strong>焦作 1.01、鹤壁 1.04</strong> —— 这两个城市地理上都在豫北，'
      '但它们的 SO₂ 季节特征和洛阳是同一档。</p>')
    A('<p>原因也不难理解：焦作有氧化铝，鹤壁有煤化工，'
      '这些和洛阳的石化、三门峡的有色冶炼一样，都是<strong>全年不停的生产工艺</strong>。</p>')
    A('<p>所以正确的说法不是"哪里 vs 哪里"，而是：</p>')
    A('<p class="lead"><strong>用 PM2.5 排名，只能看出"哪里脏"；'
      '用 SO₂ 季节比，才能看出"哪里在持续排"。</strong></p>')

    A('<h2>五、为什么太行山前是重灾区</h2>')
    A('<p>还有一个绕不开的因素：地形。</p>')
    A('<p>沿北纬 36.15° 拉一条剖面，从山西高原一直拉到豫北平原：</p>')
    A('<figure>%s<figcaption>沿 36.15°N 的高程剖面（SRTM 90m）</figcaption></figure>' % prof_svg)
    A('<p>太行山主脊 <strong>%.0f 米</strong>，在不到 <strong>30 公里</strong>内'
      '一路降到平原的 <strong>275 米</strong> —— 落差超过 1200 米。</p>' % peak)
    A('<p>冬季西北风越过山脊后下沉增温，山前平原就成了<strong>气流停滞区</strong>。'
      '本地排放、外来传输，全都在这儿堆着。</p>')
    A('<p>安阳、鹤壁、焦作、新乡，正好都在这条线上。'
      '洛阳是另一种地形 —— <strong>三面环山的盆地</strong>，静风频率高；'
      '三门峡则是<strong>黄河窄谷</strong>，河谷里污染物不容易散出去。</p>')

    A('<h2>六、还有一层：这不是一个市的事</h2>')
    A('<p>太行山前是一条连续的城市带，从北往南：邢台、邯郸、安阳、鹤壁、新乡、焦作。'
      '彼此间距只有 40–60 公里。</p>')
    A('<p>冬季西北风把上风向的污染物送过来，静稳天气下又互相叠加。'
      '这也解释了一个常见困惑：<strong>为什么本地减排了，空气质量却没明显改善</strong>。</p>')
    A('<p>单打独斗，效果会被上风向抵消。</p>')

    A('<h2>七、这对治理意味着什么</h2>')
    A('<p>把上面的东西合起来，其实就三句话：</p>')
    A('<ol>'
      '<li><strong>PM2.5 适合排名，SO₂ 季节比适合找源。</strong>'
      '前者看结果，后者看过程。</li>'
      '<li><strong>全年性 SO₂ 源（洛阳、焦作、鹤壁、三门峡）要单独拉清单。</strong>'
      '这类源的特点是"平时不显眼、但一直在排"，'
      '用冬季浓度排名反而容易被取暖型城市盖过去。</li>'
      '<li><strong>山前城市带要联防。</strong>'
      '安阳—邯郸—邢台跨省协同，汾渭平原与豫北协同，'
      '这不是"锦上添花"，是必要条件。</li>'
      '</ol>')
    A('<p>最后补一句：我们之前做的火点分析，抓的是"有热异常"的那部分排放源。'
      '而<strong>冶炼、石化这类 SO₂ 源，未必产生卫星能看到的火点</strong> ——'
      '它需要另一套方法。这也是为什么这份分析值得单独做。</p>')

    A('<h2>数据与边界</h2>')
    A('<ul class="meta">'
      '<li>空气质量：中国环境监测总站国控点，冬季 15 天样本 + 逐月（2025-11 ~ 2026-10，'
      '每月取 1/11/21 日）</li>'
      '<li>卫星柱浓度：Sentinel-5P TROPOMI L3 月产品（7 个月：2024 年 3/5/8/9/10/12 月 + '
      '2025 年 2 月）</li>'
      '<li>地形：SRTM 90m（open-elevation）</li>'
      '<li><strong>边界</strong>：SO₂ 冬夏比反映的是"源的季节性特征"，'
      '不等于源解析结论；文中行业构成为公开信息归纳，未逐企业核实。'
      '济源国控点为新增站点，历史归档未覆盖，故未纳入逐月曲线。</li>'
      '</ul>')

    # ---------------- HTML ----------------
    CSS = """
:root{--txt:#2b2b2b;--sub:#6b7280;--line:#e5e7eb;--accent:#0e7490;--mark:#fff3cd}
*{box-sizing:border-box}
body{margin:0;background:#f3f4f6;color:var(--txt);
  font:16px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.paper{max-width:700px;margin:0 auto;background:#fff;padding:38px 26px 56px;
  box-shadow:0 1px 3px rgba(0,0,0,.06)}
h1{font-size:24px;line-height:1.45;margin:0 0 14px;letter-spacing:.3px}
h2{font-size:19px;margin:38px 0 12px;padding-left:11px;border-left:4px solid var(--accent);
  line-height:1.4}
p{margin:14px 0}
.kicker{color:var(--sub);font-size:14.5px;margin-bottom:6px}
.lead{font-size:17px;font-weight:600;color:#111827}
strong{color:#0f172a;font-weight:600}
em{font-style:normal;background:var(--mark);padding:1px 4px;border-radius:3px}
hr{border:0;border-top:1px solid var(--line);margin:26px 0}
ul,ol{padding-left:22px;margin:14px 0}
li{margin:7px 0}
figure{margin:20px 0;padding:14px 10px;background:#f8fafc;border:1px solid var(--line);
  border-radius:10px}
figcaption{color:var(--sub);font-size:12.5px;text-align:center;margin-top:9px;line-height:1.6}
.meta{color:var(--sub);font-size:13px;line-height:1.75}
.meta li{margin:4px 0}
@media(max-width:520px){.paper{padding:24px 15px 40px}h1{font-size:20px}h2{font-size:17px}}
"""
    html = ('<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>%s</title>\n<style>%s</style>\n</head>\n<body><div class="paper">\n\n'
            '<h1>%s</h1>\n' % (TITLE, CSS, TITLE) + "\n".join(body) +
            '\n\n</div></body></html>\n')

    # ---------------- Markdown ----------------
    import re
    md = ["# " + TITLE, "", "> 备用标题：",
          "> · 《一个比值，把「哪里空气脏」和「哪里在持续排」分开了》",
          "> · 《豫北是烧出来的，豫西是炼出来的——但不能这么简单分》", "", "---", ""]
    for blk in body:
        if blk.startswith("<figure>"):
            cap = re.search(r"<figcaption>(.*?)</figcaption>", blk, re.S)
            md += ["> 【配图】%s" % (cap.group(1) if cap else ""), ""]
        elif blk.startswith("<h2>"):
            md += ["## " + re.sub(r"<[^>]+>", "", blk), ""]
        elif blk.startswith("<hr>"):
            md += ["---", ""]
        elif blk.startswith("<ul") or blk.startswith("<ol"):
            for li in re.findall(r"<li>(.*?)</li>", blk, re.S):
                md.append("- " + re.sub(r"<[^>]+>", "", li).strip())
            md.append("")
        else:
            t = re.sub(r"<[^>]+>", "", blk).strip()
            t = t.replace("**", "").replace("<strong>", "**").replace("</strong>", "**")
            if t:
                md += [t, ""]

    os.makedirs(ART, exist_ok=True)
    hp = os.path.join(ART, "豫北豫西-空气成因.html")
    mp = os.path.join(ART, "豫北豫西-空气成因.md")
    open(hp, "w", encoding="utf-8").write(html)
    open(mp, "w", encoding="utf-8").write("\n".join(md))
    print("已生成", hp, "%.0f KB" % (os.path.getsize(hp) / 1024))
    print("已生成", mp, "%.0f KB" % (os.path.getsize(mp) / 1024))
    print("正文字数（约）:", len(re.sub(r"<[^>]+>", "", "\n".join(body))))


if __name__ == "__main__":
    main()
