# -*- coding: utf-8 -*-
"""气象采集层：Open-Meteo（免密钥、小时级）。

选型说明（2026-09-24 实测结论）：
  - Open-Meteo  api.open-meteo.com       免费、无需 key、小时级、带边界层高度 → 采用
  - met.no      api.met.no               免费、无需 key，但需带 UA，时长较短 → 备选
  - wttr.in                              免费，3 小时粒度，太粗 → 不采用
  - ERA5 归档   archive-api.open-meteo.com  免费，可回溯历史，用于长期基线 → 备用

数据性质：模式再分析/预报产品（ECMWF IFS、ICON 等），非本地实测气象站数据，
城市尺度代表性，与国控点位所在微环境存在差异，引用时须声明。
单位统一：风速 m/s、风向 °（气象风向＝风的来向）、边界层高度 m、湿度 %、温度 °C、气压 hPa。
"""
import json
import ssl
import urllib.request
from datetime import datetime, timedelta

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "Open-Meteo"
HOURLY = "wind_speed_10m,wind_direction_10m,wind_gusts_10m,boundary_layer_height,temperature_2m,relative_humidity_2m,surface_pressure,precipitation"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "air-manager/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pack(city, lat, lon, data, keep_after=None):
    """把 Open-Meteo 响应摊平成逐小时行；keep_after 为 'YYYY-MM-DDTHH:MM' 下限"""
    h = (data or {}).get("hourly") or {}
    times = h.get("time") or []
    rows = []
    for i, t in enumerate(times):
        if keep_after and t < keep_after:
            continue
        rows.append({
            "city": city, "timepoint": t,
            "wind_speed": _num(h["wind_speed_10m"][i]) if "wind_speed_10m" in h else None,
            "wind_dir": _num(h["wind_direction_10m"][i]) if "wind_direction_10m" in h else None,
            "wind_gust": _num(h["wind_gusts_10m"][i]) if "wind_gusts_10m" in h else None,
            "blh": _num(h["boundary_layer_height"][i]) if "boundary_layer_height" in h else None,
            "temp": _num(h["temperature_2m"][i]) if "temperature_2m" in h else None,
            "rh": _num(h["relative_humidity_2m"][i]) if "relative_humidity_2m" in h else None,
            "pressure": _num(h["surface_pressure"][i]) if "surface_pressure" in h else None,
            "precip": _num(h["precipitation"][i]) if "precipitation" in h else None,
            "lat": lat, "lon": lon, "source": SOURCE,
        })
    return rows


def fetch_city_weather(city, lat, lon, past_days=1, forecast_days=1, keep_after=None):
    """取单城市逐小时气象（含过去 past_days 天，用于对齐最近时点）"""
    url = ("%s?latitude=%s&longitude=%s&hourly=%s&wind_speed_unit=ms"
           "&past_days=%d&forecast_days=%d&timezone=Asia%%2FShanghai"
           % (FORECAST_API, lat, lon, HOURLY, past_days, forecast_days))
    return _pack(city, lat, lon, _get(url), keep_after)


def fetch_archive(city, lat, lon, start_date, end_date):
    """ERA5 历史归档（免费），用于历史同期基线；注意有约 5 天滞后"""
    url = ("%s?latitude=%s&longitude=%s&start_date=%s&end_date=%s&hourly=%s"
           "&wind_speed_unit=ms&timezone=Asia%%2FShanghai"
           % (ARCHIVE_API, lat, lon, start_date, end_date,
              "wind_speed_10m,wind_direction_10m,boundary_layer_height,relative_humidity_2m"))
    return _pack(city, lat, lon, _get(url))


def fetch_all_weather(coords, past_days=1, forecast_days=1, keep_after=None):
    """逐城市抓取；返回 (rows, errors)。失败不中断，与 AQI 采集同款哨兵逻辑。"""
    rows, errors = [], []
    for city, (lat, lon) in coords.items():
        try:
            got = fetch_city_weather(city, lat, lon, past_days, forecast_days, keep_after)
            if not got:
                raise RuntimeError("返回为空")
            rows.extend(got)
            print("[气象] %s: %d 小时（%s ~ %s）"
                  % (city, len(got), got[0]["timepoint"], got[-1]["timepoint"]))
        except Exception as e:
            errors.append("%s 气象: %s" % (city, e))
            print("[告警] %s 气象采集失败: %s" % (city, e))
    return rows, errors


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import PROFILES
    cfg = PROFILES["yubei"]
    today = datetime.now().strftime("%Y-%m-%d")
    rows, errs = fetch_all_weather(cfg["coords"], keep_after=today + "T00:00")
    print("合计 %d 行，失败 %d 个" % (len(rows), len(errs)))
    tp = datetime.now().strftime("%Y-%m-%dT%H:00")
    for r in rows:
        if r["timepoint"] == tp:
            print("  %s %s | 风速 %s m/s | 风向 %s° | BLH %s m | RH %s%%"
                  % (r["city"], r["timepoint"], r["wind_speed"], r["wind_dir"], r["blh"], r["rh"]))
