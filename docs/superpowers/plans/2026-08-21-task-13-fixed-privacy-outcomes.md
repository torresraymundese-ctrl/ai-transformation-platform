# Task 13 Fixed Privacy Outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace privacy-request free-text outcomes with request-scoped stable codes whose fixed Chinese labels are the only values persisted.

**Architecture:** The lead repository owns immutable completion/rejection code catalogs and resolves codes only after loading the current request inside its existing `BEGIN IMMEDIATE` transaction. The admin route forwards only `outcome_code`, rejects the retired `resolution_note` input, and the template renders select controls from repository-provided choices while continuing to display historical stored labels.

**Tech Stack:** Python 3, Flask/Jinja, SQLite, pytest, BeautifulSoup.

**Spec:** `docs/superpowers/specs/2026-08-19-ai-platform-2.0-product-design.md` sections 2, 9, 10, 15 and 16; Task 13 ruling in `.superpowers/sdd/2026-08-19-core-assessment-report/progress.md`.

## Global Constraints

- Task 13 only; do not start Task 14 or contact production.
- Keep the shared admin account, CSRF, audit, private/no-store responses and state machines unchanged.
- Withdrawal/deletion completion still requires explicit confirmation and uses the same atomic `anonymize_lead()` transaction.
- Existing `resolution_note` labels remain displayable; no schema migration is required.
- No submitted arbitrary outcome text may persist, echo in an error response, or appear in logs.

---

### Task 1: Specify the closed outcome domain through failing HTTP tests

**Files:**
- Modify: `tests/test_lead_operations.py`

**Interfaces:**
- Consumes: `POST /admin/data-requests` and the existing `data_subject_requests.resolution_note` column.
- Produces: literal completion/rejection cases and rollback assertions that define the repository contract.

- [x] **Step 1: Replace free-text success tests with literal allowlist cases**

Use these independently specified completion cases:

```python
(
    ("access", "access_copy_provided", "已向申请人提供个人信息副本"),
    ("access", "access_no_data", "核验后确认无可提供的个人信息"),
    ("correction", "correction_completed", "已按核验结果完成信息更正"),
    ("correction", "correction_no_change", "核验后确认无需更正"),
    ("withdrawal", "withdrawal_anonymized", "已完成授权撤回并匿名化相关信息"),
    ("deletion", "deletion_anonymized", "已完成删除请求并匿名化相关信息"),
)
```

Use these rejection cases:

```python
(
    ("identity_verification_failed", "身份核验未通过"),
    ("request_scope_incomplete", "请求范围不明确，需补充信息"),
    ("request_not_applicable", "经核验，该请求不符合处理条件"),
)
```

Each case posts `outcome_code`, observes a redirect, and asserts that the exact literal label (never the code) is stored. Completion tests confirm only withdrawal/deletion anonymize, and every literal label is at most 1,000 characters.

- [x] **Step 2: Add closed-domain and rollback tests**

Post a wrong request-type completion code, an unknown rejection code, and retired/arbitrary `resolution_note` values containing ordinary text, target identifiers, phone/WeChat text, U+034F, U+115F/U+1160 and U+17B4/U+17B5. Assert generic 400, no submitted value in response/logs, request remains `verifying`, and lead/follow-up/anonymization state is unchanged.

- [x] **Step 3: Add template behavior tests**

Render a verifying request and assert there is no `textarea` or `resolution_note` control. Assert completion and rejection forms expose only `select[name="outcome_code"]`, that completion options match the current request type, and historical stored labels still render.

- [x] **Step 4: Run focused tests and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests/test_lead_operations.py -k "outcome or arbitrary or data_request_page" -q
```

Expected: failures because the route still accepts `resolution_note`, the repository has no code catalog, and the template still renders textareas.

---

### Task 2: Implement transactional code resolution and select-only UI

**Files:**
- Modify: `lead_repository.py`
- Modify: `blueprints/admin/leads.py`
- Modify: `templates/admin/data_requests.html`

**Interfaces:**
- Consumes: the literal code/label domain defined in Task 1.
- Produces: `COMPLETION_OUTCOMES`, `REJECTION_OUTCOMES`, transactional `outcome_code` resolution, and select-only admin forms.

- [x] **Step 1: Define ordered code catalogs**

Add the six completion and three rejection code/label pairs exactly as specified in Task 1. Completion choices are keyed by `access`, `correction`, `withdrawal`, and `deletion`; rejection choices are shared. Keep every label non-identifying and at most 1,000 characters.

- [x] **Step 2: Resolve codes inside existing immediate transactions**

Change `transition_data_subject_request(..., outcome_code="", ...)` so `verifying` accepts only an empty code and `rejected` resolves only `REJECTION_OUTCOMES`. Change `complete_data_subject_request(..., outcome_code, ...)` so it resolves only the catalog for the loaded row's `request_type`. Perform resolution after loading and validating the request/status inside the `_run_immediate` callback; raise a generic `ValidationError("privacy outcome has an invalid value")` on any mismatch. Persist only the fixed label.

- [x] **Step 3: Remove dead free-text detection**

Delete `validate_resolution_note` and its phone, WeChat, sanitization and Unicode helpers/constants/imports once repository call sites use only fixed labels. Retain `re`, which other repository validation still uses.

- [x] **Step 4: Restrict the route and render selects**

Reject any submitted `resolution_note` form key generically. Forward only `outcome_code`. Pass completion/rejection catalogs to the template. Replace both textareas with required select controls; use only request-type completion choices and the shared rejection catalog. Keep the withdrawal/deletion confirmation checkbox unchanged and keep `{{ item.resolution_note or '-' }}` for existing results.

- [x] **Step 5: Run focused and related GREEN verification**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests/test_lead_operations.py -q
..\..\.venv\Scripts\python.exe -m pytest tests/test_admin_auth.py tests/test_rate_limits_and_audit.py tests/test_security_gaps.py tests/test_assessment_completion.py -q
```

Expected: all pass with the closed outcome domain and unchanged security/transaction behavior.

---

### Task 3: Final verification, report and commit

**Files:**
- Modify: `.superpowers/sdd/2026-08-19-core-assessment-report/task-13-report.md` (ignored evidence ledger)
- Commit: `docs/superpowers/plans/2026-08-21-task-13-fixed-privacy-outcomes.md`, `lead_repository.py`, `blueprints/admin/leads.py`, `templates/admin/data_requests.html`, `tests/test_lead_operations.py`

**Interfaces:**
- Consumes: the completed Task 13 code and tests.
- Produces: fresh verification evidence and one reviewable Task 13 commit.

- [x] **Step 1: Run one final full suite**

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q
```

- [x] **Step 2: Run static and dependency checks**

```powershell
..\..\.venv\Scripts\python.exe -m compileall -q lead_repository.py blueprints/admin/leads.py tests/test_lead_operations.py
..\..\.venv\Scripts\python.exe -m pip check
git diff --check
```

- [x] **Step 3: Self-review and append the Task 13 evidence**

Verify the code domain is exhaustive, request-type mismatch is closed, no free-text field/call site remains, legacy labels render, errors are generic, anonymization remains atomic, and no unrelated/production files changed. Append RED/GREEN/full/check evidence to the ignored Task 13 report.

- [ ] **Step 4: Commit the explicit Task 13 files**

```powershell
git add docs/superpowers/plans/2026-08-21-task-13-fixed-privacy-outcomes.md lead_repository.py blueprints/admin/leads.py templates/admin/data_requests.html tests/test_lead_operations.py
git commit -m "fix: close privacy outcome domain"
```
