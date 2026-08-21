# 安全配置与 systemd 部署基线

本文件描述 V2.0 最终上线时的安全、数据和服务操作。当前升级期间生产主机不在
操作范围内，Nginx 保持停止。以下生产命令只能在阶段 7 的维护窗口执行，不能把
文档视为当前阶段连接或修改生产的授权。

## 请求链路与时区不变量

```text
用户 → Nginx(80/443) → 127.0.0.1:5080 → Gunicorn(2 workers) → Flask/SQLite
                         systemd: ai-platform
```

Nginx 只负责 TLS、静态文件和反向代理；Gunicorn 只监听 loopback；Flask 保持
模块化单体；SQLite 数据文件只允许写入 `/opt/ai-platform/data/platform.db`。
预约、评估完成、跟进、隐私请求和保留判断都使用显式 `Asia/Shanghai` 业务时钟，
不能依赖宿主机本地时区，也不能用 UTC 日期替代上海日期。阶段 7 可用下面命令
核对运维窗口，但应用即使运行在 UTC 宿主机上也必须保持上海时间语义：

```bash
TZ=Asia/Shanghai date '+%F %T %z'
```

仓库根目录的旧 `deploy.sh` 会删除 `/opt/ai-platform` 和数据库，禁止用于 V2
升级。V2 只允许在已验证备份上进行受控文件发布、迁移和服务切换。

## 目标状态

- Gunicorn 只监听 `127.0.0.1:5080`，不能绕过 Nginx 从公网直连。
- 应用由专用的 `ai-platform` 系统用户运行，不由 root 运行。
- 管理员用户名、密码哈希、Session 密钥和三项隐私配置来自
  `/etc/ai-platform/ai-platform.env`。
- 环境文件权限为 `0600 root:root`；源码、提交记录和命令行参数不出现明文密码。
- 运行日志进入 journald；SQLite 只有 `/opt/ai-platform/data` 可写。
- 两位人员继续共用一个管理员账号和同一权限，不新增账号/角色系统。

## 建立管理员和隐私配置

以 root 创建受限目录，再运行交互式工具：

```bash
install -d -m 0700 -o root -g root /etc/ai-platform
python3 /opt/ai-platform/scripts/configure_security.py \
  --username <new-admin-username> \
  --output /etc/ai-platform/ai-platform.env
```

工具隐式询问两次新密码。密码至少 14 个字符；文件只保存 Werkzeug scrypt 哈希
和随机 Session 密钥，并拒绝覆盖已有文件。随后使用
`sudoedit /etc/ai-platform/ai-platform.env` 在同一受限文件补齐隐私配置。

六个生产键必须全部存在且非空：

```text
AI_PLATFORM_SECRET_KEY=<随机 Session 密钥>
AI_PLATFORM_ADMIN_USERNAME=<共享管理员用户名>
AI_PLATFORM_ADMIN_PASSWORD_HASH=<Werkzeug scrypt 哈希>
AI_PLATFORM_PRIVACY_PROCESSOR_NAME=<个人信息处理者全称>
AI_PLATFORM_PRIVACY_CONTACT=<隐私请求联系渠道>
AI_PLATFORM_PRIVACY_POLICY_URL=https://<正式域名>/privacy
```

不得创建明文管理员密码变量，也不得把真实值写入源码、Git、命令参数、聊天、
工单或日志。缺少管理员安全键时 `/admin/login` 必须为 503；缺少任一隐私键时
V2 评估配置必须为可恢复的 503，不能使用虚构默认值。

只检查元数据，不输出文件内容：

```bash
stat -c '%a %U %G %n' /etc/ai-platform/ai-platform.env
```

期望为 `600 root root /etc/ai-platform/ai-platform.env`。

## 服务账号、目录和依赖

```bash
useradd --system --home /opt/ai-platform --shell /usr/sbin/nologin ai-platform
install -d -m 0750 -o ai-platform -g ai-platform /opt/ai-platform/data
chown -R root:ai-platform /opt/ai-platform
chown -R ai-platform:ai-platform /opt/ai-platform/data
```

生产虚拟环境位于 `/opt/ai-platform/.venv`，由 root 安装锁定依赖，运行用户只有
读取权限。Ubuntu 安装应用测试/备份工具和 WeasyPrint 69 运行库：

```bash
apt-get update
apt-get install -y sqlite3 rsync curl \
  libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
  libharfbuzz-subset0 fonts-noto-cjk
python3 -m venv /opt/ai-platform/.venv
/opt/ai-platform/.venv/bin/python -m pip install --upgrade pip
/opt/ai-platform/.venv/bin/python -m pip install \
  -r /opt/ai-platform/requirements-dev.txt
```

`requirements-dev.txt` 会同时安装 `requirements.txt` 中的生产依赖和固定版本的
pytest，因此下面要求的生产候选验证命令可在全新虚拟环境复现；服务运行时不会
调用 pytest。生产固定使用 `WeasyPrint==69.0`。应用依赖安装完成后，阶段 7
必须单独运行：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m weasyprint --info
```

命令必须成功显示 WeasyPrint、Python 和底层文本渲染库信息。不要把它放进
systemd `ExecStartPre`：PDF 原生运行库异常时，HTML 应用和已生成的在线报告仍
必须启动，PDF 路由只返回可重试的通用 503。

## SQLite 备份、迁移和恢复演练

阶段 7 每次迁移前先确认 Nginx 仍未启动：

```bash
systemctl is-active nginx
```

期望为 `inactive`。创建 SQLite 在线一致性备份；不能复制活动中的单个 DB 文件
来代替 `.backup`：

```bash
install -d -m 0700 /var/backups/ai-platform
BACKUP_FILE="/var/backups/ai-platform/platform-$(date +%Y%m%d-%H%M%S).db"
sqlite3 /opt/ai-platform/data/platform.db ".backup '$BACKUP_FILE'"
chmod 0600 "$BACKUP_FILE"
sqlite3 "$BACKUP_FILE" 'PRAGMA integrity_check;'
sha256sum "$BACKUP_FILE"
```

`PRAGMA integrity_check` 必须只输出 `ok`。再把备份恢复到隔离目录并对恢复副本
执行迁移，不能用生产 DB 做“演练”：

```bash
REHEARSAL_DIR="$(mktemp -d /tmp/ai-platform-restore.XXXXXX)"
rsync -a --exclude='.venv/' --exclude='data/' /opt/ai-platform/ "$REHEARSAL_DIR/"
install -d -m 0750 -o ai-platform -g ai-platform "$REHEARSAL_DIR/data"
install -m 0640 -o ai-platform -g ai-platform \
  "$BACKUP_FILE" "$REHEARSAL_DIR/data/platform.db"
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  "$REHEARSAL_DIR/manage.py" migrate
sqlite3 "$REHEARSAL_DIR/data/platform.db" \
  'PRAGMA integrity_check; SELECT version FROM schema_migrations ORDER BY version;'
```

记录备份路径、SHA-256、`ok`、迁移版本和恢复副本统计。保留恢复目录直至上线
决定；未成功恢复并迁移副本时，不得重启应用、执行删除/匿名化或启动 Nginx。

若阶段 7 明确决定回滚，先保持 Nginx 停止并停止应用，再原子替换数据库。只有
已记录校验值的备份可以作为来源：

```bash
systemctl stop ai-platform
install -m 0640 -o ai-platform -g ai-platform \
  "$BACKUP_FILE" /opt/ai-platform/data/platform.db.restore
rm -f /opt/ai-platform/data/platform.db-wal /opt/ai-platform/data/platform.db-shm
mv /opt/ai-platform/data/platform.db.restore /opt/ai-platform/data/platform.db
systemctl start ai-platform
curl --fail http://127.0.0.1:5080/health
```

这些是阶段 7 的回滚步骤，不授权当前本地任务执行任何生产操作。

## 保留期限清理

完成并记录上述备份和恢复演练后，先以运行用户执行 dry-run：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py purge-expired-leads
```

输出只能包含 `mode=dry-run`、数量和内部线索 ID，不能出现联系方式。人工核对
候选范围、备份路径和恢复记录后，才允许在维护窗口执行：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py purge-expired-leads --apply
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py purge-expired-leads
```

`--apply` 匿名化未成交到期线索并保留不可识别的评估/ROI/事件指标；已成交客户
不参与普通自动清理。没有已校验备份或恢复演练失败时严禁执行 `--apply`。

## 安装与轮换 systemd 服务

```bash
install -m 0644 ops/systemd/ai-platform.service /etc/systemd/system/ai-platform.service
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/ai-platform.service
```

服务单元通过 `EnvironmentFile` 读取配置，Gunicorn 绑定 loopback，并在每次启动
前用 `manage.py migrate` 幂等应用迁移。正式启用前必须完成数据库备份、文件权限
验证和恢复副本迁移演练。

可在维护窗口单独运行迁移：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py migrate
```

轮换管理员密码或 Session 密钥时不能覆盖现有文件。生成新文件、补齐三个隐私
键、验证权限后，才在维护窗口原子替换：

```bash
python3 /opt/ai-platform/scripts/configure_security.py \
  --username <new-admin-username> \
  --output /etc/ai-platform/ai-platform.env.new
sudoedit /etc/ai-platform/ai-platform.env.new
stat -c '%a %U %G %n' /etc/ai-platform/ai-platform.env.new
mv /etc/ai-platform/ai-platform.env.new /etc/ai-platform/ai-platform.env
systemctl restart ai-platform
```

轮换使旧密码和旧 Session 同时失效。新明文密码只保存到可信密码管理器。

## 报告与 PDF 烟雾测试

自动化核心 HTTP 闭环（PDF 成功分支使用受控适配器字节）运行：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m pytest \
  /opt/ai-platform/tests/test_core_journey.py -q
```

原生烟雾测试必须另外完成：使用一次性测试线索完成评估，在同一浏览器 Session
打开在线报告并下载 PDF；新隐私窗口访问相同报告/PDF URL 必须为 404；下载文件
必须以 `%PDF` 开头。随后把 PDF 渲染为页图，人工检查中文字形、分页、雷达图/
分数表、推荐、预算、免责声明，以及没有企业名称、联系人、手机号、邮箱和微信。
原生烟雾失败不删除已生成的在线报告，也不得伪造通过证据。

## 阶段 7 预检与启动顺序

先保持 Nginx 停止，并停止任何旧版应用进程；后续运行时烟雾测试只能命中新启动
的候选版本，不能以旧进程结果作为门禁证据：

```bash
systemctl stop nginx
systemctl stop ai-platform
test "$(systemctl is-active nginx)" = inactive
test "$(systemctl is-active ai-platform)" = inactive
```

发布代码后、应用仍停止时，在 `/opt/ai-platform` 完成离线门禁：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m pip check
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m py_compile \
  app.py security.py assessment_repository.py lead_repository.py \
  appointment_repository.py assessment_completion_service.py
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m pytest -q
sudo -u ai-platform /opt/ai-platform/.venv/bin/python -m weasyprint --info
systemd-analyze verify /etc/systemd/system/ai-platform.service
```

离线门禁、数据库备份和恢复副本迁移全部通过后，先启动新应用，立即验证它的
systemd 状态、loopback 健康状态和监听边界：

```bash
systemctl start ai-platform
systemctl is-active ai-platform
curl --fail http://127.0.0.1:5080/health
ss -ltnp | grep '127.0.0.1:5080'
```

上述命令必须命中新启动的候选版本。随后在 Nginx 仍停止的前提下完成管理员、
隐私配置、完整评估、HTML/PDF、Session 隔离、预约与后台关联的运行时烟雾测试。
任何一项失败都先停止 `ai-platform` 并执行回滚，不能启动 Nginx。

只有以下检查全部通过后才允许测试并启动 Nginx：

1. `systemctl is-active ai-platform` 返回 `active`。
2. `curl --fail http://127.0.0.1:5080/health` 返回 `{"status":"ok"}`。
3. 5080 只监听 `127.0.0.1`。
4. 未配置后台安全环境时 `/admin/login` 为 503；配置后新密码可登录和退出。
5. 三个隐私环境键可用，公开配置展示真实处理者、联系渠道和政策 URL。
6. 全量测试、安全扫描、数据库备份、恢复副本迁移和回滚命令演练通过。
7. HTML 报告、原生 PDF、Session 隔离、预约和后台关联烟雾测试通过。
8. 保留清理仍为 dry-run，或 `--apply` 已有单独备份、批准和复核记录。

全部运行时门禁通过后执行 `nginx -t`；最后只能在阶段 7 明确批准后执行
`systemctl start nginx`。应用不得在此处再次重启，否则必须重新执行全部运行时
烟雾测试。在此之前 Nginx 始终保持停止。生产操作和浏览器/PDF 证据均不由当前
本地任务代执行。
