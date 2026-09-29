# -*- coding: utf-8 -*-
"""抽取层的降级测试：干净样本 100% 不说明问题，要看它在「不像教科书」的输入上怎么崩。

三个变体，对应真实报告最常见的三类降级：

  V2 依据缺失   脚注不写标准号与用地类型 —— 抽取层**必须报未定，不能猜**
  V3 措辞不同   结论写「符合/不符合」而不是「达标/超标」—— 归一化要能覆盖
  V4 扫描件     PDF 没有文本层 —— 必须明确拒绝，不能吐半截

跑法：python test_degrade.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract as ex          # noqa: E402
import variants as vf         # noqa: E402

SAMPLE = HERE / "sample"
VAR = vf.VAR

FAILS: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  → {extra}"))
    if not cond:
        FAILS.append(name)


def main() -> None:
    print("V2 · 依据缺失（脚注不写标准号与用地类型）")
    def drop_basis(h: str) -> str:
        h = re.sub(r"注\s*1：.*?筛选值。", "注 1：本报告检测结果供内部参考。", h, flags=re.S)
        h = re.sub(r"注\s*3：.*?标准限值。", "注 3：本报告检测结果供内部参考。", h, flags=re.S)
        return h
    p2p = vf.build("v2-no-basis", vf.drop_basis)
    d2 = ex.extract(p2p)
    ok("抽到了 7 项（结构仍在）", len(d2["items"]) == 7, len(d2["items"]))
    ok("每项都标了「依据未定」而不是猜一个",
       all(it["basis"] is None and it["standard"] is None for it in d2["items"]),
       json.dumps([it["basis"] for it in d2["items"]], ensure_ascii=False))
    ok("每项都写明缺什么",
       all(any("评价口径" in x or "标准号" in x for x in it["pending"]) for it in d2["items"]),
       json.dumps([it["pending"] for it in d2["items"]][:2], ensure_ascii=False))
    ok("限值本身仍抽到了（结构可读）",
       all(it["statedLimit"] is not None for it in d2["items"]))

    print("\nV3 · 结论措辞不同（符合 / 不符合）")
    def reword(h: str) -> str:
        return h.replace("未超标", "符合").replace("超标", "不符合")
    p3p = vf.build("v3-wording", vf.reword_conclusion)
    d3 = ex.extract(p3p)
    concls = [it["conclusion"] for it in d3["items"]]
    ok("「符合/不符合」被归一化成「达标/超标」",
       all(c in ("达标", "超标") for c in concls), json.dumps(concls, ensure_ascii=False))
    ok("归一化结果与真值一致",
       concls == ["超标", "达标", "达标", "超标", "达标", "达标", "达标"],
       json.dumps(concls, ensure_ascii=False))

    print("\nV4 · 扫描件（无文本层）")
    p4 = VAR / "v4-scan.pdf"
    try:
        vf.rasterize_to_scan(SAMPLE / "sample-report.pdf", p4)
    except SystemExit as e:
        ok("扫描件测试可运行（缺 pypdfium2）", False, str(e)[:150])
        p4 = None
    if p4 is not None:
        try:
            text_len = len(ex.extract_text(p4))
            ok("扫描件确实抽不出文字（构造有效）", text_len < 50, f"抽出 {text_len} 字")
        except SystemExit:
            text_len = 0
            ok("扫描件确实抽不出文字（构造有效）", True)
        try:
            ex.extract(p4)
            ok("扫描件应明确拒绝", False, "没有报错，可能吐了半截结果")
        except SystemExit as e:
            ok("扫描件明确拒绝并说明原因", "扫描件" in str(e), str(e)[:120])

    print("\n对照：干净样本仍为满分")
    d1 = ex.extract(SAMPLE / "sample-report.pdf")
    truth = json.loads((SAMPLE / "ground-truth.json").read_text(encoding="utf-8"))
    s1 = ex.score(d1, truth)
    ok("干净样本 100%", s1["accuracy"] == 100.0, s1["accuracy"])

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} 项失败：" + "；".join(FAILS))
        sys.exit(1)
    print("✓ 降级测试全部通过")


if __name__ == "__main__":
    main()
