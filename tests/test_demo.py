"""演示模式隔离测试：DEMO_MODE 下任何接口都不得触碰本机真实快照 / 备份。

运行：python tests/test_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
from entrabuddy import demo  # noqa: E402

# 「真实」标记：若任何演示接口的响应中出现它，即为本机数据泄漏
REAL_UPN = "real.user@contoso.example"
REAL_TENANT = "99999999-real-real-real-999999999999"


def plant(root: str) -> None:
    """在临时目录里伪造本机已有的真实快照与备份。"""
    snap_dir = os.path.join(root, "snapshots")
    os.makedirs(snap_dir)
    with open(os.path.join(snap_dir, "20990101-000000.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "id": "20990101-000000",
                "saved_at": "2099-01-01T00:00:00",
                "signature": "real",
                "summary": {"total": 1},
                "accounts": [{"upn": REAL_UPN, "tenant_id": REAL_TENANT}],
            },
            fh,
            ensure_ascii=False,
        )

    backup_dir = os.path.join(root, "backups", "20990101-000001")
    os.makedirs(backup_dir)
    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "created_at": "2099-01-01T00:00:01",
                "accounts": [{"upn": REAL_UPN}],
                "files": [{"path": f"{REAL_UPN}_identity_provider"}],
            },
            fh,
            ensure_ascii=False,
        )


def patch(root: str) -> None:
    app.snapshots.SNAPSHOT_DIR = os.path.join(root, "snapshots")
    app.cleanup.BACKUP_ROOT = os.path.join(root, "backups")


def start_server():
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def get(url: str) -> str:
    with urllib.request.urlopen(url) as res:
        return res.read().decode("utf-8")


def assert_no_real_data(text: str, where: str) -> None:
    for marker in (REAL_UPN, REAL_TENANT, "20990101"):
        assert marker not in text, f"{where} 泄漏了本机数据：{marker}"
    print(f"✓ {where}：演示模式下不含本机真实数据")


def test_demo_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plant(tmp)
        patch(tmp)

        # 正常模式：真实数据应可见（验证测试夹具本身有效）
        app.DEMO_MODE = False
        server, base = start_server()
        try:
            assert "20990101-000000" in get(f"{base}/api/snapshots"), "正常模式下应返回真实快照"
            assert REAL_UPN in get(f"{base}/api/backups"), "正常模式下应返回真实备份"
            print("✓ 正常模式：真实快照 / 备份照常返回")

            # 演示模式：两个接口都必须是虚构数据
            app.DEMO_MODE = True
            assert_no_real_data(get(f"{base}/api/snapshots"), "/api/snapshots")
            assert_no_real_data(get(f"{base}/api/backups"), "/api/backups")

            assert demo.snapshots()[0]["id"] in get(f"{base}/api/snapshots"), "演示快照应为虚构内容"
            assert json.loads(get(f"{base}/api/backups"))["backups"] == demo.backups(), (
                "演示备份应与虚构数据完全一致"
            )

            # 演示模式下写操作保持禁用
            req = urllib.request.Request(
                f"{base}/api/cleanup/restore",
                data=json.dumps({"id": "20990101-000001"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-EntraBuddy": "1"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req)
            except urllib.error.HTTPError as exc:
                assert exc.code == 403, exc.code
                assert "只读" in exc.read().decode("utf-8")
                print("✓ 演示模式：写操作仍被拒绝（403）")
            else:
                raise AssertionError("演示模式下 restore 不应成功")
        finally:
            app.DEMO_MODE = False
            server.shutdown()
            server.server_close()


def test_payload_consistency() -> None:
    """payload() 内嵌的快照列表应与 /api/snapshots 返回同一份虚构数据。"""
    assert demo.payload()["changes"]["snapshots"] == demo.snapshots()
    for item in demo.snapshots() + demo.backups():
        assert isinstance(item["id"], str) and item["id"]
    accounts = {a["upn"] for a in demo.get()["accounts"]}
    assert demo.backups()[0]["account"] in accounts, "演示备份归属应为虚构账户之一"
    print("✓ 演示数据内部一致（快照列表 / 备份归属账户均为虚构）")


def main() -> int:
    test_payload_consistency()
    print()
    test_demo_isolation()
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
