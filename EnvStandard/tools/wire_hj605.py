# -*- coding: utf-8 -*-
"""把 HJ605-2011 接进 EnvStandard 数据层，并修正一处既有映射错误。

① 修正三卤甲烷的英文 ID 写反
   GB 5749-2022 里：
     一氯二溴甲烷 → 原写 bromodichloromethane   ✗
     二氯一溴甲烷 → 原写 dibromochloromethane   ✗
   中文命名按「取代基个数」直译，与英文词序**相反**：
     一氯二溴甲烷 = 1 Cl + 2 Br = CHClBr₂ = dibromochloromethane（CAS 124-48-1）
     二氯一溴甲烷 = 2 Cl + 1 Br = CHCl₂Br = bromodichloromethane（CAS 75-27-4）
   交叉验证：GB 5749 限值 一氯二溴甲烷 0.1 / 二氯一溴甲烷 0.06
             与 WHO 指导值 dibromochloromethane 0.1 / bromodichloromethane 0.06 一致。
   （同物异名：一氯二溴甲烷 ≡ 二溴氯甲烷 ≡ 氯二溴甲烷）

② 为 HJ605-2011 表 A.1 的每个化合物补 ID（已有 ID 复用，不另造）

跑法：python wire_hj605.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STD = HERE.parent.parent / "EnvStandard" / "data" / "standards"
SID = "HJ605-2011"

# 同物异名 → 规范 ID。这张表是**跨标准对齐**的依据，不是猜的。
ALIAS = {
    "氯仿": "chloroform",
    "三氯甲烷": "chloroform",
    "间,对-二甲苯": "m-p-xylene",
    "间二甲苯+对二甲苯": "m-p-xylene",
    "邻-二甲苯": "o-xylene",
    "邻二甲苯": "o-xylene",
    # 三卤甲烷：见文件头说明
    "一氯二溴甲烷": "dibromochloromethane",
    "二溴氯甲烷": "dibromochloromethane",
    "氯二溴甲烷": "dibromochloromethane",
    "二氯一溴甲烷": "bromodichloromethane",
    "一溴二氯甲烷": "bromodichloromethane",
    # 其它同物异名（HJ 605 用系统命名，GB 36600/GB 5749 用俗名或「邻/间/对」）
    "溴仿": "bromoform",
    "三溴甲烷": "bromoform",
    "1,2-二氯苯": "12-dichlorobenzene",
    "邻二氯苯": "12-dichlorobenzene",
    "1,3-二氯苯": "13-dichlorobenzene",
    "间二氯苯": "13-dichlorobenzene",
    "1,4-二氯苯": "14-dichlorobenzene",
    "对二氯苯": "14-dichlorobenzene",
    "二氯甲烷": "methylene-chloride",
    "四氯乙烯": "tetrachloroethylene",
    "三氯乙烯": "trichloroethylene",
    "苯乙烯": "styrene",
    "异丙苯": "isopropylbenzene",
}

# 需要就地改正的既有错误映射：(标准号, 中文名, 正确 ID)
FIXUPS = [
    ("GB5749-2022", "一氯二溴甲烷", "dibromochloromethane"),
    ("GB5749-2022", "二氯一溴甲烷", "bromodichloromethane"),
]


def slug(en: str) -> str:
    s = en.strip().lower().replace("α", "alpha").replace("β", "beta")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main() -> None:
    std = json.loads((STD / f"{SID}.json").read_text(encoding="utf-8"))
    ids_path = STD / "pollutant-ids.json"
    ids = json.loads(ids_path.read_text(encoding="utf-8"))

    # ---- ① 修正既有错误映射 ----
    fixed = []
    for sid, cn, right in FIXUPS:
        block = ids.get(sid)
        if not block or cn not in block:
            raise SystemExit(f"[wire] 找不到待修正项 {sid} / {cn}")
        old = block[cn]
        if old != right:
            block[cn] = right
            fixed.append((sid, cn, old, right))

    # ---- ② 全库已有映射（中文名 → ID），用于复用 ----
    known: dict[str, str] = {}
    for k, v in ids.items():
        if k == "_comment" or not isinstance(v, dict):
            continue
        for cn, pid in v.items():
            known.setdefault(cn, pid)
    known.update(ALIAS)

    # ---- ③ HJ605 映射 ----
    rows = [r for r in std["limits"] if r.get("name")]
    mapping: dict[str, str] = {}
    reused = generated = 0
    for r in rows:
        cn = r["name"]
        if cn in known:
            mapping[cn] = known[cn]
            reused += 1
        else:
            pid = slug(r["en"])
            if not pid:
                raise SystemExit(f"[wire] {cn} 无法从英文名生成 ID：{r['en']!r}")
            mapping[cn] = pid
            generated += 1

    # 唯一性
    byid: dict[str, list[str]] = {}
    for cn, pid in mapping.items():
        byid.setdefault(pid, []).append(cn)
    dup = {k: v for k, v in byid.items() if len(v) > 1}
    if dup:
        raise SystemExit(f"[wire] HJ605 内部 ID 冲突：{dup}")

    # 与全库其它标准不撞到不同物质（同物异名已在 ALIAS 里对齐）
    clash = []
    for cn, pid in mapping.items():
        for other_cn, other_pid in known.items():
            if other_pid == pid and other_cn != cn:
                # 只允许 ALIAS 里显式声明的等价
                if ALIAS.get(cn) == other_pid and ALIAS.get(other_cn) == other_pid:
                    continue
                clash.append((cn, pid, other_cn))
    if clash:
        raise SystemExit(f"[wire] 与既有 ID 冲突：{clash[:5]}")

    ids[SID] = dict(sorted(mapping.items()))
    ids_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")

    # ---- ④ index.json ----
    idx_path = STD / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    files = sorted(set(idx["standards"]) | {f"{SID}.json"})
    idx["standards"] = files
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")

    if fixed:
        print("[wire] ★ 修正既有错误映射：")
        for sid, cn, old, right in fixed:
            print(f"         {sid} / {cn}：{old} → {right}")
    print(f"[wire] pollutant-ids：HJ605 新增 {len(mapping)} 个（复用 {reused} · 新生成 {generated}）")
    print(f"[wire] index.json 标准数：{len(files)}")


if __name__ == "__main__":
    main()
