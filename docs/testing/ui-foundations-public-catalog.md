# Public UI redesign — local evidence

## Scope and boundaries

- Plan BASE: `23e6a29b80c26c92b219cb3694691965bfbdbcad`; current code HEAD for this evidence: `426be81061a7dfd668bb37035ffe35300326719e`.
- This evidence covers only the public homepage, scenario catalog/detail, and resource detail. It does not cover assessment/report UI, admin UI, all functions, final full regression, or deployment.
- All browser work used the Codex in-app browser on a disposable `127.0.0.1` fixture. No production server, real database, public URL, deploy, dependency install, or external-resource navigation was used.
- Existing unrelated Task 12 working-tree changes were preserved and were not staged with this evidence.

## Full-plan review Fix 2

The first complete-plan review of `23e6a29..a0cd1c9` found five P2 accessibility/responsive defects: mismatched CTA accessible names, a low-contrast focus indicator, low-contrast inactive shell text, a four-column mobile footer, and sub-44px shell link targets.

The production fix is commit `426be81061a7dfd668bb37035ffe35300326719e` (`fix: improve public UI accessibility`) and changes exactly:

- `static/css/design-tokens.css`
- `static/css/ui-components.css`
- `templates/industry_detail.html`
- `templates/scenario_detail.html`
- `tests/test_ui_foundations.py`

TDD evidence used a unique plan-owned basetemp and the command-scoped offline dependency layer. After correcting fixture setup that initially returned unrelated 404 pages, the true RED was `5 failed in 3.09s`; the same five event/HTTP/CSS contracts reached `5 passed in 2.88s`.

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
& $py -m pytest `
  tests/test_ui_foundations.py::test_shared_focus_rules_make_the_skip_link_and_focus_visible `
  tests/test_ui_foundations.py::test_decision_cta_accessible_name_matches_its_visible_label `
  tests/test_ui_foundations.py::test_shared_navigation_and_footer_use_readable_text_colors `
  tests/test_ui_foundations.py::test_shared_navigation_and_footer_links_keep_touch_targets_and_mobile_columns `
  -q -p no:cacheprovider `
  --basetemp .superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp\full-review-fix1-green-20260827-a
```

Current-code responsibility verification used basetemp `full-review-fix1-responsibility-20260827-a` and passed `438 passed in 225.52s`, exit `0`:

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_resources_announcements.py -q -p no:cacheprovider --basetemp .superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp\full-review-fix1-responsibility-20260827-a
node --check static/js/app.js
node --test tests/js/app_runtime.test.js tests/js/analytics_runtime.test.js
```

Node syntax exited `0`; Node runtime passed `7`, failed `0`, exit `0` (`140.29ms`). `py_compile tests/test_ui_foundations.py` and the scoped diff check also exited `0`.

The earlier frozen public partition remains useful historical evidence only: it passed `523` tests on exact visual-fix HEAD `b906bc8b415ab4c34d00651b8ac9c959d37f556b`. It was not rerun before this re-review and therefore is not claimed to cover `426be81`. No full suite was run.

## Disposable fixture and cleanup

The post-fix fixture used the existing application factory, migrations, normal admin HTTP publishing workflow, local source-check transport, disposable SQLite, and disposable media storage.

- Command: `python .superpowers/sdd/2026-08-26-ui-foundations-public-catalog/task6_local_fixture.py --db .../task6-full-review-fix1-frozen.db --media .../task6-full-review-fix1-frozen-media --host 127.0.0.1 --port 62711`.
- Process tree: launcher PID `24488`, listener PID `19612`, console child PID `21104`; the only application listener was `127.0.0.1:62711`.
- Cleanup: the exact listener/launcher processes were stopped, the console child exited, and post-stop verification reported `port 62711 closed`. The in-app viewport override was reset, the tab was moved to `about:blank`, and the tab was closed.
- Fixture DB/media/log/helper remain only as ignored local control artifacts under the Task 6 SDD directory; no fixture path is staged.

## Current-run screenshots

The in-app Browser layout viewport override was explicitly set to `1440×1024` or `390×844`. Its native screenshot API exported the visible content surface as `1425×875` on desktop and `375×811` on mobile. Every exact final PNG was inspected after capture; the desktop scenario detail was also compared with the approved baseline in the same visual input.

| Screenshot | Route / requested viewport | Exported dimensions / SHA-256 | Inspection result |
| --- | --- | --- | --- |
| [home-desktop.png](evidence/ui-public/home-desktop.png) | `/` / `1440×1024` | `1425×875` / `A09B3D31D4C04AD197850D291D4F6F60882C8F4D151913599EF170725AA1BF1F` | Accepted: hierarchy, long heading, navigation, and primary/secondary actions render without clipping or horizontal overflow. |
| [scenarios-desktop.png](evidence/ui-public/scenarios-desktop.png) | `/scenarios` / `1440×1024` | `1425×875` / `B8298BB7FB72246A472C6CD03B75DAC0DA8D9FB4863BDFECB46F4C347E1746D4` | Accepted: filters, six visible cards, long Chinese copy, active navigation, and shell text render without horizontal overflow. |
| [scenario-detail-desktop.png](evidence/ui-public/scenario-detail-desktop.png) | `/scenarios/mfg-knowledge-assistant` / `1440×1024` | `1425×875` / `BD1AF61E2BAF14EB4B61E2D0FDF0A6B88F2CE457D26FAD37849B8452DFB9446E` | Accepted: breadcrumb, title, verified context, numbered chapters, decision summary, and CTA are visible; no horizontal overflow. |
| [scenario-detail-mobile.png](evidence/ui-public/scenario-detail-mobile.png) | same scenario / `390×844` | `375×811` / `E0355246E8FFDD1B7BD211B1B6C7F87F4D2BADE42A748C4D20AA42AA24C242A1` | Accepted: long text wraps cleanly; the settled CTA is `72px`, nowrap, with `72px` body reservation and no content overlap. |
| [resource-detail-mobile.png](evidence/ui-public/resource-detail-mobile.png) | `/resources/task6-reviewed-resource` / `390×844` | `375×811` / `1C8C033675D2732EAF9D4ADEE76F3BFDC0348E6251292A42614E94A69C73AD66` | Accepted: footer is two columns with its company block spanning the row; final copyright remains reachable above the fixed CTA. |

## Approved-baseline comparison

The final scenario detail keeps the approved white shell, active `AI 场景` navigation, one navy theme containing breadcrumb/title/context, three verified context columns, a left decision narrative/right sticky summary relationship, leading-zero chapter numbering, and primary/secondary actions. It intentionally renders published data rather than copying decorative concept art or invented metrics.

## Real interaction and accessibility evidence

- CTA name: industry/scenario detail visibly says `获取适配建议` and has no conflicting `aria-label`.
- Focus: a real Browser click opened the mobile menu; real `Escape` closed it and restored focus to `<summary>菜单</summary>`. The computed focus style was solid `rgb(15, 95, 239)` with the expected outline/offset after capture scaling.
- Shell contrast/targets: inactive navigation/footer text uses `--ui-ink-650`; navigation, mobile-menu, and footer links have a minimum `2.75rem` target height.
- Scenario filter: `manufacturing + production + explore` preserved all values and returned exactly `制造知识助手`.
- Empty/reset: `retail + production + explore` produced the empty state; `清除筛选` restored `/scenarios` and 12 cards.
- Internal CTAs: real local clicks reached `/assessment`, `/service-packages`, and `/scenarios`.
- Resource source link was inspected without navigation: `target=_blank`, `rel="noopener noreferrer"`.
- Pagination: **NOT EXERCISED — fixture has one page** (`12` scenarios; smallest `per_page=20`).

## Native keyboard status and limits

**NOT PROVEN.** `Escape` was observed to work. Through the available in-app Browser keypress backend, `Tab`, `Shift+Tab`, `Enter`, and `Space` did not produce native default movement/activation. Programmatic focus, synthetic events, HTTP, Node, and mouse actions were not substituted as keyboard proof.

The screenshots and scoped checks also do not establish full WCAG conformance, 200% text zoom, assistive-technology behavior, all UI, all functions, final full regression, or deployment readiness.

## Outcome

The five accessibility/responsive defects from the first full-plan review are addressed in local code and exact refreshed visual evidence. The plan remains blocked at the evidence checkpoint because native `Tab`/`Shift+Tab`/`Enter`/`Space` is `NOT PROVEN`; no next UI plan or deployment may start.
