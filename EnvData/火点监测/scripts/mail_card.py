# -*- coding: utf-8 -*-
"""把「火点晨检卡」用 SMTP 发到任意邮箱。

为什么不走连接器：Gmail / Outlook 连接器只管自家邮箱。
SMTP 直发**任何支持 SMTP 的邮箱都能用**（QQ / 163 / 126 / 腾讯企业邮 / 阿里云邮 /
自建域名邮 / Gmail / Outlook…），只要给一个「授权码」。

密钥文件（**不进仓库、不打印**）：~/.workbuddy-ai/fire-card/smtp.json
  {
    "host": "smtp.qq.com",        # SMTP 服务器
    "port": 465,                  # 465=SSL（推荐）  587=STARTTLS
    "ssl": true,                  # port 465 用 true；587 用 false
    "user": "xxxx@qq.com",        # 发信账号（完整邮箱）
    "authcode": "xxxxxxxxxxxx",   # ★ 授权码，不是登录密码
    "to": "jinghao.song@gmail.com"  # 收件人（可逗号分隔多个）
  }

用法：
  python mail_card.py                # 发河南省全省卡（PNG 附件 + 文字正文）
  python mail_card.py 洛阳 南阳      # 发指定市（最多附 3 张图）
  python mail_card.py --no-image     # 只发文字，不带附件
  python mail_card.py --dry          # 只打印，不发送
"""
import json
import os
import smtplib
import ssl as ssl_mod
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import push_card as PC          # 复用摘要与卡片查找逻辑

CONF = Path.home() / ".workbuddy-ai" / "fire-card" / "smtp.json"
SITE = PC.SITE


def load_conf():
    if not CONF.exists():
        raise SystemExit(
            "[mail] 缺少配置文件：%s\n"
            "       格式见脚本顶部注释（host / port / ssl / user / authcode / to）。\n"
            "       授权码在各邮箱「设置 → 账户 → POP3/SMTP服务」里单独开启，不是登录密码。" % CONF)
    c = json.loads(CONF.read_text(encoding="utf-8"))
    for k in ("host", "port", "user", "authcode", "to"):
        if not c.get(k):
            raise SystemExit("[mail] 配置缺少字段：%s" % k)
    return c


def send(conf, subject, body, attachments):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = conf["user"]
    msg["To"] = conf["to"]
    msg.set_content(body)
    for p in attachments:
        msg.add_attachment(p.read_bytes(), maintype="image", subtype="png",
                           filename=p.name)
    port = int(conf["port"])
    if conf.get("ssl", port == 465):
        ctx = ssl_mod.create_default_context()
        with smtplib.SMTP_SSL(conf["host"], port, context=ctx, timeout=60) as s:
            s.login(conf["user"], conf["authcode"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(conf["host"], port, timeout=60) as s:
            s.ehlo()
            s.starttls(context=ssl_mod.create_default_context())
            s.login(conf["user"], conf["authcode"])
            s.send_message(msg)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv[1:]
    no_image = "--no-image" in sys.argv[1:]
    targets = args or ["河南省"]
    if any(t != "河南省" for t in targets):
        targets = [t[:-1] if t.endswith("市") else t for t in targets]

    payload = json.loads((PC.DATA / "fires-henan.json").read_text(encoding="utf-8"))
    title, text = PC.build_message(targets, payload)
    text = text.replace("**", "")          # 邮件正文用纯文本，去掉 markdown 粗体标记
    text += "\n\n--\n本邮件由脚本自动生成；数据源 NASA FIRMS VIIRS 375m（近实时，非确证）。"

    date_str = datetime.now(PC._BJ).strftime("%Y-%m-%d")
    pngs = [p for p in (PC.card_png(t, date_str) for t in targets[:3]) if p]

    print("[mail] 目标：%s | 正文 %d 字 | 附件 %d 张 | 快照 %s"
          % ("、".join(targets), len(text), len(pngs), payload.get("updated_utc")))

    if dry:
        print("-" * 60)
        print("Subject:", title)
        print(text)
        print("-" * 60)
        print("[mail] --dry：未发送")
        return

    conf = load_conf()
    if not pngs and not no_image:
        print("[mail] ⚠ 没找到今天的卡片图片（cards/%s/…）。先跑 morning_card.py。" % date_str)
    send(conf, title, text, [] if no_image else pngs)
    print("[mail] ✅ 已发送至 %s（附件 %d 张）" % (conf["to"], 0 if no_image else len(pngs)))


if __name__ == "__main__":
    main()
