#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务编排层：把解析 → 抽取 → 规则终审 → 匹配串起来

对外只暴露两个动作：
    analyze_document(...)  → PolicyAnalysis
    match(...)             → MatchResult
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.jev.engine import JEVEngine
from app.llm.client import call_chat_completions, DEFAULT_BASE_URL, DEFAULT_MODEL
from app.llm.parser import extract_json, validate_and_repair
from app.parser.document import ParsedDocument, is_central_or_provincial, parse_document
from app.rag.matching import MatchOptions, extract_profile, match_project
from app.rag.store import PolicyStore
from app.schemas.models import (
    DomainCode,
    MatchResult,
    PolicyAnalysis,
    PolicyFields,
    SourceInfo,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "prompts" / "policy_agent.txt"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 语义抽取
# --------------------------------------------------------------------------

def _llm_extract(
    doc: ParsedDocument,
    *,
    api_key: str,
    base_url: str,
    model: str,
    max_repair: int = 2,
):
    system = _load_prompt()
    user = f"文档标题：{doc.title}\n\n请解析以下指南全文：\n\n{doc.numbered_text}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    from app.llm.parser import ValidationReport

    report = ValidationReport()
    last_err: Exception | None = None

    for attempt in range(max_repair + 1):
        raw = call_chat_completions(
            messages, api_key=api_key, base_url=base_url, model=model
        )
        try:
            parsed = extract_json(raw, report)
        except ValueError as e:
            last_err = e
            if attempt >= max_repair:
                raise
            messages = messages[:2] + [
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content":
                    f"上面的输出无法解析：{e}\n请只输出一个合法 JSON 对象，"
                    f"不要 markdown 代码块，不要任何解释文字。"},
            ]
            continue

        cleaned, vrep = validate_and_repair(parsed, doc.sections and
                                            [(s.span, s.text) for s in doc.sections] or [])
        report.fake_spans += vrep.fake_spans
        report.unverified_quotes += vrep.unverified_quotes
        report.invalid_labels += vrep.invalid_labels
        report.missing_fields += vrep.missing_fields
        return cleaned, report

    raise RuntimeError(f"模型输出无法解析：{last_err}")


def _mock_extract(doc: ParsedDocument):
    """离线模式：用规则引擎自身抽标签，字段留空并标注"""
    from app.llm.parser import ValidationReport

    first = doc.sections[0].span if doc.sections else ""
    data = {
        "candidate_labels": [],
        "uncovered": [],
        "fields": {
            "support_directions": {"text": None, "spans": [], "note": "离线模式未抽取"},
            "key_project_types": {"items": [], "note": "离线模式未抽取"},
            "excluded_scope": {"items": [], "note": "离线模式未抽取"},
            "applicant_requirements": {"text": None, "spans": [], "note": "离线模式未抽取"},
            "funding_rules": {"text": None, "spans": [], "note": "离线模式未抽取"},
            "performance_targets": {"text": None, "spans": [], "note": "离线模式未抽取"},
            "applicable_region": {"text": None, "spans": [], "note": "离线模式未抽取"},
        },
        "flags": ["离线模式：仅规则引擎判定，无 LLM 字段抽取"],
    }
    return validate_and_repair(data, [(s.span, s.text) for s in doc.sections])


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def make_doc_id(doc: ParsedDocument) -> str:
    h = hashlib.sha1(f"{doc.title}{doc.full_text[:500]}".encode("utf-8")).hexdigest()
    return f"POL-{h[:12].upper()}"


def analyze_document(
    source: str | Path | ParsedDocument,
    *,
    title: str = "",
    issuer: str = "",
    allow_municipal: bool = False,
    use_llm: bool = True,
    engine: JEVEngine | None = None,
) -> PolicyAnalysis:
    """
    解析一份政策指南，输出结构化结果 + 证据链 + JEV 校验状态。
    """
    doc = source if isinstance(source, ParsedDocument) else parse_document(source, title=title)
    if issuer:
        doc.issuer = issuer
    if title:
        doc.title = title

    # 层级闸门
    if not allow_municipal and not is_central_or_provincial(doc.title, doc.issuer, doc.full_text):
        raise ValueError(
            f"文档层级不在受理范围（仅国家级/省级）：{doc.title or doc.source_file}。"
            f"如确需处理请设置 allow_municipal=True"
        )

    api_key = os.environ.get("ENV_AGENT_API_KEY", "").strip()
    mode = "llm" if (use_llm and api_key) else "mock"

    if mode == "llm":
        llm_out, vrep = _llm_extract(
            doc,
            api_key=api_key,
            base_url=os.environ.get("ENV_AGENT_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("ENV_AGENT_MODEL", DEFAULT_MODEL),
        )
    else:
        llm_out, vrep = _mock_extract(doc)

    candidate_codes = [
        c["code"] for c in llm_out.get("candidate_labels", []) if c["code"] != "UNCERTAIN"
    ]

    engine = engine or JEVEngine()
    positions = doc.span_index
    verdict = engine.judge(doc.numbered_text, candidate_codes, positions)

    # 语义层自身问题也进人工复核
    reasons = list(verdict["audit"]["review_reasons"])
    if vrep.fake_spans:
        reasons.append(f"剔除编造段号 {len(vrep.fake_spans)} 处：" + "、".join(vrep.fake_spans[:5]))
    if vrep.invalid_labels:
        reasons.append("剔除标签池外标签：" + "、".join(vrep.invalid_labels))
    if vrep.unverified_quotes:
        reasons.append(f"摘录与原文不符 {len(vrep.unverified_quotes)} 处")
    if vrep.missing_fields:
        reasons.append("模型未返回字段：" + "、".join(vrep.missing_fields))
    if vrep.json_repaired or vrep.text_trimmed:
        reasons.append("模型输出经裁剪/语法修复（原始返回非规范 JSON）")

    # 组装 schema
    fields_raw = llm_out.get("fields", {})
    fields = PolicyFields(
        support_directions=fields_raw.get("support_directions", {}),
        key_project_types=fields_raw.get("key_project_types", {}),
        excluded_scope=fields_raw.get("excluded_scope", {}),
        applicant_requirements=fields_raw.get("applicant_requirements", {}),
        funding_rules=fields_raw.get("funding_rules", {}),
        performance_targets=fields_raw.get("performance_targets", {}),
        applicable_region=fields_raw.get("applicable_region", {}),
    )

    jev = dict(verdict["jev"])
    jev["needs_human_review"] = bool(reasons)

    return PolicyAnalysis(
        source=SourceInfo(
            doc_title=doc.title,
            level="国家级" if _looks_central(doc.title, doc.issuer) else "省级",
            issuer=doc.issuer,
            doc_no=doc.doc_no,
            filename=doc.source_file,
        ),
        primary_track=verdict["primary_track"],
        secondary_tracks=verdict["secondary_tracks"],
        final_labels=[DomainCode(l) for l in verdict["final_labels"] if _is_domain(l)],
        llm_candidate_labels=candidate_codes,
        uncovered=llm_out.get("uncovered", []),
        fields=fields,
        evidence_chain=verdict["evidence_chain"],
        jev=jev,
        needs_human_review=bool(reasons),
        review_reasons=reasons,
        extraction_mode=mode,
        doc_id=make_doc_id(doc),
    )


def _looks_central(title: str, issuer: str) -> bool:
    import re
    return bool(re.search(r"国家|生态环境部|财政部|国务院", f"{title}{issuer}"))


_DOMAIN_VALUES = {d.value for d in DomainCode}


def _is_domain(code: str) -> bool:
    return code in _DOMAIN_VALUES


# --------------------------------------------------------------------------
# 匹配入口
# --------------------------------------------------------------------------

def match(
    user_input: str,
    store: PolicyStore,
    *,
    options: MatchOptions | None = None,
) -> MatchResult:
    """项目自然语言描述 → 画像 → 政策匹配"""
    profile = extract_profile(user_input)
    return match_project(profile, store, options)
