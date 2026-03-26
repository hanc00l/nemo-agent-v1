"""
Container - 容器创建和管理

提供创建 CTF 解题容器的公共功能。
"""
import os
import docker
from docker.models.containers import Container
from docker.errors import ImageNotFound, APIError
from typing import Dict, Optional, Tuple


# 默认配置
DEFAULT_DOCKER_IMAGE = "nemo-agent/sandbox:1.1"
DEFAULT_VNC_BASE_PORT = 55900


def get_notes_dir() -> str:
    """获取宿主机 notes 目录路径（优先使用环境变量 NOTE_PATH）"""
    notes_dir = os.getenv("NOTE_PATH", "") or "/opt/notes"
    os.makedirs(notes_dir, exist_ok=True)
    return notes_dir


def get_scripts_dir() -> str:
    """获取宿主机 scripts 目录路径（优先使用环境变量 NOTEBOOK_PATH）"""
    scripts_dir = os.getenv("NOTEBOOK_PATH", "") or "/opt/scripts"
    os.makedirs(scripts_dir, exist_ok=True)
    return scripts_dir


# 卷挂载配置（get_volumes() 会动态设置 notes 和 scripts 路径）
# 容器内路径保持绝对路径不变
DEFAULT_VOLUMES = {
    "../claude-code": {"bind": "/opt/nemo-agent/claude-code", "mode": "ro"},
}


def get_volumes() -> Dict[str, Dict]:
    """
    获取卷挂载配置（自动展开相对路径为绝对路径）

    Returns:
        卷挂载字典，所有路径已展开为绝对路径
    """
    volumes = DEFAULT_VOLUMES.copy()

    # 动态添加 notes 和 scripts 卷（使用环境变量或默认值）
    notes_dir = get_notes_dir()
    scripts_dir = get_scripts_dir()

    expanded_volumes = {
        notes_dir: {"bind": "/opt/notes", "mode": "rw"},
        scripts_dir: {"bind": "/opt/scripts", "mode": "rw"},
    }

    for host_path, config in volumes.items():
        # 展开相对路径为绝对路径
        expanded_host_path = os.path.abspath(host_path)
        expanded_volumes[expanded_host_path] = config

    return expanded_volumes


def get_vnc_port(llm_id: int, base_port: int = DEFAULT_VNC_BASE_PORT, challenge_code: str = None) -> int:
    """
    根据 LLM ID 和 challenge_code 计算 VNC 端口

    Args:
        llm_id: LLM ID
        base_port: 基础端口
        challenge_code: 挑战代码 (可选，用于多挑战端口分配)

    Returns:
        VNC 端口号
    """
    if challenge_code:
        # 基于 challenge_code 计算端口偏移，避免不同挑战间端口冲突
        # 使用哈希确保相同 challenge_code 总是得到相同偏移
        import hashlib
        hash_value = int(hashlib.md5(challenge_code.encode()).hexdigest()[:8], 16)
        # 限制偏移范围在 0-999 之间，避免端口过大
        offset = hash_value % 1000
        return base_port + offset + llm_id
    else:
        # 向后兼容：只基于 llm_id
        return base_port + llm_id


def get_container_name(challenge_code: str, llm_id: int) -> str:
    """
    生成容器名称

    Args:
        challenge_code: 挑战代码
        llm_id: LLM ID

    Returns:
        容器名称 (格式: {challenge_code}-LLM-{llm_id})
    """
    return f"{challenge_code}-LLM-{llm_id}"


def build_task_prompt(target_url: str, challenge_code: str, competition_mode: bool = False) -> str:
    """
    构建任务提示词

    Args:
        target_url: 目标 URL
        challenge_code: 挑战代码
        competition_mode: 是否为竞赛模式（需要提交答案）

    Returns:
        任务提示词字符串
    """
    base_prompt = (
        f"使用 ctf-web-agent 完成挑战：\n"
        f"**目标信息**: {target_url}\n"
        f"**题目代码 (challenge_code)**: {challenge_code}\n"
    )

    if competition_mode:
        base_prompt += (
            f"\n**重要**: 这是一个竞赛模式任务！\n"
            f"1. 获取 FLAG 后，必须使用 toolset.competition.submit_answer() 提交答案\n"
            f"2. 竞赛平台 URL: {os.getenv('COMPETITION_API_URL', 'http://host.docker.internal:8888')}\n"
            f"3. 提交成功后，将结果保存到笔记 (note_type='result')\n"
        )

    return base_prompt


def prepare_container_config(
    llm_id: int,
    llm_config: Dict,
    challenge_code: str,
    vnc_base_port: int = DEFAULT_VNC_BASE_PORT,
    competition_mode: bool = False,
) -> Dict:
    """
    准备容器配置

    Args:
        llm_id: LLM ID
        llm_config: LLM 配置字典，包含 base_url, auth_token, model
        challenge_code: 挑战代码
        vnc_base_port: VNC 基础端口
        competition_mode: 是否为竞赛模式

    Returns:
        容器配置字典，包含 name, environment, ports
    """
    # 检查是否禁用 VNC
    no_vision = os.getenv("NO_VISION", "false").lower() == "true"

    container_name = get_container_name(challenge_code, llm_id)

    environment = {
        "ANTHROPIC_BASE_URL": llm_config["base_url"],
        "ANTHROPIC_AUTH_TOKEN": llm_config["auth_token"],
        "ANTHROPIC_MODEL": llm_config["model"],
        "LLM_ID": f"LLM-{llm_id}",  # 添加 LLM 标识，方便在笔记和日志中区分
        "NOTE_PATH": "/opt/notes",  # 容器内的笔记路径
        "NOTEBOOK_PATH": "/opt/scripts",  # 容器内的 notebook 路径
    }

    # 竞赛模式：添加竞赛平台 URL
    if competition_mode:
        competition_url = os.getenv("COMPETITION_API_URL", "http://host.docker.internal:8888")
        environment["COMPETITION_API_URL"] = competition_url

    # 如果启用 VNC，添加 VNC 端口配置
    if no_vision:
        # 禁用 VNC 模式
        environment["NO_VISION"] = "true"
        config = {
            "name": container_name,
            "environment": environment,
            "ports": {},  # 不映射任何端口
            "vnc_port": None,
            "llm_id": llm_id,
        }
    else:
        # 启用 VNC 模式
        vnc_port = get_vnc_port(llm_id, vnc_base_port, challenge_code)
        environment["VNC_PORT"] = str(vnc_port)
        config = {
            "name": container_name,
            "environment": environment,
            "ports": {f"{vnc_port}/tcp": vnc_port},
            "vnc_port": vnc_port,
            "llm_id": llm_id,
        }

    return config


def create_challenge_container(
    docker_client: docker.DockerClient,
    challenge_code: str,
    llm_id: int,
    llm_config: Dict,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    vnc_base_port: int = DEFAULT_VNC_BASE_PORT,
    volumes: Optional[Dict] = None,
    competition_mode: bool = False,
) -> Container:
    """
    创建并启动 CTF 解题容器

    Args:
        docker_client: Docker 客户端
        challenge_code: 挑战代码
        llm_id: LLM ID
        llm_config: LLM 配置字典，包含 base_url, auth_token, model
        docker_image: Docker 镜像名称
        vnc_base_port: VNC 基础端口
        volumes: 卷挂载配置，默认使用 get_volumes()（自动展开 ~ 路径）
        competition_mode: 是否为竞赛模式

    Returns:
        创建的容器对象

    Raises:
        ValueError: 如果 auth_token 为空
        RuntimeError: 如果镜像不存在或创建失败
    """
    # 验证 auth_token
    auth_token = llm_config.get("auth_token")
    if not auth_token:
        raise ValueError(f"LLM-{llm_id} 缺少 AUTH_TOKEN")

    # 验证镜像存在
    try:
        docker_client.images.get(docker_image)
    except ImageNotFound:
        raise RuntimeError(
            f"Docker 镜像 '{docker_image}' 未找到。"
            f"请先拉取镜像: docker pull {docker_image}"
        )
    except APIError as e:
        raise RuntimeError(f"检查 Docker 镜像时出错: {e}")

    # 准备配置
    config = prepare_container_config(llm_id, llm_config, challenge_code, vnc_base_port, competition_mode)
    if volumes is None:
        volumes = get_volumes()  # 使用展开的卷配置（~ 已展开）

    # 创建并启动容器
    try:
        container = docker_client.containers.run(
            image=docker_image,
            name=config["name"],
            volumes=volumes,
            environment=config["environment"],
            ports=config["ports"],
            entrypoint=["/bin/bash", "/opt/nemo-agent/claude-code/entrypoint.sh"],  # 容器内绝对路径
            detach=True,
            remove=False
        )
        return container
    except Exception as e:
        raise RuntimeError(f"启动容器失败: {e}")


def verify_container_running(container: Container, timeout: int = 10) -> bool:
    """
    验证容器是否正常运行

    Args:
        container: 容器对象
        timeout: 超时时间（秒）

    Returns:
        如果容器正在运行返回 True，否则返回 False
    """
    import time

    # 等待容器初始化
    time.sleep(2)

    try:
        container.reload()
        return container.status == "running"
    except Exception:
        return False


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
