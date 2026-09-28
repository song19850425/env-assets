# -*- coding: utf-8 -*-
"""大气管家 · 云端采集器（自包含，仅用标准库）

设计意图：在**云端 runner**（GitHub Actions / 腾讯云 SCF / 任何 Linux）上跑，
不依赖本机、不依赖第三方包。因为平台的**小时级历史接口不存在**（实测 404），
未采集的小时永久丢失——所以这个脚本必须能在你不开机时照常运行。

输出（按天一个文件，追加写，便于 git diff 与长期留存）：
  <OUT_DIR>/YYYY-MM-DD.jsonl   每行一条 JSON：点位小时值 或 城市气象
  <OUT_DIR>/_health.json       最近一次运行状态（含可达性诊断）

退出码：0 = 至少一城成功；1 = 全部失败（让 workflow 显红，便于告警）
用法：python air_collect.py [输出目录]
环境变量：AIR_OUT_DIR 可覆盖输出目录
"""
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
AIR_BASE = "https://air.cnemc.cn:18007"
WEATHER_BASE = "https://api.open-meteo.com/v1/forecast"

# 本地四市：实时接口用【城市名】，坐标用于取气象
CITIES = {
    "安阳市": (36.1034, 114.3931),
    "濮阳市": (35.7615, 115.0291),
    "鹤壁市": (35.7470, 114.2973),
    "新乡市": (35.3027, 113.9268),
}

# 平台证书为自签名（非标准 CA），须放宽校验。仅对本项目数据源放宽，不做全局关闭。
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

RETRY = 3
RETRY_SLEEP = 5


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "ignore")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_city(city):
    """抓一个城市的全部国控点位当前小时值；失败抛异常"""
    url = AIR_BASE + "/CityData/GetAQIDataPublishLive?cityName=" + urllib.parse.quote(city)
    last = None
    for i in range(RETRY):
        try:
            raw = json.loads(_get(url))
            if isinstance(raw, list) and raw:
                return raw
            last = RuntimeError("接口返回空")
        except Exception as e:
            last = e
        if i < RETRY - 1:
            time.sleep(RETRY_SLEEP)
    raise last


def slim(city, d):
    """只留时序分析需要的字段（原始报文太大，逐年留存会撑爆仓库）"""
    return {
        "k": "s",                                                    # s = station
        "tp": str(d.get("TimePoint", ""))[:16],
        "city": d.get("Area", city),
        "code": d.get("StationCode", ""),
        "st": d.get("PositionName", ""),
        "aqi": _num(d.get("AQI")),
        "q": d.get("Quality", ""),
        "pri": d.get("PrimaryPollutant", ""),
        "pm25": _num(d.get("PM2_5")), "pm25_24h": _num(d.get("PM2_5_24h")),
        "pm10": _num(d.get("PM10")), "pm10_24h": _num(d.get("PM10_24h")),
        "o3_8h": _num(d.get("O3_8h")), "o3_8h_24h": _num(d.get("O3_8h_24h")),
        "no2": _num(d.get("NO2")), "so2": _num(d.get("SO2")), "co": _num(d.get("CO")),
    }


def fetch_weather(city, lat, lon, since=None):
    """Open-Meteo 免密钥；单位与时区必须显式指定，否则时点对不上。
    since（YYYY-MM-DD）用于只保留当天及之后的时次——昨天的气象昨天已存过，
    重复写会让当天文件翻倍。"""
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
                  "boundary_layer_height,temperature_2m,relative_humidity_2m,"
                  "surface_pressure,precipitation",
        "wind_speed_unit": "ms", "timezone": "Asia/Shanghai",
        "past_days": 1, "forecast_days": 1,
    })
    d = json.loads(_get(WEATHER_BASE + "?" + q))
    h = d["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        if since and str(t)[:10] < since:
            continue
        out.append({
            "k": "w", "tp": t, "city": city,
            "ws": h["wind_speed_10m"][i], "wd": h["wind_direction_10m"][i],
            "wg": h["wind_gusts_10m"][i], "blh": h["boundary_layer_height"][i],
            "t": h["temperature_2m"][i], "rh": h["relative_humidity_2m"][i],
            "p": h["surface_pressure"][i], "pr": h["precipitation"][i],
        })
    return out


def run(out_dir):
    """可被云函数直接调用的入口。返回 (退出码, 落盘路径, 本次抓取条数, 新增条数)。"""
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now(TZ8)
    day = now.strftime("%Y-%m-%d")

    records, errors, detail = [], [], {}
    for city in CITIES:
        try:
            raw = fetch_city(city)
            records += [slim(city, d) for d in raw]
            detail[city] = {"ok": True, "n": len(raw)}
            print("[点位] %s: %d 个" % (city, len(raw)))
        except Exception as e:
            errors.append("%s: %s" % (city, e))
            detail[city] = {"ok": False, "err": str(e)[:200]}
            print("[失败] %s: %s" % (city, e))

    for city, (lat, lon) in CITIES.items():
        try:
            w = fetch_weather(city, lat, lon, since=day)
            records += w
            detail[city]["weather"] = len(w)
            print("[气象] %s: %d 小时" % (city, len(w)))
        except Exception as e:
            errors.append("%s 气象: %s" % (city, e))

    # 数据落盘（按天追加）。先读当日已有键去重——
    # 否则同一小时被多次采集、气象 48 小时被重复写 24 遍，文件会膨胀 20 倍。
    path = os.path.join(out_dir, "%s.jsonl" % day)
    seen = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    seen.add((r.get("k"), r.get("city"), r.get("tp"), r.get("code", "")))
                except Exception:
                    pass
    new = []
    for r in records:
        key = (r.get("k"), r.get("city"), r.get("tp"), r.get("code", ""))
        if key in seen:
            continue
        seen.add(key)
        new.append(r)
    if new:
        with open(path, "a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    # 健康档案：即使全失败也要落盘，否则云端故障看不出来
    health = {
        "last_run": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "last_run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records_fetched": len(records),
        "records_new": len(new),
        "stations_ok": sum(1 for c in CITIES if detail[c].get("ok")),
        "cities": len(CITIES),
        "errors": errors,
        "detail": detail,
        "ok": bool(records),
    }
    with open(os.path.join(out_dir, "_health.json"), "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=1)

    print("[落盘] %s（新增 %d 条 / 抓取 %d 条）" % (path, len(new), len(records)))
    if not records:
        print("[严重] 全部失败：%s" % errors)
        return 1, path, len(records), len(new)
    return 0, path, len(records), len(new)


def main():
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.environ.get("AIR_OUT_DIR", "data-hourly"))
    rc, path, got, new = run(out_dir)
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())
