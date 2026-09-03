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
- 规范 URL 只来自经验证的 `AI_PLATFORM_PUBLIC_BASE_URL`；生产媒体根固定为
  `/opt/ai-platform/data/media`，二者都不能回退到请求头或临时目录。
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

八个生产键必须全部存在且非空：

```text
AI_PLATFORM_SECRET_KEY=<随机 Session 密钥>
AI_PLATFORM_ADMIN_USERNAME=<共享管理员用户名>
AI_PLATFORM_ADMIN_PASSWORD_HASH=<Werkzeug scrypt 哈希>
AI_PLATFORM_PRIVACY_PROCESSOR_NAME=<个人信息处理者全称>
AI_PLATFORM_PRIVACY_CONTACT=<隐私请求联系渠道>
AI_PLATFORM_PRIVACY_POLICY_URL=https://<正式域名>/privacy
AI_PLATFORM_PUBLIC_BASE_URL=https://<正式规范域名>
AI_PLATFORM_MEDIA_ROOT=/opt/ai-platform/data/media
```

`AI_PLATFORM_PUBLIC_BASE_URL` 必须是一个字面 HTTPS origin：不得带路径、query、
fragment、userinfo 或非规范端口，也不得由 `Host`/`X-Forwarded-Host` 推断。
`AI_PLATFORM_MEDIA_ROOT` 在生产 WSGI 中必须等于或位于
`/opt/ai-platform/data/media` 之下；本部署固定使用该目录本身。

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
install -d -m 0750 -o ai-platform -g ai-platform /opt/ai-platform/data/media
chown -R root:ai-platform /opt/ai-platform
chown -R ai-platform:ai-platform /opt/ai-platform/data
```

生产虚拟环境位于 `/opt/ai-platform/.venv`，由 root 安装锁定依赖，运行用户只有
读取权限。Ubuntu 安装应用测试/备份工具和 WeasyPrint 69 运行库：

```bash
apt-get update
apt-get install -y sqlite3 rsync curl python3-venv \
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
systemctl stop ai-platform
test "$(systemctl is-active ai-platform)" = inactive
```

Nginx 和应用都必须为 `inactive`，这样数据库与媒体不会在成组备份之间变化。
创建 SQLite 一致性备份；不能复制单个 DB 文件来代替 `.backup`：

```bash
install -d -m 0700 /var/backups/ai-platform
BACKUP_FILE="/var/backups/ai-platform/platform-$(date +%Y%m%d-%H%M%S).db"
sqlite3 /opt/ai-platform/data/platform.db ".backup '$BACKUP_FILE'"
chmod 0600 "$BACKUP_FILE"
sqlite3 "$BACKUP_FILE" 'PRAGMA integrity_check;'
sha256sum "$BACKUP_FILE"
```

`PRAGMA integrity_check` 必须只输出 `ok`。再把备份恢复到隔离目录并对恢复副本
执行迁移，不能用生产 DB 做“演练”。同一维护窗口还要保存媒体树；媒体归档和
数据库备份必须作为一组记录，不能只备份其中一个：

```bash
MEDIA_BACKUP="/var/backups/ai-platform/media-$(date +%Y%m%d-%H%M%S).tar"
tar --create --file "$MEDIA_BACKUP" \
  --directory /opt/ai-platform/data/media .
chmod 0600 "$MEDIA_BACKUP"
tar --list --file "$MEDIA_BACKUP"
sha256sum "$MEDIA_BACKUP"
```

媒体备份不使用 `--remove-files`、`rsync --delete` 或任何清理参数。再在隔离恢复
目录同时恢复数据库和媒体：

```bash
REHEARSAL_DIR="$(mktemp -d /tmp/ai-platform-restore.XXXXXX)"
rsync -a --exclude='.venv/' --exclude='data/' /opt/ai-platform/ "$REHEARSAL_DIR/"
install -d -m 0750 -o ai-platform -g ai-platform "$REHEARSAL_DIR/data"
install -d -m 0750 -o ai-platform -g ai-platform "$REHEARSAL_DIR/data/media"
install -m 0640 -o ai-platform -g ai-platform \
  "$BACKUP_FILE" "$REHEARSAL_DIR/data/platform.db"
tar --extract --file "$MEDIA_BACKUP" \
  --directory "$REHEARSAL_DIR/data/media"
chown -R ai-platform:ai-platform "$REHEARSAL_DIR/data/media"
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  "$REHEARSAL_DIR/manage.py" migrate
sqlite3 "$REHEARSAL_DIR/data/platform.db" \
  'PRAGMA integrity_check; SELECT version FROM schema_migrations ORDER BY version;'
find "$REHEARSAL_DIR/data/media" -type f -printf '%P\n' | LC_ALL=C sort
```

记录两份备份路径/SHA-256、`ok`、迁移版本、恢复后的相对媒体清单和副本统计。
保留恢复目录直至上线
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

## 内容目录、来源与媒体（仅阶段 7）

本节是阶段 7 操作顺序，不授权当前任务执行。先完成代码门禁、数据库/媒体成组
备份和隔离恢复演练，保持 Nginx 与应用停止，再由 `ai-platform` 用户运行迁移：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py migrate

# 默认零写入；先把通用库存输出交给内容负责人核对
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py inventory-content

# 获得逐项人工确认后，才写/更新 review 行
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py inventory-content --record

# 这是显式网络操作；只检查已记录来源并只输出通用状态/code
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py check-content-sources
```

来源检查最多读取 1 MiB，限制 scheme/host/端口/content type/encoding/重定向，
DNS 只接受有界数量的公网地址；连接固定到已验证地址并核对 peer，每次重定向都
重新执行相同策略，拒绝 loopback、私网、link-local、保留、多播、非规范地址和
userinfo。检查 tuple 绑定规范 URL hash，发布时必须为 `https_ok` 且从检查时间
起七天内有效；URL 改动、过期、未来时间或 hash 不同都必须重新检查。不得临时
放宽 SSRF、大小或七天 TTL 门禁。自动化和本地验收只用 mock transport；阶段 7
真实网络检查必须有批准的出站边界和审计记录。

运营人员把严格 JSONL decision 文件放入受限配置目录；文件不得包含私密 query、
响应正文或联系方式。先预览，再对输出中的 target、锁版本、确认项和当前来源
checksum 做人工复核，最后才 apply：

```bash
install -m 0640 -o root -g ai-platform \
  <approved-content-decisions.jsonl> \
  /etc/ai-platform/approved-content-decisions.jsonl
CONTENT_DECISIONS=/etc/ai-platform/approved-content-decisions.jsonl
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py migrate-legacy-content \
  --decisions "$CONTENT_DECISIONS"
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py migrate-legacy-content \
  --decisions "$CONTENT_DECISIONS" --apply
```

`--apply` 仍只创建或显式合并 V2 `draft`。它不发布、不删除或更新旧四表；
`delete_later` 只是人工标签。数据库触发器禁止删除内容组、修订、区块、关系、
媒体和旧内容。媒体“归档”只改变受控状态，不删除文件/行；禁止用 SQL、文件清理
脚本或 `rsync --delete` 绕过。先运行媒体恢复 dry-run：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py recover-media-storage
```

只有逐项核对 finding、成组备份仍有效且明确批准后，才可执行
`recover-media-storage --apply`；它只归档不可恢复的 pending/missing 状态，不删除
文件或数据库行。`/opt/ai-platform/data/media` 及其文件必须保持
`ai-platform:ai-platform` 所有权，目录不得对其他用户开放写权限：

```bash
stat -c '%a %U %G %n' /opt/ai-platform/data/media
find /opt/ai-platform/data/media -xdev -type f \
  ! -user ai-platform -o -type f ! -group ai-platform
```

第二条命令期望无输出。发布候选通过 loopback 健康检查、管理员内容闭环、公开
目录/媒体、Session/PDF 和回滚烟雾测试之后，才允许运行一次到期发布并复核输出：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py publish-due-content
```

仓库当前不提供内容定时器 unit；阶段 7 不得提前编造或启用。未来若另经审查加入
`publish-due-content`、来源复核或媒体恢复 timer，必须先在同一候选上手工运行、
完成上述烟雾测试，再 `enable/start`；任何候选重启都使该烟雾门禁失效，timer 必须
继续停止。`recover-media-storage --apply` 和旧内容 conversion 不得成为无人值守
定时任务。

`fetch-content` 同样不能未经演练直接加入 timer。它只从明确启用且已审核的 HTTPS
来源 allowlist 获取内容并写入私有候选队列，不直接发布；来源 code、host、adapter、
许可依据、robots 决策和正文保留策略必须先有审核记录。候选环境的手工命令、审计
核对、重复运行和失败恢复步骤见
[`docs/testing/content-operations.md`](../testing/content-operations.md)。

Nginx 候选配置必须先把全部动态请求限制为 1 MiB，只给经过认证的媒体上传适配器
精确路径 22 MiB。不能把 22 MiB 放到 `/admin/`、`/media/` 或整个 `server`：

```nginx
server {
    client_max_body_size 1m;

    location = /admin/media {
        client_max_body_size 22m;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:5080;
    }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:5080;
    }
}
```

Nginx 的 `m` 单位按 MiB 计。应用层仍只对已认证的精确 POST endpoint 放行全局
22 MiB transport ceiling，图片/附件验证分别执行更小的内容限制；其他请求即使
绕过 Nginx 也保持 1 MiB。该片段只能合并到阶段 7 候选配置；完成候选烟雾测试后
才运行 `nginx -t`，最终明确批准前仍不得启动 Nginx。

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

运行时烟雾还必须完成内容运营手册中的四份法律文档门禁、规则四行业预览/原子发布、
活动指针与快照健康、同一 Session 新旧 flow、公开服务、历史报告摘要稳定，以及
工作台筛选/公式安全 CSV/审计一致性。已发布规则不得原地回写；回滚只能从经核验的
历史内容复制新草稿并重新预览发布，禁止直接更新活动指针或不可变快照。

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
