"""
Browser - Playwright 浏览器管理器

返回原生 Playwright 对象，Agent 可使用完整 Playwright API。
详细文档: .claude/skills/pentest/browser/SKILL.md
"""
from typing import Annotated, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from core import tool, toolset, namespace

namespace()

@toolset()
class Browser:
    """
    Playwright 浏览器管理器。

    作为浏览器实例的单例管理器，返回原生 Playwright 对象。
    Agent 获取对象后可使用完整 Playwright API。

    推荐用法:
        # 快速获取页面
        page = await toolset.browser.get_page()
        await page.goto("http://target")

        # 获取浏览器实例后使用原生 API
        browser = await toolset.browser.get_browser()
        context = await browser.new_context()
        page = await context.new_page()
    """

    def __init__(self, cdp_url: Optional[str] = None, headless: bool = False):
        """
        初始化浏览器管理器。

        Args:
            cdp_url: 可选的 CDP 连接 URL（连接外部浏览器）
            headless: 是否无头模式（不连接外部浏览器时生效）
        """
        self.cdp_url = cdp_url
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None

    @tool()
    async def get_browser(self) -> Annotated[Browser, "Playwright Browser 实例"]:
        """
        获取浏览器实例（单例模式）。

        返回原生 Playwright Browser 对象，可使用完整 Browser API。
        首次调用会启动浏览器，后续调用返回同一实例。

        Returns:
            Playwright Browser 实例
        """
        if not self._browser:
            self._playwright = await async_playwright().start()

            if self.cdp_url:
                # 连接外部浏览器 (CDP)
                self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            else:
                # 启动新浏览器
                self._browser = await self._playwright.chromium.launch(headless=self.headless)

        return self._browser

    @tool()
    async def get_context(self) -> Annotated[BrowserContext, "Playwright BrowserContext"]:
        """
        获取浏览器上下文。

        返回原生 Playwright BrowserContext 对象。
        如果没有上下文则自动创建。

        Returns:
            Playwright BrowserContext 实例
        """
        browser = await self.get_browser()
        contexts = browser.contexts
        return contexts[0] if contexts else await browser.new_context()

    @tool()
    async def get_page(self) -> Annotated[Page, "Playwright Page 实例"]:
        """
        获取页面实例（推荐方法）。

        这是最常用的快捷方法，自动处理：
        1. 获取/创建浏览器实例
        2. 获取/创建上下文
        3. 获取/创建页面

        返回原生 Playwright Page 对象，可使用完整 Page API。

        Returns:
            Playwright Page 实例

        Example:
            page = await toolset.browser.get_page()
            await page.goto("http://target")
            content = await page.content()
        """
        context = await self.get_context()
        return context.pages[0] if context.pages else await context.new_page()

    @tool()
    async def new_context(self, **kwargs) -> Annotated[BrowserContext, "新的 BrowserContext"]:
        """
        创建新的浏览器上下文。

        用于隔离会话（如不同登录状态）。

        Args:
            **kwargs: 传递给 browser.new_context() 的参数
                - viewport: {"width": 1280, "height": 720}
                - user_agent: 自定义 UA
                - locale: 语言设置
                - etc.

        Returns:
            新的 BrowserContext 实例
        """
        browser = await self.get_browser()
        return await browser.new_context(**kwargs)

    @tool()
    async def close(self):
        """
        关闭浏览器。

        通常不需要手动调用，浏览器实例会复用。
        仅在需要完全重置时使用。
        """
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None