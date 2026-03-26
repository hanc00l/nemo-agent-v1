"""
Python 执行器 MCP 服务

提供基于 Jupyter 内核的 Python 代码执行能力，支持：
- 有状态会话管理（变量、导入跨调用保留）
- 超时控制和内核中断
- Notebook 格式的执行记录
"""

import time
import os
import re
import argparse
from typing import Annotated, Optional
from queue import Empty
import nbformat
from jupyter_client import KernelManager
from nbformat import v4 as nbf
from fastmcp import FastMCP

# ============== 常量配置 ==============

# 内核启动超时（秒）
KERNEL_START_TIMEOUT = 3

# toolset 路径初始化超时（秒）
TOOLSET_INIT_TIMEOUT = 2

# 消息获取超时（秒）
MESSAGE_POLL_TIMEOUT = 0.1

# 内核中断等待时间（秒）
KERNEL_INTERRUPT_WAIT = 1

# session_name 最大长度（防止滥用）
MAX_SESSION_NAME_LENGTH = 256

# 最大并发会话数（防止资源耗尽）
MAX_SESSIONS = 50

# notebook 文件存储目录
NOTEBOOK_PATH = os.getenv("NOTEBOOK_PATH", "") or "/opt/scripts"


class PythonExecutor:
    """
    Python 代码执行器

    管理多个独立的 Jupyter 内核会话，每个会话：
    - 拥有独立的变量命名空间
    - 持久化到独立的 notebook 文件
    - 支持超时中断和恢复
    """

    def __init__(self, path: str = NOTEBOOK_PATH):
        """
        初始化执行器

        Args:
            path: notebook 文件存储目录
        """
        self.path = path
        self.sessions: dict = {}
        os.makedirs(self.path, exist_ok=True)

    def _sanitize_filename(self, name: str) -> str:
        """
        清理文件名，移除危险字符

        Args:
            name: 原始 session_name

        Returns:
            安全的文件名

        Raises:
            ValueError: 名称过长或为空
        """
        if not name:
            raise ValueError("session_name 不能为空")

        if len(name) > MAX_SESSION_NAME_LENGTH:
            raise ValueError(f"session_name 长度不能超过 {MAX_SESSION_NAME_LENGTH} 字符")

        # 仅保留字母、数字、下划线、连字符和点
        sanitized = re.sub(r'[^\w\-.]', '_', name)
        return sanitized

    def _get_unique_filepath(self, session_name: str) -> str:
        """
        获取唯一的 notebook 文件路径

        如果文件已存在，添加数字后缀避免覆盖。

        Args:
            session_name: 会话名称

        Returns:
            唯一的文件路径
        """
        sanitized_name = self._sanitize_filename(session_name)
        base_path = os.path.join(self.path, f"{sanitized_name}.ipynb")
        if not os.path.exists(base_path):
            return base_path

        # 添加数字后缀，最多尝试 1000 次
        for i in range(1, 1001):
            new_path = os.path.join(self.path, f"{sanitized_name}_{i}.ipynb")
            if not os.path.exists(new_path):
                return new_path

        # 理论上不应该到达这里
        raise RuntimeError(f"无法为 session '{session_name}' 创建唯一文件路径")

    def _create_session(self, session_name: str) -> dict:
        """
        创建新的 Jupyter 内核会话

        Args:
            session_name: 会话名称（必须使用 challenge_code）

        Returns:
            会话信息字典

        Raises:
            ValueError: 会话数量超限
            RuntimeError: 内核启动失败
        """
        # 检查会话数量限制
        if len(self.sessions) >= MAX_SESSIONS:
            raise ValueError(f"已达到最大会话数限制 ({MAX_SESSIONS})，请关闭部分会话后重试")

        km = KernelManager(kernel_name='python3')
        client = None

        try:
            # 启动内核
            km.start_kernel()
            client = km.client()
            client.start_channels()
            client.wait_for_ready(timeout=KERNEL_START_TIMEOUT)

        except RuntimeError:
            # 内核启动超时，清理资源
            if client:
                client.stop_channels()
            km.shutdown_kernel(now=True)
            raise RuntimeError(f"内核启动超时（{KERNEL_START_TIMEOUT}秒）")
        except Exception as e:
            # 其他异常，确保资源清理
            if client:
                client.stop_channels()
            km.shutdown_kernel(now=True)
            raise RuntimeError(f"内核启动失败: {repr(e)}")

        # 自动添加 toolset 到 Python 路径
        # 优先使用挂载的 toolset，其次使用相对路径
        toolset_paths = [
            "/opt/toolset",  # 挂载的 toolset (优先)
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'toolset', 'src'
            )
        ]

        toolset_src = None
        for path in toolset_paths:
            if os.path.exists(path):
                toolset_src = path
                break

        if toolset_src:
            code = f"import sys; sys.path.insert(0, r'{toolset_src}')"
            msg_id = client.execute(code)
            # 等待执行完成
            try:
                while True:
                    msg = client.get_shell_msg(timeout=TOOLSET_INIT_TIMEOUT)
                    if msg['parent_header'].get('msg_id') == msg_id:
                        break
            except Empty:
                pass  # 超时不影响后续执行

        # 创建 notebook 文件
        filepath = self._get_unique_filepath(session_name)
        notebook = nbf.new_notebook()

        self.sessions[session_name] = {
            'km': km,
            'client': client,
            'notebook': notebook,
            'filepath': filepath,
            'execution_count': 1
        }
        return self.sessions[session_name]

    def _format_output(self, output_objects: list) -> list[dict]:
        """
        格式化 notebook 输出对象为字典列表

        Args:
            output_objects: nbformat 输出对象列表

        Returns:
            格式化后的字典列表
        """
        formatted_outputs = []
        for out in output_objects:
            output_type = out.output_type
            if output_type == 'stream':
                formatted_outputs.append({
                    "type": "stream",
                    "name": out.name,
                    "text": out.text
                })
            elif output_type == 'execute_result':
                formatted_outputs.append({
                    "type": "execute_result",
                    "data": dict(out.data),
                    "execution_count": out.execution_count
                })
            elif output_type == 'display_data':
                formatted_outputs.append({
                    "type": "display_data",
                    "data": dict(out.data)
                })
            elif output_type == 'error':
                formatted_outputs.append({
                    "type": "error",
                    "ename": out.ename,
                    "evalue": out.evalue,
                    "traceback": out.traceback
                })
        return formatted_outputs

    def list_sessions(self) -> list[str]:
        """返回所有活跃会话的名称列表"""
        return list(self.sessions.keys())

    def _save_notebook(self, notebook, filepath: str) -> None:
        """
        保存 notebook 到文件

        Args:
            notebook: notebook 对象
            filepath: 文件路径
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            nbformat.write(notebook, f)

    def execute_code(self, session_name: str, code: str, timeout: int = 10) -> list[dict]:
        """
        在指定会话中执行 Python 代码

        Args:
            session_name: 会话名称（必须使用 challenge_code）
            code: 要执行的 Python 代码
            timeout: 执行超时时间（秒）

        Returns:
            输出结果列表，每个元素是一个字典，包含 type 和相应数据
        """
        # 自动创建会话（如果不存在）
        if session_name not in self.sessions:
            self._create_session(session_name)

        session = self.sessions[session_name]
        client = session['client']
        km = session['km']
        notebook = session['notebook']
        filepath = session['filepath']
        exec_count = session['execution_count']

        # 创建 notebook 单元格并保存（执行前）
        cell = nbf.new_code_cell(code, execution_count=exec_count)
        cell.outputs = []
        notebook.cells.append(cell)
        self._save_notebook(notebook, filepath)

        # 执行代码
        msg_id = client.execute(code)

        output_objects = []
        start_time = time.time()

        try:
            shell_reply_received = False

            while True:
                elapsed = time.time() - start_time

                # 超时处理：中断内核但保留会话
                if elapsed > timeout:
                    error_msg = f"执行超时（超过 {timeout} 秒），正在尝试中断..."
                    output_objects.append(
                        nbf.new_output('display_data', data={'text/plain': f'[SYSTEM] {error_msg}'})
                    )

                    try:
                        km.interrupt_kernel()
                        time.sleep(KERNEL_INTERRUPT_WAIT)

                        # 清空剩余消息，等待内核进入 idle 状态
                        try:
                            while True:
                                msg = client.get_iopub_msg(timeout=MESSAGE_POLL_TIMEOUT)
                                if msg['parent_header'].get('msg_id') == msg_id:
                                    msg_type = msg['header']['msg_type']
                                    if msg_type == 'status' and msg['content']['execution_state'] == 'idle':
                                        break
                        except Empty:
                            pass

                        interrupt_msg = "内核已中断，会话状态已保留。"
                        output_objects.append(
                            nbf.new_output('display_data', data={'text/plain': f'[SYSTEM] {interrupt_msg}'})
                        )
                    except Exception as e:
                        interrupt_error = f"中断内核失败: {repr(e)}"
                        output_objects.append(
                            nbf.new_output('display_data', data={'text/plain': f'[SYSTEM] {interrupt_error}'})
                        )

                    break

                try:
                    msg = client.get_iopub_msg(timeout=MESSAGE_POLL_TIMEOUT)

                    # 忽略非当前执行的消息
                    if msg['parent_header'].get('msg_id') != msg_id:
                        continue

                    msg_type = msg['header']['msg_type']
                    content = msg['content']

                    # 执行完成，退出循环
                    if msg_type == 'status' and content['execution_state'] == 'idle':
                        break

                    # 处理各类输出
                    if msg_type == 'stream':
                        text = content.get('text', '')
                        output_objects.append(
                            nbf.new_output('stream', name=content.get('name', 'stdout'), text=text)
                        )
                    elif msg_type == 'execute_result':
                        output_objects.append(
                            nbf.new_output('execute_result', data=content.get('data', {}), execution_count=exec_count)
                        )
                    elif msg_type == 'display_data':
                        output_objects.append(
                            nbf.new_output('display_data', data=content.get('data', {}))
                        )
                    elif msg_type == 'error':
                        output_objects.append(
                            nbf.new_output('error',
                                ename=content.get('ename', ''),
                                evalue=content.get('evalue', ''),
                                traceback=content.get('traceback', []))
                        )

                except Empty:
                    # 没有消息时，检查 shell 是否有回复
                    if not shell_reply_received:
                        try:
                            client.get_shell_msg(timeout=MESSAGE_POLL_TIMEOUT)
                            shell_reply_received = True
                        except Empty:
                            pass
                    continue

        except Exception as e:
            error_msg = f"执行代码或获取输出失败: {repr(e)}"
            output_objects.append(
                nbf.new_output('display_data', data={'text/plain': f'[SYSTEM] {error_msg}'})
            )

        # 更新 notebook 并保存（执行后）
        cell.outputs = output_objects if output_objects else []
        self._save_notebook(notebook, filepath)

        session['execution_count'] += 1

        return self._format_output(output_objects)

    def close_session(self, session_name: str) -> bool:
        """
        关闭指定会话并释放资源

        Args:
            session_name: 会话名称

        Returns:
            True 如果成功关闭，False 如果会话不存在
        """
        if session_name not in self.sessions:
            return False

        session = self.sessions.pop(session_name)

        try:
            # 停止通信通道
            session['client'].stop_channels()
        except Exception:
            pass  # 忽略关闭时的错误

        try:
            # 关闭内核
            session['km'].shutdown_kernel(now=True)
        except Exception:
            pass  # 忽略关闭时的错误

        return True

    def close_all_sessions(self) -> int:
        """
        关闭所有会话并释放资源

        Returns:
            关闭的会话数量
        """
        count = len(self.sessions)
        for session_name in list(self.sessions.keys()):
            self.close_session(session_name)
        return count


# ============== MCP 服务定义 ==============

mcp = FastMCP("Python 执行器")

# 全局执行器实例
python_executer = PythonExecutor()


@mcp.tool(output_schema=None)
def execute_code(
    session_name: Annotated[str, "【必须】使用题目的 challenge_code 作为唯一会话标识符。同名会话共享状态（变量、导入等）。禁止使用其他值。"],
    code: Annotated[str, "Python 代码（支持多行）。在 Jupyter 内核中运行。支持 `%pip install pkg` 和 `!shell_cmd`。"],
    timeout: Annotated[Optional[int], "最大超时秒数（默认: 10）。超时后中断但保持会话存活。"]
) -> list[dict]:
    """
    在有状态的 Jupyter 内核中运行 Python 代码。

    **重要规则：session_name 必须使用题目的 challenge_code！**

    功能特性:
    - 跨调用保留变量/函数（有状态执行）
    - 支持 IPython magic 命令（%pip、%load 等）
    - 支持 shell 命令（!cmd）
    - 超时自动中断，会话状态保留
    - 内置 toolset 库（浏览器、终端、笔记等）

    使用示例:
    ```python
    # 查看内置工具帮助
    import toolset
    help(toolset)
    ```

    Returns:
        list[dict]: 输出结果列表，每个字典包含:
            - type: 'stream' | 'execute_result' | 'display_data' | 'error'
            - 对应类型的数据字段
    """
    return python_executer.execute_code(
        session_name=session_name,
        code=code,
        timeout=timeout or 10
    )


@mcp.tool(output_schema=None)
def list_sessions() -> list[str]:
    """
    返回所有活跃会话的名称列表。

    Returns:
        list[str]: 会话名称列表（即 challenge_code 列表）
    """
    return python_executer.list_sessions()


@mcp.tool(output_schema=None)
def close_session(session_name: Annotated[str, "要关闭的会话名称（challenge_code）。"]) -> bool:
    """
    关闭指定会话并释放内核资源。

    关闭后该会话的变量和状态将丢失。

    Returns:
        bool: True 表示成功关闭，False 表示会话不存在
    """
    return python_executer.close_session(session_name)


# ============== 主入口 ==============

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python 执行器 MCP 服务")
    parser.add_argument("--port", type=int, default=8000, help="服务端口（默认: 8000）")
    parser.add_argument('--host', type=str, default='0.0.0.0', help="监听地址（默认: 0.0.0.0）")
    args = parser.parse_args()

    mcp.run(transport="streamable-http", host=args.host, port=args.port, stateless_http=True)