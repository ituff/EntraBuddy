"""平台识别与采集器分派依据。"""

from __future__ import annotations

import sys

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


def platform_name() -> str:
    """返回面向 UI 的平台标识：macos / windows / other。"""
    if IS_MACOS:
        return "macos"
    if IS_WINDOWS:
        return "windows"
    return "other"
