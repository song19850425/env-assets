# -*- coding: utf-8 -*-
"""豫北—豫西空气质量成因分析。

回答的问题：除了火点，还有哪些原因让豫北/豫西这一带空气质量持续偏差？
核心判断：**不是一回事** —— 豫北是颗粒物型（PM2.5 + 火点），豫西是工艺型（SO₂ 全年稳定高）。

数据：
  · data/stations/aqi-monthly.json   逐月（2025-11 ~ 2026-10，每月 3 天）国控点均值
  · data/stations/aqi-winter.json    冬季 15 天样本
  · data/stations/aqi-autumn30.json  秋季 28 天样本
  · data/satellite/city-no2.json     TROPOMI NO₂ 7 个月市级中位
  · data/topo-profile.json           沿 36.15°N 的高程剖面（open-elevation）

用法：python air_quality_causes.py
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C

NORTH = ["安阳市", "鹤壁市", "新乡市", "焦作市", "濮阳市"]      # 豫北
WEST = ["洛阳市", "三门峡市"]                                    # 豫西
PLAIN = ["商丘市", "许昌市", "漯河市", "开封市"]                 # 豫中平原
SOUTH = ["信阳市", "南阳市"]                                     # 豫南
METRICS = ["PM2.5", "PM10", "SO2", "NO2", "AQI"]


def esc(s):
    return AR._esc(s)


def svg_lines(months, series, w=880, h=300, pad_l=54, pad_b=44, pad_t=20, unit=""):
    """多系列折线图。series = [(label, color, [v...]), ...]"""
    allv = [v for _, _, vs in series for v in vs if v is not None]
    mx = max(allv) if allv else 1
    mn = 0
    pw, ph = w - pad_l - 90, h - pad_t - pad_b
    n = len(months)
    def X(i): return pad_l + (pw * i / max(1, n - 1))
    def Y(v): return pad_t + ph - ph * (v - mn) / (mx - mn or 1)
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i in range(5):
        y = pad_t + ph * i / 4
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pad_l, y, pad_l + pw, y, C["line"]))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="10" text-anchor="end">%.0f</text>'
                 % (pad_l - 8, y + 4, C["dim2"], mx * (1 - i / 4)))
    for i, m in enumerate(months):
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="9.5" text-anchor="middle">%s</text>'
                 % (X(i), pad_t + ph + 16, C["dim"], m[2:]))
    for j, (lab, col, vs) in enumerate(series):
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(vs) if v is not None)
        p.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" '
                 'stroke-linejoin="round"/>' % (pts, col))
        for i, v in enumerate(vs):
            if v is None:
                continue
            p.append('<circle cx="%.1f" cy="%.1f" r="2.6" fill="%s"><title>%s %s：%.1f</title>'
                     '</circle>' % (X(i), Y(v), col, esc(lab), months[i], v))
        p.append('<text x="%d" y="%d" fill="%s" font-size="11">%s</text>'
                 % (pad_l + pw + 10, pad_t + 14 + j * 17, col, esc(lab)))
    p.append("</svg>")
    return "".join(p)


def svg_profile(topo, w=880, h=250, pad_l=54, pad_b=40, pad_t=18):
    """地形剖面：沿 36.15°N 从山西高原到豫北平原。"""
    lons = [t["longitude"] for t in topo]
    els = [t["elevation"] for t in topo]
    x0, x1 = min(lons), max(lons)
    mx = max(els) * 1.08
    pw, ph = w - pad_l - 20, h - pad_t - pad_b
    def X(ln): return pad_l + pw * (ln - x0) / (x1 - x0)
    def Y(e): return pad_t + ph - ph * e / mx
    pts = " ".join("%.1f,%.1f" % (X(l), Y(e)) for l, e in zip(lons, els))
    area = "%s %.1f,%.1f %.1f,%.1f" % (pts, X(x1), Y(0), X(x0), Y(0))
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i in range(4):
        y = pad_t + ph * i / 3
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pad_l, y, pad_l + pw, y, C["line"]))
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="10" text-anchor="end">%.0f m</text>'
                 % (pad_l - 8, y + 4, C["dim2"], mx * (1 - i / 3)))
    p.append('<polygon points="%s" fill="%s" opacity="0.25"/>' % (area, C["ok"]))
    p.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (pts, C["ok"]))
    # 标注：太行山主脊、山前陡降、平原
    peak = max(topo, key=lambda t: t["elevation"])
    p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#f97316" stroke-width="1.4" '
             'stroke-dasharray="4 3"/>' % (X(peak["longitude"]), pad_t, X(peak["longitude"]), Y(peak["elevation"])))
    p.append('<text x="%.1f" y="%.1f" fill="#f97316" font-size="11" text-anchor="middle">'
             '太行山主脊 %.0f m</text>' % (X(peak["longitude"]), Y(peak["elevation"]) - 8, peak["elevation"]))
    for ln, lab, col in [(114.05, "安阳", "#ef4444"), (114.29, "鹤壁", "#f97316"),
                         (113.24, "焦作", "#fbbf24")]:
        if x0 <= ln <= x1:
            p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2"/>'
                     % (X(ln), Y(0), X(ln), Y(0) - 12, col))
            p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10.5" text-anchor="middle">%s</text>'
                     % (X(ln), Y(0) - 16, col, lab))
    for ln, lab in [(112.5, "山西高原"), (114.6, "豫北平原")]:
        p.append('<text x="%.1f" y="%d" fill="%s" font-size="11" text-anchor="middle">%s</text>'
                 % (X(ln), pad_t + ph + 22, C["dim"], lab))
    p.append("</svg>")
    return "".join(p)


def main():
    mon = json.load(open(os.path.join(MOD, "data", "stations", "aqi-monthly.json"), encoding="utf-8"))
    winter = json.load(open(os.path.join(MOD, "data", "stations", "aqi-winter.json"), encoding="utf-8"))
    no2 = json.load(open(os.path.join(MOD, "data", "satellite", "city-no2.json"), encoding="utf-8"))
    topo = json.load(open(os.path.join(MOD, "data", "topo-profile.json"), encoding="utf-8"))
    months = sorted(mon)
    mlabel = ["%s-%s" % (m[2:4], m[5:7]) for m in months]

    def series(city, metric):
        return [mon[m].get(city, {}).get(metric) for m in months]

    def grp_avg(cities, metric, src=None):
        out = []
        for m in months:
            vals = [mon[m].get(c, {}).get(metric) for c in cities]
            vals = [v for v in vals if v]
            out.append(sum(vals) / len(vals) if vals else None)
        return out

    def win_avg(cities, metric):
        vals = [winter[c][metric] for c in cities if c in winter and metric in winter[c]]
        return sum(vals) / len(vals) if vals else 0

    # SO₂ 冬夏比
    def ratio(city, metric="SO2"):
        w = [mon[m].get(city, {}).get(metric, 0) for m in ["2025-11", "2025-12", "2026-01", "2026-02"]]
        s = [mon[m].get(city, {}).get(metric, 0) for m in ["2026-06", "2026-07", "2026-08"]]
        w = sum(w) / 4; s = sum(s) / 3
        return (w / s) if s else 0, w, s

    so2_lines = svg_lines(mlabel, [
        ("洛阳市", "#a78bfa", series("洛阳市", "SO2")),
        ("三门峡市", "#38bdf8", series("三门峡市", "SO2")),
        ("安阳市", "#ef4444", series("安阳市", "SO2")),
        ("濮阳市", "#f97316", series("濮阳市", "SO2")),
    ], h=280, unit="μg/m³")
    pm_lines = svg_lines(mlabel, [
        ("安阳市", "#ef4444", series("安阳市", "PM2.5")),
        ("濮阳市", "#f97316", series("濮阳市", "PM2.5")),
        ("洛阳市", "#a78bfa", series("洛阳市", "PM2.5")),
        ("三门峡市", "#38bdf8", series("三门峡市", "PM2.5")),
    ], h=280, unit="μg/m³")
    profile = svg_profile(topo)

    no2_rows = sorted([(c, v["med"]) for c, v in no2.items()], key=lambda x: -x[1])
    no2_bar = AR.svg_hbar([(c, round(v)) for c, v in no2_rows], row_h=24,
                          color=C["accent"], unit="μmol/m²")

    rows = []
    for c in ["安阳市", "鹤壁市", "新乡市", "焦作市", "濮阳市", "洛阳市", "三门峡市",
              "商丘市", "许昌市", "郑州市", "信阳市"]:
        r, w, s = ratio(c)
        rows.append((c, win_avg([c], "PM2.5"), win_avg([c], "SO2"), win_avg([c], "NO2"),
                     win_avg([c], "AQI"), r, w, s))

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>豫北—豫西空气质量成因分析</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>豫北—豫西空气质量成因分析</h1>',
         '<div class="sub">除火点之外，还有什么在影响这一区域　·　'
         '数据：国控点逐月（2025-11 ~ 2026-10）· TROPOMI NO₂ · 地形剖面　·　生成于 %s</div>' % dt]

    h.append('<div class="card" style="border-color:#f97316"><h2>核心结论</h2>'
             '<div style="font-size:18px;line-height:1.8">'
             '「豫西豫西北豫北都差」这句话只说对了一半 —— '
             '这一带其实混着<span class="hl">两类完全不同的问题</span>。'
             '</div>'
             '<div class="note">'
             '<b>第一层，看"哪里脏"（PM2.5）</b>：豫北、豫中确实全省最高'
             '（安阳 78、濮阳 74、鹤壁 71）；但<b>豫西的 PM2.5 反而是全省最低档</b>'
             '（三门峡 56、洛阳 60）—— 比信阳还低。'
             '<br><b>第二层，看"哪里在持续排"（SO₂ 冬夏比）</b>：'
             '洛阳 <b>1.00</b>、焦作 1.01、鹤壁 1.04 —— '
             '冬夏排得一样多、与取暖无关，是<b>全年性工业源</b>；'
             '而濮阳 <b>2.06</b>、安阳 1.45 冬季明显更高，<b>季节性（取暖）占比更大</b>。'
             '<br><b>所以不能按"豫北 vs 豫西"简单二分</b>：'
             '焦作（氧化铝）、鹤壁（煤化工）和洛阳一样有全年性 SO₂ 源。'
             '正确用法是：<b>PM2.5 用来排名，SO₂ 冬夏比用来找源</b>。</div></div>')

    h.append('<div class="card"><h2>一、三类区域，三类问题</h2>'
             '<div class="note">冬季 15 天样本（2025-12-15~19 + 2026-01-05~14）国控点均值。'
             '「SO₂ 冬夏比」= 11–2 月均值 ÷ 6–8 月均值，越接近 1 说明越不像取暖源。</div>'
             '<table><tr><th>城市</th><th class="num">PM2.5</th><th class="num">SO₂</th>'
             '<th class="num">NO₂</th><th class="num">AQI</th><th class="num">SO₂ 冬夏比</th>'
             '<th>判断</th></tr>')
    for c, pm, so, n2, aq, r, w, s in rows:
        if r < 1.15:
            tag, col = "全年性工业源", "#a78bfa"
        elif r < 1.5:
            tag, col = "工业 + 季节性", "#fbbf24"
        else:
            tag, col = "季节性（取暖）显著", "#f97316"
        hl = ' style="color:#fbbf24;font-weight:600"' if r < 1.15 else ''
        h.append('<tr><td><b>%s</b></td><td class="num">%.0f</td><td class="num">%.1f</td>'
                 '<td class="num">%.0f</td><td class="num">%.0f</td>'
                 '<td class="num"%s>%.2f</td>'
                 '<td style="color:%s">%s</td></tr>'
                 % (esc(c), pm, so, n2, aq, hl, r, col, tag))
    h.append('</table>'
             '<div class="note"><b>这张表要横着看两个维度</b>：<br>'
             '· <b>PM2.5 一列</b>看"哪里脏"：豫北/豫中最高（安阳 78、濮阳 74、鹤壁 71），'
             '豫西/豫南最低（三门峡 56、信阳 64）。<br>'
             '· <b>SO₂ 冬夏比一列</b>看"哪里在持续排"：'
             '<b>洛阳 1.00、焦作 1.01、鹤壁 1.04</b> —— 接近 1 意味着'
             '冬夏排得一样多，与取暖无关，是<b>全年性工业源</b>；'
             '而<b>濮阳 2.06、安阳 1.45</b> 冬季明显更高，说明季节性因素（取暖）占比更大。<br>'
             '注意焦作、鹤壁虽在豫北，但它们的 SO₂ 特征和洛阳同档 —— '
             '所以「豫北 vs 豫西」不是简单的南北二分，'
             '<b>焦作（氧化铝）、鹤壁（煤化工）同样有全年性 SO₂ 源</b>。</div></div>')

    h.append('<div class="card"><h2>二、证据一：SO₂ 的季节性分异</h2>'
             '%s'
             '<div class="note">洛阳、三门峡的曲线<b>几乎是平的</b>（全年 10–13 μg/m³）；'
             '安阳、濮阳的曲线<b>冬季明显隆起</b>。'
             '这是"连续工业源"与"季节性取暖源"最直观的区分。</div></div>' % so2_lines)

    h.append('<div class="card"><h2>三、证据二：PM2.5 的季节性（全省共性）</h2>'
             '%s'
             '<div class="note">PM2.5 则相反：<b>四个城市冬季都抬升</b>，夏季都降到 20–30。'
             '说明颗粒物的季节性是全省共性（气象 + 取暖 + 传输），'
             '不能用来区分区域差异 —— 这也反过来说明，'
             '<b>要用 SO₂ 而不是 PM2.5 来识别"哪里的工业源在持续排"</b>。</div></div>' % pm_lines)

    h.append('<div class="card"><h2>四、证据三：太行山前的地形</h2>'
             '%s'
             '<div class="note">沿 36.15°N 的高程剖面（open-elevation，SRTM）：'
             '太行山主脊 <b>%.0f m</b> 在约 27 km 内陡降到平原的 <b>275 m</b>，落差近 %.0f m。'
             '冬季西北风越过山脊后下沉增温，山前平原成为<b>气流停滞区</b>，'
             '本地排放叠加外来传输后在此堆积 —— 这就是安阳、鹤壁、焦作、新乡"持续偏差"的'
             '地形底层原因。<br>洛阳是另一种地形：<b>三面环山的盆地</b>，静风频率高；'
             '三门峡则是<b>黄河窄谷</b>，河谷内污染物不易扩散。</div></div>'
             % (profile, max(t["elevation"] for t in topo),
                max(t["elevation"] for t in topo) - 275))

    h.append('<div class="card"><h2>五、证据四：卫星 NO₂ 的空间分布</h2>'
             '%s'
             '<div class="note">TROPOMI 7 个月月均（2024-03/05/08/09/10/12 + 2025-02）市级中位。'
             '<b>高值集中在豫北 + 豫中</b>：焦作 172、郑州 168、鹤壁 166、新乡 165、安阳 163。'
             '而<b>三门峡 92、洛阳 103 是全省最低档</b> —— '
             '这与地面 NO₂ 的冬季数值（三门峡 38、洛阳 35 反而靠前）形成反差，'
             '说明<b>豫西的 NO₂ 是"冬季抬升型"，年尺度上并不高</b>，'
             '进一步支持"豫西问题是工艺性的、而非总量性的"。</div></div>' % no2_bar)

    h.append('<div class="card"><h2>六、排放源清单（产业结构）</h2>'
             '<table><tr><th>区域</th><th>主导行业</th><th>特征污染物</th><th>与火点的关系</th></tr>'
             '<tr><td><b>豫北</b><br>安阳·鹤壁·新乡·焦作·濮阳</td>'
             '<td>钢铁（安钢）、焦化、煤化工、建材、石化（中原油田）、化肥</td>'
             '<td>PM2.5 · PM10 · NO₂</td>'
             '<td><b>高度重合</b>：全省 34 个安阳工业点位、39 个平顶山点位都在这一带</td></tr>'
             '<tr><td><b>豫西</b><br>洛阳·三门峡·济源</td>'
             '<td>有色冶炼（黄金/铝/铅锌）、石化（洛阳石化）、耐火材料、刚玉</td>'
             '<td><b>SO₂</b> · NO₂（冬季）</td>'
             '<td><b>部分重合</b>：济源 14 个工业点位、三门峡 10 个；但洛阳的 SO₂ 源多为'
             '有组织排放，未必产生火点</td></tr>'
             '<tr><td>全省共性</td><td>燃煤（工业锅炉 + 农村散煤）、柴油重卡（晋煤外运）</td>'
             '<td>PM2.5 · SO₂（冬季）</td><td>—</td></tr>'
             '</table>'
             '<div class="note">⚠ 上表行业构成为<b>公开产业信息的归纳</b>，不是逐企业核实的结论；'
             '特征污染物一列有本报告的数据支撑。</div></div>')

    h.append('<div class="card"><h2>七、区域传输</h2>'
             '<div class="note">'
             '· <b>山西汾渭平原 → 豫北</b>：汾河谷地与豫北同属一个大气通道，'
             '冬季西北风把上风向污染物带到太行山前；<br>'
             '· <b>河北邯郸、邢台 → 安阳</b>：直线距离不到 60 km，同属太行山前城市带，'
             '污染过程高度同步；<br>'
             '· <b>山前城市带内部互输</b>：安阳—鹤壁—新乡—焦作间距 40–60 km，'
             '在静稳天气下会互相叠加。<br>'
             '这解释了为什么"本地减排了、空气质量却没明显改善"——'
             '<b>山前地带是一个整体，单打独斗效果有限</b>。</div></div>')

    h.append('<div class="card"><h2>八、结论与治理含义</h2>'
             '<div class="note">不按地域、按<b>问题类型</b>分，抓手才清楚：</div>'
             '<table><tr><th>问题类型</th><th>城市</th><th>证据</th><th>该抓什么</th></tr>'
             '<tr><td><b>全年性工业 SO₂</b></td>'
             '<td>洛阳、焦作、鹤壁、三门峡</td>'
             '<td>SO₂ 冬夏比 1.00–1.37，冬季浓度全省最高</td>'
             '<td>冶炼 / 氧化铝 / 煤化工 / 石化的有组织排放、脱硫设施运行、无组织逸散。'
             '<b>⚠ 这类源未必产生火点</b>，火点清单抓不到它</td></tr>'
             '<tr><td><b>颗粒物 + 季节性燃烧</b></td>'
             '<td>安阳、濮阳、新乡 + 豫中（商丘、许昌）</td>'
             '<td>PM2.5 冬季 71–84（全省最高），SO₂ 冬夏比 1.2–2.1</td>'
             '<td>工业窑炉与堆场（火点清单可直接交办）、散煤替代、'
             '重卡运输结构调整</td></tr>'
             '<tr><td><b>区域传输</b></td><td>太行山前整条城市带</td>'
             '<td>地形落差 1283 m/27 km；与邯郸、邢台、汾渭平原同处一个通道</td>'
             '<td>安阳—邯郸—邢台跨省联防、汾渭平原与豫北协同；'
             '单市减排效果会被上风向抵消</td></tr>'
             '</table>'
             '<div class="note">一句话：<b>用 PM2.5 排名只能看出"哪里脏"，'
             '用 SO₂ 季节比才能看出"哪里在持续排"</b>。'
             '前者适合考核，后者适合找源 —— '
             '而火点清单只覆盖后者中的"有热异常"那一部分。</div></div>')

    h.append('<footer>'
             '数据来源：中国环境监测总站国控点（经 quotsoft.net 逐小时归档，免 key）· '
             'Sentinel-5P TROPOMI L3（S5P-PAL）· open-elevation（SRTM 90m）<br>'
             '方法：逐月取 1/11/21 日代表值 → 按市聚合国控点均值；'
             '冬夏比 = 11–2 月均值 ÷ 6–8 月均值；卫星 NO₂ 为 7 个月月均的市级中位<br>'
             '<b>边界声明</b>：SO₂ 冬夏比是"源的季节性特征"推断，不等于源解析结论；'
             '行业构成来自公开信息归纳，未经逐企业核实。'
             '济源国控点为新增站点（4122A/4123A），历史归档未覆盖，故未纳入逐月曲线。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "豫北豫西空气质量成因分析.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    for c, pm, so, n2, aq, r, w, s in rows[:8]:
        print("  %-8s PM2.5 %5.0f  SO2 %5.1f  NO2 %5.0f  AQI %5.0f  SO2冬夏比 %.2f" % (c, pm, so, n2, aq, r))


if __name__ == "__main__":
    main()
