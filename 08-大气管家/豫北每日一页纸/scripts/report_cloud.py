# -*- coding: utf-8 -*-
"""大气管家 · 云端日报生成器（自包含，仅标准库）

为什么需要它
------------
采集已经在云端（air_collect.py + .github/workflows/air-hourly.yml），但报告过去仍在本机生成 ——
本机关机时，公开页 daily/latest.html 就停在旧日期，"不开机也能看到新数据"只做到一半。
本脚本让日报也做到：**云端采集完顺手出报，不需要本机参与。**

输入：<data-hourly>/YYYY-MM-DD.jsonl（air_collect.py 的产出）
输出：<模块>/daily/<日期>.html + latest.html + index.html

渲染代码不在这里重写：直接复用同目录的**镜像副本**
    aqi_stats.py   ← 项目 calc/aqi_stats.py
    daily_page.py  ← 项目 report/daily_page.py
由项目 deploy_github.py 的 sync_cloud_scripts() 每次自动同步，
因此不存在"两份模板各改各的"的问题。

退出码：0 成功；1 无可用数据（让 workflow 显红，便于告警）
用法：python report_cloud.py [daily 输出目录]
环境变量：AIR_DATA_DIR / AIR_DAILY_DIR 可覆盖输入输出目录
"""
import glob
import gzip
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.dirname(HERE)                                  # …/豫北每日一页纸
DATA_DIR = os.path.join(MODULE, "data-hourly")
DAILY_DIR = os.path.join(MODULE, "daily")

# 让镜像副本保持项目内的导入路径：
# daily_page.py 里写的是 `from calc.aqi_stats import aqi_level`，
# 只要把 calc / report 两个"包"的 __path__ 指向本目录即可原样复用，
# 不必改写源码 —— 改写会让镜像与源文件产生实质差异，就失去复用的意义了。
for _name in ("calc", "report"):
    _m = types.ModuleType(_name)
    _m.__path__ = [HERE]
    sys.modules.setdefault(_name, _m)
sys.path.insert(0, HERE)

from report.daily_page import render        # noqa: E402
from calc.aqi_stats import city_summary     # noqa: E402

# 与项目 config.PROFILES["yubei"] 对齐（只取渲染需要的键；本文件不引项目 config）
CFG = {
    "sample": True,
    "client_name": "豫北四市（安阳·濮阳·鹤壁·新乡）",
    "source": "https://air.cnemc.cn:18007  中国环境监测总站·全国城市空气质量实时发布平台",
}

# 与项目 deploy_github.section_index() 保持同一套静态模板（本地/云端谁生成都一样）
INDEX_TPL = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>大气管家 · 豫北 每日一页纸 · 归档</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#F5F4F0;color:#2B2B28;font-size:14px;line-height:1.7}
.page{max-width:720px;margin:24px auto;background:#fff;border:1px solid #E2E0D8;border-radius:12px;padding:28px 32px}
h1{font-size:20px;color:#1F3B2C;border-bottom:3px solid #1F5C45;padding-bottom:10px}
li{margin:6px 0;list-style:none}a{color:#1F5C45}
.note{background:#FDF3E7;border:1px solid #E8C99F;border-radius:8px;padding:10px 14px;font-size:12.5px;margin:14px 0}
</style></head><body><div class="page">
<h1>大气管家 · 豫北四市每日一页纸（安阳 · 濮阳 · 鹤壁 · 新乡）</h1>
<div class="note">数据来源：中国环境监测总站·全国城市空气质量实时发布平台（air.cnemc.cn:18007）。页面由自动化流水线每日自动生成，未经人工审定，仅供技术交流参考，不作为行政决策或处罚依据。</div>
<ul>%s</ul>
<p style="margin-top:16px"><a href="../index.html">← 返回模块目录</a> ｜ <a href="../../../index.html">env-assets 总目录</a></p>
</div></body></html>"""


def _read_file(path):
    """逐行产出记录；单行损坏跳过（JSONL 是追加写的，尾部可能截断）"""
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception as e:
        print("[警告] 读取失败 %s：%s" % (os.path.basename(path), e))


def load_latest(data_dir):
    """取最新时点的全部点位行，返回 (timepoint, records)。

    只读最新的 1–2 个文件：文件按日期命名，最新时点必然落在最新的文件里。
    """
    files = sorted(glob.glob(os.path.join(data_dir, "*.jsonl")) +
                   glob.glob(os.path.join(data_dir, "*.jsonl.gz")))
    for p in reversed(files[-2:]):
        rows, tp = [], ""
        for r in _read_file(p):
            if r.get("k") != "s":
                continue
            t = str(r.get("tp", ""))[:16]
            if not t:
                continue
            if t > tp:
                tp, rows = t, [r]
            elif t == tp:
                rows.append(r)
        if tp:
            return tp, rows
    return "", []


def to_rows(recs):
    """云端简写字段 → city_summary / daily_page 需要的键名（与 fetch_air 对齐）"""
    return [{
        "city": r.get("city"), "station_name": r.get("st", ""),
        "station_code": r.get("code", ""), "timepoint": str(r.get("tp", ""))[:16],
        "aqi": r.get("aqi"), "quality": r.get("q", ""),
        "primary_pollutant": r.get("pri", ""),
        "pm25": r.get("pm25"), "pm25_24h": r.get("pm25_24h"),
        "pm10": r.get("pm10"), "pm10_24h": r.get("pm10_24h"),
        "o3_8h": r.get("o3_8h"), "o3_8h_24h": r.get("o3_8h_24h"),
        "no2": r.get("no2"), "so2": r.get("so2"), "co": r.get("co"),
    } for r in recs]


def write_index(daily_dir):
    dated = sorted((f for f in os.listdir(daily_dir)
                    if f.endswith(".html") and f not in ("index.html", "latest.html")),
                   reverse=True)
    items = ""
    if dated:
        items += "<li><a href='latest.html'>最新一期</a></li>"
        items += "\n".join("<li><a href='%s'>%s</a></li>" % (f, f[:-5]) for f in dated)
    with open(os.path.join(daily_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(INDEX_TPL % items)
    return len(dated)


def main():
    data_dir = os.environ.get("AIR_DATA_DIR") or DATA_DIR
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.environ.get("AIR_DAILY_DIR") or DAILY_DIR)

    tp, recs = load_latest(data_dir)
    if not tp or not recs:
        print("[跳过] 未取到点位数据：%s" % data_dir)
        return 1

    summaries = city_summary(to_rows(recs))
    html = render(summaries, tp, CFG)

    os.makedirs(out_dir, exist_ok=True)
    day = tp[:10]
    dated = os.path.join(out_dir, "%s.html" % day)
    with open(dated, "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(out_dir, "latest.html"), "w", encoding="utf-8") as f:
        f.write(html)
    n = write_index(out_dir)

    print("[日报] %s → daily/%s.html（+ latest.html，归档 %d 期）" % (tp, day, n))
    for c in summaries:
        print("  %-4s %s %s | 点位 %d | 首要 %s | 最差 %s %s" % (
            c["city"][:2], c["aqi_max"], c["quality"], c["n"], c["primary"],
            c["worst"]["station_name"] if c["worst"] else "—",
            c["worst"]["aqi"] if c["worst"] else "—"))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())
