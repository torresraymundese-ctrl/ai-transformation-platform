# Task 11 implementation report

## Initial state

- Worktree: `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report`
- Branch: `codex/ai-platform-2.0-core`
- Initial HEAD: `61b9cacbc7d7394f044728b78ff0636845aed111`
- Initial `git status --short`: clean (no output).
- The brief was read in full and is the sole requirements source. The full plan was not read.
- Existing implementation at the frozen HEAD still had a legacy homepage query, a rendered legacy `/insights` page, direct legacy `/article/<id>` rendering, legacy shared navigation links, no mobile-menu control, and no global private-surface robots header.
- Controller-provided baseline only (not new Task 11 evidence): smoke/analytics/app-factory/security/validation five-file partition `156 passed in 84.06s`, exit 0.
- Historical evidence explicitly not reusable: Task 6 full remains UNKNOWN and involved a PyPI violation; Task 10's `1471` full covers only `d9fa16a`; Task 11 currently has no full-suite result.

## Accepted RED evidence

Every pytest command below used the required offline dependency path, a unique
absolute basetemp, and disabled pytest's cache provider.

1. Initial route/homepage/metadata/menu/link RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-red1' -p no:cacheprovider`
   - Summary/exit: `7 failed in 4.11s`, exit 1.
   - Accepted failure reasons: no confirmed-navigation selector; homepage rendered a seeded legacy case and fabricated case count; `/insights` returned 200 instead of fixed 301; homepage canonical was absent; private robots metadata/header was absent; no mobile menu existed; and reachable `_blank` links had only `noopener`.
2. Legacy resolver and rich-text sanitizer RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py tests/test_content_validation.py::test_rich_text_links_keep_only_root_relative_or_https_destinations -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-red3' -p no:cacheprovider`
   - Summary/exit: `6 failed, 7 passed in 6.94s`, exit 1.
   - Accepted failure reasons: all unmapped/polluted/nonpublic legacy article cases still rendered 200; sanitized rich text still retained HTTP, `mailto:`, `tel:`, and scheme-relative hrefs.
3. Canonical/polluted target/Unicode-control RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_public_legacy_shell_pages_have_configured_canonical tests/test_content_navigation.py::test_legacy_article_mapping_rejects_polluted_review_target_group tests/test_content_validation.py::test_rich_text_relative_link_rejects_unicode_control_characters -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-red4' -p no:cacheprovider`
   - Summary/exit: `4 failed in 1.92s`, exit 1.
   - Accepted failure reasons: `/assessment` and `/about` had no configured canonical; a polluted article review target group still redirected; a Unicode format-control character remained in a relative rich-text href.
4. Step 4 adjacent-contract RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_analytics.py tests/test_smoke.py tests/test_app_factory_and_migrations.py -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-related1' -p no:cacheprovider`
   - Summary/exit: `3 failed, 558 passed in 287.82s`, exit 1.
   - Accepted failure reasons: three pre-Task-11 test contracts still required `/insights` 200 and nine `/services` links. Controller authorized the one-file `tests/test_analytics.py` scope addition before it was edited.
5. Security/validation adjacent-contract RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_validation.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-adjacent-red1' -p no:cacheprovider`
   - Summary/exit: `3 failed, 172 passed in 11.16s`, exit 1.
   - Accepted failure reasons: legacy article/announcement assertions still expected public 200 rendering instead of unmapped/unsafe 404 or `/insights` 301 to the V2 resource owner.
6. Privacy-policy placeholder RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_privacy_policy_link_has_no_destination_before_validated_config -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-red5' -p no:cacheprovider`
   - Summary/exit: `1 failed in 0.85s`, exit 1.
   - Accepted failure reason: server-rendered assessment markup exposed `href="#"` before the privacy configuration API had validated an HTTPS policy URL. Controller authorized the one-line `templates/assessment.html` scope addition before it was edited.
7. Explicitly stale review RED
   - Exact command: `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_legacy_article_mapping_rejects_explicitly_stale_review -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-red6' -p no:cacheprovider`
   - Summary/exit: `1 failed in 0.80s`, exit 1.
   - Accepted failure reason: a review with `review_stale_at` set could still redirect if its checksums were artificially kept equal.

Rejected RED attempt: `task11-impl-red2` was not accepted and caused no production change because two tests failed from fixture/schema mistakes (`articles.source` NOT NULL and an illegal direct published-to-draft transition). Fixtures were corrected to use real save/schedule/archive paths before accepted RED 2.

## Minimal GREEN

- Homepage now calls only Tasks 6-9 fail-closed V2 read models for industries, scenarios, services, cases, resources, and announcements; it has no legacy fallback or fabricated count and conditionally omits empty case/resource/announcement sections.
- Shared navigation/footer use the confirmed IA and canonical V2 destinations. Mobile navigation is a native `<details>/<summary>` control, with CSS-owned responsive behavior and visible `:focus-visible` styles.
- `/services` is fixed 301 to `/service-packages`; `/insights` is fixed query-dropping 301 to `/resources`.
- `/article/<id>` asks `content_repository.legacy_article_resource_slug()` for a server slug. The resolver starts one SQLite `BEGIN` snapshot, recomputes the exact legacy checksum, requires a clean/non-stale checksum-current review, requires exact mapping group/item identity, resolves the group's canonical current published revision, and reuses `validate_resource_public_completeness()` before returning a slug. The blueprint contains no SQL.
- Canonicals use only validated `PUBLIC_BASE_URL`; admin/report/privacy-operation surfaces retain private no-store behavior and receive exact `X-Robots-Tag: noindex, nofollow` plus template metadata.
- Rich-text anchor sanitization now retains only root-relative or validated HTTPS hrefs. Trusted footer `tel:` stays same-window; reachable server-generated `_blank` HTTP(S) links have both rel tokens. The assessment privacy link has no href until existing runtime code receives the already validated HTTPS configuration value.
- Minimal GREEN checkpoints: `7 passed in 4.00s` (green3), `13 passed in 6.96s` (green4), `4 passed in 1.76s` (green5), `562 passed in 286.75s` (related2), `175 passed in 11.04s` (adjacent-green1), `1 passed in 0.66s` (green6), `61 passed in 32.61s` (assessment-related1), and `1 passed in 0.65s` (green7); every command exited 0.

## Final verification

- Focused: `tests/test_content_navigation.py tests/test_content_validation.py` -> `172 passed in 9.75s`, exit 0; basetemp `task11-impl-final-focused1`.
- Brief Step 4 eight-file partition -> `564 passed in 290.30s`, exit 0; basetemp `task11-impl-final-related1`.
- Security/validation adjacent partition -> `175 passed in 11.14s`, exit 0; basetemp `task11-impl-final-adjacent1`.
- Assessment Python adjacency -> `61 passed in 32.61s`, exit 0; basetemp `task11-impl-assessment-related1`.
- Dedicated final URL-context guard (configured canonical, all rendered server links, and no pre-configuration privacy href): `3 passed in 2.41s`, exit 0; basetemp `task11-impl-final-urlguard1`.
- Python `py_compile` for the production Python surface named by the brief plus every changed Python test: exit 0, no compiler output.
- Jinja parser: `jinja parsed 65 templates`, exit 0.
- Node syntax (`app.js`, `assessment.js`) plus four runtime files: `21` tests, `21` pass, `0` fail, exit 0.
- `git diff --check`: exit 0; only expected LF-to-CRLF worktree warnings, no whitespace errors.
- Scope guard: `scope ok: 18 authorized files`, exit 0 after the final code changes.
- Route-owner guard: `route owners ok: 6 exact single-owner rules; public blueprint SQL-free`, exit 0. A preceding discarded one-off guard command had a script-only `NameError` and is not evidence.
- Brief no-hunk audit: `brief no-hunk audit ok: 4 intentionally unchanged; base_admin has required hunk`, exit 0.

## File scope

- Production/read-model/security: `blueprints/public.py`, `content_repository.py`, `security.py`.
- Shared UI/templates: `static/css/app.css`, `templates/admin/base_admin.html`, `templates/assessment.html` (controller-authorized one-line addition), `templates/base.html`, `templates/components/admin_navigation.html`, `templates/components/content_card.html` (new), `templates/components/footer.html`, `templates/components/navigation.html`, `templates/index.html`.
- Tests: `tests/test_content_navigation.py` (new), `tests/test_content_validation.py`, `tests/test_security_gaps.py`, `tests/test_smoke.py`, `tests/test_validation_and_errors.py`, and controller-authorized minimal `tests/test_analytics.py` update.
- Detailed report: this ignored file; `git check-ignore -v` confirms `.superpowers/sdd/.gitignore:1:*`. It is not staged and does not appear in git status.

Brief-listed files intentionally left without hunks:

- `app.py`: its existing app factory already validates `PUBLIC_BASE_URL`, registers the public/catalog blueprints in the correct single-owner order, and installs `add_security_headers`; Task 11 needed no new registration or configuration path.
- `content_validation.py`: reviewed HTTP ingestion remains private/nonpublishable through its existing strict source-validation path. The Task 11 rich-text change belongs to the existing Bleach sanitizer/attribute boundary in `security.py`, which reuses `normalize_source_url`; duplicating a second URL parser here would violate the binding interface.
- `templates/insights.html`: `/insights` is now an unconditional fixed redirect and no reachable route renders this retired legacy shell. Editing the template would not affect the public contract.
- `templates/article.html`: `/article/<id>` now either redirects to the V2 resource owner or returns 404, so no reachable route renders this retired legacy shell. It was deliberately not made a second detail-page owner.
- `templates/admin/base_admin.html` is not in the no-hunk set: it has the required minimal template robots metadata addition.

## Self-review

- TDD audit: no production behavior was written before its corresponding accepted failing test. The rejected fixture run caused no production edit.
- Route ownership: `/cases`, `/resources`, and `/announcements/<slug>` remain owned only by `public_catalog`; compatibility routes remain in `public`; no legacy route ownership was reintroduced.
- Data boundary: homepage has no legacy fallback calls. Legacy tables remain physically intact. The compatibility resolver alone reads a specific legacy article, behind repository/read-model ownership and a single read transaction.
- URL/SEO: no Host, X-Forwarded-Host, `request.url`, `host_url`, or `url_root` participates in canonical construction. Internal template links are root-relative; content external destinations are validated HTTPS; sanitized rich text rejects HTTP/active/contact/scheme-relative/control-character hrefs.
- Analytics/cache: the public base template still invokes the existing analytics/session hook, and passing partitions confirm exact `private, no-store`, `Pragma`, and `Expires` behavior. Robots headers are additive and do not overwrite cache policy.
- Accessibility: native mobile-menu operation does not depend on JavaScript; summary and all interactive public controls receive visible keyboard focus.
- Reachability note: `templates/admin/article.html` still contains historical single-token `rel="noopener"`, but Task 9 removed every route owner for that retired template. Controller explicitly declined expanding scope to this unreachable file; all reachable `_blank` HTTP(S) links have both tokens.
- No unrelated legacy data, routes, docs, journeys, screenshots, deployment assets, or public owners were changed.

## Known limitations

- No Task 11 full suite is authorized before controller code-freeze/preflight approval.
- No browser/mobile viewport matrix was run because Task 12 owns that work. Mobile semantics are verified structurally and through CSS/static gates only.
- No production deployment/network/database was touched; all evidence uses Flask clients, disposable SQLite/media, and offline dependencies.
- Line-ending warnings reflect this Windows worktree's LF-to-CRLF conversion policy and are not `git diff --check` errors.
- Task 6 historical full remains UNKNOWN and involved a PyPI violation. Task 10's `1471` full covers only commit `d9fa16a`. Task 11 has no full-suite result, and no earlier count is presented as Task 11 full evidence.

## Not run

- Full pytest suite (explicitly prohibited at this stage).
- Browser matrix, journeys, documentation, screenshots, production/Nginx/systemd/real database/public-network checks (Task 12 or outside scope).
- Commit/stage/push (controller owns code-freeze preflight and later commit authorization).

## Fix pre-full

### Review input and accepted RED

- Controller review input (not reused as implementation evidence):
  `tests/test_report_access.py::test_html_report_renders_every_required_snapshot_section`
  had already produced `1 failed in 0.87s` under basetemp
  `task11-controller-prefull-red-report-001`, because a valid report rendered two
  robots meta elements.
- P2-1 accepted RED command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_report_access.py::test_missing_html_report_has_one_private_robots_policy tests/test_report_access.py::test_html_report_renders_every_required_snapshot_section -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-prefull-red-report1' -p no:cacheprovider`
  -> `1 failed, 1 passed in 1.46s`, exit 1. The valid report had both
  `noindex,nofollow` and `noindex,nofollow,noarchive`; the missing-report 404
  already had one valid default policy.
- P2-2 accepted RED command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_legacy_article_ids_outside_existing_sqlite_rows_fail_closed -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-prefull-red-hugeid1' -p no:cacheprovider`
  -> `1 failed, 1 passed in 1.33s`, exit 1. SQLite's maximum signed integer
  returned 404, while `9223372036854775808` reached binding, raised
  `OverflowError`, and returned 500.
- P2-3 accepted test-only coverage RED command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_rendered_server_links_follow_the_url_context_matrix -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-prefull-red-urlmatrix1' -p no:cacheprovider`
  -> `1 failed in 0.80s`, exit 1. The frozen required surface set contained the
  public, report, V2 catalog, and reachable admin contexts, while the old scan
  supplied only `public.home` and `admin.dashboard`.

No production code preceded these failing tests. Two later matrix fixture runs
were rejected as behavior evidence: `urlmatrix-run1` failed because a test row
attempted to bypass the pending-media insertion trigger, and `urlmatrix-run2`
selected the intentionally incomplete `data-process-foundation` scenario.
They caused no production change. The fixture was corrected to follow
pending-to-ready media state and to select the known complete published scenario.

### Minimal GREEN

- P2-1: `base.html` now exposes a clear `robots_meta` Jinja block. The report
  overrides it with the single authoritative
  `noindex,nofollow,noarchive` value; report 404 pages inherit the single
  `noindex,nofollow` default. The exact response header remains
  `X-Robots-Tag: noindex, nofollow`. The same two nodes with basetemp
  `task11-impl-prefull-green-report1` produced `2 passed in 1.29s`, exit 0.
- P2-2: the repository resolver now rejects anything except an exact `int` in
  `1..2**63-1` before opening/binding a SQLite query. The same parameterized
  node with basetemp `task11-impl-prefull-green-hugeid1` produced
  `2 passed in 1.12s`, exit 0.
- P2-3: the matrix publishes its dynamic case/resource/announcement through
  existing admin/publication paths, uses a mock HTTPS source transport and a
  disposable SQLite/media row, and completes a real assessment for the valid
  report and lead surfaces. The completed 37 named contexts / 36 distinct paths node with basetemp
  `task11-impl-prefull-urlmatrix-final1` produced `1 passed in 1.49s`, exit 0.

### Rendered URL-context matrix

- Public shell/report: home, assessment, about, valid report, and report 404.
- V2 public catalog: industry, scenario, service-package, case, and resource
  lists plus a complete published detail for each; the homepage's current
  announcement list plus a current announcement detail.
- Admin: anonymous login; authenticated dashboard; industry/scenario/service
  catalog list and edit; case/resource/announcement list and edit; media;
  assessments; leads list and real lead edit; appointments; data requests.
- Every response is first checked for its exact expected status and
  `text/html` mimetype, then every `a[href]` is scanned. Internal links must be
  root-relative and not `//`; all other content links must be HTTPS; every
  `_blank` HTTP(S) link must have both `noopener` and `noreferrer`.
- Contact protocols are not globally allowlisted. The only rendered exception
  is exact `tel:4001803358` on the fixed footer phone analytics selector, and it
  must remain same-window. Any `mailto:` or any other `tel:` fails the matrix.
- Direct semantic assertions cover the normalized sourced-resource HTTPS link,
  an HTTPS controlled-block CTA, the root-relative published attachment URL,
  an internal same-window announcement CTA, the homepage announcement link,
  and omission of the assessment policy `href` before safe configuration.
- Excluded from this Task 11 content matrix: `/admin/assets*` belongs to the
  separate legacy asset inventory rather than the 5A content publishing
  system; retired `/admin/case/*` and legacy article templates are not V2
  owners or navigation destinations. Binary PDF/media responses and JSON APIs
  are not HTML anchor surfaces; the published media download href itself is
  asserted in the resource detail.

### Final pre-full verification

- New exact nodes: `5 passed in 3.69s`, exit 0; basetemp
  `task11-impl-prefull-final-nodes1`.
- Focused navigation/validation: `174 passed in 11.53s`, exit 0; basetemp
  `task11-impl-prefull-final-focused1`.
- Full report-access file: `45 passed in 29.05s`, exit 0; basetemp
  `task11-impl-prefull-final-reportaccess1`.
- Final-tree brief Step 4 eight-file partition: `566 passed in 291.89s`, exit 0;
  basetemp `task11-impl-prefull-final-related3`. An earlier complete rerun had
  `566 passed in 290.99s`, but `related3` is the final-tree evidence. A prior
  detached-output attempt is not counted.
- Security/validation adjacent partition: `175 passed in 11.11s`, exit 0;
  basetemp `task11-impl-prefull-final-adjacent1`.
- Static gates: Python compile exit 0; Jinja parsed 65 templates, exit 0; Node
  syntax plus four runtime files `21 passed, 0 failed`, exit 0;
  `git diff --check` exit 0 with only LF-to-CRLF warnings; scope
  `20 authorized files`, exit 0; route-owner guard
  `6 exact single-owner rules; public blueprint SQL-free`, exit 0.

### Pre-full scope delta and freeze state

- Added controller-authorized files to the existing Task 11 change set:
  `templates/assessment/report.html` and `tests/test_report_access.py`.
- Existing authorized files with pre-full additions:
  `content_repository.py`, `templates/base.html`, and
  `tests/test_content_navigation.py`.
- Total status scope is 20 authorized files. The ignored report remains outside
  git status and staging.
- Task 11 still has no full-suite result. Task 6 historical full remains
  UNKNOWN/PyPI-violating, and Task 10's 1471 count still applies only to
  `d9fa16a`. No old count is reused.
- State after these gates: code frozen, awaiting controller preflight; no full,
  stage, commit, push, network, browser matrix, or production action was run.

## Fix2 pre-full

### P2 injected time authority RED -> GREEN

- Accepted RED exact command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_rendered_server_links_follow_the_url_context_matrix tests/test_content_navigation.py::test_legacy_article_adapter_uses_the_injected_content_clock -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-fix2-red-clock1' -p no:cacheprovider`
  -> `2 failed in 2.15s`, exit 1.
- Real homepage failure: the app's `CONTENT_NOW_PROVIDER` was fixed at `NOW`,
  while the repository fallback `shanghai_now` was deliberately fixed at 2035.
  The formal dynamic publication fixture then lost the sourced resource section
  because its review had expired under the wrong clock (and its announcement
  would also be outside its current interval). This exercised rendered behavior,
  not a call spy. The test requires all six published homepage sections and the
  exact dynamic detail link for industry, scenario, service, case, resource, and
  announcement.
- HTTP adapter failure: the explicit resolver boundary spy received
  `(article_id=17, now=None)` rather than `(17, NOW)`; it returned `None`, so the
  response safely remained 404 while proving the clock was not forwarded.
- Minimal production GREEN: `blueprints/public.py` now has the same callable
  `CONTENT_NOW_PROVIDER` selection used by `public_catalog`, falling back to
  `shanghai_now`. `index()` obtains one instant and passes it to
  `home_page_data(now=...)`; `article_page()` passes the selected instant to
  `legacy_article_resource_slug(..., now=...)`. No `public_catalog` route or
  other clock path changed.
- Same nodes with basetemp `task11-impl-fix2-green-clock1` ->
  `2 passed in 1.94s`, exit 0.

### P3 matrix count correction

- AST evaluation confirms `REQUIRED_RENDERED_SURFACES` contains exactly
  **37 named contexts**.
- They represent **36 distinct paths** because `public.home` and
  `announcements.home-list` intentionally render the same `/` path under two
  semantic assertions.
- Repository/report `rg` found one stale overstated surface-count phrase in this
  report; it was corrected. The test constant and coverage were not changed for
  this P3.

### Fix2 final verification

- Final URL matrix: `1 passed in 1.44s`, exit 0; basetemp
  `task11-impl-fix2-final-urlmatrix1`.
- Focused navigation/validation: `175 passed in 11.95s`, exit 0; basetemp
  `task11-impl-fix2-final-focused1`.
- Full report-access file: `45 passed in 29.11s`, exit 0; basetemp
  `task11-impl-fix2-final-reportaccess1`.
- Final-tree brief Step 4 eight-file partition: `567 passed in 289.23s`, exit 0;
  basetemp `task11-impl-fix2-final-related1`.
- Security/validation adjacent partition: `175 passed in 11.15s`, exit 0;
  basetemp `task11-impl-fix2-final-adjacent1`.
- Python compile: exit 0. Jinja: 65 templates parsed, exit 0. Node syntax plus
  four runtime files: 21 passed, 0 failed, exit 0. `git diff --check`: exit 0
  with only LF-to-CRLF worktree warnings. Scope: 20 authorized files, exit 0.
  Route-owner guard: 6 exact single-owner rules and public blueprint SQL-free,
  exit 0.
- Fix2 changed no additional path beyond the existing 20-file authorized set:
  only `blueprints/public.py` and `tests/test_content_navigation.py` gained
  tracked hunks; this ignored report records the evidence.
- State: code frozen, awaiting controller preflight. Task 11 still has no full;
  no full, stage, commit, push, network, browser, or production action ran.

## Fix3 privacy policy HTTPS boundary

### Accepted RED

- Exact command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_content_navigation.py::test_assessment_config_exposes_only_validated_https_policy_url -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-impl-fix3-red-privacy-url1' -p no:cacheprovider`
- Result: `2 failed, 1 passed in 1.88s`, exit 1.
- Failure reasons: the valid HTTPS policy URL correctly returned 200, but both
  `http://example.invalid/privacy` and malformed
  `https://example.invalid/%ZZ` also returned 200 and entered the assessment
  configuration payload. Because the existing assessment runtime assigns
  `privacy.policy_url` directly to the link href, those values crossed the
  browser-visible configuration boundary.

### Minimal GREEN

- `blueprints/assessment.py` now reuses the existing strict
  `source_url_checker.normalize_source_url` parser and accepts the normalized
  result only when its scheme is exactly HTTPS. Invalid/HTTP policy
  configuration follows the stable recoverable 503 contract and exposes no
  `policy_url`; the assessment HTML continues to omit the link `href` before a
  successful safe configuration response.
- Valid HTTPS remains present in `privacy_disclosure.policy_url` without a
  behavior change for the existing canonical test value.
- `static/js/assessment.js` was not changed: the server now guarantees the
  HTTPS-only value required by its existing direct assignment.
- Same exact node with basetemp `task11-impl-fix3-green-privacy-url1` ->
  `3 passed in 1.70s`, exit 0.

### Fix3 final verification and scope

- Focused navigation + assessment API + content validation:
  `233 passed in 44.75s`, exit 0; basetemp
  `task11-impl-fix3-final-focused1`.
- Source URL + security/validation adjacent partition:
  `63 passed in 10.95s`, exit 0; basetemp
  `task11-impl-fix3-final-adjacent1`.
- Python compile exit 0; Jinja parsed 65 templates, exit 0; Node syntax plus
  four runtime files `21 passed, 0 failed`, exit 0; `git diff --check` exit 0
  with only LF-to-CRLF warnings; route-owner guard retained 6 exact owners and
  a SQL-free public blueprint, exit 0.
- Fix3 tracked delta: `blueprints/assessment.py` and
  `tests/test_content_navigation.py`. Total current status scope is 21
  authorized files; the detailed report remains ignored.
- Fix2's final-tree Step 4 result predates this Fix3 and is not presented as
  Fix3 evidence. The requested proportional focused/adjacent partitions were
  run; no full, stage, commit, network, production, browser, or Task 12 action
  ran. Task 11 still has no full-suite result.
- State before full: code frozen; controller exact Fix3 node passed `3 passed
  in 1.72s`, and a brand-new final pre-full reviewer returned `CLEAN` with no
  P0-P3 across the complete 21-file scope.

## One-and-only frozen full suite

- Environment: assigned Python 3.12.13 interpreter with command-scoped offline
  `PYTHONPATH=.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps`;
  resolved `pypdf==6.10.0`. No dependency install or network access occurred.
- Exact command:
  `$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'; & 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -q --basetemp 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task11-full-final-001' -p no:cacheprovider`
- Result: `1531 passed in 656.38s (0:10:56)`, exit 0.
- This was the exactly-once Task 11 full suite on the frozen final source tree.
  It will not be repeated. No source/test file changed during or after it.
- State: awaiting exact 21-file commit, frozen review package and fresh
  post-commit read-only review. Task 12 and all deployment remain frozen.

## Frozen implementation commit and review package

- Baseline: `61b9cacbc7d7394f044728b78ff0636845aed111`.
- Implementation/final source commit:
  `fa803a5492915b4bae4be8f7a6002a5cfafbdd01`
  (`feat: integrate the public content catalog`), exactly one commit and 21
  files, 1325 insertions/406 deletions. Parent matches the baseline.
- Complete net package:
  `.superpowers/sdd/2026-08-24-content-catalog-publishing/review-61b9cac..fa803a5.diff`;
  21 files/headers, 89,451 bytes, 2,167 PowerShell text lines, SHA-256
  `BB6DF6074A67A71F242DCE70F48D06CDC7AC40A0CCB6CD0B07BC105FC4F159B9`.
- Reverse apply check and complete-range diff check passed; post-commit tracked
  and untracked status is clean. The generated package/report are ignored SDD
  evidence and do not alter the commit.
- State: fresh post-commit read-only reviewer pending. Task 12 and deployment
  remain frozen.

## Post-commit review gate

- A brand-new independent reviewer inspected the complete committed net diff
  and returned `CLEAN` with no P0-P3. It independently matched HEAD/parent,
  one commit, 21 authorized files, all handoff hashes, package dimensions,
  reverse apply and clean status. Stable package/commit patch-id was
  `8019cc2cbeeb7106b02cd75802927329a56e8065`.
- The reviewer confirmed all Task 11 behavior boundaries, the 37 named / 36
  distinct URL contexts, real behavior-level tests, and that the unique full
  evidence belongs to this exact committed source. It ran no pytest/full,
  network or writes.
- Controller post-review selector covered homepage canonical, rendered URL
  matrix, privacy HTTPS configuration, injected content clock, signed-int64
  legacy IDs, rich-text links and valid/missing report robots:
  `11 passed in 6.29s`, exit 0; basetemp
  `task11-controller-postreview-001`.
- Controller rechecked package SHA-256, reverse apply, full-range diff, exact
  HEAD and clean status; all passed.
- State: Task 11 implementation/internal review is complete. External review
  under “审查企业AI转型平台” is pending. Task 12 and all deployment/public
  exposure remain frozen until its exact gate phrase is received.

## External review and final gate

- “审查企业AI转型平台” performed a fresh scoped review of the complete
  `61b9cac..fa803a5` net range. It independently matched HEAD/parent, one
  commit, 21 files, package/brief/report/task-card hashes, stable patch-id,
  reverse apply and clean status before reviewing the full implementation.
- The external reviewer found no P0-P3. Its fresh offline selector passed
  `27 passed in 15.65s`, exit 0; all 11 changed Python files compiled, the
  complete diff check passed, public blueprints remained SQL-free, the 37
  named contexts and Task 12 exclusion gate passed. It cleaned its temporary
  directory and did not rerun full.
- It made no code/index/HEAD writes, installed nothing, used no network and
  accessed no production, Nginx, systemd or real database resources.
- The reviewer returned the exact gate phrase
  `审查通过，可以继续下一步`. Task 11 is therefore complete. Task 12 may
  start only after this report is sealed in a pure documentation commit.
- Deployment remains separately frozen: all functions, independent reviews
  and complete acceptance must finish before any server/public action.
