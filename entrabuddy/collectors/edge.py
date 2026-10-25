"""解析 Microsoft Edge 的配置文件与登录账户。"""

from __future__ import annotations

import glob
import os
from typing import Any, Dict, List

from ..util import HOME, read_json

EDGE_ROOT = os.path.join(HOME, "Library/Application Support/Microsoft Edge")
APP_PATH = "/Applications/Microsoft Edge.app"


def collect() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "installed": os.path.isdir(APP_PATH),
        "available": os.path.isdir(EDGE_ROOT),
        "profiles": [],
    }
    if not result["available"]:
        return result

    local_state = read_json(os.path.join(EDGE_ROOT, "Local State")) or {}
    info_cache = ((local_state.get("profile") or {}).get("info_cache")) or {}

    pref_paths = [os.path.join(EDGE_ROOT, "Default", "Preferences")]
    pref_paths += sorted(glob.glob(os.path.join(EDGE_ROOT, "Profile *", "Preferences")))

    for pref_path in pref_paths:
        if not os.path.exists(pref_path):
            continue
        dir_name = os.path.basename(os.path.dirname(pref_path))
        prefs = read_json(pref_path) or {}
        cached = info_cache.get(dir_name) or {}
        accounts = prefs.get("account_info") or []

        profile = {
            "dir": dir_name,
            "name": (prefs.get("profile") or {}).get("name") or cached.get("name"),
            "signed_in": bool(accounts),
            "accounts": [],
        }

        if accounts:
            for acc in accounts:
                profile["accounts"].append(
                    {
                        "email": acc.get("email") or cached.get("user_name"),
                        "full_name": acc.get("full_name") or cached.get("gaia_name"),
                        "gaia_id": cached.get("gaia_id"),
                        "hosted_domain": acc.get("hosted_domain"),
                    }
                )
        else:
            # 未登录，但保留 gaia 信息用于交叉比对
            profile["hint_email"] = cached.get("user_name")
            profile["hint_name"] = cached.get("gaia_name")

        result["profiles"].append(profile)

    return result
