# Public SEO and performance baseline

## Scope and environment

This baseline records the read-only loopback inventory in
`.superpowers/sdd/2026-09-07-admin-experience-performance-closeout/public-asset-inventory.json`.
It contains 18 successful HTML responses captured from `127.0.0.1:62851` with
`PUBLIC_BASE_URL=https://preview.invalid`. Detail routes used approved published
fixtures; an empty catalog was not treated as detail-page evidence. The inventory's
disposable database was not read.

All 160 rendered asset references resolve to 21 unique local `/static/` assets. No
remote font, image, or script dependency appears in the captured HTML. External-file
scripts are local and deferred. Inline scripts are not counted as external asset
references. The admin login is included only to record the private/noindex boundary;
its separate `admin.css` is not loaded by public pages.

The focused regression visits the approved public route fixtures and inspects every
rendered `img[src]`, every external `script[src]`, and every stylesheet link. It then
loads each shipped stylesheet locally and inspects CSS `@import` and `url()` references,
including font sources. Controlled negative fixtures prove that remote images,
protocol-relative stylesheets, remote CSS imports, and remote font URLs are rejected;
the guard does not rely on a selector that prefilters remote URLs out of view.

The responses used the application's private analytics cache policy
(`Cache-Control: private, no-store`). The byte counts below are decoded file sizes
obtained through loopback requests, not compressed production transfer sizes. No
CDN, reverse-proxy compression, cold/warm browser cache, network latency, Lighthouse,
Largest Contentful Paint, or other Core Web Vitals measurement was performed. These
figures therefore establish a repeatable local inventory, not a production speed or
CWV pass. Compression and CDN validation remain a Stage 7 deployment check.

## Route metadata matrix

| Public role | Captured routes | Title | Description | Canonical / robots |
| --- | --- | --- | --- | --- |
| Home | `/` | Unique route title | Present | Trusted configured origin plus `/`; indexable |
| Industries | `/industries`, `/industries/manufacturing` | Unique list/detail titles | Present | Trusted configured origin plus canonical list/detail path; indexable |
| Scenarios | `/scenarios`, `/scenarios/mfg-knowledge-assistant` | Unique list/detail titles | Present | Trusted configured origin plus canonical list/detail path; indexable |
| Services | `/service-packages`, legacy `/services`, `/service-packages/foundation-workshop` | Unique canonical list/detail titles | Present | `/services` resolves to the `/service-packages` canonical; indexable |
| Cases | `/cases`, `/cases/matrix-verified-case` | Unique list/detail titles | Present | Trusted configured origin plus canonical list/detail path; indexable |
| Resources | `/resources`, `/resources/matrix-sourced-resource`, `/announcements/matrix-current-announcement` | Unique list/detail titles | Present | Trusted configured origin plus canonical list/detail path; indexable |
| About | `/about` | Unique route title | Not emitted in the accepted baseline | Trusted configured origin plus `/about`; indexable |
| Assessment | `/assessment` | Unique route title | Not emitted in the accepted baseline | Trusted configured origin plus `/assessment`; indexable |
| Legal | `/legal/privacy`, `/legal/terms`; immutable version routes covered by regression fixture | Document title and version-specific title | Internal document's escaped reviewed summary | Current endpoint or exact version endpoint on trusted configured origin; indexable |

Canonical URLs do not consume the request `Host`, forwarded host, query string, or
user input. Internal current legal pages canonicalize to `/legal/<type>`; immutable
history canonicalizes to `/legal/<type>/<version>`. External legacy legal documents
remain redirects and unavailable or draft versions remain 404 responses.

Private HTML remains excluded from indexing in both layers. `/admin/login` and report
HTML emit a `robots` meta directive containing `noindex` and the
`X-Robots-Tag: noindex, nofollow` response header. The inventory captured the admin
login values as `noindex,nofollow` and `noindex, nofollow`, respectively.

## Local asset byte inventory

The 18 HTML documents total 139,677 bytes. Their 160 references are repeated across
pages and must not be summed as a per-page load. Deduplicating by URL yields exactly
21 assets and 1,375,192 bytes:

| Local asset | Bytes |
| --- | ---: |
| `/static/css/admin.css` | 9,839 |
| `/static/css/app.css` | 12,188 |
| `/static/css/assessment.css` | 9,396 |
| `/static/css/dark-evidence-home.css` | 26,236 |
| `/static/css/design-tokens.css` | 1,541 |
| `/static/css/public-pages.css` | 17,998 |
| `/static/css/silver-evidence-public.css` | 41,459 |
| `/static/css/ui-components.css` | 3,044 |
| `/static/images/ui/enterprise-compute-space.webp` | 68,898 |
| `/static/images/ui/home-ai-core-silver.webp` | 66,644 |
| `/static/images/ui/home-knowledge-system.webp` | 197,062 |
| `/static/images/ui/home-path-system.webp` | 133,698 |
| `/static/images/ui/industrial-data-infrastructure.webp` | 114,856 |
| `/static/images/ui/public-delivery-system.webp` | 146,028 |
| `/static/images/ui/public-industry-operations.webp` | 143,362 |
| `/static/images/ui/public-trust-evidence.webp` | 88,550 |
| `/static/js/app.js` | 6,904 |
| `/static/js/assessment.js` | 32,907 |
| `/static/js/guided_story.js` | 3,711 |
| `/static/js/public_reveal.js` | 1,714 |
| `/static/logo.png` | 249,157 |

## Loading contract

Shipped decorative and logo images declare intrinsic dimensions. The first decorative
hero on home, public catalog lists/details, about, case, resource, and announcement
pages is explicitly eager and high priority. Home artwork below the first hero remains
lazy-loaded with asynchronous decoding. The navigation logo uses its real 859 by 1066
pixel intrinsic ratio and asynchronous decoding. Content-authored media is excluded
from this shipped-decoration rule because its dimensions and lifecycle are governed by
the media/content contract rather than a fixed template asset.
