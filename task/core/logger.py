"""
Logger - 日志记录器

提供统一的日志记录功能。
"""
import os
import logging
import time
from typing import Optional


class Logger:
    """统一的日志记录器"""

    def __init__(
        self,
        name: str,
        log_file: Optional[str] = None,
        level: int = logging.INFO
    ):
        """
        初始化日志记录器

        Args:
            name: 日志记录器名称
            log_file: 日志文件路径
            level: 日志级别
        """
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # 避免重复添加处理器
        if not self.logger.handlers:
            # 添加文件处理器
            if log_file:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                fh = logging.FileHandler(log_file)
                fh.setLevel(level)
                fh.setFormatter(self._get_formatter())
                self.logger.addHandler(fh)

            # 添加控制台处理器
            ch = logging.StreamHandler()
            ch.setLevel(level)
            ch.setFormatter(self._get_formatter())
            self.logger.addHandler(ch)

    def _get_formatter(self) -> logging.Formatter:
        """获取日志格式化器"""
        return logging.Formatter(
            "%(asctime)s.%(msecs)03dZ [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )

    def info(self, msg: str, category: str = ""):
        """记录信息日志"""
        if category:
            msg = f"[{category}] {msg}"
        self.logger.info(msg)

    def warn(self, msg: str, category: str = ""):
        """记录警告日志"""
        if category:
            msg = f"[{category}] {msg}"
        self.logger.warning(msg)

    def error(self, msg: str, category: str = ""):
        """记录错误日志"""
        if category:
            msg = f"[{category}] {msg}"
        self.logger.error(msg)

    def debug(self, msg: str, category: str = ""):
        """记录调试日志"""
        if category:
            msg = f"[{category}] {msg}"
        self.logger.debug(msg)


class SchedulerLogger(Logger):
    """调度器专用日志记录器"""

    def _get_formatter(self) -> logging.Formatter:
        """获取本地时间的日志格式化器"""
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
        formatter.converter = time.localtime  # 本地时区时间
        return formatter
