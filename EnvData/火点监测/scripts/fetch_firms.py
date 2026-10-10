# -*- coding: utf-8 -*-
"""抓取 NASA FIRMS 火点，按市归属 + 建点位级历史归档，写静态 JSON。

用法（本地 / GitHub Actions）：
    FIRMS_MAP_KEY=xxxx python fetch_firms.py
可选环境变量：
    FIRMS_DAYS=2           本次抓取窗口（天）；>5 时按日期逐天回补
    FIRMS_SNAPSHOT_DAYS=2  页面展示窗口（天）
    FIRMS_HISTORY_DAYS=60  点位历史保留窗口（天）

输出：
    ../data/fires-henan.json
      · cities   当前快照（近 SNAPSHOT_DAYS 天，按市分组；不含省外）
      · cells    点位级历史（仅省内）：{key: {"d": {日期: 是否夜间}, "fm": 最大FRP}}
      · history  各市每日计数（滚动 HISTORY_DAYS 天）
    每个火点带 cause / cause_conf / reasons（成因推测 + 依据）/ hist（该点位历史摘要）

要点：
- 数据源：VIIRS 375m 近实时（Suomi-NPP + NOAA-20），坐标 WGS-84。
- 页面显示时再 WGS-84 → GCJ-02（页面已有 wgs2gcj），与高德底图对齐。
- 「自主学习」= 用点位历史复现统计（出现天数/夜间天数/最大FRP）驱动成因判定，
  随历史累积自动改进；不调模型、规则透明可复核。
- 密钥只从环境变量 FIRMS_MAP_KEY 读，绝不写进代码/仓库。
"""
import csv
import io
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cause  # 同目录：火点成因推测

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE.parent / "data" / "fires-henan.json"
LOG_JSON = HERE.parent / "data" / "fetch-log.json"   # 数据获取日志（每次抓取记一条）
LOG_MAX = 200                                        # 日志滚动保留条数

BBOX = (110.0, 31.0, 117.0, 36.6)   # west,south,east,north
SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]
DAYS = int(os.environ.get("FIRMS_DAYS", "2"))
SNAPSHOT_DAYS = int(os.environ.get("FIRMS_SNAPSHOT_DAYS", "2"))
HISTORY_DAYS = int(os.environ.get("FIRMS_HISTORY_DAYS", "60"))

GEO_DIR = Path(os.environ.get("HENAN_GEO_DIR", str(HERE.parent / "geo")))
PROVINCE_GEO = GEO_DIR / "河南省_县.geojson"
FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{bbox}/{days}"

_BJ = timezone(timedelta(hours=8))


def bj_now():
    return datetime.now(_BJ)


def bj_today():
    return bj_now().strftime("%Y-%m-%d")


# ---------- 几何：点落多边形（射线法，纯 Python）----------
def point_in_ring(x, y, ring):
    inside = False
    n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geom(x, y, geom):
    t = geom.get("type")
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return False
    for poly in polys:
        if poly and point_in_ring(x, y, poly[0]) and not any(point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def load_geojson(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_city_geoms():
    out = []
    for p in sorted(GEO_DIR.glob("*市_县.geojson")):
        city = p.name.replace("市_县.geojson", "")
        out.append((city, [f["geometry"] for f in load_geojson(p).get("features", [])]))
    return out


def load_province_geoms():
    return [f["geometry"] for f in load_geojson(PROVINCE_GEO).get("features", [])]


def assign_city(lng, lat, city_geoms, prov_geoms):
    for city, geoms in city_geoms:
        for g in geoms:
            if point_in_geom(lng, lat, g):
                return city
    for g in prov_geoms:
        if point_in_geom(lng, lat, g):
            return "河南·其他市"
    return "省外"


# ---------- 抓取 ----------
def fetch_source(key, src, days, date=None):
    url = FIRMS_AREA.format(key=key, src=src, bbox=",".join(str(v) for v in BBOX), days=days)
    if date:
        url += "/" + date
    req = urllib.request.Request(url, headers={"User-Agent": "envlab-fire/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        text = r.read().decode("utf-8", "replace")
    if not text.startswith("latitude"):
        raise RuntimeError("FIRMS 返回异常：%s" % text[:160])
    fires = []
    for r_ in csv.DictReader(io.StringIO(text)):
        try:
            fires.append({
                "lat": round(float(r_["latitude"]), 5),
                "lng": round(float(r_["longitude"]), 5),
                "frp": round(float(r_["frp"]), 2),
                "conf": r_.get("confidence", ""),
                "sat": r_.get("satellite", ""),
                "date": r_.get("acq_date", ""),
                "time": r_.get("acq_time", ""),
                "dn": r_.get("daynight", ""),
            })
        except (KeyError, ValueError):
            continue
    return fires


def fetch_range(key, src, days):
    """days<=5 单次请求；否则按日期逐天回补。"""
    if days <= 5:
        return fetch_source(key, src, days)
    out = []
    base = bj_now()
    for i in range(days):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            out += fetch_source(key, src, 1, d)
        except Exception as e:  # noqa
            print("[firms] %s %s 失败：%s" % (src, d, e), file=sys.stderr)
    return out


def dedupe(fires):
    seen, out = set(), []
    for f in fires:
        k = (f["lat"], f["lng"], f["date"], f["time"])
        if k not in seen:
            seen.add(k); out.append(f)
    return out


def cell_key(f):
    return "%.2f,%.2f" % (f["lat"], f["lng"])


class FetchError(RuntimeError):
    """可预期的抓取失败（缺 key、数据源异常等）——会被记入获取日志。"""


def append_log(entry):
    """把一次抓取的执行记录追加进 data/fetch-log.json（滚动保留最近 LOG_MAX 条）。

    日志是「什么时候抓的、结果是什么」的凭据，页面直接读它展示；
    失败也记（含原因），所以页面永远能显示最近一次抓取的真实结果。
    """
    hist = []
    if LOG_JSON.exists():
        try:
            hist = json.loads(LOG_JSON.read_text(encoding="utf-8"))
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []
    hist.append(entry)
    hist = hist[-LOG_MAX:]
    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    return hist


def run():
    """执行一次抓取并写出数据；返回结果摘要（供获取日志记录）。"""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        raise FetchError("缺少环境变量 FIRMS_MAP_KEY（需在仓库 Settings → Secrets and variables → Actions 里配置）")

    fires = []
    for src in SOURCES:
        try:
            got = fetch_range(key, src, DAYS)
            print("[firms] %s -> %d 条" % (src, len(got)))
            fires.extend(got)
        except Exception as e:  # noqa
            print("[firms] %s 失败：%s" % (src, e), file=sys.stderr)
    fires = dedupe(fires)
    print("[firms] 去重后 %d 条（窗口 %d 天）" % (len(fires), DAYS))
    if not fires:
        # 河南 bbox 两天窗口从未出现过 0 条；0 条几乎一定是抓取失败，
        # 此时绝不能把已有的好数据覆盖成空快照。
        raise FetchError("两个数据源都没有返回火点（可能网络不通 / MAP_KEY 失效 / 额度用尽），已保留上一版数据")

    city_geoms = load_city_geoms()
    prov_geoms = load_province_geoms()
    print("[firms] 已加载 %d 个市界 + 全省县界" % len(city_geoms))

    prev = {}
    if OUT_JSON.exists():
        try:
            prev = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    today = bj_today()
    hist_cutoff = (bj_now() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    snap_cutoff = (bj_now() - timedelta(days=SNAPSHOT_DAYS - 1)).strftime("%Y-%m-%d")

    pairs = [(f, assign_city(f["lng"], f["lat"], city_geoms, prov_geoms)) for f in fires]

    # 点位历史归档（仅省内），先裁剪到窗口（兼容旧格式：非 dict 的一律丢弃）
    cells = {k: v for k, v in (prev.get("cells") or {}).items() if isinstance(v, dict)}
    for k in list(cells):
        d = {dt: n for dt, n in (cells[k].get("d") or {}).items() if dt >= hist_cutoff}
        if d:
            cells[k]["d"] = d
        else:
            cells.pop(k, None)

    # 用「历史」（不含本次）给每个省内火点打成因 + 依据 + 历史摘要
    for f, city in pairs:
        if city == "省外":
            continue
        rec = cells.get(cell_key(f), {})
        dd = rec.get("d") or {}
        n, nt, fm = len(dd), sum(dd.values()), rec.get("fm", 0)
        cname, cconf, reasons = cause.classify(
            f, n, {"nt": nt, "fm": fm, "dates": sorted(dd), "win": HISTORY_DAYS})
        f["cause"], f["cause_conf"], f["reasons"] = cname, cconf, reasons
        f["hist"] = {"n": n, "nt": nt, "fm": round(fm, 1), "win": HISTORY_DAYS,
                     "dates": sorted(dd)[-10:]}

    # 并入本次（仅省内），更新点位历史
    for f, city in pairs:
        if city == "省外":
            continue
        rec = cells.setdefault(cell_key(f), {"d": {}, "fm": 0})
        dt = f["date"] or today
        rec["d"][dt] = max(rec["d"].get(dt, 0), 1 if f["dn"] == "N" else 0)
        rec["fm"] = max(rec.get("fm", 0), float(f["frp"] or 0))
    for k in list(cells):
        d = {dt: n for dt, n in (cells[k].get("d") or {}).items() if dt >= hist_cutoff}
        if d:
            cells[k]["d"] = d
        else:
            cells.pop(k, None)

    # 快照：近 SNAPSHOT_DAYS 天、非省外，按市分组
    cities = {}
    for f, city in pairs:
        if city == "省外" or (f["date"] or "") < snap_cutoff:
            continue
        cities.setdefault(city, []).append(f)

    # 每日明细归档（仅省内）：data/daily/<日期>.json，供周报/明细导出；保留 35 天
    daily_dir = OUT_JSON.parent / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    by_day = defaultdict(list)
    for f, city in pairs:
        if city != "省外" and f["date"]:
            by_day[f["date"]].append({**f, "city": city})
    for dt, lst in by_day.items():
        (daily_dir / f"{dt}.json").write_text(
            json.dumps(lst, ensure_ascii=False), encoding="utf-8")
    keep_from = (bj_now() - timedelta(days=35)).strftime("%Y-%m-%d")
    for p in daily_dir.glob("*.json"):
        if p.stem < keep_from:
            p.unlink()

    # 各市每日计数（用本次抓到的全部日期，回补时也能填充历史）
    history = prev.get("history") or {}
    by_date = defaultdict(lambda: defaultdict(int))
    for f, city in pairs:
        if city != "省外":
            by_date[f["date"]][city] += 1
    for dt, cmap in by_date.items():
        for c, n in cmap.items():
            h = [e for e in history.get(c, []) if e.get("date") != dt]
            h.append({"date": dt, "count": n})
            history[c] = sorted(h, key=lambda e: e["date"])[-90:]

    payload = {
        "source": "NASA FIRMS VIIRS 375m 近实时 (Suomi-NPP + NOAA-20)",
        "bbox": list(BBOX),
        "days": SNAPSHOT_DAYS,
        "history_days": HISTORY_DAYS,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": sum(len(v) for v in cities.values()),
        "counts": {k: len(v) for k, v in sorted(cities.items(), key=lambda kv: -len(kv[1]))},
        "cities": cities,
        "history": history,
        "cells": cells,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("[firms] 写出 %s（快照 %d 条 / 点位档案 %d 个）" % (OUT_JSON, payload["count"], len(cells)))
    print("[firms] 各市计数：")
    for k, v in payload["counts"].items():
        print("    %-12s %d" % (k, v))
    from collections import Counter
    cc = Counter(f.get("cause") for f, c in pairs if c != "省外")
    print("[firms] 成因推测分布（省内）：")
    for k, v in cc.most_common():
        print("    %-24s %d" % (k, v))

    return {
        "raw": len(fires),
        "count": payload["count"],
        "cells": len(cells),
        "daily_days": len(by_day),
        "cities": payload["counts"],
        "causes": dict(cc),
    }


def main():
    t0 = time.time()
    trigger = (os.environ.get("GITHUB_EVENT_NAME")
               or os.environ.get("FIRMS_TRIGGER")
               or "本地/手动").strip()
    base = {
        "t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bj": bj_now().strftime("%Y-%m-%d %H:%M"),
        "trigger": trigger,
        "days": DAYS,
        "snapshot_days": SNAPSHOT_DAYS,
        "history_days": HISTORY_DAYS,
    }
    try:
        info = run()
    except FetchError as e:
        append_log(dict(base, ok=False, stage="配置/数据源", error=str(e),
                        sec=round(time.time() - t0, 1)))
        print("[firms] 抓取失败：%s" % e, file=sys.stderr)
        print("[firms] 失败已记入 %s" % LOG_JSON, file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa
        append_log(dict(base, ok=False, stage="运行异常",
                        error="%s: %s" % (type(e).__name__, e),
                        sec=round(time.time() - t0, 1)))
        print("[firms] 抓取异常：%s" % e, file=sys.stderr)
        raise

    hist = append_log(dict(base, ok=True, sec=round(time.time() - t0, 1), **info))
    print("[firms] 获取日志已更新（共 %d 条）%s" % (len(hist), LOG_JSON))
    print("[firms] 本次结果：%s 成功 · 原始 %d 条 → 快照 %d 条 · 点位档案 %d 个 · 每日归档 %d 天 · 耗时 %.1fs"
          % (base["bj"], info["raw"], info["count"], info["cells"], info["daily_days"],
             round(time.time() - t0, 1)))


if __name__ == "__main__":
    main()
