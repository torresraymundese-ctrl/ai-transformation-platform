# Public UI redesign — local evidence

## Scope and boundaries

- Plan BASE: `5d7cd99952e62cd1146bd5ba4fafba028e054aa5`; visual-fix HEAD: `b906bc8b415ab4c34d00651b8ac9c959d37f556b`.
- This evidence covers only the public homepage, scenario catalog/detail, and resource detail. It does not cover assessment/report UI, admin UI, all functions, final full regression, or deployment.
- All browser work used the Codex in-app browser on a disposable `127.0.0.1` fixture. No production server, real database, public URL, deploy, dependency install, or external-resource navigation was used.
- Existing unrelated Task 12 working-tree changes were preserved and were not staged with this evidence.

## Frozen-source checks

```powershell
git rev-parse HEAD
git status --short
git diff --check 94693e765f215bf78b5708f7cacd4eb9cc4b857c..HEAD
node --check static/js/app.js
```

HEAD was exactly `b906bc8b415ab4c34d00651b8ac9c959d37f556b`. The range diff check and Node syntax check both exited `0`.

## Scoped automated verification

Interpreter and offline dependencies: Python `3.12.13`, Node `v24.14.1`, `pypdf 6.10.0`; `PYTHONPATH` was the absolute `.../.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps` path.

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py tests/test_pagination.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp\task6-rerun-b906bc8b-auditable
node --test tests/js/app_runtime.test.js tests/js/analytics_runtime.test.js
```

Fresh Python result on the visual-fix HEAD: `523 passed in 267.18s (0:04:27)`, exit `0`; outer timing record: `268.191s`. Node: `7` passed, `0` failed, exit `0`, `166.4532ms`. This is the plan's frozen public partition only, not a full suite.

## Disposable fixture and cleanup

The fixture used the existing application factory, migrations, normal admin HTTP publishing workflow, local source-check transport, disposable SQLite, and disposable media storage.

- Command: `python .superpowers/sdd/2026-08-26-ui-foundations-public-catalog/task6_local_fixture.py --db .../task6-visual-rerun-b906bc8b.db --media .../task6-visual-rerun-b906bc8b-media --host 127.0.0.1 --port 62637`.
- Process tree: launcher PID `6840`, listener PID `25580`, console child `9356`; the only application listener was `127.0.0.1:62637`.
- Cleanup: the exact child/listener/launcher processes were stopped; post-stop verification reported `Listening=false` and no remaining process IDs. The in-app viewport override was reset and its temporary tab was closed.
- Fixture DB/media/log/helper remain only as ignored local control artifacts under the Task 6 SDD directory; no fixture path is staged.

## Current-run screenshots

The in-app Browser layout viewport override was explicitly set to `1440×1024` or `390×844`. Its native screenshot API exported the currently visible content surface as `1425×875` on desktop and `375×811` on mobile. Every exact saved PNG was inspected after its final capture.

| Screenshot | Route / requested viewport | Exported dimensions / SHA-256 | Overflow | Inspection result |
| --- | --- | --- | --- | --- |
| [home-desktop.png](evidence/ui-public/home-desktop.png) | `/` / `1440×1024` | `1425×875` / `A69FC2BE0EAA52DE628DC3AB86A5C99FEABC4994A5A62C6AC3E01D48B559578C` | `scrollWidth=clientWidth=1425` | Accepted: hierarchy, long heading, navigation, and primary/secondary actions render without clipping or horizontal overflow. |
| [scenarios-desktop.png](evidence/ui-public/scenarios-desktop.png) | `/scenarios` / `1440×1024` | `1425×875` / `55F82F8F52E440CE8B1C952DF8334D16A99D51E814B0582E2DE3826A458060EC` | `1425=1425` | Accepted: filters, labels, six visible cards, long Chinese copy, and active navigation render without horizontal overflow. |
| [scenario-detail-desktop.png](evidence/ui-public/scenario-detail-desktop.png) | `/scenarios/mfg-knowledge-assistant` / `1440×1024` | `1425×875` / `BA64E435DD535BB8E52C03340E718B201240B7CA9ECEFE2ECA668811C5EB6D41` | `1425=1425` | Accepted: breadcrumb, title, verified context row, numbered chapters, and decision summary are simultaneously visible; no horizontal overflow. |
| [scenario-detail-mobile.png](evidence/ui-public/scenario-detail-mobile.png) | same scenario / `390×844` | `375×811` / `DDD8A2B29B089A87A2BF64104B7F3272E456F5143DB750DDD5BD39456536CFA8` | `375=375` | Accepted: header, theme/context, summary, and long text wrap cleanly. Settled CTA is exactly `72px`, `flex-wrap: nowrap`, with `72px` body reservation. |
| [resource-detail-mobile.png](evidence/ui-public/resource-detail-mobile.png) | `/resources/task6-reviewed-resource` / `390×844` | `375×811` / `BBB06437124E5906BF811F3F8C1948BAFB2696F4ECF58A0FDF8FFACC202B5610` | `375=375` | Accepted after scrolling to the attachment/footer state: the attachment remains reachable above the footer; the settled `72px` CTA has `72px` body reservation and no two-row expansion. |

## Approved-baseline comparison

The final `scenario-detail-desktop.png` and `docs/design/evidence/2026-08-26-ui-visual-baseline.png` were inspected together in one comparison input.

Matches now include the white shell, active `AI 场景` navigation, one navy theme containing the breadcrumb/title/context, three verified context columns, a left decision narrative/right sticky summary relationship, visible leading-zero chapter numbering, and primary/secondary actions. The production page remains intentionally data-driven rather than pixel-identical: it uses the published section sequence and actual `4—8 周` / `50000.0—100000.0` values, and does not reproduce the concept image's decorative geometric art or icon illustrations. No final screenshot showed a blank/loading/wrong page, cropped action, or page-level horizontal overflow.

## Real interaction evidence

- Mobile menu: opened by a real Browser click; a real Browser `Escape` closed it and left focus on `<summary>菜单</summary>`.
- Scenario filter: `manufacturing + production + explore` preserved all selected values and returned exactly `制造知识助手` at `/scenarios?industry=manufacturing&department=production&maturity=explore&per_page=20`.
- Empty/reset: `retail + production + explore` produced zero cards and the visible empty state “暂时没有符合条件的内容”. Activating a visible `清除筛选` link returned to `/scenarios`, restored `12` cards, and removed the empty state.
- Pagination: **NOT EXERCISED — fixture has one page** (`12` published scenarios, smallest available `per_page=20`, zero page links).
- Internal CTAs: real local clicks reached `/assessment` (`企业 AI 就绪度评估`), `/service-packages` (`企业 AI 转型服务包`), and returned to `/scenarios`; all pages loaded locally.
- Resource source link was inspected without navigation: `href=https://source.example/guides/ai-readiness`, `target=_blank`, `rel="noopener noreferrer"`.

## Native keyboard status and limits

**NOT PROVEN.** All required keys were attempted through the in-app Browser's real keypress input after a fresh DOM snapshot; no JavaScript focus mutation, synthetic event, Node test, HTTP request, or mouse surrogate was counted as keyboard evidence.

- `Escape`: observed PASS for the open mobile menu; it closed and focus stayed on its summary.
- `Tab` and `Shift+Tab`: active element remained `<summary>菜单</summary>`; no native focus movement was observed.
- `Enter` and `Space`: the focused summary remained closed; no native activation was observed.

The available Browser input backend therefore does not prove native default behavior for the full required key set. Screenshot evidence also cannot establish assistive-technology behavior, full WCAG conformance, 200% text zoom, or reduced-motion behavior.

## Outcome

The five production visual defects targeted by Fix 1 are closed in current local evidence, and the frozen public partition/Node checks pass. This UI plan remains blocked at the evidence checkpoint because native Tab/Shift+Tab/Enter/Space is `NOT PROVEN`; no claim is made that all UI, all functions, final full regression, or deployment is complete.
