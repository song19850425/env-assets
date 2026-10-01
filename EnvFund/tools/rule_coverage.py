#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则覆盖率分析器 —— 用真实指南回归，找出规则池的漏报点

设计意图：
    规则词表不能凭常识臆造。必须用真实文档跑出「哪些内容没被任何规则覆盖」，
    再有针对性地补锚点词。这个工具就是做这件事的。

用法：
    python tools/rule_coverage.py 指南目录/           # 批量分析
    python tools/rule_coverage.py 指南.txt --verbose  # 单份详细
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.jev.engine import JEVEngine
from app.parser.document import parse_document

# 环保政策高频术语探测表 —— 用于发现「规则没覆盖到但文本里反复出现」的词
PROBE_TERMS = [
    # 水
    "流域", "河道", "河湖", "湖库", "水生态", "水源地", "饮用水", "黑臭", "排污口",
    "雨污分流", "水系连通", "底泥", "疏浚", "滨水", "缓冲带", "生态护岸", "湿地净化",
    "断面", "水质", "富营养化", "水华", "蓝藻", "尾水", "再生水", "中水",
    # 大气
    "VOCs", "挥发性有机物", "氮氧化物", "二氧化硫", "颗粒物", "扬尘", "超低排放",
    "脱硫", "脱硝", "除尘", "散煤", "锅炉", "窑炉", "恶臭", "异味", "油烟",
    "非道路移动机械", "重污染天气", "联防联控",
    # 土壤
    "建设用地", "农用地", "耕地", "受污染耕地", "污染地块", "土壤调查", "风险管控",
    "土壤修复", "场地", "地块", "溯源", "源头管控", "安全利用",
    # 地下水
    "地下水", "监测井", "羽带", "羽状", "防渗", "阻隔", "渗漏", "抽注", "水位",
    # 固废
    "危废", "危险废物", "一般工业固废", "尾矿", "煤矸石", "堆场", "渣场", "废渣",
    "垃圾填埋", "存量垃圾", "封场", "渗滤液", "资源化", "综合利用", "贮存",
    # 农村
    "农村", "村庄", "乡村", "畜禽", "养殖", "面源", "人居环境", "村容村貌", "改厕",
    "农业面源", "秸秆", "农膜",
    # 生态修复
    "矿山", "废弃矿山", "边坡", "山水林田湖草沙", "生态屏障", "国土综合整治",
    "林地", "草地", "退化", "水土流失", "石漠化", "荒漠化", "生物多样性",
    # 气候
    "减污降碳", "碳达峰", "碳中和", "温室气体", "甲烷", "碳排放", "低碳", "气候适应",
    # 能力建设
    "监测能力", "在线监控", "自动监测", "智慧环保", "信息化", "执法能力", "应急监测",
    "遥感", "大数据", "数字化",
    # 核与辐射
    "核", "辐射", "放射性", "电磁",
    # 产业/金融
    "环保产业", "绿色金融", "EOD", "第三方治理", "特许经营", "PPP",
    # 通用机制
    "绩效", "考核", "以奖代补", "补助", "贴息", "专项资金", "中央", "省级",
]


@dataclass
class CoverageReport:
    file: str = ""
    title: str = ""
    section_count: int = 0
    force_hits: list[str] = field(default_factory=list)
    exclude_hits: list[str] = field(default_factory=list)
    matched_labels: list[str] = field(default_factory=list)
    uncovered_terms: Counter = field(default_factory=Counter)
    covered_terms: Counter = field(default_factory=Counter)
    primary_track: str | None = None
    needs_review: bool = False
    status: str = ""            # PASS / EXCLUDED / CONFLICT / REVIEW
    weight_rule: str = ""       # MULTI_TRACK 表示判定为综合类，不裁主赛道

    @property
    def is_multi_track(self) -> bool:
        """综合类文档：主赛道为空是「判定结果」，不是「未裁定」。"""
        return self.weight_rule == "MULTI_TRACK"

    @property
    def is_undecided(self) -> bool:
        """真正的未裁定：既没有主赛道，也不是综合类判定 —— 说明规则没覆盖到。"""
        return not self.primary_track and not self.is_multi_track


def build_rule_vocabulary(engine: JEVEngine) -> set[str]:
    """
    规则库的全部锚点词（不只是本次命中到的）。
    判定「某术语是否被规则覆盖」必须看整个词表，否则会把
    规则里已有、但本次未触发的词误报为漏报。
    """
    vocab: set[str] = set()
    for r in engine.force_rules:
        vocab.update(r.get("any", []))
        vocab.update(r.get("none_strict", []))   # 手段词规则的目标词也是锚点
    for r in engine.exclude_rules:
        vocab.update(r.get("all", []))
        vocab.update(r.get("all_group", []))     # 同义组字段
        vocab.update(r.get("any", []))
        vocab.update(r.get("none", []))
    return vocab


def analyze_coverage(path: Path, engine: JEVEngine, *, allow_municipal=True) -> CoverageReport:
    try:
        doc = parse_document(path)
    except Exception as e:
        r = CoverageReport(file=str(path))
        r.title = f"[解析失败] {e}"
        return r

    text = doc.full_text
    numbered = doc.numbered_text

    verdict = engine.judge(numbered, [], doc.span_index)

    vocab = build_rule_vocabulary(engine)

    def is_covered(term: str) -> bool:
        """术语本身在词表里，或被某个词表锚点包含（如 水源地⊂水源地保护）"""
        if term in vocab:
            return True
        return any(term in anchor for anchor in vocab)

    uncovered = Counter()
    covered = Counter()
    for term in PROBE_TERMS:
        n = text.count(term)
        if not n:
            continue
        if is_covered(term):
            covered[term] = n
        else:
            uncovered[term] = n

    return CoverageReport(
        file=str(path),
        title=doc.title,
        section_count=len(doc.sections),
        force_hits=verdict["jev"]["force_rules"],
        exclude_hits=verdict["jev"]["exclude_rules"],
        matched_labels=verdict["final_labels"],
        uncovered_terms=uncovered,
        covered_terms=covered,
        primary_track=verdict["primary_track"],
        needs_review=verdict["audit"]["needs_human_review"],
        status=verdict["jev"]["status"],
        weight_rule=verdict["jev"].get("weight_rule_applied", "") or "",
    )


SKIP_NAMES = {"README.md", "readme.md", "index.md", "CHANGELOG.md"}


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files = []
    for ext in (".txt", ".md"):
        for f in target.rglob(f"*{ext}"):
            # 排除说明文件与隐藏文件，避免污染语料统计
            if f.name in SKIP_NAMES or f.name.startswith("."):
                continue
            files.append(f)
    return sorted(files)


def print_single(r: CoverageReport, verbose: bool) -> None:
    print(f"\n{'=' * 62}")
    print(f"文档：{r.title}")
    print(f"文件：{r.file}")
    print(f"段数：{r.section_count}")
    track = r.primary_track or ("（综合类 · 不裁主赛道）" if r.is_multi_track else "（未裁定）")
    print(f"主赛道：{track}")
    print(f"命中标签：{('、'.join(r.matched_labels)) or '无'}")
    print(f"强制规则：{len(r.force_hits)} 条  {r.force_hits}")
    print(f"排除规则：{len(r.exclude_hits)} 条  {r.exclude_hits}")
    if r.needs_review:
        print("需人工复核：是")
    if verbose:
        if r.covered_terms:
            print(f"\n已被规则覆盖的术语（{len(r.covered_terms)} 个）：")
            for t, n in r.covered_terms.most_common(20):
                print(f"    {t}  ×{n}")
        if r.uncovered_terms:
            print(f"\n★ 出现但未被任何规则覆盖（{len(r.uncovered_terms)} 个）：")
            for t, n in r.uncovered_terms.most_common(40):
                print(f"    {t}  ×{n}")


def print_summary(reports: list[CoverageReport]) -> None:
    print(f"\n{'=' * 62}")
    print(f"汇总：{len(reports)} 份文档")
    print(f"{'=' * 62}")

    # 三种「主赛道为空」必须分开统计：
    #   undecided  —— 规则没覆盖到，是缺陷信号，必须为 0
    #   multi      —— 综合类文档，判定结果就是不裁，正常
    #   excluded   —— 排除规则明确剔除，正常
    undecided = [r for r in reports if r.is_undecided]
    multi = [r for r in reports if r.is_multi_track]
    excluded = [r for r in reports if not r.primary_track and r.status == "EXCLUDED"]
    review = [r for r in reports if r.needs_review]

    print(f"★ 未裁定主赛道：{len(undecided)} 份   ← 规则未覆盖，应为 0")
    for r in undecided:
        print(f"    - {r.title}  标签={r.matched_labels or '无'}")

    if multi:
        print(f"  综合类不裁主赛道：{len(multi)} 份   ← 判定结果，正常")
        for r in multi:
            print(f"    - {r.title}  覆盖 {len(r.matched_labels)} 个赛道")
    if excluded:
        print(f"  排除规则剔除：{len(excluded)} 份")

    print(f"需人工复核：{len(review)} 份")
    for r in review:
        print(f"    - {r.title}")

    # 全局漏报术语排行
    total_uncovered: Counter = Counter()
    for r in reports:
        total_uncovered.update(r.uncovered_terms)

    print(f"\n★ 全库未被规则覆盖的高频术语 Top 40（补规则优先级依据）")
    print(f"{'-' * 62}")
    if not total_uncovered:
        print("    （无）")
    for t, n in total_uncovered.most_common(40):
        bar = "█" * min(int(n / max(1, max(total_uncovered.values()) / 30)), 30)
        print(f"    {t:<14} {n:>4}  {bar}")

    # 按类别提示补规则建议
    print(f"\n★ 补规则建议")
    print(f"{'-' * 62}")
    for label, terms in suggest_rules(total_uncovered).items():
        if terms:
            print(f"    {label}：建议补充锚点词 {terms}")


CATEGORY_TERMS = {
    "WATER": ["流域", "河道", "河湖", "湖库", "水生态", "水源地", "饮用水", "黑臭",
              "排污口", "雨污分流", "水系连通", "底泥", "疏浚", "滨水", "缓冲带",
              "生态护岸", "断面", "水质", "富营养化", "尾水", "再生水"],
    "AIR": ["VOCs", "挥发性有机物", "氮氧化物", "二氧化硫", "颗粒物", "扬尘",
            "超低排放", "脱硫", "脱硝", "除尘", "散煤", "锅炉", "窑炉", "恶臭",
            "异味", "油烟", "非道路移动机械", "重污染天气"],
    "SOIL": ["建设用地", "农用地", "耕地", "受污染耕地", "污染地块", "土壤调查",
             "风险管控", "土壤修复", "场地", "地块", "溯源", "源头管控", "安全利用"],
    "GROUNDWATER": ["地下水", "监测井", "羽带", "羽状", "防渗", "阻隔", "渗漏",
                    "抽注", "水位"],
    "SOLID": ["危废", "危险废物", "一般工业固废", "尾矿", "煤矸石", "堆场", "渣场",
              "废渣", "垃圾填埋", "存量垃圾", "封场", "渗滤液"],
    "RURAL": ["农村", "村庄", "乡村", "畜禽", "养殖", "面源", "人居环境",
              "村容村貌", "改厕", "农业面源", "秸秆", "农膜"],
    "MOUNTAIN": ["矿山", "废弃矿山", "边坡", "山水林田湖草沙", "生态屏障",
                 "国土综合整治", "林地", "草地", "退化", "水土流失", "石漠化",
                 "荒漠化", "生物多样性"],
    "CLIMATE": ["减污降碳", "碳达峰", "碳中和", "温室气体", "甲烷", "碳排放",
                "低碳", "气候适应"],
    "CAPACITY": ["监测能力", "在线监控", "自动监测", "智慧环保", "信息化",
                 "执法能力", "应急监测", "遥感", "大数据", "数字化"],
    "NUCLEAR": ["核", "辐射", "放射性", "电磁"],
    "INDUSTRY": ["环保产业", "绿色金融", "EOD", "第三方治理", "特许经营"],
}


def suggest_rules(uncovered: Counter) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for label, terms in CATEGORY_TERMS.items():
        hits = [t for t in terms if uncovered.get(t)]
        out[label] = hits
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="规则覆盖率分析器")
    ap.add_argument("target", help="指南文件或目录")
    ap.add_argument("--verbose", "-v", action="store_true", help="显示单份详情")
    ap.add_argument("--json", help="结果写出 JSON 路径")
    ap.add_argument("--rules", help="指定规则库路径")
    args = ap.parse_args()

    engine = JEVEngine(Path(args.rules)) if args.rules else JEVEngine()
    files = collect_files(Path(args.target))
    if not files:
        print(f"未找到 .txt / .md 文件：{args.target}", file=sys.stderr)
        return 1

    reports = []
    for f in files:
        try:
            r = analyze_coverage(f, engine)
            reports.append(r)
            if len(files) == 1 or args.verbose:
                print_single(r, verbose=args.verbose)
        except Exception as e:
            print(f"[跳过] {f}: {e}", file=sys.stderr)

    if len(reports) > 1:
        print_summary(reports)

    if args.json:
        payload = [
            {
                "file": r.file, "title": r.title, "sections": r.section_count,
                "primary_track": r.primary_track, "labels": r.matched_labels,
                "force_hits": r.force_hits, "exclude_hits": r.exclude_hits,
                "needs_review": r.needs_review,
                "uncovered_terms": dict(r.uncovered_terms.most_common()),
                "covered_terms": dict(r.covered_terms.most_common()),
            }
            for r in reports
        ]
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[写出] {args.json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
