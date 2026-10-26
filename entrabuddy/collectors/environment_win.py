"""环境侧信息：已安装应用、MDM 注册、Defender、系统账户（Windows 版）。"""

from __future__ import annotations

import glob
import os
from typing import Any, Dict, List

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from ..util import (
    APPDATA_ROAMING,
    LOCALAPPDATA,
    exists,
    expand,
    iso,
    mtime,
    reg_value,
)
from .device_win import mdm_enrollments
from .office_win import app_path

# 已知的微软应用 -> 检测路径
KNOWN_APPS: List[Dict[str, str]] = [
    {"id": "com.microsoft.word", "name": "Microsoft Word", "path": "", "probe": "WINWORD.EXE", "kind": "office"},
    {"id": "com.microsoft.excel", "name": "Microsoft Excel", "path": "", "probe": "EXCEL.EXE", "kind": "office"},
    {"id": "com.microsoft.powerpoint", "name": "Microsoft PowerPoint", "path": "", "probe": "POWERPNT.EXE", "kind": "office"},
    {"id": "com.microsoft.onenote", "name": "Microsoft OneNote", "path": "", "probe": "ONENOTE.EXE", "kind": "office"},
    {"id": "com.microsoft.outlook", "name": "Microsoft Outlook", "path": "", "probe": "OUTLOOK.EXE", "kind": "office"},
    {
        "id": "com.microsoft.edge",
        "name": "Microsoft Edge",
        "path": r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        "probe": "",
        "kind": "browser",
    },
    {
        "id": "com.microsoft.onedrive",
        "name": "OneDrive",
        "path": r"%ProgramFiles%\Microsoft OneDrive\OneDrive.exe",
        "probe": "",
        "kind": "sync",
    },
    {
        "id": "com.microsoft.teams",
        "name": "Microsoft Teams",
        "path": r"%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe",
        "probe": "",
        "kind": "chat",
    },
    {
        "id": "com.microsoft.companyportal",
        "name": "Company Portal",
        "path": r"%LOCALAPPDATA%\Microsoft\WindowsApps\Microsoft.CompanyPortal_8wekyb3d8bbwe",
        "probe": "",
        "kind": "mdm",
    },
    {
        "id": "com.microsoft.rdc.win32",
        "name": "Windows App",
        "path": r"%LOCALAPPDATA%\Microsoft\WindowsApps\msrdc.exe",
        "probe": "",
        "kind": "remote",
    },
    {
        "id": "com.microsoft.wdav",
        "name": "Microsoft Defender",
        "path": r"%ProgramFiles%\Windows Defender\MsMpEng.exe",
        "probe": "",
        "kind": "security",
    },
    {
        "id": "com.microsoft.copilot",
        "name": "Microsoft 365 Copilot",
        "path": r"%LOCALAPPDATA%\Microsoft\WindowsApps\M365Copilot.exe",
        "probe": "",
        "kind": "assistant",
    },
    {
        "id": "com.microsoft.officeclicktorun",
        "name": "Microsoft 自动更新 (ClickToRun)",
        "path": r"%CommonProgramFiles%\Microsoft Shared\ClickToRun\OfficeC2RClient.exe",
        "probe": "",
        "kind": "updater",
    },
]


def _probe_installed(spec: Dict[str, str]) -> bool:
    if spec.get("probe"):
        return app_path(spec["probe"]) is not None
    path = spec.get("path") or ""
    if not path:
        return False
    if exists(path):
        return True
    # WindowsApps 下的包目录可能不可枚举，退回开始菜单快捷方式
    if "WindowsApps" in path:
        name = path.rsplit("\\", 1)[-1]
        shortcuts = glob.glob(
            expand(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
            recursive=True,
        ) + glob.glob(
            expand(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
            recursive=True,
        )
        base = name.split("_")[0].lower()
        return any(base.replace("microsoft.", "") in os.path.basename(s).lower() for s in shortcuts)
    return False


def installed_apps() -> List[Dict[str, Any]]:
    apps = []
    for spec in KNOWN_APPS:
        apps.append({**spec, "installed": _probe_installed(spec)})
    return apps


def mdm_status() -> Dict[str, Any]:
    enrollments = mdm_enrollments()
    active = [e for e in enrollments if e.get("state") == 1]
    return {
        "enrolled": bool(active),
        "provider": active[0]["provider"] if active else None,
        "raw": [f"{e['provider']} ({e.get('upn') or '未知账户'})" for e in active],
    }


def defender_status() -> Dict[str, Any]:
    if winreg is None:
        return {"installed": False}
    service = reg_value(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\WinDefend", "Start")
    org_id = reg_value(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows Advanced Threat Protection\Status",
        "OrgId",
    )
    if service is None and org_id is None:
        return {"installed": False}
    return {
        "installed": True,
        "org_id": str(org_id) if org_id else None,
        "onboarded": bool(org_id),
    }


def teams_traces() -> Dict[str, Any]:
    candidates = [
        # 经典 Teams
        os.path.join(APPDATA_ROAMING, "Microsoft", "Teams", "logs"),
        # 新版 Teams（MSIX 打包）
        os.path.join(
            LOCALAPPDATA,
            "Packages",
            "MSTeams_8wekyb3d8bbwe",
            "LocalCache",
            "Microsoft",
            "MSTeams",
            "Logs",
        ),
    ]
    for logs_dir in candidates:
        logs = glob.glob(os.path.join(logs_dir, "*.log"))
        if not logs:
            continue
        latest = max((mtime(p) or 0 for p in logs), default=0)
        return {
            "present": True,
            "path": logs_dir,
            "log_count": len(logs),
            "last_activity": iso(latest) if latest else None,
        }
    return {"present": False}


def system_accounts() -> Dict[str, Any]:
    """Windows 的 WAM 身份代理：工作/学校账户走 AAD Broker，个人账户走 MSA。"""
    aad_broker = os.path.join(LOCALAPPDATA, "Packages", "Microsoft.AAD.BrokerPlugin_cw5n1h2txyewy")
    msa_broker = os.path.join(LOCALAPPDATA, "Packages", "Microsoft.Windows.CloudExperienceHost_cw5n1h2txyewy")
    return {
        "aad_broker_present": os.path.isdir(aad_broker),
        "msa_broker_present": os.path.isdir(msa_broker),
        "identitycache_present": os.path.isdir(os.path.join(LOCALAPPDATA, "Microsoft", "IdentityCache")),
    }


def collect() -> Dict[str, Any]:
    return {
        "apps": installed_apps(),
        "mdm": mdm_status(),
        "defender": defender_status(),
        "teams": teams_traces(),
        "system": system_accounts(),
    }
