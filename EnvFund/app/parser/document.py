#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档解析层：PDF / OCR 文本 → 带段号的标准化文档

段号（P001、P002…）是一切证据链的基础，必须稳定可复现。
同一份文档两次解析必须得到相同段号，否则审计追溯失效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocSection:
    """文档段落"""
    span: str
    text: str
    page: int = 0
    heading: str = ""


@dataclass
class ParsedDocument:
    title: str
    sections: list[DocSection] = field(default_factory=list)
    issuer: str = ""
    doc_no: str = ""
    source_file: str = ""
    parser: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.sections)

    @property
    def numbered_text(self) -> str:
        return "\n".join(f"[{s.span}] {s.text}" for s in self.sections)

    @property
    def span_index(self) -> dict[str, str]:
        return {s.span: s.text for s in self.sections}


# --------------------------------------------------------------------------
# PDF 解析
# --------------------------------------------------------------------------

def parse_pdf(path: str | Path) -> ParsedDocument:
    """
    解析 PDF。优先 pypdf，失败时回退 pdftotext 风格提示。
    """
    path = Path(path)
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError(
            "解析 PDF 需要 pypdf：pip install pypdf\n"
            "或直接把 OCR 文本存成 .txt 后传入"
        ) from e

    reader = PdfReader(str(path))
    raw = ""
    page_map: list[tuple[int, str]] = []
    for pno, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_map.append((pno, text))
        raw += text + "\n\n"

    doc = parse_text(raw, title=path.stem, source_file=str(path), parser="pypdf")
    # 回填页码：按顺序切分页码区间
    _attach_pages(doc, page_map)
    return doc


def _attach_pages(doc: ParsedDocument, page_map: list[tuple[int, str]]) -> None:
    """按段落文本在页文本中的出现位置回填页码（尽力而为）"""
    for sec in doc.sections:
        probe = sec.text[:30]
        for pno, ptxt in page_map:
            if probe and probe in ptxt:
                sec.page = pno
                break


# --------------------------------------------------------------------------
# 纯文本 / OCR 文本解析
# --------------------------------------------------------------------------

def parse_text(
    raw: str,
    *,
    title: str = "",
    source_file: str = "",
    parser: str = "text",
    min_len: int = 8,
) -> ParsedDocument:
    """
    切段并编号。切分依据：
        空行、中文序号标题（一、二、）、阿拉伯数字标题（1. 2.）、条款编号（（一）（二））
    """
    blocks = re.split(
        r"\n\s*\n"
        r"|\n(?=\s*[一二三四五六七八九十]+、)"
        r"|\n(?=\s*\(?[（(][一二三四五六七八九十]+[）)])"
        r"|\n(?=\s*\d+[.、]\s*\S)",
        raw,
    )

    sections: list[DocSection] = []
    idx = 0
    heading = ""
    for b in blocks:
        text = b.strip()
        if len(text) < min_len:
            continue
        idx += 1
        # 识别标题行（短且无句号）
        if len(text) <= 30 and not re.search(r"[。；，]", text):
            heading = text
        sections.append(DocSection(span=f"P{idx:03d}", text=text, heading=heading))

    doc = ParsedDocument(title=title, sections=sections, source_file=source_file, parser=parser)
    if raw:
        doc.doc_no = _extract_doc_no(raw)
        doc.issuer = _extract_issuer(raw)
    return doc


def _extract_doc_no(raw: str) -> str:
    m = re.search(r"([\u4e00-\u9fa5]{0,4}〔|\(|\[)\s*(\d{4})\s*(〕|\)|\])\s*(\d+)\s*号", raw)
    return m.group(0) if m else ""


def _extract_issuer(raw: str) -> str:
    m = re.search(r"([\u4e00-\u9fa5]{2,12}(厅|部|局|委员会|发改委|财政厅))", raw)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------

def parse_document(path: str | Path, *, title: str = "") -> ParsedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = parse_pdf(path)
    elif suffix in (".txt", ".md"):
        doc = parse_text(
            path.read_text(encoding="utf-8", errors="replace"),
            title=path.stem,
            source_file=str(path),
        )
    else:
        raise ValueError(f"不支持的格式：{suffix}（支持 .pdf / .txt / .md）")

    if title:
        doc.title = title
    return doc


def is_central_or_provincial(title: str, issuer: str = "", text: str = "") -> bool:
    """层级闸门：只放行国家级与省级文档"""
    blob = f"{title}{issuer}"
    if re.search(r"(区|县|市)级|地市|州级|区县", blob):
        return False
    if re.search(r"(国家|生态环境部|财政部|省|自治区|直辖市)", blob):
        return True
    # 标题不规范时，退回正文特征判断
    head = text[:500]
    if re.search(r"(区|县|市)级|地市|州级", head):
        return False
    return bool(re.search(r"(国家|生态环境部|财政部|省|自治区|直辖市)", head))
