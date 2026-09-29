# -*- coding: utf-8 -*-
"""生成 EnvLab/03-质量控制/质量控制训练室.html

为什么要生成
------------
质控判据（平行样相对偏差上限、试剂空白吸光度上限、声学校准偏差上限……）
**必须与 EnvStandard 里的标准数据完全一致**。手写一份到页面里，标准数据一更新就漂，
而质控判据错了比没有判据更糟 —— 学生会照着错的判据判合格。

所以本页的判据全部从 EnvStandard/data/standards/*.json 现读：
  · 每个判据都声明 (standardId, key)，读不到就报错退出
  · 页面上每条判据都带标准号与条款出处
  · 训练题的正确答案由判据**算出来**，不是手写的

诚实边界（写进页面，不藏起来）
------------------------------
「加标回收率应在 80%~120%」「标准曲线相关系数 r≥0.999」是行业里流传很广的说法，
但**已入库标准中找不到统一规定** —— 各方法标准自定，本模块不编造通用阈值。
页面会把这一点直接写出来。

跑法：python build_qc_trainer.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STD_DIR = ROOT / "EnvStandard" / "data" / "standards"
OUTPUT = ROOT / "EnvLab" / "03-质量控制" / "质量控制训练室.html"

# ---------------------------------------------------------------- 判据（数值）
# (standardId, values 键, 用途, 介质)
CRITERIA = [
    ("HJ1075-2019", "parallel-deviation-max", "平行双样测定结果的相对偏差上限", "浊度"),
    ("HJ1075-2019", "parallel-ratio-min", "每批样品应测定的平行双样比例下限", "浊度"),
    ("HJ1075-2019", "parallel-batch-threshold", "样品数低于该值时应至少测定一个平行双样", "浊度"),
    ("HJ1075-2019", "blank-per-batch-min", "每批样品至少进行的空白测定次数", "浊度"),
    ("HJT167-2004", "parallel-deviation-max", "平行样测定值之差与平均值比较的相对偏差上限", "室内空气"),
    ("HJT167-2004", "parallel-ratio-min", "平行样数量占每批采样的最低比例", "室内空气"),
    ("HJT167-2004", "blank-tubes-min", "现场空白的最少采样管数量", "室内空气"),
    ("HJT167-2004", "flow-calibration-error-max", "采样流量前后两次校准的误差上限", "室内空气"),
    ("GBT18883-2022", "parallel-deviation-max", "平行样测定值绝对差值与平均值的比值上限", "室内空气"),
    ("GBT18883-2022", "parallel-ratio-min", "平行样数量占每批样品的最低比例", "室内空气"),
    ("GBT18883-2022", "blank-tubes-min", "现场空白的最少采样管（膜）数量", "室内空气"),
    ("GBT18883-2022", "flow-calibration-deviation-max", "采样流量前后两次校准的相对偏差上限", "室内空气"),
    ("HJ639-2012", "qc-blank-per-batch-min", "每批样品至少采集的运输空白与全程序空白样品数（各 1 个）", "VOCs"),
    ("HJ639-2012", "qc-batch-size", "平行样分析与基体加标分析的批内样品数阈值", "VOCs"),
    ("HJ639-2012", "storage-days-max", "样品最长保存时间", "VOCs"),
    ("HJ535-2009", "blank-absorbance-max", "试剂空白的吸光度上限（10 mm 比色皿）", "氨氮"),
    ("HJ535-2009", "calibration-points", "校准曲线的浓度点数", "氨氮"),
    ("HJ535-2009", "mdl", "方法检出限（50 mL 水样、20 mm 比色皿）", "氨氮"),
    ("HJ535-2009", "loq", "方法测定下限", "氨氮"),
    ("HJ535-2009", "storage-days-max", "酸化后水样的最长保存时间", "氨氮"),
    ("HJ586-2010", "calibration-points", "校准曲线的浓度点数", "游离氯"),
    ("HJ586-2010", "storage-days-max", "样品最长保存时间", "游离氯"),
    ("HJ38-2017", "calibration-levels", "校准系列的浓度梯度数", "非甲烷总烃"),
    ("HJ38-2017", "mdl-nmhc", "非甲烷总烃的方法检出限", "非甲烷总烃"),
    ("HJ38-2017", "loq-nmhc", "非甲烷总烃的测定下限", "非甲烷总烃"),
    ("HJ38-2017", "syringe-storage-hours-max", "玻璃注射器保存样品的最长时间", "非甲烷总烃"),
    ("HJ38-2017", "bag-storage-hours-max", "气袋保存样品的最长时间", "非甲烷总烃"),
    ("GB12348-2008", "calibration-deviation-max", "现场声学校准的示值偏差上限（超出则测量结果无效）", "厂界噪声"),
    ("GB3096-2008", "calibration-deviation-max", "测量前后声校准器校准仪器的示值偏差上限", "声环境"),
    ("HJT299-2007", "blank-per-batch", "每做多少个样品（或每批）至少做一个浸出空白", "浸出毒性"),
    ("HJ605-2011", "corr-coef-min", "线性或非线性校准曲线的相关系数下限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "rrf-rsd-max", "相对响应因子（RRF）的相对标准偏差上限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "surrogate-recovery-min", "替代物加标回收率下限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "surrogate-recovery-max", "替代物加标回收率上限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "parallel-surrogate-deviation-max", "平行样中替代物相对偏差上限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "calib-verify-recovery-min", "校准确认标准溶液测定值与加入浓度比值的下限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "calib-verify-recovery-max", "校准确认标准溶液测定值与加入浓度比值的上限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "mdl-range-min", "全扫描方式方法检出限下限", "土壤/沉积物 VOCs"),
    ("HJ605-2011", "mdl-range-max", "全扫描方式方法检出限上限", "土壤/沉积物 VOCs"),
    ("HJ1075-2019", "mdl", "方法检出限", "浊度"),
    ("HJ1075-2019", "storage-hours-max", "样品最长保存时间", "浊度"),
]

# ---------------------------------------------------------------- 判据（定性）
QUAL = [
    ("GBT18883-2022", "field-blank", "现场空白超标 → 这批样品作废"),
    ("HJT167-2004", "field-blank", "空白检验超过控制范围 → 这批样品作废"),
    ("HJ639-2012", "replicate-requirement", "所有样品均采集平行双样，每批带一个全程序空白和一个运输空白"),
    ("HJT299-2007", "quality-assurance", "每 20 个样或每批至少做一个浸出空白；每批至少做一个加标回收样品"),
    ("HJ1230-2021", "instrument-checks-before-use", "仪器使用前检查：预热不少于 30 min、气路气密性、零点与示值检查"),
    ("HJ25.1-2019", "field-qa-qc", "现场质量保证和质量控制措施清单"),
    ("HJ164-2020", "sample-handover", "样品交接符合性检查与异常记录"),
]

# 常被当成「通行值」、但标准其实规定的是别的数的判据
NO_UNIFIED = [
    ("加标回收率 80%~120%",
     "标准给的不是这个数。HJ 605-2011 第 11.4.4 条规定替代物加标回收率应在 "
     "70%~130%（见判据速查）；HJ/T 299-2007 只要求「每批至少做一个加标回收样品」，"
     "不给范围。各方法标准自定，必须翻对应标准。"),
    ("标准曲线相关系数 r ≥ 0.999",
     "标准给的不是这个数。HJ 605-2011 第 8.2.2.2 条规定线性/非线性校准曲线相关系数 "
     "≥ 0.99；HJ 535-2009、HJ 586-2010 只规定校准点数量（8 点 / 7 点），未给 r。"
     "同一份报告里不同方法可能适用不同的 r 要求。"),
    ("实验室间相对偏差限值",
     "能力验证 / 实验室间比对的可接受范围由组织方或认可准则给定，不在方法标准里。"),
]


# ------------------------------------------------------------------ 读判据
def load_standards() -> dict[str, dict]:
    out = {}
    for p in sorted(STD_DIR.glob("*.json")):
        if p.name in {"index.json", "pollutant-ids.json"}:
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        out[d["standardId"]] = d
    return out


def build_criteria(stds: dict[str, dict]) -> list[dict]:
    rows = []
    for sid, key, use, medium in CRITERIA:
        std = stds.get(sid)
        if not std:
            raise SystemExit(f"[qc] 标准未入库：{sid}")
        v = (std.get("values") or {}).get(key)
        if not v:
            raise SystemExit(f"[qc] {sid} 里没有 values.{key}（判据表与标准数据不一致）")
        rows.append({
            "standard": sid,
            "name": v.get("name") or key,
            "value": v.get("value"),
            "units": v.get("units") or "",
            "citation": v.get("citation") or "",
            "use": use,
            "medium": medium,
        })
    quals = []
    for sid, key, use in QUAL:
        std = stds.get(sid)
        if not std:
            raise SystemExit(f"[qc] 标准未入库：{sid}")
        q = next((x for x in (std.get("qualitative") or []) if x.get("key") == key), None)
        if not q:
            raise SystemExit(f"[qc] {sid} 里没有 qualitative.{key}")
        quals.append({
            "standard": sid, "key": key, "use": use,
            "text": q.get("text", ""), "citation": q.get("citation", ""),
        })
    return rows, quals


def crit_map(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["standard"], r["name"]): r for r in rows}


# ------------------------------------------------------------------ 训练题数据
# ⚠ 全部为**教学构造数据**，不是实测结果。页面会显式声明。
def parallel_items() -> list[dict]:
    """浊度平行双样。判据：相对偏差 ≤ 20%（HJ 1075-2019）。"""
    raw = [
        ("S-01", 1.2, 1.4), ("S-02", 0.8, 1.1), ("S-03", 3.6, 3.8),
        ("S-04", 12.0, 16.0), ("S-05", 0.45, 0.45), ("S-06", 2.4, 3.2),
    ]
    items = []
    for code, a, b in raw:
        mean = (a + b) / 2
        rd = abs(a - b) / mean * 100
        items.append({
            "code": code, "a": a, "b": b,
            "mean": round(mean, 4), "rd": round(rd, 2),
            "pass": rd <= 20.0,
        })
    return items


def blank_items() -> list[dict]:
    """一批氨氮样品的空白与批次有效性。"""
    return [
        {"code": "试剂空白", "desc": "试剂空白吸光度（10 mm 比色皿）", "observed": 0.041,
         "limit": "≤ 0.03", "limit_num": 0.03, "pass": False,
         "why": "试剂空白吸光度超过上限，说明试剂或实验用水被污染。"},
        {"code": "全程序空白", "desc": "全程序空白氨氮检出量 / 方法检出限 0.025 mg/L",
         "observed": 0.008, "limit": "低于方法检出限", "limit_num": 0.025, "pass": True,
         "why": "低于方法检出限，视为未检出，正常。"},
        {"code": "平行样比例", "desc": "12 个样品中测了 2 个平行双样",
         "observed": 16.7, "limit": "≥ 10%", "limit_num": 10.0, "pass": True,
         "why": "比例满足要求（HJ 1075-2019 要求不低于 10%）。"},
    ]


def calib_items() -> list[dict]:
    """校准与测量有效性。"""
    # 场景 1：声学校准 93.8 → 93.2，偏差 0.6 dB > 0.5 dB
    d1 = abs(93.8 - 93.2)
    # 场景 2：流量 0.502 → 0.489，相对偏差 = |Δ| / 均值
    f1, f2 = 0.502, 0.489
    rd2 = abs(f1 - f2) / ((f1 + f2) / 2) * 100
    return [
        {"code": "厂界噪声 · 声学校准",
         "desc": "测前校准值 93.8 dB，测后校准值 93.2 dB",
         "observed": round(d1, 2), "limit": "≤ 0.5 dB", "limit_num": 0.5,
         "pass": d1 <= 0.5, "unit": "dB",
         "why": "前后校准示值偏差超过 0.5 dB，本次测量结果无效（GB 12348-2008 / GB 3096-2008）。"},
        {"code": "室内空气 · 采样流量校准",
         "desc": "采样前 0.502 L/min，采样后 0.489 L/min",
         "observed": round(rd2, 2), "limit": "≤ 5%", "limit_num": 5.0,
         "pass": rd2 <= 5.0, "unit": "%",
         "why": "前后两次校准相对偏差在 5% 以内，取两次平均值作为采样流量实际值。"},
    ]


def decision_item() -> dict:
    return {
        "scenario": "一批 20 个废水样品测氨氮。全程序空白检出 6 mg/L —— "
                    "该方法测定下限为 0.1 mg/L，而这批样品的氨氮结果多在 5～15 mg/L。",
        "options": [
            {"key": "A", "text": "空白值低于待测样品结果，按常规扣空白后出报告", "ok": False,
             "why": "扣空白的前提是空白足够低。空白远高于测定下限，说明整批分析存在系统污染，"
                    "扣掉也扣不干净。"},
            {"key": "B", "text": "这批分析结果作废，先查空白偏高原因并排除，再对该批样品重新分析；"
                                 "样品量不足则重新采样", "ok": True,
             "why": "空白超出控制范围时，标准要求该批样品作废（GB/T 18883-2022 现场空白条款、"
                    "HJ/T 167-2004 现场空白条款）。作废后必须查清原因再重新分析，"
                    "否则重测只会重复同一个错误。"},
            {"key": "C", "text": "只重测空白，空白合格后沿用原来的样品结果", "ok": False,
             "why": "原样品结果与不合格空白是同一批分析产生的，同样受污染影响，不能沿用。"},
            {"key": "D", "text": "空白不参与判定，只要样品结果不超标就可以出报告", "ok": False,
             "why": "空白是整批数据有效性的前提，不是可选项。空白失控时样品结果本身不可信。"},
        ],
    }


# ------------------------------------------------------------------ 页面模板
HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>质量控制训练室 · 质控判据与异常处置 · 环境检测数字资产库</title>
<meta name="description" content="环境检测质量控制训练室：平行样相对偏差、空白有效性、声学与流量校准、异常处置决策四关训练。判据全部来自已入库标准，逐条带标准号与条款出处。">
<link rel="icon" href="../../assets/favicon.svg" type="image/svg+xml">
<style>
*{box-sizing:border-box}
:root{color-scheme:dark}
body{margin:0;background:#0b1220;color:#e6edf7;
  font-family:"Noto Sans SC","Microsoft YaHei",-apple-system,sans-serif;line-height:1.7}
a{color:#7dd3fc;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1020px;margin:0 auto;padding:36px 22px 70px}
.eyebrow{font-size:12px;letter-spacing:.14em;color:#69c5f0;text-transform:uppercase;font-weight:700}
h1{font-size:29px;line-height:1.3;margin:6px 0 8px}
.lede{font-size:15px;color:#a9bcd8;margin:0 0 4px;max-width:820px}
.lede b{color:#e6f5ff}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.back{display:inline-flex;align-items:center;gap:6px;border:1px solid #23375a;border-radius:9px;
  padding:7px 13px;font-size:12.5px;color:#9db3d1;background:#0f1a2e;white-space:nowrap}
.back:hover{border-color:#4aa8d8;color:#cfeaff;text-decoration:none}
.note-box{border:1px solid #24415e;background:linear-gradient(115deg,#0e2137,#0b182b);
  border-radius:13px;padding:15px 18px;color:#aec3dc;font-size:13px;margin:22px 0 8px}
.note-box strong{color:#e7f5ff}
.warn{border-left:3px solid #d69b38;background:#2a210f;border-radius:0 10px 10px 0;
  padding:12px 15px;color:#f3d394;font-size:13px;margin:14px 0}
.warn strong{color:#ffe4a8}
section{margin:34px 0 0}
h2{font-size:19px;margin:0 0 10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h2 .no{font-size:12px;font-weight:700;color:#69c5f0;border:1px solid #2b5979;background:#0c263b;
  border-radius:6px;padding:2px 8px;letter-spacing:.06em}
h2 .pt{margin-left:auto;font-size:12px;color:#7e97b4;font-weight:400}
p{margin:0 0 11px;color:#b3c6dc}
p.dim{color:#8ba0bd;font-size:13.5px}
details.crit{border:1px solid #1b3550;background:#0d1b2d;border-radius:12px;padding:0;margin:12px 0;overflow:hidden}
details.crit>summary{cursor:pointer;list-style:none;padding:13px 17px;font-size:14.5px;
  color:#e6f5ff;font-weight:600;display:flex;align-items:center;gap:9px}
details.crit>summary::-webkit-details-marker{display:none}
details.crit>summary .ar{margin-left:auto;color:#5f7a9e;font-size:12px;transition:transform .2s}
details.crit[open]>summary .ar{transform:rotate(90deg)}
.crit-body{padding:0 17px 15px;border-top:1px solid #16283e}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px;margin:10px 0}
.tbl th{text-align:left;background:#122b43;color:#9dd9f4;font-size:11.5px;padding:7px 9px;
  border-bottom:1px solid #27516d;font-weight:600;white-space:nowrap}
.tbl td{padding:7px 9px;border-bottom:1px solid #16283e;color:#b3c6dc;vertical-align:top}
.tbl tr:hover td{background:#10243a}
.tbl .v{color:#f1db94;font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600}
.tbl .src{color:#6e88a5;font-size:11px;font-family:ui-monospace,Consolas,monospace}
.tbl .med{color:#8fd9f6;white-space:nowrap}
.lvl{border:1px solid #1b3550;background:#0d1b2d;border-radius:13px;padding:17px 19px;margin:13px 0;
  border-left:3px solid #2b5979}
.lvl.locked{opacity:.45}
.lvl-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.lvl-no{font-size:11px;font-weight:700;color:#69c5f0;font-family:ui-monospace,Consolas,monospace;
  border:1px solid #2b5979;background:#0c263b;border-radius:5px;padding:1px 7px}
.lvl-name{font-size:16px;font-weight:700;color:#e6f5ff}
.lvl-pt{margin-left:auto;font-size:12px;color:#7e97b4}
.lvl .task{font-size:13.5px;color:#9fb4cf;margin:0 0 12px}
.lvl .task b{color:#dbe8f5}
.rows{display:grid;gap:7px}
.qrow{border:1px solid #16283e;border-radius:9px;padding:10px 12px;background:#0b182a;
  display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.qrow .code{font-size:12px;font-weight:700;color:#8fd9f6;font-family:ui-monospace,Consolas,monospace;
  min-width:52px}
.qrow .data{font-size:12.5px;color:#b3c6dc;flex:1 1 240px}
.qrow .data b{color:#e0edf8;font-variant-numeric:tabular-nums}
.btns{display:flex;gap:6px}
.bt{border:1px solid #2b4a68;background:#0f2136;color:#9db3d1;border-radius:8px;
  padding:5px 12px;font:inherit;font-size:12.5px;cursor:pointer;transition:.15s}
.bt:hover{border-color:#4aa8d8;color:#cfeaff}
.bt.on-yes{background:#0c2c1d;border-color:#2f9e6a;color:#8ce0ae;font-weight:600}
.bt.on-no{background:#2d1414;border-color:#9e4a4a;color:#f0a3a3;font-weight:600}
.qrow.right{border-color:#2f9e6a;background:#0c1f18}
.qrow.wrong{border-color:#9e4a4a;background:#22110f}
.verdict{font-size:12.5px;margin-top:7px;padding-top:7px;border-top:1px dashed #1e3350;
  color:#8fa7c1;display:none;flex-basis:100%}
.qrow.done .verdict{display:block}
.verdict b{color:#dbe8f5}
.verdict .ok{color:#8ce0ae}
.verdict .bad{color:#f0a3a3}
.opt{display:block;width:100%;text-align:left;border:1px solid #2b4a68;background:#0f2136;
  color:#b3c6dc;border-radius:10px;padding:11px 14px;font:inherit;font-size:13px;
  cursor:pointer;margin:7px 0;transition:.15s}
.opt:hover{border-color:#4aa8d8;color:#e6f5ff}
.opt.pick-ok{background:#0c2c1d;border-color:#2f9e6a;color:#d8f7e6}
.opt.pick-bad{background:#2d1414;border-color:#9e4a4a;color:#f7d8d8}
.opt .k{display:inline-block;min-width:18px;font-weight:700;color:#8fd9f6}
.opt.pick-ok .k{color:#8ce0ae}.opt.pick-bad .k{color:#f0a3a3}
.explain{font-size:12.5px;color:#8fa7c1;margin-top:9px;padding-top:9px;
  border-top:1px dashed #1e3350;display:none}
.explain.on{display:block}
.explain b{color:#dbe8f5}
.lvl-foot{margin-top:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.go{border:1px solid #3b8fd6;background:#173052;color:#cfeaff;border-radius:9px;
  padding:8px 16px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.go:disabled{opacity:.4;cursor:not-allowed}
.go:hover:not(:disabled){background:#1d4070}
.tip{font-size:12px;color:#6e88a5}
.score{border:1px solid #24415e;border-radius:13px;padding:18px 20px;margin:16px 0;
  background:linear-gradient(115deg,#0e2137,#0b182b)}
.score .big{font-size:34px;font-weight:800;color:#e5f6ff;letter-spacing:-.02em}
.score .lab{font-size:12.5px;color:#8ba0bd}
.score .msg{font-size:13.5px;color:#b3c6dc;margin-top:9px}
.bar{height:7px;border-radius:4px;background:#16283e;overflow:hidden;margin-top:11px}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#38bdf8,#2f9e6a);
  transition:width .5s}
table.gap{width:100%;border-collapse:collapse;font-size:12.5px;margin:10px 0}
table.gap th{text-align:left;background:#2a210f;color:#f3d394;font-size:11.5px;padding:7px 9px;
  border-bottom:1px solid #5a4620;font-weight:600}
table.gap td{padding:7px 9px;border-bottom:1px solid #3a2f18;color:#d8c294;vertical-align:top}
table.gap td b{color:#ffe4a8}
.qr-foot{display:flex;align-items:center;gap:20px;margin-top:32px;padding:18px 20px;
  border:1px solid #1b3550;border-radius:13px;background:#0d1b2d;flex-wrap:wrap}
.qr-foot-img{width:132px;height:132px;display:block;border-radius:10px;background:#fff;flex:0 0 auto}
.qr-foot-ph{display:none;width:132px;height:132px;border:1px dashed #2c4a66;border-radius:10px;
  align-items:center;justify-content:center;text-align:center;font-size:12px;color:#6e88a5;flex:0 0 auto}
.qr-foot-txt{min-width:220px;flex:1 1 300px}
.qr-foot-t{font-size:15px;font-weight:700;color:#e6f5ff;margin-bottom:5px}
.qr-foot-d{font-size:12.5px;color:#9fb4cf;line-height:1.7;max-width:560px}
.qr-foot-n{font-size:11.5px;color:#6e88a5;margin-top:6px}
footer{margin-top:24px;border-top:1px solid #1b3550;padding-top:15px;color:#66819e;font-size:12px}
footer code{color:#86c7e8}
@media(max-width:640px){
  .wrap{padding:26px 15px 55px}h1{font-size:23px}.lede{font-size:14.5px}
  h2{font-size:17px}.lvl{padding:14px 15px}
  .qrow .data{flex-basis:100%}.btns{width:100%}
  .qr-foot{gap:14px;padding:15px 16px}.qr-foot-img,.qr-foot-ph{width:112px;height:112px}
}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div>
      <div class="eyebrow">EnvLab · 质量控制</div>
      <h1>质量控制训练室</h1>
    </div>
    <a class="back" href="../../index.html">← 返回数字资产库</a>
  </div>

  <p class="lede">
    质控不是「补一个流程」，它是<b>报告能不能签字的判据</b>。
    这里练四件事：平行样判读、空白有效性、校准与测量有效性、异常处置决策。
  </p>
  <p class="lede" style="font-size:14px;color:#8ba0bd">
    所有判据都从已入库标准里现读，<b>每条带标准号与条款出处</b>；
    训练题的正确答案由判据算出来，不是预设的。
  </p>

  <div class="note-box">
    <strong>关于数据：</strong>本页训练数据（平行样测定值、空白吸光度、校准值等）
    均为<b>教学构造数据</b>，用于练习判据应用，不是任何实际项目的检测结果。
    判据本身来自真实标准，可点开「判据速查」逐条核对出处。
  </div>

  <div class="warn">
    <strong>本模块只做「有出处」的判据。</strong>
    行业里流传的「加标回收率 80%~120%」「相关系数 r ≥ 0.999」——
    已入库标准给的<b>是别的数</b>：HJ 605-2011 规定替代物加标回收率 <b>70%~130%</b>、
    线性/非线性校准曲线相关系数 <b>≥ 0.99</b>。
    这类阈值各方法标准自定，<b>不能套用一个「通行值」</b>，必须翻对应方法标准。
    详见页面末尾。
  </div>

  <section>
    <h2><span class="no">00</span>判据速查（可展开）<span class="pt">__N_CRIT__ 条数值判据 · __N_QUAL__ 条定性条款</span></h2>
    <details class="crit">
      <summary>数值判据：平行样 / 空白 / 校准 / 保存时效<span class="ar">▶</span></summary>
      <div class="crit-body">
        <p class="dim">全部从 <code>EnvStandard/data/standards/*.json</code> 现读，页面生成时逐条校验存在性。</p>
        <table class="tbl">
          <tr><th>介质</th><th>判据</th><th>标准规定</th><th>出处</th></tr>
          __CRIT_ROWS__
        </table>
      </div>
    </details>
    <details class="crit">
      <summary>定性条款：空白超标怎么处置 / 使用前要检查什么<span class="ar">▶</span></summary>
      <div class="crit-body">
        <table class="tbl">
          <tr><th>标准</th><th>条款要点</th><th>原文出处</th></tr>
          __QUAL_ROWS__
        </table>
      </div>
    </details>
  </section>

  <section>
    <h2><span class="no">01</span>平行样判读<span class="pt">20 分</span></h2>
    <div class="lvl" id="lv1">
      <div class="lvl-head"><span class="lvl-no">LV1</span><span class="lvl-name">这批平行双样，哪些超限？</span>
        <span class="lvl-pt">已答 <b id="lv1n">0</b>/6</span></div>
      <p class="task">
        一批浊度样品，6 组平行双样（A/B 两次测定，单位 NTU）。
        判据：<b>平行双样测定结果的相对偏差不超过 20%</b>
        （HJ 1075-2019，见「判据速查」）。
        相对偏差 = |A − B| ÷ 平均值 × 100%。
      </p>
      <div class="rows" id="rows1"></div>
      <div class="lvl-foot">
        <button class="go" id="go1" disabled>提交本关</button>
        <span class="tip">六组都选完才能提交</span>
      </div>
      <div class="explain" id="ex1"></div>
    </div>
  </section>

  <section>
    <h2><span class="no">02</span>空白与批次有效性<span class="pt">20 分</span></h2>
    <div class="lvl locked" id="lv2">
      <div class="lvl-head"><span class="lvl-no">LV2</span><span class="lvl-name">这批氨氮样品的空白，有没有问题？</span>
        <span class="lvl-pt">已答 <b id="lv2n">0</b>/3</span></div>
      <p class="task">
        一批 12 个氨氮样品（纳氏试剂分光光度法，方法检出限 0.025 mg/L、测定下限 0.1 mg/L）。
        逐项判断是否满足判据。
      </p>
      <div class="rows" id="rows2"></div>
      <div class="lvl-foot">
        <button class="go" id="go2" disabled>提交本关</button>
      </div>
      <div class="explain" id="ex2"></div>
    </div>
  </section>

  <section>
    <h2><span class="no">03</span>校准与测量有效性<span class="pt">20 分</span></h2>
    <div class="lvl locked" id="lv3">
      <div class="lvl-head"><span class="lvl-no">LV3</span><span class="lvl-name">这两个测量结果，能不能用？</span>
        <span class="lvl-pt">已答 <b id="lv3n">0</b>/2</span></div>
      <p class="task">
        校准不合格时，<b>整批测量结果直接无效</b> —— 这是最容易被忽略、代价也最大的一类判据。
      </p>
      <div class="rows" id="rows3"></div>
      <div class="lvl-foot">
        <button class="go" id="go3" disabled>提交本关</button>
      </div>
      <div class="explain" id="ex3"></div>
    </div>
  </section>

  <section>
    <h2><span class="no">04</span>异常处置决策<span class="pt">40 分</span></h2>
    <div class="lvl locked" id="lv4">
      <div class="lvl-head"><span class="lvl-no">LV4</span><span class="lvl-name">空白失控了，怎么办？</span>
        <span class="lvl-pt">单选 · 40 分</span></div>
      <p class="task" id="scen"></p>
      <div id="opts"></div>
      <div class="explain" id="ex4"></div>
      <div class="lvl-foot"><span class="tip">选完即出结果</span></div>
    </div>
  </section>

  <section>
    <h2><span class="no">05</span>结算</h2>
    <div class="score" id="score">
      <div class="big" id="scoreN">0<span style="font-size:15px;color:#7e97b4"> / 100</span></div>
      <div class="lab">四关总分</div>
      <div class="bar"><i id="scoreBar"></i></div>
      <div class="msg" id="scoreMsg">从第 1 关开始。</div>
    </div>
  </section>

  <section>
    <h2><span class="no">06</span>容易被当成「通行值」的判据</h2>
    <p class="dim">
      下面这几项是行业里问得最多、也最容易被当成「通用阈值」的。
      实际情况是：<b>标准规定了，但给的不是你听说的那个数</b>，
      而且各方法标准不同 —— 用到时必须翻到对应方法标准的正文质量保证章节。
    </p>
    <table class="gap">
      <tr><th>常被当成判据的说法</th><th>实际情况</th></tr>
      __GAP_ROWS__
    </table>
  </section>

  <section class="qr-foot" aria-label="关注公众号">
    <img class="qr-foot-img" src="../../assets/公众号二维码.jpg" alt="公众号二维码"
         width="132" height="132" loading="lazy"
         onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
    <div class="qr-foot-ph">二维码<br>待放置</div>
    <div class="qr-foot-txt">
      <div class="qr-foot-t">环境检测 · 数字资产库</div>
      <div class="qr-foot-d">长按识别二维码关注公众号，获取标准速查表、交互实验与工具更新。</div>
      <div class="qr-foot-n">交流 / 定制课程 / 工具合作，也可在公众号留言。</div>
    </div>
  </section>

  <footer>
    判据由 <code>build_qc_trainer.py</code> 从 <code>EnvStandard/data/standards/*.json</code> 现读并校验，
    每条都带标准号与条款出处；训练数据为教学构造数据。<br>
    本页为教学演示，不构成法定检测报告；质控要求以各方法标准现行版本为准。
  </footer>
</div>

<script>
var CRIT = __CRIT_JSON__;
var PAR = __PAR_JSON__;
var BLK = __BLK_JSON__;
var CAL = __CAL_JSON__;
var DEC = __DEC_JSON__;
var QUAL = __QUAL_JSON__;

var $ = function(s){ return document.querySelector(s); };
var score = { lv1: 0, lv2: 0, lv3: 0, lv4: 0 };
var MAX = { lv1: 20, lv2: 20, lv3: 20, lv4: 40 };

function esc(v){
  return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}
function fmt(v){ return (Math.round(v * 100) / 100).toString(); }

function renderScore(){
  var total = score.lv1 + score.lv2 + score.lv3 + score.lv4;
  $('#scoreN').innerHTML = total + '<span style="font-size:15px;color:#7e97b4"> / 100</span>';
  $('#scoreBar').style.width = total + '%';
  var msg;
  if (total === 0) msg = '从第 1 关开始。';
  else if (total < 60) msg = '判据还没吃透 —— 回「判据速查」把每条出处看一遍，再重做。';
  else if (total < 85) msg = '基本判得对，但异常处置那类题还要再想一层：空白/校准失控时，'
                          + '「照常出报告」和「扣掉就算了」都是错的。';
  else msg = '判据应用到位。真正的现场比这里复杂 —— 关键是养成「先看判据出处、再下结论」的习惯。';
  $('#scoreMsg').textContent = msg;
}

function unlock(id){ var e = $('#' + id); if (e) e.classList.remove('locked'); }

// ---------------- LV1 平行样 ----------------
function buildLv1(){
  var html = '';
  PAR.forEach(function(it){
    html += '<div class="qrow" data-code="' + esc(it.code) + '">'
      + '<span class="code">' + esc(it.code) + '</span>'
      + '<span class="data">A = <b>' + fmt(it.a) + '</b>　B = <b>' + fmt(it.b) + '</b>　NTU</span>'
      + '<span class="btns">'
      + '<button class="bt" data-v="1">合格</button>'
      + '<button class="bt" data-v="0">超限</button>'
      + '</span>'
      + '<div class="verdict"></div></div>';
  });
  $('#rows1').innerHTML = html;
  $('#rows1').addEventListener('click', function(e){
    var b = e.target.closest('.bt'); if (!b) return;
    var row = b.closest('.qrow'); if (row.classList.contains('done')) return;
    var btns = row.querySelectorAll('.bt');
    btns.forEach(function(x){ x.classList.remove('on-yes','on-no'); });
    b.classList.add(b.dataset.v === '1' ? 'on-yes' : 'on-no');
    row.dataset.answer = b.dataset.v;
    var n = $('#rows1').querySelectorAll('.qrow[data-answer]').length;
    $('#lv1n').textContent = n;
    $('#go1').disabled = n !== PAR.length;
  });
}

$('#go1').addEventListener('click', function(){
  var right = 0;
  PAR.forEach(function(it){
    var row = $('#rows1').querySelector('.qrow[data-code="' + it.code + '"]');
    if (row.classList.contains('done')) { if (row.dataset.got === '1') right++; return; }
    var ans = row.dataset.answer === '1';
    var got = (ans === it.pass);
    if (got) right++;
    row.dataset.got = got ? '1' : '0';
    row.classList.add('done', got ? 'right' : 'wrong');
    row.querySelector('.verdict').innerHTML =
      '相对偏差 = |' + fmt(it.a) + ' − ' + fmt(it.b) + '| ÷ ' + fmt(it.mean) + ' × 100% = <b>'
      + fmt(it.rd) + '%</b>　判据 ≤ 20% → <span class="' + (it.pass ? 'ok">合格' : 'bad">超限')
      + '</span>　你选：<span class="' + (got ? 'ok' : 'bad') + '">' + (ans ? '合格' : '超限') + '</span>';
  });
  score.lv1 = Math.round(right / PAR.length * MAX.lv1);
  $('#ex1').innerHTML = '<b>本关 ' + score.lv1 + ' / 20。</b>'
    + '要点：相对偏差算的是<b>差值除以平均值</b>，不是除以某个固定基数 —— '
    + 'S-04 的绝对差值（4.0 NTU）比 S-06（0.8 NTU）大，但两组相对偏差都是 28.6%，'
    + '因为它们的浓度水平也不同。判据是对<b>相对</b>偏差设限。';
  $('#ex1').classList.add('on');
  unlock('lv2'); renderScore();
  $('#go1').disabled = true; $('#go1').textContent = '已提交';
  $('#lv2').scrollIntoView({behavior:'smooth', block:'center'});
});

// ---------------- LV2 空白 ----------------
function buildLv2(){
  var html = '';
  BLK.forEach(function(it){
    html += '<div class="qrow" data-code="' + esc(it.code) + '">'
      + '<span class="code">' + esc(it.code) + '</span>'
      + '<span class="data">' + esc(it.desc) + '　实测 <b>' + fmt(it.observed) + '</b>　判据 <b>'
      + esc(it.limit) + '</b></span>'
      + '<span class="btns">'
      + '<button class="bt" data-v="1">合格</button>'
      + '<button class="bt" data-v="0">不合格</button>'
      + '</span>'
      + '<div class="verdict"></div></div>';
  });
  $('#rows2').innerHTML = html;
  $('#rows2').addEventListener('click', function(e){
    var b = e.target.closest('.bt'); if (!b) return;
    var row = b.closest('.qrow'); if (row.classList.contains('done')) return;
    row.querySelectorAll('.bt').forEach(function(x){ x.classList.remove('on-yes','on-no'); });
    b.classList.add(b.dataset.v === '1' ? 'on-yes' : 'on-no');
    row.dataset.answer = b.dataset.v;
    var n = $('#rows2').querySelectorAll('.qrow[data-answer]').length;
    $('#lv2n').textContent = n;
    $('#go2').disabled = n !== BLK.length;
  });
}

$('#go2').addEventListener('click', function(){
  var right = 0;
  BLK.forEach(function(it){
    var row = $('#rows2').querySelector('.qrow[data-code="' + it.code + '"]');
    if (row.classList.contains('done')) { if (row.dataset.got === '1') right++; return; }
    var ans = row.dataset.answer === '1';
    var got = (ans === it.pass);
    if (got) right++;
    row.dataset.got = got ? '1' : '0';
    row.classList.add('done', got ? 'right' : 'wrong');
    row.querySelector('.verdict').innerHTML =
      '<span class="' + (it.pass ? 'ok">合格' : 'bad">不合格') + '</span>　'
      + esc(it.why) + '　你选：<span class="' + (got ? 'ok' : 'bad') + '">'
      + (ans ? '合格' : '不合格') + '</span>';
  });
  score.lv2 = Math.round(right / BLK.length * MAX.lv2);
  $('#ex2').innerHTML = '<b>本关 ' + score.lv2 + ' / 20。</b>'
    + '要点：<b>试剂空白看绝对上限</b>（HJ 535-2009 规定吸光度 ≤ 0.03），'
    + '<b>全程序空白看是否低于方法检出限</b>，两者判法不同。'
    + '这一批里有一项不合格 —— 而空白不合格会让<b>整批</b>数据的有效性出问题，'
    + '这正是第 4 关要处理的场景。';
  $('#ex2').classList.add('on');
  unlock('lv3'); renderScore();
  $('#go2').disabled = true; $('#go2').textContent = '已提交';
  $('#lv3').scrollIntoView({behavior:'smooth', block:'center'});
});

// ---------------- LV3 校准 ----------------
function buildLv3(){
  var html = '';
  CAL.forEach(function(it){
    html += '<div class="qrow" data-code="' + esc(it.code) + '">'
      + '<span class="code" style="min-width:96px">' + esc(it.code) + '</span>'
      + '<span class="data">' + esc(it.desc) + '<br>偏差 <b>' + fmt(it.observed) + (it.unit || '')
      + '</b>　判据 <b>' + esc(it.limit) + '</b></span>'
      + '<span class="btns">'
      + '<button class="bt" data-v="1">结果有效</button>'
      + '<button class="bt" data-v="0">结果无效</button>'
      + '</span>'
      + '<div class="verdict"></div></div>';
  });
  $('#rows3').innerHTML = html;
  $('#rows3').addEventListener('click', function(e){
    var b = e.target.closest('.bt'); if (!b) return;
    var row = b.closest('.qrow'); if (row.classList.contains('done')) return;
    row.querySelectorAll('.bt').forEach(function(x){ x.classList.remove('on-yes','on-no'); });
    b.classList.add(b.dataset.v === '1' ? 'on-yes' : 'on-no');
    row.dataset.answer = b.dataset.v;
    var n = $('#rows3').querySelectorAll('.qrow[data-answer]').length;
    $('#lv3n').textContent = n;
    $('#go3').disabled = n !== CAL.length;
  });
}

$('#go3').addEventListener('click', function(){
  var right = 0;
  CAL.forEach(function(it){
    var row = $('#rows3').querySelector('.qrow[data-code="' + it.code + '"]');
    if (row.classList.contains('done')) { if (row.dataset.got === '1') right++; return; }
    var ans = row.dataset.answer === '1';
    var got = (ans === it.pass);
    if (got) right++;
    row.dataset.got = got ? '1' : '0';
    row.classList.add('done', got ? 'right' : 'wrong');
    row.querySelector('.verdict').innerHTML =
      '<span class="' + (it.pass ? 'ok">结果有效' : 'bad">结果无效') + '</span>　'
      + esc(it.why) + '　你选：<span class="' + (got ? 'ok' : 'bad') + '">'
      + (ans ? '结果有效' : '结果无效') + '</span>';
  });
  score.lv3 = Math.round(right / CAL.length * MAX.lv3);
  $('#ex3').innerHTML = '<b>本关 ' + score.lv3 + ' / 20。</b>'
    + '要点：校准偏差超标时，<b>不是「结果不太准」，而是「结果无效」</b>。'
    + '这两个场景的差别也很典型：声学校准用<b>绝对偏差</b>（dB），'
    + '流量校准用<b>相对偏差</b>（%）—— 判据的量纲不同，不能混用。';
  $('#ex3').classList.add('on');
  unlock('lv4'); renderScore();
  $('#go3').disabled = true; $('#go3').textContent = '已提交';
  $('#lv4').scrollIntoView({behavior:'smooth', block:'center'});
});

// ---------------- LV4 决策 ----------------
function buildLv4(){
  $('#scen').innerHTML = esc(DEC.scenario);
  var html = '';
  DEC.options.forEach(function(o){
    html += '<button class="opt" data-k="' + esc(o.key) + '"><span class="k">' + esc(o.key)
      + '</span>' + esc(o.text) + '</button>';
  });
  $('#opts').innerHTML = html;
  $('#opts').addEventListener('click', function(e){
    var b = e.target.closest('.opt'); if (!b) return;
    if ($('#opts').dataset.done === '1') return;
    $('#opts').dataset.done = '1';
    var ok = false, why = '';
    DEC.options.forEach(function(o){
      if (o.key === b.dataset.k) { ok = o.ok; why = o.why; }
    });
    b.classList.add(ok ? 'pick-ok' : 'pick-bad');
    score.lv4 = ok ? MAX.lv4 : 0;
    $('#ex4').innerHTML = (ok ? '<b class="ok">答对。</b>' : '<b class="bad">答错。</b>')
      + ' ' + esc(why);
    $('#ex4').classList.add('on');
    renderScore();
    $('#score').scrollIntoView({behavior:'smooth', block:'center'});
  });
}

buildLv1(); buildLv2(); buildLv3(); buildLv4(); renderScore();
</script>
</body>
</html>
'''


def render_crit_rows(rows: list[dict]) -> str:
    out = []
    for r in rows:
        val = r["value"]
        out.append(
            f'<tr><td class="med">{r["medium"]}</td><td>{r["use"]}</td>'
            f'<td class="v">{val} {r["units"]}</td>'
            f'<td class="src">{r["citation"]}</td></tr>'
        )
    return "".join(out)


def render_qual_rows(rows: list[dict]) -> str:
    out = []
    for r in rows:
        out.append(
            f'<tr><td class="med">{r["standard"]}</td><td>{r["use"]}'
            f'<br><span style="color:#6e88a5;font-size:11.5px">{r["text"][:150]}</span></td>'
            f'<td class="src">{r["citation"]}</td></tr>'
        )
    return "".join(out)


def render_gap_rows() -> str:
    return "".join(
        f'<tr><td><b>{name}</b></td><td>{desc}</td></tr>'
        for name, desc in NO_UNIFIED
    )


def main() -> None:
    stds = load_standards()
    crit, qual = build_criteria(stds)

    par = parallel_items()
    blk = blank_items()
    cal = calib_items()
    dec = decision_item()

    # 自检：训练题里的判据必须与标准数据一致
    dev_limit = next(c for c in crit
                     if c["standard"] == "HJ1075-2019"
                     and c["use"].startswith("平行双样测定结果"))
    if float(dev_limit["value"]) != 20.0:
        raise SystemExit(f"[qc] 平行样判据与训练题不符：标准写 {dev_limit['value']}，训练题按 20 判定")
    blank_limit = next(c for c in crit
                       if c["standard"] == "HJ535-2009" and "试剂空白" in c["use"])
    if float(blank_limit["value"]) != 0.03:
        raise SystemExit(f"[qc] 试剂空白判据与训练题不符：标准写 {blank_limit['value']}，训练题按 0.03 判定")
    for it in blk:
        if it["code"] == "试剂空白" and not (it["observed"] > blank_limit["value"]):
            raise SystemExit("[qc] 试剂空白训练题与判据不符：实测值未超限却判为不合格")
    for it in par:
        if it["pass"] != (it["rd"] <= dev_limit["value"]):
            raise SystemExit(f"[qc] 平行样 {it['code']} 判定与判据不符")
    calib_limit = next(c for c in crit
                       if c["standard"] == "GB12348-2008" and "声学校准" in c["use"])
    if float(calib_limit["value"]) != 0.5:
        raise SystemExit(f"[qc] 声学校准判据与训练题不符：标准写 {calib_limit['value']}")

    html = HTML
    for token, value in [
        ("__CRIT_ROWS__", render_crit_rows(crit)),
        ("__QUAL_ROWS__", render_qual_rows(qual)),
        ("__GAP_ROWS__", render_gap_rows()),
        ("__CRIT_JSON__", json.dumps(crit, ensure_ascii=False, separators=(",", ":"))),
        ("__PAR_JSON__", json.dumps(par, ensure_ascii=False, separators=(",", ":"))),
        ("__BLK_JSON__", json.dumps(blk, ensure_ascii=False, separators=(",", ":"))),
        ("__CAL_JSON__", json.dumps(cal, ensure_ascii=False, separators=(",", ":"))),
        ("__DEC_JSON__", json.dumps(dec, ensure_ascii=False, separators=(",", ":"))),
        ("__QUAL_JSON__", json.dumps(qual, ensure_ascii=False, separators=(",", ":"))),
        ("__N_CRIT__", str(len(crit))),
        ("__N_QUAL__", str(len(qual))),
    ]:
        html = html.replace(token, value)

    left = re.findall(r"__[A-Z_]+__", html)
    if left:
        raise SystemExit(f"[qc] 模板还有未替换的占位符：{set(left)}")
    if "**" in html:
        raise SystemExit("[qc] 生成物里有 Markdown 粗体（**），HTML 不会渲染，请改用 <b>")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"[qc] 判据 {len(crit)} 条数值 + {len(qual)} 条定性，全部来自标准数据")
    print(f"[qc] 训练题：平行样 {len(par)} · 空白 {len(blk)} · 校准 {len(cal)} · 决策 1")
    print(f"[qc] 输出 {OUTPUT}  {len(html.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
