"""Tools the LLM can call: server-side Python functions plus the device's MCP tools.

To add your own tool, write an async function and register it in
register_builtin_tools(), e.g. read your Obsidian notes or Garmin data.
"""
from __future__ import annotations

import datetime
import json
import re
from typing import Awaitable, Callable

Handler = Callable[[dict], Awaitable[str]]


def _safe_name(name: str) -> str:
    # OpenAI-style function names only allow [a-zA-Z0-9_-]; MCP names use dots.
    return re.sub(r"[^a-zA-Z0-9_-]", "__", name)[:64]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[dict, Handler]] = {}

    def register(self, name: str, description: str, parameters: dict, handler: Handler) -> None:
        safe = _safe_name(name)
        schema = {"type": "function",
                  "function": {"name": safe, "description": description, "parameters": parameters}}
        self._tools[safe] = (schema, handler)

    def unregister_prefix(self, prefix: str) -> None:
        for k in [k for k in self._tools if k.startswith(prefix)]:
            del self._tools[k]

    def openai_schemas(self) -> list[dict]:
        return [schema for schema, _ in self._tools.values()]

    async def call(self, name: str, args: dict) -> str:
        if name not in self._tools:
            return f"错误：没有名为 {name} 的工具"
        try:
            return await self._tools[name][1](args)
        except Exception as e:
            return f"工具执行出错：{e}"


async def _get_current_time(_: dict) -> str:
    now = datetime.datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    return now.strftime(f"%Y年%m月%d日 星期{weekday} %H:%M")


def register_builtin_tools(reg: ToolRegistry) -> None:
    reg.register(
        "get_current_time",
        "获取当前的日期、星期和时间。用户问现在几点、今天几号、星期几时调用。",
        {"type": "object", "properties": {}},
        _get_current_time,
    )


def register_device_tools(reg: ToolRegistry, mcp_tools: list[dict],
                          call: Callable[[str, dict], Awaitable[dict]]) -> None:
    """Exposes tools reported by the device (MCP tools/list) to the LLM."""
    reg.unregister_prefix("self__")
    for t in mcp_tools:
        mcp_name = t["name"]

        async def handler(args: dict, _n: str = mcp_name) -> str:
            result = await call(_n, args)
            texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
            out = "\n".join(texts) or json.dumps(result, ensure_ascii=False)
            return ("执行失败：" + out) if result.get("isError") else out

        reg.register(mcp_name, t.get("description", ""),
                     t.get("inputSchema") or {"type": "object", "properties": {}}, handler)
