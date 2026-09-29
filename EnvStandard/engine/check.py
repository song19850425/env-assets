# -*- coding: utf-8 -*-
"""EnvStandard 规则终审引擎（最小可用版）

定位
----
这是「标准引用核查」的工作流底座：输入一份**报告摘要 JSON**，
输出**逐条带出处的核查结论**。

设计原则（照抄 policy-doc-rule-engine 技能的三层架构，本文件只做第三层）
--------------------------------------------------------------------
    文档 → 语义抽取(LLM) → 容错校验 → **规则终审(本文件)** → 证据链

  · 规则终审层**只吃字面与数值比对，绝不调用模型**。
    规则层一旦靠语义判断，它就成了模型的马甲，二次校验形同虚设。
  · 判定依据全部来自 `../data/standards/*.json`，不另存一份数值。
  · 输出**可核查状态**（PASS/FAIL + 命中规则 + 证据），不输出「可信度 95%」这类空话。
  · 判定不出来时说「无法判定」，不猜。

用法
----
    python check.py samples/report-bad.json
    python check.py samples/*.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STD_DIR = HERE.parent / "data" / "standards"
RULES_PATH = HERE / "rules.json"


# ------------------------------------------------------------------ 单位换算
# 同量纲不同量级的单位必须能比，否则「μg/kg 的测定下限 vs mg/kg 的限值」
# 这种最常见的场景反而判不了。不可通约时才报无法判定。
#   key 的 μ 统一用 U+03BC 归一化后再查（PDF 里 U+00B5 / U+03BC 会混用）
_UNITS: dict[str, tuple[str, float]] = {
    # (量纲, 换算到该量纲基准值的系数)
    # —— 质量/质量，基准 mg/kg
    "mg/kg": ("mass/mass", 1.0),
    "ug/kg": ("mass/mass", 0.001),
    "g/kg": ("mass/mass", 1000.0),
    "ng/kg": ("mass/mass", 1e-6),
    # —— 质量/体积，基准 mg/L
    "mg/l": ("mass/vol", 1.0),
    "ug/l": ("mass/vol", 0.001),
    "g/l": ("mass/vol", 1000.0),
    "ng/l": ("mass/vol", 1e-6),
    # —— 质量/体积（气），基准 mg/m3
    "mg/m3": ("mass/vol-gas", 1.0),
    "mg/m³": ("mass/vol-gas", 1.0),
    "ug/m3": ("mass/vol-gas", 0.001),
    "ug/m³": ("mass/vol-gas", 0.001),
    "ng/m³": ("mass/vol-gas", 1e-6),
    # —— 摩尔分数，基准 μmol/mol
    "umol/mol": ("mole-fraction", 1.0),
    "mmol/mol": ("mole-fraction", 1000.0),
}


def _same_number(a, b) -> bool:
    """数值比较，不是字符串比较。

    ⚠ 「报告写 1.0，标准是 1」是**相等**，不是抄错。
    用 str() 比会把 1 vs 1.0、20 vs 20.0 全判成错 —— 端到端测试抓出来的假阳性。
    """
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def norm_units(u: str) -> str:
    """归一化单位串：μ 两种码位统一、全角转半角、去空白、小写。"""
    if not u:
        return ""
    s = u.strip()
    s = s.replace("\u00b5", "\u03bc").replace("\u03bc", "u")   # μ → u
    s = s.replace("³", "3").replace(" ", "").lower()
    return s


def to_base(value: float, units: str):
    """换算到同量纲基准值。返回 (量纲, 基准值) 或 None（不可通约/未知）。"""
    info = _UNITS.get(norm_units(units))
    if not info:
        return None
    dim, factor = info
    return dim, value * factor


def _base_label(dim: str) -> str:
    return {"mass/mass": "mg/kg", "mass/vol": "mg/L",
            "mass/vol-gas": "mg/m³", "mole-fraction": "μmol/mol"}.get(dim, dim)


# ------------------------------------------------------------------ 载入标准
class Standards:
    def __init__(self, std_dir: Path):
        self.by_id: dict[str, dict] = {}
        for p in sorted(std_dir.glob("*.json")):
            if p.name in {"index.json", "pollutant-ids.json"}:
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            self.by_id[d["standardId"]] = d

    def has(self, sid: str) -> bool:
        return sid in self.by_id

    def row(self, sid: str, factor: str) -> dict | None:
        """在表格式标准的 limits[] 里按名称找行。找不到返回 None（不猜）。"""
        std = self.by_id.get(sid)
        if not std:
            return None
        for r in std.get("limits") or []:
            if r.get("name") == factor:
                return r
        return None

    def value(self, sid: str, key: str) -> dict | None:
        std = self.by_id.get(sid)
        if not std:
            return None
        return (std.get("values") or {}).get(key)

    def source_of(self, sid: str) -> dict:
        return (self.by_id.get(sid) or {}).get("source") or {}

    # ---- 取值口径：把「依据字段」翻译成具体列 ----
    @staticmethod
    def resolve_column(item: dict) -> tuple[str | None, str]:
        """返回 (列名, 人话说明)。取不到列名时返回 (None, 原因)。"""
        b = item.get("basis") or {}
        matrix = item.get("matrix")
        if "landUse" in b and "kind" in b:
            col = {"first": "First", "second": "Second"}.get(b["landUse"])
            kind = {"screening": "screening", "intervention": "intervention"}.get(b["kind"])
            if not col or not kind:
                return None, f"未识别的用地/判定口径：{b}"
            label = {"first": "第一类用地", "second": "第二类用地"}[b["landUse"]]
            label += {"screening": "筛选值", "intervention": "管制值"}[b["kind"]]
            return f"{kind}{col}", label
        if "classLevel" in b:
            lv = b["classLevel"]
            if lv not in {"I", "II", "III", "IV", "V"}:
                return None, f"未识别的类别：{lv}"
            return f"class{lv}", f"{lv} 类"
        return None, "缺少 basis（landUse+kind 或 classLevel），无法定位限值列"


# ------------------------------------------------------------------ 引擎
class Engine:
    def __init__(self, stds: Standards, rules: dict):
        self.stds = stds
        self.rules = rules["rules"]
        self.severity = rules.get("severity", {})

    # ---- 单条规则的实现：全部是字面/数值比对 ----
    def _check_standard_exists(self, item):
        sid = item.get("standard")
        # ⚠ 必须区分两种「取不到」：
        #   sid 为空  → 抽取层没抽到，是**未定**，不是错（报错会掩盖真正的缺失）
        #   sid 有值但不在库 → 报告引用了一个无法核对的号，这才是**错**
        if not sid:
            return None, "未声明评价依据标准号（抽取层未取到）", None
        if not self.stds.has(sid):
            return False, f"标准 {sid} 不在已入库标准中（无法核对，按未核实处理）", None
        return True, "", None

    def _check_basis_declared(self, item):
        col, label = Standards.resolve_column(item)
        if not col:
            return False, label, None
        return True, "", label

    def _check_limit_matches(self, item):
        sid, factor = item.get("standard"), item.get("factor")
        if not sid:
            return None, "未声明评价依据标准号，无法核对限值", None
        row = self.stds.row(sid, factor)
        if row is None:
            return None, f"{sid} 的表中找不到「{factor}」，无法核对限值", None
        col, label = Standards.resolve_column(item)
        if not col:
            return None, label, None
        true_val = row.get(col)
        if true_val is None:
            return None, f"{sid} 的「{factor}」没有 {label} 列", None
        stated = item.get("statedLimit")
        if stated is None:
            return None, "报告未写明限值", None
        src = self.stds.source_of(sid)
        ev = {
            "标准": sid, "因子": factor, "列": label,
            "标准值": true_val, "报告写的": stated,
            "出处": f"{sid} {src.get('table', '')}（序号 {row.get('seq', '?')}）",
        }
        if not _same_number(true_val, stated):
            return False, f"限值抄错：报告写 {stated}，标准是 {true_val}（{label}）", ev
        return True, "", ev

    def _check_conclusion_consistent(self, item):
        sid, factor = item.get("standard"), item.get("factor")
        if not sid:
            return None, "未声明评价依据标准号，无法核对结论", None
        row = self.stds.row(sid, factor)
        if row is None:
            return None, f"{sid} 的表中找不到「{factor}」，无法核对结论", None
        col, label = Standards.resolve_column(item)
        if not col:
            return None, label, None
        limit = row.get(col)
        result = item.get("result")
        concl = item.get("conclusion")
        if limit is None or result is None or concl is None:
            return None, "限值/检测值/结论三者不齐，无法判定", None
        try:
            over = float(result) > float(limit)
        except (TypeError, ValueError):
            return None, f"限值或检测值不是数值（{limit!r} / {result!r}），无法判定", None
        expect = "超标" if over else "达标"
        ev = {"标准": sid, "因子": factor, "列": label, "限值": limit,
              "检测值": result, "报告结论": concl, "应为": expect}
        if concl != expect:
            return False, (f"结论与数据矛盾：检测值 {result} 对限值 {limit}"
                           f"（{label}）应为「{expect}」，报告写「{concl}」"), ev
        return True, "", ev

    def _check_loq_below_limit(self, item):
        """跨标准判定：方法测定下限必须低于所判定的限值。

        ⚠ 单位不同不能直接比大小 —— 拿 μg/L 的测定下限去比 mg/kg 的限值，
        数值上「成立」但结论毫无意义。遇到单位不一致必须报「无法判定」，
        并提示这可能本身就是个错误（如给土壤样品引了水质方法）。
        """
        method = item.get("method") or {}
        msid = method.get("standard")
        if not msid:
            return None, "未声明所用方法标准", None
        if not self.stds.has(msid):
            return None, f"方法标准 {msid} 未入库，无法核对测定下限", None
        mode = method.get("mode")  # scan / sim（仅对多方式方法有意义）
        row = self.stds.row(msid, item.get("factor"))
        if row is None:
            return None, f"{msid} 中没有「{item.get('factor')}」的检出限数据", None

        # 列名有两套约定，都要认：
        #   多方式方法（HJ 639 吹扫捕集/GC-MS）→ loqScan / loqSim
        #   单方式方法（HJ 605 只有全扫描）    → loq
        key = {"scan": "loqScan", "sim": "loqSim"}.get(mode or "")
        note = ""
        if key is None or row.get(key) is None:
            if row.get("loq") is not None:
                if mode:
                    note = f"（{msid} 为单方式方法，只有一档测定下限，已按 loq 取值）"
                key = "loq"
            else:
                return None, ("未声明方法方式（mode 应为 scan 或 sim），"
                              f"且 {msid} 的该因子没有单一测定下限列，无法确定取哪一档"), None
        loq = row.get(key)
        sid = item.get("standard")
        lrow = self.stds.row(sid, item.get("factor"))
        col, label = Standards.resolve_column(item)
        if not lrow or not col:
            return None, "无法定位所判定的标准限值", None
        limit = lrow.get(col)

        # ---- 单位核对：行级 units 优先于标准级；同量纲换算后比较 ----
        m_units = (self.stds.by_id.get(msid) or {}).get("units") or ""
        l_units = lrow.get("units") or (self.stds.by_id.get(sid) or {}).get("units") or ""
        conv_note = ""
        try:
            loq_f, lim_f = float(loq), float(limit)
        except (TypeError, ValueError):
            return None, f"测定下限或限值不是数值（{loq!r} / {limit!r}）", None

        mb = to_base(loq_f, m_units)
        lb = to_base(lim_f, l_units)
        if mb and lb and mb[0] == lb[0]:
            if norm_units(m_units) != norm_units(l_units):
                conv_note = (f"（已按同量纲换算：{loq} {m_units} = "
                             f"{mb[1]:g} {_base_label(mb[0])}，"
                             f"{limit} {l_units} = {lb[1]:g} {_base_label(lb[0])}）")
            loq_cmp, lim_cmp = mb[1], lb[1]
        elif m_units and l_units and mb is None or lb is None:
            return None, (f"单位无法换算，拒绝比较：方法 {msid} 是 {m_units}，"
                          f"判定标准 {sid} 是 {l_units}。"
                          f"请先确认方法是否适用于该介质 —— 给 {item.get('matrix', '该')} 样品"
                          f"引一个 {m_units} 的方法，本身可能就是错的"), {
                "方法单位": m_units, "限值单位": l_units,
            }
        else:
            return None, (f"单位不一致且不可通约，无法比较：方法 {m_units} vs 判定标准 {l_units}"), {
                "方法单位": m_units, "限值单位": l_units,
            }

        src_m = self.stds.source_of(msid)
        ev = {"方法标准": msid, "方式": mode or "—", "测定下限": loq, "单位": m_units,
              "判定标准": sid, "限值": limit, "限值列": label,
              "方法出处": f"{msid} {src_m.get('table', '')}（序号 {row.get('seq', '?')}）"}
        if loq_cmp >= lim_cmp:
            return False, (f"方法能力不足：测定下限 {loq} {m_units} ≥ 限值 {limit}"
                           f" {l_units}（{label}），该指标测不出来，必须改用能力更强的方式"
                           + note + conv_note), ev
        return True, "", ev

    def _check_holding_within_limit(self, item):
        std = item.get("holdingStandard")
        hours = item.get("holdingHours")
        if not std or hours is None:
            return None, "未声明保存时限标准或实际时长", None
        if not self.stds.has(std):
            return None, f"保存时限标准 {std} 未入库，无法核对", None
        # 按小时或天取限值（两者只应有一个存在）
        cand = []
        for key, mul in (("storage-hours-max", 1), ("storage-days-max", 24)):
            v = self.stds.value(std, key)
            if v:
                cand.append((key, v, float(v["value"]) * mul))
        if not cand:
            return None, f"{std} 未收录保存时限参数", None
        key, v, limit_h = cand[0]
        ev = {"标准": std, "实际保存": f"{hours} h", "标准规定": f"{v['value']} {v['units']}",
              "出处": v.get("citation", "")}
        if float(hours) > limit_h:
            return False, (f"样品保存超期：实际 {hours} h，标准规定 {v['value']} {v['units']}"
                           f"（≈{limit_h:g} h）"), ev
        return True, "", ev

    def _check_qc_blank_required(self, item):
        qc = item.get("qc") or {}
        n = qc.get("blankCount")
        if n is None:
            return None, "未记录空白数量", None
        ev = {"空白数量": n}
        if int(n) < 1:
            return False, "该批样品没有任何空白 —— 无法判断是否存在系统污染", ev
        return True, "", ev

    def _check_qc_parallel_ratio(self, item):
        qc = item.get("qc") or {}
        p, total = qc.get("parallelCount"), qc.get("sampleCount")
        if p is None or not total:
            return None, "未记录平行样数量或样品总数", None
        # 判据从标准取：优先 HJ1075，其次 HJ/T167
        limit_pct, src = None, ""
        for sid, key in (("HJ1075-2019", "parallel-ratio-min"),
                         ("HJT167-2004", "parallel-ratio-min"),
                         ("GBT18883-2022", "parallel-ratio-min")):
            v = self.stds.value(sid, key)
            if v:
                limit_pct, src = float(v["value"]), v.get("citation", "")
                break
        if limit_pct is None:
            return None, "库中未收录平行样比例判据", None
        pct = float(p) / float(total) * 100
        ev = {"平行样": p, "样品总数": total, "实际比例": f"{pct:.1f}%",
              "标准下限": f"{limit_pct:g}%", "出处": src}
        if pct < limit_pct:
            return False, f"平行样比例不足：实际 {pct:.1f}%，标准下限 {limit_pct:g}%", ev
        return True, "", ev

    # ---- 派发 ----
    PER_ITEM = {"standard_exists", "basis_declared", "limit_matches",
                "conclusion_consistent", "loq_below_limit"}
    BATCH_LEVEL = {"holding_within_limit", "qc_blank_required", "qc_parallel_ratio"}

    def run(self, doc: dict) -> dict:
        findings = []
        for rule in self.rules:
            fn = getattr(self, "_check_" + rule["check"], None)
            if fn is None:
                findings.append({
                    "rule": rule["id"], "name": rule["name"], "severity": "warn",
                    "verdict": "UNKNOWN", "detail": f"引擎未实现该检查项：{rule['check']}",
                    "evidence": None, "where": "—", "item_index": None,
                })
                continue

            if rule["check"] in self.BATCH_LEVEL:
                targets = [(None, doc)]
            elif rule["check"] in self.PER_ITEM:
                targets = list(enumerate(doc.get("items") or []))
            else:
                targets = [(None, doc)]

            for idx, item in targets:
                ok, detail, ev = fn(item)
                if ok is True:
                    continue
                # ⚠ 把抽取层标出的「为什么取不到」带过来。
                #   否则引擎只会说「未声明所用方法标准」，而抽取层其实知道原因
                #   （「报告列出 3 个方法却没说是哪个因子用哪个」）——
                #   丢掉这条，人工复核就得多查一轮。
                if ok is None and idx is not None and item.get("pending"):
                    detail = f'{detail}｜抽取层备注：{"；".join(item["pending"])}'
                # ⚠ 定位必须带 item 下标：同一因子可能在一份报告里出现多次
                #   （如土壤苯与地下水苯），只按因子名定位会互相覆盖。
                if idx is None:
                    where = "整批"
                else:
                    where = item.get("factor") or f"第 {idx + 1} 项"
                    matrix = item.get("matrix")
                    if matrix:
                        where = f"{where}（{matrix}）"
                findings.append({
                    "rule": rule["id"], "name": rule["name"],
                    "severity": rule["severity"],
                    "verdict": "UNDETERMINED" if ok is None else "FAIL",
                    "detail": detail, "evidence": ev,
                    "where": where, "item_index": idx,
                })

        fails = [f for f in findings if f["verdict"] == "FAIL" and f["severity"] == "error"]
        undet = [f for f in findings if f["verdict"] == "UNDETERMINED"]
        status = "FAIL" if fails else ("PARTIAL" if undet else "PASS")
        # 可核查状态，不是「可信度百分比」
        band = "LOW" if fails else ("MEDIUM" if undet else "HIGH")
        return {
            "report": doc.get("report", {}),
            "status": status,
            "confidence_band": band,
            "checked_rules": len(self.rules),
            "error_count": len(fails),
            "undetermined_count": len(undet),
            "findings": findings,
        }


# ------------------------------------------------------------------ 输出
def render(result: dict) -> str:
    L = []
    rep = result["report"]
    L.append(f"报告：{rep.get('id', '?')}　{rep.get('title', '')}")
    L.append(f"状态：{result['status']}　可核查程度：{result['confidence_band']}"
             f"　错误 {result['error_count']} · 无法判定 {result['undetermined_count']}")
    L.append("")
    if not result["findings"]:
        L.append("  未发现问题。")
        return "\n".join(L)
    for f in result["findings"]:
        tag = {"FAIL": "✗", "UNDETERMINED": "?"}[f["verdict"]]
        L.append(f"  {tag} [{f['rule']}] {f['name']}（{f['where']}）")
        L.append(f"      {f['detail']}")
        if f.get("evidence"):
            ev = "；".join(f"{k}={v}" for k, v in f["evidence"].items() if v not in (None, ""))
            L.append(f"      证据：{ev}")
        L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="EnvStandard 规则终审引擎")
    ap.add_argument("inputs", nargs="+", help="报告摘要 JSON")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是文本")
    args = ap.parse_args()

    stds = Standards(STD_DIR)
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    eng = Engine(stds, rules)

    worst = 0
    for p in args.inputs:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        res = eng.run(doc)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(render(res))
        if res["status"] == "FAIL":
            worst = 1
    sys.exit(worst)


if __name__ == "__main__":
    main()
