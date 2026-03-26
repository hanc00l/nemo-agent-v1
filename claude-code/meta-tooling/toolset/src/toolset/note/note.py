"""
Note - 笔记持久化存储

详细文档: .claude/skills/pentest/note/SKILL.md

笔记格式: {challenge_code}-{type}.md
- type 只能是: info (确切信息), infer (推测信息), result (最终结果)
- 每道题最多 3 个笔记文件
- 支持并发安全写入 (文件锁)
- 支持追加模式
"""
import os
import fcntl
from pathlib import Path
from typing import Annotated, List, Dict, Literal
from datetime import datetime
from core import tool, toolset, namespace

namespace()

NOTE_DIR = os.getenv("NOTE_PATH", "") or "/opt/notes"  

# 笔记类型定义
NoteType = Literal["info", "infer", "result"]
VALID_TYPES = ("info", "infer", "result")


@toolset()
class Note:
    """笔记持久化存储。详见 skills/pentest/note/SKILL.md"""

    def __init__(self):
        os.makedirs(NOTE_DIR, exist_ok=True)

    def _get_filepath(self, challenge_code: str, note_type: NoteType) -> str:
        """获取笔记文件路径"""
        # 清理 challenge_code 中的特殊字符
        safe_code = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in challenge_code).strip()
        return os.path.join(NOTE_DIR, f"{safe_code}-{note_type}.md")

    def _acquire_lock(self, filepath: str):
        """获取文件锁（用于并发安全）"""
        lock_path = filepath + ".lock"
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file

    def _release_lock(self, lock_file):
        """释放文件锁"""
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    @tool()
    def append_note(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"],
        note_type: Annotated[str, "笔记类型: info/infer/result"],
        content: Annotated[str, "笔记内容 (Markdown)"],
        llm_id: Annotated[str, "LLM标识 (LLM-1/2/3)，自动从环境变量获取"] = None
    ) -> str:
        """
        追加笔记内容。如果笔记不存在则新建。

        - challenge_code: 题目唯一标识
        - note_type: 只能是 info(确切信息)、infer(推测信息)、result(最终结果)
        - content: 将追加到笔记末尾，自动添加时间戳和 LLM 标识
        - llm_id: LLM标识 (LLM-1/2/3)，如不提供则自动从环境变量获取
        """
        # 验证 note_type
        if note_type not in VALID_TYPES:
            return f"错误: note_type 只能是 {VALID_TYPES}，收到: {note_type}"

        # 如果没有提供 llm_id，从环境变量获取
        if llm_id is None:
            import os
            llm_id = os.getenv("LLM_ID", "")

        filepath = self._get_filepath(challenge_code, note_type)
        lock_file = None

        try:
            # 获取文件锁
            lock_file = self._acquire_lock(filepath)

            # 添加时间戳和 LLM 标识
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            llm_info = f" [{llm_id}]" if llm_id else ""
            entry = f"\n\n---\n**[{timestamp}{llm_info}]**\n\n{content}\n"

            # 追加写入
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(entry)

            return f"已追加到: {os.path.basename(filepath)}"
        except Exception as e:
            return f"错误: {e}"
        finally:
            if lock_file:
                self._release_lock(lock_file)

    @tool()
    def add_note(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"],
        note_type: Annotated[str, "笔记类型: info/infer/result"],
        content: Annotated[str, "笔记内容 (Markdown)"],
        title: Annotated[str, "标题(兼容，自动合并到内容)"] = None,
        llm_id: Annotated[str, "LLM标识 (兼容，自动获取)"] = None
    ) -> str:
        """
        添加笔记（兼容方法，别名指向 append_note）

        这是 add_note 的兼容实现，会自动调用 append_note。
        如果提供了 title 参数，会将其作为标题合并到内容中。

        注意: 推荐直接使用 append_note 方法
        """
        print("[API 兼容] add_note 是 append_note 的别名，推荐直接使用 append_note")

        # 如果提供了 title，将其合并到内容
        if title is not None:
            content = f"# {title}\n\n{content}"

        # 调用 append_note，传递 llm_id
        return self.append_note(challenge_code, note_type, content, llm_id)

    @tool()
    def save_note(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"],
        note_type: Annotated[str, "笔记类型: info/infer/result"],
        content: Annotated[str, "笔记内容 (Markdown)"]
    ) -> str:
        """
        保存笔记，覆盖同名笔记。（不推荐，建议使用 append_note）
        """
        # 验证 note_type
        if note_type not in VALID_TYPES:
            return f"错误: note_type 只能是 {VALID_TYPES}，收到: {note_type}"

        filepath = self._get_filepath(challenge_code, note_type)
        lock_file = None

        try:
            lock_file = self._acquire_lock(filepath)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"已保存: {os.path.basename(filepath)}"
        except Exception as e:
            return f"错误: {e}"
        finally:
            if lock_file:
                self._release_lock(lock_file)

    @tool()
    def read_note(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"],
        note_type: Annotated[str, "笔记类型: info/infer/result"]
    ) -> str:
        """读取指定类型的笔记内容。"""
        # 验证 note_type
        if note_type not in VALID_TYPES:
            return f"错误: note_type 只能是 {VALID_TYPES}，收到: {note_type}"

        filepath = self._get_filepath(challenge_code, note_type)
        if not os.path.exists(filepath):
            return f"笔记不存在: {challenge_code}-{note_type}"

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"错误: {e}"

    @tool()
    def read_all_notes(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"]
    ) -> Dict[str, str]:
        """
        读取指定题目的所有笔记。

        返回: {"info": "内容或空", "infer": "内容或空", "result": "内容或空"}
        """
        result = {}
        for note_type in VALID_TYPES:
            filepath = self._get_filepath(challenge_code, note_type)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        result[note_type] = f.read()
                except Exception as e:
                    result[note_type] = f"读取错误: {e}"
            else:
                result[note_type] = ""  # 空字符串表示不存在
        return result

    @tool()
    def get_notes_summary(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"]
    ) -> str:
        """
        获取指定题目所有笔记的摘要，用于 agent 思考。

        返回格式化的 Markdown 摘要，方便 agent 快速了解之前的发现。
        """
        notes = self.read_all_notes(challenge_code)

        summary = f"# 笔记摘要: {challenge_code}\n\n"

        type_descriptions = {
            "info": "确切发现的信息",
            "infer": "推测/假设",
            "result": "最终结果"
        }

        for note_type in VALID_TYPES:
            content = notes.get(note_type, "")
            summary += f"## {note_type.upper()} ({type_descriptions[note_type]})\n\n"
            if content:
                # 如果内容太长，截断显示
                if len(content) > 2000:
                    summary += f"{content[:1000]}\n\n... [内容过长，已截断] ...\n\n{content[-500:]}\n\n"
                else:
                    summary += f"{content}\n\n"
            else:
                summary += "*暂无内容*\n\n"

        return summary

    @tool()
    def list_notes(self) -> List[str]:
        """列出所有笔记文件名。"""
        try:
            notes = []
            for f in os.listdir(NOTE_DIR):
                if f.endswith('.md') and not f.endswith('.lock'):
                    notes.append(f.replace('.md', ''))
            return sorted(notes)
        except Exception as e:
            return [f"错误: {e}"]

    @tool()
    def list_challenge_notes(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"]
    ) -> List[str]:
        """列出指定题目的所有笔记类型。"""
        existing = []
        for note_type in VALID_TYPES:
            filepath = self._get_filepath(challenge_code, note_type)
            if os.path.exists(filepath):
                existing.append(note_type)
        return existing

    @tool()
    def clear_note(
        self,
        challenge_code: Annotated[str, "题目代码 (必填)"],
        note_type: Annotated[str, "笔记类型: info/infer/result"]
    ) -> str:
        """清空指定笔记内容。"""
        if note_type not in VALID_TYPES:
            return f"错误: note_type 只能是 {VALID_TYPES}，收到: {note_type}"

        filepath = self._get_filepath(challenge_code, note_type)
        if not os.path.exists(filepath):
            return f"笔记不存在: {challenge_code}-{note_type}"

        lock_file = None
        try:
            lock_file = self._acquire_lock(filepath)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("")  # 清空
            return f"已清空: {challenge_code}-{note_type}"
        except Exception as e:
            return f"错误: {e}"
        finally:
            if lock_file:
                self._release_lock(lock_file)

    # ============ 兼容旧 API (已废弃) ============

    @tool()
    def save_note_legacy(
        self,
        title: Annotated[str, "笔记标题 (已废弃，请使用 challenge_code + note_type)"],
        content: Annotated[str, "笔记内容 (Markdown)"]
    ) -> str:
        """[已废弃] 保存笔记，覆盖同名笔记。请使用 save_note(challenge_code, note_type, content)"""
        safe_title = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in title).strip()
        filepath = os.path.join(NOTE_DIR, f"{safe_title or 'untitled_note'}.md")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"[已废弃API] Saved: {filepath}"
        except Exception as e:
            return f"Error: {e}"

    @tool()
    def read_note_legacy(self, title: Annotated[str, "笔记标题 (已废弃)"]) -> str:
        """[已废弃] 读取笔记内容。请使用 read_note(challenge_code, note_type)"""
        safe_title = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in title).strip()
        filepath = os.path.join(NOTE_DIR, f"{safe_title or 'untitled_note'}.md")
        if not os.path.exists(filepath):
            return f"[已废弃API] Not found: '{title}'. Use list_notes() to see available."
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error: {e}"
