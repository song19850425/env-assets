# -*- coding: utf-8 -*-
"""规则引擎自测。

判据不是「引擎跑起来了」，而是：
  · 干净样本不能报 FAIL（否则是误报，规则不可用）
  · 植入的每一处错误都必须被**对应规则**抓到（否则是漏报）
  · 单位不一致时必须报「无法判定」而不是硬比大小
  · 缺字段时不能崩，要如实说「无法判定」

跑法：python test_engine.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import Engine, Standards, STD_DIR, RULES_PATH  # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "samples"

FAILS: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  → {extra}"))
    if not cond:
        FAILS.append(name)


def load(p):
    return json.loads((SAMPLES / p).read_text(encoding="utf-8"))


def findings(res):
    """按 (规则, item 下标) 建索引。

    ⚠ 不能只按因子名索引：同一因子在一份报告里可能出现多次
    （土壤苯 + 地下水苯），只按名字会把两条结论互相覆盖 —— 这是自测抓出来的真缺陷。
    """
    return {(f["rule"], f.get("item_index"), f.get("where")): f for f in res["findings"]}


def find(res, rule, where_contains, item_index=None):
    for f in res["findings"]:
        if f["rule"] == rule and where_contains in (f.get("where") or "") \
                and (item_index is None or f.get("item_index") == item_index):
            return f
    return None


def main() -> None:
    eng = Engine(Standards(STD_DIR), json.loads(RULES_PATH.read_text(encoding="utf-8")))

    print("样本 A · 引用正确、结论自洽")
    a = eng.run(load("report-ok.json"))
    ok("不报任何 error", a["error_count"] == 0, f"error_count={a['error_count']}")
    ok("苯的限值核对通过（1 = 1）", find(a, "R-LIM-01", "苯") is None)
    ok("四氯化碳的测定下限核对通过（SIM 1.6 < 2.0）", find(a, "R-MDL-01", "四氯化碳") is None)
    ok("保存时限通过（24h < 48h）", find(a, "R-HOLD-01", "整批") is None)
    ok("空白数量通过（1 ≥ 1）", find(a, "R-QC-01", "整批") is None)
    ok("平行样比例通过（2/12=16.7% ≥ 10%）", find(a, "R-QC-02", "整批") is None)
    f_hj605 = find(a, "R-MDL-01", "苯")
    ok("HJ 605 未入库 → 报「无法判定」而不是放过",
       f_hj605 is not None and f_hj605["verdict"] == "UNDETERMINED", str(f_hj605))

    print("\n样本 B · 植入 6 处错误")
    b = eng.run(load("report-bad.json"))
    ok("状态为 FAIL", b["status"] == "FAIL", b["status"])
    ok("可核查程度为 LOW", b["confidence_band"] == "LOW", b["confidence_band"])
    ok("error_count = 6", b["error_count"] == 6, b["error_count"])

    def caught(rule, where, needle, item_index=None):
        f = find(b, rule, where, item_index)
        if not f or f["verdict"] != "FAIL":
            return False, f"未命中 {rule}/{where} idx={item_index}"
        if needle not in f["detail"]:
            return False, f"detail 里没有 {needle!r}：{f['detail']}"
        return True, ""

    for rule, where, needle, label, idx in [
        ("R-STD-01", "苯", "HJ 9999-2020", "① 引用不存在的标准号", 2),
        ("R-LIM-01", "苯", "报告写 2.2，标准是 1", "② 限值抄错（2.2 vs 1，真实历史错误）", 0),
        ("R-LIM-02", "苯", "应为「超标」", "③ 结论与数据矛盾（5.2 判成达标）", 0),
        ("R-MDL-01", "四氯化碳", "测定下限 6.0 μg/L ≥ 限值 2.0", "④ 方法能力不足（跨标准推论）", 1),
        ("R-HOLD-01", "整批", "实际 72 h", "⑤ 保存超期", None),
        ("R-QC-01", "整批", "没有任何空白", "⑥ 缺空白", None),
    ]:
        good, why = caught(rule, where, needle, idx)
        ok(label, good, why)

    f_qc2 = find(b, "R-QC-02", "整批")
    ok("平行样比例不足被抓到", f_qc2 is not None and f_qc2["verdict"] == "FAIL", str(f_qc2))
    f_unit = find(b, "R-MDL-01", "苯", 0)
    ok("单位不一致报「无法判定」而不是硬比大小",
       f_unit is not None and f_unit["verdict"] == "UNDETERMINED"
       and "单位不一致" in f_unit["detail"], str(f_unit))
    ok("同一因子出现两次时，两条结论不会互相覆盖",
       find(b, "R-LIM-01", "苯", 0) is not None and find(b, "R-STD-01", "苯", 2) is not None,
       "土壤苯与地下水苯的结论应各自独立")

    print("\n证据链完整性")
    lim = find(b, "R-LIM-01", "苯", 0)
    ok("限值错误的证据含标准值、报告值与出处",
       lim is not None and lim["evidence"].get("标准值") == 1
       and lim["evidence"].get("报告写的") == 2.2
       and "序号 26" in (lim["evidence"].get("出处") or ""),
       json.dumps(lim["evidence"] if lim else None, ensure_ascii=False))
    m = find(b, "R-MDL-01", "四氯化碳", 1)
    ok("方法能力错误的证据含方法出处",
       m is not None and "HJ639-2012" in (m["evidence"].get("方法出处") or ""),
       json.dumps(m["evidence"] if m else None, ensure_ascii=False))

    print("\n边界：缺字段不能崩")
    for name, doc in [
        ("空文档", {}),
        ("空 items", {"items": []}),
        ("缺 basis", {"items": [{"factor": "苯", "standard": "GB36600-2018", "statedLimit": 1}]}),
        ("缺 method", {"items": [{"factor": "苯", "standard": "GB36600-2018",
                                  "basis": {"landUse": "first", "kind": "screening"},
                                  "statedLimit": 1, "result": 0.5, "conclusion": "达标"}]}),
        ("非数值限值", {"items": [{"factor": "苯", "standard": "GB36600-2018",
                                   "basis": {"landUse": "first", "kind": "screening"},
                                   "statedLimit": "—", "result": 0.5, "conclusion": "达标"}]}),
    ]:
        try:
            r = eng.run(doc)
            ok(f"{name} 不崩且给出状态", r["status"] in ("PASS", "PARTIAL", "FAIL"), str(r)[:80])
        except Exception as e:  # noqa: BLE001
            ok(f"{name} 不崩", False, f"{type(e).__name__}: {e}")

    print("\n反向测试：把判据改掉，引擎应当不再报错")
    tampered = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    tampered["rules"] = [r for r in tampered["rules"] if r["id"] != "R-LIM-01"]
    eng2 = Engine(Standards(STD_DIR), tampered)
    b2 = eng2.run(load("report-bad.json"))
    ok("删掉 R-LIM-01 后不再报限值错", find(b2, "R-LIM-01", "苯") is None)
    ok("但 R-LIM-02 仍抓到结论矛盾（两条规则互相独立）",
       (find(b2, "R-LIM-02", "苯", 0) or {}).get("verdict") == "FAIL")

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} 项失败：" + "；".join(FAILS))
        sys.exit(1)
    print("✓ 全部通过")


if __name__ == "__main__":
    main()
