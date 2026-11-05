#!/bin/bash
# 双击这个文件 → 启动工作台并打开浏览器
cd "$(dirname "$0")" || exit 1
PORT=8901
LOG="$HOME/工作台启动日志.txt"

pause() {
  echo
  echo "----------------------------------------------"
  read -n 1 -s -r -p "按任意键关闭这个窗口…"
  echo
}

echo "=============================================="
echo " 用户整理工作台 · 启动中"
echo "=============================================="
echo

# 1) 找 python3
PY=""
for c in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "❌ 这台电脑没有 python3。"
  echo
  echo "解决办法（选一个）："
  echo "  1. 打开「终端」，输入 xcode-select --install 回车，装完再双击本文件"
  echo "  2. 或者找管理员要一份已经生成好的快照 HTML"
  pause
  exit 1
fi
echo "✓ python3：$("$PY" -V 2>&1)"

# 2) 端口是否已有服务
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/api/status"; then
  echo "✓ 服务已经在运行"
else
  echo "→ 正在启动服务…"
  nohup "$PY" 壳服务.py > "$LOG" 2>&1 &
  for i in $(seq 1 25); do
    sleep 1
    if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/api/status"; then break; fi
  done
  if ! curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/api/status"; then
    echo "❌ 服务没起来。日志："
    echo "----------------------------------------------"
    tail -20 "$LOG" 2>/dev/null
    echo "----------------------------------------------"
    pause
    exit 1
  fi
fi

# 3) 打开浏览器
open "http://127.0.0.1:$PORT"
echo
echo "=============================================="
echo " ✅ 浏览器已打开： http://127.0.0.1:$PORT"
echo "=============================================="
echo
echo " 第一次会看到「初始化」页面："
echo "   · 把 CRM 凭证（jsu_ 开头）贴进输入框"
echo "   · 点「开始生成我的工作台」"
echo "   · 等 3–8 分钟，自动进入工作台"
echo
echo " 以后再打开：双击本文件即可，不用再填凭证。"
echo " 这个窗口可以关掉，服务在后台继续跑。"
echo
sleep 2
