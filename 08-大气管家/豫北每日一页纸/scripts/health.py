# -*- coding: utf-8 -*-
"""云端健康档案：让"云端到底在不在干活"成为可查的事实。

为什么必须要有
--------------
出报侧刻意做了"内容不变就不落盘"（避免 hourly 空提交撑肥仓库），
副作用是**失败与无变化在文件层面长得一模一样**——都是"文件没动"。
只看仓库根本分辨不出是"数据没更新"还是"脚本挂了"。
采集侧早有 data-hourly/_health.json 解决同类问题；出报侧同样需要一份。

协作方式：日报与周期报告是两个进程，各自只写自己的条目，
写前先读、读完合并，因此互不覆盖（谁也不清空谁的结果）。

新鲜度：条目带 at（北京时间）。顶层 ok 只看**近 3 小时**内更新过的条目 ——
凌晨某个脚本整体崩溃时，它的旧条目不会永远把 ok 钉死在 true；
超期未更新的条目会被列进 stale，提示"这一类报告本轮没跑成"。
"""
import json
import os
import time
from datetime import datetime, timedelta

NAME = "_health_report.json"
FRESH_HOURS = 3


def _tz_offset():
    return (-time.timezone if not time.localtime().tm_isdst else -time.altzone) / 3600.0


def merge(module_dir, key, payload):
    """读-改-写健康档案，把 entry 写到 reports[key]。返回合并后的字典。"""
    path = os.path.join(module_dir, NAME)
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception as e:
            print("[警告] 健康档案读取失败，将重建（%s）" % e)
            data = {}

    now = datetime.now()
    entry = dict(payload)
    entry["at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    reports = data.get("reports") or {}
    reports[key] = entry

    fresh, stale = {}, []
    limit = now - timedelta(hours=FRESH_HOURS)
    for k, v in reports.items():
        try:
            t = datetime.strptime(str(v.get("at", "")), "%Y-%m-%d %H:%M:%S")
        except Exception:
            stale.append(k)
            continue
        if t >= limit:
            fresh[k] = v
        else:
            stale.append(k)      # 超期未更新 = 这一类报告本轮没跑成

    off = _tz_offset()
    out = {
        "last_run": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "tz": "Asia/Shanghai" if off == 8 else "UTC%+.1fh（异常：页面时间会偏差）" % off,
        "ok": all(bool(v.get("ok")) for v in fresh.values()) if fresh else False,
        "reports": reports,
        "stale": stale,
        "note": ("ok 只看近 %d 小时内更新过的条目；written=0 表示内容与上次一致（去抖生效），"
                 "不代表失败，失败看各类自身的 ok/error。" % FRESH_HOURS),
    }
    os.makedirs(module_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return out
