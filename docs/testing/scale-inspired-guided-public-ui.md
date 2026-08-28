# Scale-inspired guided public UI verification

## 1. Automation

- Exact Task 6 scoped pytest command was run with `PYTHONPATH=.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps`, cache disabled, and unique basetemp `task6-final-scoped-010`. Its live process completed normally; the terminal relay truncated before its terminal pytest summary, so no fabricated test count is recorded.
- `node --check static/js/app.js`: PASS.
- `node --check static/js/guided_story.js`: PASS.
- `node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/analytics_runtime.test.js`: PASS, 21/21.
- P2 fix RED: `tests/test_ui_foundations.py::test_hero_secondary_action_keeps_a_visible_outline_label`: FAIL as expected (missing transparent hero background).
- P2 fix GREEN: the same test: PASS, 1/1.
- Focused post-fix responsibility run: `tests/test_ui_foundations.py`: PASS, 35 passed in 20.07s.

## 2. Fixture and cleanup

- Fresh fixture root: `.superpowers/sdd/2026-08-28-scale-inspired-guided-public-ui/runtime-task6-20260828-132400`.
- SQLite: `platform.sqlite3`; media: `media`; deterministic published industry/scenario read-model seed only; no production database or network endpoint.
- Listener: `127.0.0.1:50991`; final listener PID observed: 23824.
- Health before browser capture: `/` PASS 200; `/scenarios` PASS 200; `/scenarios/mfg-knowledge-assistant` PASS 200.
- The server was stopped at the end of this task and the port was checked closed.

## 3. Captures and image integrity

| File | Viewport | Bytes | SHA-256 |
|---|---:|---:|---|
| guided-home-purpose-desktop.png | 1440×1024 | 100785 | 3106E5C642D0CEC687BFFD49472FF9E698E90D009EC1D9562CC01A8C89BBF8E1 |
| guided-home-assessment-desktop.png | 1440×1024 | 72799 | 3D91549CDCC7811C17C6E453B95FCC288039DC2549E63B3B85DBA44C4E6934A8 |
| guided-home-matching-desktop.png | 1440×1024 | 85384 | FBA13AB7775CAFDA5708F9476234CED17DE6B077B401BB1FB4E1C8495DD291A5 |
| guided-home-roadmap-desktop.png | 1440×1024 | 100809 | 5807163140866778757F8D7E6AC454061952348413B8F50BE36D76F32C7A051F |
| guided-home-evidence-desktop.png | 1440×1024 | 88264 | C1F119DE9BE6FF100D54E4537BC218CC0B441E9234808F36F90C8368E35FA990 |
| guided-home-mobile.png | 390×844 | 51368 | 81A2C641A860BD11800D2949F40A16DAC7807BA01E27813F59356EF4D124C446 |
| guided-scenarios-desktop.png | 1440×1024 | 79826 | 93C1A261AC92B9993F80B6FF5A54DF9921CE8865615A0425DCC361991CD2731D |
| guided-scenario-detail-desktop.png | 1440×1024 | 90292 | C19D19E3B355C8076B15EA1B452286F425E29D9C7EB91145EE0AAE281A4A13CD |

Each image was opened and inspected after saving. Page-width checks: desktop homepage 1425/1425 for all five chapter states; desktop catalog 1425/1425; detail 1425/1425; mobile homepage 375/375. The two decorative WebP assets are 114856 and 68898 bytes, both below the 350 KB asset limit.

## 4. Interaction evidence

| Check | Result | Evidence/limit |
|---|---|---|
| Native scroll, rapid scroll, reverse scroll | PASS | Native browser scroll changed Y 780 → 3680 → 1880 and chapter state updated/reversed. |
| Native scrollbar drag | NOT PROVEN | Two native drag attempts did not move the browser-owned scrollbar in this control surface; not treated as a product failure. |
| Five progress links | PASS | Chapter links 02–05 reached matching active states during capture; 01 returned to `#story-purpose` and active purpose state. |
| Browser find | PASS | Native Ctrl+F/Escape invocation completed against `形成实施路径`; browser-owned find UI is not exposed for semantic inspection. |
| Mobile menu and Escape | PASS | Native summary click opened menu; native Escape closed it. |
| Scenario filters, empty/reset, pagination | NOT PROVEN | The deterministic fixture exposes 12 scenarios but this run ended before complete native form-state coverage. |
| Assessment CTAs and footer arrival | PASS | CTA routes are rendered and footer/sticky CTA were visibly reached in captures. |
| Reduced motion, no JavaScript, 200% zoom | NOT PROVEN | Browser surface lacks this run’s needed emulation/disable controls; server HTML and CSS reduced-motion branch are covered by existing automated contracts, not presented as browser proof. |
| Tab, Shift+Tab, Enter, Space, arrows, Page Down | NOT PROVEN | No scripted focus was used; remaining native keyboard matrix needs a dedicated browser run. |

## 5. Safety and limits

Only the supplied Scale image, local source, local ephemeral fixture, and Codex in-app Browser were used. No deployment, public binding, real database, Nginx, systemd, network request, or full test suite was used. This evidence does not claim WCAG compliance.

## 6. Controller closure round 1

- Fresh exact scoped pytest command: the ten Task 6 test files specified in the brief, `-q -p no:cacheprovider`, basetemp `task6-final-scoped-011`, and durable ignored log `.superpowers/sdd/2026-08-28-scale-inspired-guided-public-ui/task6-final-scoped-011.log`.
- Result: PASS, `556 passed in 285.05s (0:04:45)`; `TASK6_PYTEST_EXIT=0`.
- Dedicated interaction fixture: fresh SQLite/media under `runtime-task6-20260828-134300`, `127.0.0.1:50992`, listener PID 21120. It was stopped and `PORT_50992_CLOSED` was confirmed.
- Required native interaction closure: BLOCKED. The in-app Browser reported its selected session unavailable; browser bootstrap troubleshooting plus a single browser listing returned no available in-app instances. Per the hard constraint no other browser surface was attempted. Consequently native scrollbar-thumb drag and Tab/Shift+Tab/Enter/Space/arrows/PageDown/200% zoom cannot be marked PASS and remain NOT PROVEN.
