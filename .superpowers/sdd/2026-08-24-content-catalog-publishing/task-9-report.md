# Task 9 implementation report

- Plan: `docs/superpowers/plans/2026-08-24-content-catalog-publishing.md`
- Brief: `.superpowers/sdd/2026-08-24-content-catalog-publishing/task-9-brief.md`
- Brief SHA256: `4A57230A5B62722F4500209F99F00465CBD92EB49BFE0DFB02E2110FE3C49491`
- Frozen baseline: `197418ed01b2ea6883144d42282c8e3871d97910`
- Task 9 commit: `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`
- Branch: `codex/ai-platform-2.0-core`
- Scope: Task 9 only; Task 10 is not started.
- Safety boundary: local disposable SQLite/media roots and mocked source transports only; no network, dependency installation, production, Nginx, systemd, real database, deployment, or public exposure.

## Skill and contract intake

Read the complete Task 9 brief and the binding Task 9 plan/spec sections. Applied `test-driven-development` (including `writing-good-tests.md`), `systematic-debugging`, `verification-before-completion`, and `subagent-driven-development`. The implementation is being built from observed RED tests before production changes.

## RED / GREEN ledger

### RED 001 — Task 9 HTTP/domain/service contract

Command (offline local dependency overlay, unique basetemp):

```powershell
$env:PYTHONPATH='<worktree>\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests/test_resources_announcements.py -q -p no:cacheprovider --basetemp='<worktree>\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task9-red-001'
```

Result: **19 failed in 10.41s, exit 1**. Failures were the expected missing/unsafe production behaviors: all V2 resource/announcement admin/public routes were absent (404), legacy admin owners were still present, malformed whitespace copyright passed domain/publication validation, a null announcement interval passed validation, and the due job published a corrupted resource instead of isolating it. No collection/setup error occurred.

### RED 002 — choice-first authorship runtime

Command: `node --test tests/js/content_editor_runtime.test.js`

Result: **8 passed, 1 failed, exit 1**. The new real runtime test failed with `TypeError: editor.synchronizeAuthorshipFields is not a function`, proving the resource authorship/source field synchronization behavior was absent while all prior editor runtime tests remained green.

### GREEN 001 — reviewed resources and fixed-validity announcements

The minimal implementation added the resource/announcement repository, authenticated V2 admin adapters, public read models/templates, five exact resource types, binary original/sourced choice, source-check reuse, copyright/original-time completeness, attachment MIME publication gate, announcement interval gate, immutable revision/copy behavior, public snapshot reads, and legacy admin owner removal. It also normalized announcement/block CTA URLs and made external links open with `noopener noreferrer` while keeping internal paths same-window.

Initial focused result: **33 passed in 18.85s, exit 0**. The final expanded focused result is recorded below.

The first JS GREEN attempt exposed a test-harness defect: the fake select did not model option children. After correcting only the fake DOM harness, the production behavior was exercised through real `change`/add events and passed. This was not counted as product GREEN until the corrected event-level test passed.

### RED/GREEN 003 — source validation error stability

The first related run of `tests/test_content_publishing.py -x` produced **1 failed, 7 passed**: a list-valued persisted `source_name` returned `extension_invalid` behavior through SQLite instead of the established stable validation path. The implementation was changed so missing/blank sourced names remain `source_required`, while non-string/NUL/overlong shapes remain `extension_invalid`. Fresh whole-file result: **90 passed in 53.01s, exit 0**.

### RED/GREEN 004 — dead dashboard route

An added route-owner test failed because `/admin` still rendered `href="/admin/articles"` after the legacy owner was removed. Result: **1 failed, exit 1**. The dashboard quick action was switched to `/admin/resources`; exact rerun: **1 passed in 1.10s, exit 0**.

### RED/GREEN 005 — exact second preservation

The editor rendered `datetime-local` values at minute precision, silently dropping non-zero seconds from `original_published_at`, `valid_from`, and `valid_until`. Exact RED: **1 failed, exit 1**. Both V2 editors now render all 19 timestamp characters with `step="1"`; exact GREEN: **1 passed in 0.89s, exit 0**.

### Harness corrections that were not product RED

- A relationship completeness test initially held an uncommitted fixture connection while invoking the service, producing `database is locked`; the fixture committed before the service boundary.
- Its next setup attempted to create a second core scenario group with a different canonical slug, producing `core_group_slug_mismatch`; it was corrected to edit the seeded scenario draft. The intended assertion then passed: a status-only legacy resource with malformed public completeness is rejected as `relation_target_not_published`.
- One combined core verification process transiently returned three catalog HTTP 400 results after the error-order patch. With no code change, the exact test passed, the complete catalog file passed **17/17**, and the same combined partition passed **167/167**. The unique full suite later passed all 1,371 tests. No unsupported root-cause claim is made; only the final fresh terminal evidence is treated as PASS.

## Verification ledger

All Python test commands below used this exact interpreter/environment and never contacted the network:

```powershell
$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest <tests> -q -p no:cacheprovider --basetemp='<absolute unique Task9 directory under .superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp>'
```

Runtime evidence: Python **3.12.13**, pypdf **6.10.0** from the command-scoped offline overlay, Jinja2 **3.1.6**, Flask **3.1.3**. No package was installed or changed.

### Focused and plan-required related tests

| Tests / exact basetemp suffix | Result | Exit |
| --- | --- | --- |
| `tests/test_resources_announcements.py` / `task9-focused-final-001` | **39 passed in 24.55s** | 0 |
| brief five files: `tests/test_resources_announcements.py tests/test_content_publishing.py tests/test_media_http.py tests/test_validation_and_errors.py tests/test_rate_limits_and_audit.py` / `task9-related-brief-five-001` | **167 passed in 104.50s** | 0 |
| `tests/test_validation_and_errors.py` / `task9-adj-validation-001` | **9 passed in 6.87s** | 0 |
| `tests/test_rate_limits_and_audit.py` / `task9-adj-audit-001` | **7 passed in 7.46s** | 0 |
| `tests/test_security_gaps.py` / `task9-adj-security-002` | **11 passed in 7.08s** | 0 |
| `tests/test_media_http.py` / `task9-related-media-http-001` | **24 passed in 21.29s** | 0 |
| `tests/test_smoke.py` / `task9-related-smoke-001` | **24 passed in 17.61s** | 0 |

The first security-adjacent run was **9 passed, 2 failed** because two assertions still targeted removed V1 admin URLs. They were migrated to the V2 resource/announcement CSRF contract without restoring legacy ownership.

### Risk partitions

| Partition / exact basetemp suffix | Result | Exit |
| --- | --- | --- |
| `tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py` / `task9-partition-public-001` | **344 passed in 203.21s** | 0 |
| `tests/test_security_gaps.py tests/test_smoke.py` / `task9-partition-security-001` | **35 passed in 24.57s** | 0 |
| `tests/test_content_validation.py tests/test_app_factory_and_migrations.py tests/test_catalog_content_admin.py` / `task9-partition-core-003` | **167 passed in 14.35s** | 0 |
| `tests/test_source_url_checker.py tests/test_content_migrations.py tests/test_v2_migrations.py tests/test_media_service.py tests/test_content_seed.py` / `task9-partition-source-migration-media-001` | **183 passed in 85.94s** | 0 |

The first core partition found one real regression: dangerous source URL controls were masked by the new copyright-required error. Result: **166 passed, 1 failed in 17.34s**. Validation order was corrected; the exact regression passed and the final core partition above passed.

### JavaScript and static gates

```powershell
node --test tests/js/content_editor_runtime.test.js
```

Result: **9 passed, 0 failed, duration 206.055 ms, exit 0**.

Additional gates, all exit 0:

- `node --check static/js/content_editor.js`;
- assigned Python `-m py_compile` over all changed production/test Python files;
- Jinja parse of all **9** changed/new templates;
- `git diff --check`;
- frozen-migration check: `git diff --exit-code 197418ed01b2ea6883144d42282c8e3871d97910 -- migrations`;
- Blueprint SQL/transaction text guard over `blueprints/admin/resources.py` and `blueprints/public_catalog.py`;
- public-template private-field guard;
- external source/CTA `target="_blank" rel="noopener noreferrer"` guard;
- route and endpoint uniqueness is also an HTTP/app-map assertion inside the 39-test focused file.

### The one and only Task 9 full suite

After code/test freeze, exactly once:

```powershell
$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\task9-full-001'
```

Result: **1371 passed in 817.24s (0:13:37), exit 0**. This full suite was not repeated.

After preserving every summary/exit above, cleanup resolved the worktree and SDD `test-tmp` roots, verified each target was a direct `task9-*` child inside that root, and removed exactly **32** disposable Task 9 basetemp directories; **0** remained.

## File scope and limitations

### Task 9 code/test scope

Created:

- `resource_repository.py`
- `blueprints/admin/resources.py`
- `templates/admin/resource_list_v2.html`
- `templates/admin/resource_edit_v2.html`
- `templates/admin/announcement_edit_v2.html`
- `templates/resources.html`
- `templates/resource_detail.html`
- `templates/announcement_detail.html`
- `tests/test_resources_announcements.py`

Modified plan files:

- `blueprints/admin/__init__.py`
- `blueprints/admin/content.py`
- `blueprints/public_catalog.py`
- `templates/components/admin_navigation.html`

Required adjacent/shared updates:

- `content_validation.py`
- `publishing_repository.py`
- `static/js/content_editor.js`
- `templates/admin/index.html`
- `templates/components/content_blocks.html`
- `tests/js/content_editor_runtime.test.js`
- `tests/test_media_http.py`
- `tests/test_rate_limits_and_audit.py`
- `tests/test_security_gaps.py`
- `tests/test_smoke.py`
- `tests/test_validation_and_errors.py`

The adjacent tests were migrated because Task 9 intentionally removes V1 article/announcement admin write ownership; retaining V1 writers or payload shapes would violate the binding plan.

### Boundaries and known limitations

- Per controller ruling, non-overlapping legacy public `/insights` and `/article/<int>` compatibility endpoints remain for Task 11. Their V1 admin write/list owners are removed.
- `list_current_announcements()` is complete for the homepage consumer, but homepage/navigation cutover is Task 11 and was not started.
- Legacy tables/repository helpers and unowned legacy templates remain available for later non-destructive migration review; Task 9 does not delete data.
- Source checks used mocked pinned transports only. No real external URL, production endpoint, or network stack was contacted.
- No production/server/Nginx/systemd/real-database change, deployment, or public exposure occurred. Task 10 was not started.
- `progress.md` and the external upgrade task card were not modified by this implementation task.

## Controller freeze verification and internal-review package

- Controller independently matched baseline `197418ed01b2ea6883144d42282c8e3871d97910`, implementation HEAD `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`, direct parent, one commit, 24 changed files, `2930 insertions(+), 223 deletions(-)`, and clean tracked/untracked status.
- Fresh controller focused command used the assigned Python, offline `PYTHONPATH`, `-p no:cacheprovider`, and unique absolute basetemp `task9-controller-focused-001`; result exit `0`, `39 passed in 29.97s`. Fresh Node runtime result was exit `0`, `9 passed`.
- Controller py_compile of every changed Python file, Jinja parse of all 9 changed/new templates, `node --check`, full-range `git diff --check`, frozen migrations, and Blueprint SQL guard all exited `0`. The two controller-only basetemp/pycache directories were resolved as direct children of the allowed SDD `test-tmp` root, removed by exact literal path, and the root ended with zero children.
- The first review-package invocation produced no file because its intentionally restricted Git Bash PATH omitted `/cmd` and therefore could not find `git`; it is excluded as a tooling invocation error. Re-running the same skill script with explicit `/cmd:/mingw64/bin:/usr/bin:/bin` generated `.superpowers/sdd/2026-08-24-content-catalog-publishing/review-197418e..a83fa14.diff`.
- Frozen package: 1 commit, 24 files / 24 diff headers, 165654 bytes, 3958 PowerShell text lines, SHA-256 `5037FC1EF86D0F508203320F5036FBBE8FE259DFBE0583656E14D0C007468BD6`; exact reverse apply check exited `0`.
- The one and only Task 9 full remains `1371 passed in 817.24s`; controller did not rerun full. Task 10, deployment, production infrastructure, real database/network, and public exposure remain frozen while a new read-only reviewer examines this package.

## Fresh internal review — Needs fixes

- Two independent fresh read-only reviewers examined the complete frozen range `197418ed01b2ea6883144d42282c8e3871d97910..a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`. Both matched HEAD/branch, 1 commit, 24 files/headers, 165654 bytes, 3958 lines, package SHA-256 `5037FC1EF86D0F508203320F5036FBBE8FE259DFBE0583656E14D0C007468BD6`, reverse apply and clean status; neither ran tests, wrote files, used network or touched real resources.
- P1: public media authorization checks only published/publish-at references, not resource source freshness, announcement validity or raw persisted public completeness. A future/expired announcement or a resource at `checked_at + 7d + 1s` can have a 404 detail while its referenced bytes remain available, currently with a one-year immutable cache policy.
- P1: `load_content_draft()` may raise `ContentContractError` before the validation catch. A bounded SQLite BLOB in the first due resource can abort the whole batch and prevent a later healthy due announcement from publishing.
- P2: service-related resources are projected by status only, unlike related cases; stale or malformed resources can leak their title after their own detail has failed closed.
- P2: scenario/industry resource relations are not projected publicly, while service resources render as non-navigable text. The three governed owner→resource relation sets therefore do not all produce safe public links.
- P2: central source/CTA URL validation has protocol/shape checks but no 2048-character server boundary; bypassing the browser `maxlength` can persist and render oversized URLs.
- Fix1 is restricted to these five findings and direct regression coverage. It must use real RED→minimal GREEN, preserve the sole full result as evidence only for `a83fa14`, and must not rerun full or start Task 10.

## Fix round 1 — close resource publication boundaries

### Frozen scope and method

- Fix1 baseline: `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2` on `codex/ai-platform-2.0-core`; the worktree was clean at entry.
- Fix1 commit: `48333f9722f0976b454ef37b01d80829247691f6` (`fix: close resource publication boundaries`), exactly 11 files, `898 insertions(+), 75 deletions(-)`.
- Scope remained exactly the two P1 and three P2 findings above. Task 10/11 work, deployment and production infrastructure remained frozen.
- All test invocations used the assigned interpreter `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe`, offline `PYTHONPATH=.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps`, `-p no:cacheprovider`, and a unique absolute basetemp below `.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp`. Tests used temporary SQLite/media roots and mocked time/transport only; no real network was used.

### Real RED evidence and minimal GREEN

The command shape for every row was:

```powershell
$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest <files-or-node-ids> -q -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\<suffix>'
```

| Finding / selected tests / basetemp suffix | Accepted RED | GREEN |
| --- | --- | --- |
| Media current-public authorization: `tests/test_media_http.py -k "public_announcement_media_follows_exact_current_interval or public_resource_media_follows_exact_seven_day_source_freshness or public_media_rejects_malformed_legacy_reference or public_media_allows_a_healthy_shared_reference"`; `task9-fix1-red-media-001` | **7 failed, 3 passed, 22 deselected in 8.99s**, exit 1. Outside announcement intervals and stale/malformed resource references still returned bytes; exact boundaries and a healthy shared reference were controls. | Same 10 cases: **10 passed, 22 deselected in 8.13s**, exit 0. Media reads now validate every resource/announcement reference inside one explicit read snapshot; one current complete reference authorizes the asset. Public media uses `public, max-age=0, must-revalidate` while retaining ETag, `nosniff` and disposition behavior. |
| Persisted BLOB draft boundary: the two `test_*blob*` cases in `tests/test_resources_announcements.py`; Fix1 RED BLOB basetemp | **2 failed in 2.40s**, exit 1. Direct/due paths leaked `ContentContractError`, and the due batch did not reach the healthy announcement. | **2 passed in 1.82s**, exit 0. Only `ContentContractError` from persisted aggregate construction is converted to stable `ContentValidationError("extension_invalid")`; database/programming exceptions remain unmasked. Direct replacement preserves the old public revision; due failure clears scheduling, increments the lock, emits only `{"reason_code":"validation_failed"}`, and the later announcement publishes. |
| URL boundary domain cases in `tests/test_content_validation.py`; `task9-fix1-red-url-domain-*` | **6 failed, 3 passed, 142 deselected in 0.39s**, exit 1. Raw and normalized source/CTA URLs exceeded the server boundary. | **9 passed, 142 deselected in 0.08s**, exit 0. Raw and normalized source URLs, announcement CTAs and block CTAs now have exact-string and 2048-character URL checks; dangerous protocol errors retain stable priority. |
| URL boundary admin/legacy HTTP cases in `tests/test_resources_announcements.py`; `task9-fix1-red-url-http-*` | **4 failed, 5 passed, 41 deselected in 5.74s**, exit 1. Oversized URL forms persisted or legacy rows remained public. | **9 passed, 41 deselected in 5.55s**, exit 0. Source and announcement CTA values at exactly 2048 pass and 2049 fail; legacy source/announcement/block values fail closed. The binding plan independently caps an entire block `settings_json` at 2,000 bytes, so a block CTA has a stricter effective aggregate limit: the HTTP control uses a 1,900-character valid block CTA and still proves 2,049 rejection without weakening the frozen 2 KB contract. |
| Formal service/scenario/industry resource links in `tests/test_resources_announcements.py`; Fix1 relation happy-path RED basetemp | **3 failed in 2.58s**, exit 1: all three owners lacked a navigable resource link. | **3 passed in 2.44s**, exit 0. A shared ordered projection validates resources in the owner read snapshot and all three templates link to the canonical resource detail route. |
| Owner relation archive/stale/corrupt lifecycle matrix; Fix1 relation lifecycle RED basetemp | **9 failed in 6.54s**, exit 1: every case first failed on the absent healthy pre-mutation link, proving the setup was public rather than malformed. | **9 passed in 6.95s**, exit 0. Healthy targets render; archived, source-check `7d+1s`, and raw-corrupt targets are omitted while the owner page remains public. |

The first combined focused GREEN attempt produced **243 passed, 2 failed in 63.72s**. Both were test-harness errors: two direct media helper slugs contained underscores and therefore failed the existing public `slug_invalid` gate only after Fix1 correctly invoked full public completeness. The helper now uses valid hyphenated slugs and explicitly asserts its reference is public-complete. The two exact regressions then passed (**2 passed in 1.73s**). This was not a product-code regression.

Two additional harness/contract corrections were made before accepting RED:

- the source/announcement helper fixtures now create formally complete entry-type extensions and valid image/download settings, so failures measure current-public authorization rather than unrelated completeness;
- legacy block URL corruption uses an explicit temporary `PRAGMA ignore_check_constraints=ON` abnormal-data injection because the frozen database check correctly rejects 2,049-byte `settings_json` in ordinary writes.

### Frozen focused and related verification

Exact final commands and legal terminal summaries:

```powershell
& '<assigned-python>' -m pytest tests/test_resources_announcements.py tests/test_media_http.py tests/test_content_validation.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix1-focused-002'
# 245 passed in 65.82s (0:01:05), exit 0

& '<assigned-python>' -m pytest tests/test_content_publishing.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix1-partition-publishing-001'
# 90 passed in 58.79s, exit 0

& '<assigned-python>' -m pytest tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix1-partition-public-001'
# 344 passed in 185.66s (0:03:05), exit 0

& '<assigned-python>' -m pytest tests/test_catalog_content_admin.py tests/test_validation_and_errors.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py tests/test_smoke.py tests/test_media_service.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix1-partition-adjacent-001'
# 158 passed in 94.19s (0:01:34), exit 0
```

These commands cover the complete Fix1 focused files plus publishing/due isolation, media service/HTTP, public catalog/services/cases, admin validation, audit/rate-limit/security and smoke behavior. No JavaScript file changed, so Node was not rerun.

### Static gates and evidence boundary

All final gates exited 0:

- assigned Python `-m py_compile` over the five changed production Python files and all three changed Python test files;
- Jinja parse of `industry_detail.html`, `scenario_detail.html`, and `service_package_detail.html` (**3 templates parsed**);
- `git diff --check`;
- `git diff --exit-code a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2 -- migrations`;
- changed-JavaScript guard: **0 files**;
- changed Blueprint SQL/transaction guard: **0 hits**;
- Task 9 public-template source-check/hash private-field guard: **0 hits**;
- revocable-media immutable/one-year-cache guard: **0 hits**, with the exact must-revalidate header present;
- Task 9 content source/CTA `_blank` links all carry exact `rel="noopener noreferrer"`;
- route/path and endpoint ownership uniqueness is asserted by `test_v2_routes_have_single_owners_and_remove_legacy_admin_writers`, included in the 245-test focused result.

An intentionally over-broad diagnostic scan over every site `_blank` link found two pre-existing non-Task-9 links in `admin_navigation.html` and `footer.html` with `rel="noopener"`. They are outside the reviewed resource/announcement source/CTA boundary and are assigned to the later global security/navigation task; the correctly scoped Task 9 guard passed. No out-of-scope template was changed to hide this fact.

The sole frozen Task 9 full suite remains **1371 passed in 817.24s, exit 0**, executed once at baseline implementation commit `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`. Per review instructions it was **not rerun** and does **not** constitute full-suite evidence for Fix1. Fix1 is instead supported by the focused and risk-partition results above.

After preserving the terminal summaries, cleanup resolved the allowed SDD `test-tmp` root, verified every target was a direct child whose name matched `task9-fix1-*`, and removed exactly **18** disposable basetemp directories; **0** matching directories remained.

### Fix1 file scope and boundaries

Production files changed:

- `blueprints/media.py`
- `catalog_content_repository.py`
- `content_validation.py`
- `media_service.py`
- `publishing_repository.py`
- `templates/industry_detail.html`
- `templates/scenario_detail.html`
- `templates/service_package_detail.html`

Regression files changed:

- `tests/test_content_validation.py`
- `tests/test_media_http.py`
- `tests/test_resources_announcements.py`

No migration, JavaScript, progress ledger, external upgrade card or deployment file changed. No network, dependency installation, production/server/Nginx/systemd/real-database action, deployment or public exposure occurred. Task 10 was not started.

### Controller Fix1 verification and fresh net package

- Controller independently matched Fix1 HEAD `48333f9722f0976b454ef37b01d80829247691f6`, parent `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`, the exact 11-file Fix1 scope and clean tracked/untracked status.
- Fresh controller selector covered current-public media, raw malformed media, shared-reference authorization, raw/normalized URL length, dangerous URL priority, admin/legacy URL boundaries, service runtime completeness, all three owner links/lifecycle, BLOB direct replacement and BLOB due isolation. Result: exit `0`, `41 passed in 19.44s` with unique basetemp `task9-controller-fix1-focused-001`.
- Controller py_compile, three-template Jinja parse, Fix1-range diff check, frozen migration check, Blueprint SQL guard and exact revocable cache-header guard all exited `0`. Its two controller-only temp directories were resolved as direct children of the SDD test root and removed; zero children remained.
- Fresh complete net package `.superpowers/sdd/2026-08-24-content-catalog-publishing/review-197418e..48333f9.diff`: 2 commits, 31 files / 31 diff headers, 236728 bytes, 5601 PowerShell text lines, SHA-256 `EFE80B556ACD2A821BF8241334F00244350B78490463F4986F05A4F2858DB534`; exact reverse apply exited `0`.
- Full boundary remains explicit: the only full `1371 passed` covers `a83fa14`, not Fix1. No full was rerun. A brand-new read-only reviewer now examines the full net package; Task 10 and all deployment/public exposure remain frozen.

## Fresh Fix1 re-review — Needs fixes

- The brand-new read-only reviewer independently matched HEAD `48333f9722f0976b454ef37b01d80829247691f6`, 2 commits, 31 files/headers, 236728 bytes, 5601 lines, package SHA-256 `EFE80B556ACD2A821BF8241334F00244350B78490463F4986F05A4F2858DB534`, reverse apply and clean status. It ran no tests, wrote no files and used no network.
- P1: media authorization fully validates resource and announcement references, but `case/industry/scenario/service` still take a wildcard success branch. A malformed published owner whose detail fails closed can therefore continue authorizing bytes.
- P1: the `ContentContractError` catch surrounds final `ContentDraft` construction but not earlier persisted `ContentBlock`, `ContentRelation` or `CaseMetric` construction. Non-finite JSON such as `NaN` can still escape and abort a due batch.
- P2: CTA settings are checked against the frozen 2,000-byte aggregate limit before URL normalization. Percent-encoding a Unicode URL can expand the normalized settings beyond 2,000 bytes and reach the SQLite CHECK as an unhandled integrity error.
- Findings C and D are ADDRESSED: service runtime resource completeness and all three ordered/navigable owner projections are closed. The central 2048 URL boundary is also addressed except for the normalized aggregate-size ordering above.
- Fix2 is limited to these three findings and direct regressions. It must preserve the sole full as evidence only for `a83fa14`, run no full and start no Task 10 work.

## Fix round 2 — complete public content revalidation

### Frozen scope and review verification

- Fix2 baseline: `48333f9722f0976b454ef37b01d80829247691f6` on `codex/ai-platform-2.0-core`, with a clean worktree at entry.
- Fix2 commit: `4e5be5c2b93788e2d77e4c8a2d9aef1c5ad1f30d` (`fix: complete public content revalidation`), exactly 7 files, `377 insertions(+), 30 deletions(-)`.
- The three review findings were verified against the implementation before editing: the media reference loop had an unconditional non-resource/announcement success branch; persisted child contracts were constructed before the existing `ContentContractError` catch; and CTA settings were measured only before URL percent-encoding.
- Two read-only reconnaissance agents independently traced the media/public projection dependency and the persisted-contract/CTA data flows. They made no edits, ran no full suite and used no network.
- All pytest commands used the assigned interpreter, offline `PYTHONPATH=.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps`, `-p no:cacheprovider`, and a unique absolute basetemp under the SDD `test-tmp` root. All state was temporary SQLite/media data with fixed local clocks; no real resource or network was used.

### Accepted RED → minimal GREEN

Common command prefix:

```powershell
$env:PYTHONPATH='.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest <node-ids> -q -p no:cacheprovider --basetemp='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\test-tmp\<suffix>'
```

| Finding / exact node selection | Accepted RED | Minimal GREEN |
| --- | --- | --- |
| `tests/test_media_http.py::test_public_media_requires_the_same_complete_projection_as_every_public_detail`; `task9-fix2-red-media-001` | **4 failed in 4.17s**, exit 1. Each case/industry/scenario/service fixture first proved detail and media were 200; after a real public-completeness break the detail was 404 while media remained 200. | **4 passed in 2.91s**, exit 0. A caller-owned `has_current_public_projection(db, content_id, now)` reuses the same active connection/snapshot, validates case through `validate_case_public_completeness`, and dispatches industry/scenario/service through their exact public projectors. Unknown types return false. The media loop continues past bad references and authorizes only when at least one healthy shared reference exists. |
| `test_direct_replacement_converts_nonfinite_persisted_block_to_validation_error` plus `test_due_nonfinite_block_isolated_and_later_announcement_publishes`; `task9-fix2-red-nan-001` | **2 failed in 2.42s**, exit 1. Python JSON accepted injected `NaN`, `ContentBlock` freezing raised a raw `ContentContractError`, and the due batch stopped before the later healthy announcement. | **2 passed in 1.44s**, exit 0. All persisted `ContentBlock`, `ContentRelation`, `CaseMetric`, and final `ContentDraft` construction now occurs inside one helper called from a catch that handles **only** `ContentContractError`, mapping it to stable `ContentValidationError("extension_invalid")`. SQL/programming/`ContentJsonError`/arbitrary exceptions are not caught. Direct replacement preserves the old public revision; due isolation clears schedule, increments lock, writes only the safe validation reason, and publishes the later announcement. |
| `tests/test_content_validation.py::test_cta_normalized_settings_respect_the_frozen_two_kibibyte_aggregate_limit`; `task9-fix2-red-cta-domain-001` | **1 failed, 1 passed in 0.39s**, exit 1. The 215-Unicode control normalized to exactly 2,000 bytes and passed; 216 normalized to 2,009 bytes but was not rejected. | **2 passed in 0.07s**, exit 0. CTA settings are serialized and measured again after URL normalization; 2,000 bytes pass and 2,009 bytes raise `block_settings_too_large`. |
| `tests/test_resources_announcements.py::test_admin_cta_revalidates_the_two_kibibyte_limit_after_url_normalization`; `task9-fix2-red-cta-http-001` | **1 failed, 1 passed in 2.23s**, exit 1. The 216-Unicode request returned 500 from SQLite `IntegrityError`; its transaction had no residual row. The exact 2,000-byte control returned 302. | **2 passed in 1.49s**, exit 0. The oversized normalized request now returns HTTP 400 from central validation, with no content row/audit residue; the exact-boundary request persists a 2,000-byte settings object. |

The accepted media RED used formal publication for every target revision, an uploaded ready image, an HTTP 200 control before corruption, an HTTP 404 detail after the completeness break, and a healthy same-asset announcement reference after the denial assertion. Case corruption temporarily removed and restored the exact immutable-child trigger; core catalog corruption used published→archived authority state. The NaN fixture explicitly toggled `PRAGMA ignore_check_constraints` only around the abnormal draft-row injection because SQLite correctly rejects non-standard JSON in normal writes.

### Fresh Fix2 verification

```powershell
& '<assigned-python>' -m pytest tests/test_media_http.py::test_public_media_requires_the_same_complete_projection_as_every_public_detail tests/test_resources_announcements.py::test_direct_replacement_converts_nonfinite_persisted_block_to_validation_error tests/test_resources_announcements.py::test_due_nonfinite_block_isolated_and_later_announcement_publishes tests/test_resources_announcements.py::test_admin_cta_revalidates_the_two_kibibyte_limit_after_url_normalization tests/test_content_validation.py::test_cta_normalized_settings_respect_the_frozen_two_kibibyte_aggregate_limit -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix2-focused-exact-001'
# 10 passed in 6.41s, exit 0

& '<assigned-python>' -m pytest tests/test_resources_announcements.py tests/test_media_http.py tests/test_content_validation.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix2-focused-task9-001'
# 255 passed in 74.61s (0:01:14), exit 0

& '<assigned-python>' -m pytest tests/test_content_publishing.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix2-partition-publishing-001'
# 90 passed in 50.85s, exit 0

& '<assigned-python>' -m pytest tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix2-partition-public-001'
# 344 passed in 192.15s (0:03:12), exit 0

& '<assigned-python>' -m pytest tests/test_catalog_content_admin.py tests/test_validation_and_errors.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py tests/test_smoke.py tests/test_media_service.py -q -p no:cacheprovider --basetemp='<absolute-test-tmp>\task9-fix2-partition-adjacent-001'
# 158 passed in 88.37s (0:01:28), exit 0
```

Static gates, all exit 0:

- assigned Python `-m py_compile` over the four changed production Python files and three changed test files;
- `git diff --check`;
- `git diff --exit-code 48333f9722f0976b454ef37b01d80829247691f6 -- migrations`;
- changed JavaScript files: **0**, so Node was not rerun;
- public/media Blueprint SQL/transaction hits: **0**;
- public-template source-check/hash private-field hits: **0**;
- revocable media has no immutable/one-year cache token and retains the exact `public, max-age=0, must-revalidate` header;
- route/path and endpoint uniqueness remained covered by the full Task 9 focused file.

No template changed, so no Jinja parse was required. The sole historical Task 9 full remains **1371 passed in 817.24s, exit 0** at `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`; it was not rerun and does not claim coverage of Fix1 or Fix2.

After recording every terminal summary, cleanup resolved the allowed SDD `test-tmp` root, verified each target was a direct child named `task9-fix2-*`, and removed exactly **11** disposable basetemp directories; **0** matching directories remained.

### Fix2 file scope and hard boundaries

Production:

- `catalog_content_repository.py`
- `content_validation.py`
- `media_service.py`
- `publishing_repository.py`

Regression coverage:

- `tests/test_content_validation.py`
- `tests/test_media_http.py`
- `tests/test_resources_announcements.py`

No migration, template, JavaScript, progress ledger, external upgrade card or deployment file changed. No network, dependency install, production/server/Nginx/systemd/real-database action, deployment or public exposure occurred. Task 10 was not started.

### Controller Fix2 verification and fresh complete package

- Controller independently matched Fix2 HEAD `4e5be5c2b93788e2d77e4c8a2d9aef1c5ad1f30d`, parent `48333f9722f0976b454ef37b01d80829247691f6`, the exact seven-file Fix2 scope and clean tracked/untracked status.
- Fresh controller exact selection repeated the four-entry public-media projection matrix, direct/due NaN aggregate isolation and normalized CTA aggregate-size domain/HTTP boundary: exit `0`, `10 passed in 5.41s`, unique basetemp `task9-controller-fix2-focused-001`.
- Controller pycompile, Fix2-range diff check, frozen migration check, Blueprint SQL guard and exact revocable cache-header guard all exited `0`. The two controller-only temp directories were safely removed and the SDD test root ended empty.
- Fresh complete net package `.superpowers/sdd/2026-08-24-content-catalog-publishing/review-197418e..4e5be5c.diff`: 3 commits, 31 files / 31 diff headers, 251220 bytes, 5973 PowerShell text lines, SHA-256 `C4D5F4188503FDCBCE7B93EE41E00802C77B703A75E915B42C89A6667DC24D7D`; reverse apply exited `0`.
- The sole full `1371 passed` remains scoped to `a83fa14`; Fix1/Fix2 have focused/partition evidence only. A third fresh read-only reviewer now examines the complete package. Task 10/full/deployment/public exposure remain frozen.

## Fresh Fix2 re-review CLEAN

- The third brand-new read-only reviewer judged the complete range `197418ed01b2ea6883144d42282c8e3871d97910..4e5be5c2b93788e2d77e4c8a2d9aef1c5ad1f30d` `CLEAN`, with no new P0—P3.
- Fix2 A is closed: one connection/`BEGIN` snapshot validates resource, announcement, case, industry, scenario and service references through the exact public detail gates; unknown types deny, a healthy shared reference authorizes, and revocable media retains ETag/`nosniff`/disposition with `must-revalidate`.
- Fix2 B is closed: all persisted block/relation/metric/final-draft construction lives in one helper and only `ContentContractError` is converted; JSON/SQLite/programming/arbitrary errors are not swallowed. Direct and due tests prove old-public atomicity, later-candidate isolation and safe audit.
- Fix2 C is closed: normalized CTA settings are remeasured against the frozen 2,000-byte aggregate limit; central 2,048-character/protocol/NUL/error-priority behavior, HTTP 400 and zero residue are preserved.
- The reviewer also reconfirmed the five Fix1 findings and full Task 9 net requirements: exact source freshness and announcement interval, attachment MIME, ordered/navigable three-owner resource relations, read snapshots, auth/CSRF/lock/audit, legacy route ownership and external-link policy. Package facts matched 3 commits, 31 files/headers, 251220 bytes, 5973 lines and SHA-256 `C4D5F4188503FDCBCE7B93EE41E00802C77B703A75E915B42C89A6667DC24D7D`; reverse apply, frozen migrations, diff and clean status passed. Reviewer ran no tests/network and made no writes.
- After CLEAN, controller repeated the exact Fix2 selector in a fresh `task9-controller-fix2-post-review-001` basetemp: exit `0`, `10 passed in 4.85s`. It then removed that exact temp directory, reconfirmed package SHA/reverse apply, full-range diff and clean HEAD `4e5be5c2b93788e2d77e4c8a2d9aef1c5ad1f30d`.
- Evidence boundary remains honest: the one and only full `1371 passed in 817.24s` covers main implementation `a83fa14` only; Fix1/Fix2 are covered by focused and affected partitions, not a final-HEAD full. Task 9 now enters external review; Task 10 and deployment remain frozen until the exact gate phrase is returned.

## 外部独立审查 CLEAN

- “审查企业AI转型平台”对最终净范围 `197418ed01b2ea6883144d42282c8e3871d97910..4e5be5c2b93788e2d77e4c8a2d9aef1c5ad1f30d` 完成 fresh scoped review。Reviewer 独立核对分支/HEAD、3 commits、31 files/headers、251220 bytes、5973 PowerShell text lines、完整包 SHA-256 `C4D5F4188503FDCBCE7B93EE41E00802C77B703A75E915B42C89A6667DC24D7D`、三份移交哈希、reverse apply、冻结 migrations 和 tracked/untracked clean 状态，未发现 P0—P3。
- 外部 reviewer 逐项复核后台写入、认证/CSRF、发布替换与到期隔离、公开 SQLite 快照、六类内容的媒体授权、资源关系、URL/CTA 边界和 legacy route 唯一所有权；未发现越权写入、公开泄漏、关系绕过或批处理隔离回归。
- 最终 HEAD 的新鲜离线聚焦集 `tests/test_resources_announcements.py tests/test_media_http.py tests/test_content_validation.py` 为 exit `0`、`255 passed`；`node --test tests/js/content_editor_runtime.test.js` 为 exit `0`、`9 passed`。变更 Python 编译、完整范围 `git diff --check`、Blueprint 无直接 SQL 与 clean status 均通过。
- 审查仅使用临时 SQLite、临时媒体和模拟传输；两个明确命名的临时测试目录已清理。Reviewer 未修改项目文件、未运行 full suite、未联网/安装依赖，也未接触生产服务器、Nginx、systemd、真实数据库、真实外网或公网部署。
- Reviewer 已回传精确门禁语 `审查通过，可以继续下一步`。Task 9 正式 CLEAN；Task 10 仅可在 Task 9 的纯文档封板提交后，以该提交为唯一基线启动。
- full 证据边界不变：唯一 `1371 passed in 817.24s` 只覆盖主实现 `a83fa14b8df0bb81e07d3649e34a8f0ae0f21ef2`，不覆盖 Fix1 `48333f97` 或 Fix2 `4e5be5c2`，不得表述为最终 HEAD full PASS。
- 全局发布门禁继续有效：全部功能开发、独立审查和完整测试/验收全部通过前，只允许本地开发与本地演示；不得部署、改动服务器/Nginx/systemd/真实数据库，也不得临时开放公网。
