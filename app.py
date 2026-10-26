#!/usr/bin/env python3
"""EntraBuddy 本地服务：扫描 API + 清理 / 快照 / 设备接口 + Web GUI。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict

from entrabuddy import cleanup, demo, snapshots
from entrabuddy.scan import scan

# PyInstaller 打包后资源解压到 sys._MEIPASS（Windows 单文件 exe 用）
if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(ROOT, "web")

# 写操作必须带这个头：浏览器跨站请求无法自定义头（会触发预检，而本服务不响应预检）
GUARD_HEADER = "X-EntraBuddy"

# 演示模式：返回虚构数据，禁止一切写操作
DEMO_MODE = False


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Handler(SimpleHTTPRequestHandler):
    server_version = "EntraBuddy/0.2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    # ---------- 响应工具 ----------

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError(f"请求体不是合法 JSON：{exc}") from exc

    def _guard(self) -> None:
        if self.headers.get(GUARD_HEADER) != "1":
            raise ApiError("缺少请求标识，已拒绝", status=403)

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?")[0]
        try:
            if route == "/api/scan":
                if DEMO_MODE:
                    self._json(demo.get())
                    return
                result = scan()
                result["changes"] = snapshots.changes(result)
                result["snapshot_saved"] = snapshots.save(result)
                self._json(result)
                return
            if route == "/api/snapshots":
                self._json({"snapshots": snapshots.list_all()})
                return
            if route == "/api/backups":
                self._json({"backups": cleanup.list_backups()})
                return
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
            return
        except Exception as exc:  # pragma: no cover
            self._json({"error": str(exc), "type": type(exc).__name__}, 500)
            return

        if route == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?")[0]
        handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "/api/cleanup/plan": self._cleanup_plan,
            "/api/cleanup/run": self._cleanup_run,
            "/api/cleanup/batch-plan": self._cleanup_batch_plan,
            "/api/cleanup/batch-run": self._cleanup_batch_run,
            "/api/cleanup/restore": self._cleanup_restore,
            "/api/snapshot": self._snapshot,
        }
        try:
            self._guard()
            if DEMO_MODE:
                raise ApiError("演示模式为只读，写操作已禁用", status=403)
            handler = handlers.get(route)
            if not handler:
                raise ApiError("未知接口", status=404)
            self._json(handler(self._read_json()))
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except cleanup.CleanupError as exc:
            self._json({"error": str(exc)}, 409)
        except Exception as exc:  # pragma: no cover
            self._json({"error": str(exc), "type": type(exc).__name__}, 500)

    # ---------- 接口实现 ----------

    @staticmethod
    def _apps_from(body: Dict[str, Any]) -> Any:
        """读取清理范围参数；未提供则用后端默认（identity），非法值交给 cleanup 报错。"""
        apps = body.get("apps")
        return apps if isinstance(apps, list) else None

    def _cleanup_plan(self, body: Dict[str, Any]) -> Dict[str, Any]:
        upn = (body.get("upn") or "").strip()
        if not upn:
            raise ApiError("缺少 upn")
        return cleanup.plan(upn, apps=self._apps_from(body))

    def _cleanup_run(self, body: Dict[str, Any]) -> Dict[str, Any]:
        upn = (body.get("upn") or "").strip()
        if not upn:
            raise ApiError("缺少 upn")
        if body.get("confirm") != "yes":
            raise ApiError("未确认，已中止")
        expected = body.get("expected")
        return cleanup.execute(
            upn,
            expect_files=expected if isinstance(expected, int) else None,
            apps=self._apps_from(body),
        )

    def _cleanup_batch_plan(self, body: Dict[str, Any]) -> Dict[str, Any]:
        upns = body.get("upns") or []
        if not isinstance(upns, list) or not upns:
            raise ApiError("缺少 upns")
        if len(upns) > 20:
            raise ApiError("一次最多处理 20 个账户")
        return cleanup.plan_many([str(u) for u in upns], apps=self._apps_from(body))

    def _cleanup_batch_run(self, body: Dict[str, Any]) -> Dict[str, Any]:
        upns = body.get("upns") or []
        if not isinstance(upns, list) or not upns:
            raise ApiError("缺少 upns")
        if body.get("confirm") != "yes":
            raise ApiError("未确认，已中止")
        expected = body.get("expected")
        return cleanup.execute_many(
            [str(u) for u in upns],
            expect_files=expected if isinstance(expected, int) else None,
            apps=self._apps_from(body),
        )

    def _cleanup_restore(self, body: Dict[str, Any]) -> Dict[str, Any]:
        backup_id = (body.get("id") or "").strip()
        if not backup_id:
            raise ApiError("缺少备份 ID")
        return cleanup.restore(backup_id)

    def _snapshot(self, _body: Dict[str, Any]) -> Dict[str, Any]:
        result = scan()
        saved = snapshots.save(result, force=True)
        return {"saved": saved, "snapshots": snapshots.list_all()}

    # ---------- 日志 ----------

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("ENTRABUDDY_DEBUG"):
            sys.stderr.write("[http] %s\n" % (fmt % args))
            sys.stderr.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="EntraBuddy - 微软账户管家（macOS / Windows）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--demo", action="store_true", help="用虚构账户渲染界面，写操作全部禁用"
    )
    args = parser.parse_args()

    global DEMO_MODE
    DEMO_MODE = args.demo

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"EntraBuddy 已启动：{url}")
    print("按 Ctrl+C 停止。")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
