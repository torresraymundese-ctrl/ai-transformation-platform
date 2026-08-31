# Silver Evidence Public UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild every public website surface into the approved silver-gray evidence system while preserving all existing published-data, assessment, security, and routing contracts.

**Architecture:** Keep Flask routes, repositories, view models, database schema, publishing state machines, and assessment behavior unchanged. Add a shared silver-evidence presentation layer and four semantic page families, then progressively enhance only visual reveal behavior with dependency-free JavaScript; each page remains complete without JavaScript. Generate four project-local bitmap assets from the two approved visual references and consume them as decorative media, never as text-bearing page screenshots.

**Tech Stack:** Flask, Jinja2, semantic HTML, local CSS, dependency-free JavaScript, Pillow already available in the assigned offline environment, pytest, BeautifulSoup, Node `node:test`, built-in ImageGen, and the Codex in-app Browser.

**Spec:** `docs/superpowers/specs/2026-08-31-silver-evidence-public-ui-design.md`

## Global Constraints

- Work only in `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.worktrees\core-assessment-report` on branch `codex/ai-platform-2.0-core`; it is already a linked worktree, so do not create another.
- Preserve exactly these unrelated Task 12 paths: `README.md`, `blueprints/admin/catalog.py`, `catalog_content_repository.py`, `docs/deployment/security-and-service.md`, `templates/admin/catalog_edit.html`, `tests/test_catalog_content_admin.py`, `docs/testing/content-catalog.md`, `docs/testing/evidence/content-admin-publish.png`, `docs/testing/evidence/content-case-resource.png`, `docs/testing/evidence/content-industry-desktop.png`, `docs/testing/evidence/content-keyboard.png`, `docs/testing/evidence/content-scenario-mobile.png`, and `tests/test_content_journey.py`.
- Every commit and review package uses exact pathspecs; never stage or modify the preserved Task 12 paths.
- Do not modify `blueprints/admin/*`, `templates/admin/*`, repositories, database migrations, schema, publishing, assessment APIs, matching, reporting, source checking, media security, or analytics behavior.
- Use only the assigned interpreter `D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe` and command-scoped offline dependencies from `.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps`; do not install or update packages.
- Every pytest command uses `-p no:cacheprovider` and a unique `--basetemp` under `.superpowers\sdd\2026-08-31-silver-evidence-public-ui\test-tmp`.
- All generated or edited production images must be copied into `static/images/ui/`, converted locally to single-frame sRGB WebP, stripped of metadata, visually inspected, and bounded by the exact dimensions/bytes in Task 1.
- Never use the two full-page reference PNGs as webpage backgrounds or production content. They are visual evidence only.
- Do not add remote fonts, scripts, images, runtime network calls, videos, carousels, particles, wheel interception, inline SVG, handcrafted SVG, emoji icons, CSS art, or placeholder boxes.
- Public data continues to come only from existing published view models. Do not introduce customer names, logos, claims, metrics, durations, budgets, or outcomes not present in the view model; every simulated value remains adjacent to `演示数据`.
- Local preview binds only `127.0.0.1`. Do not deploy, expose a public listener, access the real external network, or touch production server, Nginx, systemd, production database, or customer data.
- This plan must not run the repository-wide full suite. The final scoped responsibility set is named in Task 6; Stage 5A Task 12, Stage 5B, the final full suite, and deployment remain separate gates.

---

### Task 1: Establish silver-evidence assets, typography tokens, and homepage image truth

**Files:**
- Create: `static/images/ui/home-ai-core-silver.webp`
- Create: `static/images/ui/public-industry-operations.webp`
- Create: `static/images/ui/public-delivery-system.webp`
- Create: `static/images/ui/public-trust-evidence.webp`
- Modify: `static/css/design-tokens.css`
- Modify: `static/css/dark-evidence-home.css`
- Modify: `templates/index.html`
- Modify: `tests/test_ui_foundations.py`

**Interfaces:**
- Consumes: `docs/design/references/2026-08-31-silver-evidence-homepage-reference.png`, `docs/design/references/2026-08-31-silver-evidence-detail-reference.png`, existing `home-ai-core.webp`, existing local logo, and the current five homepage chapter hooks.
- Produces: four local WebPs and the typography/color/image contract consumed by Tasks 2—6. The homepage hero URL becomes `/static/images/ui/home-ai-core-silver.webp`; no later task may rename these four asset URLs.

- [ ] **Step 1: Write the failing rendered asset and homepage contract**

Add `test_silver_evidence_assets_are_local_decodable_and_bound_to_public_surfaces` to `tests/test_ui_foundations.py`. Request `/` and assert the hero uses the new local URL with `alt=""`, `width="1920"`, `height="1080"`, and `fetchpriority="high"`. For each expected file, open it with Pillow and assert one frame, `WEBP`, sRGB/RGB output, exact dimensions, and byte limit:

```python
expected = {
    "home-ai-core-silver.webp": (1920, 1080, 350_000),
    "public-industry-operations.webp": (1920, 1080, 400_000),
    "public-delivery-system.webp": (1600, 900, 340_000),
    "public-trust-evidence.webp": (1600, 900, 340_000),
}
```

The same test must assert the homepage stylesheet contains no `invert(` or `hue-rotate(` and that the hero image rule does not reduce `brightness()` below `0.9`. This catches the current production defect: a light source image is globally inverted and darkened until the silver hand becomes a black silhouette.

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-31-silver-evidence-public-ui\test-tmp'
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
& $py -m pytest tests/test_ui_foundations.py::test_silver_evidence_assets_are_local_decodable_and_bound_to_public_surfaces -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-red-001')
```

Expected: FAIL because the new asset URLs/files do not exist and the current CSS contains whole-image inversion.

- [ ] **Step 3: Generate the four source images with the built-in ImageGen tool**

Use the imagegen skill and built-in tool. Inspect every input and output. Use one call per asset and preserve these prompts in the Task 1 report:

```text
home-ai-core-silver — edit the inspected current hand image. Wide enterprise website hero. Replace the pale background with near-black graphite and deep blue-black atmosphere; keep the same right-weighted robotic hand and transparent orb composition; render the hand in clearly visible brushed silver and pearl-gray metal with crisp rim highlights; keep the left 48% quiet for live HTML copy. Single restrained electric-blue light inside the orb. Photoreal industrial product visualization. No text, logo, watermark, UI, particles, gradient bands, or extra objects.

public-industry-operations — new photoreal industrial website image. Bright, clean advanced manufacturing floor with one engineer using a workstation beside automated equipment; silver-gray machinery, cool neutral overhead light, restrained electric-blue interface reflections, realistic Chinese industrial context without readable signage. Subject and machinery weighted to the right half with clean negative space on the left. No text, logo, watermark, holographic words, or science-fiction costume.

public-delivery-system — new photoreal enterprise technology image. A refined AI delivery control environment combining an orderly server/integration room and a glass operations console, silver metal, warm-gray architectural surfaces, restrained blue status lights, bright enough to read physical detail. Wide landscape composition, focal system on the right, no people required. No text, logo, watermark, neon tunnel, or floating UI labels.

public-trust-evidence — new photoreal enterprise evidence image. Precision quality-inspection and governance workspace with a measured industrial component, optical inspection equipment, structured documentation trays and a monitor glow without readable text; silver, graphite, warm gray and one restrained electric blue. Wide landscape, clean editorial composition. No text, logo, watermark, fake metrics, or dramatic cyberpunk lighting.
```

Copy the accepted outputs from the generated-images directory to plan-owned scratch, then use Pillow already present in the assigned environment to center-crop/resize with `Image.Resampling.LANCZOS`, convert to sRGB/RGB, strip metadata, and save the exact WebPs under `static/images/ui/` within the byte limits. Do not overwrite the existing source asset.

- [ ] **Step 4: Implement the minimal token and homepage changes**

Extend `design-tokens.css` with the exact spec colors and local font stacks under `:root`. Change only the homepage hero `<img>` URL to `home-ai-core-silver.webp`. Remove whole-image inversion/hue rotation from the three homepage image rules; use background/container masks for contrast and keep image `filter: brightness(0.9)` or brighter. Preserve all five story IDs, published-content loops, routes, and current JavaScript hooks.

- [ ] **Step 5: Run GREEN and inspect all images**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_silver_evidence_assets_are_local_decodable_and_bound_to_public_surfaces tests/test_ui_foundations.py::test_home_dark_evidence_assets_are_local_decodable_and_bounded -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task1-green-002')
node --check static/js/guided_story.js
git diff --check -- static/css/design-tokens.css static/css/dark-evidence-home.css templates/index.html tests/test_ui_foundations.py
```

Open all four WebPs with the local image viewer. Reject an asset if the primary subject is muddy, cropped, overexposed, contains text/watermarks, or contradicts the binding silver-gray palette.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- static/images/ui/home-ai-core-silver.webp static/images/ui/public-industry-operations.webp static/images/ui/public-delivery-system.webp static/images/ui/public-trust-evidence.webp static/css/design-tokens.css static/css/dark-evidence-home.css templates/index.html tests/test_ui_foundations.py
git commit -m "feat: establish the silver evidence visual assets"
```

---

### Task 2: Build the unified public shell and progressive reveal layer

**Files:**
- Create: `static/css/silver-evidence-public.css`
- Create: `static/js/public_reveal.js`
- Create: `tests/js/public_reveal_runtime.test.js`
- Modify: `templates/base.html`
- Modify: `templates/components/navigation.html`
- Modify: `templates/components/footer.html`
- Modify: `templates/components/sticky_cta.html`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_content_navigation.py`

**Interfaces:**
- Consumes: Task 1 tokens/assets and the existing mobile-navigation API in `static/js/app.js`.
- Produces: body class `public-shell`, navigation marker `data-public-navigation="silver-evidence"`, stylesheet `/static/css/silver-evidence-public.css`, script `/static/js/public_reveal.js`, and optional `data-public-reveal` hooks consumed by later page tasks.

- [ ] **Step 1: Write failing shell and runtime tests**

Add rendered HTTP assertions that every representative public route loads `silver-evidence-public.css` after `public-pages.css`, has exactly one header navigation layer, no visible standalone `.site-signal`, a dark navigation marker, a named main landmark, and the existing route matrix/CTA labels. Assert the footer has the company, service, resource, and about groups without inline styles.

In `tests/js/public_reveal_runtime.test.js`, exercise the real exported initializer against a small fake DOM. Assert:

```javascript
// No IntersectionObserver: content remains visible and no enhanced class is set.
// Observer available: only [data-public-reveal] nodes are observed.
// Intersecting entry gains data-reveal-state="visible" and is unobserved.
// prefers-reduced-motion: all reveal nodes become visible without an observer.
// No wheel, touchmove, scroll-jacking handler, or preventDefault path is installed.
```

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_public_shell_uses_one_silver_evidence_navigation_layer tests/test_content_navigation.py::test_navigation_matches_confirmed_information_architecture -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-red-003')
node --test tests/js/public_reveal_runtime.test.js
```

Expected: the new shell test and Node file fail because the stylesheet, marker, and runtime do not exist; the existing navigation test remains the known behavioral baseline.

- [ ] **Step 3: Implement the semantic shell**

Load the new stylesheet after `public-pages.css` and the new script before `app.js`. Give the base body the permanent `public-shell` class while preserving each route's existing `body_class`. Remove the separate signal bar from rendered public pages and keep its truthful sentence as visually secondary navigation copy only if it fits without adding a second header row. Preserve the exact desktop/mobile link destinations, active-state logic, analytics attributes, logo, phone, WeChat, ICP link, and no-inline-style contract.

The shell CSS implements the exact near-black navigation, 1280px alignment, compact text navigation, one blue active marker, dark editorial footer, `44×44px` targets, visible focus, and mobile single/two-column footer. It must not globally force homepage-specific chapter layout onto inner pages.

- [ ] **Step 4: Implement progressive reveal without hiding the no-JS document**

Export `initializePublicReveal(pageDocument, pageWindow)` in CommonJS and browser branches. JavaScript may add an enhancement marker only after it confirms all required APIs. CSS applies opacity/translate only beneath that marker; unenhanced markup remains visible. Reduced motion immediately exposes every target. Do not register wheel/touchmove handlers or call `preventDefault()`.

- [ ] **Step 5: Run GREEN**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_content_navigation.py::test_navigation_matches_confirmed_information_architecture tests/test_content_navigation.py::test_mobile_navigation_is_native_keyboard_operable tests/test_smoke.py::test_shared_home_navigation_and_footer_use_the_confirmed_catalog_routes -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task2-green-004')
node --check static/js/app.js
node --check static/js/public_reveal.js
node --test tests/js/app_runtime.test.js tests/js/public_reveal_runtime.test.js
git diff --check -- static/css/silver-evidence-public.css static/js/public_reveal.js templates/base.html templates/components/navigation.html templates/components/footer.html templates/components/sticky_cta.html tests/test_ui_foundations.py tests/test_content_navigation.py tests/js/public_reveal_runtime.test.js
```

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- static/css/silver-evidence-public.css static/js/public_reveal.js tests/js/public_reveal_runtime.test.js templates/base.html templates/components/navigation.html templates/components/footer.html templates/components/sticky_cta.html tests/test_ui_foundations.py tests/test_content_navigation.py
git commit -m "feat: unify the silver evidence public shell"
```

---

### Task 3: Recompose all catalog and list pages as editorial result systems

**Files:**
- Modify: `templates/components/public_catalog.html`
- Modify: `templates/components/content_card.html`
- Modify: `templates/industries.html`
- Modify: `templates/scenarios.html`
- Modify: `templates/service_packages.html`
- Modify: `templates/cases.html`
- Modify: `templates/resources.html`
- Modify: `static/css/silver-evidence-public.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_public_services.py`
- Modify: `tests/test_verified_cases.py`
- Modify: `tests/test_resources_announcements.py`

**Interfaces:**
- Consumes: Task 2 shell/reveal hooks and Task 1 asset URLs.
- Produces: `data-page-family="catalog"`, `data-catalog-layout="editorial"`, numbered result rows, compact filter workspaces, and visual page headers shared by the five current public catalog routes. Task 4 reuses only the page header and reveal primitives, not list-specific markup.

- [ ] **Step 1: Add failing rendered catalog-family tests**

Add parameterized HTTP tests across `/industries`, `/scenarios`, `/service-packages`, `/cases`, and `/resources` that assert:

```python
assert main["data-page-family"] == "catalog"
assert main.select_one('[data-catalog-layout="editorial"]') is not None
assert main.select_one(".public-page-header__copy h1") is not None
assert main.select_one('img[src^="/static/images/ui/"]') is not None
assert not main.select('[style]')
```

For populated fixtures require each result to have a real heading link, summary, sequence label, and page-appropriate metadata. For a one-item case/resource fixture require the result container to use the same full-width editorial row contract rather than a three-column card grid. Preserve the real scenario filter fields, selected values, result count, clear URL, pagination query, empty state, canonicals, analytics privacy, and all current route destinations.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_silver_evidence_catalog_families_use_editorial_rows tests/test_public_catalog.py::test_scenario_catalog_uses_signal_panel_and_editorial_rows tests/test_resources_announcements.py::test_resource_empty_states_keep_the_filtered_reset_route -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-red-005')
```

Expected: the new family contract fails because current industry/service/case/resource pages still render homogeneous card grids and the shared page header has no visual composition.

- [ ] **Step 3: Extend the shared page-header and result-row macros**

Extend `page_header` with explicit optional values `section_code`, `art_url`, and `art_position`; emit a dark semantic header with a copy column and decorative local image only when `art_url` is present. Extend `content_card` with explicit `sequence_label` and `layout` arguments; keep the existing title/summary/metadata/data contracts and real anchor. Do not derive fake numbers from loop length or content values.

- [ ] **Step 4: Recompose each list with page-specific information hierarchy**

- Industries: large indexed directions with department/priority context; use `public-industry-operations.webp`.
- Scenarios: retain the compact four-field filter workspace and render results as information-rich editorial rows; use `public-industry-operations.webp`.
- Services: group visually by existing `category` labels without changing ordering or pagination; use `public-delivery-system.webp`.
- Cases: make verification status the lead metadata and allow one case to occupy the editorial width; use `public-trust-evidence.webp`.
- Resources: keep the exact type filter and make resource type/source-review framing visible; use `public-trust-evidence.webp`.

The CTA after each catalog becomes one deliberate end action, not a detached paragraph. No new public announcement list route is created.

- [ ] **Step 5: Run GREEN and the list responsibility set**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py::test_public_catalog_lists_use_the_shared_shell_and_private_analytics tests/test_public_catalog.py::test_scenario_filters_are_intersection_not_union tests/test_public_catalog.py::test_scenario_catalog_uses_signal_panel_and_editorial_rows tests/test_public_services.py::test_service_list_uses_page_contract_shell_canonical_and_compatibility_redirect tests/test_verified_cases.py::test_case_cutover_has_single_v2_owner_and_an_honest_empty_state tests/test_resources_announcements.py::test_resource_empty_states_keep_the_filtered_reset_route -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task3-green-006')
git diff --check -- templates/components/public_catalog.html templates/components/content_card.html templates/industries.html templates/scenarios.html templates/service_packages.html templates/cases.html templates/resources.html static/css/silver-evidence-public.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py
```

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- templates/components/public_catalog.html templates/components/content_card.html templates/industries.html templates/scenarios.html templates/service_packages.html templates/cases.html templates/resources.html static/css/silver-evidence-public.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py
git commit -m "feat: recompose the public catalogs as editorial rows"
```

---

### Task 4: Build the five-chapter decision-detail system and seven safe block presentations

**Files:**
- Modify: `templates/components/detail_page.html`
- Modify: `templates/components/content_blocks.html`
- Modify: `templates/industry_detail.html`
- Modify: `templates/scenario_detail.html`
- Modify: `templates/service_package_detail.html`
- Modify: `static/css/silver-evidence-public.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_public_catalog.py`
- Modify: `tests/test_public_services.py`

**Interfaces:**
- Consumes: Task 1 industry/delivery assets, Task 2 reveal primitives, and all existing safe public view-model fields.
- Produces: `data-page-family="decision-detail"`, split cover, `data-detail-facts`, exactly five top-level numbered chapters per decision page, one final action panel, and distinct visual hooks for all seven existing safe content-block types.

- [ ] **Step 1: Write failing five-chapter and safe-block rendering tests**

For one published industry, scenario, and service detail, require one split cover containing live title/summary and one decorative local image, one fact strip, exactly five top-level `[data-decision-chapter]` elements with visible `01—05` sequence labels, and exactly one final primary assessment action. Assert `.decision-summary` is absent so facts and CTAs cannot be duplicated in a white sidebar.

Update the intentional old three-chapter/summary expectations in `tests/test_public_catalog.py` and `tests/test_ui_foundations.py` to the approved five-chapter contract while retaining assertions for every required section, timeline/budget formatting, published-only relations, and exact CTA accessible names. Add one HTTP test that formally publishes all seven block types and asserts their existing `data-content-block` names render inside the new block layout without changing sanitized HTML, safe external-link attributes, or media URLs.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_public_catalog.py::test_decision_details_use_split_cover_fact_strip_and_five_chapters tests/test_ui_foundations.py::test_decision_detail_css_numbers_primary_chapters tests/test_public_catalog.py::test_formally_published_governed_block_types_render_through_safe_public_http -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-red-007')
```

Expected: the new five-chapter/split-cover contract fails while the existing seven-block safety test remains the behavioral baseline.

- [ ] **Step 3: Implement shared decision-detail primitives**

Extend `detail_hero` with explicit `image_url` and `image_alt` arguments and render live HTML title/summary separately from the image. Add a shared fact-strip macro or call-block that accepts only caller-rendered existing fields. Implement the dark-left/bright-right cover, horizontal fact strip, alternating warm-white/dark chapters, large numeric chapter labels, non-card implementation path, aligned metric rows, governance table, and one terminal action panel.

- [ ] **Step 4: Recompose the three detail families without changing data sources**

- Scenario chapters: problem boundary; implementation path; measurable indicators; risk and governance; matching services/resources/action.
- Industry chapters: industry judgment; business pains; priority scenarios; implementation path/services; related evidence/action.
- Service chapters: service positioning; applicable conditions; delivery scope and deliverables; implementation/timeline/budget/acceptance; related content/support/action.

Keep every existing `data-content-section`, `data-service-section`, relation link, formatted value, fallback, and SEO/canonical output that current tests consume. Only the top-level visual grouping changes.

- [ ] **Step 5: Style all seven content blocks as distinct safe presentations**

Retain the exact conditional branches in `content_blocks.html`; add semantic wrapper classes/data only where needed. Heading, rich text, image-text, metric, steps, download, and CTA must each remain identifiable and use the presentation table in the spec. Do not alter `safe_html`, URL logic, target/rel attributes, or media helper calls.

- [ ] **Step 6: Run GREEN and decision responsibility tests**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py::test_catalog_details_keep_verified_theme_context_and_numbered_sections tests/test_public_catalog.py::test_decision_details_use_split_cover_fact_strip_and_five_chapters tests/test_public_catalog.py::test_published_detail_has_sections_seo_canonical_and_no_internal_leaks tests/test_public_catalog.py::test_formally_published_governed_block_types_render_through_safe_public_http tests/test_public_services.py::test_every_public_service_detail_has_complete_delivery_structure_and_ctas tests/test_public_services.py::test_service_detail_formats_budget_weeks_fixed_labels_and_no_raw_values tests/test_public_services.py::test_delivery_authority_fields_and_optional_relations_render_without_placeholders -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task4-green-008')
git diff --check -- templates/components/detail_page.html templates/components/content_blocks.html templates/industry_detail.html templates/scenario_detail.html templates/service_package_detail.html static/css/silver-evidence-public.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py
```

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- templates/components/detail_page.html templates/components/content_blocks.html templates/industry_detail.html templates/scenario_detail.html templates/service_package_detail.html static/css/silver-evidence-public.css tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py
git commit -m "feat: build the silver evidence decision details"
```

---

### Task 5: Refine editorial, trust, assessment, about, and status pages

**Files:**
- Modify: `templates/case_detail.html`
- Modify: `templates/resource_detail.html`
- Modify: `templates/announcement_detail.html`
- Modify: `templates/about.html`
- Modify: `templates/error.html`
- Modify: `templates/assessment.html`
- Modify: `static/css/silver-evidence-public.css`
- Modify: `static/css/assessment.css`
- Modify: `tests/test_ui_foundations.py`
- Modify: `tests/test_verified_cases.py`
- Modify: `tests/test_resources_announcements.py`
- Modify: `tests/test_assessment_wizard.py`
- Modify: `tests/test_smoke.py`

**Interfaces:**
- Consumes: Tasks 1—2 shared assets/shell/reveal and the existing case/resource/announcement/assessment contracts.
- Produces: `data-page-family="editorial"`, evidence-article, review-dossier, dynamic-article, manifesto, assessment-conversion, and status-page presentations. Task 6 captures these exact markers.

- [ ] **Step 1: Add failing editorial and assessment visual-contract tests**

Add parameterized HTTP tests requiring:

- case detail: evidence-article marker, live verification metadata, metric evidence rows, and published blocks;
- resource detail: review-dossier marker, source/copyright/attachment metadata and safe links;
- announcement detail: dynamic-article marker, exact validity and CTA safety;
- about: manifesto marker and four semantic chapters using existing truthful copy;
- error: status-page marker, one heading and one recovery action with correct HTTP status;
- assessment: assessment-conversion marker while preserving all existing wizard IDs, data URLs, progress, error/live regions, form controls, consent, and scripts.

Assert no inline style, emoji icon, external image/font/script URL, duplicate H1, or additional form field appears.

- [ ] **Step 2: Run RED**

```powershell
& $py -m pytest tests/test_ui_foundations.py::test_silver_evidence_editorial_and_conversion_families_keep_live_contracts tests/test_assessment_wizard.py::test_assessment_page_loads_external_v2_wizard_assets tests/test_smoke.py::test_missing_public_page_keeps_its_404_status_and_text_only_recovery -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-red-009')
```

Expected: the new page-family markers/compositions fail; the existing assessment and error behaviors remain the baseline.

- [ ] **Step 3: Implement the editorial and trust pages**

Use live text and existing metadata only. Compose case metrics as large evidence rows, resource provenance as a review dossier, announcement validity as a compact publication band, and about content as four large editorial chapters. Reuse `public-trust-evidence.webp` and `public-delivery-system.webp` decoratively; do not put facts inside bitmaps. Keep every current data attribute and safe URL behavior.

- [ ] **Step 4: Restyle the assessment without changing its state machine**

Keep `assessment.html` IDs, data attributes, form names, labels, aria relationships, required flags, privacy text, and script unchanged. Use a dark introduction, warm-white work surface, editorial progress rail, large question title, full-row selection states, and distinct focus/selected/error/disabled states in `assessment.css`. Do not edit `assessment.js` unless a fresh failing behavior test proves a visual-state hook is impossible without it; if that occurs, ledger the ruling before changing scope.

- [ ] **Step 5: Run GREEN and the editorial/conversion responsibility set**

```powershell
& $py -m pytest tests/test_ui_foundations.py tests/test_verified_cases.py::test_authorized_case_publishes_metrics_and_never_leaks_private_evidence tests/test_resources_announcements.py::test_sourced_resource_requires_fresh_exact_source_check_and_renders_safe_link tests/test_resources_announcements.py::test_external_cta_is_safe_and_internal_cta_stays_same_window tests/test_resources_announcements.py::test_announcement_fixed_interval_current_future_expired_and_archived_are_exact tests/test_assessment_wizard.py tests/test_smoke.py::test_missing_public_page_keeps_its_404_status_and_text_only_recovery -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task5-green-010')
node --check static/js/assessment.js
node --test tests/js/assessment_runtime.test.js
git diff --check -- templates/case_detail.html templates/resource_detail.html templates/announcement_detail.html templates/about.html templates/error.html templates/assessment.html static/css/silver-evidence-public.css static/css/assessment.css tests/test_ui_foundations.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_assessment_wizard.py tests/test_smoke.py
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add -- templates/case_detail.html templates/resource_detail.html templates/announcement_detail.html templates/about.html templates/error.html templates/assessment.html static/css/silver-evidence-public.css static/css/assessment.css tests/test_ui_foundations.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_assessment_wizard.py tests/test_smoke.py
git commit -m "feat: refine the public editorial and assessment pages"
```

---

### Task 6: Run blocking multi-route design QA and prepare the final review gate

**Files:**
- Modify: `design-qa.md`
- Create: `docs/testing/silver-evidence-public-ui.md`
- Create: `docs/design/evidence/2026-08-31-silver-home-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-industries-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-industry-detail-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-scenarios-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-scenario-detail-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-services-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-service-detail-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-cases-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-case-detail-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-resources-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-resource-detail-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-assessment-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-about-desktop.png`
- Create: `docs/design/evidence/2026-08-31-silver-scenarios-mobile.png`
- Create: `docs/design/evidence/2026-08-31-silver-scenario-detail-mobile.png`
- Create: `docs/design/evidence/2026-08-31-silver-assessment-mobile.png`
- Modify: `.superpowers/sdd/2026-08-31-silver-evidence-public-ui/progress.md` (ignored control file)

**Interfaces:**
- Consumes: independently reviewed Tasks 1—5, the two exact binding reference PNGs, a deterministic disposable database/media fixture, and the Codex in-app Browser.
- Produces: fresh scoped automation, sixteen accepted screenshots, same-input reference comparisons, interaction/accessibility truth, `design-qa.md` ending in `final result: passed` or `final result: blocked`, a review-ready evidence commit, and a frozen complete-plan review package.

- [ ] **Step 1: Freeze implementation and run the complete scoped responsibility set**

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-31-silver-evidence-public-ui\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_assessment_wizard.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task6-final-scoped-011')
node --check static/js/app.js
node --check static/js/guided_story.js
node --check static/js/public_reveal.js
node --check static/js/assessment.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/public_reveal_runtime.test.js tests/js/assessment_runtime.test.js tests/js/analytics_runtime.test.js
```

Do not run the repository-wide full suite.

- [ ] **Step 2: Start a deterministic disposable local fixture**

Reuse or extend the plan-owned browser fixture under `.superpowers/sdd/2026-08-31-silver-evidence-public-ui/`. Create a fresh SQLite database and media root below that ignored workspace, seed deterministic published content only, use mock transport for every source check, and bind a free port on `127.0.0.1`. Record database/media paths, command, launcher/listener PIDs, port, Python version, `PYTHONPATH`, dependency versions, and HTTP 200 checks for all capture routes. Never use the real network or production state.

- [ ] **Step 3: Capture and inspect the sixteen exact screenshots**

Use the Codex in-app Browser. Capture the thirteen desktop surfaces named above at `1440×1024`, plus scenarios, scenario detail, and assessment at `390×844`. For long pages, save true PNG full-page evidence that covers the footer; keep a viewport crop for same-viewport comparison. Before accepting each image, inspect it and reject wrong routes, loading states, blank/cropped output, obscured controls, illegible imagery, duplicate navigation, or missing footer.

- [ ] **Step 4: Run blocking same-input visual comparisons**

Compare `2026-08-31-silver-evidence-homepage-reference.png` and the fresh homepage viewport in one input. Compare `2026-08-31-silver-evidence-detail-reference.png` and the fresh scenario-detail viewport in another input. Compare all five list pages together and all editorial/conversion pages together to enforce a coherent family without making them identical.

Inspect typography, silver subject brightness, image crop, near-black/warm-white balance, single blue accent, 1280px alignment, section spacing, line/radius discipline, fact strips, numbered chapters, filter density, one-item layout, content truth, mobile stacking, footer arrival, and absence of horizontal overflow. Record each difference with P0—P3 severity and exact route/viewport.

- [ ] **Step 5: Fix every P0/P1/P2 through fresh TDD and recapture**

Return each issue to the owning implementation task. Write a real failing HTTP/Node test when behavior or structural contracts can cover the defect, verify RED, implement the smallest fix, run GREEN, obtain a scoped independent re-review, and recapture only affected routes. Pure visual crop/spacing corrections must still receive same-viewport before/after evidence. Do not hand off with an open P0—P2. If capture/comparison is impossible, set the final line to `final result: blocked`.

- [ ] **Step 6: Exercise interactions and record native truth**

Exercise desktop/mobile navigation, all real catalog/detail/assessment links, scenario and resource filters, clear/reset, pagination when the fixture has more than one page, empty state, reverse/fast scroll, public reveal, image hover, assessment selection/back/continue/error, footer arrival, and external resource safety. Record native Tab/Shift+Tab/Enter/Space, reduced-motion, and 200% zoom as `PASS`, `FAIL`, or `NOT PROVEN`; never substitute Node, HTTP, mouse, or programmatic focus for native evidence.

- [ ] **Step 7: Clean up the exact fixture**

Stop the precise launcher/listener process tree, confirm its port has no listener and TCP fails, close/reset the Browser tab and viewport, and remove only plan-owned disposable database/media/raw-capture files. Preserve accepted evidence PNGs and logs. Do not use broad recursive deletion.

- [ ] **Step 8: Document and commit the QA evidence**

Write `docs/testing/silver-evidence-public-ui.md` with exact commands, summaries, exits, environment, image dimensions/SHA-256, asset sizes, route/viewport matrix, interaction results, limitations, and cleanup proof. Ensure root `design-qa.md` ends exactly `final result: passed` or `final result: blocked`.

```powershell
git diff --check
git status --short
git add -- design-qa.md docs/testing/silver-evidence-public-ui.md docs/design/evidence/2026-08-31-silver-home-desktop.png docs/design/evidence/2026-08-31-silver-industries-desktop.png docs/design/evidence/2026-08-31-silver-industry-detail-desktop.png docs/design/evidence/2026-08-31-silver-scenarios-desktop.png docs/design/evidence/2026-08-31-silver-scenario-detail-desktop.png docs/design/evidence/2026-08-31-silver-services-desktop.png docs/design/evidence/2026-08-31-silver-service-detail-desktop.png docs/design/evidence/2026-08-31-silver-cases-desktop.png docs/design/evidence/2026-08-31-silver-case-detail-desktop.png docs/design/evidence/2026-08-31-silver-resources-desktop.png docs/design/evidence/2026-08-31-silver-resource-detail-desktop.png docs/design/evidence/2026-08-31-silver-assessment-desktop.png docs/design/evidence/2026-08-31-silver-about-desktop.png docs/design/evidence/2026-08-31-silver-scenarios-mobile.png docs/design/evidence/2026-08-31-silver-scenario-detail-mobile.png docs/design/evidence/2026-08-31-silver-assessment-mobile.png
git commit -m "docs: verify the silver evidence public UI"
```

- [ ] **Step 9: Run final independent review and stop for user acceptance**

Generate one complete-plan review package from this plan's base through Task 6 HEAD. Dispatch a fresh high-judgment reviewer with the spec, plan, ledger, all task reports, exact package path, binding reference images, and global constraints. Fix only scoped P0—P2 through one final fix dispatch and scoped re-review, then run controller-focused verification. Stop at the user visual-acceptance gate with the local preview open; do not begin admin UI, Stage 5B, the repository-wide full suite, or deployment.

## Plan Completion Gate

This plan is complete only when Tasks 1—6 each have a task-scoped independent review, the whole-plan reviewer is clean, the Task 6 scoped Python/Node responsibility sets are fresh, all sixteen screenshots are accepted, both binding-reference comparisons have no P0—P2, `design-qa.md` ends `final result: passed`, the disposable fixture is stopped, and the preserved Task 12 paths remain outside every UI commit. Completion means only that the public UI is locally ready for user visual acceptance; it does not claim all platform functions, final full-suite verification, or production deployment are complete.
