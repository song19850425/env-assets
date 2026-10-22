# -*- coding: utf-8 -*-
"""每天两次出报驱动：遍历所有在采城市（去采重），生成「每城市一页纸」到 out/cities/<城市>/。

用法: py run_city_daily.py
依赖: config.PROFILES, report.city_page.render_city_page
产物: out/cities/<短城市>/<日期>.html + latest.html；out/cities/index.html（总入口）
说明: 开机先拉/复用当日 CAMS 预报（data/forecast_<日期>.json），失败则回退最新已有文件。
"""
import os
import glob
import json
import datetime
import sqlite3
import urllib.request
from config import PROFILES
from report.city_page import render_city_page, short


def collect_coords():
    coords = {}
    for cfg in PROFILES.values():
        for c, xy in cfg.get("coords", {}).items():
            coords.setdefault(c, xy)
    return coords


def pull_forecast(today):
    fn = "data/forecast_%s.json" % today
    if os.path.exists(fn):
        return fn
    coords = collect_coords()
    out = {}
    for name, (la, lo) in coords.items():
        try:
            aq = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude=%s&longitude=%s"
                  "&hourly=pm2_5,pm10,ozone,us_aqi&forecast_days=7&timezone=Asia/Shanghai" % (la, lo))
            wx = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                  "&hourly=wind_speed_10m,wind_direction_10m,precipitation&forecast_days=7"
                  "&wind_speed_unit=ms&timezone=Asia/Shanghai" % (la, lo))
            out[short(name)] = {
                "aq": json.load(urllib.request.urlopen(aq, timeout=30)),
                "wx": json.load(urllib.request.urlopen(wx, timeout=30)),
            }
        except Exception as e:
            print("  forecast %s 失败: %s" % (short(name), e))
    if out:
        json.dump(out, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
        return fn
    existing = sorted(glob.glob("data/forecast_*.json"))
    return existing[-1] if existing else None


def build_index(today):
    base = "out/cities"
    if not os.path.isdir(base):
        return
    cities = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    rows = "".join(
        "<tr><td><a href='%s/latest.html'>%s</a></td>"
        "<td><a href='%s/%s.html'>%s 当日</a></td></tr>" % (c, c, c, today, today)
        for c in cities)
    html = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>各城市大气一页纸 · 总索引</title>
<style>body{background:#0b1020;color:#e8eefc;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;padding:28px}
.wrap{max-width:680px;margin:0 auto}h1{font-size:20px}a{color:#22d3ee;text-decoration:none}
table{width:100%%;border-collapse:collapse;margin-top:14px}th,td{padding:9px;border-bottom:1px solid #23304f;text-align:left}
th{color:#8aa0c8;font-size:12px}.note{color:#8aa0c8;font-size:12px;margin-top:16px}</style></head>
<body><div class="wrap"><h1>各城市大气一页纸 · 总索引</h1>
<p class="note">每日 08:00 / 20:00 更新（实时小时值，AI 草稿未经审定）。点击城市进入该城最新页。</p>
<table><tr><th>城市</th><th>当日页</th></tr>%s</table>
<p class="note">数据来源：中国环境监测总站实时发布平台（点位小时值）+ Open-Meteo / CAMS 模式预报。
口径红线与偏差说明见各城市页与说明页。</p></div></body></html>""" % rows
    open(os.path.join(base, "index.html"), "w", encoding="utf-8").write(html)


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print("[%s] 定位/拉取当日预报" % now)
    fj = pull_forecast(today)
    print("  预报文件:", fj)

    con = sqlite3.connect("data/air.db")
    seen, tasks = set(), []
    for p, cfg in PROFILES.items():
        for c in cfg.get("cities", []):
            if c not in seen:
                seen.add(c)
                tasks.append((p, c))
    print("覆盖城市 %d: %s" % (len(tasks), " ".join(short(c) for _, c in tasks)))

    for p, city in tasks:
        cfg = PROFILES[p]
        try:
            html = render_city_page(cfg, city, con, fj, now=now)
            d = os.path.join("out/cities", short(city))
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "%s.html" % today), "w", encoding="utf-8").write(html)
            open(os.path.join(d, "latest.html"), "w", encoding="utf-8").write(html)
            print("  %s OK" % short(city))
        except Exception as e:
            print("  %s 失败: %s" % (short(city), e))
    con.close()
    build_index(today)
    print("完成 -> out/cities/index.html")


if __name__ == "__main__":
    main()
