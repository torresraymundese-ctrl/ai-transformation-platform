# 企业 AI 转型平台 V2 核心闭环

这是 Flask + SQLite 模块化单体的 V2 核心子项目，当前覆盖选择题式评估、
六维评分、场景与服务包匹配、ROI、Session 私有报告/PDF、线索同意、诊断
预约、匿名转化事件，以及两位人员共用一个管理员账号的线索操作后台。

当前阶段先验证功能和数据边界，最终视觉重设计尚未开始。生产服务器、生产
数据库和 Nginx 不属于本地开发范围；Nginx 必须保持停止，直到阶段 7 的备份、
恢复演练和上线门禁全部通过。

## Windows 本地启动

在项目根目录使用 PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

$env:AI_PLATFORM_SECRET_KEY = '<至少 32 字节的随机值>'
$env:AI_PLATFORM_ADMIN_USERNAME = '<管理员用户名>'
$env:AI_PLATFORM_ADMIN_PASSWORD_HASH = '<Werkzeug scrypt 哈希，不是明文密码>'
$env:AI_PLATFORM_PRIVACY_PROCESSOR_NAME = '<个人信息处理者全称>'
$env:AI_PLATFORM_PRIVACY_CONTACT = '<隐私请求联系方式>'
$env:AI_PLATFORM_PRIVACY_POLICY_URL = 'https://<正式域名>/privacy'

.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe app.py
```

浏览器打开 `http://127.0.0.1:5080`。可用以下命令生成随机 Session 密钥和
交互式密码哈希；不要把明文密码写入源码、命令参数、聊天或提交记录：

```powershell
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.venv\Scripts\python.exe -c "import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass.getpass('New administrator password: ')))"
```

Windows 缺少 Pango/Harfbuzz 原生运行库时，在线 HTML 报告仍可开发和测试，
但不能据此宣称原生 PDF 已验收。Ubuntu 的依赖与阶段 7 预检见
[`docs/deployment/security-and-service.md`](docs/deployment/security-and-service.md)。

## 验证与运维文档

- 核心旅程、证据边界和复现命令：
  [`docs/testing/core-assessment-report.md`](docs/testing/core-assessment-report.md)
- 管理员密钥、数据库备份/恢复、PDF、保留清理与服务上线：
  [`docs/deployment/security-and-service.md`](docs/deployment/security-and-service.md)
- 产品规格：
  [`docs/superpowers/specs/2026-08-19-ai-platform-2.0-product-design.md`](docs/superpowers/specs/2026-08-19-ai-platform-2.0-product-design.md)

仓库根目录的旧 `deploy.sh` 来自 V0.x 快照，会删除部署目录和数据库，不能用于
V2 生产升级。阶段 7 只允许按部署文档中的备份、恢复演练和受控发布流程操作。
