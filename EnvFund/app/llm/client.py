#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端 —— OpenAI 兼容接口

职责单一：只负责把消息发出去、把返回取回来。
抽取编排（提示词拼装、输出校验、失败重试）在 app/services.py。

适配：DeepSeek / 通义千问 / 智谱 / Moonshot / OpenAI 等所有兼容 /chat/completions 的服务。
仅标准库，无第三方依赖。

环境变量：
    ENV_AGENT_API_KEY   必填
    ENV_AGENT_BASE_URL  默认 https://api.deepseek.com/v1
    ENV_AGENT_MODEL     默认 deepseek-chat
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(RuntimeError):
    """模型调用失败"""


def call_chat_completions(
    messages: list[dict],
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    timeout: int = 180,
    max_retries: int = 3,
) -> str:
    """
    调用 OpenAI 兼容的 /chat/completions。

    temperature 默认 0 —— 抽取任务不需要创造力，需要可复现。
    429 / 5xx 自动指数退避重试；其他错误直接抛出。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            last_err = LLMError(f"HTTP {e.code}：{detail}")
            if e.code not in (429, 500, 502, 503, 504):
                raise last_err from e
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            last_err = LLMError(f"网络或响应异常：{e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # 2s, 4s 退避

    raise LLMError(f"模型调用失败（已重试 {max_retries} 次）：{last_err}")
