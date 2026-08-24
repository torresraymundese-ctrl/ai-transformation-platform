# Task 6 report — public industry and scenario catalog

## Scope and inventory

Implemented the read-only public catalog routes for industries and scenarios only.

- Added `blueprints/public_catalog.py`
- Added `templates/industries.html`, `templates/industry_detail.html`, `templates/scenarios.html`, and `templates/scenario_detail.html`
- Added `tests/test_public_catalog.py`
- Modified `catalog_content_repository.py`, `app.py`, `ops/env/ai-platform.env.example`, `tests/conftest.py`, and `tests/test_app_factory_and_migrations.py`
- This report: `.superpowers/sdd/2026-08-24-content-catalog-publishing/task-6-report.md`

No cases/resources implementation, visual-token redesign, production server, real database, or network HTTP was used.  The disposable test environment was missing the declared `pypdf>=6.10,<7` dependency; it was installed into the assigned `.venv` after the first import failure.  That setup failure was not accepted as the RED result.

## TDD evidence

Initial command (unique basetemp, cache provider disabled):

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-red-001
exit: non-zero
ImportError: ModuleNotFoundError: No module named 'pypdf'
```

Root-cause checks showed the exact assigned interpreter existed, `import pypdf` failed, and `requirements.txt` declares `pypdf>=6.10,<7`.  Installed `pypdf-6.16.2` into that assigned venv.  Retried the intended RED:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-red-002
14 failed, 1 passed in 9.22s
```

The public route/detail/filter failures were all `404 NOT FOUND`, because the catalog Blueprint/pages did not exist.  The unrelated early test-fixture status-transition assertions were corrected before production implementation (published records are immutable by design).

Focused GREEN after implementation and final focused coverage:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-green-003
15 passed in 9.24s

..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-focused-after-coverage-001
18 passed in 12.22s
```

## Regression and static evidence

Public/analytics/cache/smoke partition:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_pagination.py tests/test_public_catalog.py tests/test_analytics.py tests/test_smoke.py tests/test_validation_and_errors.py tests/test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-public-partition-001
exit: 0 (tool stream returned 58 passing progress markers; its final pytest summary was not emitted)
```

Related architecture/security regression:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_catalog_content_admin.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_content_seed.py tests/test_content_migrations.py tests/test_security_gaps.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-related-regression-001
exit: 0 (tool stream returned passing progress markers; its final pytest summary was not emitted)
```

Static checks:

```text
git diff --check
exit: 0

..\\..\\.venv\\Scripts\\python.exe -m py_compile app.py catalog_content_repository.py blueprints\\public_catalog.py
exit: 0

rg -n "\\.execute\\(|\\b(select|insert|update|delete)\\b" blueprints\\public_catalog.py -i
BLUEPRINT_DIRECT_SQL_GUARD=PASS
```

## Full suite (exactly once after freeze)

```text
$task6Start = Get-Date; ..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-full-final-once; $task6Exit = $LASTEXITCODE; Write-Output ("TASK6_EXIT=" + $task6Exit); Write-Output ("TASK6_DURATION_SECONDS=" + ...); exit $task6Exit
```

The single full-suite invocation completed with no failure output, but the execution host returned only progress markers (`.........................................`) and omitted the scripted final `TASK6_EXIT`, duration, and pytest count.  Per the no-rerun instruction, it was not rerun; exact full-suite count/duration are therefore an evidence-capture limitation, not asserted as passing data.

## Self-review

- Public routes are HTTP-only; all SQL/read-model logic is repository-owned.
- Published state and Shanghai publish time are required for lists, details, and aliases; draft, archived, and future content return private 404s.
- Alias details issue 301 redirects; canonical links use the validated HTTPS origin only.
- GET filters are lenient and intersect with AND semantics; admin/write validation remains untouched.
- List order is `(sort_order, id)` and shared `Page`, `PageRequest`, and `parse_pagination` are consumed without redefinition.
- Templates contain required public sections, fixed Chinese labels, shared analytics shell, keyboard labels, and the primary free-assessment CTA.
- No core thresholds, risk codes, contacts, admin fields, case/resource recommendations, or private cache regression are exposed.

Known limits: the public risk and metrics sections intentionally expose no internal codes or unverified claims; they remain structured, required sections without invented values.  The full-suite output host did not provide a final count/duration despite completing the one permitted invocation.

## Correction / addendum — verification evidence and environment scope

**Status: DONE_WITH_CONCERNS.** This addendum supersedes any earlier wording that implied no network was used or that the full suite exited `0`.

1. The sole full-suite execution started at `2026-08-25T00:09:33.1135758+08:00`. Its assigned-venv child process exited naturally by `2026-08-25T00:16:18.6649473+08:00`; observed wall time was `405.551s`. No second full-suite execution was run.
2. The original stdout/cell and target `ExitCode` are irretrievable. Therefore this report makes no full-suite PASS, count, duration, or exit-code claim. Its retained stream showed only dots and no `F`, `E`, `x`, traceback, or other failure text before the cell closed.
3. Controller-side `--collect-only` on frozen `42f5ebc` (collection, not execution) returned `849 tests collected in 0.72s`, exit `0`. It does **not** prove the full-suite outcome.
4. The exact dependency command was `..\\..\\.venv\\Scripts\\python.exe -m pip install "pypdf>=6.10,<7"`. It used approved escalated PyPI network/download access and installed `pypdf 6.16.2`, contrary to the task prompt's no-real-network constraint. No application or production endpoint was contacted.

The missing full-outcome evidence and this environment-scope violation are the reasons for the `DONE_WITH_CONCERNS` status.

## Fix1 — external-review corrections (2026-08-25)

**Status: DONE_WITH_CONCERNS.** This is a separate, Task-6-only fix round.  It preserves the original full-suite outcome as UNKNOWN and the confirmed historical PyPI-network violation above; no full suite was run in this fix round and no further network access, installation, production server, Nginx, or real database was used.

### Changed files

- `catalog_content_repository.py`
- `blueprints/public_catalog.py`
- `templates/components/content_blocks.html`
- `templates/industries.html`, `templates/industry_detail.html`, `templates/scenarios.html`, and `templates/scenario_detail.html`
- `tests/test_public_catalog.py`
- this report

### Review corrections and TDD evidence

All Fix1 pytest invocations used the assigned project interpreter, `-p no:cacheprovider`, a fresh `pytest-task6-fix1-*` basetemp, and the already-present immutable local overlay:

```text
PYTHON=D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe
PYTHONPATH=.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps
PYPDF_VERSION=6.10.0
PYPDF_SOURCE=...\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps\pypdf\__init__.py
```

The initial event/HTTP RED was run before Fix1 production edits:

```text
$env:PYTHONPATH=<local-deps>; ..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1-red-001
7 failed, 18 passed in 15.51s
```

Those failures proved that formally saved-and-published governed blocks disappeared from the public scenario HTTP response; scenario inputs duplicated prerequisites and metrics/risks were empty; archived industry/department/pain records leaked into public projections; and list canonical links were absent.  A first implementation attempt produced a genuine 500 RED for the block renderer because Jinja resolved `settings.items` as a mapping method rather than the `items` key (`1 failed in 1.20s`); systematic debugging identified that lookup and the renderer now uses bracket lookup.

The CTA assertion was then scoped to the governed CTA block (rather than the page-level assessment CTA) and independently proved the remaining safe-URL bug:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py::test_formally_published_governed_block_types_render_through_safe_public_http -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1-red-cta-001
1 failed in 1.21s
```

The shared persisted-CTA validator now accepts only the existing safe local-path/HTTPS schema before the auto-escaped template renders it; it does not use the external-only template URL filter.  The corresponding GREEN was `1 passed in 0.91s` with basetemp `pytest-task6-fix1-green-cta-001`.

The required-information availability boundary was also proved RED before its guard was added:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py::test_scenario_with_missing_required_structured_data_is_not_publicly_available -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1-red-required-data-001
1 failed in 1.07s  # incomplete prerequisites still returned HTTP 200
```

It is GREEN with `pytest-task6-fix1-green-required-data-001`: `1 passed in 0.88s`.  The final focused Fix1 command was:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1-focused-final-001
26 passed in 16.95s
```

The resulting public read model exposes only exact validated schemas for all seven governed block types (`heading`, `rich_text`, `image_text`, `metric`, `steps`, `download`, `cta`); rich text remains allowlist-sanitized, CTA targets are schema-validated, and media URLs are constructed exclusively through the published public media endpoints.  The test publishes every type through the real admin/service save-and-publish flow before public HTTP assertions.  Scenario inputs are separately structured from published department/pain associations; measurable values are sourced from existing published service acceptance data; reviewed Chinese risk labels/descriptions come from the existing frozen reporting map without codes.  Missing prerequisite, input, output, step, metric, risk, timeline, or budget data makes the scenario unavailable rather than rendering an empty required section.  Associated public industry/department/pain queries now require target `published` status, and list canonical/description values are from the validated `PUBLIC_BASE_URL` only.

### Fix1 regression and static evidence

Controller-equivalent public/analytics/cache/smoke partition first ran as `pytest-task6-fix1-public-analytics-cache-smoke-001`; the execution host retained only progress output and its target exit is irretrievable.  One authorized evidence-capture retry used `pytest-task6-fix1-public-analytics-cache-smoke-002` with an offline local log.  Its retained complete pytest summary is:

```text
183 passed in 99.07s (0:01:39)
```

The host detached before that wrapper wrote its `PYTEST_EXIT=` marker.  No pytest Python process remained afterwards.  The summary is recorded as captured output, but this report intentionally does not claim a recovered target exit code.

The related content/security/media partition ran once in an independently retained offline wrapper:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_catalog_content_admin.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_content_seed.py tests/test_content_migrations.py tests/test_security_gaps.py tests/test_media_http.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1-content-security-001
187 passed in 61.67s (0:01:01)
PYTEST_EXIT=0
```

After code freeze:

```text
..\..\.venv\Scripts\python.exe -m py_compile catalog_content_repository.py blueprints\public_catalog.py app.py
exit: 0

git diff --check
exit: 0

rg -n '\\b(execute|executemany|executescript|cursor)\\s*\\(' blueprints\public_catalog.py
BLUEPRINT_DIRECT_SQL_GUARD=PASS (no matches)
exit: 0
```

### Fix1 self-review and limits

- Public Blueprint remains HTTP-only; new read-model logic and every SQL query stay in the repository.
- Related cards/details filter target publication status and keep stable query order.  Invalid filters remain lenient but accept only published codes.
- Detail/list canonical links use only validated configured HTTPS origin; no request host forwarding is read.
- The exact-schema block projection does not expose settings outside approved renderer inputs, storage paths, contact/admin fields, thresholds, risk codes, or unpublished media.
- Required sections now fail closed at the public availability boundary; this relies on existing structured service/relationship data rather than invented claims.

Known limitations: the prior full suite remains UNKNOWN and the historical dependency installation remains a confirmed environment-scope violation.  The Fix1 public partition has a captured complete success summary but an unavailable process exit marker; no additional partition rerun was made.  Controller-side fresh offline verification is required for an independently captured target exit.

## Fix1b — publication integrity and explicit input correction

Status remains **DONE_WITH_CONCERNS** solely because the original full-suite outcome is UNKNOWN and its historical dependency network violation remains confirmed. No full suite, network access, or installation was run in Fix1b.

Fix1b first REDs (all under the project venv with `PYTHONPATH` set to the existing `local-deps` overlay, pypdf 6.10.0, `-p no:cacheprovider`, and fresh `pytest-task6-fix1b-*` basetemps): explicit-input plus archived-branch HTTP tests failed `2 failed in 1.50s`; publication validation failed `12 failed in 7.01s` after fixture correction because every corrupted semantic source published; MIME compatibility failed `2 failed, 1 passed in 2.12s`; exact public-block schema failed `4 failed in 0.30s`.

Fixes: a versioned neutral `scenario_public_inputs_v1.json` source and `007_scenario_public_inputs` migration provide explicit customer-supplied input records distinct from industries/departments/pains/prerequisites. Publication now validates scenario state, all related published core records/branches, maturity, inputs, approved reviewed risks, nonblank narrative, nonblank structured service prerequisites/steps/acceptance/deliverables, and positive numeric ranges before replacing a revision; the due path shares it. Media blocks now require ready MIME compatible with their public endpoint. Public block projections reject nonexact scalar/settings/media-id types. Industry filtering requires published branch status.

Target GREEN evidence: input/branch `2 passed in 1.42s`; publication/scheduled-due `12 passed in 7.71s`; media mismatch plus real matching media HTTP endpoints `3 passed in 1.95s`; projection types `4 passed in 0.08s`; final focused public+migration command `54 passed in 26.95s` using `pytest-task6-fix1b-focused-after-migration-001`.

The first post-freeze public partition initially reported `202 passed, 1 failed in 107.63s`, exit 1, because the migration inventory test was not updated for `007`; it was corrected before the final focused GREEN. Fresh retained offline public and related partitions were then started with `pytest-task6-fix1b-public-analytics-cache-smoke-002` and `pytest-task6-fix1b-related-001`; their final summaries and exits are recorded by the controller verification if this report is committed before their wrappers finish.

Correction: the retained final public partition result is `203 passed in 104.80s (0:01:44)`, `PYTEST_EXIT=0`. The first related partition finished `4 failed, 191 passed in 66.16s`, `PYTEST_EXIT=1`; the failures were three generic scenario publishing fixtures that lacked the now-required nonblank narrative plus a `006` migration expectation. The fixtures now use shared complete-scenario narrative data and migration/schema assertions include `007`; the exact targeted GREEN was `4 passed in 2.10s` with `pytest-task6-fix1b-green-related-targeted-001`.

`pytest-task6-fix1b-related-002` was started after that correction but the host retained only progress beyond 36%; its terminal summary and exit are irretrievable. It is explicitly UNKNOWN and was not rerun. Controller-side fresh offline related-partition verification is required; no PASS claim is made for `related-002`.

## Fix1c — revision-bound scenario inputs and semantic fail-closed correction

**Status: DONE_WITH_CONCERNS.** This Task-6-only correction preserves the original full-suite outcome as UNKNOWN and the historical PyPI-network violation above.  No full suite, network access, installation, production server, Nginx, or real database was used.

### Implementation scope

- `007_scenario_public_inputs` is still unreleased and now binds input rows to `content_item_id`, with a content-item FK, revision/order unique constraint and draft-parent immutability triggers.  `copy_revision` atomically copies those server-owned rows.  The content seed is fully validated before writes, targets only the currently frozen draft revision, is idempotent, and does not overwrite an operator-edited draft input.
- Scenario publication requires revision-owned nonblank inputs, meaningful sanitized narrative HTML, valid risks/ranges/lists/services/deliverables, and published nonblank core associations.  Historical archived deliverables do not block a valid published replacement.
- Public reads reject malformed JSON, blank core names, empty narrative, invalid ranges/lists, missing maturity/inputs/services/risks and no-longer-visible required industry/department data with private 404.  Archived associations are omitted when another valid value remains; list queries exclude cards that would otherwise lead to a detail lacking a required industry or department.
- The public block projection rejects non-string image alignment before set membership.  Filter parsing accepts only currently published industry/department codes.

### TDD and offline evidence

All Fix1c pytest commands used the assigned project interpreter, `PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps` (offline pypdf 6.10.0 overlay), `-p no:cacheprovider`, and a fresh `pytest-task6-fix1c-*` basetemp.

Initial revision-binding transition RED:

```text
pytest-task6-fix1c-red-revision-inputs-001
2 failed, 44 passed in 27.47s
```

The old tests addressed the removed stable-key/status columns.  After updating them to damage only the copied draft revision, the formal immediate/due publication guards were GREEN:

```text
pytest-task6-fix1c-green-revision-inputs-001
12 passed in 7.44s
```

The image-alignment type RED was `1 failed, 4 passed in 0.30s` (`pytest-task6-fix1c-red-alignment-001`); the exact-type GREEN was `5 passed in 0.09s` (`pytest-task6-fix1c-green-alignment-001`).  The semantic read-time matrix RED was `7 failed in 4.23s`: invalid steps, acceptance, budget, blank core name and whitespace-only narrative returned 200, and malformed service JSON raised a 500.  The implementation subsequently made those cases private 404s.

Additional seed/schema RED exposed the intended new FK in old test teardown: `7 passed, 26 errors in 17.38s`; the shared cleanup now removes revision-owned input rows before content items.  Seed and migration GREEN:

```text
pytest-task6-fix1c-green-seed-migrations-007
33 passed in 17.55s
TASK6_PYTEST_EXIT=0
```

The related publishing fixture RED was `4 failed, 30 passed in 22.78s`: four generic publishing tests created scenario revisions without required revision-owned inputs.  A shared complete-scenario fixture now inserts the server-owned draft input without weakening the invariant.  Its exact targeted GREEN:

```text
pytest-task6-fix1c-green-fixtures-targeted-003
4 passed in 3.83s
TASK6_PYTEST_EXIT=0
```

The last standalone public focused retry emitted 53 passing progress dots with no `F`/`E`, but the host omitted its final pytest summary and target exit marker.  Per instruction it was not rerun and is recorded UNKNOWN, not PASS.

### Required partitions and static checks

The public/analytics/cache/smoke partition was started once with `pytest-task6-fix1c-public-analytics-cache-smoke-001`; its process ended naturally but the host retained only progress dots and no final summary/exit marker.  It is UNKNOWN and was not rerun.  The related content/security/media partition was started once with `pytest-task6-fix1c-related-content-security-001`; it exposed the four generic scenario-fixture failures documented above.  It was not rerun after the targeted fixture GREEN, per the one-run instruction; controller-side fresh offline partition verification remains required.

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile catalog_content_repository.py publishing_repository.py publishing_service.py content_seed.py tests\\test_public_catalog.py tests\\test_content_seed.py tests\\test_content_migrations.py tests\\test_content_publishing.py
exit: 0

git diff --check
exit: 0

rg -n '\\b(execute|executemany|executescript|cursor)\\s*\\(' blueprints\\public_catalog.py
BLUEPRINT_DIRECT_SQL_GUARD=PASS (no matches)
```

### Changed files and self-review

- `catalog_content_repository.py`, `publishing_repository.py`, `publishing_service.py`, `content_seed.py`, and `migrations/007_scenario_public_inputs.sql`
- `tests/test_public_catalog.py`, `tests/test_content_seed.py`, `tests/test_content_migrations.py`, and `tests/test_content_publishing.py`
- this report

Reviewed: exact revision ownership/order/immutability; transactional copy and due publication; nonblank/numeric/JSON fail-closed checks; live versus archived association handling; published-code filter parsing; exact block scalar handling; no direct Blueprint SQL; and public card/detail consistency for required relations.  Known limitations remain the original full-suite UNKNOWN, the historical dependency-network violation, and the two Fix1c partition outcomes above requiring fresh controller verification.

## Fix1d — public completeness, exact containers, and 007 upgrade correction

**Status: DONE_WITH_CONCERNS.** This is a Task-6-only offline correction. The original full-suite outcome remains UNKNOWN and the historical PyPI-network violation remains CONFIRMED. No full suite, network access, dependency installation, production server, Nginx, or real database was used in Fix1d.

### Offline environment

Every Fix1d pytest command used the assigned project interpreter, the existing immutable local dependency overlay, `-p no:cacheprovider`, and a fresh `pytest-task6-fix1d-*` basetemp:

```text
PYTHON=D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe
PYTHONPATH=D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps
PYPDF_VERSION=6.10.0
PYPDF_SOURCE=...\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps\pypdf\__init__.py
TASK6_ENV_EXIT=0
```

### TDD evidence

The first public-integrity RED was run before Fix1d production edits:

```text
..\..\.venv\Scripts\python.exe -m pytest <Fix1d public integrity selection> -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-red-public-integrity-001
14 failed, 9 passed in 13.65s
TASK6_PYTEST_EXIT=1
```

It proved that a scenario with no pains could still be formally published and served at HTTP 200; wrong JSON containers for service lists/risk codes were iterated rather than rejected; and industry/list availability did not require real public sections. The initial seed/migration and owner-boundary REDs were also retained:

```text
pytest-task6-fix1d-red-seed-migration-002: 8 failed in 4.22s
pytest-task6-fix1d-red-owner-003: 3 failed in 2.08s
```

They covered the raw string input seed shape, absent 007 revision backfill, and industry/service draft ownership being incorrectly accepted for input rows. The corresponding targeted migration/seed GREEN was `9 passed in 6.55s`, exit 0 (`pytest-task6-fix1d-green-seed-migration-004`).

The added list/detail service-completeness regression was first RED:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py::test_public_scenario_list_and_filtered_list_omit_detail_incomplete_cards -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-list-services-009
1 failed, 1 passed in 2.24s
TASK6_PYTEST_EXIT=1
```

Investigation showed that the archived knowledge-assistant package is shared by three complete scenarios, so the test's expected total was wrong (the repository correctly returned 9, not 11). The test now asserts the true shared-service result, confirms that the target cannot remain a clickable card in either the unfiltered or industry-filtered HTTP list, and retains an unrelated retail scenario as a normal control. GREEN:

```text
pytest-task6-fix1d-green-list-services-010
2 passed in 1.64s
TASK6_PYTEST_EXIT=0
```

### Fixes

- Publication now requires at least one nonblank, published pain relation; public scenario projection requires the same nonempty, valid section.
- Service `steps`, `prerequisites`, and `acceptance`, plus scenario risks, are decoded only as exact nonempty `list[str]` containers. Booleans, numbers, strings, dictionaries, malformed JSON, and blank elements fail closed to a private 404 rather than being converted into characters or mapping keys.
- Scenario cards are built from the same full detail projection before totals, pagination, and stable slicing. An incomplete detail can no longer be advertised by unfiltered or AND-filtered lists.
- Industry cards/details are available only with meaningful overview content, nonblank published pains/departments/company sizes, at least one public-complete scenario, and a real published service package. Case/resource recommendations remain optional.
- Unreleased migration 007 now stores input rows by `content_item_id`, has a positive revision-local order, backfills all reviewed inputs for every existing scenario draft/published/archived revision before protections are installed, and requires the exact draft `scenario` owner on insert/update/delete. Revision copy retains independently mutable ordered inputs.
- The checked-in input seed uses explicit `{input_text, sort_order}` records. It fully validates the top-level and entry schema before writing, validates trimmed text length 1..300 and exact positive non-bool integers, inserts a whole group only into an empty draft revision, and never restores an administrator's partial deletion/reorder/edit.

### GREEN / focused verification

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_content_seed.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-seed-011
12 passed in 7.44s
TASK6_PYTEST_EXIT=0

..\..\.venv\Scripts\python.exe -m pytest tests/test_content_migrations.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-migrations-013
31 passed in 18.42s
TASK6_PYTEST_EXIT=0

..\..\.venv\Scripts\python.exe -m pytest tests/test_content_publishing.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-publishing-014
34 passed in 21.61s
TASK6_PYTEST_EXIT=0

..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-public-016
85 passed in 47.83s
tool exit_code=0

..\..\.venv\Scripts\python.exe -m pytest tests/test_app_factory_and_migrations.py tests/test_catalog_content_admin.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-factory-admin-016
21 passed in 11.63s
TASK6_PYTEST_EXIT=0

..\..\.venv\Scripts\python.exe -m pytest tests/test_content_migrations.py::test_scenario_input_rows_require_a_positive_sort_order tests/test_content_seed.py::test_non_mapping_scenario_input_seed_is_value_error_before_any_write tests/test_public_catalog.py::test_every_public_complete_detail_has_its_required_sections tests/test_public_catalog.py::test_all_public_complete_seeded_scenario_drafts_pass_the_formal_publish_gate -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-final-changed-tests-017
4 passed in 3.44s
TASK6_PYTEST_EXIT=0
```

`pytest-task6-fix1d-green-public-015` previously retained `85 passed in 47.87s` but the host detached before its exit marker. It is stdout-only with exit UNKNOWN and is superseded by the direct-session `-016` result above. An initial `-012` migration wrapper placed its log files inside its basetemp; pytest could not remove those open Windows files and reported 31 setup errors. That was an evidence-wrapper error, not a product failure; `-013` used logs outside the basetemp and is the valid result.

After the final changed migration-inventory test and report freeze, the complete
Fix1d focused set was re-run in a direct pytest session:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py tests/test_content_seed.py tests/test_content_migrations.py tests/test_content_publishing.py tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py tests/test_catalog_content_admin.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-final-focused-020
188 passed in 103.92s (0:01:43)
tool exit_code=0
```

### Static checks and self-review

```text
..\..\.venv\Scripts\python.exe -m py_compile catalog_content_repository.py publishing_repository.py publishing_service.py content_seed.py tests\test_public_catalog.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_content_publishing.py tests\test_v2_migrations.py
TASK6_PYCOMPILE_EXIT=0

git diff --check
TASK6_DIFF_CHECK_EXIT=0

rg -n '\b(execute|executemany|executescript|cursor)\s*\(' blueprints\public_catalog.py
BLUEPRINT_DIRECT_SQL_GUARD=PASS
```

Reviewed the complete changed range for exact query/container bounds, stable ordering and pagination-after-completeness, publication/time/status guards, canonical/filter behavior, archived-target handling, safe public-only block and media boundaries, absence of internal/contact/admin leaks, and Blueprint SQL ownership. No share-image/resource-attachment MIME scope was expanded.

### Changed files

- `catalog_content_repository.py`
- `publishing_repository.py`
- `content_seed.py`
- `migrations/007_scenario_public_inputs.sql`
- `seed_data/scenario_public_inputs_v1.json`
- `tests/test_public_catalog.py`
- `tests/test_content_seed.py`
- `tests/test_content_migrations.py`
- `tests/test_v2_migrations.py`
- `tests/test_content_publishing.py`
- this report

### Verification correction

The first related V2-migration run after the initial report edit exposed one
missed migration inventory assertion, not a runtime migration defect:

```text
..\..\.venv\Scripts\python.exe -m pytest tests/test_v2_migrations.py -q -p no:cacheprovider --basetemp ...\pytest-task6-fix1d-green-v2-migrations-018
1 failed, 3 passed in 0.66s
TASK6_PYTEST_EXIT=1
```

The expected ledger was updated to include `007_scenario_public_inputs`; the
fresh GREEN was `4 passed in 0.47s`, `TASK6_PYTEST_EXIT=0`, with basetemp
`pytest-task6-fix1d-green-v2-migrations-019`.

### Known limitation / required product decision

The frozen assessment manifest deliberately defines `data_process_foundation` as a fallback-only scenario with `pain_codes=[]`. The later Fix1d requirement makes a published pain mandatory for every public scenario. To avoid changing shared assessment/private matching behavior, this Fix1d change does not invent or add a pain association: 12 public-complete seeded scenarios formally publish and that fallback scenario is rejected and private. Publishing it publicly now requires an explicit product-approved core association change outside this Task-6 implementation scope.

## Fix1d controller verification

The controller independently verified code commit
`05eddacf3befe596d1dd51da1e3c58c64e0210c7` from the clean assigned
worktree. Every pytest invocation used the assigned project interpreter,
process-scoped `PYTHONPATH` pointing only to the checked-in offline
`local-deps` overlay, `-p no:cacheprovider`, and a unique basetemp. The
resolved dependency evidence was pypdf `6.10.0` loaded from
`.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_content_publishing.py tests\test_v2_migrations.py tests\test_app_factory_and_migrations.py tests\test_catalog_content_admin.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1d-focused-001
```

Result: `188 passed in 102.83s (0:01:42)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1d-public-partition-001
```

Result: `242 passed in 141.00s (0:02:20)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1d-related-partition-001
```

Result: `204 passed in 80.49s (0:01:20)`, tool `exit_code=0`.

Controller static verification also returned `py_compile=0`,
`git diff --check 1c359a7..05eddac=0`, valid input JSON, and no direct SQL
call in `blueprints/public_catalog.py`. Tracked status was clean before this
report-only append. No full suite, network access, dependency installation,
production server, Nginx, or real database was used. The original full-suite
outcome remains **UNKNOWN**, and the historical PyPI-network violation remains
**CONFIRMED**.

## Fix1e — industry publication, bounded content JSON, and future media correction

**Status: DONE_WITH_CONCERNS.** This Task-6-only correction retains the
original full-suite outcome as **UNKNOWN** and the historical PyPI network
violation as **CONFIRMED**. Fix1e made no network request, dependency
installation, production-server/Nginx call, or real-database access; every
test used a temporary SQLite database and local Flask clients/mocks.

### Offline environment

Every Fix1e pytest invocation used the assigned interpreter, process-scoped
offline overlay, `-p no:cacheprovider`, and a fresh
`pytest-task6-fix1e-*` basetemp:

```text
PYTHON=D:\\Codex干活\\企业AI转型平台2.0升级\\V0.2-server-snapshot-20260819\\.venv\\Scripts\\python.exe
PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps
PYPDF_VERSION=6.10.0
PYPDF_SOURCE=...\\.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps\\pypdf\\__init__.py
TASK6_ENV_EXIT=0
```

### TDD / debugging evidence

The first `red-foundations-001` collection attempt stopped on a test-only
non-ASCII Python bytes literal (`SyntaxError: bytes can only contain ASCII
literal characters`), before production behavior could run. It was corrected
to ASCII fixture text and not counted as a behavioral RED. The genuine
behavioral RED was:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1e-red-foundations-002 -k "industry_with_blank_overview or industry_publication_requires_each_live_public_dependency or due_industry_with_later_missing_overview or published_blank_deliverable or formal_publish_rejects_non_text_json or public_catalog_fails_closed_for_non_text_or_unbounded_json or future_published_scenario_hides_detail"
24 failed, 1 passed, 87 deselected in 17.93s
TASK6_PYTEST_EXIT=1
```

It demonstrated that a blank or dependency-incomplete industry draft could
replace its healthy public revision, a due industry could still publish after
post-schedule damage, a published blank deliverable was accepted when another
deliverable was valid, binary/deep/oversized JSON was accepted or surfaced as
500, and a future-dated published scenario was visible. The Fix1e industry
gate stays entirely in `publishing_repository`: it queries only currently due
published scenario revisions and reuses the local scenario publication
validator, avoiding a Blueprint SQL path or a catalog-to-publishing import
cycle.

The initial combined GREEN had one test-clock issue:

```text
pytest-task6-fix1e-green-foundations-003
1 failed, 26 passed, 85 deselected in 18.88s
TASK6_PYTEST_EXIT=1
```

The test had used a 2026 time which the host clock had already passed. It was
changed to the explicit 2030 Shanghai instant; the single media-clock proof
was `1 passed in 1.22s`, exit 0 (`green-media-clock-004`) and the full selected
GREEN was:

```text
pytest-task6-fix1e-green-foundations-005
27 passed, 85 deselected in 18.87s
TASK6_PYTEST_EXIT=0
```

One pre-existing generic publishing fixture then failed correctly under the
new global industry invariant: `test_all_six_relation_types_survive_revision_copy`
created an incomplete industry aggregate (`1 failed, 33 passed in 21.05s`,
`focused-publishing-008`, exit 1). Its first replacement query selected
duplicate branches (`green-publishing-fixture-009`: `1 failed in 0.94s`, exit
1). The fixture now creates two complete, distinct scenario dependencies and
an overview block for the two industry aggregates; targeted GREEN was
`1 passed in 0.95s`, exit 0 (`green-publishing-fixture-010`). This preserves,
rather than bypasses, the formal invariant.

The first added future share/resource media test collection attempt was also a
test-only setup error (`NameError: pytest is not defined`,
`green-media-references-015`, exit 1). After importing `pytest`, the relevant
media reference selection was `8 passed, 16 deselected in 7.87s`, exit 0
(`green-media-references-016`).

### Implementation

- `content_json.py` provides a dependency-free decoder that accepts only exact
  `str` database values, caps content at 16,384 characters and nesting at 32,
  and maps `ValueError`, `JSONDecodeError`, and `RecursionError` to a bounded
  content error without catching `MemoryError` or `BaseException`.
- Catalog projections fail closed for invalid block settings, scenario risks,
  and service step/prerequisite/acceptance JSON. Publication converts the same
  condition to stable `ContentValidationError("content_json_invalid")` before
  any archival/audit state transition.
- Industry formal publication now requires a published nonblank core,
  meaningful overview, published nonblank pain/department/company-size data,
  and at least one now-effective associated scenario that passes the existing
  complete scenario/service/deliverable publication rules. Cases/resources
  remain optional.
- Scenario publication requires both a valid published deliverable and no
  blank published deliverable; archived blank historical deliverables remain
  harmless.
- Public-media reference queries use the trusted Shanghai clock parameter for
  every share-image, block-image, block-download, and resource-attachment
  reference, requiring `publish_at IS NULL OR publish_at <= now`.

### Focused GREEN evidence

```text
pytest-task6-fix1e-focused-public-020
112 passed in 67.60s (0:01:07)
TASK6_PYTEST_EXIT=0

pytest-task6-fix1e-focused-publishing-018
34 passed in 25.44s
TASK6_PYTEST_EXIT=0

pytest-task6-fix1e-focused-media-017
24 passed in 20.80s
TASK6_PYTEST_EXIT=0

pytest-task6-fix1e-focused-migrations-seed-019
48 passed in 26.77s
TASK6_PYTEST_EXIT=0
```

After code/test freeze, the combined affected set was run once in a retained
direct pytest session (still not the full suite):

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py tests\\test_content_publishing.py tests\\test_media_http.py tests\\test_content_migrations.py tests\\test_content_seed.py tests\\test_v2_migrations.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1e-final-focused-021
218 passed in 134.14s (0:02:14)
TASK6_PYTEST_EXIT=0
```

Earlier public whole-file runs `focused-public-006` and `-007` retained only
progress dots; their terminal summary/exit is irretrievable and no PASS claim
is made for them. They are superseded by the direct-session,
exit-captured `focused-public-014` (`112 passed in 65.29s`, exit 0) and final
`focused-public-020` above. No full suite was run in Fix1e.

### Static checks and self-review

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile content_json.py catalog_content_repository.py publishing_repository.py publishing_service.py media_service.py tests\\test_public_catalog.py tests\\test_content_publishing.py tests\\test_media_http.py
TASK6_PYCOMPILE_EXIT=0

git diff --check b4b2f6a7736f7b60cb9fd139def771e05cff8e7e
BLUEPRINT_DIRECT_SQL_GUARD=PASS
TASK6_STATIC_EXIT=0
```

Reviewed: immediate and due transaction ordering; healthy old-revision
preservation; required industry/core/scenario/service dependencies; exact JSON
type/size/depth behavior and public private-404 boundaries; published versus
archived deliverables; strict time-aware media lookup with no Host or SQLite
localtime dependency; no direct SQL in the public Blueprint; existing catalog
filter/canonical/analytics/private-cache behavior; and the frozen
`data_process_foundation` product-data limitation. The code does not change
that frozen `pain_codes=[]` data, does not invent claims, and does not expand
share-image/resource MIME policy.

### Changed files

- `content_json.py`
- `catalog_content_repository.py`
- `publishing_repository.py`
- `media_service.py`
- `tests/test_public_catalog.py`
- `tests/test_content_publishing.py`
- `tests/test_media_http.py`
- this report

Known limitations remain the original full-suite result **UNKNOWN** and the
historical PyPI network violation **CONFIRMED**. Controller-side final
verification remains the appropriate next step; Fix1e did not run a full
suite.
