# -*- coding: utf-8 -*-
"""预报采集层：Open-Meteo Air Quality API（CAMS 全球模式预报，免密钥、小时级）。

选它的理由：与项目已在用的气象源（api.open-meteo.com）同一家、同一套免密钥用法，
接入成本最低；CAMS 是 ECMWF 哥白尼大气监测服务的全球预报产品，
提供 pm2_5 / pm10 / ozone / no2 / so2 / co 的逐时值，过去 1 天 + 未来最多 5 天。
（2026-09-25 实测：单城返回 96 个逐时点，6 项污染物全有值，单位 μg/m³。）

⚠️ 单位换算：本接口的 CO 是 **μg/m³**，而平台与 HJ 633 的 IAQI 分段用的是 **mg/m³**。
   本模块在采集处统一把 CO 折成 mg/m³（÷1000），使 calc/forecast.py 与实况口径一致。
   这是本项目"口径必须唯一"的延伸 —— 混单位是比缺数更难发现的错。

数据性质：模式预报值（约 40 km 网格、城市尺度），非国控点位本地实测，不作达标判据。
"""
import json
import ssl
import time
import urllib.parse
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASE = "https://air-quality-api.open-meteo.com/v1/air-quality"

HOURLY = ["pm2_5", "pm10", "ozone", "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _col(h, key, i):
    arr = h.get(key) or []
    return _num(arr[i]) if i < len(arr) else None


def fetch_city(lat, lon, past_days=1, forecast_days=3, timeout=40, retries=3):
    """抓一个城市的逐时预报。失败重试（无人值守运行必备）。"""
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(HOURLY),
        "timezone": "Asia/Shanghai",
        "past_days": past_days, "forecast_days": forecast_days,
    })
    url = BASE + "?" + q
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
            break
        except Exception as e:
            last = e
            if attempt == retries - 1:
                raise
            time.sleep(3)
    else:
        raise RuntimeError("预报接口不可用：%s" % last)

    h = d.get("hourly") or {}
    times = h.get("time") or []
    rows = []
    for i, t in enumerate(times):
        co_ug = _col(h, "carbon_monoxide", i)
        rows.append({
            "timepoint": str(t)[:16],
            "pm25": _col(h, "pm2_5", i), "pm10": _col(h, "pm10", i),
            "o3": _col(h, "ozone", i), "no2": _col(h, "nitrogen_dioxide", i),
            "so2": _col(h, "sulphur_dioxide", i),
            # μg/m³ → mg/m³，与平台 CO 单位及 IAQI 分段对齐
            "co": (round(co_ug / 1000.0, 4) if co_ug is not None else None),
        })
    return rows


def fetch_all(coords, **kw):
    """逐城市抓取。coords: {city: (lat, lon)}。返回 (data, errors)

    哨兵约定：单个城市失败记入 errors 不中断 —— 少一个城市的预报不该让整张日报出不来。
    """
    data, errors = {}, []
    for city, (lat, lon) in (coords or {}).items():
        try:
            data[city] = fetch_city(lat, lon, **kw)
        except Exception as e:
            errors.append("%s 预报采集失败：%s" % (city, str(e)[:120]))
    return data, errors


if __name__ == "__main__":
    import os
    import sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    from config import PROFILES
    cfg = PROFILES["yubei"]
    got, errs = fetch_all(cfg["coords"])
    for c, rows in got.items():
        print("OK  %-6s %d 个逐时点 %s ~ %s" % (c, len(rows), rows[0]["timepoint"], rows[-1]["timepoint"]))
    if errs:
        print("[失败]", errs)
