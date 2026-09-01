# Silver Evidence public UI — blocking design QA

## Scope and gate

- Frozen plan base: `d5d8445f0ac1b4425db905062a63330e4764e165`.
- Bound inputs: the Silver Evidence public UI spec, exact homepage/detail reference PNGs, and deterministic published local content.
- Surface: Codex in-app Browser at desktop and mobile responsive states; no Chrome, Computer Use, Playwright CLI, production, network, deployment, admin/Task12, Stage 5B, or repository-wide full suite.
- Final evidence: sixteen inspected true-PNG evidence sheets covering each route through its footer.

## Blocking visual verdict

Homepage/detail reference pairs were inspected in same-input native-pixel comparisons. Five list pages, three decision-detail pages, and four editorial/conversion pages were also compared as families.

- The homepage retains the binding bright silver subject, near-black opening stage, warm-white hierarchy, one blue action, large editorial type, and disciplined lines/radii. Its larger local crop and intentional omission of a competing header CTA are accepted P3 distinctions.
- Scenario detail retains the binding split cover, truthful five-part fact strip, bright industrial subject, single-line 1440px title, five numbered chapters, restrained blue, and dark/light rhythm. Its local production image replaces the reference mock's augmented overlay without losing content truth.
- List pages share the same cover, 1280px alignment, editorial rows, filter language, thin rules, and action treatment without becoming identical: scenarios/resources preserve filters, services preserve category boundaries, and the single case remains a full-width result rather than a sparse card grid.
- Industry/scenario/service details share fact strips and five-chapter decision structure. Case/resource details, assessment, and About remain distinct review, conversion, and manifesto experiences inside the same typographic and color system.
- Desktop/mobile stacking, footer arrival, horizontal overflow, image legibility, content truth, and reveal completion were inspected. Final captures use at least 1050ms post-scroll settle; no transition-gray frames remain.

## Findings and closure

| Severity | State | Finding | Closure |
|---|---|---|---|
| P2 | Closed | Scenario detail `制造知识助手` left an isolated `手` at desktop. | Shared balanced-title contract plus widened `>=1280px` split cover; Browser proves single line at 1440 and 390 with no overflow. |
| P2 | Closed | Services title left `包` alone. | Same shared title contract; Browser proves balanced two-line desktop result. |
| P2 | Closed | Case title left `例` alone and `8 小时 → 2 小时` isolated its last `时`. | Balanced editorial cover plus desktop-only metric nowrap; Browser proves balanced heading and one-line value. |
| P2 | Closed | Assessment title produced an unbalanced final word/character at desktop/mobile. | Shared balanced title treatment; Browser proves two balanced lines at desktop and 390. |
| P2 | Closed | Decision-detail chapter link color overrode the industry/scenario/service primary CTA foreground, producing blue text on blue. | Ordinary chapter links now use `a:not(.btn)`; rendered cascade tests pass and IAB computes all three primary CTAs to white `rgb(255,255,255)` on signal blue. |
| P2 | Closed | Scenario metadata auto-placed into the 2.75rem sequence rail at 390px and wrapped character by character. | A higher-specificity mobile rule keeps metadata in column 2. CSS/DOM contracts cover 390 and 320; IAB proves horizontal writing, useful `dd` widths, no overflow, and natural row height. |
| P2 | Closed | Industry chapter 02 and service chapter 05 lacked any complete viewport frame. | New centered `fullPage:false` Browser frames show each complete chapter heading; they were inserted 1:1 at explicit 12px sheet boundaries without changing original frame pixels. |
| Evidence quality | Closed | Full-page compositor duplicated sticky/reveal regions and produced false mobile blanks. | Rejected compositor output. Genuine Browser viewport frames are preserved 1:1 with explicit 12px separators and overlap. |
| Evidence quality | Closed | First segment round caught 700–800ms reveal transitions at 650ms. | All sixteen routes recaptured after 1100ms load and at least 1050ms per scroll; centered frames make resource filter, case meta, About 01, industry 02, and service 05 fully visible. |
| P2 | Closed | Public auxiliary labels and shared chrome rendered at 11–13px although the binding spec requires at least 14px. | A shared `0.875rem` token now covers audited visible code/eyebrow/sequence/meta/help/optional labels plus real-cascade navigation, footer, and sticky CTA selectors. Parsed-CSS RED/GREEN and IAB computed audits report no visible sub-14px text; the only smaller match is an `aria-hidden` check glyph. |
| P2 | Closed | Raising the desktop navigation CTA to 14px exposed it beside the mobile menu and wrapped its label onto two lines. | A media-cascade RED/GREEN restores the intended narrow-screen `display:none`; v3 mobile evidence shows the single 14px `菜单` summary, no desktop CTA, and no overflow. |

The Fix1 CSS corrections were test-first: authoritative RED `3 failed`, focused GREEN `66 passed`. The full scoped collection then recorded 581 passes plus one repeatable seven-day test-clock expiry; after the authorized test-only clock pin, its singleton and complete 31-test partition passed. Every one of the 582 collected scoped Python cases therefore has fresh pass evidence, and Node runtime is `34/34` pass. The final review's auxiliary-type and real-cascade contracts produced authentic REDs before their minimal fixes; final focused verification is Python `71/71` and Node `27/27`. All sixteen final-CSS evidence sheets were replaced and inspected. No open P0, P1, or P2 remains.

## Interaction and accessibility truth

PASS:

- 25 responsive route/viewport checks across 1440, 1024, 910, 390, and 320 retained one `h1`, `main`, and `nav` with no horizontal overflow.
- Real clicks cover desktop nav, list-to-detail, detail-to-assessment, header assessment, and mobile menu-to-About journeys. At 390px the desktop CTA is hidden and the single mobile summary remains 14px.
- Scenario filters returned a 3-row valid result and a real 0-row empty state; clear restored 12. Resource guide filter returned 3.
- HTTPS external resource links expose `_blank` plus `noopener noreferrer`.
- Fast downward and reverse scrolling updated guided-story chapters from 04 back to 02. Native hover scaled the detail image.
- Mobile footer arrival exposes all four groups without overlap.
- Assessment empty-selection validation and selected-industry retention passed; the disposable fixture's recoverable option-load error was visible.
- Reduced-motion emulation made the media query true, left the story static, removed the image transition, preserved no overflow, and was reset afterward.

NOT PROVEN:

- Native Tab, Shift+Tab, Enter, and Space: the IAB keypress surface produced no observable focus/action movement, so no programmatic substitute is claimed.
- Native 200% zoom: the IAB surface exposes no browser-zoom API; responsive geometry is not mislabeled as zoom proof.
- Pagination: the deterministic fixture has 12 scenarios and the UI minimum page size is 20, so a second page does not exist.
- Complete six-step assessment next/back: after industry selection the disposable fixture returned `评估选项暂时无法加载`; validation, recoverable error, and retained selection are proven, but the full journey is not.

This is a blocking design and interaction audit, not a full WCAG conformance claim. Exact commands, image hashes/dimensions, capture method, interaction evidence, limitations, and cleanup are recorded in `docs/testing/silver-evidence-public-ui.md`.

Browser/fixture cleanup completed precisely: the media override and viewport were reset, the acceptance tab closed, PID `3792` stopped, PID `17188` confirmed absent, `:51838` lost its listener, HTTP refused the connection, and only plan-owned scratch data was removed.

Final-review cleanup also completed precisely: the device-metrics override reset succeeded, tab `4` closed, exact PID `6928` stopped, `:65353` lost its listener, HTTP refused the connection, and the individually resolved final-review fixture/v1/v2/v3/test scratch paths all report absent. Accepted evidence, reports, helpers, references, and protected Task12 paths were preserved.

final result: passed
