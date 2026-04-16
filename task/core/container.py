"""
Container - 容器创建和管理

提供创建 CTF 解题容器的公共功能。
"""
import os
import threading
import docker
from docker.models.containers import Container
from docker.errors import ImageNotFound, APIError
from typing import Dict, Optional, Tuple


# 默认配置
DEFAULT_DOCKER_IMAGE = "nemo-agent/sandbox:1.0"
DEFAULT_VNC_BASE_PORT = 55900
DEFAULT_NETWORK_MODE = "bridge"

# 反弹端口配置
REVERSE_PORT_BASE = 20000    # 端口分配起始
PORT_SLOT_SIZE = 10          # 每个容器预留端口数
MAX_PORT_SLOTS = 100         # 最大容器数（100 × 10 = 端口范围 20000-20999）

# 运行时端口注册表：key="challenge_code:llm_id" -> base_port
_port_registry: Dict[str, int] = {}
_next_slot = 0
_registry_lock = threading.Lock()


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

def get_workspace_dir() -> str:
    """获取宿主机 workspace 目录路径（优先使用环境变量 WORKSPACE_PATH）"""
    workspace_dir = os.getenv("WORKSPACE_PATH", "") or "/opt/workspace"
    os.makedirs(workspace_dir, exist_ok=True)
    return workspace_dir

# 卷挂载配置（get_volumes() 会动态设置 notes 和 scripts 路径）
# 容器内路径保持绝对路径不变
DEFAULT_VOLUMES = {
    "../claude-code": {"bind": "/opt/nemo-agent/claude-code", "mode": "ro"},
}


def _registry_key(challenge_code: str, llm_id: int) -> str:
    """生成端口注册表 key"""
    return f"{challenge_code}:{llm_id}"


def init_port_registry(docker_client: docker.DockerClient) -> None:
    """
    扫描运行中的容器，重建端口注册表（调度器启动时调用）

    Args:
        docker_client: Docker 客户端
    """
    global _next_slot
    with _registry_lock:
        _port_registry.clear()
        _next_slot = 0
        try:
            for container in docker_client.containers.list():
                name = container.name
                if not name or "-LLM-" not in name:
                    continue
                parts = name.split("-LLM-")
                if len(parts) != 2:
                    continue
                challenge_code, llm_id_str = parts
                try:
                    llm_id = int(llm_id_str)
                except ValueError:
                    continue

                # 从容器端口绑定中找到 20000+ 范围的最高端口
                port_bindings = container.attrs.get('NetworkSettings', {}).get('Ports', {})
                max_slot = 0
                for port_spec in (port_bindings or {}):
                    try:
                        port = int(port_spec.split('/')[0])
                    except (ValueError, IndexError):
                        continue
                    if port >= REVERSE_PORT_BASE:
                        slot = (port - REVERSE_PORT_BASE) // PORT_SLOT_SIZE
                        max_slot = max(max_slot, slot)

                if max_slot > 0:
                    key = _registry_key(challenge_code, llm_id)
                    base = REVERSE_PORT_BASE + max_slot * PORT_SLOT_SIZE
                    _port_registry[key] = base
                    _next_slot = max(_next_slot, max_slot + 1)
        except Exception:
            pass


def get_reverse_ports(llm_id: int, challenge_code: str = "") -> Dict[str, int]:
    """
    为容器分配反弹端口（运行时注册，保证多题目 × 多 LLM 无冲突）

    每个 (challenge_code, llm_id) 组合分配独立的 10 端口槽。
    同一组合重复调用返回相同端口（幂等）。

    Args:
        llm_id: LLM ID
        challenge_code: 题目代码

    Returns:
        端口名称到端口号的映射
    """
    global _next_slot

    with _registry_lock:
        key = _registry_key(challenge_code, llm_id)

        if key in _port_registry:
            base = _port_registry[key]
        else:
            if _next_slot >= MAX_PORT_SLOTS:
                raise RuntimeError(
                    f"端口槽已耗尽（最多 {MAX_PORT_SLOTS} 个容器），"
                    f"请检查是否有僵尸容器未清理"
                )
            base = REVERSE_PORT_BASE + _next_slot * PORT_SLOT_SIZE
            _port_registry[key] = base
            _next_slot += 1

    ports = {
        "nc": base,                 # NC 反弹 shell（主）
        "nc2": base + 1,            # NC 反弹 shell（备）
        "jndi_ldap": base + 2,      # JNDI LDAP
        "jndi_http": base + 3,      # JNDI HTTP
        "socks5": base + 4,         # SOCKS5 代理
        "frp": base + 5,            # frp 服务端
        "frp_dashboard": base + 6,  # frp Dashboard
        "msf": base + 7,            # Metasploit
        "chisel": base + 8,         # chisel 服务端
        "stowaway": base + 9,       # Stowaway 管理端
    }
    return ports


def _compact_next_slot() -> None:
    """回缩 _next_slot 到 registry 中实际最大 slot + 1（需在 _registry_lock 内调用）"""
    global _next_slot
    if not _port_registry:
        _next_slot = 0
        return
    max_slot = 0
    for base in _port_registry.values():
        slot = (base - REVERSE_PORT_BASE) // PORT_SLOT_SIZE
        max_slot = max(max_slot, slot)
    _next_slot = max_slot + 1


def release_reverse_ports(challenge_code: str, llm_id: int) -> None:
    """
    释放端口注册并回收 slot（容器停止时调用）

    Args:
        challenge_code: 题目代码
        llm_id: LLM ID
    """
    with _registry_lock:
        _port_registry.pop(_registry_key(challenge_code, llm_id), None)
        _compact_next_slot()


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
    workspace_dir = get_workspace_dir()

    expanded_volumes = {
        notes_dir: {"bind": "/opt/notes", "mode": "rw"},
        scripts_dir: {"bind": "/opt/scripts", "mode": "rw"},
        workspace_dir: {"bind": "/opt/workspace", "mode": "rw"},
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


def build_task_prompt(target_url: str, challenge_code: str, competition_mode: bool = False,
                      description: str = "", hint: str = "", zone: int = 1,
                      flag_count: int = 1) -> str:
    """
    构建任务提示词

    仅包含目标信息，不重复 agent 定义中已有的规则和流程。
    Agent 行为由 .claude/agents/pentest-agent.md 和 skills/pentest/SKILL.md 定义。

    Args:
        target_url: 目标 URL
        challenge_code: 挑战代码
        competition_mode: 是否为竞赛模式（需要提交答案）
        description: 赛题描述（来自平台 API）
        hint: 提示内容（来自平台 hint API）
        zone: 赛区编号（1-4），来自平台 current_level 全局值
        flag_count: 该赛题的 Flag 总数

    Returns:
        任务提示词字符串
    """
    # 从 target_url 提取 IP（用于 nmap 等工具）
    import re as _re
    _ip_match = _re.search(r'(\d+\.\d+\.\d+\.\d+)', target_url)
    _target_ip = _ip_match.group(1) if _ip_match else target_url

    prompt = f"""使用pentest-agent，对以下目标进行渗透测试，获取 flag。

**开始前必须先读笔记！如果笔记中包含有重要的凭证信息、已有的攻击路径和成果，必须首先遵守笔记中的渗透测试流程！！！**

## 目标信息

- 目标 URL: {target_url}
- 目标 IP: {_target_ip}
- 题目代码: {challenge_code}
- 赛区: Zone {zone}
"""

    if flag_count > 1:
        prompt += f"- Flag 数量: {flag_count} 个，需全部找到并提交\n"

    if description:
        prompt += f"- 题目描述: {description}\n"

    if hint:
        prompt += f"- 提示信息: {hint}\n"

    if competition_mode:
        prompt += f"""
## 竞赛模式（已启用）

- 获取 FLAG 后必须调用: toolset.competition.submit_answer(challenge_code="{challenge_code}", answer=flag)
- 确认返回 correct=True 才算完成
"""

    return prompt


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
        "WORKSPACE_PATH":  "/opt/workspace",  # 工作目录
    }

    # 竞赛模式：添加竞赛平台 URL + Agent Token
    if competition_mode:
        environment["COMPETITION_API_URL"] = os.getenv("COMPETITION_API_URL", "http://host.docker.internal")
        agent_token = os.getenv("AGENT_TOKEN", "") or os.getenv("COMPETITION_API_TOKEN", "")
        environment["AGENT_TOKEN"] = agent_token  # 始终注入，空值时 competition.py 会警告

    # 如果启用 VNC，添加 VNC 端口配置
    if no_vision:
        # 禁用 VNC 模式
        environment["NO_VISION"] = "true"
        config = {
            "name": container_name,
            "environment": environment,
            "ports": {},  # 不映射 VNC 端口
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

    # 注入反弹 IP 和端口配置
    reverse_ip = os.getenv("REVERSE_IP", "")
    if reverse_ip:
        environment["REVERSE_IP"] = reverse_ip

    reverse_ports = get_reverse_ports(llm_id, challenge_code)
    for name, port in reverse_ports.items():
        env_key = f"PORT_{name.upper()}"
        environment[env_key] = str(port)
        config["ports"][f"{port}/tcp"] = port

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
    network_mode: str = DEFAULT_NETWORK_MODE,
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
        network_mode: 网络模式，默认 bridge

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
            entrypoint=["/bin/bash", "/opt/nemo-agent/claude-code/entrypoint.sh"],
            detach=True,
            remove=False,
            network_mode=network_mode,
            extra_hosts={"host.docker.internal": "host-gateway"},
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
