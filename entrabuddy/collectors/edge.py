"""解析 Microsoft Edge 的配置文件与登录账户（macOS / Windows 共享）。

Chromium 结构跨平台一致（Local State 的 info_cache + 各 Profile 的
Preferences），仅根目录与安装检测不同：

    macOS    ~/Library/Application Support/Microsoft Edge/
    Windows  %LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\

Windows 上很多配置文件的 `account_info` 为空，登录态要回退到
Local State info_cache 的 user_name 字段；该回退对 macOS 同样无害。
"""

from __future__ import annotations

import glob
import os
from typing import Any, Dict, List, Optional

from ..util import HOME, LOCALAPPDATA, expand, read_json

APP_ID = "com.microsoft.edge"

if os.name == "nt":
    EDGE_ROOT = os.path.join(LOCALAPPDATA, "Microsoft", "Edge", "User Data")
    _EDGE_PROBES = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ]
else:
    EDGE_ROOT = os.path.join(HOME, "Library/Application Support/Microsoft Edge")
    _EDGE_PROBES = ["/Applications/Microsoft Edge.app"]


def _installed() -> bool:
    return any(expand(p) and os.path.exists(expand(p)) for p in _EDGE_PROBES)


def _cached_account(cached: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 Local State 的 info_cache 条目提取登录账户（account_info 为空时的回退）。"""
    email = cached.get("user_name")
    if not email:
        return None
    return {
        "email": email,
        "full_name": cached.get("gaia_name") or cached.get("name"),
        "gaia_id": cached.get("gaia_id") or None,
        "hosted_domain": cached.get("hosted_domain") or None,
        "source": "cache",
    }


def collect() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "installed": _installed(),
        "available": os.path.isdir(EDGE_ROOT),
        "profiles": [],
    }
    if not result["available"]:
        return result

    local_state = read_json(os.path.join(EDGE_ROOT, "Local State")) or {}
    info_cache = ((local_state.get("profile") or {}).get("info_cache")) or {}

    pref_paths = [os.path.join(EDGE_ROOT, "Default", "Preferences")]
    pref_paths += sorted(glob.glob(os.path.join(EDGE_ROOT, "Profile *", "Preferences")))

    for pref_path in pref_paths:
        if not os.path.exists(pref_path):
            continue
        dir_name = os.path.basename(os.path.dirname(pref_path))
        prefs = read_json(pref_path) or {}
        cached = info_cache.get(dir_name) or {}
        accounts = prefs.get("account_info") or []

        profile = {
            "dir": dir_name,
            "name": (prefs.get("profile") or {}).get("name") or cached.get("name"),
            "signed_in": bool(accounts),
            "accounts": [],
        }

        if accounts:
            for acc in accounts:
                profile["accounts"].append(
                    {
                        "email": acc.get("email") or cached.get("user_name"),
                        "full_name": acc.get("full_name") or cached.get("gaia_name"),
                        "gaia_id": cached.get("gaia_id") or acc.get("gaia_id"),
                        "hosted_domain": acc.get("hosted_domain"),
                        "source": "account_info",
                    }
                )
        else:
            # account_info 为空时回退到 Local State 的 user_name
            fallback = _cached_account(cached)
            if fallback:
                profile["accounts"].append(fallback)
            else:
                # 未登录，但保留 gaia 信息用于交叉比对
                profile["hint_email"] = cached.get("user_name")
                profile["hint_name"] = cached.get("gaia_name")

        result["profiles"].append(profile)

    return result
