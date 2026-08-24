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
