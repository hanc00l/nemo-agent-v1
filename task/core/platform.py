"""
Platform - 竞赛平台 API 客户端

适配第二届腾讯云黑客松智能渗透挑战赛 API。
认证方式: Agent-Token 请求头。
"""
import os
import time
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class PlatformConfig:
    """平台配置"""
    api_url: str
    timeout: int = 30
    agent_token: str = ""

    @classmethod
    def from_env(cls) -> "PlatformConfig":
        """从环境变量加载配置"""
        return cls(
            api_url=os.getenv("COMPETITION_API_URL", "http://host.docker.internal"),
            timeout=int(os.getenv("API_TIMEOUT", "30")),
            agent_token=os.getenv("AGENT_TOKEN", "") or os.getenv("COMPETITION_API_TOKEN", ""),
        )


class PlatformClient:
    """竞赛平台 API 客户端"""

    def __init__(self, config: Optional[PlatformConfig] = None):
        self.config = config or PlatformConfig.from_env()
        self._last_request_time: float = 0

    def _rate_limit(self):
        """频率控制：请求间隔 >= 0.5s"""
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        self._last_request_time = time.time()

    def _headers(self) -> Dict[str, str]:
        """构建请求头（始终包含 Agent-Token）"""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Agent-Token": self.config.agent_token,
        }

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        """统一请求方法，含频率限制和 429 重试"""
        try:
            import requests

            self._rate_limit()
            url = f"{self.config.api_url.rstrip('/')}/api{path}"

            # 429 重试（最多 3 次）
            max_retries = 3
            for attempt in range(max_retries):
                resp = requests.request(
                    method, url,
                    headers=self._headers(),
                    timeout=self.config.timeout,
                    **kwargs
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "1"))
                    wait_time = min(retry_after, 2)
                    print(f"[WARN] 429 频率限制，等待 {wait_time}s (第 {attempt + 1}/{max_retries} 次)")
                    time.sleep(wait_time)
                    continue
                break
            else:
                # 所有重试都用完
                print(f"[ERROR] 429 重试耗尽: {method} {path}")
                return None

            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                print(f"[WARN] API 返回错误: code={data.get('code')}, message={data.get('message')}")
                return None

            return data.get("data", data)

        except Exception as e:
            print(f"[ERROR] API 请求失败: {method} {path} - {e}")
            return None

    def fetch_challenges(self, refresh: bool = True) -> Optional[Dict]:
        """
        从平台获取赛题列表（含全局元数据）

        Returns:
            完整数据字典，包含:
              - challenges: 赛题列表
              - current_level: 当前关卡等级
              - total_challenges: 总赛题数
              - solved_challenges: 已完成赛题数
            失败时返回 None
        """
        data = self._request("GET", "/challenges")
        if data is None:
            return None
        if not isinstance(data, dict):
            return None
        # 确保返回的字典包含 challenges 列表
        if "challenges" not in data:
            data["challenges"] = []
        return data

    def start_instance(self, code: str) -> Optional[List[str]]:
        """
        启动赛题实例

        Args:
            code: 赛题唯一标识

        Returns:
            入口地址列表，失败时返回 None
        """
        data = self._request("POST", "/start_challenge", json={"code": code})
        if data is None:
            return None
        # 已完成的情况
        if isinstance(data, dict) and data.get("already_completed"):
            return []
        return data if isinstance(data, list) else []

    def stop_instance(self, code: str) -> bool:
        """
        停止赛题实例

        Args:
            code: 赛题唯一标识

        Returns:
            是否成功
        """
        result = self._request("POST", "/stop_challenge", json={"code": code})
        return result is not None

    def submit_flag(self, code: str, flag: str) -> Optional[Dict]:
        """
        提交 FLAG

        Args:
            code: 赛题唯一标识
            flag: FLAG 字符串

        Returns:
            {"correct": bool, "flag_count": int, "flag_got_count": int, "message": str}
        """
        return self._request("POST", "/submit", json={"code": code, "flag": flag})

    def get_hint(self, code: str) -> Optional[str]:
        """
        获取赛题提示

        Args:
            code: 赛题唯一标识

        Returns:
            提示内容，失败时返回 None
        """
        data = self._request("POST", "/hint", json={"code": code})
        if data and isinstance(data, dict):
            return data.get("hint_content")
        return None

    def get_unsolved_challenges(self, refresh: bool = True) -> List[Dict]:
        """获取未完成的赛题 (flag_got_count < flag_count)"""
        data = self.fetch_challenges(refresh)
        if not data:
            return []
        challenges = data.get("challenges", [])
        return [c for c in challenges if c.get("flag_got_count", 0) < c.get("flag_count", 1)]

    def get_target_url(self, code: str, refresh: bool = True) -> Optional[str]:
        """获取赛题目标 URL"""
        data = self.fetch_challenges(refresh)
        if not data:
            return None
        challenges = data.get("challenges", [])

        for c in challenges:
            if c.get("code") == code:
                entrypoint = c.get("entrypoint") or []
                if entrypoint:
                    addr = entrypoint[0]
                    if not addr.startswith("http"):
                        addr = f"http://{addr}"
                    return addr
        return None
