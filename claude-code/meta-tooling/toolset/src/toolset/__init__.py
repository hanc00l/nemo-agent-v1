"""
Toolset - AI Agent 工具集 (运行时库)

详细文档见: .claude/skills/pentest/*/SKILL.md

工具列表:
- browser: Playwright 浏览器自动化 → skills/pentest/browser/SKILL.md
- terminal: tmux 终端会话 → skills/pentest/terminal/SKILL.md
- note: 笔记持久化 → skills/pentest/note/SKILL.md
- competition: 竞赛平台 API → skills/pentest/competition/SKILL.md
"""
import os
from core import namespace

namespace()

from .terminal import Terminal
from .browser import Browser
from .note import Note
from .competition import Competition

terminal = Terminal()
browser = Browser(cdp_url=os.getenv("BROWSER_PORT") and f'http://localhost:{os.getenv("BROWSER_PORT")}',
                  headless=os.getenv("BROWSER_HEADLESS", "false").lower() == "true")
note = Note()
competition = Competition()

__all__ = ['terminal', 'browser', 'note', 'competition']
