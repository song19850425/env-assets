# -*- coding: utf-8 -*-
"""配置：目标城市（后续扩展区县需合同授权的点位数据）"""
CONFIG = {
    "cities": ["郑州市", "新乡市"],
    "sample": True,          # True = 样报模式（页面带"AI草稿·未经审定"标识）
    "client_name": "样报演示",
    "db_path": "data/air.db",
    "out_dir": "out",
    "source": "https://air.cnemc.cn:18007  中国环境监测总站·全国城市空气质量实时发布平台",
}

# 多档案支持：--profile 参数选择。yubei = 豫北四市（GitHub 公开模块）
# coords = 城市代表坐标（市政府/城区中心），用于取气象数据；气象为城市尺度，非点位尺度。
PROFILES = {
    "default": CONFIG,
    "yubei": {
        "cities": ["安阳市", "濮阳市", "鹤壁市", "新乡市"],
        "coords": {
            "安阳市": (36.1034, 114.3931),
            "濮阳市": (35.7615, 115.0291),
            "鹤壁市": (35.7470, 114.2973),
            "新乡市": (35.3027, 113.9268),
        },
        # 可选：省外上风向城市（仅取 AQI，用于传输研判）。置空则不纳入。
        "neighbors": [],
        "sample": True,
        "client_name": "豫北四市（安阳·濮阳·鹤壁·新乡）",
        "db_path": "data/air.db",
        "out_dir": "out/yubei",
        "out_prefix": "大气管家豫北日报",
        "source": "https://air.cnemc.cn:18007  中国环境监测总站·全国城市空气质量实时发布平台",
        "weather_source": "https://api.open-meteo.com   Open-Meteo（免密钥，ECMWF/ICON 模式，小时级）",
    },
}
