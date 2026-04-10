"""
认证中间件 - 未登录时重定向到登录页
"""
from django.http import JsonResponse
from django.shortcuts import redirect


class AuthMiddleware:
    """
    轻量认证中间件，基于 session 检查登录状态。
    未登录用户访问任何页面都会被重定向到 /login/。
    API 请求（路径以 /api/ 开头）返回 401 JSON 响应。
    """

    EXEMPT_PATHS = ['/login/', '/logout/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # 静态文件和免认证路径放行
        if path.startswith('/static/') or path in self.EXEMPT_PATHS:
            return self.get_response(request)

        # 已认证放行
        if request.session.get('authenticated'):
            return self.get_response(request)

        # API 请求返回 401
        if path.startswith('/api/'):
            return JsonResponse({'error': '未登录'}, status=401)

        # 页面请求重定向到登录
        return redirect(f'/login/?next={path}')
