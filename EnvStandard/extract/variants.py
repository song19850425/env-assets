# -*- coding: utf-8 -*-
"""降级变体构造：把构造报告改造成「不像教科书」的输入，供降级测试与端到端测试共用。

产物在 sample/variants/ 下，是**生成物**（已在 .gitignore 里），不入库。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample"
VAR = SAMPLE / "variants"
BASE_HTML = SAMPLE / "sample-report.html"
BASE_PDF = SAMPLE / "sample-report.pdf"

NODE = r"C:/Users/jingh/.workbuddy-ai/binaries/node/versions/22.22.2-3/node.exe"
PRINT_SCRIPT = HERE.parent / "tools" / "print_pdf.mjs"


def make_html(name: str, transform) -> Path:
    VAR.mkdir(parents=True, exist_ok=True)
    html = transform(BASE_HTML.read_text(encoding="utf-8"))
    p = VAR / f"{name}.html"
    p.write_text(html, encoding="utf-8", newline="\n")
    return p


def pdf_from_html(html_path: Path, pdf_path: Path) -> None:
    """用 Node 的 playwright-core 打印 PDF（与 tools/print_pdf.mjs 同一套环境）。"""
    env = dict(os.environ)
    env["NODE_PATH"] = "C:/Users/jingh/.workbuddy-ai/binaries/node/workspace/node_modules"
    env["PDF_SRC"] = str(html_path)
    env["PDF_OUT"] = str(pdf_path)
    r = subprocess.run([NODE, str(PRINT_SCRIPT)], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise SystemExit(f"[variants] 打印 PDF 失败：{r.stdout}\n{r.stderr}")


def drop_basis(h: str) -> str:
    """V2：脚注不写标准号与评价口径。"""
    h = re.sub(r"注\s*1：.*?筛选值。", "注 1：本报告检测结果供内部参考。", h, flags=re.S)
    h = re.sub(r"注\s*3：.*?标准限值。", "注 3：本报告检测结果供内部参考。", h, flags=re.S)
    return h


def reword_conclusion(h: str) -> str:
    """V3：结论写「符合 / 不符合」而不是「达标 / 超标」。"""
    return h.replace("未超标", "符合").replace("超标", "不符合")


def build(name: str, transform) -> Path:
    pdf = VAR / f"{name}.pdf"
    if not pdf.exists():
        pdf_from_html(make_html(name, transform), pdf)
    return pdf


def build_all() -> dict[str, Path]:
    return {
        "v2-no-basis": build("v2-no-basis", drop_basis),
        "v3-wording": build("v3-wording", reword_conclusion),
    }


def rasterize_to_scan(src: Path, dst: Path) -> None:
    """V4：把有文本层的 PDF 光栅化成「扫描件」（只剩图，抽不出字）。"""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise SystemExit(
            "[variants] 需要 pypdfium2 来模拟扫描件：\n"
            "    <隔离目录>/Scripts/python.exe -m pip install pypdfium2") from None
    doc = pdfium.PdfDocument(str(src))
    pages = [page.render(scale=2.0).to_pil() for page in doc]
    pages[0].save(dst, save_all=True, append_images=pages[1:])
    doc.close()
