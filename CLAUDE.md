# CLAUDE.md

## 项目概述

基于 Claude Code 的自动化渗透测试 Agent，达到中高级网络安全专家水平。

**设计哲学**: "Intent → Code → Execute → Record → Result"

## 标准作业流程

```
0. 读取笔记 → note.get_notes_summary(challenge_code)
1. 手动侦察 → 浏览器访问、源码分析
2. 主动侦察 → nmap、katana、whatweb
3. 漏洞测试 → XSS/SQLi/IDOR/SSTI/命令注入
4. 漏洞利用 → 获取 FLAG
5. 立即提交 → competition.submit_answer()
6. 保存结果 → note.append_note("result", flag)
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

### Competition 平台 API

| 函数 | 用途 |
|------|------|
| `get_challenges()` | 获取所有挑战 |
| `get_target_url(code)` | 获取目标 URL |
| `get_hint(code)` | 获取提示（扣分） |
| `submit_answer(code, flag)` | 提交 FLAG |

### Browser 浏览器工具

Playwright 自动化：页面访问、交互、截图、JS 执行

- `goto(url)` / `screenshot(path)` / `evaluate(js)`
- `click(sel)` / `fill(sel, text)`

### Terminal 终端工具

基于 tmux 的命令执行：长时间运行、实时输出、超时控制

- `run_command(cmd, timeout)` / `get_output()` / `is_running()`

## 安全工具

| 工具 | 用途 | 命令 |
|------|------|------|
| nmap | 端口扫描 | `nmap -sV -n -T4 --open target` |
| ffuf | 模糊测试 | `ffuf -u 'http://target/FUZZ' -w wordlist` |
| katana | 网页爬取 | `katana -u http://target -d 3 -jc` |
| whatweb | 技术栈 | `whatweb -a 3 http://target` |

**字典**: `/usr/share/seclists/Discovery/Web-Content/`

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
