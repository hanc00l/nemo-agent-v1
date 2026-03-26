"""POM 核心 - 命名空间、工具和工具集装饰器。"""

import builtins
from .docstring import namespace, tool, toolset, registry, DocModel

# 替换 help 函数以使用 man()
_original_help = builtins.help

def help(obj=None):
    """增强版 help，优先使用 man() 方法（如果可用）。"""
    if obj is None:
        return _original_help()

    if hasattr(obj, 'man') and callable(obj.man):
        print(obj.man())
    else:
        _original_help(obj)

builtins.help = help

__all__ = ["namespace", "tool", "toolset", "registry", "DocModel"]
