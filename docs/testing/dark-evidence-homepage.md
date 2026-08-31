# Dark evidence homepage — Task 4 verification record

Date: 2026-08-31
Frozen implementation base: `12ec7056a2cc1a952f5bec5ee7727ae2447fb318`

## QA correction commits

| Commit | Exact scope | Reason |
|---|---|---|
| `a698f07` | `templates/index.html` | Restore published industry/scenario links to the guided chapter URL matrix. |
| `620bc4a` | `static/css/dark-evidence-home.css`, `tests/test_ui_foundations.py` | Close 1024/910 rail/title and 390 chapter-strip responsive gaps. |
| `ce026ae` | `static/js/guided_story.js`, `tests/js/guided_story_runtime.test.js` | Activate the tall chapter 05 at a reachable observer threshold. |
| `580a8ef` | `static/css/dark-evidence-home.css`, `tests/test_ui_foundations.py` | Remove reachable document overflow at 320px. |
| `e0e3619` | `templates/index.html`, `tests/test_content_navigation.py` | Keep the Hero free of catalog entry links and bind the published scenario entry to matching. |

All commits were made with explicit pathspecs. Pre-existing Task 12 dirty paths were preserved and excluded.

## Automated verification

All Python runs used the assigned interpreter, command-scoped offline dependencies, a unique Task 4 basetemp, and `-p no:cacheprovider`:

```powershell
$env:PYTHONPATH=(Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py='D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'

& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp .superpowers/sdd/2026-08-28-dark-evidence-homepage/test-tmp/task4-fix1-final-scoped-021
```

Fix round 1 result: `395 passed in 206.26s`, exit `0`. Its preceding exact RED updated the URL matrix first and failed because `story-purpose` still contained the fixture scenario href: `1 failed in 1.83s`, exit `1`. The minimal Hero correction then produced `1 passed in 1.50s`, exit `0`, before this responsibility run.

Responsive TDD evidence:

- `task4-responsive-red-009`: `1 failed in 1.22s`, exit `1`; GREEN 010: `1 passed in 0.86s`, exit `0`.
- `task4-compact-title-red-011`: `1 failed in 0.94s`, exit `1`; GREEN 012: `1 passed in 0.87s`, exit `0`.
- `task4-mobile-scrollbar-red-013`: `1 failed in 1.07s`, exit `1`; GREEN 014: `1 passed in 0.76s`, exit `0`.
- Responsibility run 015: `39 passed in 22.55s`, exit `0`.
- `task4-320-overflow-red-016`: `1 failed in 1.04s`, exit `1`; GREEN 017: `1 passed in 0.73s`, exit `0`.
- Responsibility run 018: `39 passed in 22.46s`, exit `0`.

JavaScript commands:

```powershell
node --check static/js/app.js
node --check static/js/guided_story.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/analytics_runtime.test.js
```

- Initial guided-link responsibility result: `21 passed`, exit `0`.
- Responsive responsibility result: `18 passed`, exit `0`.
- Chapter-05 RED: `14 passed, 1 failed`, exit `1`.
- Chapter-05 GREEN responsibility result: `22 passed`, exit `0`; both syntax checks exit `0`.

No full suite was run. The run did not access the network or install/update dependencies.

Fix round 2 changed evidence and control documents only, so it did not rerun product tests or alter the verified implementation.

## Disposable fixture

- Root: `.superpowers/sdd/2026-08-28-dark-evidence-homepage/test-tmp/task4-browser-fix2-20260831-001`
- Database/media: `platform.db` and an isolated media directory under that root.
- Manifest: the root's `manifest.json`; 12 published scenarios, 6 services, 4 industries, one verified case, one reviewed resource, and explicitly deterministic demonstration data.
- Address: `127.0.0.1:52537` only.
- Launcher/listener PIDs: 7356/4572.
- Interpreter: Python 3.12.13; Flask 3.1.3; Werkzeug 3.1.8; beautifulsoup4 4.15.0; Pillow 12.3.0; pypdf 6.16.2.
- Route probes before QA: `/` 200 (14244 bytes), `/assessment` 200 (8158), `/scenarios` 200 (13901), `/scenarios/mfg-knowledge-assistant` 200 (8866).

## Exact-viewport full-page evidence sheets

The in-app Browser used the exact requested emulation states. Its one-shot full-page compositor visibly duplicated sticky sections, so that raw output was rejected. The accepted evidence is built only from real viewport screenshots at named anchors: Hero, assessment, matching, roadmap, applications, proof/case, news, final CTA, and footer. Desktop/1024/910 use seven captures because their final capture contains news, CTA, and footer together; mobile uses all nine captures.

The Browser API returns JPEG screenshot bytes and has no format option. Offline Pillow therefore decoded every accepted segment and encoded a true PNG evidence sheet, preserving every pixel at 1:1 with no crop or scale. Adjacent captures are separated only by 12px of `#0b0f15`. Every final file starts `89504e470d0a1a0a`, and Pillow independently reports `format=PNG`.

| Requested viewport | Segments | PNG pixels | Bytes | SHA-256 |
|---|---:|---:|---:|---|
| 1440×1024 | 7 | 1425×5945 | 2,508,137 | `d60a86aae617b331768d5a7e436ac76c0e6c258f6c29a1d324078802bf584245` |
| 1024×900 | 7 | 1009×5924 | 2,084,669 | `8b2087e8255a60d6878e8b5b512a32f817396ccfcadfd24069fef4802aa42531` |
| 910×900 | 7 | 895×5910 | 1,962,411 | `9dd263e8ca20e4d90f9cd126338201c7e51de0b35206979689fc298378d2e959` |
| 390×844 | 9 | 375×7395 | 1,111,292 | `982aa40ad9f93320ecfa84f73f63b2486997dea63885bd7b7af58cbf0693c5f3` |

A 320×844 boundary pass additionally reported `innerWidth=320`, `clientWidth=305`, `scrollWidth=305`, and `scrollX=0` after an attempted horizontal scroll.

## Visual comparison result

The selected option-1 reference and the fresh 1440 full-page evidence sheet were opened together in one comparison input. The fresh 1024, 910, and mobile sheets were opened together in a second input. All four were also read end-to-end in the image viewer. No P0–P2 remained: the Hero has its required single assessment action and non-interactive audit note; capability chapters, applications, proof/case, news, final CTA, and footer are all visible; typography, chapter rhythm, art crop, and boundary discipline form a consistent black/white/electric-blue system across all regimes. The approved local artwork is darker than the generated reference; omission of a duplicate nav CTA follows the binding interaction spec and remains an accepted P3 distinction.

## Browser interaction matrix

| Check | Result |
|---|---|
| Five chapter links | PASS; exact hashes/active chapters, including chapter 05 `story-evidence`. |
| Fast down/reverse scroll | PASS; active chapter followed scroll direction without a wheel interceptor. |
| Hero/final assessment CTA | PASS; both reached `/assessment`. |
| Fixture content links | PASS; scenario, service, verified case, and reviewed resource routes loaded. |
| Mobile menu | PASS; open, Escape close with focus restoration, and AI-scene navigation. |
| Footer/final CTA at four requested viewports | PASS; visible, unoverlapped, no page overflow. |
| Console | PASS; zero errors and zero warnings. |
| Native Tab traversal | NOT PROVEN; the in-app key surface did not expose an observable focus advance. |
| Native reduced-motion emulation | NOT PROVEN; unsupported by this Browser surface. Node runtime coverage proves the static/no-observer branch. |
| Native 200% zoom | NOT PROVEN; repeated zoom keys did not alter observable geometry. A 720px half-width proxy passed but is not represented as native proof. |

This is a responsive and interaction QA record, not a full WCAG conformance audit.

## Cleanup

The Browser viewport was reset and the disposable tab closed. Only exact fresh-fixture PIDs 4572 and 7356 were stopped. Final cleanup checks for `127.0.0.1:52537` reported:

```text
remaining_count=0
listener_count=0
port_open=False
```

No production host, public listener, Nginx, systemd, or real database was touched.
