"""设备侧信息：设备身份、Entra ID 注册状态、本地合规信号。

说明：Intune 的合规策略结论需要 Graph 授权才能读取，这里只做本地可验证的检查，
并把「无法判定」与「不合规」严格区分开。
"""

from __future__ import annotations

import glob
import os
import re
from typing import Any, Dict, List

from ..util import HOME, exists, iso, mtime, read_defaults, read_plist, run

COMPANY_PORTAL_APP = "/Applications/Company Portal.app"
COMPANY_PORTAL_CONTAINER = os.path.join(
    HOME, "Library/Containers/com.microsoft.CompanyPortalMac"
)
ENTRA_BROKER = os.path.join(
    HOME, "Library/Group Containers/UBF8T346G9.com.microsoft.entrabroker"
)
INTUNE_SUPPORT = "/Library/Application Support/Microsoft/Intune"
DEFENDER_APP = "/Applications/Microsoft Defender.app"


def _serial() -> str | None:
    raw = run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], timeout=6) or ""
    match = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', raw)
    return match.group(1) if match else None


def device_identity() -> Dict[str, Any]:
    return {
        "hostname": run(["scutil", "--get", "ComputerName"], timeout=4),
        "local_hostname": run(["scutil", "--get", "LocalHostName"], timeout=4),
        "model": run(["sysctl", "-n", "hw.model"], timeout=4),
        "chip": run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=4),
        "serial": _serial(),
        "os_name": "macOS",
        "os_version": run(["sw_vers", "-productVersion"], timeout=4),
        "os_build": run(["sw_vers", "-buildVersion"], timeout=4),
    }


def mdm() -> Dict[str, Any]:
    raw = run(["profiles", "status", "-type", "enrollment"], timeout=6) or ""
    enrolled = "MDM enrollment: Yes" in raw
    dep = "Enrolled via DEP: Yes" in raw
    return {
        "enrolled": enrolled,
        "dep": dep,
        "lines": [line for line in raw.splitlines() if line.strip()],
    }


def ad_join() -> Dict[str, Any]:
    raw = run(["dsconfigad", "-show"], timeout=6)
    if not raw:
        return {"joined": False, "domain": None}
    domain = None
    match = re.search(r"Active Directory Domain\s*=\s*(.+)", raw)
    if match:
        domain = match.group(1).strip()
    joined = bool(domain and domain.lower() not in ("", "not bound"))
    return {"joined": joined, "domain": domain}


def entra_registration() -> Dict[str, Any]:
    """macOS 上 Entra ID 设备注册由 Company Portal（工作区加入）完成。"""
    signals: List[Dict[str, Any]] = []

    if exists(COMPANY_PORTAL_APP):
        signals.append({"signal": "Company Portal 应用", "present": True, "path": COMPANY_PORTAL_APP})
    if os.path.isdir(COMPANY_PORTAL_CONTAINER):
        signals.append(
            {"signal": "Company Portal 容器", "present": True, "path": COMPANY_PORTAL_CONTAINER}
        )
    if os.path.isdir(INTUNE_SUPPORT):
        signals.append({"signal": "Intune 支持目录", "present": True, "path": INTUNE_SUPPORT})

    broker_files = 0
    if os.path.isdir(ENTRA_BROKER):
        for _root, _dirs, files in os.walk(ENTRA_BROKER):
            broker_files += len(files)
    if broker_files:
        signals.append(
            {"signal": "Entra broker 缓存", "present": True, "path": ENTRA_BROKER, "files": broker_files}
        )

    cert = run(["security", "find-certificate", "-c", "Microsoft Intune"], timeout=6)
    has_cert = bool(cert and "keychain" in cert.lower())

    registered = bool(
        (exists(COMPANY_PORTAL_APP) and os.path.isdir(COMPANY_PORTAL_CONTAINER)) or has_cert
    )

    return {
        "registered": registered,
        "company_portal": exists(COMPANY_PORTAL_APP),
        "broker_files": broker_files,
        "device_certificate": has_cert,
        "signals": signals,
        "note": (
            "macOS 没有 Windows 那种「加入 Entra ID」；设备注册由 Company Portal 的"
            "工作区加入流程完成，凭据存放在系统钥匙串。"
        ),
    }


def _check(check_id: str, label: str, status: str, value: str, detail: str) -> Dict[str, Any]:
    return {"id": check_id, "label": label, "status": status, "value": value, "detail": detail}


def compliance(entra: Dict[str, Any], mdm_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    # 1. Entra ID 设备注册
    if entra["registered"]:
        checks.append(
            _check("entra", "Entra ID 设备注册", "ok", "已注册", "检测到 Company Portal 或设备证书")
        )
    else:
        checks.append(
            _check(
                "entra",
                "Entra ID 设备注册",
                "fail",
                "未注册",
                "未找到 Company Portal、设备证书或 broker 缓存，设备不在租户目录中",
            )
        )

    # 2. MDM
    if mdm_info["enrolled"]:
        checks.append(_check("mdm", "MDM 注册", "ok", "已注册", "设备受移动设备管理"))
    else:
        checks.append(
            _check("mdm", "MDM 注册", "fail", "未注册", "未注册 MDM，Intune 无法下发策略")
        )

    # 3. FileVault
    fv = run(["fdesetup", "status"], timeout=6) or ""
    if "FileVault is On" in fv:
        checks.append(_check("filevault", "磁盘加密", "ok", "已启用", "FileVault 已开启"))
    elif "FileVault is Off" in fv:
        checks.append(
            _check("filevault", "磁盘加密", "fail", "未启用", "FileVault 关闭，通常不满足合规要求")
        )
    else:
        checks.append(_check("filevault", "磁盘加密", "unknown", "无法判定", fv.strip() or "命令无输出"))

    # 4. SIP
    sip = run(["csrutil", "status"], timeout=6) or ""
    if "enabled" in sip and "disabled" not in sip:
        checks.append(_check("sip", "系统完整性保护", "ok", "已启用", sip.strip()))
    elif "disabled" in sip:
        checks.append(_check("sip", "系统完整性保护", "warn", "已关闭", sip.strip()))
    else:
        checks.append(_check("sip", "系统完整性保护", "unknown", "无法判定", sip.strip() or "命令无输出"))

    # 5. 防火墙
    fw = run(
        ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"], timeout=6
    ) or ""
    if "enabled" in fw.lower():
        checks.append(_check("firewall", "防火墙", "ok", "已启用", fw.strip()))
    elif "disabled" in fw.lower():
        checks.append(_check("firewall", "防火墙", "warn", "已关闭", fw.strip()))
    else:
        checks.append(_check("firewall", "防火墙", "unknown", "无法判定", fw.strip() or "命令无输出"))

    # 6. 系统版本
    version = run(["sw_vers", "-productVersion"], timeout=4) or ""
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        major = 0
    if major >= 14:
        checks.append(_check("os", "操作系统版本", "ok", f"macOS {version}", "在支持窗口内"))
    elif major >= 13:
        checks.append(
            _check("os", "操作系统版本", "warn", f"macOS {version}", "接近支持末期，建议升级")
        )
    elif major:
        checks.append(
            _check("os", "操作系统版本", "fail", f"macOS {version}", "版本过旧，多数合规策略会拒绝")
        )
    else:
        checks.append(_check("os", "操作系统版本", "unknown", "无法判定", "读取失败"))

    # 7. Defender
    if os.path.exists("/usr/local/bin/mdatp"):
        org = (run(["/usr/local/bin/mdatp", "health", "--field", "org_id"], timeout=6) or "").strip('"')
        if org:
            checks.append(_check("defender", "端点防护", "ok", "已载入租户", f"org_id={org}"))
        else:
            checks.append(
                _check("defender", "端点防护", "warn", "未载入", "Defender 已安装但未加入租户")
            )
    else:
        checks.append(
            _check("defender", "端点防护", "unknown", "未安装", "未检测到 Microsoft Defender")
        )

    return checks


def collect() -> Dict[str, Any]:
    identity = device_identity()
    mdm_info = mdm()
    entra = entra_registration()

    checks = compliance(entra, mdm_info)
    total = len(checks)
    ok_count = sum(1 for c in checks if c["status"] == "ok")

    return {
        "identity": identity,
        "enrollment": {
            "mdm": mdm_info,
            "entra": entra,
            "ad": ad_join(),
        },
        "compliance": {
            "checks": checks,
            "passed": ok_count,
            "total": total,
            "score": round(ok_count / total * 100) if total else 0,
        },
        "note": (
            "以上为本机可验证的信号。Intune 的实际合规结论由云端策略计算，"
            "需要 Graph 授权才能读取，本地无法替代。"
        ),
    }
