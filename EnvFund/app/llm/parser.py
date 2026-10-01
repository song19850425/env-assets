#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 输出容错解析与段号回填校验

模型返回的 JSON 从不可靠，本模块负责把它「驯服」成可信结构：
1. 剥离 markdown 围栏 / 前后解释文字
2. 修复常见 JSON 语法错误（尾逗号、单引号、中文引号）
3. 校验段号真实性 —— 编造的段号必须被剔除，不能进审计
4. 校验摘录文本与原始段落的一致性 —— 防止模型改写原文
5. 补齐缺失字段结构
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# 七个固定字段，不增不减
REQUIRED_FIELDS = [
    "support_directions",
    "key_project_types",
    "excluded_scope",
    "applicant_requirements",
    "funding_rules",
    "performance_targets",
    "applicable_region",
]

LIST_FIELDS = {"key_project_types", "excluded_scope"}

VALID_LABELS = {
    "WATER", "AIR", "SOIL", "GROUNDWATER", "SOLID", "RURAL",
    "MOUNTAIN", "CLIMATE", "CAPACITY", "NUCLEAR", "INDUSTRY", "UNCERTAIN",
}


@dataclass
class ValidationReport:
    """LLM 输出的校验轨迹"""
    json_repaired: bool = False
    text_trimmed: bool = False          # 返回中混有围栏或解释文字，被裁掉了
    fake_spans: list[str] = field(default_factory=list)
    unverified_quotes: list[str] = field(default_factory=list)
    invalid_labels: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any([
            self.json_repaired, self.text_trimmed, self.fake_spans,
            self.unverified_quotes, self.invalid_labels, self.missing_fields,
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "json_repaired": self.json_repaired,
            "text_trimmed": self.text_trimmed,
            "fake_spans": self.fake_spans,
            "unverified_quotes": self.unverified_quotes,
            "invalid_labels": self.invalid_labels,
            "missing_fields": self.missing_fields,
        }


# --------------------------------------------------------------------------
# 1. 抽取 JSON
# --------------------------------------------------------------------------

def extract_json(raw: str, report: ValidationReport) -> dict:
    """
    从模型原始返回中抽出 JSON 对象。
    容忍：```json 围栏、前后解释文字、尾逗号、中文引号。
    失败时抛 ValueError 并附原始文本片段，便于日志排查。
    """
    if not raw or not raw.strip():
        raise ValueError("模型返回为空")

    text = raw.strip()

    # 剥离 markdown 围栏
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
        report.text_trimmed = True

    # 直接尝试
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 截取首个 { 到末个 } 之间的内容（模型常在前后加解释）
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"模型返回中未找到 JSON 对象：{raw[:200]!r}")
    body = text[start:end + 1]
    if body != text:
        report.text_trimmed = True

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass

    # 语法修复：尾逗号 + 中文引号
    repaired = re.sub(r",\s*([}\]])", r"\1", body)
    repaired = repaired.replace("“", '"').replace("”", '"')
    repaired = repaired.replace("‘", "'").replace("’", "'")
    # 中文冒号在 key 位置偶发
    repaired = re.sub(r'"\s*：', '":', repaired)
    try:
        obj = json.loads(repaired)
        report.json_repaired = True
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败且修复无效：{e}；原文片段：{body[:200]!r}") from e


# --------------------------------------------------------------------------
# 2. 段号与摘录校验
# --------------------------------------------------------------------------

def build_span_index(paras: list[tuple[str, str]]) -> dict[str, str]:
    return {sid: txt for sid, txt in paras}


def normalize(s: str) -> str:
    """去掉空白与常见标点差异，用于宽松比对"""
    return re.sub(r"[\s　，。、；：（）()【】\[\]“”\"'‘’]", "", s)


def verify_span(span_id: str, quote: str, index: dict[str, str]) -> tuple[bool, str]:
    """
    校验 (段号, 摘录) 是否成立。
    返回 (是否可信, 不可信原因)
    """
    if span_id not in index:
        return False, "段号不存在"

    if not quote:
        return True, ""  # 只给段号不给摘录，允许通过（弱证据）

    para = normalize(index[span_id])
    q = normalize(quote)

    if q in para:
        return True, ""

    # 容错：摘录是跨段拼接或略有截断时，按 70% 字符覆盖率放宽
    if len(q) >= 6:
        hits = sum(1 for ch in q if ch in para)
        if hits / len(q) >= 0.7:
            return True, ""

    return False, "摘录与原文不符"


def validate_and_repair(llm_out: dict, paras: list[tuple[str, str]]) -> tuple[dict, ValidationReport]:
    """
    对 LLM 输出做全面校验与就地修复。
    核心原则：**宁可丢证据，不可留假证据。**
    """
    report = ValidationReport()
    index = build_span_index(paras)

    if not isinstance(llm_out, dict):
        raise ValueError("LLM 顶层输出不是对象")

    # --- 候选标签 ---
    labels_out: list[dict] = []
    for item in llm_out.get("candidate_labels", []) or []:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if code not in VALID_LABELS:
            report.invalid_labels.append(str(code))
            continue

        kept_evidence = []
        for ev in item.get("evidence", []) or []:
            if not isinstance(ev, dict):
                continue
            sid, quote = ev.get("span", ""), ev.get("quote", "")
            ok, reason = verify_span(sid, quote, index)
            if ok:
                kept_evidence.append({"span": sid, "quote": quote})
            else:
                if reason == "段号不存在":
                    report.fake_spans.append(f"{code}:{sid}")
                else:
                    report.unverified_quotes.append(f"{code}:{sid}:{str(quote)[:30]}")

        labels_out.append({"code": code, "evidence": kept_evidence})

    # --- 七个固定字段 ---
    raw_fields = llm_out.get("fields") or {}
    fields_out: dict = {}

    for fname in REQUIRED_FIELDS:
        val = raw_fields.get(fname)
        if val is None:
            report.missing_fields.append(fname)
            val = {"items": []} if fname in LIST_FIELDS else {"text": None, "spans": [], "note": "模型未返回"}

        if fname in LIST_FIELDS:
            items = val.get("items", []) if isinstance(val, dict) else []
            kept = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                spans = [s for s in (it.get("spans") or []) if s in index]
                dropped = [s for s in (it.get("spans") or []) if s not in index]
                report.fake_spans.extend(f"{fname}:{s}" for s in dropped)
                kept.append({"text": it.get("text", ""), "spans": spans})
            fields_out[fname] = {"items": kept}
        else:
            if not isinstance(val, dict):
                val = {"text": val if isinstance(val, str) else None, "spans": []}
            spans_in = val.get("spans") or []
            spans = [s for s in spans_in if s in index]
            report.fake_spans.extend(f"{fname}:{s}" for s in spans_in if s not in index)
            # text 与 span 一致性抽查
            txt = val.get("text")
            if txt and spans and not any(normalize(txt) in normalize(index[s]) for s in spans):
                if len(normalize(txt)) >= 8:
                    report.unverified_quotes.append(f"{fname}:text 与所引段号不一致")
            fields_out[fname] = {
                "text": txt,
                "spans": spans,
                **({"note": val["note"]} if val.get("note") else {}),
            }

    # --- uncovered 与 flags ---
    uncovered = [u for u in (llm_out.get("uncovered") or []) if isinstance(u, str)]
    flags = [f for f in (llm_out.get("flags") or []) if isinstance(f, str)]

    cleaned = {
        "candidate_labels": labels_out,
        "uncovered": uncovered,
        "fields": fields_out,
        "flags": flags,
    }
    return cleaned, report
