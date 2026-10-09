# -*- coding: utf-8 -*-
"""从全省县级 GeoJSON 派生 18 个地级市的边界文件：geo/<市>市_县.geojson

原理：河南省_县.geojson 的每个县 feature 带 properties.gb（9 位 = '156' + 6 位 adcode），
      adcode 前 4 位即地级市码。按此分组即可得到每个市的全部县区。

用途：补齐缺失的市界（鹤壁/新乡/焦作/濮阳/漯河/三门峡/济源），
      并让 fetch_firms.py 能把火点归属到全部 18 个市。

幂等：可重复运行；输出与源文件同源，几何一致。
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEO = HERE.parent / "geo"
PROV = GEO / "河南省_县.geojson"

# adcode 前 4 位 -> 市名（不含「市」字，用于文件名 <名>市_县.geojson）
CITY = {
    "4101": "郑州", "4102": "开封", "4103": "洛阳", "4104": "平顶山", "4105": "安阳",
    "4106": "鹤壁", "4107": "新乡", "4108": "焦作", "4109": "濮阳", "4110": "许昌",
    "4111": "漯河", "4112": "三门峡", "4113": "南阳", "4114": "商丘", "4115": "信阳",
    "4116": "周口", "4117": "驻马店", "4190": "济源",
}


def main():
    prov = json.loads(PROV.read_text(encoding="utf-8"))
    groups = defaultdict(list)
    unknown = []
    for f in prov["features"]:
        gb = f["properties"].get("gb", "")
        ad = gb[3:] if len(gb) >= 9 else gb
        code = ad[:4]
        if code in CITY:
            groups[code].append(f)
        else:
            unknown.append((code, f["properties"].get("name")))

    for code, feats in sorted(groups.items()):
        name = CITY[code]
        out = GEO / f"{name}市_县.geojson"
        fc = {
            "type": "FeatureCollection",
            "name": f"{name}市",
            "crs": prov.get("crs"),
            "features": feats,
        }
        out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        print(f"[geo] {out.name:<22} {len(feats):>3} 个县区")

    print(f"[geo] 生成 {len(groups)} 个市；未识别 {len(unknown)} 条 {unknown[:5]}")

    # 省市合并：每市一个 feature（该市全部县 → MultiPolygon），供「全省总览页」用
    city_features = []
    for code, feats in sorted(groups.items()):
        name = CITY[code]
        coords = []
        for f in feats:
            g = f["geometry"]
            if g["type"] == "Polygon":
                coords.append(g["coordinates"])
            elif g["type"] == "MultiPolygon":
                coords.extend(g["coordinates"])
        city_features.append({
            "type": "Feature",
            "properties": {"name": name, "gb": code},
            "geometry": {"type": "MultiPolygon", "coordinates": coords},
        })
    out = GEO / "henan-cities.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "name": "河南省",
                               "crs": prov.get("crs"), "features": city_features},
                              ensure_ascii=False), encoding="utf-8")
    print(f"[geo] {out.name}  {len(city_features)} 个市（全省总览用）")


if __name__ == "__main__":
    main()
