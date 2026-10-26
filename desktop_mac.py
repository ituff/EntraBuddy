#!/usr/bin/env python3
"""EntraBuddy 桌面壳：PyObjC + WKWebView，内嵌启动本地服务。

不依赖 pywebview，只需要 pyobjc-framework-Cocoa / WebKit。
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
    try:
        import objc
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyRegular,
            NSBackingStoreBuffered,
            NSMenu,
            NSMenuItem,
            NSWindow,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable,
            NSWindowStyleMaskResizable,
            NSWindowStyleMaskTitled,
        )
        from Foundation import NSMakeRect, NSURL, NSURLRequest
        from WebKit import WKWebView, WKWebViewConfiguration
    except ImportError:
        sys.stderr.write(
            "缺少 PyObjC。请安装：\n"
            "  pip install pyobjc-framework-Cocoa pyobjc-framework-WebKit\n"
        )
        raise SystemExit(1)

    port = free_port()
    server = start_server(port)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    style = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskMiniaturizable
        | NSWindowStyleMaskResizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 1320, 900), style, NSBackingStoreBuffered, False
    )
    window.setTitle_("EntraBuddy")
    window.setMinSize_((900, 640))
    window.center()
    window.setFrameAutosaveName_("EntraBuddyMainWindow")

    config = WKWebViewConfiguration.alloc().init()
    webview = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 1320, 900), config)
    webview.setAutoresizingMask_(18)  # width | height
    window.setContentView_(webview)

    url = NSURL.URLWithString_(f"http://127.0.0.1:{port}/")
    webview.loadRequest_(NSURLRequest.requestWithURL_(url))

    # 菜单栏
    main_menu = NSMenu.alloc().init()

    app_item = NSMenuItem.alloc().init()
    main_menu.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    app_menu.addItem_(
        NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("关于 EntraBuddy", None, "")
    )
    app_menu.addItem_(NSMenuItem.separatorItem())
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "退出 EntraBuddy", "terminate:", "q"
    )
    app_menu.addItem_(quit_item)
    app_item.setSubmenu_(app_menu)

    edit_item = NSMenuItem.alloc().init()
    main_menu.addItem_(edit_item)
    edit_menu = NSMenu.alloc().initWithTitle_("编辑")
    edit_menu.addItem_(
        NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("复制", "copy:", "c")
    )
    edit_menu.addItem_(
        NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("全选", "selectAll:", "a")
    )
    edit_item.setSubmenu_(edit_menu)

    app.setMainMenu_(main_menu)

    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    try:
        app.run()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
