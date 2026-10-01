#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JEV 规则终审引擎（独立于 LLM，纯字面命中判定）

设计原则：
1. 规则只吃「词表命中」，绝不调用模型判断语义
2. 优先级：EXCLUDE > FORCE > WEIGHT，写死在代码里
3. 每条判定都产出可追溯记录，便于人工复核
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# 规则库路径：项目根 / data / jev_rules.json
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = PROJECT_ROOT / "data" / "jev_rules.json"


@dataclass
class Hit:
    """一条规则命中记录"""
    rule_id: str
    kind: str          # FORCE / EXCLUDE
    label: str
    matched: list[str] = field(default_factory=list)
    note: str = ""
    negated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "label": self.label,
            "matched": self.matched,
            "negated": self.negated,
            "note": self.note,
        }


NEGATION_PREFIXES = (
    "不涉及", "不包含", "不包括", "不属于", "不予支持", "不得申报", "禁止",
    "不纳入", "非", "未涉及", "无",
)
NEGATION_WINDOW = 12  # 否定词距锚点最大字符距离

# 句子边界：否定作用域不得跨越这些字符
SENTENCE_BREAKS = "。！？；\n"
# 连词可以延续否定作用域（"不涉及A和B" 中 B 也被否定）
CONJUNCTIONS = "和与及、或以及"


def is_negated(text: str, term: str, window: int = NEGATION_WINDOW) -> bool:
    """
    判断 term 在 text 中的某次出现是否被否定词修饰。

    关键约束：否定作用域**不跨句**。遇到句号、分号、换行即截断，
    因此 "本项目不涉及管网。本次实施河湖水体治理" 中「水体治理」不被否定。

    反之，同一句内的并列成分共享否定（"不涉及A和B" 中 B 也被否定）。
    """
    start = 0
    while True:
        idx = text.find(term, start)
        if idx == -1:
            return False

        # 取锚点前的窗口，并在最近的句子边界处截断
        left = text[max(0, idx - window): idx]
        last_break = max((left.rfind(b) for b in SENTENCE_BREAKS), default=-1)
        if last_break != -1:
            left = left[last_break + 1:]

        if any(p in left for p in NEGATION_PREFIXES):
            # 若否定词与锚点之间隔着句内连词，视为同一否定的并列宾语
            return True

        # 锚点后紧跟「除外」类表述
        right = text[idx + len(term): idx + len(term) + window]
        right = right.split("。")[0]
        if any(p in right for p in ("之外", "以外的", "除外")):
            return True

        start = idx + 1
        if start >= len(text):
            return False


class JEVEngine:
    def __init__(self, rules_path: str | Path = DEFAULT_RULES):
        self.rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
        self.force_rules = self.rules.get("FORCE", [])
        self.exclude_rules = self.rules.get("EXCLUDE", [])
        self.weight_cfg = self.rules.get("WEIGHT", {})
        self.label_names = self.rules.get("labels", {})

    # ---------- 基础匹配 ----------

    def _present(self, text: str, terms: list[str], mode: str, *, skip_negated: bool = True) -> list[str]:
        """返回 text 中实际命中的词。

        三种 mode 语义必须严格区分（曾经混用 all 导致规则永不触发）：
          - any       : 词表内任一命中即通过（同义词组/并列选项）
          - all_group : 同义词组，任一命中即视为该组满足（与 any 结果相同，语义更明确）
          - all       : 词表内全部命中才通过（真·合取条件，如「技术改造」且「技改」）
        skip_negated=True 时，被否定词修饰的出现不计入命中。"""
        hit = []
        for t in terms:
            if t not in text:
                continue
            if skip_negated and is_negated(text, t):
                continue
            hit.append(t)
        if mode == "all":
            return hit if len(hit) == len(terms) else []
        # any / all_group 均为任一命中
        return hit

    def _negated_present(self, text: str, terms: list[str]) -> list[str]:
        """只返回被否定的词，用于审计留痕"""
        return [t for t in terms if t in text and is_negated(text, t)]

    def _check_force(self, rule: dict, text: str) -> Hit | None:
        """强制规则：any 任一命中即成立。

        可选 none_strict：治理目标词表，要求至少一个以「肯定形式」出现。
        用于手段词类规则（如 F-WATER-04 的「雨污分流/水系连通」）——
        这类词本身只是工程手段，必须辅以明确的水体治理目标才算数；
        「不涉及河湖水体治理」这种否定表述不能算作目标词出现。
        """
        terms = rule.get("any", [])
        matched = self._present(text, terms, "any", skip_negated=True)
        negated = self._negated_present(text, terms)
        if not matched:
            return None

        strict = rule.get("none_strict", [])
        if strict:
            affirmative = self._present(text, strict, "any", skip_negated=True)
            if not affirmative:
                return None

        return Hit(rule["id"], "FORCE", rule["label"], matched, rule.get("note", ""), negated)

    def _check_exclude(self, rule: dict, text: str) -> Hit | None:
        """排除规则：前置条件全中 且 any 至少一中（若有） 且 none 全不中。

        前置条件支持两个字段，语义不同、不可混用：
          - all       : 真·合取，词表内每个词都必须在文中出现
          - all_group : 同义组，任一命中即视为该组满足
        历史坑：把同义词组（城镇/城市/市政）写进 all，会因「要求全中」
        导致规则永不触发——这类词一律用 all_group。

        注意：排除规则中的关键词也走否定过滤——「不涉及管网」不应触发排除。"""
        all_terms = rule.get("all", [])
        group_terms = rule.get("all_group", [])
        any_terms = rule.get("any", [])
        none_terms = rule.get("none", [])

        matched: list[str] = []

        if all_terms:
            m = self._present(text, all_terms, "all", skip_negated=True)
            if not m:
                return None
            matched += m

        if group_terms:
            g = self._present(text, group_terms, "all_group", skip_negated=True)
            if not g:
                return None
            matched += g

        if not all_terms and not group_terms and not any_terms:
            return None

        if any_terms:
            a = self._present(text, any_terms, "any", skip_negated=True)
            if not a:
                return None
            matched = matched + a

        # none 命中任何一条 → 排除规则不生效（说明具备被保护要素）
        if none_terms:
            blocked = self._present(text, none_terms, "any", skip_negated=True)
            if blocked:
                return None

        return Hit(rule["id"], "EXCLUDE", rule["label"], matched, rule.get("note", ""))

    # ---------- 主流程 ----------

    @staticmethod
    def _confidence_band(status: str, evidence_count: int, conflict_count: int) -> str:
        """
        用「可核查状态」替代「可信度百分比」。
        规则引擎只能保证规则命中确定性，不能宣称整份政策解析绝对正确。
        """
        if status == "FAIL":
            return "LOW"
        if conflict_count or evidence_count == 0:
            return "MEDIUM"
        return "HIGH"

    def judge(
        self,
        text: str,
        candidate_labels: list[str] | None = None,
        positions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        text: 指南全文（或关注段落拼接）
        candidate_labels: LLM 给的候选标签 code 列表（仅供参考与对照，不参与判定）
        positions: {段号: 段落原文}，用于生成证据链的 page/section 定位

        return: 裁定结果 + 证据链 + 审计轨迹
        """
        force_hits = [h for r in self.force_rules if (h := self._check_force(r, text))]
        exclude_hits = [h for r in self.exclude_rules if (h := self._check_exclude(r, text))]

        forced_labels = {h.label for h in force_hits}
        excluded_labels = {h.label for h in exclude_hits}

        # 优先级：EXCLUDE 一票否决
        final_labels = forced_labels - excluded_labels
        conflicts = sorted(excluded_labels & forced_labels)

        # 无任何规则命中 → 交人工
        review_reasons: list[str] = []
        if not final_labels:
            review_reasons.append("无强制规则命中，语义层候选需人工确认")
        if conflicts:
            review_reasons.append(
                "规则冲突：" + "、".join(conflicts) + "（已按排除优先裁定）"
            )
        if candidate_labels:
            llm_set = set(candidate_labels)
            only_llm = llm_set - forced_labels - excluded_labels
            if only_llm:
                review_reasons.append("语义层给出但规则层无依据：" + "、".join(sorted(only_llm)))

        # ---- 多赛道综合文档：不强裁主赛道 ----
        # 「中央生态环境资金项目储备库入库指南」这类文档涵盖全部资金类别，
        # 强行裁一个主赛道会产生误导（曾把入库指南主赛道判成 MOUNTAIN）。
        # 标签数达到阈值即视为综合类，主赛道留空并明示理由。
        MULTI_TRACK_THRESHOLD = 5
        if len(final_labels) >= MULTI_TRACK_THRESHOLD:
            primary = None
            secondary = sorted(final_labels)
            weight_rule = "MULTI_TRACK"
            review_reasons.append(
                f"文档覆盖 {len(final_labels)} 个赛道，判定为综合性文档，不指定单一主赛道"
            )
        else:
            primary, secondary, weight_rule = self._resolve_weight(final_labels, force_hits)
            if weight_rule == "FALLTHROUGH_MULTI_TIE":
                review_reasons.append("多标签无权重规则覆盖且命中条数并列，主赛道需人工确认")

            # 权重规则绝对优先：即使命中条数与之相悖，也以权重规则为准，但留痕提示
            if weight_rule.startswith("W-"):
                counts: dict[str, int] = {}
                for h in force_hits:
                    counts[h.label] = counts.get(h.label, 0) + 1
                if primary and secondary:
                    top_secondary = max(secondary, key=lambda s: counts.get(s, 0))
                    if counts.get(top_secondary, 0) > counts.get(primary, 0):
                        review_reasons.append(
                            f"权重规则 {weight_rule} 与命中计数相悖：{top_secondary} 命中 "
                            f"{counts[top_secondary]} 条 > {primary} 命中 {counts.get(primary, 0)} 条，"
                            f"已按权重规则裁定 {primary} 为主赛道"
                        )

        # ---- 证据链：每个领域标签都带原文定位与命中规则 ----
        evidence_chain = self._build_evidence_chain(
            primary, secondary, force_hits, exclude_hits, positions or {}
        )
        evidence_count = sum(len(e["evidence"]) for e in evidence_chain)

        # ---- JEV 校验状态（替代"可信度 100%"）----
        # EXCLUDED：排除规则明确命中且无任何标签保留 —— 这是「已判定不属于本类资金」，
        #           不是「拿不准」，必须与 REVIEW 区分，否则审计时无法区分
        #           「规则明确排除」与「规则没覆盖到」。
        if conflicts:
            status = "CONFLICT"
        elif final_labels:
            status = "PASS"
        elif exclude_hits:
            status = "EXCLUDED"
        else:
            status = "REVIEW"
        llm_agree = bool(candidate_labels) and set(candidate_labels) == set(final_labels)

        return {
            "primary_track": self._name(primary),
            "secondary_tracks": [self._name(s) for s in secondary],
            "final_labels": sorted(final_labels),
            "evidence_chain": evidence_chain,
            "jev": {
                "status": status,
                "confidence_band": self._confidence_band(status, evidence_count, len(conflicts)),
                "force_rules": [h.rule_id for h in force_hits],
                "exclude_rules": [h.rule_id for h in exclude_hits],
                "force_rule_count": len(force_hits),
                "exclude_rule_count": len(exclude_hits),
                "conflicts": conflicts,
                "conflict_count": len(conflicts),
                "evidence_count": evidence_count,
                "llm_agreement": llm_agree,
                "weight_rule_applied": weight_rule,
            },
            "audit": {
                "force_hits": [h.to_dict() for h in force_hits],
                "exclude_hits": [h.to_dict() for h in exclude_hits],
                "excluded_labels": sorted(excluded_labels),
                "llm_candidates": candidate_labels or [],
                "weight_rule_applied": weight_rule,
                "rule_hit_count": len(force_hits),
                "by_label_hit_count": {
                    lab: sum(1 for h in force_hits if h.label == lab)
                    for lab in sorted(final_labels)
                },
                "needs_human_review": bool(review_reasons),
                "review_reasons": review_reasons,
            },
        }

    def _build_evidence_chain(
        self,
        primary: str | None,
        secondary: list[str],
        force_hits: list[Hit],
        exclude_hits: list[Hit],
        positions: dict[str, str],
    ) -> list[dict[str, Any]]:
        """
        为每个领域生成完整证据链：决策定位 + 原文片段 + 命中规则。
        这是「可解释、可审计」的载体，也是项目匹配的输入。
        """
        role_map: dict[str, str] = {}
        if primary:
            role_map[primary] = "PRIMARY"
        for s in secondary:
            if s != primary:
                role_map.setdefault(s, "SECONDARY")
        for h in exclude_hits:
            role_map.setdefault(h.label, "EXCLUDED")

        chain: list[dict[str, Any]] = []
        for label in sorted(role_map, key=lambda l: (role_map[l] != "PRIMARY", l)):
            label_hits = [h for h in force_hits if h.label == label]
            label_excludes = [h for h in exclude_hits if h.label == label]

            raw_terms = sorted({t for h in label_hits for t in h.matched})
            evidence: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()

            for term in raw_terms:
                loc = self._locate(term, positions)
                snippet = self._extract_sentence(positions.get(loc["span"], ""), term)
                # 同一段同一术语只留一条，避免证据链冗余
                key = (loc["span"], term)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({
                    "text": snippet,
                    "matched_term": term,
                    "span": loc["span"],
                    "source_type": "policy_original_text",
                    "location": loc,
                })

            # 段号去重：同一段的多条证据合并为一条，术语用顿号连接
            merged: list[dict[str, Any]] = []
            for ev in evidence:
                dup = next((m for m in merged if m["span"] == ev["span"]), None)
                if dup:
                    terms = {t for t in dup["matched_term"].split("、") if t}
                    terms.add(ev["matched_term"])
                    dup["matched_term"] = "、".join(sorted(terms))
                else:
                    merged.append(dict(ev))

            chain.append({
                "domain": self._name(label),
                "domain_code": label,
                "decision": role_map[label],
                "evidence": merged,
                "matched_rules": [h.rule_id for h in label_hits],
                "excluded_by_rules": [h.rule_id for h in label_excludes],
            })
        return chain

    @staticmethod
    def _extract_sentence(paragraph: str, term: str, max_len: int = 120) -> str:
        """
        在**段落内**提取包含 term 的句子。

        必须在段内提取而非全文 —— 否则 text 与 span 会错位，
        证据链就失去了精确定位的能力（这是审计追溯的根基）。
        """
        if not paragraph:
            return ""
        idx = paragraph.find(term)
        if idx == -1:
            return paragraph[:max_len]

        # 向前找到最近的句子边界
        breaks = "。！？；\n"
        start = 0
        for i in range(idx - 1, -1, -1):
            if paragraph[i] in breaks:
                start = i + 1
                break

        # 向后找到最近的句子边界
        end = len(paragraph)
        for i in range(idx + len(term), len(paragraph)):
            if paragraph[i] in breaks:
                end = i + 1
                break

        snippet = paragraph[start:end].strip()
        if not snippet:
            snippet = paragraph[max(0, idx - 30): idx + len(term) + 30].strip()
        return snippet[:max_len]

    @staticmethod
    def _locate(term: str, positions: dict[str, str], exclude: set[str] | None = None) -> dict[str, str]:
        """
        定位证据所在段落。返回 term 出现的**最早**段落，保证可复现。
        段号按 P001、P002… 字典序即出现顺序。
        """
        for span_id in sorted(positions):
            if exclude and span_id in exclude:
                continue
            if term in positions[span_id]:
                return {"span": span_id, "source_type": "policy_original_text"}
        return {"span": "", "source_type": "policy_original_text"}

    def _resolve_weight(
        self, labels: set[str], force_hits: list[Hit]
    ) -> tuple[str | None, list[str], str]:
        if not labels:
            return None, [], "NONE"

        for rule in self.weight_cfg.get("rules", []):
            cond = set(rule["when"])
            if cond.issubset(labels):
                primary = rule["primary"]
                if rule.get("secondary") == "*":
                    secondary = sorted(labels - {primary})
                else:
                    secondary = [rule["secondary"]]
                secondary = [s for s in secondary if s in labels and s != primary]
                # 未覆盖的标签并入协同
                secondary += sorted(labels - {primary} - set(secondary))
                return primary, secondary, rule["id"]

        # fallthrough：按「强制规则命中条数」定主赛道，命中多者为主
        counts: dict[str, int] = {}
        for h in force_hits:
            counts[h.label] = counts.get(h.label, 0) + 1
        ordered = sorted(labels, key=lambda l: (-counts.get(l, 0), l))

        if len(ordered) == 1:
            return ordered[0], [], "FALLTHROUGH_SINGLE"
        tie = counts.get(ordered[0], 0) == counts.get(ordered[1], 0)
        return ordered[0], ordered[1:], "FALLTHROUGH_MULTI_TIE" if tie else "FALLTHROUGH_MULTI"

    def _name(self, code: str | None) -> str | None:
        if code is None:
            return None
        return self.label_names.get(code, code)


def self_test() -> None:
    """用三个真实场景验证规则引擎行为"""
    eng = JEVEngine()

    cases = [
        (
            "废弃矿山+地下水监测",
            "本项目开展历史遗留矿山生态修复，配套建设地下水监测井3座，"
            "实施边坡生态治理，并对渣场渗漏进行防渗阻隔。",
            ["MOUNTAIN", "GROUNDWATER", "SOIL"],
        ),
        (
            "仅管网建设（应剔除水环境主标）",
            "对城区实施雨污分流管网建设，新建污水管网12公里，提升管网收集率。"
            "本项目不涉及河湖水体治理内容。",
            ["WATER"],
        ),
        (
            "碳类项目（应能识别 CLIMATE）",
            "支持燃煤锅炉超低排放改造与散煤替代，推动减污降碳协同增效，"
            "开展甲烷排放控制试点。",
            ["AIR", "CLIMATE"],
        ),
    ]

    for name, text, cands in cases:
        r = eng.judge(text, cands)
        print(f"\n=== {name} ===")
        print(f"主赛道: {r['primary_track']}")
        print(f"协同:   {r['secondary_tracks']}")
        print(f"最终标签: {r['final_labels']}")
        print(f"强制命中: {[h['rule_id'] for h in r['audit']['force_hits']]}")
        print(f"排除命中: {[h['rule_id'] for h in r['audit']['exclude_hits']]}")
        print(f"需人工: {r['audit']['needs_human_review']} {r['audit']['review_reasons']}")


if __name__ == "__main__":
    self_test()
