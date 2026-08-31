# SDD ledger — plan: docs/superpowers/plans/2026-08-28-dark-evidence-homepage.md

## Setup

- Spec: `docs/superpowers/specs/2026-08-28-dark-evidence-homepage-design.md` (user selected displayed option 1 on 2026-08-28).
- Plan commit: `dcb075d` (`docs: plan the dark evidence homepage`).
- Start branch: `codex/ai-platform-2.0-core`.
- Start HEAD/base: `dcb075d`.
- Workspace: existing linked worktree `D:/Codex干活/企业AI转型平台2.0升级/V0.2-server-snapshot-20260819/.worktrees/core-assessment-report`; `git-dir` differs from `git-common-dir`, and no superproject path was reported.
- Preserved unrelated Task 12 paths: `README.md`, `blueprints/admin/catalog.py`, `catalog_content_repository.py`, `docs/deployment/security-and-service.md`, `templates/admin/catalog_edit.html`, `tests/test_catalog_content_admin.py`, `docs/testing/content-catalog.md`, five `docs/testing/evidence/content-*.png`, and `tests/test_content_journey.py`.
- Environment ruling: reuse the assigned interpreter and command-scoped offline `local-deps`; do not install or update dependencies — cost if wrong: a missing dependency blocks a focused task and must be surfaced rather than repaired through network access.
- Worktree ruling: reuse the explicitly assigned linked worktree and do not create another — cost if wrong: a second worktree would omit preserved dirty state and split the review range.
- Visual-target ruling: the first displayed generated image is the binding target; implement it as semantic HTML/CSS with separate local assets, never as a single full-page bitmap — cost if wrong: small image-generation artifacts may require human visual adjustment, but accessibility and responsive behavior remain intact.
- Scope ruling: this follow-up plan changes only the homepage; current scenario catalog/detail remain frozen — cost if wrong: visual alignment between homepage and catalog may need a later explicitly authorized iteration.

## Baseline

- Fresh scoped baseline used command-scoped offline `local-deps`, assigned Python, unique basetemp `baseline-001`, and `-p no:cacheprovider`.
- `tests/test_ui_foundations.py tests/test_public_catalog.py`: `312 passed in 209.82s`, exit 0.
- `node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js`: `18 passed`, exit 0.
- No full suite, network, dependency install, production access, or deployment.

## Pre-flight task/interface scan

| Scope | Produces / consumes | Finding | Ruling |
|---|---|---|---|
| Task 1 self | Homepage body class, stylesheet, three bounded WebPs | Test contract, file names, dimensions, load priority, and source PNGs agree | Proceed as written |
| Task 2 self | Five semantic chapters and published-only content | Selected copy and one hero CTA override the older two-CTA homepage text; new spec explicitly resolves this | Proceed under the new spec |
| Task 3 self | Scoped navigation, responsive layout, progressive enhancement | Uses existing `data-story-*` APIs and forbids wheel interception; no new route or repository dependency | Proceed as written |
| Task 4 self | Scoped automation, in-app Browser captures, visual comparison, evidence | Exact viewports, failure gate, cleanup, and no-full-suite rules agree | Proceed as written |
| Task 1 → Task 2 | Assets/tokens consumed by semantic composition | URLs, dimensions, body class, and stylesheet name match | Clean |
| Task 1 → Task 3 | Homepage scope and tokens consumed by responsive/nav CSS | `.home-dark-evidence` is the shared scope; other pages remain outside it | Clean |
| Task 1 → Task 4 | Image sizes/crops consumed by Browser QA | Task 4 verifies the same exact files and viewports | Clean |
| Task 2 → Task 3 | DOM hooks consumed by active-state and responsive behavior | Existing five IDs and `data-story-*` names remain unchanged | Clean |
| Task 2 → Task 4 | Selected composition consumed by same-viewport QA | Task 4 compares the exact selected reference, not the earlier Scale screenshot alone | Clean |
| Task 3 → Task 4 | Final motion/responsive state consumed by Browser interactions | Task 4 covers 1440/1024/910/390 plus native-scroll limitations | Clean |
| Global dirty boundary | Homepage work could accidentally include Task 12 files | All commits use explicit pathspecs; `catalog_content_repository.py` is forbidden | Ruling recorded above |
| Global deployment gate | Task 4 starts a disposable local fixture | Bind `127.0.0.1`, stop exact listener, never deploy or expose publicly | Clean |

## Execution

- Next task: Task 1 — Establish the selected visual tokens and optimized asset contract.
- Task 1 BASE: `dcb075d8c383c26497ab8018077a105a5ce8ed77`.
- Task 1: complete (commits `dcb075d..25c04a4`, independent task review spec ✅ and quality Approved).
- Task 1 verification: real RED `1 failed in 1.67s`; implementer GREEN `1 passed in 1.41s`; controller fresh GREEN `1 passed in 1.44s`; Node syntax and range diff check exit 0.
- Task 1 asset verification: reviewer and controller visually inspected all three WebPs; exact sizes/bytes are `1920×1080/182094`, `1600×900/197062`, `1600×900/133698`. Controller provenance comparison against the three approved source PNGs produced mean absolute pixel differences `0.8022`, `0.8926`, `0.7991`, resolving the reviewer's provenance ⚠️ as the expected lossy WebP conversion.
- Next task: Task 2 — Rebuild the desktop homepage composition from the selected reference.
- Task 2 BASE: `25c04a4c8a76fce7fad9240669d3612ab20a9d3c`.
- Task 2 implementation: `bf1188345a7f9fbe24a1909b5daadfba568b8b33`; independent review required Fix round 1 for the single-accent boundary, Task 2/3 scope separation, and stronger rendered-content contracts.
- Task 2 Fix round 1/5: `49ab5cec0400e8cdee62f04da6e0dc8951a18a14`; scoped re-review `CLEAN`, all six findings `ADDRESSED`, no new P0—P2.
- Task 2 controller verification: 12 focused Python tests passed in 11.81s; Node syntax passed; guided-story/app runtime 18 passed; Task 2 range diff check exit 0. No full suite, network, dependency install, production access, or deployment.
- Task 2: complete (commits `25c04a4..49ab5ce`, fresh independent scoped review `CLEAN`).
- Next task: Task 3 — Harden responsive layout, motion, navigation, and progressive enhancement.
- Task 3 BASE: `49ab5cec0400e8cdee62f04da6e0dc8951a18a14`.
- Task 3 implementation: `e3319853c5d70e9c232993774bb4c687301cca12`; independent review required Fix round 1 for the duplicate root navigation conversion button and inherited non-brand focus ring.
- Task 3 Fix round 1/5: `12ec7056a2cc1a952f5bec5ee7727ae2447fb318`; scoped re-review `CLEAN`, both P2 findings `ADDRESSED`, no new P0—P2.
- Task 3 controller verification: 40 focused Python tests passed in 23.44s; Python/Node syntax passed; guided-story/app runtime 18 passed; Task 3 range diff check exit 0. No full suite, network, dependency install, production access, Browser evidence, or deployment.
- Task 3: complete (commits `49ab5ce..12ec705`, fresh independent scoped re-review `CLEAN`).
- Next task: Task 4 — Run blocking same-viewport design QA and prepare the review gate.
- Task 4 BASE: `12ec7056a2cc1a952f5bec5ee7727ae2447fb318`.
- Task 4 QA fixes: `a698f07` (guided links), `620bc4a` (1024/910/390 responsive gaps), `ce026ae` (long evidence-chapter activation), `580a8ef` (320px overflow); first evidence commit `7c9cfc2`.
- Task 4 scoped review required Fix round 1 because `a698f07` had satisfied a stale URL-matrix test by adding a scenario entry to the Hero, conflicting with the binding one-action/later-chapter spec; the same review found a P3 CSS-path typo in the evidence record.
- Task 4 Fix round 1/5: `e0e361969601bb97dc889697d45407cf82f6cec8` moves the scenario URL contract to `story-matching` and removes the Hero catalog entry; `5816654d5a499ac577a02e2bdc644113e6a912cb` refreshes the two reports and four screenshots. Scoped re-review `CLEAN`, P2/P3 `ADDRESSED`, no new P0—P2.
- Task 4 automation: fresh scoped Python `395 passed in 206.26s`; Node `22 passed`; syntax/diff checks exit 0. Controller post-review focus: Python `4 passed in 3.41s`, Node `22 passed`, screenshot hashes matched, `listener_count=0`.
- Task 4 Browser QA: exact 1440×1024, 1024×900, 910×900, 390×844 plus 320px boundary; two required same-input comparisons; zero Hero scenario links; no remaining P0—P2; `design-qa.md` ends `final result: passed`.
- Task 4 limitations remain explicit: native Tab traversal, native reduced-motion emulation, and native 200% zoom are `NOT PROVEN`; no full suite or WCAG conformance claim.
- Task 4 cleanup: fresh fixture `127.0.0.1:60052`, PIDs `26500/26740`, final `remaining_count=0`, `listener_count=0`, `port_open=False`.
- Task 4: complete at task-scoped review gate (range `12ec705..5816654`, independent scoped re-review `CLEAN`).
- Full-plan review Fix round 2/5 base: `5816654d5a499ac577a02e2bdc644113e6a912cb`; reviewer confirmed the four `.png` paths contained viewport-only JFIF/JPEG bytes and could not evidence chapters 02—05 through the footer. The reviewer also required this ledger tail to have one unambiguous gate.
- Fix2 evidence-only result: four true-PNG, 1:1 same-viewport evidence sheets cover Hero through footer at 1425×5945, 1009×5924, 895×5910, and 375×7395. The reference+desktop and 1024+910+mobile comparison inputs showed no new P0—P2; all earlier automated/Browser facts and `NOT PROVEN` limitations remain unchanged.
- Fix2 cleanup: controller reset/closed the in-app Browser; exact PIDs `7356`/`4572` stopped; `127.0.0.1:52537` has `remaining_count=0`, `listener_count=0`, `port_open=False`; all 37 raw captures and the temporary assembly helper were removed after the PNGs were independently validated.
- Next and only gate: after the Fix2 evidence commit, request fresh full-plan re-review of `dcb075d..Fix2 HEAD`; do not deploy or begin wider UI work before review CLEAN and user visual acceptance.
