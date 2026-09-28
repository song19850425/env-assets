# -*- coding: utf-8 -*-
"""小时序列看板（纯渲染层，无 DB / 网络依赖）。

存在的理由：项目一直在"采小时"，但小时数据此前只有三个原始出口
  ① data/air.db 的 station_hourly（要看只能连库）
  ② data/raw/<日期>/*.json（原始报文）
  ③ 云端 data-hourly/YYYY-MM-DD.jsonl（GitHub 上点开是 JSON 文本）
→ 没有任何"能直接看"的入口，等于"采了看不见"。本模块补上这一个口子。

设计约束（与全项目口径红线一致）：
  - 城市值按 HJ 663-2013 取点位平均，不取最差点位；
  - O₃-8h 是平台按**当前小时**推算的滑动值，不等于日最大 8 小时均值 → 图注必须标「当前值口径」；
  - 平台数据为未审核实时值 → 页面必须声明，且保留「AI草稿·未经审定」水印；
  - 不依赖任何 CDN / 外部 JS（折线自绘 SVG），离线与打印均可看。
"""
from datetime import datetime, timedelta

CITY_COLOR = {
    "安阳市": "#c0392b",
    "濮阳市": "#2b6cb0",
    "鹤壁市": "#2f6b4f",
    "新乡市": "#b3541e",
}
_FALLBACK = ["#c0392b", "#2b6cb0", "#2f6b4f", "#b3541e", "#7a4fa3", "#0f7b7b"]

METRICS = [
    ("aqi", "实时 AQI", "AQI", 0),
    ("pm25", "PM2.5", "μg/m³", 0),
    ("o3_8h", "O₃-8h（当前值口径）", "μg/m³", 0),
    ("wind_speed", "风速", "m/s", 1),
    ("blh", "边界层高度 BLH", "m", 0),
]


def _c(i, name):
    if name in CITY_COLOR:
        return CITY_COLOR[name]
    return _FALLBACK[i % len(_FALLBACK)]


def _hh(tp):
    s = str(tp)
    return s[11:16] if len(s) >= 16 else s


def _dd(tp):
    s = str(tp)
    return s[5:10] if len(s) >= 10 else s


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- 折线（自绘 SVG）
def _to_dt(tp):
    try:
        return datetime.strptime(str(tp), "%Y-%m-%dT%H:%M")
    except Exception:
        return None


def line_chart(series, xs, y_unit, height=240, width=980, note=""):
    """series: [(name, color, {tp: value})]；xs: 已排序的时点列表。

    X 轴按**真实时间**比例定位（不是按序号等距）：
    平台没有小时级历史接口，漏采是常态；若按序号等距画，10 小时的缺口会被压缩成
    与 1 小时相同的间距，看上去像连续序列 —— 那正好掩盖了本页要暴露的问题。
    同时在间隔 > 2 小时处**断开折线**，只保留真实的连续段。
    """
    pad_l, pad_r, pad_t, pad_b = 52, 14, 20, 46
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    vals = [v for _, _, d in series for tp, v in d.items() if v is not None and tp in xs]
    if not vals or not xs:
        return "<p class='sub2'>暂无数据。</p>"
    vmax = max(vals)
    vmin = 0.0
    vmax = vmax * 1.12 if vmax > 0 else 1.0

    t0 = _to_dt(xs[0])
    t1 = _to_dt(xs[-1])
    if t0 is None or t1 is None:
        return "<p class='sub2'>时点格式异常。</p>"
    span = max((t1 - t0).total_seconds() / 3600.0, 1.0)
    off = {tp: (_to_dt(tp) - t0).total_seconds() / 3600.0 for tp in xs if _to_dt(tp)}

    def X(tp):
        return pad_l + off[tp] / span * iw

    def Y(v):
        return pad_t + ih - (v - vmin) / (vmax - vmin) * ih

    g = ["<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;display:block' role='img'>" % (width, height, width)]
    # 日界竖线（让"漏了多久"有一眼可量的标尺）
    day = t0.replace(hour=0, minute=0)
    if day < t0:
        day = day + timedelta(days=1)
    while day <= t1:
        x = pad_l + (day - t0).total_seconds() / 3600.0 / span * iw
        g.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#f0e2c8' stroke-width='1'/>"
                 % (x, pad_t, x, pad_t + ih))
        g.append("<text x='%.1f' y='%d' font-size='9.5' fill='#b3541e' text-anchor='middle'>%s</text>"
                 % (x, pad_t + 10, day.strftime("%m-%d")))
        day = day + timedelta(days=1)
    # 水平网格 + Y 刻度
    for k in range(6):
        v = vmin + (vmax - vmin) * k / 5.0
        y = Y(v)
        g.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e8ece9' stroke-width='1'/>" % (pad_l, y, pad_l + iw, y))
        g.append("<text x='%d' y='%.1f' font-size='10.5' fill='#71807a' text-anchor='end'>%s</text>"
                 % (pad_l - 6, y + 3.5, ("%.1f" % v) if vmax < 10 else ("%.0f" % v)))
    g.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#c9d4cd' stroke-width='1'/>"
             % (pad_l, pad_t + ih, pad_l + iw, pad_t + ih))
    # 数据：点全画；线只在相邻间隔 ≤2h 时连（缺口断开，不假装连续）
    for name, color, d in series:
        pts = [(tp, d[tp]) for tp in xs if d.get(tp) is not None]
        if not pts:
            continue
        seg = []
        for i, (tp, v) in enumerate(pts):
            seg.append((X(tp), Y(v)))
            if i + 1 < len(pts) and (off[pts[i + 1][0]] - off[tp]) <= 2.0:
                continue
            if len(seg) >= 2:
                g.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='2' stroke-linejoin='round'/>"
                         % (" ".join("%.1f,%.1f" % p for p in seg), color))
            seg = []
        for tp, v in pts:
            g.append("<circle cx='%.1f' cy='%.1f' r='3.2' fill='%s' stroke='#fff' stroke-width='1'/>"
                     % (X(tp), Y(v), color))
    g.append("<text x='%d' y='%d' font-size='10.5' fill='#71807a'>%s</text>" % (pad_l, pad_t - 6, _esc(y_unit)))
    g.append("</svg>")
    legend = " ".join(
        "<span style='display:inline-block;margin-right:12px;font-size:12.4px;color:#41504a'>"
        "<i style='display:inline-block;width:16px;height:3px;background:%s;vertical-align:3px;margin-right:5px;border-radius:2px'></i>%s</span>"
        % (c, _esc(nm)) for nm, c, _ in series)
    out = "<div class='tscroll'>" + "".join(g) + "</div><div class='legend'>" + legend
    if note:
        out += " <span class='sub2'>" + note + "</span>"
    out += "</div>"
    return out


# ---------------------------------------------------------------- 覆盖网格
def coverage_grid(tp_counts, city_n):
    """tp_counts: {时点: {城市: 点位数}} → 日期 × 24h 网格，单元格显示该小时点位行数"""
    if not tp_counts:
        return "<p class='sub2'>暂无数据。</p>"
    tps = sorted(tp_counts)
    d0 = datetime.strptime(tps[0][:10], "%Y-%m-%d").date()
    d1 = datetime.strptime(tps[-1][:10], "%Y-%m-%d").date()
    have = {}
    for tp in tps:
        have[(tp[:10], int(tp[11:13]))] = tp_counts[tp]

    hdr = "".join("<th style='text-align:center;padding:3px 1px;font-size:10px'>%02d</th>" % h for h in range(24))
    rows = []
    d = d0
    while d <= d1:
        ds = d.strftime("%Y-%m-%d")
        cells = []
        for h in range(24):
            rec = have.get((ds, h))
            if not rec:
                cells.append("<td style='background:#fde2e2;color:#c98b8b;text-align:center;padding:3px 1px;"
                             "border-bottom:1px solid #f6eaea;font-size:10px' title='%s %02d:00 无数据'>·</td>" % (ds, h))
            else:
                tot = sum(rec.values())
                txt = "%d" % tot
                cells.append("<td style='background:#2f6b4f;color:#fff;text-align:center;padding:3px 1px;"
                             "font-size:10px;font-weight:600' title='%s %02d:00 ｜ 共 %d 条点位记录'>%s</td>"
                             % (ds, h, tot, txt))
        rows.append("<tr><td style='padding:3px 7px;font-size:11px;color:#41504a;white-space:nowrap'>%s</td>%s</tr>"
                    % (ds, "".join(cells)))
        d += timedelta(days=1)
    return ("<div class='tscroll'><table style='min-width:760px'><thead><tr>"
            "<th style='padding:3px 7px;font-size:11px'>日期 \\ 时</th>" + hdr +
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            "<div class='legend'>深绿格＝该小时已采，格内数字为该小时入库的<b>点位记录条数</b>"
            "（含四市国控点；采集到邻居城市时会更多）；<span style='color:#c98b8b'>淡红「·」＝该小时完全缺失</span>，"
            "平台无小时级历史接口，<b>缺失的小时永久无法回补</b>。</div>")


# ---------------------------------------------------------------- 主渲染
def render_hourly(hourly_rows, weather_rows, cities, generated_at=None, sample=True,
                  back_link=None):
    """hourly_rows: station_hourly 全量字典行；weather_rows: city_hourly_weather 全量字典行

    generated_at 必须写成「生成：YYYY-MM-DD HH:MM」形式 —— 云端每小时重跑，
    这个字段会被 index_pages.STAMP_RE 抹掉后再比对，否则每个整点都会因时间戳变化
    产生一次无意义提交（页脚因此不再重复出现生成时刻）。
    back_link：云端在 模块/hourly/ 下，传 "../index.html"；本机独立产物传 None。
    """
    now = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    cities = [c for c in cities] or []

    # 城市 × 时点 点位平均（HJ 663-2013）
    agg = {}
    tp_counts = {}
    for r in hourly_rows:
        tp, c = r.get("timepoint"), r.get("city")
        if not tp or c not in cities:
            continue
        tp_counts.setdefault(tp, {})
        tp_counts[tp][c] = tp_counts[tp].get(c, 0) + 1
        for k in ("aqi", "pm25", "o3_8h"):
            v = r.get(k)
            if v is None:
                continue
            agg.setdefault((c, k), {}).setdefault(tp, []).append(v)
    series_val = {}
    for (c, k), d in agg.items():
        series_val[(c, k)] = {tp: (sum(v) / len(v)) for tp, v in d.items()}

    wval = {}
    for r in (weather_rows or []):
        c, tp = r.get("city"), r.get("timepoint")
        if c not in cities or not tp:
            continue
        for k in ("wind_speed", "blh"):
            if r.get(k) is not None:
                wval.setdefault((c, k), {})[tp] = r[k]

    xs = sorted(tp_counts)

    # 统计
    n_hours = len(xs)
    if xs:
        t0 = datetime.strptime(xs[0], "%Y-%m-%dT%H:%M")
        t1 = datetime.strptime(xs[-1], "%Y-%m-%dT%H:%M")
        span_h = int((t1 - t0).total_seconds() // 3600) + 1
    else:
        span_h = 0
    cov = (100.0 * n_hours / span_h) if span_h else 0.0
    n_rec = sum(sum(v.values()) for v in tp_counts.values())

    def card(t, big, sub):
        return ("<div class='card'><div class='ct'><b>%s</b></div>"
                "<div class='big' style='font-size:24px;font-weight:700;color:#1f3b2c'>%s</div>"
                "<div class='sub2'>%s</div></div>" % (t, big, sub))

    cards = ("<div class='cards'>"
             + card("库内时点数", "%d" % n_hours, "窗口 %s ~ %s" % (_dd(xs[0]) + " " + _hh(xs[0]), _dd(xs[-1]) + " " + _hh(xs[-1])) if xs else "—")
             + card("小时覆盖率", "%.0f%%" % cov, "窗口共 %d 小时" % span_h)
             + card("点位记录", "%d" % n_rec, "四市国控点位小时值")
             + card("城市数", "%d" % len(set(c for v in tp_counts.values() for c in v)), "按 HJ 663 点位平均")
             + "</div>")

    # 折线
    charts = []
    for key, label, unit, dec in METRICS:
        s = []
        for i, c in enumerate(cities):
            d = (wval if key in ("wind_speed", "blh") else series_val).get((c, key))
            if d:
                s.append((c, _c(i, c), d))
        if not s:
            continue
        note = ""
        if key == "o3_8h":
            note = "⚠️ 平台按当前小时推算，非「日最大 8 小时滑动平均」，<b>只能作筛查信号</b>。"
        if key == "aqi":
            note = "城市值＝该时点四市国控点位 AQI 平均（HJ 663-2013）。"
        charts.append("<h2>%s</h2>%s" % (_esc(label), line_chart(s, xs, unit, note=note)))

    # 透视表：时点 × 城市 AQI
    th = "".join("<th>%s</th>" % _esc(c) for c in cities)
    trs = []
    for tp in reversed(xs):
        tds = []
        for c in cities:
            v = series_val.get((c, "aqi"), {}).get(tp)
            tds.append("<td>%s</td>" % ("—" if v is None else "%.0f" % v))
        trs.append("<tr><td>%s %s</td>%s</tr>" % (_dd(tp), _hh(tp), "".join(tds)))
    table = ("<div class='tscroll'><table><thead><tr><th>时点</th>" + th +
             "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>")

    stamp = ""
    if sample:
        stamp = "<div class='stamp'>AI草稿<br>未经审定</div>"

    html = []
    html.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    html.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    html.append("<title>豫北四市 · 小时序列看板 · %s</title><style>%s</style></head><body><div class='page'>"
                % (_dd(xs[-1]) if xs else "", CSS))
    html.append("<div class='hd'><div><h1>豫北四市大气 · 小时序列看板</h1>"
                "<div class='sub'>安阳 / 濮阳 / 鹤壁 / 新乡 ｜ 国控点位小时值 ｜ 生成：%s</div></div>%s</div>"
                % (now, stamp))
    html.append("<div class='note'><b>口径与来源（必读）</b><br>"
                "① 数据来自生态环境部全国城市空气质量实时发布平台（air.cnemc.cn:18007）的<b>未审核实时数据</b>，"
                "正式结论应以总站／省级审核后数据为准；<br>"
                "② 城市评价值按 <b>HJ 663-2013 点位平均法</b>计算，非最差点位；<br>"
                "③ <b>O₃-8h 为平台按当前小时推算值</b>，与「日最大 8 小时滑动平均」不是同一口径，仅作筛查；<br>"
                "④ 平台不提供小时级历史接口 —— <b>未采集的小时永久丢失、无法回补</b>，故本页同时呈现「采到了哪些小时」。</div>")
    html.append("<h2>一、采集覆盖（缺哪些小时一眼可见）</h2>" + coverage_grid(tp_counts, cities))
    html.append("<h2>二、关键指标</h2>" + cards)
    for i, ch in enumerate(charts):
        if i == 0:
            html.insert(len(html), "<h2>三、逐时趋势</h2>")
        html.append(ch)
    html.append("<h2>四、逐时城市 AQI 透视（点位平均）</h2>" + table)
    win = ("%s %s ~ %s %s" % (_dd(xs[0]), _hh(xs[0]), _dd(xs[-1]), _hh(xs[-1]))) if xs else "—"
    html.append("<div class='ft'>本页由自动化流水线按采集到的数据自动生成，未经人工审定，"
                "仅供技术交流参考，不作为行政决策或处罚依据。<br>"
                "数据区间 %s。折线 X 轴按<b>真实时间比例</b>定位、间隔超 2 小时即断开 —— "
                "漏采的小时在图上会留出空白，不会被伪装成连续序列；相应小时在覆盖网格中标为淡红「·」。"
                "平台不提供小时级历史接口，<b>缺失的小时永久无法回补</b>。</div>"
                % win)
    if back_link:
        html.append("<p style='margin-top:10px'><a href='%s' style='color:#1F5C45'>← 返回模块目录</a></p>"
                    % back_link)
    html.append("</div></body></html>")
    return "".join(html)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#eef2ef;color:#1f2b26;font-size:14px;line-height:1.7}
.page{max-width:1040px;margin:18px auto;background:#fff;border:1px solid #e3e8e4;border-radius:12px;padding:26px 30px}
.hd{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
 background:linear-gradient(135deg,#26523f,#3c7a5b);color:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.hd h1{font-size:21px;letter-spacing:.5px}
.hd .sub{font-size:12.5px;opacity:.9;margin-top:5px}
.stamp{flex:none;border:2px solid #ffd9d9;color:#ffd9d9;border-radius:8px;padding:5px 10px;
 font-size:12px;font-weight:600;text-align:center;line-height:1.35}
h2{font-size:15px;color:#1f3b2c;margin:22px 0 9px;border-left:4px solid #2f6b4f;padding-left:9px}
.note,.legend{background:#f6f8f4;border:1px solid #e2e8de;border-radius:9px;padding:11px 14px;font-size:12.8px;color:#41504a;margin:9px 0}
.note{background:#fdf7ea;border-color:#e8d6a8}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{border:1px solid #e3e8e4;border-radius:11px;padding:14px 15px;background:#fbfcfa}
.card .ct b{font-size:15px;color:#1f3b2c}
.sub2{font-size:11.8px;color:#71807a}
table{width:100%;border-collapse:collapse;font-size:12.8px}
th{background:#1f3b2c;color:#fff;padding:6px 8px;text-align:left;font-weight:500;white-space:nowrap}
td{padding:5px 8px;border-bottom:1px solid #eef1ee;white-space:nowrap}
tr:hover td{background:#f8faf8}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.ft{margin-top:18px;padding-top:11px;border-top:1px solid #e3e8e4;font-size:11.8px;color:#7c8a83}
@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.cards{grid-template-columns:1fr}.page{padding:18px 15px}}
@media print{
  body{background:#fff}
  .page{border:none;margin:0;max-width:none;padding:0}
  .hd{background:#26523f !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h2{page-break-after:avoid}
  .tscroll{overflow:visible}
}
"""
