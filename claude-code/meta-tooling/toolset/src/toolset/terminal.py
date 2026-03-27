"""
Terminal - tmux 终端会话管理

详细文档: .claude/skills/pentest/terminal/SKILL.md
"""
import subprocess
import psutil
import os
import time
from typing import Annotated, Optional
import libtmux
from core import tool, toolset, namespace

namespace()

@toolset()
class Terminal:
    """tmux 终端会话管理。详见 skills/pentest/terminal/SKILL.md"""

    def __init__(self):
        self.server = libtmux.Server()

    @tool()
    def list_sessions(self) -> list:
        """列出所有终端会话。"""
        return [s.session_id.replace('$', '') for s in self.server.sessions]

    @tool()
    def kill_session(self, session_id: int):
        """终止指定会话。"""
        sessions = self.server.sessions.filter(session_id=f"${session_id}")
        if sessions:
            sessions[0].kill()

    @tool()
    def new_session(self) -> int:
        """创建新终端会话，返回会话ID。"""
        workspace_dir = os.getenv("WORKSPACE", "/opt/workspace")
        session = self.server.new_session(attach=False, start_directory=workspace_dir)
        session.set_option('status', 'off')
        session_id = session.session_id.replace('$', '')

        if not os.getenv('NO_VISION'):
            xfce4_running = any('xfce4-terminal' in p.name() for p in psutil.process_iter())
            proc = subprocess.Popen(["xfce4-terminal", "--title", f"AI-Terminal-{session_id}",
                                    "--command", f"tmux attach-session -t {session_id}", "--hide-scrollbar"])
            if xfce4_running:
                proc.wait()
            else:
                time.sleep(0.5)
            session.set_option('destroy-unattached', 'on')
        return int(session_id)

    @tool()
    def get_output(
        self,
        session_id: int,
        start: Annotated[Optional[str], "起始行号，负数为历史记录"] = "",
        end: Annotated[Optional[str], "结束行号"] = ""
    ) -> str:
        """获取终端会话的输出内容。"""
        sessions = self.server.sessions.filter(session_id=f"${session_id}")
        if not sessions:
            return f"No session: {session_id}. Active: {self.list_sessions()}"
        return '\n'.join(sessions[0].windows[0].panes[0].capture_pane(start, end))

    @tool()
    def send_keys(
        self,
        session_id: int,
        keys: Annotated[str, "输入的文本或按键 (C-c=Ctrl+c, C-[=Esc)"],
        enter: Annotated[bool, "是否按回车"]
    ) -> str:
        """向会话发送按键输入，返回执行后输出。"""
        sessions = self.server.sessions.filter(session_id=f"${session_id}")
        if not sessions:
            return f"No session: {session_id}. Active: {self.list_sessions()}"
        pane = sessions[0].windows[0].panes[0]
        pane.send_keys(keys, enter=enter)
        time.sleep(1)
        return '\n'.join(pane.capture_pane())

