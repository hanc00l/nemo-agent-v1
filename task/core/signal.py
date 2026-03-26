"""
Signal - 信号处理

提供优雅关闭的信号处理功能。
"""
import signal
from typing import Callable, Optional


class GracefulShutdown:
    """优雅关闭处理器"""

    def __init__(self):
        self.shutdown = False
        self._callbacks = []

    def register(self, callback: Callable[[], None]):
        """
        注册关闭回调函数

        Args:
            callback: 关闭时调用的函数
        """
        self._callbacks.append(callback)

    def handler(self, signum, frame):
        """信号处理器"""
        signal_names = {
            signal.SIGINT: "SIGINT",
            signal.SIGTERM: "SIGTERM",
        }
        name = signal_names.get(signum, f"signal-{signum}")

        # 只执行一次关闭
        if not self.shutdown:
            self.shutdown = True
            for callback in self._callbacks:
                try:
                    callback()
                except Exception:
                    pass

    def setup(self):
        """设置信号处理器"""
        signal.signal(signal.SIGINT, self.handler)
        signal.signal(signal.SIGTERM, self.handler)

    def is_shutdown(self) -> bool:
        """检查是否应该关闭"""
        return self.shutdown


def setup_signal_handler(on_shutdown: Callable[[], None]) -> GracefulShutdown:
    """
    设置信号处理器

    Args:
        on_shutdown: 关闭时调用的函数

    Returns:
        GracefulShutdown 实例
    """
    gs = GracefulShutdown()
    gs.register(on_shutdown)
    gs.setup()
    return gs
