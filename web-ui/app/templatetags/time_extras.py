"""
模板标签过滤器 - 时间处理

处理时区转换和时间格式化
"""
from django import template
from django.utils import timezone
from datetime import datetime, timezone as dt_timezone

register = template.Library()


@register.filter
def format_local_time(iso_time_str):
    """
    将 ISO 格式的时间字符串转换为本地时区时间字符串

    Args:
        iso_time_str: ISO 格式的时间字符串 (如 "2025-03-11T10:30:00+00:00")

    Returns:
        格式化的本地时间字符串 (如 "2025-03-11 18:30:00")
    """
    if not iso_time_str:
        return '-'

    try:
        # 尝试解析 ISO 格式时间
        # 处理带 Z 后缀的 UTC 时间
        if iso_time_str.endswith('Z'):
            iso_time_str = iso_time_str[:-1] + '+00:00'

        dt = datetime.fromisoformat(iso_time_str)

        # 如果是 naive datetime，假设是 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)

        # 转换为本地时区
        local_dt = dt.astimezone(timezone.get_current_timezone())

        # 返回格式化的时间字符串
        return local_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        # 如果解析失败，返回原始字符串（截断到秒）
        return str(iso_time_str)[:19]


@register.filter
def format_local_time_short(iso_time_str):
    """
    将 ISO 格式的时间字符串转换为本地时区时间字符串（简短格式）

    Args:
        iso_time_str: ISO 格式的时间字符串

    Returns:
        格式化的本地时间字符串 (如 "03-11 18:30")
    """
    if not iso_time_str:
        return '-'

    try:
        # 处理带 Z 后缀的 UTC 时间
        if iso_time_str.endswith('Z'):
            iso_time_str = iso_time_str[:-1] + '+00:00'

        dt = datetime.fromisoformat(iso_time_str)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)

        local_dt = dt.astimezone(timezone.get_current_timezone())
        return local_dt.strftime('%m-%d %H:%M')
    except Exception:
        return str(iso_time_str)[:16]


@register.filter
def format_local_datetime(iso_time_str):
    """
    将 ISO 格式的时间字符串转换为本地时区时间字符串（完整格式）

    Args:
        iso_time_str: ISO 格式的时间字符串

    Returns:
        格式化的本地时间字符串 (如 "2025-03-11 18:30:15")
    """
    return format_local_time(iso_time_str)
