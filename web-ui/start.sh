#!/bin/bash


# 启动 CTF 解题记录 Web UI
source .venv/bin/activate
echo "启动 Web UI 在 http://0.0.0.0:8003"
python3 manage.py runserver 0.0.0.0:8003
