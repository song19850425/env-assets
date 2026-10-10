# -*- coding: utf-8 -*-
"""报告中心入口页：把 report/ 下的全部分析报告 + 线上火点页收在一页。

产出：report/index.html

用法：python report_index.py
新增报告后，在 REPORTS 里补一条元数据（标题/说明/关键数字），重跑即可。
"""
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
REPORT = MOD / "report"
OUT = REPORT / "index.html"

sys.path.insert(0, str(HERE))
import annual_report as AR      # 复用配色

ONLINE = "https://song19850425.github.io/env-assets/EnvData/" + urllib.parse.quote("火点监测") + "/"
CITIES = ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
          "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]

# ---- 报告元数据（file 必须真实存在，脚本会校验）----
REPORTS = [
    {
        "file": "河南火点年报-2025.html", "group": "省级分析", "tag": "年报",
        "title": "河南火点年报 · 2025",
        "desc": "全省全年火点全景：逐月趋势、昼夜结构、各市分布、FRP 分布、点位类型判定、"
                "反复出现点位 Top15。",
        "kpis": [("22,626", "火点"), ("337", "有火点天数"), ("60%", "夜间占比"),
                 ("48.1%", "工业源占比")],
    },
    {
        "file": "河南火点年报-2024-2025.html", "group": "省级分析", "tag": "对比",
        "title": "河南火点年报 · 2024 vs 2025",
        "desc": "两年同源（SP）对比：总量、逐月、各市双柱并排，含各市变化表与归因边界说明。",
        "kpis": [("22,914 → 22,626", "火点总量（↓1.3%）"), ("63.7% → 60.0%", "夜间占比"),
                 ("−63%", "驻马店降幅最大"), ("+95%", "商丘增幅最大")],
    },
    {
        "file": "火点类型判别模型-验证.html", "group": "省级分析", "tag": "方法",
        "title": "火点类型判别模型 · 验证",
        "desc": "怎么判断一个火点是秸秆还是工厂：判定规则、阈值依据（来自实测分布）、"
                "特征空间散点图，以及半年分割与跨年一致性验证。",
        "kpis": [("86%", "工业源跨年一致率"), ("仅 1 个", "工业源点位次年消失"),
                 ("99–100%", "秸秆/偶发次年零复现")],
    },
    {
        "file": "秸秆焚烧空间规律.html", "group": "省级分析", "tag": "空间",
        "title": "秸秆焚烧的空间与时间规律",
        "desc": "安阳 + 平顶山：带县界底图的空间散点，把工业源点位与秸秆点位分开画——"
                "看两者是不是两张网；附时间规律、强度对比、聚集性差异。",
        "kpis": [("34 km", "安阳秸秆距工业源（中位）"), ("仅 4 个月", "秸秆出现的月份数"),
                 ("96%", "秸秆点位只烧一次")],
    },
    {
        "file": "全省持续热排放点位.html", "group": "省级分析", "tag": "清单",
        "title": "全省持续热排放点位统计",
        "desc": "把两年火点聚合成点位后，203 个「反复出现 ≥10 天」的点位覆盖了全省 49.5% 的火点。"
                "完整清单（坐标 / 县区 / 出现天数 / 夜间占比 / FRP / 跨月数）+ 全省分布图，"
                "按出现天数排序，可直接用作核查清单。",
        "kpis": [("203", "持续排放点位"), ("49.5%", "覆盖全省火点"),
                 ("445 天", "最高出现天数（两年 730 天）"), ("19 个", "200 天以上点位")],
    },
    {
        "file": "安阳火点专项分析.html", "group": "市级专项", "tag": "安阳",
        "title": "安阳火点专项分析",
        "desc": "2025 年全省第一。为什么多、都是什么火、怎么管控、问责情况。"
                "含省内位次、县区×类型矩阵、高频点位 Top15、分类型管控建议。",
        "kpis": [("6,688", "两年火点"), ("85.4%", "工业源占比"), ("34 个", "工业源点位数"),
                 ("445 天", "最高点位两年出现天数")],
    },
    {
        "file": "平顶山火点专项分析.html", "group": "市级专项", "tag": "平顶山",
        "title": "平顶山火点专项分析",
        "desc": "两年合计全省第一。火点集中在煤化工/焦化集聚区，含分类型管控建议与"
                "纪委监委纠正不当问责的公开信息（逐条标注来源）。",
        "kpis": [("6,906", "两年火点"), ("57.2%", "工业源占比"), ("39 个", "工业源点位数"),
                 ("295 天", "最高点位两年出现天数")],
    },
]

# 「你关心什么 → 看哪份」
GUIDE = [
    ("这个火点要不要连夜去查？", "火点类型判别模型 · 验证"),
    ("哪个市火点最多、为什么？", "安阳 / 平顶山 火点专项分析"),
    ("全省火点长什么样？", "河南火点年报 · 2025"),
    ("今年比去年多了还是少了？", "河南火点年报 · 2024 vs 2025"),
    ("秸秆都在哪里烧、什么时候烧？", "秸秆焚烧的空间与时间规律"),
    ("今天最新的火点在哪？", "打开在线火点地图"),
]

CSS_EXTRA = """
.rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.r{background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:16px 18px;
  display:flex;flex-direction:column;gap:10px;transition:border-color .15s,transform .15s}
.r:hover{border-color:#334155;transform:translateY(-2px)}
.r .tag{display:inline-block;padding:1px 9px;border-radius:999px;font-size:11px;
  background:rgba(56,189,248,.12);color:#7dd3fc;border:1px solid rgba(56,189,248,.3);
  width:fit-content}
.r h3{margin:0;font-size:15px;color:#e2e8f0}
.r p{margin:0;font-size:12.5px;color:#94a3b8;line-height:1.65;flex:1}
.r .k{display:flex;flex-wrap:wrap;gap:10px;border-top:1px solid #1e293b;padding-top:10px}
.r .k div{font-size:11px;color:#64748b}
.r .k b{display:block;font-size:14px;color:#e2e8f0;font-weight:600}
.r a{color:#7dd3fc;font-size:12.5px;text-decoration:none}
.r a:hover{text-decoration:underline}
.guide{width:100%;border-collapse:collapse;font-size:13px}
.guide td{padding:7px 8px;border-bottom:1px solid #1e293b}
.guide td:first-child{color:#cbd5e1}
.guide td:last-child{color:#7dd3fc}
.maps{display:flex;flex-wrap:wrap;gap:8px}
.maps a{display:inline-block;padding:6px 12px;border:1px solid #1e293b;border-radius:9px;
  font-size:12.5px;color:#cbd5e1;text-decoration:none}
.maps a:hover{border-color:#38bdf8;color:#7dd3fc}
.maps a.hi{border-color:rgba(56,189,248,.5);color:#7dd3fc;font-weight:600}
h2{font-size:16px;color:#38bdf8;margin:26px 0 10px}
"""


def main():
    missing = [r["file"] for r in REPORTS if not (REPORT / r["file"]).exists()]
    if missing:
        print("[index] ⚠ 以下报告文件不存在，请检查：")
        for m in missing:
            print("        ", m)

    css = (AR.CSS.replace("__BG__", AR.C["bg"]).replace("__PANEL__", AR.C["panel"])
           .replace("__LINE__", AR.C["line"]).replace("__TXT__", AR.C["txt"])
           .replace("__DIM__", AR.C["dim"]).replace("__DIM2__", AR.C["dim2"])
           .replace("__ACC__", AR.C["accent"]).replace("__HOT__", AR.C["hot"])) + CSS_EXTRA

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>河南火点监测 · 报告中心</title><style>%s</style></head><body>' % css,
         AR.nav_back_html("../../index.html", "← 返回首页"),
         '<div class="wrap">',
         '<h1>河南火点监测 · 报告中心</h1>',
         '<div class="sub">数据源 NASA FIRMS · VIIRS 375m（Suomi-NPP + NOAA-20）　·　'
         '覆盖 2024–2025 两年　·　生成于 %s</div>'
         % datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")]

    h.append('<div class="card"><h2 style="margin-top:0">这个库能回答什么</h2>'
             '<table class="guide">')
    for q, a in GUIDE:
        h.append('<tr><td>%s</td><td>→ %s</td></tr>' % (AR._esc(q), AR._esc(a)))
    h.append('</table></div>')

    groups = []
    for r in REPORTS:
        if r["group"] not in groups:
            groups.append(r["group"])
    for g in groups:
        h.append('<h2>%s</h2><div class="rgrid">' % AR._esc(g))
        for r in REPORTS:
            if r["group"] != g:
                continue
            ok = (REPORT / r["file"]).exists()
            href = urllib.parse.quote(r["file"])
            h.append('<div class="r"><span class="tag">%s</span><h3>%s</h3><p>%s</p>'
                     '<div class="k">%s</div>%s</div>'
                     % (AR._esc(r["tag"]), AR._esc(r["title"]), AR._esc(r["desc"]),
                        "".join('<div><b>%s</b>%s</div>' % (AR._esc(v), AR._esc(l))
                                for v, l in r["kpis"]),
                        ('<a href="%s">打开报告 ›</a>' % href) if ok
                        else '<span style="color:#f97316;font-size:12px">文件缺失</span>'))
        h.append('</div>')

    # 在线地图
    h.append('<h2>在线火点地图（实时数据，每 6 小时自动更新）</h2>')
    h.append('<div class="card"><div class="maps">')
    h.append('<a class="hi" href="%s" target="_blank">河南省全省总览</a>'
             % (ONLINE + urllib.parse.quote("河南省火点监测-暗色版.html")))
    for c in CITIES:
        h.append('<a href="%s" target="_blank">%s</a>'
                 % (ONLINE + urllib.parse.quote("%s市火点监测-暗色版.html" % c), c))
    h.append('</div><div class="note">共 19 个页面（18 市 + 全省总览）。'
             '数据由 GitHub Actions 每 6 小时自动抓取更新；'
             '页面内「📜 获取日志」可看每次抓取的时间与结果。</div></div>')

    h.append('<footer><b>使用说明</b><br>'
             '· 本页与全部分析报告均为<b>单文件 HTML</b>，可直接双击打开、离线查看、'
             '也可直接转发（不含任何外部依赖）。<br>'
             '· 火点数据来自卫星遥感（NASA FIRMS VIIRS 375m），'
             '<b>成因与类型是「疑似 + 依据」的推断，不是认定，不能作为行政处罚依据</b>；'
             '用于执法须经现场核实。<br>'
             '· 报告中引用的产业背景、问责情况等外部信息，均逐条标注来源；'
             '标注「待核」的条目未经证实。<br>'
             '· 全部数字由脚本从原始数据自动算出，可复算。</footer>')
    h.append('</div></body></html>')

    OUT.write_text("".join(h), encoding="utf-8")
    print("[index] 写出 %s（%.0f KB）｜收录报告 %d 份"
          % (OUT, OUT.stat().st_size / 1024, len(REPORTS)))


if __name__ == "__main__":
    main()
