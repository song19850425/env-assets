# -*- coding: utf-8 -*-
"""幂等注入公众号二维码区块 + 邮箱混淆脚本到有 <footer> 但缺二维码的页面。

设计要点
--------
1. 用内联 <style>（不依赖页面已有 CSS），中性 rgba 配色适配深/浅主题。
2. 二维码相对路径用 os.path.relpath 按文件目录重算。
3. 插入点：最后一个 <footer 标签前。
4. 邮箱脚本：</body> 前，检查 'a.elmail' 幂等。
5. 幂等标记：检查 'qr-foot' in s。
"""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
QR_SRC = os.path.join(ROOT, "assets", "公众号二维码.jpg")

USER, DOMAIN = "jinghao.song", "gmail.com"

# ---- 内联样式（中性半透明配色，深/浅主题通用）----
STYLE = """<style>
.qr-foot{display:flex;align-items:center;gap:20px;margin:30px 0 0;padding:18px 20px;
  border:1px solid rgba(127,127,127,.25);border-radius:13px;
  background:rgba(127,127,127,.07);flex-wrap:wrap}
.qr-foot-img{width:132px;height:132px;display:block;border-radius:10px;background:#fff;flex:0 0 auto}
.qr-foot-ph{display:none;width:132px;height:132px;border:1px dashed rgba(127,127,127,.3);
  border-radius:10px;align-items:center;justify-content:center;text-align:center;
  font-size:12px;opacity:.5;flex:0 0 auto}
.qr-foot-txt{min-width:220px;flex:1 1 300px}
.qr-foot-t{font-size:15px;font-weight:700;opacity:.95;margin-bottom:5px}
.qr-foot-d{font-size:12.5px;opacity:.7;line-height:1.7;max-width:560px}
.qr-foot-n{font-size:11.5px;opacity:.5;margin-top:6px}
.qr-foot-n a.elmail{color:inherit;text-decoration:underline}
@media(max-width:640px){
  .qr-foot{gap:14px;padding:15px 16px}
  .qr-foot-img,.qr-foot-ph{width:112px;height:112px}
}
</style>"""


def build_qr_section(file_path: str) -> str:
    """构建二维码 HTML 区块（含正确相对路径）。"""
    rel = os.path.relpath(QR_SRC, os.path.dirname(file_path))
    rel = rel.replace("\\", "/")

    html = (
        f'{STYLE}\n'
        f'  <section class="qr-foot" aria-label="关注公众号">\n'
        f'    <img class="qr-foot-img" src="{rel}" alt="公众号二维码"\n'
        f'         width="132" height="132" loading="lazy"\n'
        f'         onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">\n'
        f'    <div class="qr-foot-ph">二维码<br>待放置</div>\n'
        f'    <div class="qr-foot-txt">\n'
        f'      <div class="qr-foot-t">环境检测 · 数字资产库</div>\n'
        f'      <div class="qr-foot-d">长按识别二维码关注公众号，获取标准速查表、交互实验与工具更新。</div>\n'
        f'      <div class="qr-foot-n">交流 / 定制课程 / 工具合作，可在公众号留言，或邮件 '
        f'<a class="elmail" href="#" data-u="{USER}" data-d="{DOMAIN}">载入中…</a>'
        f'<noscript><span>{USER} [at] {DOMAIN}</span></noscript>。</div>\n'
        f'    </div>\n'
        f'  </section>\n'
    )
    return html


# 邮箱混淆脚本
EMAIL_SCRIPT = (
    '<script>(function(){var a=document.querySelectorAll("a.elmail");'
    'for(var i=0;i<a.length;i++){var u=a[i].getAttribute("data-u"),d=a[i].getAttribute("data-d");'
    'if(!u||!d)continue;var e=u+"@"+d;a[i].href="mailto:"+e;a[i].textContent=e;}})();</script>'
)


def inject_one(file_path: str) -> bool:
    """对单个 HTML 文件注入二维码 + 邮箱脚本。返回是否有改动。"""
    s = io.open(file_path, encoding="utf-8", errors="replace").read()

    # 幂等：已有 qr-foot 则跳过
    if "qr-foot" in s:
        return False

    # 找最后一个 <footer 标签的位置
    footer_idx = s.rfind("<footer")
    if footer_idx == -1:
        return False

    # 构建二维码区块
    qr_html = build_qr_section(file_path)

    # 在 <footer 前插入
    s = s[:footer_idx] + qr_html + s[footer_idx:]

    # 插入邮箱脚本（如果 elmail 存在但脚本不存在）
    # 用 querySelectorAll 作为脚本已注入的标志（CSS 里的 a.elmail 选择器不算）
    if "elmail" in s and "querySelectorAll" not in s:
        if "</body>" in s:
            s = s.replace("</body>", EMAIL_SCRIPT + "\n</body>", 1)
        else:
            s = s + EMAIL_SCRIPT + "\n"

    io.open(file_path, "w", encoding="utf-8", newline="").write(s)
    return True


def main():
    processed = 0
    skipped = 0
    for dp, dn, fn in os.walk(ROOT):
        parts = os.path.relpath(dp, ROOT).replace("\\", "/").split("/")
        if ".git" in parts or "_verify" in parts:
            continue
        for name in fn:
            if not name.endswith(".html"):
                continue
            p = os.path.join(dp, name)
            s = io.open(p, encoding="utf-8", errors="replace").read()
            if "qr-foot" in s:
                skipped += 1
                continue
            if "<footer" not in s.lower():
                continue
            if inject_one(p):
                processed += 1
                print(f"  [OK] {os.path.relpath(p, ROOT)}")
    
    print(f"\n[inject] 处理 {processed} 个页面，跳过 {skipped} 个已有二维码的页面")


if __name__ == "__main__":
    main()
