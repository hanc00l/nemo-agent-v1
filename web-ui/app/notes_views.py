"""
Notes 视图 - 显示和管理 Agent 笔记文件
"""
import os
import re
import logging
from datetime import datetime
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils.safestring import mark_safe
import markdown
import bleach

# 配置日志
logger = logging.getLogger(__name__)

# Notes 文件存储目录（宿主机路径，自动展开 ~）
NOTES_DIR = getattr(settings, 'NOTES_DIR', os.path.expanduser('~/notes'))

# 验证常量
DANGEROUS_CHARS = ['..', '/', '\\', '\x00']
MAX_CHALLENGE_CODE_LENGTH = 128
MAX_SEARCH_QUERY_LENGTH = 100  # 搜索查询最大长度
VALID_NOTE_TYPES = ['info', 'infer', 'result']

# Markdown 渲染配置
ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr',
    'ul', 'ol', 'li',
    'blockquote', 'pre', 'code',
    'strong', 'em', 'b', 'i', 'u',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'div', 'span',
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title'],
    'code': ['class'],
    'pre': ['class'],
    'div': ['class'],
    'span': ['class'],
    'table': ['class'],
}


def validate_challenge_code(challenge_code):
    """
    验证挑战代码

    Args:
        challenge_code: 挑战代码

    Raises:
        Http404: 如果挑战代码无效
    """
    if not challenge_code:
        raise Http404("挑战代码不能为空")

    # 检查危险字符
    for char in DANGEROUS_CHARS:
        if char in challenge_code:
            raise Http404("无效的挑战代码")

    # 长度限制
    if len(challenge_code) > MAX_CHALLENGE_CODE_LENGTH:
        raise Http404("挑战代码过长")


def validate_search_query(query: str) -> str:
    """
    验证搜索查询并返回安全的查询字符串

    Args:
        query: 原始搜索查询

    Returns:
        str: 安全的搜索查询（已去除危险字符并限制长度）

    Raises:
        Http404: 如果查询过长或包含无效字符
    """
    if not query:
        return ""

    # 长度限制
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise Http404(f"搜索查询过长（最大 {MAX_SEARCH_QUERY_LENGTH} 字符）")

    # 只允许字母、数字、常见符号（用于 challenge_code 匹配）
    # challenge_code 可能包含: 字母、数字、连字符、下划线、点
    allowed_pattern = re.compile(r'^[\w\-\.\:\s]+$')
    if not allowed_pattern.match(query):
        raise Http404("搜索查询包含无效字符")

    return query


def validate_and_get_filepath(challenge_code, note_type):
    """
    验证参数并返回安全的文件路径

    Args:
        challenge_code: 挑战代码
        note_type: 笔记类型 (info/infer/result)

    Returns:
        tuple: (文件路径, 锁文件路径)

    Raises:
        Http404: 如果参数无效
    """
    # 验证 challenge_code
    validate_challenge_code(challenge_code)

    # 验证笔记类型
    if note_type not in VALID_NOTE_TYPES:
        raise Http404(f"无效的笔记类型，必须是: {', '.join(VALID_NOTE_TYPES)}")

    # 构建文件名
    filename = f"{challenge_code}-{note_type}.md"
    filepath = os.path.join(NOTES_DIR, filename)

    # 解析为真实路径
    try:
        real_filepath = os.path.realpath(filepath)
        real_base_dir = os.path.realpath(NOTES_DIR)
    except (OSError, ValueError) as e:
        logger.error(f"路径解析失败: {e}")
        raise Http404("无效的文件路径")

    # 验证路径在允许的目录内
    if not real_filepath.startswith(real_base_dir + os.sep):
        logger.warning(f"尝试访问目录外的文件: {real_filepath}")
        raise Http404("无效的文件路径")

    return filepath, filename


def parse_challenge_code_from_filename(filename):
    """
    从文件名解析挑战代码和笔记类型

    Args:
        filename: 文件名 (格式: {challenge_code}-{type}.md)

    Returns:
        tuple: (challenge_code, note_type) 或 None
    """
    # 匹配格式: {challenge_code}-{info|infer|result}.md
    # challenge_code 可能包含 UUID 或 IP 格式
    match = re.match(r'^(.+)-(info|infer|result)\.md$', filename)
    if match:
        return match.group(1), match.group(2)
    return None, None


def get_note_files():
    """
    获取所有笔记文件信息

    Returns:
        list: 笔记文件信息列表
    """
    notes = []

    if not os.path.exists(NOTES_DIR):
        logger.error(f"Notes 目录不存在: {NOTES_DIR}")
        return notes

    try:
        # 获取所有 .md 文件（排除 .lock 文件）
        for filename in os.listdir(NOTES_DIR):
            if filename.endswith('.md') and not filename.endswith('.lock'):
                challenge_code, note_type = parse_challenge_code_from_filename(filename)
                if challenge_code and note_type:
                    filepath = os.path.join(NOTES_DIR, filename)
                    stat = os.stat(filepath)

                    # 读取文件内容获取预览
                    preview = ""
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                            # 获取前 200 个字符作为预览
                            preview = content[:200].strip()
                            if len(content) > 200:
                                preview += "..."
                    except Exception as e:
                        logger.warning(f"读取文件预览失败 ({filepath}): {e}")
                        preview = "[无法读取]"

                    notes.append({
                        'challenge_code': challenge_code,
                        'note_type': note_type,
                        'filename': filename,
                        'size': stat.st_size,
                        'created': datetime.fromtimestamp(stat.st_ctime),
                        'modified': datetime.fromtimestamp(stat.st_mtime),
                        'preview': preview,
                    })
    except Exception as e:
        logger.exception(f"获取笔记文件列表失败: {e}")

    return notes


def render_markdown(text):
    """
    将 markdown 文本渲染为安全的 HTML

    Args:
        text: markdown 文本

    Returns:
        str: 安全的 HTML
    """
    if not text:
        return ''

    try:
        # 使用 markdown 扩展
        md = markdown.Markdown(extensions=['fenced_code', 'codehilite', 'tables', 'toc'])
        html = md.convert(text)
        # 清理不安全的 HTML
        clean_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
        return mark_safe(clean_html)
    except Exception as e:
        logger.error(f"Markdown 渲染失败: {e}")
        return f"<pre>{text}</pre>"


def group_notes_by_challenge(notes):
    """
    按挑战代码分组笔记

    Args:
        notes: 笔记列表

    Returns:
        dict: 按挑战代码分组的笔记
    """
    grouped = {}
    for note in notes:
        code = note['challenge_code']
        if code not in grouped:
            grouped[code] = {
                'challenge_code': code,
                'notes': {},
                'latest_update': note['modified'],
            }
        grouped[code]['notes'][note['note_type']] = note
        # 更新最新修改时间
        if note['modified'] > grouped[code]['latest_update']:
            grouped[code]['latest_update'] = note['modified']

    # 转换为列表并排序
    result = list(grouped.values())
    result.sort(key=lambda x: x['latest_update'], reverse=True)
    return result


@require_http_methods(["GET"])
def notes_list_page(request):
    """
    Notes 列表页面

    显示 /opt/notes 目录下的所有笔记文件，按挑战代码分组

    Query params:
        - search: 搜索关键词，模糊匹配 challenge_code
    """
    try:
        raw_search = request.GET.get('search', '').strip()
        search_query = validate_search_query(raw_search) if raw_search else ""

        # 获取所有笔记文件
        notes = get_note_files()

        # 搜索过滤
        if search_query:
            search_lower = search_query.lower()
            notes = [n for n in notes if search_lower in n['challenge_code'].lower()]

        # 按挑战代码分组
        grouped_notes = group_notes_by_challenge(notes)

        # 统计信息
        total_notes = len(notes)
        total_challenges = len(grouped_notes)
        total_size = sum(n['size'] for n in notes)

        # 按类型统计
        type_counts = {'info': 0, 'infer': 0, 'result': 0}
        for note in notes:
            type_counts[note['note_type']] = type_counts.get(note['note_type'], 0) + 1

        context = {
            'grouped_notes': grouped_notes,
            'total_notes': total_notes,
            'total_challenges': total_challenges,
            'total_size': total_size,
            'type_counts': type_counts,
            'notes_dir': NOTES_DIR,
            'search_query': search_query,
        }
        return render(request, 'notes_list.html', context)

    except Exception as e:
        logger.exception(f"加载 Notes 列表失败: {e}")
        context = {
            'grouped_notes': [],
            'total_notes': 0,
            'total_challenges': 0,
            'total_size': 0,
            'type_counts': {'info': 0, 'infer': 0, 'result': 0},
            'notes_dir': NOTES_DIR,
            'error': str(e),
            'search_query': request.GET.get('search', ''),
        }
        return render(request, 'notes_list.html', context)


@require_http_methods(["GET"])
def notes_detail_page(request, challenge_code, note_type):
    """
    Note 详情页面

    显示指定笔记文件的详细内容

    Args:
        challenge_code: 挑战代码
        note_type: 笔记类型 (info/infer/result)
    """
    # 验证并获取安全的文件路径
    filepath, filename = validate_and_get_filepath(challenge_code, note_type)

    if not os.path.exists(filepath):
        raise Http404(f"笔记文件 {filename} 不存在")

    try:
        # 读取文件内容
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 渲染 Markdown
        html_content = render_markdown(content)

        # 获取文件信息
        stat = os.stat(filepath)

        # 获取该挑战的所有笔记类型
        available_types = []
        for t in ['info', 'infer', 'result']:
            test_filepath = os.path.join(NOTES_DIR, f"{challenge_code}-{t}.md")
            if os.path.exists(test_filepath):
                available_types.append(t)

        context = {
            'challenge_code': challenge_code,
            'note_type': note_type,
            'filename': filename,
            'content': content,
            'html_content': html_content,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime),
            'available_types': available_types,
        }
        return render(request, 'notes_detail.html', context)

    except Exception as e:
        logger.exception(f"加载 Note 详情失败: {e}")
        context = {
            'challenge_code': challenge_code,
            'note_type': note_type,
            'filename': filename,
            'error': str(e),
        }
        return render(request, 'notes_detail.html', context)


@require_http_methods(["GET"])
def notes_challenge_page(request, challenge_code):
    """
    挑战的所有笔记页面

    显示指定挑战的所有类型笔记

    Args:
        challenge_code: 挑战代码
    """
    # 验证挑战代码
    validate_challenge_code(challenge_code)

    try:
        notes_data = {}
        latest_update = None

        for note_type in VALID_NOTE_TYPES:
            filename = f"{challenge_code}-{note_type}.md"
            filepath = os.path.join(NOTES_DIR, filename)

            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                stat = os.stat(filepath)
                modified = datetime.fromtimestamp(stat.st_mtime)

                notes_data[note_type] = {
                    'content': content,
                    'html_content': render_markdown(content),
                    'size': stat.st_size,
                    'modified': modified,
                }

                if not latest_update or modified > latest_update:
                    latest_update = modified

        if not notes_data:
            raise Http404(f"挑战 {challenge_code} 没有笔记")

        context = {
            'challenge_code': challenge_code,
            'notes_data': notes_data,
            'latest_update': latest_update,
            'notes_dir': NOTES_DIR,
        }
        return render(request, 'notes_challenge.html', context)

    except Http404:
        raise
    except Exception as e:
        logger.exception(f"加载挑战笔记失败: {e}")
        context = {
            'challenge_code': challenge_code,
            'notes_data': {},
            'error': str(e),
        }
        return render(request, 'notes_challenge.html', context)


@require_http_methods(["GET"])
def api_notes_list(request):
    """
    获取笔记列表 API

    Query params:
        - search: 搜索关键词，模糊匹配 challenge_code (可选)
        - challenge_code: 精确过滤指定挑战的笔记 (可选，优先级高于 search)

    Returns:
        JSON 格式的笔记列表
    """
    try:
        raw_search = request.GET.get('search', '').strip()
        search_query = validate_search_query(raw_search).lower() if raw_search else ""
        challenge_filter = request.GET.get('challenge_code')

        notes = get_note_files()

        # 优先使用精确匹配
        if challenge_filter:
            notes = [n for n in notes if n['challenge_code'] == challenge_filter]
        elif search_query:
            # 模糊匹配 challenge_code
            notes = [n for n in notes if search_query in n['challenge_code'].lower()]

        # 转换 datetime 为字符串
        for note in notes:
            note['created'] = note['created'].isoformat()
            note['modified'] = note['modified'].isoformat()

        return JsonResponse({
            'notes': notes,
            'total': len(notes)
        })

    except Exception as e:
        logger.exception(f"API 获取笔记列表失败: {e}")
        return JsonResponse({'error': '获取笔记列表失败', 'notes': [], 'total': 0}, status=500)


@require_http_methods(["GET"])
def api_note_detail(request, challenge_code, note_type):
    """
    获取笔记详情 API

    Args:
        challenge_code: 挑战代码
        note_type: 笔记类型

    Returns:
        JSON 格式的笔记数据
    """
    try:
        filepath, filename = validate_and_get_filepath(challenge_code, note_type)
    except Http404:
        return JsonResponse({'error': '无效的参数'}, status=400)

    if not os.path.exists(filepath):
        return JsonResponse({'error': '笔记文件不存在'}, status=404)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        stat = os.stat(filepath)

        return JsonResponse({
            'challenge_code': challenge_code,
            'note_type': note_type,
            'filename': filename,
            'content': content,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    except Exception as e:
        logger.exception(f"API 获取笔记详情失败: {e}")
        return JsonResponse({'error': '获取笔记详情失败'}, status=500)
