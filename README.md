# Nemo Agent

[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](https://github.com/hanc00l/nemo-agent)

基于 Claude Code 的自动化渗透测试 Agent，达到中高级网络安全专家水平。

> 目前在开发调试中，文档可能不完善。

## 特性

- **多 LLM 并行**：支持 1-3 个 LLM 并行解题，提高成功率
- **双层调度**：平台实例管理 + 本地 Docker 容器，自动恢复中断任务
- **自动化调度**：从竞赛平台自动获取挑战，管理全生命周期
- **沙盒隔离**：每个挑战运行在独立 Docker 容器中
- **实时监控**：Web UI（SSE 推送）实时查看解题过程与结果
- **笔记系统**：自动记录信息收集、推理分析、最终结果
- **VNC 可视**：支持 VNC 查看浏览器操作过程
- **技能树**：30+ 技能目录，覆盖 Web/CVE/内网/云/AI 安全
- **漏洞知识库**：1123+ 漏洞本地知识库（vulnerability-wiki）+ 317 漏洞环境索引（vulhub）
- **赛区递进**：Zone 1（Web）→ Zone 2（+CVE/云）→ Zone 3（+内网）

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      CTF 平台 API                            │
│          (认证: Agent-Token, 频率: ≤3 req/s)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   task/scheduler.py                         │
│            挑战调度器 (双层管理)                               │
│                                                              │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │   平台实例管理         │  │   本地容器管理                 │ │
│  │ start/stop instance  │  │ Docker 容器生命周期            │ │
│  │ get_hint             │  │ 容器健康检查与自动恢复          │ │
│  │ submit_flag          │  │ 死容器重启                    │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
│                                                              │
│  状态持久化: subjects.json (线程安全, 文件锁)                  │
│  频率控制: PlatformClient._rate_limit (0.5s间隔)              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Docker 容器 (每挑战 N 个 LLM)                │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Claude Agent + MCP 服务                     ││
│  │  ┌─────────────────┐ ┌─────────────────────────────────┐││
│  │  │ Jupyter Kernel  │ │         toolset 工具库           │││
│  │  │  (代码沙盒执行)  │ │ terminal│browser│competition│note│││
│  │  └─────────────────┘ └─────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │  MCP 服务: sandbox (Jupyter 内核, FastMCP HTTP)      │││
│  │  └─────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │  安全工具: nmap│sqlmap│hydra│ffuf│katana│fscan│nuclei│││
│  │  │  Java: JNDIExploit│JYso│shiro_cli                   │││
│  │  │  内网: frp│chisel│stowaway│nxc│mimikatz│xray         │││
│  │  └─────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │  技能树: web│cve│internal│cloud│ai-security│vulhub   │││
│  │  │  知识库: vulnerability-wiki(1123+)│vulhub(317)       │││
│  │  └─────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 web-ui (Django, 端口 8003)                   │
│          实时仪表盘(SSE) │ 笔记 │ Jupyter │ 认证             │
│               (无数据库, JSON 文件驱动)                        │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| AI 框架 | Claude Code (MCP) | AI Agent 核心引擎 |
| 开发语言 | Python 3.10+ | 主要开发语言 |
| 执行环境 | Jupyter (ipykernel) | Python 代码沙盒执行 |
| MCP 服务 | FastMCP (HTTP) | Jupyter 内核管理 |
| 浏览器自动化 | Playwright | 网页交互、截图、动态分析 |
| Web UI | Django 5.0+ | 实时监控（SSE）、笔记/Notebook 查看器 |
| 容器化 | Docker | 沙盒隔离、并行任务 |
| 进程管理 | libtmux | Tmux 会话管理 |
| 远程桌面 | VNC (xfce4) | 可视化浏览器操作（可选） |

## 快速开始

### 1. 构建 Docker 镜像

```bash
docker build -t nemo-agent/sandbox:1.0 .
```

### 2. 配置环境变量

```bash
cd task
cp .env.example .env
# 编辑 .env，配置 LLM API 和竞赛平台
```

主要配置项：

```bash
# LLM API 配置 (1-3个，至少配置一个)
LLM-1-ANTHROPIC_BASE_URL=https://api.anthropic.com
LLM-1-ANTHROPIC_AUTH_TOKEN=your_token
LLM-1-ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# 竞赛平台
COMPETITION_API_URL=http://192.168.52.1:8888
AGENT_TOKEN=your_agent_token_here

# 调度参数
MAX_LLM=1              # 每题并行 LLM 数 (1-3)
MAX_PARALLEL=3         # 最大并行挑战数
TIMEOUT_SECONDS=3600   # 单题超时 (秒)
FETCH_INTERVAL=60      # 平台获取间隔 (秒)
```

### 3. 启动调度器

```bash
cd task
python3 scheduler.py
```

调度器会自动：
- 从竞赛平台获取挑战列表
- 启动平台赛题实例，获取入口地址
- 为每题创建 Docker 容器（含描述和提示）
- 监控超时、容器健康、平台实例状态
- 中断重启后自动恢复（重建平台实例 + 本地容器）
- 记录结果到 `data/subjects.json`

### 4. 查看 Web UI

```bash
cd web-ui
python3 manage.py runserver 0.0.0.0:8003
```

默认登录：用户名 `nemo`，密码 `nemo`（通过 `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` 环境变量配置）。

## 使用方式

### 调度器模式（推荐）

自动从竞赛平台获取挑战并解题：

```bash
cd task
python3 scheduler.py

# 单次运行（不循环）
python3 scheduler.py --once
```

### 单一解题模式

手动指定目标进行解题：

```bash
cd task
python3 solver.py --target http://target:port --challenge_code xxx --competition
```

参数说明：
- `--target`: 目标 URL 或 IP:端口
- `--challenge_code`: 题目代码，用于关联笔记
- `--competition`: 启用竞赛模式（自动提交答案）

### 手动启动 Agent

```bash
cd claude-code

# 1. 启动浏览器服务
python3 meta-tooling/service/browser.py --port 9222 &

# 2. 启动 MCP 服务
python3 meta-tooling/service/python_executor_mcp.py --port 8000 &

# 3. 启动 Agent
claude --print --dangerously-skip-permissions \
  "使用 pentest-agent 解决 http://目标:端口 的 CTF 挑战"
```

## 核心功能

### 双层调度管理

调度器管理两个层级：

| 层级 | 职责 | API |
|------|------|-----|
| 平台实例 | 赛题靶机启停、状态查询 | `start_instance` / `stop_instance` |
| 本地容器 | 解题 Agent 运行环境 | Docker 容器管理 |

**重启恢复机制**：调度器中断后重启，`_maintain_containers` 会：
1. 检查平台实例是否存活，已停止则尝试重启
2. 检查本地容器是否运行，丢失则重建
3. 并行计数基于持久化的 `subjects.json`，确保不超限

### challenge_code

题目的唯一标识符，关联 Jupyter 会话和笔记存储。来源：竞赛平台 / 用户指定 / URL 生成。

### Note 笔记系统

| 类型 | 文件 | 用途 |
|------|------|------|
| info | `{code}-info.md` | 信息收集 |
| infer | `{code}-infer.md` | 推理分析 |
| result | `{code}-result.md` | 最终结果 |

笔记存储路径：由 `NOTE_PATH` 环境变量配置（默认 `/opt/notes`）。

API:
- `get_notes_summary(code)` - 读取摘要
- `append_note(code, type, content)` - 追加笔记

### MCP 工具服务

容器内通过 FastMCP HTTP 服务（端口 8000）提供 Jupyter 内核执行能力：

| MCP 工具 | 功能 |
|----------|------|
| `execute_code(session_name, code, timeout)` | 在 Jupyter 内核中执行 Python |
| `list_sessions()` | 列出活跃会话 |
| `close_session(session_name)` | 关闭会话 |

会话自动加载 `toolset` 包：

| 工具 | 功能 |
|------|------|
| `toolset.browser` | Playwright 浏览器控制 |
| `toolset.terminal` | Tmux 终端会话管理 |
| `toolset.note` | 笔记读写 |
| `toolset.competition` | 竞赛平台 API |

### 平台 API 频率控制

- 内置频率限制：每次请求间隔 >= 0.5s（≤ 2 req/s）
- 429 自动重试：最多 3 次，支持 Retry-After 响应头
- 认证方式：Agent-Token 请求头

### 赛区策略

> 赛区策略为累积递进，所有赛区均可使用全部工具，赛区仅影响攻击思路和优先级。

| 赛区 | 技能目录 | 覆盖能力（递进包含） |
|------|----------|----------|
| **Zone 1** | web/ | Web 漏洞、Java 反序列化、OA 系统 |
| **Zone 2** | Zone 1 + cve/, vulhub/, vulnerability-wiki/, cloud/, ai-security/ | + CVE + 知识库 + 云 + AI |
| **Zone 3** | Zone 1+2 + internal/ | + 内网渗透、横向移动、多级代理 |

### 安全工具

#### 信息收集

| 工具 | 来源 | 用途 | 示例命令 |
|------|------|------|----------|
| nmap | apt | 端口扫描 | `nmap -sV -n -T4 --open target` |
| whatweb | apt | 技术栈识别 | `whatweb -a 3 http://target` |
| observer_ward | /opt/workspace | 应用指纹识别 | `observer_ward -t http://target` |
| katana | /opt/workspace | 网页爬取 | `katana -u http://target -d 3 -jc` |
| ffuf | /opt/workspace | 目录发现/模糊测试 | `ffuf -u 'http://target/FUZZ' -w wordlist` |
| fscan | /opt/workspace | 内网综合扫描 | `fscan -h 10.10.1.0/24` |

#### 漏洞利用

| 工具 | 来源 | 用途 | 示例命令 |
|------|------|------|----------|
| sqlmap | apt | SQL 注入 | `sqlmap -u "http://target/page?id=1" --dbs` |
| nuclei | /opt/workspace | 模板化漏洞扫描 | `nuclei -u http://target` |
| xray | /opt/workspace/xray | 被动代理扫描 | `xray webscan --listen 127.0.0.1:7777` |
| msfconsole | apt (omnibus) | 漏洞利用框架 | `msfconsole` |
| hydra | apt | 暴力破解 | `hydra -l user -P pass.txt target ssh` |
| hashcat | apt | 密码破解 | `hashcat -m 0 hash.txt wordlist` |
| proxychains4 | apt | 代理链 | `proxychains4 nmap target` |

#### Java 反序列化

| 工具 | 来源 | 用途 |
|------|------|------|
| JNDIExploit | /opt/workspace/JNDIExploit/ | JNDI 注入利用 |
| JYso | /opt/workspace/JYso/ | Java 反序列化 |
| shiro_cli | /opt/workspace/shiro/ | Shiro 反序列化 |

#### 内网渗透

| 工具 | 来源 | 用途 |
|------|------|------|
| frpc/frps | /opt/workspace/frp/ | 反向代理（首选） |
| chisel | /opt/workspace | HTTP 隧道代理 |
| Stowaway | /opt/workspace/Stowaway/ | 多级节点代理 |
| Neo-reGeorg | /opt/workspace/Neo-reGeorg/ | HTTP 隧道 |
| nxc (NetExec) | /opt/workspace/NetExec/ | 横向移动（SMB/SSH/WinRM） |
| mimikatz | /opt/workspace | Windows 凭证提取 |

#### Webshell / 其他

| 工具 | 来源 | 用途 |
|------|------|------|
| weevely | apt | PHP Webshell |
| wsh | /opt/workspace | Webshell 管理 |

字典位置：`/opt/workspace/SecLists/`

### 技能树

Agent 通过 `.claude/skills/pentest/` 下的 30+ 技能文件获得领域知识：

```
skills/pentest/
├── SKILL.md                    # 顶层技能（v7.0.0，强制流程 + 工具总览）
├── browser/SKILL.md            # Playwright 浏览器操作
├── terminal/SKILL.md           # Tmux 终端操作
├── note/SKILL.md               # 笔记存储
├── competition/SKILL.md        # 竞赛平台 API
├── reverse/                    # 反连/JNDI
│   ├── SKILL.md                # 反弹 Shell 管理
│   └── jndi-exploit.md         # JNDI 注入利用
├── core/
│   ├── reconnaissance/SKILL.md # 手动/主动侦察
│   ├── vulnerability-testing/  # 漏洞测试与利用
│   ├── ctf-workflow/           # 竞赛流程与超时规则
│   └── reporting/              # 解题报告
├── web/                        # Web 安全（Zone 1）
│   ├── SKILL.md                # 企业级 Web 漏洞
│   ├── xray.md                 # 被动代理扫描
│   ├── sqlmap.md               # SQL 注入
│   ├── waf-bypass.md           # WAF 绕过
│   ├── java-deserialization.md # Java 反序列化（JYso）
│   ├── shiro.md / fastjson.md / spring-boot.md  # 框架漏洞
│   ├── wsh.md                  # Webshell 管理
│   ├── tools/weevely3.md       # PHP Webshell
│   └── oa-systems/             # OA 系统专项
├── cve/                        # CVE 利用（Zone 2）
│   ├── SKILL.md                # CVE 利用方法论
│   ├── exploits/log4j.md       # 特定 CVE payload
│   └── tools/nuclei.md         # nuclei 三阶段扫描
├── vulnerability-wiki/         # 1123+ 漏洞知识库（本地文件读取）
├── vulhub/                     # 317 漏洞环境索引（本地 JSON 索引）
│   ├── categories/             # 16 个分类文件
│   ├── exploits/               # 漏洞复现模板
│   └── index/                  # 主索引 + 应用分类映射
├── cloud/                      # 云安全（metadata-service 等）
├── ai-security/                # AI 基础设施安全（prompt-injection 等）
├── business-logic/             # 业务逻辑漏洞
└── internal/                   # 内网渗透（Zone 3）
    ├── SKILL.md                # 内网渗透总览
    ├── info-gathering/         # 内网信息收集
    ├── post-exploitation/      # 后渗透操作
    ├── multi-hop-proxy/        # 多级代理
    ├── tools-upload/           # 工具上传
    ├── workflow/               # Zone 3 递归工作流
    ├── tools/                  # 11 个工具文档
    │   ├── frp.md, chisel.md, stowaway.md  # 代理工具
    │   ├── fscan.md, netexec.md            # 扫描/横向
    │   ├── mimikatz.md                     # 凭证提取
    │   ├── neo-regeorg.md                  # HTTP 隧道
    │   ├── reverse-shell.md                # 反弹 Shell
    │   └── file-transfer.md, proxybridge.md, simple-proxy.md
    └── references/             # 域名渗透, 提权
```

## 项目结构

```
nemo-agent/
├── CLAUDE.md                    # Agent 指令文档
├── README.md                    # 项目说明
├── Dockerfile                   # Docker 镜像构建
├── claude-code/                 # Agent 核心环境
│   ├── .claude/
│   │   ├── agents/
│   │   │   └── pentest-agent.md # 渗透测试 Agent 定义
│   │   ├── commands/
│   │   │   └── pentest.md       # /pentest 命令
│   │   └── skills/pentest/      # 技能树（30+ 目录）
│   ├── .mcp.json               # MCP 配置（sandbox 服务）
│   ├── meta-tooling/
│   │   ├── service/
│   │   │   ├── python_executor_mcp.py  # FastMCP Jupyter 内核服务
│   │   │   └── browser.py              # Playwright 浏览器服务
│   │   └── toolset/             # Python 工具库
│   │       └── src/toolset/
│   │           ├── browser/     # Playwright 封装
│   │           ├── competition/ # 竞赛平台 API
│   │           ├── note/        # 笔记读写
│   │           └── terminal.py  # Tmux 终端
│   ├── entrypoint.sh           # Docker 容器入口
│   ├── setup_symlinks.sh       # 工具软链接创建
│   ├── start_claude.sh         # Claude Code 启动脚本
│   ├── install_ubuntu.sh       # Ubuntu 环境安装
│   └── install_claude.sh       # Claude Code 安装（国内镜像）
├── task/                       # 任务调度系统
│   ├── scheduler.py            # 挑战调度器（双层管理）
│   ├── solver.py               # 单题求解器（多 LLM 并行）
│   ├── container_manager.py    # 容器生命周期管理
│   ├── challenge_state.py      # 状态管理（线程安全）
│   ├── config.py               # 配置管理
│   ├── core/
│   │   ├── platform.py         # 平台 API 客户端（频率控制）
│   │   ├── container.py        # 容器创建、卷挂载、提示词构建
│   │   ├── runner.py           # Docker 任务执行
│   │   ├── parallel.py         # 并行执行器
│   │   ├── state.py            # 状态枚举与超时工具
│   │   ├── llm.py              # LLM 配置加载
│   │   ├── logger.py           # 日志
│   │   └── signal.py           # 优雅关闭
│   └── data/                   # 运行时数据
│       ├── subjects.json       # 挑战状态持久化
│       └── scheduler.log       # 调度器日志
├── web-ui/                     # Web 可视化界面
│   ├── manage.py               # Django 入口
│   ├── start.sh                # 启动脚本
│   └── app/
│       ├── dashboard_views.py  # 仪表盘 + SSE 推送
│       ├── notes_views.py      # 笔记查看器
│       ├── jupyter_views.py    # Jupyter Notebook 查看器
│       ├── auth_views.py       # 用户认证
│       ├── middleware.py       # 认证中间件
│       ├── repositories.py     # 数据层（读 JSON/文件）
│       ├── settings.py         # Django 配置（无数据库）
│       └── templates/          # HTML 模板
└── tools/                      # 预编译工具二进制
    └── README.md               # 工具说明（fscan, linpeas, mimikatz）
```

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MAX_LLM` | 每题并行 LLM 数 (1-3) | 3 |
| `MAX_PARALLEL` | 最大并行挑战数 | 3 |
| `TIMEOUT_SECONDS` | 单挑战超时 (秒) | 3600 |
| `FETCH_INTERVAL` | 平台获取间隔 (秒) | 60 |
| `DOCKER_IMAGE` | Docker 镜像 | nemo-agent/sandbox:1.0 |
| `NOTE_PATH` | 笔记存储路径 | /opt/notes |
| `NOTEBOOK_PATH` | Jupyter Notebook 路径 | /opt/scripts |
| `WORKSPACE_PATH` | 工作目录路径 | /opt/workspace |
| `NO_VISION` | 禁用 VNC | false |
| `VNC_BASE_PORT` | VNC 基础端口 | 55900 |
| `AGENT_TOKEN` | 平台认证令牌 | - |
| `COMPETITION_API_URL` | 竞赛平台 URL | http://host.docker.internal |
| `WEB_UI_USERNAME` | Web UI 用户名 | nemo |
| `WEB_UI_PASSWORD` | Web UI 密码 | nemo |

### LLM 配置

支持 1-3 个 LLM，通过编号环境变量配置：

```bash
LLM-1-ANTHROPIC_BASE_URL=https://api.anthropic.com
LLM-1-ANTHROPIC_AUTH_TOKEN=sk-ant-xxx
LLM-1-ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# 可选：第 2、3 个 LLM
LLM-2-ANTHROPIC_BASE_URL=...
LLM-2-ANTHROPIC_AUTH_TOKEN=...
LLM-2-ANTHROPIC_MODEL=...
```

### 独立 Ubuntu 运行环境（可选，主要用于调试）

在前期调试和开发阶段，使用单一的 Ubuntu 虚拟机更方便。可用 `claude-code/install_ubuntu.sh` 快速完成安装：

```bash
cd claude-code
sudo ./install_ubuntu.sh
```

安装内容：
- 基础工具：curl, wget, git, tmux, jq, openjdk-8-jdk, pipx 等
- Chrome/Chromium 浏览器
- 渗透测试工具（apt）：nmap, whatweb, sqlmap, hydra, hashcat, proxychains4, weevely
- Metasploit Framework
- Docker CE（阿里云镜像源 + Docker Hub 国内加速）+ Docker Compose
- Python 依赖：fastmcp, playwright, libtmux, docker, django 等
- sudo 免密码配置

### 靶场参考

- [xbow](https://github.com/hanc00l/tencent-cloud-hackathon-intelligent-pentest-competition-api-server)：fork 自 Neuro-Sploit/xbow-validation-benchmarks 并作了一些修改。
- [vulhub](https://github.com/vulhub/vulhub)：测试 CVE 漏洞

## 注意事项

- 仅用于授权的安全测试和 CTF 竞赛
- 所有代码在 Docker 容器中隔离执行
- 平台 API 频率限制为 ≤3 req/s，调度器内置 0.5s 间隔保护
- 解题记录和笔记使用中文
- Web UI 无数据库，数据存储在 JSON 文件和文件系统中

## 参考资源

- [TinyCTFer](https://wiki.chainreactors.red/blog/2025/12/01/intent_is_all_you_need/)
- [Meta-Tooling](https://wiki.chainreactors.red/blog/2025/12/02/intent_engineering_01/)
- [wooyun-legacy、xianzhi-research](https://github.com/tanweai)
