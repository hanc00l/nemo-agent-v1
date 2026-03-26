# Nemo Agent

基于 Claude Code 的自动化渗透测试 Agent，达到中高级网络安全专家水平。

>目前在开发调试中，文档可能不完善。

## 特性

- **多 LLM 并行**：支持 1-3 个 LLM 并行解题，提高成功率
- **自动化调度**：从竞赛平台自动获取挑战，管理容器生命周期
- **沙盒隔离**：每个挑战运行在独立 Docker 容器中
- **实时监控**：Web UI 实时查看解题过程与结果
- **笔记系统**：自动记录信息收集、推理分析、最终结果
- **VNC 可视**：支持 VNC 查看浏览器操作过程

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      CTF 平台 API                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   task/scheduler.py                         │
│               挑战调度器 (并行=3, 超时=2400s)                  │
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
│  │  │    安全工具: nmap │ ffuf │ katana │ whatweb          │││
│  │  └─────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 web-ui (Django, 端口 8003)                   │
│                  实时查看解题过程与结果                        │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| AI 框架 | Claude Agent (MCP) | AI Agent 核心引擎 |
| 开发语言 | Python 3.10+ | 主要开发语言 |
| 执行环境 | Jupyter (ipykernel) | Python 代码沙盒执行 |
| 浏览器自动化 | Playwright | 网页交互、截图、动态分析 |
| Web UI | Django 5.0+ | 实时监控解题过程 |
| 容器化 | Docker | 沙盒隔离、并行任务 |
| 进程管理 | libtmux | Tmux 会话管理 |

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
# LLM API 配置 (至少配置一个)
LLM-1-ANTHROPIC_AUTH_TOKEN=your_token
LLM-1-ANTHROPIC_MODEL=claude-sonnet-4-6

# 竞赛平台
COMPETITION_API_URL=http://192.168.52.1:8888

# LLM 数量 (1-3)
MAX_LLM=1
```

### 3. 启动调度器

```bash
cd task
python3 scheduler.py
```

调度器会自动：
- 从竞赛平台获取挑战
- 为每题创建 Docker 容器
- 监控超时和容器健康
- 记录结果到 `data/subjects.json`

### 4. 查看 Web UI

```bash
cd web-ui
python3 manage.py runserver 0.0.0.0:8003
```

## 使用方式

### 调度器模式（推荐）

自动从竞赛平台获取挑战并解题：

```bash
cd task
python3 scheduler.py
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
  "使用 ctf-web-agent 解决 http://目标:端口 的 CTF 挑战"
```

## 核心功能

### challenge_code

题目的唯一标识符，关联 Jupyter 会话和笔记存储。

### Note 笔记系统

| 类型 | 文件 | 用途 |
|------|------|------|
| info | `{code}-info.md` | 信息收集 |
| infer | `{code}-infer.md` | 推理分析 |
| result | `{code}-result.md` | 最终结果 |

### 安全工具

| 工具 | 用途 | 示例命令 |
|------|------|----------|
| nmap | 端口扫描 | `nmap -sV -n -T4 --open target` |
| ffuf | 模糊测试 | `ffuf -u 'http://target/FUZZ' -w wordlist` |
| katana | 网页爬取 | `katana -u http://target -d 3 -jc` |
| whatweb | 技术栈识别 | `whatweb -a 3 http://target` |

字典位置：`/usr/share/seclists/Discovery/Web-Content/`

## 项目结构

```
nemo-agent/
├── CLAUDE.md                    # Agent 指令文档
├── README.md                    # 项目说明
├── Dockerfile                   # Docker 镜像构建
├── claude-code/                 # 核心代码目录
│   ├── .mcp.json               # MCP 配置
│   ├── meta-tooling/           # 元工具集
│   │   ├── service/            # MCP 服务
│   │   └── toolset/            # 工具库
│   └── tests/                  # 测试代码
├── task/                       # 任务调度系统
│   ├── scheduler.py            # 挑战调度器
│   ├── solver.py               # 求解器
│   ├── core/                   # 核心模块
│   ├── config.py               # 配置管理
│   └── data/                   # 数据目录
└── web-ui/                     # Web 可视化界面
    └── app/                    # Django 应用
```

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MAX_LLM` | LLM 数量 (1-3) | 1 |
| `MAX_PARALLEL` | 最大并行挑战数 | 3 |
| `TIMEOUT_SECONDS` | 单挑战超时 (秒) | 2400 |
| `FETCH_INTERVAL` | 平台获取间隔 (秒) | 60 |
| `DOCKER_IMAGE` | Docker 镜像 | nemo-agent/sandbox:1.0 |
| `NO_VISION` | 禁用 VNC | true |


### 独立Ubuntu运行环境（可选，主要用于调试用）

在前期调试和开发阶段，使用单一的ubuntu虚拟机更方便一些。可用claude-code/install_ubuntu.sh快速完成依赖组件和环境的安装。

## 注意事项

- 仅用于授权的安全测试和 CTF 竞赛
- 所有代码在 Docker 容器中隔离执行
- 解题记录和笔记使用中文

## 参考资源

- [TinyCTFer](https://wiki.chainreactors.red/blog/2025/12/01/intent_is_all_you_need/)
- [Meta-Tooling](https://wiki.chainreactors.red/blog/2025/12/02/intent_engineering_01/)
