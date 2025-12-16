# 支付宝账单分析系统部署指南

## 1. 环境要求

### 1.1 基础环境
~~~bash
# Python 环境
Python >= 3.8
pip >= 21.0

# 操作系统
- Linux (推荐 Ubuntu 20.04+)
- macOS
- Windows 10+

### 1.2 部署平台支持
- 本地部署（Windows/Mac/Linux）
- 服务器部署（Docker/Nginx）
- **PythonAnywhere (PaaS)**: [查看详细部署指南](deployment_pythonanywhere.md)~~~

### 1.2 依赖包
~~~bash
flask>=2.0.0
pandas>=1.3.0
numpy>=1.20.0
werkzeug>=2.0.0
~~~

## 2. 安装步骤

### 2.1 获取代码
~~~bash
# 克隆代码仓库
git clone https://github.com/yourusername/alipay-analysis.git
cd alipay-analysis

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Linux/macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
~~~

### 2.2 配置文件
创建 `config.py` 配置文件：
~~~python
# config.py
import os

class Config:
    # 基础配置
    SECRET_KEY = 'your-secret-key-here'  # 修改为随机字符串
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    
    # 文件上传配置
    UPLOAD_FOLDER = './tmp/alipay_analysis'
    BACKUP_FOLDER = './backup'
    
    # 会话配置
    SESSION_TIMEOUT = 1800  # 30分钟
    
    # 日志配置
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
~~~

### 2.3 目录结构
确保创建必要的目录：
~~~bash
mkdir -p tmp/alipay_analysis
mkdir -p backup
mkdir -p logs
~~~

## 3. 部署方式

### 3.1 开发环境
~~~bash
# 直接运行
python app.py

# 或使用 Flask 命令
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --host=0.0.0.0 --port=8080
~~~

### 3.2 生产环境（Gunicorn + Nginx）

#### 安装 Gunicorn
~~~bash
pip install gunicorn
~~~

#### Gunicorn 配置
创建 `gunicorn_config.py`：
~~~python
# gunicorn_config.py
bind = '127.0.0.1:8000'
workers = 4
threads = 2
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 2
~~~

#### Nginx 配置
~~~nginx
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /path/to/your/static/files;
        expires 30d;
    }
}
~~~

#### 启动服务
~~~bash
gunicorn -c gunicorn_config.py app:app
~~~

### 3.3 使用 Docker 部署

#### Dockerfile
~~~dockerfile
FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_ENV=production

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
~~~

#### Docker Compose
~~~yaml
version: '3'
services:
  web:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./tmp:/app/tmp
      - ./backup:/app/backup
      - ./logs:/app/logs
    environment:
      - FLASK_APP=app.py
      - FLASK_ENV=production
~~~

## 4. 监控和维护

### 4.1 日志配置
~~~python
import logging

logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
~~~

### 4.2 定时任务
创建清理脚本 `cleanup.py`：
~~~python
import os
import shutil
from datetime import datetime, timedelta

def cleanup_old_files():
    """清理超过24小时的临时文件"""
    tmp_dir = './tmp/alipay_analysis'
    threshold = datetime.now() - timedelta(hours=24)
    
    for root, dirs, files in os.walk(tmp_dir):
        for name in files:
            filepath = os.path.join(root, name)
            if datetime.fromtimestamp(os.path.getmtime(filepath)) < threshold:
                os.remove(filepath)
~~~

### 4.3 健康检查
创建健康检查端点：
~~~python
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })
~~~

## 5. 安全配置

### 5.1 HTTPS 配置
~~~nginx
server {
    listen 443 ssl;
    server_name your_domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # ... 其他配置
}
~~~

### 5.2 安全头部配置
~~~python
from flask_talisman import Talisman

Talisman(app, 
    force_https=True,
    strict_transport_security=True,
    session_cookie_secure=True
)
~~~

## 6. 故障排除

### 6.1 常见问题
- 文件权限问题
- 内存使用过高
- 连接超时
- 日志写入失败

### 6.2 排查步骤
1. 检查日志文件
2. 监控系统资源
3. 验证配置文件
4. 测试文件权限

### 6.3 性能优化
- 启用缓存
- 优化数据库查询
- 使用异步任务
- 实施负载均衡
~~~ 