"""快照与变更追踪：保存账户清单，对比出新增 / 消失 / 变化。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

from .util import HOME, human_path

APP_SUPPORT = os.path.join(HOME, "Library/Application Support/EntraBuddy")
SNAPSHOT_DIR = os.path.join(APP_SUPPORT, "snapshots")
MAX_SNAPSHOTS = 60


def _ensure_dir() -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def _essence(account: Dict[str, Any]) -> Dict[str, Any]:
    """只保留对比需要的字段，控制快照体积。"""
    return {
        "upn": account["upn"],
        "kind": account.get("kind"),
        "cloud": account.get("cloud"),
        "tenant_id": account.get("tenant_id"),
        "tenant_name": account.get("tenant_name"),
        "last_seen": (account.get("last_seen") or "")[:10],
        "roles": sorted(
            f"{b['app_id']}:{r}" for b in account.get("apps", []) for r in b.get("roles", [])
        ),
    }


def signature(result: Dict[str, Any]) -> str:
    payload = json.dumps(
        [_essence(a) for a in result.get("accounts", [])],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def save(result: Dict[str, Any], force: bool = False) -> Optional[Dict[str, Any]]:
    """保存快照。内容未变化且非强制时跳过。"""
    _ensure_dir()
    sig = signature(result)

    existing = list_all()
    if existing and not force and existing[0]["signature"] == sig:
        return None

    stamp = time.strftime("%Y%m%d-%H%M%S")
    sid = stamp
    suffix = 1
    while os.path.exists(os.path.join(SNAPSHOT_DIR, f"{sid}.json")):
        suffix += 1
        sid = f"{stamp}-{suffix}"

    payload = {
        "id": sid,
        "saved_at": result.get("generated_at") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "signature": sig,
        "summary": result.get("summary", {}),
        "accounts": [_essence(a) for a in result.get("accounts", [])],
    }
    path = os.path.join(SNAPSHOT_DIR, f"{sid}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    _prune()
    return {"id": sid, "saved_at": payload["saved_at"], "path": human_path(path)}


def _prune() -> None:
    files = sorted(
        (f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")), reverse=True
    )
    for name in files[MAX_SNAPSHOTS:]:
        try:
            os.remove(os.path.join(SNAPSHOT_DIR, name))
        except OSError:
            pass


def list_all() -> List[Dict[str, Any]]:
    if not os.path.isdir(SNAPSHOT_DIR):
        return []
    items: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        path = os.path.join(SNAPSHOT_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        items.append(
            {
                "id": data.get("id") or name[:-5],
                "saved_at": data.get("saved_at"),
                "signature": data.get("signature"),
                "summary": data.get("summary", {}),
                "account_count": len(data.get("accounts") or []),
                "path": human_path(path),
            }
        )
    return items


def load(sid: str) -> Optional[Dict[str, Any]]:
    if not sid or os.sep in sid or ".." in sid:
        return None
    path = os.path.join(SNAPSHOT_DIR, f"{sid}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    old_map = {a["upn"].lower(): a for a in old.get("accounts", [])}
    new_map = {a["upn"].lower(): a for a in new.get("accounts", [])}

    added = [new_map[k] for k in new_map.keys() - old_map.keys()]
    removed = [old_map[k] for k in old_map.keys() - new_map.keys()]

    changed: List[Dict[str, Any]] = []
    for key in old_map.keys() & new_map.keys():
        before, after = old_map[key], new_map[key]
        fields = []
        if before.get("tenant_id") != after.get("tenant_id"):
            fields.append(
                {
                    "field": "租户",
                    "from": before.get("tenant_name") or before.get("tenant_id"),
                    "to": after.get("tenant_name") or after.get("tenant_id"),
                }
            )
        if before.get("cloud") != after.get("cloud"):
            fields.append({"field": "云环境", "from": before.get("cloud"), "to": after.get("cloud")})
        if before.get("roles") != after.get("roles"):
            gained = set(after.get("roles") or []) - set(before.get("roles") or [])
            lost = set(before.get("roles") or []) - set(after.get("roles") or [])
            fields.append(
                {
                    "field": "应用关联",
                    "from": f"{len(before.get('roles') or [])} 项",
                    "to": f"{len(after.get('roles') or [])} 项",
                    "gained": sorted(gained),
                    "lost": sorted(lost),
                }
            )
        if before.get("last_seen") != after.get("last_seen"):
            fields.append(
                {"field": "最后活跃", "from": before.get("last_seen"), "to": after.get("last_seen")}
            )
        if fields:
            changed.append({"upn": after["upn"], "changes": fields})

    return {
        "from": {"id": old.get("id"), "saved_at": old.get("saved_at")},
        "to": {"id": new.get("id"), "saved_at": new.get("saved_at")},
        "added": [
            {"upn": a["upn"], "kind": a.get("kind"), "tenant": a.get("tenant_name")}
            for a in added
        ],
        "removed": [
            {"upn": a["upn"], "kind": a.get("kind"), "tenant": a.get("tenant_name")}
            for a in removed
        ],
        "changed": changed,
        "has_changes": bool(added or removed or changed),
    }


def changes(current: Dict[str, Any]) -> Dict[str, Any]:
    """最近一次快照 vs 当前扫描结果。"""
    items = list_all()
    if not items:
        return {"snapshots": [], "diff": None, "hint": "还没有历史快照，每次扫描会自动记录"}

    latest = load(items[0]["id"])
    if not latest:
        return {"snapshots": items, "diff": None, "hint": "快照读取失败"}

    current_essence = {
        "id": "current",
        "saved_at": current.get("generated_at"),
        "accounts": [_essence(a) for a in current.get("accounts", [])],
    }
    return {"snapshots": items, "diff": diff(latest, current_essence), "hint": None}
