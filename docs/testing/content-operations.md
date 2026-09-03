# 内容运营闭环与恢复手册

## 当前结论与边界

阶段 5 的运营闭环由 `tests/test_operations_journey.py` 通过公开 HTTP 和管理员 HTTP
入口验证；CLI 路径由下方列出的既有测试分区验证。新测试文件的静态守卫禁止
repository 导入、SQLite 执行调用和 SQL 字面量；一次性应用只启用代码为
`task22_reviewed_source` 的测试来源，固定到
`https://task22.test.example/reviewed`，并使用 `text/plain` 的确定性 fake pinned
transport。自动化不访问公网，也不读取生产数据库。

当前实现者验证覆盖候选接入与发布、工作台到筛选及公式安全 CSV、四份法律文档的
版本绑定、规则复制/编辑/四行业预览/原子发布、同一 Session 内的新旧 flow，以及
未授权、CSRF 和无效操作的零可见写入。390px 后台壳结构合同同时保留全部导航标签、
表头、线索筛选和导出入口。控制器又以 `window.innerWidth=390` 独立验证页面
`clientWidth=scrollWidth=375`，筛选与 CSV 下载均实际成功；五张证据图保存在
`docs/testing/evidence/`。这些结果仅证明候选环境中的阶段 5 验收，不代表生产部署批准。

## 阶段 5 证据矩阵

下列浏览器证据全部来自同一个一次性数据库和媒体目录，只启用了经审核的
`task22_reviewed_source`，来源响应由确定性 fake pinned transport 提供；没有访问公网、
生产数据库或真实联系人。桌面证据为 1280×720，移动证据的浏览器视口
`window.innerWidth=390`，页面 `clientWidth=scrollWidth=375`。

| 旅程 | HTTP/合同测试 | 浏览器证据与可见状态 | 结果 |
| --- | --- | --- | --- |
| 候选抓取 → 审核 → 接受为草稿 → 来源检查 → 发布 → 公开资源 | `test_fixed_candidate_is_reviewed_into_a_draft_then_published_publicly` | [operations-ingestion.png](evidence/operations-ingestion.png)：后台显示 TEST ONLY 资源及当前公开修订 | 通过 |
| 工作台卡片 → 同条件列表/队列 → 公式安全 CSV | `test_dashboard_queue_and_filtered_leads_export_the_same_formula_safe_row`：验证新增线索卡片、列表与 CSV 一致，并验证逾期卡片计数和目标队列记录集合一致 | [operations-dashboard.png](evidence/operations-dashboard.png)：从工作台进入“跟进已逾期”队列，共 1 条 TEST ONLY 记录；[operations-mobile.png](evidence/operations-mobile.png)：390px 筛选、导出入口和线索表头保留，页面无横向溢出，CSV 实际下载成功 | 通过 |
| 四份法律文档发布 → 旧 flow → 隐私 v2 → 同 Session 新 flow → 精确版本完成 | `test_same_session_old_and_new_privacy_flows_finish_exact_versions` | [operations-legal.png](evidence/operations-legal.png)：公开 TEST ONLY 隐私 v2；自动化 HTTP 旅程验证新旧 flow 分别保留 v2/v1 精确版本 | 通过 |
| 复制规则 → 编辑 → 四行业预览 → 原子发布 → 新旧快照隔离 | `test_rule_copy_preview_publish_switches_new_flow_and_keeps_old_report` | [operations-rule-release.png](evidence/operations-rule-release.png)：新规则为已发布、旧规则为已归档；自动化 HTTP 旅程验证新 flow/公开服务切换且旧报告摘要稳定 | 通过 |
| 未授权、CSRF、无效动作零可见写入；后台移动壳完整 | `test_unauthorized_csrf_and_invalid_actions_keep_visible_domains_unchanged`、`test_admin_shell_contains_mobile_navigation_tables_and_lead_controls`、`test_operations_journey_source_is_http_only` | 五张证据均使用合成 TEST ONLY 数据；移动截图确认导航、筛选、导出及表格保留，表格仅在自身容器内横向滚动 | 通过 |

## 可复现验证

从项目根目录运行，`--basetemp` 必须是系统临时目录中的全新绝对 ASCII 路径，且
不得指向仓库或真实数据目录：

```powershell
..\..\.venv\Scripts\python.exe -m pytest `
  tests/test_content_journey.py tests/test_operations_journey.py `
  tests/test_ingestion_repository.py tests/test_content_ingestion.py `
  tests/test_operations_pagination.py tests/test_operations_dashboard.py `
  tests/test_lead_export.py tests/test_legal_versions.py `
  tests/test_rule_release_drafts.py tests/test_rule_release_admin.py `
  tests/test_assessment_flows.py tests/test_rule_release_runtime.py `
  -q -p no:cacheprovider --basetemp <系统临时目录中的唯一绝对路径>
```

新旅程文件的最终定向结果为 `7 passed in 11.84s`。上面完整分区的最终精确结果为
`445 passed in 325.08s (0:05:25)`。每次候选构建仍须重新运行
并记录；不能沿用本文计数充当后续发布证据。

## 运营闭环

### 来源、许可与候选队列

- 只把经人工审核的固定 HTTPS 来源加入来源注册表；code、允许的 scheme/host、
  adapter、许可依据、robots 决策和 `retain_body` 都必须明确记录。
- 启用列表必须是明确 allowlist。来源 URL、host、许可或 robots 决策改变后重新
  审核，不能临时打开 checked-in 条目来做测试。
- `fetch-content` 会执行受限来源获取并把候选放入私有审核队列，不会直接发布：

  ```bash
  sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
    /opt/ai-platform/manage.py fetch-content
  ```

- 运营人员在后台检查候选正文摘要、来源和许可，接受动作只能创建草稿；草稿仍需
  走内容审校、来源检查和发布门禁。CLI 输出只保留通用计数及内部 ID，不能输出响应
  正文、私密 query 或联系方式。

### 工作台、筛选和 CSV 审计

从运营工作台卡片进入线索队列后，保留 URL 上的状态、行业、日期、队列和搜索条件。
导出 POST 必须使用页面当前的同一组过滤条件及 CSRF；导出的行集合应与筛选列表
一致。以 `= + - @` 开头或可能被表格软件当作公式的单元格必须保持公式安全转义。

`admin_export_logs`、`admin_audit_logs`、`governance_audit_events` 和
`content_audit_events` 属于审计证据，不得因普通内容归档、线索保留清理或媒体恢复
而删除。备份、导出条件、操作者、结果计数和复核结论应进入受限运维记录；CSV
本身按含个人信息文件管理，不上传到公开媒体目录。

### 四份法律文档门禁

启用任何新评估 flow 前，后台必须分别创建、审校并发布：`privacy`、`terms`、
`roi_disclaimer`、`ai_content_notice`。缺任一份活动且已审核的版本时，配置、预览
或完成都应 fail closed。每个 flow 在签发时绑定四个精确版本；后续发布新隐私版本
不会改写旧 flow 或旧报告。公共法律页保留历史版本可访问性，归档/删除不能绕过
已经持久化的评估绑定。

### 规则版本、预览、发布与回滚

规则变更从当前活动版本复制新草稿；通过 choice-first 管理界面修改后，对四个行业
分支分别执行真实预览，核对分数、场景、ROI、路线图和服务。发布前确认编译摘要；
发布动作在同一事务中保存不可变快照、归档旧活动版本并 CAS 切换活动指针。新 flow
和公开服务读取新活动快照，已签发 flow 与历史报告继续读取原绑定快照。

已发布版本不可原地编辑。需要业务回滚时，从经核验的历史内容复制一个新的草稿，
完成四行业预览并发布这个新版本；禁止用 SQL 直接改活动指针、状态或快照。规则编辑
和发布使用秒级数据库时间戳，自动化连续 POST 必须跨过保存秒再发布；人工操作若收到
409，应重新加载草稿和锁版本核对，不得重复提交旧表单。

### Flow 容量与期限

评估 flow ID 由 192-bit 随机源生成。一个 Session 最多保留 8 个仍有效 flow，只有
成功生成唯一 ID 后才按签发时间驱逐最旧记录；每个 flow 自签发起最多有效 24 小时。
未知、损坏、分支不一致或过期 flow 均使用通用失败响应，不能消耗配额、写评估或在
HTML/日志中泄露内部 flow ID。历史报告访问继续受其原 Session 绑定约束。

## 发布排期和 timer 演练

`publish-due-content` 只原子发布已经到期且仍满足门禁的修订：

```bash
sudo -u ai-platform /opt/ai-platform/.venv/bin/python \
  /opt/ai-platform/manage.py publish-due-content
```

仓库当前没有内容 timer unit。未来若另经审查加入 `fetch-content` 或
`publish-due-content` timer，先在恢复副本/候选应用上以相同运行用户手工执行，核对
通用输出、后台审计、公开结果和重复运行幂等性，再演练 timer；候选代码、配置或数据
重启后重新演练。来源获取需要单独批准的受限出站边界。不得把来源复核、旧内容转换、
媒体恢复 `--apply` 或规则发布做成无人值守任务。

## 备份、恢复和迁移演练

数据库与媒体必须在应用和 Nginx 均停止时成组备份。SQLite 使用 `.backup` 获得一致
副本；媒体目录单独归档并记录相对清单、所有者、权限和 SHA-256。恢复时把两者放进
同一个隔离候选根，媒体目录及文件恢复为 `ai-platform:ai-platform`，目录不得对其他
用户开放写权限。媒体恢复命令先 dry-run；`--apply` 只允许受控状态迁移，不删除文件
或行。完整命令见部署基线的“SQLite 备份、迁移和恢复演练”章节。

迁移不能只从空库验证。对每个受支持的前置版本，使用真实留存在该版本的备份副本，
先核对 `schema_migrations` 连续记录和业务哨兵，再运行 `manage.py migrate` 两次；每次
确认 integrity check、最终迁移集合、活动指针、快照摘要、法律绑定、内容/媒体计数和
哨兵不变。禁止手工改 `schema_migrations` 来伪造旧版本，也禁止拿生产主库演练。

## 活动快照与候选烟雾检查

在隔离恢复副本上，活动规则必须恰好连接一个 `published` 版本及其不可变快照，版本
的 `validated_digest` 必须等于快照 SHA；严格运行时 loader 还会核验字节上限、SHA、
canonical schema 和 release identity。任何失败都阻止配置/公开读取，不能回退到
可变规则表或全局文案。

候选烟雾测试按以下顺序进行：

1. 发布四份 TEST ONLY 法律文档，签发旧 flow。
2. 复制规则，修改一个可见服务字段，对四行业预览并发布。
3. 新 flow 的 `rule_version` 和公开服务显示新活动规则；旧 flow 仍能完成。
4. 新旧报告均可打开，旧报告的 `data-snapshot-sha256` 和 `.report-content` 不变；
   HTML/PDF 都只使用持久化的法律及规则显示副本。
5. 工作台队列、同条件列表和公式安全 CSV 一致，且存在对应导出/治理审计。

任何一项失败都停止候选应用并恢复成组备份。Nginx 在阶段 7 的全部离线门禁、恢复
副本迁移、loopback 运行时烟雾测试和明确批准完成前始终保持停止。
