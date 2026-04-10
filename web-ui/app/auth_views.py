"""
认证视图 - 用户名密码登录/登出
"""
from django.shortcuts import render, redirect
from django.conf import settings


def login_view(request):
    """
    登录页面 - 用户名和密码验证
    """
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        if username == settings.WEB_UI_USERNAME and password == settings.WEB_UI_PASSWORD:
            request.session['authenticated'] = True
            next_url = request.GET.get('next') or '/'
            # 只允许站内相对路径，防止开放重定向
            if not next_url.startswith('/') or next_url.startswith('//'):
                next_url = '/'
            return redirect(next_url)
        else:
            return render(request, 'login.html', {
                'error': '用户名或密码错误',
            })
    return render(request, 'login.html')


def logout_view(request):
    """
    登出 - 清除 session
    """
    request.session.flush()
    return redirect('/login/')
