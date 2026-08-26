# UI Foundations and Public Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved enterprise visual foundation and apply it to the shared public shell, homepage, catalog lists, catalog details, controlled content blocks, and editorial public pages without changing business or publication semantics.

**Architecture:** Keep the existing Flask/Jinja server-rendered application and layer a small design system after the legacy stylesheet. Shared tokens and components live in focused CSS files; Jinja components own repeated public markup, while existing repositories remain the only source of public data. Each task uses HTTP/template assertions plus exact JavaScript event tests, then receives an independent review before the next task.

**Tech Stack:** Flask, Jinja2, semantic HTML, local CSS, dependency-free browser JavaScript, pytest, BeautifulSoup, Node `node:test`, in-app local Browser QA.

**Spec:** `docs/superpowers/specs/2026-08-26-enterprise-ai-platform-ui-design.md`

## Global Constraints

- Approved visual target: `docs/design/evidence/2026-08-26-ui-visual-baseline.png`, SHA-256 `9B703B75F6B3B826749B4C3E3F86BEC2704BF0319FD342E7064DDA68A18C9C36`.
- Preserve `static/logo.png`; do not invent or redraw the brand mark.
- Preserve all Flask URLs, repository/service transaction boundaries, published-only reads, canonical/noindex rules, CSRF, URL validation, rich-text sanitization, media endpoints, and analytics semantics.
- Templates consume existing validated view models only. A missing presentation field does not authorize direct SQL, repository bypass, fake copy, or a new API.
- Use only local assets and dependencies. Do not access a real network or install packages.
- Do not deploy, modify a server, Nginx, systemd, a real database, or expose a public listener.
- Run local previews only on `127.0.0.1` with a disposable SQLite database and media directory, then stop the listener.
- Do not use emoji, character icons, CSS art, handcrafted SVG, invented metrics, fake customers, avatars, notifications, assessment statuses, or unsupported budget/timeline values.
- Body text is at least 16px; actionable controls are at least 44px; visible focus is at least 3px; `prefers-reduced-motion` disables nonessential motion.
- Breakpoints are `1200px`, `1024px`, `768px`, and `390px`; 320px must not produce page-level horizontal scrolling.
- Python interpreter: `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe`.
- For each pytest invocation, set `PYTHONPATH` to `.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps`, use a new absolute directory below `.superpowers/sdd/2026-08-26-ui-foundations-public-catalog/test-tmp/`, and pass `-p no:cacheprovider`.
- The current worktree already contains unrelated Task 12 edits. Inspect `git status --short` before every task; never overwrite, stage, amend, or commit those files unless the current task explicitly owns the same path. Every commit uses an exact path list.
- This plan does not run the final full suite. The later cross-page UI QA plan owns the one frozen full run after public, assessment/report, and admin UI tasks are all reviewed.

## Plan Boundary

This is plan 1 of the approved UI rollout. It produces a working public site and the shared design-system contract. Separate plans will cover:

1. assessment and report UI;
2. admin operations UI;
3. cross-page responsive, keyboard, performance, and final regression closure.

Those plans consume the CSS variables, component classes, shell behavior, and evidence format created here. They must not redefine the visual foundation.

---

### Task 1: Freeze the design-system contract and stylesheet layers

**Files:**
- Create: `static/css/design-tokens.css`
- Create: `static/css/ui-components.css`
- Create: `static/css/public-pages.css`
- Create: `tests/test_ui_foundations.py`
- Modify: `templates/base.html`
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: existing `base.html`, `app.css`, `index.html`, Flask static routing, and the approved visual token table.
- Produces: CSS custom properties on `:root`; shared `.ui-*` component namespace; public `.public-*` namespace; ordered stylesheet links; `.skip-link`; `main#main-content` on the homepage.

- [ ] **Step 1: Write the failing stylesheet and shell tests**

Add these concrete tests to `tests/test_ui_foundations.py`:

```python
from bs4 import BeautifulSoup


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def test_public_shell_loads_design_layers_after_legacy_css(client):
    page = _page(client.get("/"))
    hrefs = [link["href"] for link in page.select('link[rel="stylesheet"]')]
    assert hrefs[-4:] == [
        "/static/css/app.css",
        "/static/css/design-tokens.css",
        "/static/css/ui-components.css",
        "/static/css/public-pages.css",
    ]


def test_home_has_skip_link_and_single_named_main(client):
    page = _page(client.get("/"))
    assert page.select_one('a.skip-link[href="#main-content"]') is not None
    mains = page.select("main#main-content")
    assert len(mains) == 1


def test_design_tokens_are_served_with_approved_values(client):
    response = client.get("/static/css/design-tokens.css")
    css = response.get_data(as_text=True)
    assert response.status_code == 200
    for token in (
        "--ui-navy-950: #061b46",
        "--ui-blue-600: #0f5fef",
        "--ui-blue-700: #0b49bf",
        "--ui-teal-700: #007c91",
        "--ui-amber-700: #9a5b00",
        "--ui-ink-950: #15213a",
        "--ui-ink-650: #536176",
        "--ui-line-200: #dde4ee",
    ):
        assert token in css.lower()
    assert "prefers-reduced-motion: reduce" in css
```

- [ ] **Step 2: Run the tests and verify the intended RED**

Run in PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-red-001')
```

Expected: FAIL because the three stylesheet files, skip link, and `#main-content` contract do not exist.

- [ ] **Step 3: Add the stylesheet layers and base tokens**

Add the links after `app.css` in `templates/base.html` and the skip link before the global navigation:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/design-tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/ui-components.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/public-pages.css') }}">
...
<a class="skip-link" href="#main-content">跳到主要内容</a>
{% include "components/navigation.html" %}
```

Change the homepage opening tag to:

```html
<main id="main-content" class="public-page public-home">
```

Create `static/css/design-tokens.css` with these foundations:

```css
:root {
  --ui-navy-950: #061b46;
  --ui-blue-600: #0f5fef;
  --ui-blue-700: #0b49bf;
  --ui-teal-700: #007c91;
  --ui-amber-700: #9a5b00;
  --ui-ink-950: #15213a;
  --ui-ink-650: #536176;
  --ui-line-200: #dde4ee;
  --ui-surface-050: #f6f8fb;
  --ui-surface-000: #ffffff;
  --ui-space-1: 0.5rem;
  --ui-space-2: 0.75rem;
  --ui-space-3: 1rem;
  --ui-space-4: 1.5rem;
  --ui-space-5: 2rem;
  --ui-space-6: 3rem;
  --ui-space-7: 4rem;
  --ui-space-8: 5rem;
  --ui-radius-control: 0.5rem;
  --ui-radius-panel: 0.75rem;
  --ui-container: 75rem;
  --ui-reading: 52rem;
  --ui-focus: 0 0 0 3px rgba(15, 95, 239, 0.42);
  --ui-motion-fast: 160ms;
  --ui-motion-standard: 220ms;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
```

Create `ui-components.css` with the first shared primitives:

```css
.skip-link {
  position: fixed;
  top: var(--ui-space-2);
  left: var(--ui-space-2);
  z-index: 1000;
  padding: var(--ui-space-2) var(--ui-space-3);
  transform: translateY(-160%);
  border-radius: var(--ui-radius-control);
  background: var(--ui-ink-950);
  color: var(--ui-surface-000);
}

.skip-link:focus { transform: translateY(0); }

:focus-visible {
  outline: 0;
  box-shadow: var(--ui-focus);
}

.btn,
button,
select,
textarea,
input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]),
summary {
  min-height: 2.75rem;
}

.ui-empty-state {
  padding: var(--ui-space-6);
  border-top: 1px solid var(--ui-line-200);
  text-align: center;
}
```

Create `public-pages.css` with the layout baseline:

```css
.public-page {
  min-width: 0;
  color: var(--ui-ink-950);
  background: var(--ui-surface-000);
}

.public-container {
  width: min(100% - 3rem, var(--ui-container));
  margin-inline: auto;
}

.public-reading { max-width: var(--ui-reading); }

.public-section { padding-block: var(--ui-space-8); }

@media (max-width: 1023px) {
  .public-container { width: min(100% - 2.5rem, var(--ui-container)); }
}

@media (max-width: 767px) {
  .public-container { width: min(100% - 2rem, var(--ui-container)); }
  .public-section { padding-block: var(--ui-space-7); }
}

@media (max-width: 389px) {
  .public-container { width: min(100% - 1.5rem, var(--ui-container)); }
}
```

Keep all new component selectors under `.ui-*`, `.public-*`, or the named exceptions above. Do not restyle catalog-specific blocks yet.

- [ ] **Step 4: Run the focused tests and the existing navigation guard**

Run:

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py::test_navigation_matches_confirmed_information_architecture -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-green-002')
```

Expected: PASS.

- [ ] **Step 5: Review and commit only Task 1 files**

```powershell
git diff --check -- static/css/design-tokens.css static/css/ui-components.css static/css/public-pages.css templates/base.html templates/index.html tests/test_ui_foundations.py
git add -- static/css/design-tokens.css static/css/ui-components.css static/css/public-pages.css templates/base.html templates/index.html tests/test_ui_foundations.py
git commit -m "feat: establish the public UI foundation"
```

Dispatch a fresh read-only reviewer for this commit. Do not start Task 2 until the reviewer is CLEAN and the controller reruns the Task 1 focused tests.

---

### Task 2: Rebuild the shared navigation, footer, and conversion shell

**Files:**
- Create: `tests/js/app_runtime.test.js`
- Modify: `templates/components/navigation.html`
- Modify: `templates/components/footer.html`
- Modify: `templates/components/sticky_cta.html`
- Modify: `static/js/app.js`
- Modify: `static/css/ui-components.css`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: Task 1 tokens and `.ui-*` primitives; existing navigation URLs and analytics attributes.
- Produces: `initializeMobileNavigation(pageDocument)` exported from `app.js`; native `<details data-mobile-navigation>` shell with deterministic Escape/link-close behavior; text-only truthful sticky CTA; structured footer classes.

- [ ] **Step 1: Add failing HTTP assertions for the shared shell**

Append:

```python
def test_shared_shell_uses_real_brand_and_truthful_conversion_copy(client):
    page = _page(client.get("/"))
    logo = page.select_one('.nav-logo img[src="/static/logo.png"]')
    assert logo is not None
    assert logo.get("alt") == ""
    assert page.select_one('.nav-logo[aria-label="企业 AI 转型平台首页"]') is not None
    assert page.select_one(".nav-brand-text").get_text(" ", strip=True) == "企业 AI转型 平台"
    assert page.select_one('[data-primary-cta][href="/assessment"]') is not None
    sticky = page.select_one("#stickyCta")
    assert sticky is not None
    text = sticky.get_text(" ", strip=True)
    assert "完成 AI 就绪度评估" in text
    assert "5 分钟" not in text
    assert "🚀" not in text


def test_footer_has_no_inline_layout_styles(client):
    page = _page(client.get("/"))
    footer = page.select_one("footer.footer")
    assert footer is not None
    assert not footer.select("[style]")
```

- [ ] **Step 2: Add failing real-event Node tests**

Create `tests/js/app_runtime.test.js` with a minimal fake DOM that supports `querySelector`, `querySelectorAll`, `addEventListener`, `dispatchEvent`, `closest`, `open`, and `focus`. Test the exported function exactly:

```javascript
const assert = require('node:assert/strict');
const test = require('node:test');
const app = require('../../static/js/app.js');

class FakeTarget {
  constructor() {
    this.listeners = new Map();
    this.open = false;
    this.focused = false;
  }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
  }
  focus() { this.focused = true; }
}

function mobileNavigationFixture() {
  const document = new FakeTarget();
  const details = new FakeTarget();
  const summary = new FakeTarget();
  const link = new FakeTarget();
  document.querySelector = (selector) => (
    selector === 'details[data-mobile-navigation]' ? details : null
  );
  details.querySelector = (selector) => selector === 'summary' ? summary : null;
  link.closest = (selector) => selector === 'a[href]' ? link : null;
  return { document, details, summary, link };
}

test('Escape closes the mobile menu and restores summary focus', () => {
  const view = mobileNavigationFixture();
  view.details.open = true;
  app.initializeMobileNavigation(view.document);
  view.document.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(view.details.open, false);
  assert.equal(view.summary.focused, true);
});

test('activating a mobile navigation link closes the menu', () => {
  const view = mobileNavigationFixture();
  view.details.open = true;
  app.initializeMobileNavigation(view.document);
  view.details.dispatchEvent({ type: 'click', target: view.link });
  assert.equal(view.details.open, false);
});
```

- [ ] **Step 3: Run both RED suites**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-red-http-003')
node --test tests/js/app_runtime.test.js
```

Expected: HTTP assertions fail on current logo alt/sticky/footer markup; Node fails because `initializeMobileNavigation` is not exported.

- [ ] **Step 4: Implement the truthful shared shell**

Use these exact public labels and routes in `navigation.html`:

```html
<a href="/" class="nav-logo" aria-label="企业 AI 转型平台首页">
  <img src="{{ url_for('static', filename='logo.png') }}" alt="">
  <span class="nav-brand-text">企业 <strong>AI转型</strong> 平台</span>
</a>
...
<a href="/assessment" class="nav-cta" data-primary-cta>免费评估</a>
```

Keep the five frozen navigation links unchanged. Keep `<details data-mobile-navigation>` and its native `<summary>菜单</summary>`.

Replace sticky CTA copy and inline styles with:

```html
<aside class="sticky-cta" id="stickyCta" aria-label="评估入口">
  <span class="cta-text">完成 AI 就绪度评估，获取与你当前条件匹配的建议</span>
  <a href="/assessment" class="btn btn-primary btn-sm">免费评估</a>
</aside>
```

Move footer inline typography into `.footer-company-summary` and `.footer-contact` classes. Preserve the existing company name, phone analytics attributes, QR link, ICP link, and safe external-link attributes.

Add this dependency-free interface inside `app.js` before browser auto-initialization:

```javascript
function initializeMobileNavigation(pageDocument) {
  const details = pageDocument && pageDocument.querySelector(
    "details[data-mobile-navigation]"
  );
  if (!details) return null;
  const summary = details.querySelector("summary");
  pageDocument.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !details.open) return;
    details.open = false;
    if (summary && typeof summary.focus === "function") summary.focus();
  });
  details.addEventListener("click", function (event) {
    const link = event.target && typeof event.target.closest === "function"
      ? event.target.closest("a[href]")
      : null;
    if (link) details.open = false;
  });
  return details;
}
```

Export it beside the existing functions and call it once in the browser path. Add these structural rules, extending them with the approved spacing tokens rather than legacy inline styles:

```css
.nav { background: rgba(255, 255, 255, 0.96); }
.nav-inner { min-height: 4.5rem; height: auto; }
.nav-logo { min-height: 2.75rem; }
.nav-logo img { width: 2rem; height: 2.5rem; }
.nav-brand-text { color: var(--ui-ink-950); white-space: nowrap; }
.nav-brand-text strong { color: var(--ui-blue-600); }
.nav-links a.active { box-shadow: inset 0 -3px 0 var(--ui-blue-600); }
.nav-cta { min-height: 2.75rem; display: inline-flex; align-items: center; }
.footer-company-summary { max-width: 32rem; line-height: 1.8; }
.sticky-cta { min-height: 4.5rem; }

@media (max-width: 767px) {
  .nav-brand-text { font-size: 1rem; }
  .mobile-navigation-panel { max-width: calc(100vw - 2rem); }
  .sticky-cta { align-items: stretch; }
}
```

Use no invented icon asset.

- [ ] **Step 5: Run HTTP, Node, and existing analytics/navigation tests**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
node --check static/js/app.js
node --test tests/js/app_runtime.test.js tests/js/analytics_runtime.test.js
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_analytics_js_runtime.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-green-004')
```

Expected: PASS; the frozen navigation list, primary CTA, footer analytics, URL matrix, and current analytics runtime remain intact.

- [ ] **Step 6: Review and commit Task 2**

```powershell
git diff --check -- templates/components/navigation.html templates/components/footer.html templates/components/sticky_cta.html static/js/app.js static/css/ui-components.css tests/test_ui_foundations.py tests/js/app_runtime.test.js
git add -- templates/components/navigation.html templates/components/footer.html templates/components/sticky_cta.html static/js/app.js static/css/ui-components.css tests/test_ui_foundations.py tests/js/app_runtime.test.js
git commit -m "feat: redesign the shared public shell"
```

Require a fresh reviewer CLEAN plus controller rerun before Task 3.

---

### Task 3: Build reusable catalog headers, filters, cards, pagination, and empty states

**Files:**
- Create: `templates/components/public_catalog.html`
- Modify: `templates/components/content_card.html`
- Modify: `templates/components/ui.html`
- Modify: `templates/industries.html`
- Modify: `templates/scenarios.html`
- Modify: `templates/service_packages.html`
- Modify: `templates/cases.html`
- Modify: `templates/resources.html`
- Modify: `static/css/public-pages.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_public_services.py`
- Modify: `tests/test_verified_cases.py`
- Modify: `tests/test_resources_announcements.py`

**Interfaces:**
- Consumes: existing `Page.items/page/total_pages/per_page`, scenario/resource filters, route names, published view models, and Task 1 component CSS.
- Produces: `page_header(title, summary, eyebrow='')`, `empty_state(message, reset_href='')`, and `content_card(item, href, eyebrow='', heading_level=2)` Jinja macros; `.public-list`, `.public-filter`, `.catalog-grid`, `.catalog-card`, and `.ui-pagination` contracts.

- [ ] **Step 1: Add failing semantic list tests**

Add focused assertions that use existing test fixtures and published objects:

```python
@pytest.mark.parametrize(
    "path, page_class",
    (
        ("/industries", "public-industries"),
        ("/scenarios", "public-scenarios"),
        ("/service-packages", "public-services"),
        ("/cases", "public-cases"),
        ("/resources", "public-resources"),
    ),
)
def test_catalog_lists_share_semantic_page_structure(client, path, page_class):
    page = _page(client.get(path))
    main = page.select_one(f"main#main-content.{page_class}")
    assert main is not None
    assert len(main.select(":scope > .public-page-header h1")) == 1
    assert main.select_one(".catalog-grid") is not None


def test_scenario_filters_keep_accessible_labels_and_selected_values(client):
    page = _page(client.get("/scenarios?industry=manufacturing&maturity=pilot"))
    form = page.select_one('form.public-filter[aria-label="筛选场景"]')
    assert form.select_one('label[for="industry"]') is not None
    assert form.select_one('#industry[value="manufacturing"]') is not None
    assert form.select_one('#maturity option[selected][value="pilot"]') is not None
    assert form.select_one('a[href="/scenarios"]') is not None
```

Extend the existing empty-state tests to require `[data-empty-state].ui-empty-state` and a route-correct reset link when filters are active. Keep the current assertions for content, pagination, status, canonical, and published-only behavior.

- [ ] **Step 2: Run the list RED suite**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-red-005')
```

Expected: new structure assertions fail while existing business assertions continue to pass.

- [ ] **Step 3: Implement shared list macros and markup**

Create `public_catalog.html` with exact macro signatures:

```jinja2
{% macro page_header(title, summary, eyebrow='') -%}
<header class="public-page-header">
  {% if eyebrow %}<p class="public-eyebrow">{{ eyebrow }}</p>{% endif %}
  <h1>{{ title }}</h1>
  <p>{{ summary }}</p>
</header>
{%- endmacro %}

{% macro empty_state(message, reset_href='') -%}
<div class="ui-empty-state" data-empty-state>
  <h2>暂时没有符合条件的内容</h2>
  <p>{{ message }}</p>
  {% if reset_href %}<a class="btn btn-outline" href="{{ reset_href }}">清除筛选</a>{% endif %}
</div>
{%- endmacro %}
```

Change `content_card` to this exact signature and hierarchy behavior:

```jinja2
{% macro content_card(item, href, eyebrow='', heading_level=2) -%}
<article class="catalog-card">
  {% if eyebrow %}<p class="public-eyebrow">{{ eyebrow }}</p>{% endif %}
  {% if heading_level == 3 %}
    <h3><a class="catalog-card-link" href="{{ href }}">{{ item.title }}</a></h3>
  {% else %}
    <h2><a class="catalog-card-link" href="{{ href }}">{{ item.title }}</a></h2>
  {% endif %}
  <p>{{ item.summary }}</p>
  <span class="catalog-card-action" aria-hidden="true">查看详情</span>
</article>
{%- endmacro %}
```

List pages use the default `heading_level=2`; homepage sections pass `heading_level=3` because each section already has an `h2`. Do not add icons or fake metadata.

Change the pagination macro class to `ui-pagination` while preserving `aria-label`, `aria-current`, `rel=prev`, `rel=next`, every current query parameter, and all page links.

Rewrite the five list templates with formatted multiline markup, `main#main-content`, a shared page header, `.catalog-grid`, and route-correct empty states. Preserve all existing `data-*` hooks used by tests and analytics.

For scenario and resource filters, keep current GET parameter names exactly. Add explicit reset links `/scenarios` and `/resources`; do not introduce client-side filtering.

- [ ] **Step 4: Add responsive list CSS**

Implement:

```css
.catalog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--ui-space-4);
}

.catalog-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--ui-space-2);
  padding: var(--ui-space-5);
  border-top: 3px solid transparent;
  background: var(--ui-surface-000);
}

.catalog-card:focus-within,
.catalog-card:hover {
  border-top-color: var(--ui-blue-600);
}

@media (max-width: 1023px) {
  .catalog-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 767px) {
  .catalog-grid { grid-template-columns: 1fr; }
  .public-filter { grid-template-columns: 1fr; }
}
```

Use lightweight row separation rather than a shadow on every card. Clamp nothing that would hide server content; allow long Chinese and URLs to wrap.

- [ ] **Step 5: Run the complete list responsibility set**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_pagination.py tests/test_content_navigation.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-green-006')
```

Expected: PASS with current canonical, query, publication, pagination, empty-state, and security assertions unchanged.

- [ ] **Step 6: Review and commit Task 3**

```powershell
git diff --check -- templates/components/public_catalog.html templates/components/content_card.html templates/components/ui.html templates/industries.html templates/scenarios.html templates/service_packages.html templates/cases.html templates/resources.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py
git add -- templates/components/public_catalog.html templates/components/content_card.html templates/components/ui.html templates/industries.html templates/scenarios.html templates/service_packages.html templates/cases.html templates/resources.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py
git commit -m "feat: redesign the public catalog lists"
```

Require fresh reviewer CLEAN and controller verification before Task 4.

---

### Task 4: Render the decision-detail shell and all controlled content blocks

**Files:**
- Create: `templates/components/detail_page.html`
- Modify: `templates/components/content_blocks.html`
- Modify: `templates/industry_detail.html`
- Modify: `templates/scenario_detail.html`
- Modify: `templates/service_package_detail.html`
- Modify: `static/css/public-pages.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_public_services.py`

**Interfaces:**
- Consumes: existing industry/scenario/service view-model fields and all seven validated content block schemas.
- Produces: `breadcrumb(back_href, back_label, current_label)`, `detail_hero(title, summary, eyebrow='')`, and `decision_item(label, value)` macros; `.decision-detail`, `.decision-main`, `.decision-summary`, `.content-block-*` visual contracts.

- [ ] **Step 1: Write failing decision-page and content-block tests**

Add assertions to the existing publish-to-public tests so they verify visible semantic output, not only section markers:

```python
def _assert_decision_shell(page):
    assert page.select_one("main#main-content.decision-detail") is not None
    assert page.select_one(".detail-hero h1") is not None
    assert page.select_one(".decision-main") is not None
    assert page.select_one('aside.decision-summary[aria-labelledby="decision-summary-title"]') is not None
    assert page.select_one('.decision-summary a[href="/assessment"]') is not None


def test_scenario_detail_uses_real_decision_summary(client):
    page = _page(client.get("/scenarios/mfg-knowledge-assistant"))
    _assert_decision_shell(page)
    summary = page.select_one(".decision-summary").get_text(" ", strip=True)
    assert "适用行业" in summary
    assert "相关部门" in summary
    assert "周期" in summary
    assert "预算" in summary
    assert "评估后确认" in summary or "周" in summary
    assert "已评估" not in summary
    assert "已覆盖" not in summary
```

In the existing seven-block publication test, require these classes:

```python
expected = {
    "heading": ".content-block-heading",
    "rich_text": ".content-block-rich-text",
    "image_text": ".content-block-image-text",
    "metric": ".content-block-metric",
    "steps": ".content-block-steps",
    "download": ".content-block-download",
    "cta": ".content-block-cta",
}
for block_type, selector in expected.items():
    assert page.select_one(f'[data-content-block="{block_type}"]{selector}') is not None
```

- [ ] **Step 2: Run the detail RED suite**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_public_catalog.py tests/test_public_services.py tests/test_ui_foundations.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-red-007')
```

Expected: new decision-shell and content-block class assertions fail.

- [ ] **Step 3: Add the reusable detail primitives**

Create `detail_page.html`:

```jinja2
{% macro breadcrumb(back_href, back_label, current_label) -%}
<nav class="detail-breadcrumb" aria-label="面包屑">
  <a href="{{ back_href }}">{{ back_label }}</a>
  <span aria-hidden="true">/</span>
  <span aria-current="page">{{ current_label }}</span>
</nav>
{%- endmacro %}

{% macro detail_hero(title, summary, eyebrow='') -%}
<header class="detail-hero">
  <div class="public-container">
    {% if eyebrow %}<p class="public-eyebrow">{{ eyebrow }}</p>{% endif %}
    <h1>{{ title }}</h1>
    <p>{{ summary }}</p>
  </div>
</header>
{%- endmacro %}

{% macro decision_item(label, value) -%}
<div class="decision-item">
  <dt>{{ label }}</dt>
  <dd>{{ value }}</dd>
</div>
{%- endmacro %}
```

Use the macros in industry, scenario, and service detail templates. Each template must contain:

```html
<main id="main-content" class="public-page decision-detail">
  ...
  <div class="public-container decision-layout">
    <div class="decision-main">...</div>
    <aside class="decision-summary" aria-labelledby="decision-summary-title">
      <h2 id="decision-summary-title">决策摘要</h2>
      <dl>...</dl>
      <a class="btn btn-primary" href="/assessment">获取适配建议</a>
      <a class="btn btn-outline" href="...">返回...列表</a>
    </aside>
  </div>
</main>
```

Use only existing view-model fields. For an optional timeline or budget collection, render its validated values when present and the exact text `评估后确认` when absent. Do not infer ranges.

- [ ] **Step 4: Make content-block markup semantic and styleable**

Preserve every existing `data-content-block` hook and safe filter/URL decision. Add these exact classes:

```jinja2
<div data-content-block="rich_text" class="content-block content-block-rich-text">...</div>
<figure data-content-block="image_text" class="content-block content-block-image-text image-text-{{ block.settings.alignment }}">...</figure>
<div data-content-block="metric" class="content-block content-block-metric">...</div>
<section data-content-block="steps" class="content-block content-block-steps">...</section>
<p data-content-block="download" class="content-block content-block-download">...</p>
<p data-content-block="cta" class="content-block content-block-cta">...</p>
```

For heading blocks, place `.content-block-heading` on the emitted `h2`, `h3`, or `h4`. Keep `safe_html`, `media_image_url`, `media_download_url`, HTTPS `_blank`, and `noopener noreferrer` exactly as they are.

Add the decision layout and content-block rules:

```css
.detail-hero {
  padding-block: var(--ui-space-7);
  color: var(--ui-surface-000);
  background: var(--ui-navy-950);
}

.detail-hero p { max-width: 48rem; color: #e3ebf8; }

.decision-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(17rem, 1fr);
  gap: var(--ui-space-7);
  padding-block: var(--ui-space-7);
}

.decision-main { min-width: 0; max-width: 65ch; }

.decision-summary {
  position: sticky;
  top: 6rem;
  align-self: start;
  padding: var(--ui-space-5);
  border: 1px solid var(--ui-line-200);
  border-radius: var(--ui-radius-panel);
  background: var(--ui-surface-000);
}

.decision-item {
  display: grid;
  grid-template-columns: minmax(6rem, 0.8fr) minmax(0, 1.2fr);
  gap: var(--ui-space-3);
  padding-block: var(--ui-space-3);
  border-bottom: 1px solid var(--ui-line-200);
}

.content-block { margin-block: var(--ui-space-5); }
.content-block img { display: block; max-width: 100%; height: auto; }
.content-block-steps ol { counter-reset: ui-step; list-style: none; }
.content-block-steps li { position: relative; padding-left: 3rem; }
.content-block-steps li::before {
  position: absolute;
  left: 0;
  counter-increment: ui-step;
  content: counter(ui-step);
  color: var(--ui-blue-600);
  font-weight: 700;
}

@media (max-width: 767px) {
  .decision-layout { grid-template-columns: 1fr; }
  .decision-summary { position: static; grid-row: 1; }
  .decision-main { grid-row: 2; }
}
```

The numbered step is semantic text generated by CSS counters, not an illustrative asset. At `<768px`, the summary precedes the main content and is not sticky.

- [ ] **Step 5: Run security and publication regressions with the detail tests**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
& $py -m pytest tests/test_public_catalog.py tests/test_public_services.py tests/test_content_navigation.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-green-008')
```

Expected: PASS, including seven-block rendering, published-only dependencies, raw-text/NUL fail-closed, safe URLs, canonical, and no direct SQL in Blueprints.

- [ ] **Step 6: Review and commit Task 4**

```powershell
git diff --check -- templates/components/detail_page.html templates/components/content_blocks.html templates/industry_detail.html templates/scenario_detail.html templates/service_package_detail.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py
git add -- templates/components/detail_page.html templates/components/content_blocks.html templates/industry_detail.html templates/scenario_detail.html templates/service_package_detail.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py
git commit -m "feat: redesign the catalog decision pages"
```

Require fresh reviewer CLEAN and controller verification before Task 5.

---

### Task 5: Finish homepage and editorial public pages

**Files:**
- Modify: `templates/index.html`
- Modify: `templates/case_detail.html`
- Modify: `templates/resource_detail.html`
- Modify: `templates/announcement_detail.html`
- Modify: `templates/about.html`
- Modify: `templates/error.html`
- Modify: `static/css/public-pages.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_content_navigation.py`
- Modify: `tests/test_verified_cases.py`
- Modify: `tests/test_resources_announcements.py`
- Modify: `tests/test_smoke.py`

**Interfaces:**
- Consumes: Task 1—4 tokens, shell, cards, detail primitives, content-block renderer, and current home/content view models.
- Produces: approved editorial homepage rhythm; readable case/resource/announcement/about/error surfaces; no inline layout styles or emoji placeholders on these pages.

- [ ] **Step 1: Add failing public-surface quality assertions**

```python
@pytest.mark.parametrize(
    "path",
    ("/", "/about"),
)
def test_static_public_pages_use_named_main_and_no_inline_layout(client, path):
    page = _page(client.get(path))
    assert page.select_one("main#main-content") is not None
    assert not page.select("main [style]")


def test_home_preserves_real_content_sections_and_single_primary_action(client):
    page = _page(client.get("/"))
    assert page.select_one(".home-hero h1") is not None
    assert page.select_one('.home-hero a[href="/assessment"]') is not None
    assert page.select_one('[data-content-section="home-industries"]') is not None
    assert page.select_one('[data-content-section="home-scenarios"]') is not None
    assert "27+" not in page.get_text(" ", strip=True)


def test_error_page_uses_text_status_without_emoji(client):
    page = BeautifulSoup(client.get("/missing-page").get_data(as_text=True), "html.parser")
    assert page.select_one("main#main-content.ui-status-page") is not None
    assert "⚠️" not in page.get_text(" ", strip=True)
```

Extend the existing case/resource/announcement tests to assert `main#main-content.editorial-detail`, readable metadata classes, and unchanged verification/source/copyright/attachment/safe CTA content.

- [ ] **Step 2: Run the editorial RED suite**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-red-009')
```

Expected: new main/style/status assertions fail.

- [ ] **Step 3: Apply the approved editorial hierarchy**

Homepage:

- Keep the current headline, summary, sections, published-only collections, and existing routes.
- Use `.home-hero`, `.public-section`, `.public-section-header`, `.catalog-grid`, and one strong `/assessment` action.
- Keep “查看服务与交付” as a visually secondary link.
- Alternate white and `surface-050` only where it improves section grouping.
- Do not add counts, claims, testimonials, logos, icons, or unsupported outcomes.

Use this structure for the hero and each server-backed collection:

```jinja2
<main id="main-content" class="public-page public-home">
  <section class="home-hero">
    <div class="public-container home-hero-inner">
      <p class="public-eyebrow">企业 AI 转型平台</p>
      <h1>企业 AI 转型，从可验证的业务场景开始</h1>
      <p>用已审核、已发布的内容建立转型路径，再通过评估确认当前准备度。</p>
      <div class="ui-actions">
        <a href="/assessment" class="btn btn-primary">免费 AI 就绪度评估</a>
        <a href="/service-packages" class="btn btn-outline">查看服务与交付</a>
      </div>
    </div>
  </section>
  {% if industries %}
  <section class="public-section" data-content-section="home-industries">
    <div class="public-container">
      <header class="public-section-header"><h2>行业方案</h2><p>从已发布的行业路径开始。</p></header>
      <div class="catalog-grid">
        {% for item in industries %}{{ content_card(item, url_for('public_catalog.industry_detail', slug=item.slug), heading_level=3) }}{% endfor %}
      </div>
    </div>
  </section>
  {% endif %}
</main>
```

Case/resource/announcement:

- Use `main#main-content.editorial-detail` and `.public-reading`.
- Keep case verification label/time, metric evidence, resource authorship/source/copyright/attachment, announcement validity, and safe CTA behavior exactly intact.
- Present metadata as lightweight definition rows, not nested cards.

About/error:

- Replace inline layout styles with `.about-page`, `.about-principles`, and `.ui-status-page` classes.
- Preserve current verified company/contact text, but remove emoji and decorative pseudo-assets.
- Error pages show a text status label, title, recovery message, and “返回首页”.

- [ ] **Step 4: Add responsive editorial CSS**

Use these base rules, then add page-specific selectors only where the markup requires them:

```css
.home-hero {
  padding-block: clamp(4rem, 8vw, 7.5rem);
  background: var(--ui-surface-000);
}

.home-hero-inner { max-width: 58rem; }
.home-hero h1 { max-width: 18ch; font-size: clamp(2.5rem, 5vw, 4rem); }
.public-section--muted { background: var(--ui-surface-050); }
.editorial-detail { padding-block: var(--ui-space-7); }
.editorial-meta { display: grid; gap: var(--ui-space-2); }
.ui-status-page { min-height: 60vh; display: grid; place-items: center; text-align: center; }
.about-principles { display: grid; gap: var(--ui-space-4); }

@media (max-width: 767px) {
  .home-hero h1 { max-width: none; }
  .editorial-detail { padding-block: var(--ui-space-6); }
}
```

Use a maximum reading width, clear section rhythm, evidence rows, and mobile-safe long text. Do not hide or line-clamp legal, source, metric, or error text.

- [ ] **Step 5: Run the complete public-page partition**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py tests/test_pagination.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-green-010')
node --test tests/js/app_runtime.test.js tests/js/analytics_runtime.test.js
```

Expected: all selected Python and Node tests PASS.

- [ ] **Step 6: Review and commit Task 5**

```powershell
git diff --check -- templates/index.html templates/case_detail.html templates/resource_detail.html templates/announcement_detail.html templates/about.html templates/error.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py
git add -- templates/index.html templates/case_detail.html templates/resource_detail.html templates/announcement_detail.html templates/about.html templates/error.html static/css/public-pages.css tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py
git commit -m "feat: complete the public editorial UI"
```

Require a fresh reviewer CLEAN before Task 6.

---

### Task 6: Produce local visual, responsive, and accessibility evidence

**Files:**
- Create: `docs/testing/ui-foundations-public-catalog.md`
- Create: `docs/testing/evidence/ui-public/home-desktop.png`
- Create: `docs/testing/evidence/ui-public/scenarios-desktop.png`
- Create: `docs/testing/evidence/ui-public/scenario-detail-desktop.png`
- Create: `docs/testing/evidence/ui-public/scenario-detail-mobile.png`
- Create: `docs/testing/evidence/ui-public/resource-detail-mobile.png`
- Modify: `.superpowers/sdd/2026-08-26-ui-foundations-public-catalog/progress.md` (ignored control file; do not stage unless project policy changes)

**Interfaces:**
- Consumes: reviewed Task 1—5 implementation, existing disposable seed/fixture approach, approved 1440×1024 visual baseline, and the in-app local Browser.
- Produces: reproducible local startup instructions, viewport evidence, screenshot hashes, overflow/focus observations, and an explicit keyboard-verification status.

- [ ] **Step 1: Freeze the reviewed public UI source**

Record:

```powershell
git rev-parse HEAD
git status --short
git diff --check HEAD~5..HEAD
node --check static/js/app.js
```

The status may show preserved Task 12 files, but no uncommitted Task 1—5 file is allowed.

- [ ] **Step 2: Run the final scoped automated verification for this plan**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-26-ui-foundations-public-catalog\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py tests/test_pagination.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task6-final-scoped-011')
node --test tests/js/app_runtime.test.js tests/js/analytics_runtime.test.js
```

Record exact commands, interpreter version, `PYTHONPATH`, dependency versions, summaries, duration, and exit codes in `docs/testing/ui-foundations-public-catalog.md`. Do not run the full suite.

- [ ] **Step 3: Start a disposable local fixture**

Use a temporary SQLite database and media directory, bind only `127.0.0.1`, and select a free local port. Record the startup command and process ID. Do not use production data or external URLs.

- [ ] **Step 4: Capture and inspect the five required screenshots**

Use the in-app Browser at these exact viewports:

- homepage: 1440×1024;
- scenario list: 1440×1024;
- scenario detail: 1440×1024;
- same scenario detail: 390×844;
- resource detail: 390×844.

Inspect each image for header wrapping, content hierarchy, long text wrapping, sticky summary collision, clipped actions, page-level horizontal overflow, and visible focus styling. Compare the scenario desktop screenshot with `docs/design/evidence/2026-08-26-ui-visual-baseline.png` at the same viewport and record visible deviations.

- [ ] **Step 5: Verify real interactions and state truthfully**

Exercise the mobile menu, list filters, pagination, CTA routes, safe resource link, and one empty state. Attempt Tab, Shift+Tab, Enter, Space, and Escape through the real Browser input surface.

If the Browser backend does not produce native default keyboard behavior, record `NOT PROVEN`; do not substitute HTTP, Node, mouse, scripted focus, or DOM mutation. That limitation blocks this plan's completion gate but does not erase the reviewed HTTP/Node results.

- [ ] **Step 6: Stop the local listener and verify cleanup**

Stop the exact fixture process and its children. Confirm the chosen port no longer listens. Preserve the disposable evidence database only if the document identifies it as local test evidence; otherwise remove only that exact verified temporary path.

- [ ] **Step 7: Hash evidence, review, and commit Task 6**

Record dimensions and SHA-256 for all screenshots. Run:

```powershell
git diff --check
git status --short
```

```powershell
git add -- docs/testing/ui-foundations-public-catalog.md docs/testing/evidence/ui-public/home-desktop.png docs/testing/evidence/ui-public/scenarios-desktop.png docs/testing/evidence/ui-public/scenario-detail-desktop.png docs/testing/evidence/ui-public/scenario-detail-mobile.png docs/testing/evidence/ui-public/resource-detail-mobile.png
git commit -m "docs: verify the public UI redesign"
```

Dispatch one new independent reviewer over the full UI plan commit range. Fix only reviewer P0—P2 findings with RED→GREEN cycles. After reviewer CLEAN and controller-focused verification, mark the plan complete only if native keyboard evidence is also PASS. If it remains `NOT PROVEN`, stop at the blocked evidence checkpoint; do not deploy and do not start assessment/report UI.

## Plan Completion Gate

This plan is complete only when all six task commits exist, every task-level reviewer is CLEAN, the final scoped reviewer is CLEAN, the controller reruns the frozen public partition and Node tests, and native Tab/Shift+Tab/Enter/Space/Escape behavior has fresh PASS evidence. A `NOT PROVEN` keyboard result keeps the plan blocked. Completion of this plan means only “shared foundation and public UI complete”; it does not mean assessment/report UI, admin UI, all product functions, final full regression, or production deployment is complete.
