"""演示数据：用虚构账户渲染界面，便于截图与文档展示（双平台）。

用法：python app.py --demo
演示模式下所有写操作都会被拒绝。
设备信息 / 证据路径 / 应用 ID 按当前平台动态生成，其余结构共享。
"""

from __future__ import annotations

import copy
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from . import _platform
from .collectors import edge, environment, office, oneauth, onedrive
from .util import human_path, iso
from .util import APP_SUPPORT

ACTIVE_DETAIL = office.ACTIVE_DETAIL
ONEAUTH_DIR = human_path(oneauth.BLOB_DIR)
SNAPSHOT_DIR = human_path(os.path.join(APP_SUPPORT, "snapshots"))

# 应用 ID 随平台取自环境采集器（浏览器 / 同步 / 聊天）
_IDS = {spec["kind"]: spec["id"] for spec in environment.KNOWN_APPS}
EDGE_ID = edge.APP_ID
ONEDRIVE_ID = onedrive.APP_ID
TEAMS_ID = _IDS.get("chat", "com.microsoft.teams")
DEFENDER_ID = _IDS.get("security", "com.microsoft.wdav")


def _ts(days_ago: float) -> str:
    return iso(time.time() - days_ago * 86400)


def _account(
    upn: str,
    kind: str,
    cloud: str,
    tenant_name: str | None,
    tenant_id: str | None,
    object_id: str | None,
    cid: str | None,
    last_seen: str,
    apps: List[Dict[str, Any]],
    stale: bool,
    freshness: str,
    license_info: Dict[str, Any] | None = None,
    notes: List[str] | None = None,
    evidence: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "key": upn.lower(),
        "upn": upn,
        "display_name": None,
        "kind": kind,
        "cloud": cloud,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "object_id": object_id,
        "cid": cid,
        "location": "CN" if cloud == "china" else ("US" if kind == "msa" else None),
        "last_seen": last_seen,
        "last_seen_ts": time.time(),
        "link_confidence": "high" if kind == "org" else None,
        "is_active_today": not stale,
        "is_stale": stale,
        "apps": apps,
        "notes": notes or [],
        "evidence": evidence or [],
        "credential": {
            "cache_age_days": 0.1 if not stale else 120.0,
            "freshness": freshness,
            "license": license_info,
        },
    }


def _binding(app_id: str, name: str, roles: List[str], details: List[str], installed: bool = True):
    return {
        "app_id": app_id,
        "app_name": name,
        "roles": roles,
        "details": details,
        "installed": installed,
    }


def _device_block() -> Dict[str, Any]:
    """设备身份 / 注册状态 / 合规信号，mac 与 Windows 各一套。"""
    if _platform.IS_MACOS:
        checks = [
            {"id": "entra", "label": "Entra ID 设备注册", "status": "ok", "value": "已注册",
             "detail": "检测到 Company Portal 与设备证书"},
            {"id": "mdm", "label": "MDM 注册", "status": "ok", "value": "已注册",
             "detail": "设备受移动设备管理，可下发合规策略"},
            {"id": "filevault", "label": "磁盘加密", "status": "ok", "value": "已启用", "detail": "FileVault 已开启"},
            {"id": "sip", "label": "系统完整性保护", "status": "ok", "value": "已启用",
             "detail": "System Integrity Protection status: enabled."},
            {"id": "firewall", "label": "防火墙", "status": "warn", "value": "已关闭",
             "detail": "Firewall is disabled. (State = 0)"},
            {"id": "os", "label": "操作系统版本", "status": "ok", "value": "macOS 15.1", "detail": "在支持窗口内"},
            {"id": "defender", "label": "端点防护", "status": "ok", "value": "已载入租户",
             "detail": "org_id=11111111-2222-3333-4444-555555555555"},
        ]
        identity = {
            "hostname": "MBP-DEMO",
            "local_hostname": "MBP-DEMO",
            "model": "MacBookPro18,3",
            "chip": "Apple M1 Pro",
            "serial": "C02XXXXXXXXX",
            "os_name": "macOS",
            "os_version": "15.1",
            "os_build": "24B83",
        }
        enrollment = {
            "mdm": {"enrolled": True, "dep": True, "lines": ["MDM enrollment: Yes"]},
            "entra": {
                "registered": True,
                "company_portal": True,
                "broker_files": 6,
                "device_certificate": True,
                "signals": [],
                "note": "macOS 没有 Windows 那种「加入 Entra ID」；设备注册由 Company Portal 的"
                "工作区加入流程完成，凭据存放在系统钥匙串。",
            },
            "ad": {"joined": False, "domain": None},
        }
    else:
        checks = [
            {"id": "entra", "label": "Entra ID 设备注册", "status": "ok", "value": "已注册",
             "detail": "设备已加入 Entra ID（AzureAdJoined : YES）"},
            {"id": "mdm", "label": "MDM 注册", "status": "ok", "value": "已注册",
             "detail": "设备受移动设备管理，可下发合规策略"},
            {"id": "bitlocker", "label": "磁盘加密", "status": "ok", "value": "已启用",
             "detail": "BitLocker 保护已开启（C:）"},
            {"id": "firewall", "label": "防火墙", "status": "ok", "value": "已启用",
             "detail": "所有配置文件的 Windows 防火墙均已开启"},
            {"id": "os", "label": "操作系统版本", "status": "ok", "value": "Windows 11 Pro 24H2",
             "detail": "Windows 11，在支持窗口内"},
            {"id": "defender", "label": "端点防护", "status": "ok", "value": "已载入租户",
             "detail": "org_id=11111111-2222-3333-4444-555555555555"},
            {"id": "smartscreen", "label": "SmartScreen", "status": "warn", "value": "已关闭",
             "detail": "SmartScreenEnabled = Off"},
        ]
        identity = {
            "hostname": "DEMO-STATION",
            "local_hostname": "DEMO-STATION",
            "model": "Fabrikam Surface Laptop 6",
            "chip": "Intel Core Ultra 7 165H",
            "serial": "DEMOXXXXXXX",
            "os_name": "Windows 11 Pro",
            "os_version": "24H2",
            "os_build": "26100.2894",
        }
        enrollment = {
            "mdm": {
                "enrolled": True,
                "provider": "MS DM Server",
                "enrollments": [],
                "lines": ["Enrollment xxxxxxxx : MS DM Server (alice.chen@contoso.com)"],
            },
            "entra": {
                "registered": True,
                "aad_joined": True,
                "workplace_joined": True,
                "device_id": "eeee5555-ffff-6666-aaaa-bbbbbbbbbbbb",
                "tenant_name": "Contoso Ltd",
                "tenant_id": "11111111-2222-3333-4444-555555555555",
                "azure_ad_prt": True,
                "signals": [],
                "note": "设备注册状态来自 dsregcmd /status：AzureAdJoined 表示设备对象在租户目录中，"
                "WorkplaceJoined 表示仅添加了工作/学校账户（应用层 SSO）。",
            },
            "ad": {"joined": False, "domain": None},
        }

    passed = sum(1 for c in checks if c["status"] == "ok")
    return {
        "identity": identity,
        "enrollment": enrollment,
        "compliance": {
            "checks": checks,
            "passed": passed,
            "total": len(checks),
            "score": round(passed / len(checks) * 100),
        },
        "note": "以上为本机可验证的信号。Intune 的实际合规结论由云端策略计算，"
        "需要 Graph 授权才能读取，本地无法替代。",
    }


def payload() -> Dict[str, Any]:
    today = datetime.now().date()
    license_end = (today + timedelta(days=48)).isoformat()
    edge_profile_label = (
        "配置文件「默认」(Default) 已登录"
        if _platform.IS_MACOS
        else "配置文件「个人」(Profile 3) 已登录"
    )

    accounts = [
        _account(
            upn="alice.chen@contoso.com",
            kind="org",
            cloud="global",
            tenant_name="Contoso Ltd",
            tenant_id="11111111-2222-3333-4444-555555555555",
            object_id="aaaa1111-bbbb-2222-cccc-333344445555",
            cid=None,
            last_seen=_ts(0.05),
            stale=False,
            freshness="fresh",
            apps=[
                _binding(
                    "com.microsoft.office",
                    "Microsoft Office",
                    ["active", "cached"],
                    [
                        ACTIVE_DETAIL,
                        "Office 套件身份存储中留有该账户",
                    ],
                ),
                _binding(
                    TEAMS_ID,
                    "Microsoft Teams",
                    ["profile"],
                    ["企业账户已登录"],
                    installed=False,
                ),
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": os.path.join(ONEAUTH_DIR, "alice.chen@contoso.com_identity_provider"),
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(0.05),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": os.path.join(ONEAUTH_DIR, "contoso.com_hrd"),
                    "detail": "域 contoso.com → 租户 11111111-2222-3333-4444-555555555555",
                    "timestamp": _ts(0.05),
                },
                {
                    "source": "OneAuth 组织信息",
                    "path": None,
                    "detail": "objectId=aaaa1111-bbbb-2222-cccc-333344445555，租户名=Contoso Ltd",
                    "timestamp": _ts(0.05),
                },
            ],
        ),
        _account(
            upn="alice.chen@outlook.com",
            kind="msa",
            cloud="global",
            tenant_name=None,
            tenant_id=None,
            object_id=None,
            cid="9999999999999999",
            last_seen=_ts(0.04),
            stale=False,
            freshness="fresh",
            license_info={
                "not_after": license_end,
                "not_before": (today - timedelta(days=28)).isoformat(),
                "days_left": 48,
                "is_trial": False,
            },
            apps=[
                _binding(
                    "com.microsoft.office",
                    "Microsoft Office",
                    ["licensed", "cached"],
                    [
                        f"授权 Office 许可证，有效期至 {license_end}",
                        "Office 套件身份存储中留有该账户",
                    ],
                ),
                _binding(
                    ONEDRIVE_ID,
                    "OneDrive",
                    ["sync"],
                    ["个人版同步账户（Personal）"],
                ),
                _binding(
                    EDGE_ID,
                    "Microsoft Edge",
                    ["profile"],
                    [edge_profile_label],
                ),
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": os.path.join(ONEAUTH_DIR, "alice.chen@outlook.com_identity_provider"),
                    "detail": "identity_provider = MSAccount",
                    "timestamp": _ts(12),
                },
                {
                    "source": "OneAuth 个人资料",
                    "path": os.path.join(ONEAUTH_DIR, "9999999999999999_substrate_profile"),
                    "detail": "cid=9999999999999999，注册地=US",
                    "timestamp": _ts(0.04),
                },
                {
                    "source": "OneDrive 同步客户端",
                    "path": onedrive.evidence_path("Personal"),
                    "detail": f"AccountInfo_Personal → alice.chen@outlook.com",
                    "timestamp": None,
                },
                {
                    "source": "Edge 配置文件",
                    "path": None,
                    "detail": "Default / 默认" if _platform.IS_MACOS else "Profile 3 / 个人",
                    "timestamp": None,
                },
            ],
        ),
        _account(
            upn="bob.wang@fabrikam.onmicrosoft.com",
            kind="org",
            cloud="global",
            tenant_name="Fabrikam Inc",
            tenant_id="66666666-7777-8888-9999-aaaaaaaaaaaa",
            object_id="bbbb2222-cccc-3333-dddd-444455556666",
            cid=None,
            last_seen=_ts(31),
            stale=True,
            freshness="aging",
            apps=[
                _binding(
                    "com.microsoft.office",
                    "Microsoft Office",
                    ["cached"],
                    ["Office 套件身份存储中留有该账户"],
                )
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": os.path.join(
                        ONEAUTH_DIR, "bob.wang@fabrikam.onmicrosoft.com_identity_provider"
                    ),
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(31),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": os.path.join(ONEAUTH_DIR, "fabrikam.onmicrosoft.com_hrd"),
                    "detail": "域 fabrikam.onmicrosoft.com → 租户 66666666-7777-8888-9999-aaaaaaaaaaaa",
                    "timestamp": _ts(31),
                },
            ],
        ),
        _account(
            upn="carol@litware.cn",
            kind="org",
            cloud="china",
            tenant_name="Litware 中国",
            tenant_id="cccc3333-dddd-4444-eeee-555566667777",
            object_id="dddd4444-eeee-5555-ffff-666677778888",
            cid=None,
            last_seen=_ts(180),
            stale=True,
            freshness="stale",
            apps=[
                _binding(
                    "com.microsoft.office",
                    "Microsoft Office",
                    ["cached"],
                    ["Office 套件身份存储中留有该账户"],
                )
            ],
            notes=["该账户位于世纪互联云，与全球云的身份互不通用"],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": os.path.join(ONEAUTH_DIR, "carol@litware.cn_identity_provider"),
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(180),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": os.path.join(ONEAUTH_DIR, "litware.cn_hrd"),
                    "detail": "域 litware.cn → 租户 cccc3333-dddd-4444-eeee-555566667777",
                    "timestamp": _ts(180),
                },
            ],
        ),
        _account(
            upn="dave@outlook.com",
            kind="msa",
            cloud="global",
            tenant_name=None,
            tenant_id=None,
            object_id=None,
            cid="8888888888888888",
            last_seen=_ts(420),
            stale=True,
            freshness="stale",
            apps=[
                _binding(
                    "com.microsoft.office",
                    "Microsoft Office",
                    ["cached"],
                    ["Office 套件身份存储中留有该账户"],
                )
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": os.path.join(ONEAUTH_DIR, "dave@outlook.com_identity_provider"),
                    "detail": "identity_provider = MSAccount",
                    "timestamp": _ts(420),
                }
            ],
        ),
    ]

    apps = [
        {
            "id": "com.microsoft.office",
            "name": "Microsoft Office",
            "kind": "office",
            "installed": True,
            "accounts": [
                {
                    "upn": "alice.chen@contoso.com",
                    "key": "alice.chen@contoso.com",
                    "roles": ["active", "cached"],
                    "details": [
                        ACTIVE_DETAIL,
                        "Office 套件身份存储中留有该账户",
                    ],
                },
                {
                    "upn": "alice.chen@outlook.com",
                    "key": "alice.chen@outlook.com",
                    "roles": ["licensed", "cached"],
                    "details": [
                        f"授权 Office 许可证，有效期至 {license_end}",
                        "Office 套件身份存储中留有该账户",
                    ],
                },
                {
                    "upn": "bob.wang@fabrikam.onmicrosoft.com",
                    "key": "bob.wang@fabrikam.onmicrosoft.com",
                    "roles": ["cached"],
                    "details": ["Office 套件身份存储中留有该账户"],
                },
                {
                    "upn": "carol@litware.cn",
                    "key": "carol@litware.cn",
                    "roles": ["cached"],
                    "details": ["Office 套件身份存储中留有该账户"],
                },
                {
                    "upn": "dave@outlook.com",
                    "key": "dave@outlook.com",
                    "roles": ["cached"],
                    "details": ["Office 套件身份存储中留有该账户"],
                },
            ],
        },
        {
            "id": EDGE_ID,
            "name": "Microsoft Edge",
            "kind": "browser",
            "installed": True,
            "accounts": [
                {
                    "upn": "alice.chen@outlook.com",
                    "key": "alice.chen@outlook.com",
                    "roles": ["profile"],
                    "details": [edge_profile_label],
                }
            ],
        },
        {
            "id": ONEDRIVE_ID,
            "name": "OneDrive",
            "kind": "sync",
            "installed": True,
            "accounts": [
                {
                    "upn": "alice.chen@outlook.com",
                    "key": "alice.chen@outlook.com",
                    "roles": ["sync"],
                    "details": ["个人版同步账户（Personal）"],
                }
            ],
        },
        {
            "id": TEAMS_ID,
            "name": "Microsoft Teams",
            "kind": "chat",
            "installed": False,
            "accounts": [
                {
                    "upn": "alice.chen@contoso.com",
                    "key": "alice.chen@contoso.com",
                    "roles": ["profile"],
                    "details": ["企业账户已登录"],
                }
            ],
        },
    ]

    return {
        "platform": _platform.platform_name(),
        "generated_at": iso(time.time()),
        "duration_ms": 1842,
        "demo": True,
        "summary": {
            "total": len(accounts),
            "org": sum(1 for a in accounts if a["kind"] == "org"),
            "msa": sum(1 for a in accounts if a["kind"] == "msa"),
            "china": sum(1 for a in accounts if a["cloud"] == "china"),
            "active_today": sum(1 for a in accounts if a["is_active_today"]),
            "stale": sum(1 for a in accounts if a["is_stale"]),
            "license_days_left": 48,
        },
        "accounts": accounts,
        "apps": apps,
        "warnings": [
            "Office 当前以工作账户 alice.chen@contoso.com 登录，但许可证来自个人账户 "
            "alice.chen@outlook.com，属于混合身份状态。",
            "共 3 个账户超过一天未活跃，属于历史缓存，可在清理时移除。",
            "检测到 1 个世纪互联（21Vianet）账户，其身份与全球云互不通用。",
        ],
        "device": _device_block(),
        "changes": {
            "snapshots": [
                {
                    "id": "20261025-093012",
                    "saved_at": _ts(0.4),
                    "signature": "demo1",
                    "summary": {"total": 4},
                    "account_count": 4,
                    "path": os.path.join(SNAPSHOT_DIR, "20261025-093012.json"),
                },
                {
                    "id": "20261024-214400",
                    "saved_at": _ts(1.2),
                    "signature": "demo2",
                    "summary": {"total": 5},
                    "account_count": 5,
                    "path": os.path.join(SNAPSHOT_DIR, "20261024-214400.json"),
                },
            ],
            "diff": {
                "from": {"id": "20261025-093012", "saved_at": _ts(0.4)},
                "to": {"id": "current", "saved_at": _ts(0)},
                "added": [{"upn": "dave@outlook.com", "kind": "msa", "tenant": None}],
                "removed": [],
                "changed": [
                    {
                        "upn": "carol@litware.cn",
                        "changes": [
                            {
                                "field": "应用关联",
                                "from": "2 项",
                                "to": "1 项",
                                "gained": [],
                                "lost": [f"{EDGE_ID}:profile"],
                            }
                        ],
                    }
                ],
                "has_changes": True,
            },
            "hint": None,
        },
        "office": {
            "activation_email": "alice.chen@outlook.com",
            "active_account_id": "aaaa1111-bbbb-2222-cccc-333344445555",
            "licenses": [
                {
                    "cid": "9999999999999999",
                    "not_before": (today - timedelta(days=28)).isoformat(),
                    "not_after": license_end,
                    "is_trial": False,
                }
            ],
        },
        "sources": {
            "oneauth": {
                "available": True,
                "path": ONEAUTH_DIR,
                "file_count": 42,
            },
            "edge": {"available": True, "profiles": 3},
            "onedrive": {"available": True, "accounts": 1},
            "office": {"available": True},
        },
        "snapshot_saved": None,
    }


def get() -> Dict[str, Any]:
    return copy.deepcopy(payload())
