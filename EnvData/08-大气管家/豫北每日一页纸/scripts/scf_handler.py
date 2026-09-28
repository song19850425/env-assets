# -*- coding: utf-8 -*-
"""腾讯云云函数 SCF 入口（国内节点，无跨境访问风险）

为什么保留这条路线：GitHub Actions 的 runner 在海外，能否访问
air.cnemc.cn:18007 尚未证实。国内云函数天然没有这个问题，
是唯一能"确定性可用"的方案。

部署要点：
1. 函数目录需与 `air_collect.py` 同层（把两个文件一起打包上传）。
2. 运行时：Python 3.9+；超时设 60 秒即可（实测全量采集约 3–8 秒）；内存 128MB 够。
3. 添加【定时触发器】：cron 表达式 `0 17 * * * * *`（SCF 为 7 段式，秒 分 时 日 月 周 年），
   即每小时 17 分 0 秒触发。
4. 存储二选一：
   a) 环境变量配置 COS（推荐，持久化）：
        COS_SECRET_ID / COS_SECRET_KEY / COS_REGION / COS_BUCKET
      依赖：在「函数配置 → 层」挂载 cos-python-sdk-v5，或改为使用函数角色+临时密钥。
   b) 不配置则只打日志（可用于先验证"国内节点能否连通接口"这一件事）。
5. 若用 a)，对象键为 `air-hourly/YYYY-MM-DD.jsonl` 与 `air-hourly/_health.json`。

返回值会出现在 SCF 日志与调用结果里，含 ok / 抓取条数 / 新增条数，便于配置告警。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import air_collect  # noqa: E402

TMP = "/tmp/air-hourly"


def _upload(local_path, key):
    """上传到 COS；未配置或缺少 SDK 时静默跳过（不阻断采集本身）"""
    sid = os.environ.get("COS_SECRET_ID")
    skey = os.environ.get("COS_SECRET_KEY")
    region = os.environ.get("COS_REGION")
    bucket = os.environ.get("COS_BUCKET")
    if not all([sid, skey, region, bucket]):
        print("[COS] 未配置，跳过上传（仅本地 /tmp）")
        return False
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        print("[COS] 未安装 cos-python-sdk-v5，跳过上传")
        return False
    try:
        client = CosS3Client(CosConfig(Region=region, SecretId=sid,
                                       SecretKey=skey, Scheme="https"))
        with open(local_path, "rb") as f:
            client.put_object(Bucket=bucket, Body=f, Key=key)
        print("[COS] 已上传 %s" % key)
        return True
    except Exception as e:
        print("[COS] 上传失败 %s: %s" % (key, e))
        return False


def main_handler(event, context):
    rc, path, got, new = air_collect.run(TMP)
    day = os.path.basename(path).replace(".jsonl", "")

    uploaded = []
    if os.path.exists(path):
        if _upload(path, "air-hourly/%s.jsonl" % day):
            uploaded.append(path)
    hp = os.path.join(TMP, "_health.json")
    if os.path.exists(hp):
        _upload(hp, "air-hourly/_health.json")

    result = {
        "ok": rc == 0,
        "exit_code": rc,
        "date": day,
        "records_fetched": got,
        "records_new": new,
        "uploaded": len(uploaded),
    }
    print("[结果] %s" % json.dumps(result, ensure_ascii=False))
    return result
