"""
浏览器调试服务

提供 Playwright 浏览器自动化调试能力。
"""

import argparse
import time
import os
from playwright.sync_api import sync_playwright

# ============== 常量配置 ==============

# 常见浏览器可执行文件路径（按优先级排序）
BROWSER_PATHS = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/home/ubuntu/.cache/ms-playwright/chrome-linux64/chrome",  # ubuntu vm
    "/home/ubuntu/.cache/ms-playwright/chromium-1187/chrome-linux/chrome", # docker里安装的
]


def _find_browser_path() -> str:
    """
    自动搜索浏览器可执行文件路径

    按优先级顺序检查常见路径，如果都找不到，返回 None，
    Playwright 将使用自带的 Chromium。

    Returns:
        str | None: 浏览器路径，如果找不到返回 None
    """
    for path in BROWSER_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def start_browser_service(port: int) -> None:
    """
    启动浏览器调试服务

    Args:
        port: 远程调试端口
    """
    with sync_playwright() as p:
        headless = bool(os.getenv('NO_VISION'))

        # 构建启动参数
        launch_args = [
            f'--remote-debugging-port={port}',
            "--no-sandbox",
            "--disable-dev-shm-usage"
        ]

        # 自动搜索浏览器路径
        browser_path = _find_browser_path()
        launch_options = {
            "headless": headless,
            "args": launch_args
        }

        # 如果找到系统浏览器，使用系统浏览器。否则使用 Playwright 自带的 Chromium
        if browser_path:
            launch_options["executable_path"] = browser_path
            print(f"使用系统浏览器: {browser_path}")
        else:
            print("使用 Playwright 自带的 Chromium")

        browser = p.chromium.launch(**launch_options)
        print(f"浏览器服务已在端口 {port} 启动")
        print(f"浏览器路径: {browser_path or 'Playwright Chromium'}")
        contexts = browser.contexts
        if contexts:
            contexts[0].new_page()
        else:
            ctx = browser.new_context()
            ctx.new_page()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("正在停止浏览器服务...")
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="浏览器调试服务")
    parser.add_argument("--port", type=int, default=9222, help="调试端口")
    args = parser.parse_args()
    start_browser_service(port=args.port)