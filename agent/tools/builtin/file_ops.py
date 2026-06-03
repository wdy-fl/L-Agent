"""Built-in file operation tools: read_file, write_file, list_directory, search_file."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from agent.tools.base import ToolSpec


def _read_file_handler(file_path: str, offset: int = 1, limit: int | None = None) -> str:
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {file_path}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    start = max(0, offset - 1)
    end = start + limit if limit else len(lines)
    selected = lines[start:end]

    numbered = []
    for i, line in enumerate(selected, start=start + 1):
        numbered.append(f"{i}\t{line.rstrip()}")
    return "\n".join(numbered)


def _write_file_handler(file_path: str, content: str) -> str:
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {file_path}"


def _list_directory_handler(path: str, recursive: bool = False, pattern: str | None = None) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    if not p.is_dir():
        raise ValueError(f"Not a directory: {path}")

    entries: list[str] = []
    if recursive:
        for root, dirs, files in os.walk(p):
            for name in dirs + files:
                rel = os.path.relpath(os.path.join(root, name), p)
                if pattern and not fnmatch.fnmatch(name, pattern):
                    continue
                entries.append(rel)
    else:
        for item in sorted(p.iterdir()):
            if pattern and not fnmatch.fnmatch(item.name, pattern):
                continue
            suffix = "/" if item.is_dir() else ""
            entries.append(item.name + suffix)

    return "\n".join(entries) if entries else "(empty)"


def _search_file_handler(pattern: str, path: str = ".", file_pattern: str | None = None) -> str:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid pattern: {e}")

    matches: list[str] = []
    target = root if root.is_dir() else root.parent
    files = [root] if root.is_file() else target.rglob("*")

    for fp in files:
        if not fp.is_file():
            continue
        if file_pattern and not fnmatch.fnmatch(fp.name, file_pattern):
            continue
        try:
            for i, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    rel = os.path.relpath(fp, path)
                    matches.append(f"{rel}:{i}: {line}")
        except (OSError, UnicodeDecodeError):
            continue

    return "\n".join(matches) if matches else "No matches found."


read_file_tool = ToolSpec(
    name="read_file",
    description="Read the contents of a file. Returns numbered lines. Use offset/limit for large files.",
    parameters_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file to read."},
            "offset": {"type": "integer", "description": "Starting line number (1-based). Default: 1."},
            "limit": {"type": "integer", "description": "Number of lines to read. Default: all."},
        },
        "required": ["file_path"],
    },
    handler=_read_file_handler,
)

write_file_tool = ToolSpec(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed. Overwrites existing content.",
    parameters_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file to write."},
            "content": {"type": "string", "description": "Content to write to the file."},
        },
        "required": ["file_path", "content"],
    },
    handler=_write_file_handler,
)

list_directory_tool = ToolSpec(
    name="list_directory",
    description="List files and directories at a path. Use recursive=true for deep listing, pattern for glob filtering.",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list."},
            "recursive": {"type": "boolean", "description": "Recurse into subdirectories. Default: false."},
            "pattern": {"type": "string", "description": "Glob pattern to filter entries (e.g. '*.py')."},
        },
        "required": ["path"],
    },
    handler=_list_directory_handler,
)

search_file_tool = ToolSpec(
    name="search_file",
    description="Search file contents using regex. Returns matching lines with file path and line number.",
    parameters_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for."},
            "path": {"type": "string", "description": "Directory or file to search in. Default: current directory."},
            "file_pattern": {"type": "string", "description": "Glob to filter filenames (e.g. '*.py')."},
        },
        "required": ["pattern"],
    },
    handler=_search_file_handler,
)
