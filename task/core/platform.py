"""
Platform - 竞赛平台 API 客户端

提供从竞赛平台获取挑战的功能。
"""
import os
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class PlatformConfig:
    """平台配置"""
    api_url: str
    timeout: int = 30
    token: Optional[str] = None

    @classmethod
    def from_env(cls) -> "PlatformConfig":
        """从环境变量加载配置"""
        return cls(
            api_url=os.getenv("COMPETITION_API_URL", "http://172.17.103.95:8888"),
            timeout=int(os.getenv("API_TIMEOUT", "30")),
            token=os.getenv("COMPETITION_API_TOKEN"),
        )


class PlatformClient:
    """竞赛平台 API 客户端"""

    def __init__(self, config: Optional[PlatformConfig] = None):
        """
        初始化平台客户端

        Args:
            config: 平台配置，默认从环境变量加载
        """
        self.config = config or PlatformConfig.from_env()

    def fetch_challenges(self, refresh: bool = True) -> Optional[List[Dict]]:
        """
        从平台获取挑战列表

        Args:
            refresh: 是否强制刷新

        Returns:
            挑战列表，失败时返回 None
        """
        try:
            import requests

            url = f"{self.config.api_url}/api/v1/challenges"
            headers = {"Content-Type": "application/json", "Accept": "application/json"}

            if self.config.token:
                headers["Authorization"] = f"Bearer {self.config.token}"

            resp = requests.get(url, headers=headers, timeout=self.config.timeout)
            resp.raise_for_status()

            data = resp.json()
            challenges = data.get("challenges", [])

            return challenges

        except ImportError:
            # requests 未安装
            return None
        except Exception as e:
            # 网络错误或 API 错误
            return None

    def get_unsolved_challenges(self, refresh: bool = True) -> List[Dict]:
        """
        获取未解决的挑战

        Args:
            refresh: 是否强制刷新

        Returns:
            未解决的挑战列表
        """
        challenges = self.fetch_challenges(refresh)
        if not challenges:
            return []

        return [c for c in challenges if not c.get("solved", False)]

    def get_target_url(self, challenge_code: str, refresh: bool = True) -> Optional[str]:
        """
        获取挑战的目标 URL

        Args:
            challenge_code: 挑战代码
            refresh: 是否强制刷新

        Returns:
            目标 URL，未找到时返回 None
        """
        challenges = self.fetch_challenges(refresh)
        if not challenges:
            return None

        for c in challenges:
            if c.get("challenge_code") == challenge_code:
                target_info = c.get("target_info", {})
                ip = target_info.get("ip", "")
                ports = target_info.get("port", [])

                if ip and ports:
                    return f"http://{ip}:{ports[0]}"

        return None
