# -*- coding: utf-8 -*-
"""周期报告构建：周报/月报的口径、取数与渲染（本地与云端共用同一份）

为什么要抽出来
--------------
同一份口径（哪 7 天算"本期"、月报窗口怎么标注）如果本地 run_period.py 和云端
report_cloud_period.py 各写一遍，迟早出现"网页上那版和本机那版不一样"，
而且没人能一眼看出哪份才是对的。这里放唯一一份，两边都调它。

口径（与第三方周报样例对齐）
--------------------------
  周报 = 最近 7 个完整日，环比其前 7 天
  月报 = 优先自然月口径（上一个完整自然月，取本地库 data/air.db 逐日值）；
         库里没有该月或天数明显不足时，退回平台 14 天窗口并如实标注
  完整日 = 平台历史接口返回的最后一天（当天为进行中，不纳入）
"""
import os
import sqlite3
from datetime import datetime, timedelta

KIND_LABEL = {"weekly": "周报", "monthly": "月报"}
KIND_PREFIX = {"weekly": "大气管家豫北周报", "monthly": "大气管家豫北月报"}
KIND_TITLE = "豫北四市环境空气质量%s（安阳 · 濮阳 · 鹤壁 · 新乡）"


def _db_month(cities, today, db_path=None):
    """取"上一个完整自然月"的本地库逐日值（月报整月口径）。

    返回 None 表示该月数据不可用（无库 / 天数不足）→ 调用方退回平台 14 天窗口。
    返回 {rows: {city: [...]}, start, end, prev_start, prev_end, counts}
      rows 内同时含上月（环比基期）日值，但**仅当上月也是完整自然月**才并入，
      否则宁可不出环比，也不拿残缺基期算出一个假的升降幅。
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = db_path or os.path.join(base, "data", "air.db")
    if not os.path.exists(db):
        return None

    this_first = today.replace(day=1)
    end = this_first - timedelta(days=1)          # 上月最后一天
    start = end.replace(day=1)                    # 上月 1 日
    need = (end - start).days + 1
    p_end = start - timedelta(days=1)
    p_start = p_end.replace(day=1)
    p_need = (p_end - p_start).days + 1

    sql = ("SELECT date,city,aqi,quality,primary_pollutant,pm25,pm10,"
           "so2,no2,co,o3_8h FROM city_daily WHERE city=? AND date>=? AND date<=? "
           "ORDER BY date")

    def _rows_of(con, city, d0, d1):
        out = []
        for r in con.execute(sql, (city, d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))):
            out.append({"date": r[0], "city": r[1], "aqi": r[2], "quality": r[3],
                        "primary": r[4] or "—", "pm25": r[5], "pm10": r[6],
                        "so2": r[7], "no2": r[8], "co": r[9], "o3_8h": r[10]})
        return out

    try:
        con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        cur_rows, prev_rows = {}, {}
        for c in cities:
            cur_rows[c] = _rows_of(con, c, start, end)
            prev_rows[c] = _rows_of(con, c, p_start, p_end)
        con.close()
    except Exception:
        return None

    counts = {c: len(cur_rows[c]) for c in cities}
    # 任一城市缺 3 天以上 → 整月口径不成立（缺城/缺日会直接改变"优良率"分母）
    if min(counts.values()) < need - 2:
        return None
    prev_ok = all(len(prev_rows[c]) >= p_need for c in cities)

    rows = {}
    for c in cities:
        merged = (prev_rows[c] if prev_ok else []) + cur_rows[c]
        rows[c] = merged
    return {"rows": rows, "start": start, "end": end,
            "prev_start": p_start, "prev_end": p_end,
            "counts": counts, "need": need, "prev_ok": prev_ok}


def build_period(kind, cfg, fetch=None, today=None):
    """构建一期周期报告，返回 dict。

    kind  : weekly | monthly
    cfg   : 档案配置（需含 cities / sample / client_name / source）
    fetch : 城市名 → 日值列表的函数（默认走平台历史接口；云端传镜像副本）
    today : 生成日（默认当前时间；显式传入便于测试与复现）

    返回：{kind, fname, title, period_desc, window_note, stats, html, start, end}
    """
    if fetch is None:
        from ingest.fetch_history import fetch_daily as fetch
    today = today or datetime.now()
    cities = list(cfg["cities"])

    # 月报优先走自然月口径（本地库）。云端镜像没有 data/air.db → 自动退回平台窗口。
    cal = _db_month(cities, today) if kind == "monthly" else None

    all_rows, failed = {}, []
    if cal:
        all_rows = cal["rows"]
        print("[口径] 自然月 %s ~ %s（本地库 city_daily，四市有效 %s 天）" % (
            cal["start"].strftime("%Y-%m-%d"), cal["end"].strftime("%Y-%m-%d"),
            "/".join(str(n) for n in [cal["counts"][c] for c in cities])))
    else:
        for c in cities:
            try:
                rows = fetch(c)
                if not rows:
                    failed.append((c, "接口返回空"))
                else:
                    all_rows[c] = rows
            except Exception as e:
                failed.append((c, str(e)[:80]))
        if failed:
            # 宁可整期不出，也不出一期"少了一个城市"的报告 ——
            # 周期报告是对外材料，缺城会直接改变结论（四市对比变三市）。
            raise RuntimeError("日值取数失败 %d/%d 城：%s" % (len(failed), len(cities), failed))

    if kind == "weekly":
        # 历史接口返回最近 14 天（09-09 起固定窗口），取库内实际可得日期
        have = [r["date"] for r in all_rows[cities[0]]]
        last_complete = have[-1]
        d_last = datetime.strptime(last_complete, "%Y-%m-%d")
        cur_start, cur_end = d_last - timedelta(days=6), d_last
        prev_start, prev_end = d_last - timedelta(days=13), d_last - timedelta(days=7)
        period_desc = "%s ~ %s（环比基期 %s ~ %s）" % (
            cur_start.strftime("%Y年%m月%d日"), cur_end.strftime("%Y年%m月%d日"),
            prev_start.strftime("%m月%d日"), prev_end.strftime("%m月%d日"))
        fname = "大气管家豫北周报_%s_to_%s.html" % (cur_start.strftime("%m%d"), cur_end.strftime("%m%d"))
        window_note = ""
    elif cal:
        # 自然月整月口径（对外交付的主力形态）
        cur_start, cur_end = cal["start"], cal["end"]
        prev_start, prev_end = cal["prev_start"], cal["prev_end"]
        need = cal["need"]
        ns = [cal["counts"][c] for c in cities]
        nt = str(need) if min(ns) == max(ns) == need else "%d~%d" % (min(ns), max(ns))
        period_desc = "%s ~ %s（自然月 %d 天，本期有效 %s 天）" % (
            cur_start.strftime("%Y年%m月%d日"), cur_end.strftime("%Y年%m月%d日"), need, nt)
        fname = "大气管家豫北月报_%s.html" % cur_start.strftime("%Y-%m")
        prev_txt = ("环比基期 %s ~ %s（上月为完整自然月，可算环比）" % (
            prev_start.strftime("%Y年%m月%d日"), prev_end.strftime("%Y年%m月%d日"))
            if cal["prev_ok"] else
            "环比基期 %s ~ %s 库内不完整，本期不出环比（避免用残缺基期算失真的升降幅）" % (
                prev_start.strftime("%Y年%m月%d日"), prev_end.strftime("%Y年%m月%d日")))
        window_note = ("<div class='note'><b>口径说明：</b>本期为 <b>自然月整月</b>口径，"
                       "取自本地逐日库（城市日均 AQI + 六参数 24 小时值），非平台实时小时值；"
                       "%s。每日值均为平台审核前数据，正式结论以总站/省级审核后数据为准。</div>"
                       % prev_txt)
    else:
        # 月报兜底：平台历史窗口当前为 14 天，如实标注
        have = [r["date"] for r in all_rows[cities[0]]]
        last_complete = have[-1]
        d_last = datetime.strptime(last_complete, "%Y-%m-%d")
        cur_start = d_last - timedelta(days=13)
        cur_end = d_last
        prev_start = prev_end = d_last  # 无上期窗口，环比置空
        period_desc = "%s ~ %s（平台历史开放窗口 %d 天，整月分析将随数据积累切换）" % (
            cur_start.strftime("%Y年%m月%d日"), d_last.strftime("%Y年%m月%d日"), len(have))
        fname = "大气管家豫北月报_%s.html" % today.strftime("%Y-%m")
        window_note = ("<div class='note'><b>窗口说明：</b>月报需要整月日值。当前平台公开接口仅开放最近 14 天历史，"
                       "本首期以 %d 天窗口生成；本地数据库（data/air.db）自 %s 起持续积累逐日数据，"
                       "窗口足够后自动切换为自然月口径。</div>") % (len(have), today.strftime("%Y-%m-%d"))

    from calc.period_stats import city_period_stats

    stats = []
    for c in cities:
        rows = all_rows[c]
        cur = [r for r in rows if cur_start.strftime("%Y-%m-%d") <= r["date"] <= cur_end.strftime("%Y-%m-%d")]
        prev = [r for r in rows if prev_start.strftime("%Y-%m-%d") <= r["date"] <= prev_end.strftime("%Y-%m-%d")]
        if not cur:
            raise RuntimeError("%s 本期无数据（%s ~ %s）" % (
                c, cur_start.strftime("%Y-%m-%d"), cur_end.strftime("%Y-%m-%d")))
        stats.append(city_period_stats(cur, prev))

    from report.period_page import render_period

    title = KIND_TITLE % KIND_LABEL[kind]
    html = render_period(kind, title, period_desc, stats, cfg, window_note)
    return {
        "kind": kind, "fname": fname, "title": title,
        "period_desc": period_desc, "window_note": window_note,
        "stats": stats, "html": html,
        "start": cur_start.strftime("%Y-%m-%d"), "end": cur_end.strftime("%Y-%m-%d"),
    }
