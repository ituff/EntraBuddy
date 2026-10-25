"""解析 Office 的登录身份与许可授权。"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Dict, List, Optional

from ..util import HOME, iso, mtime, read_bytes, read_defaults

LICENSE_ROOT = os.path.join(
    HOME, "Library/Group Containers/UBF8T346G9.Office/Licenses"
)
OFFICE_PREFS_DOMAIN = "com.microsoft.office"

# Office 应用与容器路径
OFFICE_APPS = [
    ("com.microsoft.Word", "Microsoft Word", "/Applications/Microsoft Word.app"),
    ("com.microsoft.Excel", "Microsoft Excel", "/Applications/Microsoft Excel.app"),
    (
        "com.microsoft.Powerpoint",
        "Microsoft PowerPoint",
        "/Applications/Microsoft PowerPoint.app",
    ),
    ("com.microsoft.onenote.mac", "Microsoft OneNote", "/Applications/Microsoft OneNote.app"),
]


def _b64url(seg: str) -> bytes:
    seg += "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg)


def _short_date(value: Optional[str]) -> Optional[str]:
    """把 2026-12-25T09:47:06.720309Z 收敛成 2026-12-25。"""
    if not value:
        return None
    return value.split("T")[0]


def _decode_license(raw: bytes) -> Optional[Dict[str, Any]]:
    text: Optional[str] = None
    for encoding in ("utf-16", "utf-16-le", "utf-8"):
        try:
            candidate = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if '"License"' in candidate:
            text = candidate
            break
    if text is None:
        return None

    try:
        payload = json.loads(text)
    except ValueError:
        return None

    info: Dict[str, Any] = {
        "max_devices": payload.get("MaxDevicesAllowed"),
        "is_trial": payload.get("IsTrial"),
        "is_admin": payload.get("IsAdmin"),
        "cid": None,
        "license_id": None,
        "not_before": None,
        "not_after": None,
        "identity": None,
    }

    token = payload.get("License") or ""
    # License 字段是 base64 编码的 JSON，里面再嵌一个 RenewalToken
    try:
        decoded = json.loads(_b64url(token.split(".")[0]).decode("utf-8"))
        info["max_devices"] = decoded.get("MaxDevicesAllowed", info["max_devices"])
        info["is_trial"] = decoded.get("IsTrial", info["is_trial"])
        renewal = decoded.get("RenewalToken")
        if renewal:
            renewal_payload = json.loads(_b64url(renewal.split(".")[0]).decode("utf-8"))
            identity = renewal_payload.get("Identity") or ""
            info["identity"] = identity
            cid = re.search(r"Cid=([0-9a-fA-F]{16})", identity)
            if cid:
                info["cid"] = cid.group(1).lower()
            info["license_id"] = renewal_payload.get("LicenseId")
            info["not_before"] = _short_date(renewal_payload.get("NotBefore"))
            info["not_after"] = _short_date(renewal_payload.get("NotAfter"))
    except Exception:
        pass

    return info


def collect_licenses() -> List[Dict[str, Any]]:
    licenses: List[Dict[str, Any]] = []
    if not os.path.isdir(LICENSE_ROOT):
        return licenses

    for root, _dirs, files in os.walk(LICENSE_ROOT):
        for name in files:
            path = os.path.join(root, name)
            raw = read_bytes(path)
            if not raw:
                continue
            info = _decode_license(raw)
            if not info:
                continue
            info["path"] = path
            info["last_seen"] = iso(mtime(path))
            info["product"] = os.path.basename(root)
            licenses.append(info)
    return licenses


def collect() -> Dict[str, Any]:
    prefs = read_defaults(OFFICE_PREFS_DOMAIN) or {}
    if not isinstance(prefs, dict):
        prefs = {}

    active_raw = prefs.get("OCPS-LastSuccessfulUserId") or ""
    active_id = active_raw.split("_")[0] if active_raw else None

    result: Dict[str, Any] = {
        "prefs_available": bool(prefs),
        "activation_email": prefs.get("OfficeActivationEmailAddress"),
        "active_account_id": active_id,
        "tenant_key": prefs.get("TenantIDKey"),
        "tenant_result": prefs.get("TenantIDResult"),
        "licenses": collect_licenses(),
        "apps": [
            {
                "id": bundle,
                "name": name,
                "installed": os.path.isdir(app_path),
                "path": app_path,
            }
            for bundle, name, app_path in OFFICE_APPS
        ],
    }
    return result
