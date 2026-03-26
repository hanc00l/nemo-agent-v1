"""
数据仓库 - 统一的数据访问层

负责从 JSON 文件读取数据：
- subjects.json (调度器状态)

路径说明（相对路径，基于项目根目录）：
- ../task/data/subjects.json - 调度器状态文件
- ../task/data/scheduler.log - 调度器日志文件
- ~/notes - 用户笔记目录
"""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from django.conf import settings

# 项目根目录（web-ui 的上两级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# subjects.json 路径（相对路径）
SUBJECTS_JSON_PATH = os.path.join(PROJECT_ROOT, "task", "data", "subjects.json")


# 确保 notes 目录存在
def _ensure_notes_dir():
    """确保 notes 目录存在"""
    notes_dir = os.path.expanduser("~/notes")
    os.makedirs(notes_dir, exist_ok=True)


# 模块导入时自动创建目录
_ensure_notes_dir()


class ChallengeRepository:
    """挑战数据仓库"""

    @staticmethod
    def get_json_data() -> Dict[str, Any]:
        """
        读取 subjects.json 数据

        Returns:
            包含 challenges 数据的字典
        """
        try:
            with open(SUBJECTS_JSON_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"challenges": {}}
        except json.JSONDecodeError:
            return {"challenges": {}}

    @staticmethod
    def get_all_challenges() -> List[Dict[str, Any]]:
        """
        获取所有挑战数据（从 JSON）

        Returns:
            挑战列表
        """
        data = ChallengeRepository.get_json_data()
        challenges = []

        for code, challenge_data in data.get("challenges", {}).items():
            challenges.append({
                'challenge_code': challenge_data.get('challenge_code'),
                'target_url': challenge_data.get('target_url'),
                'difficulty': challenge_data.get('difficulty'),
                'points': challenge_data.get('points'),
                'state': challenge_data.get('state'),
                'fetched_at': challenge_data.get('fetched_at'),
                'started_at': challenge_data.get('started_at'),
                'updated_at': challenge_data.get('updated_at'),
                'timeout_seconds': challenge_data.get('timeout_seconds'),
                'containers': challenge_data.get('containers', []),
                'result': challenge_data.get('result'),
            })

        return challenges

    @staticmethod
    def get_challenge(challenge_code: str) -> Optional[Dict[str, Any]]:
        """
        获取单个挑战数据

        Args:
            challenge_code: 挑战代码

        Returns:
            挑战数据，不存在时返回 None
        """
        data = ChallengeRepository.get_json_data()
        return data.get("challenges", {}).get(challenge_code)

    @staticmethod
    def get_challenges_by_state(state: str) -> List[Dict[str, Any]]:
        """
        按状态获取挑战

        Args:
            state: 状态 (open, started, success, fail, close)

        Returns:
            该状态的挑战列表
        """
        all_challenges = ChallengeRepository.get_all_challenges()
        return [c for c in all_challenges if c.get('state') == state]

    @staticmethod
    def get_statistics() -> Dict[str, int]:
        """
        获取统计数据

        Returns:
            包含各状态数量的字典
        """
        all_challenges = ChallengeRepository.get_all_challenges()

        stats = {
            'total': len(all_challenges),
            'open': 0,
            'started': 0,
            'success': 0,
            'fail': 0,
            'close': 0,
            'total_points': 0,
            'success_points': 0,
        }

        for c in all_challenges:
            state = c.get('state', '')
            if state in stats:
                stats[state] += 1

            points = c.get('points', 0)
            stats['total_points'] += points

            if state == 'success':
                stats['success_points'] += points

        return stats

    @staticmethod
    def get_container_info(challenge_code: str) -> List[str]:
        """
        获取挑战的容器列表

        Args:
            challenge_code: 挑战代码

        Returns:
            容器名称列表
        """
        challenge = ChallengeRepository.get_challenge(challenge_code)
        if not challenge:
            return []
        return challenge.get('containers', [])

    @staticmethod
    def is_container_running(challenge_code: str, container_name: str) -> bool:
        """
        检查容器是否正在运行

        Args:
            challenge_code: 挑战代码
            container_name: 容器名称

        Returns:
            容器是否运行
        """
        try:
            import docker
            # 连接到 Docker daemon (支持 socket 和环境变量)
            client = docker.DockerClient(base_url='unix://var/run/docker.sock')
            container = client.containers.get(container_name)
            return container.status == 'running'
        except Exception:
            return False


class NoteRepository:
    """笔记数据仓库

    NOTES_DIR: 宿主机路径 ~/notes（自动展开，自动创建）
    """

    NOTES_DIR = os.path.expanduser("~/notes")

    @staticmethod
    def get_note(challenge_code: str, note_type: str) -> str:
        """
        读取指定类型的笔记

        Args:
            challenge_code: 挑战代码
            note_type: 笔记类型 (info, infer, result)

        Returns:
            笔记内容
        """
        import os
        safe_code = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in challenge_code).strip()
        filepath = os.path.join(NoteRepository.NOTES_DIR, f"{safe_code}-{note_type}.md")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return ""

    @staticmethod
    def get_all_notes(challenge_code: str) -> Dict[str, str]:
        """
        获取挑战的所有笔记

        Args:
            challenge_code: 挑战代码

        Returns:
            {info: 内容, infer: 内容, result: 内容}
        """
        return {
            'info': NoteRepository.get_note(challenge_code, 'info'),
            'infer': NoteRepository.get_note(challenge_code, 'infer'),
            'result': NoteRepository.get_note(challenge_code, 'result'),
        }


class LogRepository:
    """日志数据仓库

    LOG_FILE: 调度器日志文件（相对路径）
    """

    LOG_FILE = os.path.join(PROJECT_ROOT, "task", "data", "scheduler.log")

    @staticmethod
    def get_logs(challenge_code: str, lines: int = 100) -> List[str]:
        """
        获取指定挑战的日志

        Args:
            challenge_code: 挑战代码
            lines: 返回的行数

        Returns:
            日志行列表
        """
        try:
            with open(LogRepository.LOG_FILE, 'r', encoding='utf-8') as f:
                # 读取所有行
                all_lines = f.readlines()
                # 过滤包含挑战代码的行
                filtered = [line.strip() for line in all_lines if challenge_code in line]
                # 返回最后 N 行
                return filtered[-lines:] if filtered else []
        except FileNotFoundError:
            return []

    @staticmethod
    def get_recent_logs(lines: int = 50) -> List[str]:
        """
        获取最近的日志

        Args:
            lines: 返回的行数

        Returns:
            日志行列表
        """
        try:
            with open(LogRepository.LOG_FILE, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return [line.strip() for line in all_lines[-lines:]]
        except FileNotFoundError:
            return []
