# -*- coding: utf-8 -*-
"""交付层 V2：豫北四市大气研判日报（在 V1 一页纸风格上增强）。

相对静态原型 V2.0 的修正：
 1. 样本数动态统计（原版硬编码 20，实际 21，漏一个点位）
 2. 点位清单列为全量 AQI 降序（原版手挑 5 条，漏掉 137/133 两个更高值点位）
 3. 新增【双口径对照】——实时 AQI 与 24h 滑动均值/GB 3095 二级限值两套口径并列，
    避免把"当前高值"当成"超标"对外引用（本项目核心红线）
 4. 城市 AQI 按 HJ 663-2013 点位平均法计算，并列出"点位 AQI 平均""最差点位"作对照
 5. 成因研判每条挂可自动判别的指标，不再只有框架
 6. 补回 print 样式；移动端表格可横向滚动
 7. 标题不出现版本号（对外交付物惯例）
"""
from datetime import datetime

from calc.aqi_stats import aqi_level
from calc.brief import POLL_CN

GB = {"pm25_24h": 75, "pm10_24h": 150, "o3_8h": 160}


def chip(aqi):
    name, bg, fg = aqi_level(aqi)
    a = "—" if aqi is None else ("%.0f" % aqi)
    return "<span class='tag' style='background:%s;color:%s'>%s %s</span>" % (bg, fg, a, name)


def fmt(v, d=0):
    if v is None:
        return "—"
    return ("%.*f" % (d, v))


def _hh(tp, base_date=None):
    """'2026-09-26T07:00' → '07:00'；若晚于基准日则标「次日07:00」，避免与当日时刻混淆。

    基准日必须由调用方传入（数据时点的日期），不用 now() —— 报告可复算，
    不能因为"什么时候生成"而改变内容。
    """
    s = str(tp)
    hh = s[11:16]
    if base_date and s[:10] > base_date:
        return "次日" + hh
    return hh


def _hl(v, limit, unit=""):
    """超限值标红"""
    if v is None:
        return "—"
    if v > limit:
        return "<b class='bad'>%g%s</b>" % (v, unit)
    return "%g%s" % (v, unit)


def lv_tag(aqi):
    """只显示等级名的小标签（用在回顾/预报表里，数值另有列）"""
    name, bg, fg = aqi_level(aqi)
    return "<span class='tag' style='background:%s;color:%s'>%s</span>" % (bg, fg, name)


def _review_section(review, region_rev, cities):
    """一、日评价回顾 —— 早间日报的判据段（替代"用 07:00 瞬时帧下结构结论"）

    为什么放在最前面：早间瞬时帧系统性偏向 PM2.5 与"局地源"（臭氧未生成、
    夜间颗粒物累积、边界层最低），不能用来判污染结构。日评价口径才是可引用的。
    """
    if not review:
        return ""
    rows = ""
    for c in cities:
        r = review.get(c["city"])
        if not r:
            continue
        ref, anom = r["ref"], r["aqi_anom"]
        anom_txt = "—" if anom is None else "%+.0f" % anom
        anom_cls = "" if anom is None else ("bad" if anom > 0 else "ok")
        rows += ("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td>%s</td><td class='%s'>%s</td><td>%s</td><td>%s</td></tr>") % (
            c["city"][:2], ref["date"], chip(ref["aqi"]),
            (ref["primary"] or "—"),
            fmt(r["aqi_mean14"], 1), anom_cls, anom_txt,
            ("%s%%" % r["o3_share"]) if r["o3_share"] is not None else "—",
            r["over100_days"],
        )
    if not rows:
        return ""
    roll = ""
    if region_rev:
        roll = "<div class='note'>%s</div>" % region_rev["html"]
    return """
<h2>一、日评价回顾（判据段）</h2>
<div class="legend">本节用<b>平台日评价口径</b>（城市日 AQI / 首要污染物 / 24h 值），
是<b>可对外引用</b>的口径；与后半部分"实时口径"不是一回事。<b>距平</b>为评价日 AQI 减去
其<b>之前</b>近 14 天均值（被评价日不计入均值，避免自我包含压低距平）。</div>
%s
<div class="tscroll"><table>
<tr><th>城市</th><th>评价日</th><th>日 AQI</th><th>首要污染物</th>
<th>近14天<br>AQI均值</th><th>距平</th><th>近14天<br>臭氧首要占比</th><th>AQI&gt;100<br>天数</th></tr>
%s</table></div>
%s""" % (
        "<div class='legend'>数据滞后提示：平台日评价数据通常晚一天发布，"
        "本节评价日与实际「昨日」可能不一致，以表中<b>评价日</b>列为准。</div>",
        rows, roll,
    )


def _forecast_section(forecast, bias, cities, timepoint):
    """二、未来 24 小时模式趋势 —— 预报段（此前完全缺失，管控决策缺依据）

    ⚠️ 本节的写法是刻意的：**不给"预测 AQI 会是多少"，只给"哪几个小时相对更高"**。
    原因见下表"模式偏差自检"——2026-09-25 实测：模式 PM2.5 比实测同期高 11%~328%、
    臭氧低约一半。未做 MOS 订正前，绝对值引用会误导（把模式高估读成"明天要污染"）。
    """
    if not forecast:
        return ""
    base = str(timepoint)[:10]
    rows = ""
    for c in cities:
        f = forecast.get(c["city"])
        if not f:
            continue
        rows += ("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td>%s</td><td>%s</td><td>%s</td></tr>") % (
            c["city"][:2],
            fmt(f["peak_aqi"], 0) + "（%s）" % _hh(f["peak_tp"], base),
            lv_tag(f["peak_aqi"]),
            f["primary_main"] + ("（%d/%d 小时）" % (f["primary_main_n"], f["n"]) if f["n"] else ""),
            f["over100_hours"],
            fmt(f["o3_8h_day_max"], 0) if f["o3_8h_day_max"] is not None else "—",
            "、".join(_hh(t, base) for t in f["window_tps"]) if f["window_tps"] else "—",
        )
    if not rows:
        return ""

    bias_html = ""
    if bias:
        brows = ""
        for b in bias["rows"]:
            if b["obs"] is None or b["mod"] is None:
                continue
            ratio = (b["mod"] / b["obs"]) if b["obs"] else None
            brows += "<tr><td>%s</td><td>%s</td><td>%s</td><td class='%s'>%s</td></tr>" % (
                b["city"][:2], fmt(b["obs"], 1), fmt(b["mod"], 1),
                "bad" if (ratio or 1) > 1.3 else "ok",
                ("%.2f×" % ratio) if ratio else "—")
        if brows:
            bias_html = """
<div class="legend"><b>模式偏差自检</b>（数据时点同小时，实测城市均值 vs 模式预报值）：
未订正的模式值在本市存在<b>系统性偏差</b>，故本节的 AQI 数值<b>只可用于比较时段高低，
不可作为"明天 AQI 会是多少"的预测</b>。</div>
<div class="tscroll"><table>
<tr><th>城市</th><th>PM2.5 实测</th><th>PM2.5 模式</th><th>模式/实测</th></tr>
%s</table></div>""" % brows

    return """
<h2>二、未来 24 小时模式趋势（未订正，仅供时段参考）</h2>
<div class="note"><b>口径声明：</b>本节为 <b>CAMS 全球模式预报值</b>（ECMWF 哥白尼大气监测服务，
约 40 km 网格、城市尺度），<b>不是国控点位本地实测</b>；已发现对本市存在系统性偏差（见下"模式偏差自检"）。
用途仅限：<b>判断未来 24 小时内哪几个小时相对更高、峰值大致出现在几点</b>。
<b>禁止</b>将其绝对值作为达标判据、考核依据或对外正式结论；与实测冲突时以实测为准。</div>
<div class="tscroll"><table>
<tr><th>城市</th><th>模式峰值 AQI<br>（时段）</th><th>模式等级</th><th>模式主导污染物</th>
<th>模式 AQI&gt;100<br>小时数</th><th>模式 O₃-8h<br>当日最大</th><th>相对高值时段</th></tr>
%s</table></div>
%s
<div class="legend">O₃-8h 为模式逐时 O₃ 的 8 小时滑动平均（窗口不足 8 小时记缺测，不补零），
口径与 GB 3095-2012 的 O₃-8h 一致。模式对本地臭氧存在明显低估（见自检），
因此<b>不能用"模式未超 160"推断"不会臭氧超标"</b>。</div>""" % (rows, bias_html)


def render_v2(cities, region, causes, action_list, timepoint, cfg, evidence, winds=None,
              review=None, region_rev=None, forecast=None, bias=None):
    winds = winds or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sample = cfg.get("sample", True)
    stamp = "<div class='stamp'>AI 草稿<br>未经审定</div>" if sample else ""

    total_n = sum(c["n"] for c in cities)
    total_rt = sum(c["exceed_rt_cnt"] for c in cities)
    total_dy = sum(c["exceed_dy_cnt"] for c in cities)
    worst = max(cities, key=lambda c: c["aqi_max"] or 0)

    # ── 总体研判 ──
    # 实时高值的描述必须由数据决定，不能写死。原版固定写"整体呈普遍抬升"，
    # 在四市均为"良"（如 17:00 帧 55–92）时就与实际不符 —— 属于凭空下结论。
    rt_max = max((c["aqi_rt"] or 0) for c in cities)
    if total_rt:
        rt_desc = "其中 <b>%d 个</b>已高于 100，按高值点位清单跟进" % total_rt
    elif rt_max > 80:
        rt_desc = "均在 100 以下，但最高已到 %.0f，属需留意的高位良" % rt_max
    else:
        rt_desc = "四市均处优良水平，无高值点位"

    # O₃ 只要出现筛查命中，就必须说明口径差异 —— 否则读者会当成"当日已超标"
    _o3_screen = any(h[3] for c in cities for e in c["exceed_dy"] for h in e["hits"])
    o3_note = (
        "<p class='legend'>口径提示：上表中 O₃-8h 一项是用平台<b>当前 8 小时值</b>比对日均限值，"
        "属<b>筛查口径</b>；GB 3095-2012 对该项的评价对象是<b>日最大 8 小时滑动平均</b>，"
        "二者不可混用。当日是否真的超标，须待当日数据完整后复核。</p>"
    ) if _o3_screen else ""
    # 早间帧提示：本项目的实测规律是"日变化 > 日际变化"，单帧不足以支撑结构结论。
    # 07:00 帧臭氧尚未生成、PM2.5 处夜间累积峰值、边界层最低 —— 此时判出的
    # "首要污染物/成因类型"若不加提示，会被读成全天结论（曾把 07:00 的 PM2.5 判读
    # 直接写成全天结构，当日午后实际全部转良、首要转为臭氧）。
    _hh_int = int(str(timepoint)[11:13]) if len(str(timepoint)) >= 13 else 12
    morning_note = (
        "<p class='legend'><b>帧时点提示：</b>本页实况取自 <b>%s</b> 的<b>早间瞬时帧</b>。"
        "此时臭氧尚未生成（O₃-8h 常整层缺测）、PM2.5 处于夜间累积峰值、边界层高度接近全天最低，"
        "因此本节的<b>首要污染物与成因类型不代表全天结构</b>。"
        "全天结构请以「一、日评价回顾」为准，未来趋势请以「二、未来 24 小时模式趋势」为准。</p>"
        % str(timepoint)[11:16]
    ) if _hh_int < 10 else ""

    verdict = (
        "<p><b>实时口径</b>：%d 个点位中有 <b>%d 个</b>当前 AQI&gt;100，四市实时城市 AQI "
        "由高到低为 %s，%s。</p>"
        "<p><b>日均（达标）口径</b>：改用平台 24h 滑动均值对照 GB 3095-2012 二级限值后，"
        "超标点位仅 <b>%d 个</b>——%s。"
        "两套口径差异显著，引用时须注明所用口径。</p>"
        "%s%s<p>%s</p>"
    ) % (
        total_n, total_rt,
        "、".join("%s %.0f" % (c["city"][:2], c["aqi_rt"]) for c in
                  sorted(cities, key=lambda c: c["aqi_rt"] or 0, reverse=True)),
        rt_desc,
        total_dy,
        ("；".join("<b>%s %s</b>（%s）" % (
            e["city"][:2], e["station"],
            "、".join("%s %g μg/m³ &gt; %d" % (h[0], h[1], h[2]) for h in e["hits"]))
            for e in [x for c in cities for x in c["exceed_dy"]]) if total_dy else "全部点位日均口径达标"),
        morning_note,
        o3_note,
        region["text"].replace("**", ""),
    )

    # ── 四市卡片 ──
    cards = ""
    for c in cities:
        cards += """
<div class="card">
  <div class="ct"><b>%s</b><span class="badge">%d 个点位</span></div>
  <div class="big">%s</div>
  <div class="sub2">实时城市 AQI（HJ 663 点位平均）｜ 日均口径 %s</div>
  <div class="kv">
    <div><label>首要污染物</label><b>%s</b></div>
    <div><label>当前高值点位</label><b>%d/%d</b></div>
    <div><label>日均超标点位</label><b class="%s">%d</b></div>
    <div><label>最差点位</label><b>%s</b></div>
  </div>
</div>""" % (
            c["city"], c["n"], chip(c["aqi_rt"]), chip(c["aqi_dy"]),
            POLL_CN.get(c["poll_rt"], c["poll_rt"] or "—"), c["exceed_rt_cnt"], c["n"],
            "bad" if c["exceed_dy_cnt"] else "ok", c["exceed_dy_cnt"],
            "%s %.0f" % (c["worst"]["station_name"], c["worst"]["aqi"]) if c["worst"] else "—",
        )

    # ── 双口径对照（P0 核心）──
    cmp_rows = ""
    for c in cities:
        cmp_rows += """<tr>
<td>%s</td>
<td>%s</td><td>%s</td><td>%s</td>
<td>%s</td><td>%s</td>
<td>%s / %s</td>
<td>%s（%s）</td></tr>""" % (
            c["city"][:2],
            fmt(c["aqi_rt"], 1), fmt(c["aqi_dy"], 1), fmt(c["point_avg_aqi"], 1),
            _hl(c["pm25_mean"], -1), _hl(c["pm25_24h_mean"], GB["pm25_24h"]),
            _hl(c["pm10_mean"], -1), _hl(c["pm10_24h_mean"], GB["pm10_24h"]),
            (("超 %d" % c["exceed_dy_cnt"]) if c["exceed_dy_cnt"] else "达标"),
            ("、".join(sorted({e["station"] for e in c["exceed_dy"]})) if c["exceed_dy"] else "—"),
        )

    # ── 全量点位清单（AQI 降序）──
    # 超限标签统一取自 exceed_dy（与上方研判同一判据）：
    # 原版这里另写一套只判 PM2.5/PM10 的逻辑，导致 O₃ 命中的点位在表里没有标记，
    # 与研判段的超标个数对不上。
    dy_map = {}
    for c in cities:
        for e in c["exceed_dy"]:
            dy_map[(c["city"], e["station"])] = "、".join(h[0] for h in e["hits"])

    detail = ""
    for c in cities:
        for s in c["stations"]:
            warn = " class='warn'" if (s["aqi"] or 0) > 100 else ""
            lab = dy_map.get((c["city"], s["station_name"]))
            mark = "<span class='dyex'>超日均限值·%s</span>" % lab if lab else ""
            detail += ("<tr%s><td>%s</td><td>%s%s</td><td>%s</td><td>%s</td>"
                       "<td>%s</td><td>%s</td><td>%s</td></tr>") % (
                warn, c["city"][:2], s["station_name"], mark, chip(s["aqi"]),
                fmt(s["pm25"]), _hl(s["pm25_24h"], GB["pm25_24h"]),
                _hl(s["pm10"], -1), _hl(s["o3_8h"], -1))

    # ── 三项污染物 ──
    pol = ""
    for c in cities:
        pol += """<tr><td>%s</td>
<td>%s</td><td>%s</td>
<td>%s</td><td>%s</td>
<td>%s</td><td>%s</td></tr>""" % (
            c["city"][:2],
            fmt(c["pm25_mean"]), fmt(c["pm25_24h_mean"], 1),
            fmt(c["pm10_mean"]), fmt(c["pm10_24h_mean"], 1),
            fmt(c["o3_8h_mean"], 1), fmt(c["o3_8h_max"], 1),
        )

    # ── 成因研判 ──
    cause = ""
    for cc, cf in zip(cities, causes):
        items = "".join("<li>%s</li>" % r.replace("**", "") for r in cf["reasons"])
        cause += "<div class='block'><div class='bh'>%s</div><ul>%s</ul></div>" % (cc["city"], items)

    # ── 行动任务 ──
    acts = ""
    for a in action_list:
        items = "".join("<li>%s</li>" % x for x in a["acts"])
        acts += "<div class='block'><div class='bh'>%s</div><ul>%s</ul></div>" % (a["city"], items)

    # ── 气象综合结论（并入今日研判）──
    wind_para = ""
    if winds:
        lv_rank = {"不利": 0, "较不利": 1, "一般": 2, "有利": 3, "待核": 1}
        lvs = [(c["city"], (winds.get(c["city"]) or {}).get("level", "待核")) for c in cities]
        bad = [x for x in lvs if lv_rank.get(x[1], 1) <= 0]
        verdicts = [(winds.get(c["city"]) or {}).get("transport", {}).get("verdict", "") for c in cities]
        n_tp = sum(1 for v in verdicts if v == "存在输入性传输迹象")
        n_no = sum(1 for v in verdicts if v == "输入性传输证据不足")
        if bad:
            wind_para += ("<p><b>气象条件</b>：%s 的扩散条件判为「不利」——%s。"
                          "低风速叠加低边界层，污染物水平输送与垂直扩散同时受阻，"
                          "是本次四市同步抬升的直接气象成因。</p>"
                          ) % ("、".join(x[0][:2] for x in bad),
                               "；".join("%s 风速 %s m/s、边界层 %s m"
                                        % (x[0][:2],
                                           (winds.get(x[0]) or {}).get("wind_speed"),
                                           "%.0f" % (winds.get(x[0]) or {}).get("blh", 0))
                                        for x in bad))
        else:
            wind_para += "<p><b>气象条件</b>：各市扩散条件未达不利等级，气象对污染的贡献有限。</p>"
        if n_tp:
            wind_para += ("<p><b>传输研判</b>：%d 个城市的上风向城市浓度高于本地，"
                          "存在输入性传输迹象，需结合轨迹模型复核。</p>" % n_tp)
        elif n_no:
            wind_para += ("<p><b>传输研判</b>：%d 个城市的上风向城市浓度并不高于本地，"
                          "<b>不支持</b>输入性传输为主导，本次高值更符合静稳条件下的本地累积与二次转化；"
                          "风向扇形内无已纳入城市的市，存在省外传输盲区，需扩充周边城市后方可定论。</p>" % n_no)

    verdict += wind_para   # 气象结论并入"今日研判"

    ev = "".join("<li>%s</li>" % e for e in evidence)

    # 回顾段与预报段在模板最前面 —— 顺序刻意：先判据（日评价/基线）→ 再看趋势 → 最后看瞬时实况
    review_sec = _review_section(review, region_rev, cities)
    fcst_sec = _forecast_section(forecast, bias, cities, timepoint)

    # 顶部口径声明随"实际有哪些章节"自适应：云端若拿不到日历史/预报，
    # 页面不能继续声称"本页先回顾昨日再报未来"—— 文案与内容不符比少一节更糟。
    if review_sec and fcst_sec:
        note_html = ("本页区分三套口径：<b>日评价口径</b>（平台城市日 AQI，<b>可对外引用</b>）／"
                     "<b>实时口径</b>（平台当前小时浓度，反映瞬时高值）／"
                     "<b>模式预报口径</b>（CAMS 全球模式，仅供趋势）。"
                     "引用结论前请确认口径。本页顺序刻意如此："
                     "<b>先回顾昨日与近 14 天基线 → 再看未来 24 小时趋势 → 最后看当前实况</b>——"
                     "因为单帧瞬时值不足以支撑污染结构结论（见「三、今日实况研判」的帧时点提示）。")
    elif review_sec or fcst_sec:
        which = "回顾" if review_sec else "趋势"
        note_html = ("本页区分三套口径：<b>日评价口径</b>（可对外引用）／<b>实时口径</b>（当前小时浓度）／"
                     "<b>模式预报口径</b>（CAMS，仅供趋势）。本次<b>未能取得全部补充数据</b>，"
                     "仅呈现%s相关章节，其余章节按数据可得性自动省略（不影响已列结论的有效性）。" % which)
    else:
        note_html = ("本页区分两套口径：<b>实时口径</b>（平台当前小时浓度，反映瞬时高值）与"
                     "<b>日均（达标）口径</b>（24h 滑动均值对 GB 3095-2012 二级限值，用于达标判定）。"
                     "本次<b>未取得日评价历史与模式预报数据</b>，故无回顾段与预报段；"
                     "引用结论前请确认口径。")

    # ── 气象条件与区域传输 ──
    LEVEL_CLS = {"不利": "lv-bad", "较不利": "lv-warn", "一般": "lv-mid", "有利": "lv-ok", "待核": "lv-mid"}
    wind_rows, wind_notes = "", ""
    for c in cities:
        w = winds.get(c["city"]) or {}
        if not w:
            continue
        lv = w.get("level", "待核")
        rh = w.get("rh")
        rh_txt = "—" if rh is None else "%.0f%%" % rh
        if w.get("rh_flag"):
            rh_txt += "<span class='dyex'>高湿静稳</span>"
        wind_rows += """<tr>
<td>%s</td>
<td>%s</td><td>%s（%s）</td><td>%s</td><td>%s</td><td>%s</td>
<td><span class="lv %s">%s</span></td></tr>""" % (
            c["city"][:2],
            "—" if w.get("wind_speed") is None else "%.1f" % w["wind_speed"],
            "—" if w.get("wind_dir") is None else "%.0f°" % w["wind_dir"],
            w.get("wind_dir_cn", "—"),
            "—" if w.get("wind_gust") is None else "%.1f" % w["wind_gust"],
            "—" if w.get("blh") is None else "%.0f" % w["blh"],
            rh_txt, LEVEL_CLS.get(lv, "lv-mid"), lv,
        )
        tp = w.get("transport") or {}
        lines = "".join("<li>%s</li>" % x.replace("**", "") for x in (tp.get("lines") or []))
        wind_notes += ("<div class='block'><div class='bh'>%s · 扩散条件 <span class='lv %s'>%s</span>"
                       "｜ 传输研判：%s</div><ul>%s<li>%s</li></ul></div>") % (
            c["city"], LEVEL_CLS.get(lv, "lv-mid"), lv,
            tp.get("verdict", "待核"), lines, w.get("desc", ""))

    wind_section = ""
    if wind_rows:
        wind_section = """
<h2>八、气象条件与区域传输</h2>
<div class="tscroll"><table>
<tr><th>城市</th><th>风速<br>(m/s)</th><th>风向<br>(来向)</th><th>阵风<br>(m/s)</th>
<th>边界层高度<br>(m)</th><th>相对湿度</th><th>扩散条件</th></tr>
%s</table></div>
<div class="legend">气象数据来自 Open-Meteo（免密钥模式产品，城市尺度），时点对齐 %s。
风速低于 %.1f m/s 判静稳、边界层低于 %.0f m 判垂直扩散受限、湿度≥80%% 且低风速标注"高湿静稳"——
以上均为<b>经验阈值</b>，非国家标准限值。传输研判<b>仅在已纳入的 %d 个城市内成立</b>，
省外上风向城市未纳入，存在盲区。</div>
%s""" % (wind_rows, timepoint, 2.0, 300.0, len(cities), wind_notes)

    return """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>豫北四市大气研判日报 · %s</title><style>%s</style></head><body><div class="page">
<div class="hd">
  <div>
    <h1>豫北四市大气研判日报</h1>
    <div class="sub">安阳 · 濮阳 · 鹤壁 · 新乡 ｜ 数据时点：%s ｜ 生成：%s</div>
  </div>%s
</div>

<div class="note">%s</div>

%s
%s
<h2>三、今日实况研判</h2>
<div class="verdict">%s</div>

<h2>四、四市核心指标</h2>
<div class="cards">%s</div>

<h2>五、双口径对照（口径差异是引用结论的关键）</h2>
<div class="tscroll"><table>
<tr><th>城市</th><th>实时城市<br>AQI</th><th>日均城市<br>AQI</th><th>点位 AQI<br>平均</th>
<th>PM2.5<br>实时</th><th>PM2.5·24h<br>(限 75)</th><th>PM10 实时/24h<br>(限 150)</th><th>日均口径判定</th></tr>
%s</table></div>
<div class="legend">注：城市 AQI 按 HJ 663-2013「点位平均法」计算（先取各点位浓度算术平均，再算 IAQI 取最大）。
「点位 AQI 平均」与「最差点位 AQI」列为对照，不代表城市评价值。红色为该值超过 GB 3095-2012 二级限值。</div>

<h2>六、点位异常清单（全量 %d 个点位，按当前 AQI 降序）</h2>
<div class="tscroll"><table>
<tr><th>城市</th><th>点位</th><th>实时 AQI</th><th>PM2.5</th><th>PM2.5·24h</th><th>PM10</th><th>O₃-8h</th></tr>
%s</table></div>
<div class="legend">底色标出为当前 AQI&gt;100 的点位；PM2.5·24h 加粗表示超过 24h 滑动均值对应的二级限值 75 μg/m³。
本清单为全量列示，不做人工挑选，以保证排序可复核。</div>

<h2>七、核心污染物（点位平均浓度，μg/m³）</h2>
<div class="tscroll"><table>
<tr><th>城市</th><th>PM2.5 实时</th><th>PM2.5·24h</th><th>PM10 实时</th><th>PM10·24h</th><th>O₃-8h 均值</th><th>O₃-8h 峰值</th></tr>
%s</table></div>

%s

<h2>九、污染成因研判框架</h2>
<div class="legend">以下每条均挂可自动复算的判别指标；指标不足时不出结论。PM10/PM2.5≥%.1f 判扬尘型，
同城点位极差比≥%.1f 判局地特征，四市均值极差比≤%.2f 判区域同步。</div>
%s

<h2>十、管控行动任务</h2>
<div class="legend">措施必须与<b>污染结构</b>匹配（判据见「一、日评价回顾」）：
臭氧主导期控 <b>VOCs / NOx 前体物</b>，颗粒物主导期控 <b>扬尘 / 燃烧源</b>。
结构错配的典型症状是「措施很忙、指标不动」。任务中的点位/时段均可由前文数据复算。</div>
%s

<div class="audit">
  <div class="ah">数据可信度与审定状态</div>
  <ul>%s</ul>
  <div class="sign">
    <span class="pill">审定状态：<b>AI 草稿 · 未经人工审定</b></span>
    <span class="pill">有效期：仅反映 %s 时点状况</span>
  </div>
</div>

<div class="ft">
空气质量数据来源：%s<br>
气象数据来源：%s<br>
本页由自动化流水线生成%s，结论段须经专家审定后方可对外使用；不作为行政处罚或行政决策依据。<br>
大气管家 · 大气环境第三方服务 · %s
</div>
</div></body></html>""" % (
        timepoint, CSS, timepoint, now, stamp,
        note_html,
        review_sec, fcst_sec,
        verdict, cards, cmp_rows,
        total_n, detail, pol,
        wind_section,
        2.0, 1.5, 1.25,
        cause, acts, ev, timepoint,
        cfg.get("source", ""), cfg.get("weather_source", ""),
        "（样报演示）" if sample else "", now[:10],
    )


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
.note,.legend,.verdict{background:#f6f8f4;border:1px solid #e2e8de;border-radius:9px;padding:11px 14px;font-size:12.8px;color:#41504a;margin:9px 0}
.note{background:#fdf7ea;border-color:#e8d6a8}
.legend{margin-top:7px}
.verdict p{margin:5px 0}
.verdict b{color:#1f3b2c}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{border:1px solid #e3e8e4;border-radius:11px;padding:14px 15px;background:#fbfcfa}
.card .ct{display:flex;justify-content:space-between;align-items:center}
.card .ct b{font-size:15px;color:#1f3b2c}
.badge{font-size:11.5px;color:#6b7a72;border:1px solid #dfe5e0;background:#fff;border-radius:20px;padding:1px 9px}
.big{margin:9px 0 3px}
.sub2{font-size:11.8px;color:#71807a}
.kv{margin-top:9px;border-top:1px dashed #e2e8de;padding-top:8px;font-size:12.4px}
.kv>div{display:flex;justify-content:space-between;margin:3px 0}
.kv label{color:#71807a}
.tag{padding:1px 8px;border-radius:6px;font-weight:600;font-size:12.5px;white-space:nowrap}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:12.8px;min-width:640px}
th{background:#1f3b2c;color:#fff;padding:7px 8px;text-align:left;font-weight:500;white-space:nowrap}
td{padding:6px 8px;border-bottom:1px solid #eef1ee;white-space:nowrap}
tbody tr:hover,table tr:hover td{background:#f8faf8}
tr.warn td{background:#fff7ea}
.bad{color:#c0392b}.ok{color:#2f7a4f}
.dyex{display:inline-block;margin-left:6px;font-size:10.5px;color:#b3541e;background:#fdf0e2;
 border:1px solid #f0d5b0;border-radius:4px;padding:0 5px;vertical-align:1px}
.lv{display:inline-block;padding:1px 8px;border-radius:5px;font-size:12px;font-weight:600;white-space:nowrap}
.lv-bad{background:#fde2e2;color:#a32d2d}
.lv-warn{background:#fff0e0;color:#a85a00}
.lv-mid{background:#fdf9dc;color:#8a6d00}
.lv-ok{background:#e8f5e0;color:#2e6b0f}
.block{border:1px solid #e3e8e4;border-radius:10px;padding:11px 14px;margin:8px 0;background:#fbfcfa}
.bh{font-weight:600;color:#1f3b2c;font-size:13.5px;margin-bottom:5px}
.block ul{margin:0;padding-left:18px}
.block li{font-size:12.8px;margin:3px 0;color:#41504a}
.audit{border:1px solid #d9e3dc;border-left:4px solid #2f6b4f;border-radius:9px;padding:13px 16px;margin:20px 0 6px;background:#f8faf8}
.ah{font-weight:700;color:#1f3b2c;margin-bottom:6px}
.audit ul{margin:0;padding-left:18px}
.audit li{font-size:12.6px;color:#41504a;margin:3px 0}
.sign{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.pill{font-size:12px;border:1px solid #cfe0d6;background:#fff;border-radius:20px;padding:3px 11px;color:#2f5b45}
.pill b{color:#b3541e}
.ft{margin-top:18px;padding-top:11px;border-top:1px solid #e3e8e4;font-size:11.8px;color:#7c8a83}
@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.cards{grid-template-columns:1fr}.page{padding:18px 15px}}
@media print{
  body{background:#fff}
  .page{border:none;margin:0;max-width:none;padding:0}
  .hd{background:#26523f !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h2{page-break-after:avoid}
  table,.block,.audit,.card{page-break-inside:avoid}
  .tscroll{overflow:visible}
  table{min-width:0;font-size:11px}
}
"""
