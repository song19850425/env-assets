# -*- coding: utf-8 -*-
"""构造一份「结构上像真的」第三方检测报告 PDF，用于测试抽取层。

为什么需要它
------------
抽取层要测的是「能不能从真实报告里把字段抠出来」。没有真报告时，
用一份**刻意还原真实结构难点**的构造报告做基线测试，比空谈可行。

刻意还原的难点（都是真实报告里常见的）：
  · 表头跨列合并，单位写在表头而不是每行
  · 「标准限值」列带括号说明（如「1.0（第一类用地筛选值）」）
  · 依据的标准号写在**表下脚注**，不在表格里
  · 一个项目**故意不写用地类型**（用来验证「不知道就说不知道」而不是猜）
  · 同一份报告里混两个标准（GB 36600 土壤 / GB/T 14848 地下水）

生成方式：HTML → Chromium 打印成 PDF（有文本层，不是扫描件）。
⚠ 这是**构造报告**，不是任何真实项目的检测报告。

跑法：python EnvStandard/tools/make_sample_report.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT_DIR = REPO / "EnvStandard" / "extract" / "sample"
OUT_HTML = OUT_DIR / "sample-report.html"
OUT_PDF = OUT_DIR / "sample-report.pdf"
OUT_TRUTH = OUT_DIR / "ground-truth.json"

# (项目, 介质, 单位, 检出限, 结果, 限值文本, 结论)
SOIL_ROWS = [
    ("苯", "mg/kg", "0.05", "5.2", "1.0（第一类用地筛选值）", "超标"),
    ("四氯化碳", "mg/kg", "0.03", "0.4", "0.9（第一类用地筛选值）", "未超标"),
    ("砷", "mg/kg", "0.5", "18", "20（第一类用地筛选值）", "未超标"),
    ("铅", "mg/kg", "2", "510", "400（第一类用地筛选值）", "超标"),
]
GW_ROWS = [
    ("四氯化碳", "μg/L", "0.4", "1.8", "2.0（Ⅲ类）", "未超标"),
    ("苯", "μg/L", "0.4", "4.6", "10.0（Ⅲ类）", "未超标"),
    ("三氯乙烯", "μg/L", "0.4", "12.5", "70.0（Ⅲ类）", "未超标"),
]

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: "SimSun","Songti SC",serif; font-size: 10.5pt; color:#000; line-height:1.6; }}
h1 {{ font-size: 15pt; text-align:center; margin:0 0 4px; }}
.sub {{ text-align:center; font-size:9pt; color:#333; margin-bottom:14px; }}
.meta {{ font-size:9.5pt; margin-bottom:10px; }}
.meta td {{ padding:2px 8px 2px 0; }}
h2 {{ font-size:11pt; margin:16px 0 6px; }}
table.d {{ width:100%; border-collapse:collapse; font-size:9.5pt; }}
table.d th, table.d td {{ border:1px solid #000; padding:4px 6px; }}
table.d th {{ background:#eee; text-align:center; font-weight:bold; }}
table.d td.c {{ text-align:center; }}
.note {{ font-size:9pt; margin-top:8px; line-height:1.7; }}
.note b {{ font-weight:bold; }}
</style></head><body>

<h1>检 测 报 告</h1>
<div class="sub">报告编号：DEMO-2026-0929-001</div>

<table class="meta">
<tr><td>委托单位：</td><td>某某有限公司</td><td>受检单位：</td><td>某某有限公司</td></tr>
<tr><td>项目名称：</td><td colspan="3">某某地块土壤及地下水环境质量检测</td></tr>
<tr><td>采样日期：</td><td>2026-09-20</td><td>分析日期：</td><td>2026-09-21 至 2026-09-26</td></tr>
</table>

<h2>一、土壤检测结果</h2>
<table class="d">
<thead>
<tr>
  <th rowspan="2">序号</th><th rowspan="2">检测项目</th><th rowspan="2">单位</th>
  <th rowspan="2">检出限</th><th rowspan="2">检测结果</th>
  <th colspan="2">评价</th>
</tr>
<tr><th>标准限值</th><th>结论</th></tr>
</thead>
<tbody>
{SOIL_BODY}
</tbody>
</table>
<div class="note">
注 1：土壤样品评价依据 <b>GB 36600-2018</b>《土壤环境质量 建设用地土壤污染风险管控标准（试行）》
表 1 第一类用地筛选值。<br>
注 2：检出限为本方法（HJ 605-2011、HJ 680-2013、HJ 491-2019）在 5 g 取样量下的方法检出限。
</div>

<h2>二、地下水检测结果</h2>
<table class="d">
<thead>
<tr>
  <th rowspan="2">序号</th><th rowspan="2">检测项目</th><th rowspan="2">单位</th>
  <th rowspan="2">检出限</th><th rowspan="2">检测结果</th>
  <th colspan="2">评价</th>
</tr>
<tr><th>标准限值</th><th>结论</th></tr>
</thead>
<tbody>
{GW_BODY}
</tbody>
</table>
<div class="note">
注 3：地下水样品评价依据 <b>GB/T 14848-2017</b>《地下水质量标准》表 1 Ⅲ类标准限值。<br>
注 4：四氯化碳、苯、三氯乙烯采用 HJ 639-2012 吹扫捕集/气相色谱-质谱法测定，
SIM 方式测定下限 1.6 μg/L。
</div>

<h2>三、质量保证与质量控制</h2>
<div class="note">
本批次土壤样品 4 个、地下水样品 3 个，共采集运输空白 1 个、全程序空白 1 个，
平行双样 1 个。空白试验结果均满足 HJ 605-2011 第 11.4.1 条控制指标。<br>
⚠ 本报告为<b>教学构造样本</b>，用于测试数据抽取，不是任何真实项目的检测报告。
</div>

</body></html>
"""


def rows_html(rows):
    out = []
    for i, (name, unit, mdl, val, limit, concl) in enumerate(rows, 1):
        out.append(
            f"<tr><td class='c'>{i}</td><td class='c'>{name}</td><td class='c'>{unit}</td>"
            f"<td class='c'>{mdl}</td><td class='c'>{val}</td>"
            f"<td class='c'>{limit}</td><td class='c'>{concl}</td></tr>"
        )
    return "\n".join(out)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = HTML.replace("{SOIL_BODY}", rows_html(SOIL_ROWS)).replace("{GW_BODY}", rows_html(GW_ROWS))
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")

    # ground truth：抽取层要能还原成这个
    truth = {
        "_comment": "构造报告的正确答案。抽取层输出要与此比对。",
        "report": {"id": "DEMO-2026-0929-001", "title": "某某地块土壤及地下水环境质量检测"},
        "items": [],
    }
    for name, unit, mdl, val, limit, concl in SOIL_ROWS:
        truth["items"].append({
            "factor": name, "matrix": "soil", "standard": "GB36600-2018",
            "basis": {"landUse": "first", "kind": "screening"},
            "statedLimit": float(limit.split("（")[0]),
            "result": float(val),
            # 报告写「未超标」，引擎的词汇是「达标」—— 抽取层必须归一化，这是要测的点之一
            "conclusion": "超标" if "未" not in concl else "达标",
            "limitText": limit, "unit": unit,
        })
    for name, unit, mdl, val, limit, concl in GW_ROWS:
        truth["items"].append({
            "factor": name, "matrix": "groundwater", "standard": "GBT14848-2017",
            "basis": {"classLevel": "III"},
            "statedLimit": float(limit.split("（")[0]),
            "result": float(val),
            "conclusion": "超标" if "未" not in concl else "达标",
            "limitText": limit, "unit": unit,
        })
    OUT_TRUTH.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")

    print(f"[sample] HTML {OUT_HTML}")
    print(f"[sample] 真值 {OUT_TRUTH}  共 {len(truth['items'])} 项")
    print("[sample] 下一步：用 Node 的 playwright-core 把 HTML 打成 PDF")
    print("         node EnvStandard/tools/print_pdf.mjs")


if __name__ == "__main__":
    main()
