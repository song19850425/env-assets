# -*- coding: utf-8 -*-
"""抽取层原型：从检测报告 PDF 里抠出规则引擎能吃的 items[]。

它在三层架构里的位置
--------------------
    文档 → ★语义抽取(本文件) → 容错校验(本文件) → 规则终审(../engine) → 证据链

本原型先用**确定性规则**做结构抽取（表格行、脚注依据、质控记录），
不依赖模型 —— 因为报告的表格结构是规则的，能用代码定的就不要交给模型。
真正需要模型的是「一段自由文字里这句话是什么意思」这类，那部分留接口。

最要紧的一条设计原则
--------------------
**抠不出来就说抠不出来。** 每个字段都可能返回 `pending` 并写明缺什么，
绝不用一个「看起来合理」的值填上。原因：规则引擎的下游判定完全依赖这些字段，
一个猜出来的 `basis` 会让「限值核对」整条规则静默失效 —— 比报错糟得多。

用法
----
    python extract.py sample/sample-report.pdf
    python extract.py sample/sample-report.pdf --json
    python extract.py --score            # 与 ground-truth.json 比对，出准确率
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample"

# 结论措辞归一化。
# ⚠ 不能用子串包含判断 —— 中文里否定式**包含**肯定式：
#     「不符合」含「符合」、「未超标」含「超标」。
#   按「长词优先」逐条精确匹配，第一条命中即返回。
CONCL_RULES: list[tuple[str, str]] = [
    ("未超标", "达标"), ("不超标", "达标"), ("未超限", "达标"),
    ("不符合", "超标"), ("不合格", "超标"), ("未达标", "超标"), ("不达标", "超标"),
    ("超过标准", "超标"), ("超限", "超标"), ("超标", "超标"),
    ("符合", "达标"), ("合格", "达标"), ("达标", "达标"),
    ("未检出", "达标"), ("低于检出限", "达标"), ("低于方法检出限", "达标"),
]
CONCL_RULES.sort(key=lambda x: -len(x[0]))

# 标准号写法 → 库内 ID
STD_ALIAS = {
    "GB 36600-2018": "GB36600-2018", "GB36600-2018": "GB36600-2018",
    "GB/T 14848-2017": "GBT14848-2017", "GBT14848-2017": "GBT14848-2017",
    "GB/T14848-2017": "GBT14848-2017",
    "HJ 605-2011": "HJ605-2011", "HJ605-2011": "HJ605-2011",
    "HJ 639-2012": "HJ639-2012", "HJ639-2012": "HJ639-2012",
    "HJ 535-2009": "HJ535-2009", "HJ 586-2010": "HJ586-2010",
    "HJ 1075-2019": "HJ1075-2019", "HJ 700-2014": "HJ700-2014",
    "HJ 38-2017": "HJ38-2017", "GB 5749-2022": "GB5749-2022",
}

LANDUSE_MAP = [
    (r"第一类用地", "first"), (r"第二类用地", "second"),
]
KIND_MAP = [
    (r"筛选值", "screening"), (r"管制值", "intervention"),
]
# 地下水类别：罗马数字有「Unicode 专用字符」与「ASCII 字母」两套写法，都要认。
# ⚠ 顺序必须是「长的在前」：'Ⅲ类' 里含有 'Ⅱ类' 的子串（第 2~4 个字符是 Ⅱ类），
#   先匹配 Ⅱ 会把 Ⅲ 误判成 Ⅱ。同理 IV 与 V、II 与 I。
CLASS_MAP = [
    ("Ⅲ类|III类", "III"),
    ("Ⅳ类|IV类", "IV"),
    ("Ⅱ类|II类", "II"),
    ("Ⅰ类|I类", "I"),
    ("Ⅴ类|V类", "V"),
]

# 表格数据行：序号 项目 单位 检出限 结果 限值（口径） 结论
ROW_RE = re.compile(
    r"^(?P<seq>\d+)\s+(?P<factor>\S+)\s+(?P<unit>[^\s]+)\s+"
    r"(?P<mdl>[<＜]?[\d.]+|—|-)\s+"
    r"(?P<result>[<＜]?[\d.]+|未检出|—|-)\s+"
    r"(?P<limit>[<＜]?[\d.]+)\s*[（(](?P<limitNote>[^）)]+)[）)]\s+"
    r"(?P<concl>\S+)\s*$"
)


# ------------------------------------------------------------------ 抽文
def extract_text(pdf: Path) -> str:
    try:
        import pypdf
    except ImportError:
        raise SystemExit(
            "[extract] 缺少 pypdf。请用隔离环境安装后运行：\n"
            "    <隔离目录>/Scripts/python.exe -m pip install pypdf") from None
    r = pypdf.PdfReader(str(pdf))
    pages = [(p.extract_text() or "") for p in r.pages]
    if not any(x.strip() for x in pages):
        raise SystemExit(
            "[extract] 这份 PDF 抽不出任何文字 —— 大概率是扫描件。\n"
            "         扫描件需要 OCR / 视觉转录，不在本原型范围内（见 README「边界」）。")
    return "\n".join(pages)


# ------------------------------------------------------------------ 分节
SECTION_RE = re.compile(r"^[一二三四五六七八九十]+、(.+)$", re.M)


def split_sections(text: str) -> list[dict]:
    marks = list(SECTION_RE.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        out.append({"title": m.group(1).strip(), "body": body})
    return out


# ------------------------------------------------------------------ 依据推断
def infer_basis(note_text: str) -> tuple[dict | None, str | None, list[str]]:
    """从脚注里推断「评价依据的标准」与「取哪一列限值」。

    返回 (basis, standard, pending)。
    ⚠ 推断不出来时 basis 为 None 并把原因写进 pending —— 绝不猜一个。
    """
    pending: list[str] = []
    # 标准号
    std = None
    for alias, sid in STD_ALIAS.items():
        if alias in note_text:
            std = sid
            break
    if not std:
        pending.append("脚注里找不到可识别的标准号")

    basis = None
    land = next((v for pat, v in LANDUSE_MAP if re.search(pat, note_text)), None)
    kind = next((v for pat, v in KIND_MAP if re.search(pat, note_text)), None)
    cls = None
    for pat, v in CLASS_MAP:
        if re.search(pat, note_text):
            cls = v
            break
    if land and kind:
        basis = {"landUse": land, "kind": kind}
    elif cls:
        basis = {"classLevel": cls}
    else:
        pending.append("脚注里没写评价口径（用地类型+筛选值/管制值，或地下水类别）")

    return basis, std, pending


# ------------------------------------------------------------------ 行解析
def parse_rows(body: str) -> list[dict]:
    rows = []
    for line in body.split("\n"):
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        g = m.groupdict()
        rows.append({
            "factor": g["factor"],
            "unit": g["unit"],
            "statedMdl": g["mdl"],
            "resultText": g["result"],
            "limitText": f'{g["limit"]}（{g["limitNote"]}）',
            "limitNote": g["limitNote"],
            "conclusionText": g["concl"],
        })
    return rows


def norm_conclusion(t: str) -> tuple[str | None, str | None]:
    """结论归一化。返回 (结论, pending)。长词优先，避免否定式被肯定式吃掉。"""
    t = t.strip()
    for phrase, verdict in CONCL_RULES:
        if phrase in t:
            return verdict, None
    return None, f"结论措辞无法归一化：「{t}」（既不像达标也不像超标）"


def parse_number(s: str) -> tuple[float | None, bool]:
    """返回 (数值, 是否低于检出限)。'<0.05' → (0.05, True)。"""
    s = s.strip()
    lt = s.startswith(("<", "＜"))
    s = s.lstrip("<＜")
    if s in ("—", "-", "未检出", ""):
        return None, False
    try:
        return float(s), lt
    except ValueError:
        return None, False


# ------------------------------------------------------------------ 质控
QC_RE = re.compile(r"运输空白\s*(\d+)\s*个.{0,20}?全程序空白\s*(\d+)\s*个", re.S)
PAR_RE = re.compile(r"平行(?:双样|样)\s*(\d+)\s*个")
SAMPLE_RE = re.compile(r"(\S+?)样品\s*(\d+)\s*个")


def parse_qc(text: str) -> tuple[dict, list[str]]:
    qc: dict = {}
    pending: list[str] = []
    m = QC_RE.search(text)
    if m:
        qc["blankCount"] = int(m.group(1)) + int(m.group(2))
    else:
        pending.append("找不到运输空白/全程序空白数量")
    m = PAR_RE.search(text)
    if m:
        qc["parallelCount"] = int(m.group(1))
    else:
        pending.append("找不到平行样数量")
    total = 0
    for _name, n in SAMPLE_RE.findall(text):
        total += int(n)
    if total:
        qc["sampleCount"] = total
    else:
        pending.append("找不到样品总数")
    return qc, pending


# ------------------------------------------------------------------ 主流程
def extract(pdf: Path) -> dict:
    text = extract_text(pdf)
    items: list[dict] = []
    pending: list[str] = []
    report_id = None
    m = re.search(r"报告编号[:：]\s*(\S+)", text)
    if m:
        report_id = m.group(1)

    for sec in split_sections(text):
        rows = parse_rows(sec["body"])
        if not rows:
            continue
        # 本节脚注：逐条拆开，只用**讲评价依据**的那条做依据推断。
        # ⚠ 不能把「注 1 之后的所有内容」都当依据 —— 后面的注 2 常列**方法**标准号，
        #   混进来会把方法标准误判成评价依据（实测踩过）。
        notes = re.findall(r"注\s*\d+[:：](.+?)(?=注\s*\d+[:：]|\Z)", sec["body"], re.S)
        notes = [re.sub(r"\s+", "", n) for n in notes]
        basis_notes = [n for n in notes if re.search(r"依据|评价|限值|筛选值|管制值|类标准", n)]
        note = " ".join(basis_notes) if basis_notes else ""
        basis, std, bp = infer_basis(note) if note else (
            None, None, ["本节没有可识别的评价依据脚注（注 N 里没写标准号与评价口径）"])

        # 方法标准：本节脚注里出现的**所有**方法号。
        # ⚠ 必须用正则找，不能拿 STD_ALIAS 的键去匹配 —— 别名表只覆盖已入库的标准，
        #   没入库的方法号会「隐身」，于是「本节有几个方法」被判成 1，
        #   抽取层就会把唯一那个绑到所有因子上（端到端测试抓出来的真 bug）。
        STD_NO_RE = re.compile(r"(?:HJ|GB|GB/T|HJ/T)\s*/?T?\s*\d+(?:\.\d+)?\s*[-—]\s*\d{4}")
        found = {re.sub(r"\s+", "", m.group(0)) for m in STD_NO_RE.finditer(" ".join(notes))}
        # 归一化到库内 ID（库里有的用 ID，没有的保留原号）
        norm = {STD_ALIAS.get(f, f): f for f in found}
        methods = sorted(norm.keys())
        method_note = "、".join(sorted(found))
        if len(methods) == 1:
            method_for_item = {"standard": methods[0]}
            method_pending: list[str] = []
        elif len(methods) > 1:
            method_for_item = None
            method_pending = [
                f"本节列出 {len(methods)} 个方法（{method_note}），"
                f"报告未说明各因子分别用哪个 —— 无法确定，不代猜"]
        else:
            method_for_item = None
            method_pending = ["本节脚注里找不到方法标准号"]

        matrix = "soil" if "土壤" in sec["title"] else (
            "groundwater" if "地下水" in sec["title"] else None)
        if matrix is None:
            pending.append(f"分节「{sec['title']}」的介质无法判定（既非土壤也非地下水）")
        for r in rows:
            concl, cp = norm_conclusion(r["conclusionText"])
            result, below_mdl = parse_number(r["resultText"])
            limit, _ = parse_number(r["limitText"].split("（")[0])
            item = {
                "factor": r["factor"],
                "matrix": matrix,
                "standard": std,
                "basis": basis,
                "statedLimit": limit,
                "result": result,
                "conclusion": concl,
                "limitText": r["limitText"],
                "unit": r["unit"],
                "belowMdl": below_mdl,
                "method": method_for_item,
                "pending": [x for x in (bp + method_pending + ([cp] if cp else [])) if x],
            }
            items.append(item)

    qc, qp = parse_qc(text)
    pending.extend(qp)

    return {
        "report": {"id": report_id},
        "items": items,
        "qc": qc,
        "pending": pending,
    }


# ------------------------------------------------------------------ 评分
def score(doc: dict, truth: dict) -> dict:
    """逐字段比对，出准确率。

    比的是**抽取层能不能还原真值**，不是引擎判定对不对 ——
    这两件事要分开测，否则一个字段错会污染整条链的结论。
    """
    got, want = doc["items"], truth["items"]
    fields = ["factor", "matrix", "standard", "statedLimit", "result", "conclusion"]
    detail = []
    hits = {f: 0 for f in fields}
    hits["basis"] = 0
    n = 0
    for i, w in enumerate(want):
        g = got[i] if i < len(got) else {}
        n += 1
        row = {"factor": w["factor"]}
        for f in fields:
            ok = g.get(f) == w.get(f)
            hits[f] += 1 if ok else 0
            if not ok:
                row[f] = f'得 {g.get(f)!r} 应为 {w.get(f)!r}'
        # basis 是嵌套对象，单独比
        bok = g.get("basis") == w.get("basis")
        hits["basis"] += 1 if bok else 0
        if not bok:
            row["basis"] = f'得 {g.get("basis")!r} 应为 {w.get("basis")!r}'
        detail.append(row)

    total = sum(hits.values())
    denom = n * (len(fields) + 1)
    return {
        "items_expected": len(want),
        "items_extracted": len(got),
        "field_hits": hits,
        "field_total": denom,
        "accuracy": round(total / denom * 100, 1) if denom else 0.0,
        "mismatches": [d for d in detail if len(d) > 1],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="检测报告抽取层原型")
    ap.add_argument("pdf", nargs="?", help="报告 PDF")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--score", action="store_true", help="与 ground-truth.json 比对")
    args = ap.parse_args()

    target = Path(args.pdf) if args.pdf else SAMPLE / "sample-report.pdf"
    doc = extract(target)

    if args.score:
        truth = json.loads((SAMPLE / "ground-truth.json").read_text(encoding="utf-8"))
        s = score(doc, truth)
        print(f"抽取项数 {s['items_extracted']} / 真值 {s['items_expected']}")
        print("逐字段命中：")
        for k, v in s["field_hits"].items():
            print(f"   {k:<12} {v}/{s['items_expected']}")
        print(f"字段准确率 {s['accuracy']}%（{sum(s['field_hits'].values())}/{s['field_total']}）")
        if s["mismatches"]:
            print("\n不一致：")
            for m in s["mismatches"]:
                print("   ", json.dumps(m, ensure_ascii=False))
        if doc["pending"]:
            print("\n抽取层自己标出的「未定」：")
            for p in doc["pending"]:
                print("   ?", p)
        return

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"报告编号：{doc['report'].get('id')}")
        print(f"抽出 {len(doc['items'])} 项：")
        for it in doc["items"]:
            flag = "".join("?" for _ in it["pending"])
            print(f"   {it['factor']:<8} {str(it['matrix']):<12} {str(it['standard']):<16} "
                  f"限值={it['statedLimit']} 结果={it['result']} 结论={it['conclusion']} {flag}")
            for p in it["pending"]:
                print(f"        ? {p}")
        print(f"质控：{doc['qc']}")
        if doc["pending"]:
            print("未定：")
            for p in doc["pending"]:
                print("   ?", p)


if __name__ == "__main__":
    main()
