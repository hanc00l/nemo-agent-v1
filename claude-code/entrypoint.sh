#!/bin/bash
set -e

# VNC 端口: 从环境变量获取，默认 5901
export VNC_PORT=${VNC_PORT:-5901}
export BROWSER_PORT=9222
export MCP_PORT=8000
export COMPETITION_API_URL=${COMPETITION_API_URL:-http://host.docker.internal:8888}

# docker
source ~/.myrc

# 建立工具软链接
sudo /opt/nemo-agent/claude-code/setup_symlinks.sh

# 初始化msf
msfdb init

# docker启动VNC
if [ -z "${NO_VISION}" ]; then
  mkdir -p ~/.vnc && echo 123456 | vncpasswd -f > ~/.vnc/passwd && chmod 600 ~/.vnc/passwd
  vncserver $DISPLAY -rfbport $VNC_PORT -geometry 1920x1080 -depth 24 -localhost no -xstartup /usr/bin/startxfce4
fi

# 启动Playwright浏览器
python3 /opt/nemo-agent/claude-code/meta-tooling/service/browser.py --port $BROWSER_PORT > /dev/null 2>&1 &

# 启动Python Executor MCP
python3 /opt/nemo-agent/claude-code/meta-tooling/service/python_executor_mcp.py --port $MCP_PORT

