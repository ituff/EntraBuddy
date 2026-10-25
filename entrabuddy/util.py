"""通用工具函数：路径、时间、安全读取。"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

HOME = os.path.expanduser("~")


def expand(path: str) -> str:
    return os.path.expanduser(path)


def exists(path: str) -> bool:
    return os.path.exists(expand(path))


def mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(expand(path))
    except OSError:
        return None


def iso(ts: Optional[float]) -> Optional[str]:
    """把 epoch 秒转成本地时区的 ISO8601 字符串。"""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return None


def read_text(path: str, encoding: str = "utf-8") -> Optional[str]:
    try:
        with open(expand(path), "r", encoding=encoding, errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(expand(path), "rb") as fh:
            return fh.read()
    except OSError:
        return None


def read_json(path: str) -> Any:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def read_plist(path: str) -> Any:
    raw = read_bytes(path)
    if raw is None:
        return None
    try:
        return plistlib.loads(raw)
    except Exception:
        return None


def read_defaults(domain: str) -> Any:
    """通过 defaults export 读取偏好域，避免解析文本格式。"""
    try:
        out = subprocess.run(
            ["defaults", "export", domain, "-"],
            capture_output=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0 or not out.stdout:
            return None
        return plistlib.loads(out.stdout)
    except Exception:
        return None


def run(cmd: list[str], timeout: float = 8.0) -> Optional[str]:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def human_path(path: str) -> str:
    """把绝对路径缩成 ~ 开头的形式，便于展示。"""
    p = expand(path)
    if p.startswith(HOME):
        return "~" + p[len(HOME):]
    return p
