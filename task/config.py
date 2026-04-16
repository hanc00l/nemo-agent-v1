"""
Configuration - 配置管理

从环境变量加载调度器配置，提供默认值和验证。
"""
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any

# 导入核心模块
from core import load_llm_configs, to_dict_list

# 分区超时倍率：Zone 0/1/2 = 50%, Zone 3/4 = 300%
ZONE_TIMEOUT_RATIOS = {0: 0.5, 1: 0.5, 2: 0.5, 3: 3.0, 4: 3.0}

# 分区并行槽位：Zone 3/4 = 2 个, Zone 1/2 = 1 个
ZONE_HIGH_PARALLEL = 2  # Zone 3/4
ZONE_LOW_PARALLEL = 1   # Zone 1/2


@dataclass
class SchedulerConfig:
    """调度器配置"""

    # Scheduler settings
    FETCH_INTERVAL: int = 60          # Platform fetch interval (seconds)
    MAX_PARALLEL: int = 3             # Max concurrent challenges (固定为 3)
    BASE_TIMEOUT_SECONDS: int = 3600  # 基础超时时间（分区按倍率调整）
    TIMEOUT_SECONDS: int = 3600       # Per-challenge timeout (兼容旧字段)

    # Platform settings
    COMPETITION_API_URL: str = "http://host.docker.internal"
    AGENT_TOKEN: str = ""             # Agent Token for API auth

    # Container settings
    DOCKER_IMAGE: str = "nemo-agent/sandbox:1.0"
    MAX_LLM: int = 3                  # Number of LLM agents per challenge
    VNC_BASE_PORT: int = 55900        # VNC port = VNC_BASE_PORT + llm_id
    NETWORK_MODE: str = "bridge"      # Docker 网络模式

    # Retry settings
    TASK_RETRY_MAX: int = 3           # Max retry count per failed challenge

    # Storage paths (相对路径，基于 task 目录)
    STATE_FILE: str = "data/subjects.json"
    LOG_FILE: str = "data/scheduler.log"

    # LLM configs (loaded from environment)
    llm_configs: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """验证配置"""
        # MAX_PARALLEL 强制为 3（分区调度需要 2+1=3）
        if self.MAX_PARALLEL != 3:
            import warnings
            warnings.warn(
                f"MAX_PARALLEL={self.MAX_PARALLEL} 被强制设为 3（分区调度策略需要）"
            )
            object.__setattr__(self, 'MAX_PARALLEL', 3)
        if self.MAX_LLM < 1 or self.MAX_LLM > 3:
            raise ValueError("MAX_LLM must be between 1 and 3")
        if self.BASE_TIMEOUT_SECONDS < 60:
            raise ValueError("BASE_TIMEOUT_SECONDS must be at least 60")

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        """从环境变量加载配置"""
        load_dotenv()

        # Basic settings
        fetch_interval = int(os.getenv("FETCH_INTERVAL", "60"))
        max_parallel = 3  # 固定为 3，分区调度策略需要
        base_timeout_seconds = int(os.getenv("TIMEOUT_SECONDS", "3600"))
        timeout_seconds = base_timeout_seconds  # 兼容旧字段
        competition_api_url = os.getenv("COMPETITION_API_URL", "http://host.docker.internal")
        agent_token = os.getenv("AGENT_TOKEN", "") or os.getenv("COMPETITION_API_TOKEN", "")

        # Container settings
        docker_image = os.getenv("DOCKER_IMAGE", "nemo-agent/sandbox:1.0")
        max_llm = int(os.getenv("MAX_LLM", "3"))
        vnc_base_port = int(os.getenv("VNC_BASE_PORT", "55900"))

        # Storage paths (相对路径)
        state_file = os.getenv("STATE_FILE", "data/subjects.json")
        log_file = os.getenv("LOG_FILE", "data/scheduler.log")

        # Retry settings
        task_retry_max = int(os.getenv("TASK_RETRY_MAX", "3"))

        # Load LLM configs (使用 core 模块)
        llm_config_objs = load_llm_configs(max_llm)
        llm_configs = to_dict_list(llm_config_objs)

        # Network settings
        network_mode = os.getenv("NETWORK_MODE", "bridge")

        return cls(
            FETCH_INTERVAL=fetch_interval,
            MAX_PARALLEL=max_parallel,
            BASE_TIMEOUT_SECONDS=base_timeout_seconds,
            TIMEOUT_SECONDS=timeout_seconds,
            COMPETITION_API_URL=competition_api_url,
            AGENT_TOKEN=agent_token,
            DOCKER_IMAGE=docker_image,
            MAX_LLM=max_llm,
            VNC_BASE_PORT=vnc_base_port,
            NETWORK_MODE=network_mode,
            STATE_FILE=state_file,
            LOG_FILE=log_file,
            TASK_RETRY_MAX=task_retry_max,
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
