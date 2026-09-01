# Stage 5B Operations and Rule Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the two-person operations workflow with reviewed ingestion, actionable dashboards, secure CSV export, immutable legal documents, and copy-preview-publish governance for future assessment rule versions.

**Architecture:** Build 5B on the verified 5A publishing/catalog APIs rather than adding a second CMS. Ingestion candidates, operational projections, exports, legal revisions, and rule-release drafts have separate repositories and explicit transactions. Mutable rule drafts remain relational; publishing compiles one strictly validated immutable runtime snapshot and atomically changes a single active-version pointer while Session-bound in-flight assessments retain their issued version.

**Tech Stack:** Python 3.12, Flask, SQLite/WAL, Jinja, vanilla JavaScript, pytest, BeautifulSoup, Python `csv`, existing security/audit/rate-limit and assessment rule engines.

**Spec:** `docs/superpowers/specs/2026-08-24-content-operations-design.md`

**Required predecessor:** Every task and review gate in `docs/superpowers/plans/2026-08-24-content-catalog-publishing.md` is complete.

**Binding migration-number erratum (2026-09-01):** Reviewed 5A work appended
`007_scenario_public_inputs.sql`, `008_service_content_maturity.sql`, and
`009_case_basis_types.sql` after this plan was approved. Those migrations are
immutable. Preserve every 5B behavior and task dependency below. Task 13 uses
`010`. Task 14 additionally requires append-only `011` to store a reviewed HTTP
source on a private resource draft while enforcing an HTTPS-only publication
gate at both database and service layers. The remaining unstarted migrations
shift in task order: Task 15=`012`, Task 17=`013`, Task 18=`014`, Task 19=`015`,
Task 21=`016`. The filenames and commands below have been mechanically
synchronized to this binding mapping.

**Required execution order:** Tasks 13–22 are sequential review gates. In particular, filters precede dashboard/export; legal storage and rule storage precede the shared flow credential; rule copy/preview precedes publication/runtime switching. Do not parallelize tasks that modify the same assessment runtime or admin Blueprint.

## Global Constraints

- Execute only in the isolated worktree; production, production data, systemd, Gunicorn and Nginx remain untouched.
- Keep one shared administrator role/account; do not add user, role or permission tables.
- Scraping writes only `fetched/pending_review` candidates. Acceptance creates a normal 5A draft; no path auto-publishes.
- Use explicit Asia/Shanghai timestamps and repository-owned `BEGIN IMMEDIATE` transactions for candidate decisions, legal publication, and rule publication.
- Migration filenames are append-only after execution: `010_ingestion_operations.sql`, `011_private_http_resource_drafts.sql`, `012_operations_query_indexes.sql`, `013_admin_export_audit.sql`, `014_legal_documents.sql`, `015_assessment_rule_releases.sql`, and `016_assessment_flow_enforcement.sql`. Never amend a migration after its task commits.
- CSV export is POST+CSRF, audited, private/no-store, UTF-8 BOM, formula-safe, field-allowlisted and limited to 10,000 rows.
- Operations queries and exports always exclude anonymized leads and never reconstruct contacts from consent, assessment or report snapshots.
- Published legal/rule versions and assessment/report legal snapshots are immutable. Retained consent rows are never rewritten by a policy release but remain deletable by the already-approved withdrawal/deletion/retention anonymization transaction.
- Each config response creates a bounded, expiring random `flow_id` in Session that binds branch + exact rule version + exact legal version IDs. Preview/completion accept only that opaque flow ID. This supports same-branch multi-tab sessions without allowing arbitrary history.
- `flow_id` is an authorization nonce only: never persist it in leads, assessments, reports, analytics, CSV, governance/request audit or logs, and never echo it in an error.
- Reuse `assessment_versions` as the sole rule-release identity because existing assessment/ROI foreign keys already target it. Do not add a parallel `rule_releases` root.
- High-risk domain actions write a minimal `governance_audit_events` row in the same transaction. Existing response-level `admin_audit_logs` remains supplementary and cannot provide rollback semantics.
- Do not invent legal text, customer evidence, sources or campaign data. Stage 7 must block if required legal content has not received explicit review.
- TDD RED precedes production code. After every numbered task: run its focused review, resolve all P0–P2, record exact RED/GREEN/related evidence plus commit in `D:/Codex干活/企业AI转型平台2.0升级/升级任务卡.md`, and only then start the next task.

---

### Task 13: Add the ingestion queue, attempts, deduplication, and governance audit schema

**Files:**
- Create: `migrations/010_ingestion_operations.sql`
- Create: `ingestion_contracts.py`
- Create: `ingestion_repository.py`
- Create: `tests/test_ingestion_repository.py`
- Modify: `tests/test_app_factory_and_migrations.py`

**Interfaces:**
- Consumes: migration runner and source-code syntax only. The reviewed fixed-source registry does not exist until Task 14.
- Produces: `ingestion_fetch_attempts`, `ingestion_candidates`, `governance_audit_events`, `FetchedItem`, canonical URL/content hashes, repository state transitions and indexes needed by later operations projections.

- [ ] **Step 1: Write schema, deduplication, no-auto-publish, and SSRF-boundary tests**

```python
def test_store_candidates_deduplicates_canonical_url_and_content_hash(db):
    first = store_candidates((FETCHED_ITEM,), now=NOW)
    second = store_candidates((TRACKING_VARIANT, SAME_BODY_OTHER_URL), now=NOW)
    assert first.created_ids
    assert second.created_ids == ()
    assert second.deduplicated == 2
```

Cover canonical scheme/host/path, IDNA host normalization, fragment and tracking-query removal, SHA-256 normalized-content dedupe, concurrent unique URL/hash insertion, bounded lowercase source-code syntax, exact `fetched→pending_review→accepted/rejected` transitions, optimistic lock, fixed rejection codes, explicit Shanghai timestamps and migration from databases that already recorded 001–009. Do not assert membership in a registry that is not created yet. Store network failures in `ingestion_fetch_attempts`; only successfully parsed content belongs in the unique candidate table.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_ingestion_repository.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because the queue and contracts do not exist.

- [ ] **Step 3: Add the ingestion schema and repository state machine**

`010_ingestion_operations.sql` creates fetch attempts, candidates with exact states `fetched/pending_review/accepted/rejected`, canonical URL, content hash, source code/name, title, licensed summary, sanitized candidate body when permitted, original publish time, rejection code/note, lock version, target content ID, explicit timestamps, and unique URL/hash indexes. It also creates `governance_audit_events(action,target_type,target_id,actor,metadata_json,created_at)` with no bodies, URLs, filenames, contacts or free-form search text.

Expose:

```python
@dataclass(frozen=True)
class FetchedItem:
    source_code: str
    source_name: str
    url: str
    title: str
    summary: str
    body_html: str
    original_published_at: datetime | None

def store_candidates(items: tuple[FetchedItem, ...], now: datetime) -> IngestResult: ...
def load_candidate(candidate_id: int) -> IngestionCandidate | None: ...
def mark_candidate_pending(db: sqlite3.Connection, candidate_id: int,
                           expected_lock_version: int, now: datetime) -> None: ...
```

No repository method performs network I/O or commits a caller-owned connection. Candidate decision APIs are implemented in Task 14 because they must compose with the 5A draft primitive.

- [ ] **Step 4: Run migration/repository regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_ingestion_repository.py tests/test_content_migrations.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS with no public content writes.

- [ ] **Step 5: Commit**

```bash
git add migrations/010_ingestion_operations.sql ingestion_contracts.py ingestion_repository.py tests/test_ingestion_repository.py tests/test_app_factory_and_migrations.py
git commit -m "feat: add reviewed ingestion queue"
```

---

### Task 14: Fetch only fixed sources and review candidates into ordinary drafts

**Files:**
- Create: `migrations/011_private_http_resource_drafts.sql`
- Create: `ingestion_sources.py`
- Create: `ingestion_service.py`
- Create: `seed_data/ingestion_sources_v1.json`
- Create: `blueprints/admin/ingestion.py`
- Create: `templates/admin/ingestion.html`
- Create: `templates/admin/ingestion_detail.html`
- Create: `tests/test_content_ingestion.py`
- Create: `tests/test_ingestion_sources.py`
- Modify: `scraper.py`
- Modify: `manage.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `blueprints/admin/content.py`
- Modify: `templates/components/admin_navigation.html`
- Modify: `security.py`
- Modify: `content_validation.py`
- Modify: `publishing_repository.py`
- Modify: `tests/test_content_validation.py`
- Modify: `tests/test_content_publishing.py`
- Modify: `tests/test_content_migrations.py`
- Modify: `tests/test_app_factory_and_migrations.py`
- Modify: `tests/test_v2_migrations.py`

**Interfaces:**
- Consumes: Task 13 queue, 5A `PinnedHttpTransport.fetch(...)` and `insert_content_draft(db, ...)`, this task's reviewed source registry, and existing admin controls.
- Produces: `fetch-content` CLI; compatible `/admin/scrape` queue trigger; choice-first accept/reject pages; transaction-safe candidate→resource draft conversion.

- [ ] **Step 1: Write network, copyright, no-auto-publish, decision and rollback tests**

```python
def test_accept_creates_draft_and_audit_in_one_transaction(admin_client, db):
    candidate_id = pending_candidate(db)
    response = post_decision(admin_client, candidate_id, "accept")
    assert response.status_code == 302
    assert candidate_state(db, candidate_id) == "accepted"
    assert target_content_status(db, candidate_id) == "draft"
    assert governance_action(db, candidate_id) == "ingestion_accepted"

def test_draft_failure_rolls_back_candidate_and_governance_event(db, monkeypatch):
    monkeypatch.setattr(publishing_repository, "insert_content_draft", fail)
    with pytest.raises(ContentConfigurationError):
        accept_candidate(PENDING_ID, ACCEPT_DECISION, 1, "admin", NOW)
    assert candidate_state(db, PENDING_ID) == "pending_review"
    assert governance_actions(db, PENDING_ID) == ()
```

Cover a schema-validated source registry with exact source code, exact normalized IDNA host set, adapter, allowed scheme, license-basis reference, robots policy and body-retention flag; every registry entry defaults disabled and only an environment code allowlist may enable a reviewed entry. Cover no administrator-supplied URL; direct use of the Task 3 transport with the registry host set (never a validate-then-`requests` second fetch), pinned approved IP/peer verification, disabled environment proxies, public-only mixed-answer rejection and every redirect host rejected before DNS unless present in that exact set; HTTPS/TLS by default and HTTP fetching only for an explicitly reviewed registry entry; status/content-type; separate connect/read timeout; compressed and decompressed boundaries of exactly 2,097,152 bytes accepted and 2,097,153 rejected, plus truncated streams and compression bombs; at most three redirects; generic failure category; metadata/summary-only storage unless the reviewed registry explicitly permits body retention; repeated fetch; CLI never publishes; endpoint-specific rate limit; auth/CSRF/no-store/request audit; fixed accept type/source/copyright fields; fixed reject reasons plus bounded non-sensitive note; optimistic conflict; and no exception/remote body/URL query disclosure. A reviewed HTTP URL may be stored only on the private candidate/draft through an explicit ingestion-only call context; ordinary catalog/admin draft creation must still reject HTTP. The database and publication service independently reject publish/schedule while the current source is HTTP. The operator must replace it with and separately check an HTTPS canonical source before publication.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_ingestion_sources.py tests/test_content_ingestion.py tests/test_scraper_safety_gate.py tests/test_rate_limits_and_audit.py -q`

Expected: FAIL because Task 0 still returns `ingestion_queue_not_ready`.

- [ ] **Step 3: Refactor adapters and implement one-transaction decisions**

Remove every legacy insert helper permanently. `seed_data/ingestion_sources_v1.json` is a reviewed policy registry, not a discovery list; unknown/unreviewed codes fail closed and all checked-in entries default disabled. Fixed adapters return `tuple[FetchedItem, ...]`; `run_scraper()`/`manage.py fetch-content` only processes enabled registry codes, stores candidates and prints counts/IDs. Remove the temporary `/admin/scrape` decorator/function from `blueprints/admin/content.py` before registering the queue trigger only in `blueprints/admin/ingestion.py`; preserve the intended URL, key it by endpoint in the rate limiter, accept no caller URL, and assert `app.url_map` has exactly one rule/endpoint owner.

`011_private_http_resource_drafts.sql` rebuilds `resource_content` using the latest proven table definition, preserves every row/ID/FK/unique/check/trigger behavior, and changes only the source URL storage CHECK to accept `http` or `https`. Add database triggers that allow HTTP only while the owning item is an unscheduled draft and reject any publish/schedule transition. Restore all table and cross-table integrity triggers affected by the rebuild. The service path uses an explicit reviewed-ingestion-only opt-in to `insert_content_draft`; its default validator remains HTTPS-only. The publication validator always requires the current source URL to be HTTPS in addition to the existing hash/freshness checks.

```python
def accept_candidate(candidate_id: int, decision: AcceptDecision,
                     expected_lock_version: int, actor: str,
                     now: datetime) -> int: ...
def reject_candidate(candidate_id: int, reason_code: str, note: str,
                     expected_lock_version: int, actor: str,
                     now: datetime) -> None: ...
```

Each decision starts `BEGIN IMMEDIATE`, loads the current candidate, validates the transition, calls `insert_content_draft(db, ...)` for acceptance, updates candidate state, writes a fixed `governance_audit_events` row and commits once. Acceptance never calls publish.

- [ ] **Step 4: Run GREEN and commit**

```bash
..\..\.venv\Scripts\python.exe -m pytest tests/test_ingestion_sources.py tests/test_content_ingestion.py tests/test_ingestion_repository.py tests/test_scraper_safety_gate.py tests/test_rate_limits_and_audit.py tests/test_resources_announcements.py tests/test_security_gaps.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_content_migrations.py tests/test_app_factory_and_migrations.py tests/test_v2_migrations.py -q
git add migrations/011_private_http_resource_drafts.sql ingestion_sources.py ingestion_service.py seed_data/ingestion_sources_v1.json scraper.py manage.py blueprints/admin/ingestion.py blueprints/admin/__init__.py blueprints/admin/content.py templates/admin/ingestion.html templates/admin/ingestion_detail.html templates/components/admin_navigation.html security.py content_validation.py publishing_repository.py tests/test_ingestion_sources.py tests/test_content_ingestion.py tests/test_content_validation.py tests/test_content_publishing.py tests/test_content_migrations.py tests/test_app_factory_and_migrations.py tests/test_v2_migrations.py
git commit -m "feat: review fetched content into drafts"
```

---

### Task 15: Unify pagination and filters across every operations list

**Files:**
- Create: `migrations/012_operations_query_indexes.sql`
- Create: `templates/admin/_pagination.html`
- Create: `tests/test_operations_pagination.py`
- Modify: `tests/test_app_factory_and_migrations.py`
- Modify: `pagination.py`
- Modify: `blueprints/admin/leads.py`
- Modify: `blueprints/admin/catalog.py`
- Modify: `blueprints/admin/cases.py`
- Modify: `blueprints/admin/resources.py`
- Modify: `blueprints/admin/ingestion.py`
- Modify: `lead_repository.py`
- Modify: `appointment_repository.py`
- Modify: `catalog_content_repository.py`
- Modify: `case_repository.py`
- Modify: `resource_repository.py`
- Modify: `ingestion_repository.py`
- Modify: `media_service.py`
- Modify: `templates/admin/leads.html`
- Modify: `templates/admin/appointments.html`
- Modify: `templates/admin/data_requests.html`
- Modify: `templates/admin/catalog_list.html`
- Modify: `templates/admin/case_list_v2.html`
- Modify: `templates/admin/resource_list_v2.html`
- Modify: `templates/admin/ingestion.html`
- Modify: `blueprints/admin/media.py`
- Modify: `templates/admin/media.html`

**Interfaces:**
- Consumes: the 5A `Page[T]`/`PageRequest`, Stage 4 leads/appointments and Stage 5 content/ingestion states.
- Produces: append-only query indexes plus exact filter DTOs and paginated queries for leads, appointments, privacy requests, every existing catalog/case/resource/media content list and ingestion candidates. Legal/rule lists created later must consume this same contract in their own tasks.

- [ ] **Step 1: Write count-to-list consistency and pagination tests**

```python
def test_page_size_is_only_20_or_50(admin_client):
    assert list_page_size(admin_client.get("/admin/leads?per_page=20")) == 20
    assert list_page_size(admin_client.get("/admin/leads?per_page=50")) == 50
    assert list_page_size(admin_client.get("/admin/leads?per_page=10000")) == 20
```

Cover every list, page overflow, GET invalid enums/page/per-page falling back to the documented safe default, write invalid enums remaining 400, escaped bounded search, open privacy-request status filters, no N+1 reads, query-string preservation, anonymous redirect, admin no-store, and `include_anonymized=False` enforced below the route. Freeze ordering per workflow rather than inventing one global direction: ordinary/new leads use `(created_at DESC,id DESC)`; actionable follow-ups use `(next_followup_at ASC,id ASC)` with nulls excluded; appointments use `(preferred_date ASC,time_slot ASC,id ASC)`; privacy requests use `(requested_at DESC,id DESC)`; scheduled content uses `(publish_at ASC,id ASC)` while ordinary content uses `(updated_at DESC,id DESC)`; ingestion uses `(updated_at DESC,id DESC)`. Lead search/joins must not recover contact data from anonymized assessments, reports or consents. Migration tests start from a database that already recorded `011`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_operations_pagination.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because existing lead/appointment/content lists do not share paginated filter contracts.

- [ ] **Step 3: Implement shared pagination and repository projections**

Reuse the exact 5A Task 6 public use of the Task 5 `Page[T]`, `PageRequest` and `parse_pagination()` contract without redefining it:

```python
def parse_lead_filters(values) -> LeadFilters: ...
def parse_appointment_filters(values) -> AppointmentFilters: ...
def parse_data_request_filters(values) -> DataRequestFilters: ...
def query_leads(filters: LeadFilters, page: PageRequest) -> Page[LeadRow]: ...
def query_appointments(filters: AppointmentFilters,
                       page: PageRequest) -> Page[AppointmentRow]: ...
```

`012_operations_query_indexes.sql` adds only indexes over real columns and those exact query orders: lead ordinary queues on `(anonymized_at,status,created_at DESC,id DESC)`; lead follow-up queues on `(anonymized_at,next_followup_at,id)`; branch-scoped assessment history on `(lead_id,branch_code,completed_at DESC,id DESC)` plus the cross-branch latest-per-lead export lookup on `(lead_id,completed_at DESC,id DESC)`; appointment operations on `(status,preferred_date,time_slot,id)` plus latest-per-lead export lookup on `(lead_id,created_at DESC,id DESC)`; data requests on `(status,requested_at DESC,id DESC)`; ordinary content on `(status,updated_at DESC,id DESC)`; scheduled content on `(status,publish_at,id)`; media on `(status,updated_at DESC,id DESC)`; and ingestion on `(state,updated_at DESC,id DESC)`. Migration tests assert every indexed column exists before creation. Verify query plans use each matching assessment index separately—never assume the intervening `branch_code` index can satisfy the cross-branch latest query—and do the same for representative large fixtures in every other queue. Each repository owns one bound-parameter predicate builder reused by its count and page query. Do not calculate totals by loading all rows or expect one index to serve incompatible queue orders.

- [ ] **Step 4: Update routes/templates and run related tests**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_operations_pagination.py tests/test_lead_operations.py tests/test_appointments.py tests/test_catalog_content_admin.py tests/test_verified_cases.py tests/test_resources_announcements.py tests/test_media_http.py tests/test_content_ingestion.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS with existing lead/appointment state transitions unchanged.

- [ ] **Step 5: Commit**

```bash
git add migrations/012_operations_query_indexes.sql pagination.py lead_repository.py appointment_repository.py catalog_content_repository.py case_repository.py resource_repository.py ingestion_repository.py media_service.py blueprints/admin/leads.py blueprints/admin/catalog.py blueprints/admin/cases.py blueprints/admin/resources.py blueprints/admin/ingestion.py blueprints/admin/media.py templates/admin/_pagination.html templates/admin/leads.html templates/admin/appointments.html templates/admin/data_requests.html templates/admin/catalog_list.html templates/admin/case_list_v2.html templates/admin/resource_list_v2.html templates/admin/ingestion.html templates/admin/media.html tests/test_operations_pagination.py tests/test_app_factory_and_migrations.py
git commit -m "feat: paginate operations lists"
```

---

### Task 16: Turn `/admin` into the actionable dashboard and reminder hub

**Files:**
- Create: `operations_repository.py`
- Create: `blueprints/admin/operations.py`
- Create: `templates/admin/operations_dashboard.html`
- Create: `tests/test_operations_dashboard.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `blueprints/admin/content.py`
- Delete: `templates/admin/index.html`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: Task 15 filter DTOs/predicates and Shanghai clock.
- Produces: `dashboard_snapshot(now)` and the existing `/admin` endpoint `admin.admin_index` as the two-person operations workspace.

- [ ] **Step 1: Write count-to-list and Shanghai reminder tests**

```python
def test_dashboard_counts_equal_linked_filtered_lists(admin_client):
    dashboard = BeautifulSoup(admin_client.get("/admin").data, "html.parser")
    for card in dashboard.select("[data-operation-card]"):
        linked = BeautifulSoup(admin_client.get(card.a["href"]).data, "html.parser")
        assert int(card["data-count"]) == int(linked.select_one("[data-total]")["data-total"])
```

Cover all `pending_contact` leads, newly created leads, contact-due today, overdue follow-ups, pending appointments, pending ingestion, scheduled content, drafts missing publication-required fields, complete drafts ready for review, and open `received/verifying` privacy requests at exact Asia/Shanghai boundaries; do not invent a privacy-request SLA/due date. Require anonymized leads excluded, zero states, one-query-per-card bounds, each card's count matching its linked filtered list, stable links, anonymous redirect to login, successful/404/error admin shells private/no-store, and the endpoint name remaining `admin.admin_index` for existing login redirects.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_operations_dashboard.py tests/test_admin_auth.py -q`

Expected: FAIL because `/admin` is not yet the complete operations projection.

- [ ] **Step 3: Implement shared-predicate projections without a jobs table**

```python
def dashboard_snapshot(now: datetime) -> OperationsSnapshot: ...
```

Every card calls the same repository predicate/DTO as its linked list. Counts use `COUNT(*)`, not loaded rows. Reminders are read-only database projections; Stage 5 adds no external notification, scheduler or reminder state table.

Move route ownership explicitly: remove the existing `@bp.route("/admin")` decorator and `admin_index()` function from `blueprints/admin/content.py`; define the route exactly once in `blueprints/admin/operations.py`, preserve endpoint `admin.admin_index`, and render only `templates/admin/operations_dashboard.html`. Delete the superseded `templates/admin/index.html`. A URL-map regression asserts one rule and one endpoint owner for `/admin`, and auth redirect tests continue resolving the preserved endpoint.

- [ ] **Step 4: Run GREEN and commit**

```bash
..\..\.venv\Scripts\python.exe -m pytest tests/test_operations_dashboard.py tests/test_operations_pagination.py tests/test_admin_auth.py tests/test_rate_limits_and_audit.py tests/test_lead_operations.py tests/test_appointments.py -q
git add operations_repository.py blueprints/admin/operations.py blueprints/admin/__init__.py blueprints/admin/content.py templates/admin/operations_dashboard.html templates/admin/index.html templates/components/admin_navigation.html tests/test_operations_dashboard.py
git commit -m "feat: surface actionable operations queues"
```

---

### Task 17: Export filtered leads safely

**Files:**
- Create: `migrations/013_admin_export_audit.sql`
- Create: `lead_export.py`
- Create: `tests/test_lead_export.py`
- Modify: `tests/test_app_factory_and_migrations.py`
- Modify: `blueprints/admin/leads.py`
- Modify: `lead_repository.py`
- Modify: `templates/admin/leads.html`

**Interfaces:**
- Consumes: exact lead filters from Task 15 and current admin identity.
- Produces: `export_rows(filters, limit=10000)`; `write_lead_csv(rows) -> bytes`; POST `/admin/leads/export`; `admin_export_logs`.

- [ ] **Step 1: Write field-allowlist, formula, limit, audit, and privacy tests**

```python
@pytest.mark.parametrize("value", ["=1+1", "+CMD", "-2+3", "@SUM(A1)", "  =1"])
def test_csv_neutralizes_formula_prefix(value):
    assert csv_cell(value).startswith("'")

EXPECTED_EXPORT_HEADERS = (
    "企业名称", "联系人", "手机号", "邮箱", "微信", "线索状态",
    "负责人", "行业分支", "部门", "评估编号", "成熟度",
    "推荐主场景", "预约状态", "意向日期", "时间段",
    "最后有效跟进时间", "下次跟进时间",
)

def test_export_has_exact_public_business_columns(admin_client):
    response = post_export(admin_client, status="pending_contact")
    rows = decode_utf8_bom_csv(response.data)
    assert tuple(rows[0]) == EXPECTED_EXPORT_HEADERS
    forbidden = {"analytics_id_hash", "ip_hash", "answers_json",
                 "report_snapshot_json", "resolution_note"}
    assert not forbidden.intersection(rows[0])
```

Cover POST-only, auth, CSRF, `Content-Type: text/csv; charset=utf-8`, fixed Shanghai timestamp filename, attachment disposition, `nosniff`, private/no-store, the exact Task 15 filter DTO, strict rejection (not safe-default widening) for invalid export filters, anonymized leads forcibly excluded, the latest assessment selected by `(completed_at DESC,id DESC)` and latest submitted appointment by `(created_at DESC,id DESC)`, exact 10,000 row success, fetching 10,001 returns generic 400 without partial CSV/audit, NFKC/control-character handling, newlines/quotes, phone strings explicitly encoded as spreadsheet text, no raw JSON/security fields, audit row actor/filter summary/count/time matching the returned rows, generic errors, audit failure returning no file, and metadata containing only the allowlisted keys `status/industry_branch/department/created_from/created_to/next_followup_from/next_followup_to/search_used`—never lead/assessment IDs, owner text, contact or search text.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_lead_export.py -q`

Expected: FAIL because export and export audit storage are absent.

- [ ] **Step 3: Add exact export audit schema and implementation**

Create append-only migration `013_admin_export_audit.sql` so databases that already recorded `012` still receive:

```sql
CREATE TABLE admin_export_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  filter_json TEXT NOT NULL,
  row_count INTEGER NOT NULL CHECK(row_count BETWEEN 0 AND 10000),
  created_at TEXT NOT NULL
);
```

Use one query with `LIMIT 10001`; never `COUNT` then query or silently truncate. Use Python `csv.writer(lineterminator="\r\n")`, prepend UTF-8 BOM, normalize Unicode/control characters, and prefix a single quote when the first non-whitespace character is `=`, `+`, `-`, or `@`; phone cells are also emitted explicitly as text. Export only the exact fields approved in spec section 9. Parse the primary scenario summary only through the shared `assessment_repository` report-snapshot schema dispatcher, never through a 2.0-specific parser or raw JSON; unknown/corrupt schemas fail the export generically. Task 21 extends that same dispatcher and its export regression for report schema 2.1. Build audit metadata from the fixed key allowlist above; the filename is server-generated from one Shanghai clock snapshot and contains no user input.

After rows and bytes are successfully materialized, insert `admin_export_logs` in a short `BEGIN IMMEDIATE` transaction. Return the file only after that commit; an audit failure yields a generic 503 and no CSV. The row count is the exact returned data count.

- [ ] **Step 4: Run export, privacy, audit, and lead regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_lead_export.py tests/test_lead_operations.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS; no export changes lead state or retention time.

- [ ] **Step 5: Commit**

```bash
git add migrations/013_admin_export_audit.sql lead_export.py blueprints/admin/leads.py lead_repository.py templates/admin/leads.html tests/test_lead_export.py tests/test_app_factory_and_migrations.py
git commit -m "feat: export filtered leads safely"
```

---

### Task 18: Version all four legal documents and bind historical records

**Files:**
- Create: `migrations/014_legal_documents.sql`
- Create: `legal_repository.py`
- Create: `blueprints/admin/legal.py`
- Create: `blueprints/public_legal.py`
- Create: `templates/admin/legal_list.html`
- Create: `templates/admin/legal_edit.html`
- Create: `templates/legal_detail.html`
- Create: `tests/test_legal_versions.py`
- Modify: `tests/test_app_factory_and_migrations.py`
- Modify: `app.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `templates/components/footer.html`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: existing external privacy policy code/URL, historical `lead_consents.policy_version`, and Task 15 `Page`/`PageRequest`.
- Produces: immutable legal versions, active pointer per type, schema for exact consent/report legal foreign keys, current `/legal/<document_type>`, immutable historical `/legal/<document_type>/<version_code>`, and paginated admin legal routes. Assessment config/completion/report behavior remains unchanged until Task 21 can bind an atomic four-document flow.

- [ ] **Step 1: Write immutable publication and consent-binding tests**

```python
def test_startup_reconciles_matching_old_consent_to_external_privacy_reference(db):
    consent_id = old_consent(db, policy_version=CURRENT_POLICY_VERSION)
    reconcile_external_privacy_reference(db, CURRENT_POLICY_VERSION, POLICY_URL, NOW)
    assert consent_legal_version(db, consent_id).mode == "external_legacy"

def test_future_legal_version_cannot_become_active(admin_client):
    response = publish_legal(admin_client, effective_at=SHANGHAI_TOMORROW)
    assert response.status_code == 400
```

Cover four exact document types; internal mode requiring nonempty title/body summary/body; external-legacy mode requiring an immutable validated URL and version while allowing summary/body to be empty because contents are neither fetched nor invented; one pointer-authoritative active version each; explicit review confirmation bound to the exact content digest; deterministic content SHA-256; positive optimistic `lock_version`; immutable published/archived content; draft private 404; sanitized internal content; `effective_at <= now` (future activation is rejected in Stage 5 rather than silently scheduled); atomic pointer+governance audit; review→edit→publish rejection, direct-SQL prevention of retaining a stale review digest, and re-review→publish success; external-legacy privacy reference reconciliation; exact repeated version+URL+digest no-op; same version with changed URL/digest fail-closed and zero-write; `/legal/privacy` resolving the pointer while the versioned path renders/redirects the exact published-or-archived version; draft/unknown versioned paths 404; exact legal version path round-trip and rejection of `/`, `?`, `%2F`, whitespace or overlength codes; historical consent FK backfill only when policy code matches; `assessment_legal_versions` unique `(assessment_id,document_type)` immutable snapshot schema; mode-specific missing-field/review rejection; admin list filters by exact type/status with safe-default GET, 20/50 pages, `(updated_at DESC,id DESC)`, query-string preservation and no-store; auth/CSRF/request audit/no-store; withdrawal/deletion/retention still allowed to delete `lead_consents`; and no invented seed legal text. Task 21 owns config/completion/report binding tests.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_legal_versions.py tests/test_assessment_completion.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because legal version storage/routes and exact historical links do not exist.

- [ ] **Step 3: Implement legal schema and atomic active pointers**

`014_legal_documents.sql` creates `legal_documents` with type check `privacy/terms/roi_disclaimer/ai_content_notice`, a 1–64 character ASCII `version_code` whose first character is alphanumeric and whose remainder is limited to `[A-Za-z0-9._-]` by both CHECK and service validation, mode `internal/external_legacy`, `title`, `body_summary`, sanitized `body_html`, validated `external_url`, current `content_sha256`, nullable `reviewed_content_sha256`, draft/published/archived status, positive `lock_version`, legal-review confirmation time, effective/published/archived/created/updated times, unique `(type, version_code)`, and the admin-list index `(type,status,updated_at DESC,id DESC)`. Internal review fields are either both null or both present; external-legacy requires both null. It separately creates `active_legal_documents(document_type PRIMARY KEY, legal_document_id UNIQUE NOT NULL REFERENCES legal_documents(id))`; this pointer is the sole public/current authority. Do not create a partial unique index limiting published rows per type, because publication legitimately has two published rows between the new-row transition and pointer switch inside one transaction. Versioned paths are generated with `url_for` from the validated code, never by concatenating untrusted text.

Pointer triggers require matching type, published/effective status and a structurally valid digest, then branch by mode. An `internal` target additionally requires nonempty title/summary/body and `reviewed_content_sha256 = content_sha256` with review time present. An `external_legacy` target is allowed only for `privacy`, requires no fabricated review/body, and requires nonempty version/normalized external URL. Because SQLite cannot read environment configuration or calculate SHA-256, `reconcile_external_privacy_reference` recomputes the canonical digest in Python and is the only service allowed to establish that compatibility pointer; it compares version/URL/digest to current immutable config before the transaction. The current route reads only through the pointer. The versioned route loads by exact `(document_type,version_code)`, exposes only published/archived immutable rows, renders internal content, and redirects an external-legacy row only to its own frozen normalized URL. Task 21 applies the stricter flow-readiness rule that all four pointed documents must be reviewed `internal` versions; an external compatibility pointer can never authorize a new assessment flow.

Mode CHECKs require title/summary/body and no external URL for internal mode; external-legacy requires version plus external URL, forbids a local body and allows title/summary to be null. The service computes `content_sha256` from canonical UTF-8 JSON over the exact normalized `type/version/mode/title/body_summary/body_html/external_url` keys (sorted keys and compact separators); SQLite only stores and compares the digest. Any draft edit to a digest input must atomically write the new digest, clear `reviewed_content_sha256` and `legal_review_confirmed_at`, and bump the lock. A trigger rejects an update that changes a digest input/current digest while preserving either prior review field.

It adds nullable `lead_consents.legal_version_id` FK for historical reconciliation and `assessment_legal_versions(assessment_id, document_type, legal_version_id, version_code, digest)` with unique `(assessment_id,document_type)`. Publication permits one strict `draft→published` transition changing only status, `published_at`, `updated_at`, and `lock_version` after content/review/digest validation. Published content/digest is then immutable. The sole later root lifecycle update is `published→archived` and may change only status, `archived_at`, `updated_at`, and `lock_version`; archived rows cannot change or delete. Assessment legal-snapshot rows reject update/delete; consent rows remain deletable by the existing privacy lifecycle. Cross-type consent enforcement is deliberately added only in Task 21 after runtime flow binding exists. Direct-SQL tests prove all forbidden changes fail and the archive transition succeeds only after the active pointer has moved.

Do not seed legal prose. Idempotent startup may create only an `external_legacy` privacy reference from the already configured version/URL, establish it as the privacy pointer only when no reviewed internal privacy pointer exists, and link matching old consents; it cannot masquerade as reviewed internal content or satisfy Stage 7 readiness. Reconciliation is a no-op only when type/version/normalized URL/content digest are exactly identical. If the configured policy reuses a version with a changed URL or digest, fail closed with zero writes and require a new policy version; never mutate the immutable row or evade `(type,version)`. Publishing the first reviewed internal privacy version switches the pointer and archives the now-unpointed external row while historical consents keep their FK. Tests prove the external pointer redirects without a fake review, new flow issuance still fails, and the later internal switch preserves old consent traceability. Tests create reviewed fixtures. Stage 7 fails closed until all four reviewed internal documents are active.

- [ ] **Step 4: Implement atomic publication and exact historical binding APIs**

```python
def publish_legal_version(version_id: int, expected_lock_version: int,
                          actor: str, now: datetime) -> None: ...
def confirm_legal_review(version_id: int, expected_lock_version: int,
                         actor: str, now: datetime) -> int: ...
def load_active_legal_bundle(db: sqlite3.Connection,
                             now: datetime) -> LegalBundle: ...
def load_legal_bundle(db: sqlite3.Connection,
                      version_ids: LegalVersionIds) -> LegalBundle: ...
def query_legal_versions(filters: LegalFilters,
                         page: PageRequest) -> Page[LegalVersionRow]: ...
```

`confirm_legal_review` uses `BEGIN IMMEDIATE`, reloads the internal draft and lock, recomputes its current canonical digest, writes that exact value to both digest fields with review time, bumps the lock, writes a fixed governance event and commits once. Publication uses a separate `BEGIN IMMEDIATE`, requires `reviewed_content_sha256 == content_sha256`, validates non-future effective time, marks the new row published, moves that type's pointer, archives the now-unpointed old row, writes a fixed governance event and commits once. Pointer/root triggers reject pointing to a draft or digest-less/stale-review row and reject archiving the still-pointed version. The two load APIs never call `get_db()` or commit a caller-owned connection; any convenience wrapper that owns its connection has a different name and is forbidden inside flow issuance. This task does not change the Stage 4 assessment config/completion/report path. Task 21 performs the atomic four-document binding and consent/report writes.

- [ ] **Step 5: Run legal, assessment, privacy, and report regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_legal_versions.py tests/test_assessment_v2_api.py tests/test_assessment_completion.py tests/test_lead_operations.py tests/test_report_access.py tests/test_analytics.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS; legal management is available while the Stage 4 assessment behavior remains unchanged, and privacy anonymization still deletes consent rows as approved.

- [ ] **Step 6: Commit**

```bash
git add migrations/014_legal_documents.sql legal_repository.py blueprints/admin/legal.py blueprints/public_legal.py blueprints/admin/__init__.py app.py templates/admin/legal_list.html templates/admin/legal_edit.html templates/legal_detail.html templates/components/footer.html templates/components/admin_navigation.html tests/test_legal_versions.py tests/test_app_factory_and_migrations.py
git commit -m "feat: version legal consent documents"
```

---

### Task 19: Extend `assessment_versions` into complete rule-release drafts

**Files:**
- Create: `migrations/015_assessment_rule_releases.sql`
- Create: `rule_release_repository.py`
- Create: `rule_release_validation.py`
- Create: `rule_release_seed.py`
- Create: `tests/test_rule_release_drafts.py`
- Modify: `models.py`
- Modify: `assessment/contracts.py`
- Modify: `tests/test_app_factory_and_migrations.py`

**Interfaces:**
- Consumes: active `assessment_versions`, questions/options/weights/benchmarks, scenarios/relations/ROI profiles, services/deliverables, and Task 15 `Page`/`PageRequest`.
- Produces: one expanded `assessment_versions` root, version-scoped scenario/service descendants, relational draft workspace, idempotent initial V2 snapshot/active pointer, copy/save/validate/compile APIs.

- [ ] **Step 1: Write exact copy, type/domain, and immutability tests**

```python
def test_copy_active_release_has_exact_runtime_cardinality(db):
    draft_id = copy_active_release(
        code="v2.1-draft", name="V2.1 草稿", actor="admin", now=SHANGHAI_NOW
    )
    draft = load_release_draft(draft_id)
    assert len(draft.industries) == 4
    assert len(draft.scenarios) == 13
    assert len(draft.services) == 6
    assert len(draft.questions) == 12
    assert all(len(question.options) == 4 for question in draft.questions)

def test_published_release_rows_cannot_be_edited(db):
    release_id = published_release(db)
    with pytest.raises(DataConflictError):
        save_release_draft(
            release_id, expected_lock_version=1,
            draft=replace(load_release_draft(release_id), questions=changed_questions()),
            now=SHANGHAI_NOW,
        )
```

Cover all exact codes/types/cardinalities, display labels needed by public config/report, bool-as-int rejection, Decimal finite/domain constraints, unique codes/order, branch-scoped departments/pains, scenario thresholds/relations/ROI triples, service budgets/scope/deliverables/steps/prerequisites/exclusions/acceptance/support, cross-reference integrity, no PII/contact-shaped free text, deep-copy completeness, copy code conflict, optimistic lock, child rollback, published-child immutability, repeated startup/backfill not overwriting drafts/published rows, and `assessments.rule_version_id`/`roi_estimates.rule_version_id` remaining valid foreign keys.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_rule_release_drafts.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because relational release drafts do not exist.

- [ ] **Step 3: Add relational draft and immutable snapshot schema**

`015_assessment_rule_releases.sql` alters `assessment_versions` to add nullable `copied_from_id`, positive `lock_version`, `validated_digest`, and `updated_at`, plus the admin-list index `(status,updated_at DESC,id DESC)`. It creates version-scoped scenario rows plus branch/department/pain/budget/service/ROI descendants; version-scoped service rows plus deliverables/steps/prerequisites/exclusions/acceptance descendants; immutable `assessment_version_snapshots(schema_version,canonical_json,sha256)`; and singleton `active_assessment_version` pointing to the one active published `assessment_versions` row. Existing questions/options/weights/benchmarks/ROI option ranges stay under that same root.

`assessment_version_snapshots.assessment_version_id` is unique. Before snapshot insertion, compilation writes `assessment_versions.validated_digest` while the draft root is still editable. Snapshot insertion requires its SHA-256 to equal that root digest. Once a parent has a snapshot, triggers reject INSERT/UPDATE/DELETE in every existing or new version-child table and reject snapshot mutation. The root then allows exactly one strict `draft→published` transition changing only `status,published_at,updated_at,lock_version`, with `validated_digest` already equal to the immutable snapshot SHA; after publication, only the strict `published→archived` lifecycle fields may change. Existing V2 initial reconciliation may set its digest before inserting the first snapshot because its root is already published. The active singleton may point only to a published version with exactly one matching snapshot.

`rule_release_seed.reconcile_initial_v2_release(db, now)` runs after the existing frozen seed. If an active pointer exists, validate its published status, unique snapshot and digest, then no-op. If no pointer exists and the current V2 lacks a snapshot, one `BEGIN IMMEDIATE` transaction copies the 13 scenarios/6 services and all other current descendants, compiles/validates exact frozen parity, inserts the snapshot last, and establishes the pointer. Future drafts do not suppress this backfill. Repeated startup never overwrites a draft or snapshot.

- [ ] **Step 4: Implement repository copy/save and pure validation**

```python
def copy_active_release(code: str, name: str, actor: str, now: datetime) -> int: ...
def load_release_draft(release_id: int) -> RuleReleaseDraft: ...
def save_release_draft(release_id: int, expected_lock_version: int,
                       draft: RuleReleaseDraft, now: datetime) -> int: ...
def query_rule_releases(filters: RuleReleaseFilters,
                        page: PageRequest) -> Page[RuleReleaseRow]: ...
def validate_release_draft(draft: RuleReleaseDraft) -> tuple[str, ...]: ...
def compile_release_snapshot(draft: RuleReleaseDraft) -> RuleReleaseSnapshot: ...
```

Canonical JSON uses sorted keys and fixed array order; Decimal values serialize as strings. It includes every public label and every report-critical scenario/service/calculation field. Validation imports canonical dimension/question/code domains rather than duplicating unordered sets. The old frozen V2 validator remains available by snapshot schema/version; a legitimate future snapshot is not compared against the old frozen manifest.

- [ ] **Step 5: Run draft, catalog, scoring, matching, ROI, and reporting tests**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_rule_release_drafts.py tests/test_assessment_catalog.py tests/test_scoring.py tests/test_matching.py tests/test_roi.py tests/test_reporting.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS and compiling the copied V2 release produces behavior identical to the frozen Stage 4 bundle.

- [ ] **Step 6: Commit**

```bash
git add migrations/015_assessment_rule_releases.sql rule_release_repository.py rule_release_validation.py rule_release_seed.py models.py assessment/contracts.py tests/test_rule_release_drafts.py tests/test_app_factory_and_migrations.py
git commit -m "feat: draft versioned assessment releases"
```

---

### Task 20: Edit and preview rule drafts through the real assessment pipeline

**Files:**
- Create: `rule_release_service.py`
- Create: `blueprints/admin/rules.py`
- Create: `templates/admin/rule_releases.html`
- Create: `templates/admin/rule_release_edit.html`
- Create: `templates/admin/rule_release_preview.html`
- Create: `tests/test_rule_release_admin.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `templates/components/admin_navigation.html`

**Interfaces:**
- Consumes: Task 19 drafts/compiler, Task 15 `Page`/`PageRequest`, and Stage 4 score/match/ROI/report pure functions.
- Produces: paginated admin copy/edit/preview routes and `preview_release`; no active-pointer mutation yet.

- [ ] **Step 1: Write edit, preview parity, validation, and no-domain-write tests**

```python
def test_preview_runs_real_rule_pipeline_without_writes(admin_client, db):
    release_id = valid_draft_release(db)
    before = frozen_rule_domain_digests(db)
    response = admin_client.post(
        f"/admin/rules/{release_id}/preview",
        data={"csrf_token": TOKEN, **FIXED_PREVIEW_ANSWERS},
    )
    assert response.status_code == 200
    assert preview_sections(response) == {
        "scores", "scenarios", "roi", "roadmap", "services"
    }
    assert frozen_rule_domain_digests(db) == before
```

Cover exact answer/ROI choices, all four branches, score-boundary and fallback examples, invalid/partial drafts, public-config serializability, 4,096 score-profile parity for the unchanged copied release, service completeness, report snapshot schema, unknown-field rejection, choice/reorder controls, optimistic conflict preserving submitted values, auth/CSRF/request audit/no-store, and generic errors. The rule-release list uses exact status filters, safe-default GET, 20/50 pages, `(updated_at DESC,id DESC)`, preserved query strings, matching count/page predicates and private/no-store. Because POST preview is request-audited after response, assert that rule/content/assessment domain tables do not change—not that the entire database change counter remains static.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_rule_release_admin.py -q`

Expected: FAIL because rule admin/edit/preview routes do not exist.

- [ ] **Step 3: Implement the real preview pipeline**

```python
@dataclass(frozen=True)
class ReleasePreview:
    public_config: Mapping
    scores: Mapping[str, int]
    recommendations: tuple[Mapping, ...]
    roi: Mapping
    report_snapshot: Mapping

def preview_release(release_id: int, request: PreviewRequest) -> ReleasePreview: ...
```

Preview compiles in memory and calls the existing public-config builder and pure scoring → matching → ROI → reporting functions. It does not use a simplified preview calculator. Fixed fixtures cover each industry plus threshold/fallback boundaries and persist no assessment, lead, report, ROI or analytics row.

- [ ] **Step 4: Build choice-first admin forms**

Use select/multiselect/reorder controls for codes, thresholds, relations and coefficients. Unknown fields fail. The page shows validation results, compiled digest and exact version code. Editing published/archived rows is absent from the UI and rejected server-side. Publication is deliberately deferred to Task 21.

- [ ] **Step 5: Run admin, security, and rule-engine partitions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_rule_release_admin.py tests/test_rule_release_drafts.py tests/test_admin_auth.py tests/test_rate_limits_and_audit.py tests/test_scoring.py tests/test_matching.py tests/test_roi.py tests/test_reporting.py -q`

Expected: PASS with exact old-release parity and no active-pointer change.

- [ ] **Step 6: Commit**

```bash
git add rule_release_service.py blueprints/admin/rules.py blueprints/admin/__init__.py templates/admin/rule_releases.html templates/admin/rule_release_edit.html templates/admin/rule_release_preview.html templates/components/admin_navigation.html tests/test_rule_release_admin.py
git commit -m "feat: edit and preview assessment releases"
```

---

### Task 21: Atomically publish releases and bind each assessment flow to exact rule/legal versions

**Files:**
- Create: `migrations/016_assessment_flow_enforcement.sql`
- Create: `assessment_flow.py`
- Create: `rule_release_runtime.py`
- Create: `tests/assessment_flow_helpers.py`
- Create: `tests/test_assessment_flows.py`
- Create: `tests/test_rule_release_runtime.py`
- Modify: `rule_release_service.py`
- Modify: `blueprints/admin/rules.py`
- Modify: `templates/admin/rule_releases.html`
- Create: `templates/admin/rule_release_publish.html`
- Modify: `legal_repository.py`
- Modify: `lead_repository.py`
- Modify: `assessment_repository.py`
- Modify: `assessment_completion_service.py`
- Modify: `assessment_validation.py`
- Modify: `blueprints/assessment.py`
- Modify: `assessment/reporting.py`
- Modify: `lead_export.py`
- Modify: `templates/assessment/_report_content.html`
- Modify: `templates/assessment/report_pdf.html`
- Modify: `catalog_content_repository.py`
- Modify: `static/js/assessment.js`
- Modify: `tests/conftest.py`
- Modify: `tests/test_app_factory_and_migrations.py`
- Modify: `tests/test_assessment_completion.py`
- Modify: `tests/test_assessment_v2_api.py`
- Modify: `tests/test_appointments.py`
- Modify: `tests/test_analytics.py`
- Modify: `tests/test_report_access.py`
- Modify: `tests/test_assessment_wizard.py`
- Modify: `tests/test_core_journey.py`
- Modify: `tests/test_lead_operations.py`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_lead_export.py`
- Modify: `tests/test_v2_migrations.py`
- Modify: `tests/js/assessment_runtime.test.js`

**Interfaces:**
- Consumes: Task 18 legal versions, Tasks 19–20 rule draft/snapshot/preview, 5A scenario/service authority seams.
- Produces: atomic `publish_release`; strict active/historical loaders; bounded `flow_id` Session credentials; config/preview/completion/report/public-catalog routing through exact snapshots.

- [ ] **Step 1: Write active/new-Session, in-flight-old-Session, replay, and history tests**

```python
def test_same_branch_tabs_keep_independent_old_and_new_flow_credentials(
    client, app, admin_client
):
    old_config = client.get("/api/v2/assessment/config/manufacturing").get_json()
    publish_new_release(admin_client)
    new_config = client.get("/api/v2/assessment/config/manufacturing").get_json()
    assert new_config["rule_version"] != old_config["rule_version"]
    assert new_config["flow_id"] != old_config["flow_id"]
    old_result = complete(client, payload_for(old_config))
    assert old_result.status_code == 200
    assert report_version(client, old_result) == old_config["rule_version"]
```

Cover 192-bit unpredictable flow IDs; maximum 8 live flows and 24-hour TTL with deterministic oldest eviction; same-branch/same-Session multi-tab issuance; branch mismatch; unknown/expired/tampered flow; client rule/policy version fields rejected if inconsistent and never used to select history; one flow's config/preview/complete uses the exact rule plus four legal IDs; missing any active legal type or any pointer whose target is not reviewed `mode='internal'` fails before issuing a flow (including the valid external-legacy privacy compatibility pointer); legal-only and rule-only changes; flow validation before idempotency lookup; same submission key under a different valid flow returns generic 409 unless existing branch/rule/four legal IDs all match and report remains authorized to this Session; two connections publishing competing drafts; governance-audit/snapshot/pointer failure rollback; no partial active pointer; direct-SQL rejection of a pointer to draft/snapshot-less rows and archiving a pointed row; corrupt/missing active snapshot generic 503 before quota/domain writes; rule/legal publish concurrent with flow issue or old-flow completion; historical report/PDF digest, version-specific legal link and exact disclaimer access after later legal publication; schema-2.1 lead export through the shared report dispatcher; consent privacy FK/code consistency; a one-call startup upgrade from a database recorded at migration 005 or 006 through migration 016 followed by external-privacy reconciliation, repeated-startup no-op, and rejection of any forged historical-link update that changes another consent field at the same time; withdrawal/deletion/retention still delete consent while assessment legal snapshot remains; appointment/report links; no flow ID in any database row/log/error/HTML beyond the intended config/form field; analytics event privacy; V2 initial snapshot parity; 5A public scenario/service critical fields switching with the active release while narrative revisions stay stable.

`tests/assessment_flow_helpers.py` is the sole test adapter for issuing a real config flow and constructing bound preview/completion payloads or test-only reviewed legal fixtures. Update every listed Python/Node regression that currently posts preview/complete directly or inserts a consent without `legal_version_id`. The production service contract becomes `complete_assessment(request, identity_hash, issued_flow)` with a required `IssuedFlow`; no optional flow, test-only fallback, or legacy authorization path is allowed.

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_assessment_flows.py tests/test_rule_release_runtime.py tests/test_assessment_v2_api.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because runtime loading is hardcoded and there is no per-flow credential or publication switch.

- [ ] **Step 3: Implement strict snapshot deserialization and Session binding**

```python
def publish_release(version_id: int, expected_lock_version: int,
                    actor: str, now: datetime) -> str: ...
def load_active_rule_bundle(db: sqlite3.Connection,
                            branch_code: str) -> RuleBundle: ...
def load_rule_bundle(db: sqlite3.Connection, version_id: int,
                     branch_code: str) -> RuleBundle: ...
def issue_assessment_flow(db: sqlite3.Connection, session,
                          branch_code: str, now: datetime) -> IssuedFlow: ...
def require_assessment_flow(session, flow_id: str, branch_code: str,
                            now: datetime) -> IssuedFlow: ...
```

The dedicated confirmation page displays the exact code, validation result and compiled digest. Publish POST requires CSRF plus current lock version, then starts `BEGIN IMMEDIATE`, reloads/validates the draft, runs the same fixed preview examples, compiles canonical JSON/hash, writes the matching `validated_digest` to the still-draft root, inserts the immutable snapshot, performs the one allowed strict `draft→published` transition, switches `active_assessment_version` to the now-published snapshotted row, archives the now-unpointed prior version, writes a fixed governance event and commits once. That order is mandatory: the active pointer never references an archived/draft/snapshot-less row, even transiently. Any failure rolls back all domain changes. Existing request-level audit remains supplementary.

Strict runtime loading validates snapshot byte size, exact schema/version/keys/cardinalities/types/domains and SHA-256 before contracts. The migration guarantees an initial V2 snapshot; never silently fall back from a missing/corrupt snapshot. Preserve the frozen V2 snapshot/report validator for historical V2 data and dispatch future validation by persisted snapshot schema.

`016_assessment_flow_enforcement.sql` gives consent INSERT and UPDATE deliberately different rules. Every new INSERT must provide `legal_version_id` referencing a privacy document whose version code exactly equals `policy_version`, whose status is `published` or `archived`, whose mode is `internal`, and whose review digest still equals its immutable content digest. An UPDATE may never rebind an already-bound consent. Its sole compatibility exception is `OLD.legal_version_id IS NULL → NEW.legal_version_id = <external_legacy privacy row>` where that immutable row is published/archived, its `version_code = OLD.policy_version = NEW.policy_version`, and every other consent column is byte-for-byte/`IS` unchanged. This narrow exception lets the controlled Python reconciler run after a single `apply_migrations()` has advanced an old 005/006 database all the way through 016; it cannot authorize a new external consent or smuggle a simultaneous field edit. Repeated reconciliation is an exact no-op. The migration also adds assessment-legal INSERT checks that the referenced document is reviewed internal and published/archived, document type and version code match, and `NEW.digest = legal_documents.content_sha256`; SQLite never attempts to calculate SHA-256. This permits an old valid flow to complete after its bound internal document is archived, while rejecting every mutable draft. Direct-SQL tests cover draft/external/stale-review rejection, already-bound rebinding, forged compatibility updates, and the real one-call-upgrade ordering. Assessment legal rows remain immutable. The migration does not block approved consent-row deletion during anonymization. Apply it only in the same task that changes completion and every fixture to provide the bound IDs.

Each config call opens one caller-owned SQLite connection and read transaction, calls only `load_active_rule_bundle(db, branch_code)` and `load_active_legal_bundle(db, now)`, validates the rule pointer/snapshot plus all four simultaneously active legal IDs/digests, then commits that consistent database snapshot before writing Session. Neither loader may call `get_db()`, open/close another connection, or commit. Historical preview/completion calls likewise use `load_rule_bundle(db, ...)` and `load_legal_bundle(db, ...)` on their caller-owned connection. It uses `secrets.token_urlsafe(24)` and stores only `flow_id → {branch, rule_version_id, privacy_id, terms_id, roi_disclaimer_id, ai_notice_id, issued_at}` in a maximum-eight, 24-hour Session mapping. The browser returns `flow_id`; existing `rule_version`/`policy_version` fields remain display-integrity values, never authorization. Preview and completion validate the flow before any replay/quota/domain lookup and load only its binding. Unknown/expired flows fail generically before rate quota or writes.

- [ ] **Step 4: Route all runtime paths through the exact issued version**

Completion persists the bound version ID/code, privacy consent FK/code, all four legal links/digests and immutable report snapshot in its existing atomic transaction. On an existing submission key, compare branch, rule ID and four legal IDs with the validated flow before returning the prior result; mismatch is 409 with no write. Publication/config changes never mutate existing flow bindings.

Introduce a report-snapshot schema `2.1` independent from the rule snapshot schema constant. It contains all existing score/scenario/ROI/roadmap/service data plus an exact four-entry legal map `{document_type,legal_version_id,version_code,content_sha256,public_path,external_url}`. `public_path` is the server-generated immutable version route; `external_url` is null for internal documents and the frozen normalized URL for the external-legacy compatibility shape. It also stores the exact sanitized, bounded `body_summary` actually rendered for `roi_disclaimer` and `ai_content_notice`; privacy/terms keep version/digest/version-specific path identity without copying full legal prose. The HTML/PDF renderer displays only those persisted notice strings and links only to persisted safe paths. Dispatch validation by report schema: historical `2.0` stays on the frozen Stage 4 validator byte-for-byte, while `2.1` strictly validates its own exact keys, sizes, referenced legal IDs/digests, version routes and notice/display consistency. The shared `assessment_repository` summary reader dispatches both schemas so lead export remains compatible. `RULE_SNAPSHOT_SCHEMA_VERSION` and `REPORT_SNAPSHOT_SCHEMA_VERSION` are separate constants and are never inferred from one another.

Report/PDF validates labels/services/calculations/legal notices exclusively from its own persisted release/snapshot—not current global rows or the active pointer. `catalog_content_repository` injects the current active `ScenarioAuthority`/`ServiceAuthority` into public pages so rule-critical public facts change atomically with the active version. Task fixtures create clearly test-only reviewed legal documents; production seeds no legal prose and remains fail-closed until operators publish all four.

- [ ] **Step 5: Run the complete assessment/report/appointment/privacy partition**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests/test_assessment_flows.py tests/test_rule_release_runtime.py tests/test_rule_release_admin.py tests/test_legal_versions.py tests/test_assessment_catalog.py tests/test_assessment_v2_api.py tests/test_assessment_completion.py tests/test_report_access.py tests/test_assessment_wizard.py tests/test_core_journey.py tests/test_reporting.py tests/test_lead_export.py tests/test_public_catalog.py tests/test_public_services.py tests/test_appointments.py tests/test_analytics.py tests/test_lead_operations.py tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py -q
node --test tests/js/assessment_runtime.test.js
```

Expected: PASS with old and new versions completing safely and no history widening.

- [ ] **Step 6: Commit**

```bash
git add migrations/016_assessment_flow_enforcement.sql assessment_flow.py rule_release_runtime.py rule_release_service.py blueprints/admin/rules.py templates/admin/rule_releases.html templates/admin/rule_release_publish.html legal_repository.py lead_repository.py lead_export.py assessment_repository.py assessment_completion_service.py assessment_validation.py blueprints/assessment.py assessment/reporting.py templates/assessment/_report_content.html templates/assessment/report_pdf.html catalog_content_repository.py static/js/assessment.js tests/conftest.py tests/assessment_flow_helpers.py tests/test_app_factory_and_migrations.py tests/test_assessment_flows.py tests/test_rule_release_runtime.py tests/test_assessment_completion.py tests/test_assessment_v2_api.py tests/test_appointments.py tests/test_analytics.py tests/test_report_access.py tests/test_assessment_wizard.py tests/test_core_journey.py tests/test_lead_operations.py tests/test_reporting.py tests/test_lead_export.py tests/test_v2_migrations.py tests/js/assessment_runtime.test.js
git commit -m "feat: bind assessment flows to governed releases"
```

---

### Task 22: Verify and document the complete Stage 5 operations journey

**Files:**
- Create: `tests/test_operations_journey.py`
- Create: `docs/testing/content-operations.md`
- Create: `docs/testing/evidence/operations-*.png`
- Modify: `README.md`
- Modify: `docs/deployment/security-and-service.md`
- Modify: `D:/Codex干活/企业AI转型平台2.0升级/升级任务卡.md` after verification

**Interfaces:**
- Consumes: all 5A and 5B tasks.
- Produces: one reproducible Stage 5 verification command/evidence matrix and the Stage 6 handoff.

- [ ] **Step 1: Write HTTP/CLI-only integration journeys**

Create tests that use no repository imports or direct SQL. Before creating the disposable app, inject one reviewed test-only source-registry entry, enable only its code through test config, and inject a deterministic fake `PinnedHttpTransport` response. Never enable a checked-in production entry or contact the public network. Then cover:

1. scrape fixed candidate → review → accept to draft → publish → public resource;
2. dashboard card → identical filtered list → audited formula-safe CSV;
3. create/review/publish all four clearly test-only legal documents through authenticated admin HTTP → issue old flow → publish a new privacy version → issue a second same-branch flow in the same Session → both finish their exact legal versions;
4. copy active assessment version → edit → preview all four branches → atomically publish → new flow/public service uses it → old flow/report remains accessible/digest-stable;
5. every unauthorized/CSRF/invalid action fails without visible writes.

- [ ] **Step 2: Run Stage 5 integration and related partitions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_content_journey.py tests/test_operations_journey.py tests/test_ingestion_repository.py tests/test_content_ingestion.py tests/test_operations_pagination.py tests/test_operations_dashboard.py tests/test_lead_export.py tests/test_legal_versions.py tests/test_rule_release_drafts.py tests/test_rule_release_admin.py tests/test_assessment_flows.py tests/test_rule_release_runtime.py -q`

Expected: PASS.

- [ ] **Step 3: Document deployment and recovery operations**

Document media-directory backup/restore and ownership, ingestion network/licensing allowlist, `fetch-content` and `publish-due-content` timer rehearsals, CSV/governance audit retention, required four-document legal-review gate, rule-release preview/publish/rollback, flow TTL/limit behavior, active-pointer/snapshot health checks, staged migration rehearsal from a database that has each prior migration recorded, and exact rule/public-service/report smoke tests. Nginx remains stopped until the existing Stage 7 approval gate.

- [ ] **Step 4: Run browser acceptance**

Use disposable database/media plus the same reviewed test-only registry entry and deterministic fake pinned transport; enable it only in the disposable browser app and never access the public network. Before requesting any assessment config, create, review, and publish all four clearly labeled test legal documents through the real authenticated admin forms; do not rely on production seeds or direct SQL. Then capture:

1. ingestion review/accept/publish;
2. operations dashboard and linked overdue queue;
3. 390px lead filter and export confirmation without overflow;
4. legal version publish and public document;
5. rule release copy/preview/publish and two same-Session flows retaining new/old behavior.

Save `operations-ingestion.png`, `operations-dashboard.png`, `operations-mobile.png`, `operations-legal.png`, and `operations-rule-release.png`.

- [ ] **Step 5: Run final verification**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pip check
..\..\.venv\Scripts\python.exe -m compileall -q .
node --check static/js/app.js
node --check static/js/assessment.js
node --check static/js/content_editor.js
node --test tests/js/analytics_runtime.test.js tests/js/assessment_runtime.test.js tests/js/report_runtime.test.js tests/js/content_editor_runtime.test.js
git diff --check
..\..\.venv\Scripts\python.exe -m pytest -q
```

Expected: all commands exit 0. Record exact test counts/durations and inspect all evidence before claiming Stage 5 complete.

- [ ] **Step 6: Independent review, task-card update, and commit**

Review the full Stage 5 diff against every requirement in the approved spec. Resolve every P0–P2 finding. Mark Stage 5 complete and Stage 6 in progress only after the final review is CLEAN.

```bash
git add tests/test_operations_journey.py docs/testing/content-operations.md docs/testing/evidence README.md docs/deployment/security-and-service.md
git commit -m "docs: verify content operations platform"
```
