# -*- coding: utf-8 -*-
"""大气管家 · 云端日报生成器（自包含，仅标准库）

为什么需要它
------------
采集已经在云端（air_collect.py + .github/workflows/air-hourly.yml），但报告过去仍在本机生成 ——
本机关机时，公开页 daily/latest.html 就停在旧日期，"不开机也能看到新数据"只做到一半。
本脚本让日报也做到：**云端采集完顺手出报，不需要本机参与。**

版式：**V2 研判版**（自 2026-09-24 起与 run_daily.py 统一）。不再有"本机一版、云端另一版"——
两边的编排与模板都来自 report/daily_report.py，口径唯一。

输入：<data-hourly>/YYYY-MM-DD.jsonl（air_collect.py 的产出，含点位 k=s 与气象 k=w 两类记录）
输出：<模块>/daily/<日期>.html + latest.html + index.html + 模块首页 index.html，
      以及健康档案 <模块>/_health_report.json 的 daily 条目

渲染/研判/证据链不在这里重写：直接复用同目录的**镜像副本**（由 deploy_github.sync_cloud_scripts 同步）
    config.py         ← 项目 config.py（PROFILES["yubei"]）
    daily_report.py   ← 项目 report/daily_report.py（编排：研判 → 证据链 → 渲染）
    page_v2.py        ← 项目 report/page_v2.py（版式）
    brief.py / wind.py← 项目 calc/（研判与气象逻辑）
    aqi_stats.py      ← 项目 calc/aqi_stats.py
    index_pages.py    ← 项目 report/index_pages.py（导航页模板与去抖写盘）
    health.py         ← 项目 report/health.py

气象不额外请求：air_collect.py 已经把 Open-Meteo 的小时气象写进同一份 JSONL（k=w），
这里按城市取"不晚于数据时点"的最近一小时即可 —— 少 4 次网络请求，也少一条失败路径。

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
#   daily_report.py 里写的是 `from calc.brief import ...` / `from report.page_v2 import ...`
# 只要把 calc / report 两个"包"的 __path__ 指向本目录即可原样复用，
# 不必改写源码 —— 改写会让镜像与源文件产生实质差异，就失去复用的意义了。
for _name in ("calc", "report", "ingest"):
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

from config import PROFILES                                   # noqa: E402
from report.daily_report import build, print_summary          # noqa: E402
from report.index_pages import (SECTIONS, section_index,      # noqa: E402
                               module_home, write_report)
from report.health import merge as health_merge               # noqa: E402

# 与项目 config.PROFILES["yubei"] 同源（镜像副本）
CFG = PROFILES["yubei"]

DAILY_PREFIX = {sub: prefix for sub, prefix, _ in SECTIONS}["daily"]
DAILY_LABEL = {sub: label for sub, _p, label in SECTIONS}["daily"]

# 云端可溯源到什么程度，就写什么 —— 不夸大
RAW_NOTE = ("云端采集留存的是精简字段（<code>data-hourly/&lt;日期&gt;.jsonl</code>，含各点位原始数值），"
            "平台返回的完整原始报文未入仓；逐点复核请以该 JSONL 中同点位记录为准")


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
    """取最新时点的全部记录，返回 (timepoint, records)。

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
    """云端简写字段 → 研判/渲染需要的键名（与 ingest/fetch_air 对齐）"""
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


def _read_weather(data_dir, timepoint, cities):
    """从 JSONL 的 k=w 记录里取各城市气象：优先精确命中，退到"不晚于时点的最近一小时"。

    返回 ({city: row}, 缺失城市列表, 实际对齐时点)。字段名与 core.db.load_weather 一致，
    因此 report/daily_report.build_wind 对两个来源一视同仁。
    """
    files = sorted(glob.glob(os.path.join(data_dir, "*.jsonl")) +
                   glob.glob(os.path.join(data_dir, "*.jsonl.gz")))
    best = {}       # city → (tp, row)
    for p in reversed(files[-2:]):
        for r in _read_file(p):
            if r.get("k") != "w":
                continue
            city, t = r.get("city"), str(r.get("tp", ""))[:16]
            if not city or not t or t > timepoint:
                continue
            if city not in best or t > best[city][0]:
                best[city] = (t, r)
    got = {}
    for city, (t, r) in best.items():
        got[city] = {
            "city": city, "timepoint": t,
            "wind_speed": r.get("ws"), "wind_dir": r.get("wd"), "wind_gust": r.get("wg"),
            "blh": r.get("blh"), "temp": r.get("t"), "rh": r.get("rh"),
            "pressure": r.get("p"), "precip": r.get("pr"),
        }
    missing = [c for c in cities if c not in got]
    if missing:
        # 兜底：air_collect 那一步的气象没采到时（少见但会偶发），
        # 直接补抓一次，免得"六、气象条件与区域传输"整节消失 ——
        # 与该节的研判降级相比，多一次请求更划算。
        got2, _ = _fallback_weather(missing, timepoint)
        got.update(got2)
        missing = [c for c in cities if c not in got]
    aligned = max((v["timepoint"] for v in got.values()), default="")
    if missing:
        print("[气象] 缺 %s（补抓仍未取到），研判相应降级" % "、".join(missing))
    elif aligned != timepoint:
        print("[气象] 对齐到 %s（数据时点 %s 无对应气象记录，取最近一小时）" % (aligned, timepoint))
    return got, missing, aligned


def _fallback_weather(missing, timepoint):
    """对缺气象的城市直接抓一次 Open-Meteo（镜像副本 fetch_weather.py）。失败不影响出报。"""
    coords = CFG.get("coords") or {}
    want = {c: coords[c] for c in missing if c in coords}
    if not want:
        return {}, ""
    try:
        from ingest.fetch_weather import fetch_all_weather
        rows, errs = fetch_all_weather(want, past_days=2, forecast_days=1,
                                       keep_after=timepoint[:10] + "T00:00")
    except Exception as e:
        print("[气象] 补抓失败：%s" % e)
        return {}, ""
    if errs:
        print("[气象] 补抓告警：%s" % "；".join(errs))
    best = {}
    for r in rows:
        t, city = str(r.get("timepoint", ""))[:16], r.get("city")
        if not t or t > timepoint or not city:
            continue
        if city not in best or t > best[city]["timepoint"]:
            best[city] = r
    out = {c: {"city": c, "timepoint": r["timepoint"],
               "wind_speed": r.get("wind_speed"), "wind_dir": r.get("wind_dir"),
               "wind_gust": r.get("wind_gust"), "blh": r.get("blh"),
               "temp": r.get("temp"), "rh": r.get("rh"),
               "pressure": r.get("pressure"), "precip": r.get("precip")}
           for c, r in best.items()}
    if out:
        print("[气象] 补抓命中 %s" % "、".join(sorted(out)))
    return out, max((v["timepoint"] for v in out.values()), default="")


def main():
    data_dir = os.environ.get("AIR_DATA_DIR") or DATA_DIR
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.environ.get("AIR_DAILY_DIR") or DAILY_DIR)

    tp, recs = load_latest(data_dir)
    if not tp or not recs:
        print("[跳过] 未取到点位数据：%s" % data_dir)
        health_merge(MODULE, "daily", {"ok": False, "error": "未取到点位数据：%s" % data_dir})
        return 1

    cities = CFG["cities"]
    rows = to_rows(recs)
    weather, missing, aligned = _read_weather(data_dir, tp, cities)
    result = build(CFG, rows, tp, weather=weather,
                   werr=["%s 无气象记录" % c for c in missing], raw_note=RAW_NOTE)

    os.makedirs(out_dir, exist_ok=True)
    day = tp[:10]
    written = 0
    for name in ("%s.html" % day, "latest.html"):
        if write_report(os.path.join(out_dir, name), result["html"]):
            written += 1
            print("  [写入] daily/%s" % name)
    n = write_index(out_dir)
    if module_home(MODULE, SECTIONS):
        print("  [写入] 模块 index.html（三板块入口）")

    print("[日报] %s → daily/%s.html（+ latest.html，归档 %d 期，本次写入 %d 个文件）"
          % (tp, day, n, written))
    print_summary(result, tp, len(rows))

    health_merge(MODULE, "daily", {
        "ok": True, "timepoint": tp, "stations": len(rows),
        "weather_cities": len(weather), "weather_aligned": aligned,
        "period": day, "file": "%s.html" % day, "written": written,
        "archive_count": n,
    })
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())
