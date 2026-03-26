#!/bin/bash
# Ubuntu 环境设置脚本 (无需 sudo 运行，内部自动调用 sudo)

echo "=== Ubuntu 环境设置 ==="

# 1. 更新系统
echo "[1/5] 更新系统..."
sudo apt update && sudo upgrade -y

# 2. 安装缺失的工具
echo "[2/5] 安装系统工具..."
sudo apt install -y whatweb

# 3. 安装 SecLists
echo "[3/5] 安装 SecLists..."
[ -d "/usr/share/seclists" ] || sudo git clone --depth 1 https://github.com/danielmiessler/SecLists.git /usr/share/seclists

# 4. 安装 Python 包
echo "[4/5] 安装 Python 包..."
pipx ensurepath

REQUIREMENTS_FILE=$(mktemp)
cat > "$REQUIREMENTS_FILE" << 'EOF'
fastmcp>=0.1.0
jupyter-client>=8.0.0
jupyter-core>=5.0.0
ipykernel>=6.25.0
nbformat>=5.9.0
docker>=7.0.0
playwright>=1.40.0
pydantic>=2.0.0
docstring-parser>=0.15
psutil>=5.9.0
libtmux>=0.12.0
python-dotenv>=1.0.0
requests>=2.28.0
pytest>=7.0.0
pytest-asyncio>=0.21.0
EOF

while IFS= read -r package; do
    if [ -n "$package" ] && [[ ! "$package" =~ ^# ]]; then
        # 检查是否已安装
        pkg_name=$(echo "$package" | cut -d'>' -f1 | cut -d'=' -f1)
        pipx list | grep -q "$pkg_name" || pipx install "$package" 2>/dev/null || true
    fi
done < "$REQUIREMENTS_FILE"

rm -f "$REQUIREMENTS_FILE"

# 修复 pipx symlinks
echo "修复 symlinks..."
pipx reinstall-all 2>/dev/null || true

# 5. 创建目录
echo "[5/5] 配置目录..."
sudo mkdir -p /opt/notes /opt/scripts
sudo chown ubuntu:ubuntu /opt/notes /opt/scripts

# 清除旧的文件
echo "clean..." && 
sudo rm -rf /opt/service && sudo rm -rf /opt/toolset

# 6. 更新 Claude
command -v claude &> /dev/null && sudo claude update || true

echo "=== 完成 ==="
