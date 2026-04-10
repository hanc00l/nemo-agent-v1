# CLAUDE.md

## 项目概述

基于 Claude Code 的自动化渗透测试 Agent，达到中高级网络安全专家水平。

**设计哲学**: "Intent → Code → Execute → Record → Result"

## 标准作业流程

```
0. 读取笔记 → note.get_notes_summary(challenge_code)
1. 手动侦察 → 浏览器访问、源码分析
2. 主动侦察 → nmap、katana、observer_ward、whatweb、fscan
3. 查询知识库（任何工具识别到应用时）
   ├─ 识别到应用指纹？
   │  ├─ observer_ward → "信呼OA"、"泛微OA"
   │  ├─ whatweb → "Apache Struts"
   │  ├─ fscan title → "Tomcat"、"Nginx"
   │  ├─ nuclei → CVE 编号
   │  ├─ 手动发现 → 页面特征、响应头
   │  └─ 任何来源？
   │     ├─ 是 → 查询 vulnerability-wiki
   │  │  ├─ 找到？ → 获取详情 → 继续测试
   │  │  └─ 未找到 → 立即跳过
   │     └─ 否 → 跳过此步骤
4. 漏洞测试 → XSS/SQLi/IDOR/SSTI/命令注入
5. 漏洞利用 → 获取 FLAG
6. 立即提交 → competition.submit_answer()
7. 保存结果 → note.append_note("result", flag)
```

## 核心概念

### challenge_code

题目的唯一标识符，关联 Jupyter 会话和笔记存储。来源：竞赛平台 / 用户指定 / URL 生成

### Note 笔记系统

| 类型 | 文件 | 用途 |
|------|------|------|
| info | `{code}-info.md` | 信息收集 |
| infer | `{code}-infer.md` | 推理分析 |
| result | `{code}-result.md` | 最终结果 |

API:
- `get_notes_summary(code)` - 读取摘要
- `append_note(code, type, content)` - 追加笔记

笔记存储路径由 `NOTE_PATH` 环境变量配置，容器内默认 `/opt/notes`。

### Competition 平台 API

| 函数 | 用途 |
|------|------|
| `get_challenges()` | 获取所有挑战 |
| `get_target_url(code)` | 获取目标 URL |
| `get_hint(code)` | 获取提示（扣分） |
| `submit_answer(code, flag)` | 提交 FLAG |

**频率控制**: 平台限制 ≤3 req/s。`PlatformClient._rate_limit` 内置 0.5s 间隔保护，429 响应自动重试（最多 3 次）。

### Browser 浏览器工具

Playwright 自动化：页面访问、交互、截图、JS 执行

- `goto(url)` / `screenshot(path)` / `evaluate(js)`
- `click(sel)` / `fill(sel, text)`

### Terminal 终端工具

基于 tmux 的命令执行：长时间运行、实时输出、超时控制

- `run_command(cmd, timeout)` / `get_output()` / `is_running()`


## 安全工具

### apt 安装工具

| 工具 | 用途 | 命令 |
|------|------|------|
| nmap | 端口扫描 | `nmap -sV -n -T4 --open target` |
| whatweb | 技术栈识别 | `whatweb -a 3 http://target` |
| hydra | 暴力破解 | `hydra -l user -P pass.txt target ssh` |
| hashcat | 密码破解 | `hashcat -m 0 hash.txt wordlist` |
| proxychains4 | 代理链 | `proxychains4 nmap target` |
| weevely | PHP Webshell | `weevely generate <pass> <path>` |

### 其他安装工具

| 工具 | 来源 | 用途 | 命令 |
|------|------|------|------|
| sqlmap | /opt/workspace/sqlmap | SQL 注入 | `python3 /opt/workspace/sqlmap/sqlmap.py -u "http://target/page?id=1" --batch` |
| xray | /opt/workspace/xray | 被动代理漏洞扫描 | `/opt/workspace/xray/xray webscan --listen 127.0.0.1:7777 --json-output xray.json` |
| ffuf | /opt/workspace | 模糊测试 | `ffuf -u 'http://target/FUZZ' -w wordlist` |
| katana | /opt/workspace | 网页爬取 | `katana -u http://target -d 3 -jc` |
| observer_ward | /opt/workspace | 技术栈识别 | `observer_ward -t http://target` |
| nuclei | /opt/workspace | 漏洞扫描 | `nuclei -u http://target` |
| msfconsole | omnibus 安装 | 漏洞利用 | `msfconsole` |

**字典**: `/opt/workspace/SecLists/Discovery/Web-Content/`

### 外部知识库

| 工具 | 来源 | 用途 | 命令 |
|------|------|------|------|
| vulnerability-wiki | skill/pentest/vulnerability-wiki | 漏洞知识库（1123+漏洞） | Python API |
| vulhub | skill/pentest/vulhub | 漏洞复现环境 | Docker 启动 |

**vulnerability-wiki**:
- 位置: `~/.claude/skills/pentest/vulnerability-wiki/`
- 功能: 基于 Awesome-POC 的漏洞知识库，支持应用名称和 CVE 搜索
- 使用场景: observer_ward 识别出应用后，查询相关漏洞

```python
from vuln_wiki_web import VulnerabilityWikiWebSearch

searcher = VulnerabilityWikiWebSearch(base_url="http://127.0.0.1:3001")

# 按应用搜索（指纹识别后）
results = searcher.search_by_app("信呼OA", fuzzy=True)

# 按 CVE 搜索
results = searcher.search_by_cve("CVE-2022-22963")

# 获取详细内容
detail = searcher.get_vulnerability_detail(results[0]['path'])
```

**启动服务**:
```bash
cd /path/to/Vulnerability-Wiki-master
docker-compose -f docker-compose-simple.yml up -d
# 访问 http://127.0.0.1:3001
```

## 调度系统

### 双层管理

调度器（`task/scheduler.py`）管理两个层级：

1. **平台实例**：通过竞赛平台 API 启停赛题靶机（`start_instance` / `stop_instance`）
2. **本地容器**：Docker 容器运行解题 Agent，含题目描述和提示信息

### 主循环流程

```
每个周期（FETCH_INTERVAL=60s）:
  1. 获取平台挑战列表 → sync_with_platform
  2. 同步本地状态 → 新增/移除/已解决/恢复
  3. 检查已解决挑战 → 容器状态
  4. 检查超时 → _transition_to_fail
  5. 维护容器 → 检查平台实例 + 本地容器健康
  6. 清理已完成容器 → stop_challenge_full
  7. 启动新挑战 → _transition_to_started
```

### 中断恢复

调度器重启后从 `subjects.json` 恢复状态：
- `started` 状态的题目：检查平台实例存活 → 必要时重启 → 重建本地容器
- 并行计数基于 JSON 中 `started` 记录数，确保不超 `MAX_PARALLEL`
- `open` 状态的题目：继续排队等待启动

### 状态管理

`ChallengeStateManager` 提供线程安全的 JSON 状态管理：
- 文件锁（fcntl）+ 内存锁（threading.Lock）
- 原子读写操作
- 状态文件：`task/data/subjects.json`

## 重要规则

| 规则 | 说明 |
|------|------|
| 开始前读笔记 | 了解之前的发现和推理 |
| 30分钟重读 | 重新整理思路，避免死循环 |
| 立即提交 FLAG | 获取后立即提交，防止超时丢失 |
| 发现即记录 | 重要信息立即保存到笔记 |
| 授权使用 | 仅用于授权测试和 CTF 竞赛 |
| 使用中文 | 记录和输出使用中文 |

## 运行方式

### Ubuntu 独立环境安装

```bash
cd claude-code
sudo ./install_ubuntu.sh
```

安装内容：基础工具、Chrome、渗透测试工具(apt)、Metasploit、Docker(阿里云镜像源)、Python 依赖、sudo 免密码。

### 调度器模式（推荐）

```bash
cd task
python3 scheduler.py
```

### 单一解题模式

```bash
cd task
python3 solver.py --target TARGET --challenge_code CODE --competition
```

参数：
- `--target`: 目标 URL 或 IP:端口
- `--challenge_code`: 题目代码
- `--competition`: 启用竞赛模式（自动提交）

### Web UI

```bash
cd web-ui
python3 manage.py runserver 0.0.0.0:8003
```

## 参考资源

- TinyCTFer: https://wiki.chainreactors.red/blog/2025/12/01/intent_is_all_you_need/
- Meta-Tooling: https://wiki.chainreactors.red/blog/2025/12/02/intent_engineering_01/
