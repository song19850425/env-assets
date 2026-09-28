#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 env-assets 首页按「EnvLab 学习 / EnvWork 干活 / EnvData 数据」三条产品线重组。

核心判断：**不移动任何文件**。
  132 个页面已发布，移动会让所有 URL 失效、SEO 归零、外部链接全断。
  现有 7 个分区的顺序（01+02 | 03+04+05+07 | 08）本来就已按产品线聚好，
  所以只需在 HTML 里插入「1 个顶部导航 + 3 个产品线标题」，其余一个字符不动。

改动仅三处：
  1. </style> 前插入 CSS（.pnav / .pline）
  2. .intro 之后插入三入口导航
  3. #grid 内在 data-g=0 / 2 / 6 前插入产品线标题（带锚点 id）

所有 URL、所有 <li>、原有 JS（搜索 / 筛选 / 快捷键）保持原样。
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(_HERE, "index.html")

CSS = """
/* ---- 三条产品线 ---- */
.pnav{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0 6px}
.pnav-i{display:block;text-decoration:none;border:1px solid #23375a;border-left:3px solid var(--pc,#38bdf8);
  border-radius:12px;background:#0f1a2e;padding:14px 16px;transition:border-color .15s,transform .15s}
.pnav-i:hover{border-color:var(--pc,#38bdf8);transform:translateY(-1px)}
.pnav-t{display:block;font-size:16px;font-weight:600;color:#e6eefc}
.pnav-s{display:block;font-size:11.5px;color:var(--pc,#38bdf8);margin:3px 0 6px}
.pnav-d{display:block;font-size:12px;color:#7d94b4;line-height:1.6}
.pline{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:26px 0 4px;padding:10px 0 8px;border-bottom:1px solid #1e3350}
.pline-b{display:inline-block;font-size:10px;letter-spacing:.12em;font-weight:600;
  border-radius:6px;padding:3px 9px;background:rgba(56,189,248,.12);color:var(--pc,#38bdf8)}
.pline-t{font-size:14px;color:#8ba0bd}
.pline-n{font-size:11.5px;color:#5f7a9e}
@media(max-width:860px){.pnav{grid-template-columns:1fr}}
"""

NAV = """
<div class="pnav">
  <a class="pnav-i" href="#envlab" style="--pc:#38bdf8">
    <span class="pnav-t">① 我要学习</span>
    <span class="pnav-s">EnvLab · 84 件</span>
    <span class="pnav-d">虚拟实验 · 仪器培训 · 采样模拟 · 检测流程<br>学生 / 教师 / 新员工 / 检测机构培训</span>
  </a>
  <a class="pnav-i" href="#envwork" style="--pc:#fbbf24">
    <span class="pnav-t">② 我要干活</span>
    <span class="pnav-s">EnvWork · 21 件</span>
    <span class="pnav-d">监测方案 · 标准速查 · CMA/CNAS 核查 · SOP · 环保合规 · 案例库<br>检测机构 / 环保公司 / 咨询公司 / 企业环保人员</span>
  </a>
  <a class="pnav-i" href="#envdata" style="--pc:#fb923c">
    <span class="pnav-t">③ 我要看数据</span>
    <span class="pnav-s">EnvData · 自动更新</span>
    <span class="pnav-d">豫北四市空气质量日报 / 周报 / 月报<br>流水线每小时自动跑，无需人工</span>
  </a>
</div>
"""

HEADERS = [
    # (插入到哪个 data-g 之前, id, 徽标, 名称, 件数说明, 说明, 颜色)
    ("0", "envlab", "EnvLab", "学习 · 学会环境检测", "84 件",
     "虚拟实验、仪器培训、采样模拟、检测流程 —— 面向学生 / 教师 / 新员工 / 检测机构培训", "#38bdf8"),
    ("2", "envwork", "EnvWork", "干活 · 帮环境从业人员干活", "21 件",
     "监测方案生成、标准速查、CMA/CNAS 核查、服务 SOP、环保合规、真实案例库 —— 面向检测机构 / 环保公司 / 咨询公司 / 企业环保人员", "#fbbf24"),
    ("6", "envdata", "EnvData", "数据 · 环境数据自动化", "自动更新",
     "大气管家：豫北四市空气质量日报 / 周报 / 月报，流水线每小时自动生成推送", "#fb923c"),
]


def header_html(g, hid, badge, title, cnt, desc, color):
    return ('\n<div class="pline" id="%s" style="--pc:%s">\n'
            '  <span class="pline-b">%s</span>\n'
            '  <span class="pline-t">%s</span>\n'
            '  <span class="pline-n">%s</span>\n'
            '  <div style="flex:1 0 100%%;font-size:12px;color:#5f7a9e;margin-top:4px;line-height:1.6">%s</div>\n'
            '</div>\n' % (hid, color, badge, title, cnt, desc))


def main():
    s = io.open(INDEX, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in s else "\n"
    before = len(s.encode("utf-8"))
    print("  换行：%s | 原始 %d 字节" % ("CRLF" if nl == "\r\n" else "LF", before))
    acts = []

    # ① CSS
    if ".pline{" in s:
        print("  · CSS 已存在，跳过")
    else:
        i = s.find("</style>")
        if i == -1:
            raise SystemExit("✗ 找不到 </style>")
        s = s[:i] + CSS.replace("\n", nl) + s[i:]
        acts.append("插入 CSS")

    # ② 导航（插在 .intro 之后）
    if 'class="pnav"' in s:
        print("  · 导航已存在，跳过")
    else:
        m = re.search(r'</div>\r?\n(?=\r?\n<div style="margin:26px 0 14px)', s)
        if not m:
            # 退一步：找 .intro 结束
            m = re.search(r'(<div class="intro">.*?</div>\r?\n)', s, re.S)
            if not m:
                raise SystemExit("✗ 找不到 .intro 锚点")
            s = s[:m.end()] + nl + NAV.replace("\n", nl) + s[m.end():]
        else:
            s = s[:m.end()] + nl + NAV.replace("\n", nl) + s[m.end():]
        acts.append("插入三入口导航")

    # ③ 产品线标题（必须在 #grid 内、在对应 .sec 之前）
    for g, hid, badge, title, cnt, desc, color in HEADERS:
        if 'id="%s"' % hid in s:
            print("  · 标题 %s 已存在，跳过" % hid)
            continue
        pat = '<div class="sec" data-g="%s">' % g
        i = s.find(pat)
        if i == -1:
            raise SystemExit("✗ 找不到分区锚点 data-g=%s" % g)
        s = s[:i] + header_html(g, hid, badge, title, cnt, desc, color).replace("\n", nl) + nl + s[i:]
        acts.append("插入标题 %s" % hid)

    # 结构自检
    bad = []
    if not s.lstrip().startswith("<!DOCTYPE html>"):
        bad.append("开头不是 <!DOCTYPE html>")
    if not s.rstrip().endswith("</html>"):
        bad.append("结尾不是 </html>")
    for k in ['id="envlab"', 'id="envwork"', 'id="envdata"', 'class="pnav"', '<div class="grid" id="grid">']:
        if k not in s:
            bad.append("缺 " + k)
    n_sec = len(re.findall(r'<div class="sec"', s))
    if n_sec != 7:
        bad.append("分区数变了：%d（应 7）" % n_sec)
    if bad:
        raise SystemExit("✗ 结构自检失败：%s" % "；".join(bad))

    io.open(INDEX, "w", encoding="utf-8", newline="").write(s)
    print("  ✓ " + "；".join(acts))
    print("  ✓ 结构自检通过（分区仍 7 个、三个锚点齐全、DOCTYPE 完整）")
    print("  %d → %d 字节（+%d）" % (before, len(s.encode("utf-8")), len(s.encode("utf-8")) - before))


if __name__ == "__main__":
    main()
