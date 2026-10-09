# -*- coding: utf-8 -*-
"""火点成因推测：用「点位历史复现 + 遥感特征」给出类型、置信度与详细依据。

⚠ 诚实边界：卫星遥感**无法确证**火点成因（没有地面真值）。本模块输出的是
   「疑似成因 + 依据 + 置信度」，随历史数据累积自动改进——同一点位的历史复现
   统计（出现天数 / 夜间天数 / 最大 FRP）是最强的区分特征：
   固定源（工业/堆场/垃圾焚烧）会**反复、常在夜间**出现；农田秸秆焚烧多为**一次性、白天、低强度**。
   规则透明、可复核，不调用任何模型。

输入：
  fire : {frp, dn(D/N), conf(l/n/h), date, ...}
  cell_days : 该点位近 win 天出现过的天数
  hist : {"nt": 夜间天数, "fm": 最大FRP, "dates": [日期...], "win": 窗口天数}

后续若要显著提高判别力，需要补充的外部图层（当前未接）：
  土地利用/地类、工业区/垃圾填埋场 POI、VIIRS 夜间灯光。
"""
HARVEST_MONTHS = (6, 9, 10, 11)


def _hist_ev(cell_days, nt, fm, dates, win):
    if cell_days <= 0:
        return f"近 {win} 天该点位无历史记录（本次为新出现）"
    s = f"近 {win} 天该点位出现 {cell_days} 天"
    if nt:
        s += f"，其中夜间 {nt} 天"
    if fm:
        s += f"，历史最大辐射功率 {fm:.1f} MW"
    if dates:
        s += "，最近：" + "、".join(dates[-3:])
    return s


def classify(fire, cell_days=0, hist=None):
    """返回 (cause, conf, reasons)。reasons 为可读依据列表（首条含点位历史）。"""
    hist = hist or {}
    win = hist.get("win", 60)
    nt = hist.get("nt", 0)
    fm = hist.get("fm", 0)
    dates = hist.get("dates") or []

    dn = fire.get("dn")
    frp = float(fire.get("frp") or 0)
    conf = fire.get("conf")
    date = fire.get("date") or ""
    month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else 0

    reasons = [_hist_ev(cell_days, nt, fm, dates, win)]

    # 1) 历史复现——最强信号：同一点位反复出现 = 固定源
    if cell_days >= 5:
        reasons.append("反复出现且多在夜间，符合固定源（工业/堆场/垃圾焚烧）持续排放特征")
        return ("工业/固定源疑似", "高", reasons)
    if cell_days >= 3:
        reasons.append("多次复现，偏向固定源；建议结合现场核实")
        return ("工业/固定源疑似", "中", reasons)

    # 2) 夜间 + 高强度
    if dn == "N" and frp >= 20:
        reasons.append(f"本次为夜间过境且辐射功率高（{frp:.1f} MW），夜间高强度多为工业/固定源")
        return ("工业/固定源疑似", "中高", reasons)
    if dn == "N":
        reasons.append("本次为夜间过境；华北平原夜间火点多与工业或固定源相关")
        return ("夜间火点·偏工业/固定源", "中", reasons)

    # 3) 白天极高强度
    if frp >= 50:
        reasons.append(f"辐射功率很高（{frp:.1f} MW），疑似较大火情（林火/工业）")
        return ("较大火情疑似", "中", reasons)

    # 4) 收获季 + 白天 + 低强度 + 基本不复现 → 秸秆焚烧
    if month in HARVEST_MONTHS and frp < 10 and cell_days <= 2:
        reasons.append(f"{month} 月为华北秸秆焚烧高发期；白天、低强度（{frp:.1f} MW）且基本不复现，"
                       "符合农田一次性焚烧特征")
        return ("秸秆焚烧疑似", "中", reasons)

    # 5) 低置信
    if conf == "l":
        reasons.append("卫星置信度低")
        return ("低置信火点·待核实", "低", reasons)

    reasons.append("现有特征不足以判定成因，建议结合现场核实")
    return ("待核实", "低", reasons)
