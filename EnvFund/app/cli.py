#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行工具

用法：
    python -m app.cli -i 指南.txt -t "标题" --issuer "发文单位"
    python -m app.cli -i 指南.pdf --json out.json
    python -m app.cli --match "某县拟建设农村生活污水治理项目，总投资3200万元。" -d data/policy_store.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.document import parse_document
from app.rag.matching import MatchOptions
from app.rag.store import PolicyStore
from app.schemas.models import DecisionRole
from app.services import analyze_document, make_doc_id, match

ROOT = Path(__file__).resolve().parent.parent


def cmd_analyze(args: argparse.Namespace) -> int:
    doc = parse_document(args.input, title=args.title)
    if args.issuer:
        doc.issuer = args.issuer

    try:
        analysis = analyze_document(doc, allow_municipal=args.allow_municipal,
                                    use_llm=not args.offline)
    except ValueError as e:
        print(f"[拒收] {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[失败] {e}", file=sys.stderr)
        return 3

    if args.store:
        store = PolicyStore(ROOT / "data" / "policy_store.json")
        store.add_from_analysis(analysis, doc.full_text)
        store.save()
        print(f"[入库] {analysis.doc_id} → {store.path}", file=sys.stderr)

    text = analysis.model_dump_json(indent=2, exclude_none=True)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"[写出] {args.json}", file=sys.stderr)

    if args.brief:
        _print_brief(analysis)
    else:
        print(text)
    return 0


def _val(x) -> str:
    """枚举取 .value，其余原样"""
    return getattr(x, "value", x)


def _print_brief(a) -> None:
    print(f"文档      {a.source.doc_title}  （{_val(a.source.level)}）")
    print(f"主赛道    {a.primary_track}")
    print(f"协同赛道  {'、'.join(a.secondary_tracks) or '无'}")
    print(f"抽取模式  {a.extraction_mode}")
    print()
    print(f"JEV 校验状态  {_val(a.jev.status)}    置信区间 {_val(a.jev.confidence_band)}")
    print(f"规则命中      {a.jev.force_rule_count} 条")
    print(f"规则冲突      {a.jev.conflict_count} 条")
    print(f"原文证据      {a.jev.evidence_count} 条")
    print(f"LLM 一致      {'是' if a.jev.llm_agreement else '否'}")
    print(f"权重规则      {a.jev.weight_rule_applied}")
    print()
    print("证据链：")
    mark_map = {DecisionRole.PRIMARY: "★", DecisionRole.SECONDARY: "○", DecisionRole.EXCLUDED: "×"}
    for e in a.evidence_chain:
        mark = mark_map.get(e.decision, "?")
        print(f"  {mark} {e.domain}  [{_val(e.decision)}]  规则 {','.join(e.matched_rules) or '—'}")
        for ev in e.evidence[:2]:
            print(f"      {ev.span or '?'}  [{ev.matched_term}]  {ev.text[:56]}")
    if a.needs_human_review:
        print("\n需人工复核：")
        for r in a.review_reasons:
            print(f"  - {r}")


def cmd_match(args: argparse.Namespace) -> int:
    store = PolicyStore(Path(args.db))
    if not len(store):
        print(f"[错误] 政策库为空：{args.db}\n先解析政策并入库：-i 指南.txt --store", file=sys.stderr)
        return 2

    result = match(args.match, store, options=MatchOptions(top_k=args.top_k))
    p = result.project

    print(f"项目画像")
    print(f"  所属领域  {p.domain or '未识别'}")
    print(f"  项目类型  {p.project_type or '未识别'}")
    print(f"  投资规模  {p.investment:g} 万元" if p.investment else "  投资规模  未识别")
    print(f"  所在地    {p.location or '未识别'}")
    print(f"  申报主体  {p.applicant_type or '未识别'}")
    print(f"  项目状态  {p.status}")
    print(f"\n扫描政策 {result.scanned_policy_count} 份，匹配 {len(result.matches)} 条\n")

    for i, m in enumerate(result.matches, 1):
        print(f"{'-' * 58}")
        print(f"[{i}] {m.doc_title}")
        print(f"    匹配度  {m.match_level.value}   ({m.score:.2f})")
        if m.support_direction:
            print(f"    支持方向 {m.support_direction[:60]}")
        if m.funding_type:
            print(f"    资金方式 {m.funding_type[:60]}")
        if m.missing_materials:
            print(f"    缺失材料 {'、'.join(m.missing_materials)}")
        for r in m.reasons:
            if r.kind in ("domain", "negative_list", "region") and "未触发" not in r.detail:
                print(f"    · {r.detail[:70]}")
        for r in m.excluded_reasons:
            print(f"    ✗ {r.detail[:70]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="app.cli", description="环保资金申报智能决策系统 — 命令行工具"
    )
    ap.add_argument("-i", "--input", help="政策文件路径（.txt / .md / .pdf）")
    ap.add_argument("-t", "--title", default="", help="文档标题")
    ap.add_argument("--issuer", default="", help="发文单位")
    ap.add_argument("--json", help="结果写出路径")
    ap.add_argument("--store", action="store_true", help="解析后入库")
    ap.add_argument("--offline", action="store_true", help="强制离线模式")
    ap.add_argument("--brief", action="store_true", help="精简输出（摘要 + 证据链）")
    ap.add_argument("--allow-municipal", action="store_true", help="允许市县级文档")
    ap.add_argument("--match", help="项目描述，执行政策匹配")
    ap.add_argument("-d", "--db", default=str(ROOT / "data" / "policy_store.json"),
                    help="政策库路径")
    ap.add_argument("--top-k", type=int, default=5, help="匹配返回条数")
    args = ap.parse_args()

    if args.match:
        return cmd_match(args)
    if args.input:
        return cmd_analyze(args)

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
