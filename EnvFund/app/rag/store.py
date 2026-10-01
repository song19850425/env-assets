#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 检索层：政策知识库

定位说明（重要）：
    单份指南全文可直接进上下文，**不需要 RAG**。
    RAG 的真实价值在「一个项目 → 检索多份政策」这一步。
    因此本模块服务于 matching，而非单文档抽取。

实现取舍：
    默认用 BM25 风格的纯 Python 关键词检索 —— 零依赖、可解释、可复现。
    中文场景下向量检索未必优于词法检索，且词法检索能给出「命中哪些词」，
    这对审计追溯比一个余弦相似度更有用。
    如需向量检索，替换 Retriever 接口即可。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.models import PolicyAnalysis

# 领域同义词扩展：弥合用户口语与政策术语的差距
SYNONYMS: dict[str, list[str]] = {
    "农村生活污水": ["农村污水", "村庄污水", "生活污水治理", "农村环境整治"],
    "黑臭水体": ["黑臭河", "劣五类水体", "水体黑臭"],
    "矿山修复": ["矿山治理", "废弃矿山", "矿山生态修复", "历史遗留矿山"],
    "危废": ["危险废物", "固废", "固体废物"],
    "监测能力": ["监测网络", "智慧环保", "在线监控", "自动监测"],
    "减污降碳": ["碳达峰", "碳中和", "温室气体", "低碳"],
    "水源地": ["饮用水源", "水源保护", "集中式饮用水"],
}

STOPWORDS = set("的了和与及或在是为对按以本项该等一二三四五六七八九十")


@dataclass
class PolicyRecord:
    """政策知识库中的一条记录"""
    doc_id: str
    doc_title: str
    level: str
    primary_track: str = ""
    secondary_tracks: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    support_directions: str = ""
    key_project_types: list[str] = field(default_factory=list)
    excluded_scope: list[str] = field(default_factory=list)
    applicant_requirements: str = ""
    funding_rules: str = ""
    performance_targets: str = ""
    applicable_region: str = ""
    raw_text: str = ""
    analysis: PolicyAnalysis | None = None

    @property
    def searchable_text(self) -> str:
        parts = [
            self.doc_title, self.primary_track, " ".join(self.secondary_tracks),
            self.support_directions, " ".join(self.key_project_types),
            self.applicant_requirements, self.funding_rules,
            self.applicable_region, self.raw_text,
        ]
        return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# 分词
# --------------------------------------------------------------------------

def segment(text: str) -> list[str]:
    """
    中文分词：不引入 jieba 等依赖，用「术语词表 + 二元组」组合策略。
    对政策文本的术语检索足够，且完全可复现。
    """
    terms: list[str] = []

    # 1. 已知同义词表中的长词优先
    for key, syns in SYNONYMS.items():
        for t in [key, *syns]:
            if t in text:
                terms.append(t)

    # 2. 连续中文片段切二元组（bigram），覆盖未登录词
    for chunk in re.findall(r"[\u4e00-\u9fa5]{2,}", text):
        for i in range(len(chunk) - 1):
            bg = chunk[i:i + 2]
            if not any(c in STOPWORDS for c in bg):
                terms.append(bg)

    # 3. 英文/数字串
    terms.extend(re.findall(r"[A-Za-z]{2,}|\d+", text))
    return terms


def expand_query(query: str) -> list[str]:
    """查询扩展：把口语表达映射到政策术语"""
    terms = segment(query)
    for key, syns in SYNONYMS.items():
        if key in query or any(s in query for s in syns):
            terms.extend([key, *syns])
    return list(dict.fromkeys(terms))


# --------------------------------------------------------------------------
# BM25 检索器
# --------------------------------------------------------------------------

class BM25Retriever:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.records: list[PolicyRecord] = []
        self._term_freqs: list[Counter] = []
        self._doc_lens: list[int] = []
        self._avg_len: float = 0.0
        self._df: Counter = Counter()
        self._n: int = 0

    def index(self, records: list[PolicyRecord]) -> None:
        self.records = records
        self._term_freqs, self._doc_lens, self._df = [], [], Counter()
        for r in records:
            tf = Counter(segment(r.searchable_text))
            self._term_freqs.append(tf)
            self._doc_lens.append(sum(tf.values()))
            for t in tf:
                self._df[t] += 1
        self._n = len(records)
        self._avg_len = (sum(self._doc_lens) / self._n) if self._n else 0.0

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 10) -> list[tuple[PolicyRecord, float, list[str]]]:
        """返回 [(记录, 分值, 命中的查询词)]"""
        if not self.records:
            return []

        q_terms = expand_query(query)
        scored: list[tuple[int, float, list[str]]] = []

        for i, tf in enumerate(self._term_freqs):
            score = 0.0
            hits: list[str] = []
            dl = self._doc_lens[i] or 1
            for t in q_terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = self._idf(t)
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                score += idf * (f * (self.k1 + 1)) / denom
                hits.append(t)
            if score > 0:
                scored.append((i, score, sorted(set(hits))))

        scored.sort(key=lambda x: -x[1])
        return [(self.records[i], s, h) for i, s, h in scored[:top_k]]

    def max_score(self, query: str) -> float:
        """查询的理论最高分，用于把分值归一化到 0-1"""
        return sum(self._idf(t) for t in expand_query(query)) or 1.0


# --------------------------------------------------------------------------
# 政策知识库
# --------------------------------------------------------------------------

class PolicyStore:
    """政策知识库：内存实现 + JSON 持久化。生产环境换数据库即可。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.retriever = BM25Retriever()
        self._records: dict[str, PolicyRecord] = {}
        if self.path and self.path.exists():
            self.load()

    def add(self, record: PolicyRecord) -> None:
        self._records[record.doc_id] = record
        self._reindex()

    def add_from_analysis(self, analysis: PolicyAnalysis, raw_text: str = "") -> PolicyRecord:
        src = analysis.source
        f = analysis.fields
        rec = PolicyRecord(
            doc_id=analysis.doc_id or _slug(src.doc_title),
            doc_title=src.doc_title,
            level=src.level,
            primary_track=analysis.primary_track or "",
            secondary_tracks=list(analysis.secondary_tracks),
            labels=[l.value for l in analysis.final_labels],
            support_directions=f.support_directions.text or "",
            key_project_types=[i.text for i in f.key_project_types.items],
            excluded_scope=[i.text for i in f.excluded_scope.items],
            applicant_requirements=f.applicant_requirements.text or "",
            funding_rules=f.funding_rules.text or "",
            performance_targets=f.performance_targets.text or "",
            applicable_region=f.applicable_region.text or "",
            raw_text=raw_text,
            analysis=analysis,
        )
        self.add(rec)
        return rec

    def get(self, doc_id: str) -> PolicyRecord | None:
        return self._records.get(doc_id)

    def all(self) -> list[PolicyRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    def _reindex(self) -> None:
        self.retriever.index(list(self._records.values()))

    # ---- 持久化 ----

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.path
        if not target:
            raise ValueError("未指定持久化路径")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for r in self._records.values():
            d = {k: v for k, v in r.__dict__.items() if k != "analysis"}
            d["analysis"] = json.loads(r.analysis.model_dump_json()) if r.analysis else None
            payload.append(d)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.path
        if not target or not target.exists():
            return
        for d in json.loads(target.read_text(encoding="utf-8")):
            analysis = d.pop("analysis", None)
            rec = PolicyRecord(**d)
            if analysis:
                rec.analysis = PolicyAnalysis(**analysis)
            self._records[rec.doc_id] = rec
        self._reindex()


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", title).strip("-")
    return s[:40] or "policy"
