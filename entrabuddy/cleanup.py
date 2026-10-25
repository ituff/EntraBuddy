"""账户缓存清理：先备份、再移除，可回滚。支持单账户与批量。

安全约束（硬编码，不接受外部路径）：
    * 只在 OneAuth BlobStore 目录内操作
    * 只匹配白名单前缀（该账户的 UPN / objectId / CID）
    * 拒绝符号链接与目录穿越
    * 单账户最多 40 个文件，批量最多 200 个
    * 删除前必须完整备份，备份失败则整体中止
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from .collectors import oneauth
from .util import HOME, human_path

APP_SUPPORT = os.path.join(HOME, "Library/Application Support/EntraBuddy")
BACKUP_ROOT = os.path.join(APP_SUPPORT, "backups")
BLOB_DIR = oneauth.BLOB_DIR
MAX_FILES_PER_ACCOUNT = 40
MAX_FILES_TOTAL = 200


class CleanupError(RuntimeError):
    pass


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
    if not os.path.isdir(BLOB_DIR):
        raise CleanupError("OneAuth 目录不存在，无需清理")

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
                "display_path": human_path(path),
                "size": size,
                "reason": _reason(name),
                "upn": account["upn"],
            }
        )
    return found


def plan_many(upns: List[str]) -> Dict[str, Any]:
    """生成清理计划（不落盘、不删除）。"""
    accounts = _resolve_accounts(upns)

    files: List[Dict[str, Any]] = []
    seen: set[str] = set()
    per_account: List[Dict[str, Any]] = []

    for account in accounts:
        own = [f for f in _files_for(account) if f["name"] not in seen]
        if len(own) > MAX_FILES_PER_ACCOUNT:
            raise CleanupError(
                f"{account['upn']} 待清理文件过多（{len(own)}），已中止"
            )
        for item in own:
            seen.add(item["name"])
            files.append(item)
        per_account.append(
            {
                "upn": account["upn"],
                "provider": account["provider"],
                "object_id": account["object_id"],
                "tenant_id": account["tenant_id"],
                "tenant_name": account.get("tenant_name"),
                "file_count": len(own),
                "bytes": sum(f["size"] for f in own),
            }
        )

    if len(files) > MAX_FILES_TOTAL:
        raise CleanupError(f"待清理文件过多（{len(files)}），已中止")

    return {
        "accounts": per_account,
        "account": per_account[0] if len(per_account) == 1 else None,
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "root": human_path(BLOB_DIR),
        "warnings": [
            "清理前请退出 Word / Excel / PowerPoint / OneNote，否则身份缓存会被重新写入。",
            "Edge 配置文件、OneDrive 同步状态不在本次清理范围内，需要各自在应用内退出登录。",
            "清理只移除本地缓存，不会吊销任何令牌，也不会影响云端账户。",
        ],
    }


def plan(upn: str) -> Dict[str, Any]:
    return plan_many([upn])


def execute_many(upns: List[str], expect_files: Optional[int] = None) -> Dict[str, Any]:
    """备份后删除。多个账户共用一份备份，可整体回滚。"""
    current = plan_many(upns)
    if expect_files is not None and expect_files != current["file_count"]:
        raise CleanupError("文件清单已变化，请重新生成计划")

    if not current["files"]:
        return {
            "ok": True,
            "removed": 0,
            "backup": None,
            "accounts": current["accounts"],
            "message": "没有需要清理的缓存文件",
        }

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if len(current["accounts"]) == 1:
        slug = current["accounts"][0]["upn"].replace("@", "_at_").replace("/", "_")
    else:
        slug = f"batch{len(current['accounts'])}"
    backup_dir = os.path.join(BACKUP_ROOT, f"{stamp}_{slug}")
    files_dir = os.path.join(backup_dir, "files")
    os.makedirs(files_dir, exist_ok=True)

    # 1) 备份：任何一个文件失败都整体中止
    try:
        for item in current["files"]:
            dest = os.path.join(files_dir, item["name"])
            shutil.copy2(item["path"], dest)
            if os.path.getsize(dest) != item["size"]:
                raise CleanupError(f"备份校验失败：{item['name']}")
    except Exception as exc:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise CleanupError(f"备份失败，已中止清理：{exc}") from exc

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "accounts": [
            {"upn": a["upn"], "object_id": a["object_id"], "tenant_id": a["tenant_id"]}
            for a in current["accounts"]
        ],
        "root": BLOB_DIR,
        "files": [
            {
                "name": f["name"],
                "size": f["size"],
                "reason": f["reason"],
                "upn": f["upn"],
            }
            for f in current["files"]
        ],
    }
    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # 2) 删除
    removed = 0
    failed: List[str] = []
    for item in current["files"]:
        try:
            os.remove(item["path"])
            removed += 1
        except OSError:
            failed.append(item["name"])

    label = (
        current["accounts"][0]["upn"]
        if len(current["accounts"]) == 1
        else f"{len(current['accounts'])} 个账户"
    )
    return {
        "ok": not failed,
        "removed": removed,
        "failed": failed,
        "backup": backup_dir,
        "backup_display": human_path(backup_dir),
        "accounts": current["accounts"],
        "message": f"已备份并移除 {label} 的 {removed} 个缓存文件",
    }


def execute(upn: str, expect_files: Optional[int] = None) -> Dict[str, Any]:
    return execute_many([upn], expect_files=expect_files)


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
                "account_count": len(accounts) if accounts else 1,
            }
        )
    return items


def restore(backup_id: str) -> Dict[str, Any]:
    """把备份目录里的文件复制回原位置。"""
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

    restored = 0
    for item in manifest.get("files") or []:
        src = os.path.join(backup_dir, "files", item["name"])
        if not os.path.isfile(src):
            continue
        dst = _safe_join(root, item["name"])
        shutil.copy2(src, dst)
        restored += 1

    return {"ok": True, "restored": restored, "message": f"已恢复 {restored} 个文件"}
