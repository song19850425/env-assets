"""修正站内 src 相对路径（目录重组后遗症）。

背景：2026-09-28 的「按产品线真分区」把页面整体下沉一层，
当时的链接重写脚本只处理了 href，漏了 src —— 导致 105 个页面里
页脚二维码 <img src> 全部指到了不存在的 EnvLab/assets / EnvWork/assets。

做法：不猜前缀，直接按「当前文件所在目录」重算到目标资源的相对路径。
幂等：已经正确的路径重算后与原值一致，不写盘。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parent
# 只修这个资源（其余 src 目前无断链）
TARGET = "assets/公众号二维码.jpg"


def rel_from(cur_dir: str, target: str) -> str:
    src = [p for p in cur_dir.split("/") if p]
    tgt = target.split("/")
    i = 0
    while i < len(src) and i < len(tgt) - 1 and src[i] == tgt[i]:
        i += 1
    parts = [".."] * (len(src) - i) + tgt[i:]
    return "/".join(parts)


def main() -> None:
    fixed_files = 0
    fixed_refs = 0
    skipped = 0

    for dp, _dn, fn in os.walk(REPO):
        parts = os.path.relpath(dp, REPO).replace("\\", "/").split("/")
        if ".git" in parts or parts == ["."]:
            pass
        if ".git" in parts:
            continue
        for name in fn:
            if not name.endswith(".html"):
                continue
            cur_dir = "/".join(p for p in parts if p != "." and p != "")
            path = Path(dp) / name
            raw = path.read_text(encoding="utf-8", errors="replace")
            if "公众号二维码" not in raw:
                continue

            want = rel_from(cur_dir, TARGET)
            changed = [0]

            def repl(m: re.Match) -> str:
                href = m.group(2)
                # 只处理指向二维码的本站相对路径
                if "公众号二维码" not in unquote(href):
                    return m.group(0)
                if href.startswith(("http:", "https:", "data:", "//")):
                    return m.group(0)
                # 仓库既有写法是中文字面量（未百分号编码），保持一致
                new = want
                if new == href:
                    return m.group(0)
                changed[0] += 1
                return m.group(1) + new + m.group(3)

            out = re.sub(r'(src=")([^"]+)(")', repl, raw)
            if out != raw:
                path.write_text(out, encoding="utf-8", newline="")
                fixed_files += 1
                fixed_refs += changed[0]
            else:
                skipped += 1

    print(f"[fix-src] 修改 {fixed_files} 个文件 / {fixed_refs} 处引用；已正确 {skipped} 个文件")


if __name__ == "__main__":
    main()
