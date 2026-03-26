"""
Configuration - 配置管理

从环境变量加载调度器配置，提供默认值和验证。
"""
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any

# 导入核心模块
from core import load_llm_configs, to_dict_list


@dataclass
class SchedulerConfig:
    """调度器配置"""

    # Scheduler settings
    FETCH_INTERVAL: int = 60          # Platform fetch interval (seconds)
    MAX_PARALLEL: int = 3             # Max concurrent challenges
    TIMEOUT_SECONDS: int = 3600       # Per-challenge timeout

    # Platform settings
    COMPETITION_API_URL: str = "http://172.17.103.95:8888"

    # Container settings
    DOCKER_IMAGE: str = "nemo-agent/sandbox:1.1"
    MAX_LLM: int = 3                  # Number of LLM agents per challenge
    VNC_BASE_PORT: int = 55900        # VNC port = VNC_BASE_PORT + llm_id

    # Storage paths (相对路径，基于 task 目录)
    STATE_FILE: str = "data/subjects.json"
    LOG_FILE: str = "data/scheduler.log"

    # LLM configs (loaded from environment)
    llm_configs: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """验证配置"""
        if self.MAX_PARALLEL < 1:
            raise ValueError("MAX_PARALLEL must be at least 1")
        if self.MAX_LLM < 1 or self.MAX_LLM > 3:
            raise ValueError("MAX_LLM must be between 1 and 3")
        if self.TIMEOUT_SECONDS < 60:
            raise ValueError("TIMEOUT_SECONDS must be at least 60")

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        """从环境变量加载配置"""
        load_dotenv()

        # Basic settings
        fetch_interval = int(os.getenv("FETCH_INTERVAL", "60"))
        max_parallel = int(os.getenv("MAX_PARALLEL", "3"))
        timeout_seconds = int(os.getenv("TIMEOUT_SECONDS", "3600"))
        competition_api_url = os.getenv("COMPETITION_API_URL", "http://172.17.103.95:8888")

        # Container settings
        docker_image = os.getenv("DOCKER_IMAGE", "nemo-agent/sandbox:1.1")
        max_llm = int(os.getenv("MAX_LLM", "3"))
        vnc_base_port = int(os.getenv("VNC_BASE_PORT", "55900"))

        # Storage paths (相对路径)
        state_file = os.getenv("STATE_FILE", "data/subjects.json")
        log_file = os.getenv("LOG_FILE", "data/scheduler.log")

        # Load LLM configs (使用 core 模块)
        llm_config_objs = load_llm_configs(max_llm)
        llm_configs = to_dict_list(llm_config_objs)

        return cls(
            FETCH_INTERVAL=fetch_interval,
            MAX_PARALLEL=max_parallel,
            TIMEOUT_SECONDS=timeout_seconds,
            COMPETITION_API_URL=competition_api_url,
            DOCKER_IMAGE=docker_image,
            MAX_LLM=max_llm,
            VNC_BASE_PORT=vnc_base_port,
            STATE_FILE=state_file,
            LOG_FILE=log_file,
            llm_configs=llm_configs
        )


def load_dotenv():
    """加载 .env 文件（优先使用相对路径）"""
    try:
        from dotenv import load_dotenv as _load_dotenv
        # 尝试从多个可能的路径加载（相对路径优先）
        env_paths = [
            ".env",                    # 当前目录
            "task/.env",              # 从项目根目录
            ".env.task",              # 备用名称
        ]
        for path in env_paths:
            if os.path.exists(path):
                _load_dotenv(path)
                print(f"[+] 已加载环境变量配置文件: {path}")
                return
    except ImportError:
        pass
    except Exception as e:
        print(f"[-] 加载 .env 文件时出错: {e}")
