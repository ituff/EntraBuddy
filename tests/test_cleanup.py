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
        os.makedirs(blob_dir)
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


def main() -> int:
    test_single()
    print()
    test_batch()
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
