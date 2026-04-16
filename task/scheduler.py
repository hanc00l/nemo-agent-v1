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

from config import SchedulerConfig, ZONE_TIMEOUT_RATIOS, ZONE_HIGH_PARALLEL, ZONE_LOW_PARALLEL
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
    # 提示词构建
    build_task_prompt,
)


def _difficulty_order(difficulty: str) -> int:
    """难度排序权重：easy=0, medium=1, hard=2"""
    order = {"easy": 0, "medium": 1, "hard": 2}
    return order.get(difficulty, 3)


def _sort_level_key(level: int) -> int:
    """排序用 level 权重：level=0 视为最低优先级（排到最后）"""
    return -level if level > 0 else 99


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
            default_timeout=config.TIMEOUT_SECONDS,
            zone_timeout_func=self._get_zone_timeout,
        )
        self.container_manager = ContainerManager(
            docker_image=config.DOCKER_IMAGE,
            vnc_base_port=config.VNC_BASE_PORT,
            network_mode=config.NETWORK_MODE,
        )

        # 平台客户端
        self.platform = PlatformClient()

        # 题目黑名单
        self._blacklist = self._load_blacklist()
        if self._blacklist:
            self.logger.info(
                f"已加载题目黑名单 ({len(self._blacklist)} 个): {', '.join(sorted(self._blacklist))}",
                "init"
            )

        # 全局元数据跟踪
        self._global_fetched = False  # 是否已首次获取平台数据
        saved_metadata = self.state_manager.get_global_metadata()
        self._current_level: int = self._clamp_level(saved_metadata.get("current_level", 1))
        self._total_challenges: int = saved_metadata.get("total_challenges", 0)
        self._solved_challenges: int = saved_metadata.get("solved_challenges", 0)

        # 信号处理
        self.running = False
        self._shutdown = GracefulShutdown()
        self._shutdown.register(self._on_shutdown_signal)
        self._shutdown.setup()

    @staticmethod
    def _clamp_level(level: int) -> int:
        """将 current_level 限制在 0-4 范围内"""
        return max(0, min(4, level))

    def _get_zone_timeout(self, level: int) -> int:
        """根据分区计算超时时间

        Zone 0/1/2: base × 50%
        Zone 3/4: base × 300%
        """
        ratio = ZONE_TIMEOUT_RATIOS.get(level, 1.0)
        return int(self.config.BASE_TIMEOUT_SECONDS * ratio)

    def _count_started_by_zone_group(self) -> Dict[str, int]:
        """统计当前 started 题目的分区分布

        Returns:
            {"high": zone34数量, "low": zone012数量}
        """
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)
        high = sum(1 for c in started if c.level >= 3)
        low = sum(1 for c in started if c.level < 3)
        return {"high": high, "low": low}

    @staticmethod
    def _is_zone_high(level: int) -> bool:
        """判断是否为高分区（Zone 3/4）"""
        return level >= 3

    @staticmethod
    def _load_blacklist() -> set:
        """加载题目黑名单（每行一个题目代码）"""
        blacklist_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "subject_black.txt"
        )
        codes = set()
        try:
            with open(blacklist_file, "r", encoding="utf-8") as f:
                for line in f:
                    code = line.strip()
                    if code and not code.startswith("#"):
                        codes.add(code)
        except FileNotFoundError:
            pass
        return codes

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
        self.logger.info(
            f"配置: 并行={self.config.MAX_PARALLEL} (Zone3/4={ZONE_HIGH_PARALLEL} + Zone0/1/2={ZONE_LOW_PARALLEL}), "
            f"基础超时={self.config.BASE_TIMEOUT_SECONDS}s "
            f"(Zone0/1/2={self._get_zone_timeout(0)}s, Zone3/4={self._get_zone_timeout(3)}s)"
        )
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

                # 区分"平台返回空列表"和"平台正常返回数据"
                # 空列表可能是平台暂停/维护，不应触发状态降级
                if not platform_challenges:
                    self.logger.info("平台返回空题目列表，跳过同步（可能平台暂停/维护）", "fetch")
                    # 空列表时仅执行超时检查和容器维护（不依赖平台数据），跳过同步/清理/重试
                    self._check_timeouts()
                    self._maintain_containers(None)
                    self._sleep_interruptible(self.config.FETCH_INTERVAL)
                    continue

                # 2. 同步本地状态（仅在平台有数据时执行）
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

                # 3. 检查已解决的挑战（复用平台数据）
                self._check_solved_challenges(platform_challenges)

                # 4. 检查超时
                self._check_timeouts()

                # 5. 维护容器（传入平台数据避免重复请求）
                self._maintain_containers(platform_challenges)

                # 6. 清理已完成状态的容器
                self._cleanup_finished_containers()

                # 7. 启动新挑战
                self._start_new_challenges()

                # 8. 检查并重试失败的任务（传入平台数据验证）
                self._check_and_retry_failed(platform_challenges)

            except Exception as e:
                self.logger.error(f"主循环出错: {e}", "error")

            # 等待下一个周期（可中断）
            if self.running:
                self._sleep_interruptible(self.config.FETCH_INTERVAL)

        self.logger.info("调度器主循环结束", "main")

    def _fetch_platform_challenges(self) -> Optional[List[Dict]]:
        """从平台获取挑战列表（适配新 API 字段，含全局元数据跟踪）"""
        try:
            data = self.platform.fetch_challenges()
            if data is None:
                return None

            # 提取并跟踪全局元数据
            remote_level = self._clamp_level(data.get("current_level", 1))
            remote_total = data.get("total_challenges", 0)
            remote_solved = data.get("solved_challenges", 0)

            if not self._global_fetched:
                # 首次获取
                self._current_level = remote_level
                self._total_challenges = remote_total
                self._solved_challenges = remote_solved
                self._global_fetched = True
                msg = (
                    f"首次获取平台全局数据: "
                    f"当前赛区(Zone)={self._current_level}, "
                    f"总赛题数={self._total_challenges}, "
                    f"已完成={self._solved_challenges}"
                )
                print(f"[+] {msg}")
                self.logger.info(msg, "fetch")
                # 持久化到状态文件
                self.state_manager.update_global_metadata(
                    current_level=self._current_level,
                    total_challenges=self._total_challenges,
                    solved_challenges=self._solved_challenges,
                )
            else:
                # 检测变化
                changes = []
                if remote_level != self._current_level:
                    changes.append(f"赛区(Zone): {self._current_level} -> {remote_level}")
                    self._current_level = remote_level
                if remote_total != self._total_challenges:
                    changes.append(f"总赛题数: {self._total_challenges} -> {remote_total}")
                    self._total_challenges = remote_total
                if remote_solved != self._solved_challenges:
                    changes.append(f"已完成: {self._solved_challenges} -> {remote_solved}")
                    self._solved_challenges = remote_solved

                if changes:
                    change_msg = "平台全局数据变化: " + ", ".join(changes)
                    print(f"[*] {change_msg}")
                    self.logger.info(change_msg, "fetch")
                    # 持久化变化
                    self.state_manager.update_global_metadata(
                        current_level=self._current_level,
                        total_challenges=self._total_challenges,
                        solved_challenges=self._solved_challenges,
                    )

            # 将新 API 字段映射为内部格式
            raw_challenges = data.get("challenges", [])
            challenges = []
            for c in raw_challenges:
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

    def _check_solved_challenges(self, platform_challenges: Optional[List[Dict]] = None):
        """检查已解决的挑战 - 当容器停止时用平台数据确认是否已解题"""
        started = self.state_manager.get_challenges_by_state(STATE_STARTED)

        for challenge in started:
            challenge_code = challenge.challenge_code
            statuses = self.container_manager.get_container_status(challenge_code)

            # 检查是否还有运行中的容器
            has_running = any(s == "running" for s in statuses.values())

            if not statuses or not has_running:
                # 容器已停止，用已缓存的平台数据确认是否解题
                self._check_platform_solved(challenge_code, platform_challenges)

    def _check_platform_solved(self, challenge_code: str,
                                platform_challenges: Optional[List[Dict]] = None):
        """用平台数据确认挑战是否已解决，若已解决则立即关闭平台实例"""
        if not platform_challenges:
            self.logger.info(
                f"挑战 {challenge_code} 无平台数据（等待重建或超时）",
                "check"
            )
            return

        for c in platform_challenges:
            if c.get("code") == challenge_code:
                flag_got = c.get("flag_got_count", 0)
                flag_total = c.get("flag_count", 1)
                if flag_got >= flag_total:
                    self.logger.info(
                        f"挑战 {challenge_code} 平台确认已解决，立即关闭平台实例",
                        "check"
                    )
                    self._stop_challenge_full(challenge_code)
                    self.state_manager.update_state(
                        challenge_code,
                        STATE_SUCCESS,
                        result="solved_confirmed_by_platform",
                        containers=[]
                    )
                    return

        # 未解决，容器将被 _maintain_containers 重建
        self.logger.info(
            f"挑战 {challenge_code} 尚未解决（容器将由维护流程重建）",
            "check"
        )

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
                        # 题目暂不在平台列表中（可能暂停/维护）
                        # 不关闭已有容器，但也不重建（平台实例大概率不可用）
                        # 仅重启已死亡的容器（如有），等题目重新出现后恢复正常维护
                        self.logger.info(
                            f"挑战 {challenge_code} 暂不在平台列表中，仅重启已有容器",
                            "container"
                        )
                        # 检查本地容器状态，只重启不重建
                        statuses = self.container_manager.get_container_status(challenge_code)
                        if statuses:
                            restarted = self.container_manager.restart_dead_containers(challenge_code)
                            if restarted:
                                self.logger.info(f"重启 {len(restarted)} 个容器: {challenge_code}", "container")
                        # 跳过后续的平台实例检查和容器重建逻辑
                        continue
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
                        zone=challenge.level,
                        flag_count=challenge.flag_count or 1,
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

    def _check_and_retry_failed(self, platform_challenges: Optional[List[Dict]] = None):
        """检查是否需要重试失败的任务（分区调度：Zone 3/4 优先占 2 槽位，Zone 0/1/2 占 1 槽位，允许互借）"""
        # 1. 检查前提：无 open 状态的题目（新题目优先处理）
        open_challenges = self.state_manager.get_challenges_by_state(STATE_OPEN)
        # 过滤黑名单题目（黑名单 OPEN 不会启动，不应阻塞重试）
        if self._blacklist:
            open_challenges = [c for c in open_challenges if c.challenge_code not in self._blacklist]
        if open_challenges:
            return

        # 2. 统计当前 started 按分区分组，计算可用重试槽位
        zone_counts = self._count_started_by_zone_group()
        total_running = zone_counts["high"] + zone_counts["low"]

        if total_running >= self.config.MAX_PARALLEL:
            return

        high_slots = max(0, ZONE_HIGH_PARALLEL - zone_counts["high"])
        low_slots = max(0, ZONE_LOW_PARALLEL - zone_counts["low"])

        # 3. 获取所有失败的题目
        failed_challenges = self.state_manager.get_challenges_by_state(STATE_FAIL)
        # 过滤黑名单题目
        if self._blacklist:
            failed_challenges = [c for c in failed_challenges if c.challenge_code not in self._blacklist]
        if not failed_challenges:
            return

        # 3.5 验证失败题目在平台上的状态：存在且未解决的才重试
        if platform_challenges:
            platform_map = {c.get("code", ""): c for c in platform_challenges}
            valid_failed = []
            for c in failed_challenges:
                code = c.challenge_code
                pc = platform_map.get(code)
                if pc is None:
                    self.logger.info(
                        f"挑战 {code} 暂不在平台列表中，本轮跳过重试", "retry"
                    )
                    continue
                flag_got = pc.get("flag_got_count", 0)
                flag_total = pc.get("flag_count", 1)
                if flag_got >= flag_total:
                    self.logger.info(
                        f"挑战 {code} 平台确认已解决（重试前检测），不再重试", "retry"
                    )
                    self.state_manager.update_state(code, STATE_SUCCESS, result="solved_confirmed_on_retry")
                    continue
                valid_failed.append(c)
            failed_challenges = valid_failed
            if not failed_challenges:
                return

        # 4. 过滤可重试的（retry_num < TASK_RETRY_MAX）
        retryable = [c for c in failed_challenges if c.retry_num < self.config.TASK_RETRY_MAX]

        if not retryable:
            newly_exhausted = [c for c in failed_challenges
                               if c.retry_num == self.config.TASK_RETRY_MAX]
            for c in newly_exhausted:
                self.logger.info(
                    f"挑战 {c.challenge_code} 已达最大重试次数 "
                    f"({c.retry_num}/{self.config.TASK_RETRY_MAX})，放弃",
                    "retry"
                )
                self.state_manager.update_state(
                    c.challenge_code,
                    STATE_FAIL,
                    retry_num=self.config.TASK_RETRY_MAX + 1,
                )
            return

        # 5. 按 retry_num 升序，同 retry_num 按 level 降序 → 难度升序
        retryable.sort(key=lambda c: (c.retry_num, _sort_level_key(c.level), _difficulty_order(c.difficulty)))

        # 6. 分区分配重试槽位
        high_retryable = [c for c in retryable if self._is_zone_high(c.level)]
        low_retryable = [c for c in retryable if not self._is_zone_high(c.level)]

        to_retry = []

        # 第一轮：按分区严格分配
        to_retry.extend(high_retryable[:high_slots])
        to_retry.extend(low_retryable[:low_slots])

        # 第二轮：互借剩余槽位（总上限 MAX_PARALLEL）
        already_selected = {c.challenge_code for c in to_retry}
        remaining_slots = self.config.MAX_PARALLEL - total_running - len(to_retry)
        if remaining_slots > 0:
            for c in retryable:
                if remaining_slots <= 0:
                    break
                if c.challenge_code not in already_selected:
                    to_retry.append(c)
                    already_selected.add(c.challenge_code)
                    remaining_slots -= 1

        # 7. 重置状态为 open，retry_num + 1
        for challenge in to_retry:
            new_retry = challenge.retry_num + 1
            self.state_manager.update_state(
                challenge.challenge_code,
                STATE_OPEN,
                retry_num=new_retry,
                result=None,
                started_at=None,
                containers=[],
            )
            self.logger.info(
                f"重试题目 {challenge.challenge_code} (第 {new_retry}/{self.config.TASK_RETRY_MAX} 次, "
                f"Zone {challenge.level}, 难度: {challenge.difficulty})",
                "retry"
            )

    def _start_new_challenges(self):
        """启动新挑战（分区调度：Zone 3/4 优先占 2 槽位，Zone 0/1/2 占 1 槽位，允许互借）"""
        zone_counts = self._count_started_by_zone_group()
        total_running = zone_counts["high"] + zone_counts["low"]

        if total_running >= self.config.MAX_PARALLEL:
            return

        open_challenges = self.state_manager.get_challenges_by_state(STATE_OPEN)
        # 过滤黑名单题目
        if self._blacklist:
            open_challenges = [c for c in open_challenges if c.challenge_code not in self._blacklist]
        open_challenges.sort(key=lambda c: (_sort_level_key(c.level), _difficulty_order(c.difficulty), c.fetched_at))

        if not open_challenges:
            return

        # 计算各分区可用槽位
        high_slots = max(0, ZONE_HIGH_PARALLEL - zone_counts["high"])
        low_slots = max(0, ZONE_LOW_PARALLEL - zone_counts["low"])

        # 分区启动：先按分区槽位分配，再互借剩余
        started_count = 0

        # 第一轮：按分区严格分配
        for challenge in open_challenges:
            if total_running + started_count >= self.config.MAX_PARALLEL:
                break

            is_high = self._is_zone_high(challenge.level)
            if is_high and high_slots > 0:
                if self._transition_to_started(challenge):
                    started_count += 1
                    high_slots -= 1
            elif not is_high and low_slots > 0:
                if self._transition_to_started(challenge):
                    started_count += 1
                    low_slots -= 1

        # 第二轮：互借剩余槽位（总上限 MAX_PARALLEL）
        remaining_slots = self.config.MAX_PARALLEL - total_running - started_count
        if remaining_slots > 0:
            # 重新获取未启动的 open 题目
            open_challenges = self.state_manager.get_challenges_by_state(STATE_OPEN)
            if self._blacklist:
                open_challenges = [c for c in open_challenges if c.challenge_code not in self._blacklist]
            open_challenges.sort(key=lambda c: (_sort_level_key(c.level), _difficulty_order(c.difficulty), c.fetched_at))

            for challenge in open_challenges:
                if remaining_slots <= 0:
                    break
                if self._transition_to_started(challenge):
                    started_count += 1
                    remaining_slots -= 1

        if started_count > 0:
            zone_counts_after = self._count_started_by_zone_group()
            self.logger.info(
                f"本轮启动 {started_count} 个新挑战 "
                f"(Zone3/4: {zone_counts['high']}→{zone_counts_after['high']}, "
                f"Zone0/1/2: {zone_counts['low']}→{zone_counts_after['low']})",
                "start"
            )

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

            # 3. 输出题目信息和提示词
            challenge_info = (
                f"========== 启动解题 ==========\n"
                f"题目: {challenge.title} ({challenge_code})\n"
                f"难度: {challenge.difficulty} | 赛区: Zone {challenge.level} | "
                f"Flag数: {challenge.flag_count or 1}\n"
                f"目标: {target_url}\n"
                f"描述: {challenge.description or '无'}\n"
                f"提示: {hint_content or '无'}"
            )
            self.logger.info(challenge_info, "start")

            task_prompt = build_task_prompt(
                target_url, challenge_code,
                competition_mode=True,
                description=challenge.description or "",
                hint=hint_content,
                zone=challenge.level,
                flag_count=challenge.flag_count or 1,
            )
            self.logger.info(f"提示词:\n{task_prompt}", "start")

            # 4. 启动本地 Docker 容器（解题 Agent，含描述和提示）
            container_names = self.container_manager.start_challenge_containers(
                challenge_code=challenge_code,
                target_url=target_url,
                llm_configs=self.config.llm_configs,
                description=challenge.description or "",
                hint=hint_content,
                zone=challenge.level,
                flag_count=challenge.flag_count or 1,
            )

            # 5. 更新状态
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
                timeout_seconds=self._get_zone_timeout(challenge.level),
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
                STATE_FAIL,
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
    parser.add_argument(
        "--reset-retry",
        action="store_true",
        help="重置所有非 success 试题的 retry_num 为 0"
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
    print(f"    - 并行: {config.MAX_PARALLEL} (Zone3/4={ZONE_HIGH_PARALLEL} + Zone0/1/2={ZONE_LOW_PARALLEL})")
    print(f"    - 基础超时: {config.BASE_TIMEOUT_SECONDS}s "
          f"(Zone0/1/2={int(config.BASE_TIMEOUT_SECONDS * ZONE_TIMEOUT_RATIOS[0])}s, "
          f"Zone3/4={int(config.BASE_TIMEOUT_SECONDS * ZONE_TIMEOUT_RATIOS[3])}s)")
    print(f"    - LLM 数量: {len(config.llm_configs)}")
    print(f"    - 状态文件: {config.STATE_FILE}")
    print(f"    - 日志文件: {config.LOG_FILE}")

    # 处理 --reset-retry 参数
    if args.reset_retry:
        print(f"[!] --reset-retry 将重置所有非 success 试题的 retry_num 为 0")
        confirm = input("[?] 确认执行？(y/N): ").strip().lower()
        if confirm != "y":
            print("[-] 已取消重置，退出")
            sys.exit(0)
        state_manager = ChallengeStateManager(
            config.STATE_FILE,
            default_timeout=config.TIMEOUT_SECONDS
        )
        count = state_manager.reset_retry_for_non_success()
        print(f"[+] 已重置 {count} 个非 success 试题的 retry_num 为 0")
        scheduler_logger = SchedulerLogger("scheduler", config.LOG_FILE)
        scheduler_logger.info(f"--reset-retry: 重置了 {count} 个非 success 试题的 retry_num", "init")

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
