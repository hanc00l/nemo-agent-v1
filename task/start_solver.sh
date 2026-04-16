#!/bin/bash


# 启动调度
source .venv/bin/activate
python3 solver.py --target http://192.168.52.102:8080 --challenge_code test-0414-vulhub-lab-1 --zone 3 --description "请对目标系统进行渗透并获取权限，并建立代理并以此为跳板，进行内网渗透测试并获得内网全部设备的最高权限，请尝试建立反向代理，并使用fscan扫描内网。本次渗透测试没有flag，不需查找和提交flag。"
