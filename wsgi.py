#!/usr/bin/env python                # ✅ Python 解释器声明
"""企业AI转型平台 — WSGI 入口文件"""

# 🌐 Web 服务器网关接口（WSGI）入口
# 生产环境使用: gunicorn -w 2 -b 127.0.0.1:5080 wsgi:app

import os
from pathlib import Path

from app import create_app


def _production_media_root():
    value = os.environ.get("AI_PLATFORM_MEDIA_ROOT")
    if not value:
        raise RuntimeError("AI_PLATFORM_MEDIA_ROOT is required for production")
    root = Path(value).resolve()
    allowed = Path("/opt/ai-platform/data/media").resolve()
    if root != allowed and allowed not in root.parents:
        raise RuntimeError(
            "production media root must stay under /opt/ai-platform/data/media"
        )
    return str(root)


app = create_app({"MEDIA_UPLOAD_ROOT": _production_media_root()})

if __name__ == "__main__":              # 直接运行时启动开发服务器
    app.run()                           # 生产环境请使用 gunicorn 代替
