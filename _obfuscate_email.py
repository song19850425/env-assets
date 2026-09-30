# -*- coding: utf-8 -*-
"""把站内明文邮箱改成 JS 拼装 + data 属性（防爬虫抓取）。

约定来源
--------
与另一站 envlab-lab 完全一致（那边 113 个文件在用）：

    <a class="elmail" href="#" data-u="jinghao.song" data-d="gmail.com">载入中…</a>
    <noscript><span>jinghao.song [at] gmail.com</span></noscript>
    <script>…拼出 mailto 并填回文本…</script>

为什么这样有效
--------------
静态 HTML 里不再出现完整的 `xxx@yyy` 字符串，**正则爬虫抓不到**；
人正常浏览时 JS 会把它拼出来、照样可点。代价是禁用 JS 的人看到 noscript 里的
`[at]` 写法 —— 仍然可读。

幂等：已经处理过的页面再跑不会重复插入脚本。
"""

from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
USER, DOMAIN = "jinghao.song", "gmail.com"
FULL = f"{USER}@{DOMAIN}"

ANCHOR = ('<a class="elmail" href="#" data-u="%s" data-d="%s">载入中…</a>' % (USER, DOMAIN))
NOSCRIPT = ('<noscript><span>%s [at] %s</span></noscript>' % (USER, DOMAIN))
SCRIPT = (
    '<script>(function(){var a=document.querySelectorAll("a.elmail");'
    'for(var i=0;i<a.length;i++){var u=a[i].getAttribute("data-u"),d=a[i].getAttribute("data-d");'
    'if(!u||!d)continue;var e=u+"@"+d;a[i].href="mailto:"+e;a[i].textContent=e;}})();</script>'
)

# 已有的 mailto 链接：保留原有行内样式，只换 href 与文本
LINK_RE = re.compile(
    r'<a\s+href="mailto:' + re.escape(FULL) + r'"([^>]*)>' + re.escape(FULL) + r'</a>')


def process(s: str) -> tuple[str, int, bool]:
    """返回 (新内容, 替换处数, 是否有改动)。"""
    n = 0

    def repl_link(m):
        nonlocal n
        attrs = m.group(1)
        if "class=" in attrs:
            return m.group(0)          # 已有 class，不动（避免属性冲突）
        n += 1
        return ('<a class="elmail" href="#" data-u="%s" data-d="%s"%s>载入中…</a>'
                % (USER, DOMAIN, attrs))

    s = LINK_RE.sub(repl_link, s)

    # 剩下的纯文本（页脚里的「联系方式：xxx」等）
    if FULL in s:
        cnt = s.count(FULL)
        s = s.replace(FULL, ANCHOR + NOSCRIPT)
        n += cnt

    changed = n > 0
    # 插脚本：只在确实用了 elmail 且还没插过时
    if "elmail" in s and "a.elmail" not in s:
        if "</body>" in s:
            s = s.replace("</body>", SCRIPT + "\n</body>", 1)
        else:
            s = s + SCRIPT + "\n"
        changed = True
    return s, n, changed


def main() -> None:
    files, total_refs = 0, 0
    leftover = []
    for dp, dn, fn in os.walk(ROOT):
        parts = os.path.relpath(dp, ROOT).replace("\\", "/").split("/")
        if ".git" in parts or ".cache" in parts or "_verify" in parts:
            continue
        for name in fn:
            if not name.endswith(".html"):
                continue
            p = os.path.join(dp, name)
            s = io.open(p, encoding="utf-8", errors="replace").read()
            if FULL not in s and "elmail" not in s:
                continue
            new, n, changed = process(s)
            if changed:
                io.open(p, "w", encoding="utf-8", newline="").write(new)
                files += 1
                total_refs += n
            if FULL in new:
                leftover.append(os.path.relpath(p, ROOT))

    print(f"[mail] 处理 {files} 个文件 / {total_refs} 处邮箱")
    if leftover:
        print(f"[mail] ★ 仍有明文残留的页面 {len(leftover)} 个：")
        for x in leftover[:10]:
            print("        ", x)
        raise SystemExit("[mail] 脱敏未清干净")
    print("[mail] ✓ 全站 HTML 已无完整明文邮箱")


if __name__ == "__main__":
    main()
