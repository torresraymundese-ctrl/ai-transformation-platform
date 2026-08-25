# Task 8 实施报告

## 执行边界

- 工作树：`D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report`
- 分支：`codex/ai-platform-2.0-core`
- 冻结基线：`e9087e9abfe0a972c5ef1c7679b05d51cf837f33`
- 开始状态：tracked/untracked clean（`git status --porcelain=v1 --untracked-files=all` 无输出）。
- 全程仅限本地开发与本地演示；不得部署到任何服务器，不得修改服务器、Nginx、systemd 或真实数据库，不得为展示临时开放公网。
- 来源检查仅使用 mock；数据与媒体仅使用临时 SQLite 和隔离媒体根；不真实联网、不安装或升级依赖。
- 不修改冻结迁移 `001`–`008`、plan/spec/brief/progress/Task 7 报告/review 包/外部任务卡。

## 启动核对

- 不可变 brief 已按要求一次性完整读取。
- 绑定规格已读取，重点核对设计原则、case schema、公开/后台、媒体、SEO/安全、失败边界、测试与验收。
- 当前工作树为 linked worktree；HEAD 精确等于冻结基线。

## Schema 裁决记录

- 在任何 production 或 Task 8 测试修改前发现 schema 冲突：冻结迁移 `006_content_catalog.sql` 的 `case_content.basis_type` CHECK 仅允许 `public_source/private_authorization`，`content_validation.py` 同样只接受这两个值；Task 8 冻结 brief 要求 `public_source/client_authorization/internal_delivery_record`。
- 现有列无法无损、结构化地区分 `client_authorization` 与 `internal_delivery_record`；把类型编码进 `private_basis_reference` 会混淆依据类型与私有证据引用。
- 已向 controller 上报；controller 授权方案 A：新增 append-only `009_case_basis_types.sql` 及直接 migration/app-factory tests，绝不修改 `001`–`008`。
- 009 必须完整保留所有列、行、外键语义、validate/protect triggers 与非草稿不可变性；历史 `private_authorization` 原值保留为 storage-only legacy compatibility code，不猜测映射为新类型，发布/公开读取必须 fail closed。
- 新编辑器与 `CASE_BASIS_TYPES` 只接受/创建 `public_source/client_authorization/internal_delivery_record`；两种私有依据都要求 `private_basis_reference`。
- 批准的范围扩展仅限 `migrations/009_case_basis_types.sql` 与直接 migration/app-factory tests，不涉及 Task 9。
- 随后 controller 另行批准修改 `content_validation.py`、`publishing_repository.py` 与直接 tests：Task 3 正式 publish transaction 必须在同一事务加载/验证 case extension、全部 metrics 与 review confirmation；该范围是 brief Step 3 的明示要求，不涉及 Task 9。

## TDD 证据

### Migration RED

- 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_migrations.py::test_009_case_basis_types_apply_on_an_empty_database tests/test_content_migrations.py::test_009_preserves_legacy_case_rows_and_case_integrity_guards tests/test_v2_migrations.py::test_v2_migrations_preserve_legacy_assessment_and_create_core_schema tests/test_app_factory_and_migrations.py::test_database_migrations_are_versioned_idempotent_and_preserve_data -q -p no:cacheprovider --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-red-migration-20260825-001'`
- 结果：exit `1`，`4 failed in 1.17s`。
- 失败摘要：四个节点均观察到最后迁移仍为 `008_service_content_maturity`、缺少预期 `009_case_basis_types`；失败由目标 production migration 缺失导致，不是 harness/fixture/导入错误，属于可接受的真实 RED。

### Migration GREEN

- 第一次实现迭代命令：与 Migration RED 相同四个节点，basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-green-migration-20260825-002`。
- 第一次实现迭代结果：exit `1`，`4 failed in 0.97s`；根因是重建表时仍存在挂在 `content_items` 且引用 `case_content` 的 `validate_content_publication`，SQLite 在 DDL schema 重解析时报告 `no such table: main.case_content`。事务回滚，无部分 migration。
- 修复：009 事务内先删除该外部依赖触发器，完成表重建后按 006 原定义恢复；case 表自身的 validate/protect/delete triggers 同样恢复，并新增 legacy basis 发布拒绝触发器。
- 最终命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_migrations.py::test_009_case_basis_types_apply_on_an_empty_database tests/test_content_migrations.py::test_009_preserves_legacy_case_rows_and_case_integrity_guards tests/test_v2_migrations.py::test_v2_migrations_preserve_legacy_assessment_and_create_core_schema tests/test_app_factory_and_migrations.py::test_database_migrations_are_versioned_idempotent_and_preserve_data -q -p no:cacheprovider --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-green-migration-20260825-003'`
- 最终结果：exit `0`，`4 passed in 0.80s`。

### HTTP RED

- 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_verified_cases.py -q -p no:cacheprovider --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-red-http-20260825-004'`
- 结果：exit `1`，`10 failed in 8.56s`。
- 失败摘要：`/cases` 仍由 `public.cases_page` legacy owner 占用；新 `/admin/cases/new`、编辑与 source-check 路径均为 404，导致 choice-first/admin workflow/public workflow 断言失败。Task 4 媒体上传、PDF 确认与 EXIF 清除准备路径正常运行，证明 fixture/harness 有效；失败由 V2 case HTTP/repository 缺失导致，是可接受的真实 RED。

### Domain RED / GREEN

- RED 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_validation.py::test_case_extension_accepts_only_exact_editable_authenticity_and_basis_codes tests/test_content_validation.py::test_case_extension_rejects_legacy_approximate_and_non_string_codes tests/test_content_publishing.py::test_case_publish_gate_rejects_inconsistent_or_legacy_verification_without_writes -q -p no:cacheprovider --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-red-domain-20260825-005'`
- RED 结果：exit `1`，`9 failed, 4 passed in 6.05s`。新的 exact enum 被旧 validator 拒绝，legacy `private_authorization` 反而被接受，正式 publish gate 也未完整执行 case 语义；是 production 缺失导致的真实 RED。
- GREEN 命令：与上述三个 selector 相同，basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-green-domain-20260825-006`。
- GREEN 结果：exit `0`，`13 passed in 5.96s`。

### HTTP GREEN

- 首次实现迭代命令：与 HTTP RED 相同，basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-green-http-20260825-007`。
- 首次实现迭代结果：exit `1`，`1 failed, 9 passed in 9.18s`。唯一失败是 test 将发布后的 lock version 写死为 2；正式事务是先保存 1→2、再发布 2→3，因此 409 是正确的 optimistic-lock 行为。测试已改为读取当前锁值。
- 最终命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_verified_cases.py -q -p no:cacheprovider --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-green-http-20260825-008'`
- 最终结果：exit `0`，`10 passed in 7.56s`。

## 测试与静态检查

### 计划指定 related

- 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_verified_cases.py tests/test_legacy_content_migration.py tests/test_validation_and_errors.py tests/test_security_gaps.py tests/test_lead_operations.py -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-related-20260825-009' -q`
- 结果：exit `0`，`145 passed in 91.00s (0:01:31)`。

### 受影响分区与终态重跑

- 初跑命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_validation.py tests/test_content_publishing.py tests/test_content_migrations.py tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py tests/test_legacy_content_migration.py tests/test_content_seed.py tests/test_catalog_content_admin.py tests/test_media_service.py tests/test_media_http.py tests/test_public_catalog.py tests/test_public_services.py tests/test_analytics.py tests/test_smoke.py tests/test_assessment_catalog.py -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-impact-20260825-010' -q`
- 初跑结果：exit `1`，`5 failed, 840 passed in 489.26s (0:08:09)`。失败为：schema 精确 trigger 集合未加 009 触发器；3 个旧 test helper 仍创建 legacy/近似 case enum；1 个服务测试仍断言 latest migration 为 008。这一轮不记为 PASS。
- 精确失败节点与 009 preservation 复验：使用 `tests/test_content_migrations.py::test_content_schema_exposes_the_frozen_columns_and_real_foreign_keys tests/test_content_migrations.py::test_009_preserves_legacy_case_rows_and_case_integrity_guards tests/test_catalog_content_admin.py::test_post_persists_the_selected_second_relation_target tests/test_catalog_content_admin.py::test_existing_relation_type_is_rendered_as_an_immutable_field tests/test_public_catalog.py::test_industry_publish_keeps_public_scenario_healthy_after_relation_target_archive tests/test_public_services.py::test_008_migration_allows_exact_service_owner_and_seed_is_explicit`，basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-impact-fixes-20260825-012`，exit `0`，`6 passed in 5.91s`。
- self-review focused 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_verified_cases.py tests/test_content_publishing.py::test_due_case_gate_failure_is_isolated_and_records_no_private_evidence -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-self-review-20260825-013' -q`
- self-review focused 结果：exit `0`，`12 passed in 7.57s`。
- 同一 15 分区终态重跑命令：与初跑命令的 15 个 test file 完全相同，basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-impact-final-20260825-014`。
- 同一 15 分区终态结果：exit `0`，`846 passed in 388.84s (0:06:28)`。旧测试修正仅更新精确新 enum/latest 009/新 trigger contract；legacy 原值保留、新编辑拒绝 legacy、publish/public fail closed 保护未削弱。
- analytics JS runtime pytest：`...python.exe -m pytest tests/test_analytics_js_runtime.py -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-analytics-js-20260825-015' -q`；exit `0`，`1 passed in 0.42s`。

### Static / guard

- `...python.exe -m py_compile` 覆盖全部变更 Python 文件：exit `0`，无输出。
- Jinja `Environment(FileSystemLoader('templates'), StrictUndefined)` 解析 `cases.html`、`case_detail.html`、`admin/case_list_v2.html`、`admin/case_edit_v2.html`、`components/admin_navigation.html`：exit `0`，`5 templates parsed`。
- `node --check static/js/content_editor.js`：exit `0`，无输出。
- `node --test tests/js/content_editor_runtime.test.js`：exit `0`，`8 passed, 0 failed`。
- `node --test tests/js/analytics_runtime.test.js`：exit `0`，`3 passed, 0 failed`。
- Blueprint SQL guard：对 `blueprints/admin/cases.py` 与 `blueprints/public_catalog.py` 搜索 `SELECT|INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK|PRAGMA`：exit `0`，`Blueprint SQL guard passed`。
- route owner guard：构建 Flask app 后断言 `/cases` 只有 `public_catalog.cases_page`、`/admin/cases` 只有 `admin.admin_cases_v2`：exit `0`，输出 `public_catalog.cases_page admin.admin_cases_v2`。
- public private-field guard：公开 case templates 搜索 private basis/internal codes/reviewer/contact/phone/wechat：exit `0`，`Public private-field guard passed`。
- `git diff --check`：exit `0`；仅 Git 的 LF→CRLF 工作树提示，无 whitespace error。

## Self-review

- 要求符合性：复核 V2-only owner cutover、真实性/basis/review/verified time、指标周期/证据、7 日来源时效、媒体/隐私人工确认、future/archive/legacy 404、空列表、SEO canonical 与私有数据不出公开 projection。
- 代码质量：SQL/事务仅在 repository/service；Blueprint 仅做严格 HTTP 字段适配；不使用 broad catch 吞并公开错误。
- self-review 修复：archive path/content identity 强绑定；同一请求只取一次服务器时间；公开来源使用规格精确标签“真实公开案例”；新增 case due-batch gate 失败隔离及安全 audit 覆盖。

## 变更文件

- `.superpowers/sdd/2026-08-24-content-catalog-publishing/task-8-report.md`（gitignored，仅执行证据；不提交）
- `blueprints/admin/__init__.py`
- `blueprints/admin/cases.py`
- `blueprints/admin/content.py`
- `blueprints/public.py`
- `blueprints/public_catalog.py`
- `case_repository.py`
- `content_validation.py`
- `publishing_repository.py`
- `migrations/009_case_basis_types.sql`
- `templates/admin/case_edit_v2.html`
- `templates/admin/case_list_v2.html`
- `templates/case_detail.html`
- `templates/cases.html`
- `templates/components/admin_navigation.html`
- `tests/test_app_factory_and_migrations.py`
- `tests/test_catalog_content_admin.py`
- `tests/test_content_migrations.py`
- `tests/test_content_publishing.py`
- `tests/test_content_validation.py`
- `tests/test_public_catalog.py`
- `tests/test_public_services.py`
- `tests/test_v2_migrations.py`
- `tests/test_verified_cases.py`

## 已知限制

- 历史 `private_authorization` 只能原值保留，不能推断为两种新私有依据之一；它必须保持不可发布，等待人工建立符合新枚举的修订。
- 公开来源案例的 7 日核验时效同样在公开读取时 fail closed；超时后需通过新草稿修订重新核验后发布。
- 仍受全局门禁约束：本任务只能本地开发/本地演示，不得部署、改服务器/Nginx/systemd/真实 DB 或开放公网。

## 唯一 full suite

- 代码冻结之前从未运行 full。
- 唯一一次命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; New-Item -ItemType Directory -Force -Path 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp' | Out-Null; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp\task8-final-full-20260825-016' -q`
- 终态：exit `0`，`1222 passed in 590.71s (0:09:50)`。
- 确认恰好运行一次无 selector full suite；没有第二次 full。

## 清理与提交

- basetemp 清理前使用 `Resolve-Path -LiteralPath` 分别解析工作树与 `.test-tmp`，并使用 ordinal-ignore-case prefix 检查确认目标精确位于工作树内。
- 已验证路径：`D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.test-tmp`；顶层 basetemp 数 `15`；仅对该精确 `-LiteralPath` 执行递归清理，exit `0`，`Test basetemps removed`。
- 提交前 `git diff --cached --check`：exit `0`，无 whitespace error。
- 提交：`550ed59b328ef0dad2ea3dc2090c017b6d06dbeb` (`feat: publish verified cases`)，23 个文件，`2096 insertions(+), 120 deletions(-)`。
- report/brief/ledger/review artifacts 未进入提交。
- 提交后 `git status --porcelain=v1 --untracked-files=all`：exit `0`，无输出（tracked/untracked clean，gitignored report 保留）。

## Fix round 1 — internal review corrections

### 边界与审查输入

- Fix1 从 clean HEAD `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb` 开始，仅修复独立审查确认的六个边界：领域 PII、私有依据引用、service 关联 case 完整性、GET/显式 POST copy、SQLite 公开读快照、metric NUL，以及直接相关的原子性/通用失败信息要求。未扩大到 Task 9。
- 重读不可变 brief 中 Task 8 的真实性、7 日来源、公开/后台、隐私、媒体、发布原子性与失败边界，并重读本报告的初始实现证据。
- 全程仅本地 mock/临时 SQLite；不联网、不部署、不修改服务器/Nginx/systemd/真实数据库，不开放公网。
- Fix1 早期一度使用了仓库根 `.test-tmp`；该路径的结果已全部废弃、不作为任何 RED/GREEN 证据。经绝对路径核对后删除该临时目录；以下 Fix1 pytest 证据全部使用 `.superpowers/sdd/2026-08-24-content-catalog-publishing/test-tmp/...` 下的唯一 basetemp。
- 所有 pytest 的共同精确前缀：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --basetemp='<下列绝对路径>'`。

### 合规 accepted RED

- Domain RED：共同前缀 + basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task8-fix1-accepted-red-domain-015` + `tests/test_content_validation.py tests/test_content_publishing.py -k "case_metric_text_rejects or private_case_basis or case_domain_validation_rejects or direct_case_create_and_save or direct_private_basis_reference or raw_invalid_case_revision or due_case_source_freshness"`；exit `1`，`35 failed, 2 passed, 149 deselected`。失败由领域层缺少 PII、private reference 与 metric NUL 保护，以及正式/到期发布未重检持久数据导致；非 harness 失败。
- Migration RED：共同前缀 + basetemp `...\test-tmp\task8-fix1-accepted-red-migration-016` + `tests/test_content_migrations.py -k "009_case_basis_types_apply or 009_preserves_legacy"`；exit `1`，`1 failed, 1 passed, 42 deselected`。失败由 009 对新私有 basis reference 的结构化约束不足导致。
- HTTP/snapshot RED：共同前缀 + basetemp `...\test-tmp\task8-fix1-accepted-red-http-snapshot-017` + `tests/test_verified_cases.py -k "immutable_case_get or archived_case_get or case_copy_post or existing_draft_without_writing or http_rejects_invalid_private or http_strips_private or raw_published_case_metric_nul or reads_one_wal_snapshot"`；exit `1`，`11 failed, 1 passed, 11 deselected`。失败由 GET 暗中复制、缺少显式 copy POST、公开读无单一快照与原始异常 metric 未 fail closed 导致。
- Service relation RED：共同前缀 + basetemp `...\test-tmp\task8-fix1-accepted-red-service-018` + `tests/test_public_services.py -k "persisted_legacy_case_relation or related_public_source_uses or immediate_relation_publish_rechecks or due_relation_publish_rechecks"`；exit `1`，`4 failed, 2 passed, 48 deselected`。失败由 service 公开 projection/正式发布仅看 case status/time，没有共享完整性门禁导致。

### 最小 GREEN 与自审补充 TDD

- 与上述四组 RED 完全相同 selector，分别使用 basetemp `task8-fix1-green-domain-019`、`task8-fix1-green-migration-020`、`task8-fix1-green-http-snapshot-021`、`task8-fix1-green-service-022`；结果依次为 exit `0` / `37 passed, 149 deselected`，exit `0` / `2 passed, 42 deselected`，exit `0` / `12 passed, 11 deselected`，exit `0` / `6 passed, 48 deselected`。
- 自审 RED 1：basetemp `...\test-tmp\task8-fix1-selfreview-red-026`，节点 `tests/test_content_validation.py::test_case_domain_pii_guard_cannot_be_bypassed_by_a_draft_subclass tests/test_content_publishing.py::test_copy_revision_rejects_boolean_expected_lock_without_writing tests/test_verified_cases.py::test_failed_source_check_keeps_response_and_audits_generic`；exit `1`，`1 failed, 2 passed`。唯一真实 RED 是 `ContentDraft` 子类可绕过 PII predicate；来源失败 query 保密已是 GREEN；布尔 lock 节点因 immutable source lock 已大于 1 而未建立所需边界，不计作 lock RED。
- 自审 RED 2：将 lock 节点纠正为数值相同的 `int` 子类；basetemp `...\test-tmp\task8-fix1-selfreview-red-lock-027`，节点 `tests/test_content_publishing.py::test_copy_revision_rejects_non_exact_integer_expected_lock_without_writing`；exit `1`，`1 failed`，证明非精确整数可被当成 lock 匹配。
- 上述两个产品缺口的 GREEN：basetemp `...\test-tmp\task8-fix1-selfreview-green-028`，子类 PII、精确 lock、来源失败保密三节点；exit `0`，`3 passed`。
- 自审 Migration RED：basetemp `...\test-tmp\task8-fix1-selfreview-red-migration-whitespace-029`，节点 `tests/test_content_migrations.py::test_009_case_basis_types_apply_on_an_empty_database`；exit `1`，`1 failed`；纯 tab/newline、Unicode whitespace 以及 Unicode 首尾空白可绕过 SQLite 默认 `trim`。
- Migration GREEN：009 仅对两个新私有 basis 使用与 Python `str.strip()` 对齐的 ASCII/Unicode whitespace 集合，仍对 `private_authorization` 保留任意历史 reference；basetemp `...\test-tmp\task8-fix1-selfreview-green-migration-whitespace-030`，节点 `test_009_case_basis_types_apply_on_an_empty_database` + `test_009_preserves_legacy_case_rows_and_case_integrity_guards`；exit `0`，`2 passed`。迁移运行器只记录 version、无 checksum；由于 009 尚未进入已完成阶段且全局禁止部署，本轮按 controller 授权收紧最终 009，未创建 010，从未触及真实 DB。
- 扩展回归初跑 `task8-fix1-expanded-regressions-031` 为 exit `1` / `2 failed, 48 passed`，原因是收紧后的 009 CHECK 正确拒绝 test 的原始腐化写入，非产品回归，不计 GREEN。经将该节点明确改为 `PRAGMA ignore_check_constraints` 的历史异常行注入，`task8-fix1-expanded-regressions-green-032` exit `0`，`50 passed`。
- Service 扩展回归 `033/034` 的失败分别是 test slug 中误用下划线，以及在 schedule 之前就把 target 腐化为 legacy 导致 schedule 门禁预期拒绝；两者都是 fixture/scenario 编排问题，不冒充 RED。纠正为合法 slug，并在成功 schedule 后腐化 target；`task8-fix1-service-parity-expanded-final-035` exit `0`，`8 passed`。

### 终态 focused / affected partitions

- 最终 case/validation：basetemp `...\test-tmp\task8-fix1-final-focused-case-validation-036`，命令尾 `tests/test_verified_cases.py tests/test_content_validation.py`；exit `0`，`162 passed in 16.47s`。
- 最终 publishing/service：basetemp `...\test-tmp\task8-fix1-final-focused-publishing-services-037`，命令尾 `tests/test_content_publishing.py tests/test_public_services.py`；exit `0`，`137 passed in 87.57s`。
- 最终剩余 affected partitions：basetemp `...\test-tmp\task8-fix1-final-affected-partitions-038`，命令尾 `tests/test_public_catalog.py tests/test_content_migrations.py tests/test_app_factory_and_migrations.py tests/test_security_gaps.py tests/test_legacy_content_migration.py tests/test_smoke.py`；exit `0`，`394 passed in 216.28s`。
- route owner 精确门禁：basetemp `...\test-tmp\task8-fix1-route-owner-040`，节点 `tests/test_verified_cases.py::test_case_cutover_has_single_v2_owner_and_an_honest_empty_state`；exit `0`，`1 passed in 0.80s`。

### 终态静态门禁

- `...python.exe -m py_compile` 覆盖 6 个变更 production Python 文件和 5 个变更 test Python 文件，`PYTHONPYCACHEPREFIX` 指向合规 SDD test temp；exit `0`，无输出。
- Jinja `Environment(FileSystemLoader('templates'), StrictUndefined)` 解析 `admin/case_edit_v2.html`、`cases.html`、`case_detail.html`；exit `0`，`3 templates parsed`。
- Blueprint SQL guard：`rg -n -i '\b(SELECT|INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK|PRAGMA)\b' blueprints/admin/cases.py`，以无匹配为通过；guard exit `0`，`Blueprint SQL guard passed`。
- Public private-field guard：对公开 case templates/public Blueprint 搜索 legacy/新私有 basis code、`private_basis_reference`、reviewer/contact/phone/wechat，无匹配；guard exit `0`。`PublicCase` dataclass 字段与禁止集合无交集；exit `0`，`PublicCase projection private-field guard passed`。
- 冻结迁移 guard：`git diff --exit-code 550ed59... -- migrations/001_initial.sql ... migrations/008_service_content_maturity.sql`；exit `0`，`Frozen migrations 001-008 unchanged`。
- `git diff --check`：exit `0`；仅 Git LF→CRLF 提示，无 whitespace error。
- Fix1 未变更 JavaScript，因此 Node 静态/runtime 检查不适用；未以此替代任何 Python/HTTP 证据。

### 需求/安全/事务/测试质量自审

- PII predicate 现在位于无 HTTP 依赖的 domain validator，扫描校验/清洗后的 title/summary/SEO、可见 block title/body/settings 和六个 metric 文本槽；create/save 阻止新数据，immediate/due/public projection 重检持久数据。错误与 audit 不携带被拒值；自动形状检测仍明确不是匿名证明。
- 两个新私有 basis 的 reference 在 HTTP/domain 中使用精确 `str`、NUL-free、strip 后非空且 <=300；009 同步阻止 ASCII/Unicode 首尾/纯空白与 NUL。`private_authorization` 仅 storage compatibility，不被猜测映射，新编辑/发布/公开读 fail closed。
- 六个 metric 槽均为精确 `str`、strip 后非空、NUL-free 且保留已有长度上限；原始异常持久值在公开面 fail closed。
- `validate_case_public_completeness` 是 formal relation publication 和 service 公开 projection 共用的单一完整性入口，覆盖真实性、精确 basis/reference、review/verified time、metrics、PII、media 与 7 日来源；resource 语义未改。
- GET 只读查找已有 draft；没有 draft 时渲染 immutable source 和 CSRF POST copy。copy 在 `BEGIN IMMEDIATE` 事务内精确绑定 entry type/lock，并由唯一 draft 约束及 repository 的通用 conflict 映射保证重复/并发原子性；Blueprint 无 SQL。
- `public_cases`/`public_case` 在第一个 SELECT 前 `BEGIN` 延迟读事务，列表、直接 slug、alias 都使用同一时刻与同一 SQLite 快照，`finally` rollback/close，不获取 write lock。
- 同组替换的 PII/reference/metric/source/relation 失败均回滚，旧公开修订仍在线，无 `content_published` 成功 audit；due 批次按项隔离，安全 audit 仅含 `validation_failed`。来源检查失败的 HTTP/audit 仅有通用结果类别，不含 URL query。
- 测试不使用真实外网；来源仅 mock，快照回归使用两个真实 SQLite WAL connection。需要注入旧/异常行时明确撤销 protect trigger 或临时忽略 CHECK，并立即恢复，没有削弱正常 schema 保护的断言。

### Fix1 变更文件与已知限制

- Production：`blueprints/admin/cases.py`、`case_repository.py`、`catalog_content_repository.py`、`content_validation.py`、`migrations/009_case_basis_types.sql`、`publishing_repository.py`、`publishing_service.py`、`templates/admin/case_edit_v2.html`。
- Tests：`tests/test_content_migrations.py`、`tests/test_content_publishing.py`、`tests/test_content_validation.py`、`tests/test_public_services.py`、`tests/test_verified_cases.py`。
- 限制不变：historical `private_authorization` 只保留原值且不可公开；7 日来源过期后公开读会 fail closed，需新修订重新检查/发布。本轮不处理 Task 9/resource 语义。
- 全局门禁不变：仅限本地开发/演示，不得部署、改服务器/Nginx/systemd/真实 DB 或开放公网。

### Full suite 覆盖声明

- Fix1 **没有运行任何 full suite**，也不会对后续 Fix1 commit 声称 full 覆盖。
- 本报告上方记录的唯一 full `1222 passed in 590.71s`只覆盖 commit `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb`；该结果已冻结，不覆盖 Fix1 变更。

### Fix1 临时产物清理

- 清理前使用 `Resolve-Path -LiteralPath` 解析工作树与 `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp`，同时校验精确相等与 ordinal-ignore-case worktree prefix；顶层条目数 `26`。
- 仅对上述经验证的精确 `-LiteralPath` 执行递归清理；exit `0`，`REMOVED=True`。仓库根 `.test-tmp` 与 SDD `test-tmp` 均不存在。

### Fix1 提交

- 提交前 `git diff --cached --check`：exit `0`，无输出。精确暂存 13 个上述 production/test 文件；report/brief/ledger/review/task card 均未暂存。
- 提交：`182987c` (`fix: harden verified case boundaries`)，`13 files changed, 1277 insertions(+), 88 deletions(-)`。
- 提交后 HEAD：`182987c5c959ffe0711a83be46e5b5f3c54242a9`，直接父提交为 Fix1 基线 `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb`。`git status --porcelain=v1 --untracked-files=all` exit `0`且无输出；tracked/untracked clean，gitignored report 保留。

## Fix round 2 — visible-text PII

### 边界与根因

- Fix2 从 clean HEAD `182987c5c959ffe0711a83be46e5b5f3c54242a9` 开始，仅修复 fresh review 的唯一 P1：sanitize 后的 `block.body_html` 仍按 HTML 源字符串执行 PII regex，未按浏览器最终可见文本检查。
- 根因定位：`owner&#64;example.com` 在浏览器中解码为 email；`138<strong>0013</strong>8000` 和 `微<strong>信</strong>` 的 data nodes 在渲染时连续显示，但原 regex 被 entity/tag 打断。反向地，原扫描会把允许的 `href`/`title` 属性误当可见正文。
- 本轮只使用本地临时 SQLite，未联网、未部署、未访问真实 DB/服务器/Nginx/systemd/公网；Task 9/resource 语义保持冻结。
- 所有 pytest 使用固定 venv、离线 `PYTHONPATH`、`-p no:cacheprovider` 和 `.superpowers/sdd/2026-08-24-content-catalog-publishing/test-tmp/` 下的全新唯一绝对 basetemp。

### Accepted RED

- 命令：`$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task8-fix2-accepted-red-visible-pii-041' tests/test_content_validation.py::test_case_domain_rejects_pii_in_final_visible_block_text tests/test_content_publishing.py::test_direct_case_create_and_save_reject_visible_html_pii_without_residue tests/test_content_publishing.py::test_visible_html_pii_cannot_replace_the_current_public_case tests/test_content_publishing.py::test_due_visible_html_pii_failure_is_isolated_and_keeps_old_case_online tests/test_verified_cases.py::test_raw_published_visible_html_pii_fails_closed_on_list_and_detail`。
- 结果：exit `1`，`15 failed in 8.02s`。domain/direct create+save/immediate replacement/due isolation/raw persisted published list+detail 的 entity email、allowed-inline-tag phone、tag-split WeChat 全部因未提取最终可见文本而失败；无 import/fixture/harness 错误，是可接受真实 RED。
- 隐藏属性 RED：同一固定命令前缀，basetemp `...\test-tmp\task8-fix2-accepted-red-hidden-attribute-042`，节点 `tests/test_content_validation.py::test_case_domain_visible_pii_scan_ignores_allowed_hidden_attributes`；exit `1`，`1 failed in 0.25s`。允许的 `mailto:owner@example.com`/`title="微信"` 虽不是可见正文，仍被旧源字符串扫描误拒；为真实 RED。

### 最小 GREEN

- 仅在 `content_validation.py` 使用标准库 `HTMLParser(convert_charrefs=True)` 从 **已 sanitize** 的 `body_html` 收集 data nodes，解码 character references，无分隔拼接跨允许标签文本，然后使用既有固定 email/phone/WeChat regex。属性/注释不进入正文。顶层文本与 block settings 的精确语义未改。
- GREEN 初跑：basetemp `...\test-tmp\task8-fix2-green-visible-pii-043`，exit `1`，`3 failed, 13 passed`。三个 due 节点的产品断言已全部通过，但随后执行到误插入的 Fix1 direct-save 断言尾段，触发 `NameError: invalid is not defined`。该结果不计 GREEN；定位为 test 插入位置错误，非产品失败。
- 修正：把 Fix1 原有 direct-save 断言完整恢复到原 test，并从 due test 删除误落尾段；未削弱 Fix1 保护。同一 16 个节点使用新 basetemp `...\test-tmp\task8-fix2-green-visible-pii-final-044`；exit `0`，`16 passed in 7.45s`。

### Focused / affected 验证

- 直接相关完整文件：basetemp `...\test-tmp\task8-fix2-focused-files-045`，`tests/test_content_validation.py tests/test_content_publishing.py tests/test_verified_cases.py`；exit `0`，`259 passed in 67.97s`。
- 公开关联/安全/迁移兼容/smoke 分区：basetemp `...\test-tmp\task8-fix2-affected-partitions-046`，`tests/test_public_services.py tests/test_public_catalog.py tests/test_security_gaps.py tests/test_legacy_content_migration.py tests/test_smoke.py`；exit `0`，`398 passed in 203.60s`。
- route owner guard：basetemp `...\test-tmp\task8-fix2-route-owner-048`，`tests/test_verified_cases.py::test_case_cutover_has_single_v2_owner_and_an_honest_empty_state`；exit `0`，`1 passed in 0.74s`。

### 静态/安全门禁与自审

- `...python.exe -m py_compile content_validation.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_verified_cases.py`，`PYTHONPYCACHEPREFIX` 位于合规 SDD test temp；exit `0`，无输出。
- Jinja `StrictUndefined` 解析 `cases.html`、`case_detail.html`、`components/content_blocks.html`；exit `0`，`3 public case templates parsed`。
- Blueprint SQL guard 搜索 `SELECT|INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK|PRAGMA`；exit `0`，`Blueprint SQL guard passed`。
- 公开 template/public Blueprint 搜索 private/legacy basis、reviewer/contact/phone/wechat 等禁止字段；exit `0`，`Public private-field guard passed`。
- 安全自审：entity 解码和跨 inline tag 拼接后仅返回 `obvious_pii_detected`；direct/immediate 失败不写 item/block/成功 audit，due audit 只有 `validation_failed`；被拒 HTML 不进入 error/audit/response。已发布原始异常行在 list/detail 均 fail closed。
- 事务自审：即时 replacement 失败时旧修订仍 `published` 且公开可读，新 draft item/lock 不变，无成功 publish audit；due 单项失败不阻断合法项。
- 测试质量自审：全部断言经过真实 domain/service/HTTP/public repository 路径；没有 mock 提取器，raw published 测试仅为注入历史异常行临时撤销并恢复 protect trigger。反向回归确认允许属性不会被当可见 PII。

### Fix2 文件范围、full 与限制

- Production：`content_validation.py`。
- Tests：`tests/test_content_validation.py`、`tests/test_content_publishing.py`、`tests/test_verified_cases.py`。
- Fix2 **未运行 full suite**。唯一旧 full `1222 passed in 590.71s` 仍只覆盖 `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb`，不覆盖 Fix1/Fix2 提交。
- 已知限制不变：obvious-contact regex 只是辅助门禁，不是匿名证明；Task 9/resource 语义继续冻结；仅限本地开发/演示，不得部署、联网、改服务器/Nginx/systemd/真实 DB 或开放公网。

### Fix2 HTTP 保密补测与最终复核

- 为直接证明固定失败响应不泄露被拒正文，新增正式 HTTP create 回归，逐项覆盖 entity email、跨允许 inline tag 的 phone、tag-split WeChat；断言固定 `{"error":"obvious_pii_detected"}`、无 case/item 残留、无 `content_created` 成功 audit，且 response/admin request audit 不含原 HTML。
- 该补测前两次运行不作为产品证据：basetemp `...\test-tmp\task8-fix2-http-no-leak-049` 为 exit `1` / `3 failed`，产品边界断言已通过，但测试错误假定 seed 的全局 `content_created` 计数为零；修正为相对基线时，变量误插入相邻 test，basetemp `...\test-tmp\task8-fix2-http-no-leak-final-050` 为 exit `1` / `3 failed`（`NameError`）。两次均为明确 harness/fixture 错误，未冒充 RED/GREEN。
- 最终 HTTP 节点：固定 pytest 前缀 + basetemp `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task8-fix2-http-no-leak-final-051` + `tests/test_verified_cases.py::test_case_http_visible_html_pii_failure_is_fixed_and_does_not_leak`；exit `0`，`3 passed in 1.92s`。
- 最终 `tests/test_verified_cases.py` 全文件复跑：固定 pytest 前缀 + basetemp `...\test-tmp\task8-fix2-verified-final-052`；exit `0`，`30 passed in 17.87s`。该文件包含 route owner、HTTP、raw persisted list/detail fail-closed 等保护。
- 最终 py_compile（production + 三个 test 文件，pycache `...\test-tmp\task8-fix2-pycache-final-053`）：exit `0`，无输出。Jinja StrictUndefined 最终解析三个公开 case templates：exit `0`，`3 public case templates parsed`。
- Blueprint SQL guard 最终 exit `0`，`Blueprint SQL guard passed`；公开 templates/public Blueprint 的 private-field guard 最终 exit `0`，`Public private-field guard passed`。曾有一次误把内部 repository 纳入 private-field grep，命中其合法私有存储字段并 exit `1`；纠正为规定的公开投影范围后通过，不作为产品失败。
- PII implementation guard 确认 `HTMLParser`、`convert_charrefs=True` 与 `body_html -> _visible_html_text` 调用均存在；`git diff --check` 最终 exit `0`，只有 Git LF→CRLF 提示，无 whitespace error。
- Fix2 self-review 终态：只改一个 domain 可见文本提取点；不扫描隐藏属性；不改变顶层/settings、Task 9/resource 或 schema/API；异常仍为固定 code。最终测试与静态复核均未运行 full；唯一旧 full 仍只覆盖 `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb`。
- 临时产物清理：先将 SDD `test-tmp` 与 worktree 分别解析为绝对路径，校验目标等于预期路径且位于 worktree prefix 内；顶层条目数 `12`。仅对该精确 `-LiteralPath` 递归删除，exit `0`，`Removed: True`。
- 提交前 `git diff --cached --check`：exit `0`，无 whitespace error；仅暂存四个 Fix2 production/test 文件。提交：`0a2fc11` (`fix: scan visible case content for pii`)，`4 files changed, 315 insertions(+), 2 deletions(-)`；report/brief/ledger/review/task card 未提交。
- 提交后 HEAD `0a2fc11a7c013011c63b4027c37b176447905e0f`，父提交精确为 Fix2 基线 `182987c5c959ffe0711a83be46e5b5f3c54242a9`；`git status --porcelain=v1 --untracked-files=all` exit `0`、无输出，root `.test-tmp` 与 SDD `test-tmp` 均不存在。

## Fix2 fresh internal review CLEAN

- 第二名全新只读 reviewer 对 `e9087e9abfe0a972c5ef1c7679b05d51cf837f33..0a2fc11a7c013011c63b4027c37b176447905e0f` 的完整净差异判定 `CLEAN`：A—F 全部 ADDRESSED，最终可见文本/entity/跨标签/隐藏属性边界闭合，无新 P0—P3。
- Reviewer 独立匹配 3 commits、25 files/headers、191562 bytes、4736 PowerShell text lines、包 SHA-256 `26A93C781995AC29C9CEE54522AD95CC72641967F71E3163A8652A08BAD1F14C`、reverse apply、clean status、001—008 冻结和任务卡哈希；全程只读，未运行测试/full/网络。
- Reviewer 结论后，控制器使用新 basetemp `task8-controller-fix2-post-review-002` 重跑 Fix2 七组精确 selector：exit `0`，`19 passed, 243 deselected in 8.58s`。随后安全清理 basetemp；`content_validation.py` py_compile、完整净范围 `git diff --check`、审查包 SHA-256/reverse apply 和 tracked/untracked clean 均 exit `0`。
- 证据边界保持：Fix1/Fix2 未运行 full；唯一 `1222 passed` 只覆盖 `550ed59`。当前仅进入外部审查门禁，Task 9 与部署继续冻结。

## 外部独立审查 CLEAN

- “审查企业AI转型平台”对最终净范围 `e9087e9abfe0a972c5ef1c7679b05d51cf837f33..0a2fc11a7c013011c63b4027c37b176447905e0f` 完成 fresh scoped review，独立核对分支/HEAD、3 commits、25 files/headers、审查包 SHA-256 `26A93C781995AC29C9CEE54522AD95CC72641967F71E3163A8652A08BAD1F14C`、reverse apply、001—008 零净差异、任务卡哈希与 clean status；未发现 P0—P3。
- 外部 reviewer 新鲜运行定向责任集，结果 exit `0`，`70 passed in 39.82s`；另行完成变更 Python 编译、4 个 Jinja 模板解析、冻结迁移、完整范围 diff 与 clean status 复核。未运行 full suite，未修改代码，未联网、未安装依赖，也未接触生产服务器/Nginx/systemd/真实数据库/真实外网。
- 外部 reviewer 已回传精确门禁语 `审查通过，可以继续下一步`。Task 8 正式 CLEAN，Task 9 获准在 Task 8 纯文档封板提交后启动。
- full 证据边界不变：唯一 `1222 passed in 590.71s` 只覆盖初始实现 `550ed59b328ef0dad2ea3dc2090c017b6d06dbeb`；Fix1 `182987c5` 与 Fix2 `0a2fc11a` 没有 full-suite 覆盖，不得表述为最终 HEAD full PASS。
- 全局发布门禁继续有效：全部功能、独立审查和完整测试/验收全部通过前，只允许本地开发与本地演示；不得部署、改动服务器/Nginx/systemd/真实数据库，也不得临时开放公网。
