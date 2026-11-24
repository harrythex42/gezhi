"""LLM with streaming output and a tool-calling loop.

chat() yields text deltas. When the model asks for tools, they are executed via
the ToolRegistry and the conversation continues until the model answers in text.
`messages` is mutated in place so the caller keeps the full history.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from . import config
from .tools import ToolRegistry

log = logging.getLogger("llm")
MAX_TOOL_ROUNDS = 5


class OpenAICompatLLM:
    def __init__(self):
        from openai import AsyncOpenAI

        if not config.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY（或 DASHSCOPE_API_KEY）未设置")
        self.client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

    async def chat(self, messages: list[dict], tools: ToolRegistry) -> AsyncIterator[str]:
        for _ in range(MAX_TOOL_ROUNDS):
            schemas = tools.openai_schemas()
            kwargs = {"tools": schemas} if schemas else {}
            stream = await self.client.chat.completions.create(
                model=config.LLM_MODEL, messages=messages, stream=True, **kwargs)

            text = ""
            calls: dict[int, dict] = {}
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text += delta.content
                    yield delta.content
                for tc in delta.tool_calls or []:
                    c = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    c["id"] = tc.id or c["id"]
                    if tc.function:
                        c["name"] += tc.function.name or ""
                        c["arguments"] += tc.function.arguments or ""

            if not calls:
                messages.append({"role": "assistant", "content": text})
                return

            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for c in calls.values()
                ],
            })
            for c in calls.values():
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                log.info("tool call %s %s", c["name"], args)
                result = await tools.call(c["name"], args)
                log.info("tool result %s -> %s", c["name"], result[:200])
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})

        yield "抱歉，我有点绕晕了。"


class EchoLLM:
    """Offline stand-in for testing the pipeline without any API key."""

    async def chat(self, messages: list[dict], tools: ToolRegistry) -> AsyncIterator[str]:
        user = messages[-1]["content"]
        reply = f"你刚才说的是：{user}。这是测试模式的回复，服务器链路已经跑通了。"
        for ch in reply:
            yield ch
        messages.append({"role": "assistant", "content": reply})


def create_llm():
    if config.LLM_PROVIDER == "echo":
        return EchoLLM()
    return OpenAICompatLLM()
