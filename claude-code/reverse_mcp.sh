#!/bin/bash
set -e

export WORKSPACE=/opt/workspace

# local
source .venv/bin/activate

# 启动Python Executor MCP
python3 /opt/nemo-agent/claude-code/meta-tooling/service/reverse_mcp.py

