#!/bin/bash
# 安全重启后端：只杀掉 8000 端口的进程，不误杀其他 python 进程

PORT=${PORT:-8000}

echo "=== 停止端口 $PORT 上的进程 ==="
# 查找并杀掉占用指定端口的进程
PID=$(netstat -ano 2>/dev/null | grep ":$PORT " | grep LISTENING | awk '{print $5}' | sort -u | head -1)
if [ -n "$PID" ]; then
  taskkill //f //pid $PID 2>/dev/null || kill -9 $PID 2>/dev/null
  echo "已停止 PID=$PID"
  sleep 2
else
  echo "端口 $PORT 无占用"
fi

echo "=== 启动服务器 ==="
cd "$(dirname "$0")"
exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
