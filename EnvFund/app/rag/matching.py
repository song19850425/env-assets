#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目匹配模块：项目画像 → 政策匹配

设计原则：
    匹配度（score）不是可信度。它是「项目与政策的契合程度」，
    由可拆解的因子加权得出，每个因子的结论都带依据，便于人工复核。

    不匹配也必须给原因（negative_list / region / investment），
    不能只输出一个"不匹配"了事。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.rag.store import PolicyRecord, PolicyStore
from app.schemas.models import (
    DomainCode,
    MatchLevel,
    MatchReason,
    MatchResult,
    PolicyMatch,
    ProjectProfile,
)

# 匹配因子权重（合计 1.0）
WEIGHTS = {
    "domain": 0.40,       # 领域契合 —— 最重要
    "negative": 0.25,     # 负面清单一票否决项
    "region": 0.15,       # 地域范围
    "applicant": 0.10,    # 申报主体
    "funding": 0.10,      # 资金方式与规模
}

LEVEL_THRESHOLDS = [(0.75, MatchLevel.HIGH), (0.45, MatchLevel.MEDIUM), (0.0, MatchLevel.LOW)]

# 领域不契合时的分值上限 —— 无论其他因子多好
DOMAIN_MISMATCH_CAP = 0.35


# --------------------------------------------------------------------------
# 关键词提取
# --------------------------------------------------------------------------

TYPE_PATTERNS = [
    (r"农村(生活)?污水", "农村生活污水治理", DomainCode.RURAL),
    (r"农村(生活)?垃圾", "农村生活垃圾治理", DomainCode.RURAL),
    (r"黑臭水体", "黑臭水体治理", DomainCode.WATER),
    (r"(?:河湖|河道|流域).*(?:治理|修复|整治)", "河湖水环境综合治理", DomainCode.WATER),
    (r"水源地|饮用水源", "饮用水水源地保护", DomainCode.WATER),
    (r"(?:尾矿|矿山|废弃矿)", "矿山生态修复", DomainCode.MOUNTAIN),
    (r"(?:危废|危险废物|固废|垃圾填埋)", "固体废物治理", DomainCode.SOLID),
    (r"(?:土壤|耕地|污染地块|场地)", "土壤污染治理与修复", DomainCode.SOIL),
    (r"地下水", "地下水污染防治", DomainCode.GROUNDWATER),
    (r"(?:VOC|挥发性有机物|超低排放|脱硫|脱硝|扬尘|散煤)", "大气污染防治", DomainCode.AIR),
    (r"(?:监测|在线监控|智慧环保|自动监测)", "环境监测能力建设", DomainCode.CAPACITY),
    (r"(?:减污降碳|碳达峰|碳中和|温室气体)", "减污降碳协同", DomainCode.CLIMATE),
    (r"(?:山水林田湖草沙|生态屏障|边坡生态)", "山水林田湖草沙一体化修复", DomainCode.MOUNTAIN),
]


def extract_profile(user_input: str, *, name: str = "") -> ProjectProfile:
    """
    从自然语言描述中抽取项目画像。
    规则优先、可解释；识别不到的字段留空并提示，绝不猜测。
    """
    profile = ProjectProfile(raw_input=user_input, name=name or user_input[:20])

    # 项目类型与领域
    for pat, ptype, code in TYPE_PATTERNS:
        if re.search(pat, user_input):
            profile.project_type = ptype
            profile.domain_code = code
            profile.domain = _domain_cn(code)
            break

    # 投资额（先匹配"亿元"，避免被"万元"抢先）
    m = re.search(r"(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万)", user_input)
    if m:
        val = float(m.group(1))
        profile.investment = val * 10000 if "亿" in m.group(2) else val

    # 地域：省 / 市 / 县 / 区 / 旗 / 自治州
    # 用非贪婪 + 右边界断言，避免把后半句一起吞进来
    m = re.search(
        r"([\u4e00-\u9fa5]{1,8}?(?:省|自治区|自治州|市|县|区|旗))"
        r"(?=[\u4e00-\u9fa5，。、；：,.]|$)",
        user_input,
    )
    if m:
        loc = m.group(1)
        # 排除"本项目""项目所在"这类误匹配
        if not re.search(r"(项目|实施|建设|申报|本次|该)", loc):
            profile.location = loc
            profile.region_level = (
                "省级" if loc.endswith(("省", "自治区"))
                else "市级" if loc.endswith(("市", "自治州"))
                else "县级"
            )

    # 地域兜底：从"某县/某市/某省"这类占位地名提取
    if not profile.location:
        m = re.search(r"(某[县市区省旗])", user_input)
        if m:
            profile.location = m.group(1)
            profile.region_level = (
                "省级" if m.group(1).endswith("省")
                else "市级" if m.group(1).endswith("市")
                else "县级"
            )

    # 项目状态
    m = re.search(r"(拟申报|已申报|申报中|储备|入库|待申报)", user_input)
    if m:
        profile.status = m.group(1)

    # 申报主体类型
    m = re.search(r"(政府|企业|事业单位|第三方治理单位|环保公司|科研院所)", user_input)
    if m:
        profile.applicant_type = m.group(1)

    return profile


def _domain_cn(code: DomainCode) -> str:
    return {
        DomainCode.WATER: "水生态水环境",
        DomainCode.AIR: "大气污染防治",
        DomainCode.SOIL: "土壤污染防治",
        DomainCode.GROUNDWATER: "地下水污染防治",
        DomainCode.SOLID: "固体废物污染治理",
        DomainCode.RURAL: "农村生态环境整治",
        DomainCode.MOUNTAIN: "山水林田湖草沙生态修复",
        DomainCode.CLIMATE: "应对气候变化/减污降碳协同",
        DomainCode.CAPACITY: "环境监测能力建设/智慧环保",
        DomainCode.NUCLEAR: "核与辐射安全",
        DomainCode.INDUSTRY: "环保产业/绿色金融配套",
    }.get(code, "")


# --------------------------------------------------------------------------
# 因子评估
# --------------------------------------------------------------------------

def _eval_domain(
    profile: ProjectProfile, record: PolicyRecord, query: str, hits: list[str]
) -> tuple[float, list[MatchReason]]:
    """
    领域契合度评估。

    设计要点：**词面重叠不等于领域契合。**
    「农村生活污水」与「水污染防治」共享"污水""治理"等词，但分属不同资金赛道。
    因此仅靠检索词重叠只能给很低的分，避免假阳性把不相关项目推荐出去。
    """
    reasons: list[MatchReason] = []
    if not profile.domain_code:
        return 0.0, [MatchReason(kind="domain", detail="项目领域未能识别，无法判断领域契合度")]

    code = profile.domain_code.value
    if code == record.primary_track and record.primary_track:
        return 1.0, [MatchReason(
            kind="domain", detail=f"项目领域命中政策主赛道：{record.primary_track}",
            evidence=record.labels,
        )]
    if code in record.labels:
        return 0.8, [MatchReason(
            kind="domain", detail=f"项目领域命中政策标签：{_domain_cn(profile.domain_code)}",
            evidence=record.labels,
        )]

    # 跨领域：只在「项目领域属于政策协同赛道」时给中等分
    if profile.domain_code in _secondary_of(record):
        return 0.5, [MatchReason(
            kind="domain", detail="项目领域属该政策的协同赛道，非主线支持方向",
            evidence=record.secondary_tracks,
        )]

    # 仅词面重叠 —— 不足以支撑领域契合，给低分并明示
    if hits:
        return 0.15, [MatchReason(
            kind="domain",
            detail="领域不同，仅检索词有重叠（不构成领域契合）",
            evidence=hits[:6],
        )]

    return 0.0, [MatchReason(kind="domain", detail="领域与政策不相关")]


def _secondary_of(record: PolicyRecord) -> set[DomainCode]:
    """把政策的协同赛道名反查回 DomainCode"""
    cn_to_code = {
        "水生态水环境": DomainCode.WATER,
        "大气污染防治": DomainCode.AIR,
        "土壤污染防治": DomainCode.SOIL,
        "地下水污染防治": DomainCode.GROUNDWATER,
        "固体废物污染治理": DomainCode.SOLID,
        "农村生态环境整治": DomainCode.RURAL,
        "山水林田湖草沙生态修复": DomainCode.MOUNTAIN,
        "应对气候变化/减污降碳协同": DomainCode.CLIMATE,
        "环境监测能力建设/智慧环保": DomainCode.CAPACITY,
        "核与辐射安全": DomainCode.NUCLEAR,
        "环保产业/绿色金融配套": DomainCode.INDUSTRY,
    }
    return {cn_to_code[t] for t in record.secondary_tracks if t in cn_to_code}


def _eval_negative(
    profile: ProjectProfile, record: PolicyRecord
) -> tuple[float, list[MatchReason]]:
    """负面清单是硬约束：命中即大幅扣分，不是简单加权"""
    excluded: list[MatchReason] = []
    probe = f"{profile.project_type} {profile.raw_input}"

    for item in record.excluded_scope:
        # 从负面清单条目中抽取关键名词做比对
        for kw in _negative_keywords(item):
            if kw and kw in probe:
                excluded.append(MatchReason(
                    kind="negative_list",
                    detail=f"触发政策负面清单：{item[:60]}",
                    evidence=[kw],
                ))
                break

    if excluded:
        return 0.0, excluded
    return 1.0, [MatchReason(kind="negative_list", detail="未触发负面清单")]


_NEG_KW = re.compile(
    r"(城镇[^，。；]{0,8}|城市[^，。；]{0,8}|工业企业[^，。；]{0,10}|"
    r"单纯[^，。；]{0,10}|管网|清淤|绿化|土方|资源化工厂|技改|节能)"
)


def _negative_keywords(item: str) -> list[str]:
    """从负面清单文本中提取判定关键词"""
    if not re.search(r"(不予支持|不纳入|不属于|不得申报|禁止|除外)", item):
        return []
    return [m.group(0).strip() for m in _NEG_KW.finditer(item)]


def _eval_region(profile: ProjectProfile, record: PolicyRecord) -> tuple[float, list[MatchReason]]:
    region_text = record.applicable_region or ""
    if not region_text:
        return 0.5, [MatchReason(kind="region", detail="政策未明确适用地域，按中性处理")]
    if profile.location and profile.location in region_text:
        return 1.0, [MatchReason(kind="region", detail=f"项目所在地 {profile.location} 在适用范围内")]
    if re.search(r"(全国|中央|各省|各地)", region_text):
        return 1.0, [MatchReason(kind="region", detail="政策适用范围为全国")]
    if profile.location:
        return 0.2, [MatchReason(
            kind="region", detail=f"项目所在地 {profile.location} 未明确在适用范围内",
            evidence=[region_text[:40]],
        )]
    return 0.5, [MatchReason(kind="region", detail="项目所在地未提供")]


def _eval_applicant(profile: ProjectProfile, record: PolicyRecord) -> tuple[float, list[MatchReason]]:
    req = record.applicant_requirements or ""
    if not req:
        return 0.5, [MatchReason(kind="applicant", detail="政策未明确申报主体要求")]
    if not profile.applicant_type:
        return 0.5, [MatchReason(kind="applicant", detail="项目未提供申报主体类型")]
    if profile.applicant_type in req:
        return 1.0, [MatchReason(kind="applicant", detail=f"申报主体「{profile.applicant_type}」符合要求")]
    if any(k in req for k in ("人民政府", "生态环境部门", "项目实施单位")):
        return 0.7, [MatchReason(kind="applicant", detail="申报主体需为政府部门或其授权单位，需确认")]
    return 0.3, [MatchReason(
        kind="applicant", detail=f"申报主体要求：{req[:50]}", evidence=[req[:60]],
    )]


def _eval_funding(profile: ProjectProfile, record: PolicyRecord) -> tuple[float, list[MatchReason]]:
    rules = record.funding_rules or ""
    if not rules:
        return 0.5, [MatchReason(kind="funding", detail="政策未明确资金补助方式")]
    reasons = [MatchReason(kind="funding", detail=f"资金方式：{rules[:50]}", evidence=[rules[:80]])]
    return 0.7, reasons


# --------------------------------------------------------------------------
# 匹配主流程
# --------------------------------------------------------------------------

@dataclass
class MatchOptions:
    top_k: int = 10
    min_score: float = 0.15
    include_unmatched: bool = True


def match_project(
    profile: ProjectProfile,
    store: PolicyStore,
    options: MatchOptions | None = None,
) -> MatchResult:
    """
    项目 → 政策匹配。
    先做 BM25 召回，再逐因子打分，最后给出带依据的匹配理由。
    """
    opts = options or MatchOptions()
    query = " ".join(filter(None, [
        profile.project_type, profile.domain, profile.raw_input,
    ]))

    candidates = store.retriever.search(query, top_k=max(opts.top_k, 20))
    max_score = store.retriever.max_score(query)

    matches: list[PolicyMatch] = []
    for record, raw_score, hits in candidates:
        norm = min(raw_score / max_score, 1.0) if max_score else 0.0

        d_score, d_reasons = _eval_domain(profile, record, query, hits)
        n_score, n_reasons = _eval_negative(profile, record)
        r_score, r_reasons = _eval_region(profile, record)
        a_score, a_reasons = _eval_applicant(profile, record)
        f_score, f_reasons = _eval_funding(profile, record)

        score = (
            WEIGHTS["domain"] * d_score
            + WEIGHTS["negative"] * n_score
            + WEIGHTS["region"] * r_score
            + WEIGHTS["applicant"] * a_score
            + WEIGHTS["funding"] * f_score
        )
        # 检索相关性作为微调（不改变量级，只体现文本贴近度）
        score = round(min(score * 0.9 + norm * 0.1, 1.0), 4)

        # 领域不契合 → 分值封顶，不给假阳性
        # 领域是本系统判断"该不该申请这份资金"的第一性依据
        if d_score < 0.5:
            score = min(score, DOMAIN_MISMATCH_CAP)

        # 领域完全不搭 → 直接判不匹配
        if d_score == 0.0:
            score = 0.0

        level = next(lv for th, lv in LEVEL_THRESHOLDS if score >= th)
        if score < opts.min_score:
            level = MatchLevel.NONE

        excluded = [r for r in n_reasons if r.kind == "negative_list" and "未触发" not in r.detail]
        matches.append(PolicyMatch(
            doc_id=record.doc_id,
            doc_title=record.doc_title,
            match_level=level,
            score=score,
            support_direction=record.support_directions[:200],
            funding_type=record.funding_rules[:200],
            applicant_requirement=record.applicant_requirements[:200],
            conditions=[c for c in [
                record.applicable_region and f"适用区域：{record.applicable_region}",
                record.performance_targets and f"绩效要求：{record.performance_targets[:80]}",
            ] if c],
            missing_materials=_missing_materials(profile, record, level),
            reasons=d_reasons + n_reasons + r_reasons + a_reasons + f_reasons,
            excluded_reasons=excluded,
        ))

    matches.sort(key=lambda m: -m.score)
    if not opts.include_unmatched:
        matches = [m for m in matches if m.match_level != MatchLevel.NONE]

    return MatchResult(
        project=profile,
        matches=matches[:opts.top_k],
        scanned_policy_count=len(store),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )


def _missing_materials(
    profile: ProjectProfile, record: PolicyRecord, level: MatchLevel
) -> list[str]:
    """列出为完成申报还需补的材料 —— 按缺失的画像字段推导"""
    if level == MatchLevel.NONE:
        return []
    missing: list[str] = []
    if not profile.investment:
        missing.append("项目投资概算（政策需核定投资规模与补助比例）")
    if not profile.applicant_type:
        missing.append("申报主体资质证明")
    if not profile.raw_input:
        missing.append("项目实施方案或可行性研究报告")
    if level == MatchLevel.HIGH:
        missing.append("项目绩效目标表")
        missing.append("用地/环评等前置要件")
    return missing
