"""内置 Web 工具。

web_search 是一个 *客户端* 函数工具，底层调用智谱的独立 web-search-pro
API（POST /api/paas/v4/tools）。它以文本形式返回原始搜索结果
（标题/链接/内容/媒体），供智能体进行推理。

设计说明：GLM-5.2 的「服务端内置 web_search 工具」与函数工具互斥——同请求里
一旦附带函数工具，服务端就不再注入检索结果（实测确认）。因此 web 搜索改为
客户端函数工具：模型显式调用 web_search，handler 调独立搜索 API 取原始结果回灌，
与其他函数工具（read_file/terminal/think...）天然共存。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent.tools.base import ToolSpec


def make_web_search_tool(base_url: str, api_key: str) -> ToolSpec:
    """创建一个基于智谱 web-search-pro 的 web_search 工具"""
    base = base_url.rstrip("/")

    def _web_search_handler(query: str, limit: int = 5) -> str:
        payload = {
            "model": "web-search-pro",
            "messages": [{"role": "user", "content": query}],
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{base}/tools", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"web_search request failed: {exc}")

        if resp.status_code >= 400:
            raise RuntimeError(f"web_search HTTP {resp.status_code}: {resp.text[:200]}")

        results = _extract_search_results(resp.json())
        if not results:
            return f"web_search: no results for {query!r}."
        return _format_results(query, results[: max(limit, 1)])

    return ToolSpec(
        name="web_search",
        description=(
            "搜索网页获取最新信息。返回标题、URL 和内容摘要。"
            "适用于时效性问题：近期新闻、当前事件、最新发布/版本、实时数据。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词。"},
                "limit": {
                    "type": "integer",
                    "description": "返回的最大结果数。默认：5。",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_web_search_handler,
    )


def _extract_search_results(data: dict[str, Any]) -> list[dict]:
    """从 web-search-pro 响应中提取 search_result 列表。

    响应结构：choices[0].message.tool_calls[*]；其中一项包含
    `search_result` 数组，每项为 {title, link, content, media, refer}。
    """
    choices = data.get("choices") or []
    if not choices:
        return []
    tool_calls = (choices[0].get("message") or {}).get("tool_calls") or []
    for tc in tool_calls:
        items = tc.get("search_result")
        if isinstance(items, list):
            return items
    return []


def _format_results(query: str, results: list[dict]) -> str:
    lines = [f"web_search results for {query!r} ({len(results)} hits):"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        media = (r.get("media") or "").strip()
        link = (r.get("link") or "").strip()
        content = (r.get("content") or "").strip()
        if len(content) > 800:
            content = content[:800] + "..."
        lines.append(f"\n[{i}] {title} ({media})\n    {link}\n    {content}")
    return "\n".join(lines)
