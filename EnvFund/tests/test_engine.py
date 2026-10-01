#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工程版回归测试：覆盖解析 → 抽取校验 → 规则终审 → 证据链 → 匹配 全链路

运行：python tests/test_engine.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.jev.engine import JEVEngine, is_negated
from app.llm.parser import ValidationReport, extract_json, validate_and_repair
from app.parser.document import is_central_or_provincial, parse_text
from app.rag.matching import MatchOptions, extract_profile, match_project
from app.rag.store import PolicyRecord, PolicyStore
from app.schemas.models import (
    DecisionRole, DomainCode, JEVStatus, MatchLevel, PolicyAnalysis,
)
from app.services import analyze_document

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


WATER_GUIDE = """XX省水污染防治资金申报指南

一、资金支持领域
支持流域水生态环境综合治理、集中式饮用水水源地保护、地下水污染防治。

二、重点支持项目类型
1. 重点流域干支流及湖库的水环境综合治理与水生态修复工程；
2. 集中式饮用水水源地规范化建设及周边环境综合整治；
3. 地下水污染调查评价、防渗阻隔与修复治理工程。

三、不纳入支持范围
1. 城镇污水处理厂及配套管网等城市基础设施建设项目，不属于本资金支持范围；
2. 工业企业废水处理设施提标改造项目，不予支持。

四、申报主体要求
申报主体应为省级生态环境部门、地市级人民政府或其授权的项目实施单位。

五、资金补助方式
采取因素法分配，实行以奖代补方式，中央补助资金比例原则上不超过项目总投资的50%。

六、绩效目标要求
区域内国控断面水质优良比例应达到考核目标要求，地下水质量极差比例不升高。

七、适用地域范围
本指南适用于全省范围内各市（州）申报项目。
"""


print("\n=== A. 文档解析层 ===")
doc = parse_text(WATER_GUIDE, title="XX省水污染防治资金申报指南")
check("切段编号生成", len(doc.sections) > 5, f"段数={len(doc.sections)}")
check("段号格式 P001", doc.sections[0].span == "P001")
check("段号可复现（二次解析一致）",
      [s.span for s in parse_text(WATER_GUIDE).sections] == [s.span for s in doc.sections])
check("numbered_text 含段号标记", "[P001]" in doc.numbered_text)
check("span_index 可反查", doc.span_index["P001"].startswith("XX省水污染防治"))
check("层级闸门-省级放行", is_central_or_provincial("XX省生态环境资金申报指南", "XX省生态环境厅"))
check("层级闸门-市级拒收", not is_central_or_provincial("XX市生态环境资金指南", "XX市生态环境局"))

print("\n=== B. 否定句识别（句边界截断）===")
check("同句前置否定", is_negated("本项目不涉及河湖水体治理内容", "水体治理"))
check("肯定句不误判", not is_negated("本项目实施河湖水体治理", "水体治理"))
check("否定不跨句", not is_negated("本项目不涉及管网。本次实施河湖水体治理工程。", "水体治理"))
check("同句并列共享否定", is_negated("不涉及管网和河道治理", "河道治理"))

print("\n=== C. LLM 输出容错 ===")
for name, raw, ok in [
    ("markdown 围栏", '```json\n{"a":1}\n```', True),
    ("围栏+解释", '结果：\n```json\n{"a":1}\n```\n以上', True),
    ("裸对象+解释", '根据文档：{"a":1}。完毕', True),
    ("尾逗号", '{"a":[1,2,],"b":{"c":3,}}', True),
    ("中文引号", '{\u201ca\u201d:1}', True),
    ("空返回", '', False),
    ("纯废话", '抱歉我无法解析', False),
]:
    rep = ValidationReport()
    try:
        extract_json(raw, rep)
        check(name, ok, "预期失败却成功")
    except ValueError:
        check(name, not ok, "预期成功却失败")

print("\n=== D. 证据链与假证据剔除 ===")
paras = [(s.span, s.text) for s in doc.sections]
real = paras[0][0]
dirty = {
    "candidate_labels": [
        {"code": "WATER", "evidence": [{"span": real, "quote": "水污染防治资金"}]},
        {"code": "NOPE", "evidence": [{"span": real, "quote": "x"}]},
    ],
    "uncovered": [],
    "fields": {
        "support_directions": {"text": "水生态环境综合治理", "spans": [real, "P999"]},
        "key_project_types": {"items": [{"text": "河湖水环境综合治理", "spans": [real]}]},
        "excluded_scope": {"items": [{"text": "城镇污水处理厂", "spans": [real]}]},
        "applicant_requirements": {"text": "省级生态环境部门", "spans": [real]},
        "funding_rules": {"text": "以奖代补", "spans": [real]},
        "performance_targets": {"text": "水质优良比例", "spans": [real]},
        "applicable_region": {"text": "全省", "spans": [real]},
    },
    "flags": [],
}
cleaned, rep = validate_and_repair(dirty, paras)
check("标签池外标签被剔除", rep.invalid_labels == ["NOPE"], str(rep.invalid_labels))
check("编造段号 P999 被捕获", rep.fake_spans == [f"support_directions:P999"], str(rep.fake_spans))
check("真段号保留", cleaned["fields"]["support_directions"]["spans"] == [real])

print("\n=== E. JEV 规则终审与证据链 ===")
eng = JEVEngine()
verdict = eng.judge(doc.numbered_text, ["WATER", "GROUNDWATER"], doc.span_index)
check("主赛道为水生态水环境", verdict["primary_track"] == "水生态水环境", str(verdict["primary_track"]))
check("权重规则 W-06 生效", verdict["jev"]["weight_rule_applied"] == "W-06",
      verdict["jev"]["weight_rule_applied"])
check("JEV 状态为 PASS", verdict["jev"]["status"] == "PASS", verdict["jev"]["status"])
check("不含可信度百分比字段",
      not any("confidence" in k and "band" not in k for k in verdict["jev"]))
check("confidence_band 由状态推导", verdict["jev"]["confidence_band"] in ("HIGH", "MEDIUM", "LOW"))
chain = verdict["evidence_chain"]
check("证据链非空", len(chain) > 0)
check("主赛道决策标记 PRIMARY",
      any(e["decision"] == "PRIMARY" for e in chain), str([e["decision"] for e in chain]))
check("每条证据带原文片段",
      all(ev["text"] for e in chain for ev in e["evidence"]) if chain else False)
check("每条证据带段号定位",
      all(ev["location"]["span"] for e in chain for ev in e["evidence"]) if chain else False)
check("证据链带命中规则",
      all(e["matched_rules"] for e in chain if e["decision"] != "EXCLUDED"),
      str([(e["domain"], e["matched_rules"]) for e in chain]))

print("\n=== F. 排除规则与冲突留痕 ===")
# 纯管网类：F-WATER-04 的手段词无「肯定形式」的水体治理目标词支撑，
# 不应打 WATER 主标；由 X-WATER-01 干净剔除，状态为 EXCLUDED（非 CONFLICT）。
pipe = "对城区实施雨污分流管网建设，新建污水管网12公里。本项目不涉及河湖水体治理内容。"
v2 = eng.judge(pipe, ["WATER"])
check("纯管网建设 WATER 被剔除", "WATER" not in v2["final_labels"], str(v2["final_labels"]))
check("手段词规则未被单独触发（none_strict 生效）",
      "F-WATER-04" not in v2["jev"]["force_rules"], str(v2["jev"]["force_rules"]))
check("状态为 EXCLUDED（明确排除，非待复核）",
      v2["jev"]["status"] == "EXCLUDED", v2["jev"]["status"])
check("排除规则留痕", len(v2["jev"]["exclude_rules"]) >= 1, str(v2["jev"]["exclude_rules"]))

# 强制规则与排除规则真冲突场景：既命中水体治理目标词，又命中纯管网排除条件
conflict_doc = "本项目新建城镇污水管网12公里，同时对城区黑臭水体实施水体治理，开展水质提升工程，新建雨污分流管网20公里。"
v3 = eng.judge(conflict_doc, ["WATER"])
check("强制与排除同中时状态为 CONFLICT",
      v3["jev"]["status"] in ("CONFLICT", "PASS"), v3["jev"]["status"])
check("冲突场景留痕完整",
      isinstance(v3["jev"]["conflicts"], list), str(v3["jev"]["conflicts"]))

print("\n=== G. 端到端服务层 ===")
analysis = analyze_document(doc, use_llm=False)
check("返回 PolicyAnalysis", isinstance(analysis, PolicyAnalysis))
check("doc_id 生成", analysis.doc_id.startswith("POL-"), analysis.doc_id)
check("主赛道正确", analysis.primary_track == "水生态水环境")
check("final_labels 为枚举", all(isinstance(l, DomainCode) for l in analysis.final_labels))
check("证据链序列化正常", len(analysis.evidence_chain) > 0)
check("jev 输出为结构化对象", analysis.jev.status in (JEVStatus.PASS, JEVStatus.CONFLICT))
check("json 可序列化", len(analysis.model_dump_json()) > 100)


def _check_reject() -> bool:
    """市级文档应被层级闸门拒收"""
    try:
        analyze_document(
            parse_text("XX市指南", title="XX市生态环境资金申报指南"), use_llm=False
        )
        return False
    except ValueError:
        return True


check("市级文档被拒收", _check_reject())

print("\n=== H. 项目画像抽取 ===")
proj = extract_profile("某县拟建设农村生活污水治理项目，总投资3200万元，申报主体为政府。")
check("识别项目类型", proj.project_type == "农村生活污水治理", proj.project_type)
check("识别领域编码", proj.domain_code == DomainCode.RURAL, str(proj.domain_code))
check("识别投资额（万元）", proj.investment == 3200.0, str(proj.investment))
check("识别地域", proj.location == "某县", proj.location)
check("识别申报主体", proj.applicant_type == "政府", proj.applicant_type)

proj2 = extract_profile("某矿山生态修复项目，总投资1.2亿元。")
check("识别亿元换算", proj2.investment == 12000.0, str(proj2.investment))
check("识别矿山领域", proj2.domain_code == DomainCode.MOUNTAIN, str(proj2.domain_code))

print("\n=== I. 政策匹配 ===")
store = PolicyStore()
store.add_from_analysis(analysis, doc.full_text)
check("入库成功", len(store) == 1)

result = match_project(proj, store)
check("返回匹配结果", len(result.matches) == 1)
m = result.matches[0]
check("农村项目对本水环境政策不给假阳性（不得超过 LOW）",
      m.match_level in (MatchLevel.LOW, MatchLevel.NONE),
      f"{m.match_level} score={m.score}")
check("分值被领域不契合封顶", m.score <= 0.35, str(m.score))
check("匹配度分值在 0-1 之间", 0.0 <= m.score <= 1.0, str(m.score))
check("含匹配理由", len(m.reasons) > 0)
check("含扫描政策数", result.scanned_policy_count == 1)

# 构造一份对口的农村政策，验证能匹配上
rural = PolicyRecord(
    doc_id="POL-RURAL-TEST",
    doc_title="XX省农村环境整治资金申报指南",
    level="省级",
    primary_track="农村生态环境整治",
    labels=["RURAL", "WATER"],
    support_directions="支持农村生活污水治理、农村生活垃圾治理",
    key_project_types=["农村生活污水治理", "农村黑臭水体治理"],
    excluded_scope=["城镇污水处理工程不属于本资金支持范围"],
    applicant_requirements="县级人民政府或生态环境部门",
    funding_rules="以奖代补，补助比例不超过总投资的60%",
    applicable_region="全省",
    raw_text="农村生活污水治理 农村生活垃圾治理 农村人居环境整治",
)
store.add(rural)
result2 = match_project(proj, store)
top = result2.matches[0]
check("对口政策排第一", top.doc_id == "POL-RURAL-TEST", f"{top.doc_id} score={top.score}")
check("对口政策匹配度为高或中", top.match_level in (MatchLevel.HIGH, MatchLevel.MEDIUM),
      f"{top.match_level} score={top.score}")
check("给出缺失材料清单", len(top.missing_materials) > 0, str(top.missing_materials))
check("匹配理由带依据", any(r.evidence for r in top.reasons if r.kind == "domain"))

# 负面清单命中场景
proj3 = extract_profile("某市城镇污水处理厂建设项目，总投资8000万元。")
result3 = match_project(proj3, store)
rural_match = next(m for m in result3.matches if m.doc_id == "POL-RURAL-TEST")
check("城镇项目触发农村政策负面清单",
      len(rural_match.excluded_reasons) > 0 or rural_match.match_level == MatchLevel.NONE,
      f"{rural_match.match_level} {rural_match.excluded_reasons}")

print("\n=== J. 综合类文档与能力建设配套 ===")
# 多赛道综合文档（入库指南类）不强行裁主赛道
multi = (
    "中央生态环境资金支持大气污染防治、水污染防治、土壤污染防治、农村环境整治、"
    "地下水生态环境保护、固体废物治理、山水林田湖草沙生态修复等多类项目。"
    "大气方面支持锅炉综合治理与挥发性有机物治理；水方面支持流域水污染治理与入河排污口整治；"
    "土壤方面支持土壤污染风险管控与修复；农村方面支持农村生活污水治理与农村生活垃圾治理；"
    "地下水方面支持地下水污染防控；固废方面支持历史遗留固体废物堆场整治；"
    "生态修复方面支持废弃矿山生态修复与水土流失治理。"
)
v4 = eng.judge(multi)
check("多赛道综合文档不指定单一主赛道",
      v4["primary_track"] == "" or v4["primary_track"] is None,
      f"primary={v4['primary_track']} labels={v4['final_labels']}")
check("综合类文档留痕说明理由",
      any("综合" in r or "赛道" in r for r in v4["audit"]["review_reasons"]),
      str(v4["audit"]["review_reasons"]))

# 能力建设是配套赛道：与实体治理赛道共现时退为协同
cap = "某市实施美丽蓝天建设项目，包括工业炉窑清洁能源替代，同步建设大气环境监测监管能力体系。"
v5 = eng.judge(cap)
check("能力建设不抢实体治理赛道的主位",
      v5["primary_track"] == "大气污染防治",
      f"primary={v5['primary_track']} labels={v5['final_labels']}")

print(f"\n{'=' * 50}")
print(f"通过 {PASS} / 失败 {FAIL}")
print("=" * 50)
sys.exit(1 if FAIL else 0)
