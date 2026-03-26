"""
笔记管理工具，用于状态跟踪、信息收集和跨执行步骤的长期记忆。
"""
from core import namespace

namespace()

from .note import Note

note = Note()

__all__ = ['note']