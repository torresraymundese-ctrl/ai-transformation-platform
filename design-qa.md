# Dark evidence homepage — blocking design QA

## Scope and frozen target

- Frozen implementation base: `12ec7056a2cc1a952f5bec5ee7727ae2447fb318`.
- Binding visual target: selected option 1, `C:/Users/zz/.codex/generated_images/01a03349-721a-7df2-b234-cd675d8d96d1/exec-adcdb983-d7e6-468e-ae5c-a847303e8c60.png`.
- Scope: homepage only, exercised against a fresh deterministic SQLite/media fixture on `127.0.0.1:52537` with the Codex in-app Browser.
- No production host, real database, external network, deployment surface, or full suite was used.

## Same-input visual comparison

The selected reference and the fresh 1440×1024 full-page evidence sheet were inspected together in one image-comparison input. The fresh 1024×900, 910×900, and 390×844 full-page evidence sheets were inspected together in a second input. Unlike the rejected viewport-only evidence, each sheet now exposes the complete journey from Hero through chapters 02—05, applications, proof/case, news, final CTA, and footer. The result preserves the selected direction at every responsive regime: black/white/electric-blue palette, editorial type scale, dark opening stage, right-weighted AI visual, low-radius thin-boundary components, large image crops, evidence/news sequence, and a quiet final conversion block. The Hero contains exactly one action and a plain audited-content note, with no scenario catalog entry.

No P0–P2 remained after recapture. The 1024 and 910 states retain a deliberate two-line heading and keep the fixed chapter rail outside both copy and artwork. The 390 state stacks the hero, keeps the chapter strip horizontally scrollable without causing page overflow, and preserves readable actions and evidence rows. A separate 320×844 boundary check reported `scrollWidth === clientWidth` and `scrollX=0` after an attempted horizontal scroll.

The in-app Browser was set to the exact requested emulation states. Because its full-page compositor visibly duplicated sticky sections and its screenshot bytes are JPEG, that output was rejected. Instead, genuine viewport captures were taken at named page anchors. Desktop/1024/910 use seven captures; mobile uses nine. Offline Pillow decoded each capture and assembled it 1:1—without crop or scale—with only a 12px `#0b0f15` separator, then encoded the sheet as PNG. The final PNGs are 1425×5945, 1009×5924, 895×5910, and 375×7395; every file has the PNG signature and Pillow reports `format=PNG`.

## Findings and closure

| Severity | State | Finding | Closure |
|---|---|---|---|
| P2 | Hero catalog-entry boundary | The first Task 4 evidence round exposed a published scenario link in `story-purpose`, conflicting with the binding one-action Hero and later-chapter catalog-entry contract. | Closed in `e0e3619`: the Hero is again a non-interactive `基于已审核内容` note; the scenario URL contract now points to `story-matching` and explicitly forbids a Hero scenario href/label. Fresh scoped result `395 passed`. |
| P2 | 1024/910/390 responsive states | The 910 rail overlapped the Hero artwork, the 1024 heading left a one-character final line, and mobile chapter labels collapsed into each other with a coarse scrollbar. | Closed in `620bc4a`: reserved rail space, corrected compact heading scale, and added unshrinking scrollbar-free mobile step slots; fresh UI responsibility result `39 passed`. |
| P2 | Chapter 05 interaction | The very tall evidence chapter could not cross the observer's former 0.25 minimum, so its active state stayed on chapter 04 after navigation. | Closed in `ce026ae`: included a 0.05 observer threshold; fresh Node responsibility result `22 passed`, and Browser click proof showed matching hash/current/active state. |
| P2 | 320px boundary | The root 20rem minimum created 15px of reachable page-level horizontal overflow. | Closed in `580a8ef`: root minimum is zero while children retain their own bounds; fresh UI responsibility result `39 passed`, Browser `scrollX=0`. |
| P2 | Evidence format and page coverage | The first evidence files used `.png` names for viewport-only JFIF/JPEG bytes, so later chapters and the footer could not be independently reviewed. | Closed in Fix2: four true-PNG same-viewport evidence sheets now expose Hero, chapters 02—05, applications, proof/case, news, final CTA, and footer; dimensions, bytes, hashes, and assembly method are recorded. |
| P3 | Reference fidelity | The generated reference has slightly brighter abstract art and a duplicate-looking nav CTA; the implementation uses the approved darker local artwork and intentionally omits the duplicate root conversion action required by the navigation spec. | Accepted implementation distinction; no usability or information loss. |

## Interaction and accessibility evidence

- All five chapter controls reached their exact chapter IDs; chapter 05 finished with `hash`, current link, and active section all equal to `story-evidence`.
- Fast downward and reverse scrolling updated the active chapter without wheel interception.
- Hero and final assessment actions reached `/assessment`; scenario, service, verified case, and reviewed resource links reached their real local routes.
- Mobile menu opened; Escape closed it and restored focus to its summary control. Its AI-scene link reached `/scenarios`.
- Final CTA and footer were visible and unoverlapped at 1440, 1024, 910, and 390; console errors and warnings were both zero.
- Native Tab traversal is **NOT PROVEN** because the in-app Browser key surface did not expose an observable focus advance. Escape behavior is proven.
- Native reduced-motion emulation is **NOT PROVEN** in this Browser surface. The runtime test proves the reduced-motion branch remains static and does not create the observer.
- Native 200% zoom is **NOT PROVEN** because repeated browser zoom keys did not change the observable viewport or device scale. A 720px half-width geometry proxy for a 1440px page passed without overflow, clipping, or action loss; it is recorded only as a proxy.
- This is not a full WCAG conformance audit.

## Evidence and cleanup

Four post-Fix2 full-page evidence-sheet PNGs are stored under `docs/design/evidence/`. Each sheet was visually inspected from Hero to footer; the rejected compositor output is not evidence. The disposable Browser and exact fixture cleanup are recorded in the testing report.

final result: passed
