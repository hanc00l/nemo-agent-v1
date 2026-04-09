#!/bin/bash
# 为 /opt/workspace 下的安全工具创建 symlink → /usr/local/bin/
# 用法: bash setup_symlinks.sh

set -e

TARGET_DIR="/usr/local/bin"
WORKSPACE="/opt/workspace"

echo "[*] 开始创建工具 symlink ..."

# === 信息收集工具 ===

ln -sf "$WORKSPACE/observer_ward/observer_ward" "$TARGET_DIR/observer_ward"
ln -sf "$WORKSPACE/katana/katana"               "$TARGET_DIR/katana"
ln -sf "$WORKSPACE/ffuf/ffuf"                    "$TARGET_DIR/ffuf"
ln -sf "$WORKSPACE/fscan/fscan"                  "$TARGET_DIR/fscan"

# nuclei 是直接二进制，不在子目录
ln -sf "$WORKSPACE/nuclei"                       "$TARGET_DIR/nuclei"

# === 代理/隧道工具 ===

# frp
ln -sf "$WORKSPACE/frp/frp_0.68.0_linux_amd64/frpc" "$TARGET_DIR/frpc"
ln -sf "$WORKSPACE/frp/frp_0.68.0_linux_amd64/frps" "$TARGET_DIR/frps"

# Stowaway (admin + agent 两个二进制)
ln -sf "$WORKSPACE/Stowaway/linux_x64_admin"     "$TARGET_DIR/stowaway_admin"
ln -sf "$WORKSPACE/Stowaway/linux_x64_agent"     "$TARGET_DIR/stowaway_agent"

# chisel (如果存在)
if [ -f "$WORKSPACE/chisel" ]; then
    ln -sf "$WORKSPACE/chisel" "$TARGET_DIR/chisel"
elif [ -d "$WORKSPACE/chisel" ] && [ -f "$WORKSPACE/chisel/chisel" ]; then
    ln -sf "$WORKSPACE/chisel/chisel" "$TARGET_DIR/chisel"
fi

# === 漏洞利用工具 ===

# wsh (直接二进制)
ln -sf "$WORKSPACE/wsh_linux"                    "$TARGET_DIR/wsh"

# rem
ln -sf "$WORKSPACE/rem/rem"                      "$TARGET_DIR/rem"

# === Java 反序列化工具 (jar 包，创建 alias 脚本) ===

# JNDIExploit
cat > "$TARGET_DIR/JNDIExploit" << 'EOF'
#!/bin/bash
exec java -jar /opt/workspace/JNDIExploit/JNDIExploit-1.2-SNAPSHOT.jar "$@"
EOF
chmod +x "$TARGET_DIR/JNDIExploit"

# JYso
cat > "$TARGET_DIR/JYso" << 'EOF'
#!/bin/bash
exec java -jar /opt/workspace/JYso/JYso.jar "$@"
EOF
chmod +x "$TARGET_DIR/JYso"

# shiro_cli
cat > "$TARGET_DIR/shiro_cli" << 'EOF'
#!/bin/bash
exec java -jar /opt/workspace/shiro/shiro_cli.jar -k /opt/workspace/shiro/shiro_keys.txt "$@"
EOF
chmod +x "$TARGET_DIR/shiro_cli"

# === Neo-reGeorg (Python 工具，创建 alias) ===
if [ -f "$WORKSPACE/Neo-reGeorg/neoreg.py" ]; then
    cat > "$TARGET_DIR/neoreg" << 'EOF'
#!/bin/bash
exec python3 /opt/workspace/Neo-reGeorg/neoreg.py "$@"
EOF
    chmod +x "$TARGET_DIR/neoreg"
fi

# === 验证 ===

echo ""
echo "[+] Symlink 创建完成，验证结果："
echo ""

TOOLS="observer_ward katana ffuf fscan TideFinger nuclei frpc frps stowaway_admin stowaway_agent wsh rem JNDIExploit JYso shiro_cli"

for tool in $TOOLS; do
    if command -v "$tool" &>/dev/null; then
        echo "  ✓ $tool → $(command -v "$tool")"
    else
        echo "  ✗ $tool → 未找到"
    fi
done

echo ""
echo "[*] 完成"
