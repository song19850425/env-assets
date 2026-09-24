# -*- coding: utf-8 -*-
"""历史采集：城市逐日 AQI（含六参数 24h 值、首要污染物）。
平台接口固定返回最近 14 天，POST 表单提交。"""
import json
import ssl
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASE = "https://air.cnemc.cn:18007"
TZ = timezone(timedelta(hours=8))

# 城市代码（已实测：19 个全部有效，返回 14 天。济源 419001 接口返回空，未纳入）
# GROUPS 用于传输研判与基线扩展：本地四市 + 省内上风向 + 省外上风向（补盲区）。
CITY_CODES = {
    # 本地（服务对象）
    "安阳市": 410500, "濮阳市": 410900, "鹤壁市": 410600, "新乡市": 410700,
    # 省内（上风向/背景）
    "郑州市": 410100, "开封市": 410200, "洛阳市": 410300, "平顶山市": 410400,
    "焦作市": 410800, "许昌市": 411000, "漯河市": 411100, "三门峡市": 411200,
    "南阳市": 411300, "商丘市": 411400, "信阳市": 411500, "周口市": 411600,
    "驻马店市": 411700,
    # 省外上风向（此前传输研判的"盲区"）
    "邯郸市": 130400, "邢台市": 130500,                       # 河北，安阳上风(北)
    "聊城市": 371500, "菏泽市": 371700,                       # 山东，濮阳上风(东/东南)
    "长治市": 140400, "晋城市": 140500,                       # 山西，豫北上风(西北)
}

GROUPS = {
    "local": ["安阳市", "濮阳市", "鹤壁市", "新乡市"],
    "henan": ["郑州市", "开封市", "洛阳市", "平顶山市", "焦作市", "许昌市",
              "漯河市", "三门峡市", "南阳市", "商丘市", "信阳市", "周口市",
              "驻马店市"],
    "outside": ["邯郸市", "邢台市", "聊城市", "菏泽市", "长治市", "晋城市"],
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_daily(city):
    """返回 [{date:'YYYY-MM-DD', aqi, quality, primary, pm25, pm10, so2, no2, co, o3_8h}]，按日期升序"""
    code = CITY_CODES[city]
    data = urllib.parse.urlencode({"citycode": str(code),
                                   "starttime": "2000-01-01", "endtime": "2000-01-01"}).encode()
    raw = None
    for attempt in range(3):  # 重试 3 次（无人值守运行必备）
        try:
            req = urllib.request.Request(BASE + "/HourChangesPublish/GetCityDayAqiHistoryByCondition",
                                         data=data, headers={"User-Agent": "Mozilla/5.0",
                                                             "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                raw = json.loads(r.read().decode("utf-8", "ignore"))
            break
        except Exception as e:
            if attempt == 2:
                raise
            print("[重试] %s 第%d次失败: %s" % (city, attempt + 1, e))
            time.sleep(5)
    rows = []
    for d in raw:
        ms = int(d["TimePoint"].replace("/Date(", "").replace(")/", "").split("+")[0])
        date = datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d")
        rows.append({
            "date": date, "city": d.get("Area", city),
            "aqi": _num(d.get("AQI")), "quality": d.get("Quality", ""),
            # 键名保持 "primary"：run_period.py / period_stats.py 依赖此键
            "primary": d.get("PrimaryPollutant") or "—",
            "pm25": _num(d.get("PM2_5_24h")), "pm10": _num(d.get("PM10_24h")),
            "so2": _num(d.get("SO2_24h")), "no2": _num(d.get("NO2_24h")),
            "co": _num(d.get("CO_24h")), "o3_8h": _num(d.get("O3_8h_24h")),
        })
    rows.sort(key=lambda r: r["date"])
    return rows


if __name__ == "__main__":
    import os
    import sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # 后台运行时日志即时可见
    except Exception:
        pass
    from core.db import save_daily, load_daily

    db = os.path.join(ROOT, "data/air.db")
    cities = list(CITY_CODES.keys())
    all_rows, failed = [], []
    for c in cities:
        try:
            rs = fetch_daily(c)
            all_rows += rs
            print("OK  %-6s %2d 天  %s ~ %s" % (c, len(rs), rs[0]["date"], rs[-1]["date"]))
        except Exception as e:
            failed.append((c, str(e)[:60]))
            print("ERR %-6s %s" % (c, str(e)[:60]))
    n = save_daily(db, all_rows)
    print("\n[入库] %d 行 → city_daily" % n)
    if failed:
        print("[失败] %d 城：%s" % (len(failed), failed))
    got = load_daily(db)
    days = sorted({r["date"] for v in got.values() for r in v})
    print("[核对] 库内 %d 城 / %d 天（%s ~ %s）" %
          (len(got), len(days), days[0] if days else "-", days[-1] if days else "-"))
