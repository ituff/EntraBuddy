"""清理流程的隔离测试：在临时目录里跑完整备份 / 删除 / 恢复（单账户 + 批量）。

运行：python tests/test_cleanup.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entrabuddy import cleanup  # noqa: E402

OBJECT_ID = "aaaaaaaa-1111-4111-8111-111111111111"
UPN = "alice@contoso.com"
OBJECT_ID_2 = "bbbbbbbb-2222-4222-8222-222222222222"
UPN_2 = "bob@fabrikam.com"

FILES = [
    f"{OBJECT_ID}_graph_organization",
    f"{OBJECT_ID}_avatar",
    f"{UPN}_identity_provider",
    f"{OBJECT_ID_2}_graph_organization",
    f"{UPN_2}_identity_provider",
    "someoneelse@example.org_identity_provider",  # 不该被动
    "unrelated.txt",  # 不该被动
]

ACCOUNTS = {
    UPN.lower(): {
        "upn": UPN,
        "provider": "OrgId",
        "object_id": OBJECT_ID,
        "tenant_id": "cccccccc-3333-4333-8333-333333333333",
        "tenant_name": "contoso",
        "prefixes": {UPN.lower(), OBJECT_ID.lower()},
    },
    UPN_2.lower(): {
        "upn": UPN_2,
        "provider": "OrgId",
        "object_id": OBJECT_ID_2,
        "tenant_id": "dddddddd-4444-4444-8444-444444444444",
        "tenant_name": "Fabrikam Inc",
        "prefixes": {UPN_2.lower(), OBJECT_ID_2.lower()},
    },
}


def setup(root: str) -> None:
    for name in FILES:
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write("x" * 32)


def patch(blob_dir: str, backup_root: str) -> None:
    cleanup.BLOB_DIR = blob_dir
    cleanup.BACKUP_ROOT = backup_root
    cleanup._resolve_accounts = lambda upns: [ACCOUNTS[u.lower()] for u in upns]  # type: ignore[assignment]


def test_single() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        blob_dir = os.path.join(tmp, "BlobStore")
        backup_root = os.path.join(tmp, "backups")
        os.makedirs(blob_dir, exist_ok=True)
        setup(blob_dir)
        patch(blob_dir, backup_root)

        plan = cleanup.plan(UPN)
        assert plan["file_count"] == 3, f"计划文件数应为 3，实际 {plan['file_count']}"
        assert plan["total_bytes"] == 96, plan["total_bytes"]
        assert plan["account"]["upn"] == UPN
        print(f"✓ 单账户计划：{plan['file_count']} 个文件，{plan['total_bytes']} 字节")

        try:
            cleanup.execute(UPN, expect_files=99)
        except cleanup.CleanupError as exc:
            print(f"✓ 清单变更保护生效：{exc}")
        else:
            raise AssertionError("清单不一致时应当拒绝执行")

        result = cleanup.execute(UPN, expect_files=3)
        assert result["ok"] and result["removed"] == 3, result
        print(f"✓ 单账户清理：移除 {result['removed']} 个文件")

        remaining = set(os.listdir(blob_dir))
        assert "unrelated.txt" in remaining
        assert "someoneelse@example.org_identity_provider" in remaining
        assert not any(name.startswith(OBJECT_ID) for name in remaining)
        print("✓ 无关文件未被触碰")

        restored = cleanup.restore(os.path.basename(result["backup"]))
        assert restored["restored"] == 3, restored
        assert set(FILES) <= set(os.listdir(blob_dir))
        print(f"✓ 单账户回滚：恢复 {restored['restored']} 个文件")


def test_batch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        blob_dir = os.path.join(tmp, "BlobStore")
        backup_root = os.path.join(tmp, "backups")
        os.makedirs(blob_dir)
        setup(blob_dir)
        patch(blob_dir, backup_root)

        plan = cleanup.plan_many([UPN, UPN_2])
        assert len(plan["accounts"]) == 2, plan["accounts"]
        assert plan["file_count"] == 5, plan["file_count"]
        assert plan["account"] is None, "多账户时不应返回单一 account"
        counts = {a["upn"]: a["file_count"] for a in plan["accounts"]}
        assert counts[UPN] == 3 and counts[UPN_2] == 2, counts
        print(f"✓ 批量计划：2 个账户 / {plan['file_count']} 个文件")

        result = cleanup.execute_many([UPN, UPN_2], expect_files=5)
        assert result["ok"] and result["removed"] == 5, result
        assert len(result["accounts"]) == 2
        print(f"✓ 批量清理：移除 {result['removed']} 个文件，共用 1 份备份")

        backups = cleanup.list_backups()
        assert len(backups) == 1, backups
        assert backups[0]["account"] == "2 个账户", backups[0]["account"]
        assert backups[0]["file_count"] == 5
        print("✓ 备份清单标记为「2 个账户」")

        remaining = set(os.listdir(blob_dir))
        assert "unrelated.txt" in remaining
        assert "someoneelse@example.org_identity_provider" in remaining
        print("✓ 批量清理未误伤无关文件")

        restored = cleanup.restore(backups[0]["id"])
        assert restored["restored"] == 5, restored
        assert set(FILES) <= set(os.listdir(blob_dir))
        print(f"✓ 批量回滚：恢复 {restored['restored']} 个文件")



# ---------- 按范围清理（office / onedrive） ----------

CID = "1234567890abcdef"
LICENSE_NAME = f"{CID}.license"
FAKE_REG_PATH = r"HKCU\Software\Microsoft\OneDrive\Accounts\Business1"
FAKE_REG_VALUES = {"UserEmail": UPN, "cid": CID, "ConfiguredTenantId": "t-1"}

# 可注入的注册表替身
FAKE_REGISTRY = {}


def fake_reg_snapshot(path):
    return FAKE_REGISTRY.get(path)


def fake_reg_delete_key(path):
    FAKE_REGISTRY.pop(path, None)


def fake_reg_restore(path, values):
    FAKE_REGISTRY[path] = dict(values)


def setup_scopes(tmp: str) -> None:
    """identity 文件 + office 许可证文件 + 模拟注册表键。"""
    blob_dir = os.path.join(tmp, "BlobStore")
    os.makedirs(blob_dir, exist_ok=True)
    setup(blob_dir)
    lic_dir = os.path.join(tmp, "licenses")
    os.makedirs(lic_dir, exist_ok=True)
    with open(os.path.join(lic_dir, LICENSE_NAME), "w", encoding="utf-8") as fh:
        fh.write("x" * 64)
    FAKE_REGISTRY.clear()
    FAKE_REGISTRY[FAKE_REG_PATH] = dict(FAKE_REG_VALUES)


def patch_scopes(blob_dir: str, backup_root: str, lic_dir: str) -> None:
    cleanup.BLOB_DIR = blob_dir
    cleanup.BACKUP_ROOT = backup_root
    cleanup._resolve_accounts = lambda upns, **kw: [
        {
            "upn": UPN,
            "provider": "MSAccount",
            "object_id": None,
            "cid": CID,
            "tenant_id": None,
            "tenant_name": None,
            "prefixes": {UPN.lower(), OBJECT_ID.lower()},
        }
    ]
    cleanup.office.LICENSE_ROOTS = [lic_dir]
    cleanup.office.license_paths_for_cid = lambda cid: (
        [os.path.join(lic_dir, LICENSE_NAME)] if cid == CID else []
    )
    cleanup.office.profile_registry_keys = lambda ids: []
    cleanup.onedrive.account_slot_paths = lambda upn: (
        [FAKE_REG_PATH] if upn.lower() == UPN.lower() else []
    )
    cleanup._reg_snapshot = fake_reg_snapshot
    cleanup._reg_delete_key = fake_reg_delete_key
    cleanup._reg_restore = fake_reg_restore


def test_scopes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        blob_dir = os.path.join(tmp, "BlobStore")
        backup_root = os.path.join(tmp, "backups")
        lic_dir = os.path.join(tmp, "licenses")
        setup_scopes(tmp)
        patch_scopes(blob_dir, backup_root, lic_dir)

        # 默认（identity）只见 OneAuth 文件，许可证与注册表不在计划内
        plan = cleanup.plan(UPN)
        assert plan["scopes"] == ["identity"], plan["scopes"]
        assert plan["file_count"] == 3 and plan["registry_count"] == 0, plan["file_count"]

        # office 范围只含许可证文件，不动 OneAuth
        plan = cleanup.plan(UPN, apps=["office"])
        assert plan["scopes"] == ["office"]
        assert plan["file_count"] == 1 and plan["registry_count"] == 0, plan
        assert plan["files"][0]["name"] == LICENSE_NAME

        # onedrive 范围只含注册表键，已带快照
        plan = cleanup.plan(UPN, apps=["onedrive"])
        assert plan["registry_count"] == 1 and plan["file_count"] == 0
        assert plan["registry_keys"][0]["values"] == FAKE_REG_VALUES

        # 组合范围 = 全部三项
        plan = cleanup.plan(UPN, apps=["identity", "office", "onedrive"])
        assert plan["total_count"] == 5, plan["total_count"]
        print("✓ 范围计划：identity/office/onedrive 过滤正确")

        # 非法范围被拒绝
        try:
            cleanup.plan(UPN, apps=["edge"])
        except cleanup.CleanupError as exc:
            print(f"✓ 非法范围被拒绝：{exc}")
        else:
            raise AssertionError("edge 范围应当被拒绝")

        # 执行组合清理：3 文件 + 1 许可证 + 1 注册表键
        result = cleanup.execute(UPN, expect_files=5, apps=["identity", "office", "onedrive"])
        assert result["ok"] and result["removed"] == 4, result
        assert result["deleted_keys"] == 1, result
        assert LICENSE_NAME not in os.listdir(lic_dir)
        assert FAKE_REG_PATH not in FAKE_REGISTRY
        print("✓ 组合清理：4 个文件 + 1 个注册表键全部移除")

        # 回滚：文件与注册表都恢复
        restored = cleanup.restore(os.path.basename(result["backup"]))
        assert restored["restored"] == 5, restored
        assert os.path.isfile(os.path.join(lic_dir, LICENSE_NAME))
        assert FAKE_REGISTRY[FAKE_REG_PATH] == FAKE_REG_VALUES
        print("✓ 回滚：许可证文件与注册表键均已恢复")

        # office 单独清理不碰 OneAuth 文件
        FAKE_REGISTRY.clear()
        setup_scopes(tmp)
        patch_scopes(blob_dir, backup_root, lic_dir)
        result = cleanup.execute(UPN, expect_files=1, apps=["office"])
        assert result["removed"] == 1 and result["deleted_keys"] == 0
        assert "unrelated.txt" in os.listdir(blob_dir)
        print("✓ 仅 office：OneAuth 缓存与 OneDrive 均未受影响")


def main() -> int:
    test_single()
    print()
    test_batch()
    print()
    test_scopes()
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
