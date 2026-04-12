#!/bin/bash
# 为 /opt/workspace 下的安全工具创建 symlink → /usr/local/bin/
# 用法: bash setup_symlinks.sh

set -e

TARGET_DIR="/usr/local/bin"
WORKSPACE="/opt/workspace"

echo "[*] 开始创建工具 symlink ..."

# === 信息收集工具 ===

ln -sf "$WORKSPACE/observer_ward/observer_ward" "$TARGET_DIR/observer_ward"

# observer_ward 指纹库软链接
OW_CONFIG="/home/ubuntu/.config/observer_ward"
mkdir -p "$OW_CONFIG"
for _fp in service_fingerprint_v4.json web_fingerprint_v4.json; do
    if [ -f "$WORKSPACE/observer_ward/$_fp" ]; then
        ln -sf "$WORKSPACE/observer_ward/$_fp" "$OW_CONFIG/$_fp"
    fi
done
ln -sf "$WORKSPACE/katana/katana"               "$TARGET_DIR/katana"
ln -sf "$WORKSPACE/ffuf/ffuf"                    "$TARGET_DIR/ffuf"
ln -sf "$WORKSPACE/fscan/fscan"                  "$TARGET_DIR/fscan"

# nuclei 是直接二进制，不在子目录
ln -sf "$WORKSPACE/nuclei"                       "$TARGET_DIR/nuclei"

# xray (被动代理漏洞扫描)
ln -sf "$WORKSPACE/xray/xray"                       "$TARGET_DIR/xray"

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

# NetExec (nxc)
ln -sf "$WORKSPACE/NetExec/nxc"                    "$TARGET_DIR/nxc"

# === 云安全工具 ===

# lc (多云攻击面资产梳理)
if [ -f "$WORKSPACE/lc/lc" ]; then
    ln -sf "$WORKSPACE/lc/lc" "$TARGET_DIR/lc"
fi

# cf (云函数利用)
if [ -f "$WORKSPACE/cf/cf" ]; then
    ln -sf "$WORKSPACE/cf/cf" "$TARGET_DIR/cf"
fi

# CloudSword (云安全综合测试)
if [ -f "$WORKSPACE/cloudsword/cloudsword" ]; then
    ln -sf "$WORKSPACE/cloudsword/cloudsword" "$TARGET_DIR/cloudsword"
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
exec java -jar /opt/workspace/JNDIExploit/JNDIExploit.jar "$@"
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

# ysoserial
cat > "$TARGET_DIR/ysoserial" << 'EOF'
#!/bin/bash
exec java -jar /opt/workspace/ysoserial/ysoserial-all.jar "$@"
EOF
chmod +x "$TARGET_DIR/ysoserial"

# marshalsec
cat > "$TARGET_DIR/marshalsec" << 'EOF'
#!/bin/bash
exec java -cp /opt/workspace/marshalsec/marshalsec-all.jar "$@"
EOF
chmod +x "$TARGET_DIR/marshalsec"

# docker
ln -sf "$WORKSPACE/docker/docker" "$TARGET_DIR/docker"

# kubectl
ln -sf "$WORKSPACE/kubectl/kubectl" "$TARGET_DIR/kubectl"

# === Neo-reGeorg (Python 工具，创建 alias) ===
if [ -f "$WORKSPACE/Neo-reGeorg/neoreg.py" ]; then
    cat > "$TARGET_DIR/neoreg" << 'EOF'
#!/bin/bash
exec python3 /opt/workspace/Neo-reGeorg/neoreg.py "$@"
EOF
    chmod +x "$TARGET_DIR/neoreg"
fi

# === 字典软链接（大小写兼容） ===
if [ -d "$WORKSPACE/SecLists" ] && [ ! -L "$WORKSPACE/seclists" ]; then
    ln -sf "$WORKSPACE/SecLists" "$WORKSPACE/seclists"
fi

# === 验证 ===

echo ""
echo "[+] Symlink 创建完成，验证结果："
echo ""

TOOLS="observer_ward katana ffuf fscan nuclei xray frpc frps stowaway_admin stowaway_agent chisel wsh nxc lc cf cloudsword JNDIExploit JYso shiro_cli ysoserial marshalsec docker kubectl neoreg"

for tool in $TOOLS; do
    if command -v "$tool" &>/dev/null; then
        echo "  ✓ $tool → $(command -v "$tool")"
    else
        echo "  ✗ $tool → 未找到"
    fi
done

echo ""
echo "[*] 完成"
