# -*- coding: utf-8 -*-
"""把「火点晨检卡」推送到群机器人（企业微信 / 钉钉，按 Webhook 域名自动识别）。

用法：
    python push_card.py                 # 推河南省全省卡（含图片，企业微信）
    python push_card.py 洛阳 南阳        # 推指定市
    python push_card.py --dry           # 只打印将要发送的内容，不真发
    python push_card.py --no-image      # 只发文字摘要，不发图片

Webhook 从哪来（按顺序找）：
    1) 环境变量 WEBHOOK_URL（或 DINGTALK_WEBHOOK / WECOM_WEBHOOK）
       加签密钥：WEBHOOK_SECRET（或 DINGTALK_SECRET）
    2) 本地密钥文件（默认 ~/.workbuddy-ai/fire-card/webhook.txt）
       第一行 = Webhook 地址，第二行 = 加签密钥（没有就留空）
    **绝不写进仓库**：Webhook 泄露 = 任何人都能往你群里发消息。

## 平台能力（决定了发图片还是只发文字）

| 平台 | Webhook 域名 | 能否直接发图片 |
|---|---|---|
| **企业微信** | `qyapi.weixin.qq.com` | ✅ `image` 消息，base64+md5，**原图 ≤2MB** |
| 钉钉 | `oapi.dingtalk.com` | ❌ 只有 text/markdown/link/actionCard；要图片得给**公网可访问的图片 URL** |

所以：企业微信 = 图片 + 文字摘要两条消息；钉钉 = 只能发 markdown 文字版（会明确提示）。

## 图片从哪来

由 `morning_card.py` 生成的卡片 PNG：`../cards/<日期>/<市>火点晨检卡.png`。
**本脚本不自己生成卡片**，找不到会提示先跑 morning_card.py。

数据来源：仓库里已归档的 FIRMS 数据（CI 每 6 小时更新）；本脚本不抓 FIRMS、不用 FIRMS 密钥。
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent                      # EnvData/火点监测
DATA = MOD / "data"
CARDS = MOD / "cards"
SITE = ("https://song19850425.github.io/env-assets/EnvData/"
        "%E7%81%AB%E7%82%B9%E7%9B%91%E6%B5%8B")

_BJ = timezone(timedelta(hours=8))
SECRET_FILE = Path(os.environ.get(
    "WEBHOOK_SECRET_FILE",
    str(Path.home() / ".workbuddy-ai" / "fire-card" / "webhook.txt")))
MAX_LEN = 3500                         # 钉钉 markdown 有长度上限，留足余量
WECOM_IMG_MAX = 2 * 1024 * 1024        # 企业微信 image 消息：原图 ≤2MB


# ---------------- 平台识别与发送 ----------------
def detect_platform(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if "qyapi.weixin.qq.com" in host:
        return "wecom"
    if "oapi.dingtalk.com" in host:
        return "dingtalk"
    if "open.feishu.cn" in host or "open.larksuite.com" in host:
        return "feishu"
    return "unknown"


def load_webhook():
    url = (os.environ.get("WEBHOOK_URL")
           or os.environ.get("WECOM_WEBHOOK")
           or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    secret = (os.environ.get("WEBHOOK_SECRET")
              or os.environ.get("DINGTALK_SECRET") or "").strip()
    if not url and SECRET_FILE.exists():
        lines = [l.strip() for l in SECRET_FILE.read_text(encoding="utf-8").splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
        if lines:
            url, secret = lines[0], (lines[1] if len(lines) > 1 else "")
    if not url:
        raise SystemExit(
            "[push] 没找到群机器人 Webhook。请二选一：\n"
            "       ① 设环境变量 WEBHOOK_URL（可选 WEBHOOK_SECRET）\n"
            "       ② 写本地密钥文件：%s\n"
            "          第一行 = Webhook 地址，第二行 = 加签密钥（没有就留空）" % SECRET_FILE)
    return url, secret


def post_json(url, obj, timeout=30):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except Exception:
        return {"errcode": -1, "errmsg": "返回非 JSON：%s" % raw[:200]}


def _check(resp, platform):
    """钉钉与企业微信都用 errcode==0 表示成功。"""
    code = resp.get("errcode", resp.get("code", -1))
    if code != 0:
        raise RuntimeError("%s 返回错误：%s" % (platform, resp))
    return resp


def dingtalk_url(webhook, secret):
    """钉钉「加签」：timestamp + HMAC-SHA256(secret, 'ts\\nsecret') → base64 → urlencode。"""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    raw = "%s\n%s" % (ts, secret)
    sign = urllib.parse.quote_plus(base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw.encode("utf-8"),
                 digestmod=hashlib.sha256).digest()))
    sep = "&" if "?" in webhook else "?"
    return "%s%stimestamp=%s&sign=%s" % (webhook, sep, ts, sign)


def send_text(platform, webhook, secret, title, text):
    """发一条文字消息。企业微信/钉钉都是 markdown；飞书用 post。"""
    if platform == "wecom":
        return _check(post_json(webhook, {
            "msgtype": "markdown", "markdown": {"content": text}}), "企业微信")
    if platform == "dingtalk":
        return _check(post_json(dingtalk_url(webhook, secret), {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text}}), "钉钉")
    if platform == "feishu":
        return _check(post_json(webhook, {
            "msgtype": "text", "content": {"text": text}}), "飞书")
    raise SystemExit("[push] 不认识的 Webhook 域名，无法发送：%s" % webhook)


def send_image_wecom(webhook, png_path):
    """企业微信 image 消息：base64 + md5，原图必须 ≤2MB。"""
    raw = png_path.read_bytes()
    if len(raw) > WECOM_IMG_MAX:
        raise RuntimeError("图片 %.1fMB 超过企业微信 2MB 上限：%s"
                           % (len(raw) / 1048576.0, png_path.name))
    return _check(post_json(webhook, {
        "msgtype": "image",
        "image": {"base64": base64.b64encode(raw).decode("ascii"),
                  "md5": hashlib.md5(raw).hexdigest()}}), "企业微信")


# ---------------- 组织消息内容 ----------------
def kind_of(f):
    """类型标签：昼夜 + 成因。成因本身已含「夜间」时不再重复加前缀。"""
    c = f.get("cause") or "待核实"
    if f.get("dn") == "N" and not c.startswith("夜间"):
        return "夜间·" + c
    return c


def card_png(target, date_str):
    name = ("河南省火点晨检卡.png" if target == "河南省"
            else "%s市火点晨检卡.png" % target)
    p = CARDS / date_str / name
    return p if p.exists() else None


def city_block(city, fires, limit=None):
    n = len(fires)
    frp = sum(float(f.get("frp") or 0) for f in fires)
    conf = {}
    for f in fires:
        k = (f.get("conf") or "n")[:1]
        conf[k] = conf.get(k, 0) + 1
    causes = {}
    for f in fires:
        k = f.get("cause") or "待核实"
        causes[k] = causes.get(k, 0) + 1

    out = ["**%s · %d 个火点 · %.1f MW**" % (city, n, frp)]
    confs = " · ".join(x for x in [
        ("高置信 %d" % conf.get("h", 0)) if conf.get("h") else "",
        ("中置信 %d" % conf.get("n", 0)) if conf.get("n") else "",
        ("低置信 %d" % conf.get("l", 0)) if conf.get("l") else ""] if x)
    if confs:
        out.append("置信度：%s" % confs)
    if causes:
        out.append("成因：" + " · ".join("%s %d" % (k, v)
                                        for k, v in sorted(causes.items(), key=lambda kv: -kv[1])))
    if n:
        out.append("")
        out.append("明细（按 FRP 从大到小）：")
        show = sorted(fires, key=lambda f: -(float(f.get("frp") or 0)))
        if limit:
            show = show[:limit]
        for i, f in enumerate(show, 1):
            out.append("%d. %s · %.4f,%.4f · %.1f MW"
                       % (i, kind_of(f), f["lat"], f["lng"], float(f.get("frp") or 0)))
        if limit and n > limit:
            out.append("…… 共 %d 条，其余见在线地图" % n)
    else:
        out.append("近 2 天无火点。")
    return "\n".join(out)


def build_message(targets, payload):
    cities = payload.get("cities") or {}
    snap = payload.get("updated_utc", "")
    date = datetime.now(_BJ).strftime("%Y-%m-%d")

    if targets == ["河南省"]:
        fires, by_city, causes = [], {}, {}
        for c, lst in cities.items():
            if c == "省外":
                continue
            by_city[c] = len(lst)
            fires.extend(lst)
            for f in lst:
                k = f.get("cause") or "待核实"
                causes[k] = causes.get(k, 0) + 1
        total = len(fires)
        frp = sum(float(f.get("frp") or 0) for f in fires)
        title = "河南火点晨检卡 · %s · %d 个火点" % (date, total)

        lines = ["**🔥 河南火点晨检卡 · %s**" % date, ""]
        lines.append("全省 **%d** 个火点 · FRP 合计 **%.1f MW**" % (total, frp))
        if causes:
            lines.append("成因：" + " · ".join("%s %d" % (k, v)
                                            for k, v in sorted(causes.items(), key=lambda kv: -kv[1])))
        lines.append("")
        lines.append("**各市火点（前 10）**")
        for i, (c, n) in enumerate(sorted(by_city.items(), key=lambda kv: -kv[1])[:10], 1):
            top = max(((f.get("cause") or "待核实") for f in cities[c]),
                      key=lambda k: sum(1 for f in cities[c] if (f.get("cause") or "待核实") == k))
            lines.append("%d. %s %d 个 · %s" % (i, c, n, top))
        lines.append("")
        lines.append("数据快照 %s · 每 6 小时自动更新" % snap)
        lines.append("[查看交互地图 / 各市卡片](%s)" % SITE)
        lines.append("成因列为基于「点位历史复现 + 遥感特征」的推测，非确证。")
        return title, "\n".join(lines)

    parts = ["**🔥 火点晨检卡 · %s**" % date, ""]
    for c in targets:
        parts.append(city_block(c, cities.get(c) or [], limit=15))
        parts.append("")
    parts.append("数据快照 %s · 每 6 小时自动更新" % snap)
    parts.append("[查看交互地图](%s)" % SITE)
    return "火点晨检卡 · %s · %s" % (date, "、".join(targets)), "\n".join(parts)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv[1:]
    no_image = "--no-image" in sys.argv[1:]
    targets = args or ["河南省"]
    if any(t != "河南省" for t in targets):
        targets = [t[:-1] if t.endswith("市") else t for t in targets]

    payload = json.loads((DATA / "fires-henan.json").read_text(encoding="utf-8"))
    title, text = build_message(targets, payload)
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 40] + "\n\n……（内容过长已截断，完整版见在线地图）"

    date_str = datetime.now(_BJ).strftime("%Y-%m-%d")
    pngs = [p for p in (card_png(t, date_str) for t in targets[:3]) if p]

    webhook, secret = ("", "")
    platform = "?"
    if not dry:
        webhook, secret = load_webhook()
        platform = detect_platform(webhook)

    print("[push] 目标：%s | 文字 %d 字 | 数据快照 %s"
          % ("、".join(targets), len(text), payload.get("updated_utc")))
    if dry:
        print("[push] 平台：--dry 未连接 | 找到卡片图片 %d 张：%s"
              % (len(pngs), "、".join(p.name for p in pngs) or "无"))
        print("-" * 60)
        print(text)
        print("-" * 60)
        print("[push] --dry：未发送")
        return

    print("[push] 平台：%s" % platform)
    if not pngs:
        print("[push] ⚠ 没找到今天的卡片图片（%s/%s/…）。先跑 morning_card.py 生成卡片。"
              % (CARDS.name, date_str))

    if platform == "wecom":
        sent = 0
        if pngs and not no_image:
            for p in pngs:
                send_image_wecom(webhook, p)
                sent += 1
                print("[push] ✅ 已发图片：%s（%.0f KB）" % (p.name, p.stat().st_size / 1024))
        elif pngs and no_image:
            print("[push] --no-image：跳过图片，只发文字")
        else:
            print("[push] 没有图片可发，只发文字")
        send_text(platform, webhook, secret, title, text)
        print("[push] ✅ 已发文字摘要（含 %d 张图片）" % sent)
    else:
        if pngs and platform == "dingtalk":
            print("[push] ⚠ 钉钉自定义机器人不支持直接发图片，本次只发文字版卡片。"
                  "要图片请改用企业微信机器人（支持 image 消息）。")
        send_text(platform, webhook, secret, title, text)
        print("[push] ✅ 已发文字卡片")


if __name__ == "__main__":
    main()
