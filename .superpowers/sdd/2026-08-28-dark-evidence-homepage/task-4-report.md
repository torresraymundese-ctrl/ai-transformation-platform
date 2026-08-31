# Task 4 Report — Blocking same-viewport design QA and evidence

## QA fix 1 — restore guided content links

- Frozen base: `12ec7056a2cc1a952f5bec5ee7727ae2447fb318`.
- Scope: `templates/index.html` only.
- Root cause: the Task 2 homepage composition moved published industry and scenario links out of the URL-matrix chapters consumed by the established navigation contract.
- RED observed before resumption: the scoped Python responsibility set completed with `1 failed, 394 passed`; the failing assertion was `tests/test_content_navigation.py::test_rendered_server_links_follow_the_url_context_matrix`, while the Node responsibility set remained `21 passed`.
- Minimal fix: the Hero audit note now exposes the first published scenario in `story-purpose`; `story-matching` now renders up to two published industries before its published scenario links. Existing published-only view models and route helpers are reused; no query, route, schema, or data-layer change was made.

### Fresh GREEN

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmp=Join-Path $PWD '.superpowers\sdd\2026-08-28-dark-evidence-homepage\test-tmp\task4-guided-links-green-008'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp $tmp
```

Result: `395 passed in 216.40s (0:03:36)`, exit `0`.

```powershell
node --check static/js/app.js
node --check static/js/guided_story.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/analytics_runtime.test.js
git diff --check -- templates/index.html
```

Results: both syntax checks exit `0`; Node `21 passed`, exit `0`; diff check exit `0` with only the existing LF/CRLF advisory.

## Safety and scope

- No real network, dependency installation, production service, public listener, Nginx, systemd, real database, or full suite was used.
- Pre-existing Task 12 dirty paths were left untouched and are excluded from the QA-fix commit.

## Browser QA fix 2 — compact and mobile responsive boundaries

The first exact-viewport Browser captures exposed three visual P2s: the fixed
chapter rail covered the 910px Hero artwork, the 1024px Hero heading wrapped to
a single-character final line, and the mobile chapter labels shrank into each
other with a coarse platform scrollbar. The implementation now reserves the
2.75rem rail outside compact content, uses a deliberate compact-title scale,
and gives every mobile chapter step an unshrinking scroll slot while hiding the
platform scrollbar without blocking native horizontal scrolling.

Accepted RED runs:

- `task4-responsive-red-009`: `1 failed in 1.22s`, exit `1` (missing compact content reservation).
- `task4-compact-title-red-011`: `1 failed in 0.94s`, exit `1` (oversized compact heading rule).
- `task4-mobile-scrollbar-red-013`: `1 failed in 1.07s`, exit `1` (coarse visible mobile scrollbar).

Fresh GREEN evidence:

- `task4-responsive-green-010`: `1 passed in 0.86s`, exit `0`.
- `task4-compact-title-green-012`: `1 passed in 0.87s`, exit `0`.
- `task4-mobile-scrollbar-green-014`: `1 passed in 0.76s`, exit `0`.
- `task4-responsive-responsibility-green-015`: `39 passed in 22.55s`, exit `0`.
- Node app/guided runtime: `18 passed`, exit `0`.
- Focused diff check: exit `0` with only existing LF/CRLF advisories.

Affected 1024px, 910px, and 390px captures were reloaded and recaptured after
the GREEN changes. The Browser state reported no page overflow at any of those
widths, no rail overlap with Hero text or artwork at 910px/1024px, a two-line
1024px heading, and a 390px scrollable chapter strip with distinct step boxes
and `scrollbar-width: none`.

## Browser QA fix 3 — activate the long evidence chapter

The 1440px interaction pass showed that clicking `验证价值` scrolled to
`#story-evidence` while the current progress marker remained on chapter 04.
The evidence section is substantially taller than the central observer root,
so its maximum intersection ratio could not reach the previous 0.25 minimum.
The observer now retains the same central root but includes a 0.05 threshold;
native scrolling and the no-wheel-listener contract are unchanged.

- RED: `node --test tests/js/guided_story_runtime.test.js` → `14 passed, 1 failed`, exit `1`; the observer still exposed `[0.25, 0.5, 0.75]`.
- GREEN: syntax check exit `0`; app/guided/analytics Node responsibility set → `22 passed`, exit `0`; focused diff check exit `0` with only existing LF/CRLF advisories.
- Fresh Browser proof after reload: clicking chapter 05 produced `hash=#story-evidence`, `current=#story-evidence`, `active=story-evidence`, `scrollY=2517`.

## Browser QA fix 4 — remove the 320px page overflow

The explicit 320px contract check found `clientWidth=305`, `scrollWidth=320`,
and a reachable horizontal `scrollX=15.2`. The homepage root's 20rem minimum
width included the vertical scrollbar gutter and forced the document wider than
its layout viewport. The root now allows `min-width: 0`; responsive children
continue to own their normal minimum sizes.

- RED `task4-320-overflow-red-016`: `1 failed in 1.04s`, exit `1`.
- GREEN `task4-320-overflow-green-017`: `1 passed in 0.73s`, exit `0`.
- Fresh UI responsibility set `task4-320-responsibility-green-018`: `39 passed in 22.46s`, exit `0`.
- Fresh Browser after reload and attempted horizontal scroll: `innerWidth=320`, `clientWidth=305`, `scrollWidth=305`, `scrollX=0`; the Hero heading, CTA, progress strip, and art remained readable in the inspected 320×844 capture.

## Final Browser evidence and cleanup

- The selected option-1 reference and final 1440 capture were inspected together; the final 1024, 910, and 390 captures were inspected together in a separate comparison input. No P0–P2 remained.
- Five chapter controls, fast/reverse scrolling, two assessment CTAs, scenario/service/case/resource fixture links, mobile menu open/Escape close, final CTA/footer, console, and narrow-width overflow were exercised through the Codex in-app Browser.
- Native Tab traversal, native reduced-motion emulation, and native 200% zoom remain honestly `NOT PROVEN` by the available Browser surface. Runtime coverage proves reduced-motion static behavior; a 720px geometry proxy passed but is not represented as native zoom evidence.
- Evidence: `design-qa.md`, `docs/testing/dark-evidence-homepage.md`, and four PNGs under `docs/design/evidence/`.
- Cleanup: viewport reset, browser tab closed, exact fixture PIDs `23576` and `13616` stopped; `remaining_count=0`, `listener_count=0`, and `port_open=False` for `127.0.0.1:58443`.
- No full suite, external network, install/update, production access, deployment, public listener, Nginx, systemd, or real database was used.
- Evidence commit: `7c9cfc2539fb39f46e78743a8ad47ed5fa15a45d` (`docs: verify the dark evidence homepage`), exactly the two reports and four required PNGs.

## Fix round 1/5 — keep catalog entries out of the Hero

- Review base: `7c9cfc2539fb39f46e78743a8ad47ed5fa15a45d`.
- Review finding verified: the binding spec says the Hero has one assessment CTA and defers scenario/service/case/resource entry points to later chapters, while `a698f07` had added a scenario detail link to `story-purpose`. The matching chapter already contains real published industry/scenario links, so the earlier URL-matrix expectation was stale rather than a missing-route condition.
- TDD RED: updated `test_rendered_server_links_follow_the_url_context_matrix` to require the exact scenario under `story-matching`, forbid its href under `story-purpose`, and forbid the Hero label `查看已发布场景`; result `1 failed in 1.83s`, exit `1`, at the expected Hero scenario assertion.
- Minimal GREEN: removed only the conditional scenario link from the Hero audit note, leaving the plain `基于已审核内容` proof note. Exact test: `1 passed in 1.50s`, exit `0`.
- Fresh scoped responsibility set: `395 passed in 206.26s`, exit `0`, unique basetemp `task4-fix1-final-scoped-021`.
- Node responsibility: syntax checks exit `0`; app/guided/analytics `22 passed`, exit `0`; focused diff check exit `0`.
- Code/test commit: `e0e361969601bb97dc889697d45407cf82f6cec8` (`fix: keep scenario entry out of the homepage hero`), exactly `templates/index.html` and `tests/test_content_navigation.py`.
- Documentation P3: corrected both stale underscore-style CSS paths to `static/css/dark-evidence-home.css`; this remains in the refreshed evidence commit.
- Fresh Browser fixture: `.superpowers/sdd/2026-08-28-dark-evidence-homepage/test-tmp/task4-browser-fix1-20260831-001`, bound only to `127.0.0.1:60052`; launcher/listener PID `26500`/`26740`; route health checks all 200.
- Fresh four-viewport Browser metrics: requested 1440×1024/client=scroll=1425, 1024×900/client=scroll=1009, 910×900/client=scroll=895, and 390×844/client=scroll=375; every `scrollX=0`. Every Hero had zero `a[href^="/scenarios/"]`, displayed only `基于已审核内容`, and produced zero console warnings/errors.
- Fresh post-Fix1 PNGs: desktop `1425×839`, SHA-256 `bd91e2aa6e66a6dd980d589cc24710cbed9e64f7d2d732ed30bb578d11cf1198`; 1024 `1009×836`, `bc28677ac9fb33340a21b5a719b77868ee79f0f59138da9ed707dd7774a69c5b`; 910 `895×834`, `90a1d6795d0b16ce4d3fa573f586de7fc27e4c133dfcdeded59de247ec501384`; mobile `375×811`, `9b7b0c15aaed6703a61f425f5e2c3c4b93c4d0d75d607e21482a439b13402616`.
- Same-input comparison: reference + fresh 1440 and, separately, fresh 1024/910/390 showed the single-action Hero, correct dark/white/single-blue system, right-weighted artwork, readable title/audit note, unobstructed chapter rail, mobile stacking, and no new P0–P2.
- Cleanup: controller reset/closed the in-app Browser; exact launcher/listener PIDs `26500`/`26740` stopped; `remaining_count=0`, `listener_count=0`, `port_open=False` for `127.0.0.1:60052`.
- Refreshed evidence commit: `5816654d5a499ac577a02e2bdc644113e6a912cb` (`docs: refresh dark homepage review evidence`), exactly `design-qa.md`, the testing record, and four required PNGs.

## Full-plan review Fix round 2/5 — true-PNG full-page evidence

- Review base/HEAD: `5816654d5a499ac577a02e2bdc644113e6a912cb`; evidence-only scope, with no product code or test changes.
- Reviewer reproduction: all four `.png` paths began `ffd8ffe000104a464946`, Pillow reported `format=JPEG`, and heights 839/836/834/811 covered only the Hero. The ledger tail also duplicated old Task 4 process lines and ended on the obsolete scoped-review gate.
- Fresh fixture: `.superpowers/sdd/2026-08-28-dark-evidence-homepage/test-tmp/task4-browser-fix2-20260831-001`, `127.0.0.1:52537`, launcher/listener PIDs `7356`/`4572`; `/`, `/assessment`, `/scenarios`, and `/scenarios/mfg-knowledge-assistant` returned 200.
- Browser capture: exact 1440×1024, 1024×900, 910×900, and 390×844 request states. The one-shot full-page compositor duplicated sticky segments and was rejected. Accepted real viewport captures were taken at Hero, assessment, matching, roadmap, applications, proof/case, news, final CTA, and footer.
- Evidence assembly: desktop/1024/910 use seven viewport segments; mobile uses nine. Pillow performed only 1:1 decoding, a 12px `#0b0f15` separator, and PNG encoding—no crop, scale, or generated pixels within a capture.
- Final PNG evidence: desktop `1425×5945`, 2,508,137 bytes, SHA-256 `d60a86aae617b331768d5a7e436ac76c0e6c258f6c29a1d324078802bf584245`; 1024 `1009×5924`, 2,084,669 bytes, `8b2087e8255a60d6878e8b5b512a32f817396ccfcadfd24069fef4802aa42531`; 910 `895×5910`, 1,962,411 bytes, `9dd263e8ca20e4d90f9cd126338201c7e51de0b35206979689fc298378d2e959`; mobile `375×7395`, 1,111,292 bytes, `982aa40ad9f93320ecfa84f73f63b2486997dea63885bd7b7af58cbf0693c5f3`.
- Format validation: all four start with PNG signature `89504e470d0a1a0a`; Pillow reports `format=PNG`; all sheets were inspected from Hero to final CTA/footer.
- Ledger: duplicate tail records were consolidated with `apply_patch`; preserved history now ends in one full-plan re-review/fix2 gate.
- Required same-input comparison: selected reference + desktop evidence sheet, then 1024 + 910 + mobile sheets. All four expose Hero, positioning/three capabilities, applications, proof/case, news, final CTA, and footer; no horizontal overflow, overlap, bad crop, broken asset, or new P0—P2 was found. Segment overlap remains visibly and explicitly an anchor-by-anchor evidence sheet rather than a seamless page claim.
- Cleanup: controller reset/closed the in-app Browser; exact PIDs `7356`/`4572` stopped; `remaining_count=0`, `listener_count=0`, `port_open=False` on `127.0.0.1:52537`; all 37 `fix2-*.raw` captures and the temporary assembly helper were removed after validation.
