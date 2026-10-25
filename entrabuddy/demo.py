"""演示数据：用虚构账户渲染界面，便于截图与文档展示。

用法：python app.py --demo
演示模式下所有写操作都会被拒绝。
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from .util import iso


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


def payload() -> Dict[str, Any]:
    today = datetime.now().date()
    license_end = (today + timedelta(days=48)).isoformat()

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
                        "Office 当前登录身份（OCPS-LastSuccessfulUserId）",
                        "Office 套件身份存储中留有该账户",
                    ],
                ),
                _binding(
                    "com.microsoft.teams2",
                    "Microsoft Teams",
                    ["profile"],
                    ["企业账户已登录"],
                    installed=False,
                ),
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "alice.chen@contoso.com_identity_provider",
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(0.05),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/contoso.com_hrd",
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
                    "com.microsoft.OneDrive-mac",
                    "OneDrive",
                    ["sync"],
                    ["个人版同步账户（Personal）"],
                ),
                _binding(
                    "com.microsoft.edgemac",
                    "Microsoft Edge",
                    ["profile"],
                    ["配置文件「默认」(Default) 已登录"],
                ),
            ],
            evidence=[
                {
                    "source": "OneAuth 身份缓存",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "alice.chen@outlook.com_identity_provider",
                    "detail": "identity_provider = MSAccount",
                    "timestamp": _ts(12),
                },
                {
                    "source": "OneAuth 个人资料",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "9999999999999999_substrate_profile",
                    "detail": "cid=9999999999999999，注册地=US",
                    "timestamp": _ts(0.04),
                },
                {
                    "source": "OneDrive 同步客户端",
                    "path": "~/Library/Group Containers/UBF8T346G9.OneDriveSyncClientSuite/"
                    "Library/Preferences/UBF8T346G9.OneDriveSyncClientSuite.plist",
                    "detail": "AccountInfo_Personal → alice.chen@outlook.com",
                    "timestamp": None,
                },
                {
                    "source": "Edge 配置文件",
                    "path": None,
                    "detail": "Default / 默认",
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
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "bob.wang@fabrikam.onmicrosoft.com_identity_provider",
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(31),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "fabrikam.onmicrosoft.com_hrd",
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
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "carol@litware.cn_identity_provider",
                    "detail": "identity_provider = OrgId",
                    "timestamp": _ts(180),
                },
                {
                    "source": "主域发现 (HRD)",
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/litware.cn_hrd",
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
                    "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/"
                    "dave@outlook.com_identity_provider",
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
                        "Office 当前登录身份（OCPS-LastSuccessfulUserId）",
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
            "id": "com.microsoft.edgemac",
            "name": "Microsoft Edge",
            "kind": "browser",
            "installed": True,
            "accounts": [
                {
                    "upn": "alice.chen@outlook.com",
                    "key": "alice.chen@outlook.com",
                    "roles": ["profile"],
                    "details": ["配置文件「默认」(Default) 已登录"],
                }
            ],
        },
        {
            "id": "com.microsoft.OneDrive-mac",
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
            "id": "com.microsoft.teams2",
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

    checks = [
        {
            "id": "entra",
            "label": "Entra ID 设备注册",
            "status": "ok",
            "value": "已注册",
            "detail": "检测到 Company Portal 与设备证书",
        },
        {
            "id": "mdm",
            "label": "MDM 注册",
            "status": "ok",
            "value": "已注册",
            "detail": "设备受移动设备管理，可下发合规策略",
        },
        {
            "id": "filevault",
            "label": "磁盘加密",
            "status": "ok",
            "value": "已启用",
            "detail": "FileVault 已开启",
        },
        {
            "id": "sip",
            "label": "系统完整性保护",
            "status": "ok",
            "value": "已启用",
            "detail": "System Integrity Protection status: enabled.",
        },
        {
            "id": "firewall",
            "label": "防火墙",
            "status": "warn",
            "value": "已关闭",
            "detail": "Firewall is disabled. (State = 0)",
        },
        {
            "id": "os",
            "label": "操作系统版本",
            "status": "ok",
            "value": "macOS 15.1",
            "detail": "在支持窗口内",
        },
        {
            "id": "defender",
            "label": "端点防护",
            "status": "ok",
            "value": "已载入租户",
            "detail": "org_id=11111111-2222-3333-4444-555555555555",
        },
    ]
    passed = sum(1 for c in checks if c["status"] == "ok")

    return {
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
        "device": {
            "identity": {
                "hostname": "MBP-DEMO",
                "local_hostname": "MBP-DEMO",
                "model": "MacBookPro18,3",
                "chip": "Apple M1 Pro",
                "serial": "C02XXXXXXXXX",
                "os_version": "15.1",
                "os_build": "24B83",
            },
            "enrollment": {
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
            },
            "compliance": {
                "checks": checks,
                "passed": passed,
                "total": len(checks),
                "score": round(passed / len(checks) * 100),
            },
            "note": "以上为本机可验证的信号。Intune 的实际合规结论由云端策略计算，"
            "需要 Graph 授权才能读取，本地无法替代。",
        },
        "changes": {
            "snapshots": [
                {
                    "id": "20261025-093012",
                    "saved_at": _ts(0.4),
                    "signature": "demo1",
                    "summary": {"total": 4},
                    "account_count": 4,
                    "path": "~/Library/Application Support/EntraBuddy/snapshots/20261025-093012.json",
                },
                {
                    "id": "20261024-214400",
                    "saved_at": _ts(1.2),
                    "signature": "demo2",
                    "summary": {"total": 5},
                    "account_count": 5,
                    "path": "~/Library/Application Support/EntraBuddy/snapshots/20261024-214400.json",
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
                                "lost": ["com.microsoft.edgemac:profile"],
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
                "path": "~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore",
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
