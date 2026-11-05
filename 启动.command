#!/bin/bash
cd "$(dirname "$0")" || exit 1
PORT=8901
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/api/status"; then
  open "http://127.0.0.1:$PORT"
  exit 0
fi
echo "=============================================="
echo " 用户整理工作台 · 正在启动"
echo "=============================================="
nohup python3 壳服务.py > /tmp/工作台壳.log 2>&1 &
for i in $(seq 1 25); do
  sleep 1
  curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/api/status" && break
done
open "http://127.0.0.1:$PORT"
echo
echo "浏览器已打开。首次使用要贴凭证，之后直接看。"
echo "关掉这个窗口不影响使用；要停服务：pkill -f 壳服务.py"
sleep 3
