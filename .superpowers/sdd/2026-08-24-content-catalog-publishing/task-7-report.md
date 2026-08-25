# Task 7 Report — Publish complete service-package pages

## Status

- Result: CLEAN — external review passed
- Branch: `codex/ai-platform-2.0-core`
- Frozen starting HEAD: `bf6a819990c4cfeab83bcb5be52cbc6d136c1e3a`
- Date: 2026-08-25 (Asia/Shanghai)
- Scope: Stage 5A Task 7 only; no production database, Nginx, network, dependency installation, or Task 6 files were touched. The controller updates this report, `progress.md`, and the external task card only after the implementation/review evidence is frozen.
- Full suite policy: the one and only full-suite run covered the frozen initial implementation. Review Fix1/Fix2 then changed production/tests and were verified with focused and related partitions under the explicit no-rerun gate; the full suite was not rerun or represented as covering those later commits.

## Bound requirements and adjudications

The implementation follows `task-7-brief.md` and the service, failure-boundary, test, and acceptance sections of `docs/superpowers/specs/2026-08-24-content-operations-design.md`.

Three conflicts were escalated before or during implementation and resolved as follows:

1. Service maturity is revision-owned and explicit. Additive migration `008_service_content_maturity.sql` expands the exact maturity owner validation trigger from scenario-only to scenario-or-service without rewriting frozen migration 006. The frozen `protect_content_maturity_insert` trigger remains installed byte-for-byte; 008 backfills only draft service revisions. Service maturity is non-empty and restricted to `explore`, `pilot`, `scale`, `collaborate`; other content types still reject it.
2. The initial six service mappings are fixed one-time unions of the currently frozen related scenario seed maturity, ordered `explore,pilot,scale,collaborate`:
   - `foundation_workshop`: `explore`
   - `knowledge_assistant_pilot`: `explore,pilot,scale`
   - `customer_growth_pilot`: `explore,pilot,scale`
   - `workflow_automation`: `explore,pilot,scale`
   - `data_insight`: `pilot,scale,collaborate`
   - `industry_integration`: `pilot,scale,collaborate`
3. A valid related scenario is a published frozen V2 core relation with at least one valid published industry branch and department. It need not have a Task 6 public-complete scenario page. Pain facets may therefore be empty; `foundation_workshop` renders the real empty state `暂无特定痛点限制`. Authority retains the valid core relation for gates/facets, while public related-content includes only public-complete scenario pages, so it emits neither raw `scenarios.public_name` codes nor broken links.

The shared formal publication validator was explicitly brought into scope. Immediate `publish_content` and due-job publication use the same service completeness rules and transaction boundary.

## Implementation

- Added canonical `/service-packages` and `/service-packages/<slug>` HTTP adapters using existing `Page`, `PageRequest`, `public_catalog`, `PUBLIC_BASE_URL`, private/no-store shell, and analytics CSRF shell.
- Retained `/services` as a permanent 301 compatibility redirect. Per Fix1 scope review, shared home/navigation/footer links remain at the Task 7 baseline `/services`; shared navigation integration is deferred to Task 11. The new service-package list/detail links themselves use canonical `/service-packages` URLs.
- Added `ServiceAuthority`, immutable service/facet/deliverable/scenario projections, exact fixed category/integration/maturity Chinese labels, stable deduplication/order, explicit revision maturity, safe seven-block projection, and optional published case/resource/scenario relations.
- `ServiceAuthority` injection validates its own snapshot and never falls back to mutable service/scenario tables after injection.
- Kept report-critical budget, weeks, deliverables, exclusions, acceptance, support, disclaimer, and rule-derived facets in frozen core authority; content revisions supply narrative/SEO/blocks/relations only.
- Added service publish gates for meaningful content, exact core structure, valid published deliverables, explicit maturity, and at least one valid related scenario with industry and department branches.
- Preserved the frozen analytics contract `page=services`, `source=service_packages`, and added safe `service_inquiry_clicked` markers to canonical list/detail primary CTAs.
- Added migration/seed/validation/app-factory/V2 compatibility coverage and the exact six-service maturity/facet fixtures.

## TDD evidence

All pytest invocations used this same-process prefix and no network:

```powershell
$env:PYTHONPATH = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report\.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps'
& 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --basetemp <unique-absolute-path> <selectors>
```

### Initial RED

Only `tests/test_public_services.py` was created before production edits.

1. `<selectors> = tests\test_public_services.py`; basetemp `.tmp\task7-red-20260825-001`; exit 1, `1 failed, 27 errors`. Invalid evidence because the parent basetemp directory did not exist.
2. Same selector; basetemp `task7-red-20260825-002`; exit 1, `28 failed`. Invalid evidence because one setup tried an illegal direct `published -> archived` state transition.
3. Same selector; basetemp `task7-red-20260825-003`; exit 1, `28 failed`. Invalid evidence because one setup still used an illegal direct `draft -> archived` transition.
4. Accepted RED: same selector; basetemp `task7-red-20260825-004`; exit 1, `28 failed in 17.09s`, with no collection/setup errors. Failures covered missing migration 008, rejected service maturity, 404 routes, absent authority, unguarded formal publication dependencies, and due-job failure handling.

### Initial GREEN and adjudicated edge RED/GREEN

- `tests\test_public_services.py`, basetemp `task7-green-20260825-001`: exit 1, `27 passed, 1 failed`; production behavior was correct and the due-job test expected a guessed audit name instead of the existing `content_due_failed` event.
- Same selector, basetemp `task7-green-20260825-002`: exit 0, `28 passed in 15.31s`.
- `tests\test_public_services.py::test_service_uses_core_scenario_name_without_link_when_scenario_page_is_incomplete`, basetemp `task7-edge-red-20260825-001`: exit 1, `1 failed in 0.94s`; proved the missing/incomplete related-scenario boundary.
- `tests\test_public_services.py -k scenario_name`, basetemp `task7-validator-red-20260825-001`: exit 1, `2 failed, 28 deselected in 1.70s`; proved both blank core scenario-name validation and the incomplete page projection issue.
- The first attempted edge GREEN, basetemp `task7-edge-green-20260825-001`, exited 1 (`1 passed, 1 failed`) because `scenarios.public_name` is intentionally the raw stable code. Root cause was corrected: do not expose that code; hide the optional relation unless the scenario page is public-complete.
- `tests\test_public_services.py -k 'scenario_page_is_incomplete or scenario_name'`, basetemp `task7-edge-green-20260825-002`: exit 0, `2 passed, 28 deselected in 1.40s`.
- Full focused file, basetemp `task7-focused-green-20260825-003`: exit 1, `28 passed, 2 failed`; two older focused assertions still expected the now-forbidden incomplete scenario projection.
- Full focused file, basetemp `task7-focused-green-20260825-004`: exit 0, `30 passed in 16.73s`.

## Related regressions

Exact related selector set:

```text
tests\test_public_services.py
tests\test_assessment_catalog.py
tests\test_matching.py
tests\test_reporting.py
tests\test_report_access.py
tests\test_content_migrations.py
tests\test_content_seed.py
tests\test_content_validation.py
tests\test_app_factory_and_migrations.py
tests\test_v2_migrations.py
tests\test_content_publishing.py
tests\test_public_catalog.py
tests\test_analytics.py
tests\test_smoke.py
```

- Basetemp `task7-related-20260825-001`: exit 1, `697 passed, 2 failed in 299.03s`. Failures: the old relation-copy fixture omitted mandatory service maturity; analytics expected the retired page token.
- Basetemp `task7-related-20260825-002`: exit 1, `697 passed, 2 failed in 294.32s`. This corrected the first diagnosis: explicit maturity exposed that the fixture selected legacy `services` rows with null V2 authority fields and lacked a meaningful service block. Analytics evidence also showed that `services` is the frozen allowlisted page token and `service_packages` is the source token; changing the page token was wrong.
- Exact two regressions only:
  `tests\test_content_publishing.py::test_all_six_relation_types_survive_revision_copy tests\test_analytics.py::test_public_pages_expose_safe_analytics_data_and_external_click_markers`, basetemp `task7-related-fix-green-20260825-001`: exit 0, `2 passed in 2.16s`.
- Identical related set, basetemp `task7-related-20260825-003`: exit 0, `699 passed in 290.00s`.

Production was not loosened for either related failure. The fixture now selects only `code IS NOT NULL` frozen V2 services and creates meaningful content; analytics preserves its existing allowlist.

## Full suite and static verification

- One and only full-suite command used `<selectors> =` the entire discovered suite (no selector), basetemp `task7-full-20260825-001`: exit 0, `1175 passed in 519.44s (0:08:39)`.
- Absolute interpreter `-m py_compile blueprints\public.py blueprints\public_catalog.py catalog_content_repository.py content_seed.py content_validation.py publishing_repository.py`: exit 0.
- `git diff --check`: exit 0 (only Git line-ending notices, no whitespace error).
- Blueprint SQL guard over `blueprints/public_catalog.py` for `get_db`, `.execute(`, and `execute_write`: `CLEAN`, exit 0.
- Temporary pytest basetemp directories were resolved under the exact worktree before recursive removal; no test database or temp artifact is retained.

## Changed files

Production/data:

- `blueprints/public.py`
- `blueprints/public_catalog.py`
- `catalog_content_repository.py`
- `content_seed.py`
- `content_validation.py`
- `publishing_repository.py`
- `service_authority.py`
- `migrations/008_service_content_maturity.sql`
- `seed_data/content_catalog_v1.json`

Templates:

- `templates/service_packages.html`
- `templates/service_package_detail.html`
- `templates/services.html`
- `templates/index.html` (touched in the initial commit, then restored exactly; no net Task 7 diff)
- `templates/components/navigation.html` (touched in the initial commit, then restored exactly; no net Task 7 diff)
- `templates/components/footer.html` (touched in the initial commit, then restored exactly; no net Task 7 diff)

Tests:

- `tests/test_public_services.py`
- `tests/test_content_migrations.py`
- `tests/test_content_seed.py`
- `tests/test_content_validation.py`
- `tests/test_content_publishing.py`
- `tests/test_app_factory_and_migrations.py`
- `tests/test_v2_migrations.py`
- `tests/test_analytics.py`
- `tests/test_smoke.py`

## Self-review and limitations

- Scope review: all changed files are directly required by the Task 7 brief or explicit adjudicated expansions; no SQL exists in the Blueprint.
- Security review: public narrative blocks still pass the existing seven-type validation/sanitization projection; private/no-store and analytics CSRF shell remain intact; no draft, future, archived, raw JSON, raw scenario code, or fallback authority is exposed.
- Transaction review: formal immediate/due publication rejects incomplete services before replacement; tests prove the old revision row is not replaced and no successful publish audit/lock state survives a failure. A revision-local maturity failure additionally proves the old slug remains HTTP 200. Direct corruption of shared live V2 authority makes detail reads for the affected service fail closed with HTTP 404; the list omits that item only and remains HTTP 200 with healthy services visible. This is not described as the old page staying online.
- Historical report review: a healthy narrative-only replacement leaves the existing assessment report snapshot digest byte-stable.
- Initial catalog has no service case/resource relations, so those optional subsections remain hidden until separately published and related content exists.
- Public-complete related scenario links are intentionally optional; the core relation still gates publication and drives facets even when its Task 6 page is incomplete.
- Visual polish and the 5B active rule-snapshot provider are outside Task 7. The `ServiceAuthority` injection boundary is in place for the later provider swap.

## Fix round 1 — internal review corrections

Fix1 started from `443ff35b696df9ab971091425434b797ec3a45c2`. It did not implement the later 5B persistent authority snapshot: both publication and public reads intentionally consume the same live frozen V2 core authority. Consequently, shared-core corruption makes the affected service detail fail closed even though the published revision row remains unchanged; list isolation omits only that invalid item. Revision-local validation failures are the case in which the previous detail page is proven to remain HTTP 200.

### Fix1 implementation

- Preserved migration 006's non-draft child immutability trigger. Migration 008 now changes only the maturity owner validation triggers and inserts the six fixed maturity mappings only for `content_items.status='draft'`.
- Added the leaf module `service_authority.py`, which imports neither catalog nor publishing code. It owns frozen exact dataclasses, the fail-closed predicate, and the live-V2 loader. `publishing_repository.py` and `catalog_content_repository.py` both import this one module, so their authority shapes and validity rules cannot diverge and there is no catalog/publishing import cycle.
- The shared shape covers exact service code/name/category, budgets, weeks, four structured lists, support/disclaimer, deliverable code/title/nullable description, scenario id/code/core name/integration, published industry/department/pain code+name facets, and deterministic integration ordering. Exact dataclass/tuple checks reject malformed injected objects and unhashable field values without leaking `AttributeError` or `TypeError`.
- Catalog enrichment uses `dataclasses.replace` only to add an optional pair of public-complete scenario `title`/`slug`; it cannot replace the frozen scenario code, core name, integration, or facet snapshot.
- Service list and detail open a deferred SQLite read transaction before their first SELECT and complete resolution/list, authority, maturity, blocks, and related children on that connection. A real two-connection WAL regression atomically interleaves a revision/core replacement and proves the response is the complete old or complete new pair, never a mixture; no write lock is requested.
- Removed raw service/facet/maturity/integration/deliverable code values from public HTML. Exact code sets/order remain asserted at the repository projection boundary, while templates render fixed Chinese labels and non-business structural markers only.
- When scenario/case/resource relations are all empty, the required `related-content` structural marker is hidden and empty; the visible title is absent. `foundation_workshop` remains HTTP 200 and keeps its truthful pain empty state.
- Reverted `templates/index.html`, `templates/components/navigation.html`, and `templates/components/footer.html` exactly to the Task 7 pre-change baseline while retaining the `/services` 301 route.

### Fix1 RED/GREEN evidence

Every valid run used the absolute interpreter and same-process offline overlay shown earlier, `-p no:cacheprovider`, and a unique absolute basetemp.

- Migration immutability accepted RED: `tests/test_content_migrations.py::test_008_backfills_only_draft_services_and_preserves_non_draft_maturity`, basetemp `task7-fix1-migration-red-20260825-002`; exit 1, `1 failed`; non-draft maturity rows changed because old 008 inserted into published/archived service revisions. An earlier `-001` was a superseded fixture error (non-canonical published slug), not accepted RED. GREEN basetemp `task7-fix1-migration-green-20260825-001`; exit 0, `1 passed in 0.15s`.
- Authority parity accepted RED: formal shared-authority parameter set plus revision-local and due nodes, basetemp `task7-fix1-authority-red-20260825-001`; exit 1, `10 failed, 20 passed in 17.17s`. Missing gates were deliverable code/description, service code, scenario code/integration, industry code, department code, pain code/name, and due deliverable description. Malformed injected-child RED, basetemp `task7-fix1-injection-red-20260825-001`; exit 1, `1 failed` with leaked `AttributeError`. GREEN basetemp `task7-fix1-authority-green-20260825-002`; exit 0, `31 passed in 18.71s`. The prior `-001` was infrastructure-invalid: the basetemp parent did not exist, causing 31 setup errors before tests executed.
- Additional injected-field-type RED found during self-review: basetemp `task7-fix1-injection-types-red-20260825-001`; exit 1, `1 failed in 0.97s`, reproducing `TypeError: unhashable type: 'list'`. GREEN basetemp `task7-fix1-injection-types-green-20260825-001`; exit 0, `1 passed in 0.73s`.
- SQLite snapshot RED: `test_public_service_reads_one_sqlite_snapshot_during_concurrent_replacement` list/detail parameters, basetemp `task7-fix1-snapshot-red-20260825-001`; exit 1, `2 failed in 1.60s`, both proving no transaction preceded the first SELECT. GREEN basetemp `task7-fix1-snapshot-green-20260825-001`; exit 0, `2 passed in 1.45s`.
- HTML/raw-code/empty-related RED: four focused list/facet/format/deliverable nodes, basetemp `task7-fix1-html-red-20260825-001`; exit 1, `4 failed in 3.01s`. GREEN basetemp `task7-fix1-html-green-20260825-001`; exit 0, `4 passed in 2.96s`.
- Shared shell baseline RED: `tests/test_smoke.py::test_shared_home_navigation_and_footer_stay_on_the_task7_baseline`, basetemp `task7-fix1-shared-shell-red-20260825-001`; exit 1, `1 failed in 0.74s`. GREEN basetemp `task7-fix1-shared-shell-green-20260825-001`; exit 0, `1 passed in 0.68s`.

### Fix1 focused and related verification

- Final complete focused file: `tests/test_public_services.py`, basetemp `task7-fix1-focused-public-services-20260825-002`; exit 0, `45 passed in 25.68s`.
- Related selectors were the same 14 files listed in **Related regressions**, including migration, publishing, analytics, and smoke; basetemp `task7-fix1-related-20260825-001`; exit 0, `716 passed in 302.10s (0:05:02)`.
- Per review instruction, the already recorded single full suite (`1175 passed`) was not rerun in Fix1.
- Absolute-interpreter `py_compile` over `blueprints/public.py`, `blueprints/public_catalog.py`, `catalog_content_repository.py`, `content_seed.py`, `content_validation.py`, `publishing_repository.py`, and `service_authority.py`: exit 0.
- Blueprint database/SQL guard: `CLEAN: public_catalog Blueprint contains no database access or SQL`, exit 0.
- Migration-008 frozen-protection guard: `CLEAN: 008 preserves the frozen 006 protection trigger`, exit 0.

### Fix1 changed files and limits

Implementation/tests changed by Fix1:

- `service_authority.py`
- `catalog_content_repository.py`
- `publishing_repository.py`
- `migrations/008_service_content_maturity.sql`
- `templates/service_packages.html`
- `templates/service_package_detail.html`
- `templates/index.html` (exact baseline revert)
- `templates/components/navigation.html` (exact baseline revert)
- `templates/components/footer.html` (exact baseline revert)
- `tests/test_content_migrations.py`
- `tests/test_public_services.py`
- `tests/test_smoke.py`

The ignored SDD report is not part of the implementation commit. No production/real database, external network, Nginx, task card, ledger, `progress.md`, Task 6 file, dependency, or full-suite state was changed.

## Fix round 2 — top-level injection and list isolation

Fix2 started from `e6afeb2ae05f6259a09e049cf5eb4dcdb62c8c58` and changed only `catalog_content_repository.py` and `tests/test_public_services.py`.

- `_service_projection` previously dereferenced `authority.service_id` before calling `valid_service_authority`. A supplied `object()` or `dict` therefore leaked `AttributeError` instead of failing closed. Fix2 validates any supplied top-level authority first, then compares its validated `service_id`; a provider-loaded authority is independently validated before projection. No broad exception handler was added.
- Public service lists retain their existing per-item isolation: one service with invalid shared authority is omitted, while the HTTP list remains 200 and includes healthy services. Only the affected detail returns 404. Empty directories also remain HTTP 200, and publishing then archiving the only service returns the list to that same empty lifecycle while its detail becomes 404. This corrects any ambiguous earlier wording that could be read as one bad service hiding the entire list.

Fix2 TDD and verification evidence, using the same absolute interpreter/offline overlay, `-p no:cacheprovider`, and unique absolute basetemps:

- RED, top-level injection plus HTTP list isolation nodes, basetemp `task7-fix2-authority-list-red-20260825-001`: exit 1, `1 failed, 1 passed in 1.63s`. The top-level `object()` reproduced `AttributeError: 'object' object has no attribute 'service_id'`. The real Flask/temporary-SQLite list-isolation characterization already passed and is recorded as such, not falsely described as a separate RED.
- Initial GREEN after the validation-order fix, basetemp `task7-fix2-authority-list-green-20260825-001`: exit 0, `2 passed in 1.38s`.
- Final precise nodes after removing the duplicate validation call, basetemp `task7-fix2-authority-list-green-20260825-002`: exit 0, `2 passed in 1.49s`.
- Empty/published/archived list lifecycle characterization, basetemp `task7-fix2-list-lifecycle-characterization-20260825-001`: exit 0, `1 passed in 0.81s`. This bound existing behavior and required no production change.
- Final complete focused `tests/test_public_services.py`, basetemp `task7-fix2-focused-public-services-20260825-002`: exit 0, `48 passed in 26.56s`. The earlier pre-lifecycle focused run `-001` also exited 0 with `47 passed in 26.07s`.
- Impacted public/smoke partition `tests/test_public_catalog.py tests/test_smoke.py`, basetemp `task7-fix2-public-smoke-20260825-001`: exit 0, `282 passed in 130.96s (0:02:10)`.
- Absolute-interpreter `py_compile catalog_content_repository.py service_authority.py`: exit 0.
- Blueprint database/SQL guard: `CLEAN: public_catalog Blueprint contains no database access or SQL`, exit 0.
- `git diff --check`: exit 0 with line-ending notices only.
- Per Fix2 instruction, neither the 716-node related partition nor the full suite was rerun.

## Controller review checkpoint

- Final internal HEAD: `d63cdb6bb2bede4358199971e206f4a7e11bff0a` from baseline `bf6a819990c4cfeab83bcb5be52cbc6d136c1e3a`; implementation commits are `443ff35b696df9ab971091425434b797ec3a45c2`, `e6afeb2ae05f6259a09e049cf5eb4dcdb62c8c58`, and `d63cdb6bb2bede4358199971e206f4a7e11bff0a`.
- Fresh final review package: `review-bf6a819..d63cdb6.diff`; 3 commits, 21 files/headers, 134252 bytes, 2942 text lines, SHA-256 `CFACE5A58F9B796DF4583A623E0EF9986F5FE2EE1915B5F5E7A1985B079A6DF4`; reverse apply check exit 0.
- Fresh independent Fix2 reviewer verdict: CLEAN, with no P0, P1, P2, or P3. The reviewer independently matched HEAD, clean status, file count, package hash, authority validation order, list isolation, SQLite snapshot, migration protection, HTML boundaries, and the no-Task-11-net-diff constraint.
- Controller focused command selected `tests/test_public_services.py` plus `tests/test_content_migrations.py::test_008_backfills_only_draft_services_and_preserves_non_draft_maturity`, with unique basetemp `task7-controller-20260825-001`: exit 0, `49 passed in 30.94s`.
- Controller `py_compile`, full Task 7 range `git diff --check`, Blueprint SQL guard, basetemp cleanup, exact HEAD, and tracked/untracked status all passed/clean.
- External review state: CLEAN. “审查企业AI转型平台” independently matched the branch, HEAD, 3-commit/21-file review scope, package SHA-256, task-card SHA-256, clean status, and no-production/no-network boundary. Its fresh scoped run of the controller selector set passed `49` tests; it did not rerun the full suite or access any real resource.
- External gate: the reviewer returned the exact phrase `审查通过，可以继续下一步`. Task 7 is complete and Task 8 is authorized under the existing plan/spec.
