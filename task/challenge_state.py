"""
Challenge State - 挑战状态管理

线程安全的 JSON 状态管理，支持文件锁和原子写入。
"""
import os
import fcntl
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from threading import Lock


@dataclass
class ChallengeStateData:
    """挑战状态数据"""
    challenge_code: str
    target_url: str
    difficulty: str
    points: int
    state: str  # open, started, success, fail, close
    fetched_at: str  # ISO format timestamp
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    timeout_seconds: int = 3600
    containers: List[str] = None
    result: Optional[str] = None

    def __post_init__(self):
        if self.containers is None:
            self.containers = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChallengeStateData":
        """从字典创建"""
        return cls(**data)


class ChallengeStateManager:
    """线程安全的挑战状态管理器"""

    def __init__(self, state_file: str, default_timeout: int = 3600):
        self.state_file = state_file
        self.default_timeout = default_timeout
        self._lock = Lock()
        self._ensure_state_file()

    def _ensure_state_file(self):
        """确保状态文件存在"""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        if not os.path.exists(self.state_file):
            initial_data = {
                "version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "challenges": {}
            }
            self._write_state(initial_data)

    def _read_state(self) -> Dict[str, Any]:
        """读取状态文件（带锁）"""
        with open(self.state_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                content = f.read()
                if not content.strip():
                    # Empty file, return initial state
                    return {
                        "version": "1.0",
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "challenges": {}
                    }
                return json.loads(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _read_state_locked(self) -> tuple[Dict[str, Any], Any]:
        """
        读取状态文件并保持排他锁（用于原子更新）

        Returns:
            (data, file_object): 数据和保持锁的文件对象

        注意：调用者必须关闭文件对象以释放锁！
        推荐使用上下文管理器：

            with self._read_and_lock() as (data, f):
                # 修改 data
                ...
                self._write_state_locked(data, f)
        """
        f = open(self.state_file, "r+")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            if not content.strip():
                return {
                    "version": "1.0",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "challenges": {}
                }, f
            return json.loads(content), f
        except Exception:
            f.close()
            raise

    def _write_state(self, data: Dict[str, Any]):
        """写入状态文件（原子写入 + 排他锁）"""
        # 写入临时文件
        temp_file = f"{self.state_file}.tmp"
        with open(temp_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # 原子重命名
        os.rename(temp_file, self.state_file)

    def _write_state_locked(self, data: Dict[str, Any], f):
        """
        写入状态文件到已锁定的文件对象

        Args:
            data: 要写入的数据
            f: 已持有排他锁的文件对象（来自 _read_and_lock）
        """
        # 截断文件并写入新数据
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        # 注意：不关闭文件，不释放锁
        # 调用者负责关闭文件并释放锁

    def _atomic_update(self, updater_func) -> Any:
        """
        原子更新状态文件（在整个读-修改-写周期内持有文件锁）

        Args:
            updater_func: 函数，接收 (data)，修改并可选地返回结果

        Returns:
            updater_func 的返回值

        这个方法确保：
        1. 读取时获取排他锁
        2. 修改过程中保持锁
        3. 写入时保持锁
        4. 只有在写入完成后才释放锁

        这样可以防止其他进程/线程在读取和写入之间修改数据。
        """
        # 读取并获取锁
        data, f = self._read_state_locked()
        try:
            # 调用更新函数修改数据（可返回结果）
            result = updater_func(data)
            # 写入数据（锁仍然保持）
            self._write_state_locked(data, f)
            return result
        finally:
            # 关闭文件，释放锁
            f.close()

    def get_all_challenges(self) -> Dict[str, ChallengeStateData]:
        """获取所有挑战"""
        with self._lock:
            data = self._read_state()
            challenges = {}
            for code, challenge_data in data.get("challenges", {}).items():
                challenges[code] = ChallengeStateData.from_dict(challenge_data)
            return challenges

    def get_challenge(self, challenge_code: str) -> Optional[ChallengeStateData]:
        """获取单个挑战"""
        with self._lock:
            data = self._read_state()
            challenge_data = data.get("challenges", {}).get(challenge_code)
            if challenge_data:
                return ChallengeStateData.from_dict(challenge_data)
            return None

    def add_challenge(self, challenge_code: str, target_url: str, difficulty: str, points: int):
        """添加新挑战（初始状态为 open，原子操作）"""
        with self._lock:
            def updater(data):
                now = datetime.now(timezone.utc).isoformat()

                if challenge_code in data.get("challenges", {}):
                    return  # 已存在

                new_challenge = ChallengeStateData(
                    challenge_code=challenge_code,
                    target_url=target_url,
                    difficulty=difficulty,
                    points=points,
                    state="open",
                    fetched_at=now,
                    updated_at=now,
                    timeout_seconds=self.default_timeout,
                    containers=[],
                    result=None
                )

                data["challenges"][challenge_code] = new_challenge.to_dict()
                data["last_updated"] = now

            self._atomic_update(updater)

    def update_state(
        self,
        challenge_code: str,
        new_state: str,
        **kwargs
    ):
        """更新挑战状态（原子操作，防止数据竞争）"""
        with self._lock:
            def updater(data):
                challenges = data.get("challenges", {})
                if challenge_code not in challenges:
                    return

                now = datetime.now(timezone.utc).isoformat()
                challenge_data = challenges[challenge_code]
                challenge_data["state"] = new_state
                challenge_data["updated_at"] = now

                # 更新额外字段
                for key, value in kwargs.items():
                    if value is not None:
                        challenge_data[key] = value

                data["last_updated"] = now

            # 原子更新：在整个读-修改-写周期内持有文件锁
            self._atomic_update(updater)

    def get_challenges_by_state(self, state: str) -> List[ChallengeStateData]:
        """按状态获取挑战列表"""
        with self._lock:
            data = self._read_state()
            challenges = []
            for challenge_data in data.get("challenges", {}).values():
                if challenge_data.get("state") == state:
                    challenges.append(ChallengeStateData.from_dict(challenge_data))
            return challenges

    def sync_with_platform(
        self,
        platform_challenges: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        与平台同步挑战状态（原子操作，防止数据竞争）

        Returns:
            Dict with keys:
                - 'new': 新增的挑战代码列表
                - 'removed': 移除的挑战代码列表（仅包含非最终状态的挑战）
                - 'solved': 平台确认已解决的挑战代码列表
                - 'recovered': 从 close 状态恢复的挑战代码列表
        """
        with self._lock:
            # 先计算平台数据（不涉及文件操作）
            platform_codes = {c.get("challenge_code") for c in platform_challenges}
            platform_map = {c.get("challenge_code"): c for c in platform_challenges}

            def updater(data):
                """在持有文件锁的情况下执行同步"""
                local_challenges = data.get("challenges", {})
                local_codes = set(local_challenges.keys())

                new_codes = platform_codes - local_codes

                # 计算真正需要移除的挑战（排除已经是最终状态的）
                removed_codes = []
                for code in local_codes - platform_codes:
                    local_state = local_challenges[code].get("state")
                    # 只有 open/started 状态才计入 removed，close/success/fail 忽略
                    if local_state in ("open", "started"):
                        removed_codes.append(code)

                # 检查已解决的挑战
                solved_codes = []
                for code, pc in platform_map.items():
                    if code in local_codes and pc.get("solved", False):
                        local_challenge = local_challenges[code]
                        if local_challenge.get("state") not in ("success",):
                            solved_codes.append(code)

                now = datetime.now(timezone.utc).isoformat()

                # 添加新挑战
                for code in new_codes:
                    pc = platform_map[code]
                    target_info = pc.get("target_info", {})
                    ip, ports = target_info.get("ip", ""), target_info.get("port", [])
                    target_url = f"http://{ip}:{ports[0]}" if ip and ports else ""

                    # 检查平台中该挑战是否已解决
                    is_solved = pc.get("solved", False)
                    initial_state = "success" if is_solved else "open"
                    initial_result = "solved_on_platform" if is_solved else None

                    new_challenge = ChallengeStateData(
                        challenge_code=code,
                        target_url=target_url,
                        difficulty=pc.get("difficulty", "unknown"),
                        points=pc.get("points", 0),
                        state=initial_state,
                        fetched_at=now,
                        updated_at=now,
                        timeout_seconds=self.default_timeout,
                        containers=[],
                        result=initial_result
                    )
                    local_challenges[code] = new_challenge.to_dict()

                    # 如果已解决，添加到 solved_codes
                    if is_solved:
                        solved_codes.append(code)

                # 恢复 close 状态的挑战（如果平台还存在）
                recovered_codes = []
                for code in platform_codes:
                    if code in local_challenges:
                        local_state = local_challenges[code].get("state")
                        # 恢复 close 状态的挑战
                        if local_state == "close":
                            local_challenges[code]["state"] = "open"
                            local_challenges[code]["updated_at"] = now
                            local_challenges[code]["result"] = None
                            recovered_codes.append(code)

                # 移除已删除的挑战（状态转为 close）
                # 更加保守：只有当挑战不在平台且本地状态不是已完成的最终状态时才标记为 close
                for code in removed_codes:
                    local_state = local_challenges[code].get("state")
                    # 只有 open/started 状态才转为 close，success/fail 保持原样
                    if local_state in ("open", "started"):
                        local_challenges[code]["state"] = "close"
                        local_challenges[code]["updated_at"] = now

                # 更新已解决的挑战
                for code in solved_codes:
                    local_challenges[code]["state"] = "success"
                    local_challenges[code]["updated_at"] = now
                    local_challenges[code]["result"] = "solved_on_platform"

                data["challenges"] = local_challenges
                data["last_updated"] = now

                return {
                    "new": list(new_codes),
                    "removed": list(removed_codes),
                    "solved": solved_codes,
                    "recovered": recovered_codes
                }

            # 原子更新：在整个读-修改-写周期内持有文件锁
            return self._atomic_update(updater)

    def cleanup_old_challenges(self, max_age_hours: int = 24):
        """清理旧的已完成挑战（原子操作）"""
        with self._lock:
            def updater(data):
                challenges = data.get("challenges", {})
                now = datetime.now(timezone.utc)
                to_remove = []

                for code, challenge_data in challenges.items():
                    state = challenge_data.get("state")
                    if state in ("success", "fail", "close"):
                        updated_at = challenge_data.get("updated_at", "")
                        try:
                            updated_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                            age_hours = (now - updated_time).total_seconds() / 3600
                            if age_hours > max_age_hours:
                                to_remove.append(code)
                        except (ValueError, TypeError):
                            pass

                for code in to_remove:
                    del challenges[code]

                if to_remove:
                    data["last_updated"] = now.isoformat()

                return len(to_remove)

            return self._atomic_update(updater)
