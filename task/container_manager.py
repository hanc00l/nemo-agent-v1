"""
Container Manager - Docker 容器生命周期管理

管理 CTF 挑战解题容器的创建、启动、停止和监控。
"""
import time
import threading
import os
import fcntl
import docker
from docker.models.containers import Container
from docker.errors import DockerException, ImageNotFound, APIError
from typing import List, Dict, Optional
from dataclasses import dataclass

# 导入核心模块
from core import (
    get_vnc_port,
    get_container_name,
    create_challenge_container,
    build_task_prompt,
    get_notes_dir,
    TaskResult,
)


@dataclass
class ContainerResult:
    """容器操作结果"""
    success: bool
    container_name: Optional[str] = None
    message: str = ""


class ContainerManager:
    """Docker 容器生命周期管理"""

    def __init__(self, docker_image: str, vnc_base_port: int = 55900):
        self.docker_image = docker_image
        self.vnc_base_port = vnc_base_port

        try:
            self.client = docker.DockerClient()
            # 验证连接
            self.client.ping()
        except DockerException as e:
            raise RuntimeError(f"无法连接到 Docker daemon: {e}")

        # 验证镜像存在
        self._ensure_image()

    def _ensure_image(self):
        """确保 Docker 镜像存在"""
        try:
            self.client.images.get(self.docker_image)
        except ImageNotFound:
            raise RuntimeError(
                f"Docker 镜像 '{self.docker_image}' 未找到。"
                f"请先拉取镜像: docker pull {self.docker_image}"
            )
        except APIError as e:
            raise RuntimeError(f"检查 Docker 镜像时出错: {e}")

    def start_challenge_containers(
        self,
        challenge_code: str,
        target_url: str,
        llm_configs: List[Dict]
    ) -> List[str]:
        """
        启动挑战的所有容器，并在容器中执行解题任务

        Args:
            challenge_code: 挑战代码
            target_url: 目标 URL
            llm_configs: LLM 配置列表

        Returns:
            启动的容器名称列表

        Raises:
            RuntimeError: 启动失败时抛出
        """
        if not llm_configs:
            raise ValueError("没有可用的 LLM 配置")

        container_names = []
        failed_containers = []

        for config in llm_configs:
            llm_id = config["id"]
            container_name = get_container_name(challenge_code, llm_id)

            # 检查容器是否已存在
            try:
                existing = self.client.containers.get(container_name)
                if existing.status == "running":
                    print(f"[-] 容器 {container_name} 已存在且运行中，跳过")
                    container_names.append(container_name)
                    continue
                else:
                    existing.remove(force=True)
            except:
                pass  # 容器不存在，正常情况

            try:
                # 使用核心模块创建容器
                container = create_challenge_container(
                    docker_client=self.client,
                    challenge_code=challenge_code,
                    llm_id=llm_id,
                    llm_config=config,
                    docker_image=self.docker_image,
                    vnc_base_port=self.vnc_base_port,
                    competition_mode=True,  # 启用竞赛模式
                )

                # 获取容器配置中的 VNC 端口信息
                from core.container import prepare_container_config
                container_config = prepare_container_config(
                    llm_id=llm_id,
                    llm_config=config,
                    challenge_code=challenge_code,
                    vnc_base_port=self.vnc_base_port,
                    competition_mode=True
                )
                actual_vnc_port = container_config.get("vnc_port")

                # 根据是否启用 VNC 显示不同信息
                if actual_vnc_port:
                    print(f"[+] 容器已启动: {container_name} (VNC: {actual_vnc_port})")
                else:
                    print(f"[+] 容器已启动: {container_name} (无VNC)")

                container_names.append(container_name)

                # 等待容器初始化
                time.sleep(2)

                # 检查容器状态
                container.reload()
                if container.status != "running":
                    print(f"[-] 容器 {container_name} 状态异常: {container.status}")
                    failed_containers.append(container_name)
                else:
                    # 在后台线程中执行任务
                    self._execute_task_in_container(
                        container=container,
                        challenge_code=challenge_code,
                        target_url=target_url,
                        container_name=container_name
                    )

            except Exception as e:
                print(f"[-] 启动容器 {container_name} 失败: {e}")
                failed_containers.append(container_name)

        # 清理失败的容器
        for name in failed_containers:
            if name in container_names:
                container_names.remove(name)
            try:
                c = self.client.containers.get(name)
                c.remove(force=True)
            except:
                pass

        if not container_names:
            raise RuntimeError("所有容器启动失败")

        return container_names

    def _execute_task_in_container(
        self,
        container: Container,
        challenge_code: str,
        target_url: str,
        container_name: str
    ):
        """
        在容器中异步执行解题任务

        Args:
            container: 容器对象
            challenge_code: 挑战代码
            target_url: 目标 URL
            container_name: 容器名称
        """
        def run_task():
            try:
                log_prefix = f"[{container_name}]"
                print(f"{log_prefix} [+] 等待 MCP 服务就绪...")

                # 1. 等待 MCP 服务就绪
                wait_result = container.exec_run(
                    ["bash", "wait.sh"],
                    workdir="/opt/nemo-agent/claude-code"
                )

                if wait_result.exit_code != 0:
                    print(f"{log_prefix} [-] 等待 MCP 服务失败，退出码: {wait_result.exit_code}")
                    return

                print(f"{log_prefix} [+] MCP 服务已就绪")

                # 2. 检查是否需要停止（容器可能已被停止）
                try:
                    container.reload()
                    if container.status != "running":
                        print(f"{log_prefix} [-] 容器已停止，跳过任务执行")
                        return
                except:
                    return

                # 3. 构建任务提示词
                task = build_task_prompt(target_url, challenge_code, competition_mode=True)
                print(f"{log_prefix} [+] 开始执行解题任务...")

                # 4. 执行 Claude 任务
                result = container.exec_run(
                    ["claude", "--dangerously-skip-permissions", "--print", task],
                    workdir="/opt/nemo-agent/claude-code"
                )

                print(f"{log_prefix} [+] 任务执行完成，退出码: {result.exit_code}")

                # 5. 输出结果（截断显示）
                if result.output:
                    output = result.output.decode('utf-8', errors='replace')
                    if len(output) > 1000:
                        print(f"{log_prefix} [+] 输出: {output[:500]}... [已截断] ...{output[-500:]}")
                    else:
                        print(f"{log_prefix} [+] 输出: {output}")

                    # 6. 保存结果到文件（追加模式）
                    self._save_result_to_file(challenge_code, output)

            except Exception as e:
                print(f"[-] {container_name}: 执行任务失败: {e}")

        # 在后台线程中执行任务
        thread = threading.Thread(target=run_task, daemon=True)
        thread.start()

    def stop_challenge_containers(self, challenge_code: str) -> int:
        """
        停止挑战的所有容器

        Returns:
            停止的容器数量
        """
        stopped_count = 0
        prefix = f"{challenge_code}-LLM-"

        # 获取所有相关容器
        containers = self.client.containers.list(all=True)
        for container in containers:
            if container.name and container.name.startswith(prefix):
                try:
                    container.remove(force=True)
                    print(f"[+] 容器已停止: {container.name}")
                    stopped_count += 1
                except Exception as e:
                    print(f"[-] 停止容器 {container.name} 失败: {e}")

        return stopped_count

    def get_container_status(self, challenge_code: str) -> Dict[str, str]:
        """
        获取挑战的所有容器状态

        Returns:
            {container_name: status} 字典
        """
        statuses = {}
        prefix = f"{challenge_code}-LLM-"

        containers = self.client.containers.list(all=True)
        for container in containers:
            if container.name and container.name.startswith(prefix):
                statuses[container.name] = container.status

        return statuses

    def restart_dead_containers(self, challenge_code: str) -> List[str]:
        """
        重启已停止的容器

        Returns:
            重启的容器名称列表
        """
        restarted = []
        prefix = f"{challenge_code}-LLM-"

        containers = self.client.containers.list(all=True)
        for container in containers:
            if container.name and container.name.startswith(prefix):
                if container.status != "running":
                    try:
                        container.start()
                        print(f"[+] 容器已重启: {container.name}")
                        restarted.append(container.name)
                    except Exception as e:
                        print(f"[-] 重启容器 {container.name} 失败: {e}")

        return restarted

    def get_all_running_containers(self) -> Dict[str, List[str]]:
        """
        获取所有正在运行的容器，按挑战代码分组

        Returns:
            {challenge_code: [container_names]} 字典
        """
        result: Dict[str, List[str]] = {}

        containers = self.client.containers.list(filters={"status": "running"})
        for container in containers:
            name = container.name
            if name and "-LLM-" in name:
                # 提取 challenge_code (格式: xxx-LLM-N)
                parts = name.split("-LLM-")
                if len(parts) == 2:
                    challenge_code = parts[0]
                    if challenge_code not in result:
                        result[challenge_code] = []
                    result[challenge_code].append(name)

        return result

    def cleanup_stopped_containers(self) -> int:
        """
        清理所有已停止的调度器容器

        Returns:
            清理的容器数量
        """
        cleaned = 0

        containers = self.client.containers.list(all=True)
        for container in containers:
            name = container.name
            if name and "-LLM-" in name and container.status != "running":
                try:
                    container.remove(force=True)
                    print(f"[+] 清理已停止的容器: {name}")
                    cleaned += 1
                except Exception as e:
                    print(f"[-] 清理容器 {name} 失败: {e}")

        return cleaned

    def _save_result_to_file(self, challenge_code: str, output: str):
        """
        将容器执行结果追加保存到 notes 目录（带文件锁，支持并发）

        Args:
            challenge_code: 挑战代码
            output: 输出内容
        """
        # 使用环境变量或默认的 notes 目录
        notes_dir = get_notes_dir()

        result_file = os.path.join(notes_dir, f"{challenge_code}-result.md")

        try:
            with open(result_file, 'a', encoding='utf-8') as f:
                # 获取文件锁（非阻塞）
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(output)
                    if not output.endswith('\n'):
                        f.write('\n')
                    f.write('\n---\n\n')  # 添加分隔符
                finally:
                    # 释放文件锁
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            print(f"[+] 结果已追加到笔记 `{challenge_code}-result.md`")
        except Exception as e:
            print(f"[-] 保存结果到文件失败: {e}")
