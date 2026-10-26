"""解析 OneAuth 账户库（Office 全家桶共用的身份存储，macOS / Windows 共享）。

OneAuth 是微软的跨平台同一套库，blob 命名与 JSON 结构完全一致：

    <accountId>_graph_organization      Graph /organization，含租户显示名
    <accountId>_substrate_profile       MSA 个人资料，含 passportMemberName
    <accountId>_avatar                  MSA 头像二进制
    <UPN>_identity_provider             内容为 OrgId / MSAccount
    <domain 或 tenantId>_hrd            主域发现，含 environment / tenantId

仅根目录不同：
    macOS    ~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/
    Windows  %LOCALAPPDATA%\\Microsoft\\OneAuth\\blobs\\（旧版布局为 BlobStore）

accountId 的语义：
    * MSA 账户   -> cid（16 位 hex，与 Edge 账户、OneDrive cid 一致）
    * OrgId 账户 -> 用户在租户内的 objectId（GUID），不是 tenantId
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from ..util import HOME, LOCALAPPDATA, iso, mtime, read_json, read_text

if os.name == "nt":
    _ONEAUTH_ROOT = os.path.join(LOCALAPPDATA, "Microsoft", "OneAuth")
    # Windows 实际目录是小写 blobs；保留 BlobStore 兼容旧版布局
    _BLOB_CANDIDATES = ("blobs", "BlobStore")
    BLOB_DIR = next(
        (
            os.path.join(_ONEAUTH_ROOT, name)
            for name in _BLOB_CANDIDATES
            if os.path.isdir(os.path.join(_ONEAUTH_ROOT, name))
        ),
        os.path.join(_ONEAUTH_ROOT, _BLOB_CANDIDATES[0]),
    )
else:
    BLOB_DIR = os.path.join(
        HOME, "Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore"
    )

GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
CID_RE = re.compile(r"^[0-9a-f]{16}$", re.I)
UPN_RE = re.compile(r"^[^@\s]+@[^@\s]+$")

SUFFIXES = (
    "_graph_organization_metadata",
    "_graph_organization",
    "_substrate_profile_metadata",
    "_substrate_profile",
    "_avatar_metadata",
    "_avatar",
    "_identity_provider",
    "_hrd_metadata",
    "_hrd",
)


def _split(filename: str) -> Optional[tuple[str, str]]:
    for suffix in SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)], suffix[1:]
    return None


def _env_label(environment: Optional[str], authority_host: Optional[str]) -> str:
    env = (environment or "").strip().lower()
    host = (authority_host or "").lower()
    if env == "china" or "chinacloudapi" in host or "microsoftonline.cn" in host:
        return "china"
    return "global"


def collect() -> Dict[str, Any]:
    """返回原始解析结果，不做账户合并。"""
    result: Dict[str, Any] = {
        "available": os.path.isdir(BLOB_DIR),
        "dir": BLOB_DIR,
        "identities": [],   # UPN 级身份（最可靠）
        "org_blobs": [],    # 带 graph_organization 的账户
        "msa_blobs": [],    # 带 substrate_profile 的账户
        "hrds": {},         # 域/租户 -> 主域发现结果
        "file_count": 0,
    }
    if not result["available"]:
        return result

    try:
        files = sorted(os.listdir(BLOB_DIR))
    except OSError:
        return result

    result["file_count"] = len(files)

    for name in files:
        parts = _split(name)
        if not parts:
            continue
        key, kind = parts
        path = os.path.join(BLOB_DIR, name)
        ts = mtime(path)

        if kind == "identity_provider":
            provider = (read_text(path) or "").strip()
            if provider in ("OrgId", "MSAccount") and UPN_RE.match(key):
                result["identities"].append(
                    {
                        "upn": key,
                        "provider": provider,
                        "last_seen": iso(ts),
                        "ts": ts,
                        "source": path,
                    }
                )

        elif kind == "graph_organization":
            data = read_json(path) or {}
            values = data.get("value") or []
            display = values[0].get("displayName") if values else None
            if GUID_RE.match(key) or CID_RE.match(key):
                result["org_blobs"].append(
                    {
                        "account_id": key,
                        "tenant_name": display,
                        "last_seen": iso(ts),
                        "ts": ts,
                        "source": path,
                    }
                )

        elif kind == "substrate_profile":
            data = read_json(path) or {}
            accounts = data.get("accounts") or []
            if accounts:
                first = accounts[0]
                result["msa_blobs"].append(
                    {
                        "account_id": key,
                        "upn": first.get("passportMemberName")
                        or first.get("userPrincipalName"),
                        "location": first.get("location"),
                        "last_seen": iso(ts),
                        "ts": ts,
                        "source": path,
                    }
                )

        elif kind == "hrd":
            data = read_json(path) or {}
            if not isinstance(data, dict):
                continue
            result["hrds"][key.lower()] = {
                "key": key,
                "tenant_id": data.get("tenantId"),
                "environment": _env_label(
                    data.get("environment"), data.get("authority_host")
                ),
                "raw_environment": data.get("environment"),
                "authority_host": data.get("authority_host"),
                "graph": data.get("graph"),
                "last_seen": iso(ts),
                "ts": ts,
                "source": path,
            }

    return result


def resolve_tenant(hrds: Dict[str, Any], upn: str) -> Optional[Dict[str, Any]]:
    """用 UPN 的域名去查主域发现结果。"""
    if "@" not in upn:
        return None
    domain = upn.rsplit("@", 1)[1].lower()
    hrd = hrds.get(domain)
    if hrd:
        return hrd
    # 企业自定义域未命中时，退回到租户初始域
    if not domain.endswith(".onmicrosoft.com"):
        alt = domain.split(".")[0] + ".onmicrosoft.com"
        if alt in hrds:
            return hrds[alt]
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def name_score(tenant_name: Optional[str], domain: str) -> int:
    """租户显示名与邮箱域名的相似度，0-100。

    这是比时间戳可靠得多的信号：
        contoso        vs contoso.onmicrosoft.com  -> 80
        Fabrikam Inc   vs fabrikam.com             -> 70
        Contoso Ltd    vs contoso.cn               -> 80
    """
    a = _normalize(tenant_name or "")
    b = _normalize(domain)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a in b or b in a:
        return 80
    first = _normalize(domain.split(".")[0])
    if first and (first in a or a in first):
        return 70
    return 0


def link_org_accounts(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 OrgId 的 UPN 和它的 objectId 配对。

    OneAuth 没有直接存 UPN -> objectId 的映射表。这里用「租户显示名 ↔ 邮箱域名」
    做主判据，时间邻近只作为平局时的次级依据，并输出置信度供 UI 展示。
    """
    org_identities = [i for i in raw["identities"] if i["provider"] == "OrgId"]
    msa_ids = {b["account_id"] for b in raw["msa_blobs"]}
    pool = [b for b in raw["org_blobs"] if b["account_id"] not in msa_ids]

    scored = []
    for identity in org_identities:
        domain = identity["upn"].rsplit("@", 1)[-1]
        for blob in pool:
            score = name_score(blob.get("tenant_name"), domain)
            delta = abs((identity.get("ts") or 0) - (blob.get("ts") or 0))
            scored.append((-score, delta, identity["upn"], blob["account_id"], score))

    scored.sort(key=lambda x: (x[0], x[1]))

    used_upns: set[str] = set()
    used_blobs: set[str] = set()
    assignment: Dict[str, Dict[str, Any]] = {}

    for _neg, delta, upn, blob_id, score in scored:
        if upn in used_upns or blob_id in used_blobs:
            continue
        used_upns.add(upn)
        used_blobs.add(blob_id)
        blob = next(b for b in pool if b["account_id"] == blob_id)
        if score >= 70:
            confidence = "high"
        elif score > 0:
            confidence = "medium"
        else:
            confidence = "low"
        assignment[upn] = {
            "object_id": blob_id,
            "tenant_name": blob.get("tenant_name"),
            "org_seen": blob.get("last_seen"),
            "delta_seconds": delta,
            "match_score": score,
            "confidence": confidence,
        }

    linked: List[Dict[str, Any]] = []
    for identity in org_identities:
        info = assignment.get(identity["upn"], {})
        linked.append({**identity, **info})
    return linked
