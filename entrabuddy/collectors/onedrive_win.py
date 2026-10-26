"""解析 OneDrive 同步客户端的账户信息（Windows 版，读注册表）。

macOS 版读 OneDriveSyncClientSuite.plist；Windows 版对应数据在：
    `HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\<slot>`
其中 slot 为 Business1..Business5 / Personal。实测字段：

    UserEmail                  登录邮箱
    cid                        个人版为 16 位 hex 的 MSA cid；
                               企业版实为该账户在租户内的 objectId（GUID）
    ConfiguredTenantId         企业版的租户 ID
    DisplayName / UserFolder   显示名 / 本地同步目录
    LastUserActivityTimestamp  QWORD Unix 时间戳
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from ..util import LOCALAPPDATA, expand, iso, reg_subkeys, reg_value, reg_values

APP_ID = "com.microsoft.onedrive"

ACCOUNTS_KEY = r"Software\Microsoft\OneDrive\Accounts"
# OneDrive 新版默认按机器安装到 Program Files；旧版在 LOCALAPPDATA
ONEDRIVE_EXES = [
    r"%ProgramFiles%\Microsoft OneDrive\OneDrive.exe",
    r"%ProgramFiles(x86)%\Microsoft OneDrive\OneDrive.exe",
    r"%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe",
]

CID_RE = re.compile(r"^[0-9a-f]{16}$", re.I)
GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def evidence_path(slot: str) -> str:
    return rf"HKCU\Software\Microsoft\OneDrive\Accounts\{slot}"


def _installed() -> bool:
    if winreg is None:
        return False
    if any(os.path.isfile(expand(p)) for p in ONEDRIVE_EXES):
        return True
    # 注册表里记录的启动路径
    trigger = reg_value(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive", "OneDriveTrigger")
    return bool(trigger and os.path.isfile(expand(str(trigger))))


def _latest_stamp(values: Dict[str, Any]) -> Optional[float]:
    stamps = [
        v
        for k, v in values.items()
        if k in ("LastUserActivityTimestamp", "LastSignInTime")
        and isinstance(v, int)
        and v > 0
    ]
    return max(stamps) if stamps else None


def collect() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "installed": _installed(),
        "plist_available": False,   # 保留字段名，供旧视图兼容
        "available": False,
        "accounts": [],
        "mounts": [],
    }

    if winreg is None:
        return result

    slots = reg_subkeys(winreg.HKEY_CURRENT_USER, ACCOUNTS_KEY)
    for slot in slots:
        if slot in ("FileCoAuth",):
            continue
        values = reg_values(winreg.HKEY_CURRENT_USER, ACCOUNTS_KEY + "\\" + slot)
        email = values.get("UserEmail")
        if not email:
            continue
        result["available"] = True

        raw_cid = str(values.get("cid") or "").strip()
        cid = raw_cid.lower() if CID_RE.match(raw_cid) else None
        object_id = raw_cid.lower() if GUID_RE.match(raw_cid) else None

        user_folder = values.get("UserFolder")
        if user_folder and os.path.isdir(expand(str(user_folder))):
            result["mounts"].append(
                {
                    "name": os.path.basename(expand(str(user_folder))),
                    "path": expand(str(user_folder)),
                    "kind": "personal" if slot.lower().startswith("personal") else "business",
                }
            )

        stamp = _latest_stamp(values)
        result["accounts"].append(
            {
                "slot": slot,
                "email": email,
                "cid": cid,
                "object_id": object_id,
                "tenant_id": values.get("ConfiguredTenantId") or None,
                "display_name": values.get("DisplayName") or None,
                "market": None,
                "kind": "personal" if slot.lower().startswith("personal") else "business",
                "last_seen": iso(stamp),
            }
        )

    return result
