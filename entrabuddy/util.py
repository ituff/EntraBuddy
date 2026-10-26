"""通用工具函数：路径、时间、安全读取、macOS defaults / Windows 注册表。"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

from ._platform import IS_MACOS, IS_WINDOWS

HOME = os.path.expanduser("~")

# Windows 专属根路径（在 macOS 上仅为占位，不会被采集器使用）
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
APPDATA_ROAMING = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
PROGRAMDATA = os.environ.get("ProgramData") or r"C:\ProgramData"

# EntraBuddy 自身数据目录（快照 / 备份），按平台落在约定位置
if IS_MACOS:
    APP_SUPPORT = os.path.join(HOME, "Library", "Application Support", "EntraBuddy")
else:
    APP_SUPPORT = os.path.join(LOCALAPPDATA, "EntraBuddy")


def expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


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


# ---------- macOS：defaults export ----------

def read_defaults(domain: str) -> Any:
    """通过 defaults export 读取偏好域，避免解析文本格式（仅 macOS）。"""
    if not IS_MACOS:
        return None
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


# ---------- Windows：注册表 ----------

def reg_value(root: int, path: str, name: str) -> Any:
    """读取单个注册表值；键/值不存在或不可读时返回 None（仅 Windows）。"""
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            value, _type = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None
    except ImportError:
        return None


def reg_subkeys(root: int, path: str) -> list[str]:
    """枚举子键名；键不存在时返回空列表（仅 Windows）。"""
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            names = []
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
            return names
    except OSError:
        return []
    except ImportError:
        return []


def reg_values(root: int, path: str) -> dict[str, Any]:
    """枚举一个键下的全部值；键不存在时返回空字典（仅 Windows）。"""
    result: dict[str, Any] = {}
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    name, value, _type = winreg.EnumValue(key, index)
                    result[name] = value
                    index += 1
                except OSError:
                    break
    except OSError:
        pass
    except ImportError:
        pass
    return result


# ---------- 子进程 ----------

def _decode_console(raw: bytes) -> str:
    """控制台输出可能是 UTF-8 也可能是 ANSI 代码页（如 GBK），按需回退。"""
    try:
        text = raw.decode("utf-8")
        if "\ufffd" not in text:
            return text
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("mbcs")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def run(cmd: list[str], timeout: float = 8.0) -> Optional[str]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        out = subprocess.run(
            cmd, capture_output=True, timeout=timeout, check=False, creationflags=flags
        )
        if out.returncode != 0 and not out.stdout:
            return None
        return _decode_console(out.stdout).strip()
    except Exception:
        return None


def human_path(path: str) -> str:
    """把绝对路径缩成 ~（macOS）或 %LOCALAPPDATA%（Windows）开头的形式，便于展示。"""
    p = expand(path)
    if IS_WINDOWS and p.startswith(LOCALAPPDATA):
        return "%LOCALAPPDATA%" + p[len(LOCALAPPDATA):]
    if p.startswith(HOME):
        return "~" + p[len(HOME):]
    return p
