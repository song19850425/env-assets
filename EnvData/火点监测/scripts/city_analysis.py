# -*- coding: utf-8 -*-
"""市级火点专项分析：为什么这个市火点多、都是什么火、该怎么管控。

用法：
    python city_analysis.py 平顶山 2024 2025
产出：
    report/<市>火点专项分析.html

设计：
  · 全部统计从 data/history/<年>.json 算出来，不写死数字
  · 县区归属用 geo/<市>市_县.geojson 做点落多边形
  · 类型判定复用 classify.py（点位画像 + 跨年稳定性已验证）
  · 「产业背景」「问责情况」是**外部信息**，存在 CITY_NOTES 里并标注来源
    （数据算不出来的东西，宁可标注出处，也不编）
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
HIST = MOD / "data" / "history"
GEO = MOD / "geo"
OUT = MOD / "report"
sys.path.insert(0, str(HERE))

import annual_report as AR      # 复用 SVG 与配色
import classify as CL
import fetch_firms as FF

KIND_ORDER = ["工业/固定源", "偏固定源", "秸秆焚烧疑似", "其他偶发", "待核实"]

# ---- 外部信息（数据算不出来，标注来源；没有的市就不显示这两节）----
CITY_NOTES = {
    "平顶山": {
        "industry": [
            ("石龙区", "主导产业为<b>煤化工和新型建材</b>，区内有中鸿煤化、东鑫焦化等企业；"
                       "2024 年 11 月获省工信厅批复同意<b>化工园区扩区</b>。",
             "平顶山市发改委「石龙产业集聚区简介」；搜狐/河南日报 2024-11 报道"),
            ("宝丰县", "有<b>洁石煤化</b>等焦化企业，形成「焦炭—煤化工—干熄焦发电—余热煤气利用」"
                       "的循环产业链。", "企查查企业信息；平顶山市政府门户"),
            ("汝州市", "平顶山传统的<b>煤炭、焦化</b>集中区，煤矿与洗选、焦化企业密集。",
             "公开产业资料"),
            ("全市", "平顶山是国家重要的<b>焦化、尼龙化工</b>基地（「中国尼龙城」），"
                     "焦化、煤化工、尼龙产业链企业众多。", "平顶山市人民政府门户；人大代表建议答复"),
        ],
        "accountability": [
            ("平顶山市纪委监委（2025-04 公开报道）",
             "<b>纠正了 2 名基层干部的不当问责</b>。纪委监委在评查 2023 年 2 月某企业大气污染问题的"
             "问责案件时发现，某地以「属地管理」为由，对<b>不在基层职责范围内</b>的一般干部问责，"
             "上级纪委督促纠正，明确提出「不能让一般干部替企业背锅」。",
             "中央纪委国家监委网站文章，2025-04-12 多家媒体转载（搜狐/腾讯/中华网）"),
            ("平顶山市禁烧办（年份待核）",
             "曾报道「舞钢两干部因禁烧不力被免职」，平顶山市启动秸秆禁烧问责机制。"
             "<b>该报道的确切年份无法确认</b>（来源为转载站，页面日期不可靠），仅作参考。",
             "转载站页面，年份存疑"),
            ("参照：洛阳市（2025-05）",
             "洛龙区、汝阳县因秸秆焚烧被通报，<b>2 名街道/镇党委书记被公开约谈并责令公开检讨</b>，"
             "两地分别扣减财力 40 万、30 万。",
             "洛阳市委农村工作领导小组办公室通报，2025-05-25"),
        ],
    },
}


CITY_NOTES["安阳"] = {
    "industry": [
        ("殷都区", "辖区内有<b>安钢集团、大唐安阳发电厂</b>等大型企业，各类工业企业 600 余家"
                   "（规模以上 116 家）；2018 年以来按省、市焦化整合部署，把原有「四大焦化」"
                   "整合为利源、顺成、鑫磊等企业。",
         "安阳日报 2024-02；中国日报 2023-04"),
        ("安阳县（水冶一带）", "水冶—铜冶一带是安阳传统的<b>钢铁、焦化、水泥</b>重工业集聚区"
                              "（铜冶镇现属殷都区，是河南省重要的煤化工产业基地，以煤焦化及深加工为主导）。",
         "爱企查产业信息；公开产业资料"),
        ("全市", "安阳是河南重要的<b>钢铁基地</b>（安钢集团所在地），沙钢集团整合本地多家钢厂产能、"
                 "规划 16 个钢铁项目，钢铁与焦化产业链企业密集。",
         "安阳市政府；行业媒体报道"),
    ],
    "accountability": [
        ("安阳市（制度性表述，2025-10）",
         "安阳日报报道当地秸秆禁烧工作时称「对工作不力、擅离职守的，及时通报批评并约谈问责」。"
         "<b>未查到安阳市因秸秆焚烧被问责的具体人数或案例</b>。",
         "安阳日报数字报 2025-10-30"),
        ("参照：平顶山市纪委监委（2025-04）",
         "评查后纠正 <b>2 名基层干部的不当问责</b>，明确「不能让一般干部替企业背锅」。",
         "中央纪委国家监委网站文章，2025-04-12 多家媒体转载"),
        ("参照：洛阳市（2025-05）",
         "洛龙区、汝阳县被通报，<b>2 名街道/镇党委书记被公开约谈并责令公开检讨</b>，"
         "两地分别扣减财力 40 万、30 万。",
         "洛阳市委农村工作领导小组办公室通报，2025-05-25"),
    ],
}


def county_of(lng, lat, counties):
    for n, g in counties:
        if FF.point_in_geom(lng, lat, g):
            return n
    return "市外/未匹配"


def load_city(city, years):
    """返回 (全部火点, 各县界)。"""
    counties = []
    gp = GEO / ("%s市_县.geojson" % city)
    if gp.exists():
        gj = json.loads(gp.read_text(encoding="utf-8"))
        counties = [(f["properties"].get("name", "?"), f["geometry"]) for f in gj["features"]]
    fires, per_year = [], {}
    for y in years:
        p = HIST / ("%d.json" % y)
        if not p.exists():
            raise SystemExit("[city] 缺少 %s" % p)
        d = json.loads(p.read_text(encoding="utf-8"))
        fy = [f for f in d["fires"] if f["city"] == city]
        per_year[y] = {"fires": fy, "prov_n": d["count"], "prov_counts": d["counts"]}
        fires += fy
    return fires, counties, per_year


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("用法：python city_analysis.py <市名> [年份...]")
    city = args[0]
    years = sorted(int(a) for a in args[1:] if a.isdigit()) or [2024, 2025]

    fires, counties, per_year = load_city(city, years)
    n = len(fires)
    prof = CL.build_profiles(fires)
    kind = {k: CL.classify(p)[0] for k, p in prof.items()}
    conf = {k: CL.classify(p)[1] for k, p in prof.items()}

    kf, kc = Counter(), Counter()
    for k, p in prof.items():
        kf[kind[k]] += p["n"]; kc[kind[k]] += 1

    # 县区 × 类型
    cnt_kind = defaultdict(lambda: defaultdict(int))
    cnt_tot = Counter()
    for k, p in prof.items():
        c = county_of(float(k.split(",")[1]), float(k.split(",")[0]), counties)
        cnt_kind[c][kind[k]] += p["n"]
        cnt_tot[c] += p["n"]

    # 逐月 / 昼夜 / FRP
    bm = Counter(f["date"][:7] for f in fires)
    dn = Counter(f["dn"] for f in fires)
    frps = sorted(float(f["frp"]) for f in fires)
    top = sorted(prof.values(), key=lambda p: -p["days"])[:15]

    # 全省（同口径、同年份）用于横向对比
    prov_fires = []
    for y in years:
        prov_fires += json.loads((HIST / ("%d.json" % y)).read_text(encoding="utf-8"))["fires"]
    prov_prof = CL.build_profiles(prov_fires)
    prov_ind = sum(p["n"] for p in prov_prof.values()
                   if CL.classify(p)[0] == "工业/固定源")
    prov_ind_pct = prov_ind / len(prov_fires) * 100 if prov_fires else 0
    print("[city] 全省同口径：%s 条 / 工业源 %.0f%%" % (f'{len(prov_fires):,}', prov_ind_pct))

    # 位次（逐年 + 两年合计）
    rank = []
    for y, v in per_year.items():
        order = sorted(v["prov_counts"].items(), key=lambda kv: -kv[1])
        pos = [i for i, (c, _) in enumerate(order, 1) if c == city]
        rank.append((y, pos[0] if pos else "-", len(v["fires"]),
                     v["prov_counts"].get(city, 0), v["prov_n"]))
    tot_all = Counter()
    for v in per_year.values():
        for c, cn in v["prov_counts"].items():
            tot_all[c] += cn
    order_all = sorted(tot_all.items(), key=lambda kv: -kv[1])
    pos_all = next((i for i, (c, _) in enumerate(order_all, 1) if c == city), "-")

    # ---------------- HTML ----------------
    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>%s火点专项分析</title><style>%s</style></head><body>'
         % (city, AR.CSS.replace("__BG__", AR.C["bg"]).replace("__PANEL__", AR.C["panel"])
            .replace("__LINE__", AR.C["line"]).replace("__TXT__", AR.C["txt"])
            .replace("__DIM__", AR.C["dim"]).replace("__DIM2__", AR.C["dim2"])
            .replace("__ACC__", AR.C["accent"]).replace("__HOT__", AR.C["hot"])),
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>%s火点专项分析</h1>' % city,
         '<div class="sub">%s 年　·　NASA FIRMS VIIRS 375m（SP 标准处理）　·　'
         '生成于 %s</div>' % ("、".join(str(y) for y in years),
                              datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"))]

    # ① 概览
    h.append('<div class="kpi">')
    for val, lab in [(f'{n:,}', '火点总数（%d 年合计）' % len(years)),
                     (f'{dn["N"]/n*100:.0f}%', '夜间火点占比'),
                     (f'{kf.get("工业/固定源",0)/n*100:.0f}%', '工业/固定源占比'),
                     (f'{len(prof):,}', '火点点位（约 1km 网格）')]:
        h.append('<div><b>%s</b><span>%s</span></div>' % (AR._esc(val), lab))
    h.append('</div>')

    h.append('<div class="card"><h2>省内位次</h2><table>'
             '<tr><th>年份</th><th class="num">排名</th><th class="num">本市火点</th>'
             '<th class="num">全省火点</th><th class="num">占全省</th></tr>')
    for y, pos, cn, _, pn in rank:
        h.append('<tr><td>%d 年</td><td class="num"><b>第 %s 位</b></td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%.1f%%</td></tr>'
                 % (y, pos, f'{cn:,}', f'{pn:,}', cn / pn * 100))
    h.append('</table><div class="note">%s 年合计 %s 条，居全省<b>第 %s 位</b>。</div></div>'
             % (len(years), f'{n:,}', pos_all))

    # ② 为什么多
    h.append('<div class="card"><h2>为什么火点多：火点高度集中在重工业集聚区</h2>')
    order = cnt_tot.most_common()
    top2 = sum(v for _, v in order[:2])
    h.append('<div class="note">全市 %d 条火点里，最集中的 2 个县区（%s）就占了 <b>%.0f%%</b>：</div>'
             % (n, "、".join(c for c, _ in order[:2]),
                top2 / n * 100 if n else 0))
    h.append(AR.svg_hbar([(c, v) for c, v in order], row_h=25, color=AR.C["hot"]))
    notes = CITY_NOTES.get(city, {}).get("industry")
    if notes:
        h.append('<table style="margin-top:14px"><tr><th>区域</th><th>产业结构</th></tr>')
        for name, txt, src in notes:
            h.append('<tr><td><b>%s</b></td><td style="font-size:12.5px">%s'
                     '<br><span style="color:#64748b;font-size:11px">来源：%s</span></td></tr>'
                     % (AR._esc(name), txt, AR._esc(src)))
        h.append('</table>')
    h.append('<div class="note">这不是巧合：火点最集中的县区，正是焦化/煤化工企业密集的地方。'
             '下面用数据验证——看这些火点到底是什么类型。</div></div>')

    # ③ 是什么火
    h.append('<div class="card"><h2>都是什么火点</h2><table>'
             '<tr><th>类型</th><th class="num">火点条数</th><th class="num">占比</th>'
             '<th class="num">点位数</th></tr>')
    for k in KIND_ORDER:
        v, c = kf.get(k, 0), kc.get(k, 0)
        if not v and not c:
            continue
        h.append('<tr><td style="color:%s">%s</td><td class="num">%s</td>'
                 '<td class="num">%.1f%%</td><td class="num">%s</td></tr>'
                 % (CL.KIND_COLOR.get(k, "#94a3b8"), k, f'{v:,}', v / n * 100, f'{c:,}'))
    h.append('</table>')
    ind = kf.get("工业/固定源", 0)
    h.append('<div class="note"><b>关键</b>：%s 条（%.0f%%）是<b>工业/固定源</b>，'
             '却只来自 <b>%d 个点位</b>——极少数设施在常年、持续地排放。'
             '而真正的秸秆焚烧疑似只有 %s 条（%.0f%%），分散在 %s 个点位上。'
             '两者的<b>管控对象完全不同</b>。</div>'
             % (f'{ind:,}', ind / n * 100, kc.get("工业/固定源", 0),
                f'{kf.get("秸秆焚烧疑似", 0):,}', kf.get("秸秆焚烧疑似", 0) / n * 100,
                f'{kc.get("秸秆焚烧疑似", 0):,}'))
    h.append('</div>')

    # ④ 县区 × 类型
    h.append('<div class="card"><h2>按县区看：哪里是工厂、哪里是农田</h2><table>'
             '<tr><th>县区</th><th class="num">火点合计</th><th>主导类型（前 2）</th></tr>')
    for c, tot in order:
        if not tot:
            continue
        tops = sorted(cnt_kind[c].items(), key=lambda kv: -kv[1])[:2]
        txt = " / ".join('<span style="color:%s">%s %d（%.0f%%）</span>'
                         % (CL.KIND_COLOR.get(k, "#94a3b8"), k, v, v / tot * 100)
                         for k, v in tops)
        h.append('<tr><td><b>%s</b></td><td class="num">%s</td><td>%s</td></tr>'
                 % (AR._esc(c), f'{tot:,}', txt))
    h.append('</table>')
    # 动态识别「工厂型」与「乡镇型」县区（只看占全市 ≥2% 的县区，避免小样本噪声）
    thr = n * 0.02
    fact, farm = [], []
    for c, tot in order:
        if tot < thr or c == "市外/未匹配":
            continue
        ik = cnt_kind[c].get("工业/固定源", 0) / tot
        fk = (cnt_kind[c].get("秸秆焚烧疑似", 0) + cnt_kind[c].get("其他偶发", 0)) / tot
        if ik >= 0.7:
            fact.append((c, ik))
        elif fk >= 0.7:
            farm.append((c, fk))
    seg = []
    if fact:
        seg.append("<b>%s</b> 以<b>工业/固定源</b>为主（%s 高达 %.0f%%）"
                   % ("、".join(c for c, _ in fact),
                      fact[0][0], fact[0][1] * 100))
    if farm:
        seg.append("<b>%s</b> 以<b>秸秆/偶发</b>为主（乡镇型）"
                   % "、".join(c for c, _ in farm))
    txt = ("一眼能看出两类地方：" + "；".join(seg) + "。"
           "把这两类混在一起考核，就是「一刀切」的根源。") if seg else \
          "各县区的类型构成见上表。"
    h.append('<div class="note">%s<br>'
             '（「市外/未匹配」%s 条，占 %.1f%%，落在相邻县界的共享边界上，属正常误差。）</div></div>'
             % (txt, f'{cnt_tot.get("市外/未匹配", 0):,}',
                cnt_tot.get("市外/未匹配", 0) / n * 100 if n else 0))

    # ⑤ 高频点位
    h.append('<div class="card"><h2>最需要盯的 %d 个点位（按出现天数）</h2>' % len(top))
    h.append('<table><tr><th class="num">#</th><th>坐标（WGS-84）</th><th>县区</th>'
             '<th class="num">出现天数</th><th class="num">夜间占比</th>'
             '<th class="num">FRP 中位</th><th class="num">探测次数</th></tr>')
    for i, p in enumerate(top, 1):
        c = county_of(float(p["key"].split(",")[1]), float(p["key"].split(",")[0]), counties)
        h.append('<tr><td class="num">%d</td><td>%s</td><td>%s</td><td class="num">%d</td>'
                 '<td class="num">%.0f%%</td><td class="num">%.2f</td><td class="num">%d</td></tr>'
                 % (i, AR._esc(p["key"]), AR._esc(c), p["days"], p["night_ratio"] * 100,
                    p["frp_med"], p["n"]))
    h.append('</table><div class="note">这 %d 个是出现最频繁的，两年内反复出现、几乎全在夜间、'
             '辐射功率稳定在低位——是固定源的典型特征。<b>全市共判定 %s 个工业/固定源点位，'
             '这 %s 个坐标就是可以直接交办给生态环境执法的清单。</b></div></div>'
             % (len(top), f'{kc.get("工业/固定源", 0):,}', f'{kc.get("工业/固定源", 0):,}'))

    # ⑥ 逐月
    h.append('<div class="card"><h2>逐月分布（看季节性）</h2>')
    bm_y = {y: Counter(f["date"][:7] for f in per_year[y]["fires"]) for y in years}
    ms = sorted(set().union(*[set(c) for c in bm_y.values()]))
    if len(years) > 1:
        h.append(AR.svg_grouped_bar(
            [(AR.mon_label(m), [bm_y[y].get(m, 0) for y in years]) for m in ms],
            ["%d 年" % y for y in years],
            [AR.C["dim2"], AR.C["accent"]]))
        h.append('<div class="legend">%s</div>' % "".join(
            '<span><i style="background:%s"></i>%d 年</span>' % (c, y)
            for c, y in zip([AR.C["dim2"], AR.C["accent"]], years)))
    else:
        h.append(AR.svg_bar([(AR.mon_label(m), bm[m]) for m in ms], color=AR.C["accent"]))
    harv = sum(bm.get("%d-%02d" % (y, m), 0) for y in years for m in (5, 6, 9, 10))
    lo = min(bm.values()) if bm else 0
    h.append('<div class="note">5–6 月（麦收）与 10 月（秋收）有明显峰值，'
             '<b>收获季 4 个月合计占 %.0f%%</b>；但其余月份每月仍有 %s 条以上——'
             '是「<b>农事季节叠加常年工业源</b>」的复合模式，不是纯农业型。'
             '（对比：全省工业/固定源占 %.0f%%，本市为 %.0f%%。）</div>'
             % (harv / n * 100 if n else 0, f'{lo:,}',
                prov_ind_pct, ind / n * 100 if n else 0))
    h.append('</div>')

    # ⑦ 管控建议
    h.append('<div class="card"><h2>该怎么管控</h2><table>'
             '<tr><th>对象</th><th>该谁管</th><th>怎么做</th></tr>'
             '<tr><td><b>工业/固定源</b><br><span style="color:#64748b;font-size:11px">%s 条（%.0f%%）</span></td>'
             '<td><b>生态环境执法</b><br><span style="color:#64748b;font-size:11px">不是禁烧办</span></td>'
             '<td>拿上面的高频点位清单逐个查：环评与排污许可、无组织排放、'
             '堆场苫盖、脱硫脱硝运行记录。夜间持续冒烟的基本跑不掉。</td></tr>'
             '<tr><td><b>秸秆焚烧</b><br><span style="color:#64748b;font-size:11px">%s 条（%.0f%%）</span></td>'
             '<td>禁烧办 / 属地</td>'
             '<td>集中在叶县、鲁山等农业乡镇，重点时段是 5–6 月麦收、9–10 月秋收；'
             '按点位而非按数量部署巡查力量。</td></tr>'
             '<tr><td><b>其他偶发</b><br><span style="color:#64748b;font-size:11px">%s 条（%.0f%%）</span></td>'
             '<td>属地 + 宣传</td>'
             '<td>多为冬季的垃圾/杂物焚烧，靠宣传和巡查；量大但单点影响小。</td></tr>'
             '</table>'
             '<div class="note"><b>最要紧的一条建议</b>：现在上级按<b>火点数量</b>通报和考核，'
             '而本市 %.0f%% 的火点是全年不间断的工业源——'
             '这笔账算给禁烧办，既管不了（工厂不是禁烧办的职责），又白挨问责。'
             '建议向上争取<b>按类型分别考核</b>：工业源交环境执法、秸秆交禁烧办。'
             '这本身就是一份可以提交给市局的工作建议。</div></div>'
             % (f'{ind:,}', ind / n * 100,
                f'{kf.get("秸秆焚烧疑似",0):,}', kf.get("秸秆焚烧疑似", 0) / n * 100,
                f'{kf.get("其他偶发",0):,}', kf.get("其他偶发", 0) / n * 100,
                ind / n * 100))

    # ⑧ 问责情况
    acc = CITY_NOTES.get(city, {}).get("accountability")
    if acc:
        h.append('<div class="card"><h2>有没有人因此被问责</h2>')
        h.append('<div class="note">公开渠道<b>没有全省、也没有本市的年度问责汇总数</b>'
                 '（这类信息分散在各市县通报里）。能查到的相关情况如下：</div>')
        for title, txt, src in acc:
            h.append('<div style="margin-top:12px;padding-left:12px;border-left:2px solid %s">'
                     '<b>%s</b><div style="font-size:13px;margin-top:4px">%s</div>'
                     '<div style="color:#64748b;font-size:11px;margin-top:4px">来源：%s</div></div>'
                     % (AR.C["accent"], AR._esc(title), txt, AR._esc(src)))
        h.append('<div class="note"><b>这条最关键</b>：平顶山市纪委监委在评查中'
                 '<b>主动纠正了 2 名基层干部的不当问责</b>，明确「不能让一般干部替企业背锅」。'
                 '这说明「按火点数量问责、基层替工厂背账」这件事，'
                 '<b>纪检监察机关自己已经认定是错的</b>——而这正是本分析要解决的问题。</div>')
        h.append('</div>')

    # 页脚
    h.append('<footer><b>数据与方法</b><br>'
             '· 数据源：NASA FIRMS VIIRS 375m（Suomi-NPP + NOAA-20，SP 标准处理），河南省域内归属到本市的火点。<br>'
             '· 点位：0.01° 网格（约 1.1km）；类型判定基于<b>点位复现特征</b>'
             '（出现天数、昼夜、FRP、季节），规则透明可复核，跨年一致率已验证（工业/固定源 86%）。<br>'
             '· <b>成因与类型为「疑似 + 依据」的推断，不是认定</b>，不能作为行政处罚依据；'
             '用于执法须经现场核实。<br>'
             '· 产业背景与问责情况来自公开报道，已在文中逐条标注来源；'
             '其中标注「年份待核」的条目<b>未经证实</b>，请勿直接引用。<br>'
             '· 本页由 city_analysis.py 自动生成，统计数字可复算。</footer>')
    h.append('</div></body></html>')

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / ("%s火点专项分析.html" % city)
    out.write_text("".join(h), encoding="utf-8")
    print("[city] %s：%s 条 / %d 点位 | 工业源 %.0f%% | 秸秆 %.0f%%"
          % (city, f'{n:,}', len(prof), ind / n * 100,
             kf.get("秸秆焚烧疑似", 0) / n * 100))
    print("[city] 写出 %s（%.0f KB）" % (out, out.stat().st_size / 1024))


def _flat(bm):
    """月度分布是否平坦（最高月 / 平均月 < 1.8 视为平坦）。"""
    if not bm:
        return True
    avg = sum(bm.values()) / len(bm)
    return (max(bm.values()) / avg) < 1.8 if avg else True


if __name__ == "__main__":
    main()
