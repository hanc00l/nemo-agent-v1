"""
LLM - LLM 配置管理

从环境变量加载和管理 LLM 配置。
"""
import os
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class LLMConfig:
    """LLM 配置"""
    id: int
    base_url: str
    auth_token: str
    model: str

    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return bool(self.auth_token)

    @classmethod
    def from_env(cls, llm_id: int) -> "LLMConfig":
        """从环境变量创建 LLM 配置"""
        prefix = f"LLM-{llm_id}-"
        return cls(
            id=llm_id,
            base_url=os.getenv(f"{prefix}ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            auth_token=os.getenv(f"{prefix}ANTHROPIC_AUTH_TOKEN", ""),
            model=os.getenv(f"{prefix}ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        )


def load_llm_configs(max_llm: int) -> List[LLMConfig]:
    """
    从环境变量加载 LLM 配置

    Args:
        max_llm: 最大 LLM 数量

    Returns:
        有效的 LLM 配置列表
    """
    configs = []
    for i in range(1, max_llm + 1):
        config = LLMConfig.from_env(i)
        if config.is_valid():
            configs.append(config)
        else:
            print(f"[-] 警告: LLM-{i} 未配置 AUTH_TOKEN，跳过")
    return configs


def to_dict_list(configs: List[LLMConfig]) -> List[Dict[str, Any]]:
    """将 LLMConfig 列表转换为字典列表"""
    return [
        {
            "id": c.id,
            "base_url": c.base_url,
            "auth_token": c.auth_token,
            "model": c.model,
        }
        for c in configs
    ]
