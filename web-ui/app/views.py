from django.shortcuts import render
from django.http import JsonResponse


def render_markdown(text):
    """将 markdown 文本渲染为安全的 HTML"""
    if not text:
        return ''
    import markdown
    import bleach

    # 允许的 HTML 标签和属性
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
        'th': ['align'],
        'td': ['align'],
    }

    # 使用 markdown 扩展
    md = markdown.Markdown(extensions=['fenced_code', 'codehilite', 'tables', 'toc'])
    html = md.convert(text)
    # 清理不安全的 HTML
    clean_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    from django.utils.safestring import mark_safe
    return mark_safe(clean_html)


# Tracker 相关视图已移除
# 此文件仅保留工具函数供其他模块使用
