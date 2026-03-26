"""
Runner - 解题 Runner 基础功能

提供 Docker 客户端初始化、容器验证、任务执行等公共功能。
"""
import os
import docker
import time
from docker.models.containers import Container
from docker.errors import ImageNotFound, APIError, DockerException
from typing import Dict, Optional, Any
from dataclasses import dataclass
import threading

# 默认配置
DEFAULT_DOCKER_IMAGE = "nemo-agent/sandbox:1.1"
DEFAULT_VNC_BASE_PORT = 55900
# 容器内工作目录（绝对路径）
DEFAULT_WORKDIR = "/opt/nemo-agent/claude-code"


def get_docker_image() -> str:
    """
    从环境变量获取 Docker 镜像名称

    Returns:
        Docker 镜像名称
    """
    return os.getenv("DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE)


def get_vnc_base_port() -> int:
    """
    从环境变量获取 VNC 基础端口

    Returns:
        VNC 基础端口
    """
    return int(os.getenv("VNC_BASE_PORT", str(DEFAULT_VNC_BASE_PORT)))


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    exit_code: Optional[int] = None
    output: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "output": self.output,
            "error": self.error
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        """从字典创建"""
        return cls(
            success=data.get("success", False),
            exit_code=data.get("exit_code"),
            output=data.get("output"),
            error=data.get("error")
        )

    @classmethod
    def error_result(cls, error: str) -> "TaskResult":
        """创建错误结果"""
        return cls(success=False, error=error)

    @classmethod
    def success_result(cls, exit_code: int = 0, output: str = "") -> "TaskResult":
        """创建成功结果"""
        return cls(success=True, exit_code=exit_code, output=output)


def get_log_prefix(llm_id: int) -> str:
    """获取日志前缀"""
    return f"[LLM-{llm_id}]"


def create_docker_client() -> docker.DockerClient:
    """
    创建并验证 Docker 客户端

    Returns:
        Docker 客户端

    Raises:
        RuntimeError: 连接失败时抛出
    """
    try:
        client = docker.DockerClient()
        # 验证连接
        client.ping()
        return client
    except DockerException as e:
        raise RuntimeError(f"无法连接到 Docker daemon: {e}")


def verify_docker_image(
    client: docker.DockerClient,
    image_name: str,
    log_prefix: str = ""
) -> None:
    """
    验证 Docker 镜像存在

    Args:
        client: Docker 客户端
        image_name: 镜像名称
        log_prefix: 日志前缀

    Raises:
        RuntimeError: 镜像不存在时抛出
    """
    try:
        client.images.get(image_name)
    except ImageNotFound:
        msg = f"Docker 镜像 '{image_name}' 未找到。请先拉取镜像: docker pull {image_name}"
        if log_prefix:
            print(f"{log_prefix} [-] {msg}")
        raise RuntimeError(msg)
    except APIError as e:
        msg = f"检查 Docker 镜像时出错: {e}"
        if log_prefix:
            print(f"{log_prefix} [-] {msg}")
        raise RuntimeError(msg)


def verify_container_running(
    container: Container,
    log_prefix: str = "",
    wait_seconds: int = 3
) -> bool:
    """
    验证容器正在运行

    Args:
        container: 容器对象
        log_prefix: 日志前缀
        wait_seconds: 等待秒数

    Returns:
        如果容器正在运行返回 True，否则返回 False

    Raises:
        RuntimeError: 容器状态异常时抛出
    """
    # 等待容器初始化
    time.sleep(wait_seconds)

    # 检查容器状态
    container.reload()
    status = container.status

    if status != "running":
        msg = f"容器状态异常: {status}"
        if log_prefix:
            print(f"{log_prefix} [-] {msg}")
            print(f"{log_prefix} [-] 容器日志:")
            logs = get_container_logs(container)
            print(logs if logs else "无日志")
        raise RuntimeError(msg)

    if log_prefix:
        print(f"{log_prefix} [+] 容器状态: {status}")

    return True


def wait_for_mcp_service(
    container: Container,
    log_prefix: str = "",
    workdir: str = DEFAULT_WORKDIR
) -> Optional[TaskResult]:
    """
    等待 MCP 服务就绪

    Args:
        container: 容器对象
        log_prefix: 日志前缀
        workdir: 工作目录

    Returns:
        失败时返回 TaskResult，成功时返回 None
    """
    if log_prefix:
        print(f"{log_prefix} [+] 等待沙盒环境和 MCP 服务就绪...")

    wait_result = container.exec_run(
        ["bash", "wait.sh"],
        workdir=workdir
    )

    if wait_result.exit_code != 0:
        error = f"等待脚本执行失败，退出码: {wait_result.exit_code}"
        if log_prefix:
            print(f"{log_prefix} [-] {error}")
        return TaskResult.error_result(error)

    if log_prefix:
        print(f"{log_prefix} [+] MCP 服务已就绪...")

    return None


def execute_claude_task(
    container: Container,
    task: str,
    log_prefix: str = "",
    workdir: str = DEFAULT_WORKDIR
) -> TaskResult:
    """
    在容器中执行 Claude 任务

    Args:
        container: 容器对象
        task: 任务字符串
        log_prefix: 日志前缀
        workdir: 工作目录

    Returns:
        TaskResult 对象
    """
    if log_prefix:
        print(f"{log_prefix} [+] 正在启动 ctf-web-agent...")

    res = container.exec_run(
        ["claude", "--dangerously-skip-permissions", "--print", task],
        workdir=workdir
    )

    exit_code = res.exit_code
    success = exit_code == 0

    if log_prefix:
        if success:
            print(f"{log_prefix} [+] 任务执行完成")
        else:
            print(f"{log_prefix} [-] 命令执行失败，退出码: {exit_code}")

    # 解析输出
    output = None
    if res.output:
        output = res.output.decode('utf-8', errors='replace')
        if log_prefix:
            print(f"{log_prefix} [+] 输出:\n{output}")

    return TaskResult.success_result(exit_code, output) if success else TaskResult.error_result(f"退出码: {exit_code}")


def execute_task_with_stop_check(
    container: Container,
    task: str,
    stop_event: threading.Event,
    log_prefix: str = "",
    workdir: str = DEFAULT_WORKDIR
) -> TaskResult:
    """
    执行任务，支持外部停止信号

    Args:
        container: 容器对象
        task: 任务字符串
        stop_event: 停止事件
        log_prefix: 日志前缀
        workdir: 工作目录

    Returns:
        TaskResult 对象
    """
    # 等待 MCP 服务
    mcp_result = wait_for_mcp_service(container, log_prefix, workdir)
    if mcp_result:
        return mcp_result

    # 检查是否已被停止
    if stop_event.is_set():
        msg = "任务已被外部信号停止"
        if log_prefix:
            print(f"{log_prefix} [-] {msg}")
        return TaskResult.error_result(msg)

    # 执行 Claude 任务
    return execute_claude_task(container, task, log_prefix, workdir)


def cleanup_container(
    container: Container,
    log_prefix: str = ""
) -> None:
    """
    清理容器资源

    Args:
        container: 容器对象
        log_prefix: 日志前缀
    """
    if container:
        try:
            container.remove(force=True)
            if log_prefix:
                print(f"{log_prefix} [+] 容器已清理")
        except Exception as e:
            if log_prefix:
                print(f"{log_prefix} [-] 清理容器时出错: {e}")


def get_container_logs(container: Container) -> str:
    """
    获取容器日志

    Args:
        container: 容器对象

    Returns:
        容器日志字符串
    """
    try:
        logs = container.logs(stdout=True, stderr=True)
        return logs.decode('utf-8', errors='replace') if logs else ""
    except Exception:
        return ""
