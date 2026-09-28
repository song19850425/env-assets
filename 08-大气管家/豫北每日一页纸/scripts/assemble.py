# -*- coding: utf-8 -*-
"""取数装配层：把"日报新增章节"所需的三类补充数据一次取齐（只做网络请求，不碰数据库）。

存在的理由：`report/daily_report.py` 必须保持"无数据库、无网络"才能被云端出报复用；
本机两个入口（run_daily / run_v2）又都需要同样的补充数据。若各写一份，
迟早出现"重出报的页面与采集出报的页面不一样"。故统一放在这里。

三类数据：
  neighbors  省外上风向城市实时浓度 → 补上传输研判的城市池盲区
  forecast   CAMS 模式逐时预报      → 未来 24h 趋势（此前完全缺失）
  daily      （不在此模块）日历史在 run_daily 里入库后由 core.db.load_daily 取，
             因为它需要落库（14 天滚动窗口，不落盘即永久丢失）

所有函数**失败不抛异常、只记 errors**：补充数据取不到时，日报应降级而不是出不来。
"""
import sys


def fetch_neighbors(cfg, archive=True):
    """省外上风向城市：取实时城市均值（pm25_mean），供传输研判。

    返回 (neighbor_air, rows, errors)。rows 供调用方入库（邻居城市的小时序列
    同样有长期价值），是否入库由调用方决定。
    archive=False 时不落原始报文 —— 云端 runner 落盘会污染仓库；
    且原始报文作为"唯一凭证"的意义只针对交付城市（本地四市），邻居无需留存。
    """
    from ingest.fetch_air import fetch_city
    names = list(cfg.get("neighbors") or [])
    air, rows, errors = {}, [], []
    for c in names:
        try:
            rs = fetch_city(c, archive=archive)
        except Exception as e:
            errors.append("%s 上风向城市采集失败：%s" % (c, str(e)[:100]))
            continue
        vals = [r.get("pm25") for r in rs if r.get("pm25") is not None]
        air[c] = {"pm25_mean": (round(sum(vals) / len(vals), 1) if vals else None), "n": len(rs)}
        rows.extend(rs)
    if names:
        print("[上风向] %d/%d 城取到（%s）"
              % (len(air), len(names), "、".join("%s %.1f" % (c[:2], v["pm25_mean"])
                                                 for c, v in air.items() if v["pm25_mean"] is not None)))
    return air, rows, errors


def fetch_forecast_series(cfg):
    """CAMS 模式逐时预报 → 逐时 AQI 序列（calc.forecast.hourly_aqi 的输出）。

    返回 (series {city: [...]}, errors)。预报缺失时该章节自动隐藏。
    """
    from calc.forecast import hourly_aqi
    from ingest.fetch_forecast import fetch_all as _fetch_fc
    coords = cfg.get("coords") or {}
    if not coords:
        return {}, []
    data, errors = _fetch_fc(coords)
    series = {}
    for city, rows in data.items():
        try:
            series[city] = hourly_aqi(rows)
        except Exception as e:
            errors.append("%s 预报计算失败：%s" % (city, str(e)[:100]))
    if series:
        print("[预报] %d/%d 城取到逐时预报" % (len(series), len(coords)))
    for e in errors:
        print("[告警] %s" % e)
    return series, errors


if __name__ == "__main__":
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    from config import PROFILES
    cfg = PROFILES["yubei"]
    air, rows, e1 = fetch_neighbors(cfg)
    ser, e2 = fetch_forecast_series(cfg)
    print("上风向城市 %d 个、行 %d 条、错误 %d 条" % (len(air), len(rows), len(e1)))
    print("预报城市 %d 个、错误 %d 条" % (len(ser), len(e2)))
