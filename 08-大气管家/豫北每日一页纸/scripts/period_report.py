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
  月报 = 平台开放历史窗口（实测 14 天），整月口径待本地库里攒够自然月数据后切换
  完整日 = 平台历史接口返回的最后一天（当天为进行中，不纳入）
"""
from datetime import datetime, timedelta

KIND_LABEL = {"weekly": "周报", "monthly": "月报"}
KIND_PREFIX = {"weekly": "大气管家豫北周报", "monthly": "大气管家豫北月报"}
KIND_TITLE = "豫北四市环境空气质量%s（安阳 · 濮阳 · 鹤壁 · 新乡）"


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

    all_rows, failed = {}, []
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

    # 历史接口返回最近 14 天（09-09 起固定窗口），取库内实际可得日期
    have = [r["date"] for r in all_rows[cities[0]]]
    last_complete = have[-1]
    d_last = datetime.strptime(last_complete, "%Y-%m-%d")

    if kind == "weekly":
        cur_start, cur_end = d_last - timedelta(days=6), d_last
        prev_start, prev_end = d_last - timedelta(days=13), d_last - timedelta(days=7)
        period_desc = "%s ~ %s（环比基期 %s ~ %s）" % (
            cur_start.strftime("%Y年%m月%d日"), cur_end.strftime("%Y年%m月%d日"),
            prev_start.strftime("%m月%d日"), prev_end.strftime("%m月%d日"))
        fname = "大气管家豫北周报_%s_to_%s.html" % (cur_start.strftime("%m%d"), cur_end.strftime("%m%d"))
        window_note = ""
    else:
        # 月报：平台历史窗口当前为 14 天，首期如实标注
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
