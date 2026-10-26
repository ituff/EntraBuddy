"""解析 OneDrive 同步客户端的账户信息。"""

from __future__ import annotations

import glob
import os
from typing import Any, Dict, List

from ..util import HOME, read_plist

SUITE_PLIST = os.path.join(
    HOME,
    "Library/Group Containers/UBF8T346G9.OneDriveSyncClientSuite/Library/Preferences/"
    "UBF8T346G9.OneDriveSyncClientSuite.plist",
)

APP_ID = "com.microsoft.OneDrive-mac"


def evidence_path(slot: str) -> str:
    return SUITE_PLIST
CLOUD_STORAGE = os.path.join(HOME, "Library/CloudStorage")
APP_PATH = "/Applications/OneDrive.app"


def collect() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "installed": os.path.isdir(APP_PATH),
        "plist_available": os.path.exists(SUITE_PLIST),
        "available": os.path.exists(SUITE_PLIST),
        "accounts": [],
        "mounts": [],
    }

    if os.path.isdir(CLOUD_STORAGE):
        for name in sorted(os.listdir(CLOUD_STORAGE)):
            if name.startswith("OneDrive"):
                result["mounts"].append(
                    {
                        "name": name,
                        "path": os.path.join(CLOUD_STORAGE, name),
                        "kind": "business" if "-" in name and "个人" not in name else "personal",
                    }
                )

    data = read_plist(SUITE_PLIST) or {}
    for key, value in data.items():
        if not key.startswith("AccountInfo_") or not isinstance(value, dict):
            continue
        slot = key[len("AccountInfo_"):]
        if slot == "(null)":
            continue
        email = value.get("UserEmail")
        if not email:
            continue
        stamp = value.get("LastUARTimestamp")
        if hasattr(stamp, "isoformat"):
            stamp = stamp.isoformat(timespec="seconds")
        result["accounts"].append(
            {
                "slot": slot,
                "email": email,
                "cid": value.get("cid"),
                "tenant_id": value.get("TenantId"),
                "market": value.get("AccountMarket"),
                "kind": "personal" if slot.lower().startswith("personal") else "business",
                "last_seen": stamp,
            }
        )

    return result


def account_slot_paths(upn: str) -> List[str]:
    """macOS 的 OneDrive 账户存在 plist 中，自动清理易损坏配置，暂不支持。"""
    return []
