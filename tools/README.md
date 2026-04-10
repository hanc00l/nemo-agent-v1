# 安全工具集

此目录包含用于渗透测试的安全工具，支持多架构版本。

**⚠️ 重要**：所有工具必须下载到 `/opt/workspace` 目录下

## 目录结构

```
/opt/workspace/
├── fscan/                    # 内网综合扫描工具
│   ├── fscan_amd64           # Linux AMD64
│   ├── fscan_arm64           # Linux ARM64
│   ├── fscan_386             # Linux x86 (32位)
│   ├── fscan_windows_amd64.exe   # Windows AMD64
│   └── fscan_windows_386.exe     # Windows x86 (32位)
├── linpeas/                  # Linux 提权检查工具
│   ├── linpeas_linux_amd64
│   └── linpeas_linux_arm64
└── mimikatz/                 # Windows 凭证提取
    └── mimikatz_x64.exe
```

## 工具说明

### fscan

**用途**: 内网综合扫描工具

**功能**:
- 端口扫描
- 服务识别
- 漏洞检测
- 密码爆破 (SSH/SMB/MySQL/Redis 等)
- 信息收集

**下载地址**:
- GitHub: https://github.com/shadow1ng/fscan/releases
- 选择对应架构版本下载到 `/opt/workspace/fscan/` 目录

**使用示例**:
```bash
# 创建目录
mkdir -p /opt/workspace/fscan

# Linux AMD64
wget https://github.com/shadow1ng/fscan/releases/download/v1.8.4/fscan_amd64 -O /opt/workspace/fscan/fscan_amd64
chmod +x /opt/workspace/fscan/fscan_amd64

# Windows AMD64
wget https://github.com/shadow1ng/fscan/releases/download/v1.8.4/fscan_windows_amd64.exe -O /opt/workspace/fscan/fscan_windows_amd64.exe
```

### linpeas

**用途**: Linux 提权检查脚本

**功能**:
- 检查 SUID 文件
- 检查弱权限配置
- 检查敏感信息
- 检查内核漏洞

**下载地址**: https://github.com/carlospolop/PEASS-ng/releases

**下载到**: `/opt/workspace/linpeas/`

### mimikatz

**用途**: Windows 凭证提取

**功能**:
- 读取明文密码
- 导出哈希
- Pass-the-Hash 攻击
- 黄金票据生成

**下载地址**: https://github.com/gentilkiwi/mimikatz/releases

**下载到**: `/opt/workspace/mimikatz/`

## 添加新工具

### 1. 创建工具目录

```bash
mkdir -p /opt/workspace/toolname
```

### 2. 下载多架构版本

确保支持以下架构:
- Linux AMD64
- Linux ARM64
- Linux x86 (386)
- Windows AMD64
- Windows x86 (386)

### 3. 添加可执行权限

```bash
chmod +x /opt/workspace/toolname/*
```

### 4. 更新文档

在此 README 中添加工具说明。

## 使用方式

工具会被自动上传到靶机执行，详见：
- [工具上传技能文档](../claude-code/.claude/skills/pentest/internal/tools-upload/SKILL.md)

## 安全提示

⚠️ **这些工具仅用于授权的安全测试和 CTF 竞赛**

- 未经授权使用这些工具进行扫描是违法的
- 请确保在合法的测试环境中使用
- 遵守当地法律法规和竞赛规则
