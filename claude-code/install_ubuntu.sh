#!/bin/bash
#
# Ubuntu 24.04 LTS PenTester Agent 环境安装脚本
#
# 使用方法:
#   chmod +x install_ubuntu.sh && sudo ./install_ubuntu.sh
#
# 安装的组件:
#   - 系统工具: nmap, whatweb, ffuf, katana
#   - 字典: seclists
#   - Python 依赖: fastmcp, playwright, libtmux 等
#   - Web UI: Django, markdown, bleach
#

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[+]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[-]${NC} $1"; }

# 检查 sudo 权限
if ! sudo -v &> /dev/null; then
   log_error "此脚本需要 sudo 权限"
   exit 1
fi

SUDO="sudo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRDPARTY_DIR="$SCRIPT_DIR/thirdparty"

log_info "=== Ubuntu 24.04 LTS PenTester Agent 环境安装 ==="
log_info "安装组件: nmap, whatweb, ffuf, katana, seclists"
echo ""

# ============================================================================
# 1. 系统更新和基础工具
# ============================================================================
log_info "[1/5] 安装基础工具..."

$SUDO apt-get update -qq
$SUDO apt-get install -y \
    curl wget git vim tmux htop \
    net-tools iputils-ping netcat-openbsd \
    unzip jq sqlite3 \
    python3-venv python3-pip python3-full \
    build-essential libssl-dev libffi-dev python3-dev \
    libnss3-tools

# 安装 Chrome 浏览器
if ! command -v google-chrome &> /dev/null && ! command -v google-chrome-stable &> /dev/null; then
    log_info "安装 Google Chrome..."
    if wget -q "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" -O /tmp/google-chrome.deb; then
        $SUDO dpkg -i /tmp/google-chrome.deb 2>/dev/null || \
            ($SUDO apt-get install -y -f && $SUDO dpkg -i /tmp/google-chrome.deb)
        rm -f /tmp/google-chrome.deb
    else
        log_warn "Chrome 下载失败，安装 Chromium..."
        $SUDO apt-get install -y chromium-browser || true
    fi
else
    log_info "Chrome 已存在"
fi

# ============================================================================
# 2. 安装渗透测试工具
# ============================================================================
log_info "[2/5] 安装渗透测试工具..."

# nmap
if ! command -v nmap &> /dev/null; then
    $SUDO apt-get install -y nmap
    log_info "nmap 已安装"
else
    log_info "nmap 已存在"
fi

# whatweb
if ! command -v whatweb &> /dev/null; then
    $SUDO apt-get install -y whatweb
    log_info "whatweb 已安装"
else
    log_info "whatweb 已存在"
fi

# ffuf
if ! command -v ffuf &> /dev/null; then
    FFUF_OFFLINE=$(find "$THIRDPARTY_DIR" -name "ffuf_*_linux_amd64.tar.gz" -type f 2>/dev/null | head -1)
    if [ -n "$FFUF_OFFLINE" ]; then
        $SUDO tar -xzf "$FFUF_OFFLINE" -C /usr/local/bin ffuf 2>/dev/null || true
        log_info "ffuf 从离线包安装"
    else
        FFUF_VER=$(curl -s https://api.github.com/repos/ffuf/ffuf/releases/latest | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
        wget -q "https://github.com/ffuf/ffuf/releases/download/${FFUF_VER}/ffuf_${FFUF_VER#v}_linux_amd64.tar.gz" -O /tmp/ffuf.tar.gz
        $SUDO tar -xzf /tmp/ffuf.tar.gz -C /usr/local/bin ffuf
        rm -f /tmp/ffuf.tar.gz
        log_info "ffuf ${FFUF_VER} 已安装"
    fi
    $SUDO chmod +x /usr/local/bin/ffuf
else
    log_info "ffuf 已存在"
fi

# katana
if ! command -v katana &> /dev/null; then
    KATANA_OFFLINE=$(find "$THIRDPARTY_DIR" -name "katana_*_linux_amd64.zip" -type f 2>/dev/null | head -1)
    if [ -n "$KATANA_OFFLINE" ]; then
        $SUDO unzip -o "$KATANA_OFFLINE" -d /usr/local/bin katana 2>/dev/null || true
        log_info "katana 从离线包安装"
    else
        VER=$(curl -s https://api.github.com/repos/projectdiscovery/katana/releases/latest | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
        wget -q "https://github.com/projectdiscovery/katana/releases/download/${VER}/katana_${VER#v}_linux_amd64.zip" -O /tmp/katana.zip
        $SUDO unzip -o /tmp/katana.zip -d /usr/local/bin katana
        rm -f /tmp/katana.zip
        log_info "katana ${VER} 已安装"
    fi
    $SUDO chmod +x /usr/local/bin/katana
else
    log_info "katana 已存在"
fi

# seclists 字典
if [ ! -d "/usr/share/seclists" ]; then
    log_info "安装 seclists 字典..."
    $SUDO git clone --depth 1 https://github.com/danielmiessler/SecLists.git /usr/share/seclists
else
    log_info "seclists 已存在"
fi

# ============================================================================
# 3. Python 虚拟环境和依赖
# ============================================================================
log_info "[3/5] 安装 Python 依赖..."

VENV_DIR="$SCRIPT_DIR/.venv"
[ ! -d "$VENV_DIR" ] && python3 -m venv "$VENV_DIR"

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# 核心依赖 (MCP + 执行器 + 浏览器 + 终端)
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

# Web UI 依赖
pip install -q \
    django>=5.0 \
    markdown>=3.5 \
    bleach>=6.0

deactivate

# ============================================================================
# 4. 配置 IPykernel
# ============================================================================
log_info "[4/5] 配置 IPykernel..."

# 安装 ipykernel
source "$VENV_DIR/bin/activate"
python -m ipykernel install --user --name python3 2>/dev/null || true

# 配置 Playwright 使用系统 Chrome
CHROME_EXECUTABLE=""
for cmd in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v $cmd &> /dev/null; then
        CHROME_EXECUTABLE=$cmd
        break
    fi
done

if [ -n "$CHROME_EXECUTABLE" ]; then
    log_info "Playwright 将使用系统浏览器: $CHROME_EXECUTABLE"
else
    log_warn "未检测到 Chrome，请手动安装"
fi

deactivate

# ============================================================================
# 5. 清理
# ============================================================================
log_info "[5/5] 清理临时文件..."
rm -f /tmp/ffuf.tar.gz /tmp/katana.zip
rm -rf /tmp/ffuf_extract /tmp/katana_extract 2>/dev/null

# ============================================================================
# 完成
# ============================================================================
echo ""
log_info "=== 安装完成 ==="
echo ""
log_info "后续步骤："
echo "  1. 激活虚拟环境:"
echo "     source $SCRIPT_DIR/.venv/bin/activate"
echo ""
echo "  2. 配置环境变量:"
echo "     export ANTHROPIC_BASE_URL='你的 API 地址'"
echo "     export ANTHROPIC_AUTH_TOKEN='你的 API Token'"
echo "     export ANTHROPIC_MODEL='claude-sonnet-4-5-20250929'"
echo ""
echo "  3. 启动服务:"
echo "     cd $SCRIPT_DIR"
echo "     python3 meta-tooling/service/python_executor_mcp.py --port 8000 &"
echo ""

# 验证安装
log_info "已安装组件:"
echo "  渗透测试工具:"
echo -n "    nmap:       " && nmap --version 2>/dev/null | head -1 || echo "未安装"
echo -n "    ffuf:       " && ffuf -V 2>/dev/null | head -1 || echo "未安装"
echo -n "    katana:     " && katana -version 2>/dev/null | head -1 || echo "未安装"
echo -n "    seclists:   " && [ -d "/usr/share/seclists" ] && echo "/usr/share/seclists" || echo "未安装"
echo ""
echo "  数据目录:"
echo -n "    task/data:  " && [ -d "/opt/nemo-agent/task/data" ] && echo "已创建" || echo "未创建"

source "$VENV_DIR/bin/activate" 2>/dev/null && {
    echo ""
    echo "  Python 依赖:"
    echo -n "    FastMCP:    " && python -c "import fastmcp; print('已安装')" 2>/dev/null || echo "未安装"
    echo -n "    Playwright: " && python -c "from playwright.sync_api import sync_playwright; print('已安装')" 2>/dev/null || echo "未安装"
    echo -n "    libtmux:    " && python -c "import libtmux; print('已安装')" 2>/dev/null || echo "未安装"
    echo -n "    Django:     " && python -c "import django; print('已安装')" 2>/dev/null || echo "未安装"
    deactivate
}

echo ""
log_info "安装脚本执行完成!"
