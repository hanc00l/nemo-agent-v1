"""
State - 挑战状态常量和工具

提供挑战状态定义和相关工具函数。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime, timezone
import zoneinfo


class ChallengeState(str, Enum):
    """挑战状态枚举"""
    OPEN = "open"           # 新发现的挑战
    STARTED = "started"     # 容器运行中
    SUCCESS = "success"     # 解决成功
    FAIL = "fail"           # 解决失败
    CLOSE = "close"         # 已关闭


# 状态常量（兼容性）
STATE_OPEN = ChallengeState.OPEN.value
STATE_STARTED = ChallengeState.STARTED.value
STATE_SUCCESS = ChallengeState.SUCCESS.value
STATE_FAIL = ChallengeState.FAIL.value
STATE_CLOSE = ChallengeState.CLOSE.value


# 本地时区
LOCAL_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def parse_time_to_local(time_str: str) -> datetime:
    """
    解析各种格式的时间字符串为本地时区时间

    支持的格式：
    - "2026-03-10T09:34:04.375220+08:00" (带时区偏移)
    - "2026-03-10T09:34:04.375220Z" (UTC Z 标记)
    - "2026-03-10T01:34:04.375220+00:00" (UTC 偏移)
    - "2026-03-10T09:34:04.375220" (无时区，视为本地时间)

    Args:
        time_str: ISO 格式时间字符串

    Returns:
        本地时区的 datetime 对象
    """
    # 先尝试直接解析
    try:
        dt = datetime.fromisoformat(time_str)

        # 如果已包含时区信息，转换为本地时区
        if dt.tzinfo is not None:
            return dt.astimezone(LOCAL_TZ)
        else:
            # 无时区信息，视为本地时间
            return dt.replace(tzinfo=LOCAL_TZ)
    except ValueError:
        pass

    # 处理 "Z" 结尾的情况
    if time_str.endswith("Z"):
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return dt.astimezone(LOCAL_TZ)
        except ValueError:
            pass

    # 如果都失败了，返回当前本地时间（容错）
    return datetime.now(LOCAL_TZ)


@dataclass
class TimeoutInfo:
    """超时信息"""
    started_at: str
    timeout_seconds: int

    def is_timeout(self, now: Optional[datetime] = None) -> bool:
        """
        检查是否超时

        Args:
            now: 当前时间，默认使用本地时区时间

        Returns:
            是否超时
        """
        if now is None:
            now = datetime.now(LOCAL_TZ)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=LOCAL_TZ)

        try:
            started_time = parse_time_to_local(self.started_at)
            elapsed_seconds = (now - started_time).total_seconds()
            return elapsed_seconds > self.timeout_seconds
        except (ValueError, TypeError):
            return False

    def elapsed_seconds(self, now: Optional[datetime] = None) -> float:
        """
        获取已用秒数

        Args:
            now: 当前时间，默认使用本地时区时间

        Returns:
            已用秒数
        """
        if now is None:
            now = datetime.now(LOCAL_TZ)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=LOCAL_TZ)

        try:
            started_time = parse_time_to_local(self.started_at)
            return (now - started_time).total_seconds()
        except (ValueError, TypeError):
            return 0.0


def is_challenge_timeout(
    started_at: str,
    timeout_seconds: int,
    now: Optional[datetime] = None
) -> bool:
    """
    检查挑战是否超时

    Args:
        started_at: 开始时间 (ISO 格式)
        timeout_seconds: 超时秒数
        now: 当前时间，默认使用本地时区时间

    Returns:
        是否超时
    """
    info = TimeoutInfo(started_at=started_at, timeout_seconds=timeout_seconds)
    return info.is_timeout(now)


def get_elapsed_seconds(started_at: str, now: Optional[datetime] = None) -> float:
    """
    获取已用秒数

    Args:
        started_at: 开始时间 (ISO 格式)
        now: 当前时间，默认使用本地时区时间

    Returns:
        已用秒数
    """
    info = TimeoutInfo(started_at=started_at, timeout_seconds=0)
    return info.elapsed_seconds(now)


def get_timestamp() -> str:
    """
    获取当前本地时区时间戳 (ISO 格式)

    返回格式: "2026-03-10T09:34:04.375220+08:00"
    """
    return datetime.now(LOCAL_TZ).isoformat()
