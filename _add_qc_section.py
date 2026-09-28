# -*- coding: utf-8 -*-
"""把「质量控制训练室」接进首页口径。

新增一个分区意味着四件事必须同时改，漏一处数字就对不上：
  1. `.sec` 区块（放在 EnvLab 产品线内，仪器培训之后）
  2. JS 里的 `SECS` 数组（唯一口径源）
  3. 产品线标题与三入口卡上的 EnvLab 件数（84 → 85）
  4. 页脚总件数（105 → 106）

另外，SECS 的下标就是 `.sec` 的 `data-g`，新分区插在中间就必须**整体重编号**，
否则后面的分区会全部错位（点「工具速查」筛出来的是「操作规程」）。
所以这里先重编号，再插入，最后断言 `data-g` 是 0..N 连续且唯一。

跑法：python _add_qc_section.py
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"

NEW_KEY = "EnvLab/03-质量控制"
NEW_TITLE = "质量控制训练"
NEW_DESC = "质控判据与异常处置：平行样、空白、校准、处置决策四关，判据逐条带标准出处。"
NEW_COLOR = "#22c55e"
NEW_COUNT = 1
INSERT_AT = 2  # 排在「仪器交互培训」之后

SEC_BLOCK = (
    '<div class="sec" data-g="__G__"><h2><span class="dot" style="background:#22c55e"></span>'
    '质量控制训练<span class="cnt">1 件</span></h2>'
    '<p>质控不是补流程，是报告能不能签字的判据。四关训练，判据全部来自标准并标注出处。</p>'
    '<ul><li data-n="质量控制训练室" data-sub=""><a href="EnvLab/03-质量控制/质量控制训练室.html" '
    'title="03-质量控制/质量控制训练室.html">质量控制训练室</a></li></ul></div>'
)


def main() -> None:
    s = io.open(INDEX, encoding="utf-8").read()
    orig = s

    # ---- 1. 读 SECS ----
    m = re.search(r"var SECS = (\[.*?\]);", s, re.S)
    if not m:
        raise SystemExit("[add-qc] 读不到 SECS")
    secs = json.loads(m.group(1))
    if any(x["key"] == NEW_KEY for x in secs):
        raise SystemExit("[add-qc] SECS 里已经有这个分区了，先撤销上次的改动")

    # ---- 2. 重编号 data-g：老的 >= INSERT_AT 全部 +1（从大到小改，避免撞号）----
    old_g = sorted((int(x.group(1)) for x in re.finditer(r'<div class="sec" data-g="(\d+)"', s)),
                   reverse=True)
    for g in old_g:
        if g >= INSERT_AT:
            s = s.replace(f'<div class="sec" data-g="{g}">',
                          f'<div class="sec" data-g="{g + 1}">', 1)

    # ---- 3. 插入新分区：放在原 data-g=1（仪器培训）那个 .sec 结束之后 ----
    anchor = '</ul></div>\n<div class="pline" id="envwork"'
    if anchor not in s:
        raise SystemExit("[add-qc] 找不到 EnvWork 产品线标题前的锚点")
    s = s.replace(anchor, '</ul></div>\n' + SEC_BLOCK.replace("__G__", str(INSERT_AT))
                  + '\n<div class="pline" id="envwork"', 1)

    # ---- 4. 更新 SECS ----
    secs.insert(INSERT_AT, {
        "key": NEW_KEY, "title": NEW_TITLE, "desc": NEW_DESC,
        "color": NEW_COLOR, "count": NEW_COUNT,
    })
    new_secs = json.dumps(secs, ensure_ascii=False, separators=(", ", ": "))
    s = re.sub(r"var SECS = \[.*?\];", "var SECS = " + new_secs + ";", s, count=1, flags=re.S)

    # ---- 5. 件数口径 ----
    total = sum(x["count"] for x in secs if x.get("includeInTotal", True))
    envlab = sum(x["count"] for x in secs if x["key"].startswith("EnvLab/"))
    if total != 106 or envlab != 85:
        raise SystemExit(f"[add-qc] 口径异常：总数 {total}（应为 106）、EnvLab {envlab}（应为 85）")

    s = s.replace('<span class="pnav-s">EnvLab · 84 件</span>',
                  f'<span class="pnav-s">EnvLab · {envlab} 件</span>')
    s = s.replace('<span class="pline-n">84 件</span>',
                  f'<span class="pline-n">{envlab} 件</span>')
    s = s.replace('共 <b>105</b> 件可交互资产', f'共 <b>{total}</b> 件可交互资产')

    # ---- 6. 断言 ----
    gs = [int(x.group(1)) for x in re.finditer(r'<div class="sec" data-g="(\d+)"', s)]
    if gs != list(range(len(secs))):
        raise SystemExit(f"[add-qc] data-g 序列不对：{gs}，SECS 有 {len(secs)} 项")
    for needle in ['EnvLab/03-质量控制/质量控制训练室.html', f'EnvLab · {envlab} 件',
                   f'共 <b>{total}</b> 件可交互资产']:
        if needle not in s:
            raise SystemExit(f"[add-qc] 缺少 {needle}")

    if s == orig:
        raise SystemExit("[add-qc] 没有任何改动")

    io.open(INDEX, "w", encoding="utf-8", newline="").write(s)
    print(f"[add-qc] SECS {len(secs)} 项 · 总数 {total} · EnvLab {envlab}")
    print(f"[add-qc] data-g 序列 {gs[0]}..{gs[-1]} 连续唯一")
    print(f"[add-qc] 已更新 {INDEX}")


if __name__ == "__main__":
    main()
