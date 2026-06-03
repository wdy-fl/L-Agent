"""Built-in web tools: web_search and web_fetch."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request

from agent.tools.base import ToolSpec


def _web_search_handler(query: str, limit: int = 5) -> str:
    raise RuntimeError("web_search requires a search API configuration. Set SEARCH_API_KEY in environment.")


def _web_fetch_handler(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "L-Agent/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to fetch URL: {e}")
    except TimeoutError:
        raise TimeoutError(f"Request timed out: {url}")

    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:50000]


web_search_tool = ToolSpec(
    name="web_search",
    description="Search the web for information. Returns titles, URLs, and snippets.",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "limit": {"type": "integer", "description": "Max number of results. Default: 5."},
        },
        "required": ["query"],
    },
    handler=_web_search_handler,
)

web_fetch_tool = ToolSpec(
    name="web_fetch",
    description="Fetch a web page and return its text content (HTML tags stripped).",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch."},
        },
        "required": ["url"],
    },
    handler=_web_fetch_handler,
)
