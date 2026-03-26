"""
Jupyter Session 视图 - 显示和管理 Jupyter notebook 文件
"""
import os
import json
import logging
from datetime import datetime
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.conf import settings

# 配置日志
logger = logging.getLogger(__name__)

# Jupyter notebook 文件存储目录（宿主机路径，自动展开 ~）
JUPYTER_SCRIPTS_DIR = getattr(settings, 'JUPYTER_SCRIPTS_DIR', os.path.expanduser('~/scripts'))

# 安全限制
MAX_SEARCH_QUERY_LENGTH = 100  # 搜索查询最大长度


def validate_search_query(query: str) -> str:
    """
    验证搜索查询并返回安全的查询字符串

    Args:
        query: 原始搜索查询

    Returns:
        str: 安全的搜索查询（已限制长度）

    Raises:
        Http404: 如果查询过长
    """
    if not query:
        return ""

    # 长度限制
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise Http404(f"搜索查询过长（最大 {MAX_SEARCH_QUERY_LENGTH} 字符）")

    return query


def validate_and_get_filepath(filename):
    """
    验证文件名并返回安全的文件路径

    Args:
        filename: 文件名

    Returns:
        str: 安全的文件绝对路径

    Raises:
        Http404: 如果文件名无效或路径不在允许的目录内
    """
    # 基本验证
    if not filename:
        raise Http404("文件名不能为空")

    # 检查危险字符
    if '..' in filename or '/' in filename or '\\' in filename or '\x00' in filename:
        raise Http404("无效的文件名")

    # 文件名长度限制
    if len(filename) > 255:
        raise Http404("文件名过长")

    # 必须是 .ipynb 文件
    if not filename.endswith('.ipynb'):
        raise Http404("仅支持 .ipynb 文件")

    # 构建文件路径
    filepath = os.path.join(JUPYTER_SCRIPTS_DIR, filename)

    # 解析为真实路径（处理符号链接等）
    try:
        real_filepath = os.path.realpath(filepath)
        real_base_dir = os.path.realpath(JUPYTER_SCRIPTS_DIR)
    except (OSError, ValueError) as e:
        logger.error(f"路径解析失败: {e}")
        raise Http404("无效的文件路径")

    # 验证解析后的路径仍在允许的目录内
    if not real_filepath.startswith(real_base_dir + os.sep) and real_filepath != real_base_dir:
        logger.warning(f"尝试访问目录外的文件: {real_filepath}")
        raise Http404("无效的文件路径")

    return filepath


def get_notebook_metadata(filepath):
    """
    解析 Jupyter notebook 文件，提取元数据

    Args:
        filepath: notebook 文件路径

    Returns:
        dict: 包含文件名、创建时间、单元格数量等信息，失败时返回 None
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            notebook = json.load(f)

        # 获取文件统计信息
        stat = os.stat(filepath)

        # 计算代码单元格数量
        code_cells = 0
        output_cells = 0

        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                code_cells += 1
                if cell.get('outputs'):
                    output_cells += 1

        return {
            'filename': os.path.basename(filepath),
            'filepath': filepath,
            'size': stat.st_size,
            'created': datetime.fromtimestamp(stat.st_ctime),
            'modified': datetime.fromtimestamp(stat.st_mtime),
            'code_cells': code_cells,
            'output_cells': output_cells,
            'total_cells': len(notebook.get('cells', [])),
            'kernel': notebook.get('metadata', {}).get('kernelspec', {}).get('display_name', 'Python'),
            'language': notebook.get('metadata', {}).get('kernelspec', {}).get('language', 'python'),
        }

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败 ({filepath}): {e}")
        return None
    except (OSError, IOError) as e:
        logger.warning(f"读取文件失败 ({filepath}): {e}")
        return None
    except Exception as e:
        logger.error(f"获取 notebook 元数据失败 ({filepath}): {e}")
        return None


def parse_notebook(filepath):
    """
    解析 Jupyter notebook 文件，提取所有单元格内容

    Args:
        filepath: notebook 文件路径

    Returns:
        dict: 解析后的 notebook 数据

    Raises:
        ValueError: 解析失败时
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            notebook = json.load(f)

        cells_data = []
        for idx, cell in enumerate(notebook.get('cells', [])):
            cell_data = {
                'index': idx,
                'type': cell.get('cell_type'),
                'source': ''.join(cell.get('source', [])),
                'outputs': [],
            }

            # 解析代码单元格的输出
            if cell.get('cell_type') == 'code':
                for output in cell.get('outputs', []):
                    output_data = {'output_type': output.get('output_type')}

                    # 文本输出
                    if 'text' in output:
                        output_data['text'] = ''.join(output['text'])
                    # stream 输出 (stdout/stderr)
                    elif output.get('output_type') == 'stream':
                        output_data['name'] = output.get('name')
                        output_data['text'] = ''.join(output.get('text', []))
                    # execute_result
                    elif 'data' in output:
                        data = output['data']
                        # 文本/纯文本
                        if 'text/plain' in data:
                            output_data['text'] = ''.join(data['text/plain'])
                        # 图片 (PNG base64)
                        elif 'image/png' in data:
                            output_data['image'] = data['image/png']
                        # HTML
                        elif 'text/html' in data:
                            output_data['html'] = ''.join(data['text/html'])
                        # LaTeX
                        elif 'text/latex' in data:
                            output_data['latex'] = ''.join(data['text/latex'])

                    # 错误信息
                    if 'ename' in output:
                        output_data['error'] = {
                            'name': output.get('ename'),
                            'value': output.get('evalue'),
                            'traceback': output.get('traceback', []),
                        }

                    cell_data['outputs'].append(output_data)

            cells_data.append(cell_data)

        return {
            'cells': cells_data,
            'metadata': notebook.get('metadata', {}),
        }

    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {str(e)}")
    except Exception as e:
        raise ValueError(f"解析 notebook 文件失败: {str(e)}")


@require_http_methods(["GET"])
def jupyter_list_page(request):
    """
    Jupyter session 列表页面

    显示 /opt/scripts 目录下的所有 .ipynb 文件

    Query params:
        - search: 搜索关键词，模糊匹配文件名中的 challenge_code
    """
    try:
        raw_search = request.GET.get('search', '').strip()
        search_query = validate_search_query(raw_search) if raw_search else ""

        # 验证目录存在
        if not os.path.exists(JUPYTER_SCRIPTS_DIR):
            logger.error(f"Jupyter 目录不存在: {JUPYTER_SCRIPTS_DIR}")
            context = {
                'files': [],
                'total_files': 0,
                'total_size': 0,
                'total_code_cells': 0,
                'scripts_dir': JUPYTER_SCRIPTS_DIR,
                'error': f"目录不存在: {JUPYTER_SCRIPTS_DIR}",
                'search_query': search_query,
            }
            return render(request, 'jupyter_list.html', context)

        # 获取所有 .ipynb 文件
        files = []
        for filename in os.listdir(JUPYTER_SCRIPTS_DIR):
            if filename.endswith('.ipynb'):
                filepath = os.path.join(JUPYTER_SCRIPTS_DIR, filename)
                metadata = get_notebook_metadata(filepath)
                if metadata:
                    files.append(metadata)

        # 搜索过滤
        if search_query:
            search_lower = search_query.lower()
            files = [f for f in files if search_lower in f['filename'].lower()]

        # 按修改时间降序排列（最新的在前）
        files.sort(key=lambda x: x['modified'], reverse=True)

        # 统计信息
        total_files = len(files)
        total_size = sum(f['size'] for f in files)
        total_code_cells = sum(f['code_cells'] for f in files)

        context = {
            'files': files,
            'total_files': total_files,
            'total_size': total_size,
            'total_code_cells': total_code_cells,
            'scripts_dir': JUPYTER_SCRIPTS_DIR,
            'search_query': search_query,
        }
        return render(request, 'jupyter_list.html', context)

    except Exception as e:
        logger.exception(f"加载 Jupyter 列表失败: {e}")
        context = {
            'files': [],
            'total_files': 0,
            'total_size': 0,
            'total_code_cells': 0,
            'scripts_dir': JUPYTER_SCRIPTS_DIR,
            'error': str(e),
            'search_query': request.GET.get('search', ''),
        }
        return render(request, 'jupyter_list.html', context)


@require_http_methods(["GET"])
def jupyter_detail_page(request, filename):
    """
    Jupyter session 详情页面

    显示指定 notebook 文件的详细内容

    Args:
        filename: notebook 文件名
    """
    # 验证并获取安全的文件路径
    filepath = validate_and_get_filepath(filename)

    if not os.path.exists(filepath):
        raise Http404(f"文件 {filename} 不存在")

    try:
        # 解析 notebook
        notebook_data = parse_notebook(filepath)
        metadata = get_notebook_metadata(filepath)

        context = {
            'filename': filename,
            'metadata': metadata,
            'cells': notebook_data['cells'],
            'notebook_metadata': notebook_data['metadata'],
        }
        return render(request, 'jupyter_detail.html', context)

    except ValueError as e:
        raise Http404(str(e))
    except Exception as e:
        logger.exception(f"加载 Jupyter 详情失败: {e}")
        context = {
            'filename': filename,
            'error': str(e),
        }
        return render(request, 'jupyter_detail.html', context)


@require_http_methods(["GET"])
def api_jupyter_list(request):
    """
    获取 Jupyter notebook 列表 API

    Query params:
        - search: 搜索关键词，模糊匹配文件名中的 challenge_code (可选)

    Returns:
        JSON 格式的文件列表
    """
    try:
        raw_search = request.GET.get('search', '').strip()
        search_query = validate_search_query(raw_search).lower() if raw_search else ""

        files = []
        if os.path.exists(JUPYTER_SCRIPTS_DIR):
            for filename in os.listdir(JUPYTER_SCRIPTS_DIR):
                if filename.endswith('.ipynb'):
                    filepath = os.path.join(JUPYTER_SCRIPTS_DIR, filename)
                    metadata = get_notebook_metadata(filepath)
                    if metadata:
                        # 转换 datetime 为字符串
                        metadata['created'] = metadata['created'].isoformat()
                        metadata['modified'] = metadata['modified'].isoformat()
                        files.append(metadata)

        # 搜索过滤（模糊匹配 challenge_code 或 filename）
        if search_query:
            files = [f for f in files if search_query in f['filename'].lower()]

        # 按修改时间降序排列
        files.sort(key=lambda x: x['modified'], reverse=True)

        return JsonResponse({'files': files, 'total': len(files)})

    except Exception as e:
        logger.exception(f"API 获取 Jupyter 列表失败: {e}")
        return JsonResponse({'error': str(e), 'files': [], 'total': 0}, status=500)


@require_http_methods(["GET"])
def api_jupyter_detail(request, filename):
    """
    获取 Jupyter notebook 详情 API

    Args:
        filename: notebook 文件名

    Returns:
        JSON 格式的 notebook 数据
    """
    # 验证并获取安全的文件路径
    try:
        filepath = validate_and_get_filepath(filename)
    except Http404 as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not os.path.exists(filepath):
        return JsonResponse({'error': f'文件 {filename} 不存在'}, status=404)

    try:
        notebook_data = parse_notebook(filepath)
        metadata = get_notebook_metadata(filepath)

        if not metadata:
            return JsonResponse({'error': '无法读取文件元数据'}, status=500)

        # 转换 datetime 为字符串
        metadata['created'] = metadata['created'].isoformat()
        metadata['modified'] = metadata['modified'].isoformat()

        return JsonResponse({
            'filename': filename,
            'metadata': metadata,
            'cells': notebook_data['cells'],
            'notebook_metadata': notebook_data['metadata'],
        })

    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=500)
    except Exception as e:
        logger.exception(f"API 获取 Jupyter 详情失败: {e}")
        return JsonResponse({'error': str(e)}, status=500)
