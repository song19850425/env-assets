# -*- coding: utf-8 -*-
"""交付层：导航页（归档目录页 + 模块首页）—— 本地与云端共用同一套模板

为什么单独成文件
----------------
这两类导航页在**两个地方**都会被生成，且指向同一批文件：
  · 本地  deploy_github.py（每次推送前重建）
  · 云端  cloud/report_cloud.py / cloud/report_cloud_period.py（每小时跑完重建）
模板各写一份的后果：两边轮流覆盖，同一个 index.html 内容来回翻转，
git 里堆满无意义的 diff，出了问题也说不清哪一份才是"对"的。
放在这里 = 唯一源，deploy_github.py 会自动镜像给云端复用（见 CLOUD_MIRROR）。

另外还有一件容易踩的事：**归档文件名**。
本地产物叫「大气管家豫北周报_0917_to_0923.html」（带前缀，便于本地排序识别），
模块内归档叫「0917_to_0923.html」（去前缀）。云端若各按各的写法，
同一个板块就会攒出两套重复文件。故 archive_name() 也放这里。

目录相对深度固定：模块/<子目录>/index.html 与 模块/index.html，
回链分别用 ../ 与 ../../（deploy 与云端目录结构相同，故可共用）。
"""
import os
import re

# 模块内三个板块：(子目录, 本地文件名前缀, 显示名)
SECTIONS = [
    ("daily",   "大气管家豫北日报", "每日一页纸"),
    ("weekly",  "大气管家豫北周报", "周报"),
    ("monthly", "大气管家豫北月报", "月报"),
]

SOURCE_NOTE = "数据来源：中国环境监测总站·全国城市空气质量实时发布平台（air.cnemc.cn:18007）"

# 目录页与模块首页仅 li 间距不同（8px vs 6px），其余完全一致。
# 首尾的换行是刻意的：模板里 <style> 与 </style> 各自独占一行，去掉就会与线上不符。
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#F5F4F0;color:#2B2B28;font-size:14px;line-height:1.7}
.page{max-width:720px;margin:24px auto;background:#fff;border:1px solid #E2E0D8;border-radius:12px;padding:28px 32px}
h1{font-size:20px;color:#1F3B2C;border-bottom:3px solid #1F5C45;padding-bottom:10px}
li{margin:LI_MARGIN 0;list-style:none}a{color:#1F5C45}
.note{background:#FDF3E7;border:1px solid #E8C99F;border-radius:8px;padding:10px 14px;font-size:12.5px;margin:14px 0}
"""


def archive_name(fname, prefix):
    """本地产物文件名 → 模块内归档文件名（去掉本地前缀）"""
    return fname[len(prefix) + 1:] if fname.startswith(prefix + "_") else fname


def write_if_changed(path, html):
    """内容一致就不落盘。返回是否真的写了。

    为什么需要：云端每小时跑一次，但周报/月报的**内容**一天才变一次。
    不判断的话，每个整点都会因"生成时间"这类字段变更而重写文件，
    一小时一次的无意义提交会把仓库撑肥，也让提交历史失去意义。
    """
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == html:
                    return False
        except Exception:
            pass
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return True


def dated_files(sub_dir):
    """板块内已归档的期数文件（不含 index/latest），最新在前"""
    if not os.path.isdir(sub_dir):
        return []
    return sorted((f for f in os.listdir(sub_dir)
                   if f.endswith(".html") and f not in ("index.html", "latest.html")),
                  reverse=True)


# 报告页每次渲染都会变的"生成时间"有两处，判断"内容是否真的变了"必须都抹掉，
# 否则永远判为"变了"：
#   ① 页眉的"生成：YYYY-MM-DD HH:MM"（日报/周报/月报都有）
#   ② 日报证据链里的"本页生成时刻：<b>YYYY-MM-DD HH:MM:SS</b>"
STAMP_RE = re.compile(r"生成：\d{4}-\d{2}-\d{2} \d{2}:\d{2}"
                      r"|生成时刻：<b>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}</b>")


def same_content(path, html):
    """忽略生成时间后比对，True = 与磁盘上那份实质相同"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except Exception:
        return False
    return STAMP_RE.sub("生成：T", old) == STAMP_RE.sub("生成：T", html)


def write_report(path, html):
    """报告页写盘（带去抖）：实质内容未变则不写，返回 False。

    为什么必须去抖：云端每小时跑一次，而日报背后是小时数据、周报/月报背后是日数据 ——
    只按"文件内容完全一致"判断的话，光是生成时间变化就会触发整点提交，
    一小时一次的无意义提交会把仓库撑肥（周报+月报约 32 KB/次 → 一年近 300 MB）。
    """
    if same_content(path, html):
        return False
    return write_if_changed(path, html)


def section_index(sub_dir, prefix, label):
    """生成板块归档目录页 <子目录>/index.html。返回是否写入。"""
    items = ""
    dated = dated_files(sub_dir)
    if dated:
        items += "<li><a href='latest.html'>最新一期</a></li>"
        items += "\n".join("<li><a href='%s'>%s</a></li>" % (f, archive_name(f, prefix)[:-5])
                              for f in dated)
    html = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>大气管家 · 豫北 %s · 归档</title><style>%s</style></head><body><div class="page">
<h1>大气管家 · 豫北四市%s（安阳 · 濮阳 · 鹤壁 · 新乡）</h1>
<div class="note">%s。页面由自动化流水线每日自动生成，未经人工审定，仅供技术交流参考，不作为行政决策或处罚依据。</div>
<ul>%s</ul>
<p style="margin-top:16px"><a href="../index.html">← 返回模块目录</a> ｜ <a href="../../../index.html">env-assets 总目录</a></p>
</div></body></html>""" % (label, _CSS.replace("LI_MARGIN", "6px"), label, SOURCE_NOTE, items)
    return write_if_changed(os.path.join(sub_dir, "index.html"), html)


def module_home(module_dir, sections=SECTIONS):
    """生成模块首页 <模块>/index.html（各板块入口 + 归档期数）。返回是否写入。

    小时序列看板是单页（无归档），由**云端** report_cloud_hourly.py 生成到 模块/hourly/index.html；
    本机 deploy 只重建导航页、不产出该文件。故入口**只在文件确实存在时**才输出 ——
    否则本机 deploy 的死链自检会把它当成死链（云端先产出、本机后对齐，两侧结果自然一致）。
    """
    secs = ""
    for sub, _prefix, label in sections:
        n = len(dated_files(os.path.join(module_dir, sub)))
        secs += "<li><a href='%s/latest.html'>%s · 最新一期</a> ｜ <a href='%s/index.html'>归档（%d 期）</a></li>" % (
            sub, label, sub, n)
    if os.path.exists(os.path.join(module_dir, "hourly", "index.html")):
        secs += ("<li><a href='hourly/index.html'>小时序列看板 · 最近 7 天</a>"
                 "（逐时点位值 + 采集覆盖 + 气象；含「缺了哪些小时」）</li>")
    html = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>大气管家 · 豫北每日一页纸</title><style>%s</style></head><body><div class="page">
<h1>大气管家 · 豫北四市空气质量报告（安阳 · 濮阳 · 鹤壁 · 新乡）</h1>
<div class="note">%s。全部页面由自动化流水线自动生成，未经人工审定，仅供技术交流参考，不作为行政决策或处罚依据。周期口径：日报=当日实时；周报=最近 7 个完整日；月报=平台开放历史窗口（整月口径随本地数据库积累切换）；小时看板=近 7 天逐时点位值。</div>
<ul>%s</ul>
<p style="margin-top:16px"><a href="../../index.html">← 返回 env-assets 总目录</a></p>
</div></body></html>""" % (_CSS.replace("LI_MARGIN", "8px"), SOURCE_NOTE, secs)
    return write_if_changed(os.path.join(module_dir, "index.html"), html)
