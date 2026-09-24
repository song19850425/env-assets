# -*- coding: utf-8 -*-
"""大气管家 · 云端日报生成器（自包含，仅标准库）

为什么需要它
------------
采集已经在云端（air_collect.py + .github/workflows/air-hourly.yml），但报告过去仍在本机生成 ——
本机关机时，公开页 daily/latest.html 就停在旧日期，"不开机也能看到新数据"只做到一半。
本脚本让日报也做到：**云端采集完顺手出报，不需要本机参与。**

输入：<data-hourly>/YYYY-MM-DD.jsonl（air_collect.py 的产出）
输出：<模块>/daily/<日期>.html + latest.html + index.html + 模块首页 index.html

渲染/配置不在这里重写：直接复用同目录的**镜像副本**
    config.py      ← 项目 config.py（PROFILES["yubei"]）
    aqi_stats.py   ← 项目 calc/aqi_stats.py
    daily_page.py  ← 项目 report/daily_page.py
    index_pages.py ← 项目 report/index_pages.py（导航页模板，与本地部署脚本共用一份）
由项目 deploy_github.py 的 sync_cloud_scripts() 每次自动同步，
因此不存在"两份模板各改各的"的问题。

时区：runner 是 UTC，脚本启动即切到 Asia/Shanghai —— 否则页面"生成时间"比北京时间少 8 小时。

退出码：0 成功；1 无可用数据（让 workflow 显红，便于告警）
用法：python report_cloud.py [daily 输出目录]
环境变量：AIR_DATA_DIR / AIR_DAILY_DIR / AIR_MODULE_DIR 可覆盖输入输出目录
"""
import glob
import gzip
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.environ.get("AIR_MODULE_DIR") or os.path.dirname(HERE)   # …/豫北每日一页纸
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


def _fix_tz():
    """把进程时区改成北京时间。

    云端 runner 默认 UTC，不修的话页面上的"生成：2026-09-24 09:12"实际是北京时间 17:12，
    对外材料看起来像数据滞后 8 小时（2026-09-24 实测确认存在）。

    ⚠️ Windows 上没有 time.tzset()，且给 MSVCRT 设 TZ=Asia/Shanghai 会被解析失败、
    反而把本地时间变成 UTC（实测 17:49 → 09:49）。故本机直接跳过：本机系统时区已是北京时间。
    """
    if not hasattr(time, "tzset"):
        return
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    off = -time.timezone if not time.localtime().tm_isdst else -time.altzone
    if off != 8 * 3600:
        print("[警告] 时区未切到北京时间（UTC 偏移 %+.1f h），页面时间会偏差" % (off / 3600.0))


_fix_tz()

from report.daily_page import render        # noqa: E402
from report.index_pages import (SECTIONS, section_index,  # noqa: E402
                               module_home, write_report)
from calc.aqi_stats import city_summary     # noqa: E402
from config import PROFILES                 # noqa: E402

# 与项目 config.PROFILES["yubei"] 同源（镜像副本），只取渲染需要的键
CFG = PROFILES["yubei"]

DAILY_PREFIX = {sub: prefix for sub, prefix, _ in SECTIONS}["daily"]
DAILY_LABEL = {sub: label for sub, _p, label in SECTIONS}["daily"]


def write_index(daily_dir):
    """重建 daily/index.html。

    模板统一在 report/index_pages.py —— 本地 deploy_github.py 与云端调的是同一份，
    不再各写一套（过去这里有一份自己的 INDEX_TPL，与本地那份标题、间距都略有差异，
    两侧轮流跑就会来回覆盖同一文件）。
    """
    section_index(daily_dir, DAILY_PREFIX, DAILY_LABEL)
    dated = [f for f in os.listdir(daily_dir)
             if f.endswith(".html") and f not in ("index.html", "latest.html")]
    return len(dated)


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
    for name in ("%s.html" % day, "latest.html"):
        if write_report(os.path.join(out_dir, name), html):
            print("  [写入] daily/%s" % name)
    n = write_index(out_dir)
    if module_home(MODULE, SECTIONS):
        print("  [写入] 模块 index.html（三板块入口）")

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
