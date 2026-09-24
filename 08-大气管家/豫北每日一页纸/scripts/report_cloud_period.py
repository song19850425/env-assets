# -*- coding: utf-8 -*-
"""大气管家 · 云端周报/月报生成器（自包含，仅标准库）

为什么需要它
------------
和 report_cloud.py 同一个理由，只是周期更长：日报已经能在云端自动刷新，
但周报/月报过去仍靠本机跑 run_period.py —— 本机不开机，公开页上的
"周报/月报 · 最新一期"就永远停在旧日期。本脚本把它们也搬到云端。

取数：平台历史接口（最近 14 天城市日值，直连 air.cnemc.cn:18007）
输出：<模块>/weekly/*.html、<模块>/monthly/*.html，各自的 index.html，
      以及模块首页 index.html（三板块入口 + 归档期数）

⚠️ 与日报的关键差别：**内容不变就不落盘**。
周报/月报的数据一天才滚一次，而本脚本每小时跑一次；如果照写不误，
每个整点都会因为"生成时间"这类字段变更而重写文件（周报+月报约 32 KB/次 → 一年近 300 MB）。
故用 report/index_pages.py 的 write_report()：抹掉生成时间后内容真的变了才写。

渲染/统计/取数逻辑不在这里重写，全部来自同目录镜像副本：
    config.py          ← 项目 config.py（PROFILES["yubei"]）
    fetch_history.py   ← ingest/fetch_history.py
    period_stats.py    ← calc/period_stats.py
    period_page.py     ← report/period_page.py
    period_report.py   ← report/period_report.py
    index_pages.py     ← report/index_pages.py
由项目 deploy_github.py 的 sync_cloud_scripts() 每次自动同步。

退出码：0 = 成功（含"内容无变化，跳过"）；1 = 取数/生成失败（让 workflow 显红）
用法：python report_cloud_period.py
环境变量：AIR_MODULE_DIR 可覆盖模块目录（默认脚本所在目录的上一级）
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.environ.get("AIR_MODULE_DIR") or os.path.dirname(HERE)

# 让镜像副本保持项目内的导入路径，不改写源码：
#   period_page.py 写的是 `from calc.aqi_stats import aqi_level`
#   period_report.py 写的是 `from ingest.fetch_history import fetch_daily`
# 只要把 calc / report / ingest 三个"包"的 __path__ 指到本目录即可原样复用。
# （config.py 是顶层模块，靠下面 sys.path.insert 直接 import）
for _name in ("calc", "report", "ingest"):
    _m = types.ModuleType(_name)
    _m.__path__ = [HERE]
    sys.modules.setdefault(_name, _m)
sys.path.insert(0, HERE)


def _fix_tz():
    """把进程时区改成北京时间。

    云端 runner 默认 UTC，不修的话页面上的"生成：2026-09-24 09:12"实际是北京时间 17:12 ——
    对外材料时间对不上，看起来像数据滞后 8 小时。

    ⚠️ Windows 上没有 time.tzset()，且给 MSVCRT 设 TZ=Asia/Shanghai 会解析失败、
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

from config import PROFILES                      # noqa: E402
from report.period_report import KIND_PREFIX, build_period   # noqa: E402
from report.index_pages import (SECTIONS, archive_name,   # noqa: E402
                               module_home, section_index, write_report)

CFG = PROFILES["yubei"]
LABEL = {sub: label for sub, _prefix, label in SECTIONS}


def emit(kind, result):
    """把一期报告落到模块目录：归档文件 + latest.html。返回写入文件数。"""
    sub = kind
    d = os.path.join(MODULE, sub)
    os.makedirs(d, exist_ok=True)
    arch = archive_name(result["fname"], KIND_PREFIX[kind])
    written = 0
    for name in (arch, "latest.html"):
        if write_report(os.path.join(d, name), result["html"]):
            written += 1
            print("  [写入] %s/%s" % (sub, name))
    if section_index(d, KIND_PREFIX[kind], LABEL[sub]):
        written += 1
        print("  [写入] %s/index.html（归档目录）" % sub)
    print("[%s] %s ~ %s → %s/%s（本次写入 %d 个文件）" % (
        LABEL[sub], result["start"], result["end"], sub, arch, written))
    for s in result["stats"]:
        print("  %-4s 期均AQI %-6s 优良 %d/%d ｜ PM2.5均值 %s" % (
            s["city"][:2], s["mean_aqi"], s["good"], s["n"], s["means"]["pm25"]))
    return written


def _memo_fetch():
    """带缓存的取数函数：周报与月报共用同一份日值快照。

    必要性有两个：① 同一批城市被取两遍纯属浪费（每城一次请求，还多一份失败概率）；
    ② 更要紧的是**一致性** —— 若两次取数之间平台恰好跨了整点更新，
    周报和月报就会基于不同数据算出不同结论，对外材料自相矛盾。
    """
    from ingest.fetch_history import fetch_daily
    cache = {}

    def fetch(city):
        if city not in cache:
            cache[city] = fetch_daily(city)
        return cache[city]
    return fetch


def main():
    fetch = _memo_fetch()
    ok, failed = 0, []
    for kind in ("weekly", "monthly"):
        try:
            emit(kind, build_period(kind, CFG, fetch=fetch))
            ok += 1
        except Exception as e:
            failed.append((kind, str(e)[:160]))
            print("[失败] %s：%s" % (kind, e))
    if module_home(MODULE, SECTIONS):
        print("[写入] 模块 index.html（三板块入口）")
    if failed:
        print("[警告] %d/%d 类周期报告生成失败：%s" % (len(failed), 2, failed))
        return 1 if ok == 0 else 0
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())
