"""账户缓存清理：先备份、再移除，可回滚。支持单账户与批量、按清理范围选择。

清理范围（apps 参数，白名单校验，不接受外部路径）：
    identity  OneAuth blobs 共享身份缓存（默认，向后兼容现行为）。
              Office 全家桶与新 OneDrive 客户端共用，清理后需重新登录。
    office    Office 专属存储：许可证文件（按 CID 匹配）+
              Windows 注册表 Identity\\Profiles 子键。
              不动 OneAuth，OneDrive / Edge 不受影响。
    onedrive  OneDrive 账户注册表键（按 UserEmail 匹配，slot 白名单）。
              解绑同步账户，本地同步文件夹保留。

Edge 登录态在 Chromium 配置文件内，自动清理易损坏配置文件，不在支持范围。

安全约束（硬编码）：
    * 文件只在 OneAuth blobs 目录内操作，只匹配白名单前缀
    * 注册表只操作代码构造的白名单路径（OneDrive Accounts slot /
      Office Identity Profiles），删除前快照备份
    * 拒绝符号链接与目录穿越
    * 单账户最多 40 项，批量最多 200 项
    * 删除前必须完整备份，备份失败则整体中止
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

try:
    import winreg
except ImportError:  # pragma: no cover - 非 Windows
    winreg = None

from .collectors import office, onedrive, oneauth
from .util import APP_SUPPORT, human_path

BACKUP_ROOT = os.path.join(APP_SUPPORT, "backups")
BLOB_DIR = oneauth.BLOB_DIR
MAX_FILES_PER_ACCOUNT = 40
MAX_FILES_TOTAL = 200

VALID_SCOPES = ("identity", "office", "onedrive")

_REG_HIVES = {}
if winreg is not None:
    _REG_HIVES = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }


class CleanupError(RuntimeError):
    pass


# ---------- 注册表操作（模块级，测试可注入替身） ----------

def _reg_split(path: str) -> tuple[int, str]:
    """'HKCU\\Software\\X' -> (hive, 'Software\\X')。仅接受白名单 hive。"""
    hive_name, _, sub = path.partition("\\")
    if hive_name not in _REG_HIVES:
        raise CleanupError(f"不支持的注册表根：{hive_name}")
    return _REG_HIVES[hive_name], sub


def _reg_snapshot(path: str) -> Optional[Dict[str, Any]]:
    """枚举一个键的全部值，作为删除前的备份快照。"""
    if winreg is None:
        return None
    hive, sub = _reg_split(path)
    values = {}
    try:
        with winreg.OpenKey(hive, sub) as key:
            index = 0
            while True:
                try:
                    name, value, _type = winreg.EnumValue(key, index)
                    values[name] = value
                    index += 1
                except OSError:
                    break
    except OSError:
        return None
    return values or {}


def _reg_delete_key(path: str) -> None:
    """删除一个键（含子键，自内向外）。路径必须来自代码构造的白名单。"""
    if winreg is None:
        raise CleanupError("当前平台不支持注册表清理")
    hive, sub = _reg_split(path)

    def delete_recursive(h, s: str) -> None:
        try:
            with winreg.OpenKey(h, s) as key:
                subs = []
                index = 0
                while True:
                    try:
                        subs.append(winreg.EnumKey(key, index))
                        index += 1
                    except OSError:
                        break
            for child in subs:
                delete_recursive(h, s + "\\" + child)
            winreg.DeleteKey(h, s)
        except OSError as exc:
            raise CleanupError(f"删除注册表键失败：{path}（{exc}）") from exc

    delete_recursive(hive, sub)


def _reg_restore(path: str, values: Dict[str, Any]) -> None:
    """按快照重建键与值（备份恢复用）。"""
    if winreg is None:
        raise CleanupError("当前平台不支持注册表恢复")
    hive, sub = _reg_split(path)
    with winreg.CreateKey(hive, sub) as key:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def _safe_join(root: str, name: str) -> str:
    path = os.path.realpath(os.path.join(root, name))
    root_real = os.path.realpath(root)
    if not path.startswith(root_real + os.sep):
        raise CleanupError(f"路径越界，已拒绝：{name}")
    return path


def _resolve_accounts(upns: List[str]) -> List[Dict[str, Any]]:
    """一次解析多个账户，共享同一份 OneAuth 快照。"""
    raw = oneauth.collect()
    linked = oneauth.link_org_accounts(raw)

    identity_by_upn = {i["upn"].lower(): i for i in raw["identities"]}
    msa_by_upn = {
        (b.get("upn") or "").lower(): b for b in raw["msa_blobs"] if b.get("upn")
    }
    org_by_upn = {i["upn"].lower(): i for i in linked}

    resolved: List[Dict[str, Any]] = []
    missing: List[str] = []

    for upn in upns:
        key = upn.lower()
        identity = identity_by_upn.get(key)
        if identity is None and key not in msa_by_upn:
            missing.append(upn)
            continue

        prefixes = {key}
        object_id = None
        tenant_name = None
        if identity and identity.get("provider") == "OrgId":
            org = org_by_upn.get(key) or {}
            object_id = org.get("object_id")
            tenant_name = org.get("tenant_name")
            if object_id:
                prefixes.add(object_id.lower())
        if key in msa_by_upn:
            prefixes.add(msa_by_upn[key]["account_id"].lower())

        tenant = oneauth.resolve_tenant(raw["hrds"], upn)
        resolved.append(
            {
                "upn": upn,
                "provider": (identity or {}).get("provider")
                or ("MSAccount" if key in msa_by_upn else None),
                "object_id": object_id,
                "cid": msa_by_upn[key]["account_id"].lower() if key in msa_by_upn else None,
                "tenant_id": tenant.get("tenant_id") if tenant else None,
                "tenant_name": tenant_name,
                "prefixes": prefixes,
            }
        )

    if missing and not resolved:
        raise CleanupError(f"未找到账户：{', '.join(missing)}")
    return resolved


def _resolve_account(upn: str) -> Dict[str, Any]:
    return _resolve_accounts([upn])[0]


def _reason(name: str) -> str:
    if "_identity_provider" in name:
        return "身份提供方缓存"
    if "_graph_organization" in name and "metadata" not in name:
        return "租户信息缓存"
    if "_substrate_profile" in name and "metadata" not in name:
        return "个人资料缓存"
    if "_avatar" in name:
        return "头像缓存"
    return "HTTP 响应缓存"


def _files_for(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    """identity 范围：OneAuth blobs 里属于该账户的文件。"""
    if not os.path.isdir(BLOB_DIR):
        return []

    found: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(BLOB_DIR)):
        lowered = name.lower()
        matched = next(
            (p for p in account["prefixes"] if lowered.startswith(p + "_")), None
        )
        if not matched:
            continue
        # hrd 是按域/租户共享的解析缓存，不属于单个账户，跳过
        if lowered.endswith("_hrd") or lowered.endswith("_hrd_metadata"):
            continue
        path = _safe_join(BLOB_DIR, name)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        found.append(
            {
                "name": name,
                "path": path,
                "dir": os.path.dirname(path),
                "display_path": human_path(path),
                "size": size,
                "reason": _reason(name),
                "upn": account["upn"],
                "scope": "identity",
            }
        )
    return found


def _office_files_for(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    """office 范围：该账户 CID 名下的许可证文件。"""
    cid = account.get("cid")
    if not cid:
        return []
    found: List[Dict[str, Any]] = []
    for path in office.license_paths_for_cid(cid):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        found.append(
            {
                "name": os.path.basename(path),
                "path": path,
                "dir": os.path.dirname(path),
                "display_path": human_path(path),
                "size": size,
                "reason": "Office 许可证",
                "upn": account["upn"],
                "scope": "office",
            }
        )
    return found


def _registry_keys_for(account: Dict[str, Any], scopes: List[str]) -> List[Dict[str, Any]]:
    """office / onedrive 范围的注册表键，plan 时即快照，execute 直接用。"""
    keys: List[Dict[str, Any]] = []

    if "office" in scopes:
        account_ids = set(account["prefixes"])
        if account.get("cid"):
            account_ids.add(account["cid"])
        for path in office.profile_registry_keys(sorted(account_ids)):
            snapshot = _reg_snapshot(path)
            if snapshot is None:
                continue
            keys.append(
                {
                    "path": path,
                    "values": snapshot,
                    "reason": "Office 身份记录（Identity\\Profiles）",
                    "upn": account["upn"],
                    "scope": "office",
                }
            )

    if "onedrive" in scopes:
        for path in onedrive.account_slot_paths(account["upn"]):
            snapshot = _reg_snapshot(path)
            if snapshot is None:
                continue
            keys.append(
                {
                    "path": path,
                    "values": snapshot,
                    "reason": "OneDrive 同步账户",
                    "upn": account["upn"],
                    "scope": "onedrive",
                }
            )
    return keys


def _normalize_scopes(apps: Optional[List[str]]) -> List[str]:
    """校验并归一化清理范围。None -> ['identity']（向后兼容）。"""
    if apps is None:
        return ["identity"]
    if not isinstance(apps, list):
        raise CleanupError("apps 必须是范围列表")
    normalized = []
    for app in apps:
        app = str(app).strip().lower()
        if app not in VALID_SCOPES:
            raise CleanupError(f"不支持的清理范围：{app}（可用：{'、'.join(VALID_SCOPES)}）")
        if app not in normalized:
            normalized.append(app)
    if not normalized:
        raise CleanupError("至少选择一个清理范围")
    return normalized


def _scope_warnings(scopes: List[str]) -> List[str]:
    warnings: List[str] = []
    if "office" in scopes:
        warnings.append(
            "office 范围会删除许可证文件并取消激活；身份缓存(identity)不在其中，"
            "账户可能仍显示为「身份缓存」。"
        )
    if "onedrive" in scopes:
        warnings.append(
            "onedrive 范围会解绑同步账户，本地同步文件夹保留，重新登录后可恢复同步。"
        )
    if "onedrive" in scopes or "office" in scopes:
        warnings.append("Edge 登录态不支持自动清理，请在 Edge 设置内退出登录。")
    return warnings


def plan_many(upns: List[str], apps: Optional[List[str]] = None) -> Dict[str, Any]:
    """生成清理计划（不落盘、不删除）。apps 为清理范围列表。"""
    scopes = _normalize_scopes(apps)
    accounts = _resolve_accounts(upns)

    files: List[Dict[str, Any]] = []
    registry_keys: List[Dict[str, Any]] = []
    seen: set[str] = set()
    per_account: List[Dict[str, Any]] = []

    for account in accounts:
        own_files: List[Dict[str, Any]] = []
        if "identity" in scopes:
            own_files += [f for f in _files_for(account) if f["name"] not in seen]
        if "office" in scopes:
            own_files += [f for f in _office_files_for(account) if f["name"] not in seen]
        own_keys = _registry_keys_for(account, scopes)

        item_count = len(own_files) + len(own_keys)
        if item_count > MAX_FILES_PER_ACCOUNT:
            raise CleanupError(
                f"{account['upn']} 待清理项过多（{item_count}），已中止"
            )
        for item in own_files:
            seen.add(item["name"])
            files.append(item)
        registry_keys += own_keys
        per_account.append(
            {
                "upn": account["upn"],
                "provider": account["provider"],
                "object_id": account["object_id"],
                "tenant_id": account["tenant_id"],
                "tenant_name": account.get("tenant_name"),
                "file_count": len(own_files),
                "registry_count": len(own_keys),
                "bytes": sum(f["size"] for f in own_files),
            }
        )

    total_items = len(files) + len(registry_keys)
    if total_items > MAX_FILES_TOTAL:
        raise CleanupError(f"待清理项过多（{total_items}），已中止")

    return {
        "scopes": scopes,
        "accounts": per_account,
        "account": per_account[0] if len(per_account) == 1 else None,
        "files": files,
        "registry_keys": registry_keys,
        "file_count": len(files),
        "registry_count": len(registry_keys),
        "total_count": total_items,
        "total_bytes": sum(f["size"] for f in files),
        "root": human_path(BLOB_DIR),
        "warnings": [
            "清理前请退出相关应用，否则缓存会被重新写入。",
            *_scope_warnings(scopes),
            "清理只移除本地缓存，不会吊销任何令牌，也不会影响云端账户。",
        ],
    }


def plan(upn: str, apps: Optional[List[str]] = None) -> Dict[str, Any]:
    return plan_many([upn], apps=apps)


def _regkey_backup_name(index: int, path: str) -> str:
    tail = path.replace("\\", "_").replace("/", "_")
    return f"regkey_{index:02d}_{tail}.reg.json"


def execute_many(
    upns: List[str],
    expect_files: Optional[int] = None,
    apps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """备份后删除。多个账户共用一份备份，可整体回滚。"""
    current = plan_many(upns, apps=apps)
    total_items = current["file_count"] + current["registry_count"]
    if expect_files is not None and expect_files != total_items:
        raise CleanupError("清理清单已变化，请重新生成计划")

    if not total_items:
        return {
            "ok": True,
            "removed": 0,
            "deleted_keys": 0,
            "backup": None,
            "accounts": current["accounts"],
            "message": "没有需要清理的缓存",
        }

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if len(current["accounts"]) == 1:
        slug = current["accounts"][0]["upn"].replace("@", "_at_").replace("/", "_")
    else:
        slug = f"batch{len(current['accounts'])}"
    backup_dir = os.path.join(BACKUP_ROOT, f"{stamp}_{slug}")
    files_dir = os.path.join(backup_dir, "files")
    os.makedirs(files_dir, exist_ok=True)

    # 1) 备份：文件逐个校验大小，注册表键写入快照 JSON；任一失败整体中止
    try:
        for item in current["files"]:
            dest = os.path.join(files_dir, item["name"])
            shutil.copy2(item["path"], dest)
            if os.path.getsize(dest) != item["size"]:
                raise CleanupError(f"备份校验失败：{item['name']}")
        regkey_manifest = []
        for index, key in enumerate(current["registry_keys"]):
            backup_name = _regkey_backup_name(index, key["path"])
            payload = {"path": key["path"], "values": key["values"]}
            with open(
                os.path.join(files_dir, backup_name), "w", encoding="utf-8"
            ) as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            regkey_manifest.append({"backup": backup_name, "path": key["path"]})
    except Exception as exc:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise CleanupError(f"备份失败，已中止清理：{exc}") from exc

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "apps": current["scopes"],
        "accounts": [
            {"upn": a["upn"], "object_id": a["object_id"], "tenant_id": a["tenant_id"]}
            for a in current["accounts"]
        ],
        "root": BLOB_DIR,
        "files": [
            {
                "name": f["name"],
                "dir": f.get("dir", BLOB_DIR),
                "size": f["size"],
                "reason": f["reason"],
                "upn": f["upn"],
                "scope": f.get("scope", "identity"),
            }
            for f in current["files"]
        ],
        "registry_keys": regkey_manifest,
    }
    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # 2) 删除：先文件，后注册表键
    removed = 0
    failed: List[str] = []
    for item in current["files"]:
        try:
            os.remove(item["path"])
            removed += 1
        except OSError:
            failed.append(item["name"])

    deleted_keys = 0
    for key in current["registry_keys"]:
        try:
            _reg_delete_key(key["path"])
            deleted_keys += 1
        except CleanupError:
            failed.append(key["path"])

    label = (
        current["accounts"][0]["upn"]
        if len(current["accounts"]) == 1
        else f"{len(current['accounts'])} 个账户"
    )
    summary = f"已备份并移除 {label} 的 {removed} 个缓存文件"
    if deleted_keys:
        summary += f"、{deleted_keys} 个注册表账户记录"
    return {
        "ok": not failed,
        "removed": removed,
        "deleted_keys": deleted_keys,
        "failed": failed,
        "backup": backup_dir,
        "backup_display": human_path(backup_dir),
        "accounts": current["accounts"],
        "message": summary,
    }


def execute(
    upn: str,
    expect_files: Optional[int] = None,
    apps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return execute_many([upn], expect_files=expect_files, apps=apps)


def list_backups() -> List[Dict[str, Any]]:
    if not os.path.isdir(BACKUP_ROOT):
        return []
    items = []
    for name in sorted(os.listdir(BACKUP_ROOT), reverse=True):
        path = os.path.join(BACKUP_ROOT, name)
        manifest_path = os.path.join(path, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            continue

        accounts = manifest.get("accounts")
        if accounts:
            label = (
                accounts[0].get("upn")
                if len(accounts) == 1
                else f"{len(accounts)} 个账户"
            )
        else:  # 兼容旧版单账户清单
            label = (manifest.get("account") or {}).get("upn")

        items.append(
            {
                "id": name,
                "path": path,
                "display_path": human_path(path),
                "created_at": manifest.get("created_at"),
                "account": label,
                "file_count": len(manifest.get("files") or []),
                "registry_count": len(manifest.get("registry_keys") or []),
                "account_count": len(accounts) if accounts else 1,
            }
        )
    return items


def restore(backup_id: str) -> Dict[str, Any]:
    """把备份目录里的文件与注册表快照恢复回原位置。"""
    if not backup_id or os.sep in backup_id or ".." in backup_id:
        raise CleanupError("非法备份标识")

    backup_dir = os.path.join(BACKUP_ROOT, backup_id)
    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise CleanupError("备份不存在")

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    root = manifest.get("root") or BLOB_DIR
    if os.path.realpath(root) != os.path.realpath(BLOB_DIR):
        raise CleanupError("备份来源与当前 OneAuth 目录不一致，已拒绝恢复")

    # 恢复目标只允许已知来源目录，防止被篡改的清单把文件写到任意位置
    allowed_roots = {os.path.realpath(BLOB_DIR)}
    for lic_root in getattr(office, "LICENSE_ROOTS", []):
        allowed_roots.add(os.path.realpath(lic_root))

    restored = 0
    for item in manifest.get("files") or []:
        src = os.path.join(backup_dir, "files", item["name"])
        if not os.path.isfile(src):
            continue
        target_dir = os.path.realpath(item.get("dir") or root)
        if target_dir not in allowed_roots:
            continue
        dst = os.path.join(target_dir, item["name"])
        shutil.copy2(src, dst)
        restored += 1

    # 注册表快照（旧版清单没有该字段）；路径必须在白名单前缀内
    onedrive_prefix = "HKCU" + "\\" + "Software\\Microsoft\\OneDrive\\Accounts\\"
    office_prefix = "Identity" + "\\" + "Profiles" + "\\"
    reg_prefixes = (onedrive_prefix, office_prefix)
    for item in manifest.get("registry_keys") or []:
        snapshot_path = os.path.join(backup_dir, "files", item["backup"])
        try:
            with open(snapshot_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        reg_path = payload.get("path") or ""
        if not any(prefix in reg_path for prefix in reg_prefixes):
            continue
        try:
            _reg_restore(reg_path, payload.get("values") or {})
            restored += 1
        except CleanupError:
            pass

    return {"ok": True, "restored": restored, "message": f"已恢复 {restored} 项"}
