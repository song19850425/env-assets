# -*- coding: utf-8 -*-
"""火点成因推测：基于「历史复现 + 遥感特征」的可解释规则。

⚠ 诚实边界：卫星遥感**无法确证**火点成因（没有地面真值）。本模块给出的是
   「疑似成因 + 依据 + 置信度」，会随历史数据累积而自动改进——同一点位的历史复现
   次数是最强的区分特征（固定源反复排放 vs 农田一次性焚烧）。它不调用任何模型，
   规则透明、可复核。

特征（全部来自 FIRMS，无需外部图层）：
  - cell_days : 该火点所在 ~1km 网格近 30 天被探测到的天数（复现性）→ 固定源判据
  - dn        : 昼夜（D/N）。华北平原夜间火点多与工业/固定源相关
  - frp       : 辐射功率 MW（火强度）
  - conf      : 卫星置信度（l/n/h）
  - month     : 月份（华北秸秆焚烧高发于 6 月夏收、9–11 月秋收）

后续若要显著提高判别力，需要补充的外部图层（当前未接）：
  土地利用/地类（耕地 vs 林地 vs 建设用地）、工业区/垃圾填埋场 POI、
  VIIRS 夜间灯光。接入后可在本模块增加判据。
"""

HARVEST_MONTHS = (6, 9, 10, 11)


def classify(fire, cell_days=0):
    """返回 (cause, conf, reasons)。cause/conf 为中文；reasons 为可读依据列表。"""
    dn = fire.get("dn")
    frp = float(fire.get("frp") or 0)
    conf = fire.get("conf")
    date = fire.get("date") or ""
    month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else 0
    reasons = []

    # 1) 历史复现——最强信号：同一公里网格反复出现 = 固定源
    if cell_days >= 5:
        return ("工业/固定源疑似", "高",
                [f"同一公里网格近 30 天被探测 {cell_days} 天，符合固定源（工业/堆场/垃圾焚烧）反复排放特征"])
    if cell_days >= 3:
        reasons.append(f"同一点位近 30 天复现 {cell_days} 天，偏固定源")

    # 2) 夜间 + 高强度
    if dn == "N" and frp >= 20:
        return ("工业/固定源疑似", "中高",
                reasons + [f"夜间过境且辐射功率高（{frp:.1f} MW），夜间高强度多为工业/固定源"])
    if dn == "N":
        return ("夜间火点·偏工业/固定源", "中",
                reasons + ["夜间过境；华北平原夜间火点多与工业或固定源相关"])

    # 3) 白天极高强度
    if frp >= 50:
        return ("较大火情疑似（林火/工业）", "中",
                reasons + [f"辐射功率很高（{frp:.1f} MW）"])

    # 4) 收获季 + 白天 + 低强度 → 秸秆焚烧
    if month in HARVEST_MONTHS and frp < 10:
        return ("秸秆焚烧疑似", "中",
                reasons + [f"{month} 月为华北秸秆焚烧高发期，白天低强度（{frp:.1f} MW）符合农田焚烧特征"])

    # 5) 低置信
    if conf == "l":
        return ("低置信火点·待核实", "低", reasons + ["卫星置信度低"])

    return ("待核实", "低", reasons + ["现有特征不足以判定成因，建议结合现场核实"])
