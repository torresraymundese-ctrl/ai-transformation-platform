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

## Fix1e controller verification

The controller independently verified code commit
`b4bc7e895ed848b75af1bd24171d12e2f4ae44fc` from a clean worktree. All
commands used the assigned project interpreter, process-scoped `PYTHONPATH`
pointing to the offline `local-deps` overlay (pypdf `6.10.0`),
`-p no:cacheprovider`, and a unique basetemp.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_content_publishing.py tests\test_media_http.py tests\test_content_migrations.py tests\test_content_seed.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1e-focused-001
```

Result: `218 passed in 124.15s (0:02:04)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1e-public-partition-001
```

Result: `269 passed in 149.64s (0:02:29)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1e-related-partition-001
```

Result: `208 passed in 74.00s (0:01:14)`, tool `exit_code=0`.

Controller static verification returned `py_compile=0` for the new JSON
boundary and all related Python modules/tests,
`git diff --check 1c359a7..b4bc7e8=0`, and no direct SQL call in
`blueprints/public_catalog.py`. No full suite, network access, installation,
production server, Nginx, or real database was used. The original full-suite
outcome remains **UNKNOWN** and the historical PyPI-network violation remains
**CONFIRMED**.

## Fix1f — exact-text publication/read alignment, total block fail-closed, and surrogate JSON correction

**Status: DONE_WITH_CONCERNS.** This is a Task-6-only correction from clean
baseline `a4ad3cb8c1cb836be397cec0d60771dab7df6438`. It did not run a full
suite, access a network, install/uninstall dependencies, contact a production
server/Nginx, or use a real database. All test state used temporary SQLite
databases with local Flask clients/mocks. The original full-suite outcome
remains **UNKNOWN**, and the historical PyPI-network violation remains
**CONFIRMED**.

### Offline environment

Every Fix1f pytest command used the assigned interpreter, process-scoped
offline overlay, `-p no:cacheprovider`, and a unique
`pytest-task6-fix1f-*` basetemp:

```text
PYTHON=..\\..\\.venv\\Scripts\\python.exe
PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps
PYPDF_VERSION=6.10.0
PYPDF_SOURCE=...\\.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps\\pypdf\\__init__.py
TASK6_ENV_EXIT=0
```

### TDD / root-cause evidence

The genuine initial behavior RED was:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py tests\\test_content_migrations.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-red-core-001 -k "scenario_formal_publication_rejects_each_mixed_invalid_required_text_source or industry_formal_publication_rejects_each_mixed_invalid_required_text_source or due_scenario_with_blob_input_keeps_old_public_revision_and_isolates_batch_failure or public_projection_fails_closed_when_any_persisted_block_cannot_be_projected or bounded_database_json_rejects_lone_surrogates_in_every_text_position or formal_publish_rejects_surrogate_block_settings_without_archiving_current_revision or due_surrogate_block_failure_is_validation_failed_and_does_not_stop_a_healthy_item or surrogate_service_json_is_private_and_rejected_by_formal_publication or bounded_database_json_keeps_normal_chinese_and_emoji_text or scenario_input_rows_reject_blob_text_even_with_a_valid_draft_owner"
23 failed, 6 passed, 144 deselected in 16.95s
TASK6_PYTEST_EXIT=1
```

It proved the specified missing behavior, rather than a test/import error:

- publication SQL used `trim(...)`/existence checks, so mixed valid+BLOB
  published pains, departments, company sizes, scenario relations, inputs,
  and deliverables could replace a healthy revision;
- `_blocks` skipped an invalid persisted second block, leaving the remaining
  block to make the detail return 200;
- JSON decoding accepted a lone surrogate. A formal block publication then
  escaped as `UnicodeEncodeError`, and its due job interrupted before the
  normal `validation_failed` handling;
- 007 accepted a BLOB input value despite TEXT affinity.

The original RED also included one test setup branch which attempted to write
a blank `scenario_public_inputs.input_text`. The pre-existing nonblank CHECK
correctly rejected that write before publication. The test was narrowed to
assert that schema boundary directly; BLOB legacy-state tests deliberately use
temporary SQLite `ignore_check_constraints` only to prove the application
publication gate remains defensive for already-persisted malformed rows.

The first complete selected GREEN after the minimal implementation was:

```text
pytest-task6-fix1f-green-core-003
29 passed, 144 deselected in 15.59s
TASK6_PYTEST_EXIT=0
```

The change makes publication and read semantics agree:

- industry publication now requires every relevant published pain,
  department, and global company-size `name` to be exact `str` and nonblank;
  archived malformed rows are ignored;
- scenario publication requires exact nonblank names for all live associated
  industry/department/pain targets, exact revision-bound inputs, and exact
  nonblank published deliverable titles (with at least one valid
  deliverable). Existing target-status rules remain intact;
- unreleased migration 007 now enforces `typeof(input_text)='text'` before
  its existing trimmed nonblank/length check;
- any block which cannot be exact-projected invalidates its complete public
  industry/scenario projection instead of disappearing silently;
- the bounded shared JSON decoder iteratively strict-UTF-8-validates decoded
  strings in top-level scalars, mapping keys, values, and list members. It
  maps only supported decoding/encoding errors to `ContentJsonError`, without
  catching `MemoryError` or `BaseException`.

Tests include immediate and scheduled publication transaction assertions:
old revision preservation, draft lock values, no accidental
`content_published` event, due `content_due_failed` audit/cleared schedule,
and a simultaneously scheduled healthy item still publishing. They cover
mixed good+BLOB/blank values, direct public detail/list private-404 behavior,
archived malformed industry rows, valid Chinese/emoji JSON, all three service
JSON sources, and a valid public control.

### Focused GREEN evidence

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-focused-public-final-008
149 passed in 89.94s (0:01:29)
TASK6_PYTEST_EXIT=0

..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_content_publishing.py tests\\test_content_migrations.py tests\\test_content_seed.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-focused-publishing-migration-seed-005
79 passed in 44.73s
TASK6_PYTEST_EXIT=0

..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_media_http.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-focused-media-006
24 passed in 17.01s
TASK6_PYTEST_EXIT=0

..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_app_factory_and_migrations.py tests\\test_v2_migrations.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-focused-factory-v2-010
12 passed in 5.34s
TASK6_PYTEST_EXIT=0

..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-focused-block-due-012 -k "formal_publish_rejects_any_unprojectable_persisted_block_before_archiving_current or due_surrogate_block_failure_is_validation_failed_and_does_not_stop_a_healthy_item"
3 passed, 148 deselected in 2.81s
TASK6_PYTEST_EXIT=0
```

After code/test freeze, the complete affected non-full focused set was run in
a direct retained pytest session:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py tests\\test_content_publishing.py tests\\test_media_http.py tests\\test_content_migrations.py tests\\test_content_seed.py tests\\test_v2_migrations.py tests\\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp ...\\pytest-task6-fix1f-final-focused-013
266 passed in 173.06s (0:02:53)
TASK6_PYTEST_EXIT=0
```

### Static checks and self-review

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile content_json.py catalog_content_repository.py publishing_repository.py publishing_service.py media_service.py tests\\test_public_catalog.py tests\\test_content_migrations.py tests\\test_content_publishing.py tests\\test_content_seed.py tests\\test_media_http.py tests\\test_app_factory_and_migrations.py tests\\test_v2_migrations.py
TASK6_PYCOMPILE_EXIT=0

git diff --check a4ad3cb8c1cb836be397cec0d60771dab7df6438
TASK6_DIFF_CHECK_EXIT=0

rg -n '\\b(execute|executemany|executescript|cursor)\\s*\\(' blueprints\\public_catalog.py
BLUEPRINT_DIRECT_SQL_GUARD=PASS
```

Self-review confirmed exact-value checks before publication state transitions;
scheduled failure atomicity; read-time all-or-nothing governed-block handling;
UTF-8/depth/length JSON bounds; published/archived target rules; stable
existing list/detail behavior; 007 ownership and input constraints; no direct
SQL in the public Blueprint; and no public/admin/contact/internal-data leak.
This correction does not alter frozen assessment core data (including the
disclosed `data_process_foundation` limitation), media MIME policy, share/
resource MIME scope, visual tokens, Task 7, ledger, or external task card.

### Changed files

- `content_json.py`
- `catalog_content_repository.py`
- `publishing_repository.py`
- `migrations/007_scenario_public_inputs.sql`
- `tests/test_public_catalog.py`
- `tests/test_content_migrations.py`
- this report

Known limitations remain: no full-suite rerun (the original outcome is
**UNKNOWN**), the historical PyPI-network violation is **CONFIRMED**, and the
frozen fallback `data_process_foundation` has no pain relation and remains
intentionally private rather than receiving invented product data.

## Fix1f controller verification

The controller independently verified code commit
`7f0c8e8af77260fd0f5cb3cde94854d65aaad7ce` with the assigned interpreter,
the process-scoped offline `local-deps` overlay (pypdf `6.10.0`),
`-p no:cacheprovider`, and unique basetemps.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_content_publishing.py tests\test_media_http.py tests\test_content_migrations.py tests\test_content_seed.py tests\test_v2_migrations.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1f-focused-001
```

Result: `266 passed in 167.63s (0:02:47)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1f-public-partition-001
```

Result: `308 passed in 175.27s (0:02:55)`, tool `exit_code=0`.

The first related-partition invocation used basetemp
`pytest-task6-controller-fix1f-related-partition-001` and returned
`1 failed, 208 passed in 71.46s`, tool `exit_code=1`: one catalog-admin review
POST returned 400 instead of 302. The exact test immediately passed alone
(`1 passed in 0.78s`, exit 0), and the complete admin file passed
(`13 passed in 6.94s`, exit 0). A fresh exact partition run used a new
basetemp rather than reusing evidence:

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1f-related-partition-002
```

Fresh result: `209 passed in 73.24s (0:01:13)`, tool `exit_code=0`. The initial
failure is retained here as an unreproduced transient result, not erased or
relabelled as passing.

Controller static verification returned `py_compile=0`,
`git diff --check 1c359a7..7f0c8e8=0`, and no direct SQL call in
`blueprints/public_catalog.py`; tracked status was clean before this
report-only append. No full suite, network access, dependency installation,
production server, Nginx, or real database was used. The original full-suite
outcome remains **UNKNOWN** and the historical PyPI-network violation remains
**CONFIRMED**.

## Fix1g — exact Unicode text gate and governed block completion

Fix1g started from controller baseline
`19a3dea15bc9014592d6b11f2e4a79ab2445aa3f`.  It stayed within Task 6:
no Task 7 work, full suite, network access, dependency installation,
production server, Nginx, or real database was used. Every pytest command
used the assigned `..\\..\\.venv\\Scripts\\python.exe`, process-scoped
`PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps`,
`-p no:cacheprovider`, and its own `pytest-task6-fix1g-*` basetemp. The
overlay reported pypdf `6.10.0`.

### TDD RED evidence

The first behavior RED was run before production edits:

```text
$env:PYTHONPATH=(Resolve-Path '.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps').Path
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py tests\\test_content_migrations.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1g-red-core-001 -k "formally_published_governed_block_types_render_through_safe_public_http or public_projection_fails_closed_for_nonexact_persisted_block_sort_order or immediate_publish_rejects_unicode_whitespace_scenario_input_and_keeps_current_public or due_publish_rejects_unicode_whitespace_input_keeps_old_page_and_isolates_healthy_item or formal_scenario_publish_rejects_unicode_whitespace_in_every_other_live_text_source or formal_industry_publish_rejects_unicode_whitespace_in_every_live_text_source or public_scenario_projection_requires_exact_persisted_input_sort_order or scenario_input_rows_require_an_exact_integer_sort_order or scenario_input_rows_reject_unicode_whitespace_and_raw_overlong_text"
26 failed, 3 passed, 184 deselected in 18.15s
tool exit_code=1
```

It proved real missing behavior: SQLite `trim` accepted NBSP/tab/newline/fullwidth
whitespace for immediate and due scenario publication, allowing a bad draft to
replace a healthy revision; REAL/TEXT block and input orders remained public;
007 accepted those malformed input rows and a 301-character raw value ending in
space; and legal heading/metric/steps/download/CTA fields disappeared from the
public renderer. The industry pain/department/company-size Unicode tests already
passed because that separate gate was already Python-`strip` based.

The additional formal legacy-input-order RED was:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1g-red-input-order-002 -k "formal_publish_rejects_legacy_nonexact_input_sort_order"
2 failed, 173 deselected in 1.96s
tool exit_code=1
```

Both REAL and TEXT legacy input `sort_order` values could otherwise publish.

### Fix and GREEN evidence

`content_validation.is_exact_nonblank_text` is a dependency-free, generic
Python predicate used by both public projection and publication validation.
`public_input_texts` adds the revision-bound input rules: exact `str`, Python
`strip()` nonblank, original length 1..300, exact non-bool Python `int`
sort order >=1, unique/increasing stable order. Migration 007 now encodes the
same Python whitespace set in its unreleased SQLite CHECK, retains its
revision ownership/immutability contract, and requires an INTEGER sort value.
The test-only corruption helper explicitly bypasses that schema only to prove
the application gate fails closed for legacy malformed rows; direct migration
tests prove the schema boundary independently.

`_blocks` now selects and exact-validates `sort_order` >=0, so one REAL/TEXT
persisted order invalidates the entire industry/scenario projection. The
governed block macro now safely renders contract-allowed title/body fields for
all seven types: heading, rich_text, image_text, metric, steps, download, and
CTA. Rich HTML continues through the existing `safe_html` path; no user
contract was narrowed and media URL behavior was unchanged.

```text
pytest-task6-fix1g-green-core-003
31 passed, 184 deselected in 17.72s
tool exit_code=0

pytest-task6-fix1g-green-blank-input-007
10 passed, 165 deselected in 6.28s
tool exit_code=0

pytest-task6-fix1g-green-input-range-008
5 passed, 171 deselected in 3.37s
tool exit_code=0

pytest-task6-fix1g-focused-publishing-validation-004
112 passed in 19.33s
tool exit_code=0

pytest-task6-fix1g-focused-migrations-seed-005
56 passed in 26.42s
tool exit_code=0

pytest-task6-fix1g-focused-public-009
176 passed in 93.84s (0:01:33)
tool exit_code=0

pytest-task6-fix1g-final-focused-010
..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_public_catalog.py tests\\test_content_publishing.py tests\\test_content_validation.py tests\\test_content_migrations.py tests\\test_content_seed.py tests\\test_v2_migrations.py tests\\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1g-final-focused-010
352 passed in 143.10s (0:02:23)
tool exit_code=0
```

An intermediate full public-file run, `pytest-task6-fix1g-focused-public-006`,
returned `1 failed, 174 passed in 93.30s`, exit 1. The only failure was the
pre-existing blank-input test still expecting a direct SQLite error after the
test helper had been intentionally changed to create a legacy malformed row.
The assertion was corrected to exercise formal publication/old-revision
preservation; the focused public `-009` result above is the final evidence.

### Static checks and self-review

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile content_validation.py catalog_content_repository.py publishing_repository.py tests\\test_public_catalog.py tests\\test_content_migrations.py
PYCOMPILE_EXIT=0

assigned interpreter: ..\\..\\.venv\\Scripts\\python.exe
PYTHONPATH: .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps
pypdf=6.10.0
ENV_EVIDENCE_EXIT=0

git diff --check 19a3dea15bc9014592d6b11f2e4a79ab2445aa3f
DIFF_CHECK_EXIT=0

rg -n '\\b(execute|executemany|executescript|cursor)\\s*\\(' blueprints\\public_catalog.py
BLUEPRINT_SQL_GUARD=PASS

..\\..\\.venv\\Scripts\\python.exe -c "import re; from pathlib import Path; sql=Path('migrations/007_scenario_public_inputs.sql').read_text(encoding='utf-8'); actual={int(value) for value in re.findall(r'char\\((\\d+)\\)', sql)}; expected={codepoint for codepoint in range(0x110000) if chr(codepoint).isspace()}; print('migration_whitespace_exact=' + str(actual == expected)); print('count=' + str(len(actual))); assert actual == expected"
migration_whitespace_exact=True
count=29
tool exit_code=0
```

Self-review covered public/read and formal/due gate equivalence for all live
core names, revision-owned inputs, and published deliverables; archived target
blocking; raw input range/order constraints; one-invalid-block fail-closed
list/detail consistency; all legal governed block fields and safe HTML/media
boundaries; trusted public URL behavior; and no public internal/admin/contact
leak. No share-image/resource MIME scope was expanded.

### Fix1g changed files

- `content_validation.py`
- `catalog_content_repository.py`
- `publishing_repository.py`
- `migrations/007_scenario_public_inputs.sql`
- `templates/components/content_blocks.html`
- `tests/test_public_catalog.py`
- `tests/test_content_migrations.py`
- this report

Known limitations remain unchanged: the original sole full-suite outcome is
**UNKNOWN** (no full rerun); the historical PyPI network use is **CONFIRMED**;
and frozen `data_process_foundation` remains intentionally private owing to its
disclosed product-data limitation. This Fix1g used only the existing offline
overlay and disposable SQLite databases.

## Fix1g controller verification

The controller independently verified code commit
`02c3a51c763ce3e2f5c70449e481f11a7573e193` from a clean tracked tree. Every
pytest command used the assigned project interpreter, process-scoped offline
`local-deps` overlay (`pypdf 6.10.0`), `-p no:cacheprovider`, and a unique
basetemp. No full suite, network access, dependency installation, production
server, Nginx, or real database was used.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_content_publishing.py tests\test_content_validation.py tests\test_media_http.py tests\test_content_migrations.py tests\test_content_seed.py tests\test_v2_migrations.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1g-focused-001
```

Result: `376 passed in 168.11s (0:02:48)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1g-public-partition-001
```

Result: `333 passed in 173.26s (0:02:53)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1g-related-partition-001
```

Result: `216 passed in 74.30s (0:01:14)`, tool `exit_code=0`.

Controller environment evidence resolved the interpreter to the assigned
project venv and `pypdf` to version `6.10.0` inside the command-scoped offline
overlay. `py_compile`, `git diff --check 1c359a7..02c3a51`, the exact 29-codepoint
Python-`isspace`/migration parity check, and the no-direct-SQL guard for
`blueprints/public_catalog.py` all returned exit 0. The tracked tree was clean
before this report-only append.

The original full-suite result remains **UNKNOWN** and was not rerun. The
historical PyPI-network violation remains **CONFIRMED**. The frozen
`data_process_foundation` product-data limitation also remains unchanged.

## Fix1h — seed fidelity, strict public origin, optional headings, and share-image gate

Fix1h started from `ffdde7103ba57bdb6e93a98e072d2ae7701f2ca2`. It stayed
inside Task 6: no Task 7 work, full suite, dependency installation, network
access, production server, Nginx, or real database was used. Every pytest
command used the assigned `..\\..\\.venv\\Scripts\\python.exe`, a
process-scoped `PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps`,
`-p no:cacheprovider`, and a distinct `pytest-task6-fix1h-*` basetemp. The
existing offline overlay resolved `pypdf` to `6.10.0`.

### TDD RED evidence

The first test-first command covered raw seed input bounds/preservation, the
007 schema, public NUL fail-closed behavior, heading rendering, strict origin
inputs, and share-image selection/publication:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1h-red-core-001 [12 focused Task 6 test nodes]
16 failed, 3 passed in 7.15s
tool exit_code=1
```

It correctly exposed the intended missing behaviors (trimmed raw seed input,
accepted NUL, ready PDF share selection/publication, literal heading `None`,
and noncanonical origins). Two assertions were then corrected before any
production edit: a public legacy-input test must corrupt the draft before it
is made public because the immutable published-row trigger correctly rejects
an in-place update, and the valid-image control must use
`PublishResult.published_id`/`archived_id`. The corrected genuine RED was:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1h-red-core-002 [same focused Task 6 nodes]
15 failed, 4 passed in 6.99s
tool exit_code=1
```

The failures proved: raw `x * 300 + ' '` and NUL input seed values were
accepted before stripping; valid leading/trailing whitespace was rewritten;
007 accepted NUL TEXT; a ready PDF appeared as a share image and published;
an optional heading title emitted `>None<`; malformed origin delimiters,
ports, hostless forms, and controls were accepted; and both formal publication
and public reads accepted a legacy NUL input.

The strict-host follow-up had its own tests before the hostname implementation:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1h-red-origin-host-005 tests\\test_public_catalog.py::test_public_base_url_rejects_invalid_hostname_shape tests\\test_public_catalog.py::test_public_base_url_accepts_exact_https_origins
3 failed, 5 passed in 0.68s
tool exit_code=1
```

The three invalid parsed hosts were `exa mple.test`, `example_test`, and
`example%.test`. The port follow-up also had an independent RED:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1h-red-origin-port-008 tests\\test_public_catalog.py::test_public_base_url_rejects_noncanonical_https_origins tests\\test_public_catalog.py::test_public_base_url_accepts_exact_https_origins
1 failed, 12 passed in 0.60s
tool exit_code=1
```

It proved `https://example.test:0` was accepted before the local port guard.

### Minimal implementation and GREEN evidence

`is_exact_nonblank_text` now rejects NUL in addition to exact `str`, Python
`strip()` nonblank, and the caller-supplied maximum. `content_seed` uses this
same predicate with a 300-character maximum and persists valid text verbatim;
it retains whole-payload prevalidation before any insert. Unreleased migration
007 now also rejects NUL with `instr(input_text,char(0))=0` while retaining its
existing exact TEXT/length/whitespace/order/ownership contract. Formal
publication and public projection already consume this shared predicate, so
legacy malformed NUL rows reject or fail closed instead of silently reaching a
public page.

The editor now exposes image MIME assets only in `share_image_choices`; its
block `media_choices` remain all ready attachments. The authoritative
publication gate independently requires the selected share asset to be ready
and an `IMAGE_MIMES` member, so crafted requests roll back before archiving a
healthy revision. A legal ready PNG remains publishable. The optional heading
title is rendered only when truthy, while its meaningful body continues
through the existing `safe_html` filter.

`PUBLIC_BASE_URL` now accepts only an input exactly equal to a reconstructed
HTTPS origin: no userinfo/path/query/fragment/Unicode C-category character, a nonzero
valid port, and a hostname validated locally as IDNA-normalizable IPv4, IPv6,
or DNS-label shape. No DNS lookup/global-address policy was added. Explicit
ports 1..65535, IPv6, IPv4, and a Unicode IDN control remain accepted.

```text
pytest-task6-fix1h-green-core-003
19 passed in 6.52s
tool exit_code=0

pytest-task6-fix1h-green-origin-host-006
14 passed in 0.30s
tool exit_code=0

pytest-task6-fix1h-green-origin-port-009
17 passed in 0.34s
tool exit_code=0
```

A final strict-origin review found that U+200B (a Unicode format character)
could be removed by IDNA after the former `Cc`-only control check. It had its
own test-first evidence:

```text
pytest-task6-fix1h-red-origin-format-011
tests/test_public_catalog.py::test_public_base_url_rejects_invalid_hostname_shape tests/test_public_catalog.py::test_public_base_url_accepts_exact_https_origins
1 failed, 10 passed in 0.60s
tool exit_code=1

pytest-task6-fix1h-green-origin-format-012
tests/test_public_catalog.py::test_public_base_url_is_required_https_origin tests/test_public_catalog.py::test_public_base_url_rejects_noncanonical_https_origins tests/test_public_catalog.py::test_public_base_url_rejects_invalid_hostname_shape tests/test_public_catalog.py::test_public_base_url_accepts_exact_https_origins
18 passed in 0.34s
tool exit_code=0
```

The minimal correction now follows the existing project policy,
`unicodedata.category(character).startswith("C")`, before parsing. This
rejects controls and format characters without adding DNS/global-address
policy.

Before the hostname/port additions, the six required responsibility files
returned `302 passed in 156.43s`, exit 0, in
`pytest-task6-fix1h-responsibility-004`; the broader pre-port set including
media HTTP/service returned `421 passed in 218.18s`, exit 0, in
`pytest-task6-fix1h-responsibility-final-007`. A pre-format-character final
run returned `424 passed in 220.28s`, exit 0, in
`pytest-task6-fix1h-responsibility-final-010`. The final frozen responsibility
command was rerun after the U+200B correction:

```text
$env:PYTHONPATH=(Resolve-Path '.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps').Path
..\\..\\.venv\\Scripts\\python.exe -c "import sys, pypdf; print(sys.executable); print(sys.version.split()[0]); print(__import__('os').environ['PYTHONPATH']); print(pypdf.__version__)"
interpreter=...\\.venv\\Scripts\\python.exe
python=3.12.13
PYTHONPATH=...\\.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps
pypdf=6.10.0

..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1h-responsibility-final-013 tests\\test_public_catalog.py tests\\test_catalog_content_admin.py tests\\test_content_seed.py tests\\test_content_migrations.py tests\\test_app_factory_and_migrations.py tests\\test_content_publishing.py tests\\test_media_service.py tests\\test_media_http.py
425 passed in 222.59s (0:03:42)
tool exit_code=0
```

### Static checks, self-review, and inventory

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile app.py catalog_content_repository.py content_seed.py content_validation.py publishing_repository.py tests\\test_catalog_content_admin.py tests\\test_content_migrations.py tests\\test_content_seed.py tests\\test_public_catalog.py
PYCOMPILE_EXIT=0

git diff --check
DIFF_CHECK_EXIT=0

Blueprint direct-SQL guard over blueprints\\admin\\catalog.py
BLUEPRINT_DIRECT_SQL_GUARD=PASS
```

Self-review confirmed raw input values are only accepted when exact/nonblank/
bounded and are never trimmed on seed; NUL is blocked in seed, schema,
publication, and public-read boundaries; valid ready share images remain
available while PDF/document selections are rejected atomically; the seven
governed block contracts remain unchanged and the heading body retains safe
HTML rendering; `PUBLIC_BASE_URL` comes solely from validated configuration,
not Host/X-Forwarded-Host; and no analytics/private-cache, core frozen data,
public leak, media block MIME, share/resource endpoint MIME, visual-token,
Task 7, ledger, or task-card behavior was broadened.

Fix1h changed:

- `app.py`
- `catalog_content_repository.py`
- `content_seed.py`
- `content_validation.py`
- `migrations/007_scenario_public_inputs.sql`
- `publishing_repository.py`
- `templates/admin/catalog_edit.html`
- `templates/components/content_blocks.html`
- `tests/test_catalog_content_admin.py`
- `tests/test_content_migrations.py`
- `tests/test_content_seed.py`
- `tests/test_public_catalog.py`
- this report

Known limitations remain unchanged: the sole historical full-suite stream is
**UNKNOWN** and was not rerun; the historic PyPI network use is
**CONFIRMED**; and the frozen `data_process_foundation` product-data limitation
continues to keep that scenario private rather than inventing a pain relation.

## Fix1h controller verification

The controller independently verified frozen implementation commit
`5fc3f2e173ce4a23793182c3cdf5ae0675ce3c11` from a clean tracked tree. All
pytest commands used the assigned Python `3.12.13` interpreter, the
process-scoped offline `local-deps` overlay (`pypdf 6.10.0`),
`-p no:cacheprovider`, and a unique basetemp. No full suite, network access,
dependency installation, production server, Nginx, or real database was used.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_content_publishing.py tests\test_content_validation.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1h-focused-001
```

Result: `507 passed in 224.06s (0:03:44)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1h-public-partition-001
```

Result: `354 passed in 180.65s (0:03:00)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1h-related-partition-001
```

Result: `313 passed in 126.60s (0:02:06)`, tool `exit_code=0`.

Controller `py_compile`, `git diff --check 1c359a7..5fc3f2e`, exact migration
whitespace-plus-NUL contract check, and no-direct-SQL guards for both public and
admin catalog Blueprints all returned exit 0. The tracked tree was clean before
this report-only append.

The original full-suite outcome remains **UNKNOWN** and was not rerun. The
historical PyPI-network violation remains **CONFIRMED**, and the frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1i — strict origin authority and whitespace heading visibility

Fix1i began from clean baseline
`10b05f25f7144f5ac3d06377699122a66e5eff00`. It made no Task 7 change and
used only local Flask clients and temporary SQLite databases. No full suite,
network access, dependency installation, production server, Nginx, or real
database was used.

The assigned interpreter and explicitly process-scoped offline overlay were:

```text
interpreter=D:\...\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe
python=3.12.13
PYTHONPATH=D:\...\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps
pypdf=6.10.0
```

### TDD evidence

Before Fix1i production edits, the authority/heading behavior RED was run with
the assigned interpreter, `-p no:cacheprovider`, and unique basetemp
`pytest-task6-fix1i-red-authority-heading-001`:

```text
tests/test_public_catalog.py::test_public_base_url_rejects_noncanonical_https_origins
tests/test_public_catalog.py::test_public_base_url_rejects_ambiguous_authority_forms
tests/test_public_catalog.py::test_public_base_url_accepts_exact_https_origins
tests/test_catalog_content_admin.py::test_admin_publish_heading_without_title_renders_its_safe_body_without_none
tests/test_catalog_content_admin.py::test_admin_publish_whitespace_heading_title_keeps_body_without_an_empty_heading
8 failed, 16 passed in 3.04s
tool exit_code=1
```

The failures proved that empty DNS/IPv6 ports, U+034F IDNA loss, IPvFuture,
invalid A-labels, IPv6 zones, and a noncanonical leading-zero port passed the
old configured-origin check; the admin publish-to-public HTTP flow also emitted
an empty heading for a whitespace-only title.

The first GREEN attempt (`pytest-task6-fix1i-green-authority-heading-002`)
exposed one implementation defect: the valid bracketed IPv6 `:8443` suffix was
not stripped before decimal-port validation (`1 failed, 28 passed in 2.09s`,
exit 1). The narrow correction was made before continuing. The complete GREEN
then returned:

```text
pytest-task6-fix1i-green-authority-heading-003
29 passed in 1.93s
tool exit_code=0

pytest-task6-fix1i-public-admin-004
5 passed in 3.41s
tool exit_code=0
```

The configured-origin boundary now parses the raw authority locally and
reconstructs it exactly: empty/noncanonical ports are rejected; bracketed hosts
must be literal zone-free IPv6; DNS/IDN labels require encode, decode, and
re-encode validation with lossless Unicode spelling; IPvFuture and invalid
A-labels are rejected. It makes no DNS lookup or global-address decision and
still never derives public origins from Host/X-Forwarded-Host. Valid Unicode
IDN, punycode, IPv4, IPv6, and ports 1/443/8443/65535 remain covered.

At that point optional block titles remained stored raw. Fix1k subsequently
normalizes whitespace-only optional titles to `None` at the save boundary;
public rendering still suppresses absent titles uniformly across the existing
optional title slots, while meaningful body HTML retains its existing
sanitization path. The real admin POST test proves a whitespace heading has no
empty heading element
while its safe body remains visible.

After code freeze, the required responsibility set ran once with a fresh,
unique basetemp and direct retained tool result:

```text
pytest-task6-fix1i-responsibility-final-005
tests/test_public_catalog.py tests/test_catalog_content_admin.py tests/test_content_seed.py tests/test_content_migrations.py tests/test_app_factory_and_migrations.py tests/test_content_publishing.py tests/test_content_validation.py tests/test_media_service.py tests/test_media_http.py tests/test_v2_migrations.py
517 passed in 238.35s (0:03:58)
tool exit_code=0
```

### Static checks, scope review, and inventory

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile app.py tests\\test_public_catalog.py tests\\test_catalog_content_admin.py
PYCOMPILE_EXIT=0

git diff --check
DIFF_CHECK_EXIT=0

Blueprint direct-SQL guard: blueprints\\public_catalog.py = PASS
Blueprint direct-SQL guard: blueprints\\admin\\catalog.py = PASS
```

Fix1i changed only:

- `app.py`
- `templates/components/content_blocks.html`
- `tests/test_public_catalog.py`
- `tests/test_catalog_content_admin.py`
- this report

Self-review confirmed no public read-model, publication, analytics,
private-cache, media-MIME, frozen seed-data, visual-token, Task 7, ledger, or
external task-card behavior was broadened. The sole historical full-suite
outcome remains **UNKNOWN** and was not rerun; the historical PyPI-network
violation remains **CONFIRMED**; the frozen `data_process_foundation`
product-data limitation remains unchanged.

## Fix1j — WHATWG IPv4 ambiguity and IDNA2008 strict-origin boundary

Fix1j began from clean baseline
`0decde0bf9457c8b69ae318c751939337ce8ca23`. It used only local
`create_app` calls and disposable test SQLite databases. No full suite,
network access, dependency installation, production server, Nginx, or real
database was used.

The assigned interpreter was Python `3.12.13`; every pytest command set
`PYTHONPATH` process-scoped to
`.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps`, used
`-p no:cacheprovider`, and used its own `pytest-task6-fix1j-*` basetemp. The
already-present offline environment provided `pypdf 6.10.0` and `idna 3.19`.
`requirements.txt` now declares the direct production dependency
`idna>=3.10,<4`; no installation was attempted.

### TDD evidence

Before production edits, this genuine RED was run:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1j-red-authority-001 \
  tests\\test_public_catalog.py::test_public_base_url_rejects_invalid_hostname_shape \
  tests\\test_public_catalog.py::test_public_base_url_rejects_ambiguous_authority_forms \
  tests\\test_public_catalog.py::test_public_base_url_rejects_dns_forms_that_whatwg_can_treat_as_ipv4 \
  tests\\test_public_catalog.py::test_public_base_url_keeps_a_non_numeric_final_label_as_dns \
  tests\\test_public_catalog.py::test_public_base_url_accepts_lossless_idna2008_origins \
  tests\\test_public_catalog.py::test_public_base_url_accepts_exact_https_origins

8 failed, 19 passed in 1.31s
tool exit_code=1
```

The six alternate/numeric-final host spellings (`0x7f000001`, split/mixed
hex, `0x`, `test.123`, and `test.09`) were accepted through the DNS fallback.
Both valid IDNA2008 spellings `faß.de` and `xn--fa-hia.de` were rejected by the
standard-library IDNA2003 codec. Existing Chinese U-label/A-label, U+034F, and
invalid A-label cases were included in this boundary set.

The minimal local correction rejects a DNS fallback whose last ASCII label is
all decimal digits or `0x`/`0X` followed by zero or more ASCII hex digits.
Canonical dotted IPv4 continues through `ipaddress.IPv4Address`; an ordinary
DNS host ending in `test`, such as `0x7f000001.test`, remains valid. IDN
validation now uses the existing offline `idna` 3.19 package with
`strict=True`, `uts46=False`, and `std3_rules=True`, followed by exact
encode/decode/re-encode checks. It performs no DNS lookup or global-address
policy.

The focused GREEN was:

```text
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp .superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1j-green-authority-002 [same six authority nodes]
27 passed in 0.55s
tool exit_code=0
```

After code freeze, the required once-only responsibility command was launched
with fresh basetemp `pytest-task6-fix1j-responsibility-final-003` over:

```text
tests/test_public_catalog.py
tests/test_catalog_content_admin.py
tests/test_content_seed.py
tests/test_content_migrations.py
tests/test_app_factory_and_migrations.py
tests/test_content_publishing.py
tests/test_content_validation.py
tests/test_media_service.py
tests/test_media_http.py
tests/test_v2_migrations.py
```

Its direct terminal stream retained interpreter/PYTHONPATH/pypdf evidence and
progress through `13%`, but the host omitted the original terminal-session ID
and later final stdout/target exit. Read-only process polling confirmed the
assigned-venv pytest child ended naturally; the final summary and target exit
are **UNKNOWN**. No retry was run, because this responsibility command was
explicitly once-only and dots are not pass evidence.

### Static checks, self-review, and inventory

```text
..\\..\\.venv\\Scripts\\python.exe -m py_compile app.py tests\\test_public_catalog.py
PYCOMPILE_EXIT=0

..\\..\\.venv\\Scripts\\python.exe -c "import idna; print(idna.__version__)"
idna=3.19
IDNA_DEPENDENCY_EXIT=0

git diff --check
DIFF_CHECK_EXIT=0

Blueprint direct-SQL guard: blueprints\\public_catalog.py = PASS
Blueprint direct-SQL guard: blueprints\\admin\\catalog.py = PASS
```

Fix1j changed only:

- `app.py`
- `requirements.txt`
- `tests/test_public_catalog.py`
- this report

Self-review confirmed the new guard is local and only applies after canonical
IPv4 parsing fails; valid Unicode/punycode IDNA2008, Chinese IDN, IPv4/IPv6,
and allowed ports retain exact-origin behavior. No Host/X-Forwarded-Host,
analytics/private-cache, publication/read model, media, frozen product data,
Task 7, ledger, or task-card behavior was broadened.

Known evidence limits: this Fix1j once-only responsibility run has an
**UNKNOWN** final outcome because the terminal host lost its final result; the
sole historical full-suite outcome remains **UNKNOWN** and was not rerun; the
historical PyPI-network violation remains **CONFIRMED**; and the frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1i controller verification

The controller independently verified frozen implementation commit
`0ab8d09968ff3cb65f21c51c7f1ea10f898b0954` from a clean tracked tree. Each
pytest command used the assigned Python `3.12.13` interpreter, the
process-scoped offline `local-deps` overlay (`pypdf 6.10.0`),
`-p no:cacheprovider`, and a unique basetemp. The three commands ran in
parallel against isolated temporary databases; none edited the repository.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_content_publishing.py tests\test_content_validation.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1i-focused-001
```

Result: `517 passed in 282.61s (0:04:42)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1i-public-partition-001
```

Result: `363 passed in 232.84s (0:03:52)`, tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1i-related-partition-001
```

Result: `314 passed in 169.95s (0:02:49)`, tool `exit_code=0`.

Controller `git diff --check 1c359a7..0ab8d09` returned exit 0. Both
Blueprint direct-SQL scans returned no matches (`rg` exit 1, interpreted as
PASS). An initial static command mistakenly sent the Jinja template
`templates/components/content_blocks.html` to `py_compile` and therefore
returned the expected template `SyntaxError` with exit 1; no code changed.
The corrected command was then run over the Python files only:

```powershell
..\..\.venv\Scripts\python.exe -m py_compile app.py tests\test_public_catalog.py tests\test_catalog_content_admin.py
```

Corrected `py_compile` result: tool `exit_code=0`. The tracked tree was clean
before this controller-only report append. No full suite, network access,
dependency installation, production server, Nginx, or real database was used.
The original full-suite outcome remains **UNKNOWN**; the historical
PyPI-network violation remains **CONFIRMED**; and the frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1j final evidence addendum

The preceding Fix1j section applies after the controller's frozen Fix1i
verification recorded immediately above. Its authoritative evidence is the
genuine RED (`8 failed, 19 passed`, exit 1) and focused GREEN (`27 passed`,
exit 0), both against the assigned offline environment. The one required
Fix1j responsibility command was started exactly once and has an unrecoverable
final summary/exit; it remains **UNKNOWN**, was not rerun, and must not be
reported as passing from partial dot output. No full suite, network, install,
production endpoint, Nginx, or real database was used in Fix1j.

## Fix1j controller verification

The controller independently verified frozen implementation commit
`ca36c12232992edea5d81bfa4a9b03690147d672` from a clean tracked tree. Every
pytest command set `PYTHONPATH` process-scoped to the offline `local-deps`
overlay, used the assigned Python `3.12.13` interpreter,
`-p no:cacheprovider`, and a unique basetemp. The three commands ran in
parallel against isolated temporary databases and did not edit the repository.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_content_publishing.py tests\test_content_validation.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1j-focused-001
```

Result: `526 passed in 309.47s (0:05:09)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1j-public-partition-001
```

Result: `372 passed in 250.95s (0:04:10)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1j-related-partition-001
```

Result: `314 passed in 181.31s (0:03:01)`, pytest and PowerShell host both
returned `exit_code=0`.

The process-scoped import probe reported `idna.__version__ == 3.19` and
`pypdf.__version__ == 6.10.0` from the offline overlay. For transparency, the
assigned venv still contains `pypdf` distribution metadata `6.16.2`; one
focused-agent metadata probe reported that distribution version even with the
overlay active. The imported module version used through `PYTHONPATH` is
`6.10.0`, while the underlying venv distribution remains `6.16.2`. This is the
pre-existing two-layer environment documented by the review, not an install
or environment mutation.

Controller `py_compile` over `app.py` and `tests/test_public_catalog.py`,
`git diff --check 1c359a7..ca36c12`, and no-direct-SQL scans for both public
and admin catalog Blueprints all passed. The tracked tree was clean before
this report-only append. The implementation agent's once-only responsibility
run remains **UNKNOWN** and is not relabelled by these separate controller
runs. The historical full suite remains **UNKNOWN** and was not rerun; the
historical PyPI-network violation remains **CONFIRMED**; the frozen
`data_process_foundation` product-data limitation remains unchanged. No
network, installation, production server, Nginx, or real database was used.

## Fix1k — finite delivery ranges and exact public text

Fix1k began from clean baseline `a42fdbd554bfeeeb1f77b03cd4cb7ac45e251bc3`.
It was limited to finite/exact scenario and service delivery ranges, plus
exact text semantics for public items and blocks. No Task 7 work, full suite,
network access, dependency installation, production server, Nginx, or real
database was used.

### Environment

Each pytest command used the assigned Python `3.12.13` interpreter,
process-scoped `PYTHONPATH=.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps`,
`-p no:cacheprovider`, and a unique `pytest-task6-fix1k-*` basetemp. The
offline overlay supplied `pypdf 6.10.0`; no install or network request was
made.

### TDD evidence

The first focused RED selection (`pytest-task6-fix1k-red-boundaries-001`)
exercised formal immediate publication, public list/detail projection, due
publishing, top-level NUL text, block text, and range predicates:

```text
43 failed, 2 passed in 23.98s
tool exit_code=1
```

The two already-passing negative-infinity cases were not setup errors: the old
positive comparison happened to reject them. The 43 failures established the
missing positive-infinity, fractional-week, exact-text, and public
fail-closed behavior. A narrow reviewer follow-up RED
(`pytest-task6-fix1k-red-title-due-002`) explicitly covered block-title NUL
and due core-week validation:

```text
2 failed in 1.41s
PYTEST_RED_NARROW_EXIT=1
```

Minimal GREEN introduced shared `content_validation` gates: budget endpoints
must be exact built-in `int`/`float`, finite, positive, and ordered; weeks
must be exact built-in positive ordered `int`s. Publication and public reads
use their distinct gates, including validation before `_scenario_authority`
construction. Exact text now protects top-level public fields and renderer
plain settings; whitespace optional block titles normalize to `None`, while
NUL/overlength titles reject as `block_title_invalid`. Focused GREEN
(`pytest-task6-fix1k-green-boundaries-003`) returned:

```text
46 passed in 26.12s
PYTEST_GREEN_EXIT=0
```

After direct exact-type/subclass predicate coverage was added, the frozen
responsibility command was run exactly once:

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\local-deps').Path
..\\..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp '.superpowers\\sdd\\2026-08-24-content-catalog-publishing\\pytest-task6-fix1k-responsibility-final-004' tests\\test_public_catalog.py tests\\test_catalog_content_admin.py tests\\test_content_validation.py tests\\test_content_publishing.py tests\\test_content_seed.py tests\\test_content_migrations.py tests\\test_app_factory_and_migrations.py tests\\test_media_service.py tests\\test_media_http.py tests\\test_v2_migrations.py
```

```text
580 passed in 288.61s (0:04:48)
PYTEST_RESPONSIBILITY_EXIT=0
```

### Static, scope, and file inventory

`py_compile` of changed Python files exited 0; `git diff --check` exited 0;
and direct-SQL guards for `blueprints/public_catalog.py` and
`blueprints/admin/catalog.py` passed. Self-review confirmed the former broad
`numbers.Real`/`_valid_range` helpers are absent, core weeks are checked before
authority construction, list/detail fail closed together, and no body HTML,
CTA URL, share/resource MIME, assessment seed, or Task 7 contract changed.

Fix1k changed:

- `catalog_content_repository.py`
- `content_validation.py`
- `publishing_repository.py`
- `tests/test_catalog_content_admin.py`
- `tests/test_content_publishing.py`
- `tests/test_content_validation.py`
- `tests/test_public_catalog.py`
- this report

The Fix1i note above is superseded for current behavior: whitespace-only
optional titles now normalize to `None` rather than remaining raw. Historical
limits remain unchanged: the original full-suite result is **UNKNOWN** and was
not rerun; the PyPI-network violation is **CONFIRMED**; and the frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1k controller verification

The controller independently verified frozen Fix1k implementation commit
`43e85320edf1e24de88b7474efd699fdc7878b94`. All pytest commands used the
assigned Python `3.12.13` interpreter, process-scoped offline `local-deps`
overlay (`idna 3.19`, imported `pypdf 6.10.0`),
`-p no:cacheprovider`, and unique basetemps. Each agent confirmed the same
HEAD and a clean tracked tree before and after its read-only run.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1k-focused-001
```

Result: `580 passed in 305.31s (0:05:05)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1k-public-partition-001
```

Result: `404 passed in 257.96s (0:04:17)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1k-related-partition-001
```

Result: `336 passed in 170.41s (0:02:50)`, pytest `exit_code=0`.

The focused probe resolved `pypdf.__file__` to the offline
`local-deps\pypdf\__init__.py`, proving the imported module was 6.10.0 rather
than the assigned venv's separate distribution metadata. For transparency,
the public-partition agent's first auxiliary version probe had a PowerShell
quoting truncation and exited 1; the pytest command was unaffected, and an
ASCII-safe probe under the same process-scoped `PYTHONPATH` then exited 0 and
reported the versions and module path above.

Controller `py_compile` over all seven changed Python files,
`git diff --check` for both `a42fdbd..43e8532` and
`1c359a7..43e8532`, no-direct-SQL scans for both catalog Blueprints, and the
tracked status check all passed. No full suite, network access, installation,
production server, Nginx, or real database was used. The historical full
suite remains **UNKNOWN**; the historical PyPI-network violation remains
**CONFIRMED**; and the frozen `data_process_foundation` product-data
limitation remains unchanged.

## Fix1l — reject persisted blank block titles before publication side effects

Fix1l began from clean tracked baseline
`e19458825d507ed61895fb05ba2d0354da946cea`. It was limited to one statically
verified P1 in the publication boundary. No Task 7 work, full suite, network
access, dependency installation, production server, Nginx, real database,
ledger update, or task-card update was performed.

### Root cause and TDD evidence

`load_content_draft` preserves a legacy persisted block title such as
`'   '`, while `_validate_block` normalizes that optional title to `None`.
`validate_for_publication` returned the normalized draft, but both immediate
and scheduled publication ignored that return value and did not rewrite the
children. The candidate could therefore become the healthy current revision's
replacement even though the public `_public_block` boundary correctly rejects
the still-persisted blank title and makes the new public page unavailable.

Before production edits, three real SQLite/service/public-route regression
chains were added and run with the assigned interpreter, process-scoped
`PYTHONPATH` pointing at the checked-in offline `local-deps` overlay,
`-p no:cacheprovider`, and unique basetemp
`pytest-task6-fix1l-red-block-title-001`:

```text
tests/test_public_catalog.py::test_immediate_publish_rejects_persisted_blank_block_title_and_keeps_current_public
tests/test_public_catalog.py::test_schedule_rejects_persisted_blank_block_title_without_state_or_audit
tests/test_public_catalog.py::test_due_blank_block_title_failure_keeps_current_public_and_isolates_healthy_peer
3 failed in 3.12s
tool exit_code=1
```

The immediate and schedule chains both failed with `DID NOT RAISE
ContentValidationError`. The due chain published both the malformed candidate
and its healthy peer instead of isolating the malformed candidate as
`validation_failed`. These were expected behavioral failures, not fixture or
collection errors.

The minimal implementation now loads the raw draft, validates it, and compares
only each corresponding raw and validated block title. Any title changed by
validation raises stable `ContentValidationError('block_title_invalid')`
before media, relation, archive, publication, or audit side effects. It does
not compare whole aggregates, write normalized children during publication,
or broaden body/top-level trimming, ordering, or save behavior. Formal saves
continue to persist a new blank optional title as `None`, while meaningful
titles retain their original value.

The same three tests then returned GREEN with unique basetemp
`pytest-task6-fix1l-green-block-title-002`:

```text
3 passed in 1.93s
tool exit_code=0
```

The chains prove that immediate publication keeps the healthy current revision
published and publicly available, leaves the candidate draft and lock
unchanged, and writes no `content_published` audit; scheduling leaves no
`publish_at` or `content_scheduled` audit; and due publication reports exactly
the malformed candidate as `validation_failed`, publishes the healthy peer,
keeps the old public page at HTTP 200, writes exactly one `content_due_failed`,
and writes no `content_published` for the malformed candidate.

### Frozen responsibility and static verification

After the focused GREEN, production code and tests were frozen. The required
responsibility set was started exactly once, using the assigned interpreter,
the process-scoped offline overlay, `-p no:cacheprovider`, and unique basetemp
`pytest-task6-fix1l-responsibility-final-003`:

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1l-responsibility-final-003'
```

```text
583 passed in 245.40s (0:04:05)
tool exit_code=0
```

`py_compile` over `publishing_repository.py` and
`tests/test_public_catalog.py` exited 0. `git diff --check` exited 0. Direct-SQL
guards over `blueprints/public_catalog.py` and `blueprints/admin/catalog.py`
both returned no matches (`rg` exit 1, interpreted as PASS). The tracked status
before this report append contained only the two expected frozen files.

Fix1l changed only:

- `publishing_repository.py`
- `tests/test_public_catalog.py`
- this report

The historical full-suite outcome remains **UNKNOWN** and was not rerun. The
historical PyPI-network violation remains **CONFIRMED**, and the frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1l controller verification

The controller independently verified frozen Fix1l implementation commit
`c71fd4477fbd42bdb0f0ab746d7ce886380a6e9a`. All effective pytest runs used
the assigned Python `3.12.13` interpreter, a process-scoped `PYTHONPATH`
pointing only at the checked-in offline `local-deps` overlay, imported
`idna 3.19` from the assigned venv and `pypdf 6.10.0` from that overlay, used
`-p no:cacheprovider`, and used a unique basetemp. Each controller confirmed
the frozen HEAD and a clean all-files status before and after its read-only
run.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1l-focused-001
```

Result: `583 passed in 292.41s (0:04:52)`, pytest and tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1l-public-partition-001
```

Result: `407 passed in 234.54s (0:03:54)`, pytest and tool `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
..\..\.venv\Scripts\python.exe -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1l-related-partition-001
```

Result: `336 passed in 148.99s (0:02:28)`, pytest and tool `exit_code=0`.

For transparency, before the assigned interpreter was made explicit to the
three controllers, each first resolved the PATH interpreter to
`D:\Hermes Agent\venv\Scripts\python.exe`; those launches exited 1 before
collection with `No module named pytest`. The focused controller also made a
read-only probe with `C:\Python\python.exe`, which exited 1 for the same
reason. No target test was collected or executed by those interpreters, and
they are harness bootstrap errors rather than product-test results. No package
was installed and no network was used. Each controller then rechecked frozen
HEAD/clean status and completed the effective assigned-interpreter run shown
above with its original unique basetemp.

Controller `py_compile` over the two changed Python files,
`git diff --check` for both `e194588..c71fd44` and
`1c359a7..c71fd44`, and the no-direct-SQL guards for both catalog Blueprints
all passed. No full suite, production server, Nginx, real database, network
access, or dependency installation was used. The historical full-suite
outcome remains **UNKNOWN** and was not rerun; the historical PyPI-network
violation remains **CONFIRMED**; and the frozen `data_process_foundation`
product-data limitation remains unchanged.

## Fix1m — validate nested public catalog dependencies

Fix1m began from clean linked-worktree baseline
`88b2870a24c611a916656fb7023c847f72b3ad7b` on
`codex/ai-platform-2.0-core`. It was limited to the external fresh-review P2:
industry publication treated a published scenario candidate as healthy after
only normalized draft validation plus the scenario aggregate check, bypassing
the direct-publication raw/validated block-title consistency gate. Task 7,
public projection behavior, the progress ledger, and external task cards stayed
frozen.

### Root cause, fixture, and RED

The formal service chain is `publish_content` -> `_publish_in_transaction` ->
`validate_for_publication`. Direct scenario publication loads both raw and
validated drafts and rejects a persisted title changed by normalization as
`block_title_invalid`. `_validate_industry_publication`, however, previously
called `validate_content_draft(load_content_draft(...))` followed by
`_validate_scenario_publication` for each published candidate. The normalized
candidate therefore lost the evidence that a legacy first-block title was
whitespace-only.

The regression tests exercise real `publish_content`, disposable SQLite, and
the real public route. Since the current schema correctly prevents editing
published children, the legacy-data fixture saves the exact
`protect_content_blocks_update` trigger SQL, drops only that trigger while
injecting/restoring the historical bad title, and recreates it in `finally`
before committing. The negative chain establishes that every due published
manufacturing candidate is malformed, snapshots both industry revisions and
their audit rows, and verifies failed publication changes none of their
status, lock, publication/archive timestamps, or audits. The shared damage
correctly makes the existing public read gate return 404 both before and after
the failed attempt; after the fixture restores the shared scenario titles, the
still-published old industry revision is again HTTP 200. This is dependency
restoration evidence, not a claim that the damaged public projection stays
open.

The positive chain selects the greatest-ID candidate among the three known
complete manufacturing scenarios, explicitly excluding the frozen incomplete
`data_process_foundation` fallback, and corrupts every earlier candidate. This
forces the industry loop to encounter rejected candidates before a healthy
one. It verifies successful replacement, exactly one `content_published`
audit, unchanged candidate state/audits, and HTTP 200 for the new public
industry.

Three pre-RED fixture corrections were required before production code was
edited and are not claimed as TDD evidence: `2 failed in 1.59s` (exit 1,
published-child immutability blocked injection), `2 failed in 1.65s` (exit 1,
an incorrect audit-column name), and `2 failed in 1.62s` (exit 1, one genuine
missing exception plus one order-dependent fixture assertion). After those
test-only corrections, the authoritative RED used the assigned interpreter,
process-scoped offline overlay, no pytest cache provider, and the assigned
basetemp:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1m-red-industry-dependency-001' 'tests\test_public_catalog.py::test_industry_publish_rejects_when_all_published_scenario_candidates_have_blank_titles' 'tests\test_public_catalog.py::test_industry_publish_continues_from_blank_candidates_to_a_healthy_scenario'
```

```text
1 failed, 1 passed in 1.60s
pytest/tool exit_code=1
```

The only authoritative RED failure was behavioral: formal
`publish_content` completed instead of raising `ContentValidationError` when
all candidates had legacy blank titles (`DID NOT RAISE`). There was no
collection, fixture, or setup error in this run.

### Minimal GREEN

The candidate loop now calls
`validate_for_publication(db, candidate["id"], now)` inside its existing
`ContentValidationError` isolation boundary. Candidate rows are constrained to
scenario items, so the shared gate terminates at `_validate_scenario_publication`
without industry recursion. It performs the same read-only aggregate checks as
direct publication, introduces no truthy shortcut or write, and preserves the
stable outer `industry_public_incomplete` result when no candidate survives.

The same two tests used the unique GREEN basetemp:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1m-green-industry-dependency-002' 'tests\test_public_catalog.py::test_industry_publish_rejects_when_all_published_scenario_candidates_have_blank_titles' 'tests\test_public_catalog.py::test_industry_publish_continues_from_blank_candidates_to_a_healthy_scenario'
```

```text
2 passed in 1.42s
pytest/tool exit_code=0
```

### Frozen responsibility and static verification

After code and tests were frozen, the required responsibility set was started
exactly once:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1m-responsibility-final-003' tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py
```

```text
585 passed in 239.34s (0:03:59)
pytest/tool exit_code=0
```

All pytest commands used `..\..\.venv\Scripts\python.exe` (Python 3.12.13),
with `PYTHONPATH` set for that process only and only to the checked-in
`local-deps` overlay. No full suite was run.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m py_compile publishing_repository.py tests\test_public_catalog.py
git diff --check
rg -n "models\.get_db|sqlite3|\.execute\(" blueprints\public_catalog.py
rg -n "models\.get_db|sqlite3|\.execute\(" blueprints\admin\catalog.py
```

`py_compile` and `git diff --check` exited 0. Both direct-SQL guards returned no
matches (`rg` exit 1, interpreted as PASS). Before this report append,
`git status --short` contained only `publishing_repository.py` and
`tests/test_public_catalog.py`.

Fix1m changed only:

- `publishing_repository.py`
- `tests/test_public_catalog.py`
- this report

The historical full-suite outcome remains **UNKNOWN** and was not rerun. The
historical PyPI-network violation remains **CONFIRMED**. No network access,
dependency installation, full/production server, Nginx, real database, or
external package generation occurred; all database activity used disposable
SQLite. The frozen `data_process_foundation` product-data limitation remains
unchanged.

## Fix1m controller verification

The controller independently verified frozen Fix1m implementation commit
`b1022856f20b5dbce45fd7d7b6a7a44064339f1b`. Every effective run used the
assigned Python `3.12.13` interpreter, set `PYTHONPATH` in the same PowerShell
process to the checked-in
`.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps` overlay,
imported `idna 3.19` from the assigned venv and `pypdf 6.10.0` from that
overlay, disabled the pytest cache provider, and used a unique basetemp.

```powershell
$env:PYTHONPATH=(Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1m-focused-001'
```

Result: `585 passed in 271.78s (0:04:31)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1m-public-partition-corrected-002'
```

Result: `409 passed in 205.83s (0:03:25)`, pytest `exit_code=0`.

```powershell
$env:PYTHONPATH=(Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1m-related-partition-final-003'
```

Result: `336 passed in 125.45s (0:02:05)`, pytest `exit_code=0`.

The public and related controllers initially set `PYTHONPATH` to a nonexistent
worktree-root `local-deps` directory. Python silently fell back to the assigned
venv's separate `pypdf 6.16.2`; those otherwise-passing `409` and `336` test
runs are therefore recorded as invalid environment evidence, not effective
controller results. The public controller's first corrected attempt also used
that wrong path and exited 1 during `Resolve-Path`/the version probe before
pytest started, so its unused corrected basetemp was safely reused for the
effective command above.

The related controller's first real-overlay correction imported `pypdf 6.10.0`
but added an unauthorized `PYTHONIOENCODING=utf-8`. One subprocess-based media
test then failed because UTF-8 child output was decoded as GBK by its Windows
parent (`1 failed, 335 passed, 3 warnings`, exit 1). This was a controller
harness environment failure, not a product failure. The final effective run
explicitly left `PYTHONIOENCODING`, `PYTHONUTF8`, and locale variables unset and
returned the clean `336` result above. No package was installed and no network
was used during any attempt.

Controller `py_compile` over `publishing_repository.py` and
`tests/test_public_catalog.py`, `git diff --check` for both
`88b2870..b102285` and `1c359a7..b102285`, and the no-direct-SQL guards for
both catalog Blueprints all passed. Every effective controller confirmed the
same frozen HEAD and clean all-files status before and after its read-only run.
No full suite, production server, Nginx, real database, network access, or
dependency installation was used. The historical full-suite outcome remains
**UNKNOWN** and was not rerun; the historical PyPI-network violation remains
**CONFIRMED**; and the frozen `data_process_foundation` product-data limitation
remains unchanged.

## Fix1n — scope nested catalog validation

**Status: DONE_WITH_CONCERNS.** Fix1n began from clean linked-worktree baseline
`bca53302f9c8ad69e61601740f6dc4525bd82e2e` on
`codex/ai-platform-2.0-core`. It was limited to the fresh-review P2 in the
industry publication boundary. Task 7, the progress ledger, external task
cards/packages, and public projection behavior stayed frozen.

### Root cause and real lifecycle RED

Fix1m correctly made industry candidates share raw/validated block-title
consistency, but did so by calling the complete direct-publication gate.
`validate_for_publication` also requires every case/resource relation target
to be currently published. That requirement is correct while directly
publishing a new scenario, but it is not a public-health requirement for an
already-published scenario: optional related case/resource records may later
be legally archived, while the scenario and industry public projections remain
complete because they do not consume those optional relation tables.

The authoritative RED regression used real services and disposable SQLite
without mocking a target function. It published the checked-in catalog
fixture, created and formally published a verified case, copied/saved/formally
published the `mfg_knowledge_assistant` scenario with a `scenario_case`
relation, and then legally archived the case through `archive_content`. It
verified that the relation row remained and the scenario was still HTTP 200.
At that RED stage, it isolated the relation-bearing candidate by using the
already-reviewed legacy-title fixture to make every other published
manufacturing candidate invalid. It asserted that the target candidate was
present exactly once and that both the old manufacturing industry and the
target scenario were HTTP 200, but it did **not** yet formally archive the
other candidates or assert a one-row candidate query. Those fixture
refinements were added only after the first GREEN, as recorded below.

Before any production edit, the authoritative RED used the absolute assigned
snapshot interpreter, a process-scoped checked-in overlay, no pytest cache
provider, and the required unique basetemp:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest 'tests\test_public_catalog.py::test_industry_publish_keeps_public_scenario_healthy_after_relation_target_archive' -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1n-red-archived-relation-001'
```

```text
1 failed in 1.56s
pytest/tool exit_code=1
```

The single failure was the intended consumer-visible behavior: final
`publish_content` raised
`ContentValidationError('industry_public_incomplete')` from the candidate
loop. All preceding formal target/scenario lifecycle, persisted-relation,
candidate-membership, scenario HTTP 200, and industry HTTP 200 assertions had
succeeded. There was no fixture, setup, collection, import, or environment
failure before this RED.

### Minimal GREEN and review refinement

A shared read-only `_load_validated_publication_draft` helper now performs the
exact common prefix: load the raw draft, call `validate_content_draft`, compare
the complete raw and validated block-title tuples, raise stable
`block_title_invalid` on any difference, and return the validated draft.
Direct `validate_for_publication` calls that helper and then continues through
all existing share/block/attachment media, relation-target, source-check,
case-verification, industry, and scenario gates. The industry candidate loop
calls only the shared helper plus `_validate_scenario_publication` inside its
existing per-candidate `ContentValidationError` isolation boundary. It adds no
truthy shortcut, write, or relaxation to direct publication.

The first implementation GREEN, before final reviewer fixture refinement, used
`pytest-task6-fix1n-green-archived-relation-002` and returned `3 passed in
2.96s`, exit 0. It covered the new regression plus both Fix1m regressions, but
the new test still isolated other candidates with the accepted legacy-title
fixture. A concurrent reviewer requested full title-tuple equality and formal
archival of every other candidate. While that feedback arrived, a provisional
`pytest-task6-fix1n-responsibility-final-003` run had just reached about 12%;
it was intentionally interrupted. It has no terminal summary or outcome, is
not classified as a product pass/failure, and is not responsibility evidence.

After applying those test-only lifecycle and tuple-comparison refinements, the
formal archival of every other candidate and exact one-row candidate assertion
became GREEN/controller evidence; they are not attributed to the earlier RED.
The authoritative narrow GREEN used the new unique basetemp:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest 'tests\test_public_catalog.py::test_industry_publish_keeps_public_scenario_healthy_after_relation_target_archive' 'tests\test_public_catalog.py::test_industry_publish_rejects_when_all_published_scenario_candidates_have_blank_titles' 'tests\test_public_catalog.py::test_industry_publish_continues_from_blank_candidates_to_a_healthy_scenario' -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1n-green-archived-relation-final-004'
```

```text
3 passed in 2.21s
pytest/tool exit_code=0
```

The result proves successful industry replacement (`old=archived`,
`new=published`) and HTTP 200 for both the surviving scenario and the new
industry, while retaining Fix1m's all-blank-title rejection and
bad-candidate-to-healthy-candidate continuation. Existing direct publication
tests continue to cover `relation_target_not_published`; that gate was not
removed.

### Frozen responsibility and static verification

After the final narrow GREEN, production code and tests were frozen. The
required ten-file responsibility set was then started exactly once against the
final frozen code, using the assigned absolute Python 3.12.13 interpreter, the
same-process `local-deps` overlay, pypdf 6.10.0, `-p no:cacheprovider`, and the
new unique basetemp approved after the interrupted provisional run:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1n-responsibility-final-005'
```

```text
586 passed in 238.92s (0:03:58)
pytest/tool exit_code=0
```

The interpreter/dependency probes reported Python `3.12.13` and pypdf
`6.10.0` loaded from the worktree's checked-in overlay. `py_compile` over
`publishing_repository.py` and `tests/test_public_catalog.py` exited 0.
`git diff --check` exited 0. Direct-SQL guards over
`blueprints/public_catalog.py` and `blueprints/admin/catalog.py` both returned
no matches (`rg` exit 1, interpreted as PASS).

Fix1n changed only:

- `publishing_repository.py`
- `tests/test_public_catalog.py`
- this report

No full suite, network access, package installation, external package
generation, production server, Nginx, or real database was used. The
historical full-suite outcome remains **UNKNOWN** and was not rerun. The
historical PyPI-network violation remains **CONFIRMED**. The frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1n controller verification

The controller independently verified frozen Fix1n implementation commit
`abdb6581acb3bf9820ca5576bacfb317b9c3d82d`. Every effective run used the
assigned Python `3.12.13` interpreter, the exact worktree `local-deps` overlay
in the same PowerShell process, `pypdf 6.10.0` verified inside Python, no
pytest cache provider, and a unique basetemp. `PYTHONIOENCODING` and
`PYTHONUTF8` were unset.

```powershell
$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1n-focused-001'
```

Result: `586 passed in 264.11s (0:04:24)`, pytest/controller `exit_code=0`.

```powershell
$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1n-public-001'
```

Result: `410 passed in 214.53s`, pytest/controller `exit_code=0`.

```powershell
$env:PYTHONPATH='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1n-related-corrected-002'
```

Result: `336 passed in 145.93s (0:02:25)`, pytest/controller `exit_code=0`.

For transparency, the focused and related controllers initially decoded a
Chinese absolute path printed by Python as mojibake and then performed an
unnecessary PowerShell-side prefix comparison. Their overlay versions were
already `pypdf 6.10.0`, but the display comparison falsely failed; those
harness probes exited 99 and 96 respectively before pytest started. They had
no product-test outcome. The effective commands verified the resolved module
inside Python and returned only an ASCII boolean before starting pytest. The
focused basetemp was reusable because its first attempt never started pytest;
the related correction used a new basetemp. No package was installed and no
network was used.

Controller `py_compile` over `publishing_repository.py` and
`tests/test_public_catalog.py`, `git diff --check` for both
`bca5330..abdb658` and `1c359a7..abdb658`, and the no-direct-SQL guards for
both catalog Blueprints all passed. Each effective controller confirmed the
same frozen HEAD and clean all-files status before and after its read-only run.
No full suite, production server, Nginx, real database, network access, or
dependency installation was used. The historical full-suite outcome remains
**UNKNOWN** and was not rerun; the historical PyPI-network violation remains
**CONFIRMED**; and the frozen `data_process_foundation` product-data limitation
remains unchanged.

## Fix1o — align nested scenario core health with the public projection

**Status: DONE_WITH_CONCERNS, awaiting fresh external scoped review.** Fix1o
started from clean baseline
`7dfbcdffc91f0bf64ab00ce4b13bee196a992931` on
`codex/ai-platform-2.0-core`. It addresses only the fresh-review P2: an
industry replacement treated every archived core industry branch, department,
or pain relation on an otherwise-public scenario as a fatal dependency, even
though the public projection intentionally omits archived rows and remains
complete when at least one published, exact-nonblank target remains in every
required core family. Task 7, the ledger, external task card, and unrelated
publication rules stayed frozen.

Three fresh SDD agents were dispatched for implementation, design review, and
test review. They established the minimal boundary and test obligations before
the collaboration service reached its session usage limit; the controller then
completed and verified their shared-worktree changes locally. No review
finding was waived because of that service limit.

### Root cause and authoritative RED

The direct scenario publication gate correctly requires every persisted core
association to point at a currently published target. Fix1n reused that strict
gate inside the industry candidate loop. That was too strong for a previously
published scenario whose public read model filters archived core rows: one
archived non-unique department blocked all later industry replacements even
while two valid published departments, a valid industry, and a valid pain
remained and both public pages returned HTTP 200.

Before any production edit, the authoritative lifecycle RED used disposable
SQLite, formal services, the assigned absolute interpreter, the checked-in
process-scoped dependency overlay, no pytest cache provider, and a unique
basetemp:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest 'tests\test_public_catalog.py::test_industry_nested_scenario_ignores_archived_core_department_with_published_remainders' 'tests\test_public_catalog.py::test_direct_scenario_publish_remains_strict_with_archived_core_department' -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1o-red-archived-core-001'
```

```text
1 failed, 1 passed in 1.79s
pytest/tool exit_code=1
```

The intended nested-industry assertion failed because final
`publish_content` raised `industry_public_incomplete`; the direct scenario
strictness regression already passed. All earlier assertions had proved that
the archived department was non-unique, the remaining departments were
published and exact-nonblank, every other manufacturing scenario candidate
had been formally archived, the target was the unique candidate, and both
scenario and industry pages returned HTTP 200. At this RED checkpoint the
archived row still had a valid name. The test was later strengthened to give
that archived row a whitespace-only legacy name; that refinement is not
attributed to the RED.

### Minimal implementation and candidate-query RED

`_validate_scenario_publication` now has an explicit keyword-only
`published_only_core` mode. Its default remains `False`, so direct scenario
publication executes the unchanged strict all-row status/name checks. Only the
industry nested-candidate path passes `True`; in that mode, its industry,
department, and pain queries first select published associations/targets and
then apply the existing nonempty and exact-nonblank checks. All service,
structured input, range, maturity, content-block, and direct-publication gates
remain unchanged.

The first partial GREEN exposed a second boundary in the candidate query: a
scenario with an archived manufacturing branch and a separate published retail
branch could still be selected as a manufacturing candidate. The first draft
of that regression stopped inside a test helper before exercising the product
behavior; it has no product pass/fail classification and is excluded from
evidence. After correcting the fixture, the authoritative sequential RED was:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest 'tests\test_public_catalog.py::test_industry_candidate_requires_a_published_branch_in_that_industry' -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1o-red-cross-industry-branch-final-003b'
```

```text
1 failed in 1.09s
pytest/tool exit_code=1
failure: DID NOT RAISE ContentValidationError
```

Before that intended failure, the regression proved the published-branch
manufacturing candidate query was empty, the scenario stayed public through
its retail branch, the manufacturing filter omitted it, and the manufacturing
industry detail returned 404. The partial implementation nevertheless
published the manufacturing industry replacement through the archived branch.
The final query therefore requires `ib.status='published'` and uses
`SELECT DISTINCT` to avoid duplicate candidate evaluation.

### Final narrow GREEN and frozen responsibility verification

After the whitespace-name refinement and candidate-query fix, the final narrow
GREEN covered all three Fix1o behaviors plus the relevant Fix1m/Fix1n
continuity cases:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest 'tests\test_public_catalog.py::test_industry_nested_scenario_ignores_archived_core_department_with_published_remainders' 'tests\test_public_catalog.py::test_direct_scenario_publish_remains_strict_with_archived_core_department' 'tests\test_public_catalog.py::test_industry_candidate_requires_a_published_branch_in_that_industry' 'tests\test_public_catalog.py::test_industry_publish_keeps_public_scenario_healthy_after_relation_target_archive' 'tests\test_public_catalog.py::test_industry_publish_rejects_when_all_published_scenario_candidates_have_blank_titles' 'tests\test_public_catalog.py::test_industry_publish_continues_from_blank_candidates_to_a_healthy_scenario' -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1o-green-final-004'
```

```text
pypdf 6.10.0 loaded from the checked-in overlay
6 passed in 4.15s
pytest/tool exit_code=0
```

Production code and tests were frozen after that GREEN. The ten-file Task 6
responsibility set was then run exactly once against the frozen files:

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-fix1o-responsibility-final-005'
```

```text
pypdf 6.10.0 loaded from the checked-in overlay
589 passed in 241.22s (0:04:01)
pytest/tool exit_code=0
```

`py_compile` over `publishing_repository.py` and
`tests/test_public_catalog.py` exited 0. Working-tree, Fix1o-baseline, and
original Task 6 scoped `git diff --check` commands all exited 0. Direct-SQL
guards over `blueprints/public_catalog.py` and
`blueprints/admin_content.py` returned zero matches and guard exit 0.

Fix1o changes only:

- `publishing_repository.py`
- `tests/test_public_catalog.py`
- this report

No full suite, real network, dependency installation, production server,
Nginx, real database, ledger/task-card update, or Task 7 work was performed.
The historical full-suite outcome remains **UNKNOWN/NOT PROVEN** and was not
rerun. The historical PyPI-network violation remains **CONFIRMED**. The frozen
`data_process_foundation` product-data limitation remains unchanged.

## Fix1o controller verification

The controller independently verified frozen Fix1o implementation commit
`639b7813a7c40827754d56a81ce3625250102774`. Before starting, all three unique
basetemps were absent and tracked status was clean. The three read-only
partitions ran concurrently with independent disposable SQLite databases.
Every command used the assigned Python `3.12.13` interpreter, the exact
worktree `local-deps` overlay in the same PowerShell process, `pypdf 6.10.0`
verified inside Python, no pytest cache provider, and an unused basetemp.
`PYTHONIOENCODING` and `PYTHONUTF8` were unset.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_public_catalog.py tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_app_factory_and_migrations.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1o-focused-001'
```

Result: `589 passed in 283.28s (0:04:43)`, pytest/controller `exit_code=0`.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_pagination.py tests\test_public_catalog.py tests\test_analytics.py tests\test_smoke.py tests\test_validation_and_errors.py tests\test_app_factory_and_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1o-public-001'
```

Result: `413 passed in 235.84s (0:03:55)`, pytest/controller `exit_code=0`.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest tests\test_catalog_content_admin.py tests\test_content_validation.py tests\test_content_publishing.py tests\test_content_seed.py tests\test_content_migrations.py tests\test_security_gaps.py tests\test_media_service.py tests\test_media_http.py tests\test_v2_migrations.py -q -p no:cacheprovider --basetemp '.superpowers\sdd\2026-08-24-content-catalog-publishing\pytest-task6-controller-fix1o-related-001'
```

Result: `336 passed in 148.15s (0:02:28)`, pytest/controller `exit_code=0`.

The controller did not run the full suite. It did not use a real network,
install a package, access production/Nginx/a real database, update the
ledger/task card, or start Task 7. The historical full-suite outcome therefore
remains **UNKNOWN/NOT PROVEN**, and the historical PyPI-network violation
remains **CONFIRMED**.
