"""
Playwright 浏览器管理器。

返回原生 Playwright 对象（Page、BrowserContext、Browser）。
Agent 获取对象后可使用完整 Playwright Python SDK API。

运行 help(toolset.browser) 查看使用说明。
详细文档: .claude/skills/pentest/browser/SKILL.md
"""
from core import namespace

namespace()

import os
from .browser import Browser

# 优先使用 CDP 连接外部浏览器，否则本地启动
cdp_url = os.getenv("BROWSER_PORT") and f'http://localhost:{os.getenv("BROWSER_PORT")}'
headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"

browser = Browser(cdp_url=cdp_url, headless=headless)

__all__ = ['browser']