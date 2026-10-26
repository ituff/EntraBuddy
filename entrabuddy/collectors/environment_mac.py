"""环境侧信息：已安装应用、MDM 注册、Defender、系统账户。"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List

from ..util import HOME, exists, iso, mtime, read_defaults, run

# 已知的微软应用 -> 检测路径
KNOWN_APPS: List[Dict[str, str]] = [
    {"id": "com.microsoft.Word", "name": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "kind": "office"},
    {"id": "com.microsoft.Excel", "name": "Microsoft Excel", "path": "/Applications/Microsoft Excel.app", "kind": "office"},
    {"id": "com.microsoft.Powerpoint", "name": "Microsoft PowerPoint", "path": "/Applications/Microsoft PowerPoint.app", "kind": "office"},
    {"id": "com.microsoft.onenote.mac", "name": "Microsoft OneNote", "path": "/Applications/Microsoft OneNote.app", "kind": "office"},
    {"id": "com.microsoft.Outlook", "name": "Microsoft Outlook", "path": "/Applications/Microsoft Outlook.app", "kind": "office"},
    {"id": "com.microsoft.edgemac", "name": "Microsoft Edge", "path": "/Applications/Microsoft Edge.app", "kind": "browser"},
    {"id": "com.microsoft.OneDrive-mac", "name": "OneDrive", "path": "/Applications/OneDrive.app", "kind": "sync"},
    {"id": "com.microsoft.teams2", "name": "Microsoft Teams", "path": "/Applications/Microsoft Teams.app", "kind": "chat"},
    {"id": "com.microsoft.CompanyPortalMac", "name": "Company Portal", "path": "/Applications/Company Portal.app", "kind": "mdm"},
    {"id": "com.microsoft.rdc.macos", "name": "Windows App", "path": "/Applications/Windows App.app", "kind": "remote"},
    {"id": "com.microsoft.wdav", "name": "Microsoft Defender", "path": "/Applications/Microsoft Defender.app", "kind": "security"},
    {"id": "com.microsoft.m365copilot", "name": "Microsoft 365 Copilot", "path": "/Applications/Microsoft 365 Copilot.app", "kind": "assistant"},
    {"id": "com.microsoft.autoupdate2", "name": "Microsoft AutoUpdate", "path": "/Library/Application Support/Microsoft/MAU2.0", "kind": "updater"},
]


def installed_apps() -> List[Dict[str, Any]]:
    apps = []
    for spec in KNOWN_APPS:
        path = spec["path"]
        found = exists(path)
        apps.append({**spec, "installed": found})
    return apps


def mdm_status() -> Dict[str, Any]:
    raw = run(["profiles", "status", "-type", "enrollment"], timeout=6) or ""
    enrolled = "MDM enrollment: Yes" in raw
    dep = "Enrolled via DEP: Yes" in raw
    return {
        "enrolled": enrolled,
        "dep": dep,
        "raw": raw.strip().splitlines(),
    }


def defender_status() -> Dict[str, Any]:
    binary = "/usr/local/bin/mdatp"
    if not os.path.exists(binary):
        return {"installed": False}
    org_id = run([binary, "health", "--field", "org_id"], timeout=6) or ""
    org_id = org_id.strip().strip('"')
    return {
        "installed": True,
        "org_id": org_id or None,
        "onboarded": bool(org_id),
    }


def teams_traces() -> Dict[str, Any]:
    container = os.path.join(HOME, "Library/Group Containers/UBF8T346G9.com.microsoft.teams")
    if not os.path.isdir(container):
        return {"present": False}
    logs = glob.glob(os.path.join(container, "Library/Application Support/Logs/*.log"))
    latest = max((mtime(p) or 0 for p in logs), default=0)
    return {
        "present": True,
        "path": container,
        "log_count": len(logs),
        "last_activity": iso(latest) if latest else None,
    }


def system_accounts() -> Dict[str, Any]:
    """macOS 系统「互联网账户」中是否有 Exchange / Microsoft 账户。"""
    data = read_defaults("com.apple.accountsd") or {}
    plugins = data.get("AuthenticationPluginCache") if isinstance(data, dict) else {}
    has_exchange = bool(plugins and "com.apple.account.Exchange" in plugins)
    return {
        "exchange_plugin": has_exchange,
        "accounts_dir_present": os.path.isdir(os.path.join(HOME, "Library/Accounts")),
        "accounts_dir_empty": not any(
            glob.glob(os.path.join(HOME, "Library/Accounts", "*"))
        ),
    }


def collect() -> Dict[str, Any]:
    return {
        "apps": installed_apps(),
        "mdm": mdm_status(),
        "defender": defender_status(),
        "teams": teams_traces(),
        "system": system_accounts(),
    }
