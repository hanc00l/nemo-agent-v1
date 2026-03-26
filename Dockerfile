# 基础镜像
FROM ghcr.io/l3yx/sandbox:latest

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:${PATH}"

# 1. 更新系统
RUN echo "[1/5] 更新系统..." && \
    sudo apt update && sudo apt upgrade -y

# 2. 安装系统工具
RUN echo "[2/5] 安装系统工具..." && \
    sudo apt install -y whatweb

# 3. 安装 SecLists
RUN echo "[3/5] 安装 SecLists..." && \
    sudo git clone --depth 1 https://github.com/danielmiessler/SecLists.git /usr/share/seclists

# 4. 安装 Python 包
RUN echo "[4/5] 安装 Python 包..." && \
    pipx ensurepath && \
    pipx install --pip-args=--no-cache-dir \
        "fastmcp>=0.1.0" \
        "jupyter-client>=8.0.0" \
        "jupyter-core>=5.0.0" \
        "ipykernel>=6.25.0" \
        "nbformat>=5.9.0" \
        "docker>=7.0.0" \
        "playwright>=1.40.0" \
        "pydantic>=2.0.0" \
        "docstring-parser>=0.15" \
        "psutil>=5.9.0" \
        "libtmux>=0.12.0" \
        "python-dotenv>=1.0.0" \
        "requests>=2.28.0" \
        "pytest>=7.0.0" \
        "pytest-asyncio>=0.21.0" \
        2>/dev/null || true && \
    pipx reinstall-all 2>/dev/null || true

# 5. 创建目录
RUN echo "[5/5] 配置目录..." && \
    sudo mkdir -p /opt/notes /opt/scripts && \
    sudo chown ubuntu:ubuntu /opt/notes /opt/scripts

# 清除旧的文件
RUN echo "clean..." && \
    sudo rm -rf /opt/service && sudo rm -rf /opt/toolset

# 6. 更新 Claude
RUN command -v claude &> /dev/null && sudo claude update || true    

# 设置工作目录
WORKDIR /opt/nemo-agent

# 镜像标签
LABEL version="1.0"
LABEL description="Nemo Agent Sandbox with tools and Python packages"
