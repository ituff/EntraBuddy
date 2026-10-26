"""解析 Office 的登录身份与许可授权（Windows 版）。

Windows 上 Office 身份状态的存放位置与 macOS 不同：
    * 许可证文件：`%LOCALAPPDATA%\\Microsoft\\Office\\Licenses\\<n>\\`，内容是
      UTF-16LE 编码的 JSON（含 base64 的 License 令牌），格式与 macOS 相同
    * 共享计算机激活：`C:\\ProgramData\\Microsoft\\Office\\Licenses\\`
    * 当前登录身份：注册表 `HKCU\\Software\\Microsoft\\Office\\<ver>\\Common\\Identity`
      的 ConnectedAccountCID / ConnectedOneAuthAccountId
    * 新一代许可：`Common\\Licensing` 的 NextUserLicensing* 值
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
from typing import Any, Dict, List, Optional

try:
    import winreg
except ImportError:  # pragma: no cover - 仅非 Windows 的导入安全兜底
    winreg = None

from ..util import (
    LOCALAPPDATA,
    PROGRAMDATA,
    expand,
    iso,
    mtime,
    read_bytes,
    reg_subkeys,
    reg_value,
    reg_values,
)

# scan.py 通用化所需的平台常量
ACTIVE_DETAIL = "Office 当前登录身份（Common\\Identity\\ConnectedOneAuthAccountId）"

LICENSE_ROOTS = [
    os.path.join(LOCALAPPDATA, "Microsoft", "Office", "Licenses"),
    os.path.join(PROGRAMDATA, "Microsoft", "Office", "Licenses"),
]

# Office 应用与安装检测路径（ClickToRun 优先，兼容旧 MSI 布局）
_OFFICE_ROOTS = [
    r"%ProgramFiles%\Microsoft Office\root",
    r"%ProgramFiles(x86)%\Microsoft Office\root",
    r"%ProgramFiles%\Microsoft Office",
    r"%ProgramFiles(x86)%\Microsoft Office",
]

OFFICE_APPS = [
    ("com.microsoft.word", "Microsoft Word", "WINWORD.EXE"),
    ("com.microsoft.excel", "Microsoft Excel", "EXCEL.EXE"),
    ("com.microsoft.powerpoint", "Microsoft PowerPoint", "POWERPNT.EXE"),
    ("com.microsoft.onenote", "Microsoft OneNote", "ONENOTE.EXE"),
    ("com.microsoft.outlook", "Microsoft Outlook", "OUTLOOK.EXE"),
]


def app_path(executable: str) -> Optional[str]:
    for root in _OFFICE_ROOTS:
        for version in ("Office16", "Office15", "Office14"):
            candidate = expand(os.path.join(root, version, executable))
            if os.path.isfile(candidate):
                return candidate
    return None


def _office_versions() -> List[str]:
    if winreg is None:
        return []
    versions = reg_subkeys(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Office")
    return sorted(
        (v for v in versions if re.fullmatch(r"\d+\.\d+", v)),
        key=lambda s: float(s),
        reverse=True,
    )


def _office_key(subpath: str) -> Optional[str]:
    """取最高已安装版本下的指定子键（键需真实存在）。"""
    for version in _office_versions():
        path = rf"Software\Microsoft\Office\{version}\{subpath}"
        if (
            reg_subkeys(winreg.HKEY_CURRENT_USER, path)
            or reg_values(winreg.HKEY_CURRENT_USER, path)
        ):
            return path
    return None


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
    seen_paths: set[str] = set()

    for root in LICENSE_ROOTS:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*"), recursive=True):
            if not os.path.isfile(path) or path in seen_paths:
                continue
            seen_paths.add(path)
            raw = read_bytes(path)
            if not raw:
                continue
            info = _decode_license(raw)
            if not info:
                continue
            info["path"] = path
            info["last_seen"] = iso(mtime(path))
            info["product"] = os.path.basename(os.path.dirname(path))
            licenses.append(info)
    return licenses


def collect() -> Dict[str, Any]:
    identity_path = _office_key(r"Common\Identity")
    identity = reg_values(winreg.HKEY_CURRENT_USER, identity_path) if identity_path else {}

    active_raw = (
        identity.get("ConnectedOneAuthAccountId")
        or identity.get("ConnectedAccountCID")
        or ""
    )
    active_id = str(active_raw).strip().lower() or None

    # Profiles 子键：<accountId>_LiveId / <accountId>_ADAL，是身份缓存的补充证据
    profiles: List[Dict[str, Any]] = []
    if identity_path:
        for name in reg_subkeys(winreg.HKEY_CURRENT_USER, identity_path + r"\Profiles"):
            match = re.match(r"^(.+)_(LiveId|ADAL)$", name)
            if match:
                profiles.append(
                    {"account_id": match.group(1).lower(), "provider": match.group(2)}
                )

    licensed_ids: List[str] = []
    licensing_path = _office_key(r"Common\Licensing")
    if licensing_path:
        raw_ids = str(
            reg_value(
                winreg.HKEY_CURRENT_USER,
                licensing_path,
                "NextUserLicensingLicensedUserIds",
            )
            or ""
        )
        licensed_ids = [x.strip().lower() for x in raw_ids.split(",") if x.strip()]

    apps: List[Dict[str, Any]] = []
    for app_id, name, exe in OFFICE_APPS:
        found = app_path(exe)
        apps.append(
            {
                "id": app_id,
                "name": name,
                "installed": found is not None,
                "path": found
                or expand(os.path.join(_OFFICE_ROOTS[0], "Office16", exe)),
            }
        )

    return {
        "prefs_available": bool(identity or licensed_ids or profiles),
        "identity_key": identity_path,
        "activation_email": None,
        "active_account_id": active_id,
        "tenant_key": None,
        "tenant_result": None,
        "profiles": profiles,
        "licensed_ids": licensed_ids,
        "licenses": collect_licenses(),
        "apps": apps,
    }
