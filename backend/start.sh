#!/bin/bash
# Railway 启动脚本
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
