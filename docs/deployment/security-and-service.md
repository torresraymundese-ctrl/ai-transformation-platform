# 安全配置与 systemd 部署基线

本文件描述 V2.0 最终上线时的安全配置方式。当前升级期间保持 Nginx 停止，以下命令不在生产服务器执行，直到阶段 7 的备份与回滚检查完成。

## 目标状态

- Gunicorn 只监听 `127.0.0.1:5080`，不能绕过 Nginx 从公网直连。
- 应用由专用的 `ai-platform` 系统用户运行，不再由 root 运行。
- 后台用户名、密码哈希和 Session 密钥来自 `/etc/ai-platform/ai-platform.env`。
- 环境文件权限为 `0600`，源码、提交记录和命令行参数中都不出现可读密码。
- 运行日志进入 journald；SQLite 仅允许写入 `/opt/ai-platform/data`。

## 首次建立安全配置

以 root 登录服务器后创建受限目录：

```bash
install -d -m 0700 -o root -g root /etc/ai-platform
python3 /opt/ai-platform/scripts/configure_security.py \
  --username <new-admin-username> \
  --output /etc/ai-platform/ai-platform.env
```

工具会在终端中隐式询问两次新密码，密码不会进入 shell history。密码至少 14 个字符；文件只保存 Werkzeug scrypt 哈希和随机 Session 密钥。如果目标文件已存在，工具会拒绝覆盖。

检查权限时只查看元数据，不输出文件内容：

```bash
stat -c '%a %U %G %n' /etc/ai-platform/ai-platform.env
```

期望权限为 `600 root root`。

## 服务账号和目录

```bash
useradd --system --home /opt/ai-platform --shell /usr/sbin/nologin ai-platform
install -d -m 0750 -o ai-platform -g ai-platform /opt/ai-platform/data
chown -R root:ai-platform /opt/ai-platform
chown -R ai-platform:ai-platform /opt/ai-platform/data
```

生产虚拟环境位于 `/opt/ai-platform/.venv`，由 root 安装锁定依赖，运行用户仅需读取权限。

## 安装服务单元

```bash
install -m 0644 ops/systemd/ai-platform.service /etc/systemd/system/ai-platform.service
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/ai-platform.service
```

服务单元使用 `EnvironmentFile`，并将 Gunicorn 绑定到 loopback。每次启动 Gunicorn 前，`ExecStartPre` 会运行 `manage.py migrate`，以幂等方式应用尚未执行的数据库迁移。正式启用前必须先完成数据库备份、文件权限验证和本地迁移演练。

可在维护窗口单独演练迁移：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python /opt/ai-platform/manage.py migrate
```

命令成功且备份验证完成后，才允许重启应用服务。

## 凭据轮换

不要覆盖现有文件。先生成一个新文件，验证权限后在维护窗口原子替换：

```bash
python3 /opt/ai-platform/scripts/configure_security.py \
  --username <new-admin-username> \
  --output /etc/ai-platform/ai-platform.env.new
stat -c '%a %U %G %n' /etc/ai-platform/ai-platform.env.new
mv /etc/ai-platform/ai-platform.env.new /etc/ai-platform/ai-platform.env
systemctl restart ai-platform
```

轮换会同时使旧密码和旧 Session 失效。新密码只应保存到可信密码管理器，不在聊天、工单或部署日志中传递。

## 上线门禁

只有以下检查全部通过后才允许启动 Nginx：

1. `systemctl is-active ai-platform` 返回 `active`。
2. `curl --fail http://127.0.0.1:5080/health` 返回 `{"status":"ok"}`。
3. 5080 只监听 `127.0.0.1`。
4. 未配置后台安全环境时 `/admin/login` 返回 503；配置后可用新密码登录并正常退出。
5. 全量测试、安全扫描、数据库备份和回滚演练通过。
