"""Built-in web tools.

web_search is a *client-side* function tool backed by Zhipu's standalone
web-search-pro API (POST /api/paas/v4/tools). It returns raw search hits
(title/link/content/media) as text for the agent to reason over.

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


def make_web_search_tool(api_base: str, api_key: str) -> ToolSpec:
    """Create a web_search tool backed by Zhipu web-search-pro.

    Credentials are captured in the handler closure; the tool itself is
    registered only when llm.web_search is enabled (see factory).
    """
    base = api_base.rstrip("/")

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
            "Search the web for current information. Returns titles, URLs, and "
            "content snippets. Use for time-sensitive questions: recent news, "
            "current events, latest releases/versions, real-time data."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "limit": {
                    "type": "integer",
                    "description": "Max number of results to return. Default: 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_web_search_handler,
    )


def _extract_search_results(data: dict[str, Any]) -> list[dict]:
    """Pull the search_result list out of the web-search-pro response.

    Response shape: choices[0].message.tool_calls[*]; one entry carries a
    `search_result` array of {title, link, content, media, refer}.
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
