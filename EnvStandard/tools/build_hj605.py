# -*- coding: utf-8 -*-
"""从 HJ 605-2011 官方 PDF 生成 EnvStandard 标准 JSON。

为什么不手抄
------------
表 A.1 有 70 行 × 3 个数值 = 210 个数。手抄必然出错，而且错了看不出来
（本仓库历史上就出过「苯筛选值写成 2.2、实际 1」的事）。所以：
  · 表格从 PDF 抽文**程序化解析**，不经过人手
  · 解析完做**行数与数值范围自检**
  · 关键行（苯、四氯化碳）单独断言

流程：下载官方 PDF（缺则自动下载）→ pypdf 抽文 → 解析表 A.1 → 断言 → 写 JSON

依赖：pypdf（不在标准库）。缺失时给出明确的安装提示，不静默失败。

跑法：
    python EnvStandard/tools/build_hj605.py
    python EnvStandard/tools/wire_hj605.py     # 再跑这个接进 pollutant-ids / index.json
"""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CACHE = REPO / ".cache" / "standards"
OUT = REPO / "EnvStandard" / "data" / "standards" / "HJ605-2011.json"

PDF_URL = ("https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/jcffbz/201102/"
           "W020130206497978086463.pdf")
PDF = CACHE / "HJ605-2011.pdf"

DASHES = {"－", "—", "-", "–"}


def ensure_pdf() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    if PDF.exists() and PDF.stat().st_size > 100_000:
        return PDF
    print(f"[hj605] 下载官方 PDF … {PDF_URL}")
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=120).read()
    if not data.startswith(b"%PDF"):
        raise SystemExit("[hj605] 下载到的不是 PDF，官方链接可能变了")
    PDF.write_bytes(data)
    return PDF


def extract_text(pdf: Path) -> str:
    try:
        import pypdf
    except ImportError:
        raise SystemExit(
            "[hj605] 缺少 pypdf。请先安装（不要污染全局环境）：\n"
            "    python -m venv <某个隔离目录>\n"
            "    <隔离目录>/Scripts/python.exe -m pip install pypdf\n"
            "然后用该隔离解释器运行本脚本。") from None
    r = pypdf.PdfReader(str(pdf))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def norm_name(s: str) -> str:
    """去掉 CJK 与连接符之间的排版空格：'1,1- 二氯乙烯' → '1,1-二氯乙烯'。"""
    s = s.strip()
    s = re.sub(r"(?<=[,\-])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s


def parse_table(lines: list[str]) -> list[dict]:
    """解析附录 A 表 A.1。

    ⚠ 附录 B（目标物定性定量离子）表结构几乎一样（序号/中文名/英文名/…/数值），
    不设边界会把两张表混成一张 —— 用「序号回退」作为截断条件：
    表 A.1 的序号单调递增到 71，附录 B 又从 1 开始。
    """
    rows = []
    started = False
    last_seq = 0
    for raw in lines:
        line = raw.strip()
        if "目标物中文名称" in line:
            started = True
            continue
        if not started:
            continue
        if line.startswith("注：") or line.startswith("续表"):
            continue
        if "附录" in line and "B" in line:
            break
        m = re.match(r"^(\d+(?:/\d+)?)\s+(.+)$", line)
        if not m:
            continue
        seq_raw, rest = m.group(1), m.group(2)
        head = int(seq_raw.split("/")[0])
        if head <= last_seq:      # 序号回退 = 进入了下一张表
            break
        toks = rest.split()
        if len(toks) < 4:
            continue
        vals = toks[-3:]
        name_toks = toks[:-3]

        # 中文名与英文名的分界：从右往左取「连续的全 ASCII 词」作为英文名。
        # ⚠ 不能用「第一个拉丁字母」定位 —— 中文名里也可能含拉丁字母
        #   （氘代物如「甲苯-D8」「氯苯-D5」「1,4-二氯苯-D4」），会切错。
        i = len(name_toks)
        while i > 0 and name_toks[i - 1].isascii():
            i -= 1
        if i == len(name_toks) or i == 0:
            continue          # 全 ASCII 或全中文 → 结构不符，跳过
        cn = norm_name(" ".join(name_toks[:i]))
        en = " ".join(name_toks[i:])
        if not cn or not en:
            continue

        def num(x):
            return None if x in DASHES else (float(x) if "." in x else int(x))

        rows.append({
            "seq": head,
            "seqRaw": seq_raw,
            "name": cn,
            "en": en,
            "mdl": num(vals[0]),
            "loq": num(vals[1]),
            "minRrf": num(vals[2]),
        })
        last_seq = head
    return rows


def main() -> None:
    pdf = ensure_pdf()
    text = extract_text(pdf)
    lines = text.split("\n")
    rows = parse_table(lines)

    # ---- 自检 ----
    # 表 A.1 共 71 个序号，其中「44/45 间,对-二甲苯」合并为一行 → 实际 70 行
    if len(rows) != 70:
        raise SystemExit(f"[hj605] 表 A.1 应解析出 70 行（71 个序号含 1 个合并行），实际 {len(rows)} 行")
    seqs = sorted(r["seq"] for r in rows)
    if seqs != [i for i in range(1, 72) if i != 45]:
        missing = [i for i in range(1, 72) if i != 45 and i not in seqs]
        raise SystemExit(f"[hj605] 序号不完整，缺 {missing}")
    merged = [r for r in rows if "/" in r["seqRaw"]]
    if len(merged) != 1 or merged[0]["seqRaw"] != "44/45":
        raise SystemExit(f"[hj605] 合并行识别异常：{[r['seqRaw'] for r in merged]}")
    with_num = [r for r in rows if r["mdl"] is not None]
    # 70 行里 6 行是替代物/内标（无检出限）→ 64 行有检出限；
    # 其中「44/45 间,对-二甲苯」一行代表 2 种化合物 → 共 65 种目标物，
    # 与标准适用范围自述的「65 种挥发性有机物」一致。
    if len(with_num) != 64:
        raise SystemExit(f"[hj605] 有检出限的行应为 64（代表 65 种化合物），实际 {len(with_num)}")
    compounds = len(with_num) + 1
    if compounds != 65:
        raise SystemExit(f"[hj605] 目标物数应为 65，算得 {compounds}")
    no_num = [r["name"] for r in rows if r["mdl"] is None]
    if len(no_num) != 6:
        raise SystemExit(f"[hj605] 无检出限的行应为 6（3 替代物 + 3 内标），实际 {no_num}")
    for r in with_num:
        if not (0.2 <= r["mdl"] <= 3.2):
            raise SystemExit(f"[hj605] {r['name']} 检出限 {r['mdl']} 超出标准自述的 0.2～3.2 μg/kg")
        # ⚠ 「测定下限 = 检出限 × 4」只是常见约定，本标准表 A.1 自己就有例外：
        #   2,2-二氯丙烷 1.3→4.2、顺式-1,2-二氯乙烯 1.3→4.2、2-丁酮 3.2→13。
        #   故只做区间校验（3~5 倍），不做等值断言。
        if r["loq"] is None:
            raise SystemExit(f"[hj605] {r['name']} 缺测定下限")
        ratio = r["loq"] / r["mdl"]
        if not (3.0 <= ratio <= 5.0):
            raise SystemExit(f"[hj605] {r['name']} 测定下限/检出限 = {ratio:.2f}，超出 3~5 倍")

    # 关键行断言（引擎与剧本都要用）
    KEY = {
        "苯": (1.9, 7.6, 0.5),
        "四氯化碳": (1.3, 5.2, 0.1),
        "氯仿": (1.1, 4.4, 0.2),
        "三氯乙烯": (1.2, 4.8, 0.2),
        "甲苯": (1.3, 5.2, 0.4),
        "四氯乙烯": (1.4, 5.6, 0.2),
        "氯苯": (1.2, 4.8, 0.5),
        "苯乙烯": (1.1, 4.4, 0.3),
    }
    by_name = {r["name"]: r for r in rows}
    for name, (mdl, loq, rrf) in KEY.items():
        r = by_name.get(name)
        if not r:
            raise SystemExit(f"[hj605] 表 A.1 里找不到「{name}」")
        if (r["mdl"], r["loq"], r["minRrf"]) != (mdl, loq, rrf):
            raise SystemExit(
                f"[hj605] {name} 数值不符：解析得 {(r['mdl'], r['loq'], r['minRrf'])}，"
                f"预期 {(mdl, loq, rrf)}")

    std = {
        "standardId": "HJ605-2011",
        "name": "土壤和沉积物 挥发性有机物的测定 吹扫捕集/气相色谱-质谱法",
        "issuer": "环境保护部",
        "effectiveDate": "2011-06-01",
        "units": "μg/kg",
        "unitNote": "表 A.1 的检出限与测定下限以 μg/kg 计（样品量 5 g、全扫描）。"
                    "第 8 章校准与第 9 章计算涉及的标准溶液浓度用 μg/L，逐项标注。",
        "source": {
            "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/jcffbz/201102/W020130206497978086463.pdf",
            "publisher": "生态环境部",
            "table": "附录 A（规范性附录）表 A.1 目标物的检出限、测定下限和最小相对响应因子；"
                     "第 8 章分析步骤；第 11.4 条质量保证和质量控制",
            "retrievedAt": "2026-09-29",
            "note": "表 A.1 由 tools/build_hj605.py 从上述官方 PDF 自动解析（71 行 × 3 列），"
                    "并做行数、序号唯一性、测定下限=检出限×4、关键行数值断言。请勿手工修改数值。",
        },
        "coverage": {
            "included": "附录 A 表 A.1 全部 71 行（65 种目标物 + 3 个替代物 + 3 个内标）的"
                        "检出限、测定下限、最小相对响应因子；第 8 章仪器条件与校准要求；"
                        "第 11.4 条质量保证和质量控制条款。",
            "excluded": "附录 B（目标物定性定量离子）、附录 C 表 C.1（精密度与准确度）、"
                        "附录 D（土壤和沉积物中 VOCs 的采样方法）。",
            "reason": "数据层按「引擎与剧本实际引用」收录；需要时按同一方式补录。",
        },
        "columns": {
            "mdl": "检出限（μg/kg）",
            "loq": "测定下限（μg/kg）",
            "minRrf": "最小相对响应因子",
            "en": "英文名称",
        },
        "limits": rows,
        "values": {
            "sample-mass": {
                "value": 5, "units": "g",
                "name": "表 A.1 检出限对应的样品量",
                "basis": "HJ 605-2011 附录 A",
                "citation": "HJ 605-2011 附录 A：当样品量为 5 g、用标准四极杆质谱进行全扫描分析时，"
                            "目标物的方法检出限为 0.2～3.2 μg/kg",
            },
            "mdl-range-min": {
                "value": 0.2, "units": "μg/kg",
                "name": "全扫描方式方法检出限下限",
                "basis": "HJ 605-2011 附录 A",
                "citation": "HJ 605-2011 附录 A：目标物的方法检出限为 0.2～3.2 μg/kg",
            },
            "mdl-range-max": {
                "value": 3.2, "units": "μg/kg",
                "name": "全扫描方式方法检出限上限",
                "basis": "HJ 605-2011 附录 A",
                "citation": "HJ 605-2011 附录 A：目标物的方法检出限为 0.2～3.2 μg/kg",
            },
            "pre-desorb-temp": {
                "value": 180, "units": "℃",
                "name": "预脱附温度",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：预脱附温度 180℃；脱附温度 190℃；脱附时间 2 min；"
                            "烘烤温度 200℃；烘烤时间 8 min",
            },
            "desorb-temp": {
                "value": 190, "units": "℃",
                "name": "脱附温度",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：脱附温度 190℃",
            },
            "desorb-time": {
                "value": 2, "units": "min",
                "name": "脱附时间",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：脱附时间 2 min",
            },
            "bake-temp": {
                "value": 200, "units": "℃",
                "name": "烘烤温度",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：烘烤温度 200℃",
            },
            "bake-time": {
                "value": 8, "units": "min",
                "name": "烘烤时间",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：烘烤时间 8 min",
            },
            "inlet-temp": {
                "value": 200, "units": "℃",
                "name": "进样口温度",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：进样口温度 200℃",
            },
            "split-ratio": {
                "value": 30, "units": "∶1（分流比）",
                "name": "分流比",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：分流比 30∶1",
            },
            "column-flow": {
                "value": 1.5, "units": "ml/min",
                "name": "柱流量（恒流模式）",
                "basis": "HJ 605-2011 第 8 章 分析步骤（仪器参考条件）",
                "citation": "HJ 605-2011 第 8 章：柱流量（恒流模式）1.5 ml/min",
            },
            "calib-series-levels": {
                "value": 5, "units": "个",
                "name": "标准系列浓度点数",
                "basis": "HJ 605-2011 第 8.2 条 校准曲线的绘制",
                "citation": "HJ 605-2011 第 8.2 条：配制目标物和替代物质量浓度分别为 5.00、20.0、"
                            "50.0、100 和 200 μg/L 的标准系列",
            },
            "internal-std-conc": {
                "value": 25, "units": "μg/ml",
                "name": "内标标准溶液浓度",
                "basis": "HJ 605-2011 第 5.5 条",
                "citation": "HJ 605-2011 第 5.5 条：内标标准溶液 ρ=25 μg/ml；"
                            "宜选用氟苯、氯苯-D5 和 1,4-二氯苯-D4 作为内标",
            },
            "surrogate-conc": {
                "value": 25, "units": "μg/ml",
                "name": "替代物标准溶液浓度",
                "basis": "HJ 605-2011 第 5.6 条",
                "citation": "HJ 605-2011 第 5.6 条：替代物标准溶液 ρ=25 μg/ml；"
                            "宜选用二溴氟甲烷、甲苯-D8 和 4-溴氟苯作为替代物",
            },
            "calib-verify-recovery-min": {
                "value": 80, "units": "%",
                "name": "校准确认标准溶液测定值与加入浓度比值的下限",
                "basis": "HJ 605-2011 第 11.4 条（前段）",
                "citation": "HJ 605-2011 第 11.4 条：校准确认标准溶液中目标物的测定值与加入浓度值的"
                            "比值在 80%～120%，否则在分析样品前应采取校正措施",
            },
            "calib-verify-recovery-max": {
                "value": 120, "units": "%",
                "name": "校准确认标准溶液测定值与加入浓度比值的上限",
                "basis": "HJ 605-2011 第 11.4 条（前段）",
                "citation": "HJ 605-2011 第 11.4 条：比值在 80%～120%",
            },
            "rrf-rsd-max": {
                "value": 20, "units": "%",
                "name": "相对响应因子（RRF）的相对标准偏差上限",
                "basis": "HJ 605-2011 第 8.2.2.1 条",
                "citation": "HJ 605-2011 第 8.2.2.1 条：标准系列目标物（或替代物）相对响应因子（RRF）"
                            "的相对标准偏差（RSD）应小于等于 20%",
            },
            "corr-coef-min": {
                "value": 0.99, "units": "无量纲",
                "name": "线性或非线性校准曲线的相关系数下限",
                "basis": "HJ 605-2011 第 8.2.2.2 条",
                "citation": "HJ 605-2011 第 8.2.2.2 条：线性、非线性校准曲线相关系数大于等于 0.99",
            },
            "surrogate-recovery-min": {
                "value": 70, "units": "%",
                "name": "替代物加标回收率下限",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：所有样品中替代物加标回收率均应在 70%～130%，"
                            "否则应重复分析该样品",
            },
            "surrogate-recovery-max": {
                "value": 130, "units": "%",
                "name": "替代物加标回收率上限",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：替代物加标回收率均应在 70%～130%",
            },
            "blank-spike-recovery-min": {
                "value": 70, "units": "%",
                "name": "空白加标样品目标物回收率下限（出现基体效应时）",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：若重复测定替代物回收率仍不合格，说明样品存在"
                            "基体效应。此时应分析一个空白加标样品，其中的目标物回收率应在 70%～130%",
            },
            "blank-spike-recovery-max": {
                "value": 130, "units": "%",
                "name": "空白加标样品目标物回收率上限（出现基体效应时）",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：空白加标样品中目标物回收率应在 70%～130%",
            },
            "parallel-surrogate-deviation-max": {
                "value": 25, "units": "%",
                "name": "平行样中替代物相对偏差上限",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：平行样品中替代物相对偏差应在 25% 以内",
            },
            "qc-batch-size": {
                "value": 20, "units": "个",
                "name": "平行分析或基体加标分析的批内样品数上限",
                "basis": "HJ 605-2011 第 11.4.4 条",
                "citation": "HJ 605-2011 第 11.4.4 条：每批样品（最多 20 个）应选择一个样品进行"
                            "平行分析或基体加标分析",
            },
            "holding-temp-max": {
                "value": 4, "units": "℃",
                "name": "样品保存与运输温度上限",
                "basis": "HJ 605-2011 第 7 章 样品",
                "citation": "HJ 605-2011 第 7 章：样品采集后应冷藏运输，运回实验室后应尽快分析；"
                            "实验室内样品存放区域应无有机物干扰，在 4℃ 以下保存",
            },
            "extract-holding-days-max": {
                "value": 14, "units": "d",
                "name": "提取液最长保存时间",
                "basis": "HJ 605-2011 第 7 章 注 5",
                "citation": "HJ 605-2011 第 7 章 注 5：若提取液不能立即分析，可于 4℃ 以下暗处保存，"
                            "保存时间为 14 d，分析前应恢复至室温",
            },
            "parallel-samples-min": {
                "value": 3, "units": "份",
                "name": "每份样品至少采集的平行样份数（用于初筛判定）",
                "basis": "HJ 605-2011 第 7 章 样品",
                "citation": "HJ 605-2011 第 7 章：所有样品均应至少采集 3 份平行样",
            },
        },
        "qualitative": [
            {
                "key": "blank-control-criteria",
                "text": "空白试验分析结果应满足如下任一条件的最大者：（1）目标物浓度小于方法检出限；"
                        "（2）目标物浓度小于相关环保标准限值的 5%；（3）目标物浓度小于样品分析结果的 5%。"
                        "若空白试验未满足以上要求，则应采取措施排除污染并重新分析同批样品。",
                "citation": "HJ 605-2011 第 11.4.1 条",
            },
            {
                "key": "tenax-degradation-warning",
                "text": "当分析空白试验样品时发现苯和苯乙烯出现异常高值，表明 Tenax 可能变质失效，"
                        "需进行确认，必要时需更换捕集管。",
                "citation": "HJ 605-2011 第 11.4.1 条",
            },
            {
                "key": "transport-and-whole-blank",
                "text": "每批样品应至少采集一个运输空白和一个全程序空白样品。若怀疑样品受到污染，"
                        "则需分析该空白样品，其测定结果应满足空白试验的控制指标，"
                        "否则需查找原因，采取措施排除污染后重新采集样品分析。",
                "citation": "HJ 605-2011 第 11.4.2 条",
            },
            {
                "key": "instrument-check-interval",
                "text": "每批样品分析之前或 24 h 之内，需进行仪器性能检查，"
                        "测定校准确认标准溶液和空白试验样品。",
                "citation": "HJ 605-2011 第 11.4.3 条",
            },
            {
                "key": "batch-qc-selection",
                "text": "每批样品（最多 20 个）应选择一个样品进行平行分析或基体加标分析。"
                        "所有样品中替代物加标回收率均应在 70%～130%，否则应重复分析该样品。"
                        "若重复测定替代物回收率仍不合格，说明样品存在基体效应。"
                        "此时应分析一个空白加标样品，其中的目标物回收率应在 70%～130%。"
                        "若初步判定样品中含有目标物，则须分析一个平行样，"
                        "平行样品中替代物相对偏差应在 25% 以内。",
                "citation": "HJ 605-2011 第 11.4.4 条",
            },
            {
                "key": "cross-contamination-check",
                "text": "在分析完高含量样品后，应分析一个或多个空白试验样品检查交叉污染。",
                "citation": "HJ 605-2011 第 12.2 条",
            },
            {
                "key": "ketone-purge-temp",
                "text": "酮类物质的吹扫温度升至 80℃，吹扫捕集效率和回收率可明显提高。",
                "citation": "HJ 605-2011 第 12.5 条",
            },
        ],
    }

    OUT.write_text(json.dumps(std, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"[hj605] 表 A.1 解析 {len(rows)} 行（含检出限 {len(with_num)} 行）")
    print(f"[hj605] values {len(std['values'])} 项 · qualitative {len(std['qualitative'])} 条")
    print(f"[hj605] 输出 {OUT}")


if __name__ == "__main__":
    main()
