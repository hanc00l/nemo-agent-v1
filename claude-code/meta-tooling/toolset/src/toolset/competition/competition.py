"""
Competition - CTF 竞赛平台 API

详细文档: .claude/skills/pentest/competition/SKILL.md
"""
import os
import time
import requests
from typing import Annotated, List, Dict, Any, Optional
from dataclasses import dataclass
from core import tool, toolset, namespace

namespace()

DEFAULT_BASE_URL = "http://host.docker.internal:8888"


@dataclass
class ChallengeInfo:
    challenge_code: str
    difficulty: str
    points: int
    hint_viewed: bool
    solved: bool
    target_info: Dict[str, Any]


@toolset()
class Competition:
    """CTF 竞赛平台 API。详见 skills/pentest/competition/SKILL.md"""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("COMPETITION_API_URL", DEFAULT_BASE_URL)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        self._cache: Optional[Dict[str, ChallengeInfo]] = None
        self._cache_time: float = 0

    def _log(self, msg: str, level: str = "info"):
        print(f"[{time.strftime('%H:%M:%S')}] [{level.upper()}] {msg}")

    @tool()
    def get_challenges(self, refresh: Annotated[bool, "强制刷新"] = False) -> List[Dict[str, Any]]:
        """获取所有挑战信息 (缓存60秒)。"""
        if not refresh and self._cache and (time.time() - self._cache_time) < 60:
            return [vars(c) for c in self._cache.values()]

        resp = self.session.get(f"{self.base_url}/api/v1/challenges", timeout=30)
        resp.raise_for_status()
        data = resp.json()

        self._cache = {}
        result = []
        for c in data.get("challenges", []):
            info = ChallengeInfo(
                challenge_code=c.get("challenge_code", ""),
                difficulty=c.get("difficulty", "unknown"),
                points=c.get("points", 0),
                hint_viewed=c.get("hint_viewed", False),
                solved=c.get("solved", False),
                target_info=c.get("target_info", {})
            )
            self._cache[info.challenge_code] = info
            result.append(vars(info))

        self._cache_time = time.time()
        self._log(f"获取 {len(result)} 个挑战")
        return result

    @tool()
    def get_hint(self, challenge_code: Annotated[str, "题目代码"]) -> Dict[str, Any]:
        """获取提示 (首次扣分)。"""
        resp = self.session.get(f"{self.base_url}/api/v1/hint/{challenge_code}", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = {
            "hint_content": data.get("hint_content", ""),
            "penalty_points": data.get("penalty_points", 0),
            "first_use": data.get("first_use", False)
        }
        if result["first_use"]:
            self._log(f"首次获取提示，扣 {result['penalty_points']} 分", "warn")
        return result

    @tool()
    def submit_answer(
        self,
        challenge_code: Annotated[str, "题目代码"],
        answer: Annotated[str, "FLAG (正确参数名)"],
        flag: Annotated[str, "FLAG (兼容参数，已废弃请使用 answer)"] = None
    ) -> Dict[str, Any]:
        """
        提交答案验证。

        参数:
            challenge_code: 题目代码
            answer: FLAG 字符串 (正确参数名)
            flag: FLAG 字符串 (兼容参数，会自动转换为 answer)

        返回:
            {"correct": bool, "earned_points": int, "is_solved": bool}
        """
        # 兼容处理: 如果提供了 flag 参数，使用它替代 answer
        if flag is not None:
            self._log(f"[API 兼容] 检测到 'flag' 参数，已自动转换为 'answer'", "warn")
            answer = flag

        resp = self.session.post(
            f"{self.base_url}/api/v1/answer",
            json={"challenge_code": challenge_code, "answer": answer},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        result = {
            "correct": data.get("correct", False),
            "earned_points": data.get("earned_points", 0),
            "is_solved": data.get("is_solved", False)
        }
        if result["correct"]:
            self._log(f"正确! +{result['earned_points']} 分")
            if self._cache and challenge_code in self._cache:
                self._cache[challenge_code].solved = True
        else:
            self._log("错误，继续尝试", "warn")
        return result

    @tool()
    def get_unsolved_challenges(self, refresh: Annotated[bool, "强制刷新"] = False) -> List[Dict[str, Any]]:
        """获取未解决的挑战。"""
        return [c for c in self.get_challenges(refresh) if not c.get("solved")]

    @tool()
    def get_target_url(
        self,
        challenge_code: Annotated[str, "题目代码"],
        refresh: Annotated[bool, "强制刷新"] = False
    ) -> Optional[str]:
        """获取目标 URL (http://ip:port)。"""
        for c in self.get_challenges(refresh):
            if c.get("challenge_code") == challenge_code:
                info = c.get("target_info", {})
                ip, ports = info.get("ip", ""), info.get("port", [])
                if ip and ports:
                    return f"http://{ip}:{ports[0]}"
        return None
