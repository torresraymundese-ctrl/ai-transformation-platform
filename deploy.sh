#!/bin/bash
set -e
# ==========================================
# 企业AI转型平台 - 阿里云 ECS 部署脚本
# 域名: open.sucaiyigou.cn
# 支持: Ubuntu/Debian (apt) / CentOS/Aliyun Linux (yum)
# ==========================================

echo "===== 0. 检测系统并安装依赖 ====="
if command -v apt &>/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt update -y
    apt install -y nginx python3-pip certbot python3-certbot-nginx
elif command -v yum &>/dev/null; then
    yum install -y epel-release
    yum install -y nginx python3-pip certbot python3-certbot-nginx
elif command -v dnf &>/dev/null; then
    dnf install -y epel-release
    dnf install -y nginx python3-pip certbot python3-certbot-nginx
else
    echo "ERROR: Unsupported package manager"; exit 1
fi

echo "===== 1. 部署项目文件 ====="
rm -rf /opt/ai-platform
cp -r "$(dirname "$0")" /opt/ai-platform
cd /opt/ai-platform
# Remove Windows-only binaries and dev artifacts
rm -f natapp.exe ngrok.exe natapp.zip ngrok.zip natapp_windows_amd64_3_0_3.zip
rm -rf natapp_windows_amd64_3_0_3 __pycache__ .git
rm -f platform.db data/platform.db  # fresh DB on deploy
mkdir -p data

echo "===== 2. 安装 Python 依赖 ====="
pip3 install --break-system-packages -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt

echo "===== 3. 初始化数据库 ====="
python3 -c "from models import init_db; init_db()"

echo "===== 4. 内容接入队列尚未就绪；跳过旧内容发布 ====="

echo "===== 5. 配置 Nginx ====="
cp open.sucaiyigou.cn.conf /etc/nginx/sites-available/open.sucaiyigou.cn 2>/dev/null || \
    cp open.sucaiyigou.cn.conf /etc/nginx/conf.d/open.sucaiyigou.cn.conf
ln -sf /etc/nginx/sites-available/open.sucaiyigou.cn /etc/nginx/sites-enabled/ 2>/dev/null || true
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
nginx -t && systemctl reload nginx

echo "===== 6. 配置 Systemd 进程守护 ====="
cp ai-platform.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ai-platform
systemctl restart ai-platform

echo "===== 7. 配置 SSL ====="
# Only run certbot if DNS resolves
if host open.sucaiyigou.cn &>/dev/null; then
    certbot --nginx -d open.sucaiyigou.cn --non-interactive --agree-tos -m admin@sucaiyigou.cn --redirect || echo "SSL: certbot failed (DNS may need time)"
else
    echo "SSL: DNS not resolved yet, skip certbot. Run manually: certbot --nginx -d open.sucaiyigou.cn"
fi

echo "===== 部署完成 ====="
echo "HTTP:  http://open.sucaiyigou.cn"
echo "HTTPS: https://open.sucaiyigou.cn"
echo "Health: http://open.sucaiyigou.cn/health"
