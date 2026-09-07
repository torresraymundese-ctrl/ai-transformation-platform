# Admin experience cross-page QA

Status: **local evidence finalized for review; Task 4 and whole-closeout review remain pending**. This record must not be read as a production, Lighthouse/Core Web Vitals, native 200% browser-zoom, physical-print, or real-data acceptance result.

## Scope and isolation

QA was performed on 2026-09-07 against the closeout branch and a loopback-only disposable fixture server at `http://127.0.0.1:62851`. The browser account, catalog content, copied rule, label asset, and stale-write conflict were synthetic TEST ONLY fixtures in a new temporary database under the ignored SDD workspace. No production service, external network, worktree `data/`, report data, or user data was accessed or changed.

The controller reset the temporary viewport, closed only the owned in-app-browser tab, and stopped only the verified `62851` fixture-server process and launcher. Follow-up process/listener checks returned no rows. The user's original report tab and preview at `127.0.0.1:62841` were retained. Existing dirty `README.md`, `docs/testing/core-assessment-report.md`, and `data/` paths remain outside this closeout evidence commit.

The user accepted the existing report unchanged. This closeout did not edit report templates, report CSS/JavaScript, the PDF adapter, scoring, matching, ROI, report publishing, or report seed data.

## Reviewed change boundary

The final broad review boundary is the accepted closeout baseline `e718aa9a16c1f2b0f2611b03cf35d9609dd88cd2` through the eventual final closeout HEAD. Before this evidence-only commit, implementation HEAD is `4e9842728a9b7e7732df83ce9c14aa2105f0da00`; the range contains 50 files changed, 2,548 insertions, and 335 deletions. This is not a fresh audit of the branch's much larger historical change set before `e718aa9`.

Task-level independent reviews are clean after their recorded fix loops:

- Task 1: shared shell review fixes closed at `f7895f79b54c276e7d826fe4bac4b7ba9874936e`; the final integration assertion was corrected and independently reviewed at `424b5d58b4d217131acd205c683ce4950873fccf`.
- Task 2: editor/list review closed after the runtime relationship-label fix at `69ba0b1ec2770bcff21e3bef4bf821ef75d655c3`.
- Task 3: SEO/asset review closed after complete approved-detail dependency coverage at `4e9842728a9b7e7732df83ce9c14aa2105f0da00`.
- Whole-closeout review of `e718aa9..final HEAD`: pending controller dispatch/result. Stage 6 is not represented as blanket-complete while this review gate remains open.

## Browser route and responsive evidence

The final responsive matrix contains 30 direct DOM measurements: six representative real routes at five measured CSS viewports. Every row has exactly one `main`, exactly one `h1`, and equal document client/scroll width.

| Measured CSS viewport | Routes checked | Document client/scroll width |
| --- | ---: | ---: |
| 1440x1024 | 6 | 1425/1425 |
| 1024x768 | 6 | 1009/1009 |
| 768x1024 | 6 | 753/753 |
| 390x844 | 6 | 375/375 |
| 320x844 | 6 | 305/305 |

The six routes are `/admin`, `/admin/resources`, `/admin/catalog/scenario/4`, `/admin/resources/new`, `/admin/legal/new`, and `/admin/rules/2`. The 1440px shell uses a 240px navigation column. At narrower sizes the navigation remains in normal flow; all 19 navigation links/buttons remained available.

Additional controller checks covered:

- Login and logout: the actual POST logout returned `/admin/login`; the 320px login had one main, no management navigation, no document overflow, and unclipped 44px brand/return targets. Synthetic credentials submitted through native `ENTER`.
- Active lists: leads, appointments, privacy requests, assets, media, assessments, the three catalog lists, resources, cases, announcements, ingestion, legal, and rules were inventoried. Fifteen changed list routes were rechecked at 320px with one `h1`, one main, and no document overflow.
- Empty states and filters: an unmatched lead query rendered `暂无匹配线索`; appointments rendered `暂无预约`. Selecting the actual `50 条` pagination-size link preserved the search and filter query keys and changed only `per_page=50` on page 1.
- Editors: scenario, new resource, new case, new announcement, new legal, copied-rule, and four asset auxiliary editors were rendered. At 320px the resource/case/announcement/legal forms had 5/5/5/3 named sections respectively, labelled controls, and no document overflow; the copied rule had eight named sections.
- Action reachability: scenario save/check/publish/schedule/archive actions were visible and fit the 320px content column; the three primary scenario actions measured 44px. The copied rule exposed its save and preview actions. No action was removed or represented as validated beyond the exercised synthetic fixture state.
- Required-field behavior: submitting the empty resource form stayed on the route and moved native focus to required `slug` with `validity.valueMissing=true`.
- Conflict behavior: two tabs edited the same synthetic scenario. The stale second save rendered the exact 409 conflict alert and focused `.admin-error-summary[role=alert][tabindex="-1"]`. This proves the native conflict-summary focus path, not every HTTP 400 rendering path.
- Dynamic controls: the real Add Relation action created `relations-0-target_group_id` with a wrapping visible `关联目标` label and retained the selected synthetic value.
- Populated label sheet: at 320px the document measured 305/305 while the fixed-width 767px sheet scrolled inside a 273px local wrapper; all four toolbar controls measured 44px. Print dimensions were not changed.
- Keyboard/focus: native `TAB` focused the skip link, `ENTER` moved focus to `main#admin-main`, and the next `TAB` reached the first queue link with a visible focus ring. On login, `TAB` reached the outlined submit button, `SHIFT+TAB` returned to the password field, and `ENTER` submitted. Native `SPACE` toggled the collaborate checkbox. `ESCAPE` was sent after the native required-field check, but there was no applicable modal to close, so no modal-dismissal claim is made.
- Public legal metadata: after the final implementation restart, live loopback DOM contained exactly `https://preview.invalid/legal/privacy`, `https://preview.invalid/legal/privacy/test-privacy-v1`, and `https://preview.invalid/legal/terms` as the current privacy, historical privacy, and current terms canonicals, each with its synthetic reviewed summary description.

Edge's default tab zoom was 90%, so requested capability dimensions and encoded PNG dimensions are not treated as CSS viewport evidence. The matrix and screenshot manifest use measured CSS viewport values. Narrow-viewport checks are not represented as an actual 200% browser-zoom test.

## Screenshot evidence

These are unedited bytes returned by successful browser captures and visually inspected by the controller. Timed-out capture attempts and the browser's `ERR_BLOCKED_BY_CLIENT` page are excluded. Encoded pixels can differ from CSS viewport dimensions because of browser surface and zoom; these are viewport captures, not full-document captures.

| File | Browser / route / measured CSS viewport | Encoded px | Bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `docs/design/evidence/admin-actions-320.png` | IAB, `/admin/catalog/scenario/4`, 320x844 | 305x804 | 31,451 | `7EE53A829B124F00FA665E4C361C31B8AADC79D4DAB3B9C1DDA2982C3E631771` |
| `docs/design/evidence/admin-catalog-390.png` | IAB, `/admin/catalog/scenario/4`, 390x844 | 375x811 | 33,294 | `E3820AD1B475C8EB84344369E28B1FDC694E456B5F5A2AA1774C8C2C7A921AC4` |
| `docs/design/evidence/admin-conflict-390.png` | IAB, `/admin/catalog/scenario/4`, 390x844 | 375x811 | 32,047 | `1C76391A2D5CE11388A81E885A2D45CF8A3621671628E952EF2FA84EFCBC96BF` |
| `docs/design/evidence/admin-dashboard-1440.png` | IAB, `/admin`, 1440x1024 | 1425x847 | 76,228 | `C634E93E545C0975849D78833F5F99AA741E652460CE53197E7283F4ECCCDCCF` |
| `docs/design/evidence/admin-empty-1440.png` | Edge, `/admin/leads?q=QA-empty-no-matching-record`, 1440x1024 | 1581x1138 | 68,565 | `3741FFF6E6D68E208DA929B266C9EEF9C2A1A365F95904820B9D8ADB55E67293` |
| `docs/design/evidence/admin-labels-320.png` | IAB, `/admin/assets/labels?unit=B`, 320x844 | 305x804 | 21,734 | `613513F32BB8102B60392A9E5A265AD7526BEA37B49ED726F250F0CBE99C761F` |
| `docs/design/evidence/admin-login-320.png` | Edge, `/admin/login`, measured width 320; height not retained | 356x938 | 18,292 | `F1405D7DF6BBE4FD6CDF347E56B349F080533DEB59ECAF06E190A8A0CD5620E7` |
| `docs/design/evidence/admin-rule-1440.png` | IAB, `/admin/rules/2`, 1440x1024 | 1425x847 | 73,512 | `E147D87E73ABD9D0EF012A3A909461186DA939FF8AAC0CE0AEEDEA8D92AADC8B` |

`admin-actions-320.png` records the normal narrow action area; it is not an error screenshot. `admin-conflict-390.png` is the proven native 409 conflict state. The older Edge login capture has verified CSS width 320, but its exact CSS height was not retained and is intentionally recorded as unknown.

## Automated verification record

All Python commands used the repository virtual environment, isolated ASCII basetemp directories, and `-p no:cacheprovider` unless a retained command below explicitly shows otherwise. Tests wrote only to disposable TEST ONLY locations.

### Task 1: shell and operations

| Command / phase | Actual result |
| --- | --- |
| `python -m pytest tests/test_admin_auth.py tests/test_operations_dashboard.py tests/test_operations_pagination.py -q` (baseline) | 58 passed in 38.22s |
| `python -m pytest tests/test_admin_ui.py -p no:cacheprovider -q` (initial RED) | 6 failed, 1 passed in 5.14s |
| Same focused file after initial implementation | 7 passed in 4.74s |
| `python -m pytest tests/test_admin_ui.py tests/test_admin_auth.py tests/test_operations_dashboard.py tests/test_operations_pagination.py tests/test_content_navigation.py -p no:cacheprovider -q` | 97 passed in 60.66s |
| `python -m pytest tests/test_admin_ui.py tests/test_admin_auth.py tests/test_content_navigation.py -p no:cacheprovider -q` after review fixes | 50 passed in 31.83s |
| Exact obsolete journey assertion reproduction | 1 failed in 0.89s |
| Exact journey assertion after alignment | 1 passed in 0.90s |
| `python -m pytest tests/test_operations_journey.py tests/test_admin_ui.py -p no:cacheprovider -q` | 17 passed in 16.76s |

The journey RED reproduced the first full suite's only failure: it required the removed flat navigation order and inline 640px CSS. The test-only correction asserts the exact grouped destinations, logout/CSRF, local stylesheet media/containment rules, tables, lead filters, and CSV export.

### Task 2: editors and list consistency

| Command / phase | Actual result |
| --- | --- |
| `python -m pytest -p no:cacheprovider tests/test_admin_editor_ui.py` (initial RED) | 4 failed in 3.02s |
| Same focused file after initial implementation | 4 passed in 4.19s |
| Label target-size exact RED / GREEN | 1 failed in 0.85s / 1 passed in 0.74s |
| Populated-sheet local-containment exact RED / GREEN | 1 failed in 1.00s / 1 passed in 0.78s |
| Asset auxiliary heading/label exact RED | 1 failed in 2.11s; its GREEN is included in the final six-test run |
| `python -m pytest -p no:cacheprovider tests/test_admin_ui.py tests/test_admin_auth.py tests/test_admin_editor_ui.py tests/test_catalog_content_admin.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_legal_versions.py tests/test_rule_release_admin.py` | 280 passed in 291.05s |
| `python -m pytest -p no:cacheprovider tests/test_admin_editor_ui.py -q` after the bounded auxiliary extension | 6 passed in 6.49s |
| `node --test tests/js/content_editor_runtime.test.js tests/js/admin_ui_runtime.test.js` relationship-label RED / GREEN | 12 passed, 1 failed / 13 passed, 0 failed; GREEN duration 153.1155ms |

### Task 3: public SEO and local asset baseline

| Command / phase | Actual result |
| --- | --- |
| `python -m pytest tests/test_public_performance.py -q -p no:cacheprovider` (initial RED) | 3 failed, 12 passed in 10.47s |
| Same focused file after initial implementation | 16 passed in 11.49s |
| Public navigation/UI-foundation/catalog/legal focused regressions listed in the Task 3 report | 30 passed in 20.53s |
| Remote dependency negative-mutation RED | 2 failed in 0.18s as expected |
| `python -m pytest tests/test_public_performance.py -q -p no:cacheprovider` after review round 1 | 20 passed in 12.49s; a distinct retained post-commit run was 20 passed in 12.61s |
| Approved-detail mutation RED | 1 failed in 0.91s as expected |
| Four approved-detail/legal focused fixtures after round 2 | 4 passed in 3.40s |
| Final Task 3 covering file after round 2 | 21 passed in 12.59s |

The read-only loopback inventory contains 18 successful HTML routes, 160 rendered local references, and 21 unique local assets totalling 1,375,192 decoded bytes. These totals are a deduplicated local inventory, not per-page transfer weight or a production speed score. `python -m pip check` reported `No broken requirements found.`

### Controller-wide runs

The controller's final Node invocation covered all eight `tests/js/*.test.js` runtime files: 50 passed, 0 failed, 0 skipped, exit 0, in 361.1361ms.

The first full repository run used `python -m pytest -q -p no:cacheprovider` with an isolated `C:/Users/zz/AppData/Local/Temp/admin-final-0907-a384b21f97014fa2a16dd67baf854428` basetemp and process-local native DLL configuration. It completed with **1 failed, 2,202 passed in 1,251.25s (20:51), exit 1**. Its sole failure was `tests/test_operations_journey.py::test_admin_shell_contains_mobile_navigation_tables_and_lead_controls`, the obsolete shell assertion described above. Commit `424b5d5` then reproduced it RED, corrected it test-only, and passed the exact and 17-test covering runs.

A second full repository attempt started at implementation HEAD `4e9842728a9b7e7732df83ce9c14aa2105f0da00` with `python -m pytest -q -p no:cacheprovider`, process-local `PYTHONIOENCODING=utf-8`/native DLL settings, and isolated basetemp `C:/Users/zz/AppData/Local/Temp/admin-final-rerun-0907-a26664a5c91b4d3cb98292e7c9ac9f30`. It was canceled by the controller at 61% after `tests/test_media_http.py::test_module_and_test_factories_allow_injection_but_wsgi_requires_safe_production_root` failed. The inherited UTF-8 setting made child Python emit UTF-8 while the Windows parent's `subprocess.run(..., text=True)` reader decoded with GBK; three reader threads raised `UnicodeDecodeError`, leaving captured `stdout` as `None`. A controlled one-test reproduction with the UTF-8 override produced 1 failed and 3 warnings in 3.49s; the same unchanged test under the original default environment passed in 3.29s. No application or test-code change was made for this harness-only mismatch. Because the run was canceled and did not reach a final suite summary, it is not a passing full run.

The final verification in `final-pytest-native.log` ran at the same implementation HEAD, using the original Windows encoding environment (no `PYTHONIOENCODING` override), the existing process-local native DLL setting, and isolated basetemp `C:/Users/zz/AppData/Local/Temp/admin-final-native-0907-dec39e896c184638b96e1fa2f57c410b`. The canceled attempt left no Python processes. The native-environment run completed with **2,208 passed in 1,233.91s (20:33), exit 0**. Its final output contains no failure, warning, or skip summary.

## Explicitly unproven or deferred

- Actual native 200% browser zoom/reflow on the updated backend is unproven. The measured 320/390px viewport matrix is useful responsive evidence but is not equivalent to zoom.
- Native visual rendering/focus of the generic HTTP 400 error page is unproven because both tested browser surfaces did not present that body. The 409 conflict alert/focus path is proven; focused HTTP and Node tests cover the generic summary contract.
- Physical print/A4 output is unproven. Only temporary print-media emulation and CSS assertions were checked; emulation was restored after measurement.
- Actual next-page UI behavior with more than 20 records is unproven. The real page-size interaction preserved filters and selected 50 rows per page; HTTP tests cover pagination/query behavior.
- `ESCAPE` modal dismissal is not claimed because the exercised form had no applicable modal. Runtime coverage exists for the public mobile navigation Escape behavior, not an admin modal.
- No Lighthouse, Core Web Vitals, compressed transfer, CDN, reverse-proxy cache, production latency, or deployment result was measured.
- Browser captures contain only representative synthetic fixture states. They do not validate production data quality, permissions for real accounts, or every possible content length/localization combination.

## Deferred local evidence and Stage 7 authority gates

Native 200% zoom, a generic 400 response rendered in a capable browser surface, and a synthetic dataset large enough to exercise a real next-page UI can be verified locally when the required browser capability/fixture is available; they do not require production credentials or server access. A physical-print check requires an available device and explicit approval before printing.

Stage 7 production work separately requires new authority and environment-specific inputs: a named target server/environment, deployment credentials and access approval, approved real-data migration/validation scope, backup/rollback plan, and production monitoring/acceptance owners. Production compression/CDN/cache behavior, Lighthouse/Core Web Vitals, production latency, and real-data acceptance belong to that authorized environment. None of those production actions was performed or implied by this local closeout.
