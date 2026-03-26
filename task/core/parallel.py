"""
Parallel - 并行执行管理

提供多 LLM 并行执行任务的公共功能。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass, field


@dataclass
class ParallelResult:
    """并行执行结果"""
    success: bool
    winner_index: Optional[int] = None  # 成功的 runner 索引
    results: List[Any] = field(default_factory=list)
    error: Optional[str] = None


class ParallelExecutor:
    """并行执行器 - 管理多个并行 Runner"""

    def __init__(
        self,
        configs: List[Dict],
        target: str,
        challenge_code: str,
        runner_factory: Callable,
        competition_mode: bool = False,
    ):
        """
        初始化并行执行器

        Args:
            configs: LLM 配置列表
            target: 目标 URL
            challenge_code: 挑战代码
            runner_factory: Runner 工厂函数，签名为 (llm_config, llm_id, target, challenge_code, competition_mode) -> Runner
            competition_mode: 是否为竞赛模式
        """
        self.configs = configs
        self.target = target
        self.challenge_code = challenge_code
        self.runner_factory = runner_factory
        self.competition_mode = competition_mode
        self.runners: List[Any] = []
        self.stop_event = threading.Event()
        self.success = False
        self.result = None
        self.lock = threading.Lock()

    def create_runners(self) -> List[Any]:
        """
        创建所有 Runner

        Returns:
            创建成功的 Runner 列表
        """
        runners = []
        for config in self.configs:
            try:
                runner = self.runner_factory(
                    llm_config=config,
                    llm_id=config.get("id", 0),
                    target=self.target,
                    challenge_code=self.challenge_code,
                    competition_mode=self.competition_mode
                )
                runners.append(runner)
            except Exception as e:
                llm_id = config.get("id", "unknown")
                print(f"[-] 创建 LLM-{llm_id} Runner 失败: {e}")
        return runners

    def execute_task_on_runner(
        self,
        runner: Any,
        task: str,
        execute_method: str = "run_task"
    ) -> Optional[Dict]:
        """
        在单个 Runner 中执行任务

        Args:
            runner: Runner 对象
            task: 任务字符串
            execute_method: 执行方法名

        Returns:
            执行结果字典
        """
        method = getattr(runner, execute_method, None)
        if method is None:
            return None
        return method(task, self.stop_event)

    def execute_tasks(
        self,
        task: str,
        execute_method: str = "run_task",
        get_log_prefix: Callable = lambda r: getattr(r, "log_prefix", ""),
        stop_on_first_success: bool = False,
    ) -> ParallelResult:
        """
        并行执行任务，收集所有 Runner 的执行结果

        Args:
            task: 任务字符串
            execute_method: 执行方法名
            get_log_prefix: 获取日志前缀的函数
            stop_on_first_success: 是否在首次成功时停止其他任务（默认 False，等待全部完成）

        Returns:
            ParallelResult 对象
        """
        print(f"[+] 并行执行 {len(self.runners)} 个 LLM Runner...")
        print(f"[+] 任务: {task}")
        print(f"[+] 停止策略: {'首次成功即停止' if stop_on_first_success else '等待全部完成'}")

        results = []
        first_success_log = False

        with ThreadPoolExecutor(max_workers=len(self.runners)) as executor:
            # 提交所有任务
            future_to_runner = {
                executor.submit(self.execute_task_on_runner, runner, task, execute_method): runner
                for runner in self.runners
            }

            # 处理完成的任务
            for future in as_completed(future_to_runner):
                runner = future_to_runner[future]

                # 检查是否需要跳过（仅在启用 stop_on_first_success 且已有成功时）
                if stop_on_first_success and self.stop_event.is_set():
                    continue

                try:
                    result = future.result()

                    # 记录结果
                    if result:
                        runner_index = self.runners.index(runner)
                        results.append((runner_index, result))

                        # 检查是否成功
                        if result.get("success"):
                            log_prefix = get_log_prefix(runner)

                            # 首次发现成功时记录
                            if not self.success:
                                with self.lock:
                                    if not self.success:
                                        print(f"[+] {log_prefix} 解题执行结束！")
                                        self.success = True
                                        self.result = result
                                        if stop_on_first_success:
                                            self.stop_event.set()
                                            print(f"[+] 通知其他 Runner 停止...")
                                        else:
                                            print(f"[+] 等待其他 Runner 执行完成...")

                except Exception as e:
                    log_prefix = get_log_prefix(runner)
                    print(f"[-] {log_prefix} 执行异常: {e}")

        print(f"[+] 所有 Runner 执行完成，共收集 {len(results)} 个结果")

        # 返回结果
        winner_index = None
        if self.success and self.result:
            # 找到成功的 runner
            for idx, (_, r) in enumerate(results):
                if r == self.result:
                    winner_index = idx
                    break

        return ParallelResult(
            success=self.success,
            winner_index=winner_index,
            results=[r for _, r in results],
        )

    def cleanup_all(self, cleanup_method: str = "cleanup") -> None:
        """
        清理所有 Runner

        Args:
            cleanup_method: 清理方法名
        """
        print(f"[+] 清理所有 Runner...")
        for runner in self.runners:
            method = getattr(runner, cleanup_method, None)
            if method:
                method()
