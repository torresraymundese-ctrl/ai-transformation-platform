# Task 3 report: Public SEO and asset-loading baseline

## Status

Complete. The accepted public/report visual design, CSS, JavaScript, PDF,
calculations, global tokens, business behavior, security headers, caching behavior,
and data semantics were preserved. Changes are limited to public nonvisual image
attributes, internal legal metadata, focused regressions, and baseline documentation.

## TDD evidence

RED command:

```text
D:/Codex干活/企业AI转型平台2.0升级/V0.2-server-snapshot-20260819/.venv/Scripts/python.exe -m pytest tests/test_public_performance.py -q -p no:cacheprovider --basetemp=.tmp/task3-red-20260907-02
```

RED result:

```text
..........FF.F.  [100%]
3 failed, 12 passed in 10.47s
```

The expected failures were the navigation logo's missing intrinsic dimensions, the
first hero's missing explicit eager/high-priority contract, and internal legal pages'
missing canonical. A separate approved case/resource/announcement detail fixture was
also run RED and failed at the case hero's absent eager attribute:

```text
1 failed in 0.94s
```

GREEN command:

```text
D:/Codex干活/企业AI转型平台2.0升级/V0.2-server-snapshot-20260819/.venv/Scripts/python.exe -m pytest tests/test_public_performance.py -q -p no:cacheprovider --basetemp=.tmp/task3-green-20260907-03
```

GREEN result:

```text
................  [100%]
16 passed in 11.49s
```

Relevant public navigation, UI foundation, catalog SEO, and legal behavior regression
command:

```text
D:/Codex干活/企业AI转型平台2.0升级/V0.2-server-snapshot-20260819/.venv/Scripts/python.exe -m pytest tests/test_content_navigation.py::test_navigation_matches_confirmed_information_architecture tests/test_content_navigation.py::test_home_canonical_uses_only_the_validated_public_base_url tests/test_content_navigation.py::test_public_legacy_shell_pages_have_configured_canonical tests/test_content_navigation.py::test_private_html_surfaces_have_template_and_header_noindex tests/test_content_navigation.py::test_mobile_navigation_is_native_keyboard_operable tests/test_ui_foundations.py::test_public_shell_uses_one_silver_evidence_navigation_layer tests/test_ui_foundations.py::test_skip_link_targets_a_unique_focusable_main_on_public_pages tests/test_ui_foundations.py::test_home_dark_evidence_assets_are_local_decodable_and_bounded tests/test_ui_foundations.py::test_silver_evidence_assets_are_local_decodable_and_bound_to_public_surfaces tests/test_ui_foundations.py::test_home_technology_assets_are_local_decorative_and_bounded tests/test_public_catalog.py::test_published_detail_has_sections_seo_canonical_and_no_internal_leaks tests/test_public_catalog.py::test_public_catalog_list_has_trusted_canonical_and_description tests/test_legal_versions.py::test_public_current_and_version_routes_hide_drafts_and_preserve_history tests/test_legal_versions.py::test_external_version_route_redirects_only_to_frozen_url tests/test_legal_versions.py::test_public_legal_path_rejects_noncanonical_codes -q -p no:cacheprovider --basetemp=.tmp/task3-regressions-20260907-01
```

Regression result:

```text
..............................  [100%]
30 passed in 20.53s
```

## Changed paths and metadata contract

- `blueprints/public_legal.py`: builds internal current/history canonicals from the
  validated `PUBLIC_BASE_URL` and the corresponding endpoint's `url_for` path.
- `templates/legal_detail.html`: emits one autoescaped description from the reviewed
  internal document summary; base template emits the single canonical.
- `templates/components/navigation.html`: records the real 859 by 1066 logo ratio and
  asynchronous decode hint.
- `templates/index.html`, `templates/components/public_catalog.html`,
  `templates/components/detail_page.html`, `templates/about.html`,
  `templates/case_detail.html`, `templates/resource_detail.html`, and
  `templates/announcement_detail.html`: add only role-appropriate eager/high-priority
  or intrinsic image attributes.
- `tests/test_public_performance.py`: locks local/deferred scripts, trusted unique
  canonicals and titles, private noindex, shipped image dimensions and loading roles,
  and legal metadata/current/history/redirect/404 behavior with approved fixtures.
- `docs/testing/seo-performance-baseline.md`: records the route matrix, local asset
  inventory, cache/environment scope, and measurement caveats.

Host headers, forwarded hosts, and queries cannot influence the new legal canonical.
Current internal documents canonicalize to `/legal/<type>` and immutable history to
`/legal/<type>/<version>`. External legacy documents still redirect to their frozen
validated URL; draft, unavailable, malformed, and unknown versions remain 404.

## Byte baseline and caveats

The reusable loopback inventory contains 18 HTML pages, 160 repeated asset references,
21 unique assets, 139,677 HTML bytes, and 1,375,192 deduplicated asset bytes. The asset
total is across the complete route inventory, not a per-page transfer total. It does
not account for production compression, CDN behavior, cache warmth, or network
latency. No Lighthouse or Core Web Vitals pass is claimed. Deployment compression/CDN
validation remains Stage 7 work.

## Commit and concerns

Commit: this report is part of the scoped Task 3 commit; its exact immutable hash is
reported in the controller handoff because a commit cannot embed its own final hash.

Concerns: none. The checked-in inventory remains evidence of the pre-change loopback
capture and was not altered or presented as proof of an optimization.
