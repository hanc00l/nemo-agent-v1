"""
仪表板视图 - 显示解题进度和统计
"""
import sys
import os

# 添加项目根目录到 Python 路径（必须在模块导入之前）
# 支持从项目根目录运行或从 web-ui 目录运行
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.safestring import mark_safe
import markdown
import bleach
import time
import json
import hashlib
from .repositories import ChallengeRepository, NoteRepository, LogRepository


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


def render_markdown(text):
    """将 markdown 文本渲染为安全的 HTML"""
    if not text:
        return ''
    md = markdown.Markdown(extensions=['fenced_code', 'tables', 'toc'])
    html = md.convert(text)
    clean_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    return mark_safe(clean_html)


@require_http_methods(["GET"])
def dashboard_page(request):
    """
    仪表板页面 - 显示所有挑战和解题进度
    """
    # 获取统计数据
    stats = ChallengeRepository.get_statistics()

    # 获取所有挑战，按状态分组
    all_challenges = ChallengeRepository.get_all_challenges()

    # 按状态分组
    open_challenges = [c for c in all_challenges if c.get('state') == 'open']
    started_challenges = [c for c in all_challenges if c.get('state') == 'started']
    success_challenges = [c for c in all_challenges if c.get('state') == 'success']
    fail_challenges = [c for c in all_challenges if c.get('state') == 'fail']
    close_challenges = [c for c in all_challenges if c.get('state') == 'close']

    # 计算成功率
    success_rate = 0
    finished_count = stats['success'] + stats['fail']
    if finished_count > 0:
        success_rate = round(stats['success'] / finished_count * 100, 1)

    # 计算平均解题时间
    avg_time = "N/A"
    success_challenges_with_time = [c for c in success_challenges if c.get('started_at') and c.get('updated_at')]
    if success_challenges_with_time:
        try:
            import iso8601
            from datetime import datetime

            total_seconds = 0
            for c in success_challenges_with_time:
                start = datetime.fromisoformat(c['started_at'].replace('+00:00', ''))
                end = datetime.fromisoformat(c['updated_at'].replace('+00:00', ''))
                total_seconds += (end - start).total_seconds()

            avg_seconds = total_seconds / len(success_challenges_with_time)
            avg_time = f"{int(avg_seconds // 60)}分{int(avg_seconds % 60)}秒"
        except:
            pass

    context = {
        'stats': stats,
        'success_rate': success_rate,
        'avg_time': avg_time,
        'open_challenges': open_challenges,
        'started_challenges': started_challenges,
        'success_challenges': success_challenges,
        'fail_challenges': fail_challenges,
        'close_challenges': close_challenges,
    }
    response = render(request, 'dashboard.html', context)
    # 禁用缓存，确保总是获取最新数据
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@require_http_methods(["GET"])
def api_dashboard_stats(request):
    """
    获取仪表板统计数据 API

    Returns:
        JSON 格式的统计数据
    """
    stats = ChallengeRepository.get_statistics()

    # 计算成功率
    finished_count = stats['success'] + stats['fail']
    success_rate = 0
    if finished_count > 0:
        success_rate = round(stats['success'] / finished_count * 100, 1)

    return JsonResponse({
        'stats': stats,
        'success_rate': success_rate,
        'timestamp': ChallengeRepository.get_json_data().get('last_updated')
    })


@require_http_methods(["GET"])
def api_challenges_list(request):
    """
    获取挑战列表 API

    Query params:
        - state: 过滤状态 (可选)
        - limit: 限制数量 (可选，默认 50)

    Returns:
        JSON 格式的挑战列表
    """
    state_filter = request.GET.get('state')
    limit = int(request.GET.get('limit', 50))

    if state_filter:
        challenges = ChallengeRepository.get_challenges_by_state(state_filter)
    else:
        challenges = ChallengeRepository.get_all_challenges()

    # 按 updated_at 降序排序（最新的在最前面）
    challenges = sorted(
        challenges,
        key=lambda x: x.get('updated_at') or '',
        reverse=True
    )

    # 限制数量
    challenges = challenges[:limit]

    # 添加容器运行状态
    for challenge in challenges:
        if challenge.get('state') == 'started':
            challenge['containers_running'] = []
            for container_name in challenge.get('containers', []):
                is_running = ChallengeRepository.is_container_running(
                    challenge['challenge_code'],
                    container_name
                )
                challenge['containers_running'].append({
                    'name': container_name,
                    'running': is_running
                })

    return JsonResponse({'challenges': challenges})


@require_http_methods(["GET"])
def api_challenge_detail(request, challenge_code):
    """
    获取挑战详情 API

    Returns:
        JSON 格式的挑战详情
    """
    challenge = ChallengeRepository.get_challenge(challenge_code)

    if not challenge:
        return JsonResponse({'error': '挑战不存在'}, status=404)

    # 获取笔记
    notes = NoteRepository.get_all_notes(challenge_code)

    # 获取容器运行状态
    containers_status = []
    for container_name in challenge.get('containers', []):
        is_running = ChallengeRepository.is_container_running(challenge_code, container_name)
        containers_status.append({
            'name': container_name,
            'running': is_running
        })

    # 计算运行时间
    elapsed_time = None
    if challenge.get('started_at'):
        try:
            import iso8601
            from datetime import datetime, timezone

            start = datetime.fromisoformat(challenge['started_at'].replace('+00:00', ''))
            now = datetime.now(timezone.utc)
            elapsed = now - start
            elapsed_seconds = elapsed.total_seconds()
            elapsed_time = f"{int(elapsed_seconds // 60)}分{int(elapsed_seconds % 60)}秒"
        except:
            pass

    return JsonResponse({
        'challenge': challenge,
        'notes': notes,
        'containers_status': containers_status,
        'elapsed_time': elapsed_time
    })


@require_http_methods(["GET"])
def api_challenge_logs(request, challenge_code):
    """
    获取挑战日志 API

    Query params:
        - lines: 返回的行数 (可选，默认 100)

    Returns:
        JSON 格式的日志列表
    """
    lines = int(request.GET.get('lines', 100))
    logs = LogRepository.get_logs(challenge_code, lines)

    return JsonResponse({'logs': logs})


@require_http_methods(["GET"])
def api_challenge_notes(request, challenge_code):
    """
    获取挑战笔记 API

    Returns:
        JSON 格式的笔记内容
    """
    notes = NoteRepository.get_all_notes(challenge_code)

    return JsonResponse({'notes': notes})


@require_http_methods(["GET"])
def challenge_detail_page(request, challenge_code):
    """
    挑战详情页面 - 显示实时状态、日志、笔记等

    Args:
        challenge_code: 挑战代码
    """
    challenge = ChallengeRepository.get_challenge(challenge_code)

    if not challenge:
        # 如果挑战不存在，返回 404
        from django.http import Http404
        raise Http404(f"挑战 {challenge_code} 不存在")

    # 获取笔记
    notes = NoteRepository.get_all_notes(challenge_code)

    # 获取容器运行状态
    containers_status = []
    for container_name in challenge.get('containers', []):
        is_running = ChallengeRepository.is_container_running(challenge_code, container_name)
        containers_status.append({
            'name': container_name,
            'running': is_running
        })

    # 计算运行时间
    elapsed_time = None
    if challenge.get('started_at'):
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(challenge['started_at'].replace('+00:00', ''))
            now = datetime.now(timezone.utc)
            elapsed = now - start
            elapsed_seconds = elapsed.total_seconds()
            elapsed_time = f"{int(elapsed_seconds // 60)}分{int(elapsed_seconds % 60)}秒"
        except:
            pass

    context = {
        'challenge': challenge,
        'notes': notes,
        'containers_status': containers_status,
        'elapsed_time': elapsed_time,
    }
    response = render(request, 'challenge_detail.html', context)
    # 禁用缓存，确保总是获取最新数据
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


# ============================================================================
# SSE (Server-Sent Events) 实时更新端点
# ============================================================================

def event_stream(challenge_code=None):
    """
    生成 SSE 事件流

    Args:
        challenge_code: 如果提供，只推送该挑战的更新；否则推送所有挑战更新

    Yields:
        SSE 格式的数据行
    """
    last_data_hash = None
    iteration = 0

    while True:
        try:
            if challenge_code:
                # 单个挑战更新
                challenge = ChallengeRepository.get_challenge(challenge_code)
                if not challenge:
                    yield f"event: error\ndata: {{'message': '挑战不存在'}}\n\n"
                    break

                # 获取容器状态
                containers_status = []
                for container_name in challenge.get('containers', []):
                    is_running = ChallengeRepository.is_container_running(challenge_code, container_name)
                    containers_status.append({
                        'name': container_name,
                        'running': is_running
                    })

                data = {
                    'type': 'challenge_update',
                    'challenge_code': challenge_code,
                    'state': challenge.get('state'),
                    'containers_status': containers_status,
                    'result': challenge.get('result'),
                    'updated_at': challenge.get('updated_at'),
                }
            else:
                # 仪表板统计更新
                stats = ChallengeRepository.get_statistics()
                data = {
                    'type': 'dashboard_update',
                    'stats': stats,
                }

            # 计算数据哈希，只在数据变化时发送
            import hashlib
            data_str = json.dumps(data, sort_keys=True)
            data_hash = hashlib.md5(data_str.encode()).hexdigest()

            if data_hash != last_data_hash or iteration % 10 == 0:
                # 每10次迭代强制发送一次（保持连接活跃）
                yield f"data: {data_str}\n\n"
                last_data_hash = data_hash

            iteration += 1
            time.sleep(2)  # 每2秒检查一次

        except GeneratorExit:
            # 客户端断开连接
            break
        except Exception as e:
            # 发送错误并继续
            error_data = json.dumps({'type': 'error', 'message': str(e)})
            yield f"event: error\ndata: {error_data}\n\n"
            time.sleep(5)


@require_http_methods(["GET"])
def sse_dashboard_updates(request):
    """
    SSE 端点 - 仪表板实时更新

    推送统计数据变化
    """
    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["GET"])
def sse_challenge_updates(request, challenge_code):
    """
    SSE 端点 - 单个挑战实时更新

    推送挑战状态变化、容器状态变化等

    Args:
        challenge_code: 挑战代码
    """
    response = StreamingHttpResponse(
        event_stream(challenge_code),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["GET"])
def sse_logs_stream(request, challenge_code):
    """
    SSE 端点 - 实时日志流

    推送新增的日志行

    Args:
        challenge_code: 挑战代码

    Query params:
        - tail: 从最后几行开始 (可选，默认 50)
    """
    tail_lines = int(request.GET.get('tail', 50))
    last_lines_count = tail_lines

    def log_stream():
        nonlocal last_lines_count
        last_log_hash = None

        while True:
            try:
                logs = LogRepository.get_logs(challenge_code, 200)

                if logs:
                    # 只发送新增的日志
                    new_logs = logs[-last_lines_count:] if len(logs) > last_lines_count else logs

                    for log in new_logs:
                        # 计算日志哈希避免重复
                        log_hash = hashlib.md5(log.encode()).hexdigest()
                        if log_hash != last_log_hash:
                            log_data = json.dumps({
                                'type': 'log',
                                'content': log,
                                'timestamp': time.time()
                            })
                            yield f"data: {log_data}\n\n"
                            last_log_hash = log_hash

                last_lines_count = len(logs) if logs else 0
                time.sleep(1)  # 每秒检查一次

            except GeneratorExit:
                break
            except Exception as e:
                error_data = json.dumps({'type': 'error', 'message': str(e)})
                yield f"event: error\ndata: {error_data}\n\n"
                time.sleep(5)

    response = StreamingHttpResponse(
        log_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


# ============================================================================
# Agent 解题进度相关 API
# ============================================================================

@require_http_methods(["GET"])
def api_challenge_procs(request, challenge_code):
    """
    获取挑战的 Agent 解题进度（已弃用 tracker 功能）

    Args:
        challenge_code: 挑战代码

    Returns:
        JSON 格式的空响应（tracker 功能已移除）
    """
    return JsonResponse({
        'subject_id': None,
        'challenge_code': challenge_code,
        'procs': [],
        'message': 'Tracker 功能已移除'
    })


@require_http_methods(["GET"])
def api_challenge_procs_since(request, challenge_code, last_id):
    """
    增量获取挑战的 Agent 解题进度（已弃用 tracker 功能）

    Args:
        challenge_code: 挑战代码
        last_id: 上次获取的最后一个 proc ID

    Returns:
        JSON 格式的空响应（tracker 功能已移除）
    """
    return JsonResponse({'procs': []})


@require_http_methods(["GET"])
def sse_challenge_procs(request, challenge_code):
    """
    SSE 端点 - Agent 解题进度实时流（已弃用 tracker 功能）

    仅发送心跳保持连接

    Args:
        challenge_code: 挑战代码
    """
    def procs_stream():
        iteration = 0

        while True:
            try:
                # 每10次迭代发送一次心跳
                if iteration % 10 == 0:
                    heartbeat = json.dumps({
                        'type': 'heartbeat',
                        'timestamp': time.time()
                    })
                    yield f"data: {heartbeat}\n\n"

                iteration += 1
                time.sleep(2)

            except GeneratorExit:
                break
            except Exception as e:
                error_data = json.dumps({'type': 'error', 'message': str(e)})
                yield f"event: error\ndata: {error_data}\n\n"
                time.sleep(5)

    response = StreamingHttpResponse(
        procs_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response



