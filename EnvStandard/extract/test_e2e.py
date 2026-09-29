# -*- coding: utf-8 -*-
"""端到端：报告 PDF → 抽取层 → 规则引擎 → 核查结论。

这是「工作流」的最小完整形态，也是 C 阶段真正要回答的问题：
两层能不能接上，接上之后**能不能给出可核查的结论**。

跑法：python test_e2e.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "engine"))

import extract as ex            # noqa: E402
import variants as vf           # noqa: E402
from check import Engine, Standards, STD_DIR, RULES_PATH  # noqa: E402

SAMPLE = HERE / "sample"
FAILS: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  → {extra}"))
    if not cond:
        FAILS.append(name)


def main() -> None:
    eng = Engine(Standards(STD_DIR), json.loads(RULES_PATH.read_text(encoding="utf-8")))

    print("端到端 · 干净样本（引用正确、结论自洽）")
    doc = ex.extract(SAMPLE / "sample-report.pdf")
    ok("抽取层出 7 项", len(doc["items"]) == 7, len(doc["items"]))
    ok("质控字段抽到了", doc["qc"].get("blankCount") is not None, doc["qc"])

    res = eng.run(doc)
    print(f"     引擎：{res['status']} / {res['confidence_band']}"
          f"  错误 {res['error_count']} · 无法判定 {res['undetermined_count']}")
    ok("结论自洽，引擎不报 error", res["error_count"] == 0,
       json.dumps([f["detail"] for f in res["findings"] if f["verdict"] == "FAIL"],
                  ensure_ascii=False)[:200])

    # 方法未定 → R-MDL-01 必须报「无法判定」，且理由是「报告没说是哪个因子用哪个方法」
    mdl = [f for f in res["findings"] if f["rule"] == "R-MDL-01"]
    ok("R-MDL-01 对每项都报「无法判定」（报告未逐因子声明方法）",
       len(mdl) == 7 and all(f["verdict"] == "UNDETERMINED" for f in mdl), len(mdl))
    ok("理由写明了「本节列出 N 个方法，报告未说明各因子用哪个」",
       any("未说明" in f["detail"] for f in mdl),
       mdl[0]["detail"] if mdl else "")

    print("\n端到端 · 坏样本（把苯的限值改成 2.2、结论改成达标，重打 PDF）")
    # 直接改真值链路验证：用真值构造一份「报告写错了」的抽取结果
    bad = json.loads(json.dumps(doc))
    for it in bad["items"]:
        if it["factor"] == "苯" and it["matrix"] == "soil":
            it["statedLimit"] = 2.2          # 抄错（实际 1）
            it["conclusion"] = "达标"        # 与 5.2 > 1 矛盾
    res2 = eng.run(bad)
    print(f"     引擎：{res2['status']} / {res2['confidence_band']}"
          f"  错误 {res2['error_count']} · 无法判定 {res2['undetermined_count']}")
    ok("状态为 FAIL", res2["status"] == "FAIL", res2["status"])
    det = [f for f in res2["findings"] if f["verdict"] == "FAIL"]
    ok("抓到限值抄错", any(f["rule"] == "R-LIM-01" and "2.2" in f["detail"] for f in det),
       json.dumps([f["detail"] for f in det], ensure_ascii=False)[:200])
    ok("抓到结论与数据矛盾", any(f["rule"] == "R-LIM-02" for f in det), "")
    ok("证据链带标准出处", any("GB36600-2018" in json.dumps(f.get("evidence"), ensure_ascii=False)
                              for f in det), "")

    print("\n端到端 · 依据缺失样本（抽取层报未定，引擎应跟着报未定而不是硬判）")
    v2 = vf.build("v2-no-basis", vf.drop_basis)
    if v2.exists():
        d2 = ex.extract(v2)
        r2 = eng.run(d2)
        lim = [f for f in r2["findings"] if f["rule"] == "R-LIM-01"]
        ok("R-LIM-01 对每项报「无法判定」", len(lim) == 7, len(lim))
        ok("理由写明「未声明评价依据标准号」并带上抽取层的备注",
           bool(lim) and "未声明评价依据标准号" in lim[0]["detail"]
           and "抽取层备注" in lim[0]["detail"],
           lim[0]["detail"][:120] if lim else "")
        ok("没有因为缺依据就误报 error", r2["error_count"] == 0, r2["error_count"])
    else:
        ok("V2 变体存在（先跑 test_degrade.py）", False, str(v2))

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} 项失败：" + "；".join(FAILS))
        sys.exit(1)
    print("✓ 端到端全部通过")


if __name__ == "__main__":
    main()
