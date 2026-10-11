# -*- coding: utf-8 -*-
"""河北持续火点专项：521 个点位集中在哪，是否与钢铁焦化带重合。

数据：
  · data/north6/fires-north6.json        六省两年火点（FIRMS VIIRS 375m）
  · data/north6/hebei-by-city.json       市级统计
  · geo/north6/{河北,唐山,邯郸,石家庄,秦皇岛}.json   边界（DataV）
用法：python hebei_report.py
"""
import collections
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annual_report as AR
import city_check as CC

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "report")
C = AR.C
# 区县 → 主导产业（公开信息归纳，非逐企业核实）
INDUSTRY = {
    "丰南区": "钢铁（纵横、瑞丰）、陶瓷", "迁安市": "钢铁（首钢迁安、九江线材、燕山）——「钢铁之都」",
    "丰润区": "钢铁、装备制造", "乐亭县": "钢铁（河钢乐亭）、京唐港",
    "滦州市": "钢铁（东海特钢）", "曹妃甸区": "钢铁（首钢京唐）、港口",
    "古冶区": "焦化、水泥、煤", "迁西县": "钢铁（津西钢铁）",
    "路南区": "城区", "路北区": "城区", "开平区": "陶瓷、装备",
    "玉田县": "装备制造", "遵化市": "钢铁、装备", "滦南县": "农业、轻工",
    "武安市": "钢铁（邯钢、普阳、裕华、明芳）——河北钢铁重镇",
    "涉县": "钢铁（天铁）", "峰峰矿区": "煤焦、建材", "复兴区": "钢铁（邯钢本部）",
    "磁县": "煤焦、建材", "永年区": "紧固件", "成安县": "装备",
    "平山县": "钢铁（敬业钢铁）", "鹿泉区": "建材、装备", "辛集市": "皮革、化工",
    "井陉矿区": "煤、建材", "井陉县": "建材", "灵寿县": "建材",
    "昌黎县": "钢铁（安丰钢铁）、葡萄酒", "卢龙县": "建材、轻工",
}


def esc(s):
    return AR._esc(s)


def svg_hbar(items, w=880, row_h=30, lab_w=104, val_w=170, unit="", color=None):
    mx = max(v for _, v in items) or 1
    h = row_h * len(items) + 10
    pw = w - lab_w - val_w
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (w, h)]
    for i, (lab, v) in enumerate(items):
        y = 5 + i * row_h
        bw = max(2, pw * v / mx)
        p.append('<text x="%d" y="%.1f" fill="%s" font-size="13" text-anchor="end">%s</text>'
                 % (lab_w - 8, y + 19, C["txt"], esc(lab)))
        p.append('<rect x="%d" y="%.1f" width="%.1f" height="%d" rx="4" fill="%s" opacity="0.88"/>'
                 % (lab_w, y + 5, bw, row_h - 12, color or C["hot"]))
        p.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12">%d%s</text>'
                 % (lab_w + bw + 8, y + 19, C["dim"], v, unit))
    p.append("</svg>")
    return "".join(p)


def main():
    fires = json.load(open(os.path.join(MOD, "data", "north6", "fires-north6.json"),
                           encoding="utf-8"))
    hb = [f for f in fires if f["province"] == "河北"]
    acc = collections.defaultdict(lambda: {"days": set(), "n": 0, "nd": set(), "frps": []})
    for f in hb:
        a = acc["%.2f,%.2f" % (f["lat"], f["lng"])]
        a["days"].add(f["date"]); a["n"] += 1; a["frps"].append(f["frp"])
        if f["dn"] == "N":
            a["nd"].add(f["date"])
    hot = {k: a for k, a in acc.items() if len(a["days"]) >= 10}
    hot_fire = sum(a["n"] for a in hot.values())

    def load(city):
        d = json.load(open(os.path.join(MOD, "geo", "north6", "%s.json" % city), encoding="utf-8"))
        out = []
        for f in d["features"]:
            polys = CC._rings(f["geometry"])
            xs, ys = [], []
            for poly in polys:
                for ring in poly:
                    for x, y in ring:
                        xs.append(x); ys.append(y)
            out.append((f["properties"]["name"], polys, (min(ys), max(ys), min(xs), max(xs))))
        return out

    def count_by(city, pts):
        cs = load(city)
        cnt, cntf = collections.Counter(), collections.Counter()
        for k, a in pts.items():
            la, ln = [float(v) for v in k.split(",")]
            for nm, polys, (y0, y1, x0, x1) in cs:
                if not (y0 <= la <= y1 and x0 <= ln <= x1):
                    continue
                if any(CC.in_poly(ln, la, p) for p in polys):
                    cnt[nm] += 1; cntf[nm] += a["n"]
                    break
        return cnt, cntf

    prov = load("河北")
    city_cnt, city_fire, city_all = collections.Counter(), collections.Counter(), collections.Counter()
    for k, a in hot.items():
        la, ln = [float(v) for v in k.split(",")]
        for nm, polys, (y0, y1, x0, x1) in prov:
            if not (y0 <= la <= y1 and x0 <= ln <= x1):
                continue
            if any(CC.in_poly(ln, la, p) for p in polys):
                city_cnt[nm] += 1; city_fire[nm] += a["n"]
                break
    for k, a in acc.items():
        la, ln = [float(v) for v in k.split(",")]
        for nm, polys, (y0, y1, x0, x1) in prov:
            if not (y0 <= la <= y1 and x0 <= ln <= x1):
                continue
            if any(CC.in_poly(ln, la, p) for p in polys):
                city_all[nm] += 1
                break

    ts = city_cnt.get("唐山市", 0); hd = city_cnt.get("邯郸市", 0)
    tot_city = sum(city_cnt.values())
    top2 = ts + hd
    city_bar = svg_hbar([(c.replace("市", ""), n) for c, n in city_cnt.most_common(10)],
                        unit=" 个", color=C["hot"])

    # 唐山 / 邯郸 区县
    def sub(city):
        cs = load(city)
        cnt, cntf = collections.Counter(), collections.Counter()
        for k, a in hot.items():
            la, ln = [float(v) for v in k.split(",")]
            for nm, polys, (y0, y1, x0, x1) in cs:
                if not (y0 <= la <= y1 and x0 <= ln <= x1):
                    continue
                if any(CC.in_poly(ln, la, p) for p in polys):
                    cnt[nm] += 1; cntf[nm] += a["n"]
                    break
        return cnt, cntf

    ts_cnt, ts_fire = sub("唐山")
    hd_cnt, hd_fire = sub("邯郸")
    sjz_cnt, sjz_fire = sub("石家庄")
    qhd_cnt, qhd_fire = sub("秦皇岛")
    ts_bar = svg_hbar([(c, n) for c, n in ts_cnt.most_common(8)], unit=" 个")
    hd_bar = svg_hbar([(c, n) for c, n in hd_cnt.most_common(6)], unit=" 个")

    night = sum(len(a["nd"]) for a in hot.values()) / sum(len(a["days"]) for a in hot.values()) * 100
    import statistics
    frp_med = statistics.median([statistics.median(a["frps"]) for a in hot.values()])
    hi = max(hot.values(), key=lambda a: len(a["days"]))

    dt = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    css = (AR.CSS.replace("__BG__", C["bg"]).replace("__PANEL__", C["panel"])
           .replace("__LINE__", C["line"]).replace("__TXT__", C["txt"])
           .replace("__DIM__", C["dim"]).replace("__DIM2__", C["dim2"])
           .replace("__ACC__", C["accent"]).replace("__HOT__", C["hot"]))

    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>河北持续火点专项分析</title><style>%s</style></head><body>' % css,
         AR.nav_back_html(),
         '<div class="wrap">',
         '<h1>河北持续火点专项分析</h1>',
         '<div class="sub">521 个持续排放点位集中在哪　·　'
         '数据：FIRMS VIIRS 375m 2024–2025　·　生成于 %s</div>' % dt]

    h.append('<div class="card" style="border-color:#f97316"><h2>核心结论</h2>'
             '<div style="font-size:18px;line-height:1.8">'
             '河北 %d 个持续排放点位，<span class="hl">%.0f%% 集中在唐山和邯郸两市</span> —— '
             '正好是河北钢铁、焦化最密集的两个市。'
             '</div>'
             '<div class="note">唐山 <b>%d 个</b>（%.1f%%）、邯郸 <b>%d 个</b>（%.1f%%），'
             '两市合计 %d 个。<br>'
             '再往下看，邯郸的 <b>武安市一个县级市就占 %d 个（%.0f%%）</b>、'
             '唐山的 <b>丰南区 %d 个、迁安市 %d 个、丰润区 %d 个</b> —— '
             '都是当地钢铁产能最集中的区县。<br>'
             '<b>「产业带重合」这个结论，在河北完整复现。</b></div></div>'
             % (len(hot), top2 / tot_city * 100, ts, ts / tot_city * 100,
                hd, hd / tot_city * 100, top2,
                hd_cnt.get("武安市", 0),
                hd_cnt.get("武安市", 0) / max(1, sum(hd_cnt.values())) * 100,
                ts_cnt.get("丰南区", 0), ts_cnt.get("迁安市", 0),
                ts_cnt.get("丰润区", 0)))

    h.append('<div class="kpi">'
             '<div><b>%s</b><span>两年火点（条）</span></div>'
             '<div><b>%d</b><span>持续排放点位（≥10 天）</span></div>'
             '<div><b>%s</b><span>持续点位贡献火点</span></div>'
             '<div><b>%.0f%%</b><span>持续点位夜间占比</span></div>'
             '</div>' % (format(len(hb), ","), len(hot), format(hot_fire, ","), night))

    h.append('<div class="card"><h2>一、市级分布：唐山 + 邯郸 = %.0f%%</h2>'
             '%s'
             '<table><tr><th>市</th><th class="num">持续点位</th><th class="num">占全省</th>'
             '<th class="num">贡献火点</th><th class="num">点位数</th>'
             '<th class="num">持续点占比</th></tr>' % (top2 / tot_city * 100, city_bar))
    for c, n in city_cnt.most_common():
        h.append('<tr><td><b>%s</b></td><td class="num">%d</td><td class="num">%.1f%%</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%.1f%%</td></tr>'
                 % (esc(c), n, n / tot_city * 100, format(city_fire[c], ","),
                    format(city_all[c], ","), n / city_all[c] * 100 if city_all[c] else 0))
    h.append('</table>'
             '<div class="note">唐山一个市就占了一半以上。'
             '而点位数最多的其实是沧州（2,949 个）和保定（2,036 个），'
             '但它们的持续点位分别只有 19 个和 18 个 —— '
             '<b>点位多不等于持续源多</b>，这是两个概念。</div></div>')

    h.append('<div class="card"><h2>二、唐山（%d 个）：七个区县吃掉九成</h2>'
             '%s'
             '<table><tr><th>区县</th><th class="num">持续点位</th><th class="num">贡献火点</th>'
             '<th>主导产业（公开信息）</th></tr>' % (ts, ts_bar))
    for c, n in ts_cnt.most_common(10):
        h.append('<tr><td><b>%s</b></td><td class="num">%d</td><td class="num">%s</td>'
                 '<td>%s</td></tr>'
                 % (esc(c), n, format(ts_fire[c], ","), esc(INDUSTRY.get(c, "—"))))
    h.append('</table>'
             '<div class="note">丰南、迁安、丰润、乐亭、滦州、曹妃甸、古冶 —— '
             '这七个区县都是唐山钢铁产能的集中地（迁安被称为「钢铁之都」，'
             '曹妃甸是首钢京唐所在地，古冶是焦化/水泥老基地）。<br>'
             '<b>注意迁安</b>：只有 39 个点位，却贡献了 <b>%s 条</b>火点 —— '
             '点位数量不如丰南（54 个），但火点更多，说明这里的源<b>烧得更频繁</b>。</div></div>'
             % (format(ts_fire.get("迁安市", 0), ",")))

    h.append('<div class="card"><h2>三、邯郸（%d 个）：武安一县占近六成</h2>'
             '%s'
             '<table><tr><th>区县</th><th class="num">持续点位</th><th class="num">贡献火点</th>'
             '<th>主导产业（公开信息）</th></tr>' % (hd, hd_bar))
    for c, n in hd_cnt.most_common(8):
        h.append('<tr><td><b>%s</b></td><td class="num">%d</td><td class="num">%s</td>'
                 '<td>%s</td></tr>'
                 % (esc(c), n, format(hd_fire[c], ","), esc(INDUSTRY.get(c, "—"))))
    h.append('</table>'
             '<div class="note"><b>武安市 %d 个点位、%s 条火点</b> —— '
             '一个县级市占了邯郸全市的 %.0f%%。武安是河北钢铁重镇'
             '（邯钢、普阳、裕华、明芳等），与「钢铁产能集中区」完全对应。<br>'
             '涉县（天铁）、峰峰矿区（煤焦）、复兴区（邯钢本部）也都是重工业区。</div></div>'
             % (hd_cnt.get("武安市", 0), format(hd_fire.get("武安市", 0), ","),
                hd_cnt.get("武安市", 0) / sum(hd_cnt.values()) * 100))

    h.append('<div class="card"><h2>四、石家庄与秦皇岛：同一个规律，规模小一号</h2>'
             '<table><tr><th>市</th><th>区县</th><th class="num">持续点位</th>'
             '<th>主导产业</th></tr>'
             '<tr><td rowspan="4"><b>石家庄</b><br>（%d 个）</td><td>平山县</td>'
             '<td class="num">%d</td><td>%s</td></tr>'
             '<tr><td>鹿泉区</td><td class="num">%d</td><td>%s</td></tr>'
             '<tr><td>辛集市</td><td class="num">%d</td><td>%s</td></tr>'
             '<tr><td>井陉矿区</td><td class="num">%d</td><td>%s</td></tr>'
             '<tr><td rowspan="2"><b>秦皇岛</b><br>（%d 个）</td><td>昌黎县</td>'
             '<td class="num">%d</td><td>%s</td></tr>'
             '<tr><td>卢龙县</td><td class="num">%d</td><td>%s</td></tr>'
             '</table>'
             '<div class="note">石家庄的平山（敬业钢铁）、秦皇岛的昌黎（安丰钢铁）'
             '同样是钢铁产区，只是规模小一号。'
             '<b>规律一致：有钢铁的地方就有持续火点。</b></div></div>'
             % (sum(sjz_cnt.values()), sjz_cnt.get("平山县", 0), esc(INDUSTRY["平山县"]),
                sjz_cnt.get("鹿泉区", 0), esc(INDUSTRY["鹿泉区"]),
                sjz_cnt.get("辛集市", 0), esc(INDUSTRY["辛集市"]),
                sjz_cnt.get("井陉矿区", 0), esc(INDUSTRY["井陉矿区"]),
                sum(qhd_cnt.values()), qhd_cnt.get("昌黎县", 0), esc(INDUSTRY["昌黎县"]),
                qhd_cnt.get("卢龙县", 0), esc(INDUSTRY["卢龙县"])))

    h.append('<div class="card"><h2>五、与河南对照</h2>'
             '<table><tr><th>维度</th><th>河北</th><th>河南</th></tr>'
             '<tr><td>两年火点</td><td>%s 条</td><td>45,597 条</td></tr>'
             '<tr><td>持续排放点位</td><td><b>%d 个</b></td><td>203 个</td></tr>'
             '<tr><td>持续点占比</td><td>%.1f%%</td><td>49.5%%</td></tr>'
             '<tr><td>最集中的市</td><td>唐山 %.1f%% + 邯郸 %.1f%%</td>'
             '<td>安阳 6,688 条 / 平顶山 6,906 条</td></tr>'
             '<tr><td>核心区县</td><td>武安市 %d 个、丰南区 %d 个、迁安市 %d 个</td>'
             '<td>安阳县 18 个 + 殷都区 12 个</td></tr>'
             '<tr><td>对应产业</td><td>钢铁 + 焦化（唐山、邯郸）</td>'
             '<td>钢铁 + 焦化（安阳）、煤焦（平顶山）</td></tr>'
             '</table>'
             '<div class="note">两省的结构<b>完全同构</b>：都是「钢铁/焦化集聚区 = 持续火点集聚区」。'
             '区别只是规模 —— 河北 %d 个点位是河南 203 个的 %.1f 倍，'
             '因为河北的钢铁产能本身就比河南大得多。<br>'
             '这也说明<b>这套方法可以直接复制到其他省份</b>：'
             '找钢铁、焦化、煤化工的集聚区，就能预判持续火点会在哪里。</div></div>'
             % (format(len(hb), ","), len(hot), len(hot) / len(acc) * 100,
                ts / tot_city * 100, hd / tot_city * 100,
                hd_cnt.get("武安市", 0), ts_cnt.get("丰南区", 0), ts_cnt.get("迁安市", 0),
                len(hot), len(hot) / 203))

    h.append(AR.qr_foot("../../../assets"))


    h.append('<footer>'
             '数据：NASA FIRMS VIIRS 375m（VIIRS_SNPP_SP + VIIRS_NOAA20_SP，2024–2025）· '
             'DataV.GeoAtlas 行政区划<br>'
             '方法：0.01° 网格聚合 → 出现 ≥10 天判为持续排放点位 → '
             '按市/县界射线法归属（先 bbox 预筛再逐多边形判定）<br>'
             '<b>边界声明</b>：区县归属依赖边界数据精度，边界附近点位可能误归；'
             '「主导产业」一列为<b>公开信息归纳，未逐企业核实</b>；'
             '火点位置与具体企业的对应关系需现场核查。<br>'
             '生成：%s</footer>' % dt)
    h.append('</div></body></html>')

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "河北持续火点专项分析.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("".join(h))
    print("已生成", fp, "%.0f KB" % (os.path.getsize(fp) / 1024))
    print("唐山 %d + 邯郸 %d = %d / %d (%.0f%%)" % (ts, hd, top2, tot_city, top2 / tot_city * 100))
    print("武安市 %d 个（占邯郸 %.0f%%）｜迁安市 %d 个 / %s 条火点"
          % (hd_cnt.get("武安市", 0), hd_cnt.get("武安市", 0) / sum(hd_cnt.values()) * 100,
             ts_cnt.get("迁安市", 0), format(ts_fire.get("迁安市", 0), ",")))


if __name__ == "__main__":
    main()
