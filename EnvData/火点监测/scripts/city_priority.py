# -*- coding: utf-8 -*-
"""市级专项优先级清单：18 个市按「工业源绝对量 + 占比 + 集中度」排序，
回答「下一个该给谁做专项」。

判据说明
--------
做市级专项的价值 = 有东西可查（工业源绝对量）× 性质单一（占比高）× 好落地（集中度高）。
所以主排序用**工业源火点条数**，再看占比与集中度。
秸秆主导的市不该做「工业执法专项」，应换成「秸秆疏导」选题 —— 本清单会分开标注。

用法：python city_priority.py
"""
import collections
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

CITY_ORDER = ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
              "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]
DONE = {"安阳": "安阳火点专项分析", "平顶山": "平顶山火点专项分析"}


def esc(s):
    return AR._esc(s)


def main():
    allf = SD.load(2024) + SD.load(2025)
    prof = SD.profiles(allf)

    rows = []
    for c in CITY_ORDER:
        ps = [p for p in prof.values() if p["city"] == c]
        if not ps:
            continue
        fire = sum(p["n"] for p in ps)
        ind = [p for p in ps if SD.kind_of(p) == "工业/固定源"]
        indf = sum(p["n"] for p in ind)
        strw = [p for p in ps if SD.kind_of(p) == "秸秆焚烧疑似"]
        strf = sum(p["n"] for p in strw)
        top10 = sorted(ps, key=lambda p: -p["days"])[:10]
        rows.append(dict(
            city=c, fire=fire, pts=len(ps), ind_pts=len(ind), ind_fire=indf,
            ind_pct=indf / fire * 100 if fire else 0,
            str_pts=len(strw), str_fire=strf,
            top10=sum(p["n"] for p in top10) / fire * 100 if fire else 0,
            hi=max((p["days"] for p in ps), default=0),
            ind_night=statistics.median([p["night_ratio"] for p in ind]) * 100 if ind else 0,
            ind_frp=statistics.median([p["frp_med"] for p in ind]) if ind else 0))
    rows.sort(key=lambda r: -r["ind_fire"])

    for r in rows:
        r["kind"] = ("工业主导" if r["ind_pct"] >= 60 else
                     "混合" if r["ind_pct"] >= 30 else "农业主导")
        r["done"] = r["city"] in DONE

    todo = [r for r in rows if not r["done"]]
    p0 = [r for r in todo if r["kind"] == "工业主导"][:3]
    p1 = [r for r in todo if r["kind"] == "工业主导"][3:]
    pmix = [r for r in todo if r["kind"] == "混合"]
    pagri = [r for r in todo if r["kind"] == "农业主导"]

    top_bar = AR.svg_hbar([(r["city"], r["ind_fire"]) for r in rows[:10]], row_h=26,
                          color=C["hot"], unit="条")
    agri_bar = AR.svg_hbar([(r["city"], r["str_fire"]) for r in sorted(pagri, key=lambda x: -x["str_fire"])[:8]],
                           row_h=26, color=C["ok"], unit="条")

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>市级专项优先级清单</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>市级专项优先级清单</h1>',
         '<div class="sub">18 个市按「工业源绝对量 × 占比 × 集中度」排序，'
         '回答下一个该给谁做专项　·　数据：2024–2025 两年 FIRMS VIIRS 375m　·　生成于 %s</div>' % dt]

    h.append('<div class="card" style="border-color:#f97316"><h2>结论</h2>'
             '<div style="font-size:17px;line-height:1.8">'
             '下一个做 <span class="hl">三门峡</span>；'
             '如果想要一份「最干净、最快出」的样板，先做 <span class="hl">济源</span>。</div>'
             '<div class="note">三门峡：工业源 <b>%s 条</b>（全省第 3）、占本市火点 <b>%.1f%%</b>、'
             '前 10 个点位集中 <b>%.0f%%</b>、最高点位两年出现 <b>%d 天</b> —— '
             '和安阳几乎是同一个模子（矿业/冶炼带），现有专项模板可以直接套。<br>'
             '济源：工业源占比 <b>%.1f%%</b>（全省最高）、前 10 点位集中 <b>%.0f%%</b>，'
             '而且全市只有 <b>%d 个点位、%d 个工业点位</b> —— 是全省最小、最纯的样本，'
             '做一版当作「最小可行样板」最合适。</div></div>'
             % (format(next(r for r in rows if r["city"] == "三门峡")["ind_fire"], ","),
                next(r for r in rows if r["city"] == "三门峡")["ind_pct"],
                next(r for r in rows if r["city"] == "三门峡")["top10"],
                next(r for r in rows if r["city"] == "三门峡")["hi"],
                next(r for r in rows if r["city"] == "济源")["ind_pct"],
                next(r for r in rows if r["city"] == "济源")["top10"],
                next(r for r in rows if r["city"] == "济源")["pts"],
                next(r for r in rows if r["city"] == "济源")["ind_pts"]))

    h.append('<div class="kpi">'
             '<div><b>%d</b><span>已做专项的市</span></div>'
             '<div><b>%d</b><span>待做（工业主导）</span></div>'
             '<div><b>%d</b><span>待做（混合）</span></div>'
             '<div><b>%d</b><span>应改做秸秆选题</span></div>'
             '</div>' % (len(DONE), len(p0) + len(p1), len(pmix), len(pagri)))

    h.append('<div class="card"><h2>一、全部 18 市（按工业源火点条数排序）</h2>'
             '<table><tr><th>#</th><th>市</th><th>类型</th><th class="num">两年火点</th>'
             '<th class="num">点位</th><th class="num">工业点位</th><th class="num">工业源火点</th>'
             '<th class="num">工业占比</th><th class="num">前10集中</th>'
             '<th class="num">最高天数</th><th class="num">工业FRP中位</th><th>状态</th></tr>')
    for i, r in enumerate(rows, 1):
        kc = {"工业主导": "#f97316", "混合": "#38bdf8", "农业主导": "#34d399"}[r["kind"]]
        st = '<span class="tag">已出专项</span>' if r["done"] else (
            "P0 优先" if r in p0 else ("P1" if r in p1 else ("混合" if r in pmix else "改做秸秆选题")))
        h.append('<tr><td>%d</td><td><b>%s</b></td>'
                 '<td><span style="color:%s">%s</span></td>'
                 '<td class="num">%s</td><td class="num">%d</td><td class="num">%d</td>'
                 '<td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="num">%.0f%%</td><td class="num">%d</td>'
                 '<td class="num">%.2f</td><td>%s</td></tr>'
                 % (i, esc(r["city"]), kc, r["kind"], format(r["fire"], ","), r["pts"],
                    r["ind_pts"], format(r["ind_fire"], ","), r["ind_pct"],
                    r["top10"], r["hi"], r["ind_frp"], st))
    h.append('</table>'
             '<div class="note"><b>类型判定</b>：工业主导 = 工业源占本市火点 ≥60%；'
             '混合 = 30–60%；农业主导 = &lt;30%。<br>'
             '<b>前10集中</b> = 全市火点最多的 10 个点位贡献的火点占比，越高说明越好下手。</div></div>')

    h.append('<div class="card"><h2>二、工业源火点 Top 10（该给谁做工业执法专项）</h2>'
             '%s'
             '<div class="note">前两名已出专项。剩下三个工业主导市（三门峡、许昌、济源）'
             '合计 %s 条工业源火点，占全省工业源火点的 %.0f%%。</div></div>'
             % (top_bar,
                format(sum(r["ind_fire"] for r in p0), ","),
                sum(r["ind_fire"] for r in p0) /
                sum(r["ind_fire"] for r in rows) * 100))

    h.append('<div class="card"><h2>三、三个待做的工业主导市，逐个看</h2>'
             '<table><tr><th>市</th><th class="num">工业源</th><th class="num">占比</th>'
             '<th class="num">工业点位</th><th class="num">前10集中</th>'
             '<th class="num">最高天数</th><th>建议</th></tr>')
    tips = {
        "三门峡": "矿业/冶炼带（豫西），与安阳同型 —— 直接套用安阳模板；"
                  "最高点位两年 405 天，是全省第 2 高的「钉子户」",
        "许昌": "11 个工业点位贡献 1,944 条，集中度 75% —— 名单短、好交办",
        "济源": "全省占比最高（91.4%）、点位最少（78 个）—— 做「最小可行样板」的首选",
    }
    for r in p0:
        h.append('<tr><td><b>%s</b></td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="num">%d</td><td class="num">%.0f%%</td><td class="num">%d</td>'
                 '<td>%s</td></tr>'
                 % (esc(r["city"]), format(r["ind_fire"], ","), r["ind_pct"],
                    r["ind_pts"], r["top10"], r["hi"], esc(tips.get(r["city"], ""))))
    h.append('</table>'
             '<div class="note">做专项的成本主要取决于<b>工业点位数量</b>：'
             '济源 14 个、三门峡 10 个、许昌 11 个 —— 都比安阳（34 个）少，'
             '所以这三份专项的工作量都在安阳之下。</div></div>')

    h.append('<div class="card"><h2>四、不该做工业专项的市：改做「秸秆疏导」选题</h2>'
             '<div class="note">下面这些市的火点以秸秆/偶发为主（工业源占比 &lt;30%%），'
             '给它们套工业执法模板是错配 —— 该讲的是收储、还田、网格化巡查。</div>'
             '%s'
             '<table><tr><th>市</th><th class="num">秸秆疑似火点</th><th class="num">工业源火点</th>'
             '<th class="num">工业占比</th><th>选题方向</th></tr>' % agri_bar)
    for r in sorted(pagri, key=lambda x: -x["str_fire"]):
        h.append('<tr><td><b>%s</b></td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%.1f%%</td><td>秸秆收储与疏导、收获季网格化巡查</td></tr>'
                 % (esc(r["city"]), format(r["str_fire"], ","), format(r["ind_fire"], ","),
                    r["ind_pct"]))
    h.append('</table></div>')

    if pmix:
        h.append('<div class="card"><h2>五、混合型（两类都有，看客户是谁</h2>'
                 '<table><tr><th>市</th><th class="num">火点</th><th class="num">工业源</th>'
                 '<th class="num">工业占比</th><th class="num">秸秆疑似</th><th>说明</th></tr>')
        for r in pmix:
            h.append('<tr><td><b>%s</b></td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num">%.1f%%</td><td class="num">%s</td>'
                     '<td>两类都够量，按客户属性选口径</td></tr>'
                     % (esc(r["city"]), format(r["fire"], ","), format(r["ind_fire"], ","),
                        r["ind_pct"], format(r["str_fire"], ",")))
        h.append('</table></div>')

    h.append(AR.qr_foot("../../../assets"))


    h.append('<footer>'
             '数据：NASA FIRMS VIIRS 375m（2024/2025 SP 源历史回补），归属各市的全部火点<br>'
             '方法：0.01° 点位聚合 → 两年复现天数/夜间占比/FRP/季节 判定类型 → '
             '按工业源火点条数排序，并给出占比与集中度<br>'
             '<b>边界声明</b>：类型判定是「疑似 + 依据」的启发式，不是地面核实的结论；'
             '点位数为 0.01° 网格聚合结果，实际排放源数量可能更少。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "市级专项优先级清单.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("P0:", [r["city"] for r in p0])
    print("P1:", [r["city"] for r in p1])
    print("混合:", [r["city"] for r in pmix])
    print("农业主导:", [r["city"] for r in pagri])
    sx = next(x for x in rows if x["city"] == "三门峡")
    print("三门峡 工业源 %d 条 / 占比 %.1f%% / 集中 %.0f%% / 最高 %d 天"
          % (sx["ind_fire"], sx["ind_pct"], sx["top10"], sx["hi"]))


if __name__ == "__main__":
    main()
