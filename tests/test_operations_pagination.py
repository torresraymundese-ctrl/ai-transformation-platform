"""Operations queues share one bounded pagination and filter contract."""

from dataclasses import is_dataclass
import sqlite3

import appointment_repository
import catalog_content_repository
import case_repository
import ingestion_repository
import lead_repository
import media_service
import pytest
import resource_repository
from bs4 import BeautifulSoup
from pagination import PageRequest, parse_pagination


def test_page_request_accepts_only_documented_sizes_and_safe_defaults():
    assert parse_pagination({"page": "2", "per_page": "20"}) == PageRequest(2, 20)
    assert parse_pagination({"page": "2", "per_page": "50"}) == PageRequest(2, 50)
    assert parse_pagination({"page": "bogus", "per_page": "10000"}) == PageRequest(1, 20)


def test_operations_filter_dtos_parse_invalid_get_values_to_safe_defaults():
    lead_filters = lead_repository.parse_lead_filters(
        {
            "status": "not-a-status",
            "branch": "not-a-branch",
            "queue": "not-a-queue",
            "q": "x" * 500,
        }
    )
    appointment_filters = appointment_repository.parse_appointment_filters(
        {"status": "not-a-status", "q": "x" * 500}
    )
    request_filters = lead_repository.parse_data_request_filters(
        {"status": "not-a-status", "request_type": "not-a-type", "q": "x" * 500}
    )

    assert is_dataclass(lead_filters)
    assert is_dataclass(appointment_filters)
    assert is_dataclass(request_filters)
    assert lead_filters.status is None
    assert lead_filters.branch is None
    assert lead_filters.queue == "ordinary"
    assert lead_filters.search is None
    assert appointment_filters.status is None
    assert appointment_filters.search is None
    assert request_filters.status is None
    assert request_filters.request_type is None
    assert request_filters.search is None


@pytest.mark.parametrize(
    "path",
    (
        "/admin/leads?status=invalid&branch=invalid&queue=invalid&page=bad&per_page=10000",
        "/admin/appointments?status=invalid&page=bad&per_page=10000",
        "/admin/data-requests?status=invalid&request_type=invalid&page=bad&per_page=10000",
        "/admin/catalog/scenario?status=invalid&page=bad&per_page=10000",
        "/admin/cases?status=invalid&page=bad&per_page=10000",
        "/admin/resources?status=invalid&page=bad&per_page=10000",
        "/admin/announcements?status=invalid&page=bad&per_page=10000",
        "/admin/media?status=invalid&page=bad&per_page=10000",
        "/admin/ingestion?state=invalid&page=bad&per_page=10000",
    ),
)
def test_invalid_get_filters_fall_back_inside_authenticated_admin_shell(
    admin_client, path
):
    response = admin_client.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"


def _insert_lead(db, index, *, anonymized=False, followup=None):
    timestamp = f"2026-08-{(index % 20) + 1:02d} 10:00:00"
    return db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,status,next_followup_at,anonymized_at,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            f"company-{index:03d}",
            f"contact-{index:03d}",
            "new",
            followup,
            timestamp if anonymized else None,
            timestamp,
            timestamp,
        ),
    ).lastrowid


def test_lead_pages_freeze_workflow_order_overflow_and_anonymized_boundary(db):
    created = [_insert_lead(db, index) for index in range(55)]
    hidden_id = _insert_lead(db, 99, anonymized=True)
    db.commit()

    first = lead_repository.query_leads(
        lead_repository.LeadFilters(), PageRequest(1, 20)
    )
    last = lead_repository.query_leads(
        lead_repository.LeadFilters(), PageRequest(999, 20)
    )

    expected = [
        row[0]
        for row in db.execute(
            "SELECT id FROM leads WHERE anonymized_at IS NULL "
            "ORDER BY created_at DESC,id DESC"
        )
    ]
    assert first.total == 55
    assert [row["id"] for row in first.items] == expected[:20]
    assert last.page == 3
    assert [row["id"] for row in last.items] == expected[40:]
    assert hidden_id not in created
    assert hidden_id not in [row["id"] for row in first.items + last.items]


def test_followup_queue_excludes_nulls_and_orders_ascending(db):
    later = _insert_lead(db, 1, followup="2026-09-02 09:00:00")
    earlier = _insert_lead(db, 2, followup="2026-09-01 09:00:00")
    _insert_lead(db, 3, followup=None)
    db.commit()

    page = lead_repository.query_leads(
        lead_repository.LeadFilters(queue="followup"), PageRequest(1, 20)
    )

    assert [row["id"] for row in page.items] == [earlier, later]


def test_search_escapes_sql_wildcards_and_never_recovers_anonymized_contacts(db):
    literal = db.execute(
        "INSERT INTO leads (company_name,contact_name,status,created_at,updated_at) "
        "VALUES ('literal%company','visible','new','2026-08-01 10:00:00','2026-08-01 10:00:00')"
    ).lastrowid
    db.execute(
        "INSERT INTO leads (company_name,contact_name,status,created_at,updated_at) "
        "VALUES ('literalXcompany','other','new','2026-08-01 10:00:00','2026-08-01 10:00:00')"
    )
    hidden = db.execute(
        "INSERT INTO leads (company_name,contact_name,email,status,anonymized_at,created_at,updated_at) "
        "VALUES ('erased','private-marker','private@example.invalid','new',"
        "'2026-08-01 11:00:00','2026-08-01 10:00:00','2026-08-01 10:00:00')"
    ).lastrowid
    db.execute(
        "INSERT INTO assessments (lead_id,company_name,contact_email,report_snapshot_json,completed_at) "
        "VALUES (?,?,?,?,?)",
        (hidden, "private-marker", "private@example.invalid", '{"text":"private-marker"}', "2026-08-01 10:00:00"),
    )
    db.execute(
        "INSERT INTO lead_consents (lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (hidden, "v1", "2026-08-01 10:00:00", "private-marker", "digest"),
    )
    db.commit()

    wildcard = lead_repository.query_leads(
        lead_repository.parse_lead_filters({"q": "%"}), PageRequest(1, 20)
    )
    private = lead_repository.query_leads(
        lead_repository.parse_lead_filters({"q": "private-marker"}), PageRequest(1, 20)
    )

    assert [row["id"] for row in wildcard.items] == [literal]
    assert private.total == 0


def test_appointment_and_privacy_pages_use_exact_orders_and_privacy_masking(db):
    visible = _insert_lead(db, 1)
    hidden = _insert_lead(db, 2, anonymized=True)
    first_assessment = db.execute(
        "INSERT INTO assessments (lead_id,company_name) VALUES (?,?)", (visible, "visible")
    ).lastrowid
    hidden_assessment = db.execute(
        "INSERT INTO assessments (lead_id,company_name) VALUES (?,?)", (hidden, "hidden")
    ).lastrowid
    later = db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
        "VALUES (?,?,?,?,?,?)",
        (first_assessment, visible, "later", "2026-09-02", "afternoon", "later"),
    ).lastrowid
    earlier = db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
        "VALUES (?,?,?,?,?,?)",
        (first_assessment, visible, "earlier", "2026-09-01", "morning", "earlier"),
    ).lastrowid
    db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
        "VALUES (?,?,?,?,?,?)",
        (hidden_assessment, hidden, "hidden", "2026-08-01", "morning", "hidden"),
    )
    newest_request = db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at) "
        "VALUES (?,'a','access','received','email','2026-09-02 10:00:00')",
        (visible,),
    ).lastrowid
    older_request = db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at) "
        "VALUES (?,'b','deletion','verifying','email','2026-09-01 10:00:00')",
        (hidden,),
    ).lastrowid
    db.commit()

    appointments = appointment_repository.query_appointments(
        appointment_repository.AppointmentFilters(), PageRequest(1, 20)
    )
    requests = lead_repository.query_data_subject_requests(
        lead_repository.DataRequestFilters(status="open"), PageRequest(1, 20)
    )

    assert [row["id"] for row in appointments.items] == [earlier, later]
    assert [row["id"] for row in requests.items] == [newest_request, older_request]
    hidden_row = next(row for row in requests.items if row["id"] == older_request)
    assert hidden_row["company_name"] is None
    assert hidden_row["contact_name"] is None


def test_remaining_operations_filters_have_bounded_safe_defaults():
    modules_and_parsers = (
        (catalog_content_repository, "parse_admin_catalog_filters", "status"),
        (case_repository, "parse_case_filters", "status"),
        (resource_repository, "parse_admin_entry_filters", "status"),
        (ingestion_repository, "parse_ingestion_filters", "state"),
        (media_service, "parse_media_filters", "status"),
    )
    for module, name, enum_field in modules_and_parsers:
        parsed = getattr(module, name)({"status": "invalid", "state": "invalid", "q": "x" * 500})
        assert is_dataclass(parsed)
        assert getattr(parsed, enum_field) is None
        assert parsed.search is None


def test_every_operations_list_uses_shared_pagination_and_preserves_query(admin_client):
    paths = (
        "/admin/leads?status=new&per_page=50",
        "/admin/appointments?status=pending&per_page=50",
        "/admin/data-requests?status=open&per_page=50",
        "/admin/catalog/scenario?status=draft&per_page=50",
        "/admin/cases?status=draft&per_page=50",
        "/admin/resources?status=draft&per_page=50",
        "/admin/announcements?status=draft&per_page=50",
        "/admin/media?status=ready&per_page=50",
        "/admin/ingestion?state=fetched&per_page=50",
    )
    for path in paths:
        response = admin_client.get(path)
        assert response.status_code == 200, path
        page = BeautifulSoup(response.data, "html.parser")
        pagination = page.select_one('[data-pagination="operations"]')
        assert pagination is not None, path
        assert pagination["data-per-page"] == "50"
        preserved = " ".join(link.get("href", "") for link in pagination.select("a"))
        expected_name = "state=" if "state=" in path else "status="
        assert expected_name in preserved, path


def test_every_operations_list_redirects_anonymous_and_is_private(admin_client):
    paths = (
        "/admin/leads", "/admin/appointments", "/admin/data-requests",
        "/admin/catalog/scenario", "/admin/cases", "/admin/resources",
        "/admin/announcements", "/admin/media", "/admin/ingestion",
    )
    anonymous = admin_client.application.test_client()
    for path in paths:
        assert anonymous.get(path).status_code == 302
        response = admin_client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"


def _insert_content(db, entry_type, suffix, updated_at):
    group_id = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES (?,?,?,?)",
        (entry_type, f"{entry_type}-{suffix}", updated_at, updated_at),
    ).lastrowid
    return db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,lock_version,created_at,updated_at) "
        "VALUES (?,?,1,?,?,?,?,?,'draft',1,?,?)",
        (
            group_id,
            entry_type,
            f"{entry_type}-{suffix}",
            f"title-{suffix}",
            "summary",
            f"seo-{suffix}",
            "description",
            updated_at,
            updated_at,
        ),
    ).lastrowid


def _insert_catalog_scenario_group(db, suffix):
    timestamp = "2026-08-01 10:00:00"
    scenario_id = db.execute(
        "INSERT INTO scenarios "
        "(code,category_code,public_name,minimum_business_value,minimum_process,"
        "minimum_data,minimum_systems,minimum_organization,minimum_delivery,"
        "integration_level,min_weeks,max_weeks,risk_codes_json,fallback_only,status,"
        "sort_order,created_at,updated_at) VALUES (?,?,?,1,1,1,1,1,1,'low',1,1,'[]',0,"
        "'published',0,?,?)",
        (f"matrix-{suffix}", "matrix", f"Matrix {suffix}", timestamp, timestamp),
    ).lastrowid
    group_id = db.execute(
        "INSERT INTO content_groups "
        "(entry_type,scenario_id,canonical_slug,created_at,updated_at) "
        "VALUES ('scenario',?,?,?,?)",
        (scenario_id, f"matrix-{suffix}", timestamp, timestamp),
    ).lastrowid
    return scenario_id, group_id


def _insert_catalog_revision(db, group_id, revision, title, updated_at):
    return db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,lock_version,created_at,updated_at) "
        "VALUES (?,'scenario',?,?,?,'summary','seo','description','draft',1,?,?)",
        (group_id, revision, f"matrix-revision-{group_id}", title, updated_at, updated_at),
    ).lastrowid


def _archive_catalog_revision(db, content_id, updated_at):
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,updated_at=? "
        "WHERE id=?",
        (updated_at, updated_at, content_id),
    )
    db.execute(
        "UPDATE content_items SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=?",
        (updated_at, updated_at, content_id),
    )


def test_draft_and_scheduled_content_filters_are_mutually_exclusive(
    admin_client, db
):
    db.execute("DROP TRIGGER validate_content_publication")
    ordinary_ids = {}
    scheduled_ids = {}
    for entry_type in ("case", "resource", "announcement"):
        ordinary_ids[entry_type] = _insert_content(
            db, entry_type, f"{entry_type}-ordinary", "2026-08-01 10:00:00"
        )
        scheduled_ids[entry_type] = _insert_content(
            db, entry_type, f"{entry_type}-scheduled", "2026-08-02 10:00:00"
        )
        db.execute(
            "UPDATE content_items SET publish_at='2026-09-01 10:00:00' WHERE id=?",
            (scheduled_ids[entry_type],),
        )
    db.commit()

    cases_draft = case_repository.admin_cases(
        PageRequest(1, 20), case_repository.CaseFilters(status="draft")
    )
    cases_scheduled = case_repository.admin_cases(
        PageRequest(1, 20), case_repository.CaseFilters(status="scheduled")
    )
    assert [item.id for item in cases_draft.items] == [ordinary_ids["case"]]
    assert [item.id for item in cases_scheduled.items] == [scheduled_ids["case"]]
    assert [item.status for item in cases_draft.items] == ["draft"]
    assert [item.status for item in cases_scheduled.items] == ["scheduled"]

    for entry_type in ("resource", "announcement"):
        draft = resource_repository.admin_entries(
            entry_type,
            PageRequest(1, 20),
            resource_repository.AdminEntryFilters(status="draft"),
        )
        scheduled = resource_repository.admin_entries(
            entry_type,
            PageRequest(1, 20),
            resource_repository.AdminEntryFilters(status="scheduled"),
        )
        assert [item.id for item in draft.items] == [ordinary_ids[entry_type]]
        assert [item.id for item in scheduled.items] == [scheduled_ids[entry_type]]
        assert [item.status for item in draft.items] == ["draft"]
        assert [item.status for item in scheduled.items] == ["scheduled"]

    scheduled_paths = (
        "/admin/cases?status=scheduled&q=case-scheduled",
        "/admin/resources?status=scheduled&q=resource-scheduled",
        "/admin/announcements?status=scheduled&q=announcement-scheduled",
    )
    for path in scheduled_paths:
        response = admin_client.get(path)
        assert response.status_code == 200
        page = BeautifulSoup(response.data, "html.parser")
        table_rows = page.select("table tbody tr")
        assert len(table_rows) == 1
        assert table_rows[0].select("td")[3].get_text(strip=True) == "scheduled"


def test_privacy_lead_selector_is_empty_until_bounded_escaped_search(
    admin_client, db
):
    timestamp = "2026-08-01 10:00:00"
    inserted_ids = []
    for index in range(25):
        inserted_ids.append(
            db.execute(
                "INSERT INTO leads "
                "(company_name,contact_name,status,created_at,updated_at) "
                "VALUES (?,?, 'new',?,?)",
                (f"choice%{index:02d}", f"choice-contact-{index:02d}", timestamp, timestamp),
            ).lastrowid
        )
    old_id = db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,status,created_at,updated_at) "
        "VALUES ('legacy%target','legacy-contact','new','2020-01-01 10:00:00',"
        "'2020-01-01 10:00:00')"
    ).lastrowid
    decoy_id = db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,status,created_at,updated_at) "
        "VALUES ('legacyXtarget','decoy-contact','new',?,?)",
        (timestamp, timestamp),
    ).lastrowid
    hidden_id = db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,status,anonymized_at,created_at,updated_at) "
        "VALUES ('legacy%hidden','hidden-contact','new',?,?,?)",
        (timestamp, timestamp, timestamp),
    ).lastrowid
    db.commit()

    empty = BeautifulSoup(
        admin_client.get("/admin/data-requests").data, "html.parser"
    )
    empty_options = empty.select('form select[name="lead_id"] option[value]')
    assert empty_options == []
    assert all(f'option value="{lead_id}"' not in str(empty) for lead_id in inserted_ids)

    literal = BeautifulSoup(
        admin_client.get("/admin/data-requests?lead_q=legacy%25").data,
        "html.parser",
    )
    literal_values = {
        int(option["value"])
        for option in literal.select('form select[name="lead_id"] option[value]')
    }
    assert literal_values == {old_id}
    assert decoy_id not in literal_values
    assert hidden_id not in literal_values
    assert literal.select_one('input[name="lead_q"]')["value"] == "legacy%"

    bounded = BeautifulSoup(
        admin_client.get("/admin/data-requests?lead_q=choice%25").data,
        "html.parser",
    )
    bounded_options = bounded.select('form select[name="lead_id"] option[value]')
    assert len(bounded_options) == 20


def test_catalog_archived_filter_requires_and_projects_latest_archived_revision(db):
    db.execute("DROP TRIGGER validate_content_publication")
    _insert_catalog_scenario_group(db, "empty")
    older_core_id, older_group_id = _insert_catalog_scenario_group(db, "older")
    newer_core_id, newer_group_id = _insert_catalog_scenario_group(db, "newer")

    older = _insert_catalog_revision(
        db, older_group_id, 1, "older archive", "2026-08-01 10:00:00"
    )
    _archive_catalog_revision(db, older, "2026-08-01 10:00:00")
    first_newer = _insert_catalog_revision(
        db, newer_group_id, 1, "superseded archive", "2026-08-02 10:00:00"
    )
    _archive_catalog_revision(db, first_newer, "2026-08-02 10:00:00")
    latest_newer = _insert_catalog_revision(
        db, newer_group_id, 2, "literal% latest archive", "2026-08-03 10:00:00"
    )
    _archive_catalog_revision(db, latest_newer, "2026-08-03 10:00:00")
    db.commit()

    archived = catalog_content_repository.list_catalog(
        db,
        "scenario",
        PageRequest(1, 20),
        catalog_content_repository.AdminCatalogFilters(status="archived"),
    )
    escaped_search = catalog_content_repository.list_catalog(
        db,
        "scenario",
        PageRequest(1, 20),
        catalog_content_repository.AdminCatalogFilters(search="literal%"),
    )

    assert archived.total == 2
    assert [item.core_id for item in archived.items] == [newer_core_id, older_core_id]
    assert archived.items[0].title == "literal% latest archive"
    assert archived.items[0].status == "archived"
    assert [item.core_id for item in escaped_search.items] == [newer_core_id]


def _insert_matrix_rows(db, queue):
    markers = [f"matrix%{index:03d}" for index in range(21)] + ["matrixXdecoy"]
    timestamp = "2026-08-01 10:00:00"
    if queue in {"leads", "appointments", "privacy"}:
        for index, marker in enumerate(markers):
            lead_id = db.execute(
                "INSERT INTO leads "
                "(company_name,contact_name,status,created_at,updated_at) "
                "VALUES (?,?,'new',?,?)",
                (marker, marker, timestamp, timestamp),
            ).lastrowid
            if queue == "appointments":
                assessment_id = db.execute(
                    "INSERT INTO assessments (lead_id,company_name) VALUES (?,?)",
                    (lead_id, marker),
                ).lastrowid
                db.execute(
                    "INSERT INTO appointments "
                    "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        assessment_id,
                        lead_id,
                        f"matrix-{index}",
                        "2026-09-01",
                        "morning",
                        marker,
                    ),
                )
            elif queue == "privacy":
                db.execute(
                    "INSERT INTO data_subject_requests "
                    "(lead_id,identity_hash,request_type,status,channel,requested_at) "
                    "VALUES (?,?,'access','received','email',?)",
                    (lead_id, f"{index + 1:064x}", timestamp),
                )
    elif queue == "catalog":
        for marker in markers:
            _, group_id = _insert_catalog_scenario_group(db, marker)
            _insert_catalog_revision(db, group_id, 1, marker, timestamp)
    elif queue in {"cases", "resources", "announcements"}:
        entry_type = {
            "cases": "case",
            "resources": "resource",
            "announcements": "announcement",
        }[queue]
        for marker in markers:
            _insert_content(db, entry_type, marker, timestamp)
    elif queue == "media":
        for index, marker in enumerate(markers):
            db.execute(
                "INSERT INTO media_assets "
                "(storage_name,display_name,detected_mime,byte_size,sha256,status,"
                "created_at,updated_at) VALUES (?,?, 'application/pdf',1,?,'pending',?,?)",
                (f"matrix-{index}.pdf", marker, f"{index + 1:064x}", timestamp, timestamp),
            )
    elif queue == "ingestion":
        for index, marker in enumerate(markers):
            db.execute(
                "INSERT INTO ingestion_candidates "
                "(source_code,source_name,canonical_url,content_sha256,title,licensed_summary,"
                "state,lock_version,created_at,updated_at) "
                "VALUES ('source',?, ?, ?,?,'summary','fetched',1,?,?)",
                (
                    marker,
                    f"https://example.invalid/matrix/{index}",
                    f"{index + 1:064x}",
                    marker,
                    timestamp,
                    timestamp,
                ),
            )
    db.commit()


def _traced_matrix_query(db, monkeypatch, queue, request):
    database_path = db.execute("PRAGMA database_list").fetchone()["file"]
    statements = []
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.set_trace_callback(statements.append)

    if queue == "leads":
        monkeypatch.setattr(lead_repository, "get_db", lambda: connection)
        page = lead_repository.query_leads(
            lead_repository.LeadFilters(search="matrix%"), request
        )
    elif queue == "appointments":
        monkeypatch.setattr(appointment_repository, "get_db", lambda: connection)
        page = appointment_repository.query_appointments(
            appointment_repository.AppointmentFilters(search="matrix%"), request
        )
    elif queue == "privacy":
        monkeypatch.setattr(lead_repository, "get_db", lambda: connection)
        page = lead_repository.query_data_subject_requests(
            lead_repository.DataRequestFilters(search="matrix%"), request
        )
    elif queue == "catalog":
        page = catalog_content_repository.list_catalog(
            connection,
            "scenario",
            request,
            catalog_content_repository.AdminCatalogFilters(search="matrix%"),
        )
        connection.close()
    elif queue == "cases":
        monkeypatch.setattr(case_repository.models, "get_db", lambda: connection)
        page = case_repository.admin_cases(
            request, case_repository.CaseFilters(search="matrix%")
        )
    elif queue in {"resources", "announcements"}:
        monkeypatch.setattr(resource_repository.models, "get_db", lambda: connection)
        page = resource_repository.admin_entries(
            "resource" if queue == "resources" else "announcement",
            request,
            resource_repository.AdminEntryFilters(search="matrix%"),
        )
    elif queue == "media":
        monkeypatch.setattr(media_service.models, "get_db", lambda: connection)
        page = media_service.query_media_assets(
            media_service.MediaFilters(search="matrix%"), request
        )
    else:
        monkeypatch.setattr(ingestion_repository, "get_db", lambda: connection)
        page = ingestion_repository.query_ingestion_candidates(
            ingestion_repository.IngestionFilters(search="matrix%"), request
        )

    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    return page, selects


@pytest.mark.parametrize(
    "queue",
    (
        "leads",
        "appointments",
        "privacy",
        "catalog",
        "cases",
        "resources",
        "announcements",
        "media",
        "ingestion",
    ),
)
def test_every_repository_uses_real_page_sizes_overflow_and_two_bounded_reads(
    db, monkeypatch, queue
):
    _insert_matrix_rows(db, queue)

    overflow, overflow_selects = _traced_matrix_query(
        db, monkeypatch, queue, PageRequest(999, 20)
    )
    fifty, fifty_selects = _traced_matrix_query(
        db, monkeypatch, queue, PageRequest(1, 50)
    )

    assert overflow.total == 21
    assert overflow.page == 2
    assert overflow.per_page == 20
    assert len(overflow.items) == 1
    assert fifty.total == 21
    assert fifty.page == 1
    assert fifty.per_page == 50
    assert len(fifty.items) == 21
    for statements in (overflow_selects, fifty_selects):
        assert len(statements) == 2, (queue, statements)
        assert "COUNT(*)" in statements[0].upper()
        assert "LIMIT" in statements[1].upper()


def test_invalid_write_enum_remains_bad_request(admin_client):
    response = admin_client.post(
        "/admin/appointments",
        data={
            "csrf_token": "test-csrf-token",
            "action": "transition",
            "appointment_id": "1",
            "new_status": "not-a-status",
        },
    )

    assert response.status_code == 400


def test_content_media_and_ingestion_queues_freeze_exact_orders(db):
    case_old = _insert_content(db, "case", "old", "2026-08-01 10:00:00")
    case_new = _insert_content(db, "case", "new", "2026-08-02 10:00:00")
    resource_later = _insert_content(db, "resource", "later", "2026-08-03 10:00:00")
    resource_earlier = _insert_content(db, "resource", "earlier", "2026-08-04 10:00:00")
    # This test isolates queue ordering; publication completeness remains covered by
    # the publishing migration/service responsibility tests.
    db.execute("DROP TRIGGER validate_content_publication")
    db.execute(
        "UPDATE content_items SET publish_at='2026-09-02 10:00:00' WHERE id=?",
        (resource_later,),
    )
    db.execute(
        "UPDATE content_items SET publish_at='2026-09-01 10:00:00' WHERE id=?",
        (resource_earlier,),
    )
    for index, updated in ((1, "2026-08-01 10:00:00"), (2, "2026-08-02 10:00:00")):
        db.execute(
            "INSERT INTO media_assets "
            "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'pending',?,?)",
            (f"media-{index}.pdf", f"media-{index}.pdf", "application/pdf", 1, f"{index:064x}", updated, updated),
        )
        db.execute(
            "INSERT INTO ingestion_candidates "
            "(source_code,source_name,canonical_url,content_sha256,title,licensed_summary,"
            "state,lock_version,created_at,updated_at) "
            "VALUES ('source','Source',?,?,?,?,'fetched',1,?,?)",
            (f"https://example.invalid/{index}", f"{index + 10:064x}", f"candidate-{index}", "summary", updated, updated),
        )
    db.commit()

    cases = case_repository.admin_cases(
        PageRequest(1, 20), case_repository.CaseFilters()
    )
    resources = resource_repository.admin_entries(
        "resource",
        PageRequest(1, 20),
        resource_repository.AdminEntryFilters(status="scheduled"),
    )
    media = media_service.query_media_assets(
        media_service.MediaFilters(status="pending"), PageRequest(1, 20)
    )
    ingestion = ingestion_repository.query_ingestion_candidates(
        ingestion_repository.IngestionFilters(state="fetched"), PageRequest(1, 20)
    )

    assert [item.id for item in cases.items] == [case_new, case_old]
    assert [item.id for item in resources.items] == [resource_earlier, resource_later]
    assert [item.id for item in media.items] == [2, 1]
    assert [item["title"] for item in ingestion.items] == ["candidate-2", "candidate-1"]


def test_repository_pages_issue_one_count_and_one_bounded_list_query(
    db, monkeypatch
):
    for index in range(3):
        _insert_lead(db, index)
    db.commit()
    database_path = db.execute("PRAGMA database_list").fetchone()["file"]
    statements = []
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.set_trace_callback(statements.append)
    monkeypatch.setattr(lead_repository, "get_db", lambda: connection)

    page = lead_repository.query_leads(
        lead_repository.LeadFilters(status="new"), PageRequest(1, 20)
    )

    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert page.total == 3
    assert len(selects) == 2
    assert "COUNT(*)" in selects[0]
    assert "LIMIT 20 OFFSET 0" in selects[1]


def test_unsupported_page_size_falls_back_to_twenty_for_every_list(admin_client):
    paths = (
        "/admin/leads", "/admin/appointments", "/admin/data-requests",
        "/admin/catalog/scenario", "/admin/cases", "/admin/resources",
        "/admin/announcements", "/admin/media", "/admin/ingestion",
    )
    for path in paths:
        separator = "&" if "?" in path else "?"
        response = admin_client.get(path + separator + "per_page=10000&page=invalid")
        assert response.status_code == 200
        page = BeautifulSoup(response.data, "html.parser")
        assert page.select_one('[data-pagination="operations"]')["data-per-page"] == "20"


def test_every_operations_list_exposes_its_exact_get_filters(admin_client):
    expectations = (
        ("/admin/leads?queue=followup&q=needle", "queue", "followup"),
        ("/admin/appointments?status=pending&q=needle", "status", "pending"),
        ("/admin/data-requests?status=open&request_type=access&q=needle", "request_type", "access"),
        ("/admin/catalog/scenario?status=draft&q=needle", "status", "draft"),
        ("/admin/cases?status=draft&q=needle", "status", "draft"),
        ("/admin/resources?status=draft&q=needle", "status", "draft"),
        ("/admin/announcements?status=draft&q=needle", "status", "draft"),
        ("/admin/media?status=pending&q=needle", "status", "pending"),
        ("/admin/ingestion?state=fetched&q=needle", "state", "fetched"),
    )
    for path, field, expected in expectations:
        response = admin_client.get(path)
        assert response.status_code == 200, path
        page = BeautifulSoup(response.data, "html.parser")
        form = page.select_one('form[data-operations-filters="true"]')
        assert form is not None, path
        selected = form.select_one(f'[name="{field}"]')
        assert selected is not None, path
        if selected.name == "select":
            assert selected.select_one("option:checked")["value"] == expected
        else:
            assert selected["value"] == expected
        assert form.select_one('input[name="q"]')["value"] == "needle"
