# Silver Evidence public UI verification

## Scope and environment

- Frozen plan base: `d5d8445f0ac1b4425db905062a63330e4764e165`.
- Verification date: 2026-09-01 (Asia/Shanghai).
- Surface: Codex in-app Browser only. Chrome, Computer Use, Playwright CLI, production, deployment, external networking, and the repository-wide full suite were not used.
- Local fixture: `127.0.0.1:51838`; launcher PID `3792`; child listener PID `17188`.
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
& $py -m pytest tests/test_ui_foundations.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_assessment_wizard.py tests/test_content_navigation.py tests/test_smoke.py tests/test_security_gaps.py tests/test_validation_and_errors.py -q -p no:cacheprovider --basetemp (Join-Path $tmpRoot 'task6-final-scoped-012')
node --check static/js/app.js
node --check static/js/guided_story.js
node --check static/js/public_reveal.js
node --check static/js/assessment.js
node --test tests/js/app_runtime.test.js tests/js/guided_story_runtime.test.js tests/js/public_reveal_runtime.test.js tests/js/assessment_runtime.test.js tests/js/analytics_runtime.test.js
```

- Python: `579 passed in 331.49s (0:05:31)`, exit `0`.
- Four Node syntax checks: exit `0` each.
- Node runtime: `34` tests, `34` pass, `0` fail, `0` skipped/cancelled/todo, `duration_ms 325.7764`, exit `0`.
- The Python run used command-scoped local dependencies, `-p no:cacheprovider`, and unique base temp `task6-final-scoped-012`.

The P2 typography contract was demonstrably test-first: its isolated RED failed with `KeyError: 'text-wrap'` (`1 failed in 1.66s`, exit `1`), then GREEN passed (`1 passed in 0.84s`, exit `0`) after the minimal shared CSS correction. Browser verification proved the affected scenario, services, case, and assessment headings/metric no longer leave isolated Chinese characters or horizontal overflow.

## Browser evidence method

The in-app Browser's `fullPage:true` compositor was rejected because it duplicated sticky/reveal layers and introduced false mobile gaps. DOM counts proved that the duplication was not present in the page. A CDP full-page experiment hung, was aborted, and wrote no file; it was not used again.

Final evidence consists of genuine `fullPage:false` viewport frames captured with native CUA scrolling after `1100ms` initial settle and at least `1050ms` after every scroll. Every frame reported `scrollWidth === clientWidth`; actual scroll positions were within `1px` of their targets. Frames were preserved 1:1, without crop or scale, and placed vertically with a 12px `#0B1016` separator. The separator explicitly identifies frame boundaries; repeated sticky navigation/CTA/rails and 144px overlap are expected evidence-sheet behavior, not claimed seamless page content.

The Browser viewport was set to `1440×1024` or `390×844`. Saved viewport bitmap widths are `1425` and `375` because the Browser excludes its 15px vertical scrollbar from screenshot pixels. Full-height footer coverage is present in every evidence sheet. Three additional centered frames make the resource filter, case audit metadata band, and About chapter 01 wholly reviewable.

## Route and evidence matrix

| Route | Requested viewport | Frames | Evidence file |
|---|---:|---:|---|
| `/` | 1440×1024 | 6 | `2026-08-31-silver-home-desktop.png` |
| `/industries` | 1440×1024 | 3 | `2026-08-31-silver-industries-desktop.png` |
| `/industries/manufacturing` | 1440×1024 | 5 | `2026-08-31-silver-industry-detail-desktop.png` |
| `/scenarios` | 1440×1024 | 6 | `2026-08-31-silver-scenarios-desktop.png` |
| `/scenarios/mfg-knowledge-assistant` | 1440×1024 | 6 | `2026-08-31-silver-scenario-detail-desktop.png` |
| `/service-packages` | 1440×1024 | 5 | `2026-08-31-silver-services-desktop.png` |
| `/service-packages/foundation-workshop` | 1440×1024 | 7 | `2026-08-31-silver-service-detail-desktop.png` |
| `/cases` | 1440×1024 | 2 | `2026-08-31-silver-cases-desktop.png` |
| `/cases/verified-automation-case` | 1440×1024 | 5 | `2026-08-31-silver-case-detail-desktop.png` |
| `/resources` | 1440×1024 | 4 | `2026-08-31-silver-resources-desktop.png` |
| `/resources/external-evidence-dossier` | 1440×1024 | 3 | `2026-08-31-silver-resource-detail-desktop.png` |
| `/assessment` | 1440×1024 | 3 | `2026-08-31-silver-assessment-desktop.png` |
| `/about` | 1440×1024 | 5 | `2026-08-31-silver-about-desktop.png` |
| `/scenarios` | 390×844 | 17 | `2026-08-31-silver-scenarios-mobile.png` |
| `/scenarios/mfg-knowledge-assistant` | 390×844 | 9 | `2026-08-31-silver-scenario-detail-mobile.png` |
| `/assessment` | 390×844 | 4 | `2026-08-31-silver-assessment-mobile.png` |

## Evidence files

| File | Dimensions | Bytes | SHA-256 |
|---|---:|---:|---|
| `2026-08-31-silver-about-desktop.png` | 1425×4258 | 1,324,753 | `C98F8700559F52E3573A366B0BE1C002C1A04742A7AA4B716152C53534810E58` |
| `2026-08-31-silver-assessment-desktop.png` | 1425×2550 | 427,805 | `35D2DB5C1C9D9E8076B80B644C0A4A3EF3FDDDE7770B687FBAF4A093BB9A4E89` |
| `2026-08-31-silver-assessment-mobile.png` | 375×3280 | 374,203 | `3F66A98FED2885135D15A06E580BEB1C697B2C7E445F600C4290FDC3168A9400` |
| `2026-08-31-silver-case-detail-desktop.png` | 1425×4258 | 1,233,003 | `15460C1D1553071FD4916F18900BC62EAFD7D1C5FCACF393350C3F1D41E4AC89` |
| `2026-08-31-silver-cases-desktop.png` | 1425×1696 | 500,543 | `B9C6D49A14F014692C4D99EABC2958B771CFA2CC302288F335D575A289115334` |
| `2026-08-31-silver-home-desktop.png` | 1425×5112 | 2,276,932 | `86FFECF1AE445CB01936B3125A099458F4DBC6E67E468CE86437A1B10B3E0839` |
| `2026-08-31-silver-industries-desktop.png` | 1425×2550 | 1,013,944 | `901BBC1BF46B195A98315B191C935C36A7E133E5319AA0CD04EF056FF45DFD0B` |
| `2026-08-31-silver-industry-detail-desktop.png` | 1425×4258 | 1,175,898 | `9878069A9B63A72F9630942DB594803C5198036F40F6A80199B13C99D08FF278` |
| `2026-08-31-silver-resource-detail-desktop.png` | 1425×2550 | 655,436 | `9C07C99E9ECCB13410CA7FF0CC68A8A639674BA1B50AF1A97E6B17179215F0C4` |
| `2026-08-31-silver-resources-desktop.png` | 1425×3404 | 1,059,816 | `5B7B9479FD08C60043B9B19B8B1D830EB2415749089B645687387B274C019484` |
| `2026-08-31-silver-scenario-detail-desktop.png` | 1425×5112 | 1,347,779 | `041F494B261AB06F54BABB4BE72CD4FBA6591DDF8FC9E350BD85C3170D4FCF8C` |
| `2026-08-31-silver-scenario-detail-mobile.png` | 375×7395 | 1,158,140 | `606A592E37F7F7EEFC0ECD5288075ACE156039D627D3292200F7AFBD12531E3C` |
| `2026-08-31-silver-scenarios-desktop.png` | 1425×5112 | 1,519,334 | `B508A73FE577A85D12591F75B016EC9C954F522BD913D952945AF6B40CE53EBF` |
| `2026-08-31-silver-scenarios-mobile.png` | 375×13979 | 1,740,361 | `AE743DD29D3A399AA4C7A46E8997DAF3AFA9D0F66389B04444F054D413362F7B` |
| `2026-08-31-silver-service-detail-desktop.png` | 1425×5966 | 1,423,974 | `AEBE6D3E41C378BC8D7010B9761AC0EB423AAD7B3795A337770B5BA42CC3E832` |
| `2026-08-31-silver-services-desktop.png` | 1425×4258 | 1,126,933 | `444B488B645C8D5B7640525150EBC15660E36D615A1C909C6FB31E6FFF5AE28C` |

All sixteen files have a PNG signature and were opened and inspected after final compositing.

## Blocking visual comparisons

- Homepage reference and fresh homepage first viewport were placed in one native-pixel comparison input. Both use a bright silver mechanical subject, near-black opening field, warm-white hierarchy, restrained line/radius system, and one blue conversion action. The local subject and headline are larger; the local homepage intentionally omits the header CTA to prevent competition with hero/final conversion. These are accepted P3 distinctions, not lost information.
- Detail reference and fresh scenario-detail first viewport were placed in one native-pixel comparison input. Both preserve a split cover, large single-line `制造知识助手` heading, five-part fact strip, bright industrial subject, restrained blue, and dark/light editorial rhythm. The fixture uses a truthful local manufacturing image rather than the reference mock's augmented-overlay worker. No P0–P2 difference remains.
- The five list pages were compared together. They share the same 1280px alignment, dark art cover, warm-white editorial rows, thin rules, low radius, and single blue accent. Scenario/resource filters, service category boundaries, and the one-item case layout remain functionally distinct without reverting to a generic card matrix.
- Industry/scenario/service decision details were compared together. All retain truthful fact strips and five numbered alternating chapters while allowing content-specific density and imagery.
- Case/resource details, assessment, and About were compared together. Their review dossier, conversion wizard, and manifesto structures remain distinct but coherent through the same palette, typography, spacing, and line discipline.
- Final judgment: no open P0, P1, or P2. The four heading/metric P2s found in the first comparison wave were closed through RED/GREEN plus fresh same-viewport and full-route evidence.

## Native interaction and accessibility truth

| Check | Result | In-app Browser evidence |
|---|---|---|
| Responsive route structure | PASS | 25 representative route/viewport checks across 1440, 1024, 910, 390, and 320 each retained one `h1`, one `main`, one `nav`, and `scrollWidth === clientWidth`. |
| Desktop navigation and real link journey | PASS | Scenario nav → `/scenarios` → title link → `/scenarios/mfg-knowledge-assistant`; service nav → `/service-packages`; case nav → `/cases` → title link → `/cases/verified-automation-case`; header assessment action → `/assessment`. These were real clicks, separate from the direct-navigation viewport matrix. |
| Detail-to-assessment link | PASS | Scenario detail `获取适配建议` was clicked to `/assessment`, where the landing `h1` was `企业 AI 就绪度评估`. |
| Scenario filter | PASS | `manufacturing + pilot` returned 3 real rows. |
| Scenario empty state and reset | PASS | `manufacturing + marketing + collaborate` returned 0 with the real empty state; clear/reset restored 12 rows. |
| Resource filter | PASS | `guide` returned 3 real rows. |
| External resource safety | PASS | The HTTPS source link exposes `target="_blank"` and `rel="noopener noreferrer"`. |
| Mobile navigation | PASS | The menu expanded and its real About link reached `/about`. |
| Fast/reverse scroll and chapter state | PASS | Fast downward scroll to `y=2800` activated chapter `04`; reverse scroll to `y=1100` reactivated chapter `02`. |
| Image hover | PASS | Native hover changed the image transform to a scale matrix of approximately `1.02`. |
| Mobile footer arrival | PASS | The footer was reachable with all four groups complete and no content overlap. |
| Assessment validation and state retention | PASS | Continue without a selection displayed `请选择所属行业`; selecting `manufacturing` remained selected when the fixture's recoverable load error appeared. |
| Reduced motion | PASS | CDP media emulation made `matchMedia` true, kept the story static, reduced image transition to approximately `0s`, and preserved no horizontal overflow. The override was then reset and `matchMedia` returned false. |
| Tab | NOT PROVEN | The IAB native keypress surface did not move focus from an already focused input. No programmatic focus substitute is claimed. |
| Shift+Tab | NOT PROVEN | Same IAB native keypress limitation. |
| Enter | NOT PROVEN | Native keypress produced no observable action on the focused input; mouse/HTTP/Node evidence is not substituted. |
| Space | NOT PROVEN | Native keypress produced no observable action on the focused input; mouse/HTTP/Node evidence is not substituted. |
| 200% zoom | NOT PROVEN | The IAB exposes no native browser-zoom control/API in this surface. Responsive 720/390/320 checks are not mislabeled as zoom proof. |
| Pagination | NOT PROVEN / not applicable to fixture | The deterministic fixture contains 12 scenarios while the UI's minimum `per_page` is 20, so it has no second page to exercise. |
| Complete assessment next/back journey | NOT PROVEN | After industry selection, the disposable fixture returned `评估选项暂时无法加载`. The recoverable error and retained selection are proven; six-step advance/back is not. |

The keyboard and zoom entries are capability limitations, not PASS claims. Automated runtime coverage (`579` Python and `34` Node tests) is supporting evidence only and is not substituted for native interaction.

## Cleanup

- The in-app Browser reduced-motion override was reset (`matchMedia` false), the viewport emulation was reset, and the acceptance tab was closed.
- Before stop, `netstat` identified only `127.0.0.1:51838 LISTENING 3792` for the fixture. PID `3792` was stopped precisely; the related launcher/runtime PID `17188` is also no longer alive.
- Final proof: `ProcessAlive=False`, no `:51838` listener in `netstat`, and HTTP `/health` failed with a refused connection.
- Exact plan-owned scratch paths were checked to resolve below `.superpowers/sdd/2026-08-31-silver-evidence-public-ui/`, then removed: `task6-browser.db` (plus absent `-wal`/`-shm` companions), `task6-media`, `task6-raw`, and `test-tmp`. Every target reports `exists_after=False`.
- Accepted `docs/design/evidence/*.png`, testing documentation, and the ignored Task 6 report/helpers were preserved. No broad deletion or production/external state was touched.

## Limitations

- This is a blocking design/interaction review, not a full WCAG conformance audit.
- Evidence sheets contain explicit separators and overlap; they are not seamless compositor screenshots.
- The fixture is deterministic and local, so it proves the published public journey without asserting production state.
