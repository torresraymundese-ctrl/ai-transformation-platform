#!/usr/bin/env python                # ✅ Python 解释器声明
"""企业AI转型平台 — WSGI 入口文件"""

# 🌐 Web 服务器网关接口（WSGI）入口
# 生产环境使用: gunicorn -w 2 -b 127.0.0.1:5080 wsgi:app

from app import app                     # 导入 Flask 应用实例

if __name__ == "__main__":              # 直接运行时启动开发服务器
    app.run()                           # 生产环境请使用 gunicorn 代替
