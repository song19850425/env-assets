# -*- coding: utf-8 -*-
"""生成近 N 天的河南火点明细 CSV（供每周邮件发送）。

用法：
    python weekly_report.py [天数]        # 默认 7 天

输入：../data/daily/<日期>.json   （由 fetch_firms.py 每日归档，仅省内）
输出：../data/weekly/河南火点明细_<起>_<止>.csv（UTF-8 BOM，Excel 直接打开不乱码）

列：日期 / 北京时间 / 市 / 纬度 / 经度 / 辐射功率MW / 置信度 / 昼夜 / 卫星 /
    成因推测 / 成因置信度 / 依据 / 点位近60天出现天数
"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DAILY = DATA / "daily"
OUTDIR = DATA / "weekly"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
_BJ = timezone(timedelta(hours=8))
CONF_CN = {"h": "高", "n": "中", "l": "低"}
COLS = ["日期", "北京时间", "市", "纬度", "经度", "辐射功率MW", "置信度", "昼夜", "卫星",
        "成因推测", "成因置信度", "依据", "点位近60天出现天数"]


def bj_time(date, t):
    """FIRMS acq_time 为 UTC 的 HHMM（可能丢前导零），转北京时间字符串。"""
    s = str(t or "").zfill(4)
    if len(s) != 4 or not s.isdigit():
        return ""
    try:
        dt = (datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              + timedelta(hours=8 + int(s[:2]), minutes=int(s[2:4])))
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def main():
    today = datetime.now(_BJ).date()
    start = today - timedelta(days=DAYS - 1)
    rows, missing = [], []
    for i in range(DAYS):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        p = DAILY / f"{d}.json"
        if not p.exists():
            missing.append(d)
            continue
        for f in json.loads(p.read_text(encoding="utf-8")):
            rows.append({
                "日期": f.get("date", ""),
                "北京时间": bj_time(f.get("date", ""), f.get("time", "")),
                "市": f.get("city", ""),
                "纬度": f.get("lat"),
                "经度": f.get("lng"),
                "辐射功率MW": f.get("frp"),
                "置信度": CONF_CN.get(f.get("conf"), f.get("conf", "")),
                "昼夜": "夜间" if f.get("dn") == "N" else "白天",
                "卫星": f.get("sat", ""),
                "成因推测": f.get("cause", ""),
                "成因置信度": f.get("cause_conf", ""),
                "依据": "；".join(f.get("reasons") or []),
                "点位近60天出现天数": (f.get("hist") or {}).get("n", ""),
            })
    rows.sort(key=lambda r: (r["日期"], r["市"], r["北京时间"]))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"河南火点明细_{start:%Y%m%d}_{today:%Y%m%d}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print(f"[weekly] 区间 {start} ~ {today}（{DAYS} 天）")
    print(f"[weekly] 明细 {len(rows)} 条 → {out}")
    if missing:
        print(f"[weekly] ⚠ 缺以下日期的归档（当天可能无 CI 运行或该日无火点）：{missing}")
    by_city = Counter(r["市"] for r in rows)
    by_kind = Counter(r["成因推测"] for r in rows)
    print("[weekly] 各市：", "、".join(f"{k}{v}" for k, v in by_city.most_common()) or "无")
    print("[weekly] 成因：", "、".join(f"{k}{v}" for k, v in by_kind.most_common()) or "无")
    print(f"[weekly] FILE={out.resolve()}")


if __name__ == "__main__":
    main()
