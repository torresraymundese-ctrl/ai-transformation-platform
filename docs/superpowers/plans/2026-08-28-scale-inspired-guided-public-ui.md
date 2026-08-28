# Scale-Inspired Guided Public UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally verified, Scale-inspired public experience whose homepage tells the platform story in five scroll-guided chapters and whose scenario catalog/detail pages share the same industrial design language.

**Architecture:** Keep the existing Flask/Jinja server-rendered application and published-only view models. Add a semantic five-chapter homepage, one focused local stylesheet, and dependency-free progressive-enhancement JavaScript; then restyle the scenario catalog/detail without changing repositories, routes, database schema, or publishing rules. Real local fixture UI remains the primary visual material, with at most two decorative generated raster assets added only after their slots are measured.

**Tech Stack:** Flask, Jinja2, semantic HTML, local CSS, dependency-free JavaScript, pytest, BeautifulSoup, Node `node:test`, built-in image generation, and the Codex in-app Browser for local visual QA.

**Spec:** `docs/superpowers/specs/2026-08-28-scale-inspired-guided-ui-design.md`

## Global Constraints

- Work only in the existing linked worktree `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report` on branch `codex/ai-platform-2.0-core`; do not create another worktree.
- Preserve these unrelated Task 12 paths exactly: `README.md`, `blueprints/admin/catalog.py`, `catalog_content_repository.py`, `docs/deployment/security-and-service.md`, `templates/admin/catalog_edit.html`, `tests/test_catalog_content_admin.py`, `docs/testing/content-catalog.md`, `docs/testing/evidence/content-admin-publish.png`, `docs/testing/evidence/content-case-resource.png`, `docs/testing/evidence/content-industry-desktop.png`, `docs/testing/evidence/content-keyboard.png`, `docs/testing/evidence/content-scenario-mobile.png`, and `tests/test_content_journey.py`.
- Do not stage or modify `catalog_content_repository.py`; the scenario list must use the existing `ScenarioCard` fields, while timeline and budget stay on the existing detail view model.
- Use only existing public routes and published-only view models. Do not add database queries to templates, change repositories, change schema, or alter assessment/content/security semantics.
- No production server, Nginx, systemd, real database, public listener, deployment, dependency installation, or application request to the real external network.
- Local preview binds only `127.0.0.1`; visual research references may be inspected separately but must never become runtime dependencies.
- No video, autoplay media, remote font, remote script, remote icon, runtime remote image, WebGL, particle system, or custom wheel interception.
- Never register a `wheel` handler that calls `preventDefault()`. Native scrolling, scrollbar dragging, browser find, Page Down, Space, arrows, and fast trackpad scrolling remain usable.
- Use deterministic local fixture data. Every simulated assessment/result region displays the exact visible label `演示数据`; never invent customer logos, testimonials, ROI, adoption counts, certifications, or security claims.
- Generated imagery is decorative only, uses no logos/text/fake UI/fake facts, is stored locally, and is capped at two final raster assets.
- Python interpreter: `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe`.
- For every pytest command, set `PYTHONPATH` to `.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps`, use a unique absolute `--basetemp` below `.superpowers/sdd/2026-08-28-scale-inspired-guided-public-ui/test-tmp/`, and pass `-p no:cacheprovider`.
- Follow strict RED → verify RED → minimal GREEN → verify GREEN for production behavior. Use exact-path staging and one task commit after focused verification.
- Do not run the full pytest suite. The later complete-product acceptance gate owns the single final full run.
- Every task receives a fresh independent task review. Task 6 also receives a final whole-plan review; open P0—P2 findings enter the bounded SDD fix loop.

---

### Task 1: Build the semantic five-chapter homepage

**Files:**
- Modify: `templates/index.html`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_public_catalog.py`

**Interfaces:**
- Consumes: existing `home_page_data()` keys `industries`, `scenarios`, `services`, `cases`, `resources`, and `announcements`; existing `/assessment`, `/scenarios`, `/service-packages`, `/cases`, and `/resources` routes.
- Produces: one `[data-guided-story]` root, five uniquely identified `[data-story-chapter]` sections, five `[data-story-step]` progress links, per-chapter real product/data surfaces, and stable attributes consumed by Tasks 2 and 3.

- [ ] **Step 1: Add failing HTTP contracts for the story structure**

Add to `tests/test_public_catalog.py`:

```python
def test_home_exposes_five_truthful_guided_story_chapters(published_catalog):
    document = page(published_catalog.get("/"))
    story = document.select_one("[data-guided-story]")
    assert story is not None
    expected = [
        "story-purpose",
        "story-assessment",
        "story-matching",
        "story-roadmap",
        "story-evidence",
    ]
    assert [section["id"] for section in story.select("[data-story-chapter]")] == expected
    assert [link["href"] for link in story.select("[data-story-step]")] == [
        f"#{chapter_id}" for chapter_id in expected
    ]
    assert story.select_one('#story-purpose a[href="/assessment"]') is not None
    assert story.select_one('#story-purpose a[href="/scenarios"]') is not None
    assert story.select_one('#story-evidence a[href="/assessment"]') is not None
    assert story.select("video") == []


def test_home_labels_every_simulated_result_as_demo_data(published_catalog):
    document = page(published_catalog.get("/"))
    assessment = document.select_one("#story-assessment")
    assert assessment is not None
    assert assessment.select_one("[data-demo-label]").get_text(" ", strip=True) == "演示数据"
    assert "行业平均" not in assessment.get_text(" ", strip=True)
```

Replace `test_home_uses_compact_navy_hero_and_composed_published_sections` with a contract that rejects the obsolete `.home-hero--navy` and asserts the first real published scenario and service appear inside their matching chapters. Update `test_home_preserves_real_content_sections_and_single_primary_action` so it asserts one guided-story `h1`, the `/assessment` action, the five chapter markers, and the continuing absence of the invented `27+` claim instead of requiring the removed `.home-hero` class.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-28-scale-inspired-guided-public-ui\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters tests/test_public_catalog.py::test_home_labels_every_simulated_result_as_demo_data tests/test_ui_foundations.py::test_home_preserves_real_content_sections_and_single_primary_action -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-red-001')
```

Expected: the two new tests fail because `[data-guided-story]` and `data-demo-label` do not exist; the legacy home contract also fails after its expectation is changed.

- [ ] **Step 3: Replace the homepage card stack with semantic chapters**

In `templates/index.html`, keep the existing title, canonical, analytics page, and main class. Replace the current Hero and repeated home sections with this stable structure:

```jinja2
<div class="guided-story" data-guided-story data-active-chapter="story-purpose">
  <nav class="guided-story-progress" aria-label="首页转型路径">
    {% for chapter_id, label in (
      ('story-purpose', '为什么转型'),
      ('story-assessment', '评估准备度'),
      ('story-matching', '匹配场景'),
      ('story-roadmap', '形成路径'),
      ('story-evidence', '验证价值')
    ) %}
    <a href="#{{ chapter_id }}" data-story-step="{{ chapter_id }}"{% if loop.first %} aria-current="step"{% endif %}>
      <span aria-hidden="true">0{{ loop.index }}</span><span>{{ label }}</span>
    </a>
    {% endfor %}
  </nav>

  <section id="story-purpose" class="story-chapter story-chapter--hero" data-story-chapter data-story-key="purpose">
    <div class="story-copy">
      <p class="public-eyebrow">企业 AI 转型平台</p>
      <h1>关键的业务场景，需要可验证的 AI 落地路径</h1>
      <p>先判断准备度，再匹配场景和实施路径，让每一步都有事实依据。</p>
      <div class="ui-actions">
        <a href="/assessment" class="btn btn-primary">开始 AI 就绪度评估</a>
        <a href="/scenarios" class="btn btn-outline">浏览 AI 场景</a>
      </div>
    </div>
    <div class="story-product story-product--overview" data-product-surface="overview">
      {% for scenario in scenarios[:3] %}
      <article><span>0{{ loop.index }}</span><h2>{{ scenario.title }}</h2><p>{{ scenario.summary }}</p></article>
      {% endfor %}
    </div>
  </section>
```

Add chapters `story-assessment`, `story-matching`, `story-roadmap`, and `story-evidence` with one `h2` each. Each chapter has `.story-copy` and `.story-product`; matching loops over `scenarios[:3]`, roadmap loops over `services[:3]`, and evidence uses `cases[:1]` plus `resources[:2]` only when those collections are present. Assessment contains a visible `<span data-demo-label>演示数据</span>` next to its simulated state and no “行业平均” claim. The last chapter contains `/assessment` and `/service-packages` actions. Retain published industry/resource/announcement access through compact links inside the relevant chapters instead of restoring six independent card-grid sections.

- [ ] **Step 4: Run GREEN and the homepage responsibility set**

```powershell
& $py -m pytest tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters tests/test_public_catalog.py::test_home_labels_every_simulated_result_as_demo_data tests/test_ui_foundations.py::test_home_preserves_real_content_sections_and_single_primary_action tests/test_content_navigation.py::test_homepage_never_falls_back_to_unreviewed_legacy_content tests/test_content_navigation.py::test_home_canonical_uses_only_the_validated_public_base_url -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-green-002')
```

Expected: all selected tests pass, with no warning or cache write.

- [ ] **Step 5: Verify and commit Task 1**

```powershell
git diff --check -- templates/index.html tests/test_ui_foundations.py tests/test_public_catalog.py
git add -- templates/index.html tests/test_ui_foundations.py tests/test_public_catalog.py
git commit -m "feat: structure the guided transformation story"
```

---

### Task 2: Establish the industrial visual system and real product stage

**Files:**
- Create: `static/css/guided-story.css`
- Modify: `static/css/design-tokens.css`
- Modify: `static/css/ui-components.css`
- Modify: `static/css/public-pages.css`
- Modify: `templates/components/navigation.html`
- Modify: `templates/index.html`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: Task 1 story classes/attributes and existing shared navigation/footer components.
- Produces: graphite/paper/signal tokens, Scale-inspired signal bar and navigation, 12-column story layout, desktop sticky product surfaces, mobile linear layout, and reduced-motion CSS consumed by Tasks 3—6.

- [ ] **Step 1: Add failing token, shell, and layout tests**

Add tests that require the exact new tokens and structural rules:

```python
def test_scale_inspired_tokens_and_story_layer_are_local(client):
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True).lower()
    story_css = client.get("/static/css/guided-story.css").get_data(as_text=True)
    page = _page(client.get("/"))
    for token in (
        "--ui-graphite-1000: #07090d",
        "--ui-graphite-950: #0d1117",
        "--ui-paper-050: #f3f1eb",
        "--ui-signal-blue: #0f6fef",
        "--ui-signal-cyan: #5bd9e8",
        "--ui-container-wide: 85rem",
    ):
        assert token in tokens
    assert page.select_one('link[href="/static/css/guided-story.css"]') is not None
    assert "position: sticky" in story_css
    assert "min-height: 100svh" in story_css
    assert "@media (max-width: 767px)" in story_css
    assert "@media (prefers-reduced-motion: reduce)" in story_css


def test_shared_shell_has_truthful_signal_bar(client):
    page = _page(client.get("/"))
    signal = page.select_one("[data-site-signal]")
    assert signal is not None
    assert signal.get_text(" ", strip=True) == "从评估到实施，建立可验证的 AI 转型路径"
    assert signal.select_one('a[href="/assessment"]') is not None
```

Update the approved-token test to retain the existing semantic aliases while requiring the new graphite/paper/signal values. Add an assertion that `.story-product` loses sticky positioning below 768px.

- [ ] **Step 2: Run focused RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_scale_inspired_tokens_and_story_layer_are_local tests/test_ui_foundations.py::test_shared_shell_has_truthful_signal_bar tests/test_ui_foundations.py::test_design_tokens_are_served_with_approved_values -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-red-003')
```

Expected: failures identify the missing tokens, stylesheet, and signal bar.

- [ ] **Step 3: Implement the visual layer**

Add the spec values to `design-tokens.css` while retaining old aliases needed by unchanged pages. Set `--ui-container-wide: 85rem`, `--ui-motion-story: 680ms`, and update panel/control radii to the approved 0—8px range without shrinking 44px targets.

Create `guided-story.css` with these required behaviors:

```css
.guided-story { position: relative; background: var(--ui-paper-050); }
.guided-story-progress { position: fixed; inset-inline-end: 1.5rem; inset-block-start: 50%; z-index: 20; transform: translateY(-50%); }
.story-chapter { min-height: 100svh; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: clamp(1.5rem, 3vw, 3.5rem); align-items: center; padding: clamp(5rem, 9vw, 9rem) max(1.5rem, calc((100vw - var(--ui-container-wide)) / 2)); scroll-margin-top: 6rem; }
.story-copy { grid-column: span 5; }
.story-product { grid-column: span 7; position: sticky; top: 7rem; min-width: 0; }
.story-chapter--hero { position: relative; overflow: hidden; color: #fff; background: var(--ui-graphite-1000); }
.story-chapter--hero .story-copy { position: relative; z-index: 2; }
.story-chapter--hero .story-product { position: absolute; inset: 4rem 0 0 32%; z-index: 1; opacity: 0.46; }
.story-chapter:nth-of-type(odd):not(.story-chapter--hero) { background: var(--ui-paper-050); }
.story-chapter:nth-of-type(even) { background: var(--ui-surface-000); }
@media (max-width: 767px) {
  .guided-story-progress { position: static; transform: none; overflow-x: auto; }
  .story-chapter { min-height: auto; grid-template-columns: 1fr; padding: 4.5rem 1rem; }
  .story-copy, .story-product { grid-column: 1; }
  .story-product { position: static; top: auto; }
}
@media (prefers-reduced-motion: reduce) {
  .story-chapter, .story-product { scroll-snap-align: none; transition: none; }
}
```

Add the exact signal-bar copy to `templates/components/navigation.html`, linking only the phrase “从评估到实施，建立可验证的 AI 转型路径” to `/assessment` without inventing a new route. Add the local stylesheet link inside `templates/index.html`’s existing `head` block. Restyle navigation, buttons, footer, catalog surfaces, and detail theme to use graphite/paper/signal tokens; do not remove existing focus or target-size rules.

- [ ] **Step 4: Run GREEN and shared-shell regressions**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_smoke.py::test_shared_home_navigation_and_footer_use_the_confirmed_catalog_routes tests/test_content_navigation.py::test_navigation_matches_confirmed_information_architecture -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-green-004')
```

Expected: all selected tests pass. Run `node --check static/js/app.js` to prove the unchanged shared script remains syntactically valid.

- [ ] **Step 5: Verify and commit Task 2**

```powershell
git diff --check -- static/css/guided-story.css static/css/design-tokens.css static/css/ui-components.css static/css/public-pages.css templates/components/navigation.html templates/index.html tests/test_ui_foundations.py
git add -- static/css/guided-story.css static/css/design-tokens.css static/css/ui-components.css static/css/public-pages.css templates/components/navigation.html templates/index.html tests/test_ui_foundations.py
git commit -m "feat: establish the industrial public design system"
```

---

### Task 3: Add progressive scroll guidance without wheel interception

**Files:**
- Create: `static/js/guided_story.js`
- Create: `tests/js/guided_story_runtime.test.js`
- Modify: `templates/index.html`
- Modify: `static/css/guided-story.css`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: Task 1 `[data-guided-story]`, `[data-story-chapter]`, and `[data-story-step]` attributes plus Task 2 active-state CSS hooks.
- Produces: `activateStoryChapter(story, chapterId)` and `initializeGuidedStory(pageDocument, environment)` exports, native-anchor progress navigation, IntersectionObserver state changes, and static/reduced-motion fallback.

- [ ] **Step 1: Write failing Node event tests**

Create `tests/js/guided_story_runtime.test.js` with a small fake DOM and these behaviors:

```javascript
test('the most visible chapter activates its matching progress step', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);
  view.observer.callback([{ target: view.chapters[2], isIntersecting: true, intersectionRatio: 0.75 }]);
  assert.equal(view.story.dataset.activeChapter, 'story-matching');
  assert.equal(view.steps[2].getAttribute('aria-current'), 'step');
  assert.equal(view.chapters[2].dataset.storyActive, 'true');
});

test('reduced motion keeps the complete story static and does not create an observer', () => {
  const view = guidedStoryFixture({ reducedMotion: true });
  guided.initializeGuidedStory(view.document, view.environment);
  assert.equal(view.story.dataset.storyMode, 'static');
  assert.equal(view.observer, null);
});

test('the guided story never registers a wheel handler', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);
  assert.equal(view.document.listeners.has('wheel'), false);
  assert.equal(view.environment.listeners.has('wheel'), false);
});
```

Also test a missing story root, missing `IntersectionObserver`, repeated entries, and upward activation of an earlier chapter.

- [ ] **Step 2: Run Node RED**

```powershell
node --test tests/js/guided_story_runtime.test.js
```

Expected: FAIL because `static/js/guided_story.js` does not exist.

- [ ] **Step 3: Implement the dependency-free story controller**

Create `static/js/guided_story.js` as an IIFE/CommonJS-compatible module. `activateStoryChapter` must set one story `data-active-chapter`, mark exactly one chapter with `data-story-active="true"`, remove the marker from siblings, and set exactly one progress link to `aria-current="step"`. `initializeGuidedStory` must:

```javascript
function initializeGuidedStory(pageDocument, environment) {
  const story = pageDocument && pageDocument.querySelector
    ? pageDocument.querySelector('[data-guided-story]')
    : null;
  if (!story) return null;
  const chapters = Array.from(story.querySelectorAll('[data-story-chapter]'));
  const reduceMotion = environment && typeof environment.matchMedia === 'function'
    && environment.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion || !environment || typeof environment.IntersectionObserver !== 'function') {
    story.dataset.storyMode = 'static';
    return { story, observer: null };
  }
  story.dataset.storyMode = 'enhanced';
  const observer = new environment.IntersectionObserver(handleEntries, {
    threshold: [0.25, 0.5, 0.75],
    rootMargin: '-35% 0px -35% 0px',
  });
  chapters.forEach((chapter) => observer.observe(chapter));
  return { story, observer };
}
```

`handleEntries` selects the intersecting entry with the greatest ratio and calls `activateStoryChapter`. It must not call `preventDefault`, create a `wheel` listener, synthesize scrolling, or modify the URL. Include the script in `templates/index.html` with `defer` through the existing `scripts` block. Add CSS for `[data-story-active="true"]` and keep every chapter readable when no active marker exists.

- [ ] **Step 4: Run GREEN and source-level safety contracts**

```powershell
node --check static/js/guided_story.js
node --test tests/js/guided_story_runtime.test.js tests/js/app_runtime.test.js
& $py -m pytest tests/test_ui_foundations.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-green-005')
```

Add an HTTP/source test that reads `guided_story.js`, asserts `IntersectionObserver` is present, and rejects the regular expressions `addEventListener\(['\"]wheel` and `wheel[\s\S]{0,200}preventDefault`.

- [ ] **Step 5: Verify and commit Task 3**

```powershell
git diff --check -- static/js/guided_story.js tests/js/guided_story_runtime.test.js templates/index.html static/css/guided-story.css tests/test_ui_foundations.py
git add -- static/js/guided_story.js tests/js/guided_story_runtime.test.js templates/index.html static/css/guided-story.css tests/test_ui_foundations.py
git commit -m "feat: guide the homepage through native scrolling"
```

---

### Task 4: Extend the industrial design to scenario catalog and detail

**Files:**
- Modify: `templates/scenarios.html`
- Modify: `templates/scenario_detail.html`
- Modify: `static/css/public-pages.css`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: Task 2 graphite/paper/signal tokens, existing scenario filter form/query contract, existing `ScenarioCard` fields, existing detail timeline/budget formatter, and published-only scenario view model.
- Produces: a scenario signal panel, editorial scenario rows, one decision-cover detail Hero, three existing decision chapters, and responsive/mobile presentation without data-contract changes.

- [ ] **Step 1: Add failing scenario presentation contracts**

Add tests that preserve behavior while requiring the new composition:

```python
def test_scenario_catalog_uses_signal_panel_and_editorial_rows(published_catalog):
    document = page(published_catalog.get("/scenarios?industry=manufacturing&maturity=pilot"))
    panel = document.select_one('form.scenario-signal-panel[aria-label="筛选场景"]')
    assert panel is not None
    assert panel.select_one('[data-result-count]').get_text(" ", strip=True).startswith("共 ")
    rows = document.select("[data-scenario-code].scenario-signal-row > article.catalog-card")
    assert rows
    assert rows[0].select_one("dl.catalog-card-meta") is not None
    assert document.select_one('#industry[value="manufacturing"]') is not None
    assert document.select_one('#maturity option[selected][value="pilot"]') is not None


def test_scenario_detail_uses_decision_cover_and_exact_three_chapters(published_catalog):
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    assert document.select_one(".scenario-decision-cover h1") is not None
    assert [h.get_text(" ", strip=True) for h in document.select(".decision-main > .decision-section > h2")] == [
        "适用场景", "实施路径", "关键输入、输出与风险"
    ]
    assert len(document.select('[data-content-section="timeline"]')) == 1
    assert len(document.select('[data-content-section="budget"]')) == 1
```

- [ ] **Step 2: Run focused RED**

```powershell
& $py -m pytest tests/test_public_catalog.py::test_scenario_catalog_uses_signal_panel_and_editorial_rows tests/test_public_catalog.py::test_scenario_detail_uses_decision_cover_and_exact_three_chapters tests/test_public_catalog.py::test_scenario_filters_are_intersection_not_union tests/test_ui_foundations.py::test_decision_detail_css_numbers_primary_chapters -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-red-006')
```

Expected: the two new class/composition tests fail; filter and chapter safeguards continue to pass before implementation.

- [ ] **Step 3: Implement the scenario catalog and decision cover**

In `scenarios.html`, keep the same field names, values, method, canonical, pagination arguments, empty state, and routes. Add a `.scenario-catalog-intro`, rename the form surface to include `.scenario-signal-panel`, render `共 {{ page.total }} 个已发布场景` in `[data-result-count]`, and add `.scenario-signal-row` to the existing `[data-scenario-code]` wrapper without modifying the shared `content_card` macro or introducing unavailable timeline/budget fields.

In `scenario_detail.html`, add `.scenario-decision-cover` to the existing themed Hero composition. Preserve the exact three primary `.decision-section` blocks, one timeline, one budget, published-only related data, formatter calls, assessment CTA, canonical, and SEO fields. Do not duplicate services in the summary.

Update `public-pages.css` so the scenario list uses separated editorial rows with stronger numeric/type hierarchy rather than three equal white cards. The decision cover uses graphite/paper/signal tokens, 12-column alignment, small-radius surfaces, and existing 44px actions. At `<768px`, filters, rows, cover, and summary return to one column without sticky positioning or horizontal overflow.

- [ ] **Step 4: Run GREEN and the public scenario responsibility set**

```powershell
& $py -m pytest tests/test_public_catalog.py tests/test_ui_foundations.py tests/test_pagination.py tests/test_content_navigation.py tests/test_public_services.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-green-007')
```

Expected: the complete selected public/scenario responsibility set passes. No full suite is run.

- [ ] **Step 5: Verify and commit Task 4**

```powershell
git diff --check -- templates/scenarios.html templates/scenario_detail.html static/css/public-pages.css tests/test_public_catalog.py tests/test_ui_foundations.py
git add -- templates/scenarios.html templates/scenario_detail.html static/css/public-pages.css tests/test_public_catalog.py tests/test_ui_foundations.py
git commit -m "feat: refine the scenario decision experience"
```

---

### Task 5: Produce and integrate two measured decorative technology assets

**Files:**
- Create: `static/images/ui/industrial-data-infrastructure.webp`
- Create: `static/images/ui/enterprise-compute-space.webp`
- Modify: `templates/index.html`
- Modify: `static/css/guided-story.css`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: reviewed Task 1—4 homepage structure and real product surfaces; Task 5 records fresh Browser slot measurements before generation.
- Produces: two local decorative assets with fixed dimensions, empty alt text, no factual content, bounded byte sizes, and no runtime external URL.

- [ ] **Step 1: Add failing local-asset contracts and measure slots**

Add a test that requires both local files, local URLs, empty alt text, and bounded sizes:

```python
from pathlib import Path


def test_home_technology_assets_are_local_decorative_and_bounded(client):
    page = _page(client.get("/"))
    images = page.select('img[data-technology-art]')
    assert [image["src"] for image in images] == [
        "/static/images/ui/industrial-data-infrastructure.webp",
        "/static/images/ui/enterprise-compute-space.webp",
    ]
    assert all(image.get("alt") == "" for image in images)
    root = Path(__file__).resolve().parents[1]
    for image in images:
        asset = root / "static" / image["src"].removeprefix("/static/")
        assert asset.exists()
        assert asset.stat().st_size <= 350_000
```

Before generation, inspect the current local homepage at 1440×1024 and record the rendered width/height and crop intention for the chapter-transition and final-CTA slots in the Task 5 report. Do not generate until those measurements are recorded.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_home_technology_assets_are_local_decorative_and_bounded -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-red-008')
```

Expected: FAIL because the two asset elements/files do not exist.

- [ ] **Step 3: Generate, inspect, and post-process the assets**

Use the built-in image generation tool with these exact art directions, adjusted only for the measured crop:

1. `industrial-data-infrastructure.webp`: “Wide cinematic abstract enterprise data infrastructure, graphite-black industrial control environment, dense physical server and sensor geometry, restrained cobalt-blue signal light, documentary realism, precise, quiet, premium, no text, no logos, no people, no UI, no numbers, no neon cyberpunk, 16:10 composition with subject weighted to the right.”
2. `enterprise-compute-space.webp`: “Wide premium enterprise computing space, black and warm-gray architectural volume with a single controlled blue signal path, subtle glass and metal, reliable industrial technology rather than science fiction, no text, no logos, no people, no UI, no numbers, no neon, 16:9 composition with clear negative space for a CTA.”

Inspect each generated bitmap before use. Convert/crop locally to WebP at the measured ratio, retain enough resolution for a 2× desktop slot, strip metadata, and keep each file at or below 350KB without visible banding. Do not generate a dashboard or imitate Scale assets.

- [ ] **Step 4: Integrate the assets and run GREEN**

Place the first empty-alt `<img data-technology-art>` in the roadmap transition surface and the second in the final evidence/CTA surface. Set explicit `width` and `height`; use `loading="lazy"` and `decoding="async"` because neither image is the primary Hero proof. CSS must preserve focal crop with `object-fit: cover` and provide a non-image graphite/paper background fallback.

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_home_technology_assets_are_local_decorative_and_bounded tests/test_public_catalog.py::test_home_exposes_five_truthful_guided_story_chapters -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-green-009')
```

Expected: both tests pass; inspect both final files with the image viewer.

- [ ] **Step 5: Verify and commit Task 5**

```powershell
git diff --check -- templates/index.html static/css/guided-story.css tests/test_ui_foundations.py
git add -- static/images/ui/industrial-data-infrastructure.webp static/images/ui/enterprise-compute-space.webp templates/index.html static/css/guided-story.css tests/test_ui_foundations.py
git commit -m "feat: add measured industrial technology artwork"
```

---

### Task 6: Run blocking design QA, capture evidence, and stop at review gate

**Files:**
- Create: `design-qa.md`
- Create: `docs/testing/scale-inspired-guided-public-ui.md`
- Create: `docs/design/evidence/2026-08-28-guided-home-purpose-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-home-assessment-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-home-matching-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-home-roadmap-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-home-evidence-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-home-mobile.png`
- Create: `docs/design/evidence/2026-08-28-guided-scenarios-desktop.png`
- Create: `docs/design/evidence/2026-08-28-guided-scenario-detail-desktop.png`
- Modify: `.superpowers/sdd/2026-08-28-scale-inspired-guided-public-ui/progress.md` (ignored control file only)

**Interfaces:**
- Consumes: independently reviewed Tasks 1—5, the captured Scale reference, deterministic local fixture, and Codex in-app Browser.
- Produces: fresh automated evidence, same-viewport reference/implementation comparison, five chapter screenshots, responsive screenshots, interaction findings, a `design-qa.md` whose final line is `final result: passed` or `final result: blocked`, and a review-ready evidence commit.

- [ ] **Step 1: Freeze the reviewed implementation and run final scoped automation**

Record exact `git rev-parse HEAD`, `git status --short`, Python version, `PYTHONPATH`, dependency versions, and commands. Then run:

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-28-scale-inspired-guided-public-ui\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_content_navigation.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py tests/test_pagination.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task6-final-scoped-010')
node --check static/js/app.js
node --check static/js/guided_story.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/analytics_runtime.test.js
```

Do not run the full suite.

- [ ] **Step 2: Start a deterministic disposable local fixture**

Create a fresh SQLite database and media directory below this plan’s ignored SDD workspace, seed only deterministic published content, and bind the app to a free `127.0.0.1` port. Record the database path, media path, command, launcher PID, listener PID, and local port. Confirm `/`, `/scenarios`, and `/scenarios/mfg-knowledge-assistant` return HTTP 200 before Browser capture.

- [ ] **Step 3: Capture all stable states at exact viewports**

Use the Codex in-app Browser. Capture the five homepage chapters at 1440×1024 after each chapter has settled, the full homepage flow at 390×844, scenarios at 1440×1024, and the scenario detail at 1440×1024. Record document `scrollWidth` and `clientWidth` for each viewport and reject page-level horizontal overflow.

- [ ] **Step 4: Perform the required same-input visual comparison**

Open the current Scale reference capture and the local first-chapter screenshot together in one visual comparison input. Separately open all local chapter screenshots together. Inspect headline scale, real-interface prominence, graphite/paper balance, 12-column alignment, spacing, typography, borders, radii, crop quality, generated-image fit, progress state, sticky boundaries, mobile stacking, and footer arrival.

Write findings to root `design-qa.md` with severity P0—P3 and exact screen/state. Fix every P0/P1/P2 through a Task 6 RED→GREEN fix and recapture the affected state. P3 polish may remain as explicit follow-up. The file must end with exactly `final result: passed` when all blocking findings are closed; if Browser capture or comparison is impossible, end with `final result: blocked` and stop.

- [ ] **Step 5: Verify real interactions and accessibility**

Exercise native wheel/trackpad-style scrolling, fast scroll, scrollbar drag, reverse scroll, all five progress links, browser find, mobile menu, scenario filters, empty/reset state, pagination when fixture data permits it, assessment CTAs, and footer arrival. Verify reduced-motion rendering, no-JavaScript content availability, 200% text zoom, Tab, Shift+Tab, Enter, Space, arrows, Page Down, and Escape. Record `PASS`, `FAIL`, or `NOT PROVEN` truthfully for each; do not substitute scripted focus for native keyboard evidence.

- [ ] **Step 6: Stop the fixture and document evidence**

Stop the exact listener process and children, confirm the port is closed, and do not remove any unrelated path. Record screenshot dimensions/SHA-256, asset bytes, automated summaries, interaction results, limitations, and cleanup in `docs/testing/scale-inspired-guided-public-ui.md`.

- [ ] **Step 7: Verify, commit evidence, and request final review**

```powershell
git diff --check
git status --short
git add -- design-qa.md docs/testing/scale-inspired-guided-public-ui.md docs/design/evidence/2026-08-28-guided-home-purpose-desktop.png docs/design/evidence/2026-08-28-guided-home-assessment-desktop.png docs/design/evidence/2026-08-28-guided-home-matching-desktop.png docs/design/evidence/2026-08-28-guided-home-roadmap-desktop.png docs/design/evidence/2026-08-28-guided-home-evidence-desktop.png docs/design/evidence/2026-08-28-guided-home-mobile.png docs/design/evidence/2026-08-28-guided-scenarios-desktop.png docs/design/evidence/2026-08-28-guided-scenario-detail-desktop.png
git commit -m "docs: verify the guided public experience"
```

Generate the full-plan review package from the plan base through Task 6 HEAD and dispatch one fresh independent reviewer. Fix only scoped P0—P2 findings through the SDD loop. After reviewer CLEAN and controller-focused verification, stop at the user visual-acceptance checkpoint; do not start another UI family or deployment.

## Plan Completion Gate

This plan is complete only when Tasks 1—6 each have a task-scoped independent review, the final whole-plan reviewer is CLEAN, controller-focused pytest and Node verification are fresh, `design-qa.md` says `final result: passed`, all required screenshots were inspected, and native keyboard/scroll evidence is either PASS or explicitly blocks completion. Completion means only the Scale-inspired homepage/scenario core is locally ready for user visual acceptance; it does not mean assessment/report UI, admin UI, all functions, final full regression, or production deployment is complete.
