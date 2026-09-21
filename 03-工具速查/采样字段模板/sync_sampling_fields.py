# -*- coding: utf-8 -*-
"""
采样字段同源同步脚本 (single source of truth)
------------------------------------------------
唯一手工源 : 环境实验-采样字段模板/sampling_fields.json  (common + 四域 keyed 字段)
产出(自动, 勿手改):
  - 环境实验-采样培训系统/sampling/fields.json        : canonical 副本, train.html 据此解析
  - 各模块 sampling/<id>.json 的 form.fields        : 重写为 key 数组(common_keep + 该域字段)
  - 各模块 sampling/<id>.json 的 fieldDomain        : 标记对应域
修改模板后重跑本脚本即可同步培训系统, 消除双份维护。
"""
import json, os

BASE = r"c:/Users/jingh/WorkBuddy/20260326095724"
TEMPLATE = os.path.join(BASE, "环境实验-采样字段模板", "sampling_fields.json")
TRAIN_DIR = os.path.join(BASE, "环境实验-采样培训系统", "sampling")

# 培训现场记录清单里保留的 common 字段(剔除了与域字段重复的 sample_date/weather)
COMMON_KEEP = ["entrust_no", "method_basis", "sample_no", "instrument_model", "sampler", "reviewer"]

# 培训模块 id -> 字段模板域 key
ID2DOMAIN = {
    "water-wastewater": "water",
    "soil": "soil",
    "air": "air",
    "noise": "noise",
}

def main():
    with open(TEMPLATE, encoding="utf-8") as f:
        canon = json.load(f)
    common = canon["common"]
    domains = canon["domains"]

    # 1) 生成 canonical 副本到培训系统
    with open(os.path.join(TRAIN_DIR, "fields.json"), "w", encoding="utf-8") as f:
        json.dump(canon, f, ensure_ascii=False, indent=2)
    print("[ok] 生成 fields.json (canonical 副本)")

    # 2) 重写各模块 form.fields 为 key 数组
    for fn in sorted(os.listdir(TRAIN_DIR)):
        if not fn.endswith(".json") or fn in ("index.json", "fields.json"):
            continue
        path = os.path.join(TRAIN_DIR, fn)
        with open(path, encoding="utf-8") as f:
            mod = json.load(f)
        mid = mod.get("id")
        dom = ID2DOMAIN.get(mid)
        if not dom or dom not in domains:
            print(f"[skip] {fn}: 无域映射({mid})")
            continue
        dom_keys = [fd["key"] for fd in domains[dom]["fields"]]
        keys = COMMON_KEEP + dom_keys
        mod["fieldDomain"] = dom
        if "form" not in mod:
            mod["form"] = {"name": mod.get("name", ""), "ref": "", "fields": []}
        mod["form"]["fields"] = keys
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mod, f, ensure_ascii=False, indent=2)
        print(f"[ok] {fn}: form.fields -> {len(keys)} 个 key (域={dom})")

    print("\n同步完成。唯一手工源 = sampling_fields.json, 改模板后重跑本脚本即可。")

if __name__ == "__main__":
    main()
