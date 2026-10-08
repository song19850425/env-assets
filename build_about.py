# -*- coding: utf-8 -*-
"""生成 about.html（关于本站 · 项目大纲）。

为什么要生成而不是手写
----------------------
这一页要塞进一堆数字：105 件资产、78 个实验、23 份标准、263 项检测因子……
手写就一定会漂 —— 首页加了页面、改了分区计数，这一页不会自己跟着变，
而它恰恰是**给人看「这个库有什么」的第一页**，数字错了比没有还糟。

所以：
  · 资产口径**从首页 index.html 的 SECS 里读**（首页是唯一口径源）
  · 同时**数一遍磁盘上的 HTML 文件数**，两边不一致就直接报错退出
  · 标准/因子/参数数字从 EnvStandard/data 现算
  · 大纲的每个环节都指向**真实存在的文件**，路径不存在就报错

跑法：python build_about.py
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
STD_DIR = ROOT / "EnvStandard" / "data" / "standards"
CATALOG = ROOT / "EnvStandard" / "data" / "catalog.json"
OUTPUT = ROOT / "about.html"

# ---------------------------------------------------------------- 产品线归属
LINES = [
    ("EnvLab", "学习", "#38bdf8", "我要学会怎么做",
     "把「看一眼就懂、说不清」的现场判断，做成能拖能点、有实时反馈的页面。",
     ["EnvLab/01-交互实验", "EnvLab/02-仪器培训", "EnvLab/03-质量控制"]),
    ("EnvWork", "干活", "#fbbf24", "我要把活干完",
     "干活时对着抄、对着填、对着查的东西：方案、核查表、SOP、脱敏案例。",
     ["EnvWork/03-工具速查", "EnvWork/04-操作规程", "EnvWork/05-案例库",
      "EnvWork/07-碳汇与碳市场"]),
    ("EnvData", "数据", "#fb923c", "我要看数据",
     "豫北四市空气质量日报 / 周报 / 月报，流水线每小时自动跑，不需要人管。",
     ["EnvData/08-大气管家"]),
]

# 交互实验的二级分组
SUBS = ["01-采样布点", "02-检测实验", "03-仪器分析", "04-环境评价",
        "05-修复技术", "06-大气污染控制", "07-环境执法",
        # 2026-10-04 新增：污泥浓缩机等水处理单元（此前塞进大气控制是错的）
        "08-水污染控制"]

# ------------------------------------------------ 第三方检测实验室的主体构架
# 口径：一家能对外出报告的 CMA 第三方环境检测实验室，从「能开张」到「出报告」
# 的完整链条。每个环节都标出库里对应哪些资产、覆盖到什么程度。
#   full = 有直接对应的资产   part = 部分覆盖 / 分散在别处   gap = 暂无
LAYERS = [
    ("A", "实验室能开张的前提", "#38bdf8"),
    ("B", "一份样品的完整旅程", "#8b5cf6"),
    ("C", "依据与延伸", "#14b8a6"),
]

LAB = [
    # ---------- A 层 ----------
    ("A", "资质认定与质量体系",
     "CMA 资质认定、CNAS 认可、内审与管理评审、不符合工作控制 —— 决定这家实验室"
     "能不能对外出报告、报告有没有法律效力。",
     [("CMA 现场核查总表（2023 版）", "EnvWork/03-工具速查/CMA-CNAS核查表/00-CMA现场核查总表（2023版）.html"),
      ("CNAS-CL01 现场核查总表", "EnvWork/03-工具速查/CMA-CNAS核查表/01-CNAS-CL01现场核查总表.html"),
      ("CMA 与 CNAS 双体系对照表", "EnvWork/03-工具速查/CMA-CNAS核查表/02-CMA与CNAS双体系对照表.html"),
      ("角色化核查清单（按岗位分）", "EnvWork/03-工具速查/CMA-CNAS核查表/03-角色化核查清单.html")],
     "full", "现场核查维度已覆盖；体系文件的编制与内审记录留白。"),

    ("A", "合同评审与业务受理",
     "客户委托进来先做合同评审：检测项目、依据标准、点位与频次、时限、费用，"
     "以及要不要分包。CMA 要求这一步留痕，不能口头答应。",
     [("第三方检测机构合规管理 · 操作规范", "EnvWork/04-操作规程/26-第三方检测机构合规管理-操作规范.html"),
      ("企业环保合规全栈服务目录", "EnvWork/04-操作规程/00-企业环保合规全栈服务目录.html")],
     "part", "有服务目录与合规规范；委托单、合同评审记录这类表单还没做成页。"),

    ("A", "人员、设备与设施",
     "谁能上机、谁能签字要授权；设备要检定校准、期间核查；环境条件要监控 —— "
     "人、机、料、法、环五项里最容易在评审现场被挑的三项。",
     [("仪器操作规程页（6 台，逐步走查）", "EnvLab/02-仪器培训/操作规程页/"),
      ("仪器分析交互页（35 台，含参数与谱图）", "EnvLab/01-交互实验/03-仪器分析/")],
     "part", "仪器侧做得很厚；人员授权表、设备台账与期间核查记录还没有对应页面。"),

    # ---------- B 层 ----------
    ("B", "监测方案设计",
     "踏勘之后定：测哪些因子、按哪个标准、布几个点、采几次、什么时段采。"
     "方案定错，后面采得再规范也是白做。",
     [("监测方案智能生成器（多类型版）", "EnvWork/03-工具速查/监测方案智能生成器.html"),
      ("检测因子实验室交互方案", "EnvWork/03-工具速查/检测因子实验室交互方案.html")],
     "full", "按土壤 / 地下水 / 废水 / 废气 / 噪声场景生成方案。"),

    ("B", "现场采样与样品运输",
     "布点、采样操作、现场记录、样品保存与运输 —— 检测结果的上限在这一步就定死了，"
     "实验室再准也救不回一个采错的样。",
     [("固定源废气采样", "EnvLab/01-交互实验/01-采样布点/固定源废气采样-交互版.html"),
      ("土壤采样布点", "EnvLab/01-交互实验/01-采样布点/土壤采样布点-交互版.html"),
      ("地下水洗井 + 采样", "EnvLab/01-交互实验/01-采样布点/地下水洗井采样-交互版.html"),
      ("地表水采样布点", "EnvLab/01-交互实验/01-采样布点/地表水采样布点-交互版.html"),
      ("环境空气 PM2.5 采样", "EnvLab/01-交互实验/01-采样布点/环境空气PM25采样-交互版.html"),
      ("采样字段模板（水/气/土/噪声）", "EnvWork/03-工具速查/采样字段模板/sampling_fields.html"),
      ("水和废水采样填表向导", "EnvWork/03-工具速查/采样字段模板/水和废水采样填表向导.html")],
     "full", "水、气、土、地下水四类介质都有可操作页面；噪声采样尚无对应页。"),

    ("B", "样品接收与流转",
     "接样验收（容器对不对、保存剂加没加、温度合不合规）、编号、储存、流转、留样与处置。"
     "样品一乱，后面所有数据都失去可追溯性。",
     [("检测因子实验室交互方案 · 接样验收流程", "EnvWork/03-工具速查/检测因子实验室交互方案.html"),
      ("实验分组任务单（可下发各实验组）", "EnvWork/03-工具速查/实验分组任务单（可下发各实验组）.html")],
     "part", "有接样验收流程与分组任务单；样品编号规则、留样台账还是空白。"),

    ("B", "前处理与仪器分析",
     "消解、萃取、吹扫捕集、浓缩定容，再上机：AAS / ICP-MS / ICP-OES / GC-MS / "
     "LC-MS / HPLC / 离子色谱 / 分光光度……这是实验室投入最重的一段。",
     [("检测实验（12 个完整流程）", "EnvLab/01-交互实验/02-检测实验/"),
      ("仪器分析交互页（35 台）", "EnvLab/01-交互实验/03-仪器分析/"),
      ("仪器培训规程（6 台，逐步走查）", "EnvLab/02-仪器培训/操作规程页/"),
      ("气相色谱方法开发速查表", "EnvWork/03-工具速查/气相色谱方法开发速查表.html")],
     "full", "库里最厚的一段：从样品到结果的操作序列都能点。"),

    ("B", "质量控制",
     "空白、平行样、加标回收、标准曲线、质控样、能力验证、期间核查 —— "
     "质控不是「补一个流程」，它是报告能不能签字的判据。",
     [("质量控制训练室（四关训练：平行样 / 空白 / 校准 / 异常处置）", "EnvLab/03-质量控制/质量控制训练室.html"),
      ("检测实验页内的质控环节（空白/平行/加标）", "EnvLab/01-交互实验/02-检测实验/水质四项-COD氨氮总磷总氮实验.html"),
      ("检测因子实验室交互方案 · 质控审核段", "EnvWork/03-工具速查/检测因子实验室交互方案.html"),
      ("CMA 现场核查总表 · 质控条目", "EnvWork/03-工具速查/CMA-CNAS核查表/00-CMA现场核查总表（2023版）.html")],
     "part", "已有独立的质控判读与异常处置训练（判据逐条带标准出处）；"
             "能力验证、期间核查、质控图仍是空白，"
             "加标回收率限值与相关系数 r 因标准未给统一规定，模块内明确标为「无统一阈值」而不编造。"),

    ("B", "数据处理与报告",
     "计算、修约、三级审核、报告编制、签发与归档。数字算对了但报告写错，"
     "前面的功夫一样归零。",
     [("COD 检测实验 · 从水样到报告", "EnvLab/01-交互实验/02-检测实验/COD检测实验-从水样到报告.html"),
      ("检测因子实验室交互方案 · 报告出口", "EnvWork/03-工具速查/检测因子实验室交互方案.html")],
     "part", "有一条从样品走到报告的完整样例；报告模板与审核流尚未成页。"),

    # ---------- C 层 ----------
    ("C", "标准与方法依据",
     "限值、方法、检出限、采样要求都来自标准。数字抄错一位，结论就可能反过来 —— "
     "所以这一层的关键不是「收录多少」，而是<b>每一条能不能追到出处</b>。",
     [("EnvStandard 标准库（__N_STD__ 份标准）", "EnvStandard/index.html")],
     "full", "__N_LIMITS__ 项检测因子 + __N_VALUES__ 项规定参数，逐条带标准号与条款/表格位置。"),

    ("C", "区域数据服务（延伸）",
     "不针对单个委托，而是持续看一个区域的空气质量 —— 由流水线自动跑，"
     "把「数据获取」这件事本身自动化。",
     [("大气管家 · 豫北四市日报/周报/月报", "EnvData/08-大气管家/豫北每日一页纸/index.html")],
     "full", "数据源为中国环境监测总站实时发布平台，每小时自动更新。"),
]

COVER = {
    "full": ("已覆盖", "cov-full"),
    "part": ("部分覆盖", "cov-part"),
    "gap": ("暂无", "cov-gap"),
}


# ------------------------------------------------------------------ 口径收集
def read_secs() -> list[dict]:
    """从首页读资产口径。首页是唯一源，这一页不另立一套数字。"""
    text = io.open(INDEX, encoding="utf-8").read()
    m = re.search(r"var SECS = (\[.*?\]);", text, re.S)
    if not m:
        raise SystemExit("[about] 没能从 index.html 里读到 SECS，口径源变了？")
    return json.loads(m.group(1))


def count_html(rel: str) -> int:
    p = ROOT / rel
    if not p.is_dir():
        raise SystemExit(f"[about] 目录不存在：{rel}")
    return sum(1 for _ in p.rglob("*.html"))


def collect() -> dict:
    secs = read_secs()
    by_key = {s["key"]: s for s in secs}

    sections, mismatches = [], []
    for line, tag, color, question, blurb, keys in LINES:
        rows = []
        for key in keys:
            if key not in by_key:
                raise SystemExit(f"[about] 首页 SECS 里没有 {key}，与这里的产品线定义不一致")
            declared = by_key[key]["count"]
            in_total = by_key[key].get("includeInTotal", True)
            # 不计入总数的分区（大气管家是流水线产物）不参与件数核对：
            # 首页给它的 count 只是占位，真正展示的是 countLabel「自动更新」。
            if in_total and declared != count_html(key):
                mismatches.append((key, declared, count_html(key)))
            rows.append({
                "key": key, "path": key, "title": by_key[key]["title"],
                "count": declared, "includeInTotal": in_total,
                "countLabel": by_key[key].get("countLabel"),
            })
        sections.append({
            "line": line, "tag": tag, "color": color, "question": question,
            "blurb": blurb, "rows": rows,
            "total": sum(r["count"] for r in rows if r["includeInTotal"]),
        })

    if mismatches:
        print("[about] ★ 首页声明数与磁盘文件数不一致：")
        for key, declared, actual in mismatches:
            print(f"         {key}: 首页写 {declared}，磁盘实有 {actual}")
        raise SystemExit("[about] 请先统一口径再生成")

    total_assets = sum(s["total"] for s in sections)
    footer = re.search(r"共 <b>(\d+)</b> 件可交互资产",
                       io.open(INDEX, encoding="utf-8").read())
    if footer and int(footer.group(1)) != total_assets:
        raise SystemExit(f"[about] 首页页脚写 {footer.group(1)} 件，"
                         f"按分区加总为 {total_assets} 件，不一致")

    # ---- EnvStandard 口径 ----
    std_files = sorted(p for p in STD_DIR.glob("*.json")
                       if p.name not in {"index.json", "pollutant-ids.json"})
    n_limits = n_values = n_qual = 0
    for p in std_files:
        d = json.loads(p.read_text(encoding="utf-8"))
        n_limits += len(d.get("limits", []))
        n_values += len(d.get("values", {}))
        n_qual += len(d.get("qualitative", []))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    data = {
        "sections": sections,
        "total_assets": total_assets,
        "envlab": next(s for s in sections if s["line"] == "EnvLab")["total"],
        "envwork": next(s for s in sections if s["line"] == "EnvWork")["total"],
        "n_standards": len(std_files),
        "n_limits": n_limits,
        "n_values": n_values,
        "n_qual": n_qual,
        "n_methods": len(catalog.get("methods", [])),
        "n_chains": len(catalog.get("chains", [])),
        "n_sampling": len(catalog.get("sampling", [])),
        "subs": [{"dir": d, "count": count_html(f"EnvLab/01-交互实验/{d}")} for d in SUBS],
        "lab": LAB,
    }
    check_lab(data)
    return data


def check_lab(data: dict) -> None:
    """大纲里每个环节引用的路径必须真实存在 —— 否则就是画了一张空地图。"""
    bad = []
    for layer, name, what, assets, cov, note in data["lab"]:
        if cov not in COVER:
            raise SystemExit(f"[about] 未知的覆盖度标记：{cov}（{name}）")
        for label, path in assets:
            p = ROOT / path
            if not p.exists():
                bad.append(f"{name} → {path}")
    if bad:
        print("[about] ★ 大纲引用了不存在的路径：")
        for b in bad:
            print("        ", b)
        raise SystemExit("[about] 大纲必须指向真实文件")


# ------------------------------------------------------------------ 渲染
HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>关于本站 · 项目大纲 · 环境检测数字资产库</title>
<meta name="description" content="环境检测数字资产库的定位、缘起与完整大纲：按第三方检测实验室的主体构架（资质体系 / 方案设计 / 现场采样 / 样品流转 / 前处理与仪器分析 / 质量控制 / 报告 / 标准依据）逐环节对照 __N_TOTAL__ 件资产。">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<style>
*{box-sizing:border-box}
:root{color-scheme:dark}
body{margin:0;background:#0b1220;color:#e6edf7;
  font-family:"Noto Sans SC","Microsoft YaHei",-apple-system,sans-serif;line-height:1.75}
a{color:#7dd3fc;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1020px;margin:0 auto;padding:40px 22px 70px}
.eyebrow{font-size:12px;letter-spacing:.14em;color:#69c5f0;text-transform:uppercase;font-weight:700}
h1{font-size:31px;line-height:1.3;margin:6px 0 10px}
.lede{font-size:16px;color:#a9bcd8;margin:0 0 6px;max-width:780px}
.lede b{color:#e6f5ff}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:6px}
.back{display:inline-flex;align-items:center;gap:6px;border:1px solid #23375a;border-radius:9px;
  padding:7px 13px;font-size:12.5px;color:#9db3d1;background:#0f1a2e;white-space:nowrap}
.back:hover{border-color:#4aa8d8;color:#cfeaff;text-decoration:none}
.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:24px 0 6px}
.fact{border:1px solid #1b3550;background:#0d1b2d;border-radius:12px;padding:13px 15px}
.fact-n{font-size:25px;font-weight:800;color:#e5f6ff;letter-spacing:-.01em}
.fact-l{font-size:11.5px;color:#7893b1;margin-top:1px}
section{margin:40px 0 0}
h2{font-size:20px;margin:0 0 10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h2 .no{font-size:12px;font-weight:700;color:#69c5f0;border:1px solid #2b5979;background:#0c263b;
  border-radius:6px;padding:2px 8px;letter-spacing:.06em}
h3{font-size:15px;margin:22px 0 8px;color:#dcedfb}
p{margin:0 0 12px;color:#b3c6dc}
p.dim{color:#8ba0bd;font-size:13.5px}
ul{margin:0 0 12px;padding-left:20px;color:#b3c6dc}
li{margin:5px 0}
.card{border:1px solid #1b3550;background:#0d1b2d;border-radius:13px;padding:18px 20px;margin:14px 0}
.tagline{display:inline-block;font-size:11px;letter-spacing:.1em;font-weight:700;border-radius:6px;
  padding:3px 9px;background:rgba(56,189,248,.12);color:var(--pc,#38bdf8);margin-bottom:7px}
.card h3{margin-top:0;font-size:16px;color:#e6f5ff}
.card .q{font-size:13px;color:#67d2ef;font-weight:600;margin-bottom:5px}
.card .blurb{font-size:13.5px;color:#9fb4cf;margin:0 0 12px}
.rows{display:grid;gap:6px}
.row{display:flex;align-items:baseline;gap:10px;font-size:13px;
  border-top:1px solid #16283e;padding-top:6px;flex-wrap:wrap}
.row .nm{color:#dbe8f5;font-weight:600}
.row .nm a{color:#dbe8f5}
.row .nm a:hover{color:#7dd3fc}
.row .pth{font-size:11px;color:#5f7a9e;font-family:ui-monospace,Consolas,monospace}
.row .ct{margin-left:auto;font-size:12px;color:#8ba0bd;white-space:nowrap}

/* ---- 实验室主体构架 ---- */
.layer{display:flex;align-items:center;gap:10px;margin:26px 0 10px;flex-wrap:wrap}
.layer-b{display:inline-block;font-size:10px;letter-spacing:.14em;font-weight:700;
  border-radius:6px;padding:3px 9px;background:rgba(56,189,248,.12);color:var(--lc,#38bdf8)}
.layer-t{font-size:15px;font-weight:700;color:#e6f5ff}
.layer-n{font-size:11.5px;color:#5f7a9e}
.stage{border:1px solid #1b3550;background:#0d1b2d;border-radius:13px;
  padding:16px 18px;margin:10px 0;border-left:3px solid var(--sc,#2b5979)}
.stage-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.stage-no{font-size:11px;font-weight:700;color:#69c5f0;font-family:ui-monospace,Consolas,monospace;
  border:1px solid #2b5979;background:#0c263b;border-radius:5px;padding:1px 7px}
.stage-name{font-size:16px;font-weight:700;color:#e6f5ff}
.cov{margin-left:auto;font-size:11.5px;border-radius:999px;padding:2px 10px;white-space:nowrap;
  border:1px solid #2d5873;color:#8ed9fa;background:#0c2a40}
.cov-full{border-color:#2c6649;color:#8ce0ae;background:#0c2c1d}
.cov-part{border-color:#745b2b;color:#ffd47b;background:#33250f}
.cov-gap{border-color:#5d3a3a;color:#f0a3a3;background:#2d1414}
.stage .what{font-size:13.5px;color:#9fb4cf;margin:0 0 11px}
.assets{display:grid;gap:5px;margin-bottom:9px}
.asset{display:flex;align-items:baseline;gap:8px;font-size:13px;
  border-top:1px solid #16283e;padding-top:5px;flex-wrap:wrap}
.asset a{color:#cfe2ff}
.asset a:hover{color:#7dd3fc}
.asset .arw{color:#4d6a8f;font-size:11px}
.stage .note{font-size:12.5px;color:#7e97b4;margin:0;padding-top:8px;border-top:1px dashed #1e3350}
.stage .note.gap{color:#d8a86a}

.tree{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:2;
  background:#08131f;border:1px solid #16283e;border-radius:11px;padding:15px 17px;overflow-x:auto;margin:14px 0}
.tree a{color:#a9bcd8}.tree a:hover{color:#7dd3fc}
.tree .l1{color:#e6f5ff;font-weight:700}
.tree .l2{color:#9db3d1}
.tree .n{color:#5f7a9e}
.tree .cm{color:#4d6a8f}
.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}
.mini{border:1px solid #1b3550;background:#0d1b2d;border-radius:11px;padding:14px 16px}
.mini h4{margin:0 0 5px;font-size:14px;color:#dcedfb}
.mini p{margin:0;font-size:13px;color:#8fa7c1}
.warn{border-left:3px solid #d69b38;background:#2a210f;border-radius:0 10px 10px 0;
  padding:12px 15px;color:#f3d394;font-size:13px;margin:14px 0}
.warn strong{color:#ffe4a8}
.ok{border-left:3px solid #2f9e6a;background:#0c2a1d;border-radius:0 10px 10px 0;
  padding:12px 15px;color:#a9e6c4;font-size:13px;margin:14px 0}
.ok strong{color:#d8f7e6}
table{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}
th{text-align:left;background:#122b43;color:#9dd9f4;font-size:12px;padding:8px 10px;
  border-bottom:1px solid #27516d;font-weight:600}
td{padding:8px 10px;border-bottom:1px solid #16283e;color:#b3c6dc;vertical-align:top}
tr:hover td{background:#10243a}
td b{color:#e0edf8}
.qr-foot{display:flex;align-items:center;gap:20px;margin-top:34px;padding:18px 20px;
  border:1px solid #1b3550;border-radius:13px;background:#0d1b2d;flex-wrap:wrap}
.qr-foot-img{width:132px;height:132px;display:block;border-radius:10px;background:#fff;flex:0 0 auto}
.qr-foot-ph{display:none;width:132px;height:132px;border:1px dashed #2c4a66;border-radius:10px;
  align-items:center;justify-content:center;text-align:center;font-size:12px;color:#6e88a5;flex:0 0 auto}
.qr-foot-txt{min-width:220px;flex:1 1 300px}
.qr-foot-t{font-size:15px;font-weight:700;color:#e6f5ff;margin-bottom:5px}
.qr-foot-d{font-size:12.5px;color:#9fb4cf;line-height:1.7;max-width:560px}
.qr-foot-n{font-size:11.5px;color:#6e88a5;margin-top:6px}
footer{margin-top:26px;border-top:1px solid #1b3550;padding-top:16px;color:#66819e;font-size:12px}
footer code{color:#86c7e8}
@media(max-width:820px){.facts{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
@media(max-width:640px){
  .wrap{padding:28px 15px 55px}h1{font-size:24px}.lede{font-size:15px}
  h2{font-size:18px}.card,.stage{padding:15px 16px}
  .cov{margin-left:0}.qr-foot{gap:14px;padding:15px 16px}
  .qr-foot-img,.qr-foot-ph{width:112px;height:112px}
}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div>
      <div class="eyebrow">About / 关于本站 · 项目大纲</div>
      <h1>这个库是做什么的，为什么要做它，以及它按什么构架组织</h1>
    </div>
    <a class="back" href="index.html">← 返回数字资产库</a>
  </div>

  <p class="lede">
    这是一个<b>环境检测与环保咨询方向的数字资产库</b>：
    把实验室和现场里「看一眼就懂、却说不清」的东西，做成<b>能点开就用的网页</b>。
  </p>
  <p class="lede" style="font-size:14.5px;color:#8ba0bd">
    不是 PPT，不是概念稿 —— 每件都能在浏览器里直接操作。全库纯静态单文件 HTML，
    无构建步骤、无外部依赖，拷走就能用，断网也能跑。
  </p>

  <div class="facts">
    <div class="fact"><div class="fact-n">__N_TOTAL__</div><div class="fact-l">件可交互资产</div></div>
    <div class="fact"><div class="fact-n">__N_STD__</div><div class="fact-l">份结构化标准</div></div>
    <div class="fact"><div class="fact-n">11</div><div class="fact-l">个实验室环节</div></div>
    <div class="fact"><div class="fact-n">0</div><div class="fact-l">外部依赖 / CDN</div></div>
  </div>

  <section>
    <h2><span class="no">01</span>这个仓库是做什么的</h2>
    <p>
      一句话：<b>它是环境检测这个行当的「可操作版说明书」。</b>
      不是把标准、规程、案例抄一遍放到网上，而是把那些真正需要动手判断的环节，
      做成能拖、能点、能看实时反馈的页面。
    </p>
    <p>按「你要干什么」分，库里放三类东西：</p>
    <table>
      <tr><th>你要干什么</th><th>去哪个产品线</th><th>里面是什么</th></tr>
      <tr><td><b>我要学会怎么做</b></td><td>EnvLab</td>
          <td>__N_ENVLAB__ 件交互式实验与仪器操作培训，在浏览器里走一遍完整流程</td></tr>
      <tr><td><b>我要把活干完</b></td><td>EnvWork</td>
          <td>__N_ENVWORK__ 件工具、速查表、作业规范、脱敏案例与文档结构模板</td></tr>
      <tr><td><b>我要查标准</b></td><td>EnvStandard</td>
          <td>__N_STD__ 份标准的结构化索引：__N_LIMITS__ 项检测因子、__N_VALUES__ 项规定参数，逐条带出处</td></tr>
      <tr><td><b>我要看数据</b></td><td>EnvData</td>
          <td>豫北四市空气质量日报 / 周报 / 月报，流水线每小时自动生成</td></tr>
    </table>
    <p class="dim">
      注意 EnvData 与另外三条不同：那 __N_TOTAL__ 件是<b>手工做的资产</b>，
      大气管家是<b>自动流水线的产物</b>，所以不并进「件数」里，单独标注「自动更新」。
    </p>
  </section>

  <section>
    <h2><span class="no">02</span>为什么要开这个仓库</h2>

    <h3>起点：那些「看一眼就懂、说不清」的东西</h3>
    <p>
      干了十几年环境检测和环保咨询，最常遇到的一类知识是这样的 ——
      滴定终点什么时候到、空白为什么会漂、穿透曲线哪个点开始拐、
      风量虚标在现场长什么样。老师傅看一眼就知道，但要说清楚，
      得配着手势讲半小时，讲完对方还是一脸茫然。
    </p>
    <p>
      问题在于<b>载体不对</b>。这类知识写在纸上永远是死的：文字描述不了「手感」，
      照片拍不出「过程」，视频只能看不能操作。而它本来就是一个
      <b>「调一下参数 → 看结果怎么变」</b>的东西 —— 那它就该是个能操作的网页。
    </p>

    <h3>于是有四件具体的事想解决</h3>
    <div class="split">
      <div class="mini"><h4>① 带教成本太高</h4>
        <p>同一个实验，新人来一批就要从头讲一遍。做成能自己点、自己试错的页面，重复劳动才降得下来。</p></div>
      <div class="mini"><h4>② 经验留不住</h4>
        <p>会的人走了，判断标准也跟着走。写进页面的参数、判据和流程，才算是留在了机构里。</p></div>
      <div class="mini"><h4>③ 标准数字抄来抄去</h4>
        <p>行业里到处是转手好几遍的限值和条款号。差一位数，结论就反过来 —— 而没人能说清它是从哪抄的。</p></div>
      <div class="mini"><h4>④ 演示工具本身不靠谱</h4>
        <p>很多演示页要装环境、要连 CDN、要联网。到了现场、教室或断网的机房里，直接用不了。</p></div>
    </div>

    <h3>所以定下了三条底线</h3>
    <div class="ok"><strong>单文件、零外部依赖、断网可用。</strong>
      每件资产都是一个 HTML 文件，不引 CDN、不引外部字体、不需要构建步骤。
      拷到 U 盘里、发给学员、扔进内网，都能直接打开。</div>
    <div class="ok"><strong>标准引用必须能溯源。</strong>
      页面上出现的法规数值都要标出标准号与条款/表格位置；EnvStandard 进一步把标准做成
      结构化数据，让「标准 → 方法 → 实验 → 仪器 → SOP → 报告」这条链可以逐段追溯。</div>
    <div class="ok"><strong>案例与企业信息全部脱敏。</strong>
      库里的真实案例来自实际项目，但企业名称、人员、地名均已处理，
      只保留「这个坑是怎么踩的」这部分价值。</div>

    <div class="warn"><strong>它不是法定检测报告，也不替代有资质的第三方检测机构。</strong>
      这里的东西是<b>教学与工作辅助</b>用的：可以拿来练手、对着干活、核对标准出处，
      但正式出具结论、判定达标与否，仍要按现行标准和资质要求走。</div>
  </section>

  <section>
    <h2><span class="no">03</span>项目大纲：第三方检测实验室的主体构架</h2>
    <p>
      这个库不是按「文件类型」堆起来的，而是按<b>一家能对外出报告的第三方环境检测实验室
      实际怎么运转</b>组织的。下面把实验室的主体构架拆成 A / B / C 三层、共 11 个环节，
      每个环节标出库里对应哪些资产、覆盖到什么程度。
    </p>
    <p class="dim">
      覆盖度是<b>如实标注</b>的：<span class="cov cov-full">已覆盖</span>
      <span class="cov cov-part">部分覆盖</span> —— 没做到的地方会直接写出来，不装作做完了。
    </p>
    __LAB_HTML__
  </section>

  <section>
    <h2><span class="no">04</span>四条产品线</h2>
    <p class="dim">同一样东西按「谁在用、要解决什么」再看一遍。</p>
    __LINES_HTML__
  </section>

  <section>
    <h2><span class="no">05</span>全库目录大纲</h2>
    <p class="dim">点目录名可以直接进去。这张树就是仓库的实际目录结构。</p>
    __TREE_HTML__
    <p class="dim">
      另有 <b>EnvStandard/</b> 标准库（__N_STD__ 份标准 · __N_METHODS__ 条方法索引 ·
      __N_SAMPLING__ 组采样要求 · __N_CHAINS__ 条六段链路），以及本页 <b>about.html</b>。
    </p>
  </section>

  <section>
    <h2><span class="no">06</span>怎么用</h2>
    <div class="split">
      <div class="mini"><h4>只想看看</h4>
        <p>打开在线地址，首页有搜索框和分类筛选，按关键词或分区点进去。</p></div>
      <div class="mini"><h4>拿去上课</h4>
        <p>整个文件夹拷给老师或学员，断网也能跑，不用装任何环境。</p></div>
      <div class="mini"><h4>想自己改</h4>
        <p>全是单文件 HTML，没有构建步骤、没有外部依赖，记事本打开就能改。</p></div>
      <div class="mini"><h4>收藏 / 分享</h4>
        <p>发在线地址即可；单个实验页的地址也能单独分享给某个人。</p></div>
    </div>
  </section>

  <section>
    <h2><span class="no">07</span>数据与边界</h2>
    <ul>
      <li><b>脱敏</b>：库内案例、企业名称、人员信息、地名均已脱敏处理。</li>
      <li><b>标准</b>：条文与数值引用均标注出处；实际使用请以国家 / 地方发布的<b>现行有效版本</b>为准。</li>
      <li><b>大气数据</b>：数据源为中国环境监测总站实时发布平台；页面由自动化流水线生成，<b>未经人工审定</b>，仅供技术交流参考，不作为行政决策或处罚依据。</li>
      <li><b>合成数据</b>：少数演示页为教学目的使用构造数据，页面上会明确标注。</li>
      <li><b>结论</b>：本库内容不构成法定检测报告，不替代具备资质的第三方检测机构出具的结果。</li>
    </ul>
  </section>

  <section>
    <h2><span class="no">08</span>许可与联系</h2>
    <p>
      本仓库内容采用 <b>CC BY-NC-SA 4.0</b> 许可协议：
      <b>个人学习、教学、机构内部培训可自由使用</b>；
      商业使用、二次分发或集成进产品，请先联系仓库所有者取得授权。
    </p>
    <p class="dim">完整协议文本：<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.zh-hans" target="_blank" rel="noopener">creativecommons.org/licenses/by-nc-sa/4.0 ↗</a></p>
    <p>
      如果你在做检测机构、高校环境专业或环保咨询，需要定制课程、工具或作业规范，欢迎聊两句 ——
      多数资产的完整版只对同行开放。
    </p>
  </section>

  <section class="qr-foot" aria-label="关注公众号">
    <img class="qr-foot-img" src="assets/公众号二维码.jpg" alt="公众号二维码"
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
    本页数字与大纲由 <code>build_about.py</code> 生成：资产数从首页口径读、标准数从
    EnvStandard 数据现算、大纲里每条链接都校验过文件是否存在 —— 不是手写的。<br>
    页面不构成法定检测报告；标准现行性与适用性以官方发布版本为准。
  </footer>
</div>
</body>
</html>
'''


def render_lab(data: dict) -> str:
    layer_names = {k: (t, c) for k, t, c in LAYERS}
    body: list[str] = []
    counters: dict[str, int] = {}
    for layer, name, what, assets, cov, note in data["lab"]:
        if layer not in counters:
            counters[layer] = 0
            body.append(
                f'<div class="layer" style="--lc:{layer_names[layer][1]}">'
                f'<span class="layer-b">LAYER {layer}</span>'
                f'<span class="layer-t">{layer_names[layer][0]}</span>'
                f'<span class="layer-n">· {sum(1 for x in data["lab"] if x[0] == layer)} 个环节</span>'
                f'</div>'
            )
        counters[layer] += 1
        label, cls = COVER[cov]
        rows = "".join(
            f'<div class="asset"><span class="arw">▸</span>'
            f'<a href="{path}">{asset_label}</a></div>'
            for asset_label, path in assets
        )
        note_cls = "note" if cov == "full" else "note gap"
        body.append(
            f'<div class="stage" style="--sc:{layer_names[layer][1]}">'
            f'<div class="stage-head">'
            f'<span class="stage-no">{layer}{counters[layer]:02d}</span>'
            f'<span class="stage-name">{name}</span>'
            f'<span class="cov {cls}">{label}</span>'
            f'</div>'
            f'<p class="what">{what}</p>'
            f'<div class="assets">{rows}</div>'
            f'<p class="{note_cls}">{note}</p>'
            f'</div>'
        )
    return "".join(body)


def render(data: dict) -> str:
    lines_html = []
    for s in data["sections"]:
        rows = "".join(
            f'<div class="row">'
            f'<span class="nm"><a href="{r["path"]}/">{r["title"]}</a></span>'
            f'<span class="pth">{r["path"]}/</span>'
            f'<span class="ct">{r["countLabel"] if r.get("countLabel") else str(r["count"]) + " 件"}</span>'
            f'</div>'
            for r in s["rows"]
        )
        total_txt = f'{s["total"]} 件' if s["total"] else "自动更新，不计入件数"
        lines_html.append(
            f'<div class="card" style="--pc:{s["color"]}">'
            f'<span class="tagline">{s["line"]} · {s["tag"]}</span>'
            f'<div class="q">{s["question"]}</div>'
            f'<h3>{s["line"]} —— {total_txt}</h3>'
            f'<p class="blurb">{s["blurb"]}</p>'
            f'<div class="rows">{rows}</div>'
            f'</div>'
        )

    tree = ['<div class="tree">', '<span class="l1">env-assets/</span>']
    for s in data["sections"]:
        top = s["rows"][0]["path"].split("/")[0]
        tree.append(f'<br>├─ <span class="l1"><a href="{top}/">{top}/</a></span>'
                    f' <span class="cm">← {s["line"]} · {s["tag"]}</span>')
        for r in s["rows"]:
            leaf = r["path"].split("/")[-1]
            cnt = r["countLabel"] if r.get("countLabel") else f'{r["count"]} 件'
            tree.append(f'<br>│　├─ <span class="l2"><a href="{r["path"]}/">{leaf}/</a></span>'
                        f' <span class="n">{cnt}</span>')
        if s["line"] == "EnvLab":
            for sub in data["subs"]:
                tree.append(f'<br>│　│　├─ <a href="EnvLab/01-交互实验/{sub["dir"]}/">{sub["dir"]}/</a>'
                            f' <span class="n">{sub["count"]}</span>')
    tree.append(f'<br>├─ <span class="l1"><a href="EnvStandard/">EnvStandard/</a></span>'
                f' <span class="cm">← 标准库 · {data["n_standards"]} 份标准</span>')
    tree.append('<br>├─ <span class="l2"><a href="assets/favicon.svg">assets/</a></span>'
                ' <span class="n">站内资源</span>')
    tree.append('<br>├─ <span class="l2"><a href="index.html">index.html</a></span>'
                ' <span class="n">首页（搜索 + 分类）</span>')
    tree.append('<br>├─ <span class="l2"><a href="guide.html">guide.html</a></span>'
                ' <span class="n">选型指南（按机构类型挑 10 件）</span>')
    tree.append('<br>├─ <span class="l2"><a href="business.html">business.html</a></span>'
                ' <span class="n">商务合作</span>')
    tree.append('<br>└─ <span class="l2"><a href="about.html">about.html</a></span>'
                ' <span class="n">本页</span>')
    tree.append('</div>')

    out = HTML
    # ⚠ 顺序要紧：先把 HTML 片段塞进去，再替换数字。
    # 反过来做的话，片段内部（如大纲环节的说明文字）里的 __N_STD__ 就永远替不掉了。
    for token, value in [
        ("__LAB_HTML__", render_lab(data)),
        ("__LINES_HTML__", "".join(lines_html)),
        ("__TREE_HTML__", "".join(tree)),
    ]:
        out = out.replace(token, value)
    for token, value in [
        ("__N_TOTAL__", str(data["total_assets"])),
        ("__N_ENVLAB__", str(data["envlab"])),
        ("__N_ENVWORK__", str(data["envwork"])),
        ("__N_STD__", str(data["n_standards"])),
        ("__N_LIMITS__", str(data["n_limits"])),
        ("__N_VALUES__", str(data["n_values"])),
        ("__N_METHODS__", str(data["n_methods"])),
        ("__N_SAMPLING__", str(data["n_sampling"])),
        ("__N_CHAINS__", str(data["n_chains"])),
    ]:
        out = out.replace(token, value)

    left = re.findall(r"__[A-Z_]+__", out)
    if left:
        raise SystemExit(f"[about] 模板还有未替换的占位符：{set(left)}")
    # Markdown 的 **粗体** 在 HTML 里不会渲染，会原样显示成星号
    if "**" in out:
        raise SystemExit("[about] 生成物里有 Markdown 粗体标记（**），HTML 不会渲染，请改用 <b>")
    return out


def main() -> None:
    data = collect()
    html = render(data)
    OUTPUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"[about] 资产 {data['total_assets']}（EnvLab {data['envlab']} + EnvWork {data['envwork']}）"
          f" 标准 {data['n_standards']} 份 / 因子 {data['n_limits']} / 参数 {data['n_values']}")
    print(f"[about] 大纲环节 {len(data['lab'])} 个，链接全部校验通过")
    print(f"[about] 输出 {OUTPUT}  {len(html.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
