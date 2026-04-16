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
   │     │  ├─ 找到？ → 获取详情 → 继续测试
   │     │  └─ 未找到 → nuclei 扫描 → WebSearch 兜底
   │     └─ 否 → 跳过此步骤
4. 漏洞测试 → XSS/SQLi/IDOR/SSTI/命令注入/SSRF
5. 漏洞利用 → 获取 FLAG
   ├─ SSRF 确认？ → cloud/ssrf-to-cloud + metadata-service → 云凭证
   ├─ 云指标命中？ → cloud/ 技能（容器/存储桶/AK利用）
   ├─ AI 指标命中？ → ai-security/ 技能（提示注入/LLM API）
   └─ 常规 Web 利用
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
| `submit_answer(code, answer)` | 提交 FLAG（参数名是 answer 不是 flag） |

**频率控制**: 平台限制 ≤3 req/s。`PlatformClient._rate_limit` 内置 0.5s 间隔保护，429 响应自动重试（最多 3 次）。

### Browser 浏览器工具

Playwright 自动化：页面访问、交互、截图、JS 执行

```python
page = await toolset.browser.get_page()
await page.goto("http://target")
content = await page.content()
```

### Terminal 终端工具

基于 tmux 的命令执行：长时间运行、实时输出、超时控制

```python
sid = toolset.terminal.new_session()
toolset.terminal.send_keys(sid, "nmap -sV target", enter=True)
time.sleep(30)
output = toolset.terminal.get_output(sid)
```

## 安全工具

### 信息收集

| 工具 | 来源 | 用途 | 命令 |
|------|------|------|------|
| nmap | apt | 端口扫描 | `nmap -sV -n -T4 --open target` |
| whatweb | apt | 技术栈识别 | `whatweb -a 3 http://target` |
| observer_ward | /opt/workspace | 应用指纹识别 | `observer_ward -t http://target` |
| katana | /opt/workspace | 网页爬取 | `katana -u http://target -d 3 -jc` |
| ffuf | /opt/workspace | 目录发现/模糊测试 | `ffuf -u 'http://target/FUZZ' -w wordlist` |
| fscan | /opt/workspace | 内网综合扫描 | `fscan -h 10.10.1.0/24` |
| lc | /opt/workspace/lc | 多云攻击面资产梳理 | `lc -ep -s` |

### 漏洞利用

| 工具 | 来源 | 用途 | 命令 |
|------|------|------|------|
| sqlmap | apt | SQL 注入 | `sqlmap -u "http://target/page?id=1" --batch` |
| nuclei | /opt/workspace | 模板化漏洞扫描 | `nuclei -u http://target` |
| xray | /opt/workspace/xray | 被动代理漏洞扫描 | `xray webscan --listen 127.0.0.1:7777 --json-output xray.json` |
| msfconsole | apt (omnibus) | 漏洞利用框架 | `msfconsole` |
| hydra | apt | 暴力破解 | `hydra -l user -P pass.txt target ssh` |
| hashcat | apt | 密码破解 | `hashcat -m 0 hash.txt wordlist` |
| cloudsword | /opt/workspace/cloudsword | 云安全综合测试 | `cloudsword` |
| cf | /opt/workspace/cf | 云环境利用框架 | `cf` |

### Java 反序列化

| 工具 | 来源 | 用途 |
|------|------|------|
| JNDIExploit | /opt/workspace/JNDIExploit/ | JNDI 注入利用 |
| JYso | /opt/workspace/JYso/ | Java 反序列化利用 |
| shiro_cli | /opt/workspace/shiro/ | Shiro 反序列化 |
| ysoserial | /opt/workspace/ysoserial/ | Java 原生反序列化 Payload 生成 |
| marshalsec | /opt/workspace/marshalsec/ | Java Marshalling 漏洞 + JNDI/RMI/LDAP 引导服务 |

### 容器与编排

| 工具 | 来源 | 用途 |
|------|------|------|
| docker | /opt/workspace/docker/ | 容器操作（逃逸检测、镜像审计、挂载探测） |
| kubectl | /opt/workspace/kubectl/ | K8s 集群交互（枚举资源、窃取凭证、提权） |

### 内网渗透工具

| 工具 | 来源 | 用途 |
|------|------|------|
| frpc/frps | /opt/workspace/frp/ | 反向代理（首选） |
| chisel | /opt/workspace | HTTP 隧道代理 |
| Stowaway | /opt/workspace/Stowaway/ | 多级节点代理 |
| Neo-reGeorg | /opt/workspace/Neo-reGeorg/ | HTTP 隧道 |
| nxc (NetExec) | /opt/workspace/NetExec/ | 横向移动（SMB/SSH/WinRM） |
| mimikatz | /opt/workspace | Windows 凭证提取 |

### Webshell / 其他

| 工具 | 来源 | 用途 |
|------|------|------|
| weevely | apt | PHP Webshell 生成 |
| wsh | /opt/workspace | Webshell 管理 |
| rem | /opt/workspace/rem | 漏洞利用 |
| proxychains4 | apt | 代理链 |

**字典**: `/opt/workspace/SecLists/Discovery/Web-Content/`

### 外部知识库

| 工具 | 来源 | 用途 |
|------|------|------|
| vulnerability-wiki | skills/pentest/vulnerability-wiki/ | 漏洞知识库（1123+漏洞），本地文件读取 |
| vulhub | skills/pentest/vulhub/ | 317 漏洞环境知识库（本地 JSON 索引） |

**vulnerability-wiki**:
- 位置: `~/.claude/skills/pentest/vulnerability-wiki/`
- 功能: 1123 个漏洞知识库，本地文件读取（无需容器/Web 服务）
- 使用场景: observer_ward 识别出应用后，查询相关漏洞

```python
# 查询函数定义见: skills/pentest/vulnerability-wiki/SKILL.md

# 按应用模糊搜索（返回所有匹配）
results = search_by_app("ThinkPHP")  # 返回列表

# 按 CVE 精确搜索
result = search_by_cve("CVE-2022-22963")  # 返回单条

# 读取漏洞文件
detail = read_vuln_file("framework/ThinkPHP5-5.0.23-远程代码执行漏洞.md")
```

## 赛区策略

> 赛区策略为累积递进，所有赛区均可使用全部工具，赛区仅影响攻击思路和技能优先级。

| 赛区 | 优先攻击 | 附加技能 |
|------|----------|----------|
| Zone 1 | Web 漏洞 | sqlmap, xray, business-logic |
| Zone 2 | Zone1 + CVE/云/AI | nuclei, vulhub, vulnerability-wiki, cloud, ai-security |
| Zone 3 | Zone1+2 + 内网 | fscan, netexec, mimikatz, frp, stowaway, 多级代理 |

## 技能索引

### 核心技能
- [reporting](claude-code/.claude/skills/pentest/reporting/SKILL.md) — 解题报告
- [business-logic](claude-code/.claude/skills/pentest/business-logic/SKILL.md) — 业务逻辑漏洞

### MCP 工具技能
- [browser](claude-code/.claude/skills/pentest/browser/SKILL.md) — Playwright 浏览器操作
- [terminal](claude-code/.claude/skills/pentest/terminal/SKILL.md) — Tmux 终端操作
- [note](claude-code/.claude/skills/pentest/note/SKILL.md) — 笔记存储
- [competition](claude-code/.claude/skills/pentest/competition/SKILL.md) — 竞赛平台 API
- [reverse](claude-code/.claude/skills/pentest/reverse/SKILL.md) — 反连/JNDI 注入

### Web 安全（Zone 1）

### CVE / 知识库（Zone 2）
- [jndi-exploit](claude-code/.claude/skills/pentest/reverse/jndi-exploit.md) — JNDI 注入利用
- [vulnerability-wiki](claude-code/.claude/skills/pentest/vulnerability-wiki/SKILL.md) — 漏洞知识库
- [vulhub](claude-code/.claude/skills/pentest/vulhub/SKILL.md) — 漏洞环境知识库
- [cloud/](claude-code/.claude/skills/pentest/cloud/SKILL.md) — 云安全总览
- [metadata-service](claude-code/.claude/skills/pentest/cloud/metadata-service.md) — 云元数据服务利用
- [storage-security](claude-code/.claude/skills/pentest/cloud/storage-security.md) — 对象存储安全测试
- [container-security](claude-code/.claude/skills/pentest/cloud/container-security.md) — 容器与 K8s 安全
- [ssrf-to-cloud](claude-code/.claude/skills/pentest/cloud/ssrf-to-cloud.md) — SSRF 到云攻击链
- 工具: [lc](claude-code/.claude/skills/pentest/cloud/tools/lc.md) / [cloudsword](claude-code/.claude/skills/pentest/cloud/tools/cloudsword.md) / [cf](claude-code/.claude/skills/pentest/cloud/tools/cf.md) — 多云资产梳理 / 云安全综合测试 / 云环境利用框架
- [ai-security/](claude-code/.claude/skills/pentest/ai-security/SKILL.md) — AI 安全总览
- [prompt-injection](claude-code/.claude/skills/pentest/ai-security/prompt-injection.md) — 提示词注入攻击
- [llm-api](claude-code/.claude/skills/pentest/ai-security/llm-api.md) — LLM API 安全测试

### 内网渗透（Zone 3）
- [internal/](claude-code/.claude/skills/pentest/internal/SKILL.md) — 内网渗透总览
- [zone3-workflow](claude-code/.claude/skills/pentest/internal/workflow/SKILL.md) — Zone 3 递归渗透
- [info-gathering](claude-code/.claude/skills/pentest/internal/info-gathering/SKILL.md) — 内网信息收集
- [post-exploitation](claude-code/.claude/skills/pentest/internal/post-exploitation/SKILL.md) — 后渗透操作
- [tools-upload](claude-code/.claude/skills/pentest/internal/tools-upload/SKILL.md) — 工具上传
- [multi-hop-proxy](claude-code/.claude/skills/pentest/internal/multi-hop-proxy/SKILL.md) — 多级代理
- 工具: [frp](claude-code/.claude/skills/pentest/internal/tools/frp.md) / [chisel](claude-code/.claude/skills/pentest/internal/tools/chisel.md) / [stowaway](claude-code/.claude/skills/pentest/internal/tools/stowaway.md) / [fscan](claude-code/.claude/skills/pentest/internal/tools/fscan.md) / [netexec](claude-code/.claude/skills/pentest/internal/tools/netexec.md) / [mimikatz](claude-code/.claude/skills/pentest/internal/tools/mimikatz.md) / [neo-regeorg](claude-code/.claude/skills/pentest/internal/tools/neo-regeorg.md) / [reverse-shell](claude-code/.claude/skills/pentest/internal/tools/reverse-shell.md) / [file-transfer](claude-code/.claude/skills/pentest/internal/tools/file-transfer.md)
- 参考: [privilege-escalation](claude-code/.claude/skills/pentest/internal/references/privilege-escalation.md) / [domain-pentest](claude-code/.claude/skills/pentest/internal/references/domain-pentest.md)

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

### 容器配置

每个容器挂载以下卷：
- `claude-code/` → `/opt/nemo-agent/claude-code`（只读，Agent 代码和技能文件）
- `NOTE_PATH` → `/opt/notes`（读写，笔记存储）
- `NOTEBOOK_PATH` → `/opt/scripts`（读写，Jupyter notebook）
- `WORKSPACE_PATH` → `/opt/workspace`（读写，安全工具和字典）

容器内服务启动顺序（`entrypoint.sh`）：
1. `setup_symlinks.sh` — 创建工具软链接
2. `msfdb init` — 初始化 Metasploit 数据库
3. VNC 服务（可选，`NO_VISION=true` 时跳过）
4. Playwright 浏览器服务（端口 9222）
5. Python Executor MCP 服务（端口 8000）

### MCP 配置

容器内 MCP 服务配置（`.mcp.json`）：

```json
{
  "mcpServers": {
    "sandbox": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "description": "Python 代码执行器，支持 Jupyter 内核会话管理"
    }
  }
}
```

MCP 工具：
- `execute_code(session_name, code, timeout)` — 在 Jupyter 内核中执行 Python
- `list_sessions()` — 列出活跃会话
- `close_session(session_name)` — 关闭会话

Jupyter 会话自动加载 `toolset` 包，提供 `toolset.browser`、`toolset.terminal`、`toolset.note`、`toolset.competition`。

## 重要规则

| 规则 | 说明 |
|------|------|
| 开始前读笔记 | 了解之前的发现和推理 |
| 30分钟重读 | 重新整理思路，避免死循环（Zone 3 每 20 分钟） |
| 立即提交 FLAG | 获取后立即提交，防止超时丢失 |
| 发现即记录 | 重要信息立即保存到笔记 |
| HTTP exploit 用 Python | 禁止 terminal + curl（bash 二次解析特殊字符） |
| 同类型攻击最多 3 次 | 失败后切换攻击类型 |
| 知识库优先 | 识别到应用后必须先查 vulnerability-wiki，禁止未查就 WebSearch |
| 端口自由使用 | 容器映射的 10 个端口（PORT_NC ~ PORT_STOWAWAY）均为已映射到宿主机的可用端口，可按需自由分配给任何监听服务，用途仅作参考 |
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

# 单次运行（不循环）
python3 scheduler.py --once
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

功能：
- 实时仪表盘（SSE 推送状态更新）
- 笔记查看器（读取 `/opt/notes/*.md`）
- Jupyter Notebook 查看器（读取 `/opt/scripts/*.ipynb`）
- 用户名密码认证（默认 nemo/nemo，通过 `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` 环境变量配置）

## 参考资源

- TinyCTFer: https://wiki.chainreactors.red/blog/2025/12/01/intent_is_all_you_need/
- Meta-Tooling: https://wiki.chainreactors.red/blog/2025/12/02/intent_engineering_01/
- 腾讯云黑客松智能渗透挑战赛 API 文档（项目根目录）
- 腾讯云黑客松智能渗透挑战赛 MCP 接入文档（项目根目录）
