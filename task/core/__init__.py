"""
Core - 核心模块

提供 LLM 配置管理、容器创建、Runner 基础功能、日志记录和平台访问。
"""
from .llm import load_llm_configs, LLMConfig, to_dict_list
from .container import (
    create_challenge_container,
    get_vnc_port,
    get_container_name,
    build_task_prompt,
    get_notes_dir,
)
from .runner import (
    TaskResult,
    get_log_prefix,
    get_docker_image,
    get_vnc_base_port,
    create_docker_client,
    verify_docker_image,
    verify_container_running,
    wait_for_mcp_service,
    execute_claude_task,
    execute_task_with_stop_check,
    cleanup_container,
    get_container_logs,
)
from .parallel import ParallelExecutor, ParallelResult
from .state import (
    ChallengeState,
    STATE_OPEN,
    STATE_STARTED,
    STATE_SUCCESS,
    STATE_FAIL,
    STATE_CLOSE,
    TimeoutInfo,
    is_challenge_timeout,
    get_elapsed_seconds,
    get_timestamp,
)
from .logger import Logger, SchedulerLogger
from .platform import PlatformClient, PlatformConfig
from .signal import GracefulShutdown, setup_signal_handler

__all__ = [
    # LLM
    "load_llm_configs",
    "LLMConfig",
    "to_dict_list",
    # Container
    "create_challenge_container",
    "get_vnc_port",
    "get_vnc_base_port",
    "get_container_name",
    "build_task_prompt",
    "get_notes_dir",
    # Runner
    "TaskResult",
    "get_log_prefix",
    "get_docker_image",
    "create_docker_client",
    "verify_docker_image",
    "verify_container_running",
    "wait_for_mcp_service",
    "execute_claude_task",
    "execute_task_with_stop_check",
    "cleanup_container",
    "get_container_logs",
    # Parallel
    "ParallelExecutor",
    "ParallelResult",
    # State
    "ChallengeState",
    "STATE_OPEN",
    "STATE_STARTED",
    "STATE_SUCCESS",
    "STATE_FAIL",
    "STATE_CLOSE",
    "TimeoutInfo",
    "is_challenge_timeout",
    "get_elapsed_seconds",
    "get_timestamp",
    # Logger
    "Logger",
    "SchedulerLogger",
    # Platform
    "PlatformClient",
    "PlatformConfig",
    # Signal
    "GracefulShutdown",
    "setup_signal_handler",
]
