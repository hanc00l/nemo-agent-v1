# Pentest Agent 提示词测试文档

> 用于手工测试和容器注入测试。需要注入的参数用 `{参数名}` 表示。

## 提示词加载架构

```
用户输入（手工或容器注入）
    ↓
主 Claude Code 收到 "使用pentest-agent" 指令
    ↓
调用 Agent tool，指定 subagent_type="pentest-agent"
    ↓ 自动加载
pentest-agent.md（系统提示词）+ SKILL.md（技能索引）
    ↓ 按需读取
reconnaissance/SKILL.md、vulnerability-wiki/SKILL.md 等子技能
```

- **触发方式**：用户消息中的 "使用pentest-agent" 文本指令
- **不需要** `/pentest` slash command
- **不需要** 在任务提示词中重复 pentest-agent.md 的内容

## 使用方法

### 场景 1：手工测试

在 Claude Code CLI 中直接粘贴对应赛区的提示词模板（替换 `{参数名}` 为实际值）。

### 场景 2：容器注入

solver.py 调用 `build_task_prompt()` 生成提示词，通过 `claude --print "{prompt}"` 注入容器。

两种场景使用相同的提示词模板。

## 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `{target_url}` | 目标 URL | `http://192.168.52.102:8080/` |
| `{target_ip}` | 目标 IP（从 URL 提取） | `192.168.52.102` |
| `{challenge_code}` | 题目代码 | `test-0412-1` |
| `{zone}` | 赛区编号 | `1` / `2` / `3` |
| `{description}` | 题目描述（可选） | `找到隐藏的 flag` |
| `{hint}` | 提示信息（可选） | `关注 HTTP 头` |
| `{flag_count}` | Flag 总数（可选，默认 1） | `1` |

---

# ============================================================
# 任务提示词模板
# 复制对应赛区模板，替换 {参数名} 后使用
# ============================================================

---
---

## Zone 1 — Web 漏洞赛区

使用pentest-agent，对以下目标进行渗透测试，获取 flag。

## 目标信息

- 目标 URL: {target_url}
- 目标 IP: {target_ip}
- 题目代码: {challenge_code}
- 赛区: Zone 1
- 题目描述: {description}
- 提示信息: {hint}

{competition_section}

---
---

## Zone 2 — CVE/云/AI 赛区

使用pentest-agent，对以下目标进行渗透测试，获取 flag。

## 目标信息

- 目标 URL: {target_url}
- 目标 IP: {target_ip}
- 题目代码: {challenge_code}
- 赛区: Zone 2
- 题目描述: {description}
- 提示信息: {hint}

{competition_section}

---
---

## Zone 3 — 内网渗透赛区

使用pentest-agent，对以下目标进行渗透测试，获取 flag。

## 目标信息

- 目标 URL: {target_url}
- 目标 IP: {target_ip}
- 题目代码: {challenge_code}
- 赛区: Zone 3
- 题目描述: {description}
- 提示信息: {hint}

{competition_section}

---
---

# 附录：竞赛模式附加段落
# 当 competition_mode=True 时，替换上方 {competition_section} 为以下内容

## 竞赛模式（已启用）

- 获取 FLAG 后必须调用: toolset.competition.submit_answer(challenge_code="{challenge_code}", answer=flag)
- 确认返回 correct=True 才算完成
