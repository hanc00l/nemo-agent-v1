"""
Scheduler - CTF 挑战调度器

自动从竞赛平台获取挑战，管理容器生命周期，监控超时和容器健康。
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
    """CTF 挑战调度器"""

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

        # PID 文件路径
        pid_file_path = os.path.join(
            os.path.dirname(self.config.STATE_FILE),
            "scheduler.pid"
        )

        try:
            # 打开/创建 PID 文件
            self._pid_file = open(pid_file_path, "w")
            # 尝试获取排他锁（非阻塞）
            fcntl.flock(self._pid_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # 写入当前 PID
            self._pid_file.write(str(os.getpid()))
            self._pid_file.flush()
            self._pid_lock = True
            self.logger.info(f"PID 文件锁已获取: {pid_file_path}", "init")
        except IOError:
            # 锁获取失败，说明已有实例在运行
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
                # 关闭文件会自动释放锁
                self._pid_file.close()
                # 删除 PID 文件
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

        # 停止所有容器
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
                platform_challenges = self.platform.fetch_challenges()
                if platform_challenges is None:
                    # 网络错误，等待后重试
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
                    # 立即清理已解决挑战的容器
                    for challenge_code in sync_result["solved"]:
                        self.container_manager.stop_challenge_containers(challenge_code)
                        self.logger.info(f"已清理挑战 {challenge_code} 的容器", "cleanup")
                if sync_result["recovered"]:
                    self.logger.info(f"恢复 {len(sync_result['recovered'])} 个挑战", "fetch")

                # 3. 检查已解决的挑战
                self._check_solved_challenges()

                # 4. 检查超时
                self._check_timeouts()

                # 5. 维护容器
                self._maintain_containers()

                # 6. 清理已完成状态的容器
                self._cleanup_finished_containers()

                # 7. 启动新挑战
                self._start_new_challenges()

                # 7. 清理旧的已完成挑战 (已禁用 - 永久保留所有记录)
                # removed = self.state_manager.cleanup_old_challenges(max_age_hours=24)
                # if removed > 0:
                #     self.logger.info(f"清理 {removed} 个旧挑战", "cleanup")

            except Exception as e:
                self.logger.error(f"主循环出错: {e}", "error")

            # 等待下一个周期（可中断）
            if self.running:
                self._sleep_interruptible(self.config.FETCH_INTERVAL)

        self.logger.info("调度器主循环结束", "main")

    def _sleep_interruptible(self, duration: float):
        """
        可中断的睡眠

        Args:
            duration: 睡眠时长（秒）
        """
        # 将睡眠分成小块，每块检查运行状态
        chunk_size = 0.5  # 每500ms检查一次
        elapsed = 0
        while self.running and elapsed < duration:
            sleep_time = min(chunk_size, duration - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

    def _check_solved_challenges(self):
        """检查已解决的挑战"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            challenge_code = challenge.challenge_code

            # 检查容器是否还在运行
            statuses = self.container_manager.get_container_status(challenge_code)
            if not statuses:
                # 所有容器都已停止
                # 注意：容器停止不代表任务失败，可能只是正常结束
                # 不要自动标记为失败，让超时检查和平台同步来处理
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

    def _maintain_containers(self):
        """维护容器健康"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            challenge_code = challenge.challenge_code

            # 检查容器状态
            statuses = self.container_manager.get_container_status(challenge_code)

            if not statuses:
                # 没有容器，需要重新创建
                self.logger.warn(f"挑战 {challenge_code} 没有运行的容器，重新创建", "container")
                try:
                    container_names = self.container_manager.start_challenge_containers(
                        challenge_code=challenge_code,
                        target_url=challenge.target_url,
                        llm_configs=self.config.llm_configs
                    )
                    self.logger.info(f"重新创建容器成功: {container_names}", "container")
                    # 更新容器列表
                    self.state_manager.update_state(
                        challenge_code,
                        STATE_STARTED,
                        containers=container_names
                    )
                except Exception as e:
                    self.logger.error(f"重新创建容器失败: {e}", "container")
            else:
                # 有容器，尝试重启已停止的
                restarted = self.container_manager.restart_dead_containers(challenge_code)
                if restarted:
                    self.logger.info(f"重启 {len(restarted)} 个容器: {challenge_code}", "container")

    def _cleanup_finished_containers(self):
        """清理已完成状态（close、fail、success）的容器"""
        # 检查 close、fail、success 状态
        finished_states = [STATE_CLOSE, STATE_FAIL, STATE_SUCCESS]

        for state in finished_states:
            challenges = self.state_manager.get_challenges_by_state(state)
            for challenge in challenges:
                challenge_code = challenge.challenge_code

                # 检查是否还有容器在运行
                statuses = self.container_manager.get_container_status(challenge_code)
                if statuses:
                    # 有容器还在运行，需要清理
                    self.logger.info(f"清理 {state} 状态的容器: {challenge_code}", "container")
                    self.container_manager.stop_challenge_containers(challenge_code)

    def _start_new_challenges(self):
        """启动新挑战"""
        # 获取当前运行中的数量
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)
        running_count = len(started)

        if running_count >= self.config.MAX_PARALLEL:
            return

        # 获取待处理的挑战，按获取时间排序
        open_challenges = self.state_manager.get_challenges_by_state(STATE_OPEN)
        open_challenges.sort(key=lambda c: c.fetched_at)

        # 启动新挑战
        for challenge in open_challenges:
            if running_count >= self.config.MAX_PARALLEL:
                break

            if self._transition_to_started(challenge):
                running_count += 1

    def _transition_to_started(self, challenge: ChallengeStateData) -> bool:
        """转换状态为 started"""
        challenge_code = challenge.challenge_code

        try:
            self.logger.info(f"启动挑战: {challenge_code}", "start")

            # 启动容器
            container_names = self.container_manager.start_challenge_containers(
                challenge_code=challenge_code,
                target_url=challenge.target_url,
                llm_configs=self.config.llm_configs
            )

            # 更新状态
            now = get_timestamp()
            self.state_manager.update_state(
                challenge_code,
                STATE_STARTED,
                started_at=now,
                containers=container_names
            )

            self.logger.info(
                f"挑战 {challenge_code} 已启动，容器: {container_names}",
                "start"
            )
            return True

        except Exception as e:
            self.logger.error(f"启动挑战 {challenge_code} 失败: {e}", "start")
            # 容器启动失败时不立即标记为 fail，保持 open 状态等待重试
            # 只记录失败信息到 result 字段
            self.state_manager.update_state(
                challenge_code,
                STATE_OPEN,  # 保持 open 状态
                result=f"start_failed: {e}",
                containers=[]  # 清空容器列表
            )
            return False

    def _transition_to_fail(self, challenge_code: str, reason: str):
        """转换状态为 fail"""
        self.logger.warn(f"挑战 {challenge_code} 失败: {reason}", "fail")

        # 停止容器
        self.container_manager.stop_challenge_containers(challenge_code)

        # 更新状态
        self.state_manager.update_state(
            challenge_code,
            STATE_FAIL,
            result=reason,
            containers=[]
        )

    def _transition_to_close(self, challenge_code: str):
        """转换状态为 close"""
        self.logger.info(f"关闭挑战: {challenge_code}", "close")

        # 停止容器
        self.container_manager.stop_challenge_containers(challenge_code)

        # 更新状态
        self.state_manager.update_state(
            challenge_code,
            STATE_CLOSE,
            containers=[]
        )

    def _stop_all_containers(self):
        """停止所有容器"""
        self.logger.info("停止所有容器...", "shutdown")

        # 停止所有 started 挑战的容器，但不改变状态
        # 这样调度器重启后可以继续处理这些挑战
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)
        for challenge in started:
            challenge_code = challenge.challenge_code
            # 只停止容器，保持状态为 started
            # 调度器重启后会检测到容器已停止，可以重新启动
            self.container_manager.stop_challenge_containers(challenge_code)
            self.logger.info(f"已停止 {challenge_code} 的容器（状态保持为 started）", "shutdown")

        # 清理已停止的容器
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
            # 只运行一次
            scheduler.logger.info("单次运行模式")
            scheduler.run()
        else:
            # 持续运行
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
