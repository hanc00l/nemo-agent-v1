# Docker 容器网络与端口映射改造

## 背景

原始实现使用 `network_mode="host"` 作为临时方案，使容器与宿主机共享网络栈。但这在多容器并发场景下存在根本性缺陷：

- **MCP 服务端口冲突**：每个容器内的 `python_executor_mcp` (8000) 和 `browser` (9222) 监听固定端口，host 模式下多容器必然冲突
- **反弹 shell 端口冲突**：多个容器同时监听 10080 端口无法工作
- **`REVERSE_IP` 未注入**：Agent 内的反弹 shell skill 依赖 `REVERSE_IP` 环境变量，但容器创建时未注入

## 解决方案

### 1. 默认网络模式改为 bridge

**改动文件**：`task/core/container.py`、`task/config.py`

- 默认 `network_mode` 从 `"host"` 改为 `"bridge"`
- 添加 `extra_hosts={"host.docker.internal": "host-gateway"}`，确保容器内 `COMPETITION_API_URL` 中 `host.docker.internal` 域名可解析（Linux Docker 20.10+ 支持）
- `SchedulerConfig` 新增 `NETWORK_MODE` 字段，可通过 `.env` 的 `NETWORK_MODE` 环境变量配置

**bridge 模式下的端口分类**：

| 服务 | 端口 | 是否需要映射到 host |
|------|------|---------------------|
| MCP Python Executor | 8000 | 否（容器内部通信） |
| Playwright Browser | 9222 | 否（容器内部通信） |
| VNC | 55900+ | 是（人工查看） |
| 反弹 shell / JNDI / frp 等 | 20000+ | 是（目标回连） |

### 2. 运行时端口注册表（核心机制）

**改动文件**：`task/core/container.py`

新增三个函数，管理一个线程安全的端口分配注册表：

| 函数 | 作用 | 调用时机 |
|------|------|----------|
| `get_reverse_ports(llm_id, challenge_code)` | 按 `(challenge_code, llm_id)` 分配或复用端口槽 | 容器创建时 |
| `release_reverse_ports(challenge_code, llm_id)` | 释放已注册的端口槽 | 容器停止时 |
| `init_port_registry(docker_client)` | 扫描运行中容器，重建注册表 | 调度器启动时 |

**分配规则**：
- 每个 `(challenge_code, llm_id)` 组合分配 10 个端口（一个"槽"）
- 端口从 20000 起，递增分配：第 1 个容器 20000-20009，第 2 个 20010-20019，依此类推
- 同一组合重复调用返回相同端口（幂等性）
- 最大支持 100 个并发容器（端口范围 20000-20999）

**每个槽内的端口分配**：

| 偏移 | 环境变量名 | 用途 |
|------|-----------|------|
| +0 | `PORT_NC` | NC 反弹 Shell（主） |
| +1 | `PORT_NC2` | NC 反弹 Shell（备） |
| +2 | `PORT_JNDI_LDAP` | JNDI LDAP |
| +3 | `PORT_JNDI_HTTP` | JNDI HTTP |
| +4 | `PORT_SOCKS5` | SOCKS5 代理 |
| +5 | `PORT_FRP` | frp 服务端 |
| +6 | `PORT_FRP_DASHBOARD` | frp Dashboard |
| +7 | `PORT_MSF` | Metasploit |

**示例**（3 题 × 3 LLM = 9 容器）：

| 题目 | LLM | 端口范围 |
|------|-----|----------|
| web-001 | LLM-1 | 20000-20007 |
| web-001 | LLM-2 | 20010-20017 |
| web-001 | LLM-3 | 20020-20027 |
| pwn-002 | LLM-1 | 20030-20037 |
| pwn-002 | LLM-2 | 20040-20047 |
| pwn-002 | LLM-3 | 20050-20057 |
| misc-003 | LLM-1 | 20060-20067 |
| misc-003 | LLM-2 | 20070-20077 |
| misc-003 | LLM-3 | 20080-20087 |

### 3. 环境变量注入

**改动文件**：`task/core/container.py` — `prepare_container_config()`

容器创建时自动注入以下环境变量：

```
REVERSE_IP=192.168.52.101     # 从宿主机 .env 读取
PORT_NC=20000                 # 自动分配
PORT_NC2=20001
PORT_JNDI_LDAP=20002
PORT_JNDI_HTTP=20003
PORT_SOCKS5=20004
PORT_FRP=20005
PORT_FRP_DASHBOARD=20006
PORT_MSF=20007
```

同时将这些端口添加到 Docker 端口映射（`ports` 参数），bridge 模式下自动生效。

### 4. 调度器集成

**改动文件**：`task/container_manager.py`、`task/scheduler.py`

- `ContainerManager.__init__` 新增 `network_mode` 参数，初始化时调用 `init_port_registry()` 重建端口状态
- `start_challenge_containers` 传递 `network_mode` 给 `create_challenge_container`
- `stop_challenge_containers` 停止容器前调用 `release_reverse_ports()` 释放端口

### 5. Agent Skills 更新

**改动文件**：`reverse-shell.md`（v1→v2）、`reverse/SKILL.md`（v2→v3）

- 所有端口引用从硬编码（`10080`、`1389`、`8080`）改为环境变量（`$PORT_NC`、`$PORT_JNDI_LDAP`、`$PORT_JNDI_HTTP`）
- 强制规则新增：禁止硬编码端口，必须从环境变量读取
- 示例代码从 bash 片段改为完整的 Python 片段（使用 `os.environ` 读取端口）
- 命令速查表更新为使用环境变量

### 6. 配置文件

**改动文件**：`task/.env.example`

- 删除 `NC_PORT`、`JNDI_LDAP_PORT`、`JNDI_HTTP_PORT`、`MSF_PORT` 等已废弃的固定端口配置
- 新增 `NETWORK_MODE=bridge` 配置项
- 保留 `REVERSE_IP` 配置，注释说明端口由调度器自动分配

### 7. 清理

- 删除 `create_challenge_container()` 中被注释掉的旧代码（约 20 行）
- 删除重复的 `# 创建并启动容器` 注释

## 文件变更清单

| 文件 | 变更行数 | 改动摘要 |
|------|----------|----------|
| `task/core/container.py` | +140 | 端口注册表、环境变量注入、bridge 默认、extra_hosts、清理注释 |
| `task/core/__init__.py` | +6 | 导出 `get_reverse_ports`、`release_reverse_ports`、`init_port_registry` |
| `task/container_manager.py` | +17 | 传递 `network_mode`、初始化注册表、停止时释放端口 |
| `task/scheduler.py` | +3 | 传递 `network_mode` 给 ContainerManager |
| `task/config.py` | +5 | 新增 `NETWORK_MODE` 配置字段和加载 |
| `task/.env.example` | +25/-20 | 更新端口配置说明 |
| `reverse-shell.md` | +140/-140 | 端口改为环境变量，示例改为 Python |
| `reverse/SKILL.md` | +104/-104 | 端口改为环境变量，示例改为 Python |

## 验证要点

1. **端口无冲突**：3 题 × 3 LLM = 9 容器，72 个端口互不重叠
2. **幂等性**：同一 (challenge_code, llm_id) 重复调用返回相同端口
3. **恢复性**：调度器重启后 `init_port_registry` 扫描运行中容器重建注册表
4. **bridge 连通性**：`host.docker.internal` 域名可解析，MCP 内部服务正常
5. **反弹测试**：容器内 `nc -lvnp $PORT_NC` → 外部连接宿主机映射端口 → 成功回连
