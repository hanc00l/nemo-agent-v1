"""
Scheduler - CTF 挑战调度器

自动从竞赛平台获取挑战，管理平台实例和本地容器生命周期。
双层管理：平台 API 管理赛题实例 + 本地 Docker 管理解题 Agent。
"""
import os
import sys
import time
from typing import Optional, Dict, List

# 添加父目录到路径以导入本地模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SchedulerConfig
from challenge_state import ChallengeStateManager, ChallengeStateData
from container_manager import ContainerManager

# 导入核心模块
from core import (
    # 状态常量
    STATE_OPEN,
    STATE_STARTED,
    STATE_SUCCESS,
    STATE_FAIL,
    STATE_CLOSE,
    is_challenge_timeout,
    get_elapsed_seconds,
    get_timestamp,
    # 日志
    SchedulerLogger,
    # 平台
    PlatformClient,
    # 信号
    GracefulShutdown,
)


class ChallengeScheduler:
    """CTF 挑战调度器（双层管理：平台实例 + 本地容器）"""

    def __init__(self, config: SchedulerConfig):
        self.config = config
        self.logger = SchedulerLogger("scheduler", config.LOG_FILE)

        # PID 文件锁（防止多进程同时运行）
        self._pid_file = None
        self._pid_lock = None
        self._acquire_pid_lock()

        self.state_manager = ChallengeStateManager(
            config.STATE_FILE,
            default_timeout=config.TIMEOUT_SECONDS
        )
        self.container_manager = ContainerManager(
            docker_image=config.DOCKER_IMAGE,
            vnc_base_port=config.VNC_BASE_PORT
        )

        # 平台客户端
        self.platform = PlatformClient()

        # 信号处理
        self.running = False
        self._shutdown = GracefulShutdown()
        self._shutdown.register(self._on_shutdown_signal)
        self._shutdown.setup()

    def _acquire_pid_lock(self):
        """获取 PID 文件锁（防止多进程运行）"""
        import fcntl

        pid_file_path = os.path.join(
            os.path.dirname(self.config.STATE_FILE),
            "scheduler.pid"
        )

        try:
            self._pid_file = open(pid_file_path, "w")
            fcntl.flock(self._pid_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._pid_file.write(str(os.getpid()))
            self._pid_file.flush()
            self._pid_lock = True
            self.logger.info(f"PID 文件锁已获取: {pid_file_path}", "init")
        except IOError:
            self._pid_file.close()
            self._pid_file = None
            raise RuntimeError(
                f"调度器已在运行（PID 文件: {pid_file_path}）。"
                "请先停止现有实例，或删除该 PID 文件。"
            )

    def _release_pid_lock(self):
        """释放 PID 文件锁"""
        if self._pid_file is not None:
            try:
                self._pid_file.close()
                pid_file_path = self._pid_file.name
                if os.path.exists(pid_file_path):
                    os.remove(pid_file_path)
                self.logger.info(f"PID 文件锁已释放", "shutdown")
            except Exception as e:
                self.logger.warn(f"释放 PID 文件锁失败: {e}", "shutdown")
            finally:
                self._pid_file = None
                self._pid_lock = False

    def _on_shutdown_signal(self):
        """信号处理器"""
        self.logger.info("收到关闭信号，准备优雅关闭...", "shutdown")
        self.stop()

    def start(self):
        """启动调度器"""
        self.logger.info("启动 CTF 挑战调度器", "start")
        self.logger.info(f"配置: 并行={self.config.MAX_PARALLEL}, 超时={self.config.TIMEOUT_SECONDS}s")
        self.logger.info(f"平台: {self.config.COMPETITION_API_URL}")
        self.running = True
        self.run()

    def stop(self):
        """停止调度器"""
        if not self.running:
            return

        self.logger.info("正在停止调度器...", "stop")
        self.running = False

        # 停止所有容器和平台实例
        self._stop_all_containers()

        # 释放 PID 文件锁
        self._release_pid_lock()

        self.logger.info("调度器已停止", "stop")

    def run(self):
        """主循环"""
        self.logger.info("调度器主循环开始", "main")

        while self.running:
            try:
                # 1. 从平台获取挑战
                platform_challenges = self._fetch_platform_challenges()
                if platform_challenges is None:
                    self._sleep_interruptible(self.config.FETCH_INTERVAL)
                    continue

                # 2. 同步本地状态
                sync_result = self.state_manager.sync_with_platform(platform_challenges)
                if sync_result["new"]:
                    self.logger.info(f"新增 {len(sync_result['new'])} 个挑战", "fetch")
                if sync_result["removed"]:
                    self.logger.info(f"移除 {len(sync_result['removed'])} 个挑战", "fetch")
                if sync_result["solved"]:
                    self.logger.info(f"平台确认解决 {len(sync_result['solved'])} 个挑战", "fetch")
                    for challenge_code in sync_result["solved"]:
                        self._stop_challenge_full(challenge_code)
                        self.logger.info(f"已清理已解决挑战 {challenge_code}", "cleanup")
                if sync_result["recovered"]:
                    self.logger.info(f"恢复 {len(sync_result['recovered'])} 个挑战", "fetch")

                # 3. 检查已解决的挑战
                self._check_solved_challenges()

                # 4. 检查超时
                self._check_timeouts()

                # 5. 维护容器（传入平台数据避免重复请求）
                self._maintain_containers(platform_challenges)

                # 6. 清理已完成状态的容器
                self._cleanup_finished_containers()

                # 7. 启动新挑战
                self._start_new_challenges()

            except Exception as e:
                self.logger.error(f"主循环出错: {e}", "error")

            # 等待下一个周期（可中断）
            if self.running:
                self._sleep_interruptible(self.config.FETCH_INTERVAL)

        self.logger.info("调度器主循环结束", "main")

    def _fetch_platform_challenges(self) -> Optional[List[Dict]]:
        """从平台获取挑战列表（适配新 API 字段）"""
        try:
            data = self.platform.fetch_challenges()
            if data is None:
                return None

            # 将新 API 字段映射为内部格式
            challenges = []
            for c in data:
                challenges.append({
                    "code": c.get("code", ""),
                    "challenge_code": c.get("code", ""),  # 兼容字段
                    "title": c.get("title", ""),
                    "description": c.get("description", ""),
                    "difficulty": c.get("difficulty", "unknown"),
                    "level": c.get("level", 0),
                    "total_score": c.get("total_score", 0),
                    "total_got_score": c.get("total_got_score", 0),
                    "flag_count": c.get("flag_count", 0),
                    "flag_got_count": c.get("flag_got_count", 0),
                    "hint_viewed": c.get("hint_viewed", False),
                    "instance_status": c.get("instance_status", "stopped"),
                    "entrypoint": c.get("entrypoint") or [],
                })

            return challenges

        except Exception as e:
            self.logger.error(f"获取平台挑战失败: {e}", "fetch")
            return None

    def _sleep_interruptible(self, duration: float):
        """可中断的睡眠"""
        chunk_size = 0.5
        elapsed = 0
        while self.running and elapsed < duration:
            sleep_time = min(chunk_size, duration - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

    def _stop_challenge_full(self, challenge_code: str):
        """完全停止挑战：本地容器 + 平台实例"""
        # 停止本地容器
        self.container_manager.stop_challenge_containers(challenge_code)
        # 停止平台实例
        try:
            self.platform.stop_instance(challenge_code)
        except Exception as e:
            self.logger.warn(f"停止平台实例 {challenge_code} 失败: {e}", "cleanup")

    def _check_solved_challenges(self):
        """检查已解决的挑战"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            challenge_code = challenge.challenge_code
            statuses = self.container_manager.get_container_status(challenge_code)
            if not statuses:
                self.logger.info(f"挑战 {challenge_code} 的容器已停止（等待平台确认或超时）", "check")

    def _check_timeouts(self):
        """检查超时"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            if not challenge.started_at:
                continue

            if is_challenge_timeout(challenge.started_at, challenge.timeout_seconds):
                elapsed = get_elapsed_seconds(challenge.started_at)
                self.logger.warn(
                    f"挑战 {challenge.challenge_code} 超时 "
                    f"({elapsed:.0f}s > {challenge.timeout_seconds}s)",
                    "timeout"
                )
                self._transition_to_fail(challenge.challenge_code, "timeout")

    def _maintain_containers(self, platform_challenges: Optional[List[Dict]] = None):
        """维护容器健康（双层：检查平台实例 + 本地容器）"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            challenge_code = challenge.challenge_code

            # 1. 检查平台实例是否仍在运行
            instance_alive = True
            if platform_challenges:
                try:
                    pc = next((c for c in platform_challenges if c.get("code") == challenge_code), None)
                    if pc:
                        instance_status = pc.get("instance_status", "stopped")
                        if instance_status != "running":
                            instance_alive = False
                            self.logger.warn(
                                f"挑战 {challenge_code} 平台实例状态为 {instance_status}，尝试重新启动",
                                "container"
                            )
                            # 尝试重新启动平台实例
                            entrypoint = self.platform.start_instance(challenge_code)
                            if entrypoint:
                                target_url = entrypoint[0]
                                if not target_url.startswith("http"):
                                    target_url = f"http://{target_url}"
                                self.state_manager.update_state(
                                    challenge_code,
                                    STATE_STARTED,
                                    target_url=target_url,
                                    entrypoint=entrypoint,
                                    instance_status="running",
                                )
                                instance_alive = True
                                self.logger.info(f"平台实例重新启动成功: {target_url}", "container")
                            else:
                                self.logger.error(f"平台实例重新启动失败: {challenge_code}", "container")
                    else:
                        instance_alive = False
                        self.logger.warn(f"挑战 {challenge_code} 不在平台列表中", "container")
                except Exception as e:
                    self.logger.warn(f"检查平台实例状态失败: {e}", "container")

            if not instance_alive:
                # 平台实例不可用，不重建本地容器，等待超时或平台同步处理
                continue

            # 2. 检查本地容器状态
            statuses = self.container_manager.get_container_status(challenge_code)

            if not statuses:
                self.logger.warn(f"挑战 {challenge_code} 没有运行的容器，重新创建", "container")
                try:
                    # 刷新 challenge 数据（target_url 可能已更新）
                    challenge = self.state_manager.get_challenge(challenge_code) or challenge
                    container_names = self.container_manager.start_challenge_containers(
                        challenge_code=challenge_code,
                        target_url=challenge.target_url,
                        llm_configs=self.config.llm_configs,
                        description=challenge.description or "",
                        hint=challenge.hint_content or "",
                        zone=challenge.level or 1,
                    )
                    self.logger.info(f"重新创建容器成功: {container_names}", "container")
                    self.state_manager.update_state(
                        challenge_code,
                        STATE_STARTED,
                        containers=container_names
                    )
                except Exception as e:
                    self.logger.error(f"重新创建容器失败: {e}", "container")
            else:
                restarted = self.container_manager.restart_dead_containers(challenge_code)
                if restarted:
                    self.logger.info(f"重启 {len(restarted)} 个容器: {challenge_code}", "container")

    def _cleanup_finished_containers(self):
        """清理已完成状态（close、fail、success）的容器"""
        finished_states = [STATE_CLOSE, STATE_FAIL, STATE_SUCCESS]

        for state in finished_states:
            challenges = self.state_manager.get_challenges_by_state(state)
            for challenge in challenges:
                challenge_code = challenge.challenge_code
                statuses = self.container_manager.get_container_status(challenge_code)
                if statuses:
                    self.logger.info(f"清理 {state} 状态的容器: {challenge_code}", "container")
                    self._stop_challenge_full(challenge_code)

    def _start_new_challenges(self):
        """启动新挑战（双层：先启动平台实例，再启动本地容器）"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)
        running_count = len(started)

        if running_count >= self.config.MAX_PARALLEL:
            return

        open_challenges = self.state_manager.get_challenges_by_state(STATE_OPEN)
        open_challenges.sort(key=lambda c: c.fetched_at)

        for challenge in open_challenges:
            if running_count >= self.config.MAX_PARALLEL:
                break

            if self._transition_to_started(challenge):
                running_count += 1

    def _transition_to_started(self, challenge: ChallengeStateData) -> bool:
        """转换状态为 started（双层：启动平台实例 + 本地容器）"""
        challenge_code = challenge.challenge_code

        try:
            self.logger.info(f"启动挑战: {challenge_code}", "start")

            # 1. 启动平台赛题实例
            entrypoint = self.platform.start_instance(challenge_code)
            if entrypoint is None:
                self.logger.error(f"启动平台实例失败: {challenge_code}", "start")
                return False

            if not entrypoint:
                self.logger.info(f"赛题 {challenge_code} 已全部完成", "start")
                self.state_manager.update_state(
                    challenge_code,
                    STATE_SUCCESS,
                    result="already_completed"
                )
                return False

            # 构建 target_url
            target_url = entrypoint[0]
            if not target_url.startswith("http"):
                target_url = f"http://{target_url}"

            self.logger.info(f"平台实例入口: {target_url}", "start")

            # 2. 获取提示信息（启动后立即获取，扣 10% 分数但提高解题效率）
            hint_content = ""
            hint_viewed = False
            try:
                hint_content = self.platform.get_hint(challenge_code) or ""
                hint_viewed = True
                if hint_content:
                    self.logger.info(f"获取提示成功: {challenge_code}", "start")
                else:
                    self.logger.info(f"无提示内容: {challenge_code}", "start")
            except Exception as e:
                self.logger.warn(f"获取提示失败（不影响解题）: {e}", "start")

            # 3. 启动本地 Docker 容器（解题 Agent，含描述和提示）
            container_names = self.container_manager.start_challenge_containers(
                challenge_code=challenge_code,
                target_url=target_url,
                llm_configs=self.config.llm_configs,
                description=challenge.description or "",
                hint=hint_content,
                zone=challenge.level or 1,
            )

            # 4. 更新状态
            now = get_timestamp()
            self.state_manager.update_state(
                challenge_code,
                STATE_STARTED,
                started_at=now,
                containers=container_names,
                target_url=target_url,
                instance_status="running",
                entrypoint=entrypoint,
                hint_content=hint_content,
                hint_viewed=hint_viewed,
            )

            self.logger.info(
                f"挑战 {challenge_code} 已启动，入口: {target_url}，容器: {container_names}",
                "start"
            )
            return True

        except Exception as e:
            self.logger.error(f"启动挑战 {challenge_code} 失败: {e}", "start")
            # 停止可能已启动的平台实例
            try:
                self.platform.stop_instance(challenge_code)
            except Exception:
                pass
            self.state_manager.update_state(
                challenge_code,
                STATE_OPEN,
                result=f"start_failed: {e}",
                containers=[]
            )
            return False

    def _transition_to_fail(self, challenge_code: str, reason: str):
        """转换状态为 fail（同时清理平台实例和本地容器）"""
        self.logger.warn(f"挑战 {challenge_code} 失败: {reason}", "fail")
        self._stop_challenge_full(challenge_code)
        self.state_manager.update_state(
            challenge_code,
            STATE_FAIL,
            result=reason,
            containers=[]
        )

    def _transition_to_close(self, challenge_code: str):
        """转换状态为 close（同时清理平台实例和本地容器）"""
        self.logger.info(f"关闭挑战: {challenge_code}", "close")
        self._stop_challenge_full(challenge_code)
        self.state_manager.update_state(
            challenge_code,
            STATE_CLOSE,
            containers=[]
        )

    def _stop_all_containers(self):
        """停止所有容器和平台实例"""
        self.logger.info("停止所有容器和平台实例...", "shutdown")

        started = self.state_manager.get_challenges_by_state(STATE_STARTED)
        for challenge in started:
            challenge_code = challenge.challenge_code
            # 停止本地容器
            self.container_manager.stop_challenge_containers(challenge_code)
            # 停止平台实例
            try:
                self.platform.stop_instance(challenge_code)
            except Exception:
                pass
            self.logger.info(f"已停止 {challenge_code}（状态保持为 started）", "shutdown")

        cleaned = self.container_manager.cleanup_stopped_containers()
        if cleaned > 0:
            self.logger.info(f"清理 {cleaned} 个已停止的容器", "shutdown")


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="CTF 挑战调度器 - 自动化挑战解题管理"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="配置文件路径 (默认使用环境变量)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只运行一次循环然后退出"
    )

    args = parser.parse_args()

    # 加载配置
    try:
        config = SchedulerConfig.from_env()
    except Exception as e:
        print(f"[-] 加载配置失败: {e}")
        print("[-] 请检查 .env 文件和环境变量配置")
        sys.exit(1)

    # 验证 LLM 配置
    if not config.llm_configs:
        print("[-] 错误: 没有可用的 LLM 配置")
        print("[-] 请在 .env 文件中配置 LLM-1/2/3-ANTHROPIC_AUTH_TOKEN")
        sys.exit(1)

    print(f"[+] 配置加载成功:")
    print(f"    - 平台: {config.COMPETITION_API_URL}")
    print(f"    - 并行: {config.MAX_PARALLEL}")
    print(f"    - 超时: {config.TIMEOUT_SECONDS}s")
    print(f"    - LLM 数量: {len(config.llm_configs)}")
    print(f"    - 状态文件: {config.STATE_FILE}")
    print(f"    - 日志文件: {config.LOG_FILE}")

    # 创建调度器
    scheduler = ChallengeScheduler(config)

    # 运行
    try:
        if args.once:
            scheduler.logger.info("单次运行模式")
            scheduler.run()
        else:
            scheduler.start()
    except KeyboardInterrupt:
        scheduler.logger.info("用户中断")
    except Exception as e:
        scheduler.logger.error(f"调度器异常: {e}", "error")
        raise
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
