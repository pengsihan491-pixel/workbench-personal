#!/bin/bash
# 一键：解压 zip 后第一次运行，装好快捷方式到桌面
cd "$(dirname "$0")" || exit 1
chmod +x 启动.command 2>/dev/null
D="$HOME/Desktop"
[ -d "$D" ] || D="$HOME/桌面"
if [ -d "$D" ]; then
  cat > "$D/打开工作台.command" <<SH
#!/bin/bash
cd "$(pwd)" && bash 启动.command
SH
  chmod +x "$D/打开工作台.command"
  echo "✓ 桌面已放好「打开工作台.command」，以后双击那个就行"
else
  echo "（没找到桌面目录，直接双击 启动.command 也可以）"
fi
open "先看这个.html" 2>/dev/null
