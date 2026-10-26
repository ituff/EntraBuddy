"""扫描编排：合并各来源，产出账户清单与「账户 -> 应用」关联（双平台）。

平台差异全部收敛在 collectors 分派层：
    * 应用 ID（edge/onedrive 的 APP_ID 随平台不同）
    * Office 当前登录身份的描述文案（office.ACTIVE_DETAIL）
    * OneDrive 证据路径（onedrive.evidence_path(slot)）
编排、账户合并、角色绑定与洞察生成完全共享。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List

from . import _platform
from .collectors import device, edge, environment, office, oneauth, onedrive
from .util import human_path, iso

CLOUD_LABELS = {"global": "国际版", "china": "世纪互联"}

# 关联角色权重，数字越小越靠前
ROLE_WEIGHT = {"active": 0, "licensed": 1, "sync": 2, "profile": 3, "cached": 4, "trace": 5}

# 设备与环境信息变化很慢，且要跑多个系统命令，做短时缓存避免每次重扫都等
_SLOW_CACHE: Dict[str, Any] = {}
_SLOW_TTL = 120.0


def _cached(key: str, fn):
    now = time.time()
    hit = _SLOW_CACHE.get(key)
    if hit and now - hit[0] < _SLOW_TTL:
        return hit[1]
    value = fn()
    _SLOW_CACHE[key] = (now, value)
    return value


def _blank(upn: str) -> Dict[str, Any]:
    return {
        "key": upn.lower(),
        "upn": upn,
        "display_name": None,
        "kind": "unknown",
        "cloud": "global",
        "tenant_id": None,
        "tenant_name": None,
        "object_id": None,
        "cid": None,
        "location": None,
        "last_seen": None,
        "last_seen_ts": 0.0,
        "link_confidence": None,
        "evidence": [],
        "apps": [],
        "notes": [],
    }


def _touch(account: Dict[str, Any], ts: float | None, when: str | None) -> None:
    if ts and ts > (account["last_seen_ts"] or 0):
        account["last_seen_ts"] = ts
        account["last_seen"] = when


def _add_evidence(account, source, path, detail, timestamp) -> None:
    account["evidence"].append(
        {
            "source": source,
            "path": human_path(path) if path else None,
            "detail": detail,
            "timestamp": timestamp,
        }
    )


def _bind(account, app_id, app_name, role, detail, installed=True) -> None:
    """把「应用 + 角色」记到账户上；同一应用的多个角色合并成一行。"""
    for existing in account["apps"]:
        if existing["app_id"] == app_id:
            if role not in existing["roles"]:
                existing["roles"].append(role)
                existing["details"].append(detail)
            return
    account["apps"].append(
        {
            "app_id": app_id,
            "app_name": app_name,
            "roles": [role],
            "details": [detail],
            "installed": installed,
        }
    )


def scan() -> Dict[str, Any]:
    started = time.time()

    raw = oneauth.collect()
    org_linked = oneauth.link_org_accounts(raw)
    office_data = office.collect()
    edge_data = edge.collect()
    onedrive_data = onedrive.collect()
    env = _cached("environment", environment.collect)
    device_data = _cached("device", device.collect)

    accounts: Dict[str, Dict[str, Any]] = {}

    def ensure(upn: str) -> Dict[str, Any]:
        key = upn.lower()
        if key not in accounts:
            accounts[key] = _blank(upn)
        return accounts[key]

    # ---------- 1. OneAuth 里的 UPN 级身份（最可靠） ----------
    for identity in raw["identities"]:
        account = ensure(identity["upn"])
        account["kind"] = "org" if identity["provider"] == "OrgId" else "msa"
        _touch(account, identity.get("ts"), identity.get("last_seen"))
        _add_evidence(
            account,
            "OneAuth 身份缓存",
            identity["source"],
            f"identity_provider = {identity['provider']}",
            identity.get("last_seen"),
        )

    # ---------- 2. OrgId 账户补齐 objectId / 租户 ----------
    for item in org_linked:
        account = ensure(item["upn"])
        account["kind"] = "org"
        if item.get("object_id") and not account.get("object_id"):
            account["object_id"] = item.get("object_id")
        account["tenant_name"] = account.get("tenant_name") or item.get("tenant_name")
        if item.get("confidence"):
            account["link_confidence"] = item.get("confidence")

        tenant = oneauth.resolve_tenant(raw["hrds"], item["upn"])
        if tenant:
            account["tenant_id"] = account.get("tenant_id") or tenant.get("tenant_id")
            account["cloud"] = tenant.get("environment", "global")
            _add_evidence(
                account,
                "主域发现 (HRD)",
                tenant["source"],
                f"域 {item['upn'].rsplit('@', 1)[-1]} → 租户 {tenant.get('tenant_id')}",
                tenant.get("last_seen"),
            )
        if item.get("object_id") and account.get("object_id") == item.get("object_id"):
            _add_evidence(
                account,
                "OneAuth 组织信息",
                None,
                f"objectId={item['object_id']}，租户名={item.get('tenant_name')}",
                item.get("org_seen"),
            )

    # ---------- 3. MSA 账户补齐 cid ----------
    msa_by_upn = {b["upn"].lower(): b for b in raw["msa_blobs"] if b.get("upn")}
    for upn_lower, blob in msa_by_upn.items():
        account = ensure(blob["upn"])
        account["kind"] = "msa"
        if blob["account_id"] and not account.get("cid"):
            account["cid"] = blob["account_id"]
        account["location"] = account.get("location") or blob.get("location")
        _touch(account, blob.get("ts"), blob.get("last_seen"))
        _add_evidence(
            account,
            "OneAuth 个人资料",
            blob["source"],
            f"cid={blob['account_id']}，注册地={blob.get('location')}",
            blob.get("last_seen"),
        )

    # ---------- 4. Edge 配置文件 ----------
    for profile in edge_data["profiles"]:
        for acc in profile["accounts"]:
            email = acc.get("email")
            if not email:
                continue
            account = ensure(email)
            account["display_name"] = account["display_name"] or acc.get("full_name")
            if account["kind"] == "unknown":
                account["kind"] = "msa" if not acc.get("hosted_domain") else "org"
            if acc.get("gaia_id") and not account["cid"]:
                account["cid"] = acc["gaia_id"]
            detail = f"配置文件「{profile['name']}」({profile['dir']}) 已登录"
            if acc.get("source") == "cache":
                detail += "，登录态来自 Local State 缓存"
            _bind(
                account,
                edge.APP_ID,
                "Microsoft Edge",
                "profile",
                detail,
                edge_data["installed"],
            )
            _add_evidence(
                account,
                "Edge 配置文件",
                None,
                f"{profile['dir']} / {profile['name']}",
                None,
            )

    # ---------- 5. OneDrive ----------
    for od in onedrive_data["accounts"]:
        account = ensure(od["email"])
        if account["kind"] == "unknown":
            account["kind"] = "msa" if od["kind"] == "personal" else "org"
        if od.get("cid") and not account["cid"]:
            account["cid"] = od["cid"]
        if od.get("object_id") and not account.get("object_id"):
            account["object_id"] = od["object_id"]
        if od.get("tenant_id") and not account["tenant_id"] and od["kind"] == "business":
            account["tenant_id"] = od["tenant_id"]
        _bind(
            account,
            onedrive.APP_ID,
            "OneDrive",
            "sync",
            f"{'个人版' if od['kind'] == 'personal' else '企业版'}同步账户（{od['slot']}）",
            onedrive_data["installed"],
        )
        _add_evidence(
            account,
            "OneDrive 同步客户端",
            onedrive.evidence_path(od["slot"]),
            f"{'UserEmail' if _platform.IS_WINDOWS else 'AccountInfo_' + od['slot']} → {od['email']}",
            od.get("last_seen"),
        )

    # ---------- 6. Office 身份与授权 ----------
    office_installed = any(a["installed"] for a in office_data["apps"])
    active_id = (office_data.get("active_account_id") or "").lower()

    for account in accounts.values():
        if account["kind"] in ("org", "msa"):
            _bind(
                account,
                "com.microsoft.office",
                "Microsoft Office",
                "cached",
                "Office 套件身份存储中留有该账户",
                office_installed,
            )

        if active_id and active_id in {
            (account.get("object_id") or "").lower(),
            (account.get("cid") or "").lower(),
        }:
            _bind(
                account,
                "com.microsoft.office",
                "Microsoft Office",
                "active",
                office.ACTIVE_DETAIL,
                office_installed,
            )

        for lic in office_data["licenses"]:
            if lic.get("cid") and account.get("cid") and lic["cid"] == account["cid"].lower():
                _bind(
                    account,
                    "com.microsoft.office",
                    "Microsoft Office",
                    "licensed",
                    f"授权 Office 许可证，有效期至 {lic.get('not_after') or '未知'}",
                    office_installed,
                )

        # Windows 新一代许可（NextUserLicensing）提供的 账户 -> 许可 映射
        licensed_ids = office_data.get("licensed_ids") or []
        if licensed_ids and (
            (account.get("cid") or "").lower() in licensed_ids
            or (account.get("object_id") or "").lower() in licensed_ids
        ):
            _bind(
                account,
                "com.microsoft.office",
                "Microsoft Office",
                "licensed",
                "新一代许可（NextUserLicensing）已授权该账户",
                office_installed,
            )

    # ---------- 7. Defender 租户匹配 ----------
    defender = env.get("defender") or {}
    if defender.get("onboarded") and defender.get("org_id"):
        for account in accounts.values():
            if account.get("tenant_id") and account["tenant_id"].lower() == defender["org_id"].lower():
                _bind(
                    account,
                    "com.microsoft.wdav",
                    "Microsoft Defender",
                    "trace",
                    "Defender for Endpoint 已载入该租户",
                    True,
                )

    # ---------- 8. 收尾：排序、标记活跃、生成提示 ----------
    today = datetime.now().date()

    license_by_cid: Dict[str, Dict[str, Any]] = {}
    for lic in office_data["licenses"]:
        if lic.get("cid"):
            license_by_cid[lic["cid"].lower()] = lic

    for account in accounts.values():
        # 角色按重要性排序，details 与 roles 保持同序
        for binding in account["apps"]:
            ordered_pairs = sorted(
                zip(binding["roles"], binding["details"]),
                key=lambda pair: ROLE_WEIGHT.get(pair[0], 9),
            )
            binding["roles"] = [pair[0] for pair in ordered_pairs]
            binding["details"] = [pair[1] for pair in ordered_pairs]
        account["apps"].sort(
            key=lambda a: min(ROLE_WEIGHT.get(r, 9) for r in a["roles"])
        )
        if account["last_seen"]:
            try:
                account["is_active_today"] = (
                    datetime.fromisoformat(account["last_seen"]).date() == today
                )
            except ValueError:
                account["is_active_today"] = False
        else:
            account["is_active_today"] = False

        if account["kind"] == "org" and not account.get("tenant_id"):
            account["notes"].append("未能解析租户 ID（该域无 HRD 缓存）")
        if account["link_confidence"] == "low":
            account["notes"].append("objectId 与 UPN 为时间邻近推断，置信度低")
        if not account["apps"]:
            account["notes"].append("未找到关联应用，可能仅为残留缓存")

        # 残留判定：今天没活跃，且没有任何「正在使用」的角色
        live_roles = {"active", "licensed", "sync", "profile", "trace"}
        has_live = any(live_roles & set(b["roles"]) for b in account["apps"])
        account["is_stale"] = (not account["is_active_today"]) and not has_live

        # 凭据健康：缓存新鲜度 + 许可证倒计时
        credential: Dict[str, Any] = {"cache_age_days": None, "freshness": "unknown", "license": None}
        if account["last_seen_ts"]:
            age_days = (time.time() - account["last_seen_ts"]) / 86400
            credential["cache_age_days"] = round(age_days, 1)
            if age_days <= 7:
                credential["freshness"] = "fresh"
            elif age_days <= 45:
                credential["freshness"] = "aging"
            else:
                credential["freshness"] = "stale"

        lic = license_by_cid.get((account.get("cid") or "").lower())
        if lic and lic.get("not_after"):
            try:
                end = datetime.strptime(lic["not_after"], "%Y-%m-%d").date()
                credential["license"] = {
                    "not_after": lic["not_after"],
                    "not_before": lic.get("not_before"),
                    "days_left": (end - today).days,
                    "is_trial": lic.get("is_trial"),
                }
            except ValueError:
                pass
        account["credential"] = credential

    ordered = sorted(
        accounts.values(),
        key=lambda a: (not a["is_active_today"], -(a["last_seen_ts"] or 0), a["upn"]),
    )

    # ---------- 9. 应用视图 ----------
    app_catalog: Dict[str, Dict[str, Any]] = {}
    for spec in env["apps"]:
        # Office 各组件共用同一身份存储，统一归到 "Microsoft Office" 聚合卡片
        if spec["kind"] == "office":
            continue
        app_catalog[spec["id"]] = {
            "id": spec["id"],
            "name": spec["name"],
            "kind": spec["kind"],
            "installed": spec["installed"],
            "accounts": {},
        }
    for account in ordered:
        for binding in account["apps"]:
            entry = app_catalog.get(binding["app_id"])
            if not entry:
                entry = {
                    "id": binding["app_id"],
                    "name": binding["app_name"],
                    "kind": "other",
                    "installed": binding["installed"],
                    "accounts": {},
                }
                app_catalog[binding["app_id"]] = entry
            slot = entry["accounts"].setdefault(
                account["key"],
                {"upn": account["upn"], "key": account["key"], "roles": [], "details": []},
            )
            for role, detail in zip(binding["roles"], binding["details"]):
                if role not in slot["roles"]:
                    slot["roles"].append(role)
                    slot["details"].append(detail)

    apps_view = []
    for entry in app_catalog.values():
        accounts_list = list(entry["accounts"].values())
        for item in accounts_list:
            pairs = sorted(
                zip(item["roles"], item["details"]),
                key=lambda pair: ROLE_WEIGHT.get(pair[0], 9),
            )
            item["roles"] = [pair[0] for pair in pairs]
            item["details"] = [pair[1] for pair in pairs]
        accounts_list.sort(
            key=lambda x: min(ROLE_WEIGHT.get(r, 9) for r in x["roles"]) if x["roles"] else 9
        )
        entry["accounts"] = accounts_list
        apps_view.append(entry)

    apps_view.sort(key=lambda a: (not a["accounts"], not a["installed"], a["name"]))

    # ---------- 10. 汇总与洞察 ----------
    org_count = sum(1 for a in ordered if a["kind"] == "org")
    msa_count = sum(1 for a in ordered if a["kind"] == "msa")
    china_count = sum(1 for a in ordered if a["cloud"] == "china")
    active_count = sum(1 for a in ordered if a["is_active_today"])

    warnings: List[str] = []

    active_org = next(
        (a for a in ordered if a["is_active_today"] and a["kind"] == "org"), None
    )
    licensed = next(
        (
            a
            for a in ordered
            if any("licensed" in b["roles"] for b in a["apps"])
        ),
        None,
    )
    if active_org and licensed and active_org["key"] != licensed["key"]:
        warnings.append(
            f"Office 当前以工作账户 {active_org['upn']} 登录，但许可证来自个人账户 "
            f"{licensed['upn']}，属于混合身份状态。"
        )

    tenant_key = (office_data.get("tenant_key") or "").lower()
    if active_org and tenant_key and active_org.get("tenant_id"):
        if tenant_key != active_org["tenant_id"].lower():
            warnings.append(
                f"Office 偏好中残留的租户 ID（{tenant_key}）与当前登录账户的租户"
                f"（{active_org['tenant_id']}）不一致，可能是历史遗留。"
            )

    stale = [a for a in ordered if not a["is_active_today"]]
    if stale:
        warnings.append(
            f"共 {len(stale)} 个账户超过一天未活跃，属于历史缓存，可在清理时移除。"
        )

    if china_count == 0:
        warnings.append("未发现世纪互联（21Vianet）版账户，所有身份均位于 Microsoft 全球云。")

    license_days_left = None
    for account in ordered:
        lic = (account.get("credential") or {}).get("license")
        if lic:
            license_days_left = lic["days_left"]
            if lic["days_left"] <= 30:
                warnings.append(
                    f"Office 许可证将在 {lic['days_left']} 天后到期"
                    f"（{lic['not_after']}），请及时续订。"
                )
            break

    if not env["mdm"]["enrolled"]:
        warnings.append(
            "本机未注册 MDM，因此不存在 Intune 设备对象，账户仅存在于应用层。"
        )

    return {
        "platform": _platform.platform_name(),
        "generated_at": iso(time.time()),
        "duration_ms": int((time.time() - started) * 1000),
        "summary": {
            "total": len(ordered),
            "org": org_count,
            "msa": msa_count,
            "china": china_count,
            "active_today": active_count,
            "stale": sum(1 for a in ordered if a["is_stale"]),
            "license_days_left": license_days_left,
        },
        "accounts": ordered,
        "apps": apps_view,
        "warnings": warnings,
        "device": device_data,
        "office": {
            "activation_email": office_data.get("activation_email"),
            "active_account_id": office_data.get("active_account_id"),
            "licenses": office_data.get("licenses", []),
        },
        "environment": env,
        "sources": {
            "oneauth": {
                "available": raw["available"],
                "path": human_path(raw["dir"]),
                "file_count": raw["file_count"],
            },
            "edge": {"available": edge_data["available"], "profiles": len(edge_data["profiles"])},
            "onedrive": {
                "available": onedrive_data.get("available"),
                "accounts": len(onedrive_data["accounts"]),
            },
            "office": {"available": office_data["prefs_available"]},
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(scan(), ensure_ascii=False, indent=2))
