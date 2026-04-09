#!/bin/bash
#
# Nemo Agent - Ubuntu 24.04 LTS 完整环境自动安装脚本
#
# 使用方法:
#   chmod +x install_all.sh && sudo ./install_all.sh
#

#
# 适用: Ubuntu 24.04 LTS 实体机 (非 Docker)
#

set -euo pipefail

# ============================================================================
# 颜色和日志
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

STEP=0
TOTAL=7

log_info()  { echo -e "${GREEN}[+]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[-]${NC} $1"; }
log_step()  { STEP=$((STEP+1)); echo -e "\n${BLUE}=== [${STEP}/${TOTAL}] $1 ===${NC}\n"; }

# ============================================================================
# 前置检查
# ============================================================================
if [ "$(id -u)" -ne 0 ]; then
    log_error "请使用 sudo 运行此脚本: sudo ./install_all.sh"
    exit 1
fi

if [ ! -f /etc/lsb-release ] || ! grep -q "Ubuntu" /etc/lsb-release 2>/dev/null; then
    log_warn "此脚本针对 Ubuntu 设计，在其他发行版上可能不兼容"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRDPARTY_DIR="$SCRIPT_DIR/thirdparty"
VENV_DIR="$SCRIPT_DIR/.venv"
WORKSPACE_DIR="/opt/workspace"

export DEBIAN_FRONTEND=noninteractive

log_info "=========================================="
log_info " Nemo Agent 完整环境自动安装"
log_info " 目标系统: Ubuntu 24.04 LTS (实体机)"
log_info "=========================================="
echo ""

# ============================================================================
# 系统更新 + 基础工具
# ============================================================================
log_step "系统更新 + 基础工具"

apt-get update -qq

apt-get install -y \
    curl wget git vim tmux htop \
    net-tools iputils-ping netcat-openbsd dnsutils \
    unzip jq sqlite3 p7zip-full \
    python3-venv python3-pip python3-full \
    build-essential libssl-dev libffi-dev python3-dev \
    libnss3-tools \
    pipx \
    openjdk-21-jre-headless

log_info "基础工具安装完成"


# ============================================================================
# 浏览器 (Chrome/Chromium)
# ============================================================================
log_step "浏览器 (Chrome/Chromium)"

if ! command -v google-chrome &>/dev/null && ! command -v google-chrome-stable &>/dev/null; then
    log_info "安装 Google Chrome..."
    if wget -q "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" -O /tmp/google-chrome.deb; then
        dpkg -i /tmp/google-chrome.deb 2>/dev/null || \
            (apt-get install -y -f && dpkg -i /tmp/google-chrome.deb)
        rm -f /tmp/google-chrome.deb
        log_info "Google Chrome 已安装"
    else
        log_warn "Chrome 下载失败，安装 Chromium..."
        apt-get install -y chromium-browser || apt-get install -y chromium
    fi
else
    log_info "Chrome 已存在，跳过"
fi

# 确认浏览器可执行
CHROME_CMD=""
for cmd in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$cmd" &>/dev/null; then
        CHROME_CMD=$cmd
        break
    fi
done
if [ -n "$CHROME_CMD" ]; then
    log_info "浏览器: $CHROME_CMD"
else
    log_error "未检测到浏览器"
fi

# ============================================================================
# Python 环境 + 依赖
# ============================================================================
log_step "Python 环境 + 依赖"

# pipx
pipx ensurepath 2>/dev/null || true

# 虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    log_info "Python venv 创建: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# 核心 MCP + 执行器 + 浏览器 + 终端
pip install -q \
    fastmcp>=0.1.0 \
    jupyter-client>=8.0.0 \
    jupyter-core>=5.0.0 \
    ipykernel>=6.25.0 \
    nbformat>=5.9.0 \
    playwright>=1.40.0 \
    requests>=2.28.0 \
    pydantic>=2.0.0 \
    psutil>=5.9.0 \
    libtmux>=0.12.0 \
    python-dotenv>=1.0.0 \
    docstring-parser>=0.15

# solver / container 管理
pip install -q \
    docker>=7.0.0

# Web UI
pip install -q \
    "django>=5.0" \
    "markdown>=3.5" \
    "bleach>=6.0"

# 开发/测试
pip install -q \
    pytest>=7.0.0 \
    pytest-asyncio>=0.21.0

# 配置 ipykernel
python -m ipykernel install --user --name python3 2>/dev/null || true

# Playwright 浏览器 (使用系统 Chrome, 不下载)
export PLAYWRIGHT_BROWSERS_PATH=0
log_info "Playwright 使用系统浏览器 ($CHROME_CMD)"

deactivate

log_info "Python 依赖安装完成"

# ============================================================================
# 渗透测试工具 (apt)
# ============================================================================
log_step "渗透测试工具 (apt 安装)"

# --- nmap ---
if ! command -v nmap &>/dev/null; then
    apt-get install -y nmap
    log_info "nmap 已安装"
else
    log_info "nmap 已存在"
fi

# --- whatweb ---
if ! command -v whatweb &>/dev/null; then
    apt-get install -y whatweb
    log_info "whatweb 已安装"
else
    log_info "whatweb 已存在"
fi

# --- sqlmap ---
if ! command -v sqlmap &>/dev/null; then
    apt-get install -y sqlmap
    log_info "sqlmap 已安装"
else
    log_info "sqlmap 已存在"
fi

# --- hydra ---
if ! command -v hydra &>/dev/null; then
    apt-get install -y hydra
    log_info "hydra 已安装"
else
    log_info "hydra 已存在"
fi

# --- hashcat ---
if ! command -v hashcat &>/dev/null; then
    apt-get install -y hashcat
    log_info "hashcat 已安装"
else
    log_info "hashcat 已存在"
fi

# --- proxychains4 ---
if ! command -v proxychains4 &>/dev/null; then
    apt-get install -y proxychains4
    log_info "proxychains4 已安装"
else
    log_info "proxychains4 已存在"
fi

# --- weevely3 ---
if ! command -v weevely &>/dev/null; then
    apt-get install -y weevely 2>/dev/null || {
        # weevely 可能不在标准仓库, 尝试 pip 安装
        source "$VENV_DIR/bin/activate"
        pip install -q weevely3 2>/dev/null || true
        deactivate
    }
    log_info "weevely3 已安装"
else
    log_info "weevely3 已存在"
fi

log_info "apt 渗透工具安装完成"

# ============================================================================
# 渗透测试工具 (curl)
# ============================================================================
# --- metasploit-framework ---
if ! command -v msfconsole &>/dev/null; then
    log_info "安装 metasploit-framework (较大，需要一些时间)..."
    curl -sL "https://gh-proxy.org/https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb" > /tmp/msfinstall && \
    chmod 755 /tmp/msfinstall && \
    /tmp/msfinstall
    rm -f /tmp/msfinstall
    log_info "metasploit 已安装"
else
    log_info "metasploit 已存在"
fi

# ============================================================================
# 安装验证
# ============================================================================
echo ""
log_info "=========================================="
log_info " 安装验证"
log_info "=========================================="
echo ""

echo "--- 基础工具 ---"
echo -n "  curl:      " && (command -v curl &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  wget:      " && (command -v wget &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  git:       " && (command -v git &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  tmux:      " && (command -v tmux &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  jq:        " && (command -v jq &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  java:      " && (command -v java &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  pipx:      " && (command -v pipx &>/dev/null && echo "OK" || echo "MISSING")
echo ""

echo -n "  Chrome:          " && ([ -n "$CHROME_CMD" ] && echo "$CHROME_CMD" || echo "MISSING")
echo ""

echo "--- 渗透测试工具 (apt) ---"
echo -n "  nmap:          " && (nmap --version 2>/dev/null | head -1 || echo "MISSING")
echo -n "  whatweb:       " && (command -v whatweb &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  sqlmap:        " && (command -v sqlmap &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  hydra:         " && (command -v hydra &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  hashcat:       " && (command -v hashcat &>/dev/null && echo "OK" || echo "MISSING")
echo -n "  proxychains4:  " && (command -v proxychains4 &>/dev/null && echo "OK" || echo "MISSING")
echo ""

echo "--- 渗透测试工具 (curl) ---"
echo -n "  msfconsole:    " && (command -v msfconsole &>/dev/null && echo "OK" || echo "MISSING")

source "$VENV_DIR/bin/activate" 2>/dev/null && {
    echo "--- Python 依赖 ---"
    echo -n "  fastmcp:          " && python -c "import fastmcp; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  playwright:       " && python -c "from playwright.sync_api import sync_playwright; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  libtmux:          " && python -c "import libtmux; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  django:           " && python -c "import django; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  docker:           " && python -c "import docker; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  jupyter-client:   " && python -c "import jupyter_client; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  ipykernel:        " && python -c "import ipykernel; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  pydantic:         " && python -c "import pydantic; print('OK')" 2>/dev/null || echo "MISSING"
    echo -n "  requests:         " && python -c "import requests; print('OK')" 2>/dev/null || echo "MISSING"
    deactivate
}
echo ""


