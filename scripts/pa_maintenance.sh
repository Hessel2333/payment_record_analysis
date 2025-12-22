#!/bin/bash

# ==========================================================
# PythonAnywhere 维护脚本
# 功能：1. 从 GitHub 推送更新 2. 清理临时文件 3. 重载 Web 应用
# ==========================================================

# 1. 自动定位项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "--- 开始维护任务: $(date) ---"

# 2. 从 GitHub 拉取最新代码
echo "正在从 GitHub 拉取代码更新..."
GIT_OUTPUT=$(git pull 2>&1)
echo "$GIT_OUTPUT"

# 3. 清理过期临时文件 (1小时前)
echo "正在执行文件清理..."
if [ -f "venv/bin/python" ]; then
    venv/bin/python scripts/clean_uploads.py
elif [ -f ".venv/bin/python" ]; then
    .venv/bin/python scripts/clean_uploads.py
else
    python3 scripts/clean_uploads.py
fi

# 4. 如果代码有更新，或者您希望每次都重载，执行以下命令
# 在 PythonAnywhere 上，touch WSGI 文件相当于点击 Reload 按钮
# 默认路径通常是 /var/www/您的用户名_pythonanywhere_com_wsgi.py
# 我们尝试匹配该文件
WSGI_FILE=$(ls /var/www/*_wsgi.py 2>/dev/null | head -n 1)

if [[ "$GIT_OUTPUT" != *"Already up to date."* ]]; then
    echo "检测到代码更新，正在重载 Web 应用..."
    if [ -n "$WSGI_FILE" ]; then
        touch "$WSGI_FILE"
        echo "已重载: $WSGI_FILE"
    else
        echo "警告：未找到 WSGI 文件，请在 Web 标签页手动点击 Reload。"
    fi
else
    echo "代码已是最新，无需重载。"
fi

echo "--- 维护任务完成 ---"
