#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出数据契约（Pydantic 模型）

设计原则：每个分类判定都必须能回答三个问题 ——
    凭什么？（evidence）
    哪条规则？（matched_rules）
    和 LLM 一致吗？（llm_agreement）
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------

class DomainCode(str, Enum):
    WATER = "WATER"
    AIR = "AIR"
    SOIL = "SOIL"
    GROUNDWATER = "GROUNDWATER"
    SOLID = "SOLID"
    RURAL = "RURAL"
    MOUNTAIN = "MOUNTAIN"
    CLIMATE = "CLIMATE"
    CAPACITY = "CAPACITY"
    NUCLEAR = "NUCLEAR"
    INDUSTRY = "INDUSTRY"


class DecisionRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    EXCLUDED = "EXCLUDED"


class JEVStatus(str, Enum):
    PASS = "PASS"           # 有标签保留，无冲突
    CONFLICT = "CONFLICT"   # 强制规则与排除规则相互抵触，需人工裁决
    EXCLUDED = "EXCLUDED"   # 排除规则明确命中且无标签保留（判定不属于本类资金）
    REVIEW = "REVIEW"       # 规则未覆盖，需人工复核
    FAIL = "FAIL"


class ConfidenceBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DocLevel(str, Enum):
    CENTRAL = "国家级"
    PROVINCIAL = "省级"


class SourceType(str, Enum):
    POLICY_ORIGINAL = "policy_original_text"
    PROJECT_INPUT = "project_input"
    LLM_INFERRED = "llm_inferred"


class MatchLevel(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    NONE = "不匹配"


# --------------------------------------------------------------------------
# 证据链
# --------------------------------------------------------------------------

class Evidence(BaseModel):
    """单条原文证据。定位信息是审计追溯的载体。"""
    text: str = Field(description="原文片段")
    matched_term: str | None = Field(default=None, description="触发匹配的锚点词")
    span: str = Field(default="", description="段号，如 P008")
    source_type: SourceType = SourceType.POLICY_ORIGINAL


class DomainDecision(BaseModel):
    """单个领域的判定结果及完整依据"""
    domain: str = Field(description="领域中文名")
    domain_code: DomainCode
    decision: DecisionRole
    evidence: list[Evidence] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    excluded_by_rules: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# JEV 校验状态（替代"可信度 100%"）
# --------------------------------------------------------------------------

class JEVVerdict(BaseModel):
    """
    规则引擎只能保证「规则命中确定性」，不能宣称整份政策解析绝对正确。
    因此不输出百分比，只输出可核查的状态。
    """
    status: JEVStatus
    confidence_band: ConfidenceBand = Field(
        description="由状态推导的置信区间，非系统自称的百分比"
    )
    force_rules: list[str] = Field(default_factory=list)
    exclude_rules: list[str] = Field(default_factory=list)
    force_rule_count: int = 0
    exclude_rule_count: int = 0
    conflicts: list[str] = Field(default_factory=list)
    conflict_count: int = 0
    evidence_count: int = 0
    llm_agreement: bool = Field(
        default=False, description="LLM 候选标签集与规则终审标签集是否一致"
    )
    weight_rule_applied: str = ""


# --------------------------------------------------------------------------
# 字段抽取
# --------------------------------------------------------------------------

class TextField(BaseModel):
    text: str | None = None
    spans: list[str] = Field(default_factory=list)
    note: str | None = None


class FieldItem(BaseModel):
    text: str
    spans: list[str] = Field(default_factory=list)


class ItemListField(BaseModel):
    items: list[FieldItem] = Field(default_factory=list)
    note: str | None = None


class PolicyFields(BaseModel):
    """七个固定字段，不增不减"""
    support_directions: TextField = Field(default_factory=TextField)
    key_project_types: ItemListField = Field(default_factory=ItemListField)
    excluded_scope: ItemListField = Field(default_factory=ItemListField)
    applicant_requirements: TextField = Field(default_factory=TextField)
    funding_rules: TextField = Field(default_factory=TextField)
    performance_targets: TextField = Field(default_factory=TextField)
    applicable_region: TextField = Field(default_factory=TextField)


# --------------------------------------------------------------------------
# 来源
# --------------------------------------------------------------------------

class SourceInfo(BaseModel):
    doc_title: str
    level: DocLevel
    issuer: str = ""
    doc_no: str = ""
    published_at: str = ""
    filename: str = ""


# --------------------------------------------------------------------------
# 政策解析结果
# --------------------------------------------------------------------------

class PolicyAnalysis(BaseModel):
    """一份政策指南的完整解析结果"""
    source: SourceInfo
    primary_track: str | None = None
    secondary_tracks: list[str] = Field(default_factory=list)
    final_labels: list[DomainCode] = Field(default_factory=list)
    llm_candidate_labels: list[str] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)
    fields: PolicyFields = Field(default_factory=PolicyFields)
    evidence_chain: list[DomainDecision] = Field(default_factory=list)
    jev: JEVVerdict
    needs_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    extraction_mode: str = "mock"
    doc_id: str = Field(default="", description="政策库主键，供匹配模块引用")


# --------------------------------------------------------------------------
# 项目画像与匹配
# --------------------------------------------------------------------------

class ProjectProfile(BaseModel):
    """用户输入的项目画像 —— 匹配模块的输入。
    所有字段均可留空：识别不到就留空并提示，绝不猜测。"""
    name: str = ""
    domain: str = Field(default="", description="所属领域，未识别时为空")
    domain_code: DomainCode | None = None
    secondary_domains: list[str] = Field(default_factory=list)
    project_type: str = ""
    investment: float | None = Field(default=None, description="投资额（万元）")
    location: str = ""
    region_level: str = Field(default="", description="县/市/省")
    status: str = Field(default="拟申报")
    applicant_type: str = ""
    raw_input: str = ""


class MatchReason(BaseModel):
    """匹配或不匹配的原因，必须带依据"""
    kind: str = Field(description="domain / investment / applicant / region / negative_list")
    detail: str
    evidence: list[str] = Field(default_factory=list)


class PolicyMatch(BaseModel):
    """单个政策对项目的匹配结果"""
    doc_id: str
    doc_title: str
    match_level: MatchLevel
    score: float = Field(ge=0.0, le=1.0, description="匹配度分值，非可信度")
    support_direction: str = ""
    funding_type: str = ""
    applicant_requirement: str = ""
    conditions: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    reasons: list[MatchReason] = Field(default_factory=list)
    excluded_reasons: list[MatchReason] = Field(default_factory=list)


class MatchResult(BaseModel):
    project: ProjectProfile
    matches: list[PolicyMatch] = Field(default_factory=list)
    scanned_policy_count: int = 0
    generated_at: str = ""


# --------------------------------------------------------------------------
# API 通用包装
# --------------------------------------------------------------------------

class AnalysisResponse(BaseModel):
    ok: bool = True
    data: PolicyAnalysis | None = None
    error: str | None = None


class MatchResponse(BaseModel):
    ok: bool = True
    data: MatchResult | None = None
    error: str | None = None


def dump(model: BaseModel, **kwargs: Any) -> dict:
    """统一序列化出口，默认不把 None 字段塞满 JSON"""
    kwargs.setdefault("exclude_none", True)
    kwargs.setdefault("by_alias", False)
    return model.model_dump(**kwargs)
