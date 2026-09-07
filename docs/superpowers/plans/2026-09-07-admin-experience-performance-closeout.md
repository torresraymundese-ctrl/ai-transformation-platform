# Admin Experience and Performance Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the approved Stage 6 admin presentation and local SEO/performance checks without changing the accepted report.

**Architecture:** Reuse Flask/Jinja routes and view models. Separate admin-only CSS and minimal progressive enhancement from the accepted public theme. Keep server-owned authorization, validation, publishing and snapshots unchanged.

**Tech Stack:** Flask, Jinja, plain CSS/JavaScript, pytest, Node test runner, local browser QA.

**Spec:** `docs/superpowers/specs/2026-08-26-enterprise-ai-platform-ui-design.md`, sections 6.5–12; current shared token values in `static/css/design-tokens.css` supersede the early public palette. The user approved this specification (task-card record 2026-08-26) and on 2026-09-07 explicitly accepted the report and requested completion of remaining work.

## Global Constraints

- 保留现有 Flask 模块化单体、URL、repository/service 事务边界和权限边界。
- 保留内容修订、锁、排期、发布、归档、媒体和关系的精确字段验证。
- 保留公开内容 published-only、canonical、noindex、安全 URL、HTML 清洗和媒体下载规则。
- 保留评估、报告、线索、预约和埋点的数据语义。
- 不加载第三方字体、远程图标、远程分析脚本或真实外网设计资源。
- 触控目标至少 44px，文本缩放至 200% 后仍不丢失内容或操作。
- 320px 宽度不得出现页面级横向滚动；图片、富文本和长 URL 必须安全换行。
- 报告保持现状：不修改 report templates/CSS/JS、PDF adapter、评分、匹配、ROI、发布规则或种子数据。
- Local work only. Do not access production, SSH, Nginx, systemd, live external services, or worktree `data/`. Preserve previous README/report-testing edits. Use exact git pathspecs.
- Python: `D:/Codex干活/企业AI转型平台2.0升级/V0.2-server-snapshot-20260819/.venv/Scripts/python.exe`; Node: bundled primary runtime. Use unique ASCII basetemp paths, `-p no:cacheprovider`. Existing dependencies only.
- Each task runs its focused responsibility tests; controller owns a single final full suite. No worker starts the full repository suite, spawns agents, or operates the browser concurrently with controller.

### Task 1: Shared admin shell, login and operations overview

**Files:** Create `static/css/admin.css`, `tests/test_admin_ui.py`; modify `templates/admin/base_admin.html`, `templates/components/admin_navigation.html`, `templates/admin/login.html`, `templates/admin/operations_dashboard.html`, `templates/admin/_pagination.html`.

**Interfaces:** Existing `admin_content`, `admin_navigation`, `head`, `title` template blocks remain. Provide `.admin-layout`, `.admin-main#admin-main`, `.admin-nav`, `.admin-actions`, `.admin-editor-section`, `.admin-table-wrap`, `.admin-error-summary` for later editor work. Consume shared `--ui-*` tokens without editing public CSS.

- [ ] Baseline: run `tests/test_admin_auth.py tests/test_operations_dashboard.py tests/test_operations_pagination.py`.
- [ ] Add failing HTTP/template tests for a unique focusable main and skip target, admin-only local CSS, login without management navigation, dashboard cards retaining real counts and queue links, accessible current navigation, logout POST/CSRF, and all original nav destinations. Example:

```python
def test_admin_has_unique_named_main(admin_client):
    from bs4 import BeautifulSoup
    page = BeautifulSoup(admin_client.get('/admin').data, 'html.parser')
    assert len(page.select('main')) == 1
    assert page.select_one('a[href="#admin-main"]') is not None
    assert page.select_one('main#admin-main[tabindex="-1"]') is not None
    assert page.select_one('link[href="/static/css/admin.css"]') is not None
```

- [ ] Run new tests and record actual RED before implementation.
- [ ] Replace inline shared CSS with a local admin stylesheet. Desktop >=1024px uses a 240px navigation column and a shrinking content column. Below 1024px navigation groups wrap in normal flow; no hidden destinations, no second menu, no new JS dependency. Use semantic heading groups for operations/content/governance/assets while preserving every existing route and logout form.

```css
.admin-layout { display: grid; grid-template-columns: 15rem minmax(0, 1fr); min-height: 100vh; }
.admin-main { min-width: 0; padding: clamp(1rem, 3vw, 2.5rem); }
.admin-nav a, .admin-nav button, .btn { min-height: 44px; }
@media (max-width: 1023px) { .admin-layout { grid-template-columns: minmax(0, 1fr); } }
```

- [ ] Retain usable legacy aliases (`card`, `btn`, `form-group`, `admin-grid`, `inline-form`, `tag`, `flash`, etc.). Use >=16px body/control text and >=14px auxiliary text, 3px visible focus ring, explicit danger/error treatment, system fonts and reduced-motion. Apply inputs correctly: checkbox/radio must not inherit full-width text-field rules. Wide tables scroll inside the content boundary, not at document level.
- [ ] Login uses one `main` (no nested main), existing form fields/actions/autocomplete/CSRF and clear local brand/return link. Dashboard retains exact data attributes and real counts; remove visible queue code clutter, not its data attributes. No invented metrics or controls. Paginated query state is unchanged.
- [ ] Run new tests plus baseline, `tests/test_content_navigation.py`, and `git diff --check`; self-review, commit only the listed paths. Browser verification belongs to Task 4/controller; do not claim visual completion from CSS tests.

### Task 2: Existing admin editors and list-page consistency

**Files:** Modify `templates/admin/catalog_edit.html`, `templates/admin/case_edit_v2.html`, `templates/admin/resource_edit_v2.html`, `templates/admin/announcement_edit_v2.html`, `templates/admin/legal_edit.html`, `templates/admin/rule_release_edit.html`, `templates/admin/_content_blocks.html`, `templates/admin/_content_relations.html`, `templates/admin/base_admin.html`, `static/css/admin.css`; create `static/js/admin_ui.js`, `tests/test_admin_editor_ui.py`, `tests/js/admin_ui_runtime.test.js`. Active admin list templates may receive only page-heading/label/overflow-container fixes if the route matrix proves a gap; record exact added paths before editing.

**Interfaces:** Consume Task 1 shell/classes. Add server-rendered `data-admin-editor`, section anchors and `.admin-actions`; do not rename any input name, form action, submit value, lock or content-editor data hook. Load admin_ui.js deferred from admin shell.

- [ ] Add real rendered form tests: preserve existing POST/CSRF/locks and action values; unique h1 and main; explicit section headings/anchors; labels associated with inputs; error summary has alert/focus semantics. Cover catalog + resource + case + announcement new/edit and legal/rule pages using existing fixtures.
- [ ] Add Node real event tests for invalid-field navigation, server error summary focus, absent-form no-op, no content/personal data storage. Run both test files for RED.
- [ ] Group existing fields with semantic, non-collapsing sections: basic information, public content, relationships/media, SEO, review/publishing, as applicable. Existing risk/legal/source-review groups remain visible and retain server conditionals. Expose technical metadata in secondary text, never delete hidden concurrency fields.

```html
<section class="admin-editor-section" id="editor-basic" aria-labelledby="editor-basic-title">
  <h2 id="editor-basic-title">基本信息</h2>
  <!-- Move the existing controls here unchanged; do not duplicate controls. -->
</section>
```

- [ ] Use sticky-in-form `.admin-actions` with adequate scroll padding and wrapping at 320px, no fixed overlay that hides fields. Distinguish publish/danger from save/review. Do not add extra actions, disable validation, or intercept POST submissions. Small progressive enhancement may scroll/focus an invalid native field or server summary; no fabricated field errors when server only supplies a generic error.
- [ ] Preserve original content_editor.js behavior and shared data attributes; scripts must be idempotent and tolerate missing nodes. Use 3px focus and reduced-motion-aware scrolling.
- [ ] Run new tests, existing content-editor Node tests, `tests/test_catalog_content_admin.py tests/test_case_publishing.py tests/test_resource_publishing.py tests/test_announcement_publishing.py tests/test_legal_versions.py tests/test_rule_release_admin.py` (resolve actual existing names before command), plus shared admin tests. Self-review and precise commit; send missing fixture/scope questions to controller.

### Task 3: Public SEO and asset-loading baseline

**Files:** Create `tests/test_public_performance.py`, `docs/testing/seo-performance-baseline.md`; if evidence requires, modify only public non-report templates for image width/height, decoding/loading/fetchpriority and deferred script attributes. Do not change accepted layout, assets, report pages, repositories, Flask caching/security headers, or global style tokens.

**Interfaces:** Consume existing canonical/noindex and local asset URLs. Document public route matrix (home, industries, scenarios, services, cases, resources, about, assessment, privacy/legal) and private noindex behavior. Admin stylesheet separation is already delivered by Task 1.

- [ ] Record local asset sizes and rendered public page asset references, description/title/canonical/noindex. Use approved content test fixtures for detail paths; an empty test directory is not a detail-page success.
- [ ] Add tests locking local-only fonts/scripts/images, explicit dimensions on shipped decorative/logo images, eager/high-priority first hero and lazy/async below-fold images, deferred external scripts, unique titles/canonical from trusted base and private noindex. Only assert rules appropriate to actual page roles, not all images indiscriminately.

```python
def test_home_has_no_remote_script_dependency(client):
    from bs4 import BeautifulSoup
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    for script in page.select('script[src]'):
        assert script['src'].startswith('/static/')
        assert script.has_attr('defer')
```

- [ ] Run tests; if a genuine missing dimension/loading/defer attribute is exposed, record RED then make the smallest nonvisual attribute change and rerun. If already correct, report baseline verified; no optimization for its own sake.
- [ ] Document byte totals and environment, cache scope, local-only timing vs production distinction. No claimed Lighthouse/Core Web Vitals pass without that actual measurement; no installation/network just to obtain a score. Keep deployment compression/CDN validation in Stage 7.
- [ ] Run performance tests and relevant public-navigation/UI-foundation regressions; self-review and precise commit.

### Task 4: Cross-page QA and closeout evidence

**Files:** Create `docs/testing/admin-experience-qa.md`, `docs/design/evidence/admin-*.png` as needed; update only this plan's checkboxes after verification. Controller updates the external task card. Any discovered implementation defect returns to its original implementer and covering tests before re-review.

**Interfaces:** Current Task 1–3 code, a new disposable TEST ONLY fixture server, browser screenshots obtained by controller. Keep existing PDF preview and user data untouched. Never fabricate screenshot paths or metrics.

- [ ] Controller captures actual local login, dashboard, active lists, catalog/resource/case/announcement/legal/rule editors, empty/error states, pagination and logout. Inspect 1440/1024/768/390 and 320px content widths when supported; verify keyboard Tab/Shift+Tab/Enter/Space/Escape, visible focus, 200% reflow and no hidden form actions. Record unavailable evidence as unproven, not passed.
- [ ] Run admin responsibility tests, all Node runtime tests, public smoke/navigation/SEO checks; controller runs one fresh final full pytest suite after implementation stabilizes, using an isolated basetemp and no cache provider.
- [ ] Record test commands/results, screenshot route/viewport and reviewed changes, unresolved limitations, user acceptance of unchanged report, and explicit Stage 7 deployment/real-data blockers. Independent task and whole-closeout review must be clean before marking corresponding Stage 6 items complete.
- [ ] Preserve useful QA evidence; stop only exact owned disposable processes when no longer needed. No broad cleanup, production mutation or merging to main. Commit only authored documentation/evidence.
