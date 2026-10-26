"""设备侧信息：设备身份、Entra ID 注册状态、MDM、本地合规信号（Windows 版）。

Windows 的设备注册信号比 macOS 明确得多：`dsregcmd /status` 直接给出
AzureAdJoined / WorkplaceJoined / DomainJoined / WamDefault* 等结论。
MDM 注册状态读注册表 Enrollments，Defender 载入状态读 ATP Status 的 OrgId。

说明：Intune 的合规策略结论需要 Graph 授权才能读取，这里只做本地可验证的
检查，并把「无法判定」与「不合规」严格区分开。
"""

from __future__ import annotations

import os
import re
import socket
from typing import Any, Dict, List, Optional

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from ..util import reg_value, run

ENROLLMENTS_KEY = r"SOFTWARE\Microsoft\Enrollments"
ATP_STATUS_KEY = r"SOFTWARE\Microsoft\Windows Advanced Threat Protection\Status"
WINDEFEND_KEY = r"SYSTEM\CurrentControlSet\Services\WinDefend"
NT_CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
FIREWALL_POLICY_KEY = (
    r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
)

_DSREG_FIELD_RE = re.compile(r"^\s+([A-Za-z][A-Za-z0-9 ]*?)\s*:\s*(.*?)\s*$")


def _dsregcmd() -> Dict[str, str]:
    raw = run(["cmd", "/c", "dsregcmd", "/status"], timeout=10) or ""
    fields: Dict[str, str] = {}
    for match in _DSREG_FIELD_RE.finditer(raw):
        fields[match.group(1).strip().lower()] = match.group(2).strip()
    return fields


def _yes(value: Optional[str]) -> bool:
    return bool(value) and value.strip().upper() == "YES"


def _cim_summary() -> Dict[str, Optional[str]]:
    """一次 PowerShell CIM 调用拿齐厂商 / 型号 / 序列号 / CPU / 域。"""
    script = (
        "$cs=Get-CimInstance Win32_ComputerSystem;"
        "$bios=Get-CimInstance Win32_BIOS;"
        "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1;"
        'Write-Output (@($cs.Manufacturer,$cs.Model,$bios.SerialNumber,$cpu.Name,$cs.Domain) -join "\u001f")'
    )
    raw = run(["powershell", "-NoProfile", "-Command", script], timeout=20) or ""
    parts = [p.strip() for p in raw.split("\u001f")]
    while len(parts) < 5:
        parts.append("")
    manufacturer, model, serial, cpu, domain = parts
    return {
        "manufacturer": manufacturer or None,
        "model": model or None,
        "serial": serial or None,
        "cpu": cpu or None,
        "domain": domain or None,
    }


def os_info() -> Dict[str, Optional[str]]:
    """从注册表读系统版本。ProductName 在 Win11 上仍写着 Windows 10，按 build 修正。"""
    if winreg is None:
        return {"os_name": None, "os_version": None, "os_build": None, "build_number": 0}
    build = str(reg_value(winreg.HKEY_LOCAL_MACHINE, NT_CURRENT_VERSION, "CurrentBuildNumber") or "")
    ubr = reg_value(winreg.HKEY_LOCAL_MACHINE, NT_CURRENT_VERSION, "UBR") or 0
    display = reg_value(winreg.HKEY_LOCAL_MACHINE, NT_CURRENT_VERSION, "DisplayVersion")
    product = str(reg_value(winreg.HKEY_LOCAL_MACHINE, NT_CURRENT_VERSION, "ProductName") or "")

    try:
        build_num = int(build)
    except ValueError:
        build_num = 0

    name = product
    if build_num >= 22000:
        name = re.sub(r"^Windows 10", "Windows 11", product, count=1)
    return {
        "os_name": name or None,
        "os_version": display or None,
        "os_build": f"{build}.{ubr}" if build else None,
        "build_number": build_num,
    }


def device_identity() -> Dict[str, Any]:
    cim = _cim_summary()
    osdata = os_info()
    hostname = socket.gethostname()
    model = " ".join(x for x in (cim["manufacturer"], cim["model"]) if x) or None
    return {
        "hostname": hostname,
        "local_hostname": hostname,
        "model": model,
        "chip": cim["cpu"],
        "serial": cim["serial"],
        "os_name": osdata["os_name"],
        "os_version": osdata["os_version"],
        "os_build": osdata["os_build"],
    }


def mdm_enrollments() -> List[Dict[str, Any]]:
    """注册表里的 MDM 注册记录（ProviderID = MS DM Server 的才是有效 MDM）。"""
    from ..util import reg_subkeys, reg_values

    enrollments: List[Dict[str, Any]] = []
    if winreg is None:
        return enrollments

    for guid in reg_subkeys(winreg.HKEY_LOCAL_MACHINE, ENROLLMENTS_KEY):
        values = reg_values(winreg.HKEY_LOCAL_MACHINE, ENROLLMENTS_KEY + "\\" + guid)
        provider = values.get("ProviderID")
        if not provider or "DM" not in str(provider):
            continue
        enrollments.append(
            {
                "id": guid,
                "provider": str(provider),
                "state": values.get("EnrollmentState"),
                "type": values.get("EnrollmentType"),
                "upn": values.get("UPN") or values.get("EnrollmentUPN"),
                "aad_resource": values.get("AADResourceID"),
            }
        )
    return enrollments


def mdm() -> Dict[str, Any]:
    fields = _dsregcmd()
    enrollments = mdm_enrollments()
    active = [e for e in enrollments if e.get("state") == 1]

    lines: List[str] = []
    if fields.get("mdmurl"):
        lines.append(f"MdmUrl : {fields['mdmurl']}")
    for e in active:
        lines.append(f"Enrollment {e['id']} : {e['provider']} ({e.get('upn') or '未知账户'})")

    enrolled = bool(active)
    provider = active[0]["provider"] if enrolled else None
    return {
        "enrolled": enrolled,
        "provider": provider,
        "enrollments": enrollments,
        "lines": lines,
    }


def ad_join(fields: Dict[str, str]) -> Dict[str, Any]:
    joined = _yes(fields.get("domainjoined"))
    domain = None
    if joined:
        domain = (
            reg_value(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters", "Domain")
            if winreg
            else None
        ) or _cim_summary().get("domain")
    return {"joined": joined, "domain": domain}


def entra_registration(fields: Dict[str, str]) -> Dict[str, Any]:
    """Windows 上 Entra ID 注册由 dsregcmd 直接给出结论。"""
    signals: List[Dict[str, Any]] = []

    aad_joined = _yes(fields.get("azureadjoined"))
    workplace = _yes(fields.get("workplacejoined"))
    wam_default = fields.get("wamdefaultguid", "")

    if aad_joined:
        signals.append({"signal": "Azure AD 加入", "present": True, "detail": "设备已加入 Entra ID 租户目录"})
    if workplace:
        signals.append({"signal": "工作区账户", "present": True, "detail": "Windows 已添加工作/学校账户"})
    if "AzureAd" in wam_default:
        signals.append({"signal": "WAM 默认提供方", "present": True, "detail": wam_default})
    if not signals:
        signals.append(
            {"signal": "dsregcmd", "present": False, "detail": "AzureAdJoined / WorkplaceJoined 均为 NO"}
        )

    registered = aad_joined or workplace
    device_id = fields.get("deviceid") or None
    tenant_name = fields.get("tenantname") or None

    return {
        "registered": registered,
        "aad_joined": aad_joined,
        "workplace_joined": workplace,
        "device_id": device_id,
        "tenant_name": tenant_name,
        "tenant_id": fields.get("tenantid") or None,
        "azure_ad_prt": _yes(fields.get("azureadprt")),
        "signals": signals,
        "note": (
            "设备注册状态来自 dsregcmd /status：AzureAdJoined 表示设备对象在租户目录中，"
            "WorkplaceJoined 表示仅添加了工作/学校账户（应用层 SSO）。"
        ),
    }


def _check(check_id: str, label: str, status: str, value: str, detail: str) -> Dict[str, Any]:
    return {"id": check_id, "label": label, "status": status, "value": value, "detail": detail}


def _bitlocker_check() -> Dict[str, Any]:
    raw = run(["manage-bde", "-status", "C:"], timeout=15) or ""
    if raw:
        if "Protection On" in raw or "保护已开启" in raw:
            return _check("bitlocker", "磁盘加密", "ok", "已启用", "BitLocker 保护已开启（C:）")
        if "Protection Off" in raw or "保护已关闭" in raw or "Fully Decrypted" in raw or "完全解密" in raw:
            return _check("bitlocker", "磁盘加密", "fail", "未启用", "BitLocker 未开启（C:），通常不满足合规要求")
        if "拒绝" in raw or "denied" in raw.lower():
            return _check("bitlocker", "磁盘加密", "unknown", "无法判定", "查询 BitLocker 状态需要管理员权限")
        if "BitLocker" in raw or "加密" in raw:
            return _check("bitlocker", "磁盘加密", "unknown", "无法判定", raw.strip().splitlines()[-1])
    return _check("bitlocker", "磁盘加密", "unknown", "无法判定", "manage-bde 无输出")


def _firewall_check() -> Dict[str, Any]:
    if winreg is None:
        return _check("firewall", "防火墙", "unknown", "无法判定", "仅支持 Windows")
    profiles = {"DomainProfile": "域网络", "StandardProfile": "专用网络", "PublicProfile": "公用网络"}
    off: List[str] = []
    found = 0
    for sub, label in profiles.items():
        value = reg_value(winreg.HKEY_LOCAL_MACHINE, FIREWALL_POLICY_KEY + "\\" + sub, "EnableFirewall")
        if value is None:
            continue
        found += 1
        if not value:
            off.append(label)
    if found and not off:
        return _check("firewall", "防火墙", "ok", "已启用", "所有配置文件的 Windows 防火墙均已开启")
    if off:
        return _check("firewall", "防火墙", "warn", "部分关闭", f"已关闭的网络配置文件：{'、'.join(off)}")
    return _check("firewall", "防火墙", "unknown", "无法判定", "注册表中未找到防火墙状态")


def _os_check(osdata: Dict[str, Optional[str]]) -> Dict[str, Any]:
    build = osdata.get("build_number") or 0
    label = osdata.get("os_name") or "Windows"
    version = osdata.get("os_version") or ""
    display = f"{label} {version}".strip()
    if build >= 22000:
        return _check("os", "操作系统版本", "ok", display, "Windows 11，在支持窗口内")
    if 10240 <= build < 22000:
        return _check("os", "操作系统版本", "fail", display, "Windows 10 已于 2025 年 10 月停止支持，多数合规策略会拒绝")
    return _check("os", "操作系统版本", "unknown", "无法判定", "读取失败")


def _defender_check() -> Dict[str, Any]:
    if winreg is None:
        return _check("defender", "端点防护", "unknown", "未安装", "仅支持 Windows")
    org = reg_value(winreg.HKEY_LOCAL_MACHINE, ATP_STATUS_KEY, "OrgId")
    if org:
        return _check("defender", "端点防护", "ok", "已载入租户", f"org_id={org}")
    start = reg_value(winreg.HKEY_LOCAL_MACHINE, WINDEFEND_KEY, "Start")
    if start == 4:
        return _check("defender", "端点防护", "fail", "已禁用", "WinDefend 服务已被禁用")
    if start is not None:
        return _check("defender", "端点防护", "warn", "未载入", "Defender 已内置，但未载入 Defender for Endpoint 租户")
    return _check("defender", "端点防护", "unknown", "未安装", "未检测到 Microsoft Defender 服务")


def _smartscreen_check() -> Dict[str, Any]:
    value = (
        reg_value(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer",
            "SmartScreenEnabled",
        )
        if winreg
        else None
    )
    if value in ("Warn", "Block"):
        return _check("smartscreen", "SmartScreen", "ok", "已启用", f"SmartScreenEnabled = {value}")
    if value == "Off":
        return _check("smartscreen", "SmartScreen", "warn", "已关闭", "SmartScreenEnabled = Off")
    return _check("smartscreen", "SmartScreen", "unknown", "无法判定", "注册表中未找到 SmartScreen 设置")


def compliance(entra: Dict[str, Any], mdm_info: Dict[str, Any], osdata: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    # 1. Entra ID 设备注册
    if entra["registered"]:
        how = "设备已加入 Entra ID" if entra.get("aad_joined") else "已添加工作/学校账户"
        checks.append(_check("entra", "Entra ID 设备注册", "ok", "已注册", how))
    else:
        checks.append(
            _check("entra", "Entra ID 设备注册", "fail", "未注册", "dsregcmd 显示 AzureAdJoined / WorkplaceJoined 均为 NO")
        )

    # 2. MDM
    if mdm_info["enrolled"]:
        checks.append(_check("mdm", "MDM 注册", "ok", "已注册", "设备受移动设备管理，可下发合规策略"))
    else:
        checks.append(_check("mdm", "MDM 注册", "fail", "未注册", "未注册 MDM，Intune 无法下发策略"))

    # 3. BitLocker
    checks.append(_bitlocker_check())

    # 4. 防火墙
    checks.append(_firewall_check())

    # 5. 系统版本
    checks.append(_os_check(osdata))

    # 6. Defender
    checks.append(_defender_check())

    # 7. SmartScreen
    checks.append(_smartscreen_check())

    return checks


def collect() -> Dict[str, Any]:
    fields = _dsregcmd()
    cim = _cim_summary()
    osdata = os_info()

    identity = {
        "hostname": socket.gethostname(),
        "local_hostname": socket.gethostname(),
        "model": " ".join(x for x in (cim["manufacturer"], cim["model"]) if x) or None,
        "chip": cim["cpu"],
        "serial": cim["serial"],
        "os_name": osdata["os_name"],
        "os_version": osdata["os_version"],
        "os_build": osdata["os_build"],
    }

    mdm_info = mdm()
    entra = entra_registration(fields)

    checks = compliance(entra, mdm_info, osdata)
    total = len(checks)
    ok_count = sum(1 for c in checks if c["status"] == "ok")

    return {
        "identity": identity,
        "enrollment": {
            "mdm": mdm_info,
            "entra": entra,
            "ad": ad_join(fields),
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
