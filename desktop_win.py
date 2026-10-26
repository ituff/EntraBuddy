#!/usr/bin/env python3
"""EntraBuddy 桌面壳（Windows）：pywebview + WebView2，内嵌启动本地服务。

macOS 版用 PyObjC + WKWebView（见 desktop_mac.py）；Windows 对应的原生
WebView 是 WebView2，pywebview 会优先走 EdgeChromium 后端（Win10/11 自带
WebView2 运行时）。未安装 pywebview 时自动退回浏览器模式。
"""

from __future__ import annotations

import os
import socket
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from http.server import ThreadingHTTPServer  # noqa: E402

from app import Handler  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    port = free_port()
    server = start_server(port)
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        server.shutdown()
        sys.stderr.write(
            "缺少 pywebview，无法打开原生窗口。请安装：\n"
            "  pip install pywebview\n"
            "或直接运行 python app.py（浏览器模式）。\n"
        )
        raise SystemExit(1)

    try:
        webview.create_window(
            "EntraBuddy",
            url,
            width=1320,
            height=900,
            min_size=(900, 640),
        )
        webview.start()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
