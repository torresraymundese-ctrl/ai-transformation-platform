# Stage 5A Content Catalog and Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the maintainable industry, scenario, service-package, case, and resource catalog with revision-safe publishing, media handling, public list/detail pages, and a non-destructive legacy-content migration workflow.

**Architecture:** Keep the Stage 4 assessment catalog as the single business identity source and attach revisioned public content to those stable records. A repository-owned publishing state machine atomically promotes validated drafts, while domain-specific extension/junction tables preserve real foreign keys. Public and admin Blueprints remain HTTP adapters; validation, transactions, media storage, migration classification, and read models live in focused modules.

**Tech Stack:** Python 3.12, Flask, SQLite/WAL, Jinja, vanilla JavaScript, pytest, BeautifulSoup, existing application factory/security/audit infrastructure.

**Spec:** `docs/superpowers/specs/2026-08-24-content-operations-design.md`

**Required execution order:** Task 0 is the safety gate. Then execute Tasks 1–12 in order; no task may bypass its predecessor's review. In particular, legacy conversion waits for case/resource editors. Because the 27 legacy cases are not trustworthy enough to remain public, their `/cases` ownership cuts over early in Task 8; resource/announcement navigation and all remaining compatibility cutover wait for conversion and Task 11. 5B waits until Task 12 is reviewed CLEAN.

## Global Constraints

- Execute only in the existing isolated worktree on branch `codex/ai-platform-2.0-core`; do not connect to production or start Nginx.
- Preserve the current 4 industries, 13 scenarios, 6 service packages, all historical assessments, immutable report snapshots, appointments, leads, privacy records, and analytics events.
- Use explicit Asia/Shanghai timestamps; do not add `datetime('now','localtime')` defaults for new business rows.
- Public content state is exactly `draft → published → archived`; published and archived revisions are never edited in place.
- Assessment-critical fields remain read-only in 5A. Ordinary content forms cannot change thresholds, ROI coefficients, budgets, service scope, deliverables, acceptance criteria, or rule versions.
- All admin writes require the existing authenticated Session, CSRF protection, exact server validation, private/no-store responses, and minimal audit records.
- Scraped or migrated content is never auto-published. No legacy row is physically deleted in Stage 5.
- Use repository/service-owned transactions with `BEGIN IMMEDIATE` for publish/archive/due-job claims; Blueprints contain no SQL.
- Store new business timestamps as second-precision `YYYY-MM-DD HH:MM:SS` Asia/Shanghai wall time produced by one injected helper; never use a SQLite `localtime` default. SQL comparisons use that exact normalized format.
- A stable `content_group` owns entry type, core identity, and canonical slug. Publishing a deliberate slug change creates an alias from the old slug; request `Host` is never used to build canonical URLs.
- Scenario maturity is an explicit editorial relation using the existing four codes `explore/pilot/scale/collaborate`; it is not inferred at request time from mutable score thresholds.
- Active legacy announcements become a separate `announcement` content type and draft extension; they are not disguised as one of the five resource types. Expired announcements remain archived review items.
- “Safe file” means the application never executes it and never serves active content inline. It does not claim arbitrary office/PDF files are intrinsically harmless.
- Use `apply_patch` for source edits and TDD RED before production changes. After every numbered task: run its focused review, resolve all P0–P2, record exact RED/GREEN/related evidence plus commit in `D:/Codex干活/企业AI转型平台2.0升级/升级任务卡.md`, and only then start the next task.

---

### Task 0: Disable the legacy direct-publish scraper before any content work

**Files:**
- Create: `tests/test_scraper_safety_gate.py`
- Modify: `blueprints/admin/content.py`
- Modify: `scraper.py`
- Modify: `templates/admin/index.html`
- Modify: `tests/conftest.py`
- Modify: `tests/test_rate_limits_and_audit.py`

**Interfaces:**
- Consumes: existing `/admin/scrape`, `scraper.run_scraper`, shared admin auth/CSRF/audit.
- Produces: a temporary fail-closed `410` response with fixed code `ingestion_queue_not_ready`; zero network requests and zero writes. Task 14 in the 5B plan replaces this gate with the reviewed queue.

- [ ] **Step 1: Write the safety regression**

```python
def test_legacy_scrape_is_disabled_without_network_or_writes(
    admin_client, monkeypatch, db
):
    network = Mock(side_effect=AssertionError("network must remain unused"))
    monkeypatch.setattr(requests, "get", network)
    before = legacy_article_rows(db)
    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})
    assert response.status_code == 410
    assert response.get_json()["error"] == "ingestion_queue_not_ready"
    assert legacy_article_rows(db) == before
    network.assert_not_called()
```

Cover anonymous redirect, CSRF rejection, no remote URL/body/error disclosure, the old admin button becoming a disabled explanatory state, and direct `run_scraper()` failing closed without calling a source adapter. Add the shared `db(client)` fixture here (not in a later task): it opens the already monkeypatched disposable database with foreign keys enabled, yields it, and always closes it. All later tasks reuse this fixture.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_scraper_safety_gate.py tests/test_rate_limits_and_audit.py -q`

Expected: FAIL because the current route still performs network work and writes legacy articles.

- [ ] **Step 3: Remove every direct-publish path and return the fixed unavailable result**

Delete/retire `save_article`, `add_curated_articles`, and any helper that can insert a legacy article from a fetch result. Keep only source metadata required by the future 5B adapter. The temporary route remains authenticated, CSRF-protected, audited and private/no-store.

- [ ] **Step 4: Run GREEN, inspect the diff, and commit**

```bash
..\..\.venv\Scripts\python.exe -m pytest tests/test_scraper_safety_gate.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py -q
git add scraper.py blueprints/admin/content.py templates/admin/index.html tests/conftest.py tests/test_scraper_safety_gate.py tests/test_rate_limits_and_audit.py
git commit -m "fix: disable direct scraper publication"
```

---

### Task 1: Add the revisioned content schema

**Files:**
- Create: `migrations/006_content_catalog.sql`
- Create: `tests/test_content_migrations.py`
- Modify: `tests/test_v2_migrations.py`
- Modify: `tests/test_app_factory_and_migrations.py`

**Interfaces:**
- Consumes: `migrations.apply_migrations(connection)` and the current `001`–`005` schema.
- Produces: stable `content_groups`; revisioned `content_items`; blocks and industry/scenario/service/case/resource/announcement extensions; explicit maturity relations; media; slug aliases; six domain junction tables; transaction-owned `content_audit_events`; and idempotent legacy review/mapping rows.

- [ ] **Step 1: Write migration tests against an empty database and a populated V2 database**

```python
EXPECTED_CONTENT_TABLES = {
    "content_groups", "content_items", "content_blocks", "industry_content",
    "scenario_content", "service_content", "case_content",
    "case_metrics", "resource_content", "announcement_content",
    "content_maturity_levels", "media_assets", "content_slug_aliases",
    "scenario_cases", "scenario_resources", "service_cases",
    "service_resources", "industry_cases", "industry_resources",
    "content_audit_events", "legacy_content_reviews",
    "legacy_content_mappings",
}

def test_content_migration_is_idempotent_and_preserves_v2_catalog(client, db):
    models.init_db()
    before = frozen_catalog_counts(db)
    models.init_db()
    assert EXPECTED_CONTENT_TABLES <= database_tables(db)
    assert frozen_catalog_counts(db) == before == (4, 13, 6)

def test_database_rejects_two_drafts_or_two_published_in_one_group(db):
    insert_content_item(db, group="industry:manufacturing", revision=1,
                        status="published")
    with pytest.raises(sqlite3.IntegrityError):
        insert_content_item(db, group="industry:manufacturing", revision=2,
                            status="published")
```

- [ ] **Step 2: Run the migration tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_migrations.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because migration `006` and the content tables do not exist.

- [ ] **Step 3: Implement `006_content_catalog.sql` with exact constraints**

Create `content_groups` with immutable `entry_type`, nullable-but-unique core identity fields, canonical slug and explicit timestamps. Create `content_items` with `content_group_id`, copied-and-trigger-checked `entry_type`, positive `revision_number`, copied slug, title/summary/SEO fields, status check, scheduled/published/archive timestamps, positive `lock_version`, and explicit timestamps. Add:

```sql
UNIQUE(content_group_id, revision_number);
CREATE UNIQUE INDEX one_draft_content_revision
ON content_items(content_group_id) WHERE status='draft';
CREATE UNIQUE INDEX one_published_content_revision
ON content_items(content_group_id) WHERE status='published';
CREATE UNIQUE INDEX one_public_slug_per_type
ON content_items(entry_type, slug) WHERE status='published';
```

Create domain extension tables with `UNIQUE(content_item_id)` and real foreign keys to `industries`, `scenarios`, and `services`. Require exactly one extension matching each item's entry type in publication validation. Freeze these schema contracts in migration tests:

- `case_content`: verification code, anonymized flag, basis type, private basis reference, optional normalized public-source URL plus `source_url_sha256`, `source_check_code`, `source_checked_at`, `source_check_expires_at`, and `source_check_url_sha256`, verified/review-confirmed flags and Shanghai verification time;
- `case_metrics`: case item FK, name, before value, after value, unit, statistical period, evidence explanation and sort order;
- `resource_content`: exact five-type check, original/sourced flag, source name, normalized source URL plus the same URL/check/checksum/expiry binding fields, original publish time, copyright notice and attachment media FK. Stage 5 public publishing remains HTTPS-only. A later reviewed HTTP ingestion policy may fetch a private candidate, but it does not authorize an HTTP public link;
- `announcement_content`: validity start/end and validated CTA URL;
- `content_items.share_image_media_id` and `content_blocks.media_asset_id`: real media FKs; block validation restricts media use by block type;
- `content_slug_aliases`: old slug to stable group with uniqueness checked against aliases and every group's current canonical slug.

Create six named junction tables rather than a polymorphic relation table. Each stores the owning revision item ID, target stable content-group ID and sort order; public reads resolve the target group's current published revision so a target revision replacement cannot strand relations. Publication validates the exact target type/status. Create `content_maturity_levels` with exact codes `explore/pilot/scale/collaborate`. Create `content_blocks` with this exact type allowlist:

```sql
CHECK(block_type IN ('heading','rich_text','image_text','metric','steps','download','cta'))
```

Create `media_assets` with this frozen lifecycle contract: immutable random `storage_name`; bounded `display_name`; detected MIME; byte size; SHA-256; `scan_result_code`/`scan_checked_at`; exact status `pending/ready/archived`; and explicit `created_at/ready_at/archived_at/updated_at`. Only `pending→ready`, `pending→archived`, and unreferenced `ready→archived` are legal. Once ready, storage name, MIME, byte size, hash, scan result and ready time cannot change. Direct-SQL triggers reject archiving a ready asset referenced by any currently published share image, block, or resource attachment. `storage_name` is globally unique; SHA-256 uses a partial unique index only for `status IN ('pending','ready')`, so an active duplicate reuses its existing row while bytes whose irrecoverable/missing row was archived may be uploaded into a new pending row. Migration/media tests cover active duplicate reuse and same-byte re-upload after archive. Migration tests inspect every column, CHECK, transition trigger, identity freeze and published-reference guard.

The shared disposable database path and `db` connection fixture already exist from Task 0. Extend them only if migration assertions need helpers; never assign `models.DB_PATH` directly in a test, and keep Tasks 1–3 independent of the media-root fixture introduced later.

Create `legacy_content_reviews` with unique `(source_table, source_id)`, bounded title digest/summary, current `source_checksum`, `proposed_action` check `keep/clean/archive/delete_later`, nullable `decision_action` with the same check, `decision_at`, `decision_source_checksum`, `source_state` check `reachable/unreachable/invalid/missing/unchecked`, generic `source_check_code`, `source_checked_at`, `source_check_expires_at`, `check_source_checksum`, `review_stale_at`, target-preview JSON, `source_url_display` containing only normalized scheme/IDNA host/path, and `source_url_sha256` over the full normalized source URL. Neither URL field stores credentials, fragment or query text. A decision/check is current only when its stored checksum equals the current source checksum and its expiry is valid. Create `legacy_content_mappings` with the same unique source identity, source checksum and target group/item foreign keys. Stage 5 never cascades either table into a physical legacy delete.

- [ ] **Step 4: Run migration, catalog, and app-factory tests**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_migrations.py tests/test_v2_migrations.py tests/test_assessment_catalog.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS; repeated startup retains exactly 4/13/6 core identities and all legacy sentinel rows.

- [ ] **Step 5: Review and commit**

```bash
git add migrations/006_content_catalog.sql tests/test_content_migrations.py tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py
git commit -m "feat: add revisioned content catalog schema"
```

---

### Task 2: Produce a deterministic local legacy inventory and decision artifact

**Files:**
- Create: `legacy_content_migration.py`
- Create: `seed_data/legacy_content_mapping_rules.json`
- Create: `tests/test_legacy_content_migration.py`
- Modify: `manage.py`
- Modify: `docs/testing/core-assessment-report.md`

**Interfaces:**
- Consumes: legacy `services`, `cases`, `articles`, `announcements`; `legacy_content_reviews` from Task 1.
- Produces: a frozen `ReviewItem` with title summary, checksum, proposed action/reason, target type/group, `source_state="unchecked"`, human-confirmation fields and target preview; `inventory_legacy_content(db)`; `record_legacy_inventory(db, items)`; CLI `inventory-content [--format jsonl] [--record]`. Network source checks and conversion occur only in Task 10.

- [ ] **Step 1: Write classification and non-destruction tests**

```python
def test_unverified_seed_case_is_never_publishable_or_deleted(db):
    case_id = insert_legacy_case(db, title="某企业提升 99%")
    items = inventory_legacy_content(db)
    item = next(row for row in items if row.source_table == "cases"
                and row.source_id == case_id)
    assert (item.action, item.reason_code) == (
        "delete_later", "case_source_or_metric_unverified")
    assert db.execute("SELECT title FROM cases WHERE id=?", (case_id,)).fetchone()

def test_inventory_apply_only_records_review_rows(db):
    before = legacy_table_counts(db)
    count = record_legacy_inventory(db, inventory_legacy_content(db))
    assert count > 0
    assert legacy_table_counts(db) == before
```

Also cover six known V2 service codes proposed as `keep`, unmappable legacy services as `archive`, all unverified cases as `delete_later`, articles with a syntactically valid public URL as `clean/source_state=unchecked`, and every legacy announcement requiring an explicit human `valid_from/valid_until` decision because the old table has no expiry field. An announcement without that decision is only `archive` or a non-publishable preview; never infer “active/expired” from age. Verify stable reason codes, exact target previews, output containing no contacts/config/secrets, and both rerun cases: the same source checksum may refresh derived preview fields but never overwrites an operator decision or source check; a changed checksum records `review_stale_at` and makes both prior decision/check unusable without silently inheriting either one.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_legacy_content_migration.py -q`

Expected: FAIL because the inventory module and CLI command do not exist.

- [ ] **Step 3: Implement deterministic classification**

Use a frozen dataclass and pure classifiers:

```python
@dataclass(frozen=True)
class ReviewItem:
    source_table: str
    source_id: int
    source_checksum: str
    title_summary: str
    proposed_action: Literal["keep", "clean", "archive", "delete_later"]
    reason_code: str
    target_type: str | None
    target_group: str | None
    source_state: Literal[
        "reachable", "unreachable", "invalid", "missing", "unchecked"
    ]
    required_confirmations: tuple[str, ...]
    target_preview: Mapping[str, object] | None

def inventory_legacy_content(db) -> tuple[ReviewItem, ...]: ...
def record_legacy_inventory(db, items: tuple[ReviewItem, ...]) -> int: ...
```

Do not perform network requests during this task. A missing/unparseable source URL fails closed to `archive` for articles and `delete_later` for unverifiable cases. The CLI defaults to zero-write JSONL dry-run. `--record` inserts/updates review rows in one transaction but does not mutate source tables or create target content. Its UPSERT branches on the checksum rules above; it never resets human/check state merely because inventory ran again. The checked-in mapping rules are data, not executable expressions, and accept only the four legacy tables and known target types/groups.

- [ ] **Step 4: Run focused and legacy-content regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_legacy_content_migration.py tests/test_validation_and_errors.py tests/test_smoke.py -q`

Expected: PASS and the existing public pages remain functional until their queries move to the new published catalog in later tasks.

- [ ] **Step 5: Commit**

```bash
git add legacy_content_migration.py seed_data/legacy_content_mapping_rules.json manage.py tests/test_legacy_content_migration.py docs/testing/core-assessment-report.md
git commit -m "feat: inventory legacy content safely"
```

---

### Task 3: Implement atomic revision publishing and due publishing

**Files:**
- Create: `content_contracts.py`
- Create: `content_clock.py`
- Create: `content_validation.py`
- Create: `source_url_checker.py`
- Create: `publishing_repository.py`
- Create: `publishing_service.py`
- Create: `tests/test_content_validation.py`
- Create: `tests/test_source_url_checker.py`
- Create: `tests/test_content_publishing.py`
- Modify: `manage.py`

**Interfaces:**
- Consumes: `content_items`, `content_blocks`, domain extensions, `models.get_db()`.
- Produces: exact `ContentDraft`/block/relation contracts; reusable `PinnedHttpTransport` plus the one-MiB source-check wrapper; caller-owned insert/update primitives; create/save/copy/schedule/publish/archive/public APIs; and `publish_due_content`; CLI `publish-due-content`.

- [ ] **Step 1: Write state-machine, transaction, clock, and concurrency tests**

```python
def test_publish_replaces_old_revision_atomically(db):
    first = published_revision(db, group="scenario:mfg_knowledge_assistant")
    second = draft_revision(db, group=first.revision_group, revision=2)
    result = publish_revision(second.id, now=SHANGHAI_NOW)
    assert result.published_id == second.id
    assert statuses(db, first.id, second.id) == ("archived", "published")

def test_failed_validation_keeps_old_revision_public(db):
    first = published_revision(db)
    invalid = draft_revision(db, seo_title="")
    with pytest.raises(ContentValidationError):
        publish_revision(invalid.id, now=SHANGHAI_NOW)
    assert statuses(db, first.id, invalid.id) == ("published", "draft")
```

Cover invalid transitions, stale `lock_version`, deep-copy from either published or archived revisions (draft copy rejected), blocks/extensions/metrics/media/relations, two SQLite connections allocating revision numbers or publishing one group, rollback after domain-relation/audit failure, caller-owned update rollback, explicit future scheduling that keeps the old revision public before the exact due second, schedule refusal when a required source check expires before `publish_at`, due boundaries with the host clock forced to UTC, repeated due runs, and a due batch where one stale/invalid item remains draft with a fixed safe failure code while a second valid item still publishes. Source tests cover exact compressed and decompressed byte boundaries—1,048,576 accepted and 1,048,577 rejected—plus redirect-to-unlisted-host rejection before DNS/socket work. Also cover slug rename alias collision/301, public lookup excluding draft/future/archived rows, source URL changes clearing all prior check fields, and publication proving `source_check_url_sha256 == source_url_sha256` and unexpired success while never refreshing a check inside its transaction.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_validation.py tests/test_source_url_checker.py tests/test_content_publishing.py -q`

Expected: FAIL because publishing modules and command are absent.

- [ ] **Step 3: Implement repository-owned transactions**

Freeze exact validation limits before route work: slug 80 ASCII characters; title 120; summary/SEO title/SEO description 300/60/160; at most 40 blocks; block title/body/settings 120/20,000/2,000 bytes; at most 50 relations; no nesting deeper than two; exact allowed settings keys per block; only server-validated internal paths or `https` links for CTAs. Sanitization runs before persistence and escaped/allowlisted rendering remains the output boundary.

Implement the reusable transport before case/resource editors. `PinnedHttpTransport.fetch(url, *, allowed_hosts, allowed_schemes, max_compressed_bytes, max_decompressed_bytes, allowed_content_types)` owns DNS resolution, the pinned-IP socket/TLS connection, original Host/SNI, actual peer-IP verification, proxy disabling, bounded streaming and at most three redirects. `allowed_hosts` is a frozen set of exact normalized IDNA hosts—no wildcards. Before DNS or socket work for the initial URL and every redirect, require both scheme and host membership, then rerun the complete IP/peer checks. It returns a bounded immutable result containing only final normalized URL, status, detected content type and bytes or a generic failure code. It rejects userinfo/nonstandard ports, excessive DNS answers, and any private/loopback/link-local/reserved/mixed public-private IPv4/IPv6 set. It never hands a validated URL back to ordinary `requests` for a second fetch.

`check_source_url(url, transport, now)` is the HTTPS-only one-MiB wrapper used by 5A and derives `allowed_hosts` as exactly the submitted normalized host; cross-host redirects require the operator to submit the final URL. An explicitly reviewed 5B registry may supply its exact host set, pass `http` in `allowed_schemes`, and raise both byte bounds to two MiB. Enforce separate connect/read timeouts. Return/store normalized URL, `source_url_sha256`, generic check code, `source_check_url_sha256`, checked time and seven-day expiry. Saving a changed URL atomically clears the old check tuple; publication requires exact hash equality and current expiry. Network I/O always finishes before a publication transaction.

Expose exact public and composition interfaces:

```python
@dataclass(frozen=True)
class PublishResult:
    published_id: int
    archived_id: int | None

def insert_content_draft(db: sqlite3.Connection, draft: ContentDraft,
                         *, actor: str, now: datetime) -> int: ...
def update_content_draft(db: sqlite3.Connection, content_id: int,
                         expected_lock_version: int, draft: ContentDraft,
                         *, actor: str, now: datetime) -> int: ...
def refresh_content_source_check(content_id: int, expected_lock_version: int,
                                 expected_url_sha256: str, *, actor: str,
                                 transport: PinnedHttpTransport,
                                 now: datetime) -> SourceCheckResult: ...
def create_content_draft(draft: ContentDraft, *, actor: str,
                         now: datetime | None = None) -> int: ...
def save_content_draft(content_id: int, expected_lock_version: int,
                       draft: ContentDraft, *, actor: str,
                       now: datetime | None = None) -> int: ...
def copy_revision(content_id: int, *, actor: str,
                  now: datetime | None = None) -> int: ...
def schedule_content(content_id: int, expected_lock_version: int,
                     publish_at: datetime, *, actor: str,
                     now: datetime | None = None) -> ScheduleResult: ...
def publish_content(content_id: int, expected_lock_version: int,
                    *, actor: str, now: datetime | None = None) -> PublishResult: ...
def archive_content(content_id: int, expected_lock_version: int,
                    *, actor: str, now: datetime | None = None) -> None: ...
def publish_due_content(*, actor: str = "publish_due_content",
                        now: datetime | None = None) -> PublishDueResult: ...
def get_public_revision(entry_type: str, slug: str,
                        now: datetime) -> sqlite3.Row | None: ...
```

`insert_content_draft(db, ...)` and `update_content_draft(db, ...)` never commit. The latter reloads draft state plus exact lock version and is the only primitive Task 10 may use for an approved merge; the ordinary `save_content_draft` wrapper opens `BEGIN IMMEDIATE`, calls it and commits. Public wrappers own their transactions. Every update changes extension/block/relation rows and its domain audit atomically.

`refresh_content_source_check` first reads the draft's bounded HTTPS URL, lock version and URL hash in a short read connection, performs `check_source_url` after closing that connection, then opens `BEGIN IMMEDIATE` and reloads all three values before writing the generic result/check hash/times, incrementing `lock_version`, writing the audit and committing once. A concurrent edit, second refresh, changed URL or stale form lock returns a generic conflict and writes nothing; a two-request race test proves only one refresh can consume the original version. Task 8 and Task 9 expose this same service through authenticated CSRF POST buttons with `expected_lock_version` and `expected_url_sha256`; no Blueprint performs network I/O while holding a transaction.

`schedule_content` requires a future Shanghai time. If the aggregate has a required source check, `source_check_expires_at` must be at or after `publish_at`; otherwise scheduling fails closed. It records `content_scheduled` and truthfully returns a scheduled result without archiving the old revision. `publish_content` requires `publish_at` absent or due, reloads and validates the complete aggregate, writes `content_published`, archives the old public revision and publishes the new one before one commit. The due command first snapshots ordered candidate IDs, then processes each in its own `BEGIN IMMEDIATE` transaction. A validation failure clears that item's due time, keeps it draft, writes only an allowlisted `content_due_failed` reason and continues; it cannot block later valid items. CLI prints counts, IDs and fixed reason codes only. Request-level `admin_audit_logs` remains supplementary and is not used as the domain transaction guarantee.

- [ ] **Step 4: Run focused plus transaction/security regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_validation.py tests/test_source_url_checker.py tests/test_content_publishing.py tests/test_rate_limits_and_audit.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS with exact-once due publication and no database locks after rejected transitions.

- [ ] **Step 5: Commit**

```bash
git add content_contracts.py content_clock.py content_validation.py source_url_checker.py publishing_repository.py publishing_service.py manage.py tests/test_content_validation.py tests/test_source_url_checker.py tests/test_content_publishing.py
git commit -m "feat: publish immutable content revisions"
```

---

### Task 4: Add secure media storage, controlled downloads, and recovery

**Files:**
- Create: `media_service.py`
- Create: `media_validation.py`
- Create: `blueprints/media.py`
- Create: `blueprints/admin/media.py`
- Create: `templates/admin/media.html`
- Create: `tests/test_media_service.py`
- Create: `tests/test_media_http.py`
- Modify: `requirements.txt`
- Modify: `app.py`
- Modify: `wsgi.py`
- Modify: `ops/env/ai-platform.env.example`
- Modify: `manage.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `templates/components/admin_navigation.html`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: Flask `FileStorage`, `media_assets`, 5A content references and admin security hooks.
- Produces: `store_media`, `archive_media`, controlled admin preview, published inline-image and attachment-download routes, and dry-run-first `recover-media-storage` reconciliation.

- [ ] **Step 1: Write content-schema and hostile-upload tests**

```python
@pytest.mark.parametrize("name,mime,data", [
    ("x.svg", "image/svg+xml", b"<svg><script/></svg>"),
    ("x.jpg", "image/jpeg", b"not-a-jpeg"),
    ("x.html", "text/html", b"<script>"),
])
def test_media_rejects_extension_mime_or_signature_mismatch(
    admin_client, name, mime, data
):
    response = upload_media(admin_client, name, mime, data)
    assert response.status_code == 400
    assert media_directory_is_empty()
```

Cover exact JPEG/PNG/WebP/PDF/DOCX/XLSX extension+declared MIME+detected signature agreement, 8 MiB image and 20 MiB attachment limits, 40-megapixel/decoded-dimension image bombs, image EXIF/metadata removal, and the explicit document policy: PDF/DOCX/XLSX with personal/custom metadata are rejected rather than silently rewritten. Cover OOXML macro/embedded-object/external-relationship rejection plus ZIP member-count, cumulative-uncompressed-size and compression-ratio bombs; PDF JavaScript/actions/embedded-file/encryption rejection; path traversal names; SHA-256 duplicate reuse; database/rename/crash cleanup; orphan/missing/pending reconciliation; direct-SQL referenced-media archive rejection; CSRF/auth/audit; and cache/download headers.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_media_service.py tests/test_media_http.py -q`

Expected: FAIL because media and block-validation modules/routes do not exist.

- [ ] **Step 3: Implement exact validators and atomic file/database handling**

Add config values:

```python
"MEDIA_UPLOAD_ROOT": os.environ.get("AI_PLATFORM_MEDIA_ROOT"),
"MEDIA_IMAGE_MAX_BYTES": 8 * 1024 * 1024,
"MEDIA_ATTACHMENT_MAX_BYTES": 20 * 1024 * 1024,
"MEDIA_IMAGE_MAX_PIXELS": 40_000_000,
"MEDIA_OOXML_MAX_MEMBERS": 1024,
"MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES": 100 * 1024 * 1024,
"MEDIA_OOXML_MAX_COMPRESSION_RATIO": 20,
"MEDIA_PDF_MAX_PAGES": 500,
```

Use `Pillow` for bounded decode/re-encode of JPEG/PNG/WebP and metadata removal. For DOCX/XLSX, inspect the ZIP before extraction and reject more than 1,024 members, more than 100 MiB cumulative uncompressed bytes, any member/aggregate ratio over 20:1, traversal/duplicate names, macros, embedded objects, external relationships, custom properties, or non-empty creator/last-modifier/company personal metadata. For PDF, use `pypdf`, cap at 500 pages, and reject encryption, parse failures, metadata, active actions, JavaScript and embedded files. Office/PDF bytes are validated and retained, not claimed to be rewritten; the admin must also affirm a fixed metadata/privacy review checkbox. Recalculate detected signature, size and SHA-256 from the final image rewrite or final accepted document bytes before persistence.

Generate a random storage name with a server-selected extension after detection; never join with the submitted filename. Stream to a temporary file under the configured root, validate outside a long database transaction, insert a `pending` row, atomically rename, then mark ready with failure compensation. `recover-media-storage` defaults to dry-run and reports only asset IDs/statuses; `--apply` archives irrecoverable pending/missing records but never deletes files or rows. It obeys the Task 1 status/identity triggers rather than repairing around them.

Set Flask's transport ceiling to 20 MiB plus multipart overhead, then add an early request-length guard that preserves the existing 1 MiB limit for every non-media endpoint; only the authenticated media upload route may reach 20 MiB. Tests always inject an isolated temporary root. Development defaults explicitly to repository `data/media`. Only the production WSGI factory requires an environment-provided root that resolves under `/opt/ai-platform/data/media`; module import and test-app creation must not fail before configuration is injected. Update `wsgi.py` and the environment example accordingly.

Files never live under `/static`. `/media/<id>/image` serves only re-encoded JPEG/PNG/WebP referenced by a currently published block or share-image FK, with server-selected MIME, inline disposition, digest ETag, `nosniff` and cache headers safe for a content-addressed public asset. `/media/<id>/download` serves only published PDF/DOCX/XLSX references with attachment disposition. Draft previews use an authenticated admin route with `private, no-store`; missing/archived/unreferenced assets return generic 404. Tests prove `<img>` and `og:image` use the image route while download blocks/resources use the attachment route.

- [ ] **Step 4: Run media, security, audit, and upload-size tests**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_media_service.py tests/test_media_http.py tests/test_validation_and_errors.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py -q`

Expected: PASS; no executable upload is stored and every successful/rejected admin POST is auditable without filenames or content in the audit row.

- [ ] **Step 5: Commit**

```bash
git add media_service.py media_validation.py blueprints/media.py blueprints/admin/media.py templates/admin/media.html requirements.txt app.py wsgi.py ops/env/ai-platform.env.example manage.py blueprints/admin/__init__.py templates/components/admin_navigation.html tests/conftest.py tests/test_media_service.py tests/test_media_http.py
git commit -m "feat: manage safe content media"
```

---

### Task 5: Bootstrap and administer the 4/13/6 core public catalog

**Files:**
- Create: `catalog_content_repository.py`
- Create: `content_seed.py`
- Create: `seed_data/content_catalog_v1.json`
- Create: `blueprints/admin/catalog.py`
- Create: `templates/admin/catalog_list.html`
- Create: `templates/admin/catalog_edit.html`
- Create: `templates/admin/_content_blocks.html`
- Create: `templates/admin/_content_relations.html`
- Create: `static/js/content_editor.js`
- Create: `tests/test_content_seed.py`
- Create: `tests/test_catalog_content_admin.py`
- Create: `pagination.py`
- Create: `tests/test_pagination.py`
- Create: `tests/js/content_editor_runtime.test.js`
- Modify: `models.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `blueprints/admin/content.py`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: stable core rows, the dependency-free checked-in content seed, publishing APIs from Task 3, and block/media validation from Task 4. It must not import a Flask Blueprint for labels or seed data.
- Produces: idempotent `seed_content_defaults(db, now)`; shared immutable `Page[T]`/`PageRequest` and safe-default parser; paginated catalog admin projections; choice-first block/relation editor; admin routes `/admin/catalog/<kind>` and `/admin/catalog/<kind>/<int:core_id>`.

- [ ] **Step 1: Write exact identity, read-only-field, and admin-flow tests**

```python
def test_seed_creates_one_draft_identity_without_overwriting_operator_work(db):
    seed_content_defaults(db, now=SHANGHAI_NOW)
    operator_edit_one_draft(db)
    seed_content_defaults(db, now=SHANGHAI_NOW)
    assert content_group_counts(db) == {
        "industry": 4, "scenario": 13, "service": 6
    }
    assert operator_edit_is_unchanged(db)

def test_content_form_cannot_mutate_assessment_critical_fields(admin_client, db):
    before = scenario_rule_tuple(db, "mfg_knowledge_assistant")
    response = post_catalog_content(
        admin_client, "scenario", rule_overrides={"minimum_data": "0"}
    )
    assert response.status_code == 400
    assert scenario_rule_tuple(db, "mfg_knowledge_assistant") == before
```

Cover exact slug stability, Chinese titles from the checked-in seed, neutral summaries with no fabricated metrics, explicit maturity choices, choice-based relationships, unknown-field rejection, block bounds/reorder, optimistic-lock `409` with submitted values preserved, draft-save/review/publish/archive, admin authentication/CSRF/transaction audit, repeat init after edit/archive, and all 4/13/6 groups appearing exactly once. Add a dependency guard proving `content_seed.py` imports no `blueprints.*`/Flask module and that the seed's exact industry/scenario/service code sets equal the frozen assessment catalog sets.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_catalog_content_admin.py -q`

Expected: FAIL because catalog content bootstrap, repository, routes, and templates are absent.

- [ ] **Step 3: Implement deterministic bootstrap and choice-first admin forms**

`models.init_db()` calls `seed_content_defaults()` only after `assessment.seed.seed_v2_defaults()`; do not modify the frozen assessment seed. Use stable groups/slugs:

```python
group = f"{kind}:{core_row['code']}"
slug = core_row["code"].replace("_", "-")
```

`seed_data/content_catalog_v1.json` is the only narrative/Chinese-label source used by `content_seed.py`; the assessment Blueprint may consume a future dependency-free catalog constants module, but the seed may never import the Blueprint. The JSON contains reviewed-neutral narrative drafts, explicit maturity relations and a seed version/source marker. It creates groups and drafts only; it never silently publishes, revives archived content, overwrites an operator draft or creates a second draft. Tests explicitly publish every 4/13/6 draft through the same admin/service path before public-page acceptance. Do not seed customer claims, case metrics, legal text or invented resource counts.

Create the pagination contract here, once:

```python
T = TypeVar("T")

@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    page: int
    per_page: int
    total: int
    total_pages: int

@dataclass(frozen=True)
class PageRequest:
    page: int
    per_page: Literal[20, 50]

def parse_pagination(values) -> PageRequest: ...
```

Invalid/negative/overflow pages become page 1, unsupported page sizes become 20, and an empty result is exactly `total=0,total_pages=0,items=()`.

Admin GET presents current public content and either the existing draft or a copy-on-edit draft. POST accepts only narrative/SEO/block/relation fields; reject every unknown form key except CSRF. Industry/scenario/service core identities and assessment-critical thresholds, ROI values, budgets, scope, deliverables, acceptance and support remain read-only in 5A. Publishing delegates to Task 3 and never issues direct SQL from the Blueprint. The old direct-write case editor remains a migration notice/410 until Task 8; old article/announcement editors remain so until Task 9.

- [ ] **Step 4: Run catalog, assessment, report, and admin regressions**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests/test_content_seed.py tests/test_pagination.py tests/test_catalog_content_admin.py tests/test_assessment_catalog.py tests/test_assessment_v2_api.py tests/test_reporting.py tests/test_rate_limits_and_audit.py -q
node --test tests/js/content_editor_runtime.test.js
```

Expected: PASS with the Stage 4 config/matching/report output unchanged.

- [ ] **Step 5: Commit**

```bash
git add catalog_content_repository.py content_seed.py seed_data/content_catalog_v1.json pagination.py blueprints/admin/catalog.py blueprints/admin/content.py templates/admin/catalog_list.html templates/admin/catalog_edit.html templates/admin/_content_blocks.html templates/admin/_content_relations.html static/js/content_editor.js models.py blueprints/admin/__init__.py templates/components/admin_navigation.html tests/test_content_seed.py tests/test_pagination.py tests/test_catalog_content_admin.py tests/js/content_editor_runtime.test.js
git commit -m "feat: administer core catalog content"
```

---

### Task 6: Publish industry and scenario list/detail experiences

**Files:**
- Create: `blueprints/public_catalog.py`
- Create: `templates/industries.html`
- Create: `templates/industry_detail.html`
- Create: `templates/scenarios.html`
- Create: `templates/scenario_detail.html`
- Create: `tests/test_public_catalog.py`
- Modify: `catalog_content_repository.py`
- Modify: `app.py`
- Modify: `ops/env/ai-platform.env.example`
- Modify: `tests/conftest.py`
- Modify: `tests/test_app_factory_and_migrations.py`

**Interfaces:**
- Consumes: Task 5 `Page[T]`/`PageRequest`, catalog public read models and current Shanghai time.
- Produces: `/industries`, `/industries/<slug>`, `/scenarios`, `/scenarios/<slug>` and exact filters `industry`, `department`, `maturity`, `page`, `per_page` using the shared pagination contract.

- [ ] **Step 1: Write public access, filter, SEO, and leak-boundary tests**

```python
INDUSTRY_REQUIRED_SECTIONS = {
    "overview", "business-pains", "departments", "sme-fit",
    "priority-scenarios", "service-packages", "assessment-cta",
}
SCENARIO_REQUIRED_SECTIONS = {
    "problem-boundary", "industries", "departments", "pains", "maturity",
    "prerequisites", "inputs", "outputs", "steps", "metrics", "risks",
    "timeline", "budget", "services", "assessment-cta",
}

def test_scenario_filters_are_intersection_not_union(client):
    response = client.get(
        "/scenarios?industry=manufacturing&department=production"
        "&maturity=explore"
    )
    page = BeautifulSoup(response.data, "html.parser")
    codes = {card["data-scenario-code"] for card in page.select("[data-scenario-code]")}
    assert codes == expected_scenario_intersection()

@pytest.mark.parametrize("status", ["draft", "archived"])
def test_nonpublished_detail_is_private_404(client, db, status):
    slug = content_with_status(db, "scenario", status)
    response = client.get(f"/scenarios/{slug}")
    assert response.status_code == 404
    assert slug.encode() not in response.data
```

For every published detail, assert its `data-content-section` set includes the corresponding required set above. Case/resource recommendation sections are optional and hidden when empty; every other approved section is required. Also cover future publish times, invalid GET filters—including `maturity=starting`—falling back to the documented safe default (empty enum filter, page 1, per-page 20), empty intersections with no unrelated fallback, all four explicit maturity codes, canonical links from trusted `PUBLIC_BASE_URL`, alias 301, titles/descriptions, no internal threshold/risk codes, no contacts/admin fields, pagination only 20/50 with stable `(sort_order, id)` ordering, current analytics/private-cache shell, keyboard labels, and primary free-assessment CTA. `PUBLIC_BASE_URL` is required and validated as an HTTPS origin (no credentials/query/fragment/path) by the production WSGI factory; tests/dev inject it explicitly, invalid/missing production values fail closed, and the environment example contains the key. Write/admin invalid enums remain 400 and do not reuse the lenient GET parser.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_public_catalog.py -q`

Expected: FAIL with 404 because the public catalog Blueprint/pages do not exist.

- [ ] **Step 3: Implement query DTOs and thin public routes**

Import the exact `Page`, `PageRequest` and `parse_pagination` created in Task 5; do not redefine or tuple-unpack them. Expose only the catalog read models:

```python
def public_industries(now: datetime) -> tuple[Mapping, ...]: ...
def public_industry(slug: str, now: datetime) -> Mapping | None: ...
def public_scenarios(filters: ScenarioFilters, page: PageRequest,
                     now: datetime) -> Page[ScenarioCard]: ...
def public_scenario(slug: str, now: datetime,
                    authority: ScenarioAuthority | None = None) -> Mapping | None: ...
```

Validate all filters against published core codes before querying. Scenario maturity filters join the explicit 5A relation and use AND semantics with industry/department. `ScenarioAuthority` loads the existing V2 critical fields in 5A and is the only seam 5B may replace with an active-version snapshot. Templates render structured values with fixed Chinese labels and use the existing shared shell/components; do not redesign visual tokens in this task.

- [ ] **Step 4: Run public, analytics/cache, and smoke regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_pagination.py tests/test_public_catalog.py tests/test_analytics.py tests/test_smoke.py tests/test_validation_and_errors.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS; public catalog responses keep the analytics Session and exact private/no-store policy.

- [ ] **Step 5: Commit**

```bash
git add blueprints/public_catalog.py catalog_content_repository.py templates/industries.html templates/industry_detail.html templates/scenarios.html templates/scenario_detail.html tests/conftest.py tests/test_public_catalog.py tests/test_app_factory_and_migrations.py app.py ops/env/ai-platform.env.example
git commit -m "feat: publish industry and scenario pages"
```

---

### Task 7: Publish complete service-package pages

**Files:**
- Create: `templates/service_packages.html`
- Create: `templates/service_package_detail.html`
- Create: `tests/test_public_services.py`
- Modify: `blueprints/public_catalog.py`
- Modify: `catalog_content_repository.py`
- Modify: `templates/services.html`

**Interfaces:**
- Consumes: six published services and deliverables; existing `scenario_services → scenarios → scenario_branches/scenario_departments/scenario_pains`; service-revision maturity relations; content revision/relations.
- Produces: `/service-packages`, `/service-packages/<slug>` and full service read model.

- [ ] **Step 1: Write completeness and version-isolation tests**

```python
REQUIRED_SECTIONS = {
    "industries", "departments", "maturity", "pains",
    "scope", "not-included", "deliverables", "implementation-steps",
    "prerequisites", "timeline", "budget", "acceptance", "support",
    "related-content", "pricing-disclaimer",
}

def test_every_public_service_detail_has_complete_delivery_structure(client):
    for slug in published_service_slugs():
        page = BeautifulSoup(client.get(f"/service-packages/{slug}").data,
                             "html.parser")
        assert {node["data-service-section"] for node in
                page.select("[data-service-section]")} >= REQUIRED_SECTIONS
```

Also assert integer/thousands budget formatting, weeks, fixed Chinese integration/category labels, no raw JSON/codes, empty optional related sections hidden, required relations blocking publish, report snapshots unchanged after narrative revision, draft/archived 404, and primary/secondary CTAs. Freeze an explicit expected industry/department/maturity/pain code set for each of the six seeded services and assert the rendered Chinese sets exactly match after deduplication and ordering.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_public_services.py -q`

Expected: FAIL because the new service-package routes/templates do not exist.

- [ ] **Step 3: Implement service read models and templates**

Use a `ServiceAuthority` read-model parameter whose 5A provider loads the existing published V2 service fields and related-scenario/facet codes as authoritative for report-critical sections. Content revisions may add headings, explanation blocks, media and relations, but cannot override min/max budgets, weeks, deliverables, exclusions, acceptance, support or the rule-derived scenario facets. Once an authority object is supplied, the public read model never falls back to global scenario/service tables. This boundary lets 5B replace only the authority provider with the active rule snapshot without rewriting public routes.

For the required public facets, resolve at least one valid related scenario through the existing `scenario_services` relation; publish fails when none exists. Derive industry, department and pain codes from those scenarios' frozen V2 branch/department/pain relations, deduplicate by stable code and order by each catalog's stable `sort_order,id`. Maturity comes only from the service revision's explicit `content_maturity_levels`, must contain at least one allowed code, and uses fixed order `explore,pilot,scale,collaborate`. Tests hold six exact expected-set fixtures rather than accepting whatever the current query returns. Retain `/services` as a compatibility redirect or canonical list entry without duplicating content.

- [ ] **Step 4: Run service/report/matching regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_public_services.py tests/test_assessment_catalog.py tests/test_matching.py tests/test_reporting.py tests/test_report_access.py -q`

Expected: PASS and every existing report digest remains stable.

- [ ] **Step 5: Commit**

```bash
git add blueprints/public_catalog.py catalog_content_repository.py templates/service_packages.html templates/service_package_detail.html templates/services.html tests/test_public_services.py
git commit -m "feat: publish complete service packages"
```

---

### Task 8: Build the verified-case workflow and public pages

**Files:**
- Create: `case_repository.py`
- Create: `blueprints/admin/cases.py`
- Create: `templates/admin/case_list_v2.html`
- Create: `templates/admin/case_edit_v2.html`
- Create: `templates/case_detail.html`
- Create: `tests/test_verified_cases.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `blueprints/admin/content.py`
- Modify: `blueprints/public_catalog.py`
- Modify: `blueprints/public.py`
- Modify: `templates/cases.html`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: `case_content`, `case_metrics`, private evidence metadata, content/media/publishing APIs.
- Produces: verified case draft/review/publish CRUD and `/cases`, `/cases/<slug>`.

- [ ] **Step 1: Write authenticity, source, and publication tests**

```python
def test_case_cannot_publish_without_verification_and_metric_basis(admin_client):
    draft_id = create_case_draft(admin_client, verification="unverified")
    response = publish_content(admin_client, draft_id)
    assert response.status_code == 400
    assert public_content_status(draft_id) == "draft"

def test_private_verification_basis_never_reaches_public_case(admin_client, client):
    case = create_authorized_case(admin_client, basis_reference="合同内部编号-1")
    publish_content(admin_client, case.id)
    response = client.get(case.public_path)
    assert b"合同内部编号-1" not in response.data
```

Cover internal codes `public_verified/authorized_anonymous` mapping only to visible Chinese labels “真实公开案例/经授权匿名案例”; required basis type `public_source/client_authorization/internal_delivery_record`; verification/reference metadata, review confirmation and verified time; `public_source` requiring a successful Task 3 source check no older than seven days; and an authenticated CSRF source-check POST using `expected_lock_version`/URL hash, with a concurrent URL edit returning 409 and preserving both the edit and empty check fields. Also cover complete metric period/basis; obvious email/phone/WeChat detection as an auxiliary guard; human confirmation that company/name/free-text/media is safe and that uploaded office/PDF documents passed Task 4's metadata-rejection policy; no internal code/private basis/reviewer field in public HTML/CSV/request audit; EXIF-stripped images; future/archived 404; sanitized body; choice-first forms; optimistic lock; auth/CSRF/transaction audit; and legacy rows never becoming public automatically. This is the deliberate early `/cases` cutover: remove the old `/admin/cases` and `/cases` registrations before adding V2 owners, and assert `app.url_map` has exactly one rule/endpoint for each. The shared account proves only that the shared administrator approved the record, not which natural person did so.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_verified_cases.py -q`

Expected: FAIL because V2 case/resource repositories and routes are absent.

- [ ] **Step 3: Implement verified domain records and public pages**

Define fixed enums and evidence requirements:

```python
CASE_VERIFICATION = frozenset({"public_verified", "authorized_anonymous"})
CASE_BASIS_TYPES = frozenset({
    "public_source", "client_authorization", "internal_delivery_record"
})
```

Publishing validation loads the case extension, every metric and the review confirmation inside the same transaction used by Task 3. Evidence references and review notes are separate private fields, never content blocks. An anonymized case stores no contact columns; automatic shape detection is not treated as proof of anonymity. Public list/detail queries read only V2 published content and never fall back to legacy `cases` rows. Zero verified cases produces an honest empty state and no fabricated count.

- [ ] **Step 4: Run content, privacy, security, and legacy regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_verified_cases.py tests/test_legacy_content_migration.py tests/test_validation_and_errors.py tests/test_security_gaps.py tests/test_lead_operations.py -q`

Expected: PASS; private lead/assessment data remains unrelated to public case records.

- [ ] **Step 5: Commit**

```bash
git add case_repository.py blueprints/admin/cases.py blueprints/admin/__init__.py blueprints/admin/content.py blueprints/public_catalog.py blueprints/public.py templates/admin/case_list_v2.html templates/admin/case_edit_v2.html templates/case_detail.html templates/cases.html templates/components/admin_navigation.html tests/test_verified_cases.py
git commit -m "feat: publish verified cases"
```

---

### Task 9: Build reviewed resources and announcements

**Files:**
- Create: `resource_repository.py`
- Create: `blueprints/admin/resources.py`
- Create: `templates/admin/resource_list_v2.html`
- Create: `templates/admin/resource_edit_v2.html`
- Create: `templates/admin/announcement_edit_v2.html`
- Create: `templates/resources.html`
- Create: `templates/resource_detail.html`
- Create: `templates/announcement_detail.html`
- Create: `tests/test_resources_announcements.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `blueprints/admin/content.py`
- Modify: `blueprints/public_catalog.py`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: resource/announcement extensions and 5A publishing/media APIs.
- Produces: reviewed resource/announcement admin flows; `/resources`, `/resources/<slug>`, `/announcements/<slug>`, and the published announcement read model used by the homepage.

- [ ] **Step 1: Write source, copyright, attachment and announcement tests**

```python
def test_non_original_resource_requires_public_source_and_copyright(admin_client):
    response = create_resource(
        admin_client, is_original="0", source_name="", source_url="",
        copyright_notice=""
    )
    assert response.status_code == 400

def test_expired_announcement_is_not_public(client, db):
    slug = published_announcement(valid_until=SHANGHAI_YESTERDAY)
    assert client.get(f"/announcements/{slug}").status_code == 404
```

Cover exactly `article/guide/report/template/policy`, original versus sourced work, normalized original publish time, sourced work requiring a successful Task 3 HTTPS source check no older than seven days, and the same authenticated CSRF/lock/hash source-check POST plus concurrent-edit rollback used by cases. Cover copyright notice, optional published-media attachment, fixed announcement validity interval, related links only to published targets, sanitized blocks, draft/future/expired/archived 404, admin auth/CSRF/optimistic lock/transaction audit, and no invented authorship/source/content. Every rendered external source/CTA link must pass the same normalized scheme policy and emit `target="_blank" rel="noopener noreferrer"`. Stage 5 public resource sources are HTTPS-only. A Task 14 registry may fetch reviewed HTTP into a private candidate/draft, but that draft remains nonpublishable unless the operator replaces it with a separately checked HTTPS canonical source; registry review is not public-link provenance. Remove the complete legacy article/announcement route ownership—including the old `/admin/announcements` GET list and all write routes—before registering V2 owners; assert every admin/public URL and endpoint appears exactly once in `app.url_map`.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_resources_announcements.py -q`

Expected: FAIL because V2 resource and announcement editors/read models do not exist.

- [ ] **Step 3: Implement choice-first editors and publication validation**

```python
RESOURCE_TYPES = frozenset({"article", "guide", "report", "template", "policy"})

def list_published_resources(filters: ResourceFilters, page: PageRequest,
                             *, now: datetime) -> Page[ResourceCard]: ...
def get_published_resource(slug: str, *, now: datetime) -> ResourceDetail | None: ...
def list_current_announcements(*, now: datetime) -> tuple[AnnouncementCard, ...]: ...
def get_current_announcement(slug: str, *, now: datetime) -> AnnouncementDetail | None: ...
```

The resource type is a select; source/authorship is a binary choice that reveals only the applicable fields. Publication validation occurs inside the Task 3 transaction and proves every referenced attachment is ready. Announcements are a separate content entry type, not a sixth resource type. Exact tests prove a current announcement detail is 200 and future, expired, and archived variants are each 404 without leaking their title/body.

- [ ] **Step 4: Run related regressions and commit**

```bash
..\..\.venv\Scripts\python.exe -m pytest tests/test_resources_announcements.py tests/test_content_publishing.py tests/test_media_http.py tests/test_validation_and_errors.py tests/test_rate_limits_and_audit.py -q
git add resource_repository.py blueprints/admin/resources.py blueprints/admin/__init__.py blueprints/admin/content.py blueprints/public_catalog.py templates/admin/resource_list_v2.html templates/admin/resource_edit_v2.html templates/admin/announcement_edit_v2.html templates/resources.html templates/resource_detail.html templates/announcement_detail.html templates/components/admin_navigation.html tests/test_resources_announcements.py
git commit -m "feat: publish reviewed resources and announcements"
```

---

### Task 10: Check legacy sources and idempotently convert approved rows to drafts

**Files:**
- Modify: `source_url_checker.py`
- Modify: `tests/test_source_url_checker.py`
- Create: `tests/test_content_migration_cli.py`
- Modify: `legacy_content_migration.py`
- Modify: `manage.py`
- Modify: `tests/test_legacy_content_migration.py`

**Interfaces:**
- Consumes: Task 2 review rows, an operator-authored decision JSONL file, Task 3 caller-owned `insert_content_draft`/`update_content_draft` primitives, Task 8/9 evidence requirements.
- Produces: `check-content-sources` and dry-run-first `migrate-legacy-content --decisions <file> [--apply]`; an idempotent source-row→target-draft mapping.

- [ ] **Step 1: Write SSRF, decision validation, preview and idempotency tests**

```python
def test_apply_returns_existing_target_until_source_checksum_changes(db, decisions):
    first = apply_legacy_decisions(db, decisions, actor="legacy_migration", now=NOW)
    second = apply_legacy_decisions(db, decisions, actor="legacy_migration", now=NOW)
    assert second.target_ids == first.target_ids
    mutate_legacy_source(db, decisions[0].source_id)
    assert apply_legacy_decisions(db, decisions, actor="legacy_migration", now=NOW).errors == (
        "source_changed",
    )
```

Cover the Task 3 pinned-transport URL boundary; no network call inside a database transaction; `reachable/unreachable/invalid/missing/unchecked`; exact checked-at/expiry/checksum persistence and stale check expiry; decision-file schema and checksum; unreviewed/unchecked/stale-decision rejection; six service mappings only; existing seeded service draft returning `target_draft_exists` plus a lock-versioned human merge preview rather than overwriting/creating a second draft; case evidence gate; explicitly dated announcement→announcement draft; article→resource draft; dry-run zero writes; apply zero deletes; repeated apply same target; source-changed refusal; and mapping/audit failure rolling back both a new draft and an existing-draft merge. Output remains generic without URL query/body/contact/secret.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_source_url_checker.py tests/test_content_migration_cli.py tests/test_legacy_content_migration.py -q`

Expected: FAIL because safe checking, decision application and target mappings do not exist.

- [ ] **Step 3: Implement preflight checking and one-transaction conversion**

Network work uses `check_source_url` and writes `source_state`, generic check code, checked/expiry times and `check_source_checksum`; it finishes before decision application. It never blesses a prior operator decision whose checksum differs. `migrate-legacy-content` defaults to JSONL preview. `--apply` requires exact source checksum, a non-stale decision/check, a current allowed source state, all required human confirmations and a fixed action. In one `BEGIN IMMEDIATE`, call `insert_content_draft(db, ...)` for a new target or `update_content_draft(db, ..., expected_lock_version=...)` for an explicitly approved service merge, then insert the mapping and transaction-owned audit. Any draft/mapping/audit failure rolls the aggregate back. A mapping conflict returns the existing target; checksum drift returns `source_changed` and never overwrites it. Merge validation preserves every assessment-critical field. Converted records remain drafts. Preserve every legacy row; `delete_later` is only a label for Stage 7.

- [ ] **Step 4: Run legacy/content/security partitions and commit**

```bash
..\..\.venv\Scripts\python.exe -m pytest tests/test_source_url_checker.py tests/test_content_migration_cli.py tests/test_legacy_content_migration.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_security_gaps.py -q
git add source_url_checker.py legacy_content_migration.py manage.py tests/test_source_url_checker.py tests/test_content_migration_cli.py tests/test_legacy_content_migration.py
git commit -m "feat: convert approved legacy content to drafts"
```

---

### Task 11: Integrate navigation, homepage, SEO, and compatibility routes

**Files:**
- Create: `templates/components/content_card.html`
- Create: `tests/test_content_navigation.py`
- Modify: `content_repository.py`
- Modify: `content_validation.py`
- Modify: `blueprints/public.py`
- Modify: `templates/components/navigation.html`
- Modify: `templates/components/footer.html`
- Modify: `templates/index.html`
- Modify: `templates/insights.html`
- Modify: `templates/article.html`
- Modify: `templates/base.html`
- Modify: `templates/admin/base_admin.html`
- Modify: `templates/components/admin_navigation.html`
- Modify: `app.py`
- Modify: `security.py`
- Modify: `tests/test_content_validation.py`

**Interfaces:**
- Consumes: all 5A public read models.
- Produces: confirmed top navigation, homepage published-content/announcement composition, canonical/noindex metadata, safe group aliases and legacy redirects.

- [ ] **Step 1: Write route-map, homepage, metadata, and compatibility tests**

```python
def test_navigation_matches_confirmed_information_architecture(client):
    page = BeautifulSoup(client.get("/").data, "html.parser")
    assert [link.get_text(" ", strip=True) for link in
            page.select("[data-primary-navigation] > a")] == [
        "行业方案", "AI 场景", "服务与交付", "案例与资源", "关于我们"
    ]
    assert page.select_one('[data-primary-cta][href="/assessment"]')

def test_homepage_never_falls_back_to_unreviewed_legacy_cases(client):
    response = client.get("/")
    assert b"case_source_or_metric_unverified" not in response.data
    assert legacy_seed_claims_are_absent(response.data)
```

Cover canonical links built only from configured `PUBLIC_BASE_URL`; exact `X-Robots-Tag: noindex, nofollow` plus template metadata on admin/draft/report/privacy-operation surfaces; hiding empty case/resource/announcement sections; only published relationships; alias/legacy redirects without open redirects; legacy `/services` and `/insights` compatibility behavior; old `/article/<id>` redirecting only through an approved published mapping otherwise 404; mobile menu semantics; visible keyboard focus; and exact analytics/private-cache behavior.

Freeze the URL-context matrix and crawl every rendered public/admin fixture: internal navigation uses validated relative paths; public content CTA/source URLs are HTTPS; reviewed HTTP ingestion URLs remain private and cannot publish; sanitized rich-text anchors allow only relative paths or HTTPS; trusted site-config `mailto:`/`tel:` contact links are rendered without `_blank`; every server-generated `_blank` HTTP(S) link contains both `noopener` and `noreferrer`. Update existing navigation/footer links that currently contain only `noopener`, reject unsafe sanitizer protocols/attributes, and omit links without a safe URL.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_navigation.py -q`

Expected: FAIL because the navigation and homepage still use legacy content routes/queries.

- [ ] **Step 3: Switch shared navigation and homepage to V2 read models**

Use a shared content-card component with escaped titles/summaries and server-validated URLs. Retain old detail routes only as safe redirects when a deterministic V2 mapping exists; otherwise return 404. `/cases` never reads the 27 legacy cases; `/insights` is the compatibility alias for `/resources` with the latter canonical. Do not query unreviewed legacy cases/articles for homepage recommendations and remove any fabricated count such as “27+”.

- [ ] **Step 4: Run public, analytics, accessibility, and smoke partitions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_navigation.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_analytics.py tests/test_smoke.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS with the confirmed page map and no legacy unverified claim visible.

- [ ] **Step 5: Commit**

```bash
git add content_repository.py content_validation.py blueprints/public.py templates/components/content_card.html templates/components/navigation.html templates/components/footer.html templates/components/admin_navigation.html templates/index.html templates/insights.html templates/article.html templates/base.html templates/admin/base_admin.html app.py security.py tests/test_content_validation.py tests/test_content_navigation.py
git commit -m "feat: integrate the public content catalog"
```

---

### Task 12: Verify and document the complete 5A journey

**Files:**
- Create: `tests/test_content_journey.py`
- Create: `docs/testing/content-catalog.md`
- Create: `docs/testing/evidence/content-*.png`
- Modify: `README.md`
- Modify: `docs/deployment/security-and-service.md`
- Modify: `D:/Codex干活/企业AI转型平台2.0升级/升级任务卡.md` after verification

**Interfaces:**
- Consumes: Tasks 0–11.
- Produces: one HTTP-only admin→public→revision→archive integration journey, browser evidence, reproducible verification/deployment instructions, and Task 5A completion record.

- [ ] **Step 1: Write the HTTP-only integration journey**

```python
def test_admin_can_publish_revise_and_archive_catalog_content(
    client, admin_client, tmp_path
):
    draft = admin_create_scenario_content(admin_client)
    assert client.get(draft.public_path).status_code == 404
    admin_publish(admin_client, draft.id)
    assert client.get(draft.public_path).status_code == 200
    revision = admin_copy_and_edit(admin_client, draft.id)
    admin_publish(admin_client, revision.id)
    assert public_title(client, draft.public_path) == revision.title
    admin_archive(admin_client, revision.id)
    assert client.get(draft.public_path).status_code == 404
```

Add journeys for verified case/resource/media relations, future publication preserving the old revision, active announcement expiry, mobile filters, service completeness, source-check dry-run, decision preview/idempotent draft conversion, disabled legacy scraper and safe legacy redirects. The integration test may use only public/admin/CLI surfaces, not repository calls or direct SQL assertions.

- [ ] **Step 2: Run the integration and related partition**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_journey.py tests/test_content_migrations.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_media_service.py tests/test_media_http.py tests/test_content_seed.py tests/test_catalog_content_admin.py tests/test_public_catalog.py tests/test_public_services.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_source_url_checker.py tests/test_content_migration_cli.py tests/test_content_navigation.py -q`

Expected: PASS.

- [ ] **Step 3: Document exact local and Stage 7 operations**

Document `migrate`, `inventory-content`, `check-content-sources`, `migrate-legacy-content`, `publish-due-content`, `recover-media-storage`, trusted canonical base URL, media backup/restore, `/opt/ai-platform/data/media` ownership, and a Stage 7 Nginx exact-location upload ceiling of 22 MiB for the admin media endpoint while other dynamic routes remain 1 MiB. Also document no-delete rules, source-check TTL/SSRF boundary, and that timers run only after a successful candidate smoke test. Record exact test counts and known content gaps; do not claim visual redesign or production launch.

- [ ] **Step 4: Run the 5A browser matrix**

Use a disposable database and media directory. Capture and inspect:

1. industry→scenario→service desktop journey;
2. 390×844 scenario filters with no overflow/covered controls;
3. keyboard-only filter and detail navigation with visible focus;
4. keyboard-only admin draft/block reorder/validation/publish/revise/archive flow with visible focus and conflict recovery;
5. case/resource page with verified label, source, metric period, attachment, and no contact data.

Save `content-industry-desktop.png`, `content-scenario-mobile.png`, `content-keyboard.png`, `content-admin-publish.png`, and `content-case-resource.png` under `docs/testing/evidence/`.

- [ ] **Step 5: Run final 5A verification**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pip check
..\..\.venv\Scripts\python.exe -m compileall -q .
node --check static/js/app.js
node --check static/js/content_editor.js
node --test tests/js/analytics_runtime.test.js tests/js/assessment_runtime.test.js tests/js/report_runtime.test.js tests/js/content_editor_runtime.test.js
git diff --check
..\..\.venv\Scripts\python.exe -m pytest -q
```

Expected: all commands exit 0; record the exact full-suite count and duration.

- [ ] **Step 6: Request independent review and commit**

Review against spec sections 1–10 and 12–17. Resolve every P0–P2 finding before marking 5A complete. Verify the migration from an empty database and from a copy with migrations 001–005 already recorded. Do not start the 5B plan until Task 12 is CLEAN.

```bash
git add tests/test_content_journey.py docs/testing/content-catalog.md docs/testing/evidence README.md docs/deployment/security-and-service.md
git commit -m "docs: verify content catalog publishing"
```
