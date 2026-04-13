"""
Challenge State - 挑战状态管理

线程安全的 JSON 状态管理，支持文件锁和原子写入。
适配第二届腾讯云黑客松智能渗透挑战赛 API。
"""
import os
import fcntl
import json
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from threading import Lock


@dataclass
class ChallengeStateData:
    """挑战状态数据"""
    challenge_code: str
    target_url: str
    difficulty: str
    level: int
    total_score: int
    total_got_score: int
    flag_count: int
    flag_got_count: int
    state: str  # open, started, success, fail, close
    fetched_at: str  # ISO format timestamp
    title: str = ""
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    timeout_seconds: int = 3600
    containers: List[str] = field(default_factory=list)
    result: Optional[str] = None
    hint_viewed: bool = False
    hint_content: Optional[str] = None
    description: Optional[str] = None
    instance_status: str = "stopped"
    entrypoint: List[str] = field(default_factory=list)
    retry_num: int = 0

    @property
    def is_solved(self) -> bool:
        return self.flag_got_count >= self.flag_count

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChallengeStateData":
        """从字典创建（兼容旧数据无 retry_num 字段，不修改原始 dict）"""
        data = {**data, "retry_num": data.get("retry_num", 0)}
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
                "current_level": 1,
                "total_challenges": 0,
                "solved_challenges": 0,
                "challenges": {}
            }
            self._write_state(initial_data)

    def _default_state(self) -> Dict[str, Any]:
        """默认状态数据"""
        return {
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "current_level": 1,
            "total_challenges": 0,
            "solved_challenges": 0,
            "challenges": {}
        }

    def _read_state(self) -> Dict[str, Any]:
        """读取状态文件（带锁）"""
        with open(self.state_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                content = f.read()
                if not content.strip():
                    return self._default_state()
                return json.loads(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _read_state_locked(self) -> tuple[Dict[str, Any], Any]:
        """读取状态文件并保持排他锁"""
        f = open(self.state_file, "r+")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            if not content.strip():
                return self._default_state(), f
            return json.loads(content), f
        except Exception:
            f.close()
            raise

    def _write_state(self, data: Dict[str, Any]):
        """写入状态文件（原子写入 + 排他锁）"""
        temp_file = f"{self.state_file}.tmp"
        with open(temp_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.rename(temp_file, self.state_file)

    def _write_state_locked(self, data: Dict[str, Any], f):
        """写入状态文件到已锁定的文件对象"""
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    def _atomic_update(self, updater_func) -> Any:
        """原子更新状态文件"""
        data, f = self._read_state_locked()
        try:
            result = updater_func(data)
            self._write_state_locked(data, f)
            return result
        finally:
            f.close()

    def get_global_metadata(self) -> Dict[str, int]:
        """获取全局元数据（current_level, total_challenges, solved_challenges）"""
        with self._lock:
            data = self._read_state()
            return {
                "current_level": data.get("current_level", 1),
                "total_challenges": data.get("total_challenges", 0),
                "solved_challenges": data.get("solved_challenges", 0),
            }

    def update_global_metadata(
        self,
        current_level: Optional[int] = None,
        total_challenges: Optional[int] = None,
        solved_challenges: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        更新全局元数据（原子操作）

        Returns:
            更新后的全局元数据字典
        """
        with self._lock:
            def updater(data):
                now = datetime.now(timezone.utc).isoformat()
                if current_level is not None:
                    data["current_level"] = current_level
                if total_challenges is not None:
                    data["total_challenges"] = total_challenges
                if solved_challenges is not None:
                    data["solved_challenges"] = solved_challenges
                data["last_updated"] = now
                return {
                    "current_level": data.get("current_level", 1),
                    "total_challenges": data.get("total_challenges", 0),
                    "solved_challenges": data.get("solved_challenges", 0),
                }

            return self._atomic_update(updater)

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

    def add_challenge(self, challenge_code: str, target_url: str, difficulty: str,
                      total_score: int, title: str = "", description: str = "",
                      level: int = 0, flag_count: int = 1,
                      flag_got_count: int = 0, total_got_score: int = 0,
                      hint_viewed: bool = False, instance_status: str = "stopped",
                      entrypoint: List[str] = None):
        """添加新挑战（初始状态为 open，原子操作）"""
        with self._lock:
            def updater(data):
                now = datetime.now(timezone.utc).isoformat()

                if challenge_code in data.get("challenges", {}):
                    return  # 已存在

                new_challenge = ChallengeStateData(
                    challenge_code=challenge_code,
                    title=title,
                    target_url=target_url,
                    difficulty=difficulty,
                    level=level,
                    total_score=total_score,
                    total_got_score=total_got_score,
                    flag_count=flag_count,
                    flag_got_count=flag_got_count,
                    state="open",
                    fetched_at=now,
                    updated_at=now,
                    timeout_seconds=self.default_timeout,
                    containers=[],
                    result=None,
                    hint_viewed=hint_viewed,
                    description=description or None,
                    instance_status=instance_status,
                    entrypoint=entrypoint or [],
                )

                data["challenges"][challenge_code] = new_challenge.to_dict()
                data["last_updated"] = now

            self._atomic_update(updater)

    # 哨兵值：区分"未提供参数"和"显式设置为 None"
    _UNSET = object()

    def update_state(
        self,
        challenge_code: str,
        new_state: str,
        **kwargs
    ):
        """更新挑战状态（原子操作，防止数据竞争）

        支持将字段显式设置为 None（用于重试时清除旧值）。
        未提供的参数不会被修改。
        """
        with self._lock:
            def updater(data):
                challenges = data.get("challenges", {})
                if challenge_code not in challenges:
                    return

                now = datetime.now(timezone.utc).isoformat()
                challenge_data = challenges[challenge_code]
                challenge_data["state"] = new_state
                challenge_data["updated_at"] = now

                for key, value in kwargs.items():
                    if value is not ChallengeStateManager._UNSET:
                        challenge_data[key] = value

                data["last_updated"] = now

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

        新 API 字段映射:
        - code → challenge_code
        - entrypoint → target_url
        - flag_got_count >= flag_count → solved

        Returns:
            Dict with keys:
                - 'new': 新增的挑战代码列表
                - 'removed': 移除的挑战代码列表
                - 'solved': 平台确认已解决的挑战代码列表
                - 'recovered': 从 close 状态恢复的挑战代码列表
        """
        with self._lock:
            platform_codes = {c.get("code") for c in platform_challenges if c.get("code")}
            platform_map = {c.get("code"): c for c in platform_challenges if c.get("code")}

            def updater(data):
                local_challenges = data.get("challenges", {})
                local_codes = set(local_challenges.keys())

                new_codes = platform_codes - local_codes

                # 计算需要移除的挑战
                removed_codes = []
                for code in local_codes - platform_codes:
                    local_state = local_challenges[code].get("state")
                    if local_state in ("open", "started"):
                        removed_codes.append(code)

                # 检查已解决的挑战
                solved_codes = []
                for code, pc in platform_map.items():
                    if code in local_codes:
                        flag_got = pc.get("flag_got_count", 0)
                        flag_total = pc.get("flag_count", 1)
                        if flag_got >= flag_total:
                            local_challenge = local_challenges[code]
                            if local_challenge.get("state") not in ("success",):
                                solved_codes.append(code)

                now = datetime.now(timezone.utc).isoformat()

                # 添加新挑战
                for code in new_codes:
                    pc = platform_map[code]
                    entrypoint = pc.get("entrypoint") or []
                    target_url = ""
                    if entrypoint:
                        addr = entrypoint[0]
                        target_url = addr if addr.startswith("http") else f"http://{addr}"

                    flag_got = pc.get("flag_got_count", 0)
                    flag_total = pc.get("flag_count", 1)
                    is_solved = flag_got >= flag_total
                    initial_state = "success" if is_solved else "open"
                    initial_result = "solved_on_platform" if is_solved else None

                    new_challenge = ChallengeStateData(
                        challenge_code=code,
                        title=pc.get("title", ""),
                        target_url=target_url,
                        difficulty=pc.get("difficulty", "unknown"),
                        level=pc.get("level", 0),
                        total_score=pc.get("total_score", 0),
                        total_got_score=pc.get("total_got_score", 0),
                        flag_count=flag_total,
                        flag_got_count=flag_got,
                        state=initial_state,
                        fetched_at=now,
                        updated_at=now,
                        timeout_seconds=self.default_timeout,
                        containers=[],
                        result=initial_result,
                        hint_viewed=pc.get("hint_viewed", False),
                        description=pc.get("description"),
                        instance_status=pc.get("instance_status", "stopped"),
                        entrypoint=entrypoint,
                    )
                    local_challenges[code] = new_challenge.to_dict()

                    if is_solved:
                        solved_codes.append(code)

                # 同步已存在挑战的平台字段（包括已完成的挑战）
                for code in platform_codes - new_codes:
                    if code in local_challenges:
                        pc = platform_map[code]
                        local_c = local_challenges[code]
                        # 更新平台可能变化的字段
                        for field_key, platform_key in [
                            ("title", "title"),
                            ("description", "description"),
                            ("difficulty", "difficulty"),
                            ("level", "level"),
                            ("total_score", "total_score"),
                            ("total_got_score", "total_got_score"),
                            ("flag_count", "flag_count"),
                            ("flag_got_count", "flag_got_count"),
                            ("hint_viewed", "hint_viewed"),
                            ("instance_status", "instance_status"),
                        ]:
                            if platform_key in pc:
                                local_c[field_key] = pc[platform_key]
                        # 同步 entrypoint
                        entrypoint = pc.get("entrypoint") or []
                        local_c["entrypoint"] = entrypoint
                        if entrypoint:
                            addr = entrypoint[0]
                            local_c["target_url"] = addr if addr.startswith("http") else f"http://{addr}"

                # 恢复 close 状态的挑战
                recovered_codes = []
                for code in platform_codes:
                    if code in local_challenges:
                        local_state = local_challenges[code].get("state")
                        if local_state == "close":
                            local_challenges[code]["state"] = "open"
                            local_challenges[code]["updated_at"] = now
                            local_challenges[code]["result"] = None
                            recovered_codes.append(code)

                # 移除已删除的挑战
                for code in removed_codes:
                    local_state = local_challenges[code].get("state")
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

            return self._atomic_update(updater)

    def reset_retry_for_non_success(self) -> int:
        """将所有非 success 状态的挑战 retry_num 重置为 0（原子操作）

        Returns:
            重置的挑战数量
        """
        with self._lock:
            def updater(data):
                count = 0
                for code, c in data.get("challenges", {}).items():
                    if c.get("state") != "success" and c.get("retry_num", 0) != 0:
                        c["retry_num"] = 0
                        count += 1
                if count:
                    data["last_updated"] = datetime.now(timezone.utc).isoformat()
                return count
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
