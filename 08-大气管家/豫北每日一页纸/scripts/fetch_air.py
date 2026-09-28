# -*- coding: utf-8 -*-
"""采集层：全国城市空气质量实时发布平台（中国环境监测总站）
接口 /CityData/GetAQIDataPublishLive?cityName=<城市> 返回该市全部国控点位当前小时值。
"""
import json
import os
import ssl
import urllib.request
from urllib.parse import quote
from datetime import datetime

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASE = "https://air.cnemc.cn:18007"

# 原始报文落盘目录。平台无小时级历史接口，报文一旦不存就无法回溯；
# 数值被质疑时这里是唯一凭证。按 日期/城市_时点.json 存放。
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "raw")

FIELDS = ["AQI", "PM2_5", "PM2_5_24h", "PM10", "PM10_24h", "O3", "O3_8h",
          "O3_8h_24h", "NO2", "NO2_24h", "SO2", "SO2_24h", "CO", "CO_24h"]


def _num(v):
    """平台数值可能为 'NA'，统一转 None"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def archive_raw(city, data):
    """原始响应落盘，返回落盘路径。落盘失败不影响主流程。"""
    try:
        tp = ""
        if isinstance(data, list) and data:
            tp = str(data[0].get("TimePoint", ""))[:16].replace(":", "")
        day = datetime.now().strftime("%Y-%m-%d")
        d = os.path.join(RAW_DIR, day)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "%s_%s.json" % (city, tp or "unknown"))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return p
    except Exception as e:
        print("[警告] 原始报文落盘失败(%s): %s" % (city, e))
        return None


def fetch_city(city, archive=True):
    """抓取一个城市的全部点位，返回行列表；失败抛异常"""
    url = BASE + "/CityData/GetAQIDataPublishLive?cityName=" + quote(city)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("接口返回空（%s）" % city)
    if archive:
        archive_raw(city, data)
    rows = []
    for d in data:
        rows.append({
            "timepoint": d.get("TimePoint", "")[:16],
            "station_code": d.get("StationCode", ""),
            "city": d.get("Area", city),
            "station_name": d.get("PositionName", ""),
            "aqi": _num(d.get("AQI")),
            "quality": d.get("Quality", ""),
            "primary": d.get("PrimaryPollutant", ""),
            "pm25": _num(d.get("PM2_5")),
            "pm25_24h": _num(d.get("PM2_5_24h")),
            "pm10": _num(d.get("PM10")),
            "pm10_24h": _num(d.get("PM10_24h")),
            "o3_8h": _num(d.get("O3_8h")),
            "o3_8h_24h": _num(d.get("O3_8h_24h")),
            "no2": _num(d.get("NO2")),
            "so2": _num(d.get("SO2")),
            "co": _num(d.get("CO")),
        })
    return rows


def fetch_all(cities):
    """逐城市抓取；返回 (rows, errors)——哨兵逻辑：失败城市记入 errors 不中断"""
    rows, errors = [], []
    for c in cities:
        try:
            got = fetch_city(c)
            rows.extend(got)
            print("[采集] %s: %d 个点位" % (c, len(got)))
        except Exception as e:
            errors.append("%s: %s" % (c, e))
            print("[告警] %s 采集失败: %s" % (c, e))
    return rows, errors


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    from config import CONFIG
    rows, errors = fetch_all(CONFIG["cities"])
    print("合计", len(rows), "行；失败", len(errors), "个城市")
    if rows:
        print("样例行:", json.dumps(rows[0], ensure_ascii=False, indent=None)[:300])
