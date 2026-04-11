# 基础镜像
FROM ghcr.io/l3yx/sandbox:latest

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:${PATH}"

# 1. 更新系统
RUN echo "[1/5] 更新系统..." && \
    sudo apt update && sudo apt upgrade -y

# 2. 安装渗透测试工具 (apt)
RUN echo "[2/5] 安装渗透测试工具 (apt)..." && \
    sudo apt install -y \
        nmap \
        whatweb \
        sqlmap \
        hydra \
        hashcat \
        proxychains4 \
        weevely

# 3. 安装 Metasploit Framework (omnibus)
RUN echo "[3/5] 安装 Metasploit Framework (omnibus)..." && \
    curl -sL "https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb" > /tmp/msfinstall && \
    chmod 755 /tmp/msfinstall && \
    /tmp/msfinstall && \
    rm -f /tmp/msfinstall

# 4. 安装 Python 包（docker基础镜像已有不需要重复安装）
# RUN echo "[4/5] 安装 Python 包..." && \
#     pipx ensurepath && \
#     pipx install --pip-args=--no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
#         "fastmcp>=0.1.0" \
#         "jupyter-client>=8.0.0" \
#         "jupyter-core>=5.0.0" \
#         "ipykernel>=6.25.0" \
#         "nbformat>=5.9.0" \
#         "docker>=7.0.0" \
#         "playwright>=1.40.0" \
#         "pydantic>=2.0.0" \
#         "docstring-parser>=0.15" \
#         "psutil>=5.9.0" \
#         "libtmux>=0.12.0" \
#         "python-dotenv>=1.0.0" \
#         "requests>=2.28.0" \
#         "paramiko>=3.0.0" \
#         "pyjwt>=2.0.0" \
#         "pytest>=7.0.0" \
#         "pytest-asyncio>=0.21.0" || true && \
#     pipx reinstall-all 2>/dev/null || true

# 5. 创建目录
RUN echo "[5/5] 配置目录..." && \
    sudo mkdir -p /opt/notes /opt/scripts /opt/workspace && \
    sudo chown ubuntu:ubuntu /opt/notes /opt/scripts /opt/workspace

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
