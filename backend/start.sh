#!/bin/bash
# LetsPlay 后端启动脚本
# ADMIN_TOKEN 用于 admin 接口认证，请妥善保管
cd "$(dirname "$0")"

export ADMIN_TOKEN="letsplay-admin-2024"

python3 main.py "$@"
