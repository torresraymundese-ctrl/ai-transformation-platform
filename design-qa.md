# Guided public experience design QA

## 1. Scope and evidence health

Audit scope: the five-chapter public homepage, scenario catalog, and manufacturing knowledge-assistant detail in a fresh deterministic local fixture. All eight saved browser captures were inspected after saving: no blank, loading, error, or anomalous crop state was accepted. Desktop captures used a 1440×1024 viewport (document client width 1425 with the browser scrollbar); the mobile capture used 390×844 (client width 375). Every captured viewport reported `scrollWidth === clientWidth`, so no page-level horizontal overflow was observed.

## 2. Same-input Scale comparison

The supplied Scale reference and the local purpose capture were opened together, then the five local chapter captures were opened together. The implementation takes the intended cues rather than cloning Scale: a dark task-first opening, unusually prominent product surface, restrained paper/graphite shifts, thin industrial borders, and editorial type scale. It remains recognizably this product through its Chinese task framing, actual published scenario data, platform navigation, and real internal routes.

Strengths: the hero headline is decisive, the real product surface is the compositional counterweight, the five active progress states are clear, chapter spacing is consistently generous, generated art is correctly cropped as decorative imagery, and the scenario/detail screens continue the same grid and border language. The mobile screen stacks naturally and intentionally makes the chapter progress a horizontally scrollable local control rather than causing document overflow.

P3 follow-up: the desktop chapter stage has substantial upper whitespace in chapters 2–5. It supports the editorial cadence but could be tightened after visual acceptance; it does not obscure content or interaction.

## 3. Findings and closure

| Severity | Screen/state | Finding | Closure |
|---|---|---|---|
| P2 | Homepage purpose, desktop and mobile | The secondary `浏览 AI 场景` CTA inherited a paper background while its hero override made the text paper-colored, leaving the label visually absent. | Closed. Added RED regression `test_hero_secondary_action_keeps_a_visible_outline_label` (1 expected failure), made the hero outline background transparent, GREEN 1/1, then reran `tests/test_ui_foundations.py` (35 passed) and recaptured the purpose screen. |
| P3 | Chapters 2–5 desktop | Large intentional upper whitespace may feel sparse on short laptop viewports. | Recorded for later visual-acceptance discussion; no usability, overflow, or information-loss evidence. |

## 4. Combined UX and accessibility lenses

User goal: understand a defensible path from readiness to a scenario and begin assessment. The journey exposes a clear starting CTA, preserves published-only scenario information, labels deterministic output as `演示数据`, and offers a visible return path from detail to assessment. Native scroll, rapid scroll, reverse scroll, five chapter links, mobile menu open/Escape close, and browser find were exercised through the in-app browser. Native scrollbar dragging did not move in the available browser control surface and is therefore NOT PROVEN rather than inferred. No full WCAG conformance claim is made: no-JavaScript, media-query emulation, 200% zoom, and the complete native keyboard matrix require follow-up browser/environment coverage.

final result: passed
