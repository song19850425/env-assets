# -*- coding: utf-8 -*-
"""大气管家 · 云端小时序列看板生成器（自包含，仅标准库）

为什么需要它
------------
小时数据一直只有三个"机器出口"：
    ① 本地 data/air.db 的 station_hourly（要看只能连库）
    ② 本地 data/raw/<日期>/*.json（原始报文）
    ③ 云端 data-hourly/YYYY-MM-DD.jsonl（GitHub 上点开是一堆 JSON 文本）
→ **没有任何能直接看的入口，"采了看不见"等于没采。**
本脚本让**云端自己**把 JSONL 渲染成一张可直看的页面并提交进仓库，
于是 GitHub Pages 上的看板随每次采集自动刷新，**不依赖本机开机**。

版式与本地完全同源：直接复用镜像来的 report/hourly_page.py（render_hourly），
不重写任何渲染逻辑 —— 区别只在数据来源（本地读 SQLite，云端读 JSONL）。

窗口：默认最近 7 天（环境变量 AIR_HOURLY_DAYS 可改）。看板要的是"最近"，
      不是全量，否则页面会随时日无限膨胀、耗时的读取也越滚越大。

去抖：用 index_pages.write_report —— 每小时重跑时，若实质内容未变则不落盘
      （页面时间戳写成「生成：YYYY-MM-DD HH:MM」，会被 STAMP_RE 抹掉后再比对）。

输入：<模块>/data-hourly/YYYY-MM-DD.jsonl(.gz)（air_collect.py 产出；k=s 点位 / k=w 气象）
输出：<模块>/<hourly_dir>/index.html（档案决定：豫北 → hourly/，豫西 → hourly-yuxi/），
      以及健康档案 <模块>/_health_report.json 的对应条目
退出码：0 成功（含"窗口内无数据则跳过"）；1 完全没有可用数据
用法：python report_cloud_hourly.py
环境变量：AIR_PROFILE 选档案（yubei|yuxi）；AIR_MODULE_DIR / AIR_DATA_DIR /
          AIR_HOURLY_DIR / AIR_HOURLY_DAYS

同一份脚本被 workflow 跑两遍，即为两套档案各出一张"当前实况"看板
（各自只统计本档案城市，别的档案城市在过滤阶段就被剔除）。
"""
import glob
import gzip
import json
import os
import sys
import time
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.environ.get("AIR_MODULE_DIR") or os.path.dirname(HERE)   # …/豫北每日一页纸
DATA_DIR = os.environ.get("AIR_DATA_DIR") or os.path.join(MODULE, "data-hourly")
DAYS = int(os.environ.get("AIR_HOURLY_DAYS") or 7)

# 与 report_cloud.py 同一套：让镜像副本保持项目内的导入路径，
# 这样 report/hourly_page.py 里 `from datetime import ...` 之外的相对导入无需改写。
for _name in ("calc", "report", "ingest"):
    _m = types.ModuleType(_name)
    _m.__path__ = [HERE]
    sys.modules.setdefault(_name, _m)
sys.path.insert(0, HERE)


def _fix_tz():
    """runner 默认 UTC；不切时区页面"生成时间"会少 8 小时。
    Windows 无 time.tzset()，且给 MSVCRT 设 TZ=Asia/Shanghai 反而会变成 UTC，故跳过。"""
    if not hasattr(time, "tzset"):
        return
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    off = -time.timezone if not time.localtime().tm_isdst else -time.altzone
    if off != 8 * 3600:
        print("[警告] 时区未切到北京时间（UTC 偏移 %+.1f h）" % (off / 3600.0))


_fix_tz()

from config import PROFILES                                   # noqa: E402
from report.hourly_page import render_hourly                  # noqa: E402
from report.index_pages import write_report, module_home, SECTIONS  # noqa: E402
from report.health import merge as health_merge                # noqa: E402

CFG = PROFILES[os.environ.get("AIR_PROFILE", "yubei")]
SECTION = CFG.get("section", "daily")
# 看板输出目录按档案走（豫北 hourly/、豫西 hourly-yuxi/）——
# workflow 里同一份脚本跑两遍，各出一张看板（见 config.PROFILES[*]["hourly_dir"]）。
HOURLY_SUB = CFG.get("hourly_dir") or "hourly"
HOURLY_DIR = os.environ.get("AIR_HOURLY_DIR") or os.path.join(MODULE, HOURLY_SUB)


def _lines(path):
    """逐行产出记录；单行损坏跳过（JSONL 追加写，尾部可能截断）"""
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


def _window_files(data_dir, days):
    """取最近 days 天的 JSONL（含 .gz）。文件名前缀即日期，故按名筛选即可。"""
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    files = sorted(glob.glob(os.path.join(data_dir, "*.jsonl")) +
                   glob.glob(os.path.join(data_dir, "*.jsonl.gz")))
    return [p for p in files if os.path.basename(p)[:10] >= cutoff]


def load_window(data_dir, days):
    """云端的简写字段 → hourly_page 需要的键名。

    k=s 点位：city / st / tp / aqi / pm25 / o3_8h …
    k=w 气象：city / tp / ws / wd / blh …
    字段名换算集中在这里，渲染层不必知道"云端用的是简写"。
    """
    hourly, weather, seen = [], [], set()
    files = _window_files(data_dir, days)
    for p in files:
        for r in _lines(p):
            k = r.get("k")
            city, tp = r.get("city"), str(r.get("tp", ""))[:16]
            if not city or not tp:
                continue
            if k == "s":
                # 去重键：同一 (城市,点位,时点) 可能因重跑而重复入库
                key = ("s", city, r.get("code") or r.get("st"), tp)
                if key in seen:
                    continue
                seen.add(key)
                hourly.append({
                    "city": city, "timepoint": tp,
                    "station_name": r.get("st", ""), "station_code": r.get("code", ""),
                    "aqi": r.get("aqi"), "quality": r.get("q"),
                    "primary_pollutant": r.get("pri"),
                    "pm25": r.get("pm25"), "pm10": r.get("pm10"),
                    "o3_8h": r.get("o3_8h"), "no2": r.get("no2"),
                    "so2": r.get("so2"), "co": r.get("co"),
                })
            elif k == "w":
                key = ("w", city, tp)
                if key in seen:
                    continue
                seen.add(key)
                weather.append({
                    "city": city, "timepoint": tp,
                    "wind_speed": r.get("ws"), "wind_dir": r.get("wd"),
                    "blh": r.get("blh"), "temp": r.get("t"), "rh": r.get("rh"),
                })
    return hourly, weather, files


def main():
    data_dir = DATA_DIR
    cities = CFG["cities"]
    hourly, weather, files = load_window(data_dir, DAYS)
    # 只保留本档案城市 + 已配置的上风向邻居。
    # 为什么必须过滤（2026-10-01）：云端采集池已从豫北四城扩到九城（豫西日报也要数据），
    # 而本看板的城市池概念是"本地城市（统计）+ 上风向邻居（定位）"——
    # 不过滤就会把别的档案的城市画进区域态势图，
    # 读者会以为它们是本档案的上风向城市（图上有、风玫瑰弧段却没有，自相矛盾）。
    keep = set(cities) | set((CFG.get("neighbor_coords") or {}).keys())
    hourly = [r for r in hourly if r.get("city") in keep]
    weather = [r for r in weather if r.get("city") in keep]
    if not hourly and not weather:
        print("[跳过] %s 近 %d 天无可用记录（板块 %s）" % (data_dir, DAYS, HOURLY_SUB))
        health_merge(MODULE, HOURLY_SUB, {"ok": False, "days": DAYS,
                                          "error": "窗口内无记录：%s" % data_dir})
        return 1

    tps = sorted({r["timepoint"] for r in hourly})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_hourly(hourly, weather, cities, generated_at=now, sample=True,
                         back_link="../index.html",
                         coords=CFG.get("coords"), neighbors=CFG.get("neighbor_coords"),
                         region_name=CFG.get("region_name"))

    os.makedirs(HOURLY_DIR, exist_ok=True)
    path = os.path.join(HOURLY_DIR, "index.html")
    written = write_report(path, html)
    print("[看板] 读 %d 个 JSONL ｜ 点位记录 %d 条 ｜ 气象行 %d ｜ 时点 %d 个"
          % (len(files), len(hourly), len(weather), len(tps)))
    if tps:
        print("[看板] 窗口 %s ~ %s（近 %d 天）" % (tps[0], tps[-1], DAYS))
    print("[看板] %s/index.html %s（%.1f KB）"
          % (HOURLY_SUB, "已更新" if written else "内容未变，跳过写入",
             os.path.getsize(path) / 1024.0))

    # 模块首页补上"小时序列看板"入口（该文件已存在时才会输出链接，故不会产生死链）
    if module_home(MODULE, SECTIONS):
        print("[看板] 模块 index.html 已重建（含看板入口）")

    health_merge(MODULE, HOURLY_SUB, {
        "ok": True, "days": DAYS, "files": len(files),
        "stations": len(hourly), "weather": len(weather),
        "hours": len(tps), "window": [tps[0], tps[-1]] if tps else [],
        "written": written,
    })
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())
