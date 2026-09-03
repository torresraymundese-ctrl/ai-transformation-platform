# Silver Evidence public UI verification

## Scope and environment

- Frozen plan base: `d5d8445f0ac1b4425db905062a63330e4764e165`.
- Verification dates: 2026-09-01 and final-phone closure 2026-09-03 (Asia/Shanghai).
- Surface: Codex in-app Browser only. Chrome, Computer Use, Playwright CLI, production, deployment, external networking, and the repository-wide full suite were not used.
- Initial fixture: `127.0.0.1:51838`; launcher PID `3792`; child listener PID `17188`. Fix1 used `127.0.0.1:55844`, PID `30340`. The final-review fixture is `127.0.0.1:65353`, PID `6928`; every fixture used the same ignored database/media paths and mock-only source transport.
- Disposable database/media: `.superpowers/sdd/2026-08-31-silver-evidence-public-ui/task6-browser.db` and `task6-media`.
- All source checks used `MockSourceTransport`; the content clock was fixed to `2026-08-31T10:00:00+08:00`.
- Runtime: Python `3.12.13`, Flask `3.1.3`, Werkzeug `3.1.8`, Pillow `12.3.0`, beautifulsoup4 `4.15.0`.
- Command-scoped dependencies: `.superpowers/sdd/2026-08-24-content-catalog-publishing/local-deps` through `PYTHONPATH`.
- Reference hashes: homepage `5DA39E614D5768BFE28D5C52FB5641C68C0BA1BF146B252BE10CCEA0C2C726CA`; detail `2287D6F8C5FCC8905FD3F19D0EF495607DDFAFC7E8D3428A1FBF5D062A80B588`.

## Fresh scoped automation

```powershell
$env:PYTHONPATH = (Resolve-Path '.superpowers\sdd\2026-08-24-content-catalog-publishing\local-deps').Path
$py = 'D:\Codex干活\企业AI转型平台2.0升级\V0.2-server-snapshot-20260819\.venv\Scripts\python.exe'
$tmpRoot = Join-Path $PWD '.superpowers\sdd\2026-08-31-silver-evidence-public-ui\test-tmp'
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_assessment_wizard.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task6-fix1-final-scoped-017')
node --check static/js/app.js
node --check static/js/guided_story.js
node --check static/js/public_reveal.js
node --check static/js/assessment.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/public_reveal_runtime.test.js tests/js/assessment_runtime.test.js tests/js/analytics_runtime.test.js
```

- Fix1 full Python collection: `581 passed, 1 failed in 312.87s`, exit `1`. The sole failure was an independently reproduced test-clock defect: a source check fixed at `2026-08-25 10:00` expired exactly seven days later while the public request read the real `2026-09-01 11:34` clock, turning a label assertion into the expected fail-closed 404. Production code, the seven-day TTL, and business behavior were unchanged.
- Authorized test-only clock stabilization fixed that one test's public clock to its existing `NOW`. The isolated test then passed (`1 passed in 0.83s`, `task6-fix1-clock-green-019`), and its complete file partition passed (`31 passed in 18.54s`, `task6-fix1-clock-partition-020`). Thus every one of the 582 collected scoped tests has fresh post-Fix1 pass evidence: 581 in the full run and the repaired case in the fresh partition.
- Four Node syntax checks: exit `0` each.
- Node runtime: `34` tests, `34` pass, `0` fail, `0` skipped/cancelled/todo, `duration_ms 283.0863`, exit `0`.
- Every Python command used command-scoped local dependencies, `-p no:cacheprovider`, and a unique plan-owned base temp.

The P2 typography contract was demonstrably test-first: its isolated RED failed with `KeyError: 'text-wrap'` (`1 failed in 1.66s`, exit `1`), then GREEN passed (`1 passed in 0.84s`, exit `0`) after the minimal shared CSS correction. Browser verification proved the affected scenario, services, case, and assessment headings/metric no longer leave isolated Chinese characters or horizontal overflow.

The final whole-branch review's 14px auxiliary-type finding was also closed test-first. The parsed plan-CSS RED enumerated 30 visible subminimum occurrences (`1 failed in 1.17s`), then the shared `--ui-font-size-aux:0.875rem` token and scoped consumers produced GREEN (`1 passed in 0.95s`). A real-cascade IAB audit then exposed legacy `app.css` navigation/footer/sticky values at 11–13px; the stylesheet-order/specificity RED failed and its public-shell overrides passed (`1 passed in 0.98s`). Final mobile visual inspection caught the desktop CTA restored beside the mobile menu; media-cascade RED failed and the narrow-screen silver override passed (`1 passed in 0.74s`). Final focused Python is `71 passed in 40.65s` using `task6-final-review-focused-034`; the three focused Node syntax checks exited `0`, and runtime is `27/27` pass in `233.79ms`.

## Browser evidence method

The in-app Browser's `fullPage:true` compositor was rejected because it duplicated sticky/reveal layers and introduced false mobile gaps. DOM counts proved that the duplication was not present in the page. A CDP full-page experiment hung, was aborted, and wrote no file; it was not used again.

Final evidence consists of genuine `fullPage:false` IAB/CDP viewport frames captured after `1100ms` initial settle and at least `1050ms` after every scroll. Every final-review route manifest reported `scrollWidth === clientWidth`; actual scroll positions were within `1px` of their targets. Frames were preserved 1:1, without crop or scale, and placed vertically with a 12px `#0B1016` separator. The separator explicitly identifies frame boundaries; repeated sticky navigation/CTA/rails and overlap are expected evidence-sheet behavior, not claimed seamless page content.

The final thirteen desktop sheets use 1440×1024 source frames from the clean v2 capture. Industry frame `02a` and service-detail frame `05a` are deliberate centered supplemental viewports that keep chapters 03 and 05 fully reviewable. The three mobile sheets use 390×844 source frames from the clean v3 recapture after the mobile desktop-CTA cascade was fixed. Full footer coverage is present in every sheet; no rejected v1/v2-mobile frame entered the final outputs.

## Route and evidence matrix

| Route | Requested viewport | Frames | Evidence file |
|---|---:|---:|---|
| `/` | 1440×1024 | 6 | `2026-08-31-silver-home-desktop.png` |
| `/industries` | 1440×1024 | 3 | `2026-08-31-silver-industries-desktop.png` |
| `/industries/manufacturing` | 1440×1024 | 6 | `2026-08-31-silver-industry-detail-desktop.png` |
| `/scenarios` | 1440×1024 | 6 | `2026-08-31-silver-scenarios-desktop.png` |
| `/scenarios/mfg-knowledge-assistant` | 1440×1024 | 6 | `2026-08-31-silver-scenario-detail-desktop.png` |
| `/service-packages` | 1440×1024 | 5 | `2026-08-31-silver-services-desktop.png` |
| `/service-packages/foundation-workshop` | 1440×1024 | 8 | `2026-08-31-silver-service-detail-desktop.png` |
| `/cases` | 1440×1024 | 2 | `2026-08-31-silver-cases-desktop.png` |
| `/cases/verified-automation-case` | 1440×1024 | 4 | `2026-08-31-silver-case-detail-desktop.png` |
| `/resources` | 1440×1024 | 3 | `2026-08-31-silver-resources-desktop.png` |
| `/resources/external-evidence-dossier` | 1440×1024 | 3 | `2026-08-31-silver-resource-detail-desktop.png` |
| `/assessment` | 1440×1024 | 3 | `2026-08-31-silver-assessment-desktop.png` |
| `/about` | 1440×1024 | 4 | `2026-08-31-silver-about-desktop.png` |
| `/scenarios` | 390×844 | 9 | `2026-08-31-silver-scenarios-mobile.png` |
| `/scenarios/mfg-knowledge-assistant` | 390×844 | 10 | `2026-08-31-silver-scenario-detail-mobile.png` |
| `/assessment` | 390×844 | 4 | `2026-08-31-silver-assessment-mobile.png` |

## Evidence files

| File | Dimensions | Bytes | SHA-256 |
|---|---:|---:|---|
| `2026-08-31-silver-about-desktop.png` | 1440×4132 | 809,989 | `5E1493C2AE3F550EB281BEE0A56F065700EEB9DF0A1A6F32CC23EF2B4BA10F94` |
| `2026-08-31-silver-assessment-desktop.png` | 1440×3096 | 258,029 | `0F7AB27DD61749B0460EB2AD1E5B6C634D392EDDB4509C48497510C8611A7774` |
| `2026-08-31-silver-assessment-mobile.png` | 390×3412 | 183,304 | `E1C4F928E1EF50A7A2DA0087C7C02A3FF81134CB8DC9D647BB3FD148A45136A3` |
| `2026-08-31-silver-case-detail-desktop.png` | 1440×4132 | 832,059 | `B875D419CE494964F33F0012ECB003F7D8F112AC73FF7BF124BDB257AF7486C2` |
| `2026-08-31-silver-cases-desktop.png` | 1440×2060 | 411,898 | `8B9C08CD3B0E6C8E319BE4343C288F78D3A6326DBDD67A39B4C914011357BB5B` |
| `2026-08-31-silver-home-desktop.png` | 1440×6204 | 2,525,485 | `EE5AF06364CFB78BF325095A169429A516C11958486FB2FEB7C72104127F7B9B` |
| `2026-08-31-silver-industries-desktop.png` | 1440×3096 | 638,297 | `884CE5B309ACC90BA0D78BC2C8D5B2DC9574CD434B6B0B379AA4908307095D8E` |
| `2026-08-31-silver-industry-detail-desktop.png` | 1440×6204 | 913,105 | `00A42BDF5279DB7CC0D60F4E46ACF02D8F30B03EB18B6015E00C3C6C314A4665` |
| `2026-08-31-silver-resource-detail-desktop.png` | 1440×3096 | 582,580 | `03458134E89C919E21FED2311FC2F2DB99525AFE9DCEC20D6FF66F45FADCC22A` |
| `2026-08-31-silver-resources-desktop.png` | 1440×3096 | 522,515 | `6F8ABBEE509E6615E5A6154169571229E669F3FF755EF463DBE61FECB21E0C7C` |
| `2026-08-31-silver-scenario-detail-desktop.png` | 1440×6204 | 977,911 | `BADC13F5A522F785F1BC1C07CB6A1A0F392294253CB076347C95CBC6718C78EB` |
| `2026-08-31-silver-scenario-detail-mobile.png` | 390×8548 | 738,369 | `E64F2F2790B7A77EA73A7C14D080B4C1BD6A183374345B8C4224253ED474ABDA` |
| `2026-08-31-silver-scenarios-desktop.png` | 1440×6204 | 976,532 | `B83B177F5074FE1DA5970035851135533F8A1E24E63BECE89BB13DD7834ABA96` |
| `2026-08-31-silver-scenarios-mobile.png` | 390×7692 | 681,593 | `012041A0A76103A554A9DB7F3219778CF51575D08162589074B12528FE5631F8` |
| `2026-08-31-silver-service-detail-desktop.png` | 1440×8276 | 1,080,411 | `C3C0D6D6F094774935D357DB93860E6F03B104D671625E309E1B74123F865E2E` |
| `2026-08-31-silver-services-desktop.png` | 1440×5168 | 783,860 | `E2385F9232CA9FD2F471D8206BDF9731DDA17264D569C8CE70DCF28D3265F4B7` |

All sixteen files have a PNG signature and were opened and inspected after final compositing.

## Blocking visual comparisons

- Homepage reference and fresh homepage first viewport were placed in one native-pixel comparison input. Both use a bright silver mechanical subject, near-black opening field, warm-white hierarchy, restrained line/radius system, and one blue conversion action. The local subject and headline are larger; the local homepage intentionally omits the header CTA to prevent competition with hero/final conversion. These are accepted P3 distinctions, not lost information.
- Detail reference and fresh scenario-detail first viewport were placed in one native-pixel comparison input. Both preserve a split cover, large single-line `制造知识助手` heading, five-part fact strip, bright industrial subject, restrained blue, and dark/light editorial rhythm. The fixture uses a truthful local manufacturing image rather than the reference mock's augmented-overlay worker. No P0–P2 difference remains.
- The five list pages were compared together. They share the same 1280px alignment, dark art cover, warm-white editorial rows, thin rules, low radius, and single blue accent. Scenario/resource filters, service category boundaries, and the one-item case layout remain functionally distinct without reverting to a generic card matrix.
- Industry/scenario/service decision details were compared together. All retain truthful fact strips and five numbered alternating chapters while allowing content-specific density and imagery.
- Case/resource details, assessment, and About were compared together. Their review dossier, conversion wizard, and manifesto structures remain distinct but coherent through the same palette, typography, spacing, and line discipline.
- Fix1 closed two further P2s through fresh RED/GREEN and IAB evidence. Industry, scenario, and service primary decision CTAs compute to white `rgb(255,255,255)` text on signal-blue `rgb(15,111,239)` backgrounds. Scenario metadata at 390px occupies 298.4px with 210.4px `dd` values; at 320px it occupies 220.8px with 132.8px `dd` values. Both use `horizontal-tb`, naturally wrap, and keep `scrollWidth === clientWidth`.
- Final-review IAB computed audits find no visible sub-14px text on representative homepage, resource-detail, assessment-mobile, and scenario-detail-mobile routes. The only homepage sub-14 match is the real `aria-hidden=true` check glyph. At 390px, navigation/footer/footer-bottom/sticky text/button and assessment eyebrow/progress all compute to 14px, the desktop CTA is `display:none`, the mobile summary is `inline-flex` at 14px, and `scrollWidth === clientWidth === 375`.
- Final judgment: no open P0, P1, or P2. The title/metric, CTA cascade, mobile metadata, incomplete-frame, auxiliary-type, and mobile-navigation cascade findings were closed through RED/GREEN plus fresh same-viewport and full-route evidence.

## Native interaction and accessibility truth

| Check | Result | In-app Browser evidence |
|---|---|---|
| Responsive route structure | PASS | 25 representative route/viewport checks across 1440, 1024, 910, 390, and 320 each retained one `h1`, one `main`, one `nav`, and `scrollWidth === clientWidth`. |
| Desktop navigation and real link journey | PASS | Scenario nav → `/scenarios` → title link → `/scenarios/mfg-knowledge-assistant`; service nav → `/service-packages`; case nav → `/cases` → title link → `/cases/verified-automation-case`; header assessment action → `/assessment`. These were real clicks, separate from the direct-navigation viewport matrix. |
| Detail-to-assessment link | PASS | Scenario detail `获取适配建议` was clicked to `/assessment`, where the landing `h1` was `企业 AI 就绪度评估`. |
| Decision CTA contrast | PASS | Industry, scenario, and service primary CTAs each compute to white text on signal-blue and remain approximately 157×46px with no horizontal overflow. |
| Scenario mobile metadata | PASS | At 390 and 320, metadata occupies the body column, uses horizontal writing, retains useful `dd` width, and no longer forms per-character vertical columns. The final nine-frame 390 sheet reaches the complete footer. |
| Scenario filter | PASS | `manufacturing + pilot` returned 3 real rows. |
| Scenario empty state and reset | PASS | `manufacturing + marketing + collaborate` returned 0 with the real empty state; clear/reset restored 12 rows. |
| Resource filter | PASS | `guide` returned 3 real rows. |
| External resource safety | PASS | The HTTPS source link exposes `target="_blank"` and `rel="noopener noreferrer"`. |
| Mobile navigation | PASS | The desktop CTA is hidden at 390px; the single 14px `菜单` summary remains. The menu expanded and its real About link reached `/about`. |
| Fast/reverse scroll and chapter state | PASS | Fast downward scroll to `y=2800` activated chapter `04`; reverse scroll to `y=1100` reactivated chapter `02`. |
| Image hover | PASS | Native hover changed the image transform to a scale matrix of approximately `1.02`. |
| Mobile footer arrival | PASS | The footer was reachable with all four groups complete and no content overlap. |
| Assessment validation and state retention | PASS | Continue without a selection displayed `请选择所属行业`; selecting `manufacturing` remained selected when the fixture's recoverable load error appeared. |
| Reduced motion | PASS | CDP media emulation made `matchMedia` true, kept the story static, reduced image transition to approximately `0s`, and preserved no horizontal overflow. The override was then reset and `matchMedia` returned false. |
| Tab | NOT PROVEN | The IAB native keypress surface did not move focus from an already focused input. No programmatic focus substitute is claimed. |
| Shift+Tab | NOT PROVEN | Same IAB native keypress limitation. |
| Enter | NOT PROVEN | Native keypress produced no observable action on the focused input; mouse/HTTP/Node evidence is not substituted. |
| Space | NOT PROVEN | Native keypress produced no observable action on the focused input; mouse/HTTP/Node evidence is not substituted. |
| 200% zoom | PARTIALLY PROVEN | User-supplied Edge 200% above-fold and full-page homepage captures are preserved as visual truth and pass a same-input 625px-content comparison. Native 200% was not separately recaptured for every route, so a full-site native-zoom claim is intentionally not made. |
| Pagination | NOT PROVEN / not applicable to fixture | The deterministic fixture contains 12 scenarios while the UI's minimum `per_page` is 20, so it has no second page to exercise. |
| Complete assessment next/back journey | NOT PROVEN | After industry selection, the disposable fixture returned `评估选项暂时无法加载`. The recoverable error and retained selection are proven; six-step advance/back is not. |

The keyboard and zoom entries are capability limitations, not PASS claims. Automated runtime coverage (all `582` scoped Python cases with fresh pass evidence and `34` Node tests) is supporting evidence only and is not substituted for native interaction.

## Cleanup

- The in-app Browser reduced-motion override was reset (`matchMedia` false), the viewport emulation was reset, and the acceptance tab was closed.
- Before stop, `netstat` identified only `127.0.0.1:51838 LISTENING 3792` for the fixture. PID `3792` was stopped precisely; the related launcher/runtime PID `17188` is also no longer alive.
- Final proof: `ProcessAlive=False`, no `:51838` listener in `netstat`, and HTTP `/health` failed with a refused connection.
- Fix1 cleanup: IAB `Emulation.clearDeviceMetricsOverride` returned `{}`, the QA tab returned `tab closed`, and no acceptance tab/override remained. `netstat` identified only `127.0.0.1:55844 LISTENING 30340`; that exact PID was stopped. Final proof was `ProcessAlive=False`, `ListenerPresent=False`, and HTTP refused the connection.
- Exact plan-owned scratch paths were checked to resolve below `.superpowers/sdd/2026-08-31-silver-evidence-public-ui/`, then removed: `task6-browser.db` (plus absent `-wal`/`-shm` companions), `task6-media`, `task6-raw`, and `test-tmp`. Every target reports `exists_after=False`.
- Fix1 also removed only the exact plan-owned `task6-browser` raw-capture directory after the three accepted evidence sheets were written and inspected. Helpers, reports, references, and accepted evidence were preserved.
- Final-review cleanup: CDP `Emulation.clearDeviceMetricsOverride` succeeded and acceptance tab `4` was closed at `/assessment`. Before stop, only `127.0.0.1:65353 LISTENING 6928` matched the fixture. Exact PID `6928` was stopped; final proof is `process_alive=False`, `listener_present=False`, and HTTP refused/unavailable. The resolved, inside-plan paths `task6-browser.db` (with absent WAL/SHM), `task6-media`, `final-review-browser`, `final-review-browser-v2`, `final-review-browser-v3`, and `test-tmp` were removed individually and all report `exists_after=False`.
- Accepted `docs/design/evidence/*.png`, testing documentation, and the ignored Task 6 report/helpers were preserved. No broad deletion or production/external state was touched.

## 2026-09-03 final-phone closure

The final pass used the existing deterministic mock-only fixture on `127.0.0.1:62823`; the previously approved preview on `127.0.0.1:62767` was not touched. The user's 200% homepage capture was accepted as source visual truth, normalized proportionally to 625px content width, and compared in the same input with a fresh 640px requested viewport whose scrollbar left a 625px client.

### Fresh responsive and interaction results

| Check | Result | Evidence |
|---|---|---|
| All public routes at 640/390/320 | PASS | 39/39 route-width combinations; every result had `scrollWidth === clientWidth`. |
| About at 320 | PASS after one P2 fix | Initial `332/305`; final `305/305`. Mixed Chinese/Latin principle copy now permits grid shrink and wraps anywhere on phone widths. |
| Homepage chapter 01 at 390 | PASS | Real click retained visible chapter copy; DOM and viewport evidence disproved the apparent omission in the stitched user capture. |
| Mobile menu at 390 | PASS | Real click opened it; Escape closed it and restored focus to the summary. |
| Browser console | PASS | No errors or warnings in the tested mobile interaction. |

### Fresh automation

- TDD RED for the About phone contract: `1 failed in 1.19s`.
- Focused GREEN: `1 passed in 0.82s`.
- Full UI-foundation partition: `66 passed in 49.73s`.
- Adjacent content-navigation and smoke partition: `58 passed in 37.31s`.
- JavaScript syntax: `app.js`, `guided_story.js`, and `public_reveal.js` all exit `0`.
- Node runtime: `35` tests, `35` pass, `0` fail.
- `git diff --check`: exit `0` (line-ending notices only).
- Supporting context: immediately preceding Task 22 repository full suite was `2170 passed in 1346.36s`; the final-phone production delta is one scoped two-declaration CSS rule.

### Final-phone evidence files

| File | Dimensions | Bytes | SHA-256 |
|---|---:|---:|---|
| `2026-09-03-user-home-200-percent-reference.png` | 625×5706 | 1,351,442 | `2729BFCC537389C56B6A65825BE1464ED3D241C8DD45957DF3D767A8C7FEC994` |
| `2026-09-03-final-home-640.png` | 625×824 | 290,724 | `8E982F759F3D7C4A739E222E09D682A7773AEFCDF9484917963CEF6D6EA65D45` |
| `2026-09-03-final-home-assessment-390.png` | 375×811 | 161,359 | `20A1A96818EFACD887AC056EA5677F5F9D871A4A0BF2EDD4E033855C40CDA956` |
| `2026-09-03-final-about-320.png` | 305×804 | 207,339 | `BE8BE72955AB7275019E5A5C94E7738A296533693923F1784479FC542F58584C` |
| `2026-09-03-final-home-640-comparison.png` | 1250×824 | 473,546 | `8526B27AE9D92E24FC5D1AE35C7E59DF80297634FA1BCD6E2C9B703214D4F208` |

All five files have a PNG signature and were opened and inspected. The first and last preserve the density-normalized source/comparison; the three focused runtime frames document the final implementation state.

Final-phone cleanup was exact. PID `8948` was first confirmed as the `127.0.0.1:62823` listener, then stopped; process and listener are absent. The fixture database/media and individually named test/image normalization scratch paths are absent. User preview PID `31692` remains the `127.0.0.1:62767` listener and was not touched.

## Limitations

- This is a blocking design/interaction review, not a full WCAG conformance audit.
- Evidence sheets contain explicit separators and overlap; they are not seamless compositor screenshots.
- The fixture is deterministic and local, so it proves the published public journey without asserting production state.
- Only the homepage has user-supplied native Edge 200% proof; full-site native 200% is not claimed separately from the 640/390/320 responsive matrix.
