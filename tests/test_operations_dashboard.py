"""Actionable operations dashboard and bounded reminder queue contracts."""

from datetime import datetime
import importlib

from bs4 import BeautifulSoup
import pytest

import models
from content_clock import SHANGHAI
from pagination import PageRequest
from tests.assessment_flow_helpers import ensure_test_legal_bundle


NOW = datetime(2026, 9, 2, 0, 30, tzinfo=SHANGHAI)
QUEUE_CODES = (
    "pending_contact",
    "new_leads",
    "followup_today",
    "followup_overdue",
    "pending_appointments",
    "pending_ingestion",
    "scheduled_content",
    "draft_missing_required",
    "draft_complete",
    "open_privacy",
)


def _operations():
    try:
        return importlib.import_module("operations_repository")
    except ModuleNotFoundError:
        pytest.fail("operations_repository is required for the operations dashboard")


def _counts(snapshot):
    return {card.code: card.count for card in snapshot.cards}


def _insert_lead(
    db,
    suffix,
    *,
    status="new",
    followup=None,
    anonymized=False,
):
    marker = f"private-{suffix}"
    return db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,phone_normalized,email,wechat,status,owner_text,"
        "next_followup_at,anonymized_at,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"company-{suffix}",
            marker,
            f"1380000{suffix:04d}",
            f"{marker}@example.invalid",
            marker,
            status,
            marker,
            followup,
            "2026-09-01 12:00:00" if anonymized else None,
            "2026-09-01 10:00:00",
            "2026-09-01 10:00:00",
        ),
    ).lastrowid


def _insert_assessment(db, lead_id, suffix):
    return db.execute(
        "INSERT INTO assessments (lead_id,company_name,completed_at) VALUES (?,?,?)",
        (lead_id, f"assessment-{suffix}", "2026-09-01 10:00:00"),
    ).lastrowid


def _insert_ingestion(db, suffix, *, state="pending_review"):
    timestamp = "2026-09-01 10:00:00"
    candidate_id = db.execute(
        "INSERT INTO ingestion_candidates "
        "(source_code,source_name,canonical_url,content_sha256,title,licensed_summary,"
        "state,lock_version,created_at,updated_at) VALUES (?,?,?,?,?,?,'fetched',1,?,?)",
        (
            f"source-{suffix}",
            f"source {suffix}",
            f"https://example.invalid/{suffix}",
            f"{suffix:064x}"[-64:],
            f"candidate-{suffix}",
            "summary",
            timestamp,
            timestamp,
        ),
    ).lastrowid
    if state != "fetched":
        db.execute(
            "UPDATE ingestion_candidates SET state=?,lock_version=2 WHERE id=?",
            (state, candidate_id),
        )
    return candidate_id


def _insert_content_base(db, entry_type, suffix, *, publish_at=None, blank_title=False):
    timestamp = "2026-09-01 10:00:00"
    group_columns = "entry_type,canonical_slug,created_at,updated_at"
    group_values = [entry_type, f"ops-{entry_type}-{suffix}", timestamp, timestamp]
    owner_id = None
    if entry_type == "industry":
        owner_id = db.execute(
            "INSERT INTO industries (code,name,status) VALUES (?,?,'draft')",
            (f"ops-industry-{suffix}", f"Industry {suffix}"),
        ).lastrowid
        group_columns = "entry_type,industry_id,canonical_slug,created_at,updated_at"
        group_values.insert(1, owner_id)
    elif entry_type == "scenario":
        owner_id = db.execute(
            "INSERT INTO scenarios "
            "(code,category_code,public_name,minimum_business_value,minimum_process,"
            "minimum_data,minimum_systems,minimum_organization,minimum_delivery,"
            "integration_level,min_weeks,max_weeks,risk_codes_json,fallback_only,status) "
            "VALUES (?,?,?,1,1,1,1,1,1,'low',1,1,'[]',0,'draft')",
            (f"ops-scenario-{suffix}", "ops", f"Scenario {suffix}"),
        ).lastrowid
        group_columns = "entry_type,scenario_id,canonical_slug,created_at,updated_at"
        group_values.insert(1, owner_id)
    elif entry_type == "service":
        owner_id = db.execute(
            "INSERT INTO services (name,tier,code,status) VALUES (?,?,?,'draft')",
            (f"Service {suffix}", "ops", f"ops-service-{suffix}"),
        ).lastrowid
        group_columns = "entry_type,service_id,canonical_slug,created_at,updated_at"
        group_values.insert(1, owner_id)
    group_id = db.execute(
        f"INSERT INTO content_groups ({group_columns}) VALUES ({','.join('?' for _ in group_values)})",
        tuple(group_values),
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,publish_at,lock_version,created_at,updated_at) "
        "VALUES (?,?,1,?,?,?,?,?,'draft',?,1,?,?)",
        (
            group_id,
            entry_type,
            f"ops-{entry_type}-{suffix}",
            "\u00a0\t" if blank_title else f"Title {suffix}",
            "Summary",
            f"SEO {suffix}",
            "Description",
            publish_at,
            timestamp,
            timestamp,
        ),
    ).lastrowid
    return item_id, owner_id


def _complete_content_structure(db, item_id, owner_id, entry_type):
    if entry_type == "industry":
        db.execute(
            "INSERT INTO industry_content (content_item_id,industry_id) VALUES (?,?)",
            (item_id, owner_id),
        )
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,body_html) "
            "VALUES (?,'rich_text','<p>body</p>')",
            (item_id,),
        )
    elif entry_type == "scenario":
        db.execute(
            "INSERT INTO scenario_content (content_item_id,scenario_id) VALUES (?,?)",
            (item_id, owner_id),
        )
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,body_html) "
            "VALUES (?,'rich_text','<p>body</p>')",
            (item_id,),
        )
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) "
            "VALUES (?,'input',1)",
            (item_id,),
        )
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) "
            "VALUES (?,'explore',0)",
            (item_id,),
        )
    elif entry_type == "service":
        db.execute(
            "INSERT INTO service_content (content_item_id,service_id) VALUES (?,?)",
            (item_id, owner_id),
        )
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,body_html) "
            "VALUES (?,'rich_text','<p>body</p>')",
            (item_id,),
        )
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) "
            "VALUES (?,'pilot',0)",
            (item_id,),
        )
    elif entry_type == "case":
        db.execute(
            "INSERT INTO case_content "
            "(content_item_id,verification_code,is_anonymized,basis_type,"
            "private_basis_reference) VALUES (?,'authorized_anonymous',1,"
            "'private_authorization','authorization')",
            (item_id,),
        )
        db.execute(
            "INSERT INTO case_metrics "
            "(case_content_item_id,name,before_value,after_value,unit,"
            "statistical_period,evidence_explanation) VALUES "
            "(?,'cycle','10','5','days','2026 Q2','audited')",
            (item_id,),
        )
    elif entry_type == "resource":
        db.execute(
            "INSERT INTO resource_content "
            "(content_item_id,resource_type,is_original,original_published_at,"
            "copyright_notice) VALUES (?,'guide',1,'2026-08-01 10:00:00','owned')",
            (item_id,),
        )
    elif entry_type == "announcement":
        db.execute(
            "INSERT INTO announcement_content (content_item_id,valid_from,valid_until) "
            "VALUES (?,'2026-09-01 00:00:00','2026-10-01 00:00:00')",
            (item_id,),
        )


def _incomplete_content_structure(db, item_id, owner_id, entry_type):
    """Insert the matching extension while omitting one matrix-owned requirement."""
    if entry_type == "industry":
        db.execute(
            "INSERT INTO industry_content (content_item_id,industry_id) VALUES (?,?)",
            (item_id, owner_id),
        )
    elif entry_type == "scenario":
        db.execute(
            "INSERT INTO scenario_content (content_item_id,scenario_id) VALUES (?,?)",
            (item_id, owner_id),
        )
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,body_html) "
            "VALUES (?,'rich_text','<p>body</p>')",
            (item_id,),
        )
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) "
            "VALUES (?,'explore',0)",
            (item_id,),
        )
    elif entry_type == "service":
        db.execute(
            "INSERT INTO service_content (content_item_id,service_id) VALUES (?,?)",
            (item_id, owner_id),
        )
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,body_html) "
            "VALUES (?,'rich_text','<p>body</p>')",
            (item_id,),
        )
    elif entry_type == "case":
        db.execute(
            "INSERT INTO case_content "
            "(content_item_id,verification_code,is_anonymized,basis_type,"
            "private_basis_reference) VALUES (?,'authorized_anonymous',1,"
            "'private_authorization','authorization')",
            (item_id,),
        )
    elif entry_type == "resource":
        db.execute(
            "INSERT INTO resource_content (content_item_id,resource_type,is_original) "
            "VALUES (?,'guide',1)",
            (item_id,),
        )
    elif entry_type == "announcement":
        db.execute(
            "INSERT INTO announcement_content (content_item_id,valid_from,valid_until) "
            "VALUES (?,'2026-09-01 00:00:00','2026-09-01 00:00:00')",
            (item_id,),
        )


def _all_queue_ids(repository, code):
    first = repository.query_operation_queue(code, PageRequest(1, 50), NOW)
    ids = [row["id"] for row in first.items]
    for page_number in range(2, first.total_pages + 1):
        page = repository.query_operation_queue(
            code, PageRequest(page_number, 50), NOW
        )
        ids.extend(row["id"] for row in page.items)
    return ids


def test_dashboard_has_ten_stable_cards_and_each_count_equals_linked_detail(
    admin_client,
):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW

    response = admin_client.get("/admin")

    assert response.status_code == 200
    dashboard = BeautifulSoup(response.data, "html.parser")
    cards = dashboard.select("[data-operation-card]")
    assert tuple(card["data-queue"] for card in cards) == QUEUE_CODES
    assert tuple(card.a["href"] for card in cards) == tuple(
        f"/admin?queue={code}" for code in QUEUE_CODES
    )
    for card in cards:
        linked_response = admin_client.get(card.a["href"])
        linked = BeautifulSoup(linked_response.data, "html.parser")
        assert linked_response.status_code == 200
        assert int(card["data-count"]) == int(
            linked.select_one("[data-total]")["data-total"]
        )
    assert "必填字段待补" in dashboard.get_text(" ", strip=True)
    assert "字段完整，待人工复核" in dashboard.get_text(" ", strip=True)
    assert "可发布" not in dashboard.get_text(" ", strip=True)


def test_workflow_counts_freeze_shanghai_boundaries_and_privacy_rules(
    db, admin_client
):
    repository = _operations()
    privacy_id = ensure_test_legal_bundle()["privacy"]
    pending = _insert_lead(db, 1, status="pending_contact")
    new = _insert_lead(db, 2, status="new")
    today_start = _insert_lead(db, 3, status="contacted", followup="2026-09-02 00:00:00")
    today_end = _insert_lead(db, 4, status="proposal", followup="2026-09-02 23:59:59")
    tomorrow = _insert_lead(db, 5, status="contacted", followup="2026-09-03 00:00:00")
    overdue = _insert_lead(db, 6, status="contacted", followup="2026-09-01 23:59:59")
    hidden = _insert_lead(
        db,
        7,
        status="pending_contact",
        followup="2026-09-02 10:00:00",
        anonymized=True,
    )
    visible_assessment = _insert_assessment(db, pending, 1)
    hidden_assessment = _insert_assessment(db, hidden, 2)
    db.execute(
        "UPDATE assessments SET company_name='private-7',"
        "contact_email='private-7@example.invalid',"
        "report_snapshot_json='{""private"":""private-7""}' WHERE id=?",
        (hidden_assessment,),
    )
    db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
        "VALUES (?,'test-privacy-v1','2026-09-01 10:00:00',"
        "'private-7','hidden-consent',?)",
        (hidden, privacy_id),
    )
    db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,status) "
        "VALUES (?,?,?,'2026-09-10','morning','pending')",
        (visible_assessment, pending, "visible-appointment"),
    )
    db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,status) "
        "VALUES (?,?,?,'2026-09-10','morning','pending')",
        (hidden_assessment, hidden, "hidden-appointment"),
    )
    _insert_ingestion(db, 1)
    db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at) "
        "VALUES (?,'visible','access','received','email','2026-09-01 10:00:00')",
        (new,),
    )
    hidden_request = db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at) "
        "VALUES (?,'hidden','deletion','verifying','email','2026-09-01 11:00:00')",
        (hidden,),
    ).lastrowid
    db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at) "
        "VALUES (?,'closed','access','completed','email','2026-09-01 12:00:00')",
        (new,),
    )
    db.commit()

    counts = _counts(repository.dashboard_snapshot(NOW))

    assert counts["pending_contact"] == 1
    assert counts["new_leads"] == 1
    assert counts["followup_today"] == 2
    assert counts["followup_overdue"] == 1
    assert counts["pending_appointments"] == 1
    assert counts["pending_ingestion"] == 1
    assert counts["open_privacy"] == 2
    assert tomorrow not in _all_queue_ids(repository, "followup_today")
    assert overdue not in _all_queue_ids(repository, "followup_today")
    assert {today_start, today_end}.issubset(
        set(_all_queue_ids(repository, "followup_today"))
    )

    privacy = repository.query_operation_queue(
        "open_privacy", PageRequest(1, 20), NOW
    )
    hidden_row = next(row for row in privacy.items if row["id"] == hidden_request)
    for field in (
        "company_name",
        "contact_name",
        "phone_normalized",
        "email",
        "wechat",
        "owner_text",
    ):
        assert hidden_row[field] is None
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    privacy_html = admin_client.get("/admin?queue=open_privacy").get_data(as_text=True)
    assert "private-7" not in privacy_html
    assert "private-7@example.invalid" not in privacy_html


def test_selected_queue_supports_20_50_and_clamps_overflow(db):
    repository = _operations()
    for suffix in range(100, 155):
        _insert_lead(db, suffix, status="new")
    db.commit()

    first = repository.query_operation_queue(
        "new_leads", PageRequest(1, 20), NOW
    )
    fifty = repository.query_operation_queue(
        "new_leads", PageRequest(1, 50), NOW
    )
    overflow = repository.query_operation_queue(
        "new_leads", PageRequest(999, 20), NOW
    )

    assert (first.total, len(first.items), first.page, first.per_page) == (55, 20, 1, 20)
    assert (fifty.total, len(fifty.items), fifty.page, fifty.per_page) == (55, 50, 1, 50)
    assert (overflow.total, len(overflow.items), overflow.page) == (55, 15, 3)


def test_snapshot_uses_one_count_per_card_and_detail_adds_one_bounded_select(
    client, monkeypatch
):
    repository = _operations()
    statements = []
    real_get_db = models.get_db

    def traced_connection():
        connection = real_get_db()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repository, "get_db", traced_connection)

    repository.dashboard_snapshot(NOW)
    snapshot_selects = [
        sql for sql in statements if sql.lstrip().upper().startswith("SELECT")
    ]
    assert len(snapshot_selects) == 10
    assert all(sql.lstrip().upper().startswith("SELECT COUNT(") for sql in snapshot_selects)
    assert sum(sql.upper().count("COUNT(") for sql in snapshot_selects) == 10

    statements.clear()
    repository.query_operation_queue(
        "pending_contact", PageRequest(1, 20), NOW
    )
    detail_selects = [
        sql for sql in statements if sql.lstrip().upper().startswith("SELECT")
    ]
    assert len(detail_selects) == 2
    assert sum(sql.lstrip().upper().startswith("SELECT COUNT(") for sql in detail_selects) == 1
    assert sum(" LIMIT " in sql.upper() for sql in detail_selects) == 1


def test_scheduled_content_is_cross_type_and_ordered_by_publish_time(db):
    repository = _operations()
    expected = []
    for index, entry_type in enumerate(
        ("announcement", "resource", "case", "service", "scenario", "industry")
    ):
        item_id, _ = _insert_content_base(
            db,
            entry_type,
            f"scheduled-{index}",
            publish_at=f"2026-09-{10 + index:02d} 09:00:00",
        )
        expected.append((item_id, entry_type))
    db.commit()

    page = repository.query_operation_queue(
        "scheduled_content", PageRequest(1, 50), NOW
    )
    actual = [(row["id"], row["entry_type"]) for row in page.items]

    positions = [actual.index(item) for item in expected]
    assert positions == sorted(positions)
    assert set(expected).issubset(set(actual))


def test_structural_completeness_matrix_is_complementary_and_exhaustive(db):
    repository = _operations()
    complete_ids = []
    missing_ids = []
    for index, entry_type in enumerate(
        ("industry", "scenario", "service", "case", "resource", "announcement")
    ):
        complete_id, complete_owner = _insert_content_base(
            db, entry_type, f"complete-{index}"
        )
        _complete_content_structure(db, complete_id, complete_owner, entry_type)
        complete_ids.append(complete_id)

        missing_id, missing_owner = _insert_content_base(
            db, entry_type, f"missing-{index}"
        )
        _incomplete_content_structure(db, missing_id, missing_owner, entry_type)
        missing_ids.append(missing_id)
    malformed_id, malformed_owner = _insert_content_base(
        db, "industry", "blank-base", blank_title=True
    )
    _complete_content_structure(db, malformed_id, malformed_owner, "industry")
    missing_ids.append(malformed_id)
    db.commit()

    complete_actual = set(_all_queue_ids(repository, "draft_complete"))
    missing_actual = set(_all_queue_ids(repository, "draft_missing_required"))
    unscheduled = {
        row[0]
        for row in db.execute(
            "SELECT id FROM content_items WHERE status='draft' AND publish_at IS NULL"
        )
    }

    assert set(complete_ids).issubset(complete_actual)
    assert set(missing_ids).issubset(missing_actual)
    assert complete_actual.isdisjoint(missing_actual)
    assert complete_actual | missing_actual == unscheduled


def test_non_original_resource_requires_static_source_fields(db):
    repository = _operations()
    complete_id, _ = _insert_content_base(db, "resource", "external-complete")
    db.execute(
        "INSERT INTO resource_content "
        "(content_item_id,resource_type,is_original,source_name,source_url,"
        "source_url_sha256,original_published_at,copyright_notice) "
        "VALUES (?,'report',0,'Publisher','https://example.invalid/report',?,"
        "'2026-08-01 10:00:00','licensed')",
        (complete_id, "a" * 64),
    )
    missing_id, _ = _insert_content_base(db, "resource", "external-missing")
    db.execute(
        "INSERT INTO resource_content "
        "(content_item_id,resource_type,is_original,source_name,source_url,"
        "original_published_at,copyright_notice) "
        "VALUES (?,'report',0,'Publisher','https://example.invalid/report',"
        "'2026-08-01 10:00:00','licensed')",
        (missing_id,),
    )
    db.commit()

    assert complete_id in _all_queue_ids(repository, "draft_complete")
    assert missing_id in _all_queue_ids(repository, "draft_missing_required")


@pytest.mark.parametrize(
    "basis_type", ("client_authorization", "internal_delivery_record")
)
def test_case_structural_completeness_excludes_publication_review_gates(
    db, basis_type
):
    repository = _operations()
    item_id, _ = _insert_content_base(db, "case", f"structural-{basis_type}")
    db.execute(
        "INSERT INTO case_content "
        "(content_item_id,verification_code,is_anonymized,basis_type,"
        "private_basis_reference,is_verified,review_confirmed) "
        "VALUES (?,'awaiting_review',1,?,'evidence-reference',0,0)",
        (item_id, basis_type),
    )
    db.execute(
        "INSERT INTO case_metrics "
        "(case_content_item_id,name,before_value,after_value,unit,"
        "statistical_period,evidence_explanation) VALUES "
        "(?,'cycle','10','5','days','2026 Q2','audited evidence')",
        (item_id,),
    )
    db.commit()

    assert item_id in _all_queue_ids(repository, "draft_complete")
    assert item_id not in _all_queue_ids(repository, "draft_missing_required")


@pytest.mark.parametrize(
    ("verification_code", "basis_type", "private_reference"),
    (
        (" ", "internal_delivery_record", "evidence-reference"),
        ("awaiting_review", "private_authorization", " "),
    ),
)
def test_case_structural_completeness_rejects_blank_static_extension_fields(
    db, verification_code, basis_type, private_reference
):
    repository = _operations()
    item_id, _ = _insert_content_base(
        db, "case", f"malformed-{basis_type}-{verification_code.strip() or 'blank'}"
    )
    db.execute(
        "INSERT INTO case_content "
        "(content_item_id,verification_code,is_anonymized,basis_type,"
        "private_basis_reference,is_verified,review_confirmed) "
        "VALUES (?,?,1,?,?,0,0)",
        (item_id, verification_code, basis_type, private_reference),
    )
    db.execute(
        "INSERT INTO case_metrics "
        "(case_content_item_id,name,before_value,after_value,unit,"
        "statistical_period,evidence_explanation) VALUES "
        "(?,'cycle','10','5','days','2026 Q2','audited evidence')",
        (item_id,),
    )
    db.commit()

    assert item_id in _all_queue_ids(repository, "draft_missing_required")
    assert item_id not in _all_queue_ids(repository, "draft_complete")


def test_draft_queue_plans_materialize_complete_case_metrics_once(db):
    repository = _operations()
    for suffix in range(64):
        item_id, owner_id = _insert_content_base(db, "case", f"plan-{suffix}")
        _complete_content_structure(db, item_id, owner_id, "case")
    db.commit()
    db.execute("ANALYZE")

    for code in ("draft_complete", "draft_missing_required"):
        query = repository._queue_query(code, NOW)
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*)" + query.from_sql + query.where_sql,
            query.parameters,
        ).fetchall()
        by_id = {row["id"]: row for row in plan}
        metric_scans = [
            row
            for row in plan
            if row["detail"].split()[0] in {"SCAN", "SEARCH"}
            and row["detail"].split()[1].lower() == "cm"
        ]

        assert len(metric_scans) == 1, "\n".join(row["detail"] for row in plan)
        metric_parent = by_id[metric_scans[0]["parent"]]["detail"]
        assert "LIST SUBQUERY" in metric_parent
        assert "CORRELATED" not in metric_parent


def test_invalid_get_defaults_and_zero_detail_are_rendered(admin_client):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW

    invalid = admin_client.get(
        "/admin?queue=not-a-queue&page=bad&per_page=999999"
    )
    empty = admin_client.get("/admin?queue=new_leads&page=999&per_page=50")
    invalid_pagination = admin_client.get(
        "/admin?queue=new_leads&page=bad&per_page=999999"
    )

    assert invalid.status_code == 200
    invalid_page = BeautifulSoup(invalid.data, "html.parser")
    assert invalid_page.select_one("[data-operations-dashboard]") is not None
    assert invalid_page.select_one("[data-operations-queue]") is None
    empty_page = BeautifulSoup(empty.data, "html.parser")
    assert empty_page.select_one('[data-operations-queue="new_leads"]') is not None
    assert empty_page.select_one("[data-empty-state]") is not None
    pagination = empty_page.select_one('[data-pagination="operations"]')
    assert pagination["data-per-page"] == "50"
    safe_page = BeautifulSoup(invalid_pagination.data, "html.parser")
    assert safe_page.select_one('[data-pagination="operations"]')["data-per-page"] == "20"


def test_admin_url_has_one_operations_owner_and_preserves_endpoint(admin_client):
    rules = [
        rule for rule in admin_client.application.url_map.iter_rules() if rule.rule == "/admin"
    ]

    assert len(rules) == 1
    assert rules[0].endpoint == "admin.admin_index"
    owner = admin_client.application.view_functions[rules[0].endpoint]
    assert owner.__module__ == "blueprints.admin.operations"


def test_dashboard_redirects_anonymous_and_all_admin_outcomes_are_no_store(
    admin_client, monkeypatch
):
    anonymous = admin_client.application.test_client()
    assert anonymous.get("/admin").status_code == 302

    success = admin_client.get("/admin")
    missing = admin_client.get("/admin/does-not-exist")
    assert success.status_code == 200
    assert missing.status_code == 404
    for response in (success, missing):
        assert response.headers["Cache-Control"] == "private, no-store"

    operations = importlib.import_module("blueprints.admin.operations")

    def fail_snapshot(now):
        raise RuntimeError("dashboard unavailable")

    monkeypatch.setattr(operations, "dashboard_snapshot", fail_snapshot)
    failed = admin_client.get("/admin")
    assert failed.status_code == 500
    assert failed.headers["Cache-Control"] == "private, no-store"
