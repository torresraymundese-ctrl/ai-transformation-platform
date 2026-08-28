# Dark Evidence Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the public homepage to faithfully implement the user-selected first visual concept while preserving published-only content, native scrolling, accessibility, and all local-only safety boundaries.

**Architecture:** Keep the Flask/Jinja route and `content_repository.home_page_data()` unchanged. Add one homepage-only stylesheet and three optimized local visual assets, then replace the homepage presentation with five semantic chapters that map the selected long-page composition onto the existing progressive scroll controller. Scope navigation and sticky-CTA changes through a homepage body class so catalog, assessment, admin, and report pages do not change.

**Tech Stack:** Flask, Jinja2, semantic HTML, local CSS, dependency-free JavaScript, Pillow already present in the assigned environment, pytest, BeautifulSoup, Node `node:test`, and the Codex in-app Browser.

**Spec:** `docs/superpowers/specs/2026-08-28-dark-evidence-homepage-design.md`

## Global Constraints

- Work only in `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report` on `codex/ai-platform-2.0-core`; it is already a linked worktree, so do not create another.
- Preserve exactly these unrelated dirty paths: `README.md`, `blueprints/admin/catalog.py`, `catalog_content_repository.py`, `docs/deployment/security-and-service.md`, `templates/admin/catalog_edit.html`, `tests/test_catalog_content_admin.py`, `docs/testing/content-catalog.md`, the five existing `docs/testing/evidence/content-*.png` files, and `tests/test_content_journey.py`.
- Never modify or stage `catalog_content_repository.py`.
- Use existing public routes and `content_repository.home_page_data()` only. Do not change repositories, database schema, publishing, assessment, analytics, security, canonical, or external-source behavior.
- Runtime dependencies remain local. Do not install packages, load remote fonts/scripts/images, run application requests against the real external network, or use a public listener.
- Local preview binds only `127.0.0.1`. Do not deploy or touch production server, Nginx, systemd, production database, or real customer data.
- The selected reference is `C:/Users/zz/.codex/generated_images/01a03349-721a-7df2-b234-cd675d8d96d1/exec-adcdb983-d7e6-468e-ae5c-a847303e8c60.png`; do not copy it as a full-page bitmap and do not copy Scale branding or assets.
- Every production change follows RED→GREEN. Each pytest command uses `-p no:cacheprovider` and a unique `--basetemp` below this plan's ignored SDD workspace.
- Do not run the full pytest suite. The allowed final Python responsibility set is `tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_content_navigation.py tests/test_smoke.py` plus the homepage-relevant security/validation tests named in Task 4.

---

### Task 1: Establish the selected visual tokens and optimized asset contract

**Files:**
- Create: `static/css/dark-evidence-home.css`
- Create: `static/images/ui/home-ai-core.webp`
- Create: `static/images/ui/home-knowledge-system.webp`
- Create: `static/images/ui/home-path-system.webp`
- Modify: `templates/index.html`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: the exact selected reference, three inspected source PNGs named in the spec, existing `design-tokens.css`, and the current `index.html` stylesheet block.
- Produces: body class `home-dark-evidence`, stylesheet `/static/css/dark-evidence-home.css`, and three fixed local decorative image URLs with explicit size/byte contracts for Task 2.

- [ ] **Step 1: Add the failing homepage visual-asset contract**

Add a behavior-level BeautifulSoup/Pillow test that requests `/` and asserts:

```python
assert page.body.get("class") and "home-dark-evidence" in page.body["class"]
assert page.select_one('link[href="/static/css/dark-evidence-home.css"]') is not None
expected = {
    "/static/images/ui/home-ai-core.webp": (1920, 1080, 350_000),
    "/static/images/ui/home-knowledge-system.webp": (1600, 900, 300_000),
    "/static/images/ui/home-path-system.webp": (1600, 900, 300_000),
}
```

For each expected URL require exactly one `img[data-home-art]`, empty alt text, explicit matching `width`/`height`, local path existence, WEBP format, a single decodable frame, and byte size within the listed bound. Require the hero image to use `fetchpriority="high"` and not `loading="lazy"`; require the two supporting images to use `loading="lazy"` and `decoding="async"`.

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-28-dark-evidence-homepage\test-tmp'
& $py -m pytest tests/test_ui_foundations.py::test_home_dark_evidence_assets_are_local_decodable_and_bounded -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-red-001')
```

Expected: FAIL because the body class, stylesheet link, image elements, and files do not exist.

- [ ] **Step 3: Create the minimal tokens and assets**

Create `dark-evidence-home.css` with a `.home-dark-evidence` scope and these exact custom properties:

```css
.home-dark-evidence {
  --home-graphite-1000: #07090d;
  --home-graphite-950: #0d1117;
  --home-graphite-900: #12171f;
  --home-paper: #f3f1eb;
  --home-white: #ffffff;
  --home-copy: #d7dde5;
  --home-muted: #8e99a8;
  --home-line: #2b323c;
  --home-signal: #0f6fef;
  --home-container: 80rem;
  --home-section-space: clamp(7.5rem, 11vw, 11.25rem);
}
```

Convert the three approved source images offline with Pillow. Normalize to sRGB, resize/crop to the exact dimensions in Step 1 with `Image.Resampling.LANCZOS`, strip metadata, and save WebP at the highest quality that stays under the byte limit; do not distort aspect ratio. Insert the three image elements into their final semantic slots in `index.html`, add `{% block body_class %}home-dark-evidence{% endblock %}`, and replace the old guided-story stylesheet link with the new stylesheet link.

- [ ] **Step 4: Run GREEN and inspect all bitmaps**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_home_dark_evidence_assets_are_local_decodable_and_bounded -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-green-002')
node --check static/js/guided_story.js
git diff --check -- templates/index.html static/css/dark-evidence-home.css tests/test_ui_foundations.py
```

Open all three WebPs with the local image viewer and confirm the focal object is not cropped incorrectly and no embedded UI text is being treated as page copy.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- static/css/dark-evidence-home.css static/images/ui/home-ai-core.webp static/images/ui/home-knowledge-system.webp static/images/ui/home-path-system.webp templates/index.html tests/test_ui_foundations.py
git commit -m "feat: establish the dark evidence homepage assets"
```

---

### Task 2: Rebuild the desktop homepage composition from the selected reference

**Files:**
- Modify: `templates/index.html`
- Modify: `static/css/dark-evidence-home.css`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: Task 1 body class, stylesheet, three `data-home-art` images, current five story IDs, `content_repository.home_page_data()`, and existing route helpers.
- Produces: the complete 1440px dark homepage composition, one hero CTA, three numbered capability chapters, one application feature, evidence metrics with adjacent labels, dynamic case/resource/announcement content, editorial news rows, and final CTA.

- [ ] **Step 1: Write failing semantic and truthfulness tests**

Add or amend HTTP tests so the home response requires:

```python
assert [section["id"] for section in story.select("[data-story-chapter]")] == [
    "story-purpose", "story-assessment", "story-matching",
    "story-roadmap", "story-evidence",
]
hero = story.select_one("#story-purpose")
assert hero.select_one("h1").get_text(" ", strip=True) == "让 AI 转型，从可验证的业务价值开始"
assert [link.get_text(" ", strip=True) for link in hero.select(".home-hero-actions a")] == ["开始 AI 就绪度评估"]
assert hero.select_one('a[href="/assessment"]') is not None
assert story.select_one('[data-capability="assessment"]') is not None
assert story.select_one('[data-capability="matching"]') is not None
assert story.select_one('[data-capability="delivery"]') is not None
assert story.select_one('[data-home-section="applications"]') is not None
assert story.select_one('[data-home-section="proof"]') is not None
assert story.select_one('[data-home-section="news"]') is not None
assert story.select_one('[data-home-section="final-cta"]') is not None
```

Require every `[data-demo-value]` to contain or be immediately paired with `[data-demo-label]` whose text is `演示数据`; require no video, no customer-logo wall, no inline `style`, and no external image URL. Preserve assertions that published scenario/service/case/resource/announcement links appear when fixture data provides them.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters tests/test_public_catalog.py::test_home_labels_every_simulated_result_as_demo_data tests/test_ui_foundations.py::test_home_preserves_real_content_sections_and_single_primary_action -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-red-003')
```

Expected: FAIL because the current copy, hero action count, section hooks, and composition do not match the selected reference.

- [ ] **Step 3: Implement the semantic desktop composition**

Rewrite only `templates/index.html` presentation. Keep all five existing chapter IDs and `data-story-*` hooks. Use this exact visible hierarchy:

- Hero label `企业 AI 转型平台`, H1 and supporting line from the spec, and one `/assessment` CTA.
- Positioning band `从判断起点，到形成落地路径`.
- Capability labels `01 / 评估企业准备度`, `02 / 匹配高价值场景`, `03 / 设计可执行交付`.
- Applications heading `把 AI 放进真实业务现场` and real links to published scenarios/industries.
- Proof heading `从路径到成果，持续验证价值`; deterministic values may be `12 周`, `3 个优先场景`, `阶段路径` only when each item displays `演示数据`.
- News heading `洞察与动态`; render current announcements first and audited resources second. Use only fields present on their public view models (`valid_from` for announcements, `original_published_at` for resources); show an honest empty state if both collections are empty.
- Final CTA heading `确认你的 AI 转型起点`, one `/assessment` link `开始评估`.

In `dark-evidence-home.css`, reproduce the selected reference with one black navigation bar, a right-weighted hero image and left text column, 1280px container, 12-column capability rows, full-width application image, large proof numerals, rule-separated news rows, and a dark final CTA. Do not use traditional card matrices, large rounded panels, bright gradients, or repeated pill controls.

- [ ] **Step 4: Run GREEN and the focused integration set**

```powershell
& $py -m pytest tests/test_public_catalog.py::test_home_uses_guided_story_with_published_scenario_and_service tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters tests/test_public_catalog.py::test_home_labels_every_simulated_result_as_demo_data tests/test_ui_foundations.py::test_home_preserves_real_content_sections_and_single_primary_action tests/test_ui_foundations.py::test_static_public_pages_use_named_main_and_no_inline_layout -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-green-004')
git diff --check -- templates/index.html static/css/dark-evidence-home.css tests/test_public_catalog.py tests/test_ui_foundations.py
```

Expected: all selected tests PASS, with no warning introduced by changed project files.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- templates/index.html static/css/dark-evidence-home.css tests/test_public_catalog.py tests/test_ui_foundations.py
git commit -m "feat: rebuild the dark evidence homepage"
```

---

### Task 3: Harden responsive layout, motion, navigation, and progressive enhancement

**Files:**
- Modify: `templates/components/navigation.html`
- Modify: `static/css/dark-evidence-home.css`
- Modify: `static/js/guided_story.js`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/js/guided_story_runtime.test.js`
- Modify: `tests/js/app_runtime.test.js` only if the homepage sticky CTA behavior requires a tested app-level change

**Interfaces:**
- Consumes: Task 2 semantic hooks and current `activateStoryChapter` / `initializeGuidedStory` APIs.
- Produces: homepage-scoped dark navigation, no duplicate sticky conversion surface, 1440/1024/910/390/320 layouts, active-chapter fade/shift, image hover zoom, reduced-motion static rendering, and unchanged native scroll behavior.

- [ ] **Step 1: Add failing behavior tests**

Add tests that require the homepage navigation to expose a home-scoped class without changing route targets, and runtime tests that prove active state can move forward and backward while no `wheel` listener is installed. Add a homepage HTML contract for a single visible primary conversion surface before the final CTA; do not assert CSS source text when a DOM or runtime behavior assertion is available.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_home_navigation_and_conversion_surfaces_follow_dark_evidence_contract -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-red-005')
node --test tests/js/guided_story_runtime.test.js tests/js/app_runtime.test.js
```

Expected: the new homepage navigation/conversion assertion FAILS before implementation; existing runtime tests remain a known baseline.

- [ ] **Step 3: Implement scoped responsive and motion behavior**

Use `request.path == '/'` only to add a navigation modifier class or semantic marker; do not remove links on other pages. Hide `.site-signal` and the duplicate sticky CTA only under `.home-dark-evidence`. Keep `guided_story.js` dependency-free and based on `IntersectionObserver`; if a new class/state is needed, expose it through `data-story-mode` or `data-story-active` and test the observable state. Never register `wheel`, block native keys, or call `preventDefault()` for page navigation.

CSS must include three deliberate regimes:

- `>= 1100px`: two-column hero/capability rows and fixed right progress rail outside the 1280px content area.
- `768px—1099px`: reduced title scale, narrower imagery, and a compact progress rail that cannot overlap content at 910px.
- `< 768px`: single-column flow, non-sticky product surfaces, non-fixed horizontal progress navigation, 44px targets, and no page-level overflow at 320px.

Under `prefers-reduced-motion: reduce`, remove transitions, sticky behavior, and snap behavior while preserving every section.

- [ ] **Step 4: Run GREEN**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-green-006')
node --check static/js/app.js
node --check static/js/guided_story.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js
git diff --check -- templates/components/navigation.html static/css/dark-evidence-home.css static/js/guided_story.js tests/test_ui_foundations.py tests/js/guided_story_runtime.test.js tests/js/app_runtime.test.js
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- templates/components/navigation.html static/css/dark-evidence-home.css static/js/guided_story.js tests/test_ui_foundations.py tests/js/guided_story_runtime.test.js tests/js/app_runtime.test.js
git commit -m "feat: harden the dark evidence homepage experience"
```

---

### Task 4: Run blocking same-viewport design QA and prepare the review gate

**Files:**
- Modify: `design-qa.md`
- Create: `docs/testing/dark-evidence-homepage.md`
- Create: `docs/design/evidence/2026-08-28-dark-evidence-home-desktop.png`
- Create: `docs/design/evidence/2026-08-28-dark-evidence-home-1024.png`
- Create: `docs/design/evidence/2026-08-28-dark-evidence-home-910.png`
- Create: `docs/design/evidence/2026-08-28-dark-evidence-home-mobile.png`
- Modify: `.superpowers/sdd/2026-08-28-dark-evidence-homepage/progress.md` (ignored control file)

**Interfaces:**
- Consumes: independently reviewed Tasks 1—3, the exact selected reference, deterministic local fixture, and Codex in-app Browser.
- Produces: scoped automated evidence, exact-viewport screenshots, reference-versus-implementation visual comparison, interaction results, a `design-qa.md` ending in `final result: passed` or `final result: blocked`, and a review-ready evidence commit.

- [ ] **Step 1: Freeze the implementation and run scoped automation**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-28-dark-evidence-homepage\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-final-scoped-007')
node --check static/js/app.js
node --check static/js/guided_story.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/analytics_runtime.test.js
```

Do not run the full suite.

- [ ] **Step 2: Start a deterministic disposable local fixture**

Create a fresh SQLite database and media directory below this plan's ignored SDD workspace, seed only deterministic published content, and bind to a free `127.0.0.1` port. Record the database path, media path, launcher PID, listener PID, command, port, Python version, `PYTHONPATH`, and dependency versions. Confirm `/`, `/assessment`, `/scenarios`, and one scenario detail return HTTP 200 before capture.

- [ ] **Step 3: Capture exact viewports with the Codex in-app Browser**

Capture the homepage at 1440×1024, 1024×900, 910×900, and 390×844. At each viewport record `scrollWidth`, `clientWidth`, first-screen layout, final CTA arrival, navigation state, image crop, and console errors. Reject page-level horizontal overflow, overlap, hidden CTA, unreadable copy, or progress navigation covering content.

- [ ] **Step 4: Run the blocking visual comparison**

Open the selected reference and the 1440px implementation screenshot together in one comparison input. Open the 1024/910/mobile captures together in a second input. Inspect typography, hero proportions, right-side artwork, graphite balance, single blue accent, 1280px alignment, section spacing, border/radius discipline, content density, crop quality, mobile stacking, and footer arrival.

Record each difference in root `design-qa.md` with P0—P3 severity and an exact screen/state. Fix every P0/P1/P2 through a fresh RED→GREEN cycle and recapture the affected viewport. Do not hand off while any P0—P2 remains. The final line must be exactly `final result: passed`; if capture or comparison is impossible, use `final result: blocked`.

- [ ] **Step 5: Verify interactions and cleanup**

Use the in-app Browser to exercise all five chapter links, assessment CTA, scenario/service/case/resource links that fixture data exposes, mobile menu, reverse scrolling, fast scrolling, footer arrival, reduced-motion rendering, and 200% text zoom. Record native keyboard/scrollbar operations as `PASS`, `FAIL`, or `NOT PROVEN` without substituting scripted events for native evidence. Stop the exact local listener and confirm its port is closed.

- [ ] **Step 6: Document, verify, and commit evidence**

Write `docs/testing/dark-evidence-homepage.md` with commands, exact summaries, exits, environment, screenshot dimensions/SHA-256, asset sizes, interaction results, limitations, and cleanup. Then run:

```powershell
git diff --check
git status --short
git add -- design-qa.md docs/testing/dark-evidence-homepage.md docs/design/evidence/2026-08-28-dark-evidence-home-desktop.png docs/design/evidence/2026-08-28-dark-evidence-home-1024.png docs/design/evidence/2026-08-28-dark-evidence-home-910.png docs/design/evidence/2026-08-28-dark-evidence-home-mobile.png
git commit -m "docs: verify the dark evidence homepage"
```

- [ ] **Step 7: Request final independent review and stop at the visual-acceptance gate**

Generate one full-plan review package from this plan's base through Task 4 HEAD. Dispatch a fresh reviewer with the spec, plan, ledger, reports, package, and global constraints. Fix only scoped P0—P2 findings through the SDD loop. After reviewer CLEAN and controller-focused verification, stop for user visual acceptance. Do not start deployment or another UI family.

## Plan Completion Gate

This plan is complete only when Tasks 1—4 have task-scoped independent reviews, the final whole-plan reviewer is CLEAN, the scoped Python/Node responsibility sets are fresh, `design-qa.md` says `final result: passed`, all four screenshots were inspected against the selected reference, and no P0—P2 remains. Completion means only that the homepage is locally ready for user visual acceptance; it does not authorize production deployment or claim the entire platform is finished.

