# -*- coding: utf-8 -*-
"""按年份回补历史火点数据（FIRMS 存档），按市归属后写成本地历史库。

用法：
    python backfill_firms.py 2025              # 回补 2025 全年
    python backfill_firms.py 2025 6 9          # 只回补 2025 年 6~9 月
    python backfill_firms.py 2025 --source SP  # 指定源（SP 默认 / NRT）

为什么要用 SP 源：
    FIRMS 的 NRT（近实时）只保留约 2 个月；**更早的历史必须用 SP（标准处理）源**。
    SP 实测可回溯到 2023/2024/2025（见 scripts 注释与项目备忘）。

⚠ 已知口径问题（务必注意，别直接跨源比数量）：
    SP 与 NRT 的覆盖期不重叠、无法同日对比；且实测某些时段 SP 条数远少于 NRT。
    所以本脚本**记录用了哪个源**，产物里带 `sources` 字段；做趋势分析时必须同源比较。

输出：
    ../data/history/<年>.json
      · year / sources / bbox / generated_utc
      · daily       {"YYYY-MM-DD": {"南阳": n, "洛阳": n, ...}}  逐日逐市计数
      · counts      全年各市合计
      · fires       [ {date,time,lat,lng,frp,conf,sat,dn,city}, ... ] 全部省内火点明细
      · windows     抓取窗口与每个窗口的条数（便于核查缺段）

环境变量：
    FIRMS_MAP_KEY   必需
"""
import json
import sys
import time
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
DATA = MOD / "data"
HIST = DATA / "history"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fetch_firms as FF   # 复用抓取/归属/去重逻辑，避免两套实现

SP_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"]
NRT_SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]
WIN = 5                    # FIRMS 接口单次最多 5 天


def pull(key, src, start: date, days=WIN):
    """拉一个窗口（最多 5 天）。返回 (fire_list, note)。"""
    try:
        return FF.fetch_source(key, src, days, start.strftime("%Y-%m-%d")), ""
    except Exception as e:                                   # noqa
        return [], "%s: %s" % (type(e).__name__, e)


def main():
    key = (FF.os.environ.get("FIRMS_MAP_KEY") or "").strip()
    if not key:
        raise SystemExit("[backfill] 缺少环境变量 FIRMS_MAP_KEY")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("用法：python backfill_firms.py <年份> [起月] [止月]")
    year = int(args[0])
    m0 = int(args[1]) if len(args) > 1 else 1
    m1 = int(args[2]) if len(args) > 2 else 12
    use_sp = "--source" not in sys.argv or "NRT" not in sys.argv
    sources = SP_SOURCES if use_sp else NRT_SOURCES

    start = date(year, m0, 1)
    end = (date(year, m1, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    today = datetime.now(timezone.utc).date()
    if end > today:
        end = today

    print("[backfill] %s ~ %s | 源：%s | 窗口 %d 天" % (start, end, "+".join(sources), WIN))

    city_geoms = FF.load_city_geoms()
    prov_geoms = FF.load_province_geoms()
    print("[backfill] 已加载 %d 个市界 + 全省县界" % len(city_geoms))

    # 窗口级缓存：每个 5 天窗口抓完就落盘，重跑时直接读缓存。
    # 目的：① 避免重复请求（额度虽够，但慢）；② 中断后可从断点续跑，不用从头再来。
    cache_dir = DATA / "history" / "_win" / str(year)
    cache_dir.mkdir(parents=True, exist_ok=True)

    raw, windows = [], []
    cur, win_i = start, 0
    n_hit = 0
    while cur <= end:
        d = min(WIN, (end - cur).days + 1)
        win_key = cur.strftime("%Y-%m-%d")
        cf = cache_dir / (win_key + ".json")
        if cf.exists():
            try:
                cached = json.loads(cf.read_text(encoding="utf-8"))
                raw.extend(cached["fires"])
                windows.append(cached["win"])
                n_hit += 1
                win_i += 1
                print("  [%2d] %s +%dd → %d 条（缓存）" % (win_i, cur, d, len(cached["fires"])))
                cur += timedelta(days=d)
                continue
            except Exception as e:                              # noqa
                print("  [!!] 缓存损坏，重抓：%s（%s）" % (cf.name, e))

        got_this = 0
        notes = []
        win_fires = []
        for src in sources:
            fires, note = pull(key, src, cur, d)
            got_this += len(fires)
            win_fires.extend(fires)
            if note:
                notes.append("%s %s" % (src, note))
            time.sleep(0.3)
        raw.extend(win_fires)
        win_rec = {"start": win_key, "days": d, "rows": got_this, "notes": notes}
        windows.append(win_rec)
        # 有错误的窗口不写缓存（下次重跑会重试）
        if not notes:
            try:
                cf.write_text(json.dumps({"fires": win_fires, "win": win_rec},
                                         ensure_ascii=False), encoding="utf-8")
            except Exception:                                   # noqa
                pass
        win_i += 1
        print("  [%2d] %s +%dd → %d 条%s" % (win_i, cur, d, got_this,
                                            "  ⚠ " + "; ".join(notes) if notes else ""))
        cur += timedelta(days=d)
    if n_hit:
        print("[backfill] 命中缓存 %d 个窗口（其余为本次抓取）" % n_hit)

    deduped = FF.dedupe(raw)
    print("[backfill] 原始 %d 条 → 去重 %d 条" % (len(raw), len(deduped)))

    daily = defaultdict(lambda: defaultdict(int))
    counts = defaultdict(int)
    fires_out = []
    for f in deduped:
        c = FF.assign_city(f["lng"], f["lat"], city_geoms, prov_geoms)
        if c == "省外":
            continue
        dt = f["date"]
        daily[dt][c] += 1
        counts[c] += 1
        fires_out.append({"date": dt, "time": f["time"], "lat": f["lat"], "lng": f["lng"],
                          "frp": f["frp"], "conf": f["conf"], "sat": f["sat"],
                          "dn": f["dn"], "city": c})

    HIST.mkdir(parents=True, exist_ok=True)
    out = HIST / ("%d.json" % year)
    payload = {
        "year": year,
        "sources": sources,
        "bbox": list(FF.BBOX),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "SP 与 NRT 覆盖期不重叠、检出条数量级可能不同，跨源比较数量无效。",
        "days": len(daily),
        "count": len(fires_out),
        "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "daily": {k: dict(v) for k, v in sorted(daily.items())},
        "fires": fires_out,
        "windows": windows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("[backfill] 写出 %s（%d 天有火点 / 省内共 %d 条）" % (out, len(daily), len(fires_out)))
    print("[backfill] 各市合计 Top10：")
    for k, v in list(payload["counts"].items())[:10]:
        print("    %-10s %d" % (k, v))


if __name__ == "__main__":
    main()
